# lib/brain/memory_access.py
"""
ソウルくんの脳 - 記憶アクセス層

このモジュールは、脳が必要とする全ての記憶を統一的にアクセスする機能を提供します。
複数の記憶ソース（Firestore、PostgreSQL、Memory Framework）を抽象化し、
脳が一貫したインターフェースで記憶を取得できるようにします。

設計書: docs/13_brain_architecture.md

【記憶ソースの種類】
1. conversation_history (Firestore) - 直近の会話履歴
2. conversation_summaries (B1) - 会話の要約記憶
3. user_preferences (B2) - ユーザーの嗜好
4. persons - 人物情報
5. chatwork_tasks - タスク情報
6. goals - 目標情報
7. soulkun_knowledge - 会社知識
8. soulkun_insights - インサイト情報

【10の鉄則準拠】
- 全クエリにorganization_idフィルタを含む
- SQLインジェクション対策（パラメータ化クエリ）
- エラー時は空のデータを返す（処理を止めない）
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List, Union
from uuid import UUID

from sqlalchemy import text

from lib.brain.constants import (
    RECENT_CONVERSATION_LIMIT,
    RECENT_TASKS_LIMIT,
    INSIGHTS_LIMIT,
)
from lib.brain.exceptions import MemoryAccessError, MemoryNotFoundError, MemoryConnectionError

logger = logging.getLogger(__name__)


# =============================================================================
# データクラス（記憶の型定義）
# =============================================================================


@dataclass
class ConversationMessage:
    """会話メッセージ"""
    role: str  # "user" or "assistant"
    content: str
    timestamp: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }


@dataclass
class ConversationSummaryData:
    """会話要約データ"""
    id: Optional[UUID] = None
    summary_text: str = ""
    key_topics: List[str] = field(default_factory=list)
    mentioned_persons: List[str] = field(default_factory=list)
    mentioned_tasks: List[str] = field(default_factory=list)
    message_count: int = 0
    created_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id) if self.id else None,
            "summary_text": self.summary_text,
            "key_topics": self.key_topics,
            "mentioned_persons": self.mentioned_persons,
            "mentioned_tasks": self.mentioned_tasks,
            "message_count": self.message_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


@dataclass
class UserPreferenceData:
    """ユーザー嗜好データ"""
    preference_type: str = ""
    preference_key: str = ""
    preference_value: Any = None
    confidence: float = 0.5

    def to_dict(self) -> Dict[str, Any]:
        return {
            "preference_type": self.preference_type,
            "preference_key": self.preference_key,
            "preference_value": self.preference_value,
            "confidence": self.confidence,
        }


@dataclass
class PersonInfo:
    """人物情報"""
    id: Optional[UUID] = None
    name: str = ""
    attributes: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id) if self.id else None,
            "name": self.name,
            "attributes": self.attributes,
        }


@dataclass
class TaskInfo:
    """タスク情報"""
    task_id: str = ""
    body: str = ""
    summary: Optional[str] = None
    status: str = "open"
    limit_time: Optional[datetime] = None
    room_id: Optional[str] = None
    room_name: Optional[str] = None
    assigned_to_name: Optional[str] = None
    assigned_by_name: Optional[str] = None
    is_overdue: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "body": self.body,
            "summary": self.summary,
            "status": self.status,
            "limit_time": self.limit_time.isoformat() if self.limit_time else None,
            "room_id": self.room_id,
            "room_name": self.room_name,
            "assigned_to_name": self.assigned_to_name,
            "assigned_by_name": self.assigned_by_name,
            "is_overdue": self.is_overdue,
        }


@dataclass
class GoalInfo:
    """目標情報"""
    id: Optional[UUID] = None
    title: str = ""
    why: Optional[str] = None
    what: Optional[str] = None
    how: Optional[str] = None
    status: str = "active"
    progress: float = 0.0
    deadline: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id) if self.id else None,
            "title": self.title,
            "why": self.why,
            "what": self.what,
            "how": self.how,
            "status": self.status,
            "progress": self.progress,
            "deadline": self.deadline.isoformat() if self.deadline else None,
        }


@dataclass
class KnowledgeInfo:
    """会社知識情報"""
    id: Optional[UUID] = None
    keyword: str = ""
    answer: str = ""
    category: Optional[str] = None
    relevance_score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id) if self.id else None,
            "keyword": self.keyword,
            "answer": self.answer,
            "category": self.category,
            "relevance_score": self.relevance_score,
        }


@dataclass
class InsightInfo:
    """インサイト情報"""
    id: Optional[UUID] = None
    insight_type: str = ""
    importance: str = "medium"
    title: str = ""
    description: str = ""
    recommended_action: Optional[str] = None
    status: str = "new"
    created_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id) if self.id else None,
            "insight_type": self.insight_type,
            "importance": self.importance,
            "title": self.title,
            "description": self.description,
            "recommended_action": self.recommended_action,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# =============================================================================
# BrainMemoryAccess クラス
# =============================================================================


class BrainMemoryAccess:
    """
    脳の記憶アクセス層

    全ての記憶ソースを統一的なインターフェースで提供する。
    並列クエリ、エラーハンドリング、フォールバック機能を持つ。

    使用例:
        memory = BrainMemoryAccess(pool=db_pool, org_id="org_soulsyncs")

        # 並列で全ての記憶を取得
        context = await memory.get_all_context(
            room_id="123456",
            user_id="7890",
            sender_name="菊地"
        )

        # 個別取得
        tasks = await memory.get_recent_tasks(user_id="7890")
    """

    # 会話履歴の有効期限（時間）
    HISTORY_EXPIRY_HOURS: int = 24

    # 会話履歴の最大件数
    MAX_HISTORY_COUNT: int = 10

    def __init__(
        self,
        pool,
        org_id: str,
        firestore_db=None,
    ):
        """
        Args:
            pool: SQLAlchemyデータベース接続プール
            org_id: 組織ID
            firestore_db: Firestore クライアント（オプション）
        """
        self.pool = pool
        self.org_id = org_id
        self.firestore_db = firestore_db
        # org_idがUUID形式かどうかをチェック（soulkun_insights等はUUID型を要求）
        self._org_id_is_uuid = self._check_is_uuid(org_id)

        logger.info(f"BrainMemoryAccess initialized for org_id={org_id}, is_uuid={self._org_id_is_uuid}")

    @staticmethod
    def _check_is_uuid(value: str) -> bool:
        """値がUUID形式かどうかをチェック"""
        try:
            import uuid
            uuid.UUID(value)
            return True
        except (ValueError, AttributeError):
            return False

    # =========================================================================
    # 統合アクセス（並列取得）
    # =========================================================================

    async def get_all_context(
        self,
        room_id: str,
        user_id: str,
        sender_name: str,
        message: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        脳が判断に必要な全ての記憶を並列で取得

        Args:
            room_id: ChatWorkルームID
            user_id: ユーザーのアカウントID
            sender_name: 送信者名
            message: 現在のメッセージ（関連知識検索に使用）

        Returns:
            Dict: 全ての記憶を含む辞書
        """
        # 並列で全ての記憶を取得（エラーは個別に処理）
        results = await asyncio.gather(
            self.get_recent_conversation(room_id, user_id),
            self.get_conversation_summary(user_id),
            self.get_user_preferences(user_id),
            self.get_person_info(),
            self.get_recent_tasks(user_id),
            self.get_active_goals(user_id),
            self.get_relevant_knowledge(message) if message else self._empty_list(),
            self.get_recent_insights(),
            return_exceptions=True,
        )

        context = {
            "organization_id": self.org_id,
            "room_id": room_id,
            "sender_name": sender_name,
            "sender_account_id": user_id,
            "timestamp": datetime.now(),
            "recent_conversation": [],
            "conversation_summary": None,
            "user_preferences": [],
            "person_info": [],
            "recent_tasks": [],
            "active_goals": [],
            "relevant_knowledge": [],
            "insights": [],
        }

        # 結果を統合（例外は個別にログして空データで継続）
        field_names = [
            "recent_conversation",
            "conversation_summary",
            "user_preferences",
            "person_info",
            "recent_tasks",
            "active_goals",
            "relevant_knowledge",
            "insights",
        ]

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.warning(f"Memory access error for {field_names[i]}: {result}")
            else:
                context[field_names[i]] = result

        return context

    async def _empty_list(self) -> List:
        """空リストを返す（awaitable版）"""
        return []

    # =========================================================================
    # 会話履歴（Firestore）
    # =========================================================================

    async def get_recent_conversation(
        self,
        room_id: str,
        user_id: str,
    ) -> List[ConversationMessage]:
        """
        直近の会話履歴を取得（Firestoreから）

        Args:
            room_id: ChatWorkルームID
            user_id: ユーザーのアカウントID

        Returns:
            List[ConversationMessage]: 直近の会話メッセージ
        """
        if not self.firestore_db:
            logger.debug("Firestore not configured, returning empty conversation")
            return []

        try:
            doc_ref = self.firestore_db.collection("conversations").document(
                f"{room_id}_{user_id}"
            )
            doc = doc_ref.get()

            if not doc.exists:
                return []

            data = doc.to_dict()
            updated_at = data.get("updated_at")

            # 有効期限チェック
            if updated_at:
                expiry_time = datetime.now(timezone.utc) - timedelta(
                    hours=self.HISTORY_EXPIRY_HOURS
                )
                if updated_at.replace(tzinfo=timezone.utc) < expiry_time:
                    return []

            # 会話履歴をデータクラスに変換
            history = data.get("history", [])[-self.MAX_HISTORY_COUNT:]
            return [
                ConversationMessage(
                    role=msg.get("role", "user"),
                    content=msg.get("content", ""),
                    timestamp=msg.get("timestamp"),
                )
                for msg in history
            ]

        except Exception as e:
            logger.warning(f"Error fetching conversation history: {e}")
            return []

    # =========================================================================
    # 会話要約（B1: conversation_summaries）
    # =========================================================================

    async def get_conversation_summary(
        self,
        user_id: str,
    ) -> Optional[ConversationSummaryData]:
        """
        最新の会話要約を取得

        Args:
            user_id: ユーザーのアカウントID

        Returns:
            ConversationSummaryData: 会話要約（なければNone）
        """
        try:
            # Note: user_idはChatWork account_idなので、users.chatwork_account_idと照合が必要
            # 現状はuser_idがUUIDでない場合を考慮して、ChatWork account_idで検索
            with self.pool.connect() as conn:
                result = conn.execute(
                    text("""
                        SELECT
                            cs.id,
                            cs.summary_text,
                            cs.key_topics,
                            cs.mentioned_persons,
                            cs.mentioned_tasks,
                            cs.message_count,
                            cs.created_at
                        FROM conversation_summaries cs
                        JOIN users u ON cs.user_id = u.id
                        WHERE u.chatwork_account_id = :user_id
                          AND cs.organization_id = :org_id
                        ORDER BY cs.created_at DESC
                        LIMIT 1
                    """),
                    {"user_id": user_id, "org_id": self.org_id},
                )
                row = result.fetchone()

                if not row:
                    return None

                return ConversationSummaryData(
                    id=row[0],
                    summary_text=row[1] or "",
                    key_topics=row[2] or [],
                    mentioned_persons=row[3] or [],
                    mentioned_tasks=row[4] or [],
                    message_count=row[5] or 0,
                    created_at=row[6],
                )

        except Exception as e:
            logger.warning(f"Error fetching conversation summary: {e}")
            return None

    # =========================================================================
    # ユーザー嗜好（B2: user_preferences）
    # =========================================================================

    async def get_user_preferences(
        self,
        user_id: str,
    ) -> List[UserPreferenceData]:
        """
        ユーザーの嗜好を取得

        Args:
            user_id: ユーザーのアカウントID

        Returns:
            List[UserPreferenceData]: ユーザー嗜好のリスト
        """
        try:
            with self.pool.connect() as conn:
                result = conn.execute(
                    text("""
                        SELECT
                            up.preference_type,
                            up.preference_key,
                            up.preference_value,
                            up.confidence
                        FROM user_preferences up
                        JOIN users u ON up.user_id = u.id
                        WHERE u.chatwork_account_id = :user_id
                          AND up.organization_id = :org_id
                        ORDER BY up.confidence DESC
                        LIMIT 20
                    """),
                    {"user_id": user_id, "org_id": self.org_id},
                )
                rows = result.fetchall()

                return [
                    UserPreferenceData(
                        preference_type=row[0] or "",
                        preference_key=row[1] or "",
                        preference_value=row[2],
                        confidence=row[3] or 0.5,
                    )
                    for row in rows
                ]

        except Exception as e:
            logger.warning(f"Error fetching user preferences: {e}")
            return []

    # =========================================================================
    # 人物情報（persons + person_attributes）
    # =========================================================================

    async def get_person_info(
        self,
        limit: int = 50,
    ) -> List[PersonInfo]:
        """
        登録されている人物情報を取得

        Args:
            limit: 最大取得件数

        Returns:
            List[PersonInfo]: 人物情報のリスト
        """
        try:
            with self.pool.connect() as conn:
                # personsテーブルから人物を取得
                result = conn.execute(
                    text("""
                        SELECT id, name
                        FROM persons
                        ORDER BY name
                        LIMIT :limit
                    """),
                    {"limit": limit},
                )
                person_rows = result.fetchall()

                persons = []
                for row in person_rows:
                    person_id = row[0]
                    name = row[1]

                    # person_attributesから属性を取得
                    attr_result = conn.execute(
                        text("""
                            SELECT attribute_type, attribute_value
                            FROM person_attributes
                            WHERE person_id = :person_id
                            ORDER BY updated_at DESC
                        """),
                        {"person_id": person_id},
                    )
                    attr_rows = attr_result.fetchall()
                    attributes = {attr[0]: attr[1] for attr in attr_rows}

                    persons.append(
                        PersonInfo(
                            id=person_id,
                            name=name,
                            attributes=attributes,
                        )
                    )

                return persons

        except Exception as e:
            logger.warning(f"Error fetching person info: {e}")
            return []

    # =========================================================================
    # タスク情報（chatwork_tasks）
    # =========================================================================

    async def get_recent_tasks(
        self,
        user_id: str,
        limit: int = RECENT_TASKS_LIMIT,
    ) -> List[TaskInfo]:
        """
        ユーザーに関連するタスクを取得

        Args:
            user_id: ユーザーのアカウントID
            limit: 最大取得件数

        Returns:
            List[TaskInfo]: タスク情報のリスト
        """
        try:
            now = datetime.now()

            with self.pool.connect() as conn:
                # limit_time は BIGINT (Unix timestamp) なので to_timestamp() で比較
                result = conn.execute(
                    text("""
                        SELECT
                            task_id,
                            body,
                            summary,
                            status,
                            limit_time,
                            room_id,
                            room_name,
                            assigned_to_name,
                            assigned_by_name
                        FROM chatwork_tasks
                        WHERE assigned_to_account_id = :user_id
                          AND status = 'open'
                        ORDER BY
                            CASE WHEN limit_time IS NOT NULL AND to_timestamp(limit_time) < NOW()
                                 THEN 0 ELSE 1 END,
                            limit_time ASC NULLS LAST
                        LIMIT :limit
                    """),
                    {"user_id": user_id, "limit": limit},
                )
                rows = result.fetchall()

                return [
                    TaskInfo(
                        task_id=str(row[0]) if row[0] else "",
                        body=row[1] or "",
                        summary=row[2],
                        status=row[3] or "open",
                        limit_time=row[4],
                        room_id=str(row[5]) if row[5] else None,
                        room_name=row[6],
                        assigned_to_name=row[7],
                        assigned_by_name=row[8],
                        is_overdue=(row[4] < now if row[4] else False),
                    )
                    for row in rows
                ]

        except Exception as e:
            logger.warning(f"Error fetching recent tasks: {e}")
            return []

    # =========================================================================
    # 目標情報（goals）
    # =========================================================================

    async def get_active_goals(
        self,
        user_id: str,
    ) -> List[GoalInfo]:
        """
        ユーザーのアクティブな目標を取得

        Args:
            user_id: ユーザーのアカウントID

        Returns:
            List[GoalInfo]: 目標情報のリスト
        """
        # goals テーブルは organization_id が UUID 型
        if not self._org_id_is_uuid:
            logger.debug(f"Skipping goals query: org_id={self.org_id} is not UUID format")
            return []

        try:
            with self.pool.connect() as conn:
                # 実際のgoalsテーブルスキーマに合わせたクエリ
                # カラム: id, title, description, target_value, current_value, deadline, status
                result = conn.execute(
                    text("""
                        SELECT
                            g.id,
                            g.title,
                            g.description,
                            g.target_value,
                            g.current_value,
                            g.status,
                            g.deadline
                        FROM goals g
                        JOIN users u ON g.user_id = u.id
                        WHERE u.chatwork_account_id = :user_id
                          AND g.organization_id = :org_id::uuid
                          AND g.status = 'active'
                        ORDER BY g.created_at DESC
                        LIMIT 5
                    """),
                    {"user_id": user_id, "org_id": self.org_id},
                )
                rows = result.fetchall()

                return [
                    GoalInfo(
                        id=row[0],
                        title=row[1] or "",
                        why=None,  # goalsテーブルにwhy_reasonカラムは存在しない
                        what=row[2],  # descriptionをwhatとして使用
                        how=None,  # goalsテーブルにhow_methodカラムは存在しない
                        status=row[5] or "active",
                        progress=float(row[4] / row[3] * 100) if row[3] and row[4] else 0.0,
                        deadline=row[6],
                    )
                    for row in rows
                ]

        except Exception as e:
            logger.warning(f"Error fetching active goals: {e}")
            return []

    # =========================================================================
    # 会社知識（soulkun_knowledge）
    # =========================================================================

    async def get_relevant_knowledge(
        self,
        query: str,
        limit: int = 5,
    ) -> List[KnowledgeInfo]:
        """
        クエリに関連する会社知識を取得

        Args:
            query: 検索クエリ（ユーザーのメッセージ）
            limit: 最大取得件数

        Returns:
            List[KnowledgeInfo]: 会社知識のリスト
        """
        if not query:
            return []

        try:
            with self.pool.connect() as conn:
                # キーワードマッチで関連知識を検索
                # TODO: 将来的にはベクトル検索（Pinecone）と組み合わせる
                # 注意: ILIKE の % は CONCAT を使用（SQLAlchemy が %s と誤解するため）
                result = conn.execute(
                    text("""
                        SELECT
                            id,
                            keyword,
                            answer,
                            category,
                            COALESCE(similarity(keyword, :query), 0) AS score
                        FROM soulkun_knowledge
                        WHERE keyword ILIKE CONCAT('%%', :query, '%%')
                           OR answer ILIKE CONCAT('%%', :query, '%%')
                        ORDER BY score DESC
                        LIMIT :limit
                    """),
                    {"query": query, "limit": limit},
                )
                rows = result.fetchall()

                return [
                    KnowledgeInfo(
                        id=row[0],
                        keyword=row[1] or "",
                        answer=row[2] or "",
                        category=row[3],
                        relevance_score=row[4] or 0.0,
                    )
                    for row in rows
                ]

        except Exception as e:
            # pg_trgm拡張がない場合などはログして空で返す
            logger.warning(f"Error fetching relevant knowledge: {e}")
            return []

    # =========================================================================
    # インサイト情報（soulkun_insights）
    # =========================================================================

    async def get_recent_insights(
        self,
        limit: int = INSIGHTS_LIMIT,
        importance_filter: Optional[List[str]] = None,
    ) -> List[InsightInfo]:
        """
        最新のインサイトを取得

        Args:
            limit: 最大取得件数
            importance_filter: 重要度フィルタ（例: ["critical", "high"]）

        Returns:
            List[InsightInfo]: インサイト情報のリスト
        """
        # soulkun_insights テーブルは organization_id が UUID 型
        if not self._org_id_is_uuid:
            logger.debug(f"Skipping insights query: org_id={self.org_id} is not UUID format")
            return []

        try:
            with self.pool.connect() as conn:
                # 重要度フィルタの組み立て
                importance_clause = ""
                params = {"org_id": self.org_id, "limit": limit}

                if importance_filter:
                    importance_clause = "AND importance = ANY(:importances)"
                    params["importances"] = importance_filter

                result = conn.execute(
                    text(f"""
                        SELECT
                            id,
                            insight_type,
                            importance,
                            title,
                            description,
                            recommended_action,
                            status,
                            created_at
                        FROM soulkun_insights
                        WHERE organization_id = :org_id::uuid
                          AND status IN ('new', 'acknowledged')
                          {importance_clause}
                        ORDER BY
                            CASE importance
                                WHEN 'critical' THEN 0
                                WHEN 'high' THEN 1
                                WHEN 'medium' THEN 2
                                WHEN 'low' THEN 3
                                ELSE 4
                            END,
                            created_at DESC
                        LIMIT :limit
                    """),
                    params,
                )
                rows = result.fetchall()

                return [
                    InsightInfo(
                        id=row[0],
                        insight_type=row[1] or "",
                        importance=row[2] or "medium",
                        title=row[3] or "",
                        description=row[4] or "",
                        recommended_action=row[5],
                        status=row[6] or "new",
                        created_at=row[7],
                    )
                    for row in rows
                ]

        except Exception as e:
            logger.warning(f"Error fetching recent insights: {e}")
            return []

    # =========================================================================
    # 検索機能（B4: conversation_search との連携）
    # =========================================================================

    async def search_conversation(
        self,
        query: str,
        user_id: Optional[str] = None,
        limit: int = 10,
    ) -> List[ConversationMessage]:
        """
        過去の会話を検索（B4 会話検索連携）

        Args:
            query: 検索クエリ
            user_id: ユーザーIDでフィルタ（オプション）
            limit: 最大取得件数

        Returns:
            List[ConversationMessage]: マッチした会話メッセージ
        """
        try:
            with self.pool.connect() as conn:
                # 基本クエリ
                params = {
                    "org_id": self.org_id,
                    "query": f"%{query}%",
                    "limit": limit,
                }

                user_clause = ""
                if user_id:
                    user_clause = "AND ci.user_id = (SELECT id FROM users WHERE chatwork_account_id = :user_id)"
                    params["user_id"] = user_id

                result = conn.execute(
                    text(f"""
                        SELECT
                            ci.role,
                            ci.message,
                            ci.message_time
                        FROM conversation_index ci
                        WHERE ci.organization_id = :org_id
                          AND (ci.message ILIKE :query OR ci.keywords @> ARRAY[:query])
                          {user_clause}
                        ORDER BY ci.message_time DESC
                        LIMIT :limit
                    """),
                    params,
                )
                rows = result.fetchall()

                return [
                    ConversationMessage(
                        role=row[0] or "user",
                        content=row[1] or "",
                        timestamp=row[2],
                    )
                    for row in rows
                ]

        except Exception as e:
            logger.warning(f"Error searching conversation: {e}")
            return []

    # =========================================================================
    # ユーティリティ
    # =========================================================================

    def validate_org_id(self) -> bool:
        """
        organization_idが有効かチェック
        """
        return bool(self.org_id)

    def get_context_summary(self, context: Dict[str, Any]) -> str:
        """
        コンテキストの要約を生成（プロンプト用）

        Args:
            context: get_all_context()の戻り値

        Returns:
            str: コンテキストの要約テキスト
        """
        parts = []

        # 会話要約
        if context.get("conversation_summary"):
            summary = context["conversation_summary"]
            if isinstance(summary, ConversationSummaryData):
                parts.append(f"【会話要約】{summary.summary_text}")
            elif isinstance(summary, dict):
                parts.append(f"【会話要約】{summary.get('summary_text', '')}")

        # ユーザー嗜好
        prefs = context.get("user_preferences", [])
        if prefs:
            pref_texts = []
            for p in prefs[:3]:
                if isinstance(p, UserPreferenceData):
                    pref_texts.append(f"{p.preference_key}: {p.preference_value}")
                elif isinstance(p, dict):
                    pref_texts.append(
                        f"{p.get('preference_key', '')}: {p.get('preference_value', '')}"
                    )
            if pref_texts:
                parts.append(f"【嗜好】{', '.join(pref_texts)}")

        # 直近のタスク
        tasks = context.get("recent_tasks", [])
        overdue = [t for t in tasks if (isinstance(t, TaskInfo) and t.is_overdue) or
                   (isinstance(t, dict) and t.get("is_overdue"))]
        if overdue:
            parts.append(f"【期限超過タスク】{len(overdue)}件")
        if tasks:
            parts.append(f"【未完了タスク】{len(tasks)}件")

        # 目標
        goals = context.get("active_goals", [])
        if goals:
            goal = goals[0]
            if isinstance(goal, GoalInfo):
                parts.append(f"【目標】{goal.title}")
            elif isinstance(goal, dict):
                parts.append(f"【目標】{goal.get('title', '')}")

        # インサイト
        insights = context.get("insights", [])
        critical = [i for i in insights if
                    (isinstance(i, InsightInfo) and i.importance == "critical") or
                    (isinstance(i, dict) and i.get("importance") == "critical")]
        if critical:
            parts.append(f"【重要インサイト】{len(critical)}件")

        return "\n".join(parts) if parts else "（記憶なし）"
