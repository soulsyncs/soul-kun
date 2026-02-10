# tests/test_proactive_monitor.py
"""
能動的モニタリングのユニットテスト

Phase 2: Proactive Monitoring
- ProactiveMonitor の全パブリックメソッドをカバー
- 各トリガーチェッカーの正常系・異常系
- メッセージ生成・アクション実行・クールダウンロジック
"""

import random as random_module
import pytest
from unittest.mock import Mock, MagicMock, AsyncMock, patch
from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager

from lib.brain.proactive import (
    # Enums
    TriggerType,
    ProactiveMessageType,
    ActionPriority,
    # Dataclasses
    Trigger,
    ProactiveMessage,
    ProactiveAction,
    UserContext,
    CheckResult,
    # Main class
    ProactiveMonitor,
    # Factory
    create_proactive_monitor,
    # Constants
    GOAL_ABANDONED_DAYS,
    TASK_OVERLOAD_COUNT,
    EMOTION_DECLINE_DAYS,
    LONG_ABSENCE_DAYS,
    MESSAGE_COOLDOWN_HOURS,
    MESSAGE_TEMPLATES,
    TRIGGER_PRIORITY,
    ORGANIZATION_UUID_TO_SLUG,
    DEFAULT_CHATWORK_TASKS_ORG_ID,
)
from lib.brain.constants import JST


# =============================================================================
# Fixtures
# =============================================================================


SAMPLE_ORG_ID = "5f98365f-e7c5-4f48-9918-7fe9aabae5df"
SAMPLE_USER_ID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
SAMPLE_ACCOUNT_ID = "10909425"
SAMPLE_ROOM_ID = "123456789"


def _make_db_result(fetchone_value=None, fetchall_value=None):
    """
    Create a mock DB result object with synchronous fetchone/fetchall.

    The source code pattern is:
        result = await conn.execute(query, params)
        row = result.fetchone()  # synchronous!
    So conn.execute must be async (returns awaitable), but the result
    must have synchronous fetchone/fetchall.
    """
    result = Mock()
    result.fetchone = Mock(return_value=fetchone_value)
    result.fetchall = Mock(return_value=fetchall_value if fetchall_value is not None else [])
    return result


@pytest.fixture
def mock_pool():
    """Async database pool mock with context manager support.

    pool.connect() returns an async context manager that yields conn.
    conn.execute is an AsyncMock that returns a synchronous result object.
    """
    pool = MagicMock()

    conn = AsyncMock()
    conn.commit = AsyncMock()
    # Default: execute returns a result with fetchone=None, fetchall=[]
    conn.execute = AsyncMock(return_value=_make_db_result())

    @asynccontextmanager
    async def fake_connect():
        yield conn

    pool.connect = fake_connect
    pool._conn = conn  # expose for test assertions
    return pool


@pytest.fixture
def mock_send_func():
    """Async message-sending function mock."""
    return AsyncMock(return_value=True)


@pytest.fixture
def mock_brain():
    """Brain mock (CLAUDE.md rule 1b)."""
    brain = AsyncMock()
    brain_result = Mock()
    brain_result.should_send = True
    brain_result.message = "Brain generated message"
    brain_result.reason = None
    brain.generate_proactive_message = AsyncMock(return_value=brain_result)
    return brain


@pytest.fixture
def user_ctx():
    """Standard UserContext for testing."""
    return UserContext(
        user_id=SAMPLE_USER_ID,
        organization_id=SAMPLE_ORG_ID,
        chatwork_account_id=SAMPLE_ACCOUNT_ID,
        dm_room_id=SAMPLE_ROOM_ID,
        last_activity_at=datetime.now(JST) - timedelta(days=1),
    )


@pytest.fixture
def monitor(mock_pool, mock_send_func, mock_brain):
    """ProactiveMonitor with all dependencies mocked."""
    return ProactiveMonitor(
        pool=mock_pool,
        send_message_func=mock_send_func,
        dry_run=False,
        brain=mock_brain,
    )


@pytest.fixture
def monitor_dry_run(mock_pool, mock_send_func, mock_brain):
    """ProactiveMonitor in dry_run mode."""
    return ProactiveMonitor(
        pool=mock_pool,
        send_message_func=mock_send_func,
        dry_run=True,
        brain=mock_brain,
    )


@pytest.fixture
def monitor_no_brain(mock_pool, mock_send_func):
    """ProactiveMonitor without brain (fallback mode)."""
    return ProactiveMonitor(
        pool=mock_pool,
        send_message_func=mock_send_func,
        dry_run=False,
        brain=None,
    )


@pytest.fixture
def monitor_no_pool(mock_send_func, mock_brain):
    """ProactiveMonitor without database pool."""
    return ProactiveMonitor(
        pool=None,
        send_message_func=mock_send_func,
        dry_run=False,
        brain=mock_brain,
    )


# =============================================================================
# Enum tests
# =============================================================================


class TestEnums:
    """Enum value tests."""

    def test_trigger_type_values(self):
        assert TriggerType.GOAL_ABANDONED.value == "goal_abandoned"
        assert TriggerType.TASK_OVERLOAD.value == "task_overload"
        assert TriggerType.EMOTION_DECLINE.value == "emotion_decline"
        assert TriggerType.QUESTION_UNANSWERED.value == "question_unanswered"
        assert TriggerType.GOAL_ACHIEVED.value == "goal_achieved"
        assert TriggerType.TASK_COMPLETED_STREAK.value == "task_completed_streak"
        assert TriggerType.LONG_ABSENCE.value == "long_absence"

    def test_proactive_message_type_values(self):
        assert ProactiveMessageType.FOLLOW_UP.value == "follow_up"
        assert ProactiveMessageType.ENCOURAGEMENT.value == "encouragement"
        assert ProactiveMessageType.REMINDER.value == "reminder"
        assert ProactiveMessageType.CELEBRATION.value == "celebration"
        assert ProactiveMessageType.CHECK_IN.value == "check_in"

    def test_action_priority_values(self):
        assert ActionPriority.CRITICAL.value == "critical"
        assert ActionPriority.HIGH.value == "high"
        assert ActionPriority.MEDIUM.value == "medium"
        assert ActionPriority.LOW.value == "low"


# =============================================================================
# Dataclass tests
# =============================================================================


class TestTrigger:
    """Trigger dataclass tests."""

    def test_to_dict(self):
        trigger = Trigger(
            trigger_type=TriggerType.GOAL_ABANDONED,
            user_id=SAMPLE_USER_ID,
            organization_id=SAMPLE_ORG_ID,
            priority=ActionPriority.MEDIUM,
            details={"goal_name": "Test Goal", "days_since_update": 10},
        )
        d = trigger.to_dict()
        assert d["trigger_type"] == "goal_abandoned"
        assert d["user_id"] == SAMPLE_USER_ID
        assert d["organization_id"] == SAMPLE_ORG_ID
        assert d["priority"] == "medium"
        assert d["details"]["goal_name"] == "Test Goal"
        assert "detected_at" in d

    def test_frozen(self):
        trigger = Trigger(
            trigger_type=TriggerType.GOAL_ABANDONED,
            user_id=SAMPLE_USER_ID,
            organization_id=SAMPLE_ORG_ID,
            priority=ActionPriority.MEDIUM,
        )
        with pytest.raises(AttributeError):
            trigger.user_id = "changed"


