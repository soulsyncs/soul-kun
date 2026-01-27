# lib/capabilities/feedback/delivery.py
"""
Phase F1: CEOフィードバックシステム - 配信システム

このモジュールは、生成されたフィードバックの配信を管理します。

設計書: docs/20_next_generation_capabilities.md セクション8

配信チャネル:
    - ChatWork DM
    - スケジュール配信（デイリー、ウィークリー、マンスリー）
    - リアルタイムアラート
    - オンデマンド応答

Author: Claude Opus 4.5
Created: 2026-01-27
"""

from dataclasses import dataclass, field
from datetime import datetime, date, time, timedelta
import json
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection

from .constants import (
    DeliveryParameters,
    FeedbackIcons,
    FeedbackPriority,
    FeedbackStatus,
    FeedbackTemplates,
    FeedbackType,
    FEATURE_FLAG_DAILY_DIGEST,
    FEATURE_FLAG_WEEKLY_REVIEW,
    FEATURE_FLAG_MONTHLY_INSIGHT,
    FEATURE_FLAG_REALTIME_ALERT,
)
from .models import (
    CEOFeedback,
    DeliveryResult,
    FeedbackItem,
)


# =============================================================================
# 例外クラス
# =============================================================================


class DeliveryError(Exception):
    """配信エラー"""

    def __init__(
        self,
        message: str,
        delivery_channel: str = "",
        details: Optional[Dict[str, Any]] = None,
        original_exception: Optional[Exception] = None,
    ):
        super().__init__(message)
        self.message = message
        self.delivery_channel = delivery_channel
        self.details = details or {}
        self.original_exception = original_exception


class CooldownError(DeliveryError):
    """クールダウン中エラー"""
    pass


class DailyLimitError(DeliveryError):
    """1日の上限到達エラー"""
    pass


# =============================================================================
# 配信設定データクラス
# =============================================================================


@dataclass
class DeliveryConfig:
    """
    配信設定

    Attributes:
        chatwork_room_id: 配信先ChatWorkルームID
        enable_daily_digest: デイリーダイジェストを有効にするか
        enable_weekly_review: ウィークリーレビューを有効にするか
        enable_monthly_insight: マンスリーインサイトを有効にするか
        enable_realtime_alert: リアルタイムアラートを有効にするか
        daily_digest_hour: デイリーダイジェストの配信時刻（時）
        daily_digest_minute: デイリーダイジェストの配信時刻（分）
        alert_cooldown_minutes: アラート間隔（分）
        max_daily_alerts: 1日の最大アラート数
    """
    chatwork_room_id: Optional[int] = None
    enable_daily_digest: bool = True
    enable_weekly_review: bool = True
    enable_monthly_insight: bool = True
    enable_realtime_alert: bool = True
    daily_digest_hour: int = DeliveryParameters.DAILY_DIGEST_HOUR
    daily_digest_minute: int = DeliveryParameters.DAILY_DIGEST_MINUTE
    alert_cooldown_minutes: int = DeliveryParameters.ALERT_COOLDOWN_MINUTES
    max_daily_alerts: int = DeliveryParameters.MAX_DAILY_ALERTS


# =============================================================================
# FeedbackDelivery クラス
# =============================================================================


