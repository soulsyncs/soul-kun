# lib/brain/alert_sender.py
"""
アラート通知 — 菊池さん個人DMへ送信

インフラ通知（Brain不使用）: エラー率、API障害、DB障害、
Guardian ブロック率、コスト警告、応答遅延。

レート制限: 同種アラート1時間に1回まで。
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# アラートタイプ
# =============================================================================

class AlertType(str, Enum):
    ERROR_RATE_HIGH = "error_rate_high"
    API_DOWN = "api_down"
    DB_ERROR = "db_error"
    GUARDIAN_BLOCK_SURGE = "guardian_block_surge"
    COST_WARNING = "cost_warning"
    RESPONSE_TIME_HIGH = "response_time_high"


# =============================================================================
# アラートテンプレート
# =============================================================================

_ALERT_TEMPLATES: Dict[AlertType, str] = {
    AlertType.ERROR_RATE_HIGH: "[info][title][alert] エラー率が{threshold}%超過[/title]現在のエラー率: {value:.1%}\n検知時刻: {time}[/info]",
    AlertType.API_DOWN: "[info][title][alert] AI API接続エラー[/title]OpenRouter API への接続に失敗しました。\n検知時刻: {time}[/info]",
    AlertType.DB_ERROR: "[info][title][alert] DB接続エラー[/title]Cloud SQL への接続に失敗しました。\n検知時刻: {time}[/info]",
    AlertType.GUARDIAN_BLOCK_SURGE: "[info][title][alert] Guardian ブロック率上昇[/title]現在のブロック率: {value:.1%}\n閾値: {threshold}%\n検知時刻: {time}[/info]",
    AlertType.COST_WARNING: "[info][title][alert] コスト警告[/title]本日の推定コスト: {value:,.0f}円\n閾値: {threshold:,.0f}円\n検知時刻: {time}[/info]",
    AlertType.RESPONSE_TIME_HIGH: "[info][title][alert] 応答遅延[/title]平均応答時間: {value:.0f}ms\n閾値: {threshold}ms\n検知時刻: {time}[/info]",
}

# レート制限: 1時間（秒）
_RATE_LIMIT_SECONDS = 3600


# =============================================================================
# AlertSender
# =============================================================================

class AlertSender:
    """
    アラートを菊池さんのChatWork DMに送信

    Usage:
        sender = AlertSender()
        sender.send(AlertType.ERROR_RATE_HIGH, value=0.08, threshold=5)
    """

    def __init__(
        self,
        chatwork_client=None,
        alert_room_id: Optional[str] = None,
    ):
        """
        Args:
            chatwork_client: ChatworkClient インスタンス（Noneなら自動生成）
            alert_room_id: 送信先ルームID（デフォルト: ALERT_ROOM_ID 環境変数）
        """
        self._client = chatwork_client
        # v11.2.0: CLAUDE.md §3-2 チェック項目16「ハードコード禁止」準拠
        # ルームIDは環境変数 ALERT_ROOM_ID から取得必須。デフォルト値（直書き）を廃止。
        # 未設定時は send() でスキップされる（下記 send() 内でチェック）。
        self._room_id = alert_room_id or os.environ.get("ALERT_ROOM_ID", "")

        # v11.2.0: P5 — レートリミットはメモリ管理（in-process）
        # Note: feedback_alert_cooldowns は organization_id NOT NULL のため
        # インフラアラート（org非依存）には使用不可。Cloud Run 最小インスタンス数=1
        # で運用することでマルチインスタンス問題を回避する。
        self._last_sent: Dict[AlertType, float] = {}

    def _get_client(self):
        """ChatworkClient を遅延初期化"""
        if self._client is None:
            from lib.chatwork import ChatworkClient
            self._client = ChatworkClient()
        return self._client

    def send(
        self,
        alert_type: AlertType,
        value: Any = None,
        threshold: Any = None,
    ) -> bool:
        """
        アラートを送信

        Args:
            alert_type: アラートの種類
            value: 現在の値
            threshold: 閾値

        Returns:
            送信成功したか（レート制限で抑制された場合はFalse）
        """
        # v11.2.0: ルームID未設定チェック（ALERT_ROOM_ID環境変数が必須）
        if not self._room_id:
            logger.error(
                "Alert %s cannot be sent: ALERT_ROOM_ID environment variable is not set. "
                "Please set ALERT_ROOM_ID to the destination ChatWork room ID.",
                alert_type.value,
            )
            return False

        # レートリミットチェック（in-memory）
        now = time.time()
        last = self._last_sent.get(alert_type, 0)
        if (now - last) < _RATE_LIMIT_SECONDS:
            logger.debug(
                "Alert %s suppressed by rate limit (last sent %ds ago)",
                alert_type.value,
                int(now - last),
            )
            return False

        # メッセージ生成
        template = _ALERT_TEMPLATES.get(alert_type, "[alert] {alert_type}")
        jst = timezone(timedelta(hours=9))
        time_str = datetime.now(jst).strftime("%Y-%m-%d %H:%M JST")

        message = template.format(
            value=value,
            threshold=threshold,
            time=time_str,
            alert_type=alert_type.value,
        )

        # 送信
        try:
            client = self._get_client()
            client.send_message(
                room_id=int(self._room_id),
                message=message,
            )
            self._last_sent[alert_type] = now
            logger.info("Alert sent: %s to room %s", alert_type.value, self._room_id)
            return True
        except Exception as e:
            logger.warning(
                "Failed to send alert %s: %s",
                alert_type.value,
                type(e).__name__,
            )
            return False

    def check_and_alert(self, health_status: Dict[str, Any]) -> int:
        """
        ヘルスステータスからアラートを自動判定・送信

        Args:
            health_status: LLMBrainMonitor.get_health_status() の戻り値

        Returns:
            送信されたアラート数
        """
        sent_count = 0
        status = health_status.get("status", "healthy")
        issues = health_status.get("issues", [])
        metrics = health_status.get("metrics", {})

        if status == "healthy":
            return 0

        for issue in issues:
            issue_lower = issue.lower()

            if "error rate critical" in issue_lower:
                if self.send(
                    AlertType.ERROR_RATE_HIGH,
                    value=metrics.get("error_rate", 0),
                    threshold=5,
                ):
                    sent_count += 1

            elif "response time critical" in issue_lower:
                if self.send(
                    AlertType.RESPONSE_TIME_HIGH,
                    value=metrics.get("avg_response_time_ms", 0),
                    threshold=10000,
                ):
                    sent_count += 1

            elif "guardian block rate" in issue_lower:
                if self.send(
                    AlertType.GUARDIAN_BLOCK_SURGE,
                    value=metrics.get("guardian_block_rate", 0),
                    threshold=20,
                ):
                    sent_count += 1

        return sent_count
