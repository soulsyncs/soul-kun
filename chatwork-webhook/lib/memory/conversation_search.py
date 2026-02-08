"""
Phase 2 B4: 会話検索

過去の会話を検索・参照する機能。
ユーザーが「前に話した〇〇について」と言ったときに、
関連する過去の会話を取得する。

Author: Claude Code
Created: 2026-01-24
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from uuid import UUID
from datetime import datetime, timedelta
import logging
import json

from sqlalchemy import text

from .base import BaseMemory, MemoryResult
from .constants import (
    MemoryParameters,
    MessageType,
    KEYWORD_EXTRACTION_PROMPT,
)
from .exceptions import (
    SearchError,
    IndexError,
    DatabaseError,
    wrap_memory_error,
)
from lib.brain.hybrid_search import escape_ilike


logger = logging.getLogger(__name__)


# ================================================================
# データクラス
# ================================================================

@dataclass
class SearchResult:
    """会話検索結果のデータクラス"""

    id: Optional[UUID] = None
    organization_id: Optional[UUID] = None
    user_id: Optional[UUID] = None
    message_id: Optional[str] = None
    room_id: Optional[str] = None
    message_text: str = ""
    message_type: str = MessageType.USER.value
    keywords: List[str] = field(default_factory=list)
    entities: Dict[str, Any] = field(default_factory=dict)
    message_time: Optional[datetime] = None
    classification: str = "internal"
    context: List[Dict[str, Any]] = field(default_factory=list)  # 前後の会話

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式で返す"""
        return {
            "id": str(self.id) if self.id else None,
            "organization_id": str(self.organization_id) if self.organization_id else None,
            "user_id": str(self.user_id) if self.user_id else None,
            "message_id": self.message_id,
            "room_id": self.room_id,
            "message_text": self.message_text,
            "message_type": self.message_type,
            "keywords": self.keywords,
            "entities": self.entities,
            "message_time": self.message_time.isoformat() if self.message_time else None,
            "classification": self.classification,
            "context": self.context,
        }


# ================================================================
# 会話検索クラス
# ================================================================

