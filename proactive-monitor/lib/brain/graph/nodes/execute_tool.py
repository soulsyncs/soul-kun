# lib/brain/graph/nodes/execute_tool.py
"""
ノード: Tool実行

GuardianがALLOW/MODIFYしたTool呼び出しを実行。
AuthorizationGate → BrainExecution の既存実行層を活用。

NOTE: context.recent_conversation への追加は新しいリストで行い、
入力 state の context を直接変更しない。
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


async def _log_tool_audit(**kwargs) -> bool:
    """audit_bridgeへの遅延import呼び出し（fire-and-forget用）"""
    try:
        from lib.brain.audit_bridge import log_tool_execution
        return await log_tool_execution(**kwargs)
    except Exception as e:
        logger.warning("[graph:execute_tool] audit_bridge failed: %s", e)
        return False


def make_execute_tool(brain: "SoulkunBrain"):
    """SoulkunBrainを参照するexecute_toolノードを生成"""

    async def execute_tool(state: BrainGraphState) -> dict:
        from lib.brain.core import _extract_confidence_value

        start_time = state["start_time"]
        tool_calls = state["tool_calls_to_execute"]
        llm_result = state["llm_result"]
        context = state["context"]

        try:
            # 防御チェック: tool_calls が空の場合
            if not tool_calls:
                logger.error("[graph:execute_tool] tool_calls is empty")
                raise ValueError("execute_tool called with empty tool_calls")

            # 最初のTool呼び出しを実行（複数Toolは将来対応）
            tool_call = tool_calls[0]

            # ハンドラーに元メッセージを渡すため conversation に追加
            # 新しいリストを作成して state 不変契約を守る
            recent = list(context.recent_conversation or [])
            recent.append(
                ConversationMessage(
                    role="user",
                    content=state["message"],
                    timestamp=datetime.now(),
                    sender_name=state["sender_name"],
                )
            )
            context.recent_conversation = recent

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
            logger.debug(
                "[graph:execute_tool] DONE t=%.3fs (took %.3fs)",
                time.time() - start_time, time.time() - t0,
            )

            # 観測ログ
            brain.observability.log_execution(
                action=tool_call.tool_name,
                success=result.success,
                account_id=state["account_id"],
                execution_time_ms=brain._elapsed_ms(start_time),
                error_code=result.data.get("error_code") if result.data and not result.success else None,
            )

            # Step 0-2: 監査ログ記録（fire-and-forget）
            approval_result = state.get("approval_result")
            risk_level = approval_result.risk_level if approval_result else "low"
            brain._fire_and_forget(
                _log_tool_audit(
                    organization_id=state["organization_id"],
                    tool_name=tool_call.tool_name,
                    account_id=state["account_id"],
                    success=result.success,
                    risk_level=risk_level,
                    reasoning=llm_result.reasoning,
                    parameters=tool_call.parameters,
                    error_code=result.data.get("error_code") if result.data and not result.success else None,
                )
            )

            # Phase 2F: アクション結果の学習記録（fire-and-forget）
            if getattr(brain, '_trackable_actions', None) and tool_call.tool_name in brain._trackable_actions:
                brain._fire_and_forget(
                    brain._record_outcome_event(
                        action=tool_call.tool_name,
                        target_account_id=state["account_id"],
                        target_room_id=state["room_id"],
                        action_params={
                            k: v for k, v in (tool_call.parameters or {}).items()
                            if k not in ("message", "body", "content", "text")
                        },
                        context_snapshot={
                            "intent": (llm_result.reasoning[:100] if llm_result.reasoning else None),
                        },
                    )
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
        except Exception as e:
            logger.error("[graph:execute_tool] Error: %s", e, exc_info=True)
            raise

    return execute_tool