class TestProactiveMessage:
    """ProactiveMessage dataclass tests."""

    def test_to_dict(self):
        trigger = Trigger(
            trigger_type=TriggerType.TASK_OVERLOAD,
            user_id=SAMPLE_USER_ID,
            organization_id=SAMPLE_ORG_ID,
            priority=ActionPriority.HIGH,
        )
        msg = ProactiveMessage(
            trigger=trigger,
            message_type=ProactiveMessageType.REMINDER,
            message="Test message",
            room_id=SAMPLE_ROOM_ID,
            account_id=SAMPLE_ACCOUNT_ID,
        )
        d = msg.to_dict()
        assert d["message_type"] == "reminder"
        assert d["message"] == "Test message"
        assert d["room_id"] == SAMPLE_ROOM_ID
        assert d["account_id"] == SAMPLE_ACCOUNT_ID
        assert d["trigger"]["trigger_type"] == "task_overload"

    def test_to_dict_scheduled_at_none(self):
        trigger = Trigger(
            trigger_type=TriggerType.GOAL_ACHIEVED,
            user_id=SAMPLE_USER_ID,
            organization_id=SAMPLE_ORG_ID,
            priority=ActionPriority.MEDIUM,
        )
        msg = ProactiveMessage(
            trigger=trigger,
            message_type=ProactiveMessageType.CELEBRATION,
            message="Congrats!",
        )
        d = msg.to_dict()
        assert d["scheduled_at"] is None

    def test_to_dict_scheduled_at_set(self):
        trigger = Trigger(
            trigger_type=TriggerType.GOAL_ACHIEVED,
            user_id=SAMPLE_USER_ID,
            organization_id=SAMPLE_ORG_ID,
            priority=ActionPriority.MEDIUM,
        )
        scheduled = datetime(2026, 2, 8, 10, 0, 0, tzinfo=JST)
        msg = ProactiveMessage(
            trigger=trigger,
            message_type=ProactiveMessageType.CELEBRATION,
            message="Congrats!",
            scheduled_at=scheduled,
        )
        d = msg.to_dict()
        assert d["scheduled_at"] is not None
        assert "2026-02-08" in d["scheduled_at"]


class TestProactiveAction:
    """ProactiveAction dataclass tests."""

    def test_to_dict_success(self):
        trigger = Trigger(
            trigger_type=TriggerType.EMOTION_DECLINE,
            user_id=SAMPLE_USER_ID,
            organization_id=SAMPLE_ORG_ID,
            priority=ActionPriority.CRITICAL,
        )
        msg = ProactiveMessage(
            trigger=trigger,
            message_type=ProactiveMessageType.CHECK_IN,
            message="How are you?",
        )
        action = ProactiveAction(message=msg, success=True)
        d = action.to_dict()
        assert d["success"] is True
        assert d["error_message"] is None
        assert "sent_at" in d

    def test_to_dict_failure(self):
        trigger = Trigger(
            trigger_type=TriggerType.EMOTION_DECLINE,
            user_id=SAMPLE_USER_ID,
            organization_id=SAMPLE_ORG_ID,
            priority=ActionPriority.CRITICAL,
        )
        msg = ProactiveMessage(
            trigger=trigger,
            message_type=ProactiveMessageType.CHECK_IN,
            message="",
        )
        action = ProactiveAction(
            message=msg,
            success=False,
            error_message="Send failed",
        )
        d = action.to_dict()
        assert d["success"] is False
        assert d["error_message"] == "Send failed"


class TestCheckResult:
    """CheckResult dataclass tests."""

    def test_default_values(self):
        result = CheckResult(user_id=SAMPLE_USER_ID)
        assert result.user_id == SAMPLE_USER_ID
        assert result.triggers_found == []
        assert result.actions_taken == []
        assert result.skipped_triggers == []
        assert result.checked_at is not None


# =============================================================================
# Helper method tests
# =============================================================================


class TestHelperMethods:
    """Tests for _get_chatwork_tasks_org_id, _get_chatwork_account_id_int, _is_valid_uuid."""

    def test_get_chatwork_tasks_org_id_known(self, monitor):
        result = monitor._get_chatwork_tasks_org_id(SAMPLE_ORG_ID)
        assert result == "org_soulsyncs"

    def test_get_chatwork_tasks_org_id_unknown(self, monitor):
        result = monitor._get_chatwork_tasks_org_id("unknown-uuid")
        assert result == DEFAULT_CHATWORK_TASKS_ORG_ID

    def test_get_chatwork_account_id_int_valid(self, monitor):
        assert monitor._get_chatwork_account_id_int("10909425") == 10909425

    def test_get_chatwork_account_id_int_none(self, monitor):
        assert monitor._get_chatwork_account_id_int(None) is None

    def test_get_chatwork_account_id_int_empty(self, monitor):
        assert monitor._get_chatwork_account_id_int("") is None

    def test_get_chatwork_account_id_int_invalid(self, monitor):
        assert monitor._get_chatwork_account_id_int("not_a_number") is None

    def test_is_valid_uuid_true(self, monitor):
        assert monitor._is_valid_uuid(SAMPLE_ORG_ID) is True

    def test_is_valid_uuid_false_empty(self, monitor):
        assert monitor._is_valid_uuid("") is False

    def test_is_valid_uuid_false_short(self, monitor):
        assert monitor._is_valid_uuid("short") is False

    def test_is_valid_uuid_false_invalid(self, monitor):
        assert monitor._is_valid_uuid("not-a-valid-uuid-string-at-all!") is False

    def test_is_valid_uuid_without_hyphens(self, monitor):
        # 32 hex chars without hyphens is also a valid UUID
        assert monitor._is_valid_uuid("5f98365fe7c54f4899187fe9aabae5df") is True


# =============================================================================
# _get_message_type tests
# =============================================================================


class TestGetMessageType:
    """Tests for _get_message_type mapping."""

    def test_goal_abandoned(self, monitor):
        assert monitor._get_message_type(TriggerType.GOAL_ABANDONED) == ProactiveMessageType.FOLLOW_UP

    def test_task_overload(self, monitor):
        assert monitor._get_message_type(TriggerType.TASK_OVERLOAD) == ProactiveMessageType.REMINDER

    def test_emotion_decline(self, monitor):
        assert monitor._get_message_type(TriggerType.EMOTION_DECLINE) == ProactiveMessageType.CHECK_IN

    def test_question_unanswered(self, monitor):
        assert monitor._get_message_type(TriggerType.QUESTION_UNANSWERED) == ProactiveMessageType.FOLLOW_UP

    def test_goal_achieved(self, monitor):
        assert monitor._get_message_type(TriggerType.GOAL_ACHIEVED) == ProactiveMessageType.CELEBRATION

    def test_task_completed_streak(self, monitor):
        assert monitor._get_message_type(TriggerType.TASK_COMPLETED_STREAK) == ProactiveMessageType.ENCOURAGEMENT

    def test_long_absence(self, monitor):
        assert monitor._get_message_type(TriggerType.LONG_ABSENCE) == ProactiveMessageType.CHECK_IN


# =============================================================================
# _generate_message tests (fallback template)
# =============================================================================


