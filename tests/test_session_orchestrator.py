"""
lib/brain/session_orchestrator.py のテスト

対象:
- continue_session のStateType分岐
- _is_different_intent_from_goal_setting
- _handle_interrupted_goal_setting
- _handle_confirmation_response
- _continue_announcement
- _continue_task_pending
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from lib.brain.session_orchestrator import SessionOrchestrator
from lib.brain.models import (
    BrainContext,
    ConversationState,
    StateType,
    UnderstandingResult,
    DecisionResult,
    HandlerResult,
)


def _base_context():
    return BrainContext(
        organization_id="org-1",
        room_id="room-1",
        sender_name="テスト",
        sender_account_id="acc-1",
    )


def _make_orchestrator():
    state_manager = MagicMock()
    state_manager.clear_state = AsyncMock()
    state_manager.update_step = AsyncMock()

    return SessionOrchestrator(
        handlers={},
        state_manager=state_manager,
        understanding_func=AsyncMock(),
        decision_func=AsyncMock(),
        execution_func=AsyncMock(),
        is_cancel_func=lambda msg: msg.strip() in ["やめる", "キャンセル"],
        elapsed_ms_func=lambda start: 12,
    )


@pytest.mark.asyncio
async def test_continue_session_routes_by_state_type():
    orch = _make_orchestrator()
    orch._continue_goal_setting = AsyncMock(return_value=HandlerResult(success=True, message="goal"))
    orch._continue_announcement = AsyncMock(return_value=HandlerResult(success=True, message="announce"))
    orch._handle_confirmation_response = AsyncMock(return_value=HandlerResult(success=True, message="confirm"))
    orch._continue_task_pending = AsyncMock(return_value=HandlerResult(success=True, message="task"))

    ctx = _base_context()

    for state_type, method in [
        (StateType.GOAL_SETTING, orch._continue_goal_setting),
        (StateType.ANNOUNCEMENT, orch._continue_announcement),
        (StateType.CONFIRMATION, orch._handle_confirmation_response),
        (StateType.TASK_PENDING, orch._continue_task_pending),
    ]:
        state = ConversationState(state_type=state_type, state_step="why", state_data={})
        await orch.continue_session("msg", state, ctx, "room-1", "acc-1", "テスト", 0.0)
        method.assert_awaited()


@pytest.mark.asyncio
async def test_continue_session_unknown_state_clears():
    orch = _make_orchestrator()
    ctx = _base_context()
    state = ConversationState(state_type=StateType.MULTI_ACTION, state_step="x")
    response = await orch.continue_session("msg", state, ctx, "room-1", "acc-1", "テスト", 0.0)
    assert response.new_state == "normal"
    orch.state_manager.clear_state.assert_awaited()


def test_is_different_intent_stop_words():
    orch = _make_orchestrator()
    assert orch._is_different_intent_from_goal_setting("やめる", None, None) is True


def test_is_different_intent_goal_continuation():
    orch = _make_orchestrator()
    assert orch._is_different_intent_from_goal_setting("どう思う？", None, "feedback_request") is False


def test_is_different_intent_short_message_continues():
    orch = _make_orchestrator()
    assert orch._is_different_intent_from_goal_setting("OK", None, None) is False


def test_is_different_intent_other_action():
    orch = _make_orchestrator()
    # 短文ルールにより継続扱いになる
    assert orch._is_different_intent_from_goal_setting("タスク作って", None, "chatwork_task_create") is False


def test_is_different_intent_other_action_long_message():
    orch = _make_orchestrator()
    message = "タスクと期限の状況を見たいので情報が必要です"
    assert orch._is_different_intent_from_goal_setting(message, None, None) is True


def test_is_different_intent_non_goal_action_long_message():
    orch = _make_orchestrator()
    message = "今日はタスクの整理をお願いしたいです"
    assert orch._is_different_intent_from_goal_setting(message, None, "chatwork_task_create") is True


def test_is_different_intent_question_long_non_goal():
    orch = _make_orchestrator()
    message = "これってどういう意味ですか？理由を知りたいのですが説明できますか？"
    assert orch._is_different_intent_from_goal_setting(message, None, None) is True


def test_is_different_intent_question_with_goal_response():
    orch = _make_orchestrator()
    message = "目標についてどう思う？具体的に教えてほしい"
    assert orch._is_different_intent_from_goal_setting(message, None, None) is False


@pytest.mark.asyncio
async def test_handle_interrupted_goal_setting_executes_new_action():
    orch = _make_orchestrator()
    orch.handlers["interrupt_goal_setting"] = MagicMock()
    orch._decide = AsyncMock(return_value=DecisionResult(action="general_conversation"))
    orch._execute = AsyncMock(return_value=HandlerResult(success=True, message="OK"))

    state = ConversationState(
        state_type=StateType.GOAL_SETTING,
        state_step="what",
        state_data={"why_answer": "why", "what_answer": "what"},
        reference_id="ref-1",
    )
    ctx = _base_context()
    understanding = UnderstandingResult(raw_message="x", intent="general_conversation", intent_confidence=0.9)

    response = await orch._handle_interrupted_goal_setting(
        "msg", state, ctx, understanding, "room-1", "acc-1", "テスト", 0.0
    )

    assert "目標設定" in response.message
    assert response.action_taken.startswith("interrupted_goal_setting_then_")
    assert response.debug_info.get("interrupted_session")
    orch.state_manager.clear_state.assert_awaited()


@pytest.mark.asyncio
async def test_handle_interrupted_goal_setting_execute_general_conversation_fallback():
    orch = _make_orchestrator()
    orch.handlers["interrupt_goal_setting"] = MagicMock()
    orch._decide = AsyncMock(return_value=None)
    orch._execute_general_conversation = AsyncMock(return_value=HandlerResult(success=True, message="OK"))

    state = ConversationState(
        state_type=StateType.GOAL_SETTING,
        state_step="how",
        state_data={"why_answer": "why"},
    )
    ctx = _base_context()
    understanding = UnderstandingResult(raw_message="x", intent="general_conversation", intent_confidence=0.9)

    response = await orch._handle_interrupted_goal_setting(
        "msg", state, ctx, understanding, "room-1", "acc-1", "テスト", 0.0
    )

    assert response.action_taken.startswith("interrupted_goal_setting_then_")
    assert response.debug_info.get("interrupted_session")


@pytest.mark.asyncio
async def test_continue_announcement_dict_result_clears_on_completed():
    orch = _make_orchestrator()
    orch.handlers["continue_announcement"] = MagicMock(return_value={"message": "done", "new_state": "normal"})

    state = ConversationState(state_type=StateType.ANNOUNCEMENT, state_step="x", state_data={})
    ctx = _base_context()

    response = await orch._continue_announcement("msg", state, ctx, "room-1", "acc-1", "テスト", 0.0)
    assert response.message == "done"
    orch.state_manager.clear_state.assert_awaited()


@pytest.mark.asyncio
async def test_continue_task_pending_missing_items_prompts():
    orch = _make_orchestrator()
    orch.handlers["continue_task_pending"] = MagicMock(return_value=None)

    state = ConversationState(
        state_type=StateType.TASK_PENDING,
        state_step="x",
        state_data={"missing_items": ["limit_date"]},
    )
    ctx = _base_context()

    response = await orch._continue_task_pending("msg", state, ctx, "room-1", "acc-1", "テスト", 0.0)
    assert "期限" in response.message


@pytest.mark.asyncio
async def test_handle_confirmation_response_empty_options_fallback():
    orch = _make_orchestrator()
    state = ConversationState(
        state_type=StateType.CONFIRMATION,
        state_step="confirmation",
        state_data={"confirmation_options": []},
    )
    ctx = _base_context()

    response = await orch._handle_confirmation_response("msg", state, ctx, "room-1", "acc-1", "テスト", 0.0)
    assert response.action_taken == "confirmation_fallback"
    orch.state_manager.clear_state.assert_awaited()


@pytest.mark.asyncio
async def test_handle_confirmation_response_retry_then_fallback():
    orch = _make_orchestrator()
    state = ConversationState(
        state_type=StateType.CONFIRMATION,
        state_step="confirmation",
        state_data={"confirmation_options": ["A", "B"], "confirmation_retry_count": 1},
    )
    ctx = _base_context()

    response = await orch._handle_confirmation_response("わからない", state, ctx, "room-1", "acc-1", "テスト", 0.0)
    assert response.action_taken in ["confirmation_loop_fallback", "confirmation_retry"]


@pytest.mark.asyncio
async def test_handle_confirmation_response_executes_action():
    orch = _make_orchestrator()
    orch._execute = AsyncMock(return_value=HandlerResult(success=True, message="done"))

    state = ConversationState(
        state_type=StateType.CONFIRMATION,
        state_step="confirmation",
        state_data={
            "pending_action": "do_something",
            "pending_params": {},
            "confirmation_options": ["A", "B"],
        },
    )
    ctx = _base_context()

    response = await orch._handle_confirmation_response("1", state, ctx, "room-1", "acc-1", "テスト", 0.0)
    assert response.message == "done"
    assert response.action_taken == "do_something"


def test_parse_confirmation_response_variants():
    orch = _make_orchestrator()
    assert orch._parse_confirmation_response("1", ["A"]) == 0
    assert orch._parse_confirmation_response("やめる", ["A"]) == "cancel"
    assert orch._parse_confirmation_response("はい", ["A"]) == 0
    assert orch._parse_confirmation_response("いいえ", ["A"]) == "cancel"


@pytest.mark.asyncio
async def test_continue_goal_setting_dict_session_completed_clears():
    orch = _make_orchestrator()
    orch.handlers["continue_goal_setting"] = MagicMock(return_value={
        "message": "done",
        "session_completed": True,
        "new_state": "normal",
    })
    state = ConversationState(state_type=StateType.GOAL_SETTING, state_step="why", state_data={})
    ctx = _base_context()

    response = await orch._continue_goal_setting("msg", state, ctx, "room-1", "acc-1", "テスト", 0.0)
    assert response.message == "done"
    orch.state_manager.clear_state.assert_awaited()


@pytest.mark.asyncio
async def test_continue_goal_setting_string_result():
    orch = _make_orchestrator()
    orch.handlers["continue_goal_setting"] = MagicMock(return_value="ok")
    state = ConversationState(state_type=StateType.GOAL_SETTING, state_step="why", state_data={})
    ctx = _base_context()

    response = await orch._continue_goal_setting("msg", state, ctx, "room-1", "acc-1", "テスト", 0.0)
    assert response.message == "ok"


@pytest.mark.asyncio
async def test_continue_goal_setting_handler_error_fallback():
    orch = _make_orchestrator()
    orch.handlers["continue_goal_setting"] = MagicMock(side_effect=Exception("boom"))
    state = ConversationState(state_type=StateType.GOAL_SETTING, state_step="why", state_data={})
    ctx = _base_context()

    response = await orch._continue_goal_setting("msg", state, ctx, "room-1", "acc-1", "テスト", 0.0)
    assert response.success is False
    orch.state_manager.clear_state.assert_awaited()


@pytest.mark.asyncio
async def test_continue_goal_setting_handler_missing_fallback():
    orch = _make_orchestrator()
    state = ConversationState(state_type=StateType.GOAL_SETTING, state_step="why", state_data={})
    ctx = _base_context()

    response = await orch._continue_goal_setting("msg", state, ctx, "room-1", "acc-1", "テスト", 0.0)
    assert "目標設定" in response.message


@pytest.mark.asyncio
async def test_execute_general_conversation_handler_result():
    orch = _make_orchestrator()
    orch.handlers["general_conversation"] = AsyncMock(return_value=HandlerResult(success=True, message="hi"))
    ctx = _base_context()

    result = await orch._execute_general_conversation("msg", ctx, "room-1", "acc-1", "テスト")
    assert result.message == "hi"


@pytest.mark.asyncio
async def test_execute_general_conversation_string_result():
    orch = _make_orchestrator()
    orch.handlers["general_conversation"] = AsyncMock(return_value="hello")
    ctx = _base_context()

    result = await orch._execute_general_conversation("msg", ctx, "room-1", "acc-1", "テスト")
    assert result.message == "hello"


@pytest.mark.asyncio
async def test_execute_general_conversation_handler_error():
    orch = _make_orchestrator()
    orch.handlers["general_conversation"] = AsyncMock(side_effect=Exception("boom"))
    ctx = _base_context()

    result = await orch._execute_general_conversation("msg", ctx, "room-1", "acc-1", "テスト")
    assert result is None


@pytest.mark.asyncio
async def test_continue_task_pending_dict_task_created():
    orch = _make_orchestrator()
    orch.handlers["continue_task_pending"] = MagicMock(return_value={
        "message": "created",
        "task_created": True,
        "new_state": "normal",
    })
    state = ConversationState(state_type=StateType.TASK_PENDING, state_step="x", state_data={})
    ctx = _base_context()

    response = await orch._continue_task_pending("msg", state, ctx, "room-1", "acc-1", "テスト", 0.0)
    assert response.message == "created"
    orch.state_manager.clear_state.assert_awaited()


@pytest.mark.asyncio
async def test_continue_task_pending_string_clears():
    orch = _make_orchestrator()
    orch.handlers["continue_task_pending"] = MagicMock(return_value="done")
    state = ConversationState(state_type=StateType.TASK_PENDING, state_step="x", state_data={})
    ctx = _base_context()

    response = await orch._continue_task_pending("msg", state, ctx, "room-1", "acc-1", "テスト", 0.0)
    assert response.message == "done"
    orch.state_manager.clear_state.assert_awaited()


@pytest.mark.asyncio
async def test_continue_task_pending_handler_error_fallback():
    orch = _make_orchestrator()
    orch.handlers["continue_task_pending"] = MagicMock(side_effect=Exception("boom"))
    state = ConversationState(state_type=StateType.TASK_PENDING, state_step="x", state_data={})
    ctx = _base_context()

    response = await orch._continue_task_pending("msg", state, ctx, "room-1", "acc-1", "テスト", 0.0)
    assert response.success is False
    orch.state_manager.clear_state.assert_awaited()


@pytest.mark.asyncio
async def test_handle_confirmation_response_cancel():
    orch = _make_orchestrator()
    state = ConversationState(
        state_type=StateType.CONFIRMATION,
        state_step="confirmation",
        state_data={
            "pending_action": "do_something",
            "pending_params": {},
            "confirmation_options": ["A", "B"],
        },
    )
    ctx = _base_context()

    response = await orch._handle_confirmation_response("やめる", state, ctx, "room-1", "acc-1", "テスト", 0.0)
    assert response.action_taken == "cancel_confirmation"
    orch.state_manager.clear_state.assert_awaited()


@pytest.mark.asyncio
async def test_handle_confirmation_response_retry_path():
    orch = _make_orchestrator()
    state = ConversationState(
        state_type=StateType.CONFIRMATION,
        state_step="confirmation",
        state_data={"confirmation_options": ["A", "B"], "confirmation_retry_count": 0},
    )
    ctx = _base_context()

    response = await orch._handle_confirmation_response("わからない", state, ctx, "room-1", "acc-1", "テスト", 0.0)
    assert response.action_taken == "confirmation_retry"
    orch.state_manager.update_step.assert_awaited()
