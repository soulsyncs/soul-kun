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
# SoT: lib/brain/models.py から統一版をimport
from lib.brain.models import PersonInfo, TaskInfo, GoalInfo

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


# PersonInfo, TaskInfo, GoalInfo は lib/brain/models.py からimport済み
# 重複定義を避けるため、ここでは定義しない（SoT: models.py）


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
        memory = BrainMemoryAccess(pool=db_pool, org_id="5f98365f-e7c5-4f48-9918-7fe9aabae5df")

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
        memory_flusher=None,
        hybrid_searcher=None,
    ):
        """
        Args:
            pool: SQLAlchemyデータベース接続プール
            org_id: 組織ID
            firestore_db: Firestore クライアント（オプション）
            memory_flusher: AutoMemoryFlusher インスタンス（オプション、v10.57.0追加）
            hybrid_searcher: HybridSearcher インスタンス（オプション、v10.57.1追加）
        """
        self.pool = pool
        if not org_id:
            raise ValueError("org_id is required for MemoryAccess")
        self.org_id = org_id
        self.firestore_db = firestore_db
        self.memory_flusher = memory_flusher
        self.hybrid_searcher = hybrid_searcher
        # フラッシュ重複防止用: (user_id, room_id) → 最終フラッシュ時刻
        self._flush_last_run: Dict[str, datetime] = {}
        # org_idがUUID形式かどうかをチェック（soulkun_insights等はUUID型を要求）
        self._org_id_is_uuid = self._check_is_uuid(org_id)

        logger.debug(f"BrainMemoryAccess initialized: is_uuid={self._org_id_is_uuid}")

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
                logger.warning(f"Memory access error for {field_names[i]}: {type(result).__name__}")
            else:
                context[field_names[i]] = result

        # v10.57.0: 自動メモリフラッシュ
        # 会話履歴が閾値に達したら、重要情報を永続化してから返す
        await self._try_auto_flush(context, user_id, room_id)

        return context

    async def _empty_list(self) -> List:
        """空リストを返す（awaitable版）"""
        return []

    # フラッシュのデバウンス間隔（秒）
    FLUSH_DEBOUNCE_SECONDS: int = 300  # 5分

    async def _try_auto_flush(
        self,
        context: Dict[str, Any],
        user_id: str,
        room_id: str,
    ) -> None:
        """
        自動メモリフラッシュの実行判定と実行（v10.57.0追加）

        会話履歴が閾値に達した場合、重要情報を抽出して永続化する。
        フラッシュはfire-and-forgetで実行し、get_all_context()をブロックしない。
        デバウンス機構により、同一(user_id, room_id)で5分以内の重複フラッシュを防止。
        """
        if not self.memory_flusher:
            return

        conversation = context.get("recent_conversation", [])
        if not self.memory_flusher.should_flush(len(conversation)):
            return

        # デバウンス: 同一(user_id, room_id)で直近5分以内にフラッシュ済みならスキップ
        flush_key = f"{user_id}:{room_id}"
        now = datetime.now(timezone.utc)
        last_run = self._flush_last_run.get(flush_key)
        if last_run and (now - last_run).total_seconds() < self.FLUSH_DEBOUNCE_SECONDS:
            logger.debug("Skipping auto flush (debounce): %s", flush_key)
            return

        self._flush_last_run[flush_key] = now

        try:
            history = [
                {"role": msg.role, "content": msg.content}
                for msg in conversation
                if hasattr(msg, "role") and hasattr(msg, "content")
            ]
            # fire-and-forget: フラッシュをバックグラウンドタスクとして起動
            asyncio.create_task(
                self._run_flush_background(history, user_id, room_id),
                name=f"memory_flush:{user_id}:{room_id}",
            )
        except Exception as e:
            logger.warning(f"Auto memory flush scheduling failed: {type(e).__name__}")

    async def _run_flush_background(
        self,
        history: List[Dict[str, str]],
        user_id: str,
        room_id: str,
    ) -> None:
        """バックグラウンドでフラッシュを実行（non-blocking）"""
        try:
            flush_result = await self.memory_flusher.flush(history, user_id, room_id)
            if flush_result.flushed_count > 0:
                logger.info(
                    f"Auto memory flush: {flush_result.flushed_count} items saved "
                    f"for user={user_id} room={room_id}"
                )
        except Exception as e:
            logger.warning(f"Auto memory flush failed (background): {type(e).__name__}")

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
            def _sync_firestore():
                doc_ref = self.firestore_db.collection("conversations").document(
                    f"{room_id}_{user_id}"
                )
                doc = doc_ref.get()
                if not doc.exists:
                    return None
                return doc.to_dict()

            data = await asyncio.to_thread(_sync_firestore)
            if data is None:
                return []

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
            logger.warning(f"Error fetching conversation history: {type(e).__name__}")
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
        # conversation_summaries.organization_id は UUID型
        # org_idがUUID形式でない場合はスキップ
        if not self._org_id_is_uuid:
            logger.debug(f"Skipping conversation_summaries query: org_id={self.org_id} is not UUID format")
            return None

        try:
            def _sync_query():
                import time as _t
                # Pool状態診断
                try:
                    pool_obj = self.pool.pool
                    print(f"[DIAG] summary: pool status: {pool_obj.status()}")
                except Exception:
                    print("[DIAG] summary: pool status unavailable")
                print("[DIAG] summary: pool.connect() START")
                t0 = _t.monotonic()
                with self.pool.connect() as conn:
                    t1 = _t.monotonic()
                    print(f"[DIAG] summary: pool.connect() DONE in {t1 - t0:.3f}s")
                    # DB側タイムアウト防止（5秒）
                    conn.execute(text(
                        "SELECT set_config('statement_timeout', '5000', true)"
                    ))
                    print("[DIAG] summary: statement_timeout SET, executing query")
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
                              AND cs.organization_id = CAST(:org_id AS uuid)
                            ORDER BY cs.created_at DESC
                            LIMIT 1
                        """),
                        {"user_id": user_id, "org_id": self.org_id},
                    )
                    t2 = _t.monotonic()
                    print(f"[DIAG] summary: query DONE in {t2 - t1:.3f}s")
                    return result.fetchone()

            row = await asyncio.to_thread(_sync_query)

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
            logger.warning(f"Error fetching conversation summary: {type(e).__name__}")
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
        # user_preferences.organization_id は UUID型
        # org_idがUUID形式でない場合はスキップ
        if not self._org_id_is_uuid:
            logger.debug(f"Skipping user_preferences query: org_id={self.org_id} is not UUID format")
            return []

        try:
            def _sync_query():
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
                              AND up.organization_id = CAST(:org_id AS uuid)
                            ORDER BY up.confidence DESC
                            LIMIT 20
                        """),
                        {"user_id": user_id, "org_id": self.org_id},
                    )
                    return result.fetchall()

            rows = await asyncio.to_thread(_sync_query)

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
            logger.warning(f"Error fetching user preferences: {type(e).__name__}")
            return []

    # =========================================================================
    # 人物情報（persons + person_attributes）
    # =========================================================================

    async def get_person_info(
        self,
        limit: int = 50,
        person_id: Optional[str] = None,
    ) -> List[PersonInfo]:
        """
        登録されている人物情報を取得

        Args:
            limit: 最大取得件数
            person_id: 指定時はこのIDの人物のみ取得

        Returns:
            List[PersonInfo]: 人物情報のリスト
        """
        try:
            def _sync_query():
                # v10.74.0: N+1クエリをJOINに統合（11回→1回）
                from collections import OrderedDict
                with self.pool.connect() as conn:
                    params: Dict[str, Any] = {"org_id": self.org_id, "limit": limit}
                    where_clause = "WHERE p.organization_id = :org_id"
                    if person_id:
                        try:
                            int(person_id)
                            where_clause += " AND p.id = CAST(:person_id AS integer)"
                            params["person_id"] = person_id
                        except (ValueError, TypeError):
                            pass  # persons.id is integer; skip non-integer person_id
                    result = conn.execute(
                        text(f"""
                            SELECT p.id, p.name,
                                   pa.attribute_type, pa.attribute_value
                            FROM persons p
                            LEFT JOIN person_attributes pa
                              ON pa.person_id = p.id
                              AND pa.organization_id = p.organization_id
                            {where_clause}
                            ORDER BY p.name, pa.updated_at DESC
                        """),
                        params,
                    )
                    rows = result.fetchall()

                    # 人物ごとにグルーピング
                    person_map: OrderedDict = OrderedDict()
                    for row in rows:
                        pid = row[0]
                        if pid not in person_map:
                            if len(person_map) >= limit:
                                break
                            person_map[pid] = {"name": row[1], "attributes": {}}
                        if row[2]:  # attribute_type がNULLでない場合
                            person_map[pid]["attributes"][row[2]] = row[3]

                    return [
                        PersonInfo(
                            person_id=str(pid) if pid else "",
                            name=info["name"],
                            attributes=info["attributes"],
                        )
                        for pid, info in person_map.items()
                    ]

            return await asyncio.to_thread(_sync_query)

        except Exception as e:
            logger.warning(f"Error fetching person info: {type(e).__name__}: {e}")
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
            import time as time_mod
            now_timestamp = int(time_mod.time())

            def _sync_query():
                with self.pool.connect() as conn:
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
                              AND organization_id = :org_id
                            ORDER BY
                                CASE WHEN limit_time IS NOT NULL AND to_timestamp(limit_time) < NOW()
                                     THEN 0 ELSE 1 END,
                                limit_time ASC NULLS LAST
                            LIMIT :limit
                        """),
                        {"user_id": user_id, "limit": limit, "org_id": self.org_id},
                    )
                    return result.fetchall()

            rows = await asyncio.to_thread(_sync_query)

            def _parse_limit_time(lt):
                if lt is None:
                    return None
                if isinstance(lt, datetime):
                    return lt
                if isinstance(lt, (int, float)):
                    return datetime.fromtimestamp(lt)
                return None

            def _is_overdue(lt):
                if lt is None:
                    return False
                if isinstance(lt, datetime):
                    return lt < datetime.now()
                if isinstance(lt, (int, float)):
                    return lt < now_timestamp
                return False

            return [
                TaskInfo(
                    task_id=str(row[0]) if row[0] else "",
                    body=row[1] or "",
                    summary=row[2],
                    status=row[3] or "open",
                    due_date=_parse_limit_time(row[4]),
                    room_id=str(row[5]) if row[5] else None,
                    room_name=row[6],
                    assignee_name=row[7],
                    assigned_by_name=row[8],
                    is_overdue=_is_overdue(row[4]),
                )
                for row in rows
            ]

        except Exception as e:
            logger.warning(f"Error fetching recent tasks: {type(e).__name__}")
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
            def _sync_query():
                with self.pool.connect() as conn:
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
                              AND g.organization_id = CAST(:org_id AS uuid)
                              AND g.status = 'active'
                            ORDER BY g.created_at DESC
                            LIMIT 5
                        """),
                        {"user_id": user_id, "org_id": self.org_id},
                    )
                    return result.fetchall()

            rows = await asyncio.to_thread(_sync_query)

            return [
                GoalInfo(
                    goal_id=str(row[0]) if row[0] else "",
                    title=row[1] or "",
                    why=None,
                    what=row[2],
                    how=None,
                    status=row[5] or "active",
                    progress=float(row[4] / row[3] * 100) if row[3] and row[4] else 0.0,
                    deadline=row[6],
                )
                for row in rows
            ]

        except Exception as e:
            logger.warning(f"Error fetching active goals: {type(e).__name__}")
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

        v10.57.1: HybridSearcherが設定されている場合はハイブリッド検索を使用。
        未設定の場合はILIKEフォールバック（後方互換性維持）。

        Args:
            query: 検索クエリ（ユーザーのメッセージ）
            limit: 最大取得件数

        Returns:
            List[KnowledgeInfo]: 会社知識のリスト
        """
        if not query:
            return []

        # ハイブリッド検索が利用可能な場合
        if self.hybrid_searcher:
            return await self._hybrid_knowledge_search(query, limit)

        # フォールバック: ILIKEベースの検索
        return await self._ilike_knowledge_search(query, limit)

    async def _hybrid_knowledge_search(
        self,
        query: str,
        limit: int = 5,
    ) -> List[KnowledgeInfo]:
        """ハイブリッド検索を使った知識検索"""
        try:
            response = await self.hybrid_searcher.search(query, top_k=limit)

            return [
                KnowledgeInfo(
                    keyword=r.title,
                    answer=r.content,
                    category=r.category,
                    relevance_score=r.hybrid_score,
                )
                for r in response.results
            ]

        except Exception as e:
            logger.warning("Hybrid search failed, falling back to ILIKE: %s", type(e).__name__)
            return await self._ilike_knowledge_search(query, limit)

    async def _ilike_knowledge_search(
        self,
        query: str,
        limit: int = 5,
    ) -> List[KnowledgeInfo]:
        """ILIKEベースの知識検索（フォールバック）"""
        from lib.brain.hybrid_search import escape_ilike
        escaped_query = escape_ilike(query)

        try:
            def _sync_query():
                with self.pool.connect() as conn:
                    result = conn.execute(
                        text("""
                            SELECT
                                id,
                                key,
                                value,
                                category
                            FROM soulkun_knowledge
                            WHERE organization_id = :org_id
                            AND (
                                key ILIKE '%' || CAST(:query AS TEXT) || '%' ESCAPE '\\'
                                OR value ILIKE '%' || CAST(:query AS TEXT) || '%' ESCAPE '\\'
                            )
                            ORDER BY id DESC
                            LIMIT :limit
                        """),
                        {"org_id": self.org_id, "query": escaped_query, "limit": limit},
                    )
                    return result.fetchall()

            rows = await asyncio.to_thread(_sync_query)

            return [
                KnowledgeInfo(
                    id=row[0],
                    keyword=row[1] or "",
                    answer=row[2] or "",
                    category=row[3],
                    relevance_score=1.0,
                )
                for row in rows
            ]

        except Exception as e:
            logger.warning("Error fetching relevant knowledge: %s", type(e).__name__)
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
            def _sync_query():
                with self.pool.connect() as conn:
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
                            WHERE organization_id = CAST(:org_id AS uuid)
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
                    return result.fetchall()

            rows = await asyncio.to_thread(_sync_query)

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
            logger.warning(f"Error fetching recent insights: {type(e).__name__}")
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
            from lib.brain.hybrid_search import escape_ilike
            search_params = {
                "org_id": self.org_id,
                "query": f"%{escape_ilike(query)}%",
                "limit": limit,
            }

            user_clause = ""
            if user_id:
                user_clause = "AND ci.user_id = (SELECT id FROM users WHERE chatwork_account_id = :user_id)"
                search_params["user_id"] = user_id

            def _sync_query():
                with self.pool.connect() as conn:
                    result = conn.execute(
                        text(f"""
                            SELECT
                                ci.message_type,
                                ci.message_text,
                                ci.message_time
                            FROM conversation_index ci
                            WHERE ci.organization_id = CAST(:org_id AS uuid)
                              AND ci.message_text ILIKE :query ESCAPE '\\'
                              {user_clause}
                            ORDER BY ci.message_time DESC
                            LIMIT :limit
                        """),
                        search_params,
                    )
                    return result.fetchall()

            rows = await asyncio.to_thread(_sync_query)

            return [
                ConversationMessage(
                    role=row[0] or "user",
                    content=row[1] or "",
                    timestamp=row[2],
                )
                for row in rows
            ]

        except Exception as e:
            logger.warning(f"Error searching conversation: {type(e).__name__}")
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