class TestGenerateMessage:
    """Tests for _generate_message fallback template generation."""

    def test_goal_abandoned_with_details(self, monitor):
        trigger = Trigger(
            trigger_type=TriggerType.GOAL_ABANDONED,
            user_id=SAMPLE_USER_ID,
            organization_id=SAMPLE_ORG_ID,
            priority=ActionPriority.MEDIUM,
            details={"goal_name": "Sales Target", "days": 10},
        )
        msg = monitor._generate_message(trigger)
        assert isinstance(msg, str)
        assert len(msg) > 0

    def test_task_overload_with_details(self, monitor):
        trigger = Trigger(
            trigger_type=TriggerType.TASK_OVERLOAD,
            user_id=SAMPLE_USER_ID,
            organization_id=SAMPLE_ORG_ID,
            priority=ActionPriority.HIGH,
            details={"count": 8, "overdue_count": 3},
        )
        msg = monitor._generate_message(trigger)
        assert isinstance(msg, str)
        assert len(msg) > 0

    def test_long_absence_with_days(self, monitor):
        trigger = Trigger(
            trigger_type=TriggerType.LONG_ABSENCE,
            user_id=SAMPLE_USER_ID,
            organization_id=SAMPLE_ORG_ID,
            priority=ActionPriority.MEDIUM,
            details={"days": 20},
        )
        msg = monitor._generate_message(trigger)
        assert isinstance(msg, str)
        assert len(msg) > 0

    def test_question_unanswered_with_details(self, monitor):
        """QUESTION_UNANSWERED has templates; verify they work."""
        trigger = Trigger(
            trigger_type=TriggerType.QUESTION_UNANSWERED,
            user_id=SAMPLE_USER_ID,
            organization_id=SAMPLE_ORG_ID,
            priority=ActionPriority.MEDIUM,
            details={"question_summary": "How to deploy?"},
        )
        msg = monitor._generate_message(trigger)
        assert isinstance(msg, str)
        assert len(msg) > 0

    @patch("random.choice")
    def test_message_uses_random_choice(self, mock_choice, monitor):
        """Verify random.choice is called with correct templates list.

        _generate_message does 'import random' inside the method, then
        calls random.choice(). We patch random.choice at the module level.
        """
        templates = MESSAGE_TEMPLATES[TriggerType.GOAL_ABANDONED]
        mock_choice.return_value = templates[0]

        trigger = Trigger(
            trigger_type=TriggerType.GOAL_ABANDONED,
            user_id=SAMPLE_USER_ID,
            organization_id=SAMPLE_ORG_ID,
            priority=ActionPriority.MEDIUM,
            details={},
        )
        msg = monitor._generate_message(trigger)
        mock_choice.assert_called_once_with(templates)
        assert msg == templates[0]

    def test_message_with_missing_placeholder_uses_first_template(self, monitor):
        """When random template has missing keys, falls back to first template."""
        # GOAL_ACHIEVED templates use {goal_name}; pass empty details
        trigger = Trigger(
            trigger_type=TriggerType.GOAL_ABANDONED,
            user_id=SAMPLE_USER_ID,
            organization_id=SAMPLE_ORG_ID,
            priority=ActionPriority.MEDIUM,
            details={},  # missing goal_name, days, etc.
        )
        # The first template has no placeholders, so fallback should work
        msg = monitor._generate_message(trigger)
        assert isinstance(msg, str)
        assert len(msg) > 0

    def test_emotion_decline_templates(self, monitor):
        """Emotion decline templates have no placeholders, always work."""
        trigger = Trigger(
            trigger_type=TriggerType.EMOTION_DECLINE,
            user_id=SAMPLE_USER_ID,
            organization_id=SAMPLE_ORG_ID,
            priority=ActionPriority.CRITICAL,
            details={},
        )
        msg = monitor._generate_message(trigger)
        assert isinstance(msg, str)
        assert len(msg) > 0

    def test_task_completed_streak_templates(self, monitor):
        trigger = Trigger(
            trigger_type=TriggerType.TASK_COMPLETED_STREAK,
            user_id=SAMPLE_USER_ID,
            organization_id=SAMPLE_ORG_ID,
            priority=ActionPriority.LOW,
            details={"count": 5},
        )
        msg = monitor._generate_message(trigger)
        assert isinstance(msg, str)
        assert len(msg) > 0


# =============================================================================
# _should_act tests
# =============================================================================


class TestShouldAct:
    """Tests for _should_act decision logic."""

    def test_act_when_dm_room_available(self, monitor, user_ctx):
        trigger = Trigger(
            trigger_type=TriggerType.GOAL_ABANDONED,
            user_id=SAMPLE_USER_ID,
            organization_id=SAMPLE_ORG_ID,
            priority=ActionPriority.MEDIUM,
        )
        assert monitor._should_act(trigger, user_ctx) is True

    def test_no_act_when_no_destination(self, monitor):
        ctx = UserContext(
            user_id=SAMPLE_USER_ID,
            organization_id=SAMPLE_ORG_ID,
            chatwork_account_id=None,
            dm_room_id=None,
        )
        trigger = Trigger(
            trigger_type=TriggerType.GOAL_ABANDONED,
            user_id=SAMPLE_USER_ID,
            organization_id=SAMPLE_ORG_ID,
            priority=ActionPriority.MEDIUM,
        )
        assert monitor._should_act(trigger, ctx) is False

    @patch("lib.brain.proactive.datetime")
    def test_low_priority_blocked_outside_business_hours(self, mock_dt, monitor, user_ctx):
        """LOW priority triggers only fire 9-18 JST."""
        mock_now = Mock()
        mock_now.hour = 22  # 10 PM
        mock_dt.now.return_value = mock_now
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        trigger = Trigger(
            trigger_type=TriggerType.TASK_COMPLETED_STREAK,
            user_id=SAMPLE_USER_ID,
            organization_id=SAMPLE_ORG_ID,
            priority=ActionPriority.LOW,
        )
        assert monitor._should_act(trigger, user_ctx) is False

    @patch("lib.brain.proactive.datetime")
    def test_low_priority_allowed_during_business_hours(self, mock_dt, monitor, user_ctx):
        """LOW priority triggers fire during 9-18 JST."""
        mock_now = Mock()
        mock_now.hour = 12  # noon
        mock_dt.now.return_value = mock_now
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        trigger = Trigger(
            trigger_type=TriggerType.TASK_COMPLETED_STREAK,
            user_id=SAMPLE_USER_ID,
            organization_id=SAMPLE_ORG_ID,
            priority=ActionPriority.LOW,
        )
        assert monitor._should_act(trigger, user_ctx) is True

    def test_critical_priority_always_acts(self, monitor, user_ctx):
        """CRITICAL priority should always act (regardless of time)."""
        trigger = Trigger(
            trigger_type=TriggerType.EMOTION_DECLINE,
            user_id=SAMPLE_USER_ID,
            organization_id=SAMPLE_ORG_ID,
            priority=ActionPriority.CRITICAL,
        )
        assert monitor._should_act(trigger, user_ctx) is True

    def test_act_with_only_account_id(self, monitor):
        """Should act if chatwork_account_id is available even without dm_room_id."""
        ctx = UserContext(
            user_id=SAMPLE_USER_ID,
            organization_id=SAMPLE_ORG_ID,
            chatwork_account_id=SAMPLE_ACCOUNT_ID,
            dm_room_id=None,
        )
        trigger = Trigger(
            trigger_type=TriggerType.GOAL_ABANDONED,
            user_id=SAMPLE_USER_ID,
            organization_id=SAMPLE_ORG_ID,
            priority=ActionPriority.MEDIUM,
        )
        assert monitor._should_act(trigger, ctx) is True


# =============================================================================
# _is_in_cooldown tests
# =============================================================================


