# lib/brain/graph/nodes/guardian_check.py
"""
ノード: Guardian Layer 検証 + 緊急停止 + 承認ゲート

LLM の提案を安全性チェック。
ALLOW / CONFIRM / BLOCK / MODIFY の4つの判定を返す。

処理順序:
1. 緊急停止チェック（Step 0-3）→ 停止中なら即ブロック
2. Guardian Layer判定（既存）
3. 承認ゲート（Step 0-1）→ 中リスク以上は確認フローへ

NOTE: MODIFY時は tool_calls を deepcopy してからパラメータを更新。
LangGraph の state 不変契約を守るため、入力 state を直接変更しない。
"""

import asyncio
import copy
import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lib.brain.core import SoulkunBrain

from lib.brain.approval_gate import get_approval_gate, ApprovalLevel
from lib.brain.guardian_layer import GuardianAction, GuardianResult
from lib.brain.graph.state import BrainGraphState

logger = logging.getLogger(__name__)


def make_guardian_check(brain: "SoulkunBrain"):
    """SoulkunBrainを参照するguardian_checkノードを生成"""

    async def guardian_check(state: BrainGraphState) -> dict:
        start_time = state["start_time"]
        llm_result = state["llm_result"]
        llm_context = state["llm_context"]

        try:
            # --- Step 0-3: 緊急停止チェック（最優先） ---
            emergency_checker = getattr(brain, "emergency_stop_checker", None)
            if emergency_checker is not None:
                is_stopped = await asyncio.to_thread(emergency_checker.is_stopped)
                if is_stopped:
                    logger.warning(
                        "[graph:guardian_check] EMERGENCY STOP ACTIVE — blocking all tool execution"
                    )
                    blocked_result = GuardianResult(
                        action=GuardianAction.BLOCK,
                        reason="緊急停止が有効です。管理者が解除するまでTool実行はブロックされます。",
                        blocked_reason="emergency_stop_active",
                    )
                    return {
                        "guardian_result": blocked_result,
                        "guardian_action": "block",
                        "tool_calls_to_execute": [],
                        "approval_result": None,
                    }

            t0 = time.time()
            guardian_result = await brain.llm_guardian.check(llm_result, llm_context)
            logger.debug(
                "[graph:guardian_check] DONE t=%.3fs (took %.3fs)",
                time.time() - start_time, time.time() - t0,
            )

            logger.info(
                "Guardian result: action=%s, reason=%s...",
                guardian_result.action.value,
                (guardian_result.reason[:50] if guardian_result.reason else "N/A"),
            )

            action_str = guardian_result.action.value  # "allow", "block", "confirm", "modify"

            # deepcopy して元の llm_result.tool_calls を変更しない
            tool_calls = copy.deepcopy(llm_result.tool_calls) if llm_result.tool_calls else []

            # MODIFY: パラメータを修正して実行に進む
            if action_str == "modify" and tool_calls and guardian_result.modified_params:
                tool_calls[0].parameters.update(guardian_result.modified_params)

            # Tool呼び出しなし → テキスト応答
            if action_str in ("allow", "modify") and not tool_calls:
                action_str = "text_only"

            # --- Step 0-1: 承認ゲートによるリスク判定 ---
            # Guardian Layer が allow/modify したTool呼び出しに対して、
            # リスクレベルに応じた承認チェックを追加
            approval_result = None
            if action_str in ("allow", "modify") and tool_calls:
                gate = get_approval_gate()
                first_tool = tool_calls[0]
                tool_name = getattr(first_tool, "tool_name", getattr(first_tool, "name", "unknown"))
                approval_result = gate.check(
                    tool_name,
                    first_tool.parameters if hasattr(first_tool, "parameters") else {},
                )
                # 確認が必要な場合、guardian_action を "confirm" にエスカレーション
                if approval_result.level in (
                    ApprovalLevel.REQUIRE_CONFIRMATION,
                    ApprovalLevel.REQUIRE_DOUBLE_CHECK,
                ):
                    action_str = "confirm"
                    logger.info(
                        "ApprovalGate escalated to confirm: tool=%s level=%s",
                        tool_name,
                        approval_result.level.value,
                    )

            return {
                "guardian_result": guardian_result,
                "guardian_action": action_str,
                "tool_calls_to_execute": tool_calls,
                "approval_result": approval_result,
            }
        except Exception as e:
            logger.error("[graph:guardian_check] Error: %s", e, exc_info=True)
            raise

    return guardian_check
