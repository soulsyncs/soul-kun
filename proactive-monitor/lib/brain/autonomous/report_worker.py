# lib/brain/autonomous/report_worker.py
"""
Phase AA: レポートワーカー

Brainが発行したレポートタスクの自動実行。
DBメトリクスを定型フォーマットで整形し送信する。
タスク作成時にBrainがレポート種別・送信先を決定しており、
ワーカーはBrainの実行委譲先として動作する（§1準拠）。

CLAUDE.md S1: 全出力はBrainを通る（Brain→タスク生成→ワーカー実行）
CLAUDE.md S8 鉄則#8: エラーに機密情報を含めない
"""

import logging
from typing import Any, Dict, Optional

from lib.brain.autonomous.task_queue import AutonomousTask, TaskQueue
from lib.brain.autonomous.worker import BaseWorker

logger = logging.getLogger(__name__)


class ReportWorker(BaseWorker):
    """
    レポートワーカー: データ集計→定型整形→送信

    execution_plan:
        report_type: レポート種別（daily_summary, weekly_summary, custom）
        room_id: 送信先ルームID
        metrics: 集計対象メトリクス名リスト
    """

    def __init__(self, task_queue: TaskQueue, pool=None, send_func=None):
        super().__init__(task_queue=task_queue, pool=pool)
        self.send_func = send_func

    async def execute(self, task: AutonomousTask) -> Optional[Dict[str, Any]]:
        """レポートタスクを実行"""
        if not task.organization_id:
            logger.warning("Task has empty organization_id: id=%s", task.id)
            return {"error": "missing_organization_id"}

        plan = task.execution_plan or {}
        report_type = plan.get("report_type", "daily_summary")
        room_id = plan.get("room_id", task.room_id)

        task.total_steps = 3

        # Step 1: データ収集
        await self.report_progress(task, 1, "データ収集中")
        data = await self._collect_data(
            organization_id=task.organization_id,
            report_type=report_type,
        )

        # Step 2: レポート生成
        await self.report_progress(task, 2, "レポート生成中")
        report_text = self._generate_report(report_type, data)

        # Step 3: 送信
        await self.report_progress(task, 3, "送信中")
        sent = await self._send_report(room_id, report_text)

        return {
            "report_type": report_type,
            "data_points": len(data),
            "sent": sent,
            "report_length": len(report_text),
        }

    async def _collect_data(
        self,
        organization_id: str,
        report_type: str,
    ) -> Dict[str, Any]:
        """レポート用データを収集"""
        if not self.pool:
            return {}

        try:
            from sqlalchemy import text
            import asyncio

            def _sync_collect():
                with self.pool.connect() as conn:
                    conn.execute(
                        text("SELECT set_config('app.current_organization_id', :org_id, false)"),
                        {"org_id": organization_id},
                    )

                    # AI使用量
                    usage_row = conn.execute(
                        text("""
                            SELECT
                                COUNT(*) AS call_count,
                                COALESCE(SUM(total_tokens), 0) AS total_tokens,
                                COALESCE(SUM(estimated_cost_jpy), 0) AS total_cost
                            FROM ai_usage_logs
                            WHERE organization_id = :org_id::uuid
                              AND created_at >= NOW() - INTERVAL '1 day'
                        """),
                        {"org_id": organization_id},
                    ).mappings().first()

                    # エラー率
                    error_row = conn.execute(
                        text("""
                            SELECT
                                COUNT(*) FILTER (WHERE execution_success = false) AS errors,
                                COUNT(*) AS total
                            FROM brain_decision_logs
                            WHERE organization_id = :org_id::uuid
                              AND created_at >= NOW() - INTERVAL '1 day'
                        """),
                        {"org_id": organization_id},
                    ).mappings().first()

                    return {
                        "call_count": usage_row["call_count"] if usage_row else 0,
                        "total_tokens": usage_row["total_tokens"] if usage_row else 0,
                        "total_cost": float(usage_row["total_cost"] or 0) if usage_row else 0,
                        "error_count": error_row["errors"] if error_row else 0,
                        "total_decisions": error_row["total"] if error_row else 0,
                    }

            return await asyncio.to_thread(_sync_collect)
        except Exception as e:
            logger.warning("Report data collection failed: %s", type(e).__name__)
            return {}

    def _generate_report(self, report_type: str, data: Dict[str, Any]) -> str:
        """レポートテキストを生成"""
        if not data:
            return f"[info][title]{report_type}[/title]データがありません。[/info]"

        total = data.get("total_decisions", 0)
        errors = data.get("error_count", 0)
        error_rate = (errors / total * 100) if total > 0 else 0

        lines = [
            f"[info][title]日次レポート[/title]",
            f"API呼出数: {data.get('call_count', 0)}",
            f"トークン数: {data.get('total_tokens', 0):,}",
            f"コスト: {data.get('total_cost', 0):.0f}円",
            f"判断数: {total}",
            f"エラー率: {error_rate:.1f}%",
            f"[/info]",
        ]
        return "\n".join(lines)

    async def _send_report(self, room_id: Optional[str], report: str) -> bool:
        """レポートを送信（Brain委譲実行: タスク生成時にBrainが承認済み）"""
        if not self.send_func or not room_id:
            logger.warning("Cannot send report: missing send_func or room_id")
            return False

        try:
            await self.send_func(room_id=room_id, message=report)
            return True
        except Exception as e:
            logger.warning("Report send failed: %s", type(e).__name__)
            return False
