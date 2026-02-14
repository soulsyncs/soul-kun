# lib/brain/graph/nodes/state_check.py
"""
ノード: アクティブセッション確認

LIST_CONTEXTのアクティブセッションがある場合、
SessionOrchestratorに委譲して早期リターンする。

NOTE: 元の _process_with_llm_brain() は LIST_CONTEXT のみを
特別ルーティングし、他のアクティブ状態（CONFIRMATION,
TASK_PENDING等）は通常のLLM処理へフォールスルーさせていた。
この動作を忠実に再現する。
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

            # LIST_CONTEXTのみセッションルーティング対象
            # 他のアクティブ状態は通常のLLM処理にフォールスルー（元の動作と同一）
            has_active = bool(
                current_state
                and current_state.is_active
                and current_state.state_type == StateType.LIST_CONTEXT
            )

            return {
                "current_state": current_state,
                "has_active_session": has_active,
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
