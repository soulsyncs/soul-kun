# lib/capabilities/multimodal/coordinator.py
"""
Phase M1: マルチモーダル処理コーディネーター

このモジュールは、マルチモーダル入力処理を統括し、
脳（SoulkunBrain）との連携を担当します。

設計書: docs/20_next_generation_capabilities.md セクション5.8

役割:
1. 添付ファイルの種類を判定
2. 適切なプロセッサーを選択・実行
3. 処理結果を脳が理解できる形式に変換
4. エラーハンドリングとフォールバック

使用例:
    coordinator = MultimodalCoordinator(pool, org_id)

    # 単一ファイル処理
    result = await coordinator.process_attachment(
        file_data=image_bytes,
        filename="receipt.jpg",
        room_id="123",
        user_id="456",
        instruction="この領収書を読み取って",
    )

    # 複数ファイル処理
    results = await coordinator.process_attachments(
        attachments=[
            {"data": file1, "filename": "doc1.pdf"},
            {"data": file2, "filename": "image.png"},
        ],
        room_id="123",
        user_id="456",
    )

    # 脳用コンテキスト生成
    enriched_message = coordinator.create_enriched_message(
        original_text="これ確認して",
        processed_results=results,
    )

Author: Claude Opus 4.5
Created: 2026-01-27
"""

import asyncio
import logging
import mimetypes
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse

from .constants import (
    InputType,
    ProcessingStatus,
    SUPPORTED_IMAGE_FORMATS,
    SUPPORTED_PDF_FORMATS,
    SUPPORTED_URL_PROTOCOLS,
    SUPPORTED_AUDIO_FORMATS,
    MAX_IMAGE_SIZE_BYTES,
    MAX_PDF_SIZE_BYTES,
    MAX_URL_CONTENT_SIZE_BYTES,
    MAX_AUDIO_SIZE_BYTES,
    MAX_AUDIO_DURATION_SECONDS,
    MAX_AUDIO_DURATION_MINUTES,
    FEATURE_FLAG_NAME,
    FEATURE_FLAG_IMAGE,
    FEATURE_FLAG_PDF,
    FEATURE_FLAG_URL,
)

from .exceptions import (
    MultimodalBaseException,
    ValidationError,
    UnsupportedFormatError,
    FileTooLargeError,
)

from .models import (
    MultimodalInput,
    MultimodalOutput,
    ProcessingMetadata,
    ExtractedEntity,
)

from .image_processor import ImageProcessor
from .pdf_processor import PDFProcessor
from .url_processor import URLProcessor

logger = logging.getLogger(__name__)


# =============================================================================
# 列挙型
# =============================================================================


class AttachmentType(Enum):
    """添付ファイルタイプ"""
    IMAGE = "image"
    PDF = "pdf"
    URL = "url"
    AUDIO = "audio"      # Phase M2で実装予定
    VIDEO = "video"      # Phase M3で実装予定
    DOCUMENT = "document"  # Word/PPT等、将来対応
    SPREADSHEET = "spreadsheet"  # Excel/CSV、将来対応
    UNKNOWN = "unknown"


# =============================================================================
# データクラス
# =============================================================================


@dataclass
class AttachmentInfo:
    """
    添付ファイル情報

    ChatWorkから受信した添付ファイルの基本情報を保持。
    """
    # ファイル情報
    file_id: Optional[str] = None  # ChatWorkファイルID
    filename: str = ""
    file_size_bytes: int = 0
    mime_type: Optional[str] = None

    # 判定結果
    attachment_type: AttachmentType = AttachmentType.UNKNOWN
    input_type: Optional[InputType] = None

    # データ（オプション、すでにダウンロード済みの場合）
    data: Optional[bytes] = None

    # URL（URLタイプの場合）
    url: Optional[str] = None

    def __post_init__(self):
        """初期化後処理"""
        if not self.mime_type and self.filename:
            self.mime_type, _ = mimetypes.guess_type(self.filename)


