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
async def test_handle_confirmation_response_no_pending_action():
    """pending_actionがない場合はconfirmation_no_actionを返す"""
    orch = _make_orchestrator()
    state = ConversationState(
        state_type=StateType.CONFIRMATION,
        state_step="confirmation",
        state_data={"confirmation_options": []},
    )
    ctx = _base_context()

    response = await orch._handle_confirmation_response("msg", state, ctx, "room-1", "acc-1", "テスト", 0.0)
    assert response.action_taken == "confirmation_no_action"
    orch.state_manager.clear_state.assert_awaited()


@pytest.mark.asyncio
async def test_handle_confirmation_response_empty_options_fallback():
    """pending_actionはあるがoptionsが空の場合はconfirmation_fallbackを返す"""
    orch = _make_orchestrator()
    state = ConversationState(
        state_type=StateType.CONFIRMATION,
        state_step="confirmation",
        state_data={"pending_action": "do_something", "confirmation_options": []},
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
        state_data={"pending_action": "do_something", "confirmation_options": ["A", "B"], "confirmation_retry_count": 1},
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
        state_data={"pending_action": "do_something", "confirmation_options": ["A", "B"], "confirmation_retry_count": 0},
    )
    ctx = _base_context()

    response = await orch._handle_confirmation_response("わからない", state, ctx, "room-1", "acc-1", "テスト", 0.0)
    assert response.action_taken == "confirmation_retry"
    orch.state_manager.update_step.assert_awaited()


# =============================================================================
# 追加テスト: 未カバー行を網羅
# =============================================================================


@pytest.mark.asyncio
async def test_continue_session_routes_to_list_context():
    """LINE 108: LIST_CONTEXT でルーティング"""
    orch = _make_orchestrator()
    orch.handlers["continue_list_context"] = MagicMock(
        return_value={"message": "list ok", "success": True, "session_completed": True}
    )
    state = ConversationState(
        state_type=StateType.LIST_CONTEXT, state_step="list", state_data={}
    )
    ctx = _base_context()

    response = await orch.continue_session("1", state, ctx, "room-1", "acc-1", "テスト", 0.0)
    assert response.action_taken == "continue_list_context"
    assert response.message == "list ok"


@pytest.mark.asyncio
async def test_continue_goal_setting_different_intent_interrupt():
    """LINES 156-162: 目標設定中に別の意図を検出して中断"""
    orch = _make_orchestrator()
    understanding = UnderstandingResult(
        raw_message="一覧表示して", intent="chatwork_task_search", intent_confidence=0.9
    )
    orch._understand = AsyncMock(return_value=understanding)
    orch._decide = AsyncMock(return_value=DecisionResult(action="chatwork_task_search"))
    orch._execute = AsyncMock(return_value=HandlerResult(success=True, message="タスク一覧"))
    orch.handlers["continue_goal_setting"] = MagicMock(return_value={"message": "x"})

    state = ConversationState(
        state_type=StateType.GOAL_SETTING,
        state_step="why",
        state_data={"why_answer": "成長のため"},
    )
    ctx = _base_context()

    response = await orch._continue_goal_setting(
        "一覧見せて", state, ctx, "room-1", "acc-1", "テスト", 0.0
    )
    assert "interrupted_goal_setting" in response.action_taken
    assert response.state_changed is True


@pytest.mark.asyncio
async def test_continue_goal_setting_understanding_exception():
    """LINE 162: 意図理解で例外が出ても継続"""
    orch = _make_orchestrator()
    orch._understand = AsyncMock(side_effect=RuntimeError("LLM timeout"))
    orch.handlers["continue_goal_setting"] = MagicMock(
        return_value={"message": "continue", "success": True}
    )

    state = ConversationState(
        state_type=StateType.GOAL_SETTING, state_step="why", state_data={}
    )
    ctx = _base_context()

    response = await orch._continue_goal_setting(
        "回答", state, ctx, "room-1", "acc-1", "テスト", 0.0
    )
    assert response.message == "continue"
    assert response.success is True


@pytest.mark.asyncio
async def test_continue_goal_setting_handler_coroutine():
    """LINE 181: ハンドラーがコルーチンの場合に await される"""
    async def async_goal_handler(msg, room, acc, sender, data):
        return {"message": "async goal result", "success": True}

    orch = _make_orchestrator()
    orch.handlers["continue_goal_setting"] = async_goal_handler

    state = ConversationState(
        state_type=StateType.GOAL_SETTING, state_step="why", state_data={}
    )
    ctx = _base_context()

    response = await orch._continue_goal_setting(
        "msg", state, ctx, "room-1", "acc-1", "テスト", 0.0
    )
    assert response.message == "async goal result"


