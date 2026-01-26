# lib/brain/integration.py
"""
ソウルくんの脳 - 統合層（Integration Layer）

chatwork-webhookとの統合を担当する層です。
既存のコードからスムーズに脳アーキテクチャに移行するための
ブリッジ機能を提供します。

設計思想:
- Feature Flagによる段階的な有効化/無効化
- 既存のHANDLERSマッピングとの互換性維持
- バイパスルート検出と脳への統合
- フォールバック機構による安全なロールアウト

設計書: docs/13_brain_architecture.md セクション12
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from .core import SoulkunBrain
from .models import (
    BrainContext,
    BrainResponse,
    HandlerResult,
    StateType,
)
from .constants import (
    CANCEL_KEYWORDS,
    CONFIRMATION_THRESHOLD,
)

logger = logging.getLogger(__name__)


# =============================================================================
# 定数
# =============================================================================

# Feature Flag 環境変数名
FEATURE_FLAG_NAME: str = "USE_BRAIN_ARCHITECTURE"

# デフォルトのFeature Flag値
DEFAULT_FEATURE_FLAG: bool = False

# バイパスルートのパターン（検出用）
BYPASS_ROUTE_PATTERNS: List[str] = [
    "handle_pending_task_followup",      # pending taskのフォローアップ
    "has_active_goal_session",           # 目標設定セッション中の判定
    "match_local_command",               # ローカルコマンド判定
    "_get_pending_announcement",         # アナウンス確認中の判定
    "handle_goal_registration",          # 目標登録直接呼び出し
    "handle_announcement",               # アナウンス直接呼び出し
]

# 統合時の最大リトライ回数
INTEGRATION_MAX_RETRIES: int = 2

# 統合タイムアウト（秒）
INTEGRATION_TIMEOUT_SECONDS: float = 60.0

# フォールバックが必要なエラータイプ
FALLBACK_ERROR_TYPES: Tuple[type, ...] = (
    TimeoutError,
    asyncio.TimeoutError,
)


# =============================================================================
# 列挙型
# =============================================================================

class IntegrationMode(str, Enum):
    """統合モード"""

    DISABLED = "disabled"           # 脳アーキテクチャ無効（旧コード使用）
    ENABLED = "enabled"             # 脳アーキテクチャ有効
    SHADOW = "shadow"               # シャドウモード（両方実行、結果は旧コード）
    GRADUAL = "gradual"             # 段階的移行（一部ユーザーのみ脳使用）


class BypassType(str, Enum):
    """バイパスルートの種類"""

    GOAL_SESSION = "goal_session"              # 目標設定セッション
    ANNOUNCEMENT_PENDING = "announcement_pending"  # アナウンス確認待ち
    TASK_PENDING = "task_pending"              # タスク作成待ち
    LOCAL_COMMAND = "local_command"            # ローカルコマンド
    DIRECT_HANDLER = "direct_handler"          # ハンドラー直接呼び出し


# =============================================================================
# データクラス
# =============================================================================

@dataclass
class IntegrationResult:
    """
    統合処理の結果
    """
    success: bool
    message: str
    response: Optional[BrainResponse] = None
    used_brain: bool = False
    fallback_used: bool = False
    processing_time_ms: int = 0
    error: Optional[str] = None
    bypass_detected: Optional[BypassType] = None

    def to_chatwork_message(self) -> str:
        """ChatWork用のメッセージを取得"""
        if self.response:
            return self.response.message
        return self.message


@dataclass
class IntegrationConfig:
    """
    統合設定
    """
    mode: IntegrationMode = IntegrationMode.DISABLED
    fallback_enabled: bool = True
    shadow_logging: bool = False
    gradual_percentage: float = 0.0  # 0-100
    allowed_rooms: List[str] = field(default_factory=list)  # 空=全ルーム
    allowed_users: List[str] = field(default_factory=list)  # 空=全ユーザー
    bypass_detection_enabled: bool = True


@dataclass
class BypassDetectionResult:
    """
    バイパスルート検出結果
    """
    is_bypass: bool
    bypass_type: Optional[BypassType] = None
    session_id: Optional[str] = None
    should_redirect: bool = False
    reason: Optional[str] = None


# =============================================================================
# BrainIntegration クラス
# =============================================================================

class BrainIntegration:
    """
    ソウルくんの脳 - 統合層

    chatwork-webhookとSoulkunBrainの間のブリッジを提供します。
    Feature Flagによる段階的な有効化、フォールバック機構、
    バイパスルート検出と統合を行います。

    使用例（chatwork-webhook/main.py）:

        # 初期化
        integration = BrainIntegration(
            pool=pool,
            org_id=ORG_ID,
            handlers=HANDLERS,
            capabilities=SYSTEM_CAPABILITIES,
            get_ai_response_func=get_ai_response,
        )

        # メッセージ処理
        result = await integration.process_message(
            message=message_body,
            room_id=room_id,
            account_id=account_id,
            sender_name=sender_name,
            fallback_func=original_ai_commander,  # フォールバック関数
        )

        # 結果をChatWorkに送信
        if result.success:
            send_chatwork_message(room_id, result.to_chatwork_message())

    Attributes:
        brain: SoulkunBrainインスタンス
        config: 統合設定
        pool: データベース接続プール
        org_id: 組織ID
    """

    def __init__(
        self,
        pool=None,
        org_id: str = "",
        handlers: Optional[Dict[str, Callable]] = None,
        capabilities: Optional[Dict[str, Dict]] = None,
        get_ai_response_func: Optional[Callable] = None,
        firestore_db=None,
        config: Optional[IntegrationConfig] = None,
    ):
        """
        統合層を初期化

        Args:
            pool: データベース接続プール
            org_id: 組織ID
            handlers: HANDLERSマッピング（アクション名→関数）
            capabilities: SYSTEM_CAPABILITIES（機能カタログ）
            get_ai_response_func: AI応答生成関数
            firestore_db: Firestoreクライアント
            config: 統合設定（Noneの場合は環境変数から取得）
        """
        self.pool = pool
        self.org_id = org_id
        self.handlers = handlers or {}
        self.capabilities = capabilities or {}
        self.get_ai_response_func = get_ai_response_func
        self.firestore_db = firestore_db

        # 設定の初期化
        self.config = config or self._load_config_from_env()

        # SoulkunBrainの初期化（脳アーキテクチャが有効な場合のみ）
        self.brain: Optional[SoulkunBrain] = None
        if self.config.mode != IntegrationMode.DISABLED:
            self._initialize_brain()

        # 統計情報
        self._stats = {
            "total_requests": 0,
            "brain_requests": 0,
            "fallback_requests": 0,
            "bypass_detected": 0,
            "errors": 0,
        }

        logger.info(
            f"BrainIntegration initialized: "
            f"mode={self.config.mode.value}, "
            f"org_id={org_id}"
        )

    def _load_config_from_env(self) -> IntegrationConfig:
        """
        環境変数から設定を読み込み

        Returns:
            IntegrationConfig
        """
        # Feature Flagを読み込み
        feature_flag = os.environ.get(
            FEATURE_FLAG_NAME,
            str(DEFAULT_FEATURE_FLAG)
        ).lower()

        if feature_flag in ("true", "1", "yes", "enabled"):
            mode = IntegrationMode.ENABLED
        elif feature_flag in ("shadow",):
            mode = IntegrationMode.SHADOW
        elif feature_flag in ("gradual",):
            mode = IntegrationMode.GRADUAL
        else:
            mode = IntegrationMode.DISABLED

        # 段階的移行の割合
        gradual_percentage = float(
            os.environ.get("BRAIN_GRADUAL_PERCENTAGE", "0")
        )

        # フォールバック設定
        fallback_enabled = os.environ.get(
            "BRAIN_FALLBACK_ENABLED", "true"
        ).lower() in ("true", "1", "yes")

        # シャドウログ設定
        shadow_logging = os.environ.get(
            "BRAIN_SHADOW_LOGGING", "false"
        ).lower() in ("true", "1", "yes")

        # 許可ルーム（カンマ区切り）
        allowed_rooms_str = os.environ.get("BRAIN_ALLOWED_ROOMS", "")
        allowed_rooms = [
            r.strip() for r in allowed_rooms_str.split(",") if r.strip()
        ]

        # 許可ユーザー（カンマ区切り）
        allowed_users_str = os.environ.get("BRAIN_ALLOWED_USERS", "")
        allowed_users = [
            u.strip() for u in allowed_users_str.split(",") if u.strip()
        ]

        return IntegrationConfig(
            mode=mode,
            fallback_enabled=fallback_enabled,
            shadow_logging=shadow_logging,
            gradual_percentage=gradual_percentage,
            allowed_rooms=allowed_rooms,
            allowed_users=allowed_users,
            bypass_detection_enabled=True,
        )

    def _initialize_brain(self) -> None:
        """
        SoulkunBrainを初期化
        """
        try:
            self.brain = SoulkunBrain(
                pool=self.pool,
                org_id=self.org_id,
                handlers=self.handlers,
                capabilities=self.capabilities,
                get_ai_response_func=self.get_ai_response_func,
                firestore_db=self.firestore_db,
            )
            logger.info("SoulkunBrain initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize SoulkunBrain: {e}")
            self.brain = None
            # 脳の初期化に失敗した場合はDISABLEDモードに変更
            self.config.mode = IntegrationMode.DISABLED

    # =========================================================================
    # メインエントリーポイント
    # =========================================================================

    async def process_message(
        self,
        message: str,
        room_id: str,
        account_id: str,
        sender_name: str,
        fallback_func: Optional[Callable] = None,
        bypass_context: Optional[Dict[str, Any]] = None,
    ) -> IntegrationResult:
        """
        メッセージを処理

        脳アーキテクチャの有効/無効に応じて適切な処理を行います。

        Args:
            message: ユーザーのメッセージ
            room_id: ChatWorkルームID
            account_id: ユーザーのアカウントID
            sender_name: 送信者名
            fallback_func: フォールバック関数（旧アーキテクチャの処理）
            bypass_context: バイパスルート検出用のコンテキスト

        Returns:
            IntegrationResult: 処理結果
        """
        start_time = time.time()
        self._stats["total_requests"] += 1

        try:
            # モードに応じた処理
            if self.config.mode == IntegrationMode.DISABLED:
                return await self._process_fallback(
                    message, room_id, account_id, sender_name,
                    fallback_func, start_time
                )

            # 脳使用の可否をチェック
            if not self._should_use_brain(room_id, account_id):
                return await self._process_fallback(
                    message, room_id, account_id, sender_name,
                    fallback_func, start_time
                )

            # バイパスルート検出
            if self.config.bypass_detection_enabled and bypass_context:
                bypass_result = self._detect_bypass(bypass_context)
                if bypass_result.is_bypass and not bypass_result.should_redirect:
                    self._stats["bypass_detected"] += 1
                    # バイパスルートでも脳に通す（統合済み）
                    logger.debug(
                        f"Bypass detected but redirecting to brain: "
                        f"type={bypass_result.bypass_type}"
                    )

            # シャドウモードの場合
            if self.config.mode == IntegrationMode.SHADOW:
                return await self._process_shadow(
                    message, room_id, account_id, sender_name,
                    fallback_func, start_time
                )

            # 脳で処理
            return await self._process_with_brain(
                message, room_id, account_id, sender_name,
                fallback_func, start_time
            )

        except Exception as e:
            self._stats["errors"] += 1
            logger.error(f"Integration error: {e}")

            # フォールバック
            if self.config.fallback_enabled and fallback_func:
                return await self._process_fallback(
                    message, room_id, account_id, sender_name,
                    fallback_func, start_time, error=str(e)
                )

            return IntegrationResult(
                success=False,
                message="申し訳ありません、処理中にエラーが発生しましたウル",
                used_brain=False,
                fallback_used=False,
                processing_time_ms=int((time.time() - start_time) * 1000),
                error=str(e),
            )

    async def _process_with_brain(
        self,
        message: str,
        room_id: str,
        account_id: str,
        sender_name: str,
        fallback_func: Optional[Callable],
        start_time: float,
    ) -> IntegrationResult:
        """
        脳アーキテクチャで処理
        """
        if not self.brain:
            return await self._process_fallback(
                message, room_id, account_id, sender_name,
                fallback_func, start_time,
                error="Brain not initialized"
            )

        try:
            self._stats["brain_requests"] += 1

            # タイムアウト付きで脳の処理を実行
            response = await asyncio.wait_for(
                self.brain.process_message(
                    message=message,
                    room_id=room_id,
                    account_id=account_id,
                    sender_name=sender_name,
                ),
                timeout=INTEGRATION_TIMEOUT_SECONDS,
            )

            processing_time_ms = int((time.time() - start_time) * 1000)

            return IntegrationResult(
                success=response.success,
                message=response.message,
                response=response,
                used_brain=True,
                fallback_used=False,
                processing_time_ms=processing_time_ms,
            )

        except FALLBACK_ERROR_TYPES as e:
            logger.warning(f"Brain processing timeout, falling back: {e}")

            if self.config.fallback_enabled and fallback_func:
                return await self._process_fallback(
                    message, room_id, account_id, sender_name,
                    fallback_func, start_time,
                    error=f"Timeout: {e}"
                )

            return IntegrationResult(
                success=False,
                message="処理がタイムアウトしましたウル。もう一度お試しくださいウル",
                used_brain=True,
                fallback_used=False,
                processing_time_ms=int((time.time() - start_time) * 1000),
                error=str(e),
            )

        except Exception as e:
            logger.error(f"Brain processing error: {e}")

            if self.config.fallback_enabled and fallback_func:
                return await self._process_fallback(
                    message, room_id, account_id, sender_name,
                    fallback_func, start_time,
                    error=str(e)
                )

            return IntegrationResult(
                success=False,
                message="申し訳ありません、処理中にエラーが発生しましたウル",
                used_brain=True,
                fallback_used=False,
                processing_time_ms=int((time.time() - start_time) * 1000),
                error=str(e),
            )

    async def _process_fallback(
        self,
        message: str,
        room_id: str,
        account_id: str,
        sender_name: str,
        fallback_func: Optional[Callable],
        start_time: float,
        error: Optional[str] = None,
    ) -> IntegrationResult:
        """
        フォールバック処理（旧アーキテクチャ）
        """
        self._stats["fallback_requests"] += 1

        if not fallback_func:
            return IntegrationResult(
                success=False,
                message="フォールバック処理が設定されていませんウル",
                used_brain=False,
                fallback_used=False,
                processing_time_ms=int((time.time() - start_time) * 1000),
                error=error or "No fallback function provided",
            )

        try:
            # フォールバック関数を呼び出し
            result = await fallback_func(
                message, room_id, account_id, sender_name
            )

            processing_time_ms = int((time.time() - start_time) * 1000)

            # 結果を正規化
            if isinstance(result, str):
                return IntegrationResult(
                    success=True,
                    message=result,
                    used_brain=False,
                    fallback_used=True,
                    processing_time_ms=processing_time_ms,
                )
            elif isinstance(result, dict):
                return IntegrationResult(
                    success=result.get("success", True),
                    message=result.get("message", ""),
                    used_brain=False,
                    fallback_used=True,
                    processing_time_ms=processing_time_ms,
                )
            else:
                return IntegrationResult(
                    success=True,
                    message=str(result) if result else "",
                    used_brain=False,
                    fallback_used=True,
                    processing_time_ms=processing_time_ms,
                )

        except Exception as e:
            logger.error(f"Fallback processing error: {e}")
            return IntegrationResult(
                success=False,
                message="申し訳ありません、処理中にエラーが発生しましたウル",
                used_brain=False,
                fallback_used=True,
                processing_time_ms=int((time.time() - start_time) * 1000),
                error=str(e),
            )

    async def _process_shadow(
        self,
        message: str,
        room_id: str,
        account_id: str,
        sender_name: str,
        fallback_func: Optional[Callable],
        start_time: float,
    ) -> IntegrationResult:
        """
        シャドウモード処理（両方実行、結果は旧コード）
        """
        # 脳とフォールバックを並列実行
        brain_task = asyncio.create_task(
            self._process_with_brain(
                message, room_id, account_id, sender_name,
                None, start_time  # フォールバックなし
            )
        )
        fallback_task = asyncio.create_task(
            self._process_fallback(
                message, room_id, account_id, sender_name,
                fallback_func, start_time
            )
        )

        # 両方の結果を待つ
        brain_result, fallback_result = await asyncio.gather(
            brain_task, fallback_task, return_exceptions=True
        )

        # シャドウログ
        if self.config.shadow_logging:
            self._log_shadow_comparison(
                message, brain_result, fallback_result
            )

        # フォールバックの結果を返す
        if isinstance(fallback_result, IntegrationResult):
            return fallback_result
        else:
            # 例外の場合
            return IntegrationResult(
                success=False,
                message="申し訳ありません、処理中にエラーが発生しましたウル",
                used_brain=False,
                fallback_used=True,
                processing_time_ms=int((time.time() - start_time) * 1000),
                error=str(fallback_result),
            )

    def _log_shadow_comparison(
        self,
        message: str,
        brain_result: Any,
        fallback_result: Any,
    ) -> None:
        """
        シャドウモードの比較結果をログ

        v10.29.5: Codex指摘修正 - プライバシー保護のため、
        メッセージ本文ではなく文字数のみをログ出力する
        """
        brain_len = 0
        brain_status = "unknown"
        fallback_len = 0
        fallback_status = "unknown"

        if isinstance(brain_result, IntegrationResult):
            brain_len = len(brain_result.message)
            brain_status = "success" if brain_result.success else "failed"
        elif isinstance(brain_result, Exception):
            brain_status = "error"

        if isinstance(fallback_result, IntegrationResult):
            fallback_len = len(fallback_result.message)
            fallback_status = "success" if fallback_result.success else "failed"
        elif isinstance(fallback_result, Exception):
            fallback_status = "error"

        # プライバシー保護: 本文ではなく文字数のみ記録
        logger.info(
            "[SHADOW] input_len=%d brain_len=%d brain_status=%s "
            "fallback_len=%d fallback_status=%s",
            len(message), brain_len, brain_status, fallback_len, fallback_status
        )

    # =========================================================================
    # ヘルパーメソッド
    # =========================================================================

    def _should_use_brain(
        self,
        room_id: str,
        account_id: str,
    ) -> bool:
        """
        脳を使用すべきかどうかを判定

        Args:
            room_id: ルームID
            account_id: アカウントID

        Returns:
            脳を使用すべきか
        """
        # 脳が初期化されていない場合
        if not self.brain:
            return False

        # DISABLEDモードの場合
        if self.config.mode == IntegrationMode.DISABLED:
            return False

        # 許可ルームのチェック
        if self.config.allowed_rooms:
            if room_id not in self.config.allowed_rooms:
                return False

        # 許可ユーザーのチェック
        if self.config.allowed_users:
            if account_id not in self.config.allowed_users:
                return False

        # 段階的移行モードの場合
        if self.config.mode == IntegrationMode.GRADUAL:
            # v10.29.5: Codex指摘修正 - hash()はプロセス間で不安定なためsha256を使用
            # sha256は決定論的で、同じaccount_idは常に同じ結果を返す
            hash_digest = hashlib.sha256(account_id.encode("utf-8")).hexdigest()
            hash_value = int(hash_digest, 16) % 100
            if hash_value >= self.config.gradual_percentage:
                return False

        return True

    def _detect_bypass(
        self,
        context: Dict[str, Any],
    ) -> BypassDetectionResult:
        """
        バイパスルートを検出

        Args:
            context: 検出用コンテキスト

        Returns:
            BypassDetectionResult
        """
        # 目標設定セッション中
        if context.get("has_active_goal_session"):
            return BypassDetectionResult(
                is_bypass=True,
                bypass_type=BypassType.GOAL_SESSION,
                session_id=context.get("goal_session_id"),
                should_redirect=True,  # 脳に統合済み
                reason="Active goal setting session",
            )

        # アナウンス確認待ち
        if context.get("has_pending_announcement"):
            return BypassDetectionResult(
                is_bypass=True,
                bypass_type=BypassType.ANNOUNCEMENT_PENDING,
                session_id=context.get("announcement_id"),
                should_redirect=True,  # 脳に統合済み
                reason="Pending announcement confirmation",
            )

        # タスク作成待ち
        if context.get("has_pending_task"):
            return BypassDetectionResult(
                is_bypass=True,
                bypass_type=BypassType.TASK_PENDING,
                session_id=context.get("pending_task_id"),
                should_redirect=True,  # 脳に統合済み
                reason="Pending task creation",
            )

        # ローカルコマンド
        if context.get("is_local_command"):
            return BypassDetectionResult(
                is_bypass=True,
                bypass_type=BypassType.LOCAL_COMMAND,
                should_redirect=True,  # 脳に統合済み
                reason="Local command detected",
            )

        return BypassDetectionResult(is_bypass=False)

    # =========================================================================
    # 統計・状態管理
    # =========================================================================

    def get_stats(self) -> Dict[str, Any]:
        """
        統計情報を取得

        Returns:
            統計情報
        """
        return {
            **self._stats,
            "mode": self.config.mode.value,
            "brain_initialized": self.brain is not None,
            "fallback_enabled": self.config.fallback_enabled,
        }

    def reset_stats(self) -> None:
        """
        統計情報をリセット
        """
        self._stats = {
            "total_requests": 0,
            "brain_requests": 0,
            "fallback_requests": 0,
            "bypass_detected": 0,
            "errors": 0,
        }

    def is_brain_enabled(self) -> bool:
        """
        脳アーキテクチャが有効かどうか

        Returns:
            有効か
        """
        return (
            self.config.mode != IntegrationMode.DISABLED
            and self.brain is not None
        )

    def get_mode(self) -> IntegrationMode:
        """
        現在の統合モードを取得

        Returns:
            IntegrationMode
        """
        return self.config.mode

    def set_mode(self, mode: IntegrationMode) -> None:
        """
        統合モードを変更

        Args:
            mode: 新しいモード
        """
        old_mode = self.config.mode
        self.config.mode = mode

        # 有効化された場合は脳を初期化
        if old_mode == IntegrationMode.DISABLED and mode != IntegrationMode.DISABLED:
            if not self.brain:
                self._initialize_brain()

        logger.info(f"Integration mode changed: {old_mode.value} -> {mode.value}")

    # =========================================================================
    # ユーティリティ
    # =========================================================================

    def get_brain(self) -> Optional[SoulkunBrain]:
        """
        SoulkunBrainインスタンスを取得

        Returns:
            SoulkunBrain または None
        """
        return self.brain

    async def health_check(self) -> Dict[str, Any]:
        """
        ヘルスチェック

        Returns:
            ヘルスチェック結果
        """
        health = {
            "status": "healthy",
            "mode": self.config.mode.value,
            "brain_initialized": self.brain is not None,
            "stats": self.get_stats(),
        }

        # 脳の初期化チェック
        if self.config.mode != IntegrationMode.DISABLED and not self.brain:
            health["status"] = "degraded"
            health["issues"] = ["Brain not initialized despite mode being enabled"]

        return health


# =============================================================================
# ファクトリ関数
# =============================================================================

def create_integration(
    pool=None,
    org_id: str = "",
    handlers: Optional[Dict[str, Callable]] = None,
    capabilities: Optional[Dict[str, Dict]] = None,
    get_ai_response_func: Optional[Callable] = None,
    firestore_db=None,
    config: Optional[IntegrationConfig] = None,
) -> BrainIntegration:
    """
    BrainIntegrationインスタンスを作成

    Args:
        pool: データベース接続プール
        org_id: 組織ID
        handlers: HANDLERSマッピング
        capabilities: SYSTEM_CAPABILITIES
        get_ai_response_func: AI応答生成関数
        firestore_db: Firestoreクライアント
        config: 統合設定

    Returns:
        BrainIntegration
    """
    return BrainIntegration(
        pool=pool,
        org_id=org_id,
        handlers=handlers,
        capabilities=capabilities,
        get_ai_response_func=get_ai_response_func,
        firestore_db=firestore_db,
        config=config,
    )


def is_brain_enabled() -> bool:
    """
    環境変数から脳アーキテクチャが有効かを確認

    Returns:
        有効か
    """
    feature_flag = os.environ.get(
        FEATURE_FLAG_NAME,
        str(DEFAULT_FEATURE_FLAG)
    ).lower()
    return feature_flag in ("true", "1", "yes", "enabled", "shadow", "gradual")
