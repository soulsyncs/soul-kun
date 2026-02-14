# lib/brain/graph/nodes/execute_tool.py
"""
ノード: Tool実行

GuardianがALLOW/MODIFYしたTool呼び出しを実行。
AuthorizationGate → BrainExecution の既存実行層を活用。
"""

import logging
import time
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lib.brain.core import SoulkunBrain

from lib.brain.graph.state import BrainGraphState
from lib.brain.models import DecisionResult, ConversationMessage

logger = logging.getLogger(__name__)


def make_execute_tool(brain: "SoulkunBrain"):
    """SoulkunBrainを参照するexecute_toolノードを生成"""

    async def execute_tool(state: BrainGraphState) -> dict:
        from lib.brain.core import _extract_confidence_value

        start_time = state["start_time"]
        tool_calls = state["tool_calls_to_execute"]
        llm_result = state["llm_result"]
        context = state["context"]

        # 最初のTool呼び出しを実行（複数Toolは将来対応）
        tool_call = tool_calls[0]

        # ハンドラーに元メッセージを渡すためcontext.recent_conversationに追加
        if not context.recent_conversation:
            context.recent_conversation = []
        context.recent_conversation.append(
            ConversationMessage(
                role="user",
                content=state["message"],
                timestamp=datetime.now(),
                sender_name=state["sender_name"],
            )
        )

        # DecisionResultを構築して既存のexecution層に渡す
        decision_confidence = _extract_confidence_value(
            llm_result.confidence,
            "graph:execute_tool:confidence"
        )
        decision = DecisionResult(
            action=tool_call.tool_name,
            params=tool_call.parameters,
            confidence=decision_confidence,
            needs_confirmation=False,  # Guardianで既にチェック済み
        )

        t0 = time.time()
        result = await brain._execute(
            decision=decision,
            context=context,
            room_id=state["room_id"],
            account_id=state["account_id"],
            sender_name=state["sender_name"],
        )
        print(f"[DIAG] graph:execute_tool DONE t={time.time()-start_time:.3f}s (took {time.time()-t0:.3f}s)")

        # 観測ログ
        brain.observability.log_execution(
            action=tool_call.tool_name,
            success=result.success,
            account_id=state["account_id"],
            execution_time_ms=brain._elapsed_ms(start_time),
            error_code=result.data.get("error_code") if result.data and not result.success else None,
        )

        # ナレッジ合成が必要か判定
        needs_synthesis = bool(
            result.success
            and result.data
            and isinstance(result.data, dict)
            and result.data.get("needs_answer_synthesis")
            and brain.llm_brain is not None
        )

        return {
            "decision": decision,
            "execution_result": result,
            "needs_synthesis": needs_synthesis,
        }

    return execute_tool
