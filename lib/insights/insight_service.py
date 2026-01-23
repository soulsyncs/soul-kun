"""
Phase 2 進化版: インサイト管理サービス

このモジュールは、soulkun_insights テーブルのCRUD操作と
インサイトに関するビジネスロジックを提供します。

設計書: docs/06_phase2_a1_pattern_detection.md

Author: Claude Code（経営参謀・SE・PM）
Created: 2026-01-23
Version: 1.0
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import json
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection

from lib.detection.constants import (
    Classification,
    Importance,
    InsightStatus,
    InsightType,
    SourceType,
)
from lib.detection.exceptions import (
    DatabaseError,
    InsightCreateError,
    ValidationError,
    wrap_database_error,
)


def _should_audit(classification: Classification) -> bool:
    """機密区分がconfidential以上の場合はTrue"""
    return classification in {Classification.CONFIDENTIAL, Classification.RESTRICTED}


# ================================================================
# データクラス
# ================================================================

@dataclass
class InsightFilter:
    """
    インサイト検索のフィルタ条件

    Attributes:
        organization_id: 組織ID（必須）
        department_id: 部署ID（オプション）
        insight_types: インサイトタイプのリスト（オプション）
        source_types: ソースタイプのリスト（オプション）
        statuses: ステータスのリスト（オプション）
        importances: 重要度のリスト（オプション）
        from_date: 検索開始日（オプション）
        to_date: 検索終了日（オプション）
        notified: 通知済みかどうか（オプション）
    """

    organization_id: UUID
    department_id: Optional[UUID] = None
    insight_types: Optional[list[InsightType]] = None
    source_types: Optional[list[SourceType]] = None
    statuses: Optional[list[InsightStatus]] = None
    importances: Optional[list[Importance]] = None
    from_date: Optional[datetime] = None
    to_date: Optional[datetime] = None
    notified: Optional[bool] = None


@dataclass
class InsightSummary:
    """
    インサイトのサマリー情報

    Attributes:
        total: 総件数
        by_status: ステータス別件数
        by_importance: 重要度別件数
        by_type: タイプ別件数
    """

    total: int
    by_status: dict[str, int] = field(default_factory=dict)
    by_importance: dict[str, int] = field(default_factory=dict)
    by_type: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """
        辞書形式に変換

        Returns:
            サマリー情報の辞書
        """
        return {
            "total": self.total,
            "by_status": self.by_status,
            "by_importance": self.by_importance,
            "by_type": self.by_type,
        }


@dataclass
class InsightRecord:
    """
    インサイトレコード

    soulkun_insights テーブルの1レコードを表現

    Attributes:
        id: インサイトID
        organization_id: 組織ID
        department_id: 部署ID
        insight_type: インサイトタイプ
        source_type: ソースタイプ
        source_id: ソースID
        importance: 重要度
        title: タイトル
        description: 説明
        recommended_action: 推奨アクション
        evidence: 根拠データ
        status: ステータス
        acknowledged_at: 確認日時
        acknowledged_by: 確認者ID
        addressed_at: 対応日時
        addressed_by: 対応者ID
        addressed_action: 対応内容
        dismissed_reason: 無視理由
        notified_at: 通知日時
        notified_to: 通知先ユーザーリスト
        notified_via: 通知方法
        classification: 機密区分
        created_by: 作成者ID
        updated_by: 更新者ID
        created_at: 作成日時
        updated_at: 更新日時
    """

    id: UUID
    organization_id: UUID
    department_id: Optional[UUID]
    insight_type: str
    source_type: str
    source_id: Optional[UUID]
    importance: str
    title: str
    description: str
    recommended_action: Optional[str]
    evidence: dict[str, Any]
    status: str
    acknowledged_at: Optional[datetime]
    acknowledged_by: Optional[UUID]
    addressed_at: Optional[datetime]
    addressed_by: Optional[UUID]
    addressed_action: Optional[str]
    dismissed_reason: Optional[str]
    notified_at: Optional[datetime]
    notified_to: list[UUID]
    notified_via: Optional[str]
    classification: str
    created_by: Optional[UUID]
    updated_by: Optional[UUID]
    created_at: datetime
    updated_at: datetime

    def to_dict(self) -> dict[str, Any]:
        """
        辞書形式に変換

        Returns:
            インサイトデータの辞書
        """
        return {
            "id": str(self.id),
            "organization_id": str(self.organization_id),
            "department_id": str(self.department_id) if self.department_id else None,
            "insight_type": self.insight_type,
            "source_type": self.source_type,
            "source_id": str(self.source_id) if self.source_id else None,
            "importance": self.importance,
            "title": self.title,
            "description": self.description,
            "recommended_action": self.recommended_action,
            "evidence": self.evidence,
            "status": self.status,
            "acknowledged_at": self.acknowledged_at.isoformat() if self.acknowledged_at else None,
            "acknowledged_by": str(self.acknowledged_by) if self.acknowledged_by else None,
            "addressed_at": self.addressed_at.isoformat() if self.addressed_at else None,
            "addressed_by": str(self.addressed_by) if self.addressed_by else None,
            "addressed_action": self.addressed_action,
            "dismissed_reason": self.dismissed_reason,
            "notified_at": self.notified_at.isoformat() if self.notified_at else None,
            "notified_to": [str(uid) for uid in self.notified_to] if self.notified_to else [],
            "notified_via": self.notified_via,
            "classification": self.classification,
            "created_by": str(self.created_by) if self.created_by else None,
            "updated_by": str(self.updated_by) if self.updated_by else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ================================================================
# InsightService クラス
# ================================================================

class InsightService:
    """
    インサイト管理サービス

    soulkun_insights テーブルへのCRUD操作と
    インサイトに関するビジネスロジックを提供

    使用例:
        >>> service = InsightService(conn, org_id)
        >>>
        >>> # インサイト一覧を取得
        >>> insights = await service.get_insights(
        ...     filter=InsightFilter(
        ...         organization_id=org_id,
        ...         statuses=[InsightStatus.NEW, InsightStatus.ACKNOWLEDGED]
        ...     )
        ... )
        >>>
        >>> # インサイトを確認済みに更新
        >>> await service.acknowledge(insight_id, user_id)

    Attributes:
        conn: データベース接続
        org_id: 組織ID
    """

    def __init__(self, conn: Connection, org_id: UUID) -> None:
        """
        InsightServiceを初期化

        Args:
            conn: データベース接続（SQLAlchemy Connection）
            org_id: 組織ID（UUID）
        """
        self._conn = conn
        self._org_id = org_id

        # ロガーの初期化
        try:
            from lib.logging import get_logger
            self._logger = get_logger("insights.service")
        except ImportError:
            import logging
            self._logger = logging.getLogger("insights.service")

    # ================================================================
    # プロパティ
    # ================================================================

    @property
    def conn(self) -> Connection:
        """データベース接続を取得"""
        return self._conn

    @property
    def org_id(self) -> UUID:
        """組織IDを取得"""
        return self._org_id

    # ================================================================
    # 監査ログ（鉄則3: confidential以上の操作を記録）
    # ================================================================

    def _log_audit(
        self,
        action: str,
        resource_type: str,
        resource_id: Optional[UUID],
        classification: Classification,
        user_id: Optional[UUID] = None,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        """
        監査ログを記録（SQLAlchemy Connection対応版）

        鉄則3に基づき、confidential以上の操作を audit_logs に記録します。
        記録に失敗しても本処理は継続します（non-blocking）。

        Args:
            action: アクション（create, update, read, delete等）
            resource_type: リソースタイプ（soulkun_insight等）
            resource_id: リソースID
            classification: 機密区分
            user_id: 実行ユーザーID
            details: 詳細情報
        """
        try:
            self._conn.execute(text("""
                INSERT INTO audit_logs (
                    organization_id,
                    user_id,
                    action,
                    resource_type,
                    resource_id,
                    classification,
                    details,
                    created_at
                ) VALUES (
                    :organization_id,
                    :user_id,
                    :action,
                    :resource_type,
                    :resource_id,
                    :classification,
                    :details,
                    CURRENT_TIMESTAMP
                )
            """), {
                "organization_id": str(self._org_id),
                "user_id": str(user_id) if user_id else None,
                "action": action,
                "resource_type": resource_type,
                "resource_id": str(resource_id) if resource_id else None,
                "classification": classification.value,
                "details": json.dumps(details) if details else None,
            })

            self._logger.info(
                "Audit log recorded",
                extra={
                    "organization_id": str(self._org_id),
                    "action": action,
                    "resource_type": resource_type,
                    "resource_id": str(resource_id) if resource_id else None,
                }
            )
        except Exception as e:
            # 監査ログの記録失敗は本処理を止めない（non-blocking）
            self._logger.warning(
                "Failed to record audit log (non-blocking)",
                extra={
                    "organization_id": str(self._org_id),
                    "action": action,
                    "resource_type": resource_type,
                    "error": str(e),
                }
            )

    # ================================================================
    # CRUD操作
    # ================================================================

    async def create_insight(
        self,
        insight_type: InsightType,
        source_type: SourceType,
        importance: Importance,
        title: str,
        description: str,
        source_id: Optional[UUID] = None,
        department_id: Optional[UUID] = None,
        recommended_action: Optional[str] = None,
        evidence: Optional[dict[str, Any]] = None,
        classification: Classification = Classification.INTERNAL,
        created_by: Optional[UUID] = None,
    ) -> UUID:
        """
        新しいインサイトを作成

        Args:
            insight_type: インサイトタイプ
            source_type: ソースタイプ
            importance: 重要度
            title: タイトル（200文字以内）
            description: 説明
            source_id: ソースID（オプション）
            department_id: 部署ID（オプション）
            recommended_action: 推奨アクション（オプション）
            evidence: 根拠データ（オプション）
            classification: 機密区分（デフォルト: INTERNAL）
            created_by: 作成者ID（オプション）

        Returns:
            UUID: 作成されたインサイトのID

        Raises:
            InsightCreateError: 作成に失敗した場合
            ValidationError: バリデーションエラー
        """
        # バリデーション
        if not title or len(title) > 200:
            raise ValidationError(
                message="Title must be between 1 and 200 characters",
                details={"field": "title", "length": len(title) if title else 0}
            )

        if not description:
            raise ValidationError(
                message="Description is required",
                details={"field": "description"}
            )

        self._logger.info(
            "Creating insight",
            extra={
                "organization_id": str(self._org_id),
                "insight_type": insight_type.value,
                "importance": importance.value,
            }
        )

        try:
            result = self._conn.execute(text("""
                INSERT INTO soulkun_insights (
                    organization_id,
                    department_id,
                    insight_type,
                    source_type,
                    source_id,
                    importance,
                    title,
                    description,
                    recommended_action,
                    evidence,
                    status,
                    classification,
                    created_by,
                    created_at,
                    updated_at
                ) VALUES (
                    :organization_id,
                    :department_id,
                    :insight_type,
                    :source_type,
                    :source_id,
                    :importance,
                    :title,
                    :description,
                    :recommended_action,
                    :evidence,
                    :status,
                    :classification,
                    :created_by,
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP
                )
                RETURNING id
            """), {
                "organization_id": str(self._org_id),
                "department_id": str(department_id) if department_id else None,
                "insight_type": insight_type.value,
                "source_type": source_type.value,
                "source_id": str(source_id) if source_id else None,
                "importance": importance.value,
                "title": title[:200],
                "description": description,
                "recommended_action": recommended_action,
                "evidence": json.dumps(evidence or {}),
                "status": InsightStatus.NEW.value,
                "classification": classification.value,
                "created_by": str(created_by) if created_by else None,
            })

            row = result.fetchone()
            if row is None:
                raise InsightCreateError(
                    message="Failed to get inserted insight ID",
                    details={"insight_type": insight_type.value}
                )

            insight_id = UUID(str(row[0]))

            self._logger.info(
                "Insight created successfully",
                extra={
                    "organization_id": str(self._org_id),
                    "insight_id": str(insight_id),
                }
            )

            # 鉄則3: confidential以上の操作は監査ログ記録
            if _should_audit(classification):
                self._log_audit(
                    action="create",
                    resource_type="soulkun_insight",
                    resource_id=insight_id,
                    classification=classification,
                    user_id=created_by,
                    details={
                        "insight_type": insight_type.value,
                        "importance": importance.value,
                    }
                )

            return insight_id

        except (InsightCreateError, ValidationError):
            raise
        except Exception as e:
            self._logger.error(
                "Failed to create insight",
                extra={
                    "organization_id": str(self._org_id),
                    "error": str(e),
                }
            )
            raise InsightCreateError(
                message="Failed to create insight",
                details={"insight_type": insight_type.value},
                original_exception=e
            )

    async def get_insight(self, insight_id: UUID) -> Optional[InsightRecord]:
        """
        インサイトを取得

        Args:
            insight_id: インサイトID

        Returns:
            InsightRecord: インサイトレコード（存在しない場合はNone）

        Raises:
            DatabaseError: データベースエラー
        """
        try:
            result = self._conn.execute(text("""
                SELECT
                    id,
                    organization_id,
                    department_id,
                    insight_type,
                    source_type,
                    source_id,
                    importance,
                    title,
                    description,
                    recommended_action,
                    evidence,
                    status,
                    acknowledged_at,
                    acknowledged_by,
                    addressed_at,
                    addressed_by,
                    addressed_action,
                    dismissed_reason,
                    notified_at,
                    notified_to,
                    notified_via,
                    classification,
                    created_by,
                    updated_by,
                    created_at,
                    updated_at
                FROM soulkun_insights
                WHERE organization_id = :org_id
                  AND id = :insight_id
            """), {
                "org_id": str(self._org_id),
                "insight_id": str(insight_id),
            })

            row = result.fetchone()
            if row is None:
                return None

            record = self._row_to_record(row)

            # 鉄則3: confidential以上の閲覧操作は監査ログ記録（Codex MEDIUM指摘対応）
            if record and _should_audit(record.classification):
                self._log_audit(
                    action="read",
                    resource_type="soulkun_insight",
                    resource_id=insight_id,
                    classification=record.classification,
                    user_id=None,  # 閲覧者情報が引数にないため
                    details={"insight_type": record.insight_type}
                )

            return record

        except Exception as e:
            raise wrap_database_error(e, "get insight")

    async def get_insights(
        self,
        filter: InsightFilter,
        limit: int = 100,
        offset: int = 0,
        order_by: str = "created_at",
        order_desc: bool = True,
    ) -> list[InsightRecord]:
        """
        インサイト一覧を取得

        Args:
            filter: フィルタ条件
            limit: 取得件数（デフォルト: 100、最大: 1000）
            offset: オフセット（デフォルト: 0）
            order_by: ソートカラム（デフォルト: created_at）
            order_desc: 降順ソート（デフォルト: True）

        Returns:
            list[InsightRecord]: インサイトレコードのリスト

        Raises:
            DatabaseError: データベースエラー
            ValidationError: バリデーションエラー
        """
        # 鉄則5: 1000件超えAPIにページネーションを実装
        if limit > 1000:
            limit = 1000

        # ソートカラムのホワイトリスト（SQLインジェクション対策）
        allowed_order_columns = {
            "created_at", "updated_at", "importance", "status",
            "insight_type", "title", "notified_at"
        }
        if order_by not in allowed_order_columns:
            order_by = "created_at"

        # フィルタ条件の組み立て
        where_clauses = ["organization_id = :org_id"]
        params: dict[str, Any] = {"org_id": str(self._org_id)}

        if filter.department_id:
            where_clauses.append("department_id = :department_id")
            params["department_id"] = str(filter.department_id)

        if filter.insight_types:
            where_clauses.append("insight_type = ANY(:insight_types)")
            params["insight_types"] = [t.value for t in filter.insight_types]

        if filter.source_types:
            where_clauses.append("source_type = ANY(:source_types)")
            params["source_types"] = [t.value for t in filter.source_types]

        if filter.statuses:
            where_clauses.append("status = ANY(:statuses)")
            params["statuses"] = [s.value for s in filter.statuses]

        if filter.importances:
            where_clauses.append("importance = ANY(:importances)")
            params["importances"] = [i.value for i in filter.importances]

        if filter.from_date:
            where_clauses.append("created_at >= :from_date")
            params["from_date"] = filter.from_date

        if filter.to_date:
            where_clauses.append("created_at <= :to_date")
            params["to_date"] = filter.to_date

        if filter.notified is not None:
            if filter.notified:
                where_clauses.append("notified_at IS NOT NULL")
            else:
                where_clauses.append("notified_at IS NULL")

        where_sql = " AND ".join(where_clauses)
        order_direction = "DESC" if order_desc else "ASC"

        # 重要度でソートする場合の特別処理
        if order_by == "importance":
            order_sql = f"""
                CASE importance
                    WHEN 'critical' THEN 1
                    WHEN 'high' THEN 2
                    WHEN 'medium' THEN 3
                    ELSE 4
                END {order_direction}
            """
        else:
            order_sql = f"{order_by} {order_direction}"

        params["limit"] = limit
        params["offset"] = offset

        try:
            result = self._conn.execute(text(f"""
                SELECT
                    id,
                    organization_id,
                    department_id,
                    insight_type,
                    source_type,
                    source_id,
                    importance,
                    title,
                    description,
                    recommended_action,
                    evidence,
                    status,
                    acknowledged_at,
                    acknowledged_by,
                    addressed_at,
                    addressed_by,
                    addressed_action,
                    dismissed_reason,
                    notified_at,
                    notified_to,
                    notified_via,
                    classification,
                    created_by,
                    updated_by,
                    created_at,
                    updated_at
                FROM soulkun_insights
                WHERE {where_sql}
                ORDER BY {order_sql}
                LIMIT :limit OFFSET :offset
            """), params)

            records = [self._row_to_record(row) for row in result.fetchall()]

            # 鉄則3: confidential以上の閲覧操作は監査ログ記録（Codex MEDIUM指摘対応）
            confidential_records = [
                r for r in records
                if r and _should_audit(r.classification)
            ]
            if confidential_records:
                self._log_audit(
                    action="read_list",
                    resource_type="soulkun_insight",
                    resource_id=None,
                    classification=Classification.CONFIDENTIAL,
                    user_id=None,
                    details={
                        "count": len(confidential_records),
                        "insight_ids": [str(r.id) for r in confidential_records[:10]],
                    }
                )

            return records

        except Exception as e:
            raise wrap_database_error(e, "get insights")

    async def count_insights(self, filter: InsightFilter) -> int:
        """
        インサイト件数を取得

        Args:
            filter: フィルタ条件

        Returns:
            int: インサイト件数

        Raises:
            DatabaseError: データベースエラー
        """
        # フィルタ条件の組み立て
        where_clauses = ["organization_id = :org_id"]
        params: dict[str, Any] = {"org_id": str(self._org_id)}

        if filter.department_id:
            where_clauses.append("department_id = :department_id")
            params["department_id"] = str(filter.department_id)

        if filter.insight_types:
            where_clauses.append("insight_type = ANY(:insight_types)")
            params["insight_types"] = [t.value for t in filter.insight_types]

        if filter.source_types:
            where_clauses.append("source_type = ANY(:source_types)")
            params["source_types"] = [t.value for t in filter.source_types]

        if filter.statuses:
            where_clauses.append("status = ANY(:statuses)")
            params["statuses"] = [s.value for s in filter.statuses]

        if filter.importances:
            where_clauses.append("importance = ANY(:importances)")
            params["importances"] = [i.value for i in filter.importances]

        if filter.from_date:
            where_clauses.append("created_at >= :from_date")
            params["from_date"] = filter.from_date

        if filter.to_date:
            where_clauses.append("created_at <= :to_date")
            params["to_date"] = filter.to_date

        if filter.notified is not None:
            if filter.notified:
                where_clauses.append("notified_at IS NOT NULL")
            else:
                where_clauses.append("notified_at IS NULL")

        where_sql = " AND ".join(where_clauses)

        try:
            result = self._conn.execute(text(f"""
                SELECT COUNT(*) FROM soulkun_insights
                WHERE {where_sql}
            """), params)

            row = result.fetchone()
            return row[0] if row else 0

        except Exception as e:
            raise wrap_database_error(e, "count insights")

    # ================================================================
    # ステータス更新操作
    # ================================================================

    async def acknowledge(
        self,
        insight_id: UUID,
        user_id: UUID,
    ) -> bool:
        """
        インサイトを確認済みに更新

        Args:
            insight_id: インサイトID
            user_id: 確認者のユーザーID

        Returns:
            bool: 更新成功したかどうか

        Raises:
            DatabaseError: データベースエラー
        """
        self._logger.info(
            "Acknowledging insight",
            extra={
                "organization_id": str(self._org_id),
                "insight_id": str(insight_id),
                "user_id": str(user_id),
            }
        )

        try:
            # 鉄則3: 監査ログ用に機密区分を事前取得
            classification_result = self._conn.execute(text("""
                SELECT classification
                FROM soulkun_insights
                WHERE organization_id = :org_id AND id = :insight_id
            """), {
                "org_id": str(self._org_id),
                "insight_id": str(insight_id),
            })
            classification_row = classification_result.fetchone()
            classification = Classification(classification_row[0]) if classification_row else None

            result = self._conn.execute(text("""
                UPDATE soulkun_insights
                SET
                    status = :status,
                    acknowledged_at = CURRENT_TIMESTAMP,
                    acknowledged_by = :user_id,
                    updated_by = :user_id,
                    updated_at = CURRENT_TIMESTAMP
                WHERE organization_id = :org_id
                  AND id = :insight_id
                  AND status = :current_status
            """), {
                "org_id": str(self._org_id),
                "insight_id": str(insight_id),
                "user_id": str(user_id),
                "status": InsightStatus.ACKNOWLEDGED.value,
                "current_status": InsightStatus.NEW.value,
            })

            updated = result.rowcount > 0

            # 鉄則3: confidential以上の操作は監査ログ記録
            if updated and classification and _should_audit(classification):
                self._log_audit(
                    action="acknowledge",
                    resource_type="soulkun_insight",
                    resource_id=insight_id,
                    classification=classification,
                    user_id=user_id,
                    details={}
                )

            return updated

        except Exception as e:
            raise wrap_database_error(e, "acknowledge insight")

    async def address(
        self,
        insight_id: UUID,
        user_id: UUID,
        action: str,
    ) -> bool:
        """
        インサイトを対応完了に更新

        Args:
            insight_id: インサイトID
            user_id: 対応者のユーザーID
            action: 対応内容

        Returns:
            bool: 更新成功したかどうか

        Raises:
            DatabaseError: データベースエラー
            ValidationError: バリデーションエラー
        """
        if not action:
            raise ValidationError(
                message="Action is required",
                details={"field": "action"}
            )

        self._logger.info(
            "Addressing insight",
            extra={
                "organization_id": str(self._org_id),
                "insight_id": str(insight_id),
                "user_id": str(user_id),
            }
        )

        try:
            # 鉄則3: 監査ログ用に機密区分を事前取得
            classification_result = self._conn.execute(text("""
                SELECT classification
                FROM soulkun_insights
                WHERE organization_id = :org_id AND id = :insight_id
            """), {
                "org_id": str(self._org_id),
                "insight_id": str(insight_id),
            })
            classification_row = classification_result.fetchone()
            classification = Classification(classification_row[0]) if classification_row else None

            result = self._conn.execute(text("""
                UPDATE soulkun_insights
                SET
                    status = :status,
                    addressed_at = CURRENT_TIMESTAMP,
                    addressed_by = :user_id,
                    addressed_action = :action,
                    updated_by = :user_id,
                    updated_at = CURRENT_TIMESTAMP
                WHERE organization_id = :org_id
                  AND id = :insight_id
                  AND status IN (:status_new, :status_acknowledged)
            """), {
                "org_id": str(self._org_id),
                "insight_id": str(insight_id),
                "user_id": str(user_id),
                "action": action,
                "status": InsightStatus.ADDRESSED.value,
                "status_new": InsightStatus.NEW.value,
                "status_acknowledged": InsightStatus.ACKNOWLEDGED.value,
            })

            updated = result.rowcount > 0

            # 鉄則3: confidential以上の操作は監査ログ記録
            if updated and classification and _should_audit(classification):
                self._log_audit(
                    action="address",
                    resource_type="soulkun_insight",
                    resource_id=insight_id,
                    classification=classification,
                    user_id=user_id,
                    details={"addressed_action": action}
                )

            return updated

        except Exception as e:
            raise wrap_database_error(e, "address insight")

    async def dismiss(
        self,
        insight_id: UUID,
        user_id: UUID,
        reason: str,
    ) -> bool:
        """
        インサイトを無視に更新

        Args:
            insight_id: インサイトID
            user_id: 無視したユーザーID
            reason: 無視理由

        Returns:
            bool: 更新成功したかどうか

        Raises:
            DatabaseError: データベースエラー
            ValidationError: バリデーションエラー
        """
        if not reason:
            raise ValidationError(
                message="Reason is required",
                details={"field": "reason"}
            )

        self._logger.info(
            "Dismissing insight",
            extra={
                "organization_id": str(self._org_id),
                "insight_id": str(insight_id),
                "user_id": str(user_id),
            }
        )

        try:
            # 鉄則3: 監査ログ用に機密区分を事前取得
            classification_result = self._conn.execute(text("""
                SELECT classification
                FROM soulkun_insights
                WHERE organization_id = :org_id AND id = :insight_id
            """), {
                "org_id": str(self._org_id),
                "insight_id": str(insight_id),
            })
            classification_row = classification_result.fetchone()
            classification = Classification(classification_row[0]) if classification_row else None

            result = self._conn.execute(text("""
                UPDATE soulkun_insights
                SET
                    status = :status,
                    dismissed_reason = :reason,
                    updated_by = :user_id,
                    updated_at = CURRENT_TIMESTAMP
                WHERE organization_id = :org_id
                  AND id = :insight_id
                  AND status IN (:status_new, :status_acknowledged)
            """), {
                "org_id": str(self._org_id),
                "insight_id": str(insight_id),
                "user_id": str(user_id),
                "reason": reason,
                "status": InsightStatus.DISMISSED.value,
                "status_new": InsightStatus.NEW.value,
                "status_acknowledged": InsightStatus.ACKNOWLEDGED.value,
            })

            updated = result.rowcount > 0

            # 鉄則3: confidential以上の操作は監査ログ記録
            if updated and classification and _should_audit(classification):
                self._log_audit(
                    action="dismiss",
                    resource_type="soulkun_insight",
                    resource_id=insight_id,
                    classification=classification,
                    user_id=user_id,
                    details={"dismissed_reason": reason}
                )

            return updated

        except Exception as e:
            raise wrap_database_error(e, "dismiss insight")

    # ================================================================
    # 通知関連
    # ================================================================

    async def mark_as_notified(
        self,
        insight_id: UUID,
        notified_to: list[UUID],
        notified_via: str,
    ) -> bool:
        """
        インサイトを通知済みとしてマーク

        Args:
            insight_id: インサイトID
            notified_to: 通知先ユーザーIDリスト
            notified_via: 通知方法（chatwork, email等）

        Returns:
            bool: 更新成功したかどうか

        Raises:
            DatabaseError: データベースエラー
        """
        self._logger.info(
            "Marking insight as notified",
            extra={
                "organization_id": str(self._org_id),
                "insight_id": str(insight_id),
                "notified_via": notified_via,
            }
        )

        try:
            result = self._conn.execute(text("""
                UPDATE soulkun_insights
                SET
                    notified_at = CURRENT_TIMESTAMP,
                    notified_to = :notified_to,
                    notified_via = :notified_via,
                    updated_at = CURRENT_TIMESTAMP
                WHERE organization_id = :org_id
                  AND id = :insight_id
            """), {
                "org_id": str(self._org_id),
                "insight_id": str(insight_id),
                "notified_to": [str(uid) for uid in notified_to],
                "notified_via": notified_via,
            })

            return result.rowcount > 0

        except Exception as e:
            raise wrap_database_error(e, "mark insight as notified")

    async def get_unnotified_high_priority_insights(
        self,
        since: Optional[datetime] = None,
    ) -> list[InsightRecord]:
        """
        未通知の高優先度インサイトを取得

        Critical/High の重要度で、まだ通知されていないインサイトを取得

        Args:
            since: この日時以降に作成されたインサイトのみ取得（オプション）

        Returns:
            list[InsightRecord]: インサイトレコードのリスト

        Raises:
            DatabaseError: データベースエラー
        """
        try:
            params: dict[str, Any] = {
                "org_id": str(self._org_id),
                "importances": [Importance.CRITICAL.value, Importance.HIGH.value],
            }

            since_clause = ""
            if since:
                since_clause = "AND created_at >= :since"
                params["since"] = since

            result = self._conn.execute(text(f"""
                SELECT
                    id,
                    organization_id,
                    department_id,
                    insight_type,
                    source_type,
                    source_id,
                    importance,
                    title,
                    description,
                    recommended_action,
                    evidence,
                    status,
                    acknowledged_at,
                    acknowledged_by,
                    addressed_at,
                    addressed_by,
                    addressed_action,
                    dismissed_reason,
                    notified_at,
                    notified_to,
                    notified_via,
                    classification,
                    created_by,
                    updated_by,
                    created_at,
                    updated_at
                FROM soulkun_insights
                WHERE organization_id = :org_id
                  AND importance = ANY(:importances)
                  AND notified_at IS NULL
                  AND status IN ('new', 'acknowledged')
                  {since_clause}
                ORDER BY
                    CASE importance
                        WHEN 'critical' THEN 1
                        WHEN 'high' THEN 2
                        ELSE 3
                    END,
                    created_at ASC
            """), params)

            return [self._row_to_record(row) for row in result.fetchall()]

        except Exception as e:
            raise wrap_database_error(e, "get unnotified high priority insights")

    # ================================================================
    # 統計・サマリー
    # ================================================================

    async def get_summary(
        self,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
    ) -> InsightSummary:
        """
        インサイトのサマリーを取得

        Args:
            from_date: 集計開始日（オプション）
            to_date: 集計終了日（オプション）

        Returns:
            InsightSummary: サマリー情報

        Raises:
            DatabaseError: データベースエラー
        """
        try:
            params: dict[str, Any] = {"org_id": str(self._org_id)}

            date_clause = ""
            if from_date:
                date_clause += " AND created_at >= :from_date"
                params["from_date"] = from_date
            if to_date:
                date_clause += " AND created_at <= :to_date"
                params["to_date"] = to_date

            # 総件数
            total_result = self._conn.execute(text(f"""
                SELECT COUNT(*) FROM soulkun_insights
                WHERE organization_id = :org_id {date_clause}
            """), params)
            total = total_result.fetchone()[0]

            # ステータス別
            status_result = self._conn.execute(text(f"""
                SELECT status, COUNT(*) FROM soulkun_insights
                WHERE organization_id = :org_id {date_clause}
                GROUP BY status
            """), params)
            by_status = {row[0]: row[1] for row in status_result.fetchall()}

            # 重要度別
            importance_result = self._conn.execute(text(f"""
                SELECT importance, COUNT(*) FROM soulkun_insights
                WHERE organization_id = :org_id {date_clause}
                GROUP BY importance
            """), params)
            by_importance = {row[0]: row[1] for row in importance_result.fetchall()}

            # タイプ別
            type_result = self._conn.execute(text(f"""
                SELECT insight_type, COUNT(*) FROM soulkun_insights
                WHERE organization_id = :org_id {date_clause}
                GROUP BY insight_type
            """), params)
            by_type = {row[0]: row[1] for row in type_result.fetchall()}

            return InsightSummary(
                total=total,
                by_status=by_status,
                by_importance=by_importance,
                by_type=by_type,
            )

        except Exception as e:
            raise wrap_database_error(e, "get insight summary")

    async def get_pending_insights_for_report(
        self,
        from_date: datetime,
        to_date: datetime,
    ) -> list[InsightRecord]:
        """
        週次レポート用のインサイトを取得

        指定期間内に作成された未対応のインサイトを取得

        Args:
            from_date: 集計開始日
            to_date: 集計終了日

        Returns:
            list[InsightRecord]: インサイトレコードのリスト

        Raises:
            DatabaseError: データベースエラー
        """
        try:
            result = self._conn.execute(text("""
                SELECT
                    id,
                    organization_id,
                    department_id,
                    insight_type,
                    source_type,
                    source_id,
                    importance,
                    title,
                    description,
                    recommended_action,
                    evidence,
                    status,
                    acknowledged_at,
                    acknowledged_by,
                    addressed_at,
                    addressed_by,
                    addressed_action,
                    dismissed_reason,
                    notified_at,
                    notified_to,
                    notified_via,
                    classification,
                    created_by,
                    updated_by,
                    created_at,
                    updated_at
                FROM soulkun_insights
                WHERE organization_id = :org_id
                  AND created_at >= :from_date
                  AND created_at <= :to_date
                  AND status IN ('new', 'acknowledged')
                ORDER BY
                    CASE importance
                        WHEN 'critical' THEN 1
                        WHEN 'high' THEN 2
                        WHEN 'medium' THEN 3
                        ELSE 4
                    END,
                    created_at DESC
            """), {
                "org_id": str(self._org_id),
                "from_date": from_date,
                "to_date": to_date,
            })

            return [self._row_to_record(row) for row in result.fetchall()]

        except Exception as e:
            raise wrap_database_error(e, "get pending insights for report")

    # ================================================================
    # 重複チェック
    # ================================================================

    async def insight_exists_for_source(
        self,
        source_type: SourceType,
        source_id: UUID,
    ) -> bool:
        """
        指定したソースに対するインサイトが既に存在するか確認

        Args:
            source_type: ソースタイプ
            source_id: ソースID

        Returns:
            bool: インサイトが存在する場合True

        Raises:
            DatabaseError: データベースエラー
        """
        try:
            result = self._conn.execute(text("""
                SELECT 1 FROM soulkun_insights
                WHERE organization_id = :org_id
                  AND source_type = :source_type
                  AND source_id = :source_id
                LIMIT 1
            """), {
                "org_id": str(self._org_id),
                "source_type": source_type.value,
                "source_id": str(source_id),
            })

            return result.fetchone() is not None

        except Exception as e:
            raise wrap_database_error(e, "check insight existence")

    # ================================================================
    # ヘルパーメソッド
    # ================================================================

    def _row_to_record(self, row: Any) -> InsightRecord:
        """
        データベース行をInsightRecordに変換

        Args:
            row: データベースの行データ

        Returns:
            InsightRecord: インサイトレコード
        """
        return InsightRecord(
            id=UUID(str(row[0])),
            organization_id=UUID(str(row[1])),
            department_id=UUID(str(row[2])) if row[2] else None,
            insight_type=row[3],
            source_type=row[4],
            source_id=UUID(str(row[5])) if row[5] else None,
            importance=row[6],
            title=row[7],
            description=row[8],
            recommended_action=row[9],
            evidence=row[10] if row[10] else {},
            status=row[11],
            acknowledged_at=row[12],
            acknowledged_by=UUID(str(row[13])) if row[13] else None,
            addressed_at=row[14],
            addressed_by=UUID(str(row[15])) if row[15] else None,
            addressed_action=row[16],
            dismissed_reason=row[17],
            notified_at=row[18],
            notified_to=[UUID(str(uid)) for uid in (row[19] or [])],
            notified_via=row[20],
            classification=row[21],
            created_by=UUID(str(row[22])) if row[22] else None,
            updated_by=UUID(str(row[23])) if row[23] else None,
            created_at=row[24],
            updated_at=row[25],
        )