class FeedbackDelivery:
    """
    フィードバック配信システム

    生成されたフィードバックをChatWorkに配信する。

    使用例:
        >>> delivery = FeedbackDelivery(conn, org_id, chatwork_room_id)
        >>> result = await delivery.deliver(feedback)
        >>> print(f"配信結果: {result.status}")

    Attributes:
        conn: データベース接続
        org_id: 組織ID
        config: 配信設定
    """

    def __init__(
        self,
        conn: Connection,
        organization_id: UUID,
        config: Optional[DeliveryConfig] = None,
    ) -> None:
        """
        FeedbackDeliveryを初期化

        Args:
            conn: データベース接続
            organization_id: 組織ID
            config: 配信設定（オプション）
        """
        self._conn = conn
        self._org_id = organization_id
        self._config = config or DeliveryConfig()

        # ロガーの初期化
        try:
            from lib.logging import get_logger
            self._logger = get_logger("feedback.delivery")
        except ImportError:
            import logging
            self._logger = logging.getLogger("feedback.delivery")

    # =========================================================================
    # プロパティ
    # =========================================================================

    @property
    def conn(self) -> Connection:
        """データベース接続を取得"""
        return self._conn

    @property
    def organization_id(self) -> UUID:
        """組織IDを取得"""
        return self._org_id

    @property
    def config(self) -> DeliveryConfig:
        """配信設定を取得"""
        return self._config

    # =========================================================================
    # メイン配信メソッド
    # =========================================================================

    async def deliver(
        self,
        feedback: CEOFeedback,
        chatwork_room_id: Optional[int] = None,
    ) -> DeliveryResult:
        """
        フィードバックを配信

        Args:
            feedback: 配信するフィードバック
            chatwork_room_id: 配信先ルームID（オプション、指定しない場合は設定から取得）

        Returns:
            DeliveryResult: 配信結果

        Raises:
            DeliveryError: 配信に失敗した場合
            CooldownError: クールダウン中の場合
            DailyLimitError: 1日の上限に達した場合
        """
        room_id = chatwork_room_id or self._config.chatwork_room_id

        self._logger.info(
            "Starting feedback delivery",
            extra={
                "organization_id": str(self._org_id),
                "feedback_id": feedback.feedback_id,
                "feedback_type": feedback.feedback_type.value,
                "room_id": room_id,
            }
        )

        try:
            # 1. 配信可能かチェック
            await self._check_delivery_eligibility(feedback)

            # 2. メッセージをフォーマット
            message = self._format_feedback_message(feedback)

            # 3. ChatWorkに送信
            message_id = await self._send_to_chatwork(room_id, message)

            # 4. 配信ログを記録
            await self._record_delivery_log(feedback, room_id, message_id)

            # 5. フィードバックのステータスを更新
            feedback.status = FeedbackStatus.SENT
            feedback.delivered_at = datetime.now()

            result = DeliveryResult(
                feedback_id=feedback.feedback_id,
                success=True,
                delivered_at=datetime.now(),
                channel="chatwork",
                channel_target=str(room_id) if room_id else None,
                message_id=message_id,
            )

            self._logger.info(
                "Feedback delivered successfully",
                extra={
                    "organization_id": str(self._org_id),
                    "feedback_id": feedback.feedback_id,
                    "message_id": message_id,
                }
            )

            return result

        except (CooldownError, DailyLimitError):
            raise
        except Exception as e:
            self._logger.error(
                "Feedback delivery failed",
                extra={
                    "organization_id": str(self._org_id),
                    "feedback_id": feedback.feedback_id,
                    "error": str(e),
                }
            )
            return DeliveryResult(
                feedback_id=feedback.feedback_id,
                success=False,
                delivered_at=None,
                channel="chatwork",
                error_message=str(e),
            )

    # =========================================================================
    # 配信可否チェック
    # =========================================================================

    async def _check_delivery_eligibility(
        self,
        feedback: CEOFeedback,
    ) -> None:
        """
        配信可能かチェック

        Args:
            feedback: 配信するフィードバック

        Raises:
            CooldownError: クールダウン中の場合
            DailyLimitError: 1日の上限に達した場合
        """
        # リアルタイムアラートの場合は追加チェック
        if feedback.feedback_type == FeedbackType.REALTIME_ALERT:
            # クールダウンチェック
            await self._check_alert_cooldown()

            # 1日の上限チェック
            await self._check_daily_alert_limit()

    async def _check_alert_cooldown(self) -> None:
        """
        アラートのクールダウンをチェック

        Raises:
            CooldownError: クールダウン中の場合
        """
        try:
            cooldown_minutes = self._config.alert_cooldown_minutes
            cooldown_threshold = datetime.now() - timedelta(minutes=cooldown_minutes)

            result = self._conn.execute(text("""
                SELECT COUNT(*) FROM feedback_deliveries
                WHERE organization_id = :org_id
                  AND feedback_type = :feedback_type
                  AND delivered_at > :cooldown_threshold
            """), {
                "org_id": str(self._org_id),
                "feedback_type": FeedbackType.REALTIME_ALERT.value,
                "cooldown_threshold": cooldown_threshold,
            })

            row = result.fetchone()
            if row and row[0] > 0:
                raise CooldownError(
                    message=f"アラートは{cooldown_minutes}分間隔でのみ送信できます",
                    delivery_channel="chatwork",
                )

        except CooldownError:
            raise
        except Exception as e:
            # テーブルが存在しない場合などはスキップ
            self._logger.warning(
                "Failed to check alert cooldown",
                extra={"error": str(e)}
            )

    async def _check_daily_alert_limit(self) -> None:
        """
        1日のアラート上限をチェック

        Raises:
            DailyLimitError: 上限に達した場合
        """
        try:
            today_start = datetime.combine(date.today(), time.min)

            result = self._conn.execute(text("""
                SELECT COUNT(*) FROM feedback_deliveries
                WHERE organization_id = :org_id
                  AND feedback_type = :feedback_type
                  AND delivered_at >= :today_start
            """), {
                "org_id": str(self._org_id),
                "feedback_type": FeedbackType.REALTIME_ALERT.value,
                "today_start": today_start,
            })

            row = result.fetchone()
            if row and row[0] >= self._config.max_daily_alerts:
                raise DailyLimitError(
                    message=f"1日のアラート上限（{self._config.max_daily_alerts}件）に達しました",
                    delivery_channel="chatwork",
                )

        except DailyLimitError:
            raise
        except Exception as e:
            self._logger.warning(
                "Failed to check daily alert limit",
                extra={"error": str(e)}
            )

    # =========================================================================
    # メッセージフォーマット
    # =========================================================================

    def _format_feedback_message(
        self,
        feedback: CEOFeedback,
    ) -> str:
        """
        フィードバックをChatWorkメッセージにフォーマット

        Args:
            feedback: フィードバック

        Returns:
            str: フォーマットされたメッセージ
        """
        if feedback.feedback_type == FeedbackType.DAILY_DIGEST:
            return self._format_daily_digest(feedback)
        elif feedback.feedback_type == FeedbackType.WEEKLY_REVIEW:
            return self._format_weekly_review(feedback)
        elif feedback.feedback_type == FeedbackType.REALTIME_ALERT:
            return self._format_realtime_alert(feedback)
        elif feedback.feedback_type == FeedbackType.ON_DEMAND:
            return self._format_on_demand(feedback)
        else:
            return self._format_generic(feedback)

    def _format_daily_digest(self, feedback: CEOFeedback) -> str:
        """デイリーダイジェストをフォーマット"""
        today = date.today()
        weekday_names = ["月", "火", "水", "木", "金", "土", "日"]
        weekday = weekday_names[today.weekday()]

        lines = [
            FeedbackTemplates.DAILY_DIGEST_HEADER.format(
                date=today.strftime("%m/%d"),
                weekday=weekday,
                name=feedback.recipient_name,
            ),
            "",
        ]

        # サマリー
        if feedback.summary:
            lines.append(feedback.summary)
            lines.append("")

        # 注目すべき項目
        lines.append("【今日注目してほしいこと】")
        lines.append("")

        for item in feedback.items:
            icon = self._get_priority_icon(item.priority)
            lines.append(f"{icon} {item.title}")
            lines.append(f"   {item.description}")

            if item.recommendation:
                lines.append(f"   → {item.recommendation}")

            lines.append("")

        lines.append(FeedbackTemplates.FOOTER)

        return "\n".join(lines)

    def _format_weekly_review(self, feedback: CEOFeedback) -> str:
        """ウィークリーレビューをフォーマット"""
        today = date.today()
        week_start = today - timedelta(days=today.weekday() + 7)
        week_end = week_start + timedelta(days=6)

        lines = [
            FeedbackTemplates.WEEKLY_REVIEW_HEADER.format(
                week_start=week_start.strftime("%m/%d"),
                week_end=week_end.strftime("%m/%d"),
            ),
            "",
        ]

        # サマリー
        if feedback.summary:
            lines.append(feedback.summary)
            lines.append("")

        # 項目を分類して表示
        highlights = [i for i in feedback.items if i.category.value == "positive_change"]
        concerns = [i for i in feedback.items if i.category.value != "positive_change"]

        if highlights:
            lines.append("【今週のハイライト】")
            for item in highlights:
                lines.append(f"✨ {item.description}")
            lines.append("")

        if concerns:
            lines.append("【注意が必要な事項】")
            for item in concerns:
                icon = self._get_priority_icon(item.priority)
                lines.append(f"{icon} {item.title}: {item.description}")
            lines.append("")

        lines.append(FeedbackTemplates.FOOTER)

        return "\n".join(lines)

    def _format_realtime_alert(self, feedback: CEOFeedback) -> str:
        """リアルタイムアラートをフォーマット"""
        lines = [
            FeedbackTemplates.ALERT_HEADER.format(name=feedback.recipient_name),
            "",
        ]

        for item in feedback.items:
            lines.append("【検知した事実】")
            lines.append(item.description)
            lines.append("")

            if item.evidence:
                lines.append("【具体的な変化】")
                for ev in item.evidence:
                    lines.append(f"・{ev}")
                lines.append("")

            if item.hypothesis:
                lines.append("【仮説】")
                lines.append(f"（{item.hypothesis}）")
                lines.append("")

            if item.recommendation:
                lines.append("【提案】")
                lines.append(item.recommendation)
                lines.append("")

        lines.append(FeedbackTemplates.FOOTER)

        return "\n".join(lines)

    def _format_on_demand(self, feedback: CEOFeedback) -> str:
        """オンデマンド分析をフォーマット"""
        lines = []

        # サマリー
        if feedback.summary:
            lines.append(feedback.summary)
            lines.append("")

        # 項目
        for item in feedback.items:
            icon = self._get_priority_icon(item.priority)
            lines.append(f"{icon} {item.title}")
            lines.append(f"   {item.description}")

            if item.evidence:
                for ev in item.evidence:
                    lines.append(f"   ・{ev}")

            if item.recommendation:
                lines.append(f"   → {item.recommendation}")

            lines.append("")

        return "\n".join(lines)

    def _format_generic(self, feedback: CEOFeedback) -> str:
        """汎用フォーマット"""
        lines = []

        if feedback.summary:
            lines.append(feedback.summary)
            lines.append("")

        for item in feedback.items:
            lines.append(f"・{item.title}: {item.description}")

        return "\n".join(lines)

    def _get_priority_icon(self, priority: FeedbackPriority) -> str:
        """優先度に対応するアイコンを取得"""
        icons = {
            FeedbackPriority.CRITICAL: FeedbackIcons.PRIORITY_CRITICAL,
            FeedbackPriority.HIGH: FeedbackIcons.PRIORITY_HIGH,
            FeedbackPriority.MEDIUM: FeedbackIcons.PRIORITY_MEDIUM,
            FeedbackPriority.LOW: FeedbackIcons.PRIORITY_LOW,
        }
        return icons.get(priority, "")

    # =========================================================================
    # ChatWork送信
    # =========================================================================

    async def _send_to_chatwork(
        self,
        room_id: Optional[int],
        message: str,
    ) -> Optional[str]:
        """
        ChatWorkにメッセージを送信

        Args:
            room_id: ルームID
            message: メッセージ

        Returns:
            str: メッセージID（送信成功時）
        """
        if not room_id:
            self._logger.warning(
                "No room_id specified for ChatWork delivery",
                extra={"organization_id": str(self._org_id)}
            )
            return None

        try:
            # ChatWork APIを使用して送信
            from lib.chatwork import post_message

            message_id = post_message(room_id, message)
            return message_id

        except ImportError:
            self._logger.warning(
                "ChatWork module not available, skipping delivery"
            )
            return None
        except Exception as e:
            self._logger.error(
                "Failed to send message to ChatWork",
                extra={
                    "room_id": room_id,
                    "error": str(e),
                }
            )
            raise DeliveryError(
                message="ChatWorkへのメッセージ送信に失敗しました",
                delivery_channel="chatwork",
                details={"room_id": room_id},
                original_exception=e,
            )

    # =========================================================================
    # 配信ログ記録
    # =========================================================================

    async def _record_delivery_log(
        self,
        feedback: CEOFeedback,
        room_id: Optional[int],
        message_id: Optional[str],
    ) -> None:
        """
        配信ログをDBに記録

        Args:
            feedback: 配信したフィードバック
            room_id: 配信先ルームID
            message_id: ChatWorkメッセージID
        """
        try:
            self._conn.execute(text("""
                INSERT INTO feedback_deliveries (
                    id,
                    organization_id,
                    feedback_id,
                    feedback_type,
                    recipient_user_id,
                    channel,
                    channel_target,
                    message_id,
                    delivered_at,
                    created_at
                ) VALUES (
                    gen_random_uuid(),
                    :organization_id,
                    :feedback_id,
                    :feedback_type,
                    :recipient_user_id,
                    :channel,
                    :channel_target,
                    :message_id,
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP
                )
            """), {
                "organization_id": str(self._org_id),
                "feedback_id": feedback.feedback_id,
                "feedback_type": feedback.feedback_type.value,
                "recipient_user_id": feedback.recipient_user_id,
                "channel": "chatwork",
                "channel_target": str(room_id) if room_id else None,
                "message_id": message_id,
            })

        except Exception as e:
            # ログ記録の失敗は警告のみ（配信は成功とする）
            self._logger.warning(
                "Failed to record delivery log",
                extra={
                    "feedback_id": feedback.feedback_id,
                    "error": str(e),
                }
            )

    # =========================================================================
    # スケジュール配信ヘルパー
    # =========================================================================

    def should_deliver_daily_digest(self, now: Optional[datetime] = None) -> bool:
        """
        デイリーダイジェストを配信すべきかチェック

        Args:
            now: 現在時刻（テスト用）

        Returns:
            bool: 配信すべき場合True
        """
        if not self._config.enable_daily_digest:
            return False

        now = now or datetime.now()
        return (
            now.hour == self._config.daily_digest_hour and
            now.minute == self._config.daily_digest_minute
        )

    def should_deliver_weekly_review(self, now: Optional[datetime] = None) -> bool:
        """
        ウィークリーレビューを配信すべきかチェック

        Args:
            now: 現在時刻（テスト用）

        Returns:
            bool: 配信すべき場合True
        """
        if not self._config.enable_weekly_review:
            return False

        now = now or datetime.now()
        return (
            now.weekday() == DeliveryParameters.WEEKLY_REVIEW_DAY and
            now.hour == DeliveryParameters.WEEKLY_REVIEW_HOUR and
            now.minute == DeliveryParameters.WEEKLY_REVIEW_MINUTE
        )

    def should_deliver_monthly_insight(self, now: Optional[datetime] = None) -> bool:
        """
        マンスリーインサイトを配信すべきかチェック

        Args:
            now: 現在時刻（テスト用）

        Returns:
            bool: 配信すべき場合True
        """
        if not self._config.enable_monthly_insight:
            return False

        now = now or datetime.now()
        return (
            now.day == DeliveryParameters.MONTHLY_INSIGHT_DAY and
            now.hour == DeliveryParameters.MONTHLY_INSIGHT_HOUR and
            now.minute == DeliveryParameters.MONTHLY_INSIGHT_MINUTE
        )


# =============================================================================
# ファクトリー関数
# =============================================================================


def create_feedback_delivery(
    conn: Connection,
    organization_id: UUID,
    chatwork_room_id: Optional[int] = None,
    config: Optional[DeliveryConfig] = None,
) -> FeedbackDelivery:
    """
    FeedbackDeliveryを作成

    Args:
        conn: データベース接続
        organization_id: 組織ID
        chatwork_room_id: ChatWorkルームID（オプション）
        config: 配信設定（オプション）

    Returns:
        FeedbackDelivery: 配信システム
    """
    if config is None:
        config = DeliveryConfig(chatwork_room_id=chatwork_room_id)
    elif chatwork_room_id is not None:
        config.chatwork_room_id = chatwork_room_id

    return FeedbackDelivery(
        conn=conn,
        organization_id=organization_id,
        config=config,
    )
