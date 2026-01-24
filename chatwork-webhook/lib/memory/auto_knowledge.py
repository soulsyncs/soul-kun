"""
Phase 2 B3: 組織知識自動蓄積

A1パターン検出で検出された頻出質問を自動的にナレッジ化。
管理者の承認後、Phase 3のナレッジ検索に統合。

Author: Claude Code
Created: 2026-01-24
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from uuid import UUID
from datetime import datetime
import logging
import json

from sqlalchemy import text

from lib.memory.base import BaseMemory, MemoryResult
from lib.memory.constants import (
    MemoryParameters,
    KnowledgeStatus,
    AUTO_KNOWLEDGE_GENERATION_PROMPT,
)
from lib.memory.exceptions import (
    KnowledgeSaveError,
    KnowledgeGenerationError,
    DatabaseError,
    wrap_memory_error,
)


logger = logging.getLogger(__name__)


# ================================================================
# データクラス
# ================================================================

@dataclass
class KnowledgeData:
    """組織知識のデータクラス"""

    id: Optional[UUID] = None
    organization_id: Optional[UUID] = None
    source_insight_id: Optional[UUID] = None
    source_pattern_id: Optional[UUID] = None
    question: str = ""
    answer: str = ""
    category: Optional[str] = None
    keywords: List[str] = field(default_factory=list)
    status: str = KnowledgeStatus.DRAFT.value
    approved_at: Optional[datetime] = None
    approved_by: Optional[UUID] = None
    rejection_reason: Optional[str] = None
    synced_to_phase3: bool = False
    phase3_document_id: Optional[UUID] = None
    usage_count: int = 0
    helpful_count: int = 0
    quality_score: Optional[float] = None
    classification: str = "internal"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式で返す"""
        return {
            "id": str(self.id) if self.id else None,
            "organization_id": str(self.organization_id) if self.organization_id else None,
            "source_insight_id": str(self.source_insight_id) if self.source_insight_id else None,
            "source_pattern_id": str(self.source_pattern_id) if self.source_pattern_id else None,
            "question": self.question,
            "answer": self.answer,
            "category": self.category,
            "keywords": self.keywords,
            "status": self.status,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "approved_by": str(self.approved_by) if self.approved_by else None,
            "rejection_reason": self.rejection_reason,
            "synced_to_phase3": self.synced_to_phase3,
            "phase3_document_id": str(self.phase3_document_id) if self.phase3_document_id else None,
            "usage_count": self.usage_count,
            "helpful_count": self.helpful_count,
            "quality_score": self.quality_score,
            "classification": self.classification,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ================================================================
# 組織知識自動蓄積クラス
# ================================================================

class AutoKnowledge(BaseMemory):
    """
    B3: 組織知識自動蓄積

    A1パターン検出と連携して、頻出質問から自動的に
    ナレッジを生成し、承認フローを経てPhase 3に統合する。
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
            memory_type="b3_auto_knowledge",
            openrouter_api_key=openrouter_api_key,
            model=model
        )

    # ================================================================
    # 公開メソッド
    # ================================================================

    @wrap_memory_error
    async def save(
        self,
        question: str,
        answer: str,
        category: Optional[str] = None,
        keywords: Optional[List[str]] = None,
        source_insight_id: Optional[UUID] = None,
        source_pattern_id: Optional[UUID] = None,
        classification: str = "internal"
    ) -> MemoryResult:
        """
        知識を保存

        Args:
            question: 質問
            answer: 回答
            category: カテゴリ
            keywords: キーワード
            source_insight_id: 元のインサイトID（A1連携）
            source_pattern_id: 元のパターンID（A1連携）
            classification: 機密区分

        Returns:
            MemoryResult: 保存結果
        """
        # テキスト長の制限
        answer = self.truncate_text(answer, MemoryParameters.KNOWLEDGE_ANSWER_MAX_LENGTH)
        keywords = (keywords or [])[:MemoryParameters.KNOWLEDGE_MAX_KEYWORDS]

        try:
            result = self.conn.execute(text("""
                INSERT INTO organization_auto_knowledge (
                    organization_id, source_insight_id, source_pattern_id,
                    question, answer, category, keywords,
                    status, classification
                ) VALUES (
                    :org_id, :source_insight_id, :source_pattern_id,
                    :question, :answer, :category, :keywords,
                    :status, :classification
                )
                RETURNING id
            """), {
                "org_id": str(self.org_id),
                "source_insight_id": str(source_insight_id) if source_insight_id else None,
                "source_pattern_id": str(source_pattern_id) if source_pattern_id else None,
                "question": question,
                "answer": answer,
                "category": category,
                "keywords": keywords,
                "status": KnowledgeStatus.DRAFT.value,
                "classification": classification,
            })

            row = result.fetchone()
            self.conn.commit()

            knowledge_id = row[0]
            self._log_operation("save_knowledge", details={
                "knowledge_id": str(knowledge_id),
                "source_insight_id": str(source_insight_id) if source_insight_id else None,
            })

            return MemoryResult(
                success=True,
                memory_id=knowledge_id,
                message="Knowledge saved successfully",
                data={"status": KnowledgeStatus.DRAFT.value}
            )

        except Exception as e:
            logger.error(f"Failed to save knowledge: {e}")
            raise KnowledgeSaveError(
                message=f"Failed to save knowledge: {str(e)}",
                source_id=str(source_insight_id) if source_insight_id else None
            )

    @wrap_memory_error
    async def retrieve(
        self,
        status: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[KnowledgeData]:
        """
        知識を取得

        Args:
            status: ステータスフィルタ
            category: カテゴリフィルタ
            limit: 取得件数
            offset: オフセット

        Returns:
            List[KnowledgeData]: 知識のリスト
        """
        conditions = ["organization_id = :org_id"]
        params = {"org_id": str(self.org_id)}

        if status:
            conditions.append("status = :status")
            params["status"] = status

        if category:
            conditions.append("category = :category")
            params["category"] = category

        where_clause = " AND ".join(conditions)
        params["limit"] = min(limit, 100)
        params["offset"] = offset

        try:
            result = self.conn.execute(text(f"""
                SELECT
                    id, organization_id, source_insight_id, source_pattern_id,
                    question, answer, category, keywords, status,
                    approved_at, approved_by, rejection_reason,
                    synced_to_phase3, phase3_document_id,
                    usage_count, helpful_count, quality_score,
                    classification, created_at, updated_at
                FROM organization_auto_knowledge
                WHERE {where_clause}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """), params)

            knowledge_list = []
            for row in result.fetchall():
                knowledge_list.append(KnowledgeData(
                    id=row[0],
                    organization_id=row[1],
                    source_insight_id=row[2],
                    source_pattern_id=row[3],
                    question=row[4],
                    answer=row[5],
                    category=row[6],
                    keywords=row[7] or [],
                    status=row[8],
                    approved_at=row[9],
                    approved_by=row[10],
                    rejection_reason=row[11],
                    synced_to_phase3=row[12],
                    phase3_document_id=row[13],
                    usage_count=row[14],
                    helpful_count=row[15],
                    quality_score=float(row[16]) if row[16] else None,
                    classification=row[17],
                    created_at=row[18],
                    updated_at=row[19],
                ))

            return knowledge_list

        except Exception as e:
            logger.error(f"Failed to retrieve knowledge: {e}")
            raise DatabaseError(
                message=f"Failed to retrieve knowledge: {str(e)}",
                original_error=e
            )

    @wrap_memory_error
    async def generate_from_pattern(
        self,
        insight_id: UUID,
        pattern_id: UUID,
        question: str,
        occurrence_count: int,
        unique_users: int,
        category: str,
        sample_questions: List[str]
    ) -> MemoryResult:
        """
        A1パターン検出から自動的に知識を生成

        Args:
            insight_id: インサイトID
            pattern_id: パターンID
            question: 正規化された質問
            occurrence_count: 発生回数
            unique_users: ユニークユーザー数
            category: カテゴリ
            sample_questions: サンプル質問

        Returns:
            MemoryResult: 生成結果
        """
        # 既存の知識がないか確認
        existing = await self._get_by_pattern_id(pattern_id)
        if existing:
            return MemoryResult(
                success=False,
                memory_id=existing.id,
                message="Knowledge already exists for this pattern"
            )

        # LLMで回答を生成
        answer_data = await self._generate_answer(
            question=question,
            occurrence_count=occurrence_count,
            unique_users=unique_users,
            category=category,
            sample_questions=sample_questions
        )

        # 保存
        return await self.save(
            question=question,
            answer=answer_data.get("answer", ""),
            category=category,
            keywords=answer_data.get("keywords", []),
            source_insight_id=insight_id,
            source_pattern_id=pattern_id
        )

    @wrap_memory_error
    async def approve(
        self,
        knowledge_id: UUID,
        approved_by: UUID,
        answer: Optional[str] = None
    ) -> MemoryResult:
        """
        知識を承認

        Args:
            knowledge_id: 知識ID
            approved_by: 承認者ID
            answer: 修正後の回答（オプション）

        Returns:
            MemoryResult: 承認結果
        """
        knowledge_id = self.validate_uuid(knowledge_id, "knowledge_id")
        approved_by = self.validate_uuid(approved_by, "approved_by")

        try:
            update_parts = [
                "status = :status",
                "approved_at = CURRENT_TIMESTAMP",
                "approved_by = :approved_by",
                "updated_at = CURRENT_TIMESTAMP"
            ]
            params = {
                "knowledge_id": str(knowledge_id),
                "org_id": str(self.org_id),
                "status": KnowledgeStatus.APPROVED.value,
                "approved_by": str(approved_by),
            }

            if answer:
                update_parts.append("answer = :answer")
                params["answer"] = answer

            update_clause = ", ".join(update_parts)

            result = self.conn.execute(text(f"""
                UPDATE organization_auto_knowledge
                SET {update_clause}
                WHERE id = :knowledge_id
                  AND organization_id = :org_id
                RETURNING id
            """), params)

            row = result.fetchone()
            self.conn.commit()

            if not row:
                return MemoryResult(
                    success=False,
                    message="Knowledge not found"
                )

            self._log_operation("approve_knowledge", details={
                "knowledge_id": str(knowledge_id),
                "approved_by": str(approved_by),
            })

            return MemoryResult(
                success=True,
                memory_id=knowledge_id,
                message="Knowledge approved successfully"
            )

        except Exception as e:
            logger.error(f"Failed to approve knowledge: {e}")
            raise DatabaseError(
                message=f"Failed to approve knowledge: {str(e)}",
                original_error=e
            )

    @wrap_memory_error
    async def reject(
        self,
        knowledge_id: UUID,
        reason: str
    ) -> MemoryResult:
        """
        知識を却下

        Args:
            knowledge_id: 知識ID
            reason: 却下理由

        Returns:
            MemoryResult: 却下結果
        """
        knowledge_id = self.validate_uuid(knowledge_id, "knowledge_id")

        try:
            result = self.conn.execute(text("""
                UPDATE organization_auto_knowledge
                SET status = :status,
                    rejection_reason = :reason,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :knowledge_id
                  AND organization_id = :org_id
                RETURNING id
            """), {
                "knowledge_id": str(knowledge_id),
                "org_id": str(self.org_id),
                "status": KnowledgeStatus.REJECTED.value,
                "reason": reason,
            })

            row = result.fetchone()
            self.conn.commit()

            if not row:
                return MemoryResult(
                    success=False,
                    message="Knowledge not found"
                )

            return MemoryResult(
                success=True,
                memory_id=knowledge_id,
                message="Knowledge rejected"
            )

        except Exception as e:
            logger.error(f"Failed to reject knowledge: {e}")
            raise DatabaseError(
                message=f"Failed to reject knowledge: {str(e)}",
                original_error=e
            )

    @wrap_memory_error
    async def record_usage(
        self,
        knowledge_id: UUID,
        was_helpful: bool = True
    ) -> MemoryResult:
        """
        使用を記録

        Args:
            knowledge_id: 知識ID
            was_helpful: 役に立ったか

        Returns:
            MemoryResult: 記録結果
        """
        knowledge_id = self.validate_uuid(knowledge_id, "knowledge_id")

        try:
            helpful_increment = 1 if was_helpful else 0

            result = self.conn.execute(text("""
                UPDATE organization_auto_knowledge
                SET usage_count = usage_count + 1,
                    helpful_count = helpful_count + :helpful_increment,
                    quality_score = CASE
                        WHEN usage_count + 1 > 0
                        THEN (helpful_count + :helpful_increment)::DECIMAL / (usage_count + 1)
                        ELSE NULL
                    END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :knowledge_id
                  AND organization_id = :org_id
                RETURNING usage_count, helpful_count, quality_score
            """), {
                "knowledge_id": str(knowledge_id),
                "org_id": str(self.org_id),
                "helpful_increment": helpful_increment,
            })

            row = result.fetchone()
            self.conn.commit()

            if not row:
                return MemoryResult(
                    success=False,
                    message="Knowledge not found"
                )

            return MemoryResult(
                success=True,
                memory_id=knowledge_id,
                data={
                    "usage_count": row[0],
                    "helpful_count": row[1],
                    "quality_score": float(row[2]) if row[2] else None,
                }
            )

        except Exception as e:
            logger.error(f"Failed to record usage: {e}")
            raise DatabaseError(
                message=f"Failed to record usage: {str(e)}",
                original_error=e
            )

    @wrap_memory_error
    async def search_approved(
        self,
        query: str,
        limit: int = 5
    ) -> List[KnowledgeData]:
        """
        承認済みの知識を検索

        Args:
            query: 検索クエリ
            limit: 取得件数

        Returns:
            List[KnowledgeData]: マッチした知識
        """
        try:
            # キーワード配列でのマッチングと質問文でのマッチング
            result = self.conn.execute(text("""
                SELECT
                    id, organization_id, source_insight_id, source_pattern_id,
                    question, answer, category, keywords, status,
                    approved_at, approved_by, rejection_reason,
                    synced_to_phase3, phase3_document_id,
                    usage_count, helpful_count, quality_score,
                    classification, created_at, updated_at
                FROM organization_auto_knowledge
                WHERE organization_id = :org_id
                  AND status = :status
                  AND (
                      question ILIKE :query
                      OR :query_word = ANY(keywords)
                  )
                ORDER BY usage_count DESC, quality_score DESC NULLS LAST
                LIMIT :limit
            """), {
                "org_id": str(self.org_id),
                "status": KnowledgeStatus.APPROVED.value,
                "query": f"%{query}%",
                "query_word": query,
                "limit": limit,
            })

            knowledge_list = []
            for row in result.fetchall():
                knowledge_list.append(KnowledgeData(
                    id=row[0],
                    organization_id=row[1],
                    source_insight_id=row[2],
                    source_pattern_id=row[3],
                    question=row[4],
                    answer=row[5],
                    category=row[6],
                    keywords=row[7] or [],
                    status=row[8],
                    approved_at=row[9],
                    approved_by=row[10],
                    rejection_reason=row[11],
                    synced_to_phase3=row[12],
                    phase3_document_id=row[13],
                    usage_count=row[14],
                    helpful_count=row[15],
                    quality_score=float(row[16]) if row[16] else None,
                    classification=row[17],
                    created_at=row[18],
                    updated_at=row[19],
                ))

            return knowledge_list

        except Exception as e:
            logger.error(f"Failed to search knowledge: {e}")
            raise DatabaseError(
                message=f"Failed to search knowledge: {str(e)}",
                original_error=e
            )

    # ================================================================
    # 内部メソッド
    # ================================================================

    async def _get_by_pattern_id(self, pattern_id: UUID) -> Optional[KnowledgeData]:
        """パターンIDで知識を取得"""
        try:
            result = self.conn.execute(text("""
                SELECT id FROM organization_auto_knowledge
                WHERE organization_id = :org_id
                  AND source_pattern_id = :pattern_id
            """), {
                "org_id": str(self.org_id),
                "pattern_id": str(pattern_id),
            })

            row = result.fetchone()
            if row:
                return KnowledgeData(id=row[0])
            return None

        except Exception:
            return None

    async def _generate_answer(
        self,
        question: str,
        occurrence_count: int,
        unique_users: int,
        category: str,
        sample_questions: List[str]
    ) -> Dict[str, Any]:
        """
        LLMで回答を生成

        Args:
            question: 質問
            occurrence_count: 発生回数
            unique_users: ユニークユーザー数
            category: カテゴリ
            sample_questions: サンプル質問

        Returns:
            Dict: 回答データ
        """
        sample_text = "\n".join(f"- {q}" for q in sample_questions[:5])

        prompt = AUTO_KNOWLEDGE_GENERATION_PROMPT.format(
            question=question,
            occurrence_count=occurrence_count,
            unique_users=unique_users,
            category=category,
            sample_questions=sample_text
        )

        try:
            response = await self.call_llm(prompt)
            return self.extract_json_from_response(response)

        except Exception as e:
            logger.error(f"Failed to generate answer: {e}")
            # フォールバック
            return {
                "answer": f"この質問（{question}）への回答は管理者により作成される予定です。",
                "keywords": [],
            }
