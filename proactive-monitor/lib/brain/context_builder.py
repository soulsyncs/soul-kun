# lib/brain/context_builder.py
"""
LLM Brainに渡すコンテキストを構築する

設計書: docs/25_llm_native_brain_architecture.md セクション5.1（6.1）

【目的】
LLM Brainに渡す「文脈情報」を構築する。
全ての記憶・状態・設計思想をここで集約し、LLMが適切な判断を行えるようにする。

【収集する情報（優先順）】
1. 現在の状態（セッション状態、pending操作）
2. 会話履歴（直近10件）
3. ユーザー情報・嗜好
4. 記憶（人物情報、タスク、目標）
5. 価値観（CEO教え、会社のMVV）
6. ナレッジ（必要時に遅延取得）

【Truth順位（CLAUDE.md セクション3）】
1位: リアルタイムAPI
2位: DB（正規データ）
3位: 設計書・仕様書
4位: Memory（会話の文脈）
5位: 推測 → 禁止

Author: Claude Opus 4.5
Created: 2026-01-30
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any, List
from zoneinfo import ZoneInfo

# SoT: lib/brain/models.py から統一版をimport
from lib.brain.models import PersonInfo, TaskInfo, GoalInfo

logger = logging.getLogger(__name__)

# 日本時間
JST = ZoneInfo("Asia/Tokyo")


# =============================================================================
# データクラス
# =============================================================================

@dataclass
class Message:
    """会話メッセージ"""
    role: str  # "user" or "assistant"
    content: str
    timestamp: Optional[datetime] = None
    sender: Optional[str] = None  # sender name for display

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "sender": self.sender,
        }


@dataclass
class UserPreferences:
    """ユーザー嗜好"""
    preferred_name: Optional[str] = None  # 呼ばれたい名前
    report_format: Optional[str] = None   # 報告形式の好み
    notification_time: Optional[str] = None  # 通知希望時間
    other_preferences: Dict[str, Any] = field(default_factory=dict)

    def to_string(self) -> str:
        parts = []
        if self.preferred_name:
            parts.append(f"呼び名: {self.preferred_name}")
        if self.report_format:
            parts.append(f"報告形式: {self.report_format}")
        if self.notification_time:
            parts.append(f"通知時間: {self.notification_time}")
        for key, value in self.other_preferences.items():
            parts.append(f"{key}: {value}")
        return ", ".join(parts) if parts else "なし"


# PersonInfo, TaskInfo, GoalInfo は lib/brain/models.py からimport済み
# 重複定義を避けるため、ここでは定義しない（SoT: models.py）


@dataclass
class CEOTeaching:
    """CEO教え"""
    content: str
    category: Optional[str] = None
    priority: int = 0
    created_at: Optional[datetime] = None

    def to_string(self) -> str:
        if self.category:
            return f"[{self.category}] {self.content}"
        return self.content


@dataclass
class KnowledgeChunk:
    """ナレッジの断片"""
    content: str
    source: str
    relevance_score: float = 0.0


@dataclass
class SessionState:
    """セッション状態（LLM Brain用の簡易版）"""
    mode: str = "normal"  # normal, confirmation_pending, multi_step_flow
    pending_action: Optional[Dict[str, Any]] = None
    last_intent: Optional[str] = None
    last_tool_called: Optional[str] = None

    def to_string(self) -> str:
        lines = [f"モード: {self.mode}"]
        if self.pending_action:
            lines.append(f"確認待ち: {self.pending_action.get('tool_name', '不明')}")
        if self.last_intent:
            lines.append(f"直前の意図: {self.last_intent}")
        return "\n".join(lines)


@dataclass
class LLMContext:
    """
    LLM Brainに渡すコンテキスト

    設計書: docs/25_llm_native_brain_architecture.md セクション5.1.3
    """

    # === 現在の状態 ===
    session_state: Optional[SessionState] = None
    pending_action: Optional[Dict[str, Any]] = None

    # === ユーザー情報 ===
    user_id: str = ""
    user_name: str = ""
    user_role: str = ""
    user_preferences: Optional[UserPreferences] = None

    # === 会話履歴 ===
    recent_messages: List[Message] = field(default_factory=list)
    conversation_summary: Optional[str] = None

    # === 記憶 ===
    known_persons: List[PersonInfo] = field(default_factory=list)
    recent_tasks: List[TaskInfo] = field(default_factory=list)
    active_goals: List[GoalInfo] = field(default_factory=list)

    # === 価値観 ===
    ceo_teachings: List[CEOTeaching] = field(default_factory=list)
    company_values: str = ""

    # === ナレッジ（遅延取得可） ===
    relevant_knowledge: Optional[List[KnowledgeChunk]] = None

    # === メタ情報 ===
    current_datetime: datetime = field(default_factory=lambda: datetime.now(JST))
    organization_id: str = ""
    room_id: str = ""

    def to_prompt_string(self) -> str:
        """
        LLMプロンプト用の文字列に変換

        Returns:
            LLMに渡す形式のコンテキスト文字列
        """
        sections = []

        # 現在の状態
        if self.session_state:
            sections.append(f"【現在のセッション】\n{self.session_state.to_string()}")
        if self.pending_action:
            tool_name = self.pending_action.get("tool_name", "不明")
            question = self.pending_action.get("confirmation_question", "")
            sections.append(f"【確認待ち操作】\nTool: {tool_name}\n確認質問: {question}")

        # ユーザー情報
        user_info_lines = [
            f"- 名前: {self.user_name}",
            f"- 役職: {self.user_role}" if self.user_role else None,
            f"- 嗜好: {self.user_preferences.to_string()}" if self.user_preferences else None,
        ]
        user_info = "\n".join([line for line in user_info_lines if line])
        sections.append(f"【ユーザー情報】\n{user_info}")

        # 会話履歴（直近5件）
        if self.recent_messages:
            history_lines = []
            for m in self.recent_messages[-5:]:
                sender = m.sender or ("ソウルくん" if m.role == "assistant" else "ユーザー")
                history_lines.append(f"- {sender}: {m.content[:100]}{'...' if len(m.content) > 100 else ''}")
            sections.append(f"【直近の会話】\n" + "\n".join(history_lines))

        # 記憶している人物
        if self.known_persons:
            persons = "\n".join([f"- {p.to_string()}" for p in self.known_persons[:5]])
            sections.append(f"【記憶している人物】\n{persons}")

        # 関連タスク
        if self.recent_tasks:
            tasks = "\n".join([f"- {t.to_string()}" for t in self.recent_tasks[:5]])
            sections.append(f"【関連タスク】\n{tasks}")

        # アクティブな目標
        if self.active_goals:
            goals = "\n".join([f"- {g.to_string()}" for g in self.active_goals[:3]])
            sections.append(f"【アクティブな目標】\n{goals}")

        # CEO教え
        if self.ceo_teachings:
            teachings = "\n".join([f"- {t.to_string()}" for t in self.ceo_teachings[:3]])
            sections.append(f"【CEO教え（最優先で従う）】\n{teachings}")

        # ナレッジ
        if self.relevant_knowledge:
            knowledge = "\n".join([f"- {k.content[:100]}..." for k in self.relevant_knowledge[:3]])
            sections.append(f"【関連ナレッジ】\n{knowledge}")

        # 現在日時
        sections.append(f"【現在日時】\n{self.current_datetime.strftime('%Y年%m月%d日 %H:%M')}")

        return "\n\n".join(sections)


# =============================================================================
# ContextBuilder クラス
# =============================================================================

class ContextBuilder:
    """
    LLM Brainに渡すコンテキストを構築する

    設計書: docs/25_llm_native_brain_architecture.md セクション5.1

    【使用例】
    builder = ContextBuilder(pool, memory_access, state_manager, ceo_repo)
    context = await builder.build(user_id, room_id, organization_id, message)
    """

    def __init__(
        self,
        pool,
        memory_access=None,
        state_manager=None,
        ceo_teaching_repository=None,
    ):
        """
        Args:
            pool: データベース接続プール
            memory_access: BrainMemoryAccessインスタンス（Noneの場合は内部で生成）
            state_manager: BrainStateManagerインスタンス
            ceo_teaching_repository: CEOTeachingRepositoryインスタンス
        """
        self.pool = pool
        self.memory_access = memory_access
        self.state_manager = state_manager
        self.ceo_teaching_repository = ceo_teaching_repository

    async def build(
        self,
        user_id: str,
        room_id: str,
        organization_id: str,
        message: str,
        sender_name: Optional[str] = None,
    ) -> LLMContext:
        """
        コンテキストを構築する

        Truth順位（CLAUDE.md セクション3）に従ってデータを取得。
        1位: リアルタイムAPI
        2位: DB（正規データ）
        3位: 設計書・仕様書
        4位: Memory（会話の文脈）
        5位: 推測 → 禁止

        Args:
            user_id: ユーザーID
            room_id: ChatWorkルームID
            organization_id: 組織ID
            message: 現在のユーザーメッセージ
            sender_name: 送信者名

        Returns:
            LLMContext: 構築されたコンテキスト
        """
        logger.info(f"Building LLM context for user={user_id}, room={room_id}")

        # 並列で全ての情報を取得
        tasks = [
            self._get_session_state(user_id, room_id),
            self._get_recent_messages(user_id, room_id, organization_id),
            self._get_conversation_summary(user_id, organization_id),
            self._get_user_preferences(user_id, organization_id),
            self._get_known_persons(organization_id),
            self._get_recent_tasks(user_id, room_id, organization_id),
            self._get_active_goals(user_id, organization_id),
            self._get_ceo_teachings(organization_id, message),
            self._get_user_info(user_id, organization_id, sender_name),
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 結果を展開（エラーはログしてデフォルト値を使用）
        (
            session_state,
            recent_messages,
            conversation_summary,
            user_preferences,
            known_persons,
            recent_tasks,
            active_goals,
            ceo_teachings,
            user_info,
        ) = self._handle_results(results)

        return LLMContext(
            session_state=session_state,
            pending_action=session_state.pending_action if session_state else None,
            user_id=user_id,
            user_name=user_info.get("name", sender_name or "ユーザー"),
            user_role=user_info.get("role", ""),
            user_preferences=user_preferences,
            recent_messages=recent_messages,
            conversation_summary=conversation_summary,
            known_persons=known_persons,
            recent_tasks=recent_tasks,
            active_goals=active_goals,
            ceo_teachings=ceo_teachings,
            company_values=self._get_company_values(),
            relevant_knowledge=None,  # 必要時に遅延取得
            current_datetime=datetime.now(JST),
            organization_id=organization_id,
            room_id=room_id,
        )

    def _handle_results(self, results: List[Any]) -> tuple:
        """結果を処理し、エラーをログする"""
        field_names = [
            "session_state",
            "recent_messages",
            "conversation_summary",
            "user_preferences",
            "known_persons",
            "recent_tasks",
            "active_goals",
            "ceo_teachings",
            "user_info",
        ]
        defaults = [
            None,  # session_state
            [],    # recent_messages
            None,  # conversation_summary
            None,  # user_preferences
            [],    # known_persons
            [],    # recent_tasks
            [],    # active_goals
            [],    # ceo_teachings
            {},    # user_info
        ]

        processed = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.warning(f"Error fetching {field_names[i]}: {result}")
                processed.append(defaults[i])
            else:
                processed.append(result)

        return tuple(processed)

    async def _get_session_state(
        self,
        user_id: str,
        room_id: str,
    ) -> Optional[SessionState]:
        """セッション状態を取得"""
        if not self.state_manager:
            return None

        try:
            state = await self.state_manager.get_current_state(room_id, user_id)
            if not state:
                return None

            return SessionState(
                mode=state.state_type.value if hasattr(state, 'state_type') else "normal",
                pending_action=state.state_data if hasattr(state, 'state_data') else None,
                last_intent=state.state_step if hasattr(state, 'state_step') else None,
            )
        except Exception as e:
            logger.warning(f"Error getting session state: {e}")
            return None

    async def _get_recent_messages(
        self,
        user_id: str,
        room_id: str,
        organization_id: str,
    ) -> List[Message]:
        """直近の会話履歴を取得"""
        if not self.memory_access:
            return []

        try:
            messages = await self.memory_access.get_recent_conversation(room_id, user_id)
            return [
                Message(
                    role=msg.role,
                    content=msg.content,
                    timestamp=msg.timestamp,
                    sender=None,
                )
                for msg in messages
            ]
        except Exception as e:
            logger.warning(f"Error getting recent messages: {e}")
            return []

    async def _get_conversation_summary(
        self,
        user_id: str,
        organization_id: str,
    ) -> Optional[str]:
        """会話の要約を取得"""
        if not self.memory_access:
            return None

        try:
            summary = await self.memory_access.get_conversation_summary(user_id)
            if summary and hasattr(summary, 'summary_text'):
                return summary.summary_text
            return None
        except Exception as e:
            logger.warning(f"Error getting conversation summary: {e}")
            return None

    async def _get_user_preferences(
        self,
        user_id: str,
        organization_id: str,
    ) -> Optional[UserPreferences]:
        """ユーザー嗜好を取得"""
        if not self.memory_access:
            return None

        try:
            prefs = await self.memory_access.get_user_preferences(user_id)
            if not prefs:
                return None

            # 嗜好をUserPreferencesに変換
            result = UserPreferences()
            for pref in prefs:
                if hasattr(pref, 'preference_key') and hasattr(pref, 'preference_value'):
                    key = pref.preference_key
                    value = pref.preference_value
                    if key == "preferred_name":
                        result.preferred_name = value
                    elif key == "report_format":
                        result.report_format = value
                    elif key == "notification_time":
                        result.notification_time = value
                    else:
                        result.other_preferences[key] = value
            return result
        except Exception as e:
            logger.warning(f"Error getting user preferences: {e}")
            return None

    async def _get_known_persons(
        self,
        organization_id: str,
    ) -> List[PersonInfo]:
        """記憶している人物情報を取得"""
        if not self.memory_access:
            return []

        try:
            persons = await self.memory_access.get_person_info()
            return [
                PersonInfo(
                    person_id=p.person_id if hasattr(p, 'person_id') else "",  # 修正: person_id追加
                    name=p.name,
                    description=str(p.attributes) if p.attributes else "",
                    attributes=p.attributes if p.attributes else {},
                )
                for p in persons[:10]  # 最大10人
            ]
        except Exception as e:
            logger.warning(f"Error getting known persons: {e}")
            return []

    async def _get_recent_tasks(
        self,
        user_id: str,
        room_id: str,
        organization_id: str,
    ) -> List[TaskInfo]:
        """関連タスクを取得"""
        if not self.memory_access:
            return []

        try:
            tasks = await self.memory_access.get_recent_tasks(user_id)
            return [
                TaskInfo(
                    task_id=str(t.task_id),
                    title=t.summary or t.body[:50],
                    due_date=t.due_date,  # 修正: limit_time → due_date（統一版フィールド名）
                    status=t.status,
                    assignee_name=t.assignee_name,  # 修正: assigned_to → assignee_name
                    assigned_by_name=t.assigned_by_name,  # 修正: assigned_by → assigned_by_name
                    is_overdue=t.is_overdue,
                )
                for t in tasks[:10]  # 最大10件
            ]
        except Exception as e:
            logger.warning(f"Error getting recent tasks: {e}")
            return []

    async def _get_active_goals(
        self,
        user_id: str,
        organization_id: str,
    ) -> List[GoalInfo]:
        """アクティブな目標を取得"""
        if not self.memory_access:
            return []

        try:
            goals = await self.memory_access.get_active_goals(user_id)
            result = []
            for g in goals[:5]:  # 最大5件
                # memory_access.GoalInfoオブジェクトから属性を直接取得
                goal_info = GoalInfo(
                    goal_id=str(g.goal_id) if g.goal_id else "",  # 修正: g.id → g.goal_id（統一版フィールド名）
                    title=g.title or "",
                    progress=float(g.progress) if g.progress else 0.0,
                    status=g.status or "active",
                )
                result.append(goal_info)
            return result
        except Exception as e:
            logger.warning(f"Error getting active goals: {e}")
            return []

    async def _get_ceo_teachings(
        self,
        organization_id: str,
        message: str,
    ) -> List[CEOTeaching]:
        """CEO教えを取得"""
        if not self.ceo_teaching_repository:
            return []

        try:
            # 関連するCEO教えを検索
            teachings = await self.ceo_teaching_repository.search_relevant(
                query=message,
                organization_id=organization_id,
                limit=5,
            )
            return [
                CEOTeaching(
                    content=t.content if hasattr(t, 'content') else str(t),
                    category=t.category if hasattr(t, 'category') else None,
                    priority=t.priority if hasattr(t, 'priority') else 0,
                )
                for t in teachings
            ]
        except Exception as e:
            logger.warning(f"Error getting CEO teachings: {e}")
            return []

    async def _get_user_info(
        self,
        user_id: str,
        organization_id: str,
        sender_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """ユーザー基本情報を取得"""
        # TODO: ユーザーテーブルから取得する実装を追加
        return {
            "name": sender_name or "ユーザー",
            "role": "",
        }

    def _get_company_values(self) -> str:
        """会社の価値観（MVV）を取得"""
        # 設計書 docs/01_philosophy_and_principles.md より
        return """
ミッション: 可能性の解放
ビジョン: 前を向く全ての人の可能性を解放し続けることで、企業も人も心で繋がる未来
バリュー: 感謝で自分を満たし、満たした自分で相手を満たし、相手も自分で自分を満たせるように伴走する
""".strip()

    async def enrich_with_knowledge(
        self,
        context: LLMContext,
        query: str,
    ) -> LLMContext:
        """
        必要に応じてナレッジを追加取得

        Args:
            context: 既存のコンテキスト
            query: 検索クエリ

        Returns:
            ナレッジを追加したコンテキスト
        """
        if not self.memory_access:
            return context

        try:
            knowledge = await self.memory_access.get_relevant_knowledge(query)
            context.relevant_knowledge = [
                KnowledgeChunk(
                    content=k.get("content", ""),
                    source=k.get("source", ""),
                    relevance_score=k.get("score", 0.0),
                )
                for k in knowledge[:5]
            ]
        except Exception as e:
            logger.warning(f"Error enriching with knowledge: {e}")

        return context