@dataclass
class ProcessedAttachment:
    """
    処理済み添付ファイル

    プロセッサーによる処理結果を保持。
    """
    # 元情報
    attachment_info: AttachmentInfo

    # 処理結果
    success: bool = False
    output: Optional[MultimodalOutput] = None

    # エラー情報
    error_message: Optional[str] = None
    error_code: Optional[str] = None

    # メタデータ
    processing_time_ms: int = 0

    def to_context_text(self) -> str:
        """
        脳のコンテキスト用テキストに変換

        Returns:
            脳が理解できる形式のテキスト
        """
        if not self.success or not self.output:
            return f"[{self.attachment_info.filename}の処理に失敗: {self.error_message}]"

        parts = []

        # ファイル名とタイプ
        type_label = {
            AttachmentType.IMAGE: "画像",
            AttachmentType.PDF: "PDF",
            AttachmentType.URL: "Webページ",
            AttachmentType.AUDIO: "音声",
            AttachmentType.VIDEO: "動画",
        }.get(self.attachment_info.attachment_type, "ファイル")

        parts.append(f"【{type_label}: {self.attachment_info.filename}】")

        # サマリー
        if self.output.summary:
            parts.append(f"概要: {self.output.summary}")

        # 抽出テキスト
        if self.output.extracted_text:
            text = self.output.extracted_text
            if len(text) > 500:
                text = text[:500] + "...(以下省略)"
            parts.append(f"抽出内容:\n{text}")

        # エンティティ
        if self.output.entities:
            entity_texts = []
            for entity in self.output.entities[:10]:  # 最大10件
                entity_texts.append(f"  - {entity.entity_type}: {entity.value}")
            if entity_texts:
                parts.append("検出された情報:\n" + "\n".join(entity_texts))

        return "\n".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "filename": self.attachment_info.filename,
            "type": self.attachment_info.attachment_type.value,
            "success": self.success,
            "summary": self.output.summary if self.output else None,
            "extracted_text": self.output.extracted_text if self.output else None,
            "entities": [e.to_dict() for e in (self.output.entities or [])] if self.output else [],
            "error": self.error_message,
            "processing_time_ms": self.processing_time_ms,
        }


@dataclass
class EnrichedMessage:
    """
    エンリッチされたメッセージ

    元のテキストメッセージに、マルチモーダル処理結果を統合したもの。
    脳（SoulkunBrain）に渡す。
    """
    # 元のメッセージ
    original_text: str

    # 処理済み添付ファイル
    processed_attachments: List[ProcessedAttachment] = field(default_factory=list)

    # 統合されたコンテキストテキスト
    context_text: str = ""

    # 抽出されたエンティティ（全添付ファイルから統合）
    all_entities: List[ExtractedEntity] = field(default_factory=list)

    # メタデータ
    has_multimodal_content: bool = False
    total_processing_time_ms: int = 0
    successful_count: int = 0
    failed_count: int = 0

    def __post_init__(self):
        """初期化後処理"""
        self._update_stats()

    def _update_stats(self):
        """統計情報を更新"""
        self.has_multimodal_content = len(self.processed_attachments) > 0
        self.successful_count = sum(1 for p in self.processed_attachments if p.success)
        self.failed_count = sum(1 for p in self.processed_attachments if not p.success)
        self.total_processing_time_ms = sum(p.processing_time_ms for p in self.processed_attachments)

    def get_full_context(self) -> str:
        """
        脳に渡すフルコンテキストを生成

        Returns:
            元のメッセージ + 添付ファイルの処理結果を統合したテキスト
        """
        parts = []

        # 元のメッセージ
        if self.original_text:
            parts.append(self.original_text)

        # 添付ファイルの処理結果
        if self.processed_attachments:
            parts.append("\n--- 添付ファイル情報 ---")
            for processed in self.processed_attachments:
                parts.append(processed.to_context_text())

        return "\n\n".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "original_text": self.original_text,
            "attachments": [p.to_dict() for p in self.processed_attachments],
            "has_multimodal_content": self.has_multimodal_content,
            "successful_count": self.successful_count,
            "failed_count": self.failed_count,
            "total_processing_time_ms": self.total_processing_time_ms,
        }


# =============================================================================
# MultimodalCoordinator クラス
# =============================================================================


