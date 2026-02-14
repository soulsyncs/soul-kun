# lib/brain/graph/nodes/state_check.py
"""
ノード: アクティブセッション確認

LIST_CONTEXT等のアクティブセッションがある場合、
SessionOrchestratorに委譲して早期リターンする。
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
        start_time = state["start_time"]
        room_id = state["room_id"]
        account_id = state["account_id"]

        t0 = time.time()
        current_state = await brain._get_current_state_with_user_org(room_id, account_id)
        print(f"[DIAG] graph:state_check DONE t={time.time()-start_time:.3f}s (took {time.time()-t0:.3f}s)")

        has_active = bool(
            current_state
            and current_state.is_active
        )

        return {
            "current_state": current_state,
            "has_active_session": has_active,
        }

    return state_check


def make_route_session(brain: "SoulkunBrain"):
    """アクティブセッション時にSessionOrchestratorに委譲するノード"""

    async def route_session(state: BrainGraphState) -> dict:
        from lib.brain.models import StateType

        current_state = state["current_state"]
        if not current_state:
            return {}

        if current_state.state_type == StateType.LIST_CONTEXT:
            logger.debug(
                f"📋 LIST_CONTEXT状態検出 → セッション継続へルーティング: "
                f"step={current_state.state_step}"
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

        return {}

    return route_session
