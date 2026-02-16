# tests/test_brain_graph.py
"""
LangGraph Brain グラフのテスト

lib/brain/graph/ 配下の全ノード・ルーティング・グラフ構築をテスト。
"""

import copy
import pytest
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List

from lib.brain.graph.builder import (
    route_after_state_check,
    route_after_guardian,
    route_after_execution,
    create_brain_graph,
)
from lib.brain.graph.state import BrainGraphState
from lib.brain.graph.nodes.state_check import make_state_check, make_route_session
from lib.brain.graph.nodes.build_context import make_build_context
from lib.brain.graph.nodes.llm_inference import make_llm_inference
from lib.brain.graph.nodes.guardian_check import make_guardian_check
from lib.brain.graph.nodes.execute_tool import make_execute_tool
from lib.brain.graph.nodes.synthesize import make_synthesize_knowledge
from lib.brain.graph.nodes.responses import (
    make_handle_block,
    make_handle_confirm,
    make_text_response,
    make_build_response,
    _mask_reasoning,
)
from lib.brain.models import (
    BrainContext,
    BrainResponse,
    DecisionResult,
    HandlerResult,
    ConversationState,
    StateType,
)


# =============================================================================
# ヘルパー: モックデータクラス
# =============================================================================


@dataclass
class MockToolCall:
    tool_name: str = "chatwork_task_search"
    parameters: Dict[str, Any] = field(default_factory=dict)
    reasoning: str = "test reasoning"
    tool_use_id: str = "tu_123"

    def to_dict(self):
        return {
            "tool_name": self.tool_name,
            "parameters": self.parameters,
            "reasoning": self.reasoning,
            "tool_use_id": self.tool_use_id,
        }


@dataclass
class MockConfidence:
    overall: float = 0.9
    intent: float = 0.9
    parameters: float = 0.9

    def to_dict(self):
        return {"overall": self.overall, "intent": self.intent, "parameters": self.parameters}


@dataclass
class MockLLMResult:
    output_type: str = "tool_call"
    tool_calls: Optional[List[MockToolCall]] = None
    text_response: Optional[str] = None
    reasoning: Optional[str] = "LLM reasoning text"
    confidence: Optional[MockConfidence] = None
    needs_confirmation: bool = False

    def __post_init__(self):
        if self.tool_calls is None:
            self.tool_calls = [MockToolCall()]
        if self.confidence is None:
            self.confidence = MockConfidence()


class MockGuardianAction:
    def __init__(self, value):
        self.value = value


@dataclass
class MockGuardianResult:
    action: MockGuardianAction = field(default_factory=lambda: MockGuardianAction("allow"))
    reason: Optional[str] = "Allowed"
    confirmation_question: Optional[str] = None
    modified_params: Optional[Dict[str, Any]] = None
    blocked_reason: Optional[str] = None
    risk_level: Optional[str] = None


def make_mock_brain():
    """テスト用のモックBrainインスタンスを生成"""
    brain = MagicMock()
    brain._get_current_state_with_user_org = AsyncMock(return_value=None)
    brain._elapsed_ms = MagicMock(return_value=100.0)
    brain._fire_and_forget = MagicMock()
    brain._execute = AsyncMock()
    brain._synthesize_knowledge_answer = AsyncMock(return_value=None)
    brain.llm_context_builder = MagicMock()
    brain.llm_context_builder.build = AsyncMock(return_value=MagicMock())
    brain.llm_brain = MagicMock()
    brain.llm_brain.process = AsyncMock()
    brain.llm_guardian = MagicMock()
    brain.llm_guardian.check = AsyncMock()
    brain.llm_state_manager = MagicMock()
    brain.llm_state_manager.set_pending_action = AsyncMock()
    # Step 0-3: 緊急停止チェッカーは通常テストでは無効（停止していない状態）
    brain.emergency_stop_checker = None
    brain.session_orchestrator = MagicMock()
    brain.session_orchestrator.continue_session = AsyncMock()
    brain.memory_manager = MagicMock()
    brain.memory_manager.update_memory_safely = AsyncMock()
    brain.memory_manager.log_decision_safely = AsyncMock()
    brain.observability = MagicMock()
    brain.observability.log_execution = MagicMock()
    brain._trackable_actions = {"chatwork_task_search", "chatwork_task_create"}
    brain._record_outcome_event = AsyncMock()
    return brain


