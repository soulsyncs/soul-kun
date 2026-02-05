# lib/brain/ceo_teaching_repository.py
"""
CEO教えのリポジトリ層

DBアクセスを抽象化し、CEO教えの永続化を担当します。

設計書: docs/15_phase2d_ceo_learning.md
10の鉄則:
- #1: 全クエリにorganization_idフィルタ
- #9: SQLインジェクション対策（パラメータ化クエリ）
"""

from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from uuid import UUID
import json
import logging

from sqlalchemy import text
from sqlalchemy.engine import Engine

from .models import (
    CEOTeaching,
    TeachingCategory,
    ValidationStatus,
    ConflictInfo,
    ConflictType,
    GuardianAlert,
    AlertStatus,
    Severity,
    TeachingUsageContext,
)

logger = logging.getLogger(__name__)


# =============================================================================
# UUID検証ヘルパー
# =============================================================================

def _check_uuid_format(org_id: str) -> bool:
    """
    organization_idがUUID形式かどうかをチェック

    ceo_teachingsテーブルのorganization_idカラムはUUID型のため、
    "org_soulsyncs"のようなテキスト形式の場合はクエリを実行できない。

    Args:
        org_id: 組織ID

    Returns:
        bool: UUID形式ならTrue、そうでなければFalse
    """
    if not org_id:
        return False
    try:
        UUID(org_id)
        return True
    except (ValueError, TypeError):
        return False


# =============================================================================
# CEO教えリポジトリ
# =============================================================================