def test_is_different_intent_goal_in_action_name():
    """LINE 317: inferred_actionに'goal'が含まれる場合は is_goal_action=True"""
    orch = _make_orchestrator()
    # 長文 + question ending → would be different intent,
    # but action has 'goal' so is_goal_action=True → returns False
    msg = "目標のチェック項目を確認させてほしいのですが、何をすればいいですか？"
    result = orch._is_different_intent_from_goal_setting(msg, None, "goal_detailed_check")
    assert result is False


def test_is_different_intent_non_goal_actions():
    """LINES 326-332: non_goal_actions リスト内の各アクション"""
    orch = _make_orchestrator()
    non_goal_actions = [
        "chatwork_task_search",
        "chatwork_task_create",
        "query_knowledge",
        "save_memory",
        "query_memory",
        "announcement_create",
        "daily_reflection",
    ]
    for action in non_goal_actions:
        # 21文字以上で、stop wordなし、continuation intentでもない
        # goal_response_keywords / other_action_keywords / question_words を含まない
        msg = "よろしくおねがいいたしますぜひともおねがいいたします"
        result = orch._is_different_intent_from_goal_setting(msg, None, action)
        assert result is True, f"Expected True for action={action}"


@pytest.mark.asyncio
async def test_interrupt_goal_setting_handler_called_and_error():
    """LINES 376-377: interrupt_goal_setting ハンドラーが呼ばれる + エラー時もログだけ"""
    # Success case
    interrupt_handler = MagicMock()
    orch = _make_orchestrator()
    orch.handlers["interrupt_goal_setting"] = interrupt_handler
    orch._decide = AsyncMock(return_value=DecisionResult(action="general"))
    orch._execute = AsyncMock(return_value=HandlerResult(success=True, message="ok"))

    state = ConversationState(
        state_type=StateType.GOAL_SETTING,
        state_step="what",
        state_data={"why_answer": "x", "what_answer": "y"},
    )
    ctx = _base_context()
    understanding = UnderstandingResult(raw_message="t", intent="g", intent_confidence=0.5)

    await orch._handle_interrupted_goal_setting(
        "test", state, ctx, understanding, "room-1", "acc-1", "テスト", 0.0
    )
    interrupt_handler.assert_called_once()

    # Error case: handler raises but should not propagate
    interrupt_handler_err = MagicMock(side_effect=RuntimeError("save failed"))
    orch2 = _make_orchestrator()
    orch2.handlers["interrupt_goal_setting"] = interrupt_handler_err
    orch2._decide = AsyncMock(return_value=DecisionResult(action="general"))
    orch2._execute = AsyncMock(return_value=HandlerResult(success=True, message="ok"))

    response = await orch2._handle_interrupted_goal_setting(
        "test", state, ctx, understanding, "room-1", "acc-1", "テスト", 0.0
    )
    assert response.success is True


@pytest.mark.asyncio
async def test_interrupt_goal_setting_outer_exception():
    """LINES 429-432: 外部例外時のフォールバック"""
    orch = _make_orchestrator()
    orch._decide = AsyncMock(side_effect=RuntimeError("catastrophic error"))

    state = ConversationState(
        state_type=StateType.GOAL_SETTING, state_step="why", state_data={}
    )
    ctx = _base_context()
    understanding = UnderstandingResult(raw_message="t", intent="g", intent_confidence=0.5)

    response = await orch._handle_interrupted_goal_setting(
        "test", state, ctx, understanding, "room-1", "acc-1", "テスト", 0.0
    )
    assert response.action_taken == "goal_setting_interrupted"
    assert response.success is True
    assert response.new_state == "normal"
    orch.state_manager.clear_state.assert_awaited()


@pytest.mark.asyncio
async def test_continue_announcement_handler_coroutine():
    """LINE 485: アナウンスハンドラーがコルーチンの場合"""
    async def async_announce_handler(msg, room, acc, sender, data):
        return {"message": "async announce", "success": True}

    orch = _make_orchestrator()
    orch.handlers["continue_announcement"] = async_announce_handler

    state = ConversationState(
        state_type=StateType.ANNOUNCEMENT, state_step="x", state_data={}
    )
    ctx = _base_context()

    response = await orch._continue_announcement(
        "msg", state, ctx, "room-1", "acc-1", "テスト", 0.0
    )
    assert response.message == "async announce"