class MultimodalCoordinator:
    """
    マルチモーダル処理コーディネーター

    添付ファイルの処理を統括し、脳との連携を担当する。

    責務:
    1. ファイルタイプの判定
    2. 適切なプロセッサーの選択
    3. 処理の実行（並列可）
    4. 結果の統合
    5. エラーハンドリング

    Attributes:
        pool: データベース接続プール
        org_id: 組織ID
        image_processor: 画像プロセッサー
        pdf_processor: PDFプロセッサー
        url_processor: URLプロセッサー
    """

    # ファイル拡張子→AttachmentTypeのマッピング
    EXTENSION_TYPE_MAP = {
        # 画像
        "jpg": AttachmentType.IMAGE,
        "jpeg": AttachmentType.IMAGE,
        "png": AttachmentType.IMAGE,
        "gif": AttachmentType.IMAGE,
        "webp": AttachmentType.IMAGE,
        "bmp": AttachmentType.IMAGE,
        "tiff": AttachmentType.IMAGE,
        "tif": AttachmentType.IMAGE,

        # PDF
        "pdf": AttachmentType.PDF,

        # 音声（Phase M2）
        "mp3": AttachmentType.AUDIO,
        "wav": AttachmentType.AUDIO,
        "m4a": AttachmentType.AUDIO,
        "webm": AttachmentType.AUDIO,
        "ogg": AttachmentType.AUDIO,

        # 動画（Phase M3）
        "mp4": AttachmentType.VIDEO,
        "mov": AttachmentType.VIDEO,
        "avi": AttachmentType.VIDEO,
        "mkv": AttachmentType.VIDEO,

        # ドキュメント（将来）
        "doc": AttachmentType.DOCUMENT,
        "docx": AttachmentType.DOCUMENT,
        "ppt": AttachmentType.DOCUMENT,
        "pptx": AttachmentType.DOCUMENT,

        # スプレッドシート（将来）
        "xls": AttachmentType.SPREADSHEET,
        "xlsx": AttachmentType.SPREADSHEET,
        "csv": AttachmentType.SPREADSHEET,
    }

    # MIMEタイプ→AttachmentTypeのマッピング
    MIME_TYPE_MAP = {
        "image/jpeg": AttachmentType.IMAGE,
        "image/png": AttachmentType.IMAGE,
        "image/gif": AttachmentType.IMAGE,
        "image/webp": AttachmentType.IMAGE,
        "image/bmp": AttachmentType.IMAGE,
        "application/pdf": AttachmentType.PDF,
        "audio/mpeg": AttachmentType.AUDIO,
        "audio/wav": AttachmentType.AUDIO,
        "audio/mp4": AttachmentType.AUDIO,
        "video/mp4": AttachmentType.VIDEO,
        "video/quicktime": AttachmentType.VIDEO,
    }

    def __init__(
        self,
        pool,
        org_id: str,
        feature_flags: Optional[Dict[str, bool]] = None,
    ):
        """
        Args:
            pool: データベース接続プール
            org_id: 組織ID
            feature_flags: Feature Flagの設定（オプション）
        """
        self.pool = pool
        self.org_id = org_id
        self.feature_flags = feature_flags or {}

        # プロセッサーの初期化
        self.image_processor = ImageProcessor(pool, org_id)
        self.pdf_processor = PDFProcessor(pool, org_id)
        self.url_processor = URLProcessor(pool, org_id)

        logger.info(f"MultimodalCoordinator initialized for org_id={org_id}")

    # =========================================================================
    # Feature Flag チェック
    # =========================================================================

    def _is_feature_enabled(self, feature_key: str) -> bool:
        """
        Feature Flagが有効かチェック

        Args:
            feature_key: フィーチャーキー

        Returns:
            有効ならTrue
        """
        # メインフラグが無効なら全て無効
        if not self.feature_flags.get(FEATURE_FLAG_NAME, True):
            return False

        # 個別フラグ
        return self.feature_flags.get(feature_key, True)

    # =========================================================================
    # ファイルタイプ判定
    # =========================================================================

    def detect_attachment_type(
        self,
        filename: Optional[str] = None,
        mime_type: Optional[str] = None,
        data: Optional[bytes] = None,
    ) -> AttachmentType:
        """
        添付ファイルのタイプを判定

        判定優先順位:
        1. MIMEタイプ（信頼性が高い）
        2. ファイル拡張子
        3. マジックバイト（バイナリヘッダー）

        Args:
            filename: ファイル名
            mime_type: MIMEタイプ
            data: ファイルデータ（オプション）

        Returns:
            判定されたAttachmentType
        """
        # MIMEタイプで判定
        if mime_type:
            mime_lower = mime_type.lower()
            if mime_lower in self.MIME_TYPE_MAP:
                return self.MIME_TYPE_MAP[mime_lower]

            # プレフィックスで判定
            if mime_lower.startswith("image/"):
                return AttachmentType.IMAGE
            elif mime_lower.startswith("audio/"):
                return AttachmentType.AUDIO
            elif mime_lower.startswith("video/"):
                return AttachmentType.VIDEO

        # ファイル拡張子で判定
        if filename:
            ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
            if ext in self.EXTENSION_TYPE_MAP:
                return self.EXTENSION_TYPE_MAP[ext]

        # マジックバイトで判定
        if data and len(data) >= 8:
            return self._detect_by_magic_bytes(data)

        return AttachmentType.UNKNOWN

    def _detect_by_magic_bytes(self, data: bytes) -> AttachmentType:
        """
        マジックバイトでファイルタイプを判定

        Args:
            data: ファイルデータ（先頭部分）

        Returns:
            判定されたAttachmentType
        """
        # PNG
        if data[:8] == b'\x89PNG\r\n\x1a\n':
            return AttachmentType.IMAGE

        # JPEG
        if data[:2] == b'\xff\xd8':
            return AttachmentType.IMAGE

        # GIF
        if data[:6] in (b'GIF87a', b'GIF89a'):
            return AttachmentType.IMAGE

        # WebP
        if data[:4] == b'RIFF' and len(data) >= 12 and data[8:12] == b'WEBP':
            return AttachmentType.IMAGE

        # PDF
        if data[:5] == b'%PDF-':
            return AttachmentType.PDF

        # MP3
        if data[:3] == b'ID3' or data[:2] == b'\xff\xfb':
            return AttachmentType.AUDIO

        # MP4/MOV
        if len(data) >= 12 and data[4:8] == b'ftyp':
            return AttachmentType.VIDEO

        return AttachmentType.UNKNOWN

    def detect_url_in_text(self, text: str) -> List[str]:
        """
        テキストからURLを検出

        Args:
            text: テキスト

        Returns:
            検出されたURLのリスト
        """
        # URLパターン
        url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
        urls = re.findall(url_pattern, text)

        # 有効なURLのみフィルタ
        valid_urls = []
        for url in urls:
            try:
                parsed = urlparse(url)
                if parsed.scheme in SUPPORTED_URL_PROTOCOLS and parsed.netloc:
                    valid_urls.append(url)
            except Exception:
                continue

        return valid_urls

    # =========================================================================
    # 単一ファイル処理
    # =========================================================================

    async def process_attachment(
        self,
        file_data: Optional[bytes] = None,
        filename: str = "",
        mime_type: Optional[str] = None,
        url: Optional[str] = None,
        room_id: str = "",
        user_id: str = "",
        instruction: Optional[str] = None,
    ) -> ProcessedAttachment:
        """
        単一の添付ファイルを処理

        Args:
            file_data: ファイルデータ
            filename: ファイル名
            mime_type: MIMEタイプ
            url: URL（URLタイプの場合）
            room_id: ChatWorkルームID
            user_id: ユーザーID
            instruction: 処理指示（オプション）

        Returns:
            処理結果
        """
        start_time = datetime.now()

        # 添付ファイル情報を構築
        attachment_info = AttachmentInfo(
            filename=filename,
            file_size_bytes=len(file_data) if file_data else 0,
            mime_type=mime_type,
            data=file_data,
            url=url,
        )

        # タイプ判定
        if url:
            attachment_info.attachment_type = AttachmentType.URL
            attachment_info.input_type = InputType.URL
        else:
            attachment_info.attachment_type = self.detect_attachment_type(
                filename=filename,
                mime_type=mime_type,
                data=file_data,
            )

            # InputTypeへのマッピング
            type_mapping = {
                AttachmentType.IMAGE: InputType.IMAGE,
                AttachmentType.PDF: InputType.PDF,
                AttachmentType.AUDIO: InputType.AUDIO,
                AttachmentType.VIDEO: InputType.VIDEO,
            }
            attachment_info.input_type = type_mapping.get(
                attachment_info.attachment_type
            )

        try:
            # 処理実行
            output = await self._process_by_type(
                attachment_info=attachment_info,
                room_id=room_id,
                user_id=user_id,
                instruction=instruction,
            )

            processing_time_ms = int((datetime.now() - start_time).total_seconds() * 1000)

            return ProcessedAttachment(
                attachment_info=attachment_info,
                success=output.success if output else False,
                output=output,
                error_message=output.error_message if output and not output.success else None,
                error_code=output.error_code if output and not output.success else None,
                processing_time_ms=processing_time_ms,
            )

        except MultimodalBaseException as e:
            processing_time_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            logger.warning(f"Multimodal processing failed: {e}")

            return ProcessedAttachment(
                attachment_info=attachment_info,
                success=False,
                error_message=str(e),
                error_code=e.error_code,
                processing_time_ms=processing_time_ms,
            )

        except Exception as e:
            processing_time_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            logger.error(f"Unexpected error in multimodal processing: {e}", exc_info=True)

            return ProcessedAttachment(
                attachment_info=attachment_info,
                success=False,
                error_message=f"処理中にエラーが発生しました: {str(e)}",
                error_code="UNEXPECTED_ERROR",
                processing_time_ms=processing_time_ms,
            )

    async def _process_by_type(
        self,
        attachment_info: AttachmentInfo,
        room_id: str,
        user_id: str,
        instruction: Optional[str] = None,
    ) -> Optional[MultimodalOutput]:
        """
        タイプに応じたプロセッサーで処理

        Args:
            attachment_info: 添付ファイル情報
            room_id: ChatWorkルームID
            user_id: ユーザーID
            instruction: 処理指示

        Returns:
            処理結果
        """
        att_type = attachment_info.attachment_type

        # 画像処理
        if att_type == AttachmentType.IMAGE:
            if not self._is_feature_enabled(FEATURE_FLAG_IMAGE):
                raise UnsupportedFormatError(
                    format_name="image",
                    supported_formats=[],
                )

            input_data = MultimodalInput(
                input_type=InputType.IMAGE,
                organization_id=self.org_id,
                image_data=attachment_info.data,
                instruction=instruction,
                room_id=room_id,
                user_id=user_id,
            )
            return await self.image_processor.process(input_data)  # type: ignore[no-any-return]

        # PDF処理
        elif att_type == AttachmentType.PDF:
            if not self._is_feature_enabled(FEATURE_FLAG_PDF):
                raise UnsupportedFormatError(
                    format_name="pdf",
                    supported_formats=[],
                )

            input_data = MultimodalInput(
                input_type=InputType.PDF,
                organization_id=self.org_id,
                pdf_data=attachment_info.data,
                instruction=instruction,
                room_id=room_id,
                user_id=user_id,
            )
            return await self.pdf_processor.process(input_data)  # type: ignore[no-any-return]

        # URL処理
        elif att_type == AttachmentType.URL:
            if not self._is_feature_enabled(FEATURE_FLAG_URL):
                raise UnsupportedFormatError(
                    format_name="url",
                    supported_formats=[],
                )

            input_data = MultimodalInput(
                input_type=InputType.URL,
                organization_id=self.org_id,
                url=attachment_info.url,
                instruction=instruction,
                room_id=room_id,
                user_id=user_id,
            )
            return await self.url_processor.process(input_data)  # type: ignore[no-any-return]

        # 音声（Phase M2で実装）
        elif att_type == AttachmentType.AUDIO:
            raise UnsupportedFormatError(
                format_name="audio",
                supported_formats=[],
            )

        # 動画（Phase M3で実装）
        elif att_type == AttachmentType.VIDEO:
            raise UnsupportedFormatError(
                format_name="video",
                supported_formats=[],
            )

        # 未対応フォーマット
        else:
            raise UnsupportedFormatError(
                format_name=att_type.value,
                supported_formats=[],
            )

    # =========================================================================
    # 複数ファイル処理
    # =========================================================================

    async def process_attachments(
        self,
        attachments: List[Dict[str, Any]],
        room_id: str = "",
        user_id: str = "",
        instruction: Optional[str] = None,
        parallel: bool = True,
    ) -> List[ProcessedAttachment]:
        """
        複数の添付ファイルを処理

        Args:
            attachments: 添付ファイルのリスト
                [{"data": bytes, "filename": str, "mime_type": str}, ...]
            room_id: ChatWorkルームID
            user_id: ユーザーID
            instruction: 処理指示（全ファイル共通）
            parallel: 並列処理を行うか（デフォルトTrue）

        Returns:
            処理結果のリスト
        """
        if not attachments:
            return []

        if parallel:
            # 並列処理
            tasks = [
                self.process_attachment(
                    file_data=att.get("data"),
                    filename=att.get("filename", ""),
                    mime_type=att.get("mime_type"),
                    url=att.get("url"),
                    room_id=room_id,
                    user_id=user_id,
                    instruction=instruction,
                )
                for att in attachments
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # 例外をProcessedAttachmentに変換
            processed_results: List[ProcessedAttachment] = []
            for i, result in enumerate(results):
                if isinstance(result, BaseException):
                    processed_results.append(ProcessedAttachment(
                        attachment_info=AttachmentInfo(
                            filename=attachments[i].get("filename", "unknown"),
                        ),
                        success=False,
                        error_message=str(result),
                        error_code="PROCESSING_ERROR",
                    ))
                else:
                    processed_results.append(result)

            return processed_results

        else:
            # 順次処理
            seq_results: List[ProcessedAttachment] = []
            for att in attachments:
                result = await self.process_attachment(
                    file_data=att.get("data"),
                    filename=att.get("filename", ""),
                    mime_type=att.get("mime_type"),
                    url=att.get("url"),
                    room_id=room_id,
                    user_id=user_id,
                    instruction=instruction,
                )
                seq_results.append(result)

            return seq_results

    # =========================================================================
    # テキスト内URL処理
    # =========================================================================

    async def process_urls_in_text(
        self,
        text: str,
        room_id: str = "",
        user_id: str = "",
        max_urls: int = 3,
    ) -> List[ProcessedAttachment]:
        """
        テキスト内のURLを検出・処理

        Args:
            text: テキスト
            room_id: ChatWorkルームID
            user_id: ユーザーID
            max_urls: 処理するURLの最大数

        Returns:
            処理結果のリスト
        """
        urls = self.detect_url_in_text(text)

        if not urls:
            return []

        # 最大数で制限
        urls = urls[:max_urls]

        # URLを添付ファイルとして処理
        attachments = [
            {"url": url, "filename": url}
            for url in urls
        ]

        return await self.process_attachments(
            attachments=attachments,
            room_id=room_id,
            user_id=user_id,
        )

    # =========================================================================
    # エンリッチドメッセージ生成
    # =========================================================================

    def create_enriched_message(
        self,
        original_text: str,
        processed_results: List[ProcessedAttachment],
    ) -> EnrichedMessage:
        """
        エンリッチドメッセージを生成

        元のメッセージとマルチモーダル処理結果を統合した、
        脳に渡すメッセージを作成する。

        Args:
            original_text: 元のテキストメッセージ
            processed_results: 処理済み添付ファイルのリスト

        Returns:
            エンリッチドメッセージ
        """
        # 全エンティティを収集
        all_entities = []
        for result in processed_results:
            if result.success and result.output and result.output.entities:
                all_entities.extend(result.output.entities)

        # コンテキストテキストを構築
        context_parts = []
        for result in processed_results:
            context_parts.append(result.to_context_text())

        return EnrichedMessage(
            original_text=original_text,
            processed_attachments=processed_results,
            context_text="\n\n".join(context_parts),
            all_entities=all_entities,
        )

    # =========================================================================
    # ユーティリティ
    # =========================================================================

    def get_supported_formats(self) -> Dict[str, List[str]]:
        """
        サポートしているフォーマット一覧を取得

        Returns:
            タイプごとのサポートフォーマット
        """
        return {
            "image": list(SUPPORTED_IMAGE_FORMATS),
            "pdf": list(SUPPORTED_PDF_FORMATS),
            "url": list(SUPPORTED_URL_PROTOCOLS),
            "audio": ["mp3", "wav", "m4a", "webm", "ogg"],  # Phase M2
            "video": ["mp4", "mov", "avi", "mkv"],  # Phase M3
        }

    def get_size_limits(self) -> Dict[str, int]:
        """
        サイズ制限を取得

        Returns:
            タイプごとのサイズ制限（バイト）
        """
        return {
            "image": MAX_IMAGE_SIZE_BYTES,
            "pdf": MAX_PDF_SIZE_BYTES,
            "url": MAX_URL_CONTENT_SIZE_BYTES,
            "audio": MAX_AUDIO_SIZE_BYTES,
        }

    def get_audio_limits(self) -> Dict[str, Any]:
        """
        音声制限情報を取得

        Returns:
            音声のサイズ・時間制限とサポートフォーマット
        """
        return {
            "max_size_bytes": MAX_AUDIO_SIZE_BYTES,
            "max_duration_minutes": MAX_AUDIO_DURATION_MINUTES,
            "max_duration_seconds": MAX_AUDIO_DURATION_SECONDS,
            "supported_formats": list(SUPPORTED_AUDIO_FORMATS),
        }


# =============================================================================
# ファクトリ関数
# =============================================================================


def create_multimodal_coordinator(
    pool,
    org_id: str,
    feature_flags: Optional[Dict[str, bool]] = None,
) -> MultimodalCoordinator:
    """
    MultimodalCoordinatorを作成するファクトリ関数

    Args:
        pool: データベース接続プール
        org_id: 組織ID
        feature_flags: Feature Flagの設定

    Returns:
        MultimodalCoordinator インスタンス
    """
    return MultimodalCoordinator(
        pool=pool,
        org_id=org_id,
        feature_flags=feature_flags,
    )
