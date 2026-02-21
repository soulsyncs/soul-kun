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
    bridge = CapabilityBridge(pool=db_pool, org_id="5f98365f-e7c5-4f48-9918-7fe9aabae5df")

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
from typing import Any, Callable, Dict, List, Optional, Tuple

from lib.brain.models import HandlerResult
from lib.brain.capabilities import (
    handle_connection_query,
    handle_create_presentation,
    handle_create_spreadsheet,
    handle_deep_research,
    handle_document_generation,
    handle_feedback_generation,
    handle_google_meet_minutes,
    handle_image_generation,
    handle_meeting_transcription,
    handle_past_meeting_query,
    handle_read_presentation,
    handle_read_spreadsheet,
    handle_video_generation,
    handle_write_spreadsheet,
    handle_zoom_meeting_minutes,
)

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
    "ENABLE_ZOOM_MEETING_MINUTES": True,  # Phase C Case C: 有効化済み (2026-02-13)
    # Google Meet Minutes (Phase C MVP0 Google Meet対応)
    "ENABLE_GOOGLE_MEET_MINUTES": False,  # Phase C MVP0: 実装済み、OAuth Drive権限確認後に有効化

    # Past Meeting Query (機能②: 過去会議質問)
    "ENABLE_PAST_MEETING_QUERY": True,  # 機能②: 「先月の会議は？」への回答
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
        bridge = CapabilityBridge(pool=db_pool, org_id="5f98365f-e7c5-4f48-9918-7fe9aabae5df")

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

        logger.info(
            f"CapabilityBridge initialized for org_id={org_id}, "
            f"flags={self.feature_flags}"
        )

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
            logger.warning(f"[CapabilityBridge] Multimodal module not available: {type(e).__name__}")
            return message, None
        except Exception as e:
            logger.error(f"[CapabilityBridge] Multimodal preprocessing failed: {type(e).__name__}", exc_info=True)
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
                        f"{att.get('filename')}: {type(e).__name__}"
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

        # Google Meet Minutes (Phase C MVP0 Google Meet対応)
        if self.feature_flags.get("ENABLE_GOOGLE_MEET_MINUTES", False):
            handlers["google_meet_minutes"] = self._handle_google_meet_minutes

        # Past Meeting Query（機能②: 過去会議質問）
        if self.feature_flags.get("ENABLE_PAST_MEETING_QUERY", False):
            handlers["past_meeting_query"] = self._handle_past_meeting_query

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
        """文書生成ハンドラー — capabilities/generation.py に委譲"""
        return await handle_document_generation(
            pool=self.pool,
            org_id=self.org_id,
            room_id=room_id,
            account_id=account_id,
            sender_name=sender_name,
            params=params,
            **kwargs,
        )

    async def _handle_image_generation(
        self,
        room_id: str,
        account_id: str,
        sender_name: str,
        params: Dict[str, Any],
        **kwargs,
    ) -> HandlerResult:
        """画像生成ハンドラー — capabilities/generation.py に委譲

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
        return await handle_image_generation(
            pool=self.pool,
            org_id=self.org_id,
            room_id=room_id,
            account_id=account_id,
            sender_name=sender_name,
            params=params,
            **kwargs,
        )

    async def _handle_video_generation(
        self,
        room_id: str,
        account_id: str,
        sender_name: str,
        params: Dict[str, Any],
        **kwargs,
    ) -> HandlerResult:
        """動画生成ハンドラー — capabilities/generation.py に委譲"""
        return await handle_video_generation(
            pool=self.pool,
            org_id=self.org_id,
            room_id=room_id,
            account_id=account_id,
            sender_name=sender_name,
            params=params,
            **kwargs,
        )

    async def _handle_feedback_generation(
        self,
        room_id: str,
        account_id: str,
        sender_name: str,
        params: Dict[str, Any],
        **kwargs,
    ) -> HandlerResult:
        """CEOフィードバック生成ハンドラー — capabilities/feedback.py に委譲"""
        return await handle_feedback_generation(
            pool=self.pool,
            org_id=self.org_id,
            room_id=room_id,
            account_id=account_id,
            sender_name=sender_name,
            params=params,
            **kwargs,
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
        """ディープリサーチハンドラー — capabilities/generation.py に委譲"""
        return await handle_deep_research(
            pool=self.pool,
            org_id=self.org_id,
            room_id=room_id,
            account_id=account_id,
            sender_name=sender_name,
            params=params,
            **kwargs,
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
        """スプレッドシート読み込みハンドラー — capabilities/google_workspace.py に委譲"""
        return await handle_read_spreadsheet(
            pool=self.pool,
            org_id=self.org_id,
            room_id=room_id,
            account_id=account_id,
            sender_name=sender_name,
            params=params,
            **kwargs,
        )

    async def _handle_write_spreadsheet(
        self,
        room_id: str,
        account_id: str,
        sender_name: str,
        params: Dict[str, Any],
        **kwargs,
    ) -> HandlerResult:
        """スプレッドシート書き込みハンドラー — capabilities/google_workspace.py に委譲"""
        return await handle_write_spreadsheet(
            pool=self.pool,
            org_id=self.org_id,
            room_id=room_id,
            account_id=account_id,
            sender_name=sender_name,
            params=params,
            **kwargs,
        )

    async def _handle_create_spreadsheet(
        self,
        room_id: str,
        account_id: str,
        sender_name: str,
        params: Dict[str, Any],
        **kwargs,
    ) -> HandlerResult:
        """スプレッドシート作成ハンドラー — capabilities/google_workspace.py に委譲"""
        return await handle_create_spreadsheet(
            pool=self.pool,
            org_id=self.org_id,
            room_id=room_id,
            account_id=account_id,
            sender_name=sender_name,
            params=params,
            **kwargs,
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
        """プレゼンテーション読み込みハンドラー — capabilities/google_workspace.py に委譲"""
        return await handle_read_presentation(
            pool=self.pool,
            org_id=self.org_id,
            room_id=room_id,
            account_id=account_id,
            sender_name=sender_name,
            params=params,
            **kwargs,
        )

    async def _handle_create_presentation(
        self,
        room_id: str,
        account_id: str,
        sender_name: str,
        params: Dict[str, Any],
        **kwargs,
    ) -> HandlerResult:
        """プレゼンテーション作成ハンドラー — capabilities/google_workspace.py に委譲"""
        return await handle_create_presentation(
            pool=self.pool,
            org_id=self.org_id,
            room_id=room_id,
            account_id=account_id,
            sender_name=sender_name,
            params=params,
            **kwargs,
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
    ) -> HandlerResult:
        """会議文字起こしハンドラー — capabilities/meeting.py に委譲"""
        return await handle_meeting_transcription(
            pool=self.pool,
            org_id=self.org_id,
            room_id=room_id,
            account_id=account_id,
            sender_name=sender_name,
            params=params,
            feature_flags=self.feature_flags,
            llm_caller=self.llm_caller,
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
    ) -> HandlerResult:
        """Zoom議事録ハンドラー — capabilities/meeting.py に委譲"""
        return await handle_zoom_meeting_minutes(
            pool=self.pool,
            org_id=self.org_id,
            room_id=room_id,
            account_id=account_id,
            sender_name=sender_name,
            params=params,
            **kwargs,
        )

    # =========================================================================
    # Google Meet Minutes（Phase C MVP0 Google Meet対応）
    # =========================================================================

    async def _handle_google_meet_minutes(
        self,
        room_id: str,
        account_id: str,
        sender_name: str,
        params: Dict[str, Any],
        **kwargs,
    ) -> HandlerResult:
        """Google Meet議事録ハンドラー — capabilities/meeting.py に委譲"""
        return await handle_google_meet_minutes(
            pool=self.pool,
            org_id=self.org_id,
            room_id=room_id,
            account_id=account_id,
            sender_name=sender_name,
            params=params,
            llm_caller=self.llm_caller,
            **kwargs,
        )

    # =========================================================================
    # Past Meeting Query（機能②: 過去会議質問）
    # =========================================================================

    async def _handle_past_meeting_query(
        self,
        room_id: str,
        account_id: str,
        sender_name: str,
        params: Dict[str, Any],
        **kwargs,
    ) -> HandlerResult:
        """過去会議質問ハンドラー — capabilities/meeting.py に委譲"""
        return await handle_past_meeting_query(
            pool=self.pool,
            org_id=self.org_id,
            room_id=room_id,
            account_id=account_id,
            sender_name=sender_name,
            params=params,
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
        """接続クエリハンドラー — capabilities/connection.py に委譲"""
        return await handle_connection_query(
            pool=self.pool,
            org_id=self.org_id,
            room_id=room_id,
            account_id=account_id,
            sender_name=sender_name,
            params=params,
            **kwargs,
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