@pytest.mark.asyncio
async def test_continue_announcement_handler_returns_string():
    """LINES 505-511: ハンドラーが文字列を返した場合"""
    orch = _make_orchestrator()
    orch.handlers["continue_announcement"] = MagicMock(return_value="確認中ウル")

    state = ConversationState(
        state_type=StateType.ANNOUNCEMENT, state_step="x", state_data={}
    )
    ctx = _base_context()

    response = await orch._continue_announcement(
        "test", state, ctx, "room-1", "acc-1", "テスト", 0.0
    )
    assert response.message == "確認中ウル"
    assert response.action_taken == "continue_announcement"
    assert response.success is True


@pytest.mark.asyncio
async def test_continue_announcement_handler_exception():
    """LINES 513-523: ハンドラーが例外を投げた場合"""
    orch = _make_orchestrator()
    orch.handlers["continue_announcement"] = MagicMock(
        side_effect=RuntimeError("announce error")
    )

    state = ConversationState(
        state_type=StateType.ANNOUNCEMENT, state_step="x", state_data={}
    )
    ctx = _base_context()

    response = await orch._continue_announcement(
        "test", state, ctx, "room-1", "acc-1", "テスト", 0.0
    )
    assert response.success is False
    assert response.state_changed is True
    assert response.new_state == "normal"
    assert "エラー" in response.message


@pytest.mark.asyncio
async def test_continue_announcement_no_handler_fallback():
    """LINES 525-530: ハンドラー未登録のフォールバック"""
    orch = _make_orchestrator()
    state = ConversationState(
        state_type=StateType.ANNOUNCEMENT, state_step="x", state_data={}
    )
    ctx = _base_context()

    response = await orch._continue_announcement(
        "test", state, ctx, "room-1", "acc-1", "テスト", 0.0
    )
    assert response.action_taken == "continue_announcement"
    assert "アナウンス" in response.message


@pytest.mark.asyncio
async def test_continue_task_pending_handler_coroutine():
    """LINE 723: タスク保留ハンドラーがコルーチンの場合"""
    async def async_task_handler(msg, room, acc, sender, data):
        return {"message": "async task", "success": True, "task_created": True}

    orch = _make_orchestrator()
    orch.handlers["continue_task_pending"] = async_task_handler

    state = ConversationState(
        state_type=StateType.TASK_PENDING, state_step="x", state_data={}
    )
    ctx = _base_context()

    response = await orch._continue_task_pending(
        "明日", state, ctx, "room-1", "acc-1", "テスト", 0.0
    )
    assert response.message == "async task"
    orch.state_manager.clear_state.assert_awaited()


@pytest.mark.asyncio
async def test_continue_task_pending_none_result_missing_items():
    """LINES 729-734: ハンドラーがNoneを返し、各種missing_items"""
    orch = _make_orchestrator()

    # limit_date
    orch.handlers["continue_task_pending"] = MagicMock(return_value=None)
    state = ConversationState(
        state_type=StateType.TASK_PENDING,
        state_step="x",
        state_data={"missing_items": ["limit_date"]},
    )
    ctx = _base_context()
    resp = await orch._continue_task_pending("x", state, ctx, "room-1", "acc-1", "テスト", 0.0)
    assert "期限" in resp.message

    # task_body
    state2 = ConversationState(
        state_type=StateType.TASK_PENDING,
        state_step="x",
        state_data={"missing_items": ["task_body"]},
    )
    resp2 = await orch._continue_task_pending("x", state2, ctx, "room-1", "acc-1", "テスト", 0.0)
    assert "内容" in resp2.message

    # assigned_to
    state3 = ConversationState(
        state_type=StateType.TASK_PENDING,
        state_step="x",
        state_data={"missing_items": ["assigned_to"]},
    )
    resp3 = await orch._continue_task_pending("x", state3, ctx, "room-1", "acc-1", "テスト", 0.0)
    assert "担当" in resp3.message

    # empty (default)
    state4 = ConversationState(
        state_type=StateType.TASK_PENDING,
        state_step="x",
        state_data={"missing_items": []},
    )
    resp4 = await orch._continue_task_pending("x", state4, ctx, "room-1", "acc-1", "テスト", 0.0)
    assert "詳細" in resp4.message