class TestIsInCooldown:
    """Tests for _is_in_cooldown."""

    @pytest.mark.asyncio
    async def test_not_in_cooldown_when_no_pool(self, user_ctx):
        monitor = ProactiveMonitor(pool=None)
        result = await monitor._is_in_cooldown(user_ctx, TriggerType.GOAL_ABANDONED)
        assert result is False

    @pytest.mark.asyncio
    async def test_in_cooldown_when_recent_action_found(self, monitor, mock_pool, user_ctx):
        conn = mock_pool._conn
        conn.execute.return_value = _make_db_result(fetchone_value=Mock(id=1))

        result = await monitor._is_in_cooldown(user_ctx, TriggerType.GOAL_ABANDONED)
        assert result is True

    @pytest.mark.asyncio
    async def test_not_in_cooldown_when_no_recent_action(self, monitor, mock_pool, user_ctx):
        conn = mock_pool._conn
        conn.execute.return_value = _make_db_result(fetchone_value=None)

        result = await monitor._is_in_cooldown(user_ctx, TriggerType.GOAL_ABANDONED)
        assert result is False

    @pytest.mark.asyncio
    async def test_cooldown_db_error_returns_false(self, monitor, mock_pool, user_ctx):
        conn = mock_pool._conn
        conn.execute.side_effect = Exception("DB error")

        result = await monitor._is_in_cooldown(user_ctx, TriggerType.GOAL_ABANDONED)
        assert result is False


# =============================================================================
# Trigger checker tests: _check_goal_abandoned
# =============================================================================


class TestCheckGoalAbandoned:
    """Tests for _check_goal_abandoned."""

    @pytest.mark.asyncio
    async def test_returns_none_without_pool(self, monitor_no_pool, user_ctx):
        result = await monitor_no_pool._check_goal_abandoned(user_ctx)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_invalid_uuid(self, monitor):
        ctx = UserContext(
            user_id=SAMPLE_USER_ID,
            organization_id="not-a-uuid",
        )
        result = await monitor._check_goal_abandoned(ctx)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_trigger_when_goal_found(self, monitor, mock_pool, user_ctx):
        conn = mock_pool._conn
        row = Mock()
        row.id = "goal-123"
        row.title = "Sales Target Q1"
        row.created_at = datetime.now(JST) - timedelta(days=15)
        row.updated_at = datetime.now(JST) - timedelta(days=10)

        conn.execute.return_value = _make_db_result(fetchone_value=row)

        trigger = await monitor._check_goal_abandoned(user_ctx)

        assert trigger is not None
        assert trigger.trigger_type == TriggerType.GOAL_ABANDONED
        assert trigger.user_id == SAMPLE_USER_ID
        assert trigger.organization_id == SAMPLE_ORG_ID
        assert trigger.priority == ActionPriority.MEDIUM
        assert "goal_name" in trigger.details
        assert trigger.details["goal_name"] == "Sales Target Q1"

    @pytest.mark.asyncio
    async def test_returns_none_when_no_abandoned_goal(self, monitor, mock_pool, user_ctx):
        conn = mock_pool._conn
        conn.execute.return_value = _make_db_result(fetchone_value=None)

        trigger = await monitor._check_goal_abandoned(user_ctx)
        assert trigger is None

    @pytest.mark.asyncio
    async def test_db_error_returns_none(self, monitor, mock_pool, user_ctx):
        conn = mock_pool._conn
        conn.execute.side_effect = Exception("DB error")

        trigger = await monitor._check_goal_abandoned(user_ctx)
        assert trigger is None

    @pytest.mark.asyncio
    async def test_goal_title_truncated_to_50_chars(self, monitor, mock_pool, user_ctx):
        conn = mock_pool._conn
        long_title = "A" * 100
        row = Mock()
        row.id = "goal-123"
        row.title = long_title
        row.updated_at = datetime.now(JST) - timedelta(days=10)

        conn.execute.return_value = _make_db_result(fetchone_value=row)

        trigger = await monitor._check_goal_abandoned(user_ctx)
        assert trigger is not None
        assert len(trigger.details["goal_name"]) == 50

    @pytest.mark.asyncio
    async def test_goal_title_none_returns_empty_string(self, monitor, mock_pool, user_ctx):
        conn = mock_pool._conn
        row = Mock()
        row.id = "goal-123"
        row.title = None
        row.updated_at = datetime.now(JST) - timedelta(days=10)

        conn.execute.return_value = _make_db_result(fetchone_value=row)

        trigger = await monitor._check_goal_abandoned(user_ctx)
        assert trigger is not None
        assert trigger.details["goal_name"] == ""


# =============================================================================
# Trigger checker tests: _check_task_overload
# =============================================================================


class TestCheckTaskOverload:
    """Tests for _check_task_overload."""

    @pytest.mark.asyncio
    async def test_returns_none_without_pool(self, monitor_no_pool, user_ctx):
        result = await monitor_no_pool._check_task_overload(user_ctx)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_without_account_id(self, monitor):
        ctx = UserContext(
            user_id=SAMPLE_USER_ID,
            organization_id=SAMPLE_ORG_ID,
            chatwork_account_id=None,
        )
        result = await monitor._check_task_overload(ctx)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_invalid_account_id(self, monitor):
        ctx = UserContext(
            user_id=SAMPLE_USER_ID,
            organization_id=SAMPLE_ORG_ID,
            chatwork_account_id="abc",  # non-numeric
        )
        result = await monitor._check_task_overload(ctx)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_trigger_when_overloaded(self, monitor, mock_pool, user_ctx):
        conn = mock_pool._conn
        row = Mock()
        row.total_count = 7
        row.overdue_count = 2

        conn.execute.return_value = _make_db_result(fetchone_value=row)

        trigger = await monitor._check_task_overload(user_ctx)

        assert trigger is not None
        assert trigger.trigger_type == TriggerType.TASK_OVERLOAD
        assert trigger.priority == ActionPriority.HIGH
        assert trigger.details["count"] == 7
        assert trigger.details["overdue_count"] == 2

    @pytest.mark.asyncio
    async def test_returns_none_below_threshold(self, monitor, mock_pool, user_ctx):
        conn = mock_pool._conn
        row = Mock()
        row.total_count = 3  # below TASK_OVERLOAD_COUNT (5)
        row.overdue_count = 0

        conn.execute.return_value = _make_db_result(fetchone_value=row)

        trigger = await monitor._check_task_overload(user_ctx)
        assert trigger is None

    @pytest.mark.asyncio
    async def test_returns_trigger_at_exact_threshold(self, monitor, mock_pool, user_ctx):
        conn = mock_pool._conn
        row = Mock()
        row.total_count = TASK_OVERLOAD_COUNT  # exactly 5
        row.overdue_count = 0

        conn.execute.return_value = _make_db_result(fetchone_value=row)

        trigger = await monitor._check_task_overload(user_ctx)
        assert trigger is not None

    @pytest.mark.asyncio
    async def test_overdue_count_defaults_to_zero(self, monitor, mock_pool, user_ctx):
        conn = mock_pool._conn
        row = Mock()
        row.total_count = 6
        row.overdue_count = None  # NULL from DB

        conn.execute.return_value = _make_db_result(fetchone_value=row)

        trigger = await monitor._check_task_overload(user_ctx)
        assert trigger is not None
        assert trigger.details["overdue_count"] == 0

    @pytest.mark.asyncio
    async def test_db_error_returns_none(self, monitor, mock_pool, user_ctx):
        conn = mock_pool._conn
        conn.execute.side_effect = Exception("Connection lost")

        trigger = await monitor._check_task_overload(user_ctx)
        assert trigger is None


# =============================================================================
# Trigger checker tests: _check_emotion_decline
# =============================================================================


