# lib/brain/autonomous/reminder_worker.py
"""
Phase AA: リマインダーワーカー

Brainが発行したスケジュールタスクの準備・検証を行う。
送信メッセージはBrainがタスク生成時に決定済み。
ワーカーは確認状態の検証のみ行い、実際の送信はBrainが行う（§1準拠）。

CLAUDE.md S1: 全出力はBrainを通る（ワーカーは準備のみ、送信はBrain）
CLAUDE.md S8 鉄則#8: エラーに機密情報を含めない
"""

import logging
from typing import Any, Dict, Optional

from lib.brain.autonomous.task_queue import AutonomousTask, TaskQueue
from lib.brain.autonomous.worker import BaseWorker

logger = logging.getLogger(__name__)


class ReminderWorker(BaseWorker):
    """
    リマインダーワーカー: スケジュール通知の準備・検証

    送信はBrainの責務（§1準拠）。ワーカーは確認状態と送信準備のみ行い、
    結果にroom_idとready=Trueを返す。Brainが結果を受けて送信を実行する。

    execution_plan:
        message: リマインダーメッセージ（Brain生成済み）
        room_id: 送信先ルームID
        account_id: 送信先アカウントID（DM用）
        confirmed: ユーザーが確認済みか（初回はfalse）
    """

    async def execute(self, task: AutonomousTask) -> Optional[Dict[str, Any]]:
        """リマインダータスクを検証・準備"""
        if not task.organization_id:
            logger.warning("Task has empty organization_id: id=%s", task.id)
            return {"error": "missing_organization_id"}

        plan = task.execution_plan or {}
        message = plan.get("message") or task.description or ""
        room_id = plan.get("room_id", task.room_id)
        confirmed = plan.get("confirmed", False)

        task.total_steps = 2

        # Step 1: 確認チェック
        await self.report_progress(task, 1, "確認チェック中")
        if not confirmed:
            return {
                "status": "awaiting_confirmation",
                "message_length": len(message),
                "room_id": room_id,
            }

        # Step 2: 送信準備完了（実際の送信はBrainが行う）
        await self.report_progress(task, 2, "送信準備完了")

        return {
            "status": "ready",
            "message_length": len(message),
            "room_id": room_id,
        }
