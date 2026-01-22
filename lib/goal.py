"""
Goal Management Service

目標達成支援用のサービス層（Phase 2.5）

設計書: docs/05_phase2-5_goal_achievement.md (v1.5)

使用例（Flask/Cloud Functions）:
    from lib.goal import GoalService

    service = GoalService()
    goal = await service.create_goal(
        organization_id=org_id,
        user_id=user_id,
        title="粗利300万円",
        goal_type="numeric",
        target_value=3000000,
        unit="円",
        period_type="monthly",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
    )
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from enum import Enum
from typing import Optional, List, Dict, Any, Tuple
from uuid import UUID, uuid4
import logging

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from lib.db import get_db_pool

logger = logging.getLogger(__name__)


# =============================================================================
# 定数定義
# =============================================================================

class GoalLevel(str, Enum):
    """目標レベル"""
    COMPANY = "company"       # 会社目標
    DEPARTMENT = "department" # 部署目標
    INDIVIDUAL = "individual" # 個人目標


class GoalType(str, Enum):
    """目標タイプ"""
    NUMERIC = "numeric"   # 数値目標（粗利300万円、獲得10件など）
    DEADLINE = "deadline" # 期限目標（○月○日までに完了）
    ACTION = "action"     # 行動目標（毎日○○をする）


class GoalStatus(str, Enum):
    """目標ステータス"""
    ACTIVE = "active"       # アクティブ
    COMPLETED = "completed" # 完了
    CANCELLED = "cancelled" # キャンセル


class PeriodType(str, Enum):
    """期間タイプ"""
    YEARLY = "yearly"       # 年次
    QUARTERLY = "quarterly" # 四半期
    MONTHLY = "monthly"     # 月次
    WEEKLY = "weekly"       # 週次


class Classification(str, Enum):
    """機密区分（4段階）"""
    PUBLIC = "public"           # 公開
    INTERNAL = "internal"       # 社内限定（デフォルト）
    CONFIDENTIAL = "confidential" # 機密
    RESTRICTED = "restricted"   # 極秘


class ReminderType(str, Enum):
    """リマインドタイプ"""
    DAILY_CHECK = "daily_check"         # 17時進捗確認
    DAILY_REMINDER = "daily_reminder"   # 18時未回答リマインド
    MORNING_FEEDBACK = "morning_feedback" # 8時個人フィードバック
    TEAM_SUMMARY = "team_summary"       # 8時チームサマリー


# =============================================================================
# データクラス
# =============================================================================

class Goal:
    """目標データクラス"""

    def __init__(
        self,
        id: UUID,
        organization_id: UUID,
        user_id: UUID,
        title: str,
        goal_type: GoalType,
        period_start: date,
        period_end: date,
        department_id: Optional[UUID] = None,
        parent_goal_id: Optional[UUID] = None,
        goal_level: GoalLevel = GoalLevel.INDIVIDUAL,
        description: Optional[str] = None,
        target_value: Optional[Decimal] = None,
        current_value: Optional[Decimal] = None,
        unit: Optional[str] = None,
        deadline: Optional[date] = None,
        period_type: PeriodType = PeriodType.MONTHLY,
        status: GoalStatus = GoalStatus.ACTIVE,
        classification: Classification = Classification.INTERNAL,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
        created_by: Optional[UUID] = None,
        updated_by: Optional[UUID] = None,
    ):
        self.id = id
        self.organization_id = organization_id
        self.user_id = user_id
        self.department_id = department_id
        self.parent_goal_id = parent_goal_id
        self.goal_level = goal_level
        self.title = title
        self.description = description
        self.goal_type = goal_type
        self.target_value = target_value
        self.current_value = current_value or Decimal(0)
        self.unit = unit
        self.deadline = deadline
        self.period_type = period_type
        self.period_start = period_start
        self.period_end = period_end
        self.status = status
        self.classification = classification
        self.created_at = created_at
        self.updated_at = updated_at
        self.created_by = created_by
        self.updated_by = updated_by

    @property
    def achievement_rate(self) -> float:
        """達成率を計算（数値目標の場合）"""
        if self.goal_type != GoalType.NUMERIC or not self.target_value:
            return 0.0
        if self.target_value == 0:
            return 0.0
        return float((self.current_value or 0) / self.target_value * 100)

    @property
    def remaining_value(self) -> Optional[Decimal]:
        """残り目標値を計算（数値目標の場合）"""
        if self.goal_type != GoalType.NUMERIC or not self.target_value:
            return None
        return self.target_value - (self.current_value or Decimal(0))

    @property
    def days_remaining(self) -> int:
        """残り日数を計算"""
        today = date.today()
        return (self.period_end - today).days

    def to_dict(self) -> Dict[str, Any]:
        """辞書に変換"""
        return {
            "id": str(self.id),
            "organization_id": str(self.organization_id),
            "user_id": str(self.user_id),
            "department_id": str(self.department_id) if self.department_id else None,
            "parent_goal_id": str(self.parent_goal_id) if self.parent_goal_id else None,
            "goal_level": self.goal_level.value,
            "title": self.title,
            "description": self.description,
            "goal_type": self.goal_type.value,
            "target_value": float(self.target_value) if self.target_value else None,
            "current_value": float(self.current_value) if self.current_value else None,
            "unit": self.unit,
            "deadline": self.deadline.isoformat() if self.deadline else None,
            "period_type": self.period_type.value,
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "status": self.status.value,
            "classification": self.classification.value,
            "achievement_rate": self.achievement_rate,
            "remaining_value": float(self.remaining_value) if self.remaining_value else None,
            "days_remaining": self.days_remaining,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class GoalProgress:
    """進捗記録データクラス"""

    def __init__(
        self,
        id: UUID,
        goal_id: UUID,
        organization_id: UUID,
        progress_date: date,
        value: Optional[Decimal] = None,
        cumulative_value: Optional[Decimal] = None,
        daily_note: Optional[str] = None,
        daily_choice: Optional[str] = None,
        ai_feedback: Optional[str] = None,
        ai_feedback_sent_at: Optional[datetime] = None,
        classification: Classification = Classification.INTERNAL,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
        created_by: Optional[UUID] = None,
        updated_by: Optional[UUID] = None,
    ):
        self.id = id
        self.goal_id = goal_id
        self.organization_id = organization_id
        self.progress_date = progress_date
        self.value = value
        self.cumulative_value = cumulative_value
        self.daily_note = daily_note
        self.daily_choice = daily_choice
        self.ai_feedback = ai_feedback
        self.ai_feedback_sent_at = ai_feedback_sent_at
        self.classification = classification
        self.created_at = created_at
        self.updated_at = updated_at
        self.created_by = created_by
        self.updated_by = updated_by

    def to_dict(self) -> Dict[str, Any]:
        """辞書に変換"""
        return {
            "id": str(self.id),
            "goal_id": str(self.goal_id),
            "organization_id": str(self.organization_id),
            "progress_date": self.progress_date.isoformat(),
            "value": float(self.value) if self.value else None,
            "cumulative_value": float(self.cumulative_value) if self.cumulative_value else None,
            "daily_note": self.daily_note,
            "daily_choice": self.daily_choice,
            "ai_feedback": self.ai_feedback,
            "ai_feedback_sent_at": self.ai_feedback_sent_at.isoformat() if self.ai_feedback_sent_at else None,
            "classification": self.classification.value,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# =============================================================================
# ヘルパー関数
# =============================================================================

def parse_goal_type_from_text(text: str) -> Tuple[GoalType, Optional[Decimal], Optional[str]]:
    """
    テキストから目標タイプ、目標値、単位を抽出

    例:
        "粗利300万円" -> (NUMERIC, 3000000, "円")
        "月末までに納品" -> (DEADLINE, None, None)
        "毎日日報を書く" -> (ACTION, None, None)
    """
    # 数値目標のパターン
    numeric_patterns = [
        # 「〇〇万円」
        (r'(\d+(?:\.\d+)?)\s*万円', lambda m: Decimal(m.group(1)) * 10000, "円"),
        # 「〇〇円」
        (r'(\d+(?:,\d{3})*)\s*円', lambda m: Decimal(m.group(1).replace(",", "")), "円"),
        # 「〇〇件」
        (r'(\d+)\s*件', lambda m: Decimal(m.group(1)), "件"),
        # 「〇〇人」
        (r'(\d+)\s*人', lambda m: Decimal(m.group(1)), "人"),
        # 「〇〇%」
        (r'(\d+(?:\.\d+)?)\s*[%％]', lambda m: Decimal(m.group(1)), "%"),
    ]

    for pattern, value_func, unit in numeric_patterns:
        match = re.search(pattern, text)
        if match:
            return GoalType.NUMERIC, value_func(match), unit

    # 行動目標のパターン
    action_patterns = [
        r'^毎日',
        r'^毎週',
        r'^毎月',
        r'日課',
        r'習慣',
        r'継続',
    ]

    for pattern in action_patterns:
        if re.search(pattern, text):
            return GoalType.ACTION, None, None

    # 期限目標のパターン
    deadline_patterns = [
        r'までに',
        r'完了',
        r'完成',
        r'納品',
        r'リリース',
        r'提出',
    ]

    for pattern in deadline_patterns:
        if re.search(pattern, text):
            return GoalType.DEADLINE, None, None

    # デフォルトは行動目標
    return GoalType.ACTION, None, None


def calculate_period_from_type(
    period_type: PeriodType,
    reference_date: Optional[date] = None,
) -> Tuple[date, date]:
    """
    期間タイプから開始日と終了日を計算

    Args:
        period_type: 期間タイプ
        reference_date: 基準日（デフォルトは今日）

    Returns:
        (period_start, period_end)
    """
    ref = reference_date or date.today()

    if period_type == PeriodType.WEEKLY:
        # 今週の月曜から日曜
        start = ref - timedelta(days=ref.weekday())
        end = start + timedelta(days=6)
    elif period_type == PeriodType.MONTHLY:
        # 今月の1日から末日
        start = ref.replace(day=1)
        if ref.month == 12:
            end = ref.replace(year=ref.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            end = ref.replace(month=ref.month + 1, day=1) - timedelta(days=1)
    elif period_type == PeriodType.QUARTERLY:
        # 今四半期の開始から終了
        quarter = (ref.month - 1) // 3
        start = ref.replace(month=quarter * 3 + 1, day=1)
        if quarter == 3:
            end = ref.replace(year=ref.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            end = ref.replace(month=(quarter + 1) * 3 + 1, day=1) - timedelta(days=1)
    else:  # YEARLY
        # 今年の1月1日から12月31日
        start = ref.replace(month=1, day=1)
        end = ref.replace(month=12, day=31)

    return start, end


# =============================================================================
# GoalService クラス
# =============================================================================

class GoalService:
    """
    目標管理サービス

    使用例:
        service = GoalService()

        # 目標登録
        goal = service.create_goal(
            organization_id=org_id,
            user_id=user_id,
            title="粗利300万円",
            goal_type=GoalType.NUMERIC,
            target_value=Decimal(3000000),
            unit="円",
            period_type=PeriodType.MONTHLY,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )

        # 進捗記録
        progress = service.record_progress(
            goal_id=goal.id,
            organization_id=org_id,
            progress_date=date.today(),
            value=Decimal(50000),
            daily_note="今日は1件成約した",
            user_id=user_id,
        )
    """

    def __init__(self, pool=None):
        """
        Args:
            pool: SQLAlchemy connection pool（省略時は自動取得）
        """
        self._pool = pool

    @property
    def pool(self):
        if self._pool is None:
            self._pool = get_db_pool()
        return self._pool

    # -------------------------------------------------------------------------
    # 目標管理
    # -------------------------------------------------------------------------

    def create_goal(
        self,
        organization_id: UUID,
        user_id: UUID,
        title: str,
        goal_type: GoalType,
        period_start: date,
        period_end: date,
        department_id: Optional[UUID] = None,
        parent_goal_id: Optional[UUID] = None,
        goal_level: GoalLevel = GoalLevel.INDIVIDUAL,
        description: Optional[str] = None,
        target_value: Optional[Decimal] = None,
        unit: Optional[str] = None,
        deadline: Optional[date] = None,
        period_type: PeriodType = PeriodType.MONTHLY,
        classification: Classification = Classification.INTERNAL,
        created_by: Optional[UUID] = None,
    ) -> Goal:
        """
        目標を登録

        Args:
            organization_id: テナントID
            user_id: 目標の所有者
            title: 目標タイトル
            goal_type: 目標タイプ
            period_start: 期間開始日
            period_end: 期間終了日
            その他: オプション

        Returns:
            Goal: 作成された目標
        """
        goal_id = uuid4()

        with self.pool.connect() as conn:
            conn.execute(
                text("""
                    INSERT INTO goals (
                        id, organization_id, user_id, department_id, parent_goal_id,
                        goal_level, title, description, goal_type, target_value,
                        current_value, unit, deadline, period_type, period_start,
                        period_end, status, classification, created_by, updated_by
                    ) VALUES (
                        :id, :organization_id, :user_id, :department_id, :parent_goal_id,
                        :goal_level, :title, :description, :goal_type, :target_value,
                        0, :unit, :deadline, :period_type, :period_start,
                        :period_end, 'active', :classification, :created_by, :created_by
                    )
                """),
                {
                    "id": str(goal_id),
                    "organization_id": str(organization_id),
                    "user_id": str(user_id),
                    "department_id": str(department_id) if department_id else None,
                    "parent_goal_id": str(parent_goal_id) if parent_goal_id else None,
                    "goal_level": goal_level.value if isinstance(goal_level, GoalLevel) else goal_level,
                    "title": title,
                    "description": description,
                    "goal_type": goal_type.value if isinstance(goal_type, GoalType) else goal_type,
                    "target_value": float(target_value) if target_value else None,
                    "unit": unit,
                    "deadline": deadline,
                    "period_type": period_type.value if isinstance(period_type, PeriodType) else period_type,
                    "period_start": period_start,
                    "period_end": period_end,
                    "classification": classification.value if isinstance(classification, Classification) else classification,
                    "created_by": str(created_by) if created_by else str(user_id),
                },
            )
            conn.commit()

        logger.info(f"Goal created: id={goal_id}, title={title}, user_id={user_id}")

        return Goal(
            id=goal_id,
            organization_id=organization_id,
            user_id=user_id,
            department_id=department_id,
            parent_goal_id=parent_goal_id,
            goal_level=goal_level,
            title=title,
            description=description,
            goal_type=goal_type,
            target_value=target_value,
            current_value=Decimal(0),
            unit=unit,
            deadline=deadline,
            period_type=period_type,
            period_start=period_start,
            period_end=period_end,
            status=GoalStatus.ACTIVE,
            classification=classification,
            created_at=datetime.now(),
            created_by=created_by or user_id,
        )

    def get_goal(self, goal_id: UUID, organization_id: UUID) -> Optional[Goal]:
        """目標を取得"""
        with self.pool.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT * FROM goals
                    WHERE id = :id AND organization_id = :organization_id
                """),
                {"id": str(goal_id), "organization_id": str(organization_id)},
            ).fetchone()

        if not result:
            return None

        return self._row_to_goal(result)

    def get_goals_for_user(
        self,
        user_id: UUID,
        organization_id: UUID,
        status: Optional[GoalStatus] = None,
        period_start: Optional[date] = None,
        period_end: Optional[date] = None,
    ) -> List[Goal]:
        """ユーザーの目標一覧を取得"""
        query = """
            SELECT * FROM goals
            WHERE user_id = :user_id AND organization_id = :organization_id
        """
        params = {
            "user_id": str(user_id),
            "organization_id": str(organization_id),
        }

        if status:
            query += " AND status = :status"
            params["status"] = status.value if isinstance(status, GoalStatus) else status

        if period_start:
            query += " AND period_end >= :period_start"
            params["period_start"] = period_start

        if period_end:
            query += " AND period_start <= :period_end"
            params["period_end"] = period_end

        query += " ORDER BY period_start DESC, created_at DESC"

        with self.pool.connect() as conn:
            results = conn.execute(text(query), params).fetchall()

        return [self._row_to_goal(row) for row in results]

    def get_active_goals_for_user(
        self,
        user_id: UUID,
        organization_id: UUID,
    ) -> List[Goal]:
        """ユーザーのアクティブな目標を取得"""
        return self.get_goals_for_user(
            user_id=user_id,
            organization_id=organization_id,
            status=GoalStatus.ACTIVE,
        )

    def update_goal_current_value(
        self,
        goal_id: UUID,
        organization_id: UUID,
        current_value: Decimal,
        updated_by: Optional[UUID] = None,
    ) -> bool:
        """目標の現在値を更新"""
        with self.pool.connect() as conn:
            result = conn.execute(
                text("""
                    UPDATE goals
                    SET current_value = :current_value,
                        updated_at = CURRENT_TIMESTAMP,
                        updated_by = :updated_by
                    WHERE id = :id AND organization_id = :organization_id
                """),
                {
                    "id": str(goal_id),
                    "organization_id": str(organization_id),
                    "current_value": float(current_value),
                    "updated_by": str(updated_by) if updated_by else None,
                },
            )
            conn.commit()

        return result.rowcount > 0

    def complete_goal(
        self,
        goal_id: UUID,
        organization_id: UUID,
        updated_by: Optional[UUID] = None,
    ) -> bool:
        """目標を完了"""
        with self.pool.connect() as conn:
            result = conn.execute(
                text("""
                    UPDATE goals
                    SET status = 'completed',
                        updated_at = CURRENT_TIMESTAMP,
                        updated_by = :updated_by
                    WHERE id = :id AND organization_id = :organization_id
                """),
                {
                    "id": str(goal_id),
                    "organization_id": str(organization_id),
                    "updated_by": str(updated_by) if updated_by else None,
                },
            )
            conn.commit()

        return result.rowcount > 0

    # -------------------------------------------------------------------------
    # 進捗管理
    # -------------------------------------------------------------------------

    def record_progress(
        self,
        goal_id: UUID,
        organization_id: UUID,
        progress_date: date,
        value: Optional[Decimal] = None,
        daily_note: Optional[str] = None,
        daily_choice: Optional[str] = None,
        user_id: Optional[UUID] = None,
    ) -> GoalProgress:
        """
        進捗を記録（UPSERT）

        同日に複数回呼び出された場合は上書き。
        """
        progress_id = uuid4()

        # 累計値を計算
        cumulative_value = None
        if value is not None:
            with self.pool.connect() as conn:
                result = conn.execute(
                    text("""
                        SELECT COALESCE(SUM(value), 0) as total
                        FROM goal_progress
                        WHERE goal_id = :goal_id
                          AND organization_id = :organization_id
                          AND progress_date < :progress_date
                    """),
                    {
                        "goal_id": str(goal_id),
                        "organization_id": str(organization_id),
                        "progress_date": progress_date,
                    },
                ).fetchone()

                previous_total = Decimal(str(result[0])) if result else Decimal(0)
                cumulative_value = previous_total + value

        # UPSERT
        with self.pool.connect() as conn:
            conn.execute(
                text("""
                    INSERT INTO goal_progress (
                        id, goal_id, organization_id, progress_date, value,
                        cumulative_value, daily_note, daily_choice, classification,
                        created_by, updated_by
                    ) VALUES (
                        :id, :goal_id, :organization_id, :progress_date, :value,
                        :cumulative_value, :daily_note, :daily_choice, 'internal',
                        :created_by, :created_by
                    )
                    ON CONFLICT (goal_id, progress_date)
                    DO UPDATE SET
                        value = EXCLUDED.value,
                        cumulative_value = EXCLUDED.cumulative_value,
                        daily_note = EXCLUDED.daily_note,
                        daily_choice = EXCLUDED.daily_choice,
                        updated_at = CURRENT_TIMESTAMP,
                        updated_by = EXCLUDED.created_by
                """),
                {
                    "id": str(progress_id),
                    "goal_id": str(goal_id),
                    "organization_id": str(organization_id),
                    "progress_date": progress_date,
                    "value": float(value) if value is not None else None,
                    "cumulative_value": float(cumulative_value) if cumulative_value is not None else None,
                    "daily_note": daily_note,
                    "daily_choice": daily_choice,
                    "created_by": str(user_id) if user_id else None,
                },
            )
            conn.commit()

            # 目標のcurrent_valueも更新
            if cumulative_value is not None:
                conn.execute(
                    text("""
                        UPDATE goals
                        SET current_value = :cumulative_value,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = :goal_id AND organization_id = :organization_id
                    """),
                    {
                        "goal_id": str(goal_id),
                        "organization_id": str(organization_id),
                        "cumulative_value": float(cumulative_value),
                    },
                )
                conn.commit()

        logger.info(f"Progress recorded: goal_id={goal_id}, date={progress_date}, value={value}")

        return GoalProgress(
            id=progress_id,
            goal_id=goal_id,
            organization_id=organization_id,
            progress_date=progress_date,
            value=value,
            cumulative_value=cumulative_value,
            daily_note=daily_note,
            daily_choice=daily_choice,
            classification=Classification.INTERNAL,
            created_at=datetime.now(),
            created_by=user_id,
        )

    def get_progress_for_goal(
        self,
        goal_id: UUID,
        organization_id: UUID,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> List[GoalProgress]:
        """目標の進捗一覧を取得"""
        query = """
            SELECT * FROM goal_progress
            WHERE goal_id = :goal_id AND organization_id = :organization_id
        """
        params = {
            "goal_id": str(goal_id),
            "organization_id": str(organization_id),
        }

        if start_date:
            query += " AND progress_date >= :start_date"
            params["start_date"] = start_date

        if end_date:
            query += " AND progress_date <= :end_date"
            params["end_date"] = end_date

        query += " ORDER BY progress_date DESC"

        with self.pool.connect() as conn:
            results = conn.execute(text(query), params).fetchall()

        return [self._row_to_progress(row) for row in results]

    def get_today_progress(
        self,
        goal_id: UUID,
        organization_id: UUID,
    ) -> Optional[GoalProgress]:
        """今日の進捗を取得"""
        today = date.today()

        with self.pool.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT * FROM goal_progress
                    WHERE goal_id = :goal_id
                      AND organization_id = :organization_id
                      AND progress_date = :progress_date
                """),
                {
                    "goal_id": str(goal_id),
                    "organization_id": str(organization_id),
                    "progress_date": today,
                },
            ).fetchone()

        if not result:
            return None

        return self._row_to_progress(result)

    def save_ai_feedback(
        self,
        goal_id: UUID,
        organization_id: UUID,
        progress_date: date,
        ai_feedback: str,
        user_id: Optional[UUID] = None,
    ) -> bool:
        """
        AIフィードバックを保存（confidentialに昇格）

        CLAUDE.md鉄則#3: confidential以上の操作では監査ログを記録
        """
        with self.pool.connect() as conn:
            result = conn.execute(
                text("""
                    UPDATE goal_progress
                    SET ai_feedback = :ai_feedback,
                        ai_feedback_sent_at = CURRENT_TIMESTAMP,
                        classification = 'confidential',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE goal_id = :goal_id
                      AND organization_id = :organization_id
                      AND progress_date = :progress_date
                """),
                {
                    "goal_id": str(goal_id),
                    "organization_id": str(organization_id),
                    "progress_date": progress_date,
                    "ai_feedback": ai_feedback,
                },
            )

            # 監査ログを記録（CLAUDE.md鉄則#3: confidential操作の監査）
            if result.rowcount > 0:
                # goal_progress_idを取得
                progress_result = conn.execute(
                    text("""
                        SELECT id FROM goal_progress
                        WHERE goal_id = :goal_id
                          AND organization_id = :organization_id
                          AND progress_date = :progress_date
                    """),
                    {
                        "goal_id": str(goal_id),
                        "organization_id": str(organization_id),
                        "progress_date": progress_date,
                    },
                )
                progress_row = progress_result.fetchone()
                progress_id = str(progress_row[0]) if progress_row else None

                conn.execute(
                    text("""
                        INSERT INTO audit_logs (
                            organization_id, user_id, action, resource_type,
                            resource_id, classification, details, created_at
                        ) VALUES (
                            :org_id, :user_id, 'update', 'goal_progress',
                            :resource_id, 'confidential',
                            :details::jsonb, CURRENT_TIMESTAMP
                        )
                    """),
                    {
                        "org_id": str(organization_id),
                        "user_id": str(user_id) if user_id else None,
                        "resource_id": progress_id,
                        "details": f'{{"goal_id": "{goal_id}", "progress_date": "{progress_date}", "action": "save_ai_feedback", "classification_change": "internal->confidential"}}',
                    },
                )

            conn.commit()

        return result.rowcount > 0

    # -------------------------------------------------------------------------
    # ヘルパーメソッド
    # -------------------------------------------------------------------------

    def _row_to_goal(self, row) -> Goal:
        """DBの行をGoalオブジェクトに変換"""
        return Goal(
            id=UUID(row.id) if isinstance(row.id, str) else row.id,
            organization_id=UUID(row.organization_id) if isinstance(row.organization_id, str) else row.organization_id,
            user_id=UUID(row.user_id) if isinstance(row.user_id, str) else row.user_id,
            department_id=UUID(row.department_id) if row.department_id and isinstance(row.department_id, str) else row.department_id,
            parent_goal_id=UUID(row.parent_goal_id) if row.parent_goal_id and isinstance(row.parent_goal_id, str) else row.parent_goal_id,
            goal_level=GoalLevel(row.goal_level) if row.goal_level else GoalLevel.INDIVIDUAL,
            title=row.title,
            description=row.description,
            goal_type=GoalType(row.goal_type) if row.goal_type else GoalType.ACTION,
            target_value=Decimal(str(row.target_value)) if row.target_value else None,
            current_value=Decimal(str(row.current_value)) if row.current_value else Decimal(0),
            unit=row.unit,
            deadline=row.deadline,
            period_type=PeriodType(row.period_type) if row.period_type else PeriodType.MONTHLY,
            period_start=row.period_start,
            period_end=row.period_end,
            status=GoalStatus(row.status) if row.status else GoalStatus.ACTIVE,
            classification=Classification(row.classification) if row.classification else Classification.INTERNAL,
            created_at=row.created_at,
            updated_at=row.updated_at,
            created_by=UUID(row.created_by) if row.created_by and isinstance(row.created_by, str) else row.created_by,
            updated_by=UUID(row.updated_by) if row.updated_by and isinstance(row.updated_by, str) else row.updated_by,
        )

    def _row_to_progress(self, row) -> GoalProgress:
        """DBの行をGoalProgressオブジェクトに変換"""
        return GoalProgress(
            id=UUID(row.id) if isinstance(row.id, str) else row.id,
            goal_id=UUID(row.goal_id) if isinstance(row.goal_id, str) else row.goal_id,
            organization_id=UUID(row.organization_id) if isinstance(row.organization_id, str) else row.organization_id,
            progress_date=row.progress_date,
            value=Decimal(str(row.value)) if row.value else None,
            cumulative_value=Decimal(str(row.cumulative_value)) if row.cumulative_value else None,
            daily_note=row.daily_note,
            daily_choice=row.daily_choice,
            ai_feedback=row.ai_feedback,
            ai_feedback_sent_at=row.ai_feedback_sent_at,
            classification=Classification(row.classification) if row.classification else Classification.INTERNAL,
            created_at=row.created_at,
            updated_at=row.updated_at,
            created_by=UUID(row.created_by) if row.created_by and isinstance(row.created_by, str) else row.created_by,
            updated_by=UUID(row.updated_by) if row.updated_by and isinstance(row.updated_by, str) else row.updated_by,
        )


# =============================================================================
# 便利関数
# =============================================================================

def get_goal_service(pool=None) -> GoalService:
    """GoalServiceのインスタンスを取得"""
    return GoalService(pool=pool)