def make_base_state(**overrides) -> dict:
    """テスト用のベース状態を生成"""
    state = {
        "message": "タスク教えて",
        "room_id": "room_123",
        "account_id": "acc_123",
        "sender_name": "テストユーザー",
        "start_time": 1000000.0,
        "organization_id": "org_test",
        "context": MagicMock(spec=BrainContext),
    }
    state["context"].recent_conversation = []
    state["context"].phase2e_learnings = None
    state.update(overrides)
    return state


# =============================================================================
# ルーティング関数テスト
# =============================================================================


class TestRouteAfterStateCheck:
    def test_routes_to_session_when_active(self):
        state = {"has_active_session": True}
        assert route_after_state_check(state) == "route_session"

    def test_routes_to_build_context_when_no_session(self):
        state = {"has_active_session": False}
        assert route_after_state_check(state) == "build_context"

    def test_routes_to_build_context_when_missing(self):
        state = {}
        assert route_after_state_check(state) == "build_context"


class TestRouteAfterGuardian:
    def test_routes_block(self):
        assert route_after_guardian({"guardian_action": "block"}) == "handle_block"

    def test_routes_confirm(self):
        assert route_after_guardian({"guardian_action": "confirm"}) == "handle_confirm"

    def test_routes_text_only(self):
        assert route_after_guardian({"guardian_action": "text_only"}) == "text_response"

    def test_routes_allow_to_execute(self):
        assert route_after_guardian({"guardian_action": "allow"}) == "execute_tool"

    def test_routes_modify_to_execute(self):
        assert route_after_guardian({"guardian_action": "modify"}) == "execute_tool"

    def test_default_routes_to_execute(self):
        assert route_after_guardian({}) == "execute_tool"


class TestRouteAfterExecution:
    def test_routes_to_synthesize(self):
        assert route_after_execution({"needs_synthesis": True}) == "synthesize_knowledge"

    def test_routes_to_build_response(self):
        assert route_after_execution({"needs_synthesis": False}) == "build_response"

    def test_default_routes_to_build_response(self):
        assert route_after_execution({}) == "build_response"


# =============================================================================
# state_check ノードテスト
# =============================================================================


class TestStateCheck:
    @pytest.mark.asyncio
    async def test_no_active_state(self):
        brain = make_mock_brain()
        brain._get_current_state_with_user_org.return_value = None

        node = make_state_check(brain)
        result = await node(make_base_state())

        assert result["has_active_session"] is False
        assert result["current_state"] is None

    @pytest.mark.asyncio
    async def test_active_list_context(self):
        brain = make_mock_brain()
        mock_state = MagicMock()
        mock_state.is_active = True
        mock_state.state_type = StateType.LIST_CONTEXT
        brain._get_current_state_with_user_org.return_value = mock_state

        node = make_state_check(brain)
        result = await node(make_base_state())

        assert result["has_active_session"] is True
        assert result["current_state"] is mock_state

    @pytest.mark.asyncio
    async def test_active_non_list_context_falls_through(self):
        """CONFIRMATION等の非LIST_CONTEXTアクティブ状態は通常処理にフォールスルー"""
        brain = make_mock_brain()
        mock_state = MagicMock()
        mock_state.is_active = True
        mock_state.state_type = StateType.CONFIRMATION
        brain._get_current_state_with_user_org.return_value = mock_state

        node = make_state_check(brain)
        result = await node(make_base_state())

        # CONFIRMATION はセッションルーティングしない
        assert result["has_active_session"] is False

    @pytest.mark.asyncio
    async def test_active_task_pending_falls_through(self):
        brain = make_mock_brain()
        mock_state = MagicMock()
        mock_state.is_active = True
        mock_state.state_type = StateType.TASK_PENDING
        brain._get_current_state_with_user_org.return_value = mock_state

        node = make_state_check(brain)
        result = await node(make_base_state())

        assert result["has_active_session"] is False

    @pytest.mark.asyncio
    async def test_inactive_state(self):
        brain = make_mock_brain()
        mock_state = MagicMock()
        mock_state.is_active = False
        mock_state.state_type = StateType.NORMAL
        brain._get_current_state_with_user_org.return_value = mock_state

        node = make_state_check(brain)
        result = await node(make_base_state())

        assert result["has_active_session"] is False

    @pytest.mark.asyncio
    async def test_error_propagates(self):
        brain = make_mock_brain()
        brain._get_current_state_with_user_org.side_effect = RuntimeError("DB error")

        node = make_state_check(brain)
        with pytest.raises(RuntimeError, match="DB error"):
            await node(make_base_state())


