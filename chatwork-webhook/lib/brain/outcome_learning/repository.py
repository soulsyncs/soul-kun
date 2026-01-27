"""
Phase 2F: 結果からの学習 - リポジトリ層

設計書: docs/17_brain_completion_roadmap.md セクション Phase 2F

イベント・パターンデータのDB操作を担当する。
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.engine import Connection

from .constants import (
    TABLE_BRAIN_OUTCOME_EVENTS,
    TABLE_BRAIN_OUTCOME_PATTERNS,
    MAX_EVENTS_PER_QUERY,
    MAX_PATTERNS_PER_QUERY,
    OUTCOME_CHECK_MAX_AGE_HOURS,
    PatternScope,
)
from .models import OutcomeEvent, OutcomePattern, OutcomeStatistics


logger = logging.getLogger(__name__)


class OutcomeRepository:
    """結果学習リポジトリ

    イベント・パターンデータのCRUD操作を提供する。
    """

    def __init__(self, organization_id: str):
        """初期化

        Args:
            organization_id: 組織ID
        """
        self.organization_id = organization_id

    # ========================================================================
    # イベント保存系メソッド
    # ========================================================================

    def save_event(
        self,
        conn: Connection,
        event: OutcomeEvent,
    ) -> str:
        """イベントを保存

        Args:
            conn: DB接続
            event: イベントオブジェクト

        Returns:
            保存されたイベントのID

        Raises:
            ValueError: 保存に失敗した場合
        """
        event_id = event.id or str(uuid4())

        query = text(f"""
            INSERT INTO {TABLE_BRAIN_OUTCOME_EVENTS} (
                id,
                organization_id,
                event_type,
                event_subtype,
                event_timestamp,
                target_account_id,
                target_room_id,
                event_details,
                related_resource_type,
                related_resource_id,
                outcome_detected,
                context_snapshot,
                created_at
            ) VALUES (
                CAST(:id AS uuid),
                CAST(:organization_id AS uuid),
                :event_type,
                :event_subtype,
                :event_timestamp,
                :target_account_id,
                :target_room_id,
                CAST(:event_details AS jsonb),
                :related_resource_type,
                CAST(:related_resource_id AS uuid),
                :outcome_detected,
                CAST(:context_snapshot AS jsonb),
                :created_at
            )
            RETURNING id
        """)

        now = datetime.now()
        result = conn.execute(query, {
            "id": event_id,
            "organization_id": self.organization_id,
            "event_type": event.event_type,
            "event_subtype": event.event_subtype,
            "event_timestamp": event.event_timestamp or now,
            "target_account_id": event.target_account_id,
            "target_room_id": event.target_room_id,
            "event_details": json.dumps(event.event_details, ensure_ascii=False),
            "related_resource_type": event.related_resource_type,
            "related_resource_id": event.related_resource_id,
            "outcome_detected": event.outcome_detected,
            "context_snapshot": (
                json.dumps(event.context_snapshot, ensure_ascii=False)
                if event.context_snapshot else None
            ),
            "created_at": now,
        })

        row = result.fetchone()
        if row is None:
            raise ValueError("イベントの保存に失敗しました")

        return str(row[0])

    def update_outcome(
        self,
        conn: Connection,
        event_id: str,
        outcome_type: str,
        outcome_details: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """イベントの結果を更新

        Args:
            conn: DB接続
            event_id: イベントID
            outcome_type: 結果タイプ
            outcome_details: 結果詳細

        Returns:
            更新成功かどうか
        """
        query = text(f"""
            UPDATE {TABLE_BRAIN_OUTCOME_EVENTS}
            SET
                outcome_detected = true,
                outcome_type = :outcome_type,
                outcome_detected_at = :outcome_detected_at,
                outcome_details = CAST(:outcome_details AS jsonb)
            WHERE id = CAST(:event_id AS uuid)
              AND organization_id = CAST(:organization_id AS uuid)
            RETURNING id
        """)

        result = conn.execute(query, {
            "event_id": event_id,
            "organization_id": self.organization_id,
            "outcome_type": outcome_type,
            "outcome_detected_at": datetime.now(),
            "outcome_details": (
                json.dumps(outcome_details, ensure_ascii=False)
                if outcome_details else None
            ),
        })

        return result.fetchone() is not None

    def mark_learning_extracted(
        self,
        conn: Connection,
        event_id: str,
        pattern_id: Optional[str] = None,
        learning_id: Optional[str] = None,
    ) -> bool:
        """学習抽出済みとしてマーク

        Args:
            conn: DB接続
            event_id: イベントID
            pattern_id: パターンID（抽出された場合）
            learning_id: 学習ID（昇格された場合）

        Returns:
            更新成功かどうか
        """
        query = text(f"""
            UPDATE {TABLE_BRAIN_OUTCOME_EVENTS}
            SET
                learning_extracted = true,
                pattern_id = CAST(:pattern_id AS uuid),
                learning_id = CAST(:learning_id AS uuid)
            WHERE id = CAST(:event_id AS uuid)
              AND organization_id = CAST(:organization_id AS uuid)
            RETURNING id
        """)

        result = conn.execute(query, {
            "event_id": event_id,
            "organization_id": self.organization_id,
            "pattern_id": pattern_id,
            "learning_id": learning_id,
        })

        return result.fetchone() is not None

    # ========================================================================
    # イベント検索系メソッド
    # ========================================================================

    def find_pending_events(
        self,
        conn: Connection,
        max_age_hours: int = OUTCOME_CHECK_MAX_AGE_HOURS,
        limit: int = MAX_EVENTS_PER_QUERY,
    ) -> List[OutcomeEvent]:
        """未処理イベントを検索

        Args:
            conn: DB接続
            max_age_hours: 最大経過時間（時間）
            limit: 最大取得件数

        Returns:
            イベントリスト
        """
        threshold = datetime.now() - timedelta(hours=max_age_hours)

        query = text(f"""
            SELECT *
            FROM {TABLE_BRAIN_OUTCOME_EVENTS}
            WHERE organization_id = CAST(:organization_id AS uuid)
              AND outcome_detected = false
              AND event_timestamp >= :threshold
            ORDER BY event_timestamp ASC
            LIMIT :limit
        """)

        result = conn.execute(query, {
            "organization_id": self.organization_id,
            "threshold": threshold,
            "limit": limit,
        })

        return [OutcomeEvent.from_db_row(dict(row._mapping)) for row in result]

    def find_events_by_target(
        self,
        conn: Connection,
        target_account_id: str,
        event_type: Optional[str] = None,
        days: int = 30,
        limit: int = MAX_EVENTS_PER_QUERY,
    ) -> List[OutcomeEvent]:
        """ターゲット別イベントを検索

        Args:
            conn: DB接続
            target_account_id: 対象ユーザーID
            event_type: イベントタイプ（オプション）
            days: 検索期間（日数）
            limit: 最大取得件数

        Returns:
            イベントリスト
        """
        threshold = datetime.now() - timedelta(days=days)

        query_parts = [
            f"SELECT * FROM {TABLE_BRAIN_OUTCOME_EVENTS}",
            "WHERE organization_id = CAST(:organization_id AS uuid)",
            "  AND target_account_id = :target_account_id",
            "  AND event_timestamp >= :threshold",
        ]
        params: Dict[str, Any] = {
            "organization_id": self.organization_id,
            "target_account_id": target_account_id,
            "threshold": threshold,
            "limit": limit,
        }

        if event_type:
            query_parts.append("  AND event_type = :event_type")
            params["event_type"] = event_type

        query_parts.append("ORDER BY event_timestamp DESC")
        query_parts.append("LIMIT :limit")

        query = text("\n".join(query_parts))
        result = conn.execute(query, params)

        return [OutcomeEvent.from_db_row(dict(row._mapping)) for row in result]

    def find_event_by_id(
        self,
        conn: Connection,
        event_id: str,
    ) -> Optional[OutcomeEvent]:
        """IDでイベントを検索

        Args:
            conn: DB接続
            event_id: イベントID

        Returns:
            イベント（見つからない場合はNone）
        """
        query = text(f"""
            SELECT *
            FROM {TABLE_BRAIN_OUTCOME_EVENTS}
            WHERE id = CAST(:event_id AS uuid)
              AND organization_id = CAST(:organization_id AS uuid)
        """)

        result = conn.execute(query, {
            "event_id": event_id,
            "organization_id": self.organization_id,
        })

        row = result.fetchone()
        if row is None:
            return None

        return OutcomeEvent.from_db_row(dict(row._mapping))

    # ========================================================================
    # パターン保存系メソッド
    # ========================================================================

    def save_pattern(
        self,
        conn: Connection,
        pattern: OutcomePattern,
    ) -> str:
        """パターンを保存

        Args:
            conn: DB接続
            pattern: パターンオブジェクト

        Returns:
            保存されたパターンのID

        Raises:
            ValueError: 保存に失敗した場合
        """
        pattern_id = pattern.id or str(uuid4())

        query = text(f"""
            INSERT INTO {TABLE_BRAIN_OUTCOME_PATTERNS} (
                id,
                organization_id,
                pattern_type,
                pattern_category,
                scope,
                scope_target_id,
                pattern_content,
                sample_count,
                success_count,
                failure_count,
                success_rate,
                confidence_score,
                is_active,
                created_at,
                updated_at
            ) VALUES (
                CAST(:id AS uuid),
                CAST(:organization_id AS uuid),
                :pattern_type,
                :pattern_category,
                :scope,
                :scope_target_id,
                CAST(:pattern_content AS jsonb),
                :sample_count,
                :success_count,
                :failure_count,
                :success_rate,
                :confidence_score,
                :is_active,
                :created_at,
                :updated_at
            )
            RETURNING id
        """)

        now = datetime.now()
        result = conn.execute(query, {
            "id": pattern_id,
            "organization_id": self.organization_id,
            "pattern_type": pattern.pattern_type,
            "pattern_category": pattern.pattern_category,
            "scope": pattern.scope,
            "scope_target_id": pattern.scope_target_id,
            "pattern_content": json.dumps(pattern.pattern_content, ensure_ascii=False),
            "sample_count": pattern.sample_count,
            "success_count": pattern.success_count,
            "failure_count": pattern.failure_count,
            "success_rate": pattern.success_rate,
            "confidence_score": pattern.confidence_score,
            "is_active": pattern.is_active,
            "created_at": now,
            "updated_at": now,
        })

        row = result.fetchone()
        if row is None:
            raise ValueError("パターンの保存に失敗しました")

        return str(row[0])

    def update_pattern_stats(
        self,
        conn: Connection,
        pattern_id: str,
        sample_count: int,
        success_count: int,
        failure_count: int,
        success_rate: float,
        confidence_score: float,
    ) -> bool:
        """パターンの統計を更新

        Args:
            conn: DB接続
            pattern_id: パターンID
            sample_count: サンプル数
            success_count: 成功数
            failure_count: 失敗数
            success_rate: 成功率
            confidence_score: 確信度

        Returns:
            更新成功かどうか
        """
        query = text(f"""
            UPDATE {TABLE_BRAIN_OUTCOME_PATTERNS}
            SET
                sample_count = :sample_count,
                success_count = :success_count,
                failure_count = :failure_count,
                success_rate = :success_rate,
                confidence_score = :confidence_score,
                updated_at = :updated_at
            WHERE id = CAST(:pattern_id AS uuid)
              AND organization_id = CAST(:organization_id AS uuid)
            RETURNING id
        """)

        result = conn.execute(query, {
            "pattern_id": pattern_id,
            "organization_id": self.organization_id,
            "sample_count": sample_count,
            "success_count": success_count,
            "failure_count": failure_count,
            "success_rate": success_rate,
            "confidence_score": confidence_score,
            "updated_at": datetime.now(),
        })

        return result.fetchone() is not None

    def mark_pattern_promoted(
        self,
        conn: Connection,
        pattern_id: str,
        learning_id: str,
    ) -> bool:
        """パターンを学習昇格済みとしてマーク

        Args:
            conn: DB接続
            pattern_id: パターンID
            learning_id: 昇格先の学習ID

        Returns:
            更新成功かどうか
        """
        query = text(f"""
            UPDATE {TABLE_BRAIN_OUTCOME_PATTERNS}
            SET
                promoted_to_learning_id = CAST(:learning_id AS uuid),
                promoted_at = :promoted_at,
                updated_at = :updated_at
            WHERE id = CAST(:pattern_id AS uuid)
              AND organization_id = CAST(:organization_id AS uuid)
            RETURNING id
        """)

        now = datetime.now()
        result = conn.execute(query, {
            "pattern_id": pattern_id,
            "organization_id": self.organization_id,
            "learning_id": learning_id,
            "promoted_at": now,
            "updated_at": now,
        })

        return result.fetchone() is not None

    # ========================================================================
    # パターン検索系メソッド
    # ========================================================================

    def find_patterns(
        self,
        conn: Connection,
        pattern_type: Optional[str] = None,
        scope: Optional[str] = None,
        scope_target_id: Optional[str] = None,
        active_only: bool = True,
        limit: int = MAX_PATTERNS_PER_QUERY,
    ) -> List[OutcomePattern]:
        """パターンを検索

        Args:
            conn: DB接続
            pattern_type: パターンタイプ（オプション）
            scope: スコープ（オプション）
            scope_target_id: スコープ対象ID（オプション）
            active_only: アクティブのみ
            limit: 最大取得件数

        Returns:
            パターンリスト
        """
        query_parts = [
            f"SELECT * FROM {TABLE_BRAIN_OUTCOME_PATTERNS}",
            "WHERE organization_id = CAST(:organization_id AS uuid)",
        ]
        params: Dict[str, Any] = {
            "organization_id": self.organization_id,
            "limit": limit,
        }

        if active_only:
            query_parts.append("  AND is_active = true")

        if pattern_type:
            query_parts.append("  AND pattern_type = :pattern_type")
            params["pattern_type"] = pattern_type

        if scope:
            query_parts.append("  AND scope = :scope")
            params["scope"] = scope

        if scope_target_id:
            query_parts.append("  AND scope_target_id = :scope_target_id")
            params["scope_target_id"] = scope_target_id

        query_parts.append("ORDER BY confidence_score DESC NULLS LAST")
        query_parts.append("LIMIT :limit")

        query = text("\n".join(query_parts))
        result = conn.execute(query, params)

        return [OutcomePattern.from_db_row(dict(row._mapping)) for row in result]

    def find_applicable_patterns(
        self,
        conn: Connection,
        target_account_id: str,
        pattern_type: Optional[str] = None,
    ) -> List[OutcomePattern]:
        """適用可能なパターンを検索

        グローバルパターンとユーザー固有パターンを取得。

        Args:
            conn: DB接続
            target_account_id: 対象ユーザーID
            pattern_type: パターンタイプ（オプション）

        Returns:
            パターンリスト
        """
        query_parts = [
            f"SELECT * FROM {TABLE_BRAIN_OUTCOME_PATTERNS}",
            "WHERE organization_id = CAST(:organization_id AS uuid)",
            "  AND is_active = true",
            "  AND (",
            "    scope = :scope_global",
            "    OR (scope = :scope_user AND scope_target_id = :target_account_id)",
            "  )",
        ]
        params: Dict[str, Any] = {
            "organization_id": self.organization_id,
            "scope_global": PatternScope.GLOBAL.value,
            "scope_user": PatternScope.USER.value,
            "target_account_id": target_account_id,
        }

        if pattern_type:
            query_parts.append("  AND pattern_type = :pattern_type")
            params["pattern_type"] = pattern_type

        query_parts.append("ORDER BY confidence_score DESC NULLS LAST")

        query = text("\n".join(query_parts))
        result = conn.execute(query, params)

        return [OutcomePattern.from_db_row(dict(row._mapping)) for row in result]

    def find_promotable_patterns(
        self,
        conn: Connection,
        min_confidence: float,
        min_sample_count: int,
    ) -> List[OutcomePattern]:
        """昇格可能なパターンを検索

        Args:
            conn: DB接続
            min_confidence: 最小確信度
            min_sample_count: 最小サンプル数

        Returns:
            パターンリスト
        """
        query = text(f"""
            SELECT *
            FROM {TABLE_BRAIN_OUTCOME_PATTERNS}
            WHERE organization_id = CAST(:organization_id AS uuid)
              AND is_active = true
              AND promoted_to_learning_id IS NULL
              AND confidence_score >= :min_confidence
              AND sample_count >= :min_sample_count
            ORDER BY confidence_score DESC
        """)

        result = conn.execute(query, {
            "organization_id": self.organization_id,
            "min_confidence": min_confidence,
            "min_sample_count": min_sample_count,
        })

        return [OutcomePattern.from_db_row(dict(row._mapping)) for row in result]

    # ========================================================================
    # 統計系メソッド
    # ========================================================================

    def get_statistics(
        self,
        conn: Connection,
        target_account_id: Optional[str] = None,
        days: int = 30,
    ) -> OutcomeStatistics:
        """統計を取得

        Args:
            conn: DB接続
            target_account_id: 対象ユーザーID（オプション、指定なしで全体）
            days: 集計期間（日数）

        Returns:
            統計オブジェクト
        """
        threshold = datetime.now() - timedelta(days=days)

        query_parts = [
            f"""
            SELECT
                COUNT(*) as total_events,
                COUNT(CASE WHEN outcome_type = 'adopted' THEN 1 END) as adopted_count,
                COUNT(CASE WHEN outcome_type = 'ignored' THEN 1 END) as ignored_count,
                COUNT(CASE WHEN outcome_type = 'delayed' THEN 1 END) as delayed_count,
                COUNT(CASE WHEN outcome_type = 'rejected' THEN 1 END) as rejected_count,
                COUNT(CASE WHEN outcome_detected = false THEN 1 END) as pending_count
            FROM {TABLE_BRAIN_OUTCOME_EVENTS}
            WHERE organization_id = CAST(:organization_id AS uuid)
              AND event_timestamp >= :threshold
            """,
        ]
        params: Dict[str, Any] = {
            "organization_id": self.organization_id,
            "threshold": threshold,
        }

        if target_account_id:
            query_parts.append("  AND target_account_id = :target_account_id")
            params["target_account_id"] = target_account_id

        query = text("".join(query_parts))
        result = conn.execute(query, params)
        row = result.fetchone()

        if row is None:
            return OutcomeStatistics(
                target_account_id=target_account_id,
                period_start=threshold,
                period_end=datetime.now(),
            )

        row_dict = row._mapping
        total = row_dict["total_events"] or 0
        adopted = row_dict["adopted_count"] or 0
        ignored = row_dict["ignored_count"] or 0

        return OutcomeStatistics(
            target_account_id=target_account_id,
            period_start=threshold,
            period_end=datetime.now(),
            total_events=total,
            adopted_count=adopted,
            ignored_count=ignored,
            delayed_count=row_dict["delayed_count"] or 0,
            rejected_count=row_dict["rejected_count"] or 0,
            pending_count=row_dict["pending_count"] or 0,
            adoption_rate=adopted / total if total > 0 else 0.0,
            ignore_rate=ignored / total if total > 0 else 0.0,
        )

    def get_hourly_statistics(
        self,
        conn: Connection,
        target_account_id: Optional[str] = None,
        days: int = 30,
    ) -> Dict[int, Dict[str, int]]:
        """時間帯別統計を取得

        Args:
            conn: DB接続
            target_account_id: 対象ユーザーID（オプション）
            days: 集計期間（日数）

        Returns:
            時間帯別統計 {hour: {"total": N, "adopted": N, "ignored": N}}
        """
        threshold = datetime.now() - timedelta(days=days)

        query_parts = [
            f"""
            SELECT
                EXTRACT(HOUR FROM event_timestamp) as hour,
                COUNT(*) as total,
                COUNT(CASE WHEN outcome_type = 'adopted' THEN 1 END) as adopted,
                COUNT(CASE WHEN outcome_type = 'ignored' THEN 1 END) as ignored
            FROM {TABLE_BRAIN_OUTCOME_EVENTS}
            WHERE organization_id = CAST(:organization_id AS uuid)
              AND event_timestamp >= :threshold
              AND outcome_detected = true
            """,
        ]
        params: Dict[str, Any] = {
            "organization_id": self.organization_id,
            "threshold": threshold,
        }

        if target_account_id:
            query_parts.append("  AND target_account_id = :target_account_id")
            params["target_account_id"] = target_account_id

        query_parts.append("GROUP BY hour ORDER BY hour")

        query = text("".join(query_parts))
        result = conn.execute(query, params)

        return {
            int(row._mapping["hour"]): {
                "total": row._mapping["total"],
                "adopted": row._mapping["adopted"],
                "ignored": row._mapping["ignored"],
            }
            for row in result
        }

    def get_day_of_week_statistics(
        self,
        conn: Connection,
        target_account_id: Optional[str] = None,
        days: int = 30,
    ) -> Dict[int, Dict[str, int]]:
        """曜日別統計を取得

        Args:
            conn: DB接続
            target_account_id: 対象ユーザーID（オプション）
            days: 集計期間（日数）

        Returns:
            曜日別統計 {day_of_week: {"total": N, "adopted": N, "ignored": N}}
            day_of_week: 0=Monday, 6=Sunday
        """
        threshold = datetime.now() - timedelta(days=days)

        query_parts = [
            f"""
            SELECT
                EXTRACT(DOW FROM event_timestamp) as dow,
                COUNT(*) as total,
                COUNT(CASE WHEN outcome_type = 'adopted' THEN 1 END) as adopted,
                COUNT(CASE WHEN outcome_type = 'ignored' THEN 1 END) as ignored
            FROM {TABLE_BRAIN_OUTCOME_EVENTS}
            WHERE organization_id = CAST(:organization_id AS uuid)
              AND event_timestamp >= :threshold
              AND outcome_detected = true
            """,
        ]
        params: Dict[str, Any] = {
            "organization_id": self.organization_id,
            "threshold": threshold,
        }

        if target_account_id:
            query_parts.append("  AND target_account_id = :target_account_id")
            params["target_account_id"] = target_account_id

        query_parts.append("GROUP BY dow ORDER BY dow")

        query = text("".join(query_parts))
        result = conn.execute(query, params)

        # PostgreSQLのDOWは0=Sunday, 6=Saturday
        # Pythonのweekdayは0=Monday, 6=Sunday
        # 変換: (dow + 6) % 7
        return {
            (int(row._mapping["dow"]) + 6) % 7: {
                "total": row._mapping["total"],
                "adopted": row._mapping["adopted"],
                "ignored": row._mapping["ignored"],
            }
            for row in result
        }
