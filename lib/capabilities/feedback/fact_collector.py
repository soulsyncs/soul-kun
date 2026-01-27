# lib/capabilities/feedback/fact_collector.py
"""
Phase F1: CEOフィードバックシステム - ファクト収集エンジン

このモジュールは、CEOフィードバックに必要なファクト（事実データ）を
各種データソースから収集します。

設計書: docs/20_next_generation_capabilities.md セクション8

アーキテクチャ:
    FactCollector
    ├─ タスクデータ (chatwork_tasks)
    ├─ 目標データ (goals)
    ├─ コミュニケーションデータ (conversation_logs等)
    ├─ 既存インサイト (soulkun_insights)
    └─ チーム集計 (上記の集約)

Author: Claude Opus 4.5
Created: 2026-01-27
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
import json
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection

from .constants import (
    AnalysisParameters,
    FeedbackPriority,
    TrendDirection,
)
from .models import (
    TaskFact,
    GoalFact,
    CommunicationFact,
    TeamFact,
    DailyFacts,
)


# =============================================================================
# 例外クラス
# =============================================================================


class FactCollectionError(Exception):
    """ファクト収集エラー"""

    def __init__(
        self,
        message: str,
        source: str = "",
        details: Optional[Dict[str, Any]] = None,
        original_exception: Optional[Exception] = None,
    ):
        super().__init__(message)
        self.message = message
        self.source = source
        self.details = details or {}
        self.original_exception = original_exception


# =============================================================================
# ユーザー情報データクラス
# =============================================================================


@dataclass
class UserInfo:
    """
    ユーザー基本情報

    ファクト収集時に使用するユーザー情報
    """

    user_id: str
    name: str
    chatwork_account_id: Optional[str] = None
    department_id: Optional[str] = None
    department_name: Optional[str] = None
    is_active: bool = True


# =============================================================================
# FactCollector クラス
# =============================================================================


class FactCollector:
    """
    ファクト収集エンジン

    各種データソースからファクト（事実データ）を収集し、
    DailyFacts としてまとめて返す。

    使用例:
        >>> collector = FactCollector(conn, org_id)
        >>> facts = await collector.collect_daily()
        >>> print(f"タスクファクト: {len(facts.task_facts)}件")
        >>> print(f"目標ファクト: {len(facts.goal_facts)}件")

    Attributes:
        conn: データベース接続
        org_id: 組織ID
    """

    def __init__(
        self,
        conn: Connection,
        org_id: UUID,
        stale_days: int = AnalysisParameters.TASK_STALE_DAYS,
    ) -> None:
        """
        FactCollectorを初期化

        Args:
            conn: データベース接続（SQLAlchemy Connection）
            org_id: 組織ID（UUID）
            stale_days: タスク滞留と判定する日数（デフォルト: 3日）
        """
        self._conn = conn
        self._org_id = org_id
        self._stale_days = stale_days

        # ロガーの初期化
        try:
            from lib.logging import get_logger
            self._logger = get_logger("feedback.fact_collector")
        except ImportError:
            import logging
            self._logger = logging.getLogger("feedback.fact_collector")

    # =========================================================================
    # プロパティ
    # =========================================================================

    @property
    def conn(self) -> Connection:
        """データベース接続を取得"""
        return self._conn

    @property
    def org_id(self) -> UUID:
        """組織IDを取得"""
        return self._org_id

    # =========================================================================
    # メイン収集メソッド
    # =========================================================================

    async def collect_daily(
        self,
        target_date: Optional[date] = None,
    ) -> DailyFacts:
        """
        日次ファクトを収集

        指定された日付（デフォルトは今日）のファクトを収集し、
        DailyFacts としてまとめて返す。

        Args:
            target_date: 収集対象日（デフォルト: 今日）

        Returns:
            DailyFacts: 収集されたファクト

        Raises:
            FactCollectionError: 収集に失敗した場合
        """
        if target_date is None:
            target_date = date.today()

        self._logger.info(
            "Starting daily fact collection",
            extra={
                "organization_id": str(self._org_id),
                "target_date": target_date.isoformat(),
            }
        )

        try:
            # 1. ユーザー一覧を取得
            users = await self._get_organization_users()

            # 2. 各種ファクトを収集
            task_facts = await self._collect_task_facts(users, target_date)
            goal_facts = await self._collect_goal_facts(users, target_date)
            communication_facts = await self._collect_communication_facts(users, target_date)

            # 3. チーム全体のファクトを集計
            team_fact = await self._aggregate_team_fact(
                task_facts=task_facts,
                goal_facts=goal_facts,
                communication_facts=communication_facts,
                total_members=len(users),
            )

            # 4. 既存のインサイトを取得
            existing_insights = await self._get_existing_insights(target_date)

            # 5. DailyFactsを構築
            facts = DailyFacts(
                date=target_date,
                organization_id=str(self._org_id),
                task_facts=task_facts,
                goal_facts=goal_facts,
                communication_facts=communication_facts,
                team_fact=team_fact,
                existing_insights=existing_insights,
                collected_at=datetime.now(),
            )

            self._logger.info(
                "Daily fact collection completed",
                extra={
                    "organization_id": str(self._org_id),
                    "target_date": target_date.isoformat(),
                    "task_facts": len(task_facts),
                    "goal_facts": len(goal_facts),
                    "communication_facts": len(communication_facts),
                    "existing_insights": len(existing_insights),
                }
            )

            return facts

        except Exception as e:
            self._logger.error(
                "Daily fact collection failed",
                extra={
                    "organization_id": str(self._org_id),
                    "error": str(e),
                }
            )
            raise FactCollectionError(
                message="日次ファクト収集に失敗しました",
                source="collect_daily",
                details={"target_date": target_date.isoformat()},
                original_exception=e,
            )

    async def collect_weekly(
        self,
        week_start: Optional[date] = None,
    ) -> List[DailyFacts]:
        """
        週次ファクトを収集

        指定された週（デフォルトは今週）の各日のファクトを収集。

        Args:
            week_start: 週の開始日（月曜日）、デフォルトは今週

        Returns:
            List[DailyFacts]: 各日のファクトのリスト
        """
        if week_start is None:
            today = date.today()
            week_start = today - timedelta(days=today.weekday())

        weekly_facts = []
        for i in range(7):
            target_date = week_start + timedelta(days=i)
            if target_date <= date.today():
                daily_facts = await self.collect_daily(target_date)
                weekly_facts.append(daily_facts)

        return weekly_facts

    # =========================================================================
    # ユーザー取得
    # =========================================================================

    async def _get_organization_users(self) -> List[UserInfo]:
        """
        組織のユーザー一覧を取得

        Returns:
            List[UserInfo]: ユーザー情報のリスト
        """
        try:
            result = self._conn.execute(text("""
                SELECT
                    u.id,
                    u.name,
                    cu.chatwork_account_id,
                    ud.department_id,
                    d.name as department_name
                FROM users u
                LEFT JOIN chatwork_users cu ON u.id = cu.user_id
                LEFT JOIN user_departments ud ON u.id = ud.user_id
                    AND ud.is_primary = TRUE
                    AND ud.ended_at IS NULL
                LEFT JOIN departments d ON ud.department_id = d.id
                WHERE u.organization_id = :org_id
                  AND u.is_active = TRUE
                ORDER BY u.name
            """), {
                "org_id": str(self._org_id),
            })

            users = []
            for row in result.fetchall():
                users.append(UserInfo(
                    user_id=str(row[0]),
                    name=row[1] or "不明",
                    chatwork_account_id=str(row[2]) if row[2] else None,
                    department_id=str(row[3]) if row[3] else None,
                    department_name=row[4],
                ))

            return users

        except Exception as e:
            self._logger.warning(
                "Failed to get organization users",
                extra={
                    "organization_id": str(self._org_id),
                    "error": str(e),
                }
            )
            return []

    # =========================================================================
    # タスクファクト収集
    # =========================================================================

    async def _collect_task_facts(
        self,
        users: List[UserInfo],
        target_date: date,
    ) -> List[TaskFact]:
        """
        タスクに関するファクトを収集

        chatwork_tasks テーブルから各ユーザーのタスク状況を収集。

        Args:
            users: ユーザー情報のリスト
            target_date: 収集対象日

        Returns:
            List[TaskFact]: タスクファクトのリスト
        """
        task_facts = []

        for user in users:
            if not user.chatwork_account_id:
                continue

            try:
                fact = await self._get_user_task_fact(user, target_date)
                if fact:
                    task_facts.append(fact)
            except Exception as e:
                self._logger.warning(
                    "Failed to collect task fact for user",
                    extra={
                        "user_id": user.user_id,
                        "error": str(e),
                    }
                )

        return task_facts

    async def _get_user_task_fact(
        self,
        user: UserInfo,
        target_date: date,
    ) -> Optional[TaskFact]:
        """
        特定ユーザーのタスクファクトを取得

        Args:
            user: ユーザー情報
            target_date: 収集対象日

        Returns:
            TaskFact: タスクファクト（タスクがない場合はNone）
        """
        try:
            # 今日のタイムスタンプ範囲
            target_start = datetime.combine(target_date, datetime.min.time())
            target_end = datetime.combine(target_date + timedelta(days=1), datetime.min.time())
            target_start_ts = int(target_start.timestamp())
            target_end_ts = int(target_end.timestamp())

            # 滞留日数の閾値（UNIXタイムスタンプ）
            stale_threshold = datetime.now() - timedelta(days=self._stale_days)
            stale_threshold_ts = int(stale_threshold.timestamp())

            # タスク集計クエリ
            result = self._conn.execute(text("""
                SELECT
                    COUNT(*) as total_tasks,
                    COUNT(CASE WHEN status = 'done' THEN 1 END) as completed_tasks,
                    COUNT(CASE
                        WHEN status = 'open'
                         AND limit_time IS NOT NULL
                         AND limit_time < :today_ts
                        THEN 1
                    END) as overdue_tasks,
                    COUNT(CASE
                        WHEN status = 'open'
                         AND last_synced_at < :stale_threshold
                        THEN 1
                    END) as stale_tasks,
                    MAX(CASE
                        WHEN status = 'open'
                         AND limit_time IS NOT NULL
                         AND limit_time < :today_ts
                        THEN (:today_ts - limit_time) / 86400
                        ELSE 0
                    END) as oldest_overdue_days
                FROM chatwork_tasks
                WHERE assigned_to_account_id = :account_id
            """), {
                "account_id": user.chatwork_account_id,
                "today_ts": target_start_ts,
                "stale_threshold": stale_threshold,
            })

            row = result.fetchone()
            if row is None:
                return None

            total_tasks = row[0] or 0
            completed_tasks = row[1] or 0
            overdue_tasks = row[2] or 0
            stale_tasks = row[3] or 0
            oldest_overdue_days = int(row[4] or 0)

            # 今日作成・完了されたタスクを取得
            # （created_atカラムがない可能性があるため、try-catchで対応）
            tasks_created_today = 0
            tasks_completed_today = 0

            try:
                today_result = self._conn.execute(text("""
                    SELECT
                        COUNT(CASE
                            WHEN created_at >= :target_start AND created_at < :target_end
                            THEN 1
                        END) as created_today,
                        COUNT(CASE
                            WHEN completed_at >= :target_start AND completed_at < :target_end
                            THEN 1
                        END) as completed_today
                    FROM chatwork_tasks
                    WHERE assigned_to_account_id = :account_id
                """), {
                    "account_id": user.chatwork_account_id,
                    "target_start": target_start,
                    "target_end": target_end,
                })
                today_row = today_result.fetchone()
                if today_row:
                    tasks_created_today = today_row[0] or 0
                    tasks_completed_today = today_row[1] or 0
            except Exception:
                pass

            # タスクがない場合はスキップ
            if total_tasks == 0:
                return None

            return TaskFact(
                user_id=user.user_id,
                user_name=user.name,
                total_tasks=total_tasks,
                completed_tasks=completed_tasks,
                overdue_tasks=overdue_tasks,
                stale_tasks=stale_tasks,
                tasks_created_today=tasks_created_today,
                tasks_completed_today=tasks_completed_today,
                oldest_overdue_days=oldest_overdue_days,
            )

        except Exception as e:
            self._logger.warning(
                "Failed to get user task fact",
                extra={
                    "user_id": user.user_id,
                    "error": str(e),
                }
            )
            return None

    # =========================================================================
    # 目標ファクト収集
    # =========================================================================

    async def _collect_goal_facts(
        self,
        users: List[UserInfo],
        target_date: date,
    ) -> List[GoalFact]:
        """
        目標に関するファクトを収集

        goals テーブルから各ユーザーの目標状況を収集。

        Args:
            users: ユーザー情報のリスト
            target_date: 収集対象日

        Returns:
            List[GoalFact]: 目標ファクトのリスト
        """
        goal_facts = []

        try:
            # アクティブな目標を取得
            result = self._conn.execute(text("""
                SELECT
                    g.id,
                    g.user_id,
                    u.name as user_name,
                    g.title,
                    g.target_value,
                    g.current_value,
                    g.deadline,
                    g.period_end,
                    g.updated_at
                FROM goals g
                JOIN users u ON g.user_id = u.id
                WHERE g.organization_id = :org_id
                  AND g.status = 'active'
                  AND (g.period_end IS NULL OR g.period_end >= :target_date)
                ORDER BY g.user_id, g.deadline
            """), {
                "org_id": str(self._org_id),
                "target_date": target_date,
            })

            for row in result.fetchall():
                goal_id = str(row[0])
                user_id = str(row[1])
                user_name = row[2] or "不明"
                title = row[3]
                target_value = float(row[4]) if row[4] else 0.0
                current_value = float(row[5]) if row[5] else 0.0
                deadline = row[6]
                period_end = row[7]
                updated_at = row[8]

                # 進捗率を計算
                progress_rate = 0.0
                if target_value > 0:
                    progress_rate = current_value / target_value

                # 残り日数を計算
                days_remaining = 0
                effective_deadline = deadline or period_end
                if effective_deadline:
                    days_remaining = (effective_deadline - target_date).days

                # トレンドを判定（簡易版: 前回更新からの変化で判定）
                trend = TrendDirection.STABLE
                if updated_at:
                    days_since_update = (datetime.now() - updated_at).days
                    if days_since_update > 7:
                        trend = TrendDirection.STABLE  # 更新がない

                goal_facts.append(GoalFact(
                    user_id=user_id,
                    user_name=user_name,
                    goal_id=goal_id,
                    goal_title=title,
                    target_value=target_value,
                    current_value=current_value,
                    progress_rate=progress_rate,
                    days_remaining=days_remaining,
                    trend=trend,
                    last_updated=updated_at,
                ))

        except Exception as e:
            self._logger.warning(
                "Failed to collect goal facts",
                extra={
                    "organization_id": str(self._org_id),
                    "error": str(e),
                }
            )

        return goal_facts

    # =========================================================================
    # コミュニケーションファクト収集
    # =========================================================================

    async def _collect_communication_facts(
        self,
        users: List[UserInfo],
        target_date: date,
    ) -> List[CommunicationFact]:
        """
        コミュニケーションに関するファクトを収集

        会話ログからメッセージ数、感情スコアなどを収集。

        Args:
            users: ユーザー情報のリスト
            target_date: 収集対象日

        Returns:
            List[CommunicationFact]: コミュニケーションファクトのリスト
        """
        communication_facts = []

        # 日付範囲
        target_start = datetime.combine(target_date, datetime.min.time())
        target_end = datetime.combine(target_date + timedelta(days=1), datetime.min.time())
        week_start = target_date - timedelta(days=7)

        for user in users:
            try:
                fact = await self._get_user_communication_fact(
                    user=user,
                    target_start=target_start,
                    target_end=target_end,
                    week_start=week_start,
                )
                if fact:
                    communication_facts.append(fact)
            except Exception as e:
                self._logger.warning(
                    "Failed to collect communication fact for user",
                    extra={
                        "user_id": user.user_id,
                        "error": str(e),
                    }
                )

        return communication_facts

    async def _get_user_communication_fact(
        self,
        user: UserInfo,
        target_start: datetime,
        target_end: datetime,
        week_start: date,
    ) -> Optional[CommunicationFact]:
        """
        特定ユーザーのコミュニケーションファクトを取得

        Args:
            user: ユーザー情報
            target_start: 対象日開始
            target_end: 対象日終了
            week_start: 週の開始日

        Returns:
            CommunicationFact: コミュニケーションファクト
        """
        try:
            # conversation_logsからメッセージ数を集計
            # （テーブルが存在しない場合はデフォルト値を使用）
            message_count_today = 0
            message_count_week = 0
            sentiment_score = 0.0
            question_count = 0

            try:
                result = self._conn.execute(text("""
                    SELECT
                        COUNT(CASE
                            WHEN created_at >= :target_start AND created_at < :target_end
                            THEN 1
                        END) as count_today,
                        COUNT(CASE
                            WHEN created_at >= :week_start
                            THEN 1
                        END) as count_week
                    FROM conversation_logs
                    WHERE organization_id = :org_id
                      AND user_id = :user_id
                """), {
                    "org_id": str(self._org_id),
                    "user_id": user.user_id,
                    "target_start": target_start,
                    "target_end": target_end,
                    "week_start": week_start,
                })
                row = result.fetchone()
                if row:
                    message_count_today = row[0] or 0
                    message_count_week = row[1] or 0
            except Exception:
                # conversation_logsテーブルが存在しない場合はスキップ
                pass

            # 感情スコアを取得（Phase 2 A4 emotion_detectionの結果）
            try:
                emotion_result = self._conn.execute(text("""
                    SELECT
                        AVG(COALESCE((evidence->>'sentiment_score')::float, 0)) as avg_sentiment
                    FROM soulkun_insights
                    WHERE organization_id = :org_id
                      AND source_type = 'a4_emotion'
                      AND (evidence->>'user_id')::text = :user_id
                      AND created_at >= :week_start
                """), {
                    "org_id": str(self._org_id),
                    "user_id": user.user_id,
                    "week_start": week_start,
                })
                emotion_row = emotion_result.fetchone()
                if emotion_row and emotion_row[0]:
                    sentiment_score = float(emotion_row[0])
            except Exception:
                pass

            # メッセージ数がゼロの場合はスキップ
            if message_count_today == 0 and message_count_week == 0:
                return None

            # 感情トレンドを判定
            sentiment_trend = TrendDirection.STABLE
            if sentiment_score < -0.3:
                sentiment_trend = TrendDirection.DECREASING
            elif sentiment_score > 0.3:
                sentiment_trend = TrendDirection.INCREASING

            return CommunicationFact(
                user_id=user.user_id,
                user_name=user.name,
                message_count_today=message_count_today,
                message_count_week=message_count_week,
                sentiment_score=sentiment_score,
                sentiment_trend=sentiment_trend,
                question_count=question_count,
            )

        except Exception as e:
            self._logger.warning(
                "Failed to get user communication fact",
                extra={
                    "user_id": user.user_id,
                    "error": str(e),
                }
            )
            return None

    # =========================================================================
    # チームファクト集計
    # =========================================================================

    async def _aggregate_team_fact(
        self,
        task_facts: List[TaskFact],
        goal_facts: List[GoalFact],
        communication_facts: List[CommunicationFact],
        total_members: int,
    ) -> TeamFact:
        """
        チーム全体のファクトを集計

        Args:
            task_facts: タスクファクトのリスト
            goal_facts: 目標ファクトのリスト
            communication_facts: コミュニケーションファクトのリスト
            total_members: 総メンバー数

        Returns:
            TeamFact: チーム全体のファクト
        """
        # タスク完了率の集計
        total_completion_rate = 0.0
        total_overdue_tasks = 0
        active_members = set()

        for tf in task_facts:
            total_completion_rate += tf.completion_rate
            total_overdue_tasks += tf.overdue_tasks
            if tf.tasks_completed_today > 0 or tf.tasks_created_today > 0:
                active_members.add(tf.user_id)

        avg_task_completion_rate = 0.0
        if task_facts:
            avg_task_completion_rate = total_completion_rate / len(task_facts)

        # リスクのある目標数
        total_goals_at_risk = sum(1 for gf in goal_facts if gf.is_at_risk)

        # コミュニケーションからアクティブメンバーを追加
        for cf in communication_facts:
            if cf.message_count_today > 0:
                active_members.add(cf.user_id)

        # トップパフォーマー（タスク完了率が高いユーザー）
        top_performers = []
        sorted_by_completion = sorted(
            task_facts,
            key=lambda x: x.completion_rate,
            reverse=True
        )
        for tf in sorted_by_completion[:3]:
            if tf.completion_rate >= 0.8:
                top_performers.append(tf.user_name)

        # 注意が必要なメンバー（期限超過や滞留タスクが多いユーザー）
        members_needing_attention = []
        for tf in task_facts:
            if tf.overdue_tasks >= 3 or tf.stale_tasks >= 5:
                members_needing_attention.append(tf.user_name)

        # 感情面で気になるメンバーも追加
        for cf in communication_facts:
            if cf.is_sentiment_concerning and cf.user_name not in members_needing_attention:
                members_needing_attention.append(cf.user_name)

        return TeamFact(
            organization_id=str(self._org_id),
            total_members=total_members,
            active_members=len(active_members),
            avg_task_completion_rate=avg_task_completion_rate,
            total_overdue_tasks=total_overdue_tasks,
            total_goals_at_risk=total_goals_at_risk,
            top_performers=top_performers[:3],
            members_needing_attention=members_needing_attention[:5],
        )

    # =========================================================================
    # 既存インサイト取得
    # =========================================================================

    async def _get_existing_insights(
        self,
        target_date: date,
    ) -> List[Dict[str, Any]]:
        """
        既存のインサイト（A1-A4で検出されたもの）を取得

        Args:
            target_date: 収集対象日

        Returns:
            List[Dict[str, Any]]: インサイトのリスト
        """
        try:
            # 過去7日間のインサイトを取得
            week_start = target_date - timedelta(days=7)

            result = self._conn.execute(text("""
                SELECT
                    id,
                    insight_type,
                    source_type,
                    importance,
                    title,
                    description,
                    recommended_action,
                    evidence,
                    status,
                    created_at
                FROM soulkun_insights
                WHERE organization_id = :org_id
                  AND created_at >= :week_start
                  AND status IN ('new', 'acknowledged')
                ORDER BY
                    CASE importance
                        WHEN 'critical' THEN 1
                        WHEN 'high' THEN 2
                        WHEN 'medium' THEN 3
                        ELSE 4
                    END,
                    created_at DESC
                LIMIT 50
            """), {
                "org_id": str(self._org_id),
                "week_start": week_start,
            })

            insights = []
            for row in result.fetchall():
                insights.append({
                    "id": str(row[0]),
                    "insight_type": row[1],
                    "source_type": row[2],
                    "importance": row[3],
                    "title": row[4],
                    "description": row[5],
                    "recommended_action": row[6],
                    "evidence": row[7] if row[7] else {},
                    "status": row[8],
                    "created_at": row[9].isoformat() if row[9] else None,
                })

            return insights

        except Exception as e:
            self._logger.warning(
                "Failed to get existing insights",
                extra={
                    "organization_id": str(self._org_id),
                    "error": str(e),
                }
            )
            return []


# =============================================================================
# ファクトリー関数
# =============================================================================


def create_fact_collector(
    conn: Connection,
    org_id: UUID,
    stale_days: int = AnalysisParameters.TASK_STALE_DAYS,
) -> FactCollector:
    """
    FactCollectorを作成

    Args:
        conn: データベース接続
        org_id: 組織ID
        stale_days: タスク滞留と判定する日数

    Returns:
        FactCollector: ファクト収集エンジン
    """
    return FactCollector(
        conn=conn,
        org_id=org_id,
        stale_days=stale_days,
    )
