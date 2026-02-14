# lib/brain/graph/nodes/responses.py
"""
ノード: レスポンス生成

各分岐の最終ステップで BrainResponse を構築する。
- handle_block: Guardianがブロックした場合
- handle_confirm: Guardianが確認を求めた場合
- text_response: Tool呼び出しなし（テキスト応答のみ）
- build_response: Tool実行後の最終応答

全パスで記憶更新（fire-and-forget）を実行。
debug_info 内の reasoning には mask_pii() を適用（CLAUDE.md §9-4）。
"""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lib.brain.core import SoulkunBrain

from lib.brain.graph.state import BrainGraphState
from lib.brain.models import BrainResponse, HandlerResult
from lib.brain.memory_sanitizer import mask_pii

logger = logging.getLogger(__name__)


def _mask_reasoning(reasoning: str | None, max_len: int = 200) -> str | None:
    """reasoning を切り詰め + PII マスク"""
    if not reasoning:
        return None
    truncated = reasoning[:max_len]
    masked, _ = mask_pii(truncated)
    return masked


def make_handle_block(brain: "SoulkunBrain"):
    """Guardianブロック時のレスポンス生成"""

    async def handle_block(state: BrainGraphState) -> dict:
        from lib.brain.core import _safe_confidence_to_dict

        guardian_result = state["guardian_result"]
        llm_result = state["llm_result"]
        start_time = state["start_time"]

        try:
            block_message = (
                guardian_result.blocked_reason
                or guardian_result.reason
                or "その操作は実行できませんウル"
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
                        "reasoning": _mask_reasoning(llm_result.reasoning),
                    },
                    "guardian": {
                        "action": guardian_result.action.value,
                        "reason": guardian_result.reason,
                    },
                },
                total_time_ms=brain._elapsed_ms(start_time),
            )

            # 記憶更新（fire-and-forget）
            minimal_result = HandlerResult(success=False, message=block_message)
            brain._fire_and_forget(
                brain.memory_manager.update_memory_safely(
                    state["message"], minimal_result, state["context"],
                    state["room_id"], state["account_id"], state["sender_name"],
                )
            )

            return {"response": response}
        except Exception as e:
            logger.error("[graph:handle_block] Error: %s", e, exc_info=True)
            raise

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

        try:
            tool_call = llm_result.tool_calls[0] if llm_result.tool_calls else None
            confirm_question = (
                guardian_result.confirmation_question
                or guardian_result.reason
                or "確認させてほしいウル"
            )

            confirm_confidence = _extract_confidence_value(
                llm_result.confidence, "graph:handle_confirm:confidence"
            )

            # original_message にも PII マスクを適用
            masked_message, _ = mask_pii(state["message"])

            pending_action = LLMPendingAction(
                action_id=str(uuid_mod.uuid4()),
                tool_name=tool_call.tool_name if tool_call else "",
                parameters=tool_call.parameters if tool_call else {},
                confirmation_question=confirm_question,
                confirmation_type=guardian_result.risk_level or "ambiguous",
                original_message=masked_message,
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

            # 記憶更新（fire-and-forget）
            minimal_result = HandlerResult(success=True, message=confirm_question)
            brain._fire_and_forget(
                brain.memory_manager.update_memory_safely(
                    state["message"], minimal_result, state["context"],
                    state["room_id"], state["account_id"], state["sender_name"],
                )
            )

            return {"response": response}
        except Exception as e:
            logger.error("[graph:handle_confirm] Error: %s", e, exc_info=True)
            raise

    return handle_confirm


def make_text_response(brain: "SoulkunBrain"):
    """テキスト応答のみ（Tool呼び出しなし）のレスポンス生成"""

    async def text_response(state: BrainGraphState) -> dict:
        from lib.brain.core import _safe_confidence_to_dict

        llm_result = state["llm_result"]
        start_time = state["start_time"]

        try:
            text_msg = llm_result.text_response or "お手伝いできることはありますかウル？"

            response = BrainResponse(
                message=text_msg,
                action_taken="llm_text_response",
                success=True,
                debug_info={
                    "llm_brain": {
                        "confidence": _safe_confidence_to_dict(
                            llm_result.confidence, "graph:text_response"
                        ),
                        "reasoning": _mask_reasoning(llm_result.reasoning),
                    },
                },
                total_time_ms=brain._elapsed_ms(start_time),
            )

            # 記憶更新（fire-and-forget）
            minimal_result = HandlerResult(success=True, message=text_msg)
            brain._fire_and_forget(
                brain.memory_manager.update_memory_safely(
                    state["message"], minimal_result, state["context"],
                    state["room_id"], state["account_id"], state["sender_name"],
                )
            )

            return {"response": response}
        except Exception as e:
            logger.error("[graph:text_response] Error: %s", e, exc_info=True)
            raise

    return text_response


def make_build_response(brain: "SoulkunBrain"):
    """Tool実行後の最終レスポンス生成 + 記憶更新 + 判断ログ"""

    async def build_response(state: BrainGraphState) -> dict:
        from lib.brain.core import _safe_confidence_to_dict
        from lib.brain.constants import SAVE_DECISION_LOGS

        llm_result = state["llm_result"]
        guardian_result = state["guardian_result"]
        tool_calls = state["tool_calls_to_execute"]
        result = state["execution_result"]
        start_time = state["start_time"]

        try:
            if not tool_calls:
                logger.error("[graph:build_response] tool_calls is empty")
                return {"response": BrainResponse(
                    message=result.message if result else "処理が完了したウル",
                    action_taken="unknown",
                    success=bool(result and result.success),
                    total_time_ms=brain._elapsed_ms(start_time),
                )}

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

            # 判断ログ記録（非同期）
            if SAVE_DECISION_LOGS:
                decision = state.get("decision")
                if decision:
                    brain._fire_and_forget(
                        brain.memory_manager.log_decision_safely(
                            state["message"],
                            None,  # understanding (LLM Brain パスでは不使用)
                            decision,
                            result,
                            state["room_id"],
                            state["account_id"],
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
                        "reasoning": _mask_reasoning(llm_result.reasoning),
                    },
                    "guardian": {
                        "action": guardian_result.action.value,
                    },
                },
                total_time_ms=brain._elapsed_ms(start_time),
            )
            return {"response": response}
        except Exception as e:
            logger.error("[graph:build_response] Error: %s", e, exc_info=True)
            raise

    return build_response
