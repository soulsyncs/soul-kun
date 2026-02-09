# lib/brain/autonomous/reminder_worker.py
"""
Phase AA: リマインダーワーカー

スケジュールメッセージ送信（初回確認あり）。

自動化通知（Brain不使用）: ユーザー確認済みスケジュールメッセージの定時配信。
メッセージ内容はユーザーが事前に設定・確認済みのため、Brain判断不要。
（AlertSender同様、インフラ/自動化通知はBrain bypass許容）

CLAUDE.md S1: 全出力はBrainを通る（例外: 確認済み自動化通知）
CLAUDE.md S8 鉄則#8: エラーに機密情報を含めない
"""

import logging
from typing import Any, Dict, Optional

from lib.brain.autonomous.task_queue import AutonomousTask, TaskQueue
from lib.brain.autonomous.worker import BaseWorker

logger = logging.getLogger(__name__)


class ReminderWorker(BaseWorker):
    """
    リマインダーワーカー: スケジュール通知

    execution_plan:
        message: リマインダーメッセージ
        room_id: 送信先ルームID
        account_id: 送信先アカウントID（DM用）
        confirmed: ユーザーが確認済みか（初回はfalse）
    """

    def __init__(self, task_queue: TaskQueue, pool=None, send_func=None):
        super().__init__(task_queue=task_queue, pool=pool)
        self.send_func = send_func

    async def execute(self, task: AutonomousTask) -> Optional[Dict[str, Any]]:
        """リマインダータスクを実行"""
        if not task.organization_id:
            logger.warning("Task has empty organization_id: id=%s", task.id)
            return {"error": "missing_organization_id"}

        plan = task.execution_plan or {}
        message = plan.get("message", task.description)
        room_id = plan.get("room_id", task.room_id)
        confirmed = plan.get("confirmed", False)

        task.total_steps = 2

        # Step 1: 確認チェック
        await self.report_progress(task, 1, "確認チェック中")
        if not confirmed:
            return {
                "status": "awaiting_confirmation",
                "message_preview": message[:20] + "..." if len(message) > 20 else message,
                "room_id": room_id,
            }

        # Step 2: メッセージ送信
        await self.report_progress(task, 2, "メッセージ送信中")
        sent = await self._send_message(room_id, message)

        return {
            "status": "sent" if sent else "send_failed",
            "message_length": len(message),
            "room_id": room_id,
        }

    async def _send_message(self, room_id: Optional[str], message: str) -> bool:
        """メッセージを送信（自動化通知: Brain bypass許容）"""
        if not self.send_func or not room_id:
            logger.warning("Cannot send reminder: missing send_func or room_id")
            return False

        try:
            await self.send_func(room_id=room_id, message=message)
            return True
        except Exception as e:
            logger.warning("Reminder send failed: %s", type(e).__name__)
            return False
