# lib/brain/graph/nodes/build_context.py
"""
ノード: LLMコンテキスト構築

ContextBuilder.build() を呼び出して LLM に渡すコンテキストを構築。
メモリ、CEO教え、学習データを並列取得する。
"""

import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lib.brain.core import SoulkunBrain

from lib.brain.graph.state import BrainGraphState
from lib.brain.tool_converter import get_tools_for_llm

logger = logging.getLogger(__name__)


def make_build_context(brain: "SoulkunBrain"):
    """SoulkunBrainを参照するbuild_contextノードを生成"""

    async def build_context(state: BrainGraphState) -> dict:
        start_time = state["start_time"]
        context = state["context"]

        try:
            t0 = time.time()
            llm_context = await brain.llm_context_builder.build(
                user_id=state["account_id"],
                room_id=state["room_id"],
                organization_id=state["organization_id"],
                message=state["message"],
                sender_name=state["sender_name"],
                phase2e_learnings_prefetched=context.phase2e_learnings,
            )
            logger.debug(
                "[graph:build_context] DONE t=%.3fs (took %.3fs)",
                time.time() - start_time, time.time() - t0,
            )

            tools = get_tools_for_llm()
            logger.info("🧠 [DIAG] tools_for_llm: count=%d", len(tools))
            logger.debug(
                "🧠 [DIAG] tools_for_llm: names=%s",
                [t.get("name", "?") for t in tools] if tools else [],
            )

            return {
                "llm_context": llm_context,
                "tools": tools,
            }
        except Exception as e:
            logger.error("[graph:build_context] Error: %s", e, exc_info=True)
            raise

    return build_context
