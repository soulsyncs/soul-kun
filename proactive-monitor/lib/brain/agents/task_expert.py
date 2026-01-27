# lib/brain/agents/task_expert.py
"""
ソウルくんの脳 - タスク専門家エージェント

Ultimate Brain Phase 3: タスク管理に特化したエキスパートエージェント

設計思想:
- タスク管理のあらゆる側面を深く理解
- 優先順位付けと時間管理のアドバイス
- リマインドと進捗追跡

主要機能:
1. タスク作成・検索・完了
2. 優先順位の提案
3. 遅延タスクの管理
4. タスク分析とアドバイス

設計書: docs/19_ultimate_brain_architecture.md セクション5.3
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

from lib.brain.agents.base import (
    BaseAgent,
    AgentType,
    AgentCapability,
    AgentMessage,
    AgentResponse,
    AgentContext,
    MessageType,
    ExpertiseLevel,
)


logger = logging.getLogger(__name__)


# =============================================================================
# 定数
# =============================================================================

# タスク優先度の定義
TASK_PRIORITY_URGENT = "urgent"
TASK_PRIORITY_HIGH = "high"
TASK_PRIORITY_NORMAL = "normal"
TASK_PRIORITY_LOW = "low"

# 遅延タスクの閾値（日）
OVERDUE_THRESHOLD_DAYS = 0
WARNING_THRESHOLD_DAYS = 2

# タスク検索のデフォルト上限
DEFAULT_TASK_SEARCH_LIMIT = 10

# タスク作成のキーワード
TASK_CREATE_KEYWORDS = [
    "タスク作成", "タスクを作って", "タスク追加", "やることを登録",
    "タスクを追加", "新しいタスク", "タスクにして", "タスクに追加",
    "にタスク", "さんにタスク",
]

# タスク検索のキーワード
TASK_SEARCH_KEYWORDS = [
    "タスク検索", "タスクを探して", "タスク一覧", "自分のタスク",
    "タスクを教えて", "やること教えて", "タスク確認", "タスクを見せて",
    "今日のタスク", "タスクある？",
]

# タスク完了のキーワード
TASK_COMPLETE_KEYWORDS = [
    "タスク完了", "タスクを完了", "終わった", "できた", "完了にして",
    "やった", "終了", "達成した", "done", "完了",
]

# 優先順位のキーワード
PRIORITY_KEYWORDS = {
    TASK_PRIORITY_URGENT: ["緊急", "至急", "今すぐ", "急ぎ", "ASAP"],
    TASK_PRIORITY_HIGH: ["高", "重要", "優先", "先に"],
    TASK_PRIORITY_NORMAL: ["普通", "通常", "一般"],
    TASK_PRIORITY_LOW: ["低", "後で", "いつでも", "暇な時"],
}


# =============================================================================
# データクラス
# =============================================================================

@dataclass
class TaskInfo:
    """
    タスク情報
    """
    task_id: str = ""
    title: str = ""
    body: str = ""
    status: str = ""
    priority: str = TASK_PRIORITY_NORMAL
    assignee_id: str = ""
    assignee_name: str = ""
    due_date: Optional[datetime] = None
    room_id: str = ""
    room_name: str = ""
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    @property
    def is_overdue(self) -> bool:
        """期限切れか"""
        if self.due_date and self.status != "done":
            return datetime.now() > self.due_date
        return False

    @property
    def days_until_due(self) -> Optional[int]:
        """期限までの日数"""
        if self.due_date:
            delta = self.due_date - datetime.now()
            return delta.days
        return None


@dataclass
class TaskAnalysis:
    """
    タスク分析結果
    """
    total_tasks: int = 0
    overdue_tasks: int = 0
    tasks_due_today: int = 0
    tasks_due_this_week: int = 0
    high_priority_tasks: int = 0
    recommendations: List[str] = field(default_factory=list)
    workload_level: str = "normal"  # "light", "normal", "heavy", "overloaded"


# =============================================================================
# TaskExpert クラス
# =============================================================================

class TaskExpert(BaseAgent):
    """
    タスク専門家エージェント

    タスク管理のあらゆる側面に対応する専門家。
    タスクの作成、検索、完了、優先順位付け、分析を行う。

    Attributes:
        pool: データベース接続プール
        organization_id: 組織ID
    """

    def __init__(
        self,
        pool: Optional[Any] = None,
        organization_id: str = "",
    ):
        """
        初期化

        Args:
            pool: データベース接続プール
            organization_id: 組織ID
        """
        super().__init__(
            agent_type=AgentType.TASK_EXPERT,
            pool=pool,
            organization_id=organization_id,
        )

        logger.info(
            "TaskExpert initialized",
            extra={"organization_id": organization_id}
        )

    # -------------------------------------------------------------------------
    # BaseAgent 実装
    # -------------------------------------------------------------------------

    def _initialize_capabilities(self) -> None:
        """エージェントの能力を初期化"""
        self._capabilities = [
            AgentCapability(
                capability_id="task_create",
                name="タスク作成",
                description="新しいタスクを作成する",
                keywords=TASK_CREATE_KEYWORDS,
                actions=["task_create", "chatwork_task_create"],
                expertise_level=ExpertiseLevel.PRIMARY,
                confidence_boost=0.15,
            ),
            AgentCapability(
                capability_id="task_search",
                name="タスク検索",
                description="タスクを検索・一覧表示する",
                keywords=TASK_SEARCH_KEYWORDS,
                actions=["task_search", "chatwork_task_search"],
                expertise_level=ExpertiseLevel.PRIMARY,
                confidence_boost=0.15,
            ),
            AgentCapability(
                capability_id="task_complete",
                name="タスク完了",
                description="タスクを完了状態にする",
                keywords=TASK_COMPLETE_KEYWORDS,
                actions=["task_complete", "chatwork_task_complete"],
                expertise_level=ExpertiseLevel.PRIMARY,
                confidence_boost=0.15,
            ),
            AgentCapability(
                capability_id="task_priority",
                name="優先順位付け",
                description="タスクの優先順位を判断・提案する",
                keywords=["優先順位", "重要度", "緊急度", "先に", "後で"],
                actions=["task_prioritize", "task_analyze"],
                expertise_level=ExpertiseLevel.PRIMARY,
                confidence_boost=0.1,
            ),
            AgentCapability(
                capability_id="task_reminder",
                name="リマインド",
                description="タスクのリマインドを管理する",
                keywords=["リマインド", "思い出させて", "忘れないように", "通知"],
                actions=["task_remind", "task_schedule_reminder"],
                expertise_level=ExpertiseLevel.SECONDARY,
                confidence_boost=0.05,
            ),
            AgentCapability(
                capability_id="overdue_management",
                name="遅延タスク管理",
                description="期限切れタスクの管理とエスカレーション",
                keywords=["遅延", "期限切れ", "遅れてる", "オーバーデュー"],
                actions=["overdue_report", "overdue_escalate"],
                expertise_level=ExpertiseLevel.PRIMARY,
                confidence_boost=0.1,
            ),
        ]

    def _register_handlers(self) -> None:
        """ハンドラーを登録"""
        self._handlers = {
            "task_create": self._handle_task_create,
            "chatwork_task_create": self._handle_task_create,
            "task_search": self._handle_task_search,
            "chatwork_task_search": self._handle_task_search,
            "task_complete": self._handle_task_complete,
            "chatwork_task_complete": self._handle_task_complete,
            "task_prioritize": self._handle_task_prioritize,
            "task_analyze": self._handle_task_analyze,
            "task_remind": self._handle_task_remind,
            "overdue_report": self._handle_overdue_report,
        }

    async def process(
        self,
        context: AgentContext,
        message: AgentMessage,
    ) -> AgentResponse:
        """
        メッセージを処理

        Args:
            context: エージェントコンテキスト
            message: 処理するメッセージ

        Returns:
            AgentResponse: 処理結果
        """
        content = message.content
        action = content.get("action", "")

        # アクションが明示されている場合
        if action and action in self._handlers:
            handler = self._handlers[action]
            try:
                result = await handler(content, context)
                confidence = self.get_confidence(action, context)
                return AgentResponse(
                    request_id=message.id,
                    agent_type=self._agent_type,
                    success=True,
                    result=result,
                    confidence=confidence,
                )
            except Exception as e:
                logger.error(f"Handler error: {action}: {e}", exc_info=True)
                return AgentResponse(
                    request_id=message.id,
                    agent_type=self._agent_type,
                    success=False,
                    error_message=str(e),
                )

        # メッセージからアクションを推論
        original_message = content.get("message", context.original_message)
        inferred_action = self._infer_action(original_message)

        if inferred_action and inferred_action in self._handlers:
            content["action"] = inferred_action
            handler = self._handlers[inferred_action]
            try:
                result = await handler(content, context)
                confidence = self.get_confidence(inferred_action, context)
                return AgentResponse(
                    request_id=message.id,
                    agent_type=self._agent_type,
                    success=True,
                    result=result,
                    confidence=confidence,
                )
            except Exception as e:
                logger.error(f"Handler error: {inferred_action}: {e}", exc_info=True)
                return AgentResponse(
                    request_id=message.id,
                    agent_type=self._agent_type,
                    success=False,
                    error_message=str(e),
                )

        # アクションが特定できない場合
        return AgentResponse(
            request_id=message.id,
            agent_type=self._agent_type,
            success=False,
            error_message="タスク関連の操作を特定できませんでした",
            confidence=0.3,
        )

    def can_handle(
        self,
        action: str,
        context: AgentContext,
    ) -> bool:
        """
        指定されたアクションを処理できるか判定

        Args:
            action: アクション名
            context: エージェントコンテキスト

        Returns:
            bool: 処理可能ならTrue
        """
        if action in self._handlers:
            return True

        # 能力からチェック
        for capability in self._capabilities:
            if action in capability.actions:
                return True

        return False

    def get_confidence(
        self,
        action: str,
        context: AgentContext,
    ) -> float:
        """
        指定されたアクションに対する確信度を計算

        Args:
            action: アクション名
            context: エージェントコンテキスト

        Returns:
            float: 確信度（0.0〜1.0）
        """
        base_confidence = 0.5

        # アクションに対応する能力を取得
        capability = self.get_capability_for_action(action)
        if capability:
            base_confidence = 0.7
            base_confidence += capability.confidence_boost

            if capability.expertise_level == ExpertiseLevel.PRIMARY:
                base_confidence += 0.1
            elif capability.expertise_level == ExpertiseLevel.SECONDARY:
                base_confidence += 0.05

        return min(base_confidence, 1.0)

    # -------------------------------------------------------------------------
    # アクション推論
    # -------------------------------------------------------------------------

    def _infer_action(self, message: str) -> Optional[str]:
        """
        メッセージからアクションを推論

        Args:
            message: ユーザーメッセージ

        Returns:
            str: 推論されたアクション（なければNone）
        """
        message_lower = message.lower()

        # タスク作成
        for keyword in TASK_CREATE_KEYWORDS:
            if keyword.lower() in message_lower:
                return "task_create"

        # タスク完了
        for keyword in TASK_COMPLETE_KEYWORDS:
            if keyword.lower() in message_lower:
                return "task_complete"

        # タスク検索
        for keyword in TASK_SEARCH_KEYWORDS:
            if keyword.lower() in message_lower:
                return "task_search"

        return None

    def _extract_priority(self, message: str) -> str:
        """
        メッセージから優先度を抽出

        Args:
            message: ユーザーメッセージ

        Returns:
            str: 優先度
        """
        message_lower = message.lower()

        for priority, keywords in PRIORITY_KEYWORDS.items():
            for keyword in keywords:
                if keyword.lower() in message_lower:
                    return priority

        return TASK_PRIORITY_NORMAL

    # -------------------------------------------------------------------------
    # ハンドラー
    # -------------------------------------------------------------------------

    async def _handle_task_create(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """タスク作成ハンドラー"""
        message = content.get("message", "")
        assignee_id = content.get("assignee_id", context.user_id)
        assignee_name = content.get("assignee_name", "")
        due_date = content.get("due_date")
        room_id = content.get("room_id", context.room_id)

        # 優先度を抽出
        priority = self._extract_priority(message)

        # タスク内容を抽出（簡易的な実装）
        task_body = content.get("body", message)

        # 実際の作成はmain.pyのハンドラーに委任される
        return {
            "action": "task_create",
            "task_info": {
                "body": task_body,
                "assignee_id": assignee_id,
                "assignee_name": assignee_name,
                "priority": priority,
                "due_date": due_date,
                "room_id": room_id,
            },
            "response": f"タスクを作成しますウル！優先度: {priority}",
            "requires_external_handler": True,
        }

    async def _handle_task_search(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """タスク検索ハンドラー"""
        user_id = content.get("user_id", context.user_id)
        status = content.get("status", "open")
        limit = content.get("limit", DEFAULT_TASK_SEARCH_LIMIT)

        # 検索条件
        search_params = {
            "user_id": user_id,
            "status": status,
            "limit": limit,
        }

        return {
            "action": "task_search",
            "search_params": search_params,
            "response": "タスクを検索しますウル！",
            "requires_external_handler": True,
        }

    async def _handle_task_complete(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """タスク完了ハンドラー"""
        task_id = content.get("task_id", "")
        message = content.get("message", "")

        # タスクIDが明示されていない場合は特定が必要
        if not task_id:
            return {
                "action": "task_complete",
                "needs_clarification": True,
                "response": "どのタスクを完了にしますか？",
                "requires_external_handler": True,
            }

        return {
            "action": "task_complete",
            "task_id": task_id,
            "response": "タスクを完了にしますウル！",
            "requires_external_handler": True,
        }

    async def _handle_task_prioritize(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """優先順位付けハンドラー"""
        tasks = content.get("tasks", [])

        if not tasks:
            return {
                "action": "task_prioritize",
                "response": "優先順位を付けるタスクがありませんウル",
            }

        # 優先順位付けロジック
        prioritized = self._prioritize_tasks(tasks)

        return {
            "action": "task_prioritize",
            "prioritized_tasks": prioritized,
            "response": "タスクの優先順位を付けましたウル！",
        }

    async def _handle_task_analyze(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """タスク分析ハンドラー"""
        tasks = content.get("tasks", [])

        analysis = self._analyze_tasks(tasks)

        return {
            "action": "task_analyze",
            "analysis": {
                "total_tasks": analysis.total_tasks,
                "overdue_tasks": analysis.overdue_tasks,
                "tasks_due_today": analysis.tasks_due_today,
                "high_priority_tasks": analysis.high_priority_tasks,
                "workload_level": analysis.workload_level,
                "recommendations": analysis.recommendations,
            },
            "response": self._format_analysis_response(analysis),
        }

    async def _handle_task_remind(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """リマインドハンドラー"""
        task_id = content.get("task_id", "")
        remind_at = content.get("remind_at")

        return {
            "action": "task_remind",
            "task_id": task_id,
            "remind_at": remind_at,
            "response": "リマインドを設定しますウル！",
            "requires_external_handler": True,
        }

    async def _handle_overdue_report(
        self,
        content: Dict[str, Any],
        context: AgentContext,
    ) -> Dict[str, Any]:
        """遅延レポートハンドラー"""
        user_id = content.get("user_id", context.user_id)

        return {
            "action": "overdue_report",
            "user_id": user_id,
            "response": "遅延タスクを確認しますウル！",
            "requires_external_handler": True,
        }

    # -------------------------------------------------------------------------
    # 分析・ユーティリティ
    # -------------------------------------------------------------------------

    def _prioritize_tasks(self, tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        タスクを優先順位でソート

        Args:
            tasks: タスクのリスト

        Returns:
            List: 優先順位順のタスクリスト
        """
        priority_order = {
            TASK_PRIORITY_URGENT: 0,
            TASK_PRIORITY_HIGH: 1,
            TASK_PRIORITY_NORMAL: 2,
            TASK_PRIORITY_LOW: 3,
        }

        def sort_key(task):
            priority = task.get("priority", TASK_PRIORITY_NORMAL)
            due_date = task.get("due_date")
            priority_score = priority_order.get(priority, 2)

            # 期限が近いほど優先
            if due_date:
                try:
                    if isinstance(due_date, str):
                        due = datetime.fromisoformat(due_date)
                    else:
                        due = due_date
                    days = (due - datetime.now()).days
                    due_score = max(0, days)
                except:
                    due_score = 999
            else:
                due_score = 999

            return (priority_score, due_score)

        return sorted(tasks, key=sort_key)

    def _analyze_tasks(self, tasks: List[Dict[str, Any]]) -> TaskAnalysis:
        """
        タスクを分析

        Args:
            tasks: タスクのリスト

        Returns:
            TaskAnalysis: 分析結果
        """
        analysis = TaskAnalysis()
        analysis.total_tasks = len(tasks)

        now = datetime.now()
        today_end = now.replace(hour=23, minute=59, second=59)
        week_end = now + timedelta(days=7)

        for task in tasks:
            due_date = task.get("due_date")
            priority = task.get("priority", TASK_PRIORITY_NORMAL)
            status = task.get("status", "open")

            if status == "done":
                continue

            # 優先度チェック
            if priority in [TASK_PRIORITY_URGENT, TASK_PRIORITY_HIGH]:
                analysis.high_priority_tasks += 1

            # 期限チェック
            if due_date:
                try:
                    if isinstance(due_date, str):
                        due = datetime.fromisoformat(due_date)
                    else:
                        due = due_date

                    if due < now:
                        analysis.overdue_tasks += 1
                    elif due <= today_end:
                        analysis.tasks_due_today += 1
                    elif due <= week_end:
                        analysis.tasks_due_this_week += 1
                except:
                    pass

        # ワークロードレベル
        if analysis.overdue_tasks >= 5 or analysis.total_tasks >= 15:
            analysis.workload_level = "overloaded"
        elif analysis.overdue_tasks >= 2 or analysis.total_tasks >= 10:
            analysis.workload_level = "heavy"
        elif analysis.total_tasks >= 5:
            analysis.workload_level = "normal"
        else:
            analysis.workload_level = "light"

        # 推奨事項
        if analysis.overdue_tasks > 0:
            analysis.recommendations.append(
                f"期限切れのタスクが{analysis.overdue_tasks}件あります。先に対応しましょう！"
            )
        if analysis.tasks_due_today > 0:
            analysis.recommendations.append(
                f"今日期限のタスクが{analysis.tasks_due_today}件あります。"
            )
        if analysis.high_priority_tasks > 3:
            analysis.recommendations.append(
                "高優先度タスクが多いです。本当に全て急ぎか見直してみましょう。"
            )

        return analysis

    def _format_analysis_response(self, analysis: TaskAnalysis) -> str:
        """
        分析結果をメッセージにフォーマット

        Args:
            analysis: 分析結果

        Returns:
            str: フォーマットされたメッセージ
        """
        lines = [f"タスク状況を分析したウル！"]
        lines.append(f"総タスク数: {analysis.total_tasks}件")

        if analysis.overdue_tasks > 0:
            lines.append(f"期限切れ: {analysis.overdue_tasks}件")
        if analysis.tasks_due_today > 0:
            lines.append(f"今日期限: {analysis.tasks_due_today}件")
        if analysis.high_priority_tasks > 0:
            lines.append(f"高優先度: {analysis.high_priority_tasks}件")

        lines.append(f"ワークロード: {analysis.workload_level}")

        if analysis.recommendations:
            lines.append("")
            lines.append("アドバイス:")
            for rec in analysis.recommendations:
                lines.append(f"・{rec}")

        return "\n".join(lines)


# =============================================================================
# ファクトリ関数
# =============================================================================

def create_task_expert(
    pool: Optional[Any] = None,
    organization_id: str = "",
) -> TaskExpert:
    """
    タスク専門家エージェントを作成するファクトリ関数

    Args:
        pool: データベース接続プール
        organization_id: 組織ID

    Returns:
        TaskExpert: 作成されたタスク専門家エージェント
    """
    return TaskExpert(
        pool=pool,
        organization_id=organization_id,
    )
