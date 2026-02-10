# lib/brain/memory_authority_logger.py
"""
Memory Authority 観測モードロガー

v10.43.2: Cloud Logging対応（ローカルファイル保存廃止）

【役割】
P4 MemoryAuthorityがSOFT_CONFLICTを検出した全ケースをCloud Loggingに保存し、
将来の精度改善のためのデータを蓄積する。

【ログ内容】
- action: 実行しようとしたアクション
- detected_memory_reference: 検出された記憶参照
- conflict_reason: 矛盾理由
- user_response: ユーザーの応答（OK/修正）

【設計方針】
- Cloud Loggingに構造化ログとして出力
- 非同期で保存（実行速度に影響を与えない）
- 判定ロジックは変更しない（観測のみ）
"""

import asyncio
import logging
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    import google.cloud.logging
    from google.cloud.logging_v2 import Logger
    CLOUD_LOGGING_AVAILABLE = True
except ImportError:
    CLOUD_LOGGING_AVAILABLE = False
    Logger = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)


# =============================================================================
# ログデータ型定義
# =============================================================================


@dataclass
class SoftConflictLog:
    """
    SOFT_CONFLICT検出ログ

    Attributes:
        timestamp: 検出時刻（ISO 8601形式）
        action: 実行しようとしたアクション名
        detected_memory_reference: 検出された記憶の抜粋
        conflict_reason: 矛盾と判定された理由
        user_response: ユーザーの応答（"ok", "modify", None）
        room_id: ChatWorkルームID
        account_id: ユーザーアカウントID
        organization_id: 組織ID
        message_excerpt: 元メッセージの抜粋（先頭100文字）
        conflict_details: 詳細な矛盾情報
        confidence: 判定の確信度
    """
    timestamp: str
    action: str
    detected_memory_reference: str
    conflict_reason: str
    user_response: Optional[str] = None
    room_id: str = ""
    account_id: str = ""
    organization_id: str = ""
    message_excerpt: str = ""
    conflict_details: List[Dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0
    log_id: str = ""

    def __post_init__(self):
        if not self.log_id:
            # ユニークなログIDを生成
            self.log_id = f"sc_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return asdict(self)


# =============================================================================
# ロガークラス
# =============================================================================


class MemoryAuthorityLogger:
    """
    Memory Authority 観測モードロガー

    SOFT_CONFLICT検出をCloud Loggingに構造化ログとして出力する。
    """

    CLOUD_LOGGER_NAME = "memory_authority_soft_conflicts"

    def __init__(
        self,
        enabled: bool = True,
    ):
        """
        Args:
            enabled: ロギングが有効か（Feature Flag連携用）
        """
        self.enabled = enabled
        self._pending_logs: Dict[str, SoftConflictLog] = {}
        self._cloud_logger: Optional[Logger] = None
        self._client = None

        # Cloud Loggingクライアント初期化
        if self.enabled and CLOUD_LOGGING_AVAILABLE:
            try:
                self._client = google.cloud.logging.Client()
                self._cloud_logger = self._client.logger(self.CLOUD_LOGGER_NAME)
                logger.debug(
                    f"MemoryAuthorityLogger initialized with Cloud Logging: "
                    f"logger_name={self.CLOUD_LOGGER_NAME}"
                )
            except Exception as e:
                logger.warning(f"Failed to initialize Cloud Logging client: {type(e).__name__}")
                self._cloud_logger = None
        elif self.enabled and not CLOUD_LOGGING_AVAILABLE:
            logger.warning(
                "google-cloud-logging not available. "
                "Logs will only go to standard logging."
            )

        logger.debug(
            f"MemoryAuthorityLogger initialized: "
            f"enabled={self.enabled}, cloud_logging={self._cloud_logger is not None}"
        )

    def log_soft_conflict(
        self,
        action: str,
        detected_memory_reference: str,
        conflict_reason: str,
        room_id: str = "",
        account_id: str = "",
        organization_id: str = "",
        message_excerpt: str = "",
        conflict_details: Optional[List[Dict[str, Any]]] = None,
        confidence: float = 0.0,
    ) -> str:
        """
        SOFT_CONFLICT検出をログに記録（同期版）

        Args:
            action: 実行しようとしたアクション名
            detected_memory_reference: 検出された記憶の抜粋
            conflict_reason: 矛盾と判定された理由
            room_id: ChatWorkルームID
            account_id: ユーザーアカウントID
            organization_id: 組織ID
            message_excerpt: 元メッセージの抜粋
            conflict_details: 詳細な矛盾情報
            confidence: 判定の確信度

        Returns:
            str: ログID（後でuser_responseを更新するため）
        """
        if not self.enabled:
            return ""

        log_entry = SoftConflictLog(
            timestamp=datetime.now().isoformat(),
            action=action,
            detected_memory_reference=detected_memory_reference[:200],
            conflict_reason=conflict_reason,
            room_id=room_id,
            account_id=account_id,
            organization_id=organization_id,
            message_excerpt=message_excerpt[:100] if message_excerpt else "",
            conflict_details=conflict_details or [],
            confidence=confidence,
        )

        # ペンディングログに保存（user_response待ち）
        self._pending_logs[log_entry.log_id] = log_entry

        logger.info(
            f"[MemoryAuthorityLogger] SOFT_CONFLICT logged: "
            f"log_id={log_entry.log_id}, action={action}"
        )

        return log_entry.log_id

    async def log_soft_conflict_async(
        self,
        action: str,
        detected_memory_reference: str,
        conflict_reason: str,
        room_id: str = "",
        account_id: str = "",
        organization_id: str = "",
        message_excerpt: str = "",
        conflict_details: Optional[List[Dict[str, Any]]] = None,
        confidence: float = 0.0,
    ) -> str:
        """
        SOFT_CONFLICT検出をログに記録（非同期版）

        非同期で実行し、メイン処理をブロックしない。
        """
        if not self.enabled:
            return ""

        # 非同期でログ記録（メイン処理をブロックしない）
        loop = asyncio.get_event_loop()
        log_id = await loop.run_in_executor(
            None,
            lambda: self.log_soft_conflict(
                action=action,
                detected_memory_reference=detected_memory_reference,
                conflict_reason=conflict_reason,
                room_id=room_id,
                account_id=account_id,
                organization_id=organization_id,
                message_excerpt=message_excerpt,
                conflict_details=conflict_details,
                confidence=confidence,
            )
        )
        return log_id

    def update_user_response(
        self,
        log_id: str,
        user_response: str,
    ) -> bool:
        """
        ユーザーの応答を更新してCloud Loggingに出力

        Args:
            log_id: ログID
            user_response: ユーザーの応答（"ok", "modify", "cancel"）

        Returns:
            bool: 更新成功したか
        """
        if not self.enabled:
            return False

        if log_id not in self._pending_logs:
            logger.warning(f"Log ID not found in pending: {log_id}")
            return False

        log_entry = self._pending_logs.pop(log_id)
        log_entry.user_response = user_response

        # Cloud Loggingに出力
        try:
            self._write_to_cloud_logging(log_entry)
            logger.info(
                f"[MemoryAuthorityLogger] User response saved to Cloud Logging: "
                f"log_id={log_id}, response={user_response}"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to write to Cloud Logging: {type(e).__name__}")
            # 失敗したらペンディングに戻す
            self._pending_logs[log_id] = log_entry
            return False

    async def update_user_response_async(
        self,
        log_id: str,
        user_response: str,
    ) -> bool:
        """
        ユーザーの応答を非同期で更新
        """
        if not self.enabled:
            return False

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.update_user_response(log_id, user_response)
        )

    def flush_pending(self, default_response: str = "timeout") -> int:
        """
        ペンディングログを全てCloud Loggingに出力

        ユーザー応答がタイムアウトした場合等に使用。

        Args:
            default_response: デフォルトの応答

        Returns:
            int: 保存したログ数
        """
        if not self.enabled:
            return 0

        count = 0
        for log_id in list(self._pending_logs.keys()):
            if self.update_user_response(log_id, default_response):
                count += 1

        return count

    def _write_to_cloud_logging(self, log_entry: SoftConflictLog) -> None:
        """
        Cloud Loggingに構造化ログを出力

        Args:
            log_entry: ログエントリ
        """
        log_dict = log_entry.to_dict()

        if self._cloud_logger is not None:
            try:
                self._cloud_logger.log_struct(log_dict, severity="INFO")
            except Exception as e:
                logger.warning(f"Cloud Logging failed: {type(e).__name__}")
                # フォールバック: 標準ログに出力
                logger.info(f"[SOFT_CONFLICT_LOG] {log_dict}")
        else:
            # Cloud Logging利用不可の場合は標準ログに出力
            logger.info(f"[SOFT_CONFLICT_LOG] {log_dict}")

    def get_pending_count(self) -> int:
        """
        ペンディングログの件数を取得

        Returns:
            int: ペンディング件数
        """
        return len(self._pending_logs)


# =============================================================================
# シングルトンインスタンス & ファクトリー関数
# =============================================================================


_logger_instance: Optional[MemoryAuthorityLogger] = None


def get_memory_authority_logger(
    enabled: bool = True,
) -> MemoryAuthorityLogger:
    """
    MemoryAuthorityLoggerのシングルトンインスタンスを取得

    Args:
        enabled: ロギングが有効か（初回のみ有効）

    Returns:
        MemoryAuthorityLogger: ロガーインスタンス
    """
    global _logger_instance

    if _logger_instance is None:
        _logger_instance = MemoryAuthorityLogger(
            enabled=enabled,
        )

    return _logger_instance


def create_memory_authority_logger(
    enabled: bool = True,
) -> MemoryAuthorityLogger:
    """
    新しいMemoryAuthorityLoggerインスタンスを作成

    シングルトンを使わずに新しいインスタンスが必要な場合に使用。

    Args:
        enabled: ロギングが有効か

    Returns:
        MemoryAuthorityLogger: 新しいロガーインスタンス
    """
    return MemoryAuthorityLogger(
        enabled=enabled,
    )