class TestCheckEmotionDecline:
    """Tests for _check_emotion_decline."""

    @pytest.mark.asyncio
    async def test_returns_none_without_pool(self, monitor_no_pool, user_ctx):
        result = await monitor_no_pool._check_emotion_decline(user_ctx)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_invalid_uuid(self, monitor):
        ctx = UserContext(
            user_id=SAMPLE_USER_ID,
            organization_id="not-valid",
        )
        result = await monitor._check_emotion_decline(ctx)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_trigger_when_negative_trend(self, monitor, mock_pool, user_ctx):
        conn = mock_pool._conn
        rows = [
            Mock(sentiment_score=-0.5, message_time=datetime.now(JST) - timedelta(hours=i))
            for i in range(5)
        ]

        conn.execute.return_value = _make_db_result(fetchall_value=rows)

        trigger = await monitor._check_emotion_decline(user_ctx)

        assert trigger is not None
        assert trigger.trigger_type == TriggerType.EMOTION_DECLINE
        assert trigger.priority == ActionPriority.CRITICAL
        assert trigger.details["avg_sentiment_score"] == -0.5
        assert trigger.details["sample_count"] == 5

    @pytest.mark.asyncio
    async def test_returns_none_when_positive(self, monitor, mock_pool, user_ctx):
        conn = mock_pool._conn
        rows = [
            Mock(sentiment_score=0.5, message_time=datetime.now(JST))
            for _ in range(5)
        ]

        conn.execute.return_value = _make_db_result(fetchall_value=rows)

        trigger = await monitor._check_emotion_decline(user_ctx)
        assert trigger is None

    @pytest.mark.asyncio
    async def test_returns_none_with_fewer_than_3_samples(self, monitor, mock_pool, user_ctx):
        conn = mock_pool._conn
        rows = [
            Mock(sentiment_score=-0.8, message_time=datetime.now(JST)),
            Mock(sentiment_score=-0.9, message_time=datetime.now(JST)),
        ]

        conn.execute.return_value = _make_db_result(fetchall_value=rows)

        trigger = await monitor._check_emotion_decline(user_ctx)
        assert trigger is None

    @pytest.mark.asyncio
    async def test_borderline_score_not_triggered(self, monitor, mock_pool, user_ctx):
        """Average of -0.3 exactly should NOT trigger (needs to be < -0.3)."""
        conn = mock_pool._conn
        rows = [
            Mock(sentiment_score=-0.3, message_time=datetime.now(JST))
            for _ in range(4)
        ]

        conn.execute.return_value = _make_db_result(fetchall_value=rows)

        trigger = await monitor._check_emotion_decline(user_ctx)
        assert trigger is None

    @pytest.mark.asyncio
    async def test_db_error_returns_none(self, monitor, mock_pool, user_ctx):
        conn = mock_pool._conn
        conn.execute.side_effect = Exception("DB error")

        trigger = await monitor._check_emotion_decline(user_ctx)
        assert trigger is None


# =============================================================================
# Trigger checker tests: _check_question_unanswered
# =============================================================================


class TestCheckQuestionUnanswered:
    """Tests for _check_question_unanswered (currently unimplemented)."""

    @pytest.mark.asyncio
    async def test_always_returns_none(self, monitor, user_ctx):
        result = await monitor._check_question_unanswered(user_ctx)
        assert result is None


# =============================================================================
# Trigger checker tests: _check_goal_achieved
# =============================================================================


class TestCheckGoalAchieved:
    """Tests for _check_goal_achieved."""

    @pytest.mark.asyncio
    async def test_returns_none_without_pool(self, monitor_no_pool, user_ctx):
        result = await monitor_no_pool._check_goal_achieved(user_ctx)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_invalid_uuid(self, monitor):
        ctx = UserContext(
            user_id=SAMPLE_USER_ID,
            organization_id="bad-uuid",
        )
        result = await monitor._check_goal_achieved(ctx)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_trigger_when_goal_completed(self, monitor, mock_pool, user_ctx):
        conn = mock_pool._conn
        row = Mock()
        row.id = "goal-456"
        row.title = "Monthly Revenue"
        row.updated_at = datetime.now(JST) - timedelta(hours=2)

        conn.execute.return_value = _make_db_result(fetchone_value=row)

        trigger = await monitor._check_goal_achieved(user_ctx)

        assert trigger is not None
        assert trigger.trigger_type == TriggerType.GOAL_ACHIEVED
        assert trigger.priority == ActionPriority.MEDIUM
        assert trigger.details["goal_id"] == "goal-456"
        assert trigger.details["goal_name"] == "Monthly Revenue"

    @pytest.mark.asyncio
    async def test_returns_none_when_no_completed_goal(self, monitor, mock_pool, user_ctx):
        conn = mock_pool._conn
        conn.execute.return_value = _make_db_result(fetchone_value=None)

        trigger = await monitor._check_goal_achieved(user_ctx)
        assert trigger is None

    @pytest.mark.asyncio
    async def test_db_error_returns_none(self, monitor, mock_pool, user_ctx):
        conn = mock_pool._conn
        conn.execute.side_effect = Exception("DB error")

        trigger = await monitor._check_goal_achieved(user_ctx)
        assert trigger is None

    @pytest.mark.asyncio
    async def test_goal_title_none_returns_empty_string(self, monitor, mock_pool, user_ctx):
        conn = mock_pool._conn
        row = Mock()
        row.id = "goal-789"
        row.title = None
        row.updated_at = datetime.now(JST) - timedelta(hours=1)

        conn.execute.return_value = _make_db_result(fetchone_value=row)

        trigger = await monitor._check_goal_achieved(user_ctx)
        assert trigger is not None
        assert trigger.details["goal_name"] == ""


# =============================================================================
# Trigger checker tests: _check_task_completed_streak
# =============================================================================


class TestCheckTaskCompletedStreak:
    """Tests for _check_task_completed_streak."""

    @pytest.mark.asyncio
    async def test_returns_none_without_pool(self, monitor_no_pool, user_ctx):
        result = await monitor_no_pool._check_task_completed_streak(user_ctx)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_without_account_id(self, monitor):
        ctx = UserContext(
            user_id=SAMPLE_USER_ID,
            organization_id=SAMPLE_ORG_ID,
            chatwork_account_id=None,
        )
        result = await monitor._check_task_completed_streak(ctx)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_trigger_when_streak(self, monitor, mock_pool, user_ctx):
        conn = mock_pool._conn
        row = Mock()
        row.count = 5

        conn.execute.return_value = _make_db_result(fetchone_value=row)

        trigger = await monitor._check_task_completed_streak(user_ctx)

        assert trigger is not None
        assert trigger.trigger_type == TriggerType.TASK_COMPLETED_STREAK
        assert trigger.priority == ActionPriority.LOW
        assert trigger.details["count"] == 5

    @pytest.mark.asyncio
    async def test_returns_none_below_streak_threshold(self, monitor, mock_pool, user_ctx):
        conn = mock_pool._conn
        row = Mock()
        row.count = 2  # below 3

        conn.execute.return_value = _make_db_result(fetchone_value=row)

        trigger = await monitor._check_task_completed_streak(user_ctx)
        assert trigger is None

    @pytest.mark.asyncio
    async def test_returns_trigger_at_exact_threshold(self, monitor, mock_pool, user_ctx):
        conn = mock_pool._conn
        row = Mock()
        row.count = 3  # exactly 3

        conn.execute.return_value = _make_db_result(fetchone_value=row)

        trigger = await monitor._check_task_completed_streak(user_ctx)
        assert trigger is not None

    @pytest.mark.asyncio
    async def test_db_error_returns_none(self, monitor, mock_pool, user_ctx):
        conn = mock_pool._conn
        conn.execute.side_effect = Exception("timeout")

        trigger = await monitor._check_task_completed_streak(user_ctx)
        assert trigger is None


# =============================================================================
# Trigger checker tests: _check_long_absence
# =============================================================================