class CEOTeachingRepository:
    """
    CEO教えのリポジトリ

    ceo_teachings テーブルへのCRUD操作を提供します。

    【注意】organization_idがUUID形式でない場合
    ceo_teachingsテーブルのorganization_idカラムはUUID型のため、
    "org_soulsyncs"のようなテキスト形式の場合はDBクエリを実行せず、
    空のリスト/Noneを返します。これにより、PostgreSQLの
    "invalid input syntax for type uuid" エラーを防ぎます。
    """

    def __init__(self, pool: Engine, organization_id: str):
        """
        初期化

        Args:
            pool: SQLAlchemyのエンジン（DB接続プール）
            organization_id: 組織ID（テナント分離用）
        """
        self._pool = pool
        self._organization_id = organization_id
        # organization_idがUUID形式かどうかを判定
        self._org_id_is_uuid = _check_uuid_format(organization_id)
        if not self._org_id_is_uuid:
            logger.debug(
                f"CEOTeachingRepository: organization_id={organization_id} is not UUID format. "
                "DB queries will be skipped."
            )

    # -------------------------------------------------------------------------
    # Create
    # -------------------------------------------------------------------------

    def create_teaching(self, teaching: CEOTeaching) -> CEOTeaching:
        """
        教えを作成

        Args:
            teaching: 作成する教え

        Returns:
            作成された教え（IDが設定済み）

        Raises:
            ValueError: organization_idがUUID形式でない場合
        """
        # UUID形式でない場合はエラー（教え作成は重要な操作のためスキップではなくエラー）
        if not self._org_id_is_uuid:
            raise ValueError(
                f"Cannot create CEO teaching: organization_id={self._organization_id} is not UUID format"
            )

        query = text("""
            INSERT INTO ceo_teachings (
                organization_id,
                ceo_user_id,
                statement,
                reasoning,
                context,
                target,
                category,
                subcategory,
                keywords,
                validation_status,
                mvv_alignment_score,
                theory_alignment_score,
                priority,
                is_active,
                supersedes,
                source_room_id,
                source_message_id,
                classification
            ) VALUES (
                :organization_id,
                :ceo_user_id,
                :statement,
                :reasoning,
                :context,
                :target,
                :category,
                :subcategory,
                :keywords,
                :validation_status,
                :mvv_alignment_score,
                :theory_alignment_score,
                :priority,
                :is_active,
                :supersedes,
                :source_room_id,
                :source_message_id,
                :classification
            )
            RETURNING id, created_at, updated_at
        """)

        params = {
            "organization_id": self._organization_id,
            "ceo_user_id": teaching.ceo_user_id,
            "statement": teaching.statement,
            "reasoning": teaching.reasoning,
            "context": teaching.context,
            "target": teaching.target,
            "category": teaching.category.value if isinstance(teaching.category, TeachingCategory) else teaching.category,
            "subcategory": teaching.subcategory,
            "keywords": teaching.keywords,
            "validation_status": teaching.validation_status.value if isinstance(teaching.validation_status, ValidationStatus) else teaching.validation_status,
            "mvv_alignment_score": teaching.mvv_alignment_score,
            "theory_alignment_score": teaching.theory_alignment_score,
            "priority": teaching.priority,
            "is_active": teaching.is_active,
            "supersedes": teaching.supersedes,
            "source_room_id": teaching.source_room_id,
            "source_message_id": teaching.source_message_id,
            "classification": "confidential",  # CEO教えは機密
        }

        with self._pool.connect() as conn:
            result = conn.execute(query, params)
            row = result.fetchone()
            conn.commit()

        if row is None:
            raise ValueError("Failed to create teaching: no row returned")

        teaching.id = str(row[0])
        teaching.organization_id = self._organization_id
        teaching.created_at = row[1]
        teaching.updated_at = row[2]

        logger.info(
            f"CEO teaching created: id={teaching.id}, "
            f"category={teaching.category}, statement={teaching.statement[:50]}..."
        )

        return teaching

    # -------------------------------------------------------------------------
    # Read
    # -------------------------------------------------------------------------

    def get_teaching_by_id(self, teaching_id: str) -> Optional[CEOTeaching]:
        """
        IDで教えを取得

        Args:
            teaching_id: 教えのID

        Returns:
            教え（見つからない場合はNone）
        """
        # UUID形式でない場合はスキップ
        if not self._org_id_is_uuid:
            logger.debug(f"Skipping get_teaching_by_id: organization_id is not UUID format")
            return None

        query = text("""
            SELECT
                id, organization_id, ceo_user_id,
                statement, reasoning, context, target,
                category, subcategory, keywords,
                validation_status, mvv_alignment_score, theory_alignment_score,
                priority, is_active, supersedes,
                usage_count, last_used_at, helpful_count,
                source_room_id, source_message_id, extracted_at,
                created_at, updated_at
            FROM ceo_teachings
            WHERE id = :teaching_id
              AND organization_id = :organization_id
        """)

        with self._pool.connect() as conn:
            result = conn.execute(query, {
                "teaching_id": teaching_id,
                "organization_id": self._organization_id,
            })
            row = result.fetchone()

        if row is None:
            return None

        return self._row_to_teaching(row)

    def get_active_teachings(
        self,
        category: Optional[TeachingCategory] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[CEOTeaching]:
        """
        アクティブな教えを取得

        Args:
            category: カテゴリでフィルタ（省略時は全カテゴリ）
            limit: 取得件数
            offset: オフセット

        Returns:
            教えのリスト（優先度順）
        """
        # UUID形式でない場合はスキップ
        if not self._org_id_is_uuid:
            logger.debug(f"Skipping get_active_teachings: organization_id is not UUID format")
            return []

        base_query = """
            SELECT
                id, organization_id, ceo_user_id,
                statement, reasoning, context, target,
                category, subcategory, keywords,
                validation_status, mvv_alignment_score, theory_alignment_score,
                priority, is_active, supersedes,
                usage_count, last_used_at, helpful_count,
                source_room_id, source_message_id, extracted_at,
                created_at, updated_at
            FROM ceo_teachings
            WHERE organization_id = :organization_id
              AND is_active = true
              AND validation_status IN ('verified', 'overridden')
        """

        params: Dict[str, Any] = {
            "organization_id": self._organization_id,
            "limit": limit,
            "offset": offset,
        }

        if category:
            base_query += " AND category = :category"
            params["category"] = category.value if isinstance(category, TeachingCategory) else category

        base_query += " ORDER BY priority DESC, usage_count DESC, created_at DESC"
        base_query += " LIMIT :limit OFFSET :offset"

        query = text(base_query)

        with self._pool.connect() as conn:
            result = conn.execute(query, params)
            rows = result.fetchall()

        return [self._row_to_teaching(row) for row in rows]

    async def search_relevant(
        self,
        query: str,
        organization_id: Optional[str] = None,
        limit: int = 10,
    ) -> List[CEOTeaching]:
        """
        関連するCEO教えを非同期検索（ContextBuilder用）

        設計書: docs/25_llm_native_brain_architecture.md
        LLM Brainのコンテキスト構築時に使用。

        Args:
            query: 検索クエリ
            organization_id: 組織ID（省略時はインスタンスのものを使用）
            limit: 取得件数

        Returns:
            関連度順の教えリスト
        """
        # UUID形式でない場合はスキップ（エラーログも出さない）
        if not self._org_id_is_uuid:
            logger.debug(f"Skipping search_relevant: organization_id is not UUID format")
            return []

        # 同期メソッドをラップ
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.search_teachings(query, limit)
        )

    def search_teachings(
        self,
        query_text: str,
        limit: int = 10,
    ) -> List[CEOTeaching]:
        """
        教えをキーワード検索

        Args:
            query_text: 検索クエリ
            limit: 取得件数

        Returns:
            関連度順の教えリスト
        """
        # UUID形式でない場合はスキップ
        if not self._org_id_is_uuid:
            logger.debug(f"Skipping search_teachings: organization_id is not UUID format")
            return []

        # キーワードを分割
        keywords = [k.strip() for k in query_text.split() if k.strip()]

        if not keywords:
            return []

        # LIKE検索（将来的にはベクトル検索も検討）
        conditions = []
        params: Dict[str, Any] = {
            "organization_id": self._organization_id,
            "limit": limit,
        }

        for i, kw in enumerate(keywords[:5]):  # 最大5キーワード
            param_name = f"kw_{i}"
            conditions.append(f"""
                (statement ILIKE :{param_name}
                 OR reasoning ILIKE :{param_name}
                 OR context ILIKE :{param_name}
                 OR :{param_name} = ANY(keywords))
            """)
            params[param_name] = f"%{kw}%"

        where_clause = " OR ".join(conditions)

        query = text(f"""
            SELECT
                id, organization_id, ceo_user_id,
                statement, reasoning, context, target,
                category, subcategory, keywords,
                validation_status, mvv_alignment_score, theory_alignment_score,
                priority, is_active, supersedes,
                usage_count, last_used_at, helpful_count,
                source_room_id, source_message_id, extracted_at,
                created_at, updated_at
            FROM ceo_teachings
            WHERE organization_id = :organization_id
              AND is_active = true
              AND validation_status IN ('verified', 'overridden')
              AND ({where_clause})
            ORDER BY priority DESC, usage_count DESC
            LIMIT :limit
        """)

        with self._pool.connect() as conn:
            result = conn.execute(query, params)
            rows = result.fetchall()

        return [self._row_to_teaching(row) for row in rows]

    def get_teachings_by_category(
        self,
        categories: List[TeachingCategory],
        limit: int = 10,
    ) -> List[CEOTeaching]:
        """
        指定カテゴリの教えを取得

        Args:
            categories: カテゴリのリスト
            limit: 取得件数

        Returns:
            教えのリスト
        """
        # UUID形式でない場合はスキップ
        if not self._org_id_is_uuid:
            logger.debug(f"Skipping get_teachings_by_category: organization_id is not UUID format")
            return []

        if not categories:
            return []

        category_values = [
            c.value if isinstance(c, TeachingCategory) else c
            for c in categories
        ]

        query = text("""
            SELECT
                id, organization_id, ceo_user_id,
                statement, reasoning, context, target,
                category, subcategory, keywords,
                validation_status, mvv_alignment_score, theory_alignment_score,
                priority, is_active, supersedes,
                usage_count, last_used_at, helpful_count,
                source_room_id, source_message_id, extracted_at,
                created_at, updated_at
            FROM ceo_teachings
            WHERE organization_id = :organization_id
              AND is_active = true
              AND validation_status IN ('verified', 'overridden')
              AND category = ANY(:categories)
            ORDER BY priority DESC, usage_count DESC
            LIMIT :limit
        """)

        with self._pool.connect() as conn:
            result = conn.execute(query, {
                "organization_id": self._organization_id,
                "categories": category_values,
                "limit": limit,
            })
            rows = result.fetchall()

        return [self._row_to_teaching(row) for row in rows]

    def get_pending_teachings(self) -> List[CEOTeaching]:
        """
        検証待ちの教えを取得

        Returns:
            検証待ちの教えリスト
        """
        # UUID形式でない場合はスキップ
        if not self._org_id_is_uuid:
            logger.debug(f"Skipping get_pending_teachings: organization_id is not UUID format")
            return []

        query = text("""
            SELECT
                id, organization_id, ceo_user_id,
                statement, reasoning, context, target,
                category, subcategory, keywords,
                validation_status, mvv_alignment_score, theory_alignment_score,
                priority, is_active, supersedes,
                usage_count, last_used_at, helpful_count,
                source_room_id, source_message_id, extracted_at,
                created_at, updated_at
            FROM ceo_teachings
            WHERE organization_id = :organization_id
              AND validation_status = 'pending'
            ORDER BY created_at ASC
        """)

        with self._pool.connect() as conn:
            result = conn.execute(query, {
                "organization_id": self._organization_id,
            })
            rows = result.fetchall()

        return [self._row_to_teaching(row) for row in rows]

    # -------------------------------------------------------------------------
    # Update
    # -------------------------------------------------------------------------

    def update_teaching(
        self,
        teaching_id: str,
        updates: Dict[str, Any],
    ) -> Optional[CEOTeaching]:
        """
        教えを更新

        Args:
            teaching_id: 教えのID
            updates: 更新するフィールドと値

        Returns:
            更新された教え（見つからない場合はNone）
        """
        # UUID形式でない場合はスキップ
        if not self._org_id_is_uuid:
            logger.debug(f"Skipping update_teaching: organization_id is not UUID format")
            return None

        if not updates:
            return self.get_teaching_by_id(teaching_id)

        # 許可されたフィールドのみ更新
        allowed_fields = {
            "statement", "reasoning", "context", "target",
            "category", "subcategory", "keywords",
            "validation_status", "mvv_alignment_score", "theory_alignment_score",
            "priority", "is_active", "supersedes",
        }

        filtered_updates = {
            k: v for k, v in updates.items() if k in allowed_fields
        }

        if not filtered_updates:
            return self.get_teaching_by_id(teaching_id)

        # SET句を構築
        set_clauses = []
        params: Dict[str, Any] = {
            "teaching_id": teaching_id,
            "organization_id": self._organization_id,
        }

        for field, value in filtered_updates.items():
            set_clauses.append(f"{field} = :{field}")
            # Enumを値に変換
            if isinstance(value, TeachingCategory):
                params[field] = value.value
            elif isinstance(value, ValidationStatus):
                params[field] = value.value
            else:
                params[field] = value

        query = text(f"""
            UPDATE ceo_teachings
            SET {", ".join(set_clauses)}, updated_at = CURRENT_TIMESTAMP
            WHERE id = :teaching_id
              AND organization_id = :organization_id
            RETURNING id
        """)

        with self._pool.connect() as conn:
            result = conn.execute(query, params)
            row = result.fetchone()
            conn.commit()

        if row is None:
            return None

        logger.info(f"CEO teaching updated: id={teaching_id}, fields={list(filtered_updates.keys())}")

        return self.get_teaching_by_id(teaching_id)

    def update_validation_status(
        self,
        teaching_id: str,
        status: ValidationStatus,
        mvv_score: Optional[float] = None,
        theory_score: Optional[float] = None,
    ) -> bool:
        """
        検証ステータスを更新

        Args:
            teaching_id: 教えのID
            status: 新しいステータス
            mvv_score: MVV整合性スコア
            theory_score: 組織論整合性スコア

        Returns:
            更新成功ならTrue
        """
        # UUID形式でない場合はスキップ
        if not self._org_id_is_uuid:
            logger.debug(f"Skipping update_validation_status: organization_id is not UUID format")
            return False

        query = text("""
            UPDATE ceo_teachings
            SET validation_status = :status,
                mvv_alignment_score = COALESCE(:mvv_score, mvv_alignment_score),
                theory_alignment_score = COALESCE(:theory_score, theory_alignment_score),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :teaching_id
              AND organization_id = :organization_id
            RETURNING id
        """)

        with self._pool.connect() as conn:
            result = conn.execute(query, {
                "teaching_id": teaching_id,
                "organization_id": self._organization_id,
                "status": status.value if isinstance(status, ValidationStatus) else status,
                "mvv_score": mvv_score,
                "theory_score": theory_score,
            })
            row = result.fetchone()
            conn.commit()

        return row is not None

    def increment_usage(
        self,
        teaching_id: str,
        was_helpful: Optional[bool] = None,
    ) -> bool:
        """
        使用回数を増加

        Args:
            teaching_id: 教えのID
            was_helpful: 役に立ったかどうか

        Returns:
            更新成功ならTrue
        """
        # UUID形式でない場合はスキップ
        if not self._org_id_is_uuid:
            logger.debug(f"Skipping increment_usage: organization_id is not UUID format")
            return False

        helpful_increment = 1 if was_helpful else 0

        query = text("""
            UPDATE ceo_teachings
            SET usage_count = usage_count + 1,
                helpful_count = helpful_count + :helpful_increment,
                last_used_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :teaching_id
              AND organization_id = :organization_id
            RETURNING id
        """)

        with self._pool.connect() as conn:
            result = conn.execute(query, {
                "teaching_id": teaching_id,
                "organization_id": self._organization_id,
                "helpful_increment": helpful_increment,
            })
            row = result.fetchone()
            conn.commit()

        return row is not None

    # -------------------------------------------------------------------------
    # Delete (Soft Delete)
    # -------------------------------------------------------------------------

    def deactivate_teaching(
        self,
        teaching_id: str,
        superseded_by: Optional[str] = None,
    ) -> bool:
        """
        教えを無効化（ソフトデリート）

        Args:
            teaching_id: 教えのID
            superseded_by: 上書きした新しい教えのID

        Returns:
            無効化成功ならTrue
        """
        # UUID形式でない場合はスキップ
        if not self._org_id_is_uuid:
            logger.debug(f"Skipping deactivate_teaching: organization_id is not UUID format")
            return False

        query = text("""
            UPDATE ceo_teachings
            SET is_active = false,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :teaching_id
              AND organization_id = :organization_id
            RETURNING id
        """)

        with self._pool.connect() as conn:
            result = conn.execute(query, {
                "teaching_id": teaching_id,
                "organization_id": self._organization_id,
            })
            row = result.fetchone()

            # superseded_byが指定された場合、新しい教えを更新
            if row and superseded_by:
                conn.execute(text("""
                    UPDATE ceo_teachings
                    SET supersedes = :old_teaching_id
                    WHERE id = :new_teaching_id
                      AND organization_id = :organization_id
                """), {
                    "old_teaching_id": teaching_id,
                    "new_teaching_id": superseded_by,
                    "organization_id": self._organization_id,
                })

            conn.commit()

        if row:
            logger.info(f"CEO teaching deactivated: id={teaching_id}")

        return row is not None

    # -------------------------------------------------------------------------
    # Helper Methods
    # -------------------------------------------------------------------------

    def _row_to_teaching(self, row) -> CEOTeaching:
        """DBの行をCEOTeachingに変換"""
        return CEOTeaching(
            id=str(row[0]),
            organization_id=str(row[1]),
            ceo_user_id=str(row[2]) if row[2] else None,
            statement=row[3],
            reasoning=row[4],
            context=row[5],
            target=row[6],
            category=TeachingCategory(row[7]) if row[7] else TeachingCategory.OTHER,
            subcategory=row[8],
            keywords=row[9] if row[9] else [],
            validation_status=ValidationStatus(row[10]) if row[10] else ValidationStatus.PENDING,
            mvv_alignment_score=float(row[11]) if row[11] is not None else None,
            theory_alignment_score=float(row[12]) if row[12] is not None else None,
            priority=row[13] if row[13] is not None else 5,
            is_active=row[14] if row[14] is not None else True,
            supersedes=str(row[15]) if row[15] else None,
            usage_count=row[16] if row[16] is not None else 0,
            last_used_at=row[17],
            helpful_count=row[18] if row[18] is not None else 0,
            source_room_id=row[19],
            source_message_id=row[20],
            extracted_at=row[21] if row[21] else datetime.now(),
            created_at=row[22] if row[22] else datetime.now(),
            updated_at=row[23] if row[23] else datetime.now(),
        )