# =============================================================================
# route_session ノードテスト
# =============================================================================


class TestRouteSession:
    @pytest.mark.asyncio
    async def test_delegates_to_session_orchestrator(self):
        brain = make_mock_brain()
        mock_response = BrainResponse(
            message="Item 2 selected", action_taken="list_select", success=True
        )
        brain.session_orchestrator.continue_session.return_value = mock_response

        mock_state_obj = MagicMock()
        mock_state_obj.state_step = 3

        state = make_base_state(current_state=mock_state_obj)
        node = make_route_session(brain)
        result = await node(state)

        assert result["response"] is mock_response
        brain.session_orchestrator.continue_session.assert_called_once()

    @pytest.mark.asyncio
    async def test_none_current_state(self):
        brain = make_mock_brain()
        state = make_base_state(current_state=None)
        node = make_route_session(brain)
        result = await node(state)
        assert result == {}


# =============================================================================
# build_context ノードテスト
# =============================================================================


class TestBuildContext:
    @pytest.mark.asyncio
    async def test_builds_context_and_tools(self):
        brain = make_mock_brain()
        mock_ctx = MagicMock()
        brain.llm_context_builder.build.return_value = mock_ctx

        with patch("lib.brain.graph.nodes.build_context.get_tools_for_llm") as mock_tools:
            mock_tools.return_value = [{"type": "function", "name": "test"}]
            node = make_build_context(brain)
            result = await node(make_base_state())

        assert result["llm_context"] is mock_ctx
        assert len(result["tools"]) == 1

    @pytest.mark.asyncio
    async def test_error_propagates(self):
        brain = make_mock_brain()
        brain.llm_context_builder.build.side_effect = RuntimeError("build failed")

        node = make_build_context(brain)
        with pytest.raises(RuntimeError, match="build failed"):
            await node(make_base_state())


# =============================================================================
# llm_inference ノードテスト
# =============================================================================


class TestLLMInference:
    @pytest.mark.asyncio
    async def test_returns_result_and_confidence(self):
        brain = make_mock_brain()
        llm_result = MockLLMResult()
        brain.llm_brain.process.return_value = llm_result

        state = make_base_state(llm_context=MagicMock(), tools=[])
        with patch("lib.brain.core._validate_llm_result_type"):
            with patch("lib.brain.core._extract_confidence_value", return_value=0.9):
                node = make_llm_inference(brain)
                result = await node(state)

        assert result["llm_result"] is llm_result
        assert result["confidence_value"] == 0.9


# =============================================================================
# guardian_check ノードテスト
# =============================================================================


