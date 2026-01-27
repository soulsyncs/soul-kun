"""
Phase 2E: 学習基盤 - リポジトリ層

設計書: docs/18_phase2e_learning_foundation.md v1.1.0
セクション: 8.2.3 リポジトリ層

学習データのDB操作を担当する。
"""

import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.engine import Connection

from .constants import (
    AuthorityLevel,
    AUTHORITY_PRIORITY,
    LearningScope,
    TABLE_BRAIN_LEARNINGS,
    TABLE_BRAIN_LEARNING_LOGS,
    MAX_LEARNINGS_PER_QUERY,
    MAX_LOGS_PER_QUERY,
    MAX_LEARNINGS_PER_CATEGORY_DISPLAY,
)
from .models import Learning, LearningLog


class LearningRepository:
    """学習リポジトリ

    学習データのCRUD操作を提供する。

    設計書セクション8.2.3に準拠。
    """

    def __init__(self, organization_id: str):
        """初期化

        Args:
            organization_id: 組織ID
        """
        self.organization_id = organization_id

    # ========================================================================
    # 保存系メソッド
    # ========================================================================

    def save(
        self,
        conn: Connection,
        learning: Learning,
    ) -> str:
        """学習を保存

        Args:
            conn: DB接続
            learning: 学習オブジェクト

        Returns:
            保存された学習のID

        Raises:
            ValueError: 保存に失敗した場合
        """
        query = text(f"""
            INSERT INTO {TABLE_BRAIN_LEARNINGS} (
                id,
                organization_id,
                category,
                trigger_type,
                trigger_value,
                learned_content,
                learned_content_version,
                scope,
                scope_target_id,
                authority_level,
                valid_from,
                valid_until,
                taught_by_account_id,
                taught_by_name,
                taught_in_room_id,
                source_message,
                source_context,
                detection_pattern,
                detection_confidence,
                classification,
                is_active,
                created_at,
                updated_at
            ) VALUES (
                :id,
                :organization_id,
                :category,
                :trigger_type,
                :trigger_value,
                CAST(:learned_content AS jsonb),
                :learned_content_version,
                :scope,
                :scope_target_id,
                :authority_level,
                :valid_from,
                :valid_until,
                :taught_by_account_id,
                :taught_by_name,
                :taught_in_room_id,
                :source_message,
                CAST(:source_context AS jsonb),
                :detection_pattern,
                :detection_confidence,
                :classification,
                :is_active,
                :created_at,
                :updated_at
            )
            RETURNING id
        """)

        now = datetime.now()
        result = conn.execute(query, {
            "id": learning.id,
            "organization_id": self.organization_id,
            "category": learning.category,
            "trigger_type": learning.trigger_type,
            "trigger_value": learning.trigger_value,
            "learned_content": json.dumps(learning.learned_content, ensure_ascii=False),
            "learned_content_version": learning.learned_content_version,
            "scope": learning.scope,
            "scope_target_id": learning.scope_target_id,
            "authority_level": learning.authority_level,
            "valid_from": learning.valid_from or now,
            "valid_until": learning.valid_until,
            "taught_by_account_id": learning.taught_by_account_id,
            "taught_by_name": learning.taught_by_name,
            "taught_in_room_id": learning.taught_in_room_id,
            "source_message": learning.source_message,
            "source_context": json.dumps(learning.source_context, ensure_ascii=False) if learning.source_context else None,
            "detection_pattern": learning.detection_pattern,
            "detection_confidence": learning.detection_confidence,
            "classification": learning.classification,
            "is_active": learning.is_active,
            "created_at": now,
            "updated_at": now,
        })

        row = result.fetchone()
        if row is None:
            raise ValueError("学習の保存に失敗しました")

        return row[0]

    def save_log(
        self,
        conn: Connection,
        log: LearningLog,
    ) -> str:
        """学習適用ログを保存

        Args:
            conn: DB接続
            log: ログオブジェクト

        Returns:
            保存されたログのID
        """
        query = text(f"""
            INSERT INTO {TABLE_BRAIN_LEARNING_LOGS} (
                id,
                organization_id,
                learning_id,
                applied_at,
                applied_in_room_id,
                applied_for_account_id,
                trigger_message,
                applied_result,
                user_feedback,
                feedback_at,
                created_at
            ) VALUES (
                :id,
                :organization_id,
                :learning_id,
                :applied_at,
                :applied_in_room_id,
                :applied_for_account_id,
                :trigger_message,
                :applied_result,
                :user_feedback,
                :feedback_at,
                :created_at
            )
            RETURNING id
        """)

        now = datetime.now()
        result = conn.execute(query, {
            "id": log.id or str(uuid4()),
            "organization_id": self.organization_id,
            "learning_id": log.learning_id,
            "applied_at": log.applied_at or now,
            "applied_in_room_id": log.applied_in_room_id,
            "applied_for_account_id": log.applied_for_account_id,
            "trigger_message": log.trigger_message,
            "applied_result": log.applied_result,
            "user_feedback": log.user_feedback,
            "feedback_at": log.feedback_at,
            "created_at": now,
        })

        row = result.fetchone()
        return row[0] if row else ""

    # ========================================================================
    # 検索系メソッド
    # ========================================================================

    def find_by_id(
        self,
        conn: Connection,
        learning_id: str,
    ) -> Optional[Learning]:
        """IDで学習を検索

        Args:
            conn: DB接続
            learning_id: 学習ID

        Returns:
            学習オブジェクト（見つからない場合はNone）
        """
        query = text(f"""
            SELECT
                id, organization_id, category, trigger_type, trigger_value,
                learned_content, learned_content_version, scope, scope_target_id,
                authority_level, valid_from, valid_until, taught_by_account_id,
                taught_by_name, taught_in_room_id, source_message, source_context,
                detection_pattern, detection_confidence, classification,
                supersedes_id, superseded_by_id, related_learning_ids,
                is_active, effectiveness_score, apply_count, positive_feedback_count,
                negative_feedback_count, created_at, updated_at
            FROM {TABLE_BRAIN_LEARNINGS}
            WHERE organization_id = :organization_id
              AND id = :learning_id
        """)

        result = conn.execute(query, {
            "organization_id": self.organization_id,
            "learning_id": learning_id,
        })

        row = result.fetchone()
        if row is None:
            return None

        return self._row_to_learning(row)

    def find_applicable(
        self,
        conn: Connection,
        message: str,
        user_id: Optional[str] = None,
        room_id: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = MAX_LEARNINGS_PER_QUERY,
    ) -> List[Learning]:
        """適用可能な学習を検索

        設計書セクション5.2に従い、以下の条件でフィルタ:
        - is_active = true
        - 有効期間内
        - スコープ条件に合致
        - authority_levelの優先度順（CEOが最優先）

        Args:
            conn: DB接続
            message: トリガーとなるメッセージ
            user_id: ユーザーID（スコープフィルタ用）
            room_id: ルームID（スコープフィルタ用）
            category: カテゴリフィルタ（指定時）
            limit: 最大取得件数

        Returns:
            適用可能な学習のリスト（優先度順）
        """
        # 基本クエリ
        base_query = f"""
            SELECT
                id, organization_id, category, trigger_type, trigger_value,
                learned_content, learned_content_version, scope, scope_target_id,
                authority_level, valid_from, valid_until, taught_by_account_id,
                taught_by_name, taught_in_room_id, source_message, source_context,
                detection_pattern, detection_confidence, classification,
                supersedes_id, superseded_by_id, related_learning_ids,
                is_active, effectiveness_score, apply_count, positive_feedback_count,
                negative_feedback_count, created_at, updated_at
            FROM {TABLE_BRAIN_LEARNINGS}
            WHERE organization_id = :organization_id
              AND is_active = true
              AND (valid_from IS NULL OR valid_from <= :now)
              AND (valid_until IS NULL OR valid_until >= :now)
        """

        params: Dict[str, Any] = {
            "organization_id": self.organization_id,
            "now": datetime.now(),
            "limit": limit,
        }

        # カテゴリフィルタ
        if category:
            base_query += " AND category = :category"
            params["category"] = category

        # スコープフィルタ
        scope_conditions = ["scope = 'global'"]

        if user_id:
            scope_conditions.append(
                "(scope = 'user' AND scope_target_id = :user_id)"
            )
            params["user_id"] = user_id

        if room_id:
            scope_conditions.append(
                "(scope = 'room' AND scope_target_id = :room_id)"
            )
            params["room_id"] = room_id

        # temporaryスコープは常に含める
        scope_conditions.append("scope = 'temporary'")

        base_query += f" AND ({' OR '.join(scope_conditions)})"

        # 権限レベル順にソート（CEOが最優先）
        # CASE文で優先度を数値化
        base_query += """
            ORDER BY
                CASE authority_level
                    WHEN 'ceo' THEN 1
                    WHEN 'manager' THEN 2
                    WHEN 'user' THEN 3
                    WHEN 'system' THEN 4
                    ELSE 5
                END ASC,
                detection_confidence DESC,
                created_at DESC
            LIMIT :limit
        """

        query = text(base_query)
        result = conn.execute(query, params)

        learnings = []
        for row in result.fetchall():
            learning = self._row_to_learning(row)
            # トリガー条件をメッセージと照合
            if self._matches_trigger(learning, message):
                learnings.append(learning)

        return learnings

    def find_by_trigger(
        self,
        conn: Connection,
        trigger_type: str,
        trigger_value: str,
        category: Optional[str] = None,
    ) -> List[Learning]:
        """トリガーで学習を検索

        同じトリガーを持つ学習を検索（矛盾検出用）

        Args:
            conn: DB接続
            trigger_type: トリガータイプ
            trigger_value: トリガー値
            category: カテゴリフィルタ

        Returns:
            該当する学習のリスト
        """
        base_query = f"""
            SELECT
                id, organization_id, category, trigger_type, trigger_value,
                learned_content, learned_content_version, scope, scope_target_id,
                authority_level, valid_from, valid_until, taught_by_account_id,
                taught_by_name, taught_in_room_id, source_message, source_context,
                detection_pattern, detection_confidence, classification,
                supersedes_id, superseded_by_id, related_learning_ids,
                is_active, effectiveness_score, apply_count, positive_feedback_count,
                negative_feedback_count, created_at, updated_at
            FROM {TABLE_BRAIN_LEARNINGS}
            WHERE organization_id = :organization_id
              AND is_active = true
              AND trigger_type = :trigger_type
              AND trigger_value = :trigger_value
        """

        params: Dict[str, Any] = {
            "organization_id": self.organization_id,
            "trigger_type": trigger_type,
            "trigger_value": trigger_value,
        }

        if category:
            base_query += " AND category = :category"
            params["category"] = category

        base_query += " ORDER BY created_at DESC"

        query = text(base_query)
        result = conn.execute(query, params)

        return [self._row_to_learning(row) for row in result.fetchall()]

    def find_by_category(
        self,
        conn: Connection,
        category: str,
        active_only: bool = True,
        limit: int = MAX_LEARNINGS_PER_CATEGORY_DISPLAY,
    ) -> List[Learning]:
        """カテゴリで学習を検索

        Args:
            conn: DB接続
            category: カテゴリ
            active_only: アクティブのみ
            limit: 最大取得件数

        Returns:
            該当する学習のリスト
        """
        base_query = f"""
            SELECT
                id, organization_id, category, trigger_type, trigger_value,
                learned_content, learned_content_version, scope, scope_target_id,
                authority_level, valid_from, valid_until, taught_by_account_id,
                taught_by_name, taught_in_room_id, source_message, source_context,
                detection_pattern, detection_confidence, classification,
                supersedes_id, superseded_by_id, related_learning_ids,
                is_active, effectiveness_score, apply_count, positive_feedback_count,
                negative_feedback_count, created_at, updated_at
            FROM {TABLE_BRAIN_LEARNINGS}
            WHERE organization_id = :organization_id
              AND category = :category
        """

        params: Dict[str, Any] = {
            "organization_id": self.organization_id,
            "category": category,
            "limit": limit,
        }

        if active_only:
            base_query += " AND is_active = true"

        base_query += " ORDER BY created_at DESC LIMIT :limit"

        query = text(base_query)
        result = conn.execute(query, params)

        return [self._row_to_learning(row) for row in result.fetchall()]

    def find_all(
        self,
        conn: Connection,
        active_only: bool = True,
        limit: int = MAX_LEARNINGS_PER_QUERY,
        offset: int = 0,
    ) -> Tuple[List[Learning], int]:
        """全学習を取得

        Args:
            conn: DB接続
            active_only: アクティブのみ
            limit: 最大取得件数
            offset: オフセット

        Returns:
            (学習のリスト, 総件数)
        """
        # 総件数を取得
        count_query = f"""
            SELECT COUNT(*)
            FROM {TABLE_BRAIN_LEARNINGS}
            WHERE organization_id = :organization_id
        """
        if active_only:
            count_query += " AND is_active = true"

        count_result = conn.execute(
            text(count_query),
            {"organization_id": self.organization_id}
        )
        total_count = count_result.scalar() or 0

        # データを取得
        base_query = f"""
            SELECT
                id, organization_id, category, trigger_type, trigger_value,
                learned_content, learned_content_version, scope, scope_target_id,
                authority_level, valid_from, valid_until, taught_by_account_id,
                taught_by_name, taught_in_room_id, source_message, source_context,
                detection_pattern, detection_confidence, classification,
                supersedes_id, superseded_by_id, related_learning_ids,
                is_active, effectiveness_score, apply_count, positive_feedback_count,
                negative_feedback_count, created_at, updated_at
            FROM {TABLE_BRAIN_LEARNINGS}
            WHERE organization_id = :organization_id
        """

        if active_only:
            base_query += " AND is_active = true"

        base_query += " ORDER BY created_at DESC LIMIT :limit OFFSET :offset"

        query = text(base_query)
        result = conn.execute(query, {
            "organization_id": self.organization_id,
            "limit": limit,
            "offset": offset,
        })

        learnings = [self._row_to_learning(row) for row in result.fetchall()]
        return learnings, total_count

    def find_by_user(
        self,
        conn: Connection,
        user_id: str,
        active_only: bool = True,
        limit: int = MAX_LEARNINGS_PER_QUERY,
    ) -> List[Learning]:
        """ユーザーが教えた学習を検索

        Args:
            conn: DB接続
            user_id: ユーザーID
            active_only: アクティブのみ
            limit: 最大取得件数

        Returns:
            該当する学習のリスト
        """
        base_query = f"""
            SELECT
                id, organization_id, category, trigger_type, trigger_value,
                learned_content, learned_content_version, scope, scope_target_id,
                authority_level, valid_from, valid_until, taught_by_account_id,
                taught_by_name, taught_in_room_id, source_message, source_context,
                detection_pattern, detection_confidence, classification,
                supersedes_id, superseded_by_id, related_learning_ids,
                is_active, effectiveness_score, apply_count, positive_feedback_count,
                negative_feedback_count, created_at, updated_at
            FROM {TABLE_BRAIN_LEARNINGS}
            WHERE organization_id = :organization_id
              AND taught_by_account_id = :user_id
        """

        params: Dict[str, Any] = {
            "organization_id": self.organization_id,
            "user_id": user_id,
            "limit": limit,
        }

        if active_only:
            base_query += " AND is_active = true"

        base_query += " ORDER BY created_at DESC LIMIT :limit"

        query = text(base_query)
        result = conn.execute(query, params)

        return [self._row_to_learning(row) for row in result.fetchall()]

    # ========================================================================
    # 更新系メソッド
    # ========================================================================

    def deactivate(
        self,
        conn: Connection,
        learning_id: str,
    ) -> bool:
        """学習を無効化

        Args:
            conn: DB接続
            learning_id: 学習ID

        Returns:
            成功したかどうか
        """
        query = text(f"""
            UPDATE {TABLE_BRAIN_LEARNINGS}
            SET is_active = false,
                updated_at = :updated_at
            WHERE organization_id = :organization_id
              AND id = :learning_id
        """)

        result = conn.execute(query, {
            "organization_id": self.organization_id,
            "learning_id": learning_id,
            "updated_at": datetime.now(),
        })

        return result.rowcount > 0

    def activate(
        self,
        conn: Connection,
        learning_id: str,
    ) -> bool:
        """学習を有効化

        Args:
            conn: DB接続
            learning_id: 学習ID

        Returns:
            成功したかどうか
        """
        query = text(f"""
            UPDATE {TABLE_BRAIN_LEARNINGS}
            SET is_active = true,
                updated_at = :updated_at
            WHERE organization_id = :organization_id
              AND id = :learning_id
        """)

        result = conn.execute(query, {
            "organization_id": self.organization_id,
            "learning_id": learning_id,
            "updated_at": datetime.now(),
        })

        return result.rowcount > 0

    def update_supersedes(
        self,
        conn: Connection,
        new_learning_id: str,
        old_learning_id: str,
    ) -> bool:
        """置き換え関係を設定

        Args:
            conn: DB接続
            new_learning_id: 新しい学習ID
            old_learning_id: 古い学習ID

        Returns:
            成功したかどうか
        """
        now = datetime.now()

        # 新しい学習に supersedes_id を設定
        query1 = text(f"""
            UPDATE {TABLE_BRAIN_LEARNINGS}
            SET supersedes_id = :old_learning_id,
                updated_at = :updated_at
            WHERE organization_id = :organization_id
              AND id = :new_learning_id
        """)

        result1 = conn.execute(query1, {
            "organization_id": self.organization_id,
            "new_learning_id": new_learning_id,
            "old_learning_id": old_learning_id,
            "updated_at": now,
        })

        # 古い学習に superseded_by_id を設定し、無効化
        query2 = text(f"""
            UPDATE {TABLE_BRAIN_LEARNINGS}
            SET superseded_by_id = :new_learning_id,
                is_active = false,
                updated_at = :updated_at
            WHERE organization_id = :organization_id
              AND id = :old_learning_id
        """)

        result2 = conn.execute(query2, {
            "organization_id": self.organization_id,
            "new_learning_id": new_learning_id,
            "old_learning_id": old_learning_id,
            "updated_at": now,
        })

        return result1.rowcount > 0 and result2.rowcount > 0

    def increment_apply_count(
        self,
        conn: Connection,
        learning_id: str,
    ) -> bool:
        """適用回数をインクリメント

        Args:
            conn: DB接続
            learning_id: 学習ID

        Returns:
            成功したかどうか
        """
        query = text(f"""
            UPDATE {TABLE_BRAIN_LEARNINGS}
            SET apply_count = apply_count + 1,
                updated_at = :updated_at
            WHERE organization_id = :organization_id
              AND id = :learning_id
        """)

        result = conn.execute(query, {
            "organization_id": self.organization_id,
            "learning_id": learning_id,
            "updated_at": datetime.now(),
        })

        return result.rowcount > 0

    def update_feedback_count(
        self,
        conn: Connection,
        learning_id: str,
        is_positive: bool,
    ) -> bool:
        """フィードバックカウントを更新

        Args:
            conn: DB接続
            learning_id: 学習ID
            is_positive: ポジティブフィードバックかどうか

        Returns:
            成功したかどうか
        """
        column = "positive_feedback_count" if is_positive else "negative_feedback_count"

        query = text(f"""
            UPDATE {TABLE_BRAIN_LEARNINGS}
            SET {column} = {column} + 1,
                updated_at = :updated_at
            WHERE organization_id = :organization_id
              AND id = :learning_id
        """)

        result = conn.execute(query, {
            "organization_id": self.organization_id,
            "learning_id": learning_id,
            "updated_at": datetime.now(),
        })

        return result.rowcount > 0

    def update_effectiveness_score(
        self,
        conn: Connection,
        learning_id: str,
        score: float,
    ) -> bool:
        """有効性スコアを更新

        Args:
            conn: DB接続
            learning_id: 学習ID
            score: 新しいスコア

        Returns:
            成功したかどうか
        """
        query = text(f"""
            UPDATE {TABLE_BRAIN_LEARNINGS}
            SET effectiveness_score = :score,
                updated_at = :updated_at
            WHERE organization_id = :organization_id
              AND id = :learning_id
        """)

        result = conn.execute(query, {
            "organization_id": self.organization_id,
            "learning_id": learning_id,
            "score": score,
            "updated_at": datetime.now(),
        })

        return result.rowcount > 0

    def update_log_feedback(
        self,
        conn: Connection,
        log_id: str,
        feedback: str,
    ) -> bool:
        """ログにフィードバックを記録

        Args:
            conn: DB接続
            log_id: ログID
            feedback: フィードバック（positive/negative/neutral）

        Returns:
            成功したかどうか
        """
        query = text(f"""
            UPDATE {TABLE_BRAIN_LEARNING_LOGS}
            SET user_feedback = :feedback,
                feedback_at = :feedback_at
            WHERE organization_id = :organization_id
              AND id = :log_id
        """)

        result = conn.execute(query, {
            "organization_id": self.organization_id,
            "log_id": log_id,
            "feedback": feedback,
            "feedback_at": datetime.now(),
        })

        return result.rowcount > 0

    # ========================================================================
    # 削除系メソッド
    # ========================================================================

    def delete(
        self,
        conn: Connection,
        learning_id: str,
        hard_delete: bool = False,
    ) -> bool:
        """学習を削除

        Args:
            conn: DB接続
            learning_id: 学習ID
            hard_delete: 物理削除するかどうか（デフォルトは論理削除）

        Returns:
            成功したかどうか
        """
        if hard_delete:
            # 物理削除（通常は使わない）
            query = text(f"""
                DELETE FROM {TABLE_BRAIN_LEARNINGS}
                WHERE organization_id = :organization_id
                  AND id = :learning_id
            """)
        else:
            # 論理削除（is_active = false）
            query = text(f"""
                UPDATE {TABLE_BRAIN_LEARNINGS}
                SET is_active = false,
                    updated_at = :updated_at
                WHERE organization_id = :organization_id
                  AND id = :learning_id
            """)

        params: Dict[str, Any] = {
            "organization_id": self.organization_id,
            "learning_id": learning_id,
        }

        if not hard_delete:
            params["updated_at"] = datetime.now()

        result = conn.execute(query, params)
        return result.rowcount > 0

    # ========================================================================
    # ログ検索メソッド
    # ========================================================================

    def find_logs_by_learning(
        self,
        conn: Connection,
        learning_id: str,
        limit: int = MAX_LOGS_PER_QUERY,
    ) -> List[LearningLog]:
        """学習IDでログを検索

        Args:
            conn: DB接続
            learning_id: 学習ID
            limit: 最大取得件数

        Returns:
            ログのリスト
        """
        query = text(f"""
            SELECT
                id, organization_id, learning_id, applied_at,
                applied_in_room_id, applied_for_account_id,
                trigger_message, applied_result, user_feedback,
                feedback_at, created_at
            FROM {TABLE_BRAIN_LEARNING_LOGS}
            WHERE organization_id = :organization_id
              AND learning_id = :learning_id
            ORDER BY applied_at DESC
            LIMIT :limit
        """)

        result = conn.execute(query, {
            "organization_id": self.organization_id,
            "learning_id": learning_id,
            "limit": limit,
        })

        return [self._row_to_log(row) for row in result.fetchall()]

    def find_recent_logs(
        self,
        conn: Connection,
        limit: int = MAX_LOGS_PER_QUERY,
    ) -> List[LearningLog]:
        """最近のログを取得

        Args:
            conn: DB接続
            limit: 最大取得件数

        Returns:
            ログのリスト
        """
        query = text(f"""
            SELECT
                id, organization_id, learning_id, applied_at,
                applied_in_room_id, applied_for_account_id,
                trigger_message, applied_result, user_feedback,
                feedback_at, created_at
            FROM {TABLE_BRAIN_LEARNING_LOGS}
            WHERE organization_id = :organization_id
            ORDER BY applied_at DESC
            LIMIT :limit
        """)

        result = conn.execute(query, {
            "organization_id": self.organization_id,
            "limit": limit,
        })

        return [self._row_to_log(row) for row in result.fetchall()]

    # ========================================================================
    # プライベートメソッド
    # ========================================================================

    def _row_to_learning(self, row) -> Learning:
        """DBの行をLearningオブジェクトに変換

        Args:
            row: DBの行

        Returns:
            Learningオブジェクト
        """
        # rowがタプルの場合とRowの場合の両方に対応
        if hasattr(row, "_mapping"):
            # SQLAlchemy Row
            data = dict(row._mapping)
        else:
            # タプル（インデックスでアクセス）
            columns = [
                "id", "organization_id", "category", "trigger_type", "trigger_value",
                "learned_content", "learned_content_version", "scope", "scope_target_id",
                "authority_level", "valid_from", "valid_until", "taught_by_account_id",
                "taught_by_name", "taught_in_room_id", "source_message", "source_context",
                "detection_pattern", "detection_confidence", "classification",
                "supersedes_id", "superseded_by_id", "related_learning_ids",
                "is_active", "effectiveness_score", "apply_count", "positive_feedback_count",
                "negative_feedback_count", "created_at", "updated_at"
            ]
            data = dict(zip(columns, row))

        # JSONBフィールドの処理
        learned_content = data.get("learned_content", {})
        if isinstance(learned_content, str):
            learned_content = json.loads(learned_content)

        source_context = data.get("source_context")
        if isinstance(source_context, str):
            source_context = json.loads(source_context)

        related_learning_ids = data.get("related_learning_ids")
        if isinstance(related_learning_ids, str):
            related_learning_ids = json.loads(related_learning_ids)

        return Learning(
            id=data["id"],
            organization_id=data["organization_id"],
            category=data["category"],
            trigger_type=data["trigger_type"],
            trigger_value=data["trigger_value"],
            learned_content=learned_content,
            learned_content_version=data["learned_content_version"],
            scope=data["scope"],
            scope_target_id=data.get("scope_target_id"),
            authority_level=data["authority_level"],
            valid_from=data.get("valid_from"),
            valid_until=data.get("valid_until"),
            taught_by_account_id=data.get("taught_by_account_id"),
            taught_by_name=data.get("taught_by_name"),
            taught_in_room_id=data.get("taught_in_room_id"),
            source_message=data.get("source_message"),
            source_context=source_context,
            detection_pattern=data.get("detection_pattern"),
            detection_confidence=data.get("detection_confidence"),
            classification=data["classification"],
            supersedes_id=data.get("supersedes_id"),
            superseded_by_id=data.get("superseded_by_id"),
            related_learning_ids=related_learning_ids,
            is_active=data["is_active"],
            effectiveness_score=data.get("effectiveness_score"),
            apply_count=data.get("apply_count", 0),
            positive_feedback_count=data.get("positive_feedback_count", 0),
            negative_feedback_count=data.get("negative_feedback_count", 0),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )

    def _row_to_log(self, row) -> LearningLog:
        """DBの行をLearningLogオブジェクトに変換

        Args:
            row: DBの行

        Returns:
            LearningLogオブジェクト
        """
        if hasattr(row, "_mapping"):
            data = dict(row._mapping)
        else:
            columns = [
                "id", "organization_id", "learning_id", "applied_at",
                "applied_in_room_id", "applied_for_account_id",
                "trigger_message", "applied_result", "user_feedback",
                "feedback_at", "created_at"
            ]
            data = dict(zip(columns, row))

        return LearningLog(
            id=data["id"],
            organization_id=data["organization_id"],
            learning_id=data["learning_id"],
            applied_at=data.get("applied_at"),
            applied_in_room_id=data.get("applied_in_room_id"),
            applied_for_account_id=data.get("applied_for_account_id"),
            trigger_message=data.get("trigger_message"),
            applied_result=data.get("applied_result"),
            user_feedback=data.get("user_feedback"),
            feedback_at=data.get("feedback_at"),
            created_at=data.get("created_at"),
        )

    def _matches_trigger(self, learning: Learning, message: str) -> bool:
        """メッセージがトリガー条件に一致するか判定

        Args:
            learning: 学習オブジェクト
            message: メッセージ

        Returns:
            一致するかどうか
        """
        import re

        trigger_type = learning.trigger_type
        trigger_value = learning.trigger_value

        if trigger_type == "always":
            return True

        if trigger_type == "keyword":
            # キーワード一致（カンマ区切りで複数可）
            keywords = trigger_value.split(",")
            for keyword in keywords:
                keyword = keyword.strip()
                if keyword and keyword.lower() in message.lower():
                    return True
            return False

        if trigger_type == "pattern":
            # 正規表現パターン
            try:
                pattern = re.compile(trigger_value, re.IGNORECASE)
                return bool(pattern.search(message))
            except re.error:
                return False

        if trigger_type == "context":
            # 文脈条件（キーワードとして扱う）
            return trigger_value.lower() in message.lower()

        return False


# ============================================================================
# ファクトリ関数
# ============================================================================

def create_repository(organization_id: str) -> LearningRepository:
    """学習リポジトリを作成

    Args:
        organization_id: 組織ID

    Returns:
        LearningRepository インスタンス
    """
    return LearningRepository(organization_id)
