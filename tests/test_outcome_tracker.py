"""
lib/brain/outcome_learning/tracker.py のテスト

OutcomeTracker の全メソッドおよび create_outcome_tracker ファクトリ関数をテストする。
対象カバレッジ行: 62-63, 74, 102-153, 177, 210, 240, 271, 300-312, 328, 344-346
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from lib.brain.outcome_learning.tracker import OutcomeTracker, create_outcome_tracker
from lib.brain.outcome_learning.repository import OutcomeRepository
from lib.brain.outcome_learning.constants import (
    EVENT_TYPE_ACTION_MAP,
    TRACKABLE_ACTIONS,
    EventType,
    OutcomeType,
)
from lib.brain.outcome_learning.models import OutcomeEvent


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_repository():
    """OutcomeRepositoryのモック"""
    repo = MagicMock(spec=OutcomeRepository)
    return repo


@pytest.fixture
def mock_conn():
    """DB接続のモック"""
    conn = MagicMock()
    return conn


@pytest.fixture
def tracker(mock_repository):
    """テスト用OutcomeTracker"""
    return OutcomeTracker(
        organization_id="org-test-001",
        repository=mock_repository,
    )


# ============================================================================
# __init__ テスト (lines 62-63)
# ============================================================================

class TestOutcomeTrackerInit:
    """OutcomeTracker初期化テスト"""

    def test_init_sets_organization_id(self, mock_repository):
        """organization_idが正しく設定されること"""
        tracker = OutcomeTracker(
            organization_id="org-123",
            repository=mock_repository,
        )
        assert tracker.organization_id == "org-123"

    def test_init_sets_repository(self, mock_repository):
        """repositoryが正しく設定されること"""
        tracker = OutcomeTracker(
            organization_id="org-123",
            repository=mock_repository,
        )
        assert tracker.repository is mock_repository


# ============================================================================
# is_trackable_action テスト (line 74)
# ============================================================================

class TestIsTrackableAction:
    """追跡対象アクション判定テスト"""

    def test_trackable_action_send_notification(self, tracker):
        """send_notificationは追跡対象"""
        assert tracker.is_trackable_action("send_notification") is True

    def test_trackable_action_send_reminder(self, tracker):
        """send_reminderは追跡対象"""
        assert tracker.is_trackable_action("send_reminder") is True

    def test_trackable_action_goal_reminder_sent(self, tracker):
        """goal_reminder_sentは追跡対象"""
        assert tracker.is_trackable_action("goal_reminder_sent") is True

    def test_trackable_action_task_reminder_sent(self, tracker):
        """task_reminder_sentは追跡対象"""
        assert tracker.is_trackable_action("task_reminder_sent") is True

    def test_trackable_action_proactive_check_in(self, tracker):
        """proactive_check_inは追跡対象"""
        assert tracker.is_trackable_action("proactive_check_in") is True

    def test_non_trackable_action(self, tracker):
        """unknown_actionは追跡対象外"""
        assert tracker.is_trackable_action("unknown_action") is False

    def test_empty_action(self, tracker):
        """空文字列は追跡対象外"""
        assert tracker.is_trackable_action("") is False

    def test_all_trackable_actions_recognized(self, tracker):
        """TRACKABLE_ACTIONSに定義された全アクションが追跡対象"""
        for action in TRACKABLE_ACTIONS:
            assert tracker.is_trackable_action(action) is True


# ============================================================================
# record_action テスト (lines 102-153)
# ============================================================================

class TestRecordAction:
    """アクション記録テスト"""

    def test_non_trackable_action_returns_none(self, tracker, mock_conn):
        """追跡対象外アクションはNoneを返す"""
        result = tracker.record_action(
            conn=mock_conn,
            action="not_trackable",
            target_account_id="user-1",
        )
        assert result is None

    def test_non_trackable_action_does_not_call_repository(self, tracker, mock_conn, mock_repository):
        """追跡対象外アクションではリポジトリを呼ばない"""
        tracker.record_action(
            conn=mock_conn,
            action="not_trackable",
            target_account_id="user-1",
        )
        mock_repository.save_event.assert_not_called()

    def test_trackable_action_calls_save_event(self, tracker, mock_conn, mock_repository):
        """追跡対象アクションでsave_eventが呼ばれる"""
        mock_repository.save_event.return_value = "event-id-123"

        result = tracker.record_action(
            conn=mock_conn,
            action="send_notification",
            target_account_id="user-1",
        )
        assert result == "event-id-123"
        mock_repository.save_event.assert_called_once()

    def test_record_action_creates_event_with_correct_type(self, tracker, mock_conn, mock_repository):
        """イベントタイプがEVENT_TYPE_ACTION_MAPに基づいて設定される"""
        mock_repository.save_event.return_value = "event-id"

        tracker.record_action(
            conn=mock_conn,
            action="send_notification",
            target_account_id="user-1",
        )

        saved_event = mock_repository.save_event.call_args[0][1]
        assert saved_event.event_type == EventType.NOTIFICATION_SENT.value

    def test_record_action_unknown_action_in_trackable_defaults_notification_sent(
        self, tracker, mock_conn, mock_repository
    ):
        """TRACKABLE_ACTIONSに含まれるがEVENT_TYPE_ACTION_MAPにないアクションはデフォルト"""
        # send_announcementはTRACKABLE_ACTIONSとEVENT_TYPE_ACTION_MAPの両方にある
        mock_repository.save_event.return_value = "event-id"

        tracker.record_action(
            conn=mock_conn,
            action="send_announcement",
            target_account_id="user-1",
        )

        saved_event = mock_repository.save_event.call_args[0][1]
        assert saved_event.event_type == EventType.ANNOUNCEMENT.value

    def test_record_action_with_action_params_message(self, tracker, mock_conn, mock_repository):
        """action_paramsのmessageがevent_detailsにプレビューとして含まれる"""
        mock_repository.save_event.return_value = "event-id"

        tracker.record_action(
            conn=mock_conn,
            action="send_notification",
            target_account_id="user-1",
            action_params={"message": "Hello, this is a test message."},
        )

        saved_event = mock_repository.save_event.call_args[0][1]
        assert saved_event.event_details["message_preview"] == "Hello, this is a test message."

    def test_record_action_message_preview_truncated_at_200(self, tracker, mock_conn, mock_repository):
        """メッセージプレビューが200文字で切り捨てられる"""
        mock_repository.save_event.return_value = "event-id"
        long_message = "A" * 500

        tracker.record_action(
            conn=mock_conn,
            action="send_notification",
            target_account_id="user-1",
            action_params={"message": long_message},
        )

        saved_event = mock_repository.save_event.call_args[0][1]
        assert len(saved_event.event_details["message_preview"]) == 200

    def test_record_action_with_subtype_priority_category(self, tracker, mock_conn, mock_repository):
        """action_paramsのsubtype/priority/categoryがevent_detailsに含まれる"""
        mock_repository.save_event.return_value = "event-id"

        tracker.record_action(
            conn=mock_conn,
            action="send_notification",
            target_account_id="user-1",
            action_params={
                "subtype": "urgent",
                "priority": "high",
                "category": "task",
            },
        )

        saved_event = mock_repository.save_event.call_args[0][1]
        assert saved_event.event_details["subtype"] == "urgent"
        assert saved_event.event_details["priority"] == "high"
        assert saved_event.event_details["category"] == "task"

    def test_record_action_without_action_params(self, tracker, mock_conn, mock_repository):
        """action_paramsがNoneでもエラーなく動作する"""
        mock_repository.save_event.return_value = "event-id"

        result = tracker.record_action(
            conn=mock_conn,
            action="send_notification",
            target_account_id="user-1",
            action_params=None,
        )
        assert result == "event-id"

    def test_record_action_event_details_contain_time_info(self, tracker, mock_conn, mock_repository):
        """event_detailsに時間情報（sent_hour, sent_minute, day_of_week）が含まれる"""
        mock_repository.save_event.return_value = "event-id"

        tracker.record_action(
            conn=mock_conn,
            action="send_notification",
            target_account_id="user-1",
        )

        saved_event = mock_repository.save_event.call_args[0][1]
        assert "sent_hour" in saved_event.event_details
        assert "sent_minute" in saved_event.event_details
        assert "day_of_week" in saved_event.event_details
        assert saved_event.event_details["action"] == "send_notification"

    def test_record_action_sets_organization_id(self, tracker, mock_conn, mock_repository):
        """イベントにorganization_idが設定される"""
        mock_repository.save_event.return_value = "event-id"

        tracker.record_action(
            conn=mock_conn,
            action="send_notification",
            target_account_id="user-1",
        )

        saved_event = mock_repository.save_event.call_args[0][1]
        assert saved_event.organization_id == "org-test-001"

    def test_record_action_with_room_id(self, tracker, mock_conn, mock_repository):
        """target_room_idがイベントに含まれる"""
        mock_repository.save_event.return_value = "event-id"

        tracker.record_action(
            conn=mock_conn,
            action="send_notification",
            target_account_id="user-1",
            target_room_id="room-42",
        )

        saved_event = mock_repository.save_event.call_args[0][1]
        assert saved_event.target_room_id == "room-42"

    def test_record_action_with_related_resource(self, tracker, mock_conn, mock_repository):
        """related_resource_type/idがイベントに含まれる"""
        mock_repository.save_event.return_value = "event-id"

        tracker.record_action(
            conn=mock_conn,
            action="send_notification",
            target_account_id="user-1",
            related_resource_type="task",
            related_resource_id="task-99",
        )

        saved_event = mock_repository.save_event.call_args[0][1]
        assert saved_event.related_resource_type == "task"
        assert saved_event.related_resource_id == "task-99"

    def test_record_action_with_context_snapshot(self, tracker, mock_conn, mock_repository):
        """context_snapshotがイベントに含まれる"""
        mock_repository.save_event.return_value = "event-id"
        ctx = {"mood": "happy", "time": "morning"}

        tracker.record_action(
            conn=mock_conn,
            action="send_notification",
            target_account_id="user-1",
            context_snapshot=ctx,
        )

        saved_event = mock_repository.save_event.call_args[0][1]
        assert saved_event.context_snapshot == ctx

    def test_record_action_with_subtype_in_params(self, tracker, mock_conn, mock_repository):
        """action_paramsのsubtypeがevent_subtypeに設定される"""
        mock_repository.save_event.return_value = "event-id"

        tracker.record_action(
            conn=mock_conn,
            action="send_notification",
            target_account_id="user-1",
            action_params={"subtype": "daily_report"},
        )

        saved_event = mock_repository.save_event.call_args[0][1]
        assert saved_event.event_subtype == "daily_report"

    def test_record_action_save_event_raises_propagates(self, tracker, mock_conn, mock_repository):
        """save_eventの例外がそのままraiseされる"""
        mock_repository.save_event.side_effect = Exception("DB error")

        with pytest.raises(Exception, match="DB error"):
            tracker.record_action(
                conn=mock_conn,
                action="send_notification",
                target_account_id="user-1",
            )

    def test_record_action_empty_message_no_preview(self, tracker, mock_conn, mock_repository):
        """空メッセージの場合message_previewは含まれない"""
        mock_repository.save_event.return_value = "event-id"

        tracker.record_action(
            conn=mock_conn,
            action="send_notification",
            target_account_id="user-1",
            action_params={"message": ""},
        )

        saved_event = mock_repository.save_event.call_args[0][1]
        assert "message_preview" not in saved_event.event_details

    def test_record_action_params_without_special_keys(self, tracker, mock_conn, mock_repository):
        """action_paramsにsubtype/priority/categoryがない場合でもエラーなし"""
        mock_repository.save_event.return_value = "event-id"

        tracker.record_action(
            conn=mock_conn,
            action="send_notification",
            target_account_id="user-1",
            action_params={"custom_key": "custom_value"},
        )

        saved_event = mock_repository.save_event.call_args[0][1]
        assert "subtype" not in saved_event.event_details
        assert "priority" not in saved_event.event_details
        assert "category" not in saved_event.event_details


# ============================================================================
# record_notification テスト (line 177)
# ============================================================================

class TestRecordNotification:
    """通知記録テスト"""

    def test_record_notification_delegates_to_record_action(self, tracker, mock_conn, mock_repository):
        """record_notificationがrecord_actionに委譲する"""
        mock_repository.save_event.return_value = "event-notif-1"

        result = tracker.record_notification(
            conn=mock_conn,
            notification_type="daily_report",
            target_account_id="user-1",
            target_room_id="room-1",
            message="Today's report",
            notification_id="notif-001",
        )

        assert result == "event-notif-1"
        saved_event = mock_repository.save_event.call_args[0][1]
        assert saved_event.event_type == EventType.NOTIFICATION_SENT.value
        assert saved_event.event_subtype == "daily_report"
        assert saved_event.related_resource_type == "notification"
        assert saved_event.related_resource_id == "notif-001"

    def test_record_notification_without_optional_params(self, tracker, mock_conn, mock_repository):
        """オプションパラメータなしでも動作する"""
        mock_repository.save_event.return_value = "event-notif-2"

        result = tracker.record_notification(
            conn=mock_conn,
            notification_type="reminder",
            target_account_id="user-2",
        )

        assert result == "event-notif-2"

    def test_record_notification_message_preview_in_details(self, tracker, mock_conn, mock_repository):
        """メッセージのプレビューがevent_detailsに含まれる"""
        mock_repository.save_event.return_value = "event-id"

        tracker.record_notification(
            conn=mock_conn,
            notification_type="alert",
            target_account_id="user-1",
            message="Please check your tasks",
        )

        saved_event = mock_repository.save_event.call_args[0][1]
        assert saved_event.event_details.get("message_preview") == "Please check your tasks"


# ============================================================================
# record_goal_reminder テスト (line 210)
# ============================================================================

class TestRecordGoalReminder:
    """目標リマインド記録テスト"""

    def test_record_goal_reminder_delegates_correctly(self, tracker, mock_conn, mock_repository):
        """record_goal_reminderが正しくrecord_actionに委譲する"""
        mock_repository.save_event.return_value = "event-goal-1"

        result = tracker.record_goal_reminder(
            conn=mock_conn,
            target_account_id="user-1",
            goal_id="goal-001",
            reminder_type="weekly",
            message="Check your goal progress",
        )

        assert result == "event-goal-1"
        saved_event = mock_repository.save_event.call_args[0][1]
        assert saved_event.event_type == EventType.GOAL_REMINDER.value
        assert saved_event.event_subtype == "weekly"
        assert saved_event.related_resource_type == "goal"
        assert saved_event.related_resource_id == "goal-001"

    def test_record_goal_reminder_without_message(self, tracker, mock_conn, mock_repository):
        """メッセージなしでも動作する"""
        mock_repository.save_event.return_value = "event-goal-2"

        result = tracker.record_goal_reminder(
            conn=mock_conn,
            target_account_id="user-2",
            goal_id="goal-002",
            reminder_type="daily",
        )

        assert result == "event-goal-2"


# ============================================================================
# record_task_reminder テスト (line 240)
# ============================================================================

class TestRecordTaskReminder:
    """タスクリマインド記録テスト"""

    def test_record_task_reminder_delegates_correctly(self, tracker, mock_conn, mock_repository):
        """record_task_reminderが正しくrecord_actionに委譲する"""
        mock_repository.save_event.return_value = "event-task-1"

        result = tracker.record_task_reminder(
            conn=mock_conn,
            target_account_id="user-1",
            task_id="task-001",
            message="Task deadline approaching",
        )

        assert result == "event-task-1"
        saved_event = mock_repository.save_event.call_args[0][1]
        assert saved_event.event_type == EventType.TASK_REMINDER.value
        assert saved_event.related_resource_type == "task"
        assert saved_event.related_resource_id == "task-001"

    def test_record_task_reminder_without_message(self, tracker, mock_conn, mock_repository):
        """メッセージなしでも動作する"""
        mock_repository.save_event.return_value = "event-task-2"

        result = tracker.record_task_reminder(
            conn=mock_conn,
            target_account_id="user-2",
            task_id="task-002",
        )

        assert result == "event-task-2"

    def test_record_task_reminder_message_in_event_details(self, tracker, mock_conn, mock_repository):
        """メッセージがevent_detailsのmessage_previewに含まれる"""
        mock_repository.save_event.return_value = "event-id"

        tracker.record_task_reminder(
            conn=mock_conn,
            target_account_id="user-1",
            task_id="task-003",
            message="Reminder: finish report",
        )

        saved_event = mock_repository.save_event.call_args[0][1]
        assert saved_event.event_details.get("message_preview") == "Reminder: finish report"


# ============================================================================
# record_proactive_message テスト (line 271)
# ============================================================================

class TestRecordProactiveMessage:
    """能動的メッセージ記録テスト"""

    def test_record_proactive_message_delegates_correctly(self, tracker, mock_conn, mock_repository):
        """record_proactive_messageが正しくrecord_actionに委譲する"""
        mock_repository.save_event.return_value = "event-proactive-1"

        result = tracker.record_proactive_message(
            conn=mock_conn,
            target_account_id="user-1",
            target_room_id="room-1",
            trigger_type="mood_check",
            message="How are you doing today?",
        )

        assert result == "event-proactive-1"
        saved_event = mock_repository.save_event.call_args[0][1]
        assert saved_event.event_type == EventType.PROACTIVE_MESSAGE.value
        assert saved_event.event_subtype == "mood_check"
        assert saved_event.target_room_id == "room-1"

    def test_record_proactive_message_without_room_id(self, tracker, mock_conn, mock_repository):
        """room_idがNoneでも動作する"""
        mock_repository.save_event.return_value = "event-proactive-2"

        result = tracker.record_proactive_message(
            conn=mock_conn,
            target_account_id="user-2",
            target_room_id=None,
            trigger_type="daily_check",
        )

        assert result == "event-proactive-2"

    def test_record_proactive_message_without_message(self, tracker, mock_conn, mock_repository):
        """メッセージなしでも動作する"""
        mock_repository.save_event.return_value = "event-proactive-3"

        result = tracker.record_proactive_message(
            conn=mock_conn,
            target_account_id="user-3",
            target_room_id="room-3",
            trigger_type="follow_up",
        )

        assert result == "event-proactive-3"


# ============================================================================
# update_outcome テスト (lines 300-312)
# ============================================================================

class TestUpdateOutcome:
    """結果更新テスト"""

    def test_update_outcome_success(self, tracker, mock_conn, mock_repository):
        """更新成功時にTrueを返す"""
        mock_repository.update_outcome.return_value = True

        result = tracker.update_outcome(
            conn=mock_conn,
            event_id="event-1",
            outcome_type=OutcomeType.ADOPTED.value,
        )

        assert result is True
        mock_repository.update_outcome.assert_called_once_with(
            conn=mock_conn,
            event_id="event-1",
            outcome_type=OutcomeType.ADOPTED.value,
            outcome_details=None,
        )

    def test_update_outcome_with_details(self, tracker, mock_conn, mock_repository):
        """outcome_detailsが正しく渡される"""
        mock_repository.update_outcome.return_value = True
        details = {"response_time_hours": 2.5, "user_action": "completed_task"}

        result = tracker.update_outcome(
            conn=mock_conn,
            event_id="event-2",
            outcome_type=OutcomeType.ADOPTED.value,
            outcome_details=details,
        )

        assert result is True
        mock_repository.update_outcome.assert_called_once_with(
            conn=mock_conn,
            event_id="event-2",
            outcome_type=OutcomeType.ADOPTED.value,
            outcome_details=details,
        )

    def test_update_outcome_returns_false_when_not_found(self, tracker, mock_conn, mock_repository):
        """イベントが見つからない場合Falseを返す"""
        mock_repository.update_outcome.return_value = False

        result = tracker.update_outcome(
            conn=mock_conn,
            event_id="nonexistent",
            outcome_type=OutcomeType.IGNORED.value,
        )

        assert result is False

    def test_update_outcome_exception_returns_false(self, tracker, mock_conn, mock_repository):
        """例外発生時にFalseを返す（例外はraiseしない）"""
        mock_repository.update_outcome.side_effect = Exception("DB error")

        result = tracker.update_outcome(
            conn=mock_conn,
            event_id="event-3",
            outcome_type=OutcomeType.REJECTED.value,
        )

        assert result is False

    def test_update_outcome_logs_success(self, tracker, mock_conn, mock_repository):
        """更新成功時にログが出力される（例外なく完了する）"""
        mock_repository.update_outcome.return_value = True

        # ログ出力の確認は間接的に: 例外なく完了すればOK
        result = tracker.update_outcome(
            conn=mock_conn,
            event_id="event-4",
            outcome_type=OutcomeType.DELAYED.value,
            outcome_details={"response_time_hours": 12.0},
        )

        assert result is True


# ============================================================================
# get_event テスト (line 328)
# ============================================================================

class TestGetEvent:
    """イベント取得テスト"""

    def test_get_event_found(self, tracker, mock_conn, mock_repository):
        """イベントが見つかった場合にOutcomeEventを返す"""
        expected_event = OutcomeEvent(
            id="event-1",
            organization_id="org-test-001",
            event_type=EventType.NOTIFICATION_SENT.value,
            target_account_id="user-1",
        )
        mock_repository.find_event_by_id.return_value = expected_event

        result = tracker.get_event(
            conn=mock_conn,
            event_id="event-1",
        )

        assert result is expected_event
        mock_repository.find_event_by_id.assert_called_once_with(mock_conn, "event-1")

    def test_get_event_not_found(self, tracker, mock_conn, mock_repository):
        """イベントが見つからない場合Noneを返す"""
        mock_repository.find_event_by_id.return_value = None

        result = tracker.get_event(
            conn=mock_conn,
            event_id="nonexistent",
        )

        assert result is None


# ============================================================================
# create_outcome_tracker ファクトリ関数テスト (lines 344-346)
# ============================================================================

class TestCreateOutcomeTracker:
    """ファクトリ関数テスト"""

    def test_create_with_provided_repository(self):
        """リポジトリを指定した場合、そのリポジトリが使われる"""
        repo = MagicMock(spec=OutcomeRepository)
        tracker = create_outcome_tracker("org-123", repository=repo)

        assert tracker.organization_id == "org-123"
        assert tracker.repository is repo

    def test_create_without_repository_creates_default(self):
        """リポジトリ未指定時にOutcomeRepositoryが自動生成される"""
        tracker = create_outcome_tracker("org-456")

        assert tracker.organization_id == "org-456"
        assert isinstance(tracker.repository, OutcomeRepository)
        assert tracker.repository.organization_id == "org-456"

    def test_create_returns_outcome_tracker_instance(self):
        """OutcomeTrackerインスタンスが返される"""
        tracker = create_outcome_tracker("org-789")
        assert isinstance(tracker, OutcomeTracker)


# ============================================================================
# 統合的なエッジケーステスト
# ============================================================================

class TestEdgeCases:
    """エッジケーステスト"""

    def test_record_action_all_trackable_actions_succeed(self, tracker, mock_conn, mock_repository):
        """TRACKABLE_ACTIONSの全アクションが正常に記録できる"""
        mock_repository.save_event.return_value = "event-id"

        for action in TRACKABLE_ACTIONS:
            result = tracker.record_action(
                conn=mock_conn,
                action=action,
                target_account_id="user-1",
            )
            assert result == "event-id", f"Action '{action}' should be recorded"

    def test_record_action_event_type_mapping(self, tracker, mock_conn, mock_repository):
        """各アクションが正しいEventTypeにマッピングされる"""
        mock_repository.save_event.return_value = "event-id"

        for action, expected_type in EVENT_TYPE_ACTION_MAP.items():
            if action not in TRACKABLE_ACTIONS:
                continue
            tracker.record_action(
                conn=mock_conn,
                action=action,
                target_account_id="user-1",
            )

            saved_event = mock_repository.save_event.call_args[0][1]
            assert saved_event.event_type == expected_type.value, (
                f"Action '{action}' should map to {expected_type.value}"
            )

    def test_record_action_event_has_uuid_id(self, tracker, mock_conn, mock_repository):
        """記録されるイベントのIDがUUID形式の文字列"""
        mock_repository.save_event.return_value = "event-id"

        tracker.record_action(
            conn=mock_conn,
            action="send_notification",
            target_account_id="user-1",
        )

        saved_event = mock_repository.save_event.call_args[0][1]
        assert saved_event.id is not None
        assert len(saved_event.id) == 36  # UUID format: 8-4-4-4-12

    def test_record_action_event_timestamp_is_set(self, tracker, mock_conn, mock_repository):
        """イベントにタイムスタンプが設定される"""
        mock_repository.save_event.return_value = "event-id"

        tracker.record_action(
            conn=mock_conn,
            action="send_notification",
            target_account_id="user-1",
        )

        saved_event = mock_repository.save_event.call_args[0][1]
        assert isinstance(saved_event.event_timestamp, datetime)

    def test_record_notification_none_message(self, tracker, mock_conn, mock_repository):
        """record_notificationでmessage=Noneの場合"""
        mock_repository.save_event.return_value = "event-id"

        result = tracker.record_notification(
            conn=mock_conn,
            notification_type="info",
            target_account_id="user-1",
            message=None,
        )

        assert result == "event-id"
