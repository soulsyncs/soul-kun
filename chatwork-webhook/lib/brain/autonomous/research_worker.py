# lib/brain/autonomous/research_worker.py
"""
Phase AA: リサーチワーカー

ナレッジ検索 → Brain合成 → 返答のパイプラインを実行する。

CLAUDE.md S1: 全出力はBrainを通る
CLAUDE.md S8 鉄則#8: エラーに機密情報を含めない
"""

import logging
from typing import Any, Dict, Optional

from lib.brain.autonomous.task_queue import AutonomousTask, TaskQueue
from lib.brain.autonomous.worker import BaseWorker

logger = logging.getLogger(__name__)


class ResearchWorker(BaseWorker):
    """
    リサーチワーカー: ナレッジ検索→合成→返答

    execution_plan:
        query: 検索クエリ
        max_results: 最大結果数（デフォルト5）
    """

    def __init__(self, task_queue: TaskQueue, pool=None, brain=None):
        super().__init__(task_queue=task_queue, pool=pool)
        self.brain = brain

    async def execute(self, task: AutonomousTask) -> Optional[Dict[str, Any]]:
        """リサーチタスクを実行"""
        if not task.organization_id:
            logger.warning("Task has empty organization_id: id=%s", task.id)
            return {"error": "missing_organization_id"}

        plan = task.execution_plan or {}
        query = plan.get("query", task.description)
        max_results = plan.get("max_results", 5)

        task.total_steps = 3

        # Step 1: ナレッジ検索
        await self.report_progress(task, 1, "ナレッジ検索中")
        knowledge_results = await self._search_knowledge(
            query=query,
            organization_id=task.organization_id,
            max_results=max_results,
        )

        # Step 2: Brain合成
        await self.report_progress(task, 2, "情報合成中")
        synthesis = self._synthesize(query, knowledge_results)

        # Step 3: 結果整形
        await self.report_progress(task, 3, "結果整形中")

        return {
            "query": query,
            "results_count": len(knowledge_results),
            "synthesis_length": len(synthesis),
        }

    async def _search_knowledge(
        self,
        query: str,
        organization_id: str,
        max_results: int = 5,
    ) -> list:
        """
        ナレッジベースを検索

        documents + document_chunks（UUID org_id）を使用。
        soulkun_knowledge は VARCHAR/slug の org_id のため使用しない。
        """
        if not self.pool:
            return []

        try:
            from sqlalchemy import text
            import asyncio

            def _sync_search():
                with self.pool.connect() as conn:
                    conn.execute(
                        text("SELECT set_config('app.current_organization_id', :org_id, false)"),
                        {"org_id": organization_id},
                    )
                    rows = conn.execute(
                        text("""
                            SELECT d.title, dc.content
                            FROM document_chunks dc
                            JOIN documents d ON d.id = dc.document_id
                            WHERE d.organization_id = :org_id::uuid
                            ORDER BY d.updated_at DESC
                            LIMIT :limit
                        """),
                        {"org_id": organization_id, "limit": max_results},
                    ).mappings().all()
                    return [{"title": r["title"], "content": (r["content"] or "")[:500]} for r in rows]

            return await asyncio.to_thread(_sync_search)
        except Exception as e:
            logger.warning("Knowledge search failed: %s", type(e).__name__)
            return []

    def _synthesize(self, query: str, results: list) -> str:
        """検索結果を合成（Brain経由でLLM合成する前段階）"""
        if not results:
            return f"「{query}」に関するナレッジは見つかりませんでした。"

        summaries = []
        for r in results[:5]:
            title = r.get("title", "不明")
            content = r.get("content", "")[:200]
            summaries.append(f"- {title}: {content}")

        return f"「{query}」に関する情報:\n" + "\n".join(summaries)