class ConversationSearch(BaseMemory):
    """
    B4: 会話検索

    過去の会話をインデックス化し、検索可能にする。
    """

    def __init__(
        self,
        conn,
        org_id: UUID,
        openrouter_api_key: Optional[str] = None,
        model: str = "google/gemini-3-flash-preview"
    ):
        """
        初期化

        Args:
            conn: データベース接続
            org_id: 組織ID
            openrouter_api_key: OpenRouter APIキー
            model: 使用するLLMモデル
        """
        super().__init__(
            conn=conn,
            org_id=org_id,
            memory_type="b4_conversation_search",
            openrouter_api_key=openrouter_api_key,
            model=model
        )

    # ================================================================
    # 公開メソッド
    # ================================================================

    @wrap_memory_error
    async def save(
        self,
        user_id: UUID,
        message_text: str,
        message_type: str,
        message_time: datetime,
        message_id: Optional[str] = None,
        room_id: Optional[str] = None,
        keywords: Optional[List[str]] = None,
        entities: Optional[Dict[str, Any]] = None,
        classification: str = "internal"
    ) -> MemoryResult:
        """
        会話をインデックスに保存

        Args:
            user_id: ユーザーID
            message_text: メッセージ本文
            message_type: メッセージタイプ（user/assistant）
            message_time: メッセージ時刻
            message_id: ChatWorkメッセージID
            room_id: ChatWorkルームID
            keywords: キーワード
            entities: エンティティ
            classification: 機密区分

        Returns:
            MemoryResult: 保存結果
        """
        user_id = self.validate_uuid(user_id, "user_id")

        # メッセージタイプの検証
        valid_types = [t.value for t in MessageType]
        if message_type not in valid_types:
            message_type = MessageType.USER.value

        # キーワードが指定されていない場合は抽出
        if not keywords:
            extracted = await self._extract_keywords(message_text)
            keywords = extracted.get("keywords", [])
            entities = extracted.get("entities", {})

        try:
            result = self.conn.execute(text("""
                INSERT INTO conversation_index (
                    organization_id, user_id, message_id, room_id,
                    message_text, message_type, keywords, entities,
                    embedding_id, message_time, classification
                ) VALUES (
                    :org_id, :user_id, :message_id, :room_id,
                    :message_text, :message_type, :keywords, CAST(:entities AS jsonb),
                    :embedding_id, :message_time, :classification
                )
                RETURNING id
            """), {
                "org_id": str(self.org_id),
                "user_id": str(user_id),
                "message_id": message_id,
                "room_id": room_id,
                "message_text": message_text,
                "message_type": message_type,
                "keywords": keywords or [],
                "entities": json.dumps(entities or {}, ensure_ascii=False),
                "embedding_id": None,  # 将来のベクトル検索用
                "message_time": message_time,
                "classification": classification,
            })

            row = result.fetchone()
            self.conn.commit()

            index_id = row[0]
            self._log_operation("save_conversation_index", user_id, {
                "index_id": str(index_id),
            })

            return MemoryResult(
                success=True,
                memory_id=index_id,
                message="Conversation indexed successfully",
                data={"keywords": keywords}
            )

        except Exception as e:
            logger.error(f"Failed to save conversation index: {e}")
            raise IndexError(
                message=f"Failed to save conversation index: {str(e)}",
                message_id=message_id
            )

    @wrap_memory_error
    async def retrieve(
        self,
        user_id: Optional[UUID] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        room_id: Optional[str] = None,
        limit: int = MemoryParameters.SEARCH_DEFAULT_LIMIT,
        offset: int = 0
    ) -> List[SearchResult]:
        """
        会話を取得

        Args:
            user_id: ユーザーID
            from_date: 開始日時
            to_date: 終了日時
            room_id: ChatWorkルームID
            limit: 取得件数
            offset: オフセット

        Returns:
            List[SearchResult]: 会話のリスト
        """
        conditions = ["organization_id = :org_id"]
        params = {"org_id": str(self.org_id)}

        if user_id:
            user_id = self.validate_uuid(user_id, "user_id")
            conditions.append("user_id = :user_id")
            params["user_id"] = str(user_id)

        if from_date:
            conditions.append("message_time >= :from_date")
            params["from_date"] = from_date

        if to_date:
            conditions.append("message_time <= :to_date")
            params["to_date"] = to_date

        if room_id:
            conditions.append("room_id = :room_id")
            params["room_id"] = room_id

        where_clause = " AND ".join(conditions)
        params["limit"] = min(limit, MemoryParameters.SEARCH_MAX_LIMIT)
        params["offset"] = offset

        try:
            result = self.conn.execute(text(f"""
                SELECT
                    id, organization_id, user_id, message_id, room_id,
                    message_text, message_type, keywords, entities,
                    message_time, classification
                FROM conversation_index
                WHERE {where_clause}
                ORDER BY message_time DESC
                LIMIT :limit OFFSET :offset
            """), params)

            conversations = []
            for row in result.fetchall():
                entities = row[8]
                if isinstance(entities, str):
                    try:
                        entities = json.loads(entities)
                    except json.JSONDecodeError:
                        entities = {}

                conversations.append(SearchResult(
                    id=row[0],
                    organization_id=row[1],
                    user_id=row[2],
                    message_id=row[3],
                    room_id=row[4],
                    message_text=row[5],
                    message_type=row[6],
                    keywords=row[7] or [],
                    entities=entities,
                    message_time=row[9],
                    classification=row[10],
                ))

            return conversations

        except Exception as e:
            logger.error(f"Failed to retrieve conversations: {e}")
            raise DatabaseError(
                message=f"Failed to retrieve conversations: {str(e)}",
                original_error=e
            )

    @wrap_memory_error
    async def search(
        self,
        query: str,
        user_id: Optional[UUID] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        limit: int = MemoryParameters.SEARCH_DEFAULT_LIMIT,
        include_context: bool = True
    ) -> List[SearchResult]:
        """
        会話を検索

        Args:
            query: 検索クエリ
            user_id: ユーザーID
            from_date: 開始日時
            to_date: 終了日時
            limit: 取得件数
            include_context: 前後の会話を含めるか

        Returns:
            List[SearchResult]: 検索結果
        """
        conditions = ["organization_id = :org_id"]
        params = {
            "org_id": str(self.org_id),
            "query": f"%{escape_ilike(query)}%",
            "query_word": query,
        }

        if user_id:
            user_id = self.validate_uuid(user_id, "user_id")
            conditions.append("user_id = :user_id")
            params["user_id"] = str(user_id)

        if from_date:
            conditions.append("message_time >= :from_date")
            params["from_date"] = from_date

        if to_date:
            conditions.append("message_time <= :to_date")
            params["to_date"] = to_date

        where_clause = " AND ".join(conditions)
        params["limit"] = min(limit, MemoryParameters.SEARCH_MAX_LIMIT)

        try:
            # キーワード検索とテキスト検索
            result = self.conn.execute(text(f"""
                SELECT
                    id, organization_id, user_id, message_id, room_id,
                    message_text, message_type, keywords, entities,
                    message_time, classification
                FROM conversation_index
                WHERE {where_clause}
                  AND (
                      message_text ILIKE :query ESCAPE '\\'
                      OR :query_word = ANY(keywords)
                  )
                ORDER BY message_time DESC
                LIMIT :limit
            """), params)

            conversations = []
            for row in result.fetchall():
                entities = row[8]
                if isinstance(entities, str):
                    try:
                        entities = json.loads(entities)
                    except json.JSONDecodeError:
                        entities = {}

                search_result = SearchResult(
                    id=row[0],
                    organization_id=row[1],
                    user_id=row[2],
                    message_id=row[3],
                    room_id=row[4],
                    message_text=row[5],
                    message_type=row[6],
                    keywords=row[7] or [],
                    entities=entities,
                    message_time=row[9],
                    classification=row[10],
                )

                # 前後の会話を取得
                if include_context and search_result.id:
                    search_result.context = await self._get_context(
                        search_result.id,
                        search_result.user_id,
                        search_result.message_time
                    )

                conversations.append(search_result)

            self._log_operation("search_conversation", details={
                "query": query[:50],
                "result_count": len(conversations),
            })

            return conversations

        except Exception as e:
            logger.error(f"Failed to search conversations: {e}")
            raise SearchError(
                message=f"Failed to search conversations: {str(e)}",
                query=query
            )

    @wrap_memory_error
    async def search_by_topic(
        self,
        topic: str,
        user_id: Optional[UUID] = None,
        days: int = 30,
        limit: int = 10
    ) -> List[SearchResult]:
        """
        トピックで会話を検索

        Args:
            topic: トピック（例: "週報", "有給", "タスク"）
            user_id: ユーザーID
            days: 対象期間（日）
            limit: 取得件数

        Returns:
            List[SearchResult]: 検索結果
        """
        from_date = datetime.utcnow() - timedelta(days=days)

        return await self.search(
            query=topic,
            user_id=user_id,
            from_date=from_date,
            limit=limit,
            include_context=True
        )

    @wrap_memory_error
    async def get_recent_conversations(
        self,
        user_id: UUID,
        count: int = 10
    ) -> List[SearchResult]:
        """
        直近の会話を取得

        Args:
            user_id: ユーザーID
            count: 取得件数

        Returns:
            List[SearchResult]: 直近の会話
        """
        return await self.retrieve(
            user_id=user_id,
            limit=count
        )

    @wrap_memory_error
    async def batch_index(
        self,
        user_id: UUID,
        messages: List[Dict[str, Any]]
    ) -> int:
        """
        複数のメッセージを一括インデックス

        Args:
            user_id: ユーザーID
            messages: メッセージのリスト

        Returns:
            int: インデックスした件数
        """
        indexed_count = 0

        for msg in messages:
            try:
                message_time = msg.get("timestamp") or msg.get("created_at")
                if isinstance(message_time, str):
                    message_time = datetime.fromisoformat(message_time.replace("Z", "+00:00"))
                elif not message_time:
                    message_time = datetime.utcnow()

                await self.save(
                    user_id=user_id,
                    message_text=msg.get("content", msg.get("message", "")),
                    message_type=msg.get("role", MessageType.USER.value),
                    message_time=message_time,
                    message_id=msg.get("message_id"),
                    room_id=msg.get("room_id"),
                )
                indexed_count += 1

            except Exception as e:
                logger.warning(f"Failed to index message: {e}")
                continue

        return indexed_count

    @wrap_memory_error
    async def cleanup_old_index(
        self,
        retention_days: Optional[int] = None
    ) -> int:
        """
        古いインデックスを削除

        Args:
            retention_days: 保持期間（日）

        Returns:
            int: 削除件数
        """
        retention_days = retention_days or MemoryParameters.SEARCH_INDEX_RETENTION_DAYS
        cutoff_date = datetime.utcnow() - timedelta(days=retention_days)

        try:
            result = self.conn.execute(text("""
                DELETE FROM conversation_index
                WHERE organization_id = :org_id
                  AND created_at < :cutoff_date
            """), {
                "org_id": str(self.org_id),
                "cutoff_date": cutoff_date
            })

            deleted_count = result.rowcount
            self.conn.commit()

            logger.info(f"Cleaned up {deleted_count} old conversation indexes")
            return deleted_count

        except Exception as e:
            logger.error(f"Failed to cleanup old indexes: {e}")
            raise DatabaseError(
                message=f"Failed to cleanup old indexes: {str(e)}",
                original_error=e
            )

    # ================================================================
    # 内部メソッド
    # ================================================================

    async def _extract_keywords(
        self,
        message_text: str
    ) -> Dict[str, Any]:
        """
        メッセージからキーワードを抽出

        Args:
            message_text: メッセージ本文

        Returns:
            Dict: キーワードとエンティティ
        """
        if not self.openrouter_api_key:
            # LLMが使えない場合はシンプルな抽出
            return self._simple_keyword_extraction(message_text)

        prompt = KEYWORD_EXTRACTION_PROMPT.format(message=message_text)

        try:
            response = await self.call_llm(prompt, max_tokens=500)
            return self.extract_json_from_response(response)

        except Exception as e:
            logger.warning(f"Failed to extract keywords with LLM: {e}")
            return self._simple_keyword_extraction(message_text)

    def _simple_keyword_extraction(
        self,
        message_text: str
    ) -> Dict[str, Any]:
        """
        シンプルなキーワード抽出（LLMなし）

        Args:
            message_text: メッセージ本文

        Returns:
            Dict: キーワードとエンティティ
        """
        import re

        keywords = []

        # 日本語の名詞っぽい単語を抽出（簡易）
        # カタカナ語
        katakana = re.findall(r'[ァ-ヶー]+', message_text)
        keywords.extend([k for k in katakana if len(k) >= 2])

        # 漢字を含む単語（2-6文字）
        kanji = re.findall(r'[\u4e00-\u9fff]{2,6}', message_text)
        keywords.extend(kanji)

        # 業務用語
        business_terms = [
            "タスク", "週報", "有給", "会議", "報告", "確認",
            "承認", "依頼", "完了", "期限", "進捗", "資料",
        ]
        for term in business_terms:
            if term in message_text:
                keywords.append(term)

        # 重複を除去して返す
        keywords = list(set(keywords))[:MemoryParameters.KNOWLEDGE_MAX_KEYWORDS]

        return {
            "keywords": keywords,
            "entities": {}
        }

    async def _get_context(
        self,
        index_id: UUID,
        user_id: UUID,
        message_time: datetime,
        window: int = MemoryParameters.SEARCH_CONTEXT_WINDOW
    ) -> List[Dict[str, Any]]:
        """
        メッセージの前後の会話を取得

        Args:
            index_id: インデックスID
            user_id: ユーザーID
            message_time: メッセージ時刻
            window: 前後の件数

        Returns:
            List[Dict]: 前後の会話
        """
        try:
            # 前後の会話を取得
            result = self.conn.execute(text("""
                (
                    SELECT
                        id, message_text, message_type, message_time,
                        'before' as position
                    FROM conversation_index
                    WHERE organization_id = :org_id
                      AND user_id = :user_id
                      AND message_time < :message_time
                      AND id != :index_id
                    ORDER BY message_time DESC
                    LIMIT :window
                )
                UNION ALL
                (
                    SELECT
                        id, message_text, message_type, message_time,
                        'after' as position
                    FROM conversation_index
                    WHERE organization_id = :org_id
                      AND user_id = :user_id
                      AND message_time > :message_time
                      AND id != :index_id
                    ORDER BY message_time ASC
                    LIMIT :window
                )
                ORDER BY message_time ASC
            """), {
                "org_id": str(self.org_id),
                "user_id": str(user_id),
                "message_time": message_time,
                "index_id": str(index_id),
                "window": window,
            })

            context = []
            for row in result.fetchall():
                context.append({
                    "id": str(row[0]),
                    "message_text": row[1],
                    "message_type": row[2],
                    "message_time": row[3].isoformat() if row[3] else None,
                    "position": row[4],
                })

            return context

        except Exception as e:
            logger.warning(f"Failed to get context: {e}")
            return []
