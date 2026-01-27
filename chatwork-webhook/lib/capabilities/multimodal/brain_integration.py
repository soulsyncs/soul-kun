# lib/capabilities/multimodal/brain_integration.py
"""
Phase M1: 脳との統合モジュール

このモジュールは、マルチモーダル処理と脳（SoulkunBrain）の
連携を担当する関数・クラスを提供します。

設計書: docs/20_next_generation_capabilities.md セクション3.2

【脳の7つの鉄則との整合性】
1. 全ての入力は脳を通る → このモジュールは脳に渡す前の前処理を担当
2. 脳は全ての記憶にアクセスできる → 処理結果はコンテキストとして脳に渡る
3. 脳が判断、機能は実行のみ → このモジュールは実行のみ、判断は脳が行う
4. 機能拡張しても脳の構造は変わらない → 脳のコードは変更せず、コンテキスト拡張のみ
5. 確認は脳の責務 → 確認が必要かどうかは脳が判断
6. 状態管理は脳が統一管理 → このモジュールは状態を持たない
7. 速度より正確性を優先 → 正確なテキスト変換を優先

使用例:
    from lib.capabilities.multimodal.brain_integration import (
        process_message_with_multimodal,
        create_multimodal_context,
        MultimodalBrainContext,
    )

    # ChatWorkからのメッセージを処理
    enriched_message, multimodal_context = await process_message_with_multimodal(
        message_text="この画像を確認して",
        attachments=[{"data": image_bytes, "filename": "image.png"}],
        pool=db_pool,
        org_id="org_soulsyncs",
        room_id="123",
        user_id="456",
    )

    # 脳に渡す
    brain_response = await brain.process_message(
        message=enriched_message.get_full_context(),
        room_id=room_id,
        account_id=user_id,
        sender_name=sender_name,
        # multimodal_context=multimodal_context,  # オプション
    )

Author: Claude Opus 4.5
Created: 2026-01-27
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .constants import InputType, ProcessingStatus
from .models import ExtractedEntity, MultimodalOutput
from .coordinator import (
    MultimodalCoordinator,
    EnrichedMessage,
    ProcessedAttachment,
    AttachmentType,
)

logger = logging.getLogger(__name__)


# =============================================================================
# マルチモーダルコンテキスト
# =============================================================================


@dataclass
class MultimodalBrainContext:
    """
    脳に渡すマルチモーダルコンテキスト

    BrainContextに追加する情報を保持。
    脳はこの情報を参照して、より適切な判断を行う。

    Attributes:
        has_image: 画像が含まれるか
        has_pdf: PDFが含まれるか
        has_url: URLが含まれるか
        has_audio: 音声が含まれるか（Phase M2）
        has_video: 動画が含まれるか（Phase M3）
        attachment_count: 添付ファイル数
        successful_count: 処理成功数
        failed_count: 処理失敗数
        extracted_entities: 抽出されたエンティティ
        summaries: 各添付ファイルの要約
        processing_details: 処理詳細情報
    """

    # フラグ
    has_image: bool = False
    has_pdf: bool = False
    has_url: bool = False
    has_audio: bool = False
    has_video: bool = False

    # 統計
    attachment_count: int = 0
    successful_count: int = 0
    failed_count: int = 0
    total_processing_time_ms: int = 0

    # 抽出データ
    extracted_entities: List[ExtractedEntity] = field(default_factory=list)
    summaries: List[str] = field(default_factory=list)

    # 詳細情報
    processing_details: List[Dict[str, Any]] = field(default_factory=list)

    # タイムスタンプ
    processed_at: datetime = field(default_factory=datetime.now)

    @property
    def has_multimodal_content(self) -> bool:
        """マルチモーダルコンテンツがあるか"""
        return self.attachment_count > 0

    @property
    def all_successful(self) -> bool:
        """全ての処理が成功したか"""
        return self.failed_count == 0 and self.successful_count > 0

    @property
    def primary_type(self) -> Optional[str]:
        """主要なコンテンツタイプを返す"""
        if self.has_image:
            return "image"
        elif self.has_pdf:
            return "pdf"
        elif self.has_url:
            return "url"
        elif self.has_audio:
            return "audio"
        elif self.has_video:
            return "video"
        return None

    def get_entities_by_type(self, entity_type: str) -> List[ExtractedEntity]:
        """
        特定タイプのエンティティを取得

        Args:
            entity_type: エンティティタイプ（amount, date, email等）

        Returns:
            該当するエンティティのリスト
        """
        return [e for e in self.extracted_entities if e.entity_type == entity_type]

    def to_prompt_context(self) -> str:
        """
        LLMプロンプト用のコンテキスト文字列を生成

        Returns:
            プロンプトに追加するコンテキスト文字列
        """
        if not self.has_multimodal_content:
            return ""

        parts = ["【添付ファイル分析結果】"]

        # 処理状況
        parts.append(f"処理: {self.successful_count}件成功 / {self.attachment_count}件")

        # タイプ
        types = []
        if self.has_image:
            types.append("画像")
        if self.has_pdf:
            types.append("PDF")
        if self.has_url:
            types.append("URL")
        if types:
            parts.append(f"タイプ: {', '.join(types)}")

        # 要約
        if self.summaries:
            parts.append("要約:")
            for i, summary in enumerate(self.summaries[:3], 1):
                parts.append(f"  {i}. {summary[:200]}")

        # 主要エンティティ
        if self.extracted_entities:
            parts.append("検出された情報:")
            for entity in self.extracted_entities[:10]:
                parts.append(f"  - {entity.entity_type}: {entity.value}")

        return "\n".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "has_image": self.has_image,
            "has_pdf": self.has_pdf,
            "has_url": self.has_url,
            "has_audio": self.has_audio,
            "has_video": self.has_video,
            "attachment_count": self.attachment_count,
            "successful_count": self.successful_count,
            "failed_count": self.failed_count,
            "total_processing_time_ms": self.total_processing_time_ms,
            "entities": [e.to_dict() for e in self.extracted_entities],
            "summaries": self.summaries,
            "processed_at": self.processed_at.isoformat(),
        }


# =============================================================================
# メイン処理関数
# =============================================================================


async def process_message_with_multimodal(
    message_text: str,
    attachments: List[Dict[str, Any]],
    pool,
    org_id: str,
    room_id: str = "",
    user_id: str = "",
    feature_flags: Optional[Dict[str, bool]] = None,
    process_urls_in_text: bool = True,
    max_urls: int = 3,
) -> Tuple[EnrichedMessage, MultimodalBrainContext]:
    """
    メッセージをマルチモーダル処理してエンリッチする

    ChatWorkからのメッセージ（テキスト + 添付ファイル）を処理し、
    脳に渡すためのエンリッチドメッセージとコンテキストを生成する。

    Args:
        message_text: 元のテキストメッセージ
        attachments: 添付ファイルのリスト
            [{"data": bytes, "filename": str, "mime_type": str}, ...]
        pool: データベース接続プール
        org_id: 組織ID
        room_id: ChatWorkルームID
        user_id: ユーザーID
        feature_flags: Feature Flagの設定
        process_urls_in_text: テキスト内のURLも処理するか
        max_urls: 処理するURLの最大数

    Returns:
        (EnrichedMessage, MultimodalBrainContext) のタプル

    使用例:
        enriched, context = await process_message_with_multimodal(
            message_text="この画像を確認して",
            attachments=[{"data": image_bytes, "filename": "receipt.jpg"}],
            pool=db_pool,
            org_id="org_soulsyncs",
            room_id="123",
            user_id="456",
        )

        # 脳に渡すテキストを取得
        full_text = enriched.get_full_context()

        # マルチモーダルコンテキストを確認
        if context.has_image:
            print("画像が含まれています")
    """
    # コーディネーター作成
    coordinator = MultimodalCoordinator(
        pool=pool,
        org_id=org_id,
        feature_flags=feature_flags,
    )

    # 処理結果リスト
    all_results: List[ProcessedAttachment] = []

    # 添付ファイルを処理
    if attachments:
        attachment_results = await coordinator.process_attachments(
            attachments=attachments,
            room_id=room_id,
            user_id=user_id,
        )
        all_results.extend(attachment_results)

    # テキスト内のURLを処理
    if process_urls_in_text and message_text:
        url_results = await coordinator.process_urls_in_text(
            text=message_text,
            room_id=room_id,
            user_id=user_id,
            max_urls=max_urls,
        )
        all_results.extend(url_results)

    # エンリッチドメッセージを作成
    enriched_message = coordinator.create_enriched_message(
        original_text=message_text,
        processed_results=all_results,
    )

    # マルチモーダルコンテキストを作成
    multimodal_context = create_multimodal_context(all_results)

    logger.info(
        f"Multimodal processing complete: "
        f"{multimodal_context.successful_count}/{multimodal_context.attachment_count} successful, "
        f"types={multimodal_context.primary_type}, "
        f"entities={len(multimodal_context.extracted_entities)}"
    )

    return enriched_message, multimodal_context


def create_multimodal_context(
    processed_results: List[ProcessedAttachment],
) -> MultimodalBrainContext:
    """
    処理結果からマルチモーダルコンテキストを作成

    Args:
        processed_results: 処理済み添付ファイルのリスト

    Returns:
        MultimodalBrainContext
    """
    context = MultimodalBrainContext()

    if not processed_results:
        return context

    context.attachment_count = len(processed_results)

    for result in processed_results:
        # 成功/失敗カウント
        if result.success:
            context.successful_count += 1
        else:
            context.failed_count += 1

        # 処理時間
        context.total_processing_time_ms += result.processing_time_ms

        # タイプフラグ
        att_type = result.attachment_info.attachment_type
        if att_type == AttachmentType.IMAGE:
            context.has_image = True
        elif att_type == AttachmentType.PDF:
            context.has_pdf = True
        elif att_type == AttachmentType.URL:
            context.has_url = True
        elif att_type == AttachmentType.AUDIO:
            context.has_audio = True
        elif att_type == AttachmentType.VIDEO:
            context.has_video = True

        # 抽出データ
        if result.success and result.output:
            # エンティティ
            if result.output.entities:
                context.extracted_entities.extend(result.output.entities)

            # 要約
            if result.output.summary:
                context.summaries.append(result.output.summary)

        # 詳細情報
        context.processing_details.append({
            "filename": result.attachment_info.filename,
            "type": att_type.value,
            "success": result.success,
            "processing_time_ms": result.processing_time_ms,
            "error": result.error_message if not result.success else None,
        })

    return context


# =============================================================================
# ヘルパー関数
# =============================================================================


def should_process_as_multimodal(
    message_text: str,
    attachments: List[Dict[str, Any]],
) -> bool:
    """
    メッセージをマルチモーダル処理すべきかを判定

    Args:
        message_text: テキストメッセージ
        attachments: 添付ファイルリスト

    Returns:
        マルチモーダル処理すべきならTrue
    """
    # 添付ファイルがあれば処理
    if attachments:
        return True

    # テキスト内にURLがあれば処理
    if message_text:
        import re
        url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
        if re.search(url_pattern, message_text):
            return True

    return False


def extract_instruction_from_message(
    message_text: str,
    default_instruction: str = "",
) -> str:
    """
    メッセージから処理指示を抽出

    ユーザーのメッセージから、何をしてほしいかの指示部分を抽出する。

    Args:
        message_text: テキストメッセージ
        default_instruction: デフォルトの指示

    Returns:
        抽出された指示
    """
    if not message_text:
        return default_instruction

    # URL部分を除去
    import re
    text_without_urls = re.sub(r'https?://[^\s]+', '', message_text).strip()

    if text_without_urls:
        return text_without_urls

    return default_instruction


def format_multimodal_response(
    brain_response: str,
    multimodal_context: MultimodalBrainContext,
    include_processing_info: bool = True,
) -> str:
    """
    マルチモーダル処理情報を応答に追加

    脳からの応答に、マルチモーダル処理の情報を追加する。

    Args:
        brain_response: 脳からの応答
        multimodal_context: マルチモーダルコンテキスト
        include_processing_info: 処理情報を含めるか

    Returns:
        フォーマット済み応答
    """
    if not multimodal_context.has_multimodal_content:
        return brain_response

    parts = [brain_response]

    if include_processing_info and multimodal_context.failed_count > 0:
        # 失敗した処理があれば通知
        parts.append("")
        parts.append(
            f"⚠️ {multimodal_context.failed_count}件の添付ファイルの処理に失敗しました"
        )

    return "\n".join(parts)


# =============================================================================
# ChatWork連携用関数
# =============================================================================


async def handle_chatwork_message_with_attachments(
    message_body: str,
    attachments: List[Dict[str, Any]],
    room_id: str,
    account_id: str,
    sender_name: str,
    pool,
    org_id: str,
    brain,  # SoulkunBrain instance
    download_func=None,  # ファイルダウンロード関数
    feature_flags: Optional[Dict[str, bool]] = None,
) -> str:
    """
    ChatWorkからの添付ファイル付きメッセージを処理

    ChatWork Webhookから呼び出される統合関数。
    添付ファイルをダウンロード、処理し、脳に渡して応答を生成する。

    Args:
        message_body: メッセージ本文
        attachments: ChatWorkの添付ファイル情報
            [{"file_id": str, "filename": str, "file_size": int}, ...]
        room_id: ChatWorkルームID
        account_id: ユーザーアカウントID
        sender_name: 送信者名
        pool: データベース接続プール
        org_id: 組織ID
        brain: SoulkunBrainインスタンス
        download_func: ファイルダウンロード関数 (file_id) -> bytes
        feature_flags: Feature Flagの設定

    Returns:
        脳からの応答テキスト

    使用例:
        # chatwork_webhook/handlers/message_handler.py
        from lib.capabilities.multimodal.brain_integration import (
            handle_chatwork_message_with_attachments
        )

        async def handle_message(event, brain, pool, org_id):
            if event.attachments:
                return await handle_chatwork_message_with_attachments(
                    message_body=event.body,
                    attachments=event.attachments,
                    room_id=event.room_id,
                    account_id=event.account_id,
                    sender_name=event.sender_name,
                    pool=pool,
                    org_id=org_id,
                    brain=brain,
                    download_func=chatwork_api.download_file,
                )
            else:
                return await brain.process_message(...)
    """
    try:
        # 添付ファイルをダウンロード
        downloaded_attachments = []
        if attachments and download_func:
            for att in attachments:
                try:
                    file_data = await download_func(att.get("file_id"))
                    downloaded_attachments.append({
                        "data": file_data,
                        "filename": att.get("filename", ""),
                        "mime_type": att.get("mime_type"),
                    })
                except Exception as e:
                    logger.warning(
                        f"Failed to download attachment {att.get('filename')}: {e}"
                    )

        # マルチモーダル処理
        enriched_message, multimodal_context = await process_message_with_multimodal(
            message_text=message_body,
            attachments=downloaded_attachments,
            pool=pool,
            org_id=org_id,
            room_id=room_id,
            user_id=account_id,
            feature_flags=feature_flags,
        )

        # 脳に渡す
        # エンリッチドメッセージのフルコンテキストを使用
        brain_response = await brain.process_message(
            message=enriched_message.get_full_context(),
            room_id=room_id,
            account_id=account_id,
            sender_name=sender_name,
        )

        # 応答をフォーマット
        formatted_response = format_multimodal_response(
            brain_response=brain_response.message,
            multimodal_context=multimodal_context,
        )

        return formatted_response

    except Exception as e:
        logger.error(f"Error in handle_chatwork_message_with_attachments: {e}", exc_info=True)
        # エラー時は通常のメッセージ処理にフォールバック
        brain_response = await brain.process_message(
            message=message_body,
            room_id=room_id,
            account_id=account_id,
            sender_name=sender_name,
        )
        return brain_response.message


# =============================================================================
# エクスポート用
# =============================================================================


__all__ = [
    "MultimodalBrainContext",
    "process_message_with_multimodal",
    "create_multimodal_context",
    "should_process_as_multimodal",
    "extract_instruction_from_message",
    "format_multimodal_response",
    "handle_chatwork_message_with_attachments",
]