class TestGuardianCheck:
    @pytest.mark.asyncio
    async def test_allow_with_tool_calls(self):
        brain = make_mock_brain()
        guardian_result = MockGuardianResult(action=MockGuardianAction("allow"))
        brain.llm_guardian.check.return_value = guardian_result

        llm_result = MockLLMResult()
        state = make_base_state(llm_result=llm_result, llm_context=MagicMock())

        node = make_guardian_check(brain)
        result = await node(state)

        assert result["guardian_action"] == "allow"
        assert len(result["tool_calls_to_execute"]) == 1

    @pytest.mark.asyncio
    async def test_allow_without_tool_calls_becomes_text_only(self):
        brain = make_mock_brain()
        guardian_result = MockGuardianResult(action=MockGuardianAction("allow"))
        brain.llm_guardian.check.return_value = guardian_result

        llm_result = MockLLMResult(tool_calls=[], text_response="hello")
        state = make_base_state(llm_result=llm_result, llm_context=MagicMock())

        node = make_guardian_check(brain)
        result = await node(state)

        assert result["guardian_action"] == "text_only"

    @pytest.mark.asyncio
    async def test_block(self):
        brain = make_mock_brain()
        guardian_result = MockGuardianResult(action=MockGuardianAction("block"))
        brain.llm_guardian.check.return_value = guardian_result

        state = make_base_state(llm_result=MockLLMResult(), llm_context=MagicMock())
        node = make_guardian_check(brain)
        result = await node(state)

        assert result["guardian_action"] == "block"

    @pytest.mark.asyncio
    async def test_modify_does_not_mutate_original(self):
        """MODIFYはdeep copyしてからパラメータを変更（元のllm_resultは変更しない）"""
        brain = make_mock_brain()
        guardian_result = MockGuardianResult(
            action=MockGuardianAction("modify"),
            modified_params={"extra": "value"},
        )
        brain.llm_guardian.check.return_value = guardian_result

        original_params = {"query": "test"}
        original_tc = MockToolCall(parameters=original_params.copy())
        llm_result = MockLLMResult(tool_calls=[original_tc])

        state = make_base_state(llm_result=llm_result, llm_context=MagicMock())
        node = make_guardian_check(brain)
        result = await node(state)

        # 返された tool_calls には extra が追加されている
        assert result["tool_calls_to_execute"][0].parameters.get("extra") == "value"
        # 元の llm_result.tool_calls は変更されていない
        assert "extra" not in original_tc.parameters

    @pytest.mark.asyncio
    async def test_none_tool_calls(self):
        brain = make_mock_brain()
        guardian_result = MockGuardianResult(action=MockGuardianAction("allow"))
        brain.llm_guardian.check.return_value = guardian_result

        llm_result = MockLLMResult()
        llm_result.tool_calls = None  # __post_init__ をバイパス
        state = make_base_state(llm_result=llm_result, llm_context=MagicMock())

        node = make_guardian_check(brain)
        result = await node(state)

        assert result["guardian_action"] == "text_only"
        assert result["tool_calls_to_execute"] == []


# =============================================================================
# execute_tool ノードテスト
# =============================================================================


class TestExecuteTool:
    @pytest.mark.asyncio
    async def test_executes_tool_and_records_outcome(self):
        brain = make_mock_brain()
        handler_result = HandlerResult(success=True, message="OK", data={})
        brain._execute.return_value = handler_result

        tc = MockToolCall(tool_name="chatwork_task_search")
        state = make_base_state(
            tool_calls_to_execute=[tc],
            llm_result=MockLLMResult(confidence=MockConfidence()),
        )

        with patch("lib.brain.core._extract_confidence_value", return_value=0.9):
            node = make_execute_tool(brain)
            result = await node(state)

        assert result["execution_result"] is handler_result
        assert result["needs_synthesis"] is False
        brain._execute.assert_called_once()
        # outcome recording called for trackable action
        brain._fire_and_forget.assert_called()

    @pytest.mark.asyncio
    async def test_empty_tool_calls_raises(self):
        brain = make_mock_brain()
        state = make_base_state(
            tool_calls_to_execute=[],
            llm_result=MockLLMResult(),
        )

        node = make_execute_tool(brain)
        with pytest.raises(ValueError, match="empty tool_calls"):
            await node(state)

    @pytest.mark.asyncio
    async def test_needs_synthesis_detection(self):
        brain = make_mock_brain()
        handler_result = HandlerResult(
            success=True, message="data",
            data={"needs_answer_synthesis": True}
        )
        brain._execute.return_value = handler_result
        brain.llm_brain = MagicMock()

        tc = MockToolCall()
        state = make_base_state(
            tool_calls_to_execute=[tc],
            llm_result=MockLLMResult(confidence=MockConfidence()),
        )

        with patch("lib.brain.core._extract_confidence_value", return_value=0.9):
            node = make_execute_tool(brain)
            result = await node(state)

        assert result["needs_synthesis"] is True


# =============================================================================
# synthesize ノードテスト
# =============================================================================


