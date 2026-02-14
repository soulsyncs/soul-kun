# lib/brain/graph/nodes/llm_inference.py
"""
ノード: LLM Brain 推論

Claude API + Function Calling でメッセージを処理。
意図理解・Tool選択・テキスト応答生成を行う。
"""

import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lib.brain.core import SoulkunBrain

from lib.brain.graph.state import BrainGraphState

logger = logging.getLogger(__name__)


def make_llm_inference(brain: "SoulkunBrain"):
    """SoulkunBrainを参照するllm_inferenceノードを生成"""

    async def llm_inference(state: BrainGraphState) -> dict:
        from lib.brain.core import _validate_llm_result_type, _extract_confidence_value

        start_time = state["start_time"]

        try:
            t0 = time.time()
            llm_result = await brain.llm_brain.process(
                context=state["llm_context"],
                message=state["message"],
                tools=state["tools"],
            )
            logger.debug(
                "[graph:llm_inference] DONE t=%.3fs (took %.3fs)",
                time.time() - start_time, time.time() - t0,
            )

            # 境界型検証
            _validate_llm_result_type(llm_result, "graph:llm_inference")

            confidence_value = _extract_confidence_value(
                llm_result.confidence, "graph:llm_inference:confidence"
            )

            logger.info(
                "LLM Brain result: tool_calls=%d, has_text=%s, confidence=%.2f",
                len(llm_result.tool_calls or []),
                llm_result.text_response is not None,
                confidence_value,
            )

            return {
                "llm_result": llm_result,
                "confidence_value": confidence_value,
            }
        except Exception as e:
            logger.error("[graph:llm_inference] Error: %s", e, exc_info=True)
            raise

    return llm_inference
