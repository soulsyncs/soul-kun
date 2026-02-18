# lib/brain/graph/nodes/synthesize.py
"""
ノード: ナレッジ回答合成

ハンドラーが返した検索データを Brain（LLM）で回答に合成する。
CLAUDE.md §1: 全出力は脳を通る。ハンドラーはデータ取得のみ。
"""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lib.brain.core import SoulkunBrain

from lib.brain.graph.state import BrainGraphState
from lib.brain.models import HandlerResult

logger = logging.getLogger(__name__)


def make_synthesize_knowledge(brain: "SoulkunBrain"):
    """SoulkunBrainを参照するsynthesize_knowledgeノードを生成"""

    async def synthesize_knowledge(state: BrainGraphState) -> dict:
        result = state["execution_result"]
        tool_calls = state["tool_calls_to_execute"]

        try:
            if not tool_calls:
                logger.error("[graph:synthesize] tool_calls is empty")
                return {"execution_result": result}

            tool_call = tool_calls[0]

            # original_query: ツールのqueryパラメータがあればそれを使い、
            # なければユーザーの元メッセージを使う（calendar_read等はqueryパラメータがない）
            original_query = (
                tool_call.parameters.get("query")
                or state.get("message", "")
            )

            synthesized = await brain._synthesize_knowledge_answer(
                search_data=result.data,
                original_query=original_query,
            )

            if synthesized:
                new_result = HandlerResult(
                    success=True,
                    message=synthesized,
                    data=result.data,
                )
            else:
                # 合成失敗時: 検索結果をそのまま表示
                fallback = result.data.get("formatted_context", "") if isinstance(result.data, dict) else ""
                if fallback:
                    new_result = HandlerResult(
                        success=True,
                        message=f"検索結果を見つけたウル！\n\n{fallback}",
                        data=result.data,
                    )
                else:
                    new_result = result

            return {"execution_result": new_result}
        except Exception as e:
            logger.error("[graph:synthesize] Error: %s", e, exc_info=True)
            raise

    return synthesize_knowledge