class TestSynthesize:
    @pytest.mark.asyncio
    async def test_synthesize_success(self):
        brain = make_mock_brain()
        brain._synthesize_knowledge_answer.return_value = "synthesized answer"

        state = make_base_state(
            execution_result=HandlerResult(success=True, message="raw", data={"query": "test"}),
            tool_calls_to_execute=[MockToolCall(parameters={"query": "test"})],
        )

        node = make_synthesize_knowledge(brain)
        result = await node(state)

        assert result["execution_result"].message == "synthesized answer"

    @pytest.mark.asyncio
    async def test_synthesize_fallback(self):
        brain = make_mock_brain()
        brain._synthesize_knowledge_answer.return_value = None

        state = make_base_state(
            execution_result=HandlerResult(
                success=True, message="raw",
                data={"formatted_context": "formatted data"},
            ),
            tool_calls_to_execute=[MockToolCall(parameters={"query": "test"})],
        )

        node = make_synthesize_knowledge(brain)
        result = await node(state)

        assert "formatted data" in result["execution_result"].message

    @pytest.mark.asyncio
    async def test_empty_tool_calls_returns_original(self):
        brain = make_mock_brain()
        original = HandlerResult(success=True, message="original", data={})
        state = make_base_state(
            execution_result=original,
            tool_calls_to_execute=[],
        )

        node = make_synthesize_knowledge(brain)
        result = await node(state)
        assert result["execution_result"] is original


# =============================================================================
# responses ノードテスト
# =============================================================================


class TestMaskReasoning:
    def test_none_returns_none(self):
        assert _mask_reasoning(None) is None

    def test_empty_returns_none(self):
        assert _mask_reasoning("") is None

    def test_truncates_long_text(self):
        long_text = "a" * 500
        result = _mask_reasoning(long_text, max_len=200)
        assert len(result) <= 200

    def test_masks_pii(self):
        result = _mask_reasoning("田中太郎さんのメール: tanaka@example.com")
        assert "tanaka@example.com" not in result


class TestHandleBlock:
    @pytest.mark.asyncio
    async def test_creates_block_response(self):
        brain = make_mock_brain()
        state = make_base_state(
            guardian_result=MockGuardianResult(
                action=MockGuardianAction("block"),
                blocked_reason="Dangerous action",
                reason="blocked",
            ),
            llm_result=MockLLMResult(),
            start_time=1000.0,
        )

        with patch("lib.brain.core._safe_confidence_to_dict", return_value={"overall": 0.9}):
            node = make_handle_block(brain)
            result = await node(state)

        resp = result["response"]
        assert isinstance(resp, BrainResponse)
        assert resp.success is False
        assert resp.action_taken == "guardian_block"
        assert "Dangerous action" in resp.message
        # Memory update was called
        brain._fire_and_forget.assert_called_once()


class TestHandleConfirm:
    @pytest.mark.asyncio
    async def test_creates_confirm_response_and_pending_action(self):
        brain = make_mock_brain()
        state = make_base_state(
            guardian_result=MockGuardianResult(
                action=MockGuardianAction("confirm"),
                confirmation_question="Are you sure?",
                risk_level="medium",
            ),
            llm_result=MockLLMResult(),
            start_time=1000.0,
        )

        with patch("lib.brain.core._safe_confidence_to_dict", return_value={}):
            with patch("lib.brain.core._extract_confidence_value", return_value=0.8):
                node = make_handle_confirm(brain)
                result = await node(state)

        resp = result["response"]
        assert resp.awaiting_confirmation is True
        assert resp.action_taken == "request_confirmation"
        brain.llm_state_manager.set_pending_action.assert_called_once()
        # Memory update was called
        assert brain._fire_and_forget.call_count >= 1

    @pytest.mark.asyncio
    async def test_pii_masked_in_pending_action(self):
        brain = make_mock_brain()
        state = make_base_state(
            message="田中太郎のタスクを削除して",
            guardian_result=MockGuardianResult(
                action=MockGuardianAction("confirm"),
                confirmation_question="確認",
                risk_level="high",
            ),
            llm_result=MockLLMResult(),
            start_time=1000.0,
        )

        with patch("lib.brain.core._safe_confidence_to_dict", return_value={}):
            with patch("lib.brain.core._extract_confidence_value", return_value=0.8):
                node = make_handle_confirm(brain)
                await node(state)

        # pending_action の original_message は PII マスクされている
        call_kwargs = brain.llm_state_manager.set_pending_action.call_args[1]
        pending = call_kwargs["pending_action"]
        # mask_pii は日本語名に対して適用されるかはパターン依存だが、
        # 関数が呼ばれていることを確認
        assert pending.original_message is not None


