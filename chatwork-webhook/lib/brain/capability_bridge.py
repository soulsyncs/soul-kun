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

    # Feedback (Phase F)
    "ENABLE_CEO_FEEDBACK": True,
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

            document_type = params.get("document_type", "report")
            topic = params.get("topic", "")
            outline = params.get("outline")
            output_format = params.get("output_format", "google_docs")

            if not topic:
                return HandlerResult(
                    success=False,
                    message="何について文書を作成すればいいか教えてほしいウル🐺",
                )

            # 文書生成器を初期化
            generator = DocumentGenerator(
                pool=self.pool,
                org_id=self.org_id,
                llm_caller=self.llm_caller,
            )

            # 文書を生成
            result = await generator.generate(
                document_type=document_type,
                topic=topic,
                outline=outline,
                output_format=output_format,
                user_id=account_id,
                room_id=room_id,
            )

            if result.success:
                message = f"文書を作成したウル！🐺\n\n"
                if result.url:
                    message += f"📄 {result.url}"
                return HandlerResult(
                    success=True,
                    message=message,
                    data={"document_url": result.url, "document_id": result.document_id},
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

            prompt = params.get("prompt", "")
            style = params.get("style")
            size = params.get("size", "1024x1024")

            if not prompt:
                return HandlerResult(
                    success=False,
                    message="どんな画像を作ればいいか教えてほしいウル🐺",
                )

            # 画像生成器を初期化
            generator = ImageGenerator(
                pool=self.pool,
                org_id=self.org_id,
            )

            # 画像を生成
            result = await generator.generate(
                prompt=prompt,
                style=style,
                size=size,
                user_id=account_id,
                room_id=room_id,
            )

            if result.success:
                message = f"画像を作成したウル！🐺\n\n"
                if result.url:
                    message += f"🖼️ {result.url}"
                return HandlerResult(
                    success=True,
                    message=message,
                    data={"image_url": result.url},
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

            prompt = params.get("prompt", "")
            duration = params.get("duration", 5)

            if not prompt:
                return HandlerResult(
                    success=False,
                    message="どんな動画を作ればいいか教えてほしいウル🐺",
                )

            # 動画生成器を初期化
            generator = VideoGenerator(
                pool=self.pool,
                org_id=self.org_id,
            )

            # 動画を生成
            result = await generator.generate(
                prompt=prompt,
                duration=duration,
                user_id=account_id,
                room_id=room_id,
            )

            if result.success:
                message = f"動画を作成したウル！🐺\n\n"
                if result.url:
                    message += f"🎬 {result.url}"
                return HandlerResult(
                    success=True,
                    message=message,
                    data={"video_url": result.url},
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

            target_user_id = params.get("target_user_id")
            period = params.get("period", "week")

            # フィードバックエンジンを初期化
            engine = CEOFeedbackEngine(
                pool=self.pool,
                org_id=self.org_id,
                llm_caller=self.llm_caller,
            )

            # フィードバックを生成
            result = await engine.generate_feedback(
                user_id=target_user_id or account_id,
                period=period,
                requester_id=account_id,
            )

            if result.success:
                return HandlerResult(
                    success=True,
                    message=result.feedback_text,
                    data={"feedback_id": result.feedback_id},
                )
            else:
                return HandlerResult(
                    success=False,
                    message=f"フィードバックの生成に失敗したウル🐺 {result.error_message}",
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
