"""
接続クエリログ（Connection Query Logger）

Cloud Loggingに構造化ログとして出力。
lib/brain/memory_authority_logger.py のパターンを踏襲。

【10の鉄則準拠】
- #3: 監査ログを記録（全クエリを記録）
- #8: 機密情報をログに含めない
"""

import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Cloud Logging 利用可否
try:
    import google.cloud.logging
    CLOUD_LOGGING_AVAILABLE = True
except ImportError:
    CLOUD_LOGGING_AVAILABLE = False


# =============================================================================
# ログデータクラス
# =============================================================================

@dataclass
class ConnectionQueryLog:
    """
    接続クエリログ

    Attributes:
        timestamp: クエリ時刻（ISO 8601形式）
        event_type: "CONNECTION_QUERY"
        data_source: "chatwork_1on1"
        allowed: アクセス許可されたか
        requester_user_id: リクエスト者のアカウントID
        result_count: 結果件数（許可時のみ）
        organization_id: 組織ID
        room_id: クエリ元のルームID
    """
    timestamp: str
    event_type: str = "CONNECTION_QUERY"
    data_source: str = "chatwork_1on1"
    allowed: bool = False
    requester_user_id: str = ""
    result_count: int = 0
    organization_id: str = ""
    room_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """辞書に変換"""
        return asdict(self)


# =============================================================================
# ロガークラス
# =============================================================================

class ConnectionLogger:
    """
    接続クエリロガー

    使用例:
        logger = get_connection_logger()
        logger.log_query(
            requester_user_id="1728974",
            allowed=True,
            result_count=25,
            organization_id="org-uuid",
            room_id="123456",
        )
    """

    CLOUD_LOGGER_NAME = "connection_query_logs"

    def __init__(self, enabled: bool = True):
        """
        Args:
            enabled: ログ出力を有効にするか
        """
        self.enabled = enabled
        self._cloud_logger = None

        if self.enabled and CLOUD_LOGGING_AVAILABLE:
            try:
                client = google.cloud.logging.Client()
                self._cloud_logger = client.logger(self.CLOUD_LOGGER_NAME)
                logger.info(
                    f"[ConnectionLogger] Cloud Logging initialized: "
                    f"logger_name={self.CLOUD_LOGGER_NAME}"
                )
            except Exception as e:
                logger.warning(f"[ConnectionLogger] Failed to init Cloud Logging: {e}")

    def log_query(
        self,
        requester_user_id: str,
        allowed: bool,
        result_count: int = 0,
        organization_id: str = "",
        room_id: str = "",
    ) -> None:
        """
        接続クエリをログに記録

        Args:
            requester_user_id: リクエスト者のChatWorkアカウントID
            allowed: アクセスが許可されたか
            result_count: 結果件数（許可時のみ意味がある）
            organization_id: 組織ID
            room_id: クエリ元のルームID
        """
        if not self.enabled:
            return

        log_entry = ConnectionQueryLog(
            timestamp=datetime.now().isoformat(),
            allowed=allowed,
            requester_user_id=str(requester_user_id),
            result_count=result_count if allowed else 0,
            organization_id=organization_id,
            room_id=str(room_id),
        )

        log_dict = log_entry.to_dict()

        # Cloud Logging に出力
        if self._cloud_logger is not None:
            try:
                self._cloud_logger.log_struct(log_dict, severity="INFO")
            except Exception as e:
                logger.warning(f"[ConnectionLogger] Cloud Logging failed: {e}")
                # フォールバック: 標準ログに出力
                logger.info(f"[CONNECTION_QUERY_LOG] {log_dict}")
        else:
            # Cloud Logging 未初期化時は標準ログに出力
            logger.info(f"[CONNECTION_QUERY_LOG] {log_dict}")


# =============================================================================
# シングルトン
# =============================================================================

_logger_instance: Optional[ConnectionLogger] = None


def get_connection_logger(enabled: bool = True) -> ConnectionLogger:
    """
    ConnectionLogger のシングルトンインスタンスを取得

    Args:
        enabled: 初回呼び出し時のみ有効。ログ出力を有効にするか。

    Returns:
        ConnectionLogger インスタンス
    """
    global _logger_instance
    if _logger_instance is None:
        _logger_instance = ConnectionLogger(enabled=enabled)
    return _logger_instance