class TestCheckLongAbsence:
    """Tests for _check_long_absence."""

    @pytest.mark.asyncio
    async def test_returns_none_when_no_last_activity(self, monitor):
        ctx = UserContext(
            user_id=SAMPLE_USER_ID,
            organization_id=SAMPLE_ORG_ID,
            last_activity_at=None,
        )
        result = await monitor._check_long_absence(ctx)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_trigger_for_long_absence(self, monitor):
        ctx = UserContext(
            user_id=SAMPLE_USER_ID,
            organization_id=SAMPLE_ORG_ID,
            last_activity_at=datetime.now(JST) - timedelta(days=20),
        )
        trigger = await monitor._check_long_absence(ctx)

        assert trigger is not None
        assert trigger.trigger_type == TriggerType.LONG_ABSENCE
        assert trigger.priority == ActionPriority.MEDIUM
        assert trigger.details["days"] >= LONG_ABSENCE_DAYS

    @pytest.mark.asyncio
    async def test_returns_none_for_recent_activity(self, monitor):
        ctx = UserContext(
            user_id=SAMPLE_USER_ID,
            organization_id=SAMPLE_ORG_ID,
            last_activity_at=datetime.now(JST) - timedelta(days=5),
        )
        trigger = await monitor._check_long_absence(ctx)
        assert trigger is None

    @pytest.mark.asyncio
    async def test_returns_trigger_at_exact_threshold(self, monitor):
        ctx = UserContext(
            user_id=SAMPLE_USER_ID,
            organization_id=SAMPLE_ORG_ID,
            last_activity_at=datetime.now(JST) - timedelta(days=LONG_ABSENCE_DAYS),
        )
        trigger = await monitor._check_long_absence(ctx)
        assert trigger is not None


# =============================================================================
# _take_action tests
# =============================================================================


class TestTakeAction:
    """Tests for _take_action."""

    @pytest.mark.asyncio
    async def test_brain_generated_message_sent(self, monitor, mock_brain, mock_send_func, mock_pool, user_ctx):
        """Brain generates message, message is sent via send_func."""
        trigger = Trigger(
            trigger_type=TriggerType.GOAL_ABANDONED,
            user_id=SAMPLE_USER_ID,
            organization_id=SAMPLE_ORG_ID,
            priority=ActionPriority.MEDIUM,
            details={"goal_name": "Test"},
        )
        # _log_action uses pool.connect; default mock_pool returns empty result
        conn = mock_pool._conn
        conn.execute.return_value = _make_db_result()

        action = await monitor._take_action(trigger, user_ctx)

        assert action.success is True
        assert action.message.message == "Brain generated message"
        mock_send_func.assert_called_once_with(
            room_id=SAMPLE_ROOM_ID,
            message="Brain generated message",
        )

    @pytest.mark.asyncio
    async def test_brain_decides_not_to_send(self, monitor, mock_brain, user_ctx):
        """When brain says should_send=False, action is skipped."""
        brain_result = Mock()
        brain_result.should_send = False
        brain_result.reason = "User prefers silence"
        mock_brain.generate_proactive_message.return_value = brain_result

        trigger = Trigger(
            trigger_type=TriggerType.EMOTION_DECLINE,
            user_id=SAMPLE_USER_ID,
            organization_id=SAMPLE_ORG_ID,
            priority=ActionPriority.CRITICAL,
        )

        action = await monitor._take_action(trigger, user_ctx)

        assert action.success is True
        assert action.message.message == ""
        assert "Skipped by brain" in action.error_message

    @pytest.mark.asyncio
    async def test_brain_failure_falls_back_to_template(self, monitor, mock_brain, mock_send_func, mock_pool, user_ctx):
        """When brain raises, fallback to template message."""
        mock_brain.generate_proactive_message.side_effect = Exception("Brain error")

        trigger = Trigger(
            trigger_type=TriggerType.GOAL_ABANDONED,
            user_id=SAMPLE_USER_ID,
            organization_id=SAMPLE_ORG_ID,
            priority=ActionPriority.MEDIUM,
            details={"goal_name": "Test", "days": 10},
        )
        conn = mock_pool._conn
        conn.execute.return_value = _make_db_result()

        action = await monitor._take_action(trigger, user_ctx)

        assert action.success is True
        assert len(action.message.message) > 0

    @pytest.mark.asyncio
    async def test_no_brain_uses_template(self, monitor_no_brain, mock_send_func, mock_pool, user_ctx):
        """Without brain, template is used."""
        trigger = Trigger(
            trigger_type=TriggerType.TASK_OVERLOAD,
            user_id=SAMPLE_USER_ID,
            organization_id=SAMPLE_ORG_ID,
            priority=ActionPriority.HIGH,
            details={"count": 6, "overdue_count": 2},
        )
        conn = mock_pool._conn
        conn.execute.return_value = _make_db_result()

        action = await monitor_no_brain._take_action(trigger, user_ctx)

        assert action.success is True
        assert len(action.message.message) > 0

    @pytest.mark.asyncio
    async def test_dry_run_does_not_send(self, monitor_dry_run, mock_send_func, user_ctx):
        """Dry run mode: message not actually sent."""
        trigger = Trigger(
            trigger_type=TriggerType.GOAL_ACHIEVED,
            user_id=SAMPLE_USER_ID,
            organization_id=SAMPLE_ORG_ID,
            priority=ActionPriority.MEDIUM,
            details={"goal_name": "Sales"},
        )

        action = await monitor_dry_run._take_action(trigger, user_ctx)

        assert action.success is True
        mock_send_func.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_failure_records_error(self, monitor, mock_brain, mock_send_func, mock_pool, user_ctx):
        """When send_message_func raises, error is recorded."""
        mock_send_func.side_effect = Exception("Network error")

        trigger = Trigger(
            trigger_type=TriggerType.GOAL_ABANDONED,
            user_id=SAMPLE_USER_ID,
            organization_id=SAMPLE_ORG_ID,
            priority=ActionPriority.MEDIUM,
        )

        action = await monitor._take_action(trigger, user_ctx)

        assert action.success is False
        assert "Exception" in action.error_message

    @pytest.mark.asyncio
    async def test_send_returns_false(self, monitor, mock_brain, mock_send_func, mock_pool, user_ctx):
        """When send_message_func returns False, success is False."""
        mock_send_func.return_value = False

        trigger = Trigger(
            trigger_type=TriggerType.GOAL_ABANDONED,
            user_id=SAMPLE_USER_ID,
            organization_id=SAMPLE_ORG_ID,
            priority=ActionPriority.MEDIUM,
        )

        action = await monitor._take_action(trigger, user_ctx)

        assert action.success is False

    @pytest.mark.asyncio
    async def test_no_send_func_still_succeeds(self, mock_pool, mock_brain, user_ctx):
        """Without send_message_func, action still succeeds (just no send)."""
        m = ProactiveMonitor(pool=mock_pool, send_message_func=None, brain=mock_brain)
        trigger = Trigger(
            trigger_type=TriggerType.LONG_ABSENCE,
            user_id=SAMPLE_USER_ID,
            organization_id=SAMPLE_ORG_ID,
            priority=ActionPriority.MEDIUM,
            details={"days": 20},
        )
        conn = mock_pool._conn
        conn.execute.return_value = _make_db_result()

        action = await m._take_action(trigger, user_ctx)
        assert action.success is True

    @pytest.mark.asyncio
    async def test_no_dm_room_does_not_send(self, monitor, mock_brain, mock_send_func, mock_pool):
        """Without dm_room_id, send_message_func is not called."""
        ctx = UserContext(
            user_id=SAMPLE_USER_ID,
            organization_id=SAMPLE_ORG_ID,
            chatwork_account_id=SAMPLE_ACCOUNT_ID,
            dm_room_id=None,
        )
        trigger = Trigger(
            trigger_type=TriggerType.GOAL_ABANDONED,
            user_id=SAMPLE_USER_ID,
            organization_id=SAMPLE_ORG_ID,
            priority=ActionPriority.MEDIUM,
        )
        conn = mock_pool._conn
        conn.execute.return_value = _make_db_result()

        action = await monitor._take_action(trigger, ctx)

        assert action.success is True
        mock_send_func.assert_not_called()