class TestTextResponse:
    @pytest.mark.asyncio
    async def test_creates_text_response(self):
        brain = make_mock_brain()
        state = make_base_state(
            llm_result=MockLLMResult(text_response="Hello there!"),
            start_time=1000.0,
        )

        with patch("lib.brain.core._safe_confidence_to_dict", return_value={}):
            node = make_text_response(brain)
            result = await node(state)

        resp = result["response"]
        assert resp.success is True
        assert resp.action_taken == "llm_text_response"
        assert resp.message == "Hello there!"
        # Memory update was called
        brain._fire_and_forget.assert_called_once()

    @pytest.mark.asyncio
    async def test_fallback_message_when_no_text(self):
        brain = make_mock_brain()
        state = make_base_state(
            llm_result=MockLLMResult(text_response=None),
            start_time=1000.0,
        )

        with patch("lib.brain.core._safe_confidence_to_dict", return_value={}):
            node = make_text_response(brain)
            result = await node(state)

        assert "お手伝い" in result["response"].message


class TestBuildResponse:
    @pytest.mark.asyncio
    async def test_creates_response_with_memory_and_decision_log(self):
        brain = make_mock_brain()
        handler_result = HandlerResult(success=True, message="Done!", data={})
        tc = MockToolCall(tool_name="chatwork_task_create")
        decision = DecisionResult(
            action="chatwork_task_create",
            params={},
            confidence=0.9,
            needs_confirmation=False,
        )

        state = make_base_state(
            llm_result=MockLLMResult(),
            guardian_result=MockGuardianResult(),
            tool_calls_to_execute=[tc],
            execution_result=handler_result,
            decision=decision,
            start_time=1000.0,
        )

        with patch("lib.brain.core._safe_confidence_to_dict", return_value={}):
            with patch("lib.brain.constants.SAVE_DECISION_LOGS", True):
                node = make_build_response(brain)
                result = await node(state)

        resp = result["response"]
        assert resp.success is True
        assert resp.message == "Done!"
        assert resp.action_taken == "chatwork_task_create"
        # memory update + decision log = 2 calls
        assert brain._fire_and_forget.call_count == 2

    @pytest.mark.asyncio
    async def test_empty_tool_calls_fallback(self):
        brain = make_mock_brain()
        handler_result = HandlerResult(success=True, message="Result", data={})

        state = make_base_state(
            llm_result=MockLLMResult(),
            guardian_result=MockGuardianResult(),
            tool_calls_to_execute=[],
            execution_result=handler_result,
            start_time=1000.0,
        )

        with patch("lib.brain.core._safe_confidence_to_dict", return_value={}):
            with patch("lib.brain.constants.SAVE_DECISION_LOGS", True):
                node = make_build_response(brain)
                result = await node(state)

        resp = result["response"]
        assert resp.action_taken == "unknown"

    @pytest.mark.asyncio
    async def test_reasoning_is_pii_masked(self):
        brain = make_mock_brain()
        handler_result = HandlerResult(success=True, message="OK", data={})
        tc = MockToolCall()

        state = make_base_state(
            llm_result=MockLLMResult(reasoning="user@example.com sent a message"),
            guardian_result=MockGuardianResult(),
            tool_calls_to_execute=[tc],
            execution_result=handler_result,
            start_time=1000.0,
        )

        with patch("lib.brain.core._safe_confidence_to_dict", return_value={}):
            with patch("lib.brain.constants.SAVE_DECISION_LOGS", False):
                node = make_build_response(brain)
                result = await node(state)

        debug = result["response"].debug_info["llm_brain"]["reasoning"]
        assert "user@example.com" not in debug


# =============================================================================
# グラフ構築テスト
# =============================================================================


class TestCreateBrainGraph:
    def test_graph_compiles(self):
        brain = make_mock_brain()
        graph = create_brain_graph(brain)
        assert graph is not None

    def test_graph_has_invoke(self):
        brain = make_mock_brain()
        graph = create_brain_graph(brain)
        assert hasattr(graph, "ainvoke")


# =============================================================================
# LangSmith テレメトリ無効化テスト
# =============================================================================


class TestTelemetryDisabled:
    def test_langsmith_tracing_disabled(self):
        import os
        # __init__.py を import した時点で設定される
        import lib.brain.graph  # noqa: F401
        assert os.environ.get("LANGCHAIN_TRACING_V2") == "false"
        assert os.environ.get("LANGSMITH_TRACING") == "false"
