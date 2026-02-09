# lib/brain/capability_bridge.py
"""
脳と機能モジュールの橋渡し層（Capability Bridge）

このモジュールは、SoulkunBrainと各機能モジュール（capabilities）の
統合を担当する。

設計書: docs/brain_capability_integration_design.md

【7つの鉄則との整合性】
1. 全ての入力は脳を通る → 前処理後は必ず脳に渡す
2. 脳は全ての記憶にアクセスできる → 処理結果はBrainContextに含める
3. 脳が判断、機能は実行のみ → このモジュールは前処理と実行のみ
4. 機能拡張しても脳の構造は変わらない → ブリッジパターンで分離
5. 確認は脳の責務 → 確認判断は脳が行う
6. 状態管理は脳が統一管理 → このモジュールは状態を持たない
7. 速度より正確性を優先 → 処理品質を優先

使用例:
    from lib.brain.capability_bridge import CapabilityBridge

    # 初期化
    bridge = CapabilityBridge(pool=db_pool, org_id="org_soulsyncs")

    # メッセージ前処理（添付ファイル処理）
    enriched_message, multimodal_context = await bridge.preprocess_message(
        message="この画像を確認して",
        attachments=[{"data": image_bytes, "filename": "image.png"}],
        room_id="123",
        user_id="456",
    )

    # ハンドラー取得
    handlers = bridge.get_capability_handlers()

Author: Claude Opus 4.5
Created: 2026-01-28
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple
from uuid import UUID

from lib.brain.models import HandlerResult

logger = logging.getLogger(__name__)


# =============================================================================
# Feature Flags
# =============================================================================

# 各機能のON/OFF（デフォルトは無効、段階的に有効化）
DEFAULT_FEATURE_FLAGS = {
    # Multimodal (Phase M)
    "ENABLE_IMAGE_PROCESSING": True,
    "ENABLE_PDF_PROCESSING": True,
    "ENABLE_URL_PROCESSING": True,
    "ENABLE_AUDIO_PROCESSING": False,  # Phase M2
    "ENABLE_VIDEO_PROCESSING": False,  # Phase M3

    # Generation (Phase G)
    "ENABLE_DOCUMENT_GENERATION": True,
    "ENABLE_IMAGE_GENERATION": True,
    "ENABLE_VIDEO_GENERATION": False,  # コスト高いためデフォルト無効
    "ENABLE_DEEP_RESEARCH": True,  # G3: ディープリサーチ
    "ENABLE_GOOGLE_SHEETS": True,  # G4: スプレッドシート操作
    "ENABLE_GOOGLE_SLIDES": True,  # G4: スライド操作

    # Feedback (Phase F)
    "ENABLE_CEO_FEEDBACK": True,

    # Meeting Transcription (Phase C)
    "ENABLE_MEETING_TRANSCRIPTION": False,  # Phase C MVP0: フィーチャーフラグで段階有効化

    # Meeting Minutes Generation (Phase C MVP1)
    "ENABLE_MEETING_MINUTES": False,  # Phase C MVP1: ChatWork音声→議事録自動生成

    # Zoom Meeting Minutes (Phase C Case C)
    "ENABLE_ZOOM_MEETING_MINUTES": False,  # Phase C Case C: フィーチャーフラグで段階有効化
}


# =============================================================================
# 定数
# =============================================================================

# 処理タイムアウト（秒）
MULTIMODAL_TIMEOUT_SECONDS = 60
GENERATION_TIMEOUT_SECONDS = 120

# 最大処理数
MAX_ATTACHMENTS_PER_MESSAGE = 5
MAX_URLS_PER_MESSAGE = 3


# =============================================================================
# CapabilityBridge クラス
# =============================================================================


class CapabilityBridge:
    """
    脳と機能モジュールの橋渡し層

    主な責務:
    1. メッセージの前処理（Multimodal）
    2. 生成ハンドラーの提供（Generation）
    3. フィードバック機能の統合（Feedback）

    使用例:
        bridge = CapabilityBridge(pool=db_pool, org_id="org_soulsyncs")

        # 前処理
        enriched, context = await bridge.preprocess_message(...)

        # ハンドラー取得
        handlers = bridge.get_capability_handlers()
    """

    def __init__(
        self,
        pool,
        org_id: str,
        feature_flags: Optional[Dict[str, bool]] = None,
        llm_caller: Optional[Callable] = None,
    ):
        """
        初期化

        Args:
            pool: データベース接続プール
            org_id: 組織ID
            feature_flags: Feature Flagの設定（省略時はデフォルト）
            llm_caller: LLM呼び出し関数
        """
        self.pool = pool
        self.org_id = org_id
        self.feature_flags = {**DEFAULT_FEATURE_FLAGS, **(feature_flags or {})}
        self.llm_caller = llm_caller

        # 遅延初期化用のインスタンス変数
        self._multimodal_coordinator = None
        self._document_generator = None
        self._image_generator = None
        self._video_generator = None
        self._feedback_engine = None

        logger.info(
            f"CapabilityBridge initialized for org_id={org_id}, "
            f"flags={self.feature_flags}"
        )

    @staticmethod
    def _safe_parse_uuid(value: Optional[str]) -> Optional[UUID]:
        """文字列をUUIDに安全に変換するヘルパー

        ChatworkのアカウントIDなど、UUID形式でない場合はuuid5で変換する。
        """
        if not value:
            return None
        try:
            return UUID(str(value))
        except (ValueError, TypeError, AttributeError):
            import uuid as uuid_mod
            return uuid_mod.uuid5(uuid_mod.NAMESPACE_OID, str(value))

    def _parse_org_uuid(self) -> UUID:
        """org_id文字列をUUIDに変換するヘルパー

        UUID形式でない場合（例: "org_soulsyncs"）はuuid5で決定論的に変換する。
        """
        if isinstance(self.org_id, UUID):
            return self.org_id
        try:
            return UUID(self.org_id)
        except (ValueError, TypeError, AttributeError):
            import uuid as uuid_mod
            return uuid_mod.uuid5(uuid_mod.NAMESPACE_OID, str(self.org_id))

    # =========================================================================
    # Multimodal 前処理
    # =========================================================================

    async def preprocess_message(
        self,
        message: str,
        attachments: List[Dict[str, Any]],
        room_id: str,
        user_id: str,
        download_func: Optional[Callable] = None,
    ) -> Tuple[str, Optional[Any]]:
        """
        メッセージの前処理（マルチモーダル）

        添付ファイルやURLを処理し、テキストを拡張する。

        Args:
            message: 元のメッセージテキスト
            attachments: 添付ファイル情報のリスト
                ChatWork形式: [{"file_id": str, "filename": str}, ...]
                直接データ: [{"data": bytes, "filename": str}, ...]
            room_id: ChatWorkルームID
            user_id: ユーザーID
            download_func: ファイルダウンロード関数（ChatWork用）

        Returns:
            (enriched_message, multimodal_context) のタプル
            - enriched_message: 拡張されたメッセージテキスト
            - multimodal_context: MultimodalBrainContext または None
        """
        # マルチモーダル処理が無効なら早期リターン
        if not self._is_multimodal_enabled():
            return message, None

        # 添付ファイルがなく、URLもなければ早期リターン
        if not attachments and not self._contains_urls(message):
            return message, None

        try:
            # Multimodal統合モジュールをインポート
            from lib.capabilities.multimodal.brain_integration import (
                process_message_with_multimodal,
                should_process_as_multimodal,
            )

            # 処理すべきか判定
            if not should_process_as_multimodal(message, attachments):
                return message, None

            # 添付ファイルをダウンロード（必要に応じて）
            downloaded_attachments = await self._download_attachments(
                attachments, download_func
            )

            # マルチモーダル処理を実行
            enriched_message, multimodal_context = await process_message_with_multimodal(
                message_text=message,
                attachments=downloaded_attachments,
                pool=self.pool,
                org_id=self.org_id,
                room_id=room_id,
                user_id=user_id,
                feature_flags=self.feature_flags,
                process_urls_in_text=self.feature_flags.get("ENABLE_URL_PROCESSING", True),
                max_urls=MAX_URLS_PER_MESSAGE,
            )

            # エンリッチドメッセージからフルテキストを取得
            full_text = enriched_message.get_full_context()

            logger.info(
                f"[CapabilityBridge] Multimodal preprocessing complete: "
                f"attachments={len(downloaded_attachments)}, "
                f"successful={multimodal_context.successful_count if multimodal_context else 0}"
            )

            return full_text, multimodal_context

        except ImportError as e:
            logger.warning(f"[CapabilityBridge] Multimodal module not available: {e}")
            return message, None
        except Exception as e:
            logger.error(f"[CapabilityBridge] Multimodal preprocessing failed: {e}", exc_info=True)
            # エラー時は元のメッセージをそのまま返す
            return message, None

    def _is_multimodal_enabled(self) -> bool:
        """マルチモーダル処理が有効かどうか"""
        return any([
            self.feature_flags.get("ENABLE_IMAGE_PROCESSING", False),
            self.feature_flags.get("ENABLE_PDF_PROCESSING", False),
            self.feature_flags.get("ENABLE_URL_PROCESSING", False),
            self.feature_flags.get("ENABLE_AUDIO_PROCESSING", False),
        ])

    def _contains_urls(self, text: str) -> bool:
        """テキストにURLが含まれているか"""
        import re
        url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
        return bool(re.search(url_pattern, text))

    async def _download_attachments(
        self,
        attachments: List[Dict[str, Any]],
        download_func: Optional[Callable],
    ) -> List[Dict[str, Any]]:
        """
        添付ファイルをダウンロード

        ChatWorkのfile_id形式の場合はダウンロードし、
        直接data形式の場合はそのまま返す。
        """
        if not attachments:
            return []

        downloaded = []
        for att in attachments[:MAX_ATTACHMENTS_PER_MESSAGE]:
            # 既にdataがある場合はそのまま使用
            if "data" in att:
                downloaded.append(att)
                continue

            # file_idがあり、download_funcがある場合はダウンロード
            if "file_id" in att and download_func:
                try:
                    file_data = await download_func(att["file_id"])
                    downloaded.append({
                        "data": file_data,
                        "filename": att.get("filename", ""),
                        "mime_type": att.get("mime_type"),
                    })
                except Exception as e:
                    logger.warning(
                        f"[CapabilityBridge] Failed to download attachment "
                        f"{att.get('filename')}: {e}"
                    )

        return downloaded

    # =========================================================================
    # Generation ハンドラー
    # =========================================================================

    def get_capability_handlers(self) -> Dict[str, Callable]:
        """
        生成機能のハンドラーを取得

        脳のBrainExecutionに登録するハンドラーを返す。

        Returns:
            ハンドラー名 → ハンドラー関数のマッピング
        """
        handlers = {}

        # Document Generation
        if self.feature_flags.get("ENABLE_DOCUMENT_GENERATION", False):
            handlers["generate_document"] = self._handle_document_generation
            handlers["generate_report"] = self._handle_document_generation
            handlers["create_document"] = self._handle_document_generation

        # Image Generation
        if self.feature_flags.get("ENABLE_IMAGE_GENERATION", False):
            handlers["generate_image"] = self._handle_image_generation
            handlers["create_image"] = self._handle_image_generation

        # Video Generation
        if self.feature_flags.get("ENABLE_VIDEO_GENERATION", False):
            handlers["generate_video"] = self._handle_video_generation
            handlers["create_video"] = self._handle_video_generation

        # CEO Feedback
        if self.feature_flags.get("ENABLE_CEO_FEEDBACK", False):
            handlers["generate_feedback"] = self._handle_feedback_generation
            handlers["ceo_feedback"] = self._handle_feedback_generation

        # Deep Research (G3)
        if self.feature_flags.get("ENABLE_DEEP_RESEARCH", False):
            handlers["deep_research"] = self._handle_deep_research
            handlers["research"] = self._handle_deep_research
            handlers["investigate"] = self._handle_deep_research

        # Google Sheets (G4)
        if self.feature_flags.get("ENABLE_GOOGLE_SHEETS", False):
            handlers["read_spreadsheet"] = self._handle_read_spreadsheet
            handlers["write_spreadsheet"] = self._handle_write_spreadsheet
            handlers["create_spreadsheet"] = self._handle_create_spreadsheet

        # Google Slides (G4)
        if self.feature_flags.get("ENABLE_GOOGLE_SLIDES", False):
            handlers["read_presentation"] = self._handle_read_presentation
            handlers["create_presentation"] = self._handle_create_presentation

        # Meeting Transcription (Phase C MVP0)
        if self.feature_flags.get("ENABLE_MEETING_TRANSCRIPTION", False):
            handlers["meeting_transcription"] = self._handle_meeting_transcription

        # Zoom Meeting Minutes (Phase C Case C)
        if self.feature_flags.get("ENABLE_ZOOM_MEETING_MINUTES", False):
            handlers["zoom_meeting_minutes"] = self._handle_zoom_meeting_minutes

        # Connection Query（v10.44.0: DM可能な相手一覧）
        # Feature Flag不要（常に有効）
        handlers["connection_query"] = self._handle_connection_query

        logger.debug(f"[CapabilityBridge] Handlers registered: {list(handlers.keys())}")
        return handlers

    async def _handle_document_generation(
        self,
        room_id: str,
        account_id: str,
        sender_name: str,
        params: Dict[str, Any],
        **kwargs,
    ) -> HandlerResult:
        """
        文書生成ハンドラー

        Args:
            room_id: ChatWorkルームID
            account_id: ユーザーアカウントID
            sender_name: 送信者名
            params: パラメータ
                - document_type: 文書タイプ（report/summary/proposal）
                - topic: トピック
                - outline: アウトライン（オプション）
                - output_format: 出力形式（google_docs/markdown）

        Returns:
            HandlerResult
        """
        try:
            from lib.capabilities.generation import DocumentGenerator
            from lib.capabilities.generation.models import (
                DocumentRequest,
                GenerationInput,
            )
            from lib.capabilities.generation.constants import (
                DocumentType,
                GenerationType,
                OutputFormat,
            )

            document_type_str = params.get("document_type", "report")
            topic = params.get("topic", "")
            outline = params.get("outline")
            output_format_str = params.get("output_format", "google_docs")

            if not topic:
                return HandlerResult(
                    success=False,
                    message="何について文書を作成すればいいか教えてほしいウル🐺",
                )

            org_uuid = self._parse_org_uuid()

            # 文書タイプのマッピング
            doc_type_map: Dict[str, DocumentType] = {
                "report": DocumentType.REPORT,
                "summary": DocumentType.SUMMARY,
                "proposal": DocumentType.PROPOSAL,
                "minutes": DocumentType.MINUTES,
                "manual": DocumentType.MANUAL,
            }
            doc_type = doc_type_map.get(document_type_str, DocumentType.REPORT)

            # 出力形式のマッピング
            format_map: Dict[str, OutputFormat] = {
                "google_docs": OutputFormat.GOOGLE_DOCS,
                "markdown": OutputFormat.MARKDOWN,
            }
            out_format = format_map.get(output_format_str, OutputFormat.GOOGLE_DOCS)

            # 文書生成器を初期化
            generator = DocumentGenerator(
                pool=self.pool,
                organization_id=org_uuid,
            )

            # リクエスト作成
            instruction = topic
            if outline:
                instruction = f"{topic}\n\nアウトライン:\n{outline}"
            doc_request = DocumentRequest(
                title=topic,
                organization_id=org_uuid,
                document_type=doc_type,
                output_format=out_format,
                instruction=instruction,
                require_confirmation=False,
            )

            # 文書を生成
            result = await generator.generate(GenerationInput(
                generation_type=GenerationType.DOCUMENT,
                organization_id=org_uuid,
                document_request=doc_request,
            ))

            if result.success:
                message = f"文書を作成したウル！🐺\n\n"
                doc_result = result.document_result
                doc_url = doc_result.document_url if doc_result else None
                doc_id = doc_result.document_id if doc_result else None
                if doc_url:
                    message += f"📄 {doc_url}"
                return HandlerResult(
                    success=True,
                    message=message,
                    data={"document_url": doc_url, "document_id": doc_id},
                )
            else:
                return HandlerResult(
                    success=False,
                    message=f"文書の作成に失敗したウル🐺 {result.error_message}",
                )

        except ImportError:
            return HandlerResult(
                success=False,
                message="文書生成機能が利用できないウル🐺",
            )
        except Exception as e:
            logger.error(f"[CapabilityBridge] Document generation failed: {e}", exc_info=True)
            return HandlerResult(
                success=False,
                message="文書の作成中にエラーが発生したウル🐺",
            )

    async def _handle_image_generation(
        self,
        room_id: str,
        account_id: str,
        sender_name: str,
        params: Dict[str, Any],
        **kwargs,
    ) -> HandlerResult:
        """
        画像生成ハンドラー

        Args:
            room_id: ChatWorkルームID
            account_id: ユーザーアカウントID
            sender_name: 送信者名
            params: パラメータ
                - prompt: 画像の説明
                - style: スタイル（オプション）
                - size: サイズ（オプション）

        Returns:
            HandlerResult
        """
        try:
            from lib.capabilities.generation import ImageGenerator
            from lib.capabilities.generation.models import (
                ImageRequest,
                GenerationInput,
            )
            from lib.capabilities.generation.constants import GenerationType

            prompt = params.get("prompt", "")
            style = params.get("style")
            size = params.get("size", "1024x1024")

            if not prompt:
                return HandlerResult(
                    success=False,
                    message="どんな画像を作ればいいか教えてほしいウル🐺",
                )

            org_uuid = self._parse_org_uuid()

            # 画像生成器を初期化
            generator = ImageGenerator(
                pool=self.pool,
                organization_id=org_uuid,
            )

            # スタイル・サイズのマッピング
            from lib.capabilities.generation.constants import ImageStyle, ImageSize

            style_map: Dict[str, ImageStyle] = {
                "vivid": ImageStyle.VIVID,
                "natural": ImageStyle.NATURAL,
                "anime": ImageStyle.ANIME,
                "realistic": ImageStyle.PHOTOREALISTIC,
                "photorealistic": ImageStyle.PHOTOREALISTIC,
                "illustration": ImageStyle.ILLUSTRATION,
                "minimalist": ImageStyle.MINIMALIST,
                "corporate": ImageStyle.CORPORATE,
            }
            size_map: Dict[str, ImageSize] = {
                "1024x1024": ImageSize.SQUARE_1024,
                "1792x1024": ImageSize.LANDSCAPE_1792,
                "1024x1792": ImageSize.PORTRAIT_1024,
            }

            # リクエスト作成
            image_request = ImageRequest(
                organization_id=org_uuid,
                prompt=prompt,
                style=style_map.get(style, ImageStyle.VIVID) if style else ImageStyle.VIVID,
                size=size_map.get(size, ImageSize.SQUARE_1024),
                send_to_chatwork=True,
                chatwork_room_id=room_id,
            )

            # 画像を生成
            result = await generator.generate(GenerationInput(
                generation_type=GenerationType.IMAGE,
                organization_id=org_uuid,
                image_request=image_request,
            ))

            if result.success:
                message = f"画像を作成したウル！🐺\n\n"
                img_result = result.image_result
                img_url = img_result.image_url if img_result else None
                if img_url:
                    message += f"🖼️ {img_url}"
                return HandlerResult(
                    success=True,
                    message=message,
                    data={"image_url": img_url},
                )
            else:
                return HandlerResult(
                    success=False,
                    message=f"画像の作成に失敗したウル🐺 {result.error_message}",
                )

        except ImportError:
            return HandlerResult(
                success=False,
                message="画像生成機能が利用できないウル🐺",
            )
        except Exception as e:
            logger.error(f"[CapabilityBridge] Image generation failed: {e}", exc_info=True)
            return HandlerResult(
                success=False,
                message="画像の作成中にエラーが発生したウル🐺",
            )

    async def _handle_video_generation(
        self,
        room_id: str,
        account_id: str,
        sender_name: str,
        params: Dict[str, Any],
        **kwargs,
    ) -> HandlerResult:
        """
        動画生成ハンドラー

        Args:
            room_id: ChatWorkルームID
            account_id: ユーザーアカウントID
            sender_name: 送信者名
            params: パラメータ
                - prompt: 動画の説明
                - duration: 長さ（秒）
                - style: スタイル

        Returns:
            HandlerResult
        """
        try:
            from lib.capabilities.generation import VideoGenerator
            from lib.capabilities.generation.models import (
                VideoRequest,
                GenerationInput,
            )
            from lib.capabilities.generation.constants import GenerationType

            prompt = params.get("prompt", "")
            duration = params.get("duration", 5)

            if not prompt:
                return HandlerResult(
                    success=False,
                    message="どんな動画を作ればいいか教えてほしいウル🐺",
                )

            org_uuid = self._parse_org_uuid()

            # 動画生成器を初期化
            generator = VideoGenerator(
                pool=self.pool,
                organization_id=org_uuid,
            )

            # Duration マッピング
            from lib.capabilities.generation.constants import VideoDuration

            duration_map: Dict[int, VideoDuration] = {
                5: VideoDuration.SHORT_5S,
                10: VideoDuration.STANDARD_10S,
            }

            # リクエスト作成
            video_request = VideoRequest(
                organization_id=org_uuid,
                prompt=prompt,
                duration=duration_map.get(int(duration), VideoDuration.SHORT_5S),
            )

            # 動画を生成
            result = await generator.generate(GenerationInput(
                generation_type=GenerationType.VIDEO,
                organization_id=org_uuid,
                video_request=video_request,
            ))

            if result.success:
                message = f"動画を作成したウル！🐺\n\n"
                vid_result = result.video_result
                vid_url = vid_result.video_url if vid_result else None
                if vid_url:
                    message += f"🎬 {vid_url}"
                return HandlerResult(
                    success=True,
                    message=message,
                    data={"video_url": vid_url},
                )
            else:
                return HandlerResult(
                    success=False,
                    message=f"動画の作成に失敗したウル🐺 {result.error_message}",
                )

        except ImportError:
            return HandlerResult(
                success=False,
                message="動画生成機能が利用できないウル🐺",
            )
        except Exception as e:
            logger.error(f"[CapabilityBridge] Video generation failed: {e}", exc_info=True)
            return HandlerResult(
                success=False,
                message="動画の作成中にエラーが発生したウル🐺",
            )

    async def _handle_feedback_generation(
        self,
        room_id: str,
        account_id: str,
        sender_name: str,
        params: Dict[str, Any],
        **kwargs,
    ) -> HandlerResult:
        """
        CEOフィードバック生成ハンドラー

        Args:
            room_id: ChatWorkルームID
            account_id: ユーザーアカウントID
            sender_name: 送信者名
            params: パラメータ
                - target_user_id: 対象ユーザーID（オプション）
                - period: 期間（week/month/quarter）

        Returns:
            HandlerResult
        """
        try:
            from lib.capabilities.feedback import CEOFeedbackEngine
            from lib.capabilities.feedback.ceo_feedback_engine import CEOFeedbackSettings

            target_user_id = params.get("target_user_id")
            period = params.get("period", "week")

            org_uuid = self._parse_org_uuid()

            # account_idはChatwork数値IDの場合があるため、安全にUUID変換
            recipient_id = self._safe_parse_uuid(target_user_id or account_id)
            if recipient_id is None:
                return HandlerResult(
                    success=False,
                    message="対象ユーザーを特定できなかったウル🐺",
                )

            # フィードバック設定を作成
            settings = CEOFeedbackSettings(
                recipient_user_id=recipient_id,
                recipient_name=sender_name,
            )

            # フィードバックエンジンを初期化（Poolからconnectionを取得）
            with self.pool.connect() as conn:
                engine = CEOFeedbackEngine(
                    conn=conn,
                    organization_id=org_uuid,
                    settings=settings,
                )

                # フィードバックを生成（オンデマンド分析を使用）
                query = f"{period}のフィードバック"
                feedback, _delivery_result = await engine.analyze_on_demand(
                    query=query,
                    deliver=False,
                )

            return HandlerResult(
                success=True,
                message=feedback.summary or "フィードバックを生成したウル🐺",
                data={"feedback_id": feedback.feedback_id},
            )

        except ImportError:
            return HandlerResult(
                success=False,
                message="フィードバック機能が利用できないウル🐺",
            )
        except Exception as e:
            logger.error(f"[CapabilityBridge] Feedback generation failed: {e}", exc_info=True)
            return HandlerResult(
                success=False,
                message="フィードバックの生成中にエラーが発生したウル🐺",
            )

    # =========================================================================
    # G3: Deep Research ハンドラー
    # =========================================================================

    async def _handle_deep_research(
        self,
        room_id: str,
        account_id: str,
        sender_name: str,
        params: Dict[str, Any],
        **kwargs,
    ) -> HandlerResult:
        """
        ディープリサーチハンドラー

        Args:
            room_id: ChatWorkルームID
            account_id: ユーザーアカウントID
            sender_name: 送信者名
            params: パラメータ
                - query: 調査クエリ
                - depth: 調査深度 (quick/standard/deep/comprehensive)
                - research_type: 調査タイプ (general/competitor/market/technology)

        Returns:
            HandlerResult
        """
        try:
            from lib.capabilities.generation import (
                ResearchEngine,
                ResearchRequest,
                ResearchDepth,
                ResearchType,
                GenerationInput,
                GenerationType,
            )

            query = params.get("query", "")
            depth_str = params.get("depth", "standard")
            research_type_str = params.get("research_type", "general")

            if not query:
                return HandlerResult(
                    success=False,
                    message="何について調べればいいか教えてほしいウル🐺",
                )

            # 深度のマッピング
            depth_map = {
                "quick": ResearchDepth.QUICK,
                "standard": ResearchDepth.STANDARD,
                "deep": ResearchDepth.DEEP,
                "comprehensive": ResearchDepth.COMPREHENSIVE,
            }
            depth = depth_map.get(depth_str, ResearchDepth.STANDARD)

            # タイプのマッピング
            type_map = {
                "general": ResearchType.TOPIC,
                "competitor": ResearchType.COMPETITOR,
                "market": ResearchType.MARKET,
                "technology": ResearchType.TECHNOLOGY,
            }
            research_type = type_map.get(research_type_str, ResearchType.TOPIC)

            org_uuid = self._parse_org_uuid()

            # リサーチエンジンを初期化
            engine = ResearchEngine(
                pool=self.pool,
                organization_id=org_uuid,
            )

            # リクエスト作成
            request = ResearchRequest(
                organization_id=org_uuid,
                query=query,
                depth=depth,
                research_type=research_type,
                user_id=self._safe_parse_uuid(account_id),
                chatwork_room_id=room_id,
                save_to_drive=True,
            )

            # リサーチ実行
            result = await engine.generate(GenerationInput(
                generation_type=GenerationType.RESEARCH,
                organization_id=org_uuid,
                research_request=request,
            ))

            if result.success and result.research_result:
                res = result.research_result
                message = f"調査が完了したウル！🐺\n\n"
                message += f"📊 **調査結果: {query[:30]}...**\n\n"
                if res.executive_summary:
                    message += f"**要約:**\n{res.executive_summary}\n\n"
                if res.key_findings:
                    message += f"**主な発見:**\n"
                    for i, finding in enumerate(res.key_findings[:5], 1):
                        message += f"{i}. {finding}\n"
                    message += "\n"
                if res.document_url:
                    message += f"📄 詳細レポート: {res.document_url}\n"
                if res.actual_cost_jpy:
                    message += f"\n💰 調査コスト: ¥{res.actual_cost_jpy:.0f}"

                return HandlerResult(
                    success=True,
                    message=message,
                    data={
                        "document_url": res.document_url,
                        "sources_count": res.sources_count,
                        "cost_jpy": res.actual_cost_jpy,
                    },
                )
            else:
                return HandlerResult(
                    success=False,
                    message="調査に失敗したウル🐺",
                )

        except ImportError:
            return HandlerResult(
                success=False,
                message="ディープリサーチ機能が利用できないウル🐺",
            )
        except Exception as e:
            logger.error(f"[CapabilityBridge] Deep research failed: {e}", exc_info=True)
            return HandlerResult(
                success=False,
                message="調査中にエラーが発生したウル🐺",
            )

    # =========================================================================
    # G4: Google Sheets ハンドラー
    # =========================================================================

    async def _handle_read_spreadsheet(
        self,
        room_id: str,
        account_id: str,
        sender_name: str,
        params: Dict[str, Any],
        **kwargs,
    ) -> HandlerResult:
        """
        スプレッドシート読み込みハンドラー

        Args:
            params: パラメータ
                - spreadsheet_id: スプレッドシートID
                - range: 読み込み範囲（例: "Sheet1!A1:D10"）

        Returns:
            HandlerResult
        """
        try:
            from lib.capabilities.generation import GoogleSheetsClient

            spreadsheet_id = params.get("spreadsheet_id", "")
            range_name = params.get("range", "")

            if not spreadsheet_id:
                return HandlerResult(
                    success=False,
                    message="スプレッドシートのIDを教えてほしいウル🐺",
                )

            client = GoogleSheetsClient()
            data = await client.read_sheet(
                spreadsheet_id=spreadsheet_id,
                range_notation=range_name or "Sheet1",
            )

            if data:
                # Markdownテーブルに変換
                markdown = client.to_markdown_table(data)
                message = f"スプレッドシートの内容ウル！🐺\n\n{markdown}"
                return HandlerResult(
                    success=True,
                    message=message,
                    data={"rows": len(data), "data": data},
                )
            else:
                return HandlerResult(
                    success=True,
                    message="スプレッドシートにデータがなかったウル🐺",
                    data={"rows": 0, "data": []},
                )

        except ImportError:
            return HandlerResult(
                success=False,
                message="スプレッドシート機能が利用できないウル🐺",
            )
        except Exception as e:
            logger.error(f"[CapabilityBridge] Read spreadsheet failed: {e}", exc_info=True)
            return HandlerResult(
                success=False,
                message="スプレッドシートの読み込みに失敗したウル🐺",
            )

    async def _handle_write_spreadsheet(
        self,
        room_id: str,
        account_id: str,
        sender_name: str,
        params: Dict[str, Any],
        **kwargs,
    ) -> HandlerResult:
        """
        スプレッドシート書き込みハンドラー

        Args:
            params: パラメータ
                - spreadsheet_id: スプレッドシートID
                - range: 書き込み範囲
                - data: 書き込みデータ（2次元配列）

        Returns:
            HandlerResult
        """
        try:
            from lib.capabilities.generation import GoogleSheetsClient

            spreadsheet_id = params.get("spreadsheet_id", "")
            range_name = params.get("range", "Sheet1!A1")
            data = params.get("data", [])

            if not spreadsheet_id:
                return HandlerResult(
                    success=False,
                    message="スプレッドシートのIDを教えてほしいウル🐺",
                )

            if not data:
                return HandlerResult(
                    success=False,
                    message="書き込むデータを教えてほしいウル🐺",
                )

            client = GoogleSheetsClient()
            result = await client.write_sheet(
                spreadsheet_id=spreadsheet_id,
                range_notation=range_name,
                values=data,
            )

            return HandlerResult(
                success=True,
                message=f"スプレッドシートに書き込んだウル！🐺\n更新セル数: {result.get('updatedCells', 0)}",
                data=result,
            )

        except ImportError:
            return HandlerResult(
                success=False,
                message="スプレッドシート機能が利用できないウル🐺",
            )
        except Exception as e:
            logger.error(f"[CapabilityBridge] Write spreadsheet failed: {e}", exc_info=True)
            return HandlerResult(
                success=False,
                message="スプレッドシートへの書き込みに失敗したウル🐺",
            )

    async def _handle_create_spreadsheet(
        self,
        room_id: str,
        account_id: str,
        sender_name: str,
        params: Dict[str, Any],
        **kwargs,
    ) -> HandlerResult:
        """
        スプレッドシート作成ハンドラー

        Args:
            params: パラメータ
                - title: スプレッドシート名
                - sheets: シート名のリスト（オプション）

        Returns:
            HandlerResult
        """
        try:
            from lib.capabilities.generation import GoogleSheetsClient

            title = params.get("title", "新規スプレッドシート")
            sheets = params.get("sheets", ["Sheet1"])

            client = GoogleSheetsClient()
            result = await client.create_spreadsheet(
                title=title,
                sheet_names=sheets,
            )

            spreadsheet_url = f"https://docs.google.com/spreadsheets/d/{result['spreadsheet_id']}"
            return HandlerResult(
                success=True,
                message=f"スプレッドシートを作成したウル！🐺\n\n📊 {spreadsheet_url}",
                data={
                    "spreadsheet_id": result["spreadsheet_id"],
                    "url": spreadsheet_url,
                },
            )

        except ImportError:
            return HandlerResult(
                success=False,
                message="スプレッドシート機能が利用できないウル🐺",
            )
        except Exception as e:
            logger.error(f"[CapabilityBridge] Create spreadsheet failed: {e}", exc_info=True)
            return HandlerResult(
                success=False,
                message="スプレッドシートの作成に失敗したウル🐺",
            )

    # =========================================================================
    # G4: Google Slides ハンドラー
    # =========================================================================

    async def _handle_read_presentation(
        self,
        room_id: str,
        account_id: str,
        sender_name: str,
        params: Dict[str, Any],
        **kwargs,
    ) -> HandlerResult:
        """
        プレゼンテーション読み込みハンドラー

        Args:
            params: パラメータ
                - presentation_id: プレゼンテーションID

        Returns:
            HandlerResult
        """
        try:
            from lib.capabilities.generation import GoogleSlidesClient

            presentation_id = params.get("presentation_id", "")

            if not presentation_id:
                return HandlerResult(
                    success=False,
                    message="プレゼンテーションのIDを教えてほしいウル🐺",
                )

            client = GoogleSlidesClient()
            info = await client.get_presentation_info(presentation_id)
            content = await client.get_presentation_content(presentation_id)

            # Markdown形式で内容を表示
            markdown = client.to_markdown(content)
            message = f"📽️ **{info.get('title', 'プレゼンテーション')}**\n\n"
            message += f"スライド数: {info.get('slides_count', 0)}\n\n"
            message += f"{markdown}"

            return HandlerResult(
                success=True,
                message=message,
                data={
                    "title": info.get("title"),
                    "slides_count": info.get("slides_count"),
                    "content": content,
                },
            )

        except ImportError:
            return HandlerResult(
                success=False,
                message="プレゼンテーション機能が利用できないウル🐺",
            )
        except Exception as e:
            logger.error(f"[CapabilityBridge] Read presentation failed: {e}", exc_info=True)
            return HandlerResult(
                success=False,
                message="プレゼンテーションの読み込みに失敗したウル🐺",
            )

    async def _handle_create_presentation(
        self,
        room_id: str,
        account_id: str,
        sender_name: str,
        params: Dict[str, Any],
        **kwargs,
    ) -> HandlerResult:
        """
        プレゼンテーション作成ハンドラー

        Args:
            params: パラメータ
                - title: プレゼンテーション名
                - slides: スライド内容のリスト

        Returns:
            HandlerResult
        """
        try:
            from lib.capabilities.generation import GoogleSlidesClient

            title = params.get("title", "新規プレゼンテーション")
            slides = params.get("slides", [])

            client = GoogleSlidesClient()

            # プレゼンテーション作成
            result = await client.create_presentation(title=title)
            presentation_id = result["presentationId"]

            # スライドを追加
            for slide_data in slides:
                slide_title = slide_data.get("title", "")
                slide_body = slide_data.get("body", "")
                if slide_title or slide_body:
                    await client.add_slide(
                        presentation_id=presentation_id,
                        layout="TITLE_AND_BODY",
                        title=slide_title,
                        body=slide_body,
                    )

            presentation_url = f"https://docs.google.com/presentation/d/{presentation_id}"
            return HandlerResult(
                success=True,
                message=f"プレゼンテーションを作成したウル！🐺\n\n📽️ {presentation_url}",
                data={
                    "presentation_id": presentation_id,
                    "url": presentation_url,
                },
            )

        except ImportError:
            return HandlerResult(
                success=False,
                message="プレゼンテーション機能が利用できないウル🐺",
            )
        except Exception as e:
            logger.error(f"[CapabilityBridge] Create presentation failed: {e}", exc_info=True)
            return HandlerResult(
                success=False,
                message="プレゼンテーションの作成に失敗したウル🐺",
            )

    # =========================================================================
    # Meeting Transcription（Phase C MVP0）
    # =========================================================================

    async def _handle_meeting_transcription(
        self,
        room_id: str,
        account_id: str,
        sender_name: str,
        params: Dict[str, Any],
        **kwargs,
    ) -> "HandlerResult":
        """会議文字起こしハンドラー — MeetingBrainInterfaceに委譲"""
        from handlers.meeting_handler import handle_meeting_upload

        # Phase C MVP1: 議事録自動生成が有効な場合、LLM関数とフラグを注入
        extra_kwargs = {}
        if self.feature_flags.get("ENABLE_MEETING_MINUTES", False) and self.llm_caller:
            extra_kwargs["get_ai_response_func"] = self.llm_caller
            extra_kwargs["enable_minutes"] = True

        return await handle_meeting_upload(
            room_id=room_id,
            account_id=account_id,
            sender_name=sender_name,
            params=params,
            pool=self.pool,
            organization_id=self.org_id,
            **extra_kwargs,
            **kwargs,
        )

    # =========================================================================
    # Zoom Meeting Minutes（Phase C Case C）
    # =========================================================================

    async def _handle_zoom_meeting_minutes(
        self,
        room_id: str,
        account_id: str,
        sender_name: str,
        params: Dict[str, Any],
        **kwargs,
    ) -> "HandlerResult":
        """Zoom議事録ハンドラー — ZoomBrainInterfaceに委譲"""
        from handlers.zoom_meeting_handler import handle_zoom_meeting_minutes

        return await handle_zoom_meeting_minutes(
            room_id=room_id,
            account_id=account_id,
            sender_name=sender_name,
            params=params,
            pool=self.pool,
            organization_id=self.org_id,
            **kwargs,
        )

    # =========================================================================
    # Connection Query（v10.44.0）
    # =========================================================================

    async def _handle_connection_query(
        self,
        room_id: str,
        account_id: str,
        sender_name: str,
        params: Dict[str, Any],
        **kwargs,
    ) -> HandlerResult:
        """
        接続クエリハンドラー（DM可能な相手一覧）

        セキュリティ:
        - OWNER（CEO/Admin）のみ全リストを開示
        - 非OWNERには拒否メッセージ

        Args:
            room_id: ChatWorkルームID
            account_id: リクエスト者のアカウントID
            sender_name: 送信者名
            params: パラメータ（未使用）

        Returns:
            HandlerResult
        """
        try:
            from lib.connection_service import ConnectionService
            from lib.connection_logger import get_connection_logger
            from lib.chatwork import ChatworkClient

            # ChatWorkクライアント取得
            client = ChatworkClient()

            # サービス実行
            service = ConnectionService(
                chatwork_client=client,
                org_id=self.org_id,
            )
            result = service.query_connections(account_id)

            # 構造化ログ出力
            conn_logger = get_connection_logger()
            conn_logger.log_query(
                requester_user_id=account_id,
                allowed=result.allowed,
                result_count=result.total_count,
                organization_id=self.org_id,
                room_id=room_id,
            )

            data: Dict[str, Any] = {
                    "allowed": result.allowed,
                    "total_count": result.total_count,
                    "truncated": result.truncated,
                } if result.allowed else {}

            return HandlerResult(
                success=True,
                message=result.message,
                data=data,
            )

        except ImportError as e:
            logger.error(f"[CapabilityBridge] Connection query import error: {e}")
            return HandlerResult(
                success=False,
                message="接続クエリ機能が利用できないウル🐺",
            )
        except Exception as e:
            logger.error(f"[CapabilityBridge] Connection query failed: {e}", exc_info=True)
            return HandlerResult(
                success=False,
                message="接続情報の取得に失敗したウル🐺",
            )


# =============================================================================
# ファクトリ関数
# =============================================================================


def create_capability_bridge(
    pool,
    org_id: str,
    feature_flags: Optional[Dict[str, bool]] = None,
    llm_caller: Optional[Callable] = None,
) -> CapabilityBridge:
    """
    CapabilityBridgeを作成

    Args:
        pool: データベース接続プール
        org_id: 組織ID
        feature_flags: Feature Flagの設定
        llm_caller: LLM呼び出し関数

    Returns:
        CapabilityBridge インスタンス
    """
    return CapabilityBridge(
        pool=pool,
        org_id=org_id,
        feature_flags=feature_flags,
        llm_caller=llm_caller,
    )


# =============================================================================
# SYSTEM_CAPABILITIES 拡張
# =============================================================================


# 生成機能のCAPABILITIES定義（chatwork-webhook/handlers/__init__.pyに追加用）
GENERATION_CAPABILITIES = {
    "generate_document": {
        "name": "generate_document",
        "description": "文書（レポート、議事録、提案書等）を生成する",
        "keywords": [
            "資料作成", "ドキュメント", "レポート作成", "議事録作成",
            "提案書作成", "文書を作って", "資料を作って",
        ],
        "parameters": {
            "document_type": "文書タイプ (report/summary/proposal/minutes)",
            "topic": "トピック・内容",
            "outline": "アウトライン（オプション）",
            "output_format": "出力形式 (google_docs/markdown)",
        },
        "requires_confirmation": True,
        "confirmation_template": "「{topic}」について{document_type}を作成するウル？🐺",
    },
    "generate_image": {
        "name": "generate_image",
        "description": "画像を生成する",
        "keywords": [
            "画像作成", "イラスト作成", "図を作って", "画像を作って",
            "絵を描いて", "イメージ生成",
        ],
        "parameters": {
            "prompt": "画像の説明",
            "style": "スタイル（オプション）",
            "size": "サイズ (1024x1024/1792x1024/1024x1792)",
        },
        "requires_confirmation": True,
        "confirmation_template": "「{prompt}」の画像を作成するウル？🐺",
    },
    "generate_video": {
        "name": "generate_video",
        "description": "動画を生成する",
        "keywords": [
            "動画作成", "ビデオ作成", "動画を作って", "ムービー作成",
        ],
        "parameters": {
            "prompt": "動画の説明",
            "duration": "長さ（秒）",
        },
        "requires_confirmation": True,
        "confirmation_template": "「{prompt}」の動画（{duration}秒）を作成するウル？🐺",
    },
    "generate_feedback": {
        "name": "generate_feedback",
        "description": "CEOフィードバックを生成する",
        "keywords": [
            "フィードバック", "評価", "振り返り", "レビュー",
        ],
        "parameters": {
            "target_user_id": "対象ユーザーID（オプション）",
            "period": "期間 (week/month/quarter)",
        },
        "requires_confirmation": True,
        "confirmation_template": "{period}のフィードバックを生成するウル？🐺",
    },
    # G3: ディープリサーチ
    "deep_research": {
        "name": "deep_research",
        "description": "Web検索を使った深い調査を実行する",
        "keywords": [
            "調査", "調べて", "リサーチ", "分析", "調査して",
            "詳しく調べて", "競合調査", "市場調査", "技術調査",
        ],
        "parameters": {
            "query": "調査クエリ（何について調べるか）",
            "depth": "調査深度 (quick/standard/deep/comprehensive)",
            "research_type": "調査タイプ (general/competitor/market/technology)",
        },
        "requires_confirmation": True,
        "confirmation_template": "「{query}」について{depth}調査を実行するウル？🐺",
    },
    # G4: Google Sheets
    "read_spreadsheet": {
        "name": "read_spreadsheet",
        "description": "スプレッドシートを読み込む",
        "keywords": [
            "スプレッドシート読む", "シート読む", "エクセル読む",
            "表を見せて", "スプレッドシート開いて",
        ],
        "parameters": {
            "spreadsheet_id": "スプレッドシートID",
            "range": "読み込み範囲（例: Sheet1!A1:D10）",
        },
        "requires_confirmation": False,
        "confirmation_template": "",
    },
    "write_spreadsheet": {
        "name": "write_spreadsheet",
        "description": "スプレッドシートに書き込む",
        "keywords": [
            "スプレッドシート書く", "シート更新", "エクセル更新",
            "表に追加", "スプレッドシート更新",
        ],
        "parameters": {
            "spreadsheet_id": "スプレッドシートID",
            "range": "書き込み範囲",
            "data": "書き込みデータ（2次元配列）",
        },
        "requires_confirmation": True,
        "confirmation_template": "スプレッドシートに書き込むウル？🐺",
    },
    "create_spreadsheet": {
        "name": "create_spreadsheet",
        "description": "新しいスプレッドシートを作成する",
        "keywords": [
            "スプレッドシート作成", "シート作成", "エクセル作成",
            "新しい表を作って",
        ],
        "parameters": {
            "title": "スプレッドシート名",
            "sheets": "シート名のリスト（オプション）",
        },
        "requires_confirmation": True,
        "confirmation_template": "「{title}」というスプレッドシートを作成するウル？🐺",
    },
    # G4: Google Slides
    "read_presentation": {
        "name": "read_presentation",
        "description": "プレゼンテーションを読み込む",
        "keywords": [
            "スライド読む", "プレゼン読む", "スライド開いて",
            "プレゼンテーション見せて",
        ],
        "parameters": {
            "presentation_id": "プレゼンテーションID",
        },
        "requires_confirmation": False,
        "confirmation_template": "",
    },
    "create_presentation": {
        "name": "create_presentation",
        "description": "新しいプレゼンテーションを作成する",
        "keywords": [
            "スライド作成", "プレゼン作成", "プレゼンテーション作成",
            "スライドを作って",
        ],
        "parameters": {
            "title": "プレゼンテーション名",
            "slides": "スライド内容のリスト",
        },
        "requires_confirmation": True,
        "confirmation_template": "「{title}」というプレゼンテーションを作成するウル？🐺",
    },
}


# =============================================================================
# エクスポート
# =============================================================================


__all__ = [
    "CapabilityBridge",
    "create_capability_bridge",
    "GENERATION_CAPABILITIES",
    "DEFAULT_FEATURE_FLAGS",
]
