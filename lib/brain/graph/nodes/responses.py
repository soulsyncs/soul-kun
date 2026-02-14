# lib/brain/graph/nodes/responses.py
"""
ノード: レスポンス生成

各分岐の最終ステップで BrainResponse を構築する。
- handle_block: Guardianがブロックした場合
- handle_confirm: Guardianが確認を求めた場合
- text_response: Tool呼び出しなし（テキスト応答のみ）
- build_response: Tool実行後の最終応答
"""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lib.brain.core import SoulkunBrain

from lib.brain.graph.state import BrainGraphState
from lib.brain.models import BrainResponse

logger = logging.getLogger(__name__)


def make_handle_block(brain: "SoulkunBrain"):
    """Guardianブロック時のレスポンス生成"""

    async def handle_block(state: BrainGraphState) -> dict:
        from lib.brain.core import _safe_confidence_to_dict

        guardian_result = state["guardian_result"]
        llm_result = state["llm_result"]
        start_time = state["start_time"]

        block_message = (
            guardian_result.blocked_reason
            or guardian_result.reason
            or "その操作は実行できませんウル🐺"
        )

        response = BrainResponse(
            message=block_message,
            action_taken="guardian_block",
            success=False,
            debug_info={
                "llm_brain": {
                    "tool_calls": [tc.to_dict() for tc in llm_result.tool_calls] if llm_result.tool_calls else [],
                    "confidence": _safe_confidence_to_dict(
                        llm_result.confidence, "graph:handle_block"
                    ),
                    "reasoning": llm_result.reasoning[:200] if llm_result.reasoning else None,
                },
                "guardian": {
                    "action": guardian_result.action.value,
                    "reason": guardian_result.reason,
                },
            },
            total_time_ms=brain._elapsed_ms(start_time),
        )
        return {"response": response}

    return handle_block


def make_handle_confirm(brain: "SoulkunBrain"):
    """Guardian確認要求時のレスポンス生成"""

    async def handle_confirm(state: BrainGraphState) -> dict:
        import uuid as uuid_mod
        from lib.brain.core import _extract_confidence_value, _safe_confidence_to_dict
        from lib.brain.state_manager import LLMPendingAction

        guardian_result = state["guardian_result"]
        llm_result = state["llm_result"]
        start_time = state["start_time"]

        tool_call = llm_result.tool_calls[0] if llm_result.tool_calls else None
        confirm_question = (
            guardian_result.confirmation_question
            or guardian_result.reason
            or "確認させてほしいウル🐺"
        )

        confirm_confidence = _extract_confidence_value(
            llm_result.confidence, "graph:handle_confirm:confidence"
        )

        pending_action = LLMPendingAction(
            action_id=str(uuid_mod.uuid4()),
            tool_name=tool_call.tool_name if tool_call else "",
            parameters=tool_call.parameters if tool_call else {},
            confirmation_question=confirm_question,
            confirmation_type=guardian_result.risk_level or "ambiguous",
            original_message=state["message"],
            original_reasoning=llm_result.reasoning or "",
            confidence=confirm_confidence,
        )
        await brain.llm_state_manager.set_pending_action(
            user_id=state["account_id"],
            room_id=state["room_id"],
            pending_action=pending_action,
        )

        response = BrainResponse(
            message=confirm_question,
            action_taken="request_confirmation",
            success=True,
            awaiting_confirmation=True,
            state_changed=True,
            new_state="llm_confirmation_pending",
            debug_info={
                "llm_brain": {
                    "tool_calls": [tc.to_dict() for tc in llm_result.tool_calls] if llm_result.tool_calls else [],
                    "confidence": _safe_confidence_to_dict(
                        llm_result.confidence, "graph:handle_confirm"
                    ),
                },
                "guardian": {
                    "action": guardian_result.action.value,
                    "reason": guardian_result.reason,
                },
            },
            total_time_ms=brain._elapsed_ms(start_time),
        )
        return {"response": response}

    return handle_confirm


def make_text_response(brain: "SoulkunBrain"):
    """テキスト応答のみ（Tool呼び出しなし）のレスポンス生成"""

    async def text_response(state: BrainGraphState) -> dict:
        from lib.brain.core import _safe_confidence_to_dict

        llm_result = state["llm_result"]
        start_time = state["start_time"]

        response = BrainResponse(
            message=llm_result.text_response or "お手伝いできることはありますかウル？🐺",
            action_taken="llm_text_response",
            success=True,
            debug_info={
                "llm_brain": {
                    "confidence": _safe_confidence_to_dict(
                        llm_result.confidence, "graph:text_response"
                    ),
                    "reasoning": llm_result.reasoning[:200] if llm_result.reasoning else None,
                },
            },
            total_time_ms=brain._elapsed_ms(start_time),
        )
        return {"response": response}

    return text_response


def make_build_response(brain: "SoulkunBrain"):
    """Tool実行後の最終レスポンス生成 + 記憶更新"""

    async def build_response(state: BrainGraphState) -> dict:
        from lib.brain.core import _safe_confidence_to_dict

        llm_result = state["llm_result"]
        guardian_result = state["guardian_result"]
        tool_calls = state["tool_calls_to_execute"]
        result = state["execution_result"]
        start_time = state["start_time"]
        tool_call = tool_calls[0]

        # 記憶更新（非同期）
        brain._fire_and_forget(
            brain.memory_manager.update_memory_safely(
                state["message"],
                result,
                state["context"],
                state["room_id"],
                state["account_id"],
                state["sender_name"],
            )
        )

        response = BrainResponse(
            message=result.message,
            action_taken=tool_call.tool_name,
            action_params=tool_call.parameters,
            success=result.success,
            suggestions=result.suggestions,
            debug_info={
                "llm_brain": {
                    "tool_calls": [tc.to_dict() for tc in tool_calls],
                    "confidence": _safe_confidence_to_dict(
                        llm_result.confidence, "graph:build_response"
                    ),
                    "reasoning": llm_result.reasoning[:200] if llm_result.reasoning else None,
                },
                "guardian": {
                    "action": guardian_result.action.value,
                },
            },
            total_time_ms=brain._elapsed_ms(start_time),
        )
        return {"response": response}

    return build_response
