# lib/brain/daily_log.py
"""
日次ログ生成

ソウルくんの1日の活動を集計し、人間可読なサマリーを生成する。
Phase 2-B: 活動の透明性向上。

【設計原則】
- CLAUDE.md 2-1: 脳を経由 → 日次ログは脳の判断記録の集計
- CLAUDE.md 1: organization_id必須 → 全クエリにorg_idフィルタ
- CLAUDE.md 9: SQLパラメータ化

【データソース】
- monitoring.py の AggregatedMetrics（レスポンス時間、コスト等）
- DB: conversation_timestamps（会話数）
- DB: user_preferences（新規学習数）
- DB: soulkun_knowledge（新規ナレッジ数）
- DB: brain_learnings（脳の学習数）

Author: Claude Code
Created: 2026-02-07
"""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone, timedelta
from typing import List, Dict, Any, Optional

from sqlalchemy import text as sql_text

logger = logging.getLogger(__name__)

# 日本時間オフセット
JST = timezone(timedelta(hours=9))


# =============================================================================
# データクラス
# =============================================================================


@dataclass
class DailyActivity:
    """1日の活動サマリー"""
    target_date: date
    org_id: str

    # 会話メトリクス
    total_conversations: int = 0
    unique_users: int = 0

    # アクション内訳
    action_counts: Dict[str, int] = field(default_factory=dict)

    # メモリ・ナレッジ
    new_preferences: int = 0
    new_knowledge: int = 0
    new_learnings: int = 0

    # パフォーマンス（monitoring.pyから取得）
    avg_response_time_ms: float = 0.0
    error_rate: float = 0.0
    total_cost_yen: float = 0.0

    # Guardian
    guardian_allow: int = 0
    guardian_confirm: int = 0
    guardian_block: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target_date": self.target_date.isoformat(),
            "org_id": self.org_id,
            "conversations": {
                "total": self.total_conversations,
                "unique_users": self.unique_users,
            },
            "actions": self.action_counts,
            "memory": {
                "new_preferences": self.new_preferences,
                "new_knowledge": self.new_knowledge,
                "new_learnings": self.new_learnings,
            },
            "performance": {
                "avg_response_time_ms": round(self.avg_response_time_ms, 1),
                "error_rate": round(self.error_rate, 4),
                "total_cost_yen": round(self.total_cost_yen, 2),
            },
            "guardian": {
                "allow": self.guardian_allow,
                "confirm": self.guardian_confirm,
                "block": self.guardian_block,
            },
        }

    def to_display_text(self) -> str:
        """ChatWork向けの日次レポートテキスト生成"""
        date_str = self.target_date.strftime("%Y/%m/%d")

        lines = [
            f"[info][title]日次レポート ({date_str})[/title]",
            "",
            f"会話数: {self.total_conversations}件（{self.unique_users}人のユーザー）",
        ]

        # アクション内訳
        if self.action_counts:
            lines.append("")
            lines.append("アクション内訳:")
            for action, count in sorted(
                self.action_counts.items(), key=lambda x: x[1], reverse=True
            ):
                lines.append(f"  - {action}: {count}件")

        # メモリ活動
        memory_total = self.new_preferences + self.new_knowledge + self.new_learnings
        if memory_total > 0:
            lines.append("")
            lines.append("記憶・学習:")
            if self.new_preferences > 0:
                lines.append(f"  - 新しい好み・設定: {self.new_preferences}件")
            if self.new_knowledge > 0:
                lines.append(f"  - 新しいナレッジ: {self.new_knowledge}件")
            if self.new_learnings > 0:
                lines.append(f"  - 脳の学習: {self.new_learnings}件")

        # パフォーマンス
        lines.append("")
        lines.append("パフォーマンス:")
        lines.append(f"  - 平均応答: {self.avg_response_time_ms:.0f}ms")
        lines.append(f"  - エラー率: {self.error_rate:.1%}")
        lines.append(f"  - コスト: {self.total_cost_yen:.0f}円")

        # Guardian
        guardian_total = self.guardian_allow + self.guardian_confirm + self.guardian_block
        if guardian_total > 0:
            lines.append("")
            lines.append("Guardian Layer:")
            lines.append(f"  - 許可: {self.guardian_allow}件")
            if self.guardian_confirm > 0:
                lines.append(f"  - 確認: {self.guardian_confirm}件")
            if self.guardian_block > 0:
                lines.append(f"  - ブロック: {self.guardian_block}件")

        lines.append("[/info]")
        return "\n".join(lines)


# =============================================================================
# 日次ログジェネレーター
# =============================================================================


