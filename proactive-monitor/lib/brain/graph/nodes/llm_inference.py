# lib/brain/graph/nodes/llm_inference.py
"""
ノード: LLM Brain 推論

Claude API + Function Calling でメッセージを処理。
意図理解・Tool選択・テキスト応答生成を行う。
"""

import asyncio
import logging
import time
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lib.brain.core import SoulkunBrain

from lib.brain.graph.state import BrainGraphState

logger = logging.getLogger(__name__)


async def _log_llm_usage(pool, org_id: str, model_id: str,
                          input_tokens: int, output_tokens: int,
                          room_id: str, user_id: str) -> None:
    """LLM API利用ログをai_usage_logsに記録（非同期 + asyncio.to_thread）"""
    try:
        from lib.brain.model_orchestrator.usage_logger import UsageLogger
        from lib.brain.model_orchestrator.constants import Tier

        def _sync():
            ul = UsageLogger(pool=pool, organization_id=org_id)
            ul.log_usage(
                model_id=model_id,
                task_type="llm_brain_inference",
                tier=Tier.PREMIUM,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_jpy=Decimal("0"),  # TODO: 実コスト計算（model_orchestrator統合後）
                latency_ms=0,
                success=True,
                room_id=room_id,
                user_id=user_id,
            )
        await asyncio.to_thread(_sync)
    except Exception as e:
        logger.warning("[graph:llm_inference] ai_usage_logs記録失敗: %s", e)


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

            # ツール名のみ記録（引数はPIIを含む可能性があるため除外）
            _tool_names = [tc.tool_name for tc in (llm_result.tool_calls or [])] if llm_result.tool_calls else []
            logger.info(
                "🧠 [DIAG] LLM_BRAIN PATH: tool_calls=%d, tools=%s, has_text=%s, confidence=%.2f",
                len(llm_result.tool_calls or []),
                _tool_names,
                llm_result.text_response is not None,
                confidence_value,
            )

            # ai_usage_logs記録（LLM Brain はOrchestrator経由しないため直接記録）
            if llm_result.input_tokens or llm_result.output_tokens:
                brain._fire_and_forget(
                    _log_llm_usage(
                        pool=brain.pool,
                        org_id=brain.org_id,
                        model_id=getattr(brain.llm_brain, "model", "openai/gpt-5.2"),
                        input_tokens=llm_result.input_tokens,
                        output_tokens=llm_result.output_tokens,
                        room_id=state.get("room_id", ""),
                        user_id=state.get("account_id", ""),
                    )
                )

            return {
                "llm_result": llm_result,
                "confidence_value": confidence_value,
            }
        except Exception as e:
            logger.error("[graph:llm_inference] Error: %s", e, exc_info=True)
            raise

    return llm_inference
