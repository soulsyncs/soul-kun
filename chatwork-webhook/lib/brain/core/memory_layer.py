# lib/brain/core/memory_layer.py
"""
SoulkunBrain 記憶層（BrainMemoryAccess経由）

コンテキスト取得、会話履歴、ユーザー嗜好、人物情報、
タスク情報、目標情報、インサイト、関連知識の取得メソッドを含む。
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional, List, Any

from lib.brain.models import (
    BrainContext,
    ConversationMessage,
    PersonInfo,
    TaskInfo,
    GoalInfo,
    InsightInfo,
    SummaryData,
    PreferenceData,
    KnowledgeChunk,
)
from lib.brain.memory_access import (
    UserPreferenceData,
)

logger = logging.getLogger(__name__)


class MemoryLayerMixin:
    """SoulkunBrain記憶層関連メソッドを提供するMixin"""

    # =========================================================================
    # 記憶層（BrainMemoryAccess経由）
    # =========================================================================

    async def _get_context(
        self,
        room_id: str,
        user_id: str,
        sender_name: str,
        message: Optional[str] = None,
    ) -> BrainContext:
        """
        脳が判断に必要な全ての記憶を取得

        BrainMemoryAccessを使用して複数の記憶ソースから並列で取得し、
        統合したコンテキストを返す。

        Args:
            room_id: ChatWorkルームID
            user_id: ユーザーのアカウントID
            sender_name: 送信者名
            message: 現在のメッセージ（関連知識検索に使用）

        Returns:
            BrainContext: 統合されたコンテキスト
        """
        context = BrainContext(
            organization_id=self.org_id,
            room_id=room_id,
            sender_name=sender_name,
            sender_account_id=user_id,
            timestamp=datetime.now(),
        )

        try:
            # BrainMemoryAccessで全ての記憶を並列取得
            memory_context = await self.memory_access.get_all_context(
                room_id=room_id,
                user_id=user_id,
                sender_name=sender_name,
                message=message,
            )

            # 結果をBrainContextに統合
            # 会話履歴（ConversationMessageに変換）
            if memory_context.get("recent_conversation"):
                context.recent_conversation = [
                    ConversationMessage(
                        role=msg.role if hasattr(msg, 'role') else msg.get('role', 'user'),
                        content=msg.content if hasattr(msg, 'content') else msg.get('content', ''),
                        timestamp=msg.timestamp if hasattr(msg, 'timestamp') else msg.get('timestamp'),
                    )
                    for msg in memory_context["recent_conversation"]
                ]

            # 会話要約（v10.54.4: SummaryDataオブジェクトとして代入）
            if memory_context.get("conversation_summary"):
                summary = memory_context["conversation_summary"]
                context.conversation_summary = SummaryData(
                    summary=summary.summary_text if hasattr(summary, 'summary_text') else summary.get('summary_text', ''),
                    key_topics=summary.key_topics if hasattr(summary, 'key_topics') else summary.get('key_topics', []),
                    mentioned_persons=summary.mentioned_persons if hasattr(summary, 'mentioned_persons') else summary.get('mentioned_persons', []),
                    mentioned_tasks=summary.mentioned_tasks if hasattr(summary, 'mentioned_tasks') else summary.get('mentioned_tasks', []),
                    created_at=datetime.now(),
                )

            # ユーザー嗜好 — UserPreferenceData/dictの両形式を正規化
            if memory_context.get("user_preferences"):
                keywords = {}
                for pref in memory_context["user_preferences"]:
                    if isinstance(pref, UserPreferenceData):
                        keywords[pref.preference_key] = str(pref.preference_value)
                    elif isinstance(pref, dict):
                        keywords[pref.get("preference_key", "")] = str(pref.get("preference_value", ""))
                context.user_preferences = PreferenceData(
                    response_style=None,
                    feature_usage={},
                    preferred_times=[],
                    custom_keywords=keywords,
                )

            # 人物情報（v10.54: PersonInfoオブジェクトとして代入）
            if memory_context.get("person_info"):
                context.person_info = [
                    person if isinstance(person, PersonInfo) else PersonInfo(
                        name=person.name if hasattr(person, 'name') else person.get('name', ''),
                        attributes=person.attributes if hasattr(person, 'attributes') else person.get('attributes', {}),
                    )
                    for person in memory_context["person_info"]
                ]

            # タスク情報（v10.54: TaskInfoオブジェクトとして代入）
            if memory_context.get("recent_tasks"):
                context.recent_tasks = [
                    task if isinstance(task, TaskInfo) else TaskInfo(
                        task_id=task.task_id if hasattr(task, 'task_id') else task.get('task_id', ''),
                        body=task.body if hasattr(task, 'body') else task.get('body', ''),
                        summary=task.summary if hasattr(task, 'summary') else task.get('summary'),
                        status=task.status if hasattr(task, 'status') else task.get('status', 'open'),
                        due_date=task.due_date if hasattr(task, 'due_date') else (task.limit_time if hasattr(task, 'limit_time') else task.get('limit_time') or task.get('due_date')),
                        is_overdue=task.is_overdue if hasattr(task, 'is_overdue') else task.get('is_overdue', False),
                    )
                    for task in memory_context["recent_tasks"]
                ]

            # 目標情報（v10.54: GoalInfoオブジェクトとして代入）
            if memory_context.get("active_goals"):
                context.active_goals = [
                    goal if isinstance(goal, GoalInfo) else GoalInfo(
                        goal_id=goal.goal_id if hasattr(goal, 'goal_id') else goal.get('goal_id', ''),
                        title=goal.title if hasattr(goal, 'title') else goal.get('title', ''),
                        why=goal.why if hasattr(goal, 'why') else goal.get('why'),
                        what=goal.what if hasattr(goal, 'what') else goal.get('what'),
                        how=goal.how if hasattr(goal, 'how') else goal.get('how'),
                        status=goal.status if hasattr(goal, 'status') else goal.get('status', 'active'),
                        progress=float(goal.progress if hasattr(goal, 'progress') else goal.get('progress', 0.0)),
                    )
                    for goal in memory_context["active_goals"]
                ]

            # インサイト（v10.54.4: models.py InsightInfoの正しいフィールドを使用）
            if memory_context.get("insights"):
                context.insights = [
                    insight if isinstance(insight, InsightInfo) else InsightInfo(
                        insight_id=str(insight.id if hasattr(insight, 'id') else insight.get('id', '')) if (hasattr(insight, 'id') or isinstance(insight, dict) and 'id' in insight) else '',
                        insight_type=insight.insight_type if hasattr(insight, 'insight_type') else insight.get('insight_type', ''),
                        title=insight.title if hasattr(insight, 'title') else insight.get('title', ''),
                        description=insight.description if hasattr(insight, 'description') else insight.get('description', ''),
                        severity=insight.importance if hasattr(insight, 'importance') else insight.get('importance', 'medium'),
                        created_at=insight.created_at if hasattr(insight, 'created_at') else datetime.now(),
                    )
                    for insight in memory_context["insights"]
                ]

            # 関連知識（v10.54.4: KnowledgeChunkオブジェクトとして代入）
            if memory_context.get("relevant_knowledge"):
                context.relevant_knowledge = [
                    knowledge if isinstance(knowledge, KnowledgeChunk) else KnowledgeChunk(
                        chunk_id=knowledge.keyword if hasattr(knowledge, 'keyword') else knowledge.get('keyword', ''),
                        content=knowledge.answer if hasattr(knowledge, 'answer') else knowledge.get('answer', ''),
                        source=knowledge.category if hasattr(knowledge, 'category') else knowledge.get('category', ''),
                        relevance_score=knowledge.relevance_score if hasattr(knowledge, 'relevance_score') else knowledge.get('relevance_score', 0.0),
                    )
                    for knowledge in memory_context["relevant_knowledge"]
                ]

            # Phase 2E: 適用可能な学習をコンテキストに追加
            # asyncio.to_thread()で同期DB呼び出しをオフロード
            if self.learning.phase2e_learning:
                try:
                    def _fetch_learnings():
                        with self.pool.connect() as conn:
                            applicable = self.learning.phase2e_learning.find_applicable(
                                conn, message or "", None, user_id, room_id
                            )
                            if applicable:
                                additions = self.learning.phase2e_learning.build_context_additions(applicable)
                                return self.learning.phase2e_learning.build_prompt_instructions(additions)
                            return None
                    result = await asyncio.to_thread(_fetch_learnings)
                    if result:
                        context.phase2e_learnings = result
                except Exception as e:
                    logger.warning(f"Error fetching Phase 2E learnings: {type(e).__name__}")

            # タスクD: エピソード記憶を想起（キャッシュ参照のみ、高速）
            # recall()はin-memoryキャッシュを参照するため to_thread で安全に呼ぶ
            if message and hasattr(self, 'episodic_memory') and self.episodic_memory:
                try:
                    recall_results = await asyncio.to_thread(
                        self.episodic_memory.recall, message, user_id
                    )
                    if recall_results:
                        context.recent_episodes = recall_results
                        logger.debug("Recalled %d episodes", len(recall_results))
                except Exception as e:
                    logger.warning(f"Error recalling episodes: {type(e).__name__}")

            logger.debug(
                f"Context loaded: conversation={len(context.recent_conversation)}, "
                f"tasks={len(context.recent_tasks)}, goals={len(context.active_goals)}, "
                f"insights={len(context.insights)}"
            )

        except Exception as e:
            logger.warning(f"Error fetching context via BrainMemoryAccess: {type(e).__name__}")
            # コンテキスト取得に失敗しても処理は続行

        return context

    async def _get_recent_conversation(
        self,
        room_id: str,
        user_id: str,
    ) -> List[ConversationMessage]:
        """直近の会話を取得（BrainMemoryAccess経由）"""
        messages = await self.memory_access.get_recent_conversation(room_id, user_id)
        return [
            ConversationMessage(
                role=msg.role,
                content=msg.content,
                timestamp=msg.timestamp if msg.timestamp else datetime.now(),
            )
            for msg in messages
        ]

    async def _get_conversation_summary(self, user_id: str):
        """会話要約を取得（BrainMemoryAccess経由）"""
        return await self.memory_access.get_conversation_summary(user_id)

    async def _get_user_preferences(self, user_id: str):
        """ユーザー嗜好を取得（BrainMemoryAccess経由）"""
        return await self.memory_access.get_user_preferences(user_id)

    async def _get_person_info(self) -> List[Any]:
        """人物情報を取得（BrainMemoryAccess経由）"""
        result: List[Any] = await self.memory_access.get_person_info()
        return result

    async def _get_recent_tasks(self, user_id: str) -> List[Any]:
        """直近のタスクを取得（BrainMemoryAccess経由）"""
        result: List[Any] = await self.memory_access.get_recent_tasks(user_id)
        return result

    async def _get_active_goals(self, user_id: str) -> List[Any]:
        """アクティブな目標を取得（BrainMemoryAccess経由）"""
        result: List[Any] = await self.memory_access.get_active_goals(user_id)
        return result

    async def _get_insights(self) -> List[Any]:
        """インサイトを取得（BrainMemoryAccess経由）"""
        result: List[Any] = await self.memory_access.get_recent_insights()
        return result

    async def _get_relevant_knowledge(self, query: str) -> List[Any]:
        """関連知識を取得（BrainMemoryAccess経由）"""
        result: List[Any] = await self.memory_access.get_relevant_knowledge(query)
        return result