class DailyLogGenerator:
    """
    日次活動ログの生成

    DBからその日の活動データを集計し、DailyActivityを生成する。
    monitoring.pyのAggregatedMetricsと組み合わせて使う。
    """

    def __init__(self, pool, org_id: str):
        """
        Args:
            pool: SQLAlchemyデータベース接続プール
            org_id: 組織ID（slug）

        Raises:
            ValueError: org_idが空または不正な型の場合
        """
        if not org_id or not isinstance(org_id, str):
            raise ValueError("org_id must be a non-empty string")
        self.pool = pool
        self.org_id = org_id

    def generate(
        self,
        target_date: Optional[date] = None,
        metrics=None,
    ) -> DailyActivity:
        """
        指定日の日次活動サマリーを生成

        Args:
            target_date: 対象日（省略時は前日）
            metrics: AggregatedMetrics（省略時はDB集計のみ）

        Returns:
            DailyActivity
        """
        if target_date is None:
            # デフォルト: 前日（JST基準）
            now_jst = datetime.now(JST)
            target_date = (now_jst - timedelta(days=1)).date()

        activity = DailyActivity(
            target_date=target_date,
            org_id=self.org_id,
        )

        # DB集計（単一コネクションで実行）
        # 日付範囲: target_date 00:00:00 〜 翌日 00:00:00（HIGH-2: ::date castを回避）
        date_start = activity.target_date.isoformat()
        date_end = (activity.target_date + timedelta(days=1)).isoformat()

        try:
            with self.pool.connect() as conn:
                self._collect_conversation_stats(activity, conn, date_start, date_end)
                self._collect_memory_stats(activity, conn, date_start, date_end)
                self._collect_learning_stats(activity, conn, date_start, date_end)
        except Exception as e:
            logger.warning("Error in daily log DB collection: %s", e)

        # monitoring.pyのメトリクスがあれば統合
        if metrics is not None:
            self._merge_metrics(activity, metrics)

        return activity

    def _collect_conversation_stats(
        self, activity: DailyActivity, conn, date_start: str, date_end: str,
    ) -> None:
        """会話統計を集計（CRITICAL-1: JOINベース + date range）"""
        try:
            result = conn.execute(
                sql_text("""
                    SELECT
                        COUNT(*) AS total,
                        COUNT(DISTINCT ct.account_id) AS unique_users
                    FROM conversation_timestamps ct
                    JOIN chatwork_rooms cr ON cr.room_id::text = ct.room_id
                    JOIN organizations o ON o.id = cr.organization_id
                    WHERE o.slug = :org_id
                      AND ct.last_conversation_at >= CAST(:date_start AS DATE)
                      AND ct.last_conversation_at < CAST(:date_end AS DATE)
                """),
                {
                    "org_id": self.org_id,
                    "date_start": date_start,
                    "date_end": date_end,
                },
            ).fetchone()

            if result:
                activity.total_conversations = result[0] or 0
                activity.unique_users = result[1] or 0

        except Exception as e:
            logger.warning("Error collecting conversation stats: %s", e)

    def _collect_memory_stats(
        self, activity: DailyActivity, conn, date_start: str, date_end: str,
    ) -> None:
        """メモリ・ナレッジ統計を集計"""
        try:
            # user_preferences（当日作成分）
            pref_result = conn.execute(
                sql_text("""
                    SELECT COUNT(*)
                    FROM user_preferences up
                    JOIN organizations o ON o.id = up.organization_id
                    WHERE o.slug = :org_id
                      AND up.created_at >= CAST(:date_start AS DATE)
                      AND up.created_at < CAST(:date_end AS DATE)
                """),
                {
                    "org_id": self.org_id,
                    "date_start": date_start,
                    "date_end": date_end,
                },
            ).fetchone()

            if pref_result:
                activity.new_preferences = pref_result[0] or 0

            # soulkun_knowledge（当日作成分、org_idプレフィックスでスコープ）
            escaped_org = self.org_id.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            knowledge_result = conn.execute(
                sql_text("""
                    SELECT COUNT(*)
                    FROM soulkun_knowledge
                    WHERE key LIKE :key_prefix ESCAPE '\\'
                      AND created_at >= CAST(:date_start AS DATE)
                      AND created_at < CAST(:date_end AS DATE)
                """),
                {
                    "key_prefix": f"[{escaped_org}:%",
                    "date_start": date_start,
                    "date_end": date_end,
                },
            ).fetchone()

            if knowledge_result:
                activity.new_knowledge = knowledge_result[0] or 0

        except Exception as e:
            logger.warning("Error collecting memory stats: %s", e)

    def _collect_learning_stats(
        self, activity: DailyActivity, conn, date_start: str, date_end: str,
    ) -> None:
        """脳の学習統計を集計"""
        try:
            result = conn.execute(
                sql_text("""
                    SELECT COUNT(*)
                    FROM brain_learnings bl
                    JOIN organizations o ON o.id = bl.organization_id
                    WHERE o.slug = :org_id
                      AND bl.created_at >= CAST(:date_start AS DATE)
                      AND bl.created_at < CAST(:date_end AS DATE)
                """),
                {
                    "org_id": self.org_id,
                    "date_start": date_start,
                    "date_end": date_end,
                },
            ).fetchone()

            if result:
                activity.new_learnings = result[0] or 0

        except Exception as e:
            logger.warning("Error collecting learning stats: %s", e)

    def _merge_metrics(self, activity: DailyActivity, metrics) -> None:
        """AggregatedMetricsのデータをDailyActivityに統合"""
        try:
            activity.avg_response_time_ms = metrics.avg_response_time_ms
            activity.error_rate = metrics.error_rate
            activity.total_cost_yen = metrics.estimated_cost_yen
            activity.guardian_allow = metrics.guardian_allow_count
            activity.guardian_confirm = metrics.guardian_confirm_count
            activity.guardian_block = metrics.guardian_block_count

            # アクション内訳
            # NOTE: output_typesのキーはシステム定義の定数（general_conversation等）であり、
            # ユーザー入力由来のPIIは含まれない（lib/brain/constants.pyで定義）
            if hasattr(metrics, "output_types"):
                activity.action_counts = dict(metrics.output_types)

        except Exception as e:
            logger.warning("Error merging metrics: %s", e)
