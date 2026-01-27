"""
Phase 2F: 結果からの学習 - 結果追跡

設計書: docs/17_brain_completion_roadmap.md セクション Phase 2F

行動結果を追跡するクラス。
通知・提案などのアクションの結果を追跡し、暗黙のフィードバックとして記録する。
"""

import logging
from datetime import datetime
from typing import Any, Callable, Dict, Optional
from uuid import uuid4

from sqlalchemy.engine import Connection

from .constants import (
    EVENT_TYPE_ACTION_MAP,
    TRACKABLE_ACTIONS,
    EventType,
    OutcomeType,
)
from .models import OutcomeEvent
from .repository import OutcomeRepository


logger = logging.getLogger(__name__)


class OutcomeTracker:
    """行動結果追跡クラス

    主な責務:
    1. 通知送信後の結果追跡
    2. 提案の採用/無視の検出
    3. イベントの記録

    使用例:
        tracker = OutcomeTracker(organization_id, repository)

        # イベント記録
        event_id = await tracker.record_action(
            conn=conn,
            action="send_reminder",
            target_account_id="12345",
            target_room_id="67890",
            action_params={"task_id": "...", "message": "..."},
        )
    """

    def __init__(
        self,
        organization_id: str,
        repository: OutcomeRepository,
    ):
        """初期化

        Args:
            organization_id: 組織ID
            repository: リポジトリ
        """
        self.organization_id = organization_id
        self.repository = repository

    def is_trackable_action(self, action: str) -> bool:
        """追跡対象のアクションかどうか

        Args:
            action: アクション名

        Returns:
            追跡対象かどうか
        """
        return action in TRACKABLE_ACTIONS

    def record_action(
        self,
        conn: Connection,
        action: str,
        target_account_id: str,
        target_room_id: Optional[str] = None,
        action_params: Optional[Dict[str, Any]] = None,
        related_resource_type: Optional[str] = None,
        related_resource_id: Optional[str] = None,
        context_snapshot: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """アクションを記録

        Args:
            conn: DB接続
            action: アクション名
            target_account_id: 対象ユーザーID
            target_room_id: 対象ルームID
            action_params: アクションパラメータ
            related_resource_type: 関連リソースタイプ
            related_resource_id: 関連リソースID
            context_snapshot: コンテキストスナップショット

        Returns:
            イベントID（追跡対象外の場合はNone）
        """
        if not self.is_trackable_action(action):
            logger.debug(f"Action not trackable: {action}")
            return None

        # イベントタイプを決定
        event_type = EVENT_TYPE_ACTION_MAP.get(action, EventType.NOTIFICATION_SENT)

        # イベント詳細を構築
        now = datetime.now()
        event_details = {
            "action": action,
            "sent_hour": now.hour,
            "sent_minute": now.minute,
            "day_of_week": now.strftime("%A").lower(),
        }

        if action_params:
            # メッセージのプレビュー
            message = action_params.get("message", "")
            if message:
                event_details["message_preview"] = message[:200]

            # その他のパラメータ
            for key in ["subtype", "priority", "category"]:
                if key in action_params:
                    event_details[key] = action_params[key]

        # イベントオブジェクト作成
        event = OutcomeEvent(
            id=str(uuid4()),
            organization_id=self.organization_id,
            event_type=event_type.value if isinstance(event_type, EventType) else event_type,
            event_subtype=action_params.get("subtype") if action_params else None,
            event_timestamp=now,
            target_account_id=target_account_id,
            target_room_id=target_room_id,
            event_details=event_details,
            related_resource_type=related_resource_type,
            related_resource_id=related_resource_id,
            context_snapshot=context_snapshot,
        )

        try:
            event_id = self.repository.save_event(conn, event)
            logger.info(
                f"Outcome event recorded: {event_type} for {target_account_id}, "
                f"event_id={event_id}"
            )
            return event_id
        except Exception as e:
            logger.error(f"Failed to record outcome event: {e}")
            raise

    def record_notification(
        self,
        conn: Connection,
        notification_type: str,
        target_account_id: str,
        target_room_id: Optional[str] = None,
        message: Optional[str] = None,
        notification_id: Optional[str] = None,
    ) -> Optional[str]:
        """通知を記録

        Args:
            conn: DB接続
            notification_type: 通知タイプ
            target_account_id: 対象ユーザーID
            target_room_id: 対象ルームID
            message: メッセージ
            notification_id: 通知ID

        Returns:
            イベントID
        """
        return self.record_action(
            conn=conn,
            action="send_notification",
            target_account_id=target_account_id,
            target_room_id=target_room_id,
            action_params={
                "subtype": notification_type,
                "message": message,
            },
            related_resource_type="notification",
            related_resource_id=notification_id,
        )

    def record_goal_reminder(
        self,
        conn: Connection,
        target_account_id: str,
        goal_id: str,
        reminder_type: str,
        message: Optional[str] = None,
    ) -> Optional[str]:
        """目標リマインドを記録

        Args:
            conn: DB接続
            target_account_id: 対象ユーザーID
            goal_id: 目標ID
            reminder_type: リマインドタイプ
            message: メッセージ

        Returns:
            イベントID
        """
        return self.record_action(
            conn=conn,
            action="goal_reminder_sent",
            target_account_id=target_account_id,
            action_params={
                "subtype": reminder_type,
                "message": message,
            },
            related_resource_type="goal",
            related_resource_id=goal_id,
        )

    def record_task_reminder(
        self,
        conn: Connection,
        target_account_id: str,
        task_id: str,
        message: Optional[str] = None,
    ) -> Optional[str]:
        """タスクリマインドを記録

        Args:
            conn: DB接続
            target_account_id: 対象ユーザーID
            task_id: タスクID
            message: メッセージ

        Returns:
            イベントID
        """
        return self.record_action(
            conn=conn,
            action="task_reminder_sent",
            target_account_id=target_account_id,
            action_params={
                "message": message,
            },
            related_resource_type="task",
            related_resource_id=task_id,
        )

    def record_proactive_message(
        self,
        conn: Connection,
        target_account_id: str,
        target_room_id: Optional[str],
        trigger_type: str,
        message: Optional[str] = None,
    ) -> Optional[str]:
        """能動的メッセージを記録

        Args:
            conn: DB接続
            target_account_id: 対象ユーザーID
            target_room_id: 対象ルームID
            trigger_type: トリガータイプ
            message: メッセージ

        Returns:
            イベントID
        """
        return self.record_action(
            conn=conn,
            action="proactive_check_in",
            target_account_id=target_account_id,
            target_room_id=target_room_id,
            action_params={
                "subtype": trigger_type,
                "message": message,
            },
        )

    def update_outcome(
        self,
        conn: Connection,
        event_id: str,
        outcome_type: str,
        outcome_details: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """イベントの結果を更新

        Args:
            conn: DB接続
            event_id: イベントID
            outcome_type: 結果タイプ（OutcomeType値）
            outcome_details: 結果詳細

        Returns:
            更新成功かどうか
        """
        try:
            success = self.repository.update_outcome(
                conn=conn,
                event_id=event_id,
                outcome_type=outcome_type,
                outcome_details=outcome_details,
            )
            if success:
                logger.info(f"Outcome updated: event_id={event_id}, type={outcome_type}")
            return success
        except Exception as e:
            logger.error(f"Failed to update outcome: {e}")
            return False

    def get_event(
        self,
        conn: Connection,
        event_id: str,
    ) -> Optional[OutcomeEvent]:
        """イベントを取得

        Args:
            conn: DB接続
            event_id: イベントID

        Returns:
            イベント
        """
        return self.repository.find_event_by_id(conn, event_id)


def create_outcome_tracker(
    organization_id: str,
    repository: Optional[OutcomeRepository] = None,
) -> OutcomeTracker:
    """OutcomeTrackerのファクトリ関数

    Args:
        organization_id: 組織ID
        repository: リポジトリ（Noneの場合は新規作成）

    Returns:
        OutcomeTracker
    """
    if repository is None:
        repository = OutcomeRepository(organization_id)
    return OutcomeTracker(organization_id, repository)
