# lib/brain/graph/builder.py
"""
LangGraph StateGraph ビルダー

_process_with_llm_brain() のフローを StateGraph に変換。

【グラフ構造】

    state_check
        │
        ├── LIST_CONTEXT → route_session → END
        ├── CONFIRMATION → handle_confirmation_response → END
        │
        └── otherwise → build_context → llm_inference → guardian_check
                                                              │
                                               ┌──────────────┼──────────┐
                                               │              │          │
                                          handle_block  handle_confirm   │
                                               │              │          │
                                              END            END    (allow/modify)
                                                                         │
                                                         ┌───────────────┤
                                                         │               │
                                                    text_response   execute_tool
                                                         │               │
                                                        END    ┌─────────┴─────────┐
                                                               │                   │
                                                        synthesize_knowledge  build_response
                                                               │                   │
                                                         build_response           END
                                                               │
                                                              END
"""

import logging
from typing import TYPE_CHECKING

from langgraph.graph import StateGraph, END

from lib.brain.graph.state import BrainGraphState
from lib.brain.graph.nodes.state_check import (
    make_state_check,
    make_route_session,
    make_handle_confirmation_response,
)
from lib.brain.graph.nodes.build_context import make_build_context
from lib.brain.graph.nodes.llm_inference import make_llm_inference
from lib.brain.graph.nodes.guardian_check import make_guardian_check
from lib.brain.graph.nodes.execute_tool import make_execute_tool
from lib.brain.graph.nodes.synthesize import make_synthesize_knowledge
from lib.brain.graph.nodes.responses import (
    make_handle_block,
    make_handle_confirm,
    make_text_response,
    make_build_response,
)

if TYPE_CHECKING:
    from lib.brain.core import SoulkunBrain

logger = logging.getLogger(__name__)


# =========================================================================
# ルーティング関数
# =========================================================================


def route_after_state_check(state: BrainGraphState) -> str:
    """state_check後のルーティング: セッション中 / 確認応答 / 通常処理"""
    if state.get("has_active_session"):
        return "route_session"
    if state.get("has_pending_confirmation"):
        return "handle_confirmation_response"
    return "build_context"


def route_after_guardian(state: BrainGraphState) -> str:
    """guardian_check後のルーティング: block/confirm/text_only/execute"""
    action = state.get("guardian_action", "allow")
    if action == "block":
        return "handle_block"
    if action == "confirm":
        return "handle_confirm"
    if action == "text_only":
        return "text_response"
    # allow or modify → execute
    return "execute_tool"


def route_after_execution(state: BrainGraphState) -> str:
    """execute_tool後のルーティング: ナレッジ合成 or 直接レスポンス"""
    if state.get("needs_synthesis"):
        return "synthesize_knowledge"
    return "build_response"


# =========================================================================
# グラフ構築
# =========================================================================


def create_brain_graph(brain: "SoulkunBrain"):
    """
    LLM Brain処理フローのStateGraphを構築・コンパイルする。

    Args:
        brain: SoulkunBrainインスタンス（各ノードがコンポーネントを参照）

    Returns:
        CompiledGraph: ainvoke() で実行可能なコンパイル済みグラフ
    """
    graph = StateGraph(BrainGraphState)

    # --- ノード登録 ---
    graph.add_node("state_check", make_state_check(brain))
    graph.add_node("route_session", make_route_session(brain))
    graph.add_node("handle_confirmation_response", make_handle_confirmation_response(brain))
    graph.add_node("build_context", make_build_context(brain))
    graph.add_node("llm_inference", make_llm_inference(brain))
    graph.add_node("guardian_check", make_guardian_check(brain))
    graph.add_node("handle_block", make_handle_block(brain))
    graph.add_node("handle_confirm", make_handle_confirm(brain))
    graph.add_node("text_response", make_text_response(brain))
    graph.add_node("execute_tool", make_execute_tool(brain))
    graph.add_node("synthesize_knowledge", make_synthesize_knowledge(brain))
    graph.add_node("build_response", make_build_response(brain))

    # --- エントリーポイント ---
    graph.set_entry_point("state_check")

    # --- エッジ ---

    # state_check → route_session or build_context
    graph.add_conditional_edges(
        "state_check",
        route_after_state_check,
        {
            "route_session": "route_session",
            "handle_confirmation_response": "handle_confirmation_response",
            "build_context": "build_context",
        },
    )

    # route_session → END（SessionOrchestratorが応答を生成）
    graph.add_edge("route_session", END)

    # handle_confirmation_response → END（確認応答処理）
    graph.add_edge("handle_confirmation_response", END)

    # build_context → llm_inference → guardian_check
    graph.add_edge("build_context", "llm_inference")
    graph.add_edge("llm_inference", "guardian_check")

    # guardian_check → block/confirm/text_only/execute
    graph.add_conditional_edges(
        "guardian_check",
        route_after_guardian,
        {
            "handle_block": "handle_block",
            "handle_confirm": "handle_confirm",
            "text_response": "text_response",
            "execute_tool": "execute_tool",
        },
    )

    # 各終端 → END
    graph.add_edge("handle_block", END)
    graph.add_edge("handle_confirm", END)
    graph.add_edge("text_response", END)

    # execute_tool → synthesize or build_response
    graph.add_conditional_edges(
        "execute_tool",
        route_after_execution,
        {
            "synthesize_knowledge": "synthesize_knowledge",
            "build_response": "build_response",
        },
    )

    # synthesize → build_response → END
    graph.add_edge("synthesize_knowledge", "build_response")
    graph.add_edge("build_response", END)

    logger.info("🧠 LLM Brain graph compiled (12 nodes)")
    return graph.compile()
