"""
lib/brain/proactive.py のテスト
"""

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from lib.brain.proactive import (
    ProactiveMonitor,
    Trigger,
    TriggerType,
    ActionPriority,
    ProactiveMessageType,
    UserContext,
    MESSAGE_TEMPLATES,
    LONG_ABSENCE_DAYS,
    MESSAGE_COOLDOWN_HOURS,
)
from lib.brain.constants import JST


class _AsyncConn:
    def __init__(self, result):
        self._result = result
        self.execute = AsyncMock(return_value=result)
        self.commit = AsyncMock()


class _AsyncPool:
    def __init__(self, result):
        self._result = result

    def connect(self):
        result = self._result

        class _Ctx:
            async def __aenter__(self_inner):
                return _AsyncConn(result)

            async def __aexit__(self_inner, exc_type, exc, tb):
                return False

        return _Ctx()


class _Result:
    def __init__(self, fetchone=None, fetchall=None, iterable=None):
        self._fetchone = fetchone
        self._fetchall = fetchall or []
        self._iterable = iterable

    def fetchone(self):
        return self._fetchone

    def fetchall(self):
        return self._fetchall

    def __iter__(self):
        return iter(self._iterable or [])


def test_get_chatwork_tasks_org_id():
    monitor = ProactiveMonitor()
    assert monitor._get_chatwork_tasks_org_id("5f98365f-e7c5-4f48-9918-7fe9aabae5df") == "org_soulsyncs"
    assert monitor._get_chatwork_tasks_org_id("unknown") == "org_soulsyncs"


def test_get_chatwork_account_id_int():
    monitor = ProactiveMonitor()
    assert monitor._get_chatwork_account_id_int("123") == 123
    assert monitor._get_chatwork_account_id_int("abc") is None


def test_is_valid_uuid():
    monitor = ProactiveMonitor()
    assert monitor._is_valid_uuid("11111111-1111-1111-1111-111111111111") is True
    assert monitor._is_valid_uuid("not-uuid") is False


def test_should_act_priority_and_missing_targets():
    monitor = ProactiveMonitor()
    trigger = Trigger(
        trigger_type=TriggerType.TASK_OVERLOAD,
        user_id="u",
        organization_id="org",
        priority=ActionPriority.MEDIUM,
    )
    user_ctx = UserContext(user_id="u", organization_id="org")
    assert monitor._should_act(trigger, user_ctx) is False


def test_generate_message_template_fallback():
    monitor = ProactiveMonitor()
    trigger = Trigger(
        trigger_type=TriggerType.GOAL_ABANDONED,
        user_id="u",
        organization_id="org",
        priority=ActionPriority.MEDIUM,
        details={"goal_name": "目標A", "days": 7},
    )
    msg = monitor._generate_message(trigger)
    assert isinstance(msg, str)


def test_get_message_type_mapping():
    monitor = ProactiveMonitor()
    assert monitor._get_message_type(TriggerType.GOAL_ACHIEVED) == ProactiveMessageType.CELEBRATION


@pytest.mark.asyncio
async def test_check_long_absence_trigger():
    monitor = ProactiveMonitor()
    user_ctx = UserContext(
        user_id="u",
        organization_id="org",
        last_activity_at=datetime.now(JST) - timedelta(days=LONG_ABSENCE_DAYS + 1),
    )
    trigger = await monitor._check_long_absence(user_ctx)
    assert trigger is not None
    assert trigger.trigger_type == TriggerType.LONG_ABSENCE


@pytest.mark.asyncio
async def test_is_in_cooldown_true():
    result = _Result(fetchone=("id",))
    monitor = ProactiveMonitor(pool=_AsyncPool(result))
    user_ctx = UserContext(user_id="u", organization_id="org")
    in_cd = await monitor._is_in_cooldown(user_ctx, TriggerType.GOAL_ABANDONED)
    assert in_cd is True


@pytest.mark.asyncio
async def test_is_in_cooldown_false_on_error():
    class BadPool:
        def connect(self):
            class _Ctx:
                async def __aenter__(self_inner):
                    raise Exception("db")
                async def __aexit__(self_inner, exc_type, exc, tb):
                    return False
            return _Ctx()

    monitor = ProactiveMonitor(pool=BadPool())
    user_ctx = UserContext(user_id="u", organization_id="org")
    in_cd = await monitor._is_in_cooldown(user_ctx, TriggerType.GOAL_ABANDONED)
    assert in_cd is False


@pytest.mark.asyncio
async def test_take_action_brain_skips_send():
    class BrainResult:
        should_send = False
        reason = "no"
        message = ""

    brain = AsyncMock()
    brain.generate_proactive_message = AsyncMock(return_value=BrainResult())

    monitor = ProactiveMonitor(brain=brain, dry_run=False)
    trigger = Trigger(
        trigger_type=TriggerType.GOAL_ABANDONED,
        user_id="u",
        organization_id="org",
        priority=ActionPriority.MEDIUM,
    )
    user_ctx = UserContext(user_id="u", organization_id="org", dm_room_id="room", chatwork_account_id="acc")

    action = await monitor._take_action(trigger, user_ctx)
    assert action.success is True
    assert "Skipped by brain" in (action.error_message or "")


@pytest.mark.asyncio
async def test_take_action_fallback_template_dry_run():
    monitor = ProactiveMonitor(dry_run=True, brain=None)
    trigger = Trigger(
        trigger_type=TriggerType.GOAL_ABANDONED,
        user_id="u",
        organization_id="org",
        priority=ActionPriority.MEDIUM,
        details={"goal_name": "目標A", "days": 7},
    )
    user_ctx = UserContext(user_id="u", organization_id="org", dm_room_id="room", chatwork_account_id="acc")

    action = await monitor._take_action(trigger, user_ctx)
    assert action.success is True


@pytest.mark.asyncio
async def test_check_and_act_handles_user_error():
    monitor = ProactiveMonitor()

    async def bad_get_active_users(_):
        return [UserContext(user_id="u", organization_id="org")]

    async def bad_check(user_ctx):
        raise Exception("boom")

    monitor._get_active_users = bad_get_active_users
    monitor._check_single_user = bad_check

    results = await monitor.check_and_act()
    assert len(results) == 1
    assert results[0].actions_taken


@pytest.mark.asyncio
async def test_get_active_users_maps_rows():
    row = SimpleNamespace(
        id="user-1",
        organization_id="org",
        chatwork_account_id="123",
        dm_room_id="room",
        last_active_at=None,
    )
    result = _Result(fetchall=[row])
    monitor = ProactiveMonitor(pool=_AsyncPool(result))
    users = await monitor._get_active_users()
    assert users[0].user_id == "user-1"


@pytest.mark.asyncio
async def test_get_user_context_returns_none_when_missing():
    result = _Result(fetchone=None)
    monitor = ProactiveMonitor(pool=_AsyncPool(result))
    ctx = await monitor._get_user_context("u", "org")
    assert ctx is None