@pytest.mark.asyncio
async def test_continue_task_pending_no_handler_fallback_all_missing_items():
    """LINES 784-795: ハンドラー未登録 + 各種missing_itemsのフォールバック"""
    orch = _make_orchestrator()
    ctx = _base_context()

    # limit_date
    state1 = ConversationState(
        state_type=StateType.TASK_PENDING,
        state_step="x",
        state_data={"missing_items": ["limit_date"]},
    )
    resp1 = await orch._continue_task_pending("x", state1, ctx, "room-1", "acc-1", "テスト", 0.0)
    assert "期限" in resp1.message
    assert resp1.action_taken == "continue_task_pending"

    # task_body
    state2 = ConversationState(
        state_type=StateType.TASK_PENDING,
        state_step="x",
        state_data={"missing_items": ["task_body"]},
    )
    resp2 = await orch._continue_task_pending("x", state2, ctx, "room-1", "acc-1", "テスト", 0.0)
    assert "内容" in resp2.message

    # assigned_to
    state3 = ConversationState(
        state_type=StateType.TASK_PENDING,
        state_step="x",
        state_data={"missing_items": ["assigned_to"]},
    )
    resp3 = await orch._continue_task_pending("x", state3, ctx, "room-1", "acc-1", "テスト", 0.0)
    assert "担当" in resp3.message

    # empty (default)
    state4 = ConversationState(
        state_type=StateType.TASK_PENDING,
        state_step="x",
        state_data={},
    )
    resp4 = await orch._continue_task_pending("x", state4, ctx, "room-1", "acc-1", "テスト", 0.0)
    assert "詳細" in resp4.message

    # state_data is None (edge case)
    state5 = ConversationState(
        state_type=StateType.TASK_PENDING,
        state_step="x",
    )
    state5.state_data = None
    resp5 = await orch._continue_task_pending("x", state5, ctx, "room-1", "acc-1", "テスト", 0.0)
    assert "詳細" in resp5.message


# =============================================================================
# _continue_list_context テスト (LINES 819-902)
# =============================================================================


@pytest.mark.asyncio
async def test_continue_list_context_dict_session_completed():
    """LINES 819-875: ハンドラーが session_completed=True を返す"""
    orch = _make_orchestrator()
    orch.handlers["continue_list_context"] = MagicMock(
        return_value={"message": "削除完了", "success": True, "session_completed": True}
    )
    state = ConversationState(
        state_type=StateType.LIST_CONTEXT, state_step="list", state_data={}
    )
    ctx = _base_context()

    response = await orch._continue_list_context(
        "1番削除", state, ctx, "room-1", "acc-1", "テスト", 0.0
    )
    assert response.message == "削除完了"
    assert response.state_changed is True
    assert response.new_state == "normal"
    orch.state_manager.clear_state.assert_awaited()


@pytest.mark.asyncio
async def test_continue_list_context_dict_fallback_to_general():
    """LINES 851-854: fallback_to_general=True"""
    orch = _make_orchestrator()
    orch.handlers["continue_list_context"] = MagicMock(
        return_value={"message": "", "success": True, "fallback_to_general": True}
    )
    state = ConversationState(
        state_type=StateType.LIST_CONTEXT, state_step="list", state_data={}
    )
    ctx = _base_context()

    response = await orch._continue_list_context(
        "別のこと", state, ctx, "room-1", "acc-1", "テスト", 0.0
    )
    assert response.state_changed is True
    assert response.new_state == "normal"
    assert response.debug_info.get("fallback_to_general") is True
    orch.state_manager.clear_state.assert_awaited()


@pytest.mark.asyncio
async def test_continue_list_context_dict_new_state_data():
    """LINES 856-865: new_state_data がある場合に transition_to が呼ばれる"""
    orch = _make_orchestrator()
    orch.state_manager.transition_to = AsyncMock()
    orch.handlers["continue_list_context"] = MagicMock(
        return_value={
            "message": "本当に削除しますか？",
            "success": True,
            "new_state_data": {"step": "confirm_delete", "target_ids": [1, 2]},
        }
    )
    state = ConversationState(
        state_type=StateType.LIST_CONTEXT, state_step="list", state_data={}
    )
    ctx = _base_context()

    response = await orch._continue_list_context(
        "1以外削除", state, ctx, "room-1", "acc-1", "テスト", 0.0
    )
    assert response.message == "本当に削除しますか？"
    assert response.new_state == "list_context"
    assert response.state_changed is False
    orch.state_manager.transition_to.assert_awaited_once()
    # Verify transition_to call parameters
    call_kwargs = orch.state_manager.transition_to.call_args.kwargs
    assert call_kwargs["state_type"] == StateType.LIST_CONTEXT
    assert call_kwargs["timeout_minutes"] == 5