# =============================================================================
# 矛盾情報リポジトリ
# =============================================================================


class ConflictRepository:
    """
    矛盾情報のリポジトリ

    ceo_teaching_conflicts テーブルへのCRUD操作を提供します。

    【注意】organization_idがUUID形式でない場合はDBクエリを実行しません。
    """

    def __init__(self, pool: Engine, organization_id: str):
        self._pool = pool
        self._organization_id = organization_id
        self._org_id_is_uuid = _check_uuid_format(organization_id)

    def create_conflict(self, conflict: ConflictInfo) -> ConflictInfo:
        """矛盾情報を作成"""
        if not self._org_id_is_uuid:
            raise ValueError(
                f"Cannot create conflict: organization_id={self._organization_id} is not UUID format"
            )

        query = text("""
            INSERT INTO ceo_teaching_conflicts (
                organization_id,
                teaching_id,
                conflict_type,
                conflict_subtype,
                description,
                reference,
                severity,
                conflicting_teaching_id
            ) VALUES (
                :organization_id,
                :teaching_id,
                :conflict_type,
                :conflict_subtype,
                :description,
                :reference,
                :severity,
                :conflicting_teaching_id
            )
            RETURNING id, created_at
        """)

        params = {
            "organization_id": self._organization_id,
            "teaching_id": conflict.teaching_id,
            "conflict_type": conflict.conflict_type.value if isinstance(conflict.conflict_type, ConflictType) else conflict.conflict_type,
            "conflict_subtype": conflict.conflict_subtype,
            "description": conflict.description,
            "reference": conflict.reference,
            "severity": conflict.severity.value if isinstance(conflict.severity, Severity) else conflict.severity,
            "conflicting_teaching_id": conflict.conflicting_teaching_id,
        }

        with self._pool.connect() as conn:
            result = conn.execute(query, params)
            row = result.fetchone()
            conn.commit()

        if row is None:
            raise ValueError("Failed to create conflict: no row returned")

        conflict.id = str(row[0])
        conflict.organization_id = self._organization_id
        conflict.created_at = row[1]

        return conflict

    def get_conflicts_for_teaching(self, teaching_id: str) -> List[ConflictInfo]:
        """教えに関連する矛盾を取得"""
        if not self._org_id_is_uuid:
            logger.debug(f"Skipping get_conflicts_for_teaching: organization_id is not UUID format")
            return []

        query = text("""
            SELECT
                id, organization_id, teaching_id,
                conflict_type, conflict_subtype, description,
                reference, severity, conflicting_teaching_id,
                created_at
            FROM ceo_teaching_conflicts
            WHERE teaching_id = :teaching_id
              AND organization_id = :organization_id
            ORDER BY
                CASE severity
                    WHEN 'high' THEN 1
                    WHEN 'medium' THEN 2
                    WHEN 'low' THEN 3
                END,
                created_at DESC
        """)

        with self._pool.connect() as conn:
            result = conn.execute(query, {
                "teaching_id": teaching_id,
                "organization_id": self._organization_id,
            })
            rows = result.fetchall()

        return [self._row_to_conflict(row) for row in rows]

    def delete_conflicts_for_teaching(self, teaching_id: str) -> int:
        """教えに関連する矛盾を削除"""
        if not self._org_id_is_uuid:
            logger.debug(f"Skipping delete_conflicts_for_teaching: organization_id is not UUID format")
            return 0

        query = text("""
            DELETE FROM ceo_teaching_conflicts
            WHERE teaching_id = :teaching_id
              AND organization_id = :organization_id
        """)

        with self._pool.connect() as conn:
            result = conn.execute(query, {
                "teaching_id": teaching_id,
                "organization_id": self._organization_id,
            })
            conn.commit()

        rowcount: int = result.rowcount
        return rowcount

    def _row_to_conflict(self, row) -> ConflictInfo:
        """DBの行をConflictInfoに変換"""
        return ConflictInfo(
            id=str(row[0]),
            organization_id=str(row[1]),
            teaching_id=str(row[2]),
            conflict_type=ConflictType(row[3]) if row[3] else ConflictType.MVV,
            conflict_subtype=row[4],
            description=row[5],
            reference=row[6],
            severity=Severity(row[7]) if row[7] else Severity.MEDIUM,
            conflicting_teaching_id=str(row[8]) if row[8] else None,
            created_at=row[9] if row[9] else datetime.now(),
        )


