# lib/brain/graph/__init__.py
"""
LangGraph ベースの Brain 処理グラフ

core.py の _process_with_llm_brain() を StateGraph に分解。
各ノードは独立してテスト可能。Langfuse と統合してトレーシング可能。

設計書: docs/30_strategic_improvement_plan_3ai.md (Phase 3)
"""

from lib.brain.graph.builder import create_brain_graph

__all__ = ["create_brain_graph"]
