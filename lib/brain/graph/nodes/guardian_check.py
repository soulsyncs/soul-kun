# lib/brain/graph/nodes/guardian_check.py
"""
ノード: Guardian Layer 検証

LLM の提案を安全性チェック。
ALLOW / CONFIRM / BLOCK / MODIFY の4つの判定を返す。

NOTE: MODIFY時は tool_calls を deepcopy してからパラメータを更新。
LangGraph の state 不変契約を守るため、入力 state を直接変更しない。
"""

import copy
import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lib.brain.core import SoulkunBrain

from lib.brain.graph.state import BrainGraphState

logger = logging.getLogger(__name__)


def make_guardian_check(brain: "SoulkunBrain"):
    """SoulkunBrainを参照するguardian_checkノードを生成"""

    async def guardian_check(state: BrainGraphState) -> dict:
        start_time = state["start_time"]
        llm_result = state["llm_result"]
        llm_context = state["llm_context"]

        try:
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

            return {
                "guardian_result": guardian_result,
                "guardian_action": action_str,
                "tool_calls_to_execute": tool_calls,
            }
        except Exception as e:
            logger.error("[graph:guardian_check] Error: %s", e, exc_info=True)
            raise

    return guardian_check