# =============================================================================
# _log_action tests
# =============================================================================


class TestLogAction:
    """Tests for _log_action."""

    @pytest.mark.asyncio
    async def test_log_action_success(self, monitor, mock_pool, user_ctx):
        conn = mock_pool._conn
        conn.execute.return_value = _make_db_result()

        trigger = Trigger(
            trigger_type=TriggerType.GOAL_ABANDONED,
            user_id=SAMPLE_USER_ID,
            organization_id=SAMPLE_ORG_ID,
            priority=ActionPriority.MEDIUM,
            details={"goal_name": "Test"},
        )

        # Should not raise
        await monitor._log_action(trigger, user_ctx)

        # Verify execute was called (for set_config + INSERT)
        assert conn.execute.call_count >= 1

    @pytest.mark.asyncio
    async def test_log_action_without_pool(self, user_ctx):
        m = ProactiveMonitor(pool=None)
        trigger = Trigger(
            trigger_type=TriggerType.GOAL_ABANDONED,
            user_id=SAMPLE_USER_ID,
            organization_id=SAMPLE_ORG_ID,
            priority=ActionPriority.MEDIUM,
        )
        # Should not raise
        await m._log_action(trigger, user_ctx)

    @pytest.mark.asyncio
    async def test_log_action_db_error_graceful(self, monitor, mock_pool, user_ctx):
        conn = mock_pool._conn
        conn.execute.side_effect = Exception("Insert failed")

        trigger = Trigger(
            trigger_type=TriggerType.GOAL_ABANDONED,
            user_id=SAMPLE_USER_ID,
            organization_id=SAMPLE_ORG_ID,
            priority=ActionPriority.MEDIUM,
        )
        # Should not raise
        await monitor._log_action(trigger, user_ctx)


# =============================================================================
# _get_active_users tests
# =============================================================================


class TestGetActiveUsers:
    """Tests for _get_active_users."""

    @pytest.mark.asyncio
    async def test_returns_empty_without_pool(self):
        m = ProactiveMonitor(pool=None)
        result = await m._get_active_users()
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_users(self, monitor, mock_pool):
        conn = mock_pool._conn
        row1 = Mock()
        row1.id = SAMPLE_USER_ID
        row1.organization_id = SAMPLE_ORG_ID
        row1.chatwork_account_id = SAMPLE_ACCOUNT_ID
        row1.dm_room_id = SAMPLE_ROOM_ID
        row1.last_active_at = None

        conn.execute.return_value = _make_db_result(fetchall_value=[row1])

        users = await monitor._get_active_users()
        assert len(users) == 1
        assert users[0].user_id == SAMPLE_USER_ID
        assert users[0].organization_id == SAMPLE_ORG_ID

    @pytest.mark.asyncio
    async def test_returns_users_with_org_filter(self, monitor, mock_pool):
        conn = mock_pool._conn
        row1 = Mock()
        row1.id = SAMPLE_USER_ID
        row1.organization_id = SAMPLE_ORG_ID
        row1.chatwork_account_id = SAMPLE_ACCOUNT_ID
        row1.dm_room_id = SAMPLE_ROOM_ID
        row1.last_active_at = None

        conn.execute.return_value = _make_db_result(fetchall_value=[row1])

        users = await monitor._get_active_users(organization_id=SAMPLE_ORG_ID)
        assert len(users) == 1

    @pytest.mark.asyncio
    async def test_returns_empty_on_db_error(self, monitor, mock_pool):
        conn = mock_pool._conn
        conn.execute.side_effect = Exception("DB unavailable")

        users = await monitor._get_active_users()
        assert users == []


# =============================================================================
# _get_user_context tests
# =============================================================================


class TestGetUserContext:
    """Tests for _get_user_context."""

    @pytest.mark.asyncio
    async def test_returns_none_without_pool(self):
        m = ProactiveMonitor(pool=None)
        result = await m._get_user_context(SAMPLE_USER_ID, SAMPLE_ORG_ID)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_user_context(self, monitor, mock_pool):
        conn = mock_pool._conn
        row = Mock()
        row.id = SAMPLE_USER_ID
        row.organization_id = SAMPLE_ORG_ID
        row.chatwork_account_id = SAMPLE_ACCOUNT_ID
        row.dm_room_id = SAMPLE_ROOM_ID
        row.last_active_at = None

        conn.execute.return_value = _make_db_result(fetchone_value=row)

        ctx = await monitor._get_user_context(SAMPLE_USER_ID, SAMPLE_ORG_ID)
        assert ctx is not None
        assert ctx.user_id == SAMPLE_USER_ID
        assert ctx.organization_id == SAMPLE_ORG_ID
        assert ctx.chatwork_account_id == SAMPLE_ACCOUNT_ID
        assert ctx.dm_room_id == SAMPLE_ROOM_ID

    @pytest.mark.asyncio
    async def test_returns_none_when_user_not_found(self, monitor, mock_pool):
        conn = mock_pool._conn
        conn.execute.return_value = _make_db_result(fetchone_value=None)

        ctx = await monitor._get_user_context("nonexistent", SAMPLE_ORG_ID)
        assert ctx is None

    @pytest.mark.asyncio
    async def test_returns_none_on_db_error(self, monitor, mock_pool):
        conn = mock_pool._conn
        conn.execute.side_effect = Exception("Query failed")

        ctx = await monitor._get_user_context(SAMPLE_USER_ID, SAMPLE_ORG_ID)
        assert ctx is None


# =============================================================================
# check_user tests
# =============================================================================