# =============================================================================
# ガーディアンアラートリポジトリ
# =============================================================================


class GuardianAlertRepository:
    """
    ガーディアンアラートのリポジトリ

    guardian_alerts テーブルへのCRUD操作を提供します。

    【注意】organization_idがUUID形式でない場合はDBクエリを実行しません。
    """

    def __init__(self, pool: Engine, organization_id: str):
        self._pool = pool
        self._organization_id = organization_id
        self._org_id_is_uuid = _check_uuid_format(organization_id)
        self._conflict_repo = ConflictRepository(pool, organization_id)

    def create_alert(self, alert: GuardianAlert) -> GuardianAlert:
        """アラートを作成"""
        if not self._org_id_is_uuid:
            raise ValueError(
                f"Cannot create alert: organization_id={self._organization_id} is not UUID format"
            )

        query = text("""
            INSERT INTO guardian_alerts (
                organization_id,
                teaching_id,
                conflict_summary,
                alert_message,
                alternative_suggestion,
                status,
                classification
            ) VALUES (
                :organization_id,
                :teaching_id,
                :conflict_summary,
                :alert_message,
                :alternative_suggestion,
                :status,
                :classification
            )
            RETURNING id, created_at, updated_at
        """)

        params = {
            "organization_id": self._organization_id,
            "teaching_id": alert.teaching_id,
            "conflict_summary": alert.conflict_summary,
            "alert_message": alert.alert_message,
            "alternative_suggestion": alert.alternative_suggestion,
            "status": alert.status.value if isinstance(alert.status, AlertStatus) else alert.status,
            "classification": "confidential",
        }

        with self._pool.connect() as conn:
            result = conn.execute(query, params)
            row = result.fetchone()
            conn.commit()

        if row is None:
            raise ValueError("Failed to create alert: no row returned")

        alert.id = str(row[0])
        alert.organization_id = self._organization_id
        alert.created_at = row[1]
        alert.updated_at = row[2]

        logger.info(f"Guardian alert created: id={alert.id}, teaching_id={alert.teaching_id}")

        return alert

    def get_alert_by_id(self, alert_id: str) -> Optional[GuardianAlert]:
        """IDでアラートを取得"""
        if not self._org_id_is_uuid:
            logger.debug(f"Skipping get_alert_by_id: organization_id is not UUID format")
            return None

        query = text("""
            SELECT
                id, organization_id, teaching_id,
                conflict_summary, alert_message, alternative_suggestion,
                status, ceo_response, ceo_reasoning, resolved_at,
                notified_at, notification_room_id, notification_message_id,
                created_at, updated_at
            FROM guardian_alerts
            WHERE id = :alert_id
              AND organization_id = :organization_id
        """)

        with self._pool.connect() as conn:
            result = conn.execute(query, {
                "alert_id": alert_id,
                "organization_id": self._organization_id,
            })
            row = result.fetchone()

        if row is None:
            return None

        alert = self._row_to_alert(row)

        # 関連する矛盾情報を取得
        alert.conflicts = self._conflict_repo.get_conflicts_for_teaching(alert.teaching_id)

        return alert

    def get_pending_alerts(self) -> List[GuardianAlert]:
        """未解決のアラートを取得"""
        if not self._org_id_is_uuid:
            logger.debug(f"Skipping get_pending_alerts: organization_id is not UUID format")
            return []

        query = text("""
            SELECT
                id, organization_id, teaching_id,
                conflict_summary, alert_message, alternative_suggestion,
                status, ceo_response, ceo_reasoning, resolved_at,
                notified_at, notification_room_id, notification_message_id,
                created_at, updated_at
            FROM guardian_alerts
            WHERE organization_id = :organization_id
              AND status = 'pending'
            ORDER BY created_at ASC
        """)

        with self._pool.connect() as conn:
            result = conn.execute(query, {
                "organization_id": self._organization_id,
            })
            rows = result.fetchall()

        alerts = []
        for row in rows:
            alert = self._row_to_alert(row)
            alert.conflicts = self._conflict_repo.get_conflicts_for_teaching(alert.teaching_id)
            alerts.append(alert)

        return alerts

    def get_alert_by_teaching_id(self, teaching_id: str) -> Optional[GuardianAlert]:
        """教えIDでアラートを取得"""
        if not self._org_id_is_uuid:
            logger.debug(f"Skipping get_alert_by_teaching_id: organization_id is not UUID format")
            return None

        query = text("""
            SELECT
                id, organization_id, teaching_id,
                conflict_summary, alert_message, alternative_suggestion,
                status, ceo_response, ceo_reasoning, resolved_at,
                notified_at, notification_room_id, notification_message_id,
                created_at, updated_at
            FROM guardian_alerts
            WHERE teaching_id = :teaching_id
              AND organization_id = :organization_id
            ORDER BY created_at DESC
            LIMIT 1
        """)

        with self._pool.connect() as conn:
            result = conn.execute(query, {
                "teaching_id": teaching_id,
                "organization_id": self._organization_id,
            })
            row = result.fetchone()

        if row is None:
            return None

        alert = self._row_to_alert(row)
        alert.conflicts = self._conflict_repo.get_conflicts_for_teaching(alert.teaching_id)

        return alert

    def update_notification_info(
        self,
        alert_id: str,
        room_id: str,
        message_id: str,
    ) -> bool:
        """通知情報を更新"""
        if not self._org_id_is_uuid:
            logger.debug(f"Skipping update_notification_info: organization_id is not UUID format")
            return False

        query = text("""
            UPDATE guardian_alerts
            SET notified_at = CURRENT_TIMESTAMP,
                notification_room_id = :room_id,
                notification_message_id = :message_id,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :alert_id
              AND organization_id = :organization_id
            RETURNING id
        """)

        with self._pool.connect() as conn:
            result = conn.execute(query, {
                "alert_id": alert_id,
                "organization_id": self._organization_id,
                "room_id": room_id,
                "message_id": message_id,
            })
            row = result.fetchone()
            conn.commit()

        return row is not None

    def resolve_alert(
        self,
        alert_id: str,
        status: AlertStatus,
        ceo_response: Optional[str] = None,
        ceo_reasoning: Optional[str] = None,
    ) -> bool:
        """アラートを解決"""
        if not self._org_id_is_uuid:
            logger.debug(f"Skipping resolve_alert: organization_id is not UUID format")
            return False

        query = text("""
            UPDATE guardian_alerts
            SET status = :status,
                ceo_response = :ceo_response,
                ceo_reasoning = :ceo_reasoning,
                resolved_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :alert_id
              AND organization_id = :organization_id
            RETURNING id
        """)

        with self._pool.connect() as conn:
            result = conn.execute(query, {
                "alert_id": alert_id,
                "organization_id": self._organization_id,
                "status": status.value if isinstance(status, AlertStatus) else status,
                "ceo_response": ceo_response,
                "ceo_reasoning": ceo_reasoning,
            })
            row = result.fetchone()
            conn.commit()

        if row:
            logger.info(f"Guardian alert resolved: id={alert_id}, status={status}")

        return row is not None

    def _row_to_alert(self, row) -> GuardianAlert:
        """DBの行をGuardianAlertに変換"""
        return GuardianAlert(
            id=str(row[0]),
            organization_id=str(row[1]),
            teaching_id=str(row[2]),
            conflict_summary=row[3],
            alert_message=row[4],
            alternative_suggestion=row[5],
            status=AlertStatus(row[6]) if row[6] else AlertStatus.PENDING,
            ceo_response=row[7],
            ceo_reasoning=row[8],
            resolved_at=row[9],
            notified_at=row[10],
            notification_room_id=row[11],
            notification_message_id=row[12],
            created_at=row[13] if row[13] else datetime.now(),
            updated_at=row[14] if row[14] else datetime.now(),
        )