@pytest.mark.asyncio
async def test_continue_list_context_dict_ongoing():
    """LINES 867-875: session_completed/fallback/new_state_data なし"""
    orch = _make_orchestrator()
    orch.handlers["continue_list_context"] = MagicMock(
        return_value={"message": "選択しました", "success": True}
    )
    state = ConversationState(
        state_type=StateType.LIST_CONTEXT, state_step="list", state_data={}
    )
    ctx = _base_context()

    response = await orch._continue_list_context(
        "1", state, ctx, "room-1", "acc-1", "テスト", 0.0
    )
    assert response.message == "選択しました"
    assert response.new_state == "list_context"
    assert response.state_changed is False


@pytest.mark.asyncio
async def test_continue_list_context_handler_returns_none():
    """LINES 834-845: ハンドラーがNoneを返す → フォールバック"""
    orch = _make_orchestrator()
    orch.handlers["continue_list_context"] = MagicMock(return_value=None)
    state = ConversationState(
        state_type=StateType.LIST_CONTEXT, state_step="list", state_data={}
    )
    ctx = _base_context()

    response = await orch._continue_list_context(
        "abc", state, ctx, "room-1", "acc-1", "テスト", 0.0
    )
    assert response.action_taken == "list_context_fallback"
    assert response.state_changed is True
    assert response.new_state == "normal"
    assert response.debug_info.get("fallback_to_general") is True
    orch.state_manager.clear_state.assert_awaited()


@pytest.mark.asyncio
async def test_continue_list_context_handler_returns_string():
    """LINES 876-885: ハンドラーが文字列を返す"""
    orch = _make_orchestrator()
    orch.handlers["continue_list_context"] = MagicMock(return_value="操作完了テキスト")
    state = ConversationState(
        state_type=StateType.LIST_CONTEXT, state_step="list", state_data={}
    )
    ctx = _base_context()

    response = await orch._continue_list_context(
        "1", state, ctx, "room-1", "acc-1", "テスト", 0.0
    )
    assert response.message == "操作完了テキスト"
    assert response.state_changed is True
    assert response.new_state == "normal"
    orch.state_manager.clear_state.assert_awaited()


@pytest.mark.asyncio
async def test_continue_list_context_handler_coroutine():
    """LINES 831-832: ハンドラーがコルーチンの場合"""
    async def async_list_handler(msg, room, acc, sender, data):
        return {"message": "async list ok", "success": True, "session_completed": True}

    orch = _make_orchestrator()
    orch.handlers["continue_list_context"] = async_list_handler
    state = ConversationState(
        state_type=StateType.LIST_CONTEXT, state_step="list", state_data={}
    )
    ctx = _base_context()

    response = await orch._continue_list_context(
        "1", state, ctx, "room-1", "acc-1", "テスト", 0.0
    )
    assert response.message == "async list ok"


@pytest.mark.asyncio
async def test_continue_list_context_handler_exception():
    """LINES 887-897: ハンドラーが例外を投げた場合"""
    orch = _make_orchestrator()
    orch.handlers["continue_list_context"] = MagicMock(
        side_effect=RuntimeError("list error")
    )
    state = ConversationState(
        state_type=StateType.LIST_CONTEXT, state_step="list", state_data={}
    )
    ctx = _base_context()

    response = await orch._continue_list_context(
        "1", state, ctx, "room-1", "acc-1", "テスト", 0.0
    )
    assert response.success is False
    assert response.state_changed is True
    assert response.new_state == "normal"
    assert "エラー" in response.message
    orch.state_manager.clear_state.assert_awaited()


@pytest.mark.asyncio
async def test_continue_list_context_no_handler_fallback():
    """LINES 899-909: ハンドラー未登録のフォールバック"""
    orch = _make_orchestrator()
    state = ConversationState(
        state_type=StateType.LIST_CONTEXT, state_step="list", state_data={}
    )
    ctx = _base_context()

    response = await orch._continue_list_context(
        "1", state, ctx, "room-1", "acc-1", "テスト", 0.0
    )
    assert response.action_taken == "continue_list_context"
    assert response.state_changed is True
    assert response.new_state == "normal"
    assert "リセット" in response.message
    orch.state_manager.clear_state.assert_awaited()
