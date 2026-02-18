# lib/brain/graph/nodes/state_check.py
"""
ノード: アクティブセッション確認

- LIST_CONTEXT → SessionOrchestratorに委譲
- CONFIRMATION → 確認応答を処理（ループ防止）
- その他 → 通常のLLM処理にフォールスルー
"""

import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lib.brain.core import SoulkunBrain

from lib.brain.graph.state import BrainGraphState

logger = logging.getLogger(__name__)


def make_state_check(brain: "SoulkunBrain"):
    """SoulkunBrainを参照するstate_checkノードを生成"""

    async def state_check(state: BrainGraphState) -> dict:
        from lib.brain.models import StateType

        start_time = state["start_time"]
        room_id = state["room_id"]
        account_id = state["account_id"]

        try:
            t0 = time.time()
            current_state = await brain._get_current_state_with_user_org(room_id, account_id)
            logger.debug(
                "[graph:state_check] DONE t=%.3fs (took %.3fs)",
                time.time() - start_time, time.time() - t0,
            )

            has_active = False
            has_pending_confirmation = False

            if current_state and current_state.is_active:
                if current_state.state_type == StateType.LIST_CONTEXT:
                    has_active = True
                elif current_state.state_type == StateType.CONFIRMATION:
                    has_pending_confirmation = True

            return {
                "current_state": current_state,
                "has_active_session": has_active,
                "has_pending_confirmation": has_pending_confirmation,
            }
        except Exception as e:
            logger.error("[graph:state_check] Error: %s", e, exc_info=True)
            raise

    return state_check


def make_route_session(brain: "SoulkunBrain"):
    """LIST_CONTEXTセッション時にSessionOrchestratorに委譲するノード"""

    async def route_session(state: BrainGraphState) -> dict:
        current_state = state["current_state"]
        if not current_state:
            logger.warning("[graph:route_session] current_state is None, returning empty")
            return {}

        try:
            logger.debug(
                "[graph:route_session] LIST_CONTEXT検出 step=%s",
                current_state.state_step,
            )
            response = await brain.session_orchestrator.continue_session(
                message=state["message"],
                state=current_state,
                context=state["context"],
                room_id=state["room_id"],
                account_id=state["account_id"],
                sender_name=state["sender_name"],
                start_time=state["start_time"],
            )
            return {"response": response}
        except Exception as e:
            logger.error("[graph:route_session] Error: %s", e, exc_info=True)
            raise

    return route_session


def make_handle_confirmation_response(brain: "SoulkunBrain"):
    """CONFIRMATION状態で確認応答（はい/いいえ）を処理するノード

    Guardianが確認要求を出し保存済みのツールコールを、
    ユーザーの応答に基づいて実行またはキャンセルする。
    LLMを再呼び出ししないことでループを防止する。
    """

    async def handle_confirmation_response(state: BrainGraphState) -> dict:
        from lib.brain.models import BrainResponse, DecisionResult

        message = state["message"]
        room_id = state["room_id"]
        account_id = state["account_id"]
        start_time = state["start_time"]

        try:
            # 承認/拒否を判定（状態はここでクリアされる）
            approved, pending_action = await brain.llm_state_manager.handle_confirmation_response(
                user_id=account_id,
                room_id=room_id,
                response=message,
            )

            if not approved:
                # キャンセル
                response = BrainResponse(
                    message="了解ウル、キャンセルしたウル🐺",
                    action_taken="confirmation_cancelled",
                    success=True,
                    total_time_ms=brain._elapsed_ms(start_time),
                )
                return {"response": response}

            if pending_action is None:
                response = BrainResponse(
                    message="確認待ちの操作が見つからなかったウル。もう一度お願いしてほしいウル🐺",
                    action_taken="confirmation_expired",
                    success=False,
                    total_time_ms=brain._elapsed_ms(start_time),
                )
                return {"response": response}

            # 承認された → 保存済みのツールコールを直接実行（Guardianスキップ）
            logger.info(
                "[graph:handle_confirmation_response] Approved: executing %s",
                pending_action.tool_name,
            )
            decision = DecisionResult(
                action=pending_action.tool_name,
                params=pending_action.parameters,
                confidence=pending_action.confidence or 0.9,
                needs_confirmation=False,
            )

            try:
                result = await brain._execute(
                    decision=decision,
                    context=state["context"],
                    room_id=room_id,
                    account_id=account_id,
                    sender_name=state["sender_name"],
                )
            except Exception as exec_err:
                # 実行失敗 → 保留アクションを復元して再試行可能にする
                logger.error(
                    "[graph:handle_confirmation_response] Execution failed, "
                    "restoring pending action: %s", exec_err,
                )
                await brain.llm_state_manager.set_pending_action(
                    user_id=account_id,
                    room_id=room_id,
                    pending_action=pending_action,
                )
                response = BrainResponse(
                    message="実行中にエラーが発生したウル。もう一度「はい」で再試行できるウル🐺",
                    action_taken="confirmation_execution_error",
                    success=False,
                    total_time_ms=brain._elapsed_ms(start_time),
                )
                return {"response": response}

            # 監査ログ記録（CLAUDE.md §3 鉄則#3: 監査ログ必須）
            try:
                from lib.brain.audit_bridge import log_tool_execution
                brain._fire_and_forget(
                    log_tool_execution(
                        organization_id=state.get("organization_id", ""),
                        tool_name=pending_action.tool_name,
                        account_id=account_id,
                        success=result.success,
                        risk_level="high",  # Guardian確認が必要だったツール
                        reasoning=f"User confirmed: {pending_action.confirmation_type}",
                        parameters=pending_action.parameters,
                        error_code=result.data.get("error_code") if result.data and not result.success else None,
                    )
                )
            except ImportError:
                logger.warning("[graph:handle_confirmation_response] audit_bridge not available")

            response = BrainResponse(
                message=result.message or "実行したウル🐺",
                action_taken=pending_action.tool_name,
                success=result.success,
                debug_info={
                    "confirmed_tool": pending_action.tool_name,
                },
                total_time_ms=brain._elapsed_ms(start_time),
            )
            return {"response": response}

        except Exception as e:
            logger.error(
                "[graph:handle_confirmation_response] Error: %s", e, exc_info=True
            )
            response = BrainResponse(
                message="確認応答の処理中にエラーが発生したウル🐺",
                action_taken="confirmation_error",
                success=False,
                total_time_ms=brain._elapsed_ms(start_time),
            )
            return {"response": response}

    return handle_confirmation_response