class TestCheckUser:
    """Tests for check_user (public method)."""

    @pytest.mark.asyncio
    async def test_returns_empty_result_when_user_not_found(self, monitor, mock_pool):
        conn = mock_pool._conn
        conn.execute.return_value = _make_db_result(fetchone_value=None)

        result = await monitor.check_user(
            user_id="nonexistent",
            organization_id=SAMPLE_ORG_ID,
        )
        assert result.user_id == "nonexistent"
        assert result.triggers_found == []

    @pytest.mark.asyncio
    async def test_checks_user_and_returns_result(self, monitor, mock_pool, mock_brain):
        conn = mock_pool._conn

        # First call: _get_user_context returns user
        user_row = Mock()
        user_row.id = SAMPLE_USER_ID
        user_row.organization_id = SAMPLE_ORG_ID
        user_row.chatwork_account_id = SAMPLE_ACCOUNT_ID
        user_row.dm_room_id = SAMPLE_ROOM_ID
        user_row.last_active_at = None

        user_result = _make_db_result(fetchone_value=user_row)

        # Subsequent calls: trigger checkers return no triggers
        empty_result = _make_db_result(fetchone_value=None, fetchall_value=[])

        call_count = 0

        async def side_effect_execute(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return user_result
            return empty_result

        conn.execute = AsyncMock(side_effect=side_effect_execute)

        result = await monitor.check_user(
            user_id=SAMPLE_USER_ID,
            organization_id=SAMPLE_ORG_ID,
        )
        assert result.user_id == SAMPLE_USER_ID


# =============================================================================
# check_and_act tests
# =============================================================================


class TestCheckAndAct:
    """Tests for check_and_act (main public method)."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_users(self, monitor, mock_pool):
        conn = mock_pool._conn
        conn.execute.return_value = _make_db_result(fetchall_value=[])

        results = await monitor.check_and_act()
        assert results == []

    @pytest.mark.asyncio
    async def test_returns_results_for_each_user(self, monitor, mock_pool):
        conn = mock_pool._conn

        # _get_active_users returns 2 users
        user1 = Mock(
            id=SAMPLE_USER_ID,
            organization_id=SAMPLE_ORG_ID,
            chatwork_account_id=SAMPLE_ACCOUNT_ID,
            dm_room_id=SAMPLE_ROOM_ID,
            last_active_at=None,
        )
        user2 = Mock(
            id="user-2",
            organization_id=SAMPLE_ORG_ID,
            chatwork_account_id="999",
            dm_room_id="room-2",
            last_active_at=None,
        )

        users_result = _make_db_result(fetchall_value=[user1, user2])
        empty_result = _make_db_result(fetchone_value=None, fetchall_value=[])

        call_count = 0

        async def side_effect_execute(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return users_result
            return empty_result

        conn.execute = AsyncMock(side_effect=side_effect_execute)

        results = await monitor.check_and_act()
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_with_organization_id_filter(self, monitor, mock_pool):
        conn = mock_pool._conn
        conn.execute.return_value = _make_db_result(fetchall_value=[])

        results = await monitor.check_and_act(organization_id=SAMPLE_ORG_ID)
        assert results == []

    @pytest.mark.asyncio
    async def test_user_check_error_creates_error_result(self, monitor, mock_pool):
        """When _check_single_user raises, check_and_act creates an error result."""
        conn = mock_pool._conn

        user1 = Mock(
            id=SAMPLE_USER_ID,
            organization_id=SAMPLE_ORG_ID,
            chatwork_account_id=SAMPLE_ACCOUNT_ID,
            dm_room_id=SAMPLE_ROOM_ID,
            last_active_at=None,
        )

        users_result = _make_db_result(fetchall_value=[user1])

        # First execute returns users list; subsequent calls succeed
        call_count = 0

        async def side_effect_execute(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return users_result
            return _make_db_result()

        conn.execute = AsyncMock(side_effect=side_effect_execute)

        # Patch _check_single_user to raise an exception directly
        with patch.object(
            monitor, '_check_single_user', new_callable=AsyncMock
        ) as mock_check:
            mock_check.side_effect = Exception("Unexpected error in _check_single_user")

            results = await monitor.check_and_act()
            assert len(results) == 1
            result = results[0]
            assert len(result.actions_taken) == 1
            assert result.actions_taken[0].success is False
            assert "Exception" in result.actions_taken[0].error_message

    @pytest.mark.asyncio
    async def test_critical_error_returns_empty(self, monitor, mock_pool):
        """When _get_active_users itself fails, return empty."""
        conn = mock_pool._conn
        conn.execute.side_effect = Exception("Critical DB failure")

        results = await monitor.check_and_act()
        assert results == []


# =============================================================================
# _check_single_user tests
# =============================================================================


class TestCheckSingleUser:
    """Tests for _check_single_user."""

    @pytest.mark.asyncio
    async def test_trigger_in_cooldown_is_skipped(self, monitor, mock_pool, user_ctx):
        """When a trigger is in cooldown, it should be added to skipped_triggers."""
        long_absence_ctx = UserContext(
            user_id=SAMPLE_USER_ID,
            organization_id=SAMPLE_ORG_ID,
            chatwork_account_id=SAMPLE_ACCOUNT_ID,
            dm_room_id=SAMPLE_ROOM_ID,
            last_activity_at=datetime.now(JST) - timedelta(days=20),
        )

        conn = mock_pool._conn
        conn.execute.return_value = _make_db_result(fetchone_value=None, fetchall_value=[])

        # Patch _is_in_cooldown to return True for all triggers
        with patch.object(monitor, '_is_in_cooldown', new_callable=AsyncMock) as mock_cooldown:
            mock_cooldown.return_value = True

            result = await monitor._check_single_user(long_absence_ctx)

            # Long absence trigger should be found but skipped due to cooldown
            assert len(result.skipped_triggers) > 0

    @pytest.mark.asyncio
    async def test_checker_exception_does_not_stop_others(self, monitor, mock_pool, user_ctx):
        """An exception in one checker should not prevent other checkers from running."""
        conn = mock_pool._conn
        conn.execute.return_value = _make_db_result(fetchone_value=None, fetchall_value=[])

        # Make one checker raise
        with patch.object(monitor, '_check_goal_abandoned', new_callable=AsyncMock) as mock_checker:
            mock_checker.side_effect = Exception("Checker crashed")

            result = await monitor._check_single_user(user_ctx)

            # Should still return a result (other checkers ran)
            assert result.user_id == SAMPLE_USER_ID


# =============================================================================
# _connect_with_org_context tests
# =============================================================================


class TestConnectWithOrgContext:
    """Tests for _connect_with_org_context (RLS context manager)."""

    @pytest.mark.asyncio
    async def test_sets_and_resets_org_context(self, monitor, mock_pool):
        conn = mock_pool._conn
        conn.execute.return_value = _make_db_result()

        async with monitor._connect_with_org_context(SAMPLE_ORG_ID) as c:
            assert c is conn

        # set_config should be called at least twice (set + reset)
        assert conn.execute.call_count >= 2


# =============================================================================
# create_proactive_monitor factory tests
# =============================================================================


class TestCreateProactiveMonitor:
    """Tests for create_proactive_monitor factory function."""

    def test_creates_monitor_with_all_params(self, mock_pool, mock_send_func, mock_brain):
        m = create_proactive_monitor(
            pool=mock_pool,
            send_message_func=mock_send_func,
            dry_run=True,
            brain=mock_brain,
        )
        assert isinstance(m, ProactiveMonitor)
        assert m._pool is mock_pool
        assert m._send_message_func is mock_send_func
        assert m._dry_run is True
        assert m._brain is mock_brain

    def test_creates_monitor_without_brain_logs_warning(self, mock_pool):
        """Without brain, a warning should be logged."""
        with patch("lib.brain.proactive.logger") as mock_logger:
            m = create_proactive_monitor(pool=mock_pool)
            mock_logger.warning.assert_called_once()
            assert "brain not provided" in mock_logger.warning.call_args[0][0]

    def test_creates_monitor_with_defaults(self):
        m = create_proactive_monitor()
        assert isinstance(m, ProactiveMonitor)
        assert m._pool is None
        assert m._send_message_func is None
        assert m._dry_run is False
        assert m._brain is None


# =============================================================================
# Constants validation tests
# =============================================================================


class TestConstants:
    """Tests to verify constant definitions are consistent."""

    def test_all_trigger_types_have_cooldown(self):
        for tt in TriggerType:
            assert tt in MESSAGE_COOLDOWN_HOURS, f"Missing cooldown for {tt}"

    def test_all_trigger_types_have_priority(self):
        for tt in TriggerType:
            assert tt in TRIGGER_PRIORITY, f"Missing priority for {tt}"

    def test_all_trigger_types_have_templates(self):
        for tt in TriggerType:
            assert tt in MESSAGE_TEMPLATES, f"Missing template for {tt}"
            assert len(MESSAGE_TEMPLATES[tt]) > 0, f"Empty templates for {tt}"

    def test_threshold_values_positive(self):
        assert GOAL_ABANDONED_DAYS > 0
        assert TASK_OVERLOAD_COUNT > 0
        assert EMOTION_DECLINE_DAYS > 0
        assert LONG_ABSENCE_DAYS > 0

    def test_org_uuid_to_slug_mapping(self):
        assert SAMPLE_ORG_ID in ORGANIZATION_UUID_TO_SLUG
        assert ORGANIZATION_UUID_TO_SLUG[SAMPLE_ORG_ID] == "org_soulsyncs"
