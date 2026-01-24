"""
Phase 2 B1: 会話サマリー記憶

会話が一定量たまったら自動的にサマリー化し、
長期記憶として保存。新しい会話時にサマリーを参照して文脈を維持。

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

from lib.memory.base import BaseMemory, MemoryResult
from lib.memory.constants import (
    MemoryParameters,
    CONVERSATION_SUMMARY_PROMPT,
    GeneratedBy,
)
from lib.memory.exceptions import (
    SummarySaveError,
    SummaryGenerationError,
    DatabaseError,
    wrap_memory_error,
)


logger = logging.getLogger(__name__)


# ================================================================
# データクラス
# ================================================================

@dataclass
class SummaryData:
    """会話サマリーのデータクラス"""

    id: Optional[UUID] = None
    organization_id: Optional[UUID] = None
    user_id: Optional[UUID] = None
    summary_text: str = ""
    key_topics: List[str] = field(default_factory=list)
    mentioned_persons: List[str] = field(default_factory=list)
    mentioned_tasks: List[str] = field(default_factory=list)
    conversation_start: Optional[datetime] = None
    conversation_end: Optional[datetime] = None
    message_count: int = 0
    room_id: Optional[str] = None
    generated_by: str = GeneratedBy.LLM.value
    classification: str = "internal"
    created_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式で返す"""
        return {
            "id": str(self.id) if self.id else None,
            "organization_id": str(self.organization_id) if self.organization_id else None,
            "user_id": str(self.user_id) if self.user_id else None,
            "summary_text": self.summary_text,
            "key_topics": self.key_topics,
            "mentioned_persons": self.mentioned_persons,
            "mentioned_tasks": self.mentioned_tasks,
            "conversation_start": self.conversation_start.isoformat() if self.conversation_start else None,
            "conversation_end": self.conversation_end.isoformat() if self.conversation_end else None,
            "message_count": self.message_count,
            "room_id": self.room_id,
            "generated_by": self.generated_by,
            "classification": self.classification,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ================================================================
# 会話サマリー記憶クラス
# ================================================================

class ConversationSummary(BaseMemory):
    """
    B1: 会話サマリー記憶

    会話履歴を分析してサマリーを生成し、長期記憶として保存する。
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
            memory_type="b1_summary",
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
        summary_text: str,
        key_topics: List[str],
        mentioned_persons: List[str],
        mentioned_tasks: List[str],
        conversation_start: datetime,
        conversation_end: datetime,
        message_count: int,
        room_id: Optional[str] = None,
        generated_by: str = GeneratedBy.LLM.value,
        classification: str = "internal"
    ) -> MemoryResult:
        """
        サマリーを保存

        Args:
            user_id: ユーザーID
            summary_text: サマリーテキスト
            key_topics: 主要トピック
            mentioned_persons: 言及された人物
            mentioned_tasks: 言及されたタスク
            conversation_start: 会話開始時刻
            conversation_end: 会話終了時刻
            message_count: メッセージ数
            room_id: ChatWorkルームID
            generated_by: 生成方法
            classification: 機密区分

        Returns:
            MemoryResult: 保存結果
        """
        user_id = self.validate_uuid(user_id, "user_id")

        # テキスト長の制限
        summary_text = self.truncate_text(
            summary_text,
            MemoryParameters.SUMMARY_MAX_LENGTH
        )
        key_topics = key_topics[:MemoryParameters.SUMMARY_MAX_TOPICS]
        mentioned_persons = mentioned_persons[:MemoryParameters.SUMMARY_MAX_PERSONS]
        mentioned_tasks = mentioned_tasks[:MemoryParameters.SUMMARY_MAX_TASKS]

        try:
            result = self.conn.execute(text("""
                INSERT INTO conversation_summaries (
                    organization_id, user_id, summary_text,
                    key_topics, mentioned_persons, mentioned_tasks,
                    conversation_start, conversation_end, message_count,
                    room_id, generated_by, classification
                ) VALUES (
                    :org_id, :user_id, :summary_text,
                    :key_topics, :mentioned_persons, :mentioned_tasks,
                    :conversation_start, :conversation_end, :message_count,
                    :room_id, :generated_by, :classification
                )
                RETURNING id
            """), {
                "org_id": str(self.org_id),
                "user_id": str(user_id),
                "summary_text": summary_text,
                "key_topics": key_topics,
                "mentioned_persons": mentioned_persons,
                "mentioned_tasks": mentioned_tasks,
                "conversation_start": conversation_start,
                "conversation_end": conversation_end,
                "message_count": message_count,
                "room_id": room_id,
                "generated_by": generated_by,
                "classification": classification,
            })

            row = result.fetchone()
            self.conn.commit()

            summary_id = row[0]
            self._log_operation("save_summary", user_id, {"summary_id": str(summary_id)})

            return MemoryResult(
                success=True,
                memory_id=summary_id,
                message="Summary saved successfully",
                data={"message_count": message_count}
            )

        except Exception as e:
            logger.error(f"Failed to save summary: {e}")
            raise SummarySaveError(
                message=f"Failed to save summary: {str(e)}",
                user_id=str(user_id)
            )

    @wrap_memory_error
    async def retrieve(
        self,
        user_id: Optional[UUID] = None,
        limit: int = 10,
        offset: int = 0,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None
    ) -> List[SummaryData]:
        """
        サマリーを取得

        Args:
            user_id: ユーザーID（指定しない場合は全ユーザー）
            limit: 取得件数
            offset: オフセット
            from_date: 開始日時
            to_date: 終了日時

        Returns:
            List[SummaryData]: サマリーのリスト
        """
        conditions = ["organization_id = :org_id"]
        params = {"org_id": str(self.org_id)}

        if user_id:
            user_id = self.validate_uuid(user_id, "user_id")
            conditions.append("user_id = :user_id")
            params["user_id"] = str(user_id)

        if from_date:
            conditions.append("conversation_end >= :from_date")
            params["from_date"] = from_date

        if to_date:
            conditions.append("conversation_start <= :to_date")
            params["to_date"] = to_date

        where_clause = " AND ".join(conditions)
        params["limit"] = min(limit, 100)
        params["offset"] = offset

        try:
            result = self.conn.execute(text(f"""
                SELECT
                    id, organization_id, user_id, summary_text,
                    key_topics, mentioned_persons, mentioned_tasks,
                    conversation_start, conversation_end, message_count,
                    room_id, generated_by, classification, created_at
                FROM conversation_summaries
                WHERE {where_clause}
                ORDER BY conversation_end DESC
                LIMIT :limit OFFSET :offset
            """), params)

            summaries = []
            for row in result.fetchall():
                summaries.append(SummaryData(
                    id=row[0],
                    organization_id=row[1],
                    user_id=row[2],
                    summary_text=row[3],
                    key_topics=row[4] or [],
                    mentioned_persons=row[5] or [],
                    mentioned_tasks=row[6] or [],
                    conversation_start=row[7],
                    conversation_end=row[8],
                    message_count=row[9],
                    room_id=row[10],
                    generated_by=row[11],
                    classification=row[12],
                    created_at=row[13],
                ))

            return summaries

        except Exception as e:
            logger.error(f"Failed to retrieve summaries: {e}")
            raise DatabaseError(
                message=f"Failed to retrieve summaries: {str(e)}",
                original_error=e
            )

    @wrap_memory_error
    async def generate_and_save(
        self,
        user_id: UUID,
        conversation_history: List[Dict[str, Any]],
        room_id: Optional[str] = None
    ) -> MemoryResult:
        """
        会話履歴からサマリーを生成して保存

        Args:
            user_id: ユーザーID
            conversation_history: 会話履歴
            room_id: ChatWorkルームID

        Returns:
            MemoryResult: 保存結果
        """
        user_id = self.validate_uuid(user_id, "user_id")

        if len(conversation_history) < MemoryParameters.SUMMARY_TRIGGER_COUNT:
            return MemoryResult(
                success=False,
                message=f"Not enough messages for summary (need {MemoryParameters.SUMMARY_TRIGGER_COUNT}, got {len(conversation_history)})"
            )

        # 会話履歴をテキストに変換
        history_text = self._format_conversation_history(conversation_history)

        # LLMでサマリーを生成
        summary_data = await self._generate_summary(history_text)

        # タイムスタンプを取得
        timestamps = [
            msg.get("timestamp") or msg.get("created_at")
            for msg in conversation_history
            if msg.get("timestamp") or msg.get("created_at")
        ]

        if timestamps:
            conversation_start = min(timestamps)
            conversation_end = max(timestamps)
        else:
            conversation_end = datetime.utcnow()
            conversation_start = conversation_end - timedelta(hours=1)

        # 保存
        return await self.save(
            user_id=user_id,
            summary_text=summary_data.get("summary", ""),
            key_topics=summary_data.get("key_topics", []),
            mentioned_persons=summary_data.get("mentioned_persons", []),
            mentioned_tasks=summary_data.get("mentioned_tasks", []),
            conversation_start=conversation_start,
            conversation_end=conversation_end,
            message_count=len(conversation_history),
            room_id=room_id,
            generated_by=GeneratedBy.LLM.value
        )

    @wrap_memory_error
    async def get_recent_context(
        self,
        user_id: UUID,
        days: int = 7
    ) -> str:
        """
        直近のサマリーからコンテキストを取得

        Args:
            user_id: ユーザーID
            days: 対象期間（日）

        Returns:
            str: コンテキストテキスト
        """
        from_date = datetime.utcnow() - timedelta(days=days)

        summaries = await self.retrieve(
            user_id=user_id,
            from_date=from_date,
            limit=5
        )

        if not summaries:
            return ""

        context_parts = []
        for summary in summaries:
            context_parts.append(f"【{summary.conversation_end.strftime('%Y-%m-%d')}】")
            context_parts.append(summary.summary_text)
            if summary.key_topics:
                context_parts.append(f"トピック: {', '.join(summary.key_topics)}")
            context_parts.append("")

        return "\n".join(context_parts)

    # ================================================================
    # 内部メソッド
    # ================================================================

    def _format_conversation_history(
        self,
        conversation_history: List[Dict[str, Any]]
    ) -> str:
        """
        会話履歴をテキスト形式に変換

        Args:
            conversation_history: 会話履歴

        Returns:
            str: テキスト形式の会話履歴
        """
        lines = []
        for msg in conversation_history:
            role = msg.get("role", "user")
            content = msg.get("content", msg.get("message", ""))
            timestamp = msg.get("timestamp", "")

            if timestamp:
                lines.append(f"[{timestamp}] {role}: {content}")
            else:
                lines.append(f"{role}: {content}")

        return "\n".join(lines)

    async def _generate_summary(
        self,
        history_text: str
    ) -> Dict[str, Any]:
        """
        LLMを使ってサマリーを生成

        Args:
            history_text: 会話履歴テキスト

        Returns:
            Dict: サマリーデータ
        """
        prompt = CONVERSATION_SUMMARY_PROMPT.format(
            conversation_history=history_text
        )

        try:
            response = await self.call_llm(prompt)
            return self.extract_json_from_response(response)

        except Exception as e:
            logger.error(f"Failed to generate summary: {e}")
            # フォールバック: シンプルなサマリーを返す
            return {
                "summary": f"会話履歴（{len(history_text)}文字）のサマリー生成に失敗しました。",
                "key_topics": [],
                "mentioned_persons": [],
                "mentioned_tasks": [],
            }

    async def cleanup_old_summaries(
        self,
        retention_days: Optional[int] = None
    ) -> int:
        """
        古いサマリーを削除

        Args:
            retention_days: 保持期間（日）

        Returns:
            int: 削除件数
        """
        retention_days = retention_days or MemoryParameters.SUMMARY_RETENTION_DAYS
        cutoff_date = datetime.utcnow() - timedelta(days=retention_days)

        try:
            result = self.conn.execute(text("""
                DELETE FROM conversation_summaries
                WHERE organization_id = :org_id
                  AND created_at < :cutoff_date
            """), {
                "org_id": str(self.org_id),
                "cutoff_date": cutoff_date
            })

            deleted_count = result.rowcount
            self.conn.commit()

            logger.info(f"Cleaned up {deleted_count} old summaries")
            return deleted_count

        except Exception as e:
            logger.error(f"Failed to cleanup old summaries: {e}")
            raise DatabaseError(
                message=f"Failed to cleanup old summaries: {str(e)}",
                original_error=e
            )