# =============================================================================
# 教え使用ログリポジトリ
# =============================================================================


class TeachingUsageRepository:
    """
    教え使用ログのリポジトリ

    teaching_usage_logs テーブルへの操作を提供します。

    【注意】organization_idがUUID形式でない場合はDBクエリを実行しません。
    """

    def __init__(self, pool: Engine, organization_id: str):
        self._pool = pool
        self._organization_id = organization_id
        self._org_id_is_uuid = _check_uuid_format(organization_id)

    def log_usage(self, usage: TeachingUsageContext) -> TeachingUsageContext:
        """使用ログを記録"""
        if not self._org_id_is_uuid:
            logger.debug(f"Skipping log_usage: organization_id is not UUID format")
            return usage  # ログ記録なしでそのまま返す

        query = text("""
            INSERT INTO teaching_usage_logs (
                organization_id,
                teaching_id,
                room_id,
                account_id,
                user_message,
                response_excerpt,
                relevance_score,
                selection_reasoning,
                classification
            ) VALUES (
                :organization_id,
                :teaching_id,
                :room_id,
                :account_id,
                :user_message,
                :response_excerpt,
                :relevance_score,
                :selection_reasoning,
                :classification
            )
            RETURNING id, created_at
        """)

        params = {
            "organization_id": self._organization_id,
            "teaching_id": usage.teaching_id,
            "room_id": usage.room_id,
            "account_id": usage.account_id,
            "user_message": usage.user_message[:500] if usage.user_message else "",  # 500文字まで
            "response_excerpt": usage.response_excerpt[:200] if usage.response_excerpt else None,  # 200文字まで
            "relevance_score": usage.relevance_score,
            "selection_reasoning": usage.selection_reasoning,
            "classification": "internal",
        }

        with self._pool.connect() as conn:
            result = conn.execute(query, params)
            row = result.fetchone()
            conn.commit()

        return usage

    def update_feedback(
        self,
        teaching_id: str,
        room_id: str,
        was_helpful: bool,
        feedback: Optional[str] = None,
    ) -> bool:
        """フィードバックを更新"""
        if not self._org_id_is_uuid:
            logger.debug(f"Skipping update_feedback: organization_id is not UUID format")
            return False

        # 直近の使用ログを更新
        query = text("""
            UPDATE teaching_usage_logs
            SET was_helpful = :was_helpful,
                feedback = :feedback
            WHERE id = (
                SELECT id FROM teaching_usage_logs
                WHERE organization_id = :organization_id
                  AND teaching_id = :teaching_id
                  AND room_id = :room_id
                ORDER BY created_at DESC
                LIMIT 1
            )
            RETURNING id
        """)

        with self._pool.connect() as conn:
            result = conn.execute(query, {
                "organization_id": self._organization_id,
                "teaching_id": teaching_id,
                "room_id": room_id,
                "was_helpful": was_helpful,
                "feedback": feedback,
            })
            row = result.fetchone()
            conn.commit()

        return row is not None

    def get_usage_stats(
        self,
        teaching_id: str,
        days: int = 30,
    ) -> Dict[str, Any]:
        """使用統計を取得"""
        if not self._org_id_is_uuid:
            logger.debug(f"Skipping get_usage_stats: organization_id is not UUID format")
            return {
                "total_usage": 0,
                "helpful_count": 0,
                "not_helpful_count": 0,
                "avg_relevance_score": None,
            }

        query = text("""
            SELECT
                COUNT(*) as total_usage,
                COUNT(CASE WHEN was_helpful = true THEN 1 END) as helpful_count,
                COUNT(CASE WHEN was_helpful = false THEN 1 END) as not_helpful_count,
                AVG(relevance_score) as avg_relevance_score
            FROM teaching_usage_logs
            WHERE organization_id = :organization_id
              AND teaching_id = :teaching_id
              AND created_at >= :since
        """)

        since = datetime.now() - timedelta(days=days)

        with self._pool.connect() as conn:
            result = conn.execute(query, {
                "organization_id": self._organization_id,
                "teaching_id": teaching_id,
                "since": since,
            })
            row = result.fetchone()

        if row is None:
            return {
                "total_usage": 0,
                "helpful_count": 0,
                "not_helpful_count": 0,
                "avg_relevance_score": None,
            }

        return {
            "total_usage": row[0] or 0,
            "helpful_count": row[1] or 0,
            "not_helpful_count": row[2] or 0,
            "avg_relevance_score": float(row[3]) if row[3] else None,
        }
