"""
lib/goal.py のテスト

Phase 2.5 目標管理サービスのユニットテスト
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import date, datetime, timedelta
from decimal import Decimal
import uuid

from lib.goal import (
    GoalLevel,
    GoalType,
    GoalStatus,
    PeriodType,
    Classification,
    ReminderType,
    Goal,
    GoalProgress,
    GoalService,
    get_goal_service,
    parse_goal_type_from_text,
    calculate_period_from_type,
)


class TestGoalEnums:
    """Enum定義のテスト"""

    def test_goal_level_values(self):
        """GoalLevel の値"""
        assert GoalLevel.COMPANY.value == "company"
        assert GoalLevel.DEPARTMENT.value == "department"
        assert GoalLevel.INDIVIDUAL.value == "individual"

    def test_goal_type_values(self):
        """GoalType の値"""
        assert GoalType.NUMERIC.value == "numeric"
        assert GoalType.DEADLINE.value == "deadline"
        assert GoalType.ACTION.value == "action"

    def test_goal_status_values(self):
        """GoalStatus の値"""
        assert GoalStatus.ACTIVE.value == "active"
        assert GoalStatus.COMPLETED.value == "completed"
        assert GoalStatus.CANCELLED.value == "cancelled"

    def test_period_type_values(self):
        """PeriodType の値"""
        assert PeriodType.YEARLY.value == "yearly"
        assert PeriodType.QUARTERLY.value == "quarterly"
        assert PeriodType.MONTHLY.value == "monthly"
        assert PeriodType.WEEKLY.value == "weekly"

    def test_classification_values(self):
        """Classification の値（4段階）"""
        assert Classification.PUBLIC.value == "public"
        assert Classification.INTERNAL.value == "internal"
        assert Classification.CONFIDENTIAL.value == "confidential"
        assert Classification.RESTRICTED.value == "restricted"

    def test_reminder_type_values(self):
        """ReminderType の値"""
        assert ReminderType.DAILY_CHECK.value == "daily_check"
        assert ReminderType.MORNING_FEEDBACK.value == "morning_feedback"
        assert ReminderType.TEAM_SUMMARY.value == "team_summary"
        assert ReminderType.DAILY_REMINDER.value == "daily_reminder"


class TestGoalDataclass:
    """Goal データクラスのテスト"""

    def test_goal_creation(self, sample_goal):
        """Goalインスタンスの作成"""
        goal = Goal(
            id=sample_goal["id"],
            organization_id=sample_goal["organization_id"],
            user_id=sample_goal["user_id"],
            goal_level=GoalLevel.INDIVIDUAL,
            title=sample_goal["title"],
            goal_type=GoalType.NUMERIC,
            period_type=PeriodType.MONTHLY,
            period_start=sample_goal["period_start"],
            period_end=sample_goal["period_end"],
            status=GoalStatus.ACTIVE,
            classification=Classification.INTERNAL,
            target_value=sample_goal["target_value"],
            current_value=sample_goal["current_value"],
            unit=sample_goal["unit"],
        )

        assert goal.id == sample_goal["id"]
        assert goal.title == "粗利300万円"
        assert goal.target_value == 3000000
        assert goal.current_value == 1500000

    def test_goal_achievement_rate(self):
        """達成率の計算"""
        goal = Goal(
            id="test_goal",
            organization_id="org_test",
            user_id="user_test",
            goal_level=GoalLevel.INDIVIDUAL,
            title="テスト目標",
            goal_type=GoalType.NUMERIC,
            period_type=PeriodType.MONTHLY,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            status=GoalStatus.ACTIVE,
            classification=Classification.INTERNAL,
            target_value=1000,
            current_value=500,
        )

        assert goal.achievement_rate == 50.0

    def test_goal_achievement_rate_zero_target(self):
        """target_value=0の場合の達成率"""
        goal = Goal(
            id="test_goal",
            organization_id="org_test",
            user_id="user_test",
            goal_level=GoalLevel.INDIVIDUAL,
            title="テスト目標",
            goal_type=GoalType.NUMERIC,
            period_type=PeriodType.MONTHLY,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            status=GoalStatus.ACTIVE,
            classification=Classification.INTERNAL,
            target_value=0,
            current_value=100,
        )

        assert goal.achievement_rate == 0.0

    def test_goal_achievement_rate_no_target(self):
        """target_value=Noneの場合の達成率"""
        goal = Goal(
            id="test_goal",
            organization_id="org_test",
            user_id="user_test",
            goal_level=GoalLevel.INDIVIDUAL,
            title="テスト目標",
            goal_type=GoalType.DEADLINE,
            period_type=PeriodType.MONTHLY,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            status=GoalStatus.ACTIVE,
            classification=Classification.INTERNAL,
            target_value=None,
            current_value=None,
        )

        assert goal.achievement_rate == 0.0


class TestGoalProgressDataclass:
    """GoalProgress データクラスのテスト"""

    def test_goal_progress_creation(self, sample_goal_progress):
        """GoalProgressインスタンスの作成"""
        progress = GoalProgress(
            id=sample_goal_progress["id"],
            goal_id=sample_goal_progress["goal_id"],
            organization_id=sample_goal_progress["organization_id"],
            progress_date=sample_goal_progress["progress_date"],
            value=sample_goal_progress["value"],
            cumulative_value=sample_goal_progress["cumulative_value"],
            daily_note=sample_goal_progress["daily_note"],
            daily_choice=sample_goal_progress["daily_choice"],
            classification=Classification.INTERNAL,
        )

        assert progress.goal_id == "goal_test_001"
        assert progress.value == 150000
        assert progress.daily_note == "新規案件の契約が取れました"


class TestParseGoalTypeFromText:
    """parse_goal_type_from_text のテスト"""

    def test_numeric_goal_patterns(self):
        """数値目標パターンの検出"""
        # 金額パターン（関数は(GoalType, value, unit)のタプルを返す）
        result = parse_goal_type_from_text("粗利300万円")
        assert result[0] == GoalType.NUMERIC
        assert result[1] == Decimal("3000000")
        assert result[2] == "円"

        result = parse_goal_type_from_text("売上500万円達成")
        assert result[0] == GoalType.NUMERIC

        # 件数パターン
        result = parse_goal_type_from_text("獲得10件")
        assert result[0] == GoalType.NUMERIC
        assert result[1] == Decimal("10")
        assert result[2] == "件"

        # 人数パターン
        result = parse_goal_type_from_text("採用3人")
        assert result[0] == GoalType.NUMERIC
        assert result[1] == Decimal("3")
        assert result[2] == "人"

    def test_deadline_goal_patterns(self):
        """期限目標パターンの検出"""
        assert parse_goal_type_from_text("1/31までに完了")[0] == GoalType.DEADLINE
        assert parse_goal_type_from_text("3月末までにリリース")[0] == GoalType.DEADLINE
        assert parse_goal_type_from_text("今月中に提出")[0] == GoalType.DEADLINE
        assert parse_goal_type_from_text("来週までに完成")[0] == GoalType.DEADLINE

    def test_action_goal_patterns(self):
        """行動目標パターンの検出"""
        assert parse_goal_type_from_text("毎日朝礼で発言")[0] == GoalType.ACTION
        assert parse_goal_type_from_text("毎週レポート提出")[0] == GoalType.ACTION
        assert parse_goal_type_from_text("継続的に学習")[0] == GoalType.ACTION

    def test_default_to_action(self):
        """判定不能な場合はACTIONをデフォルトとする"""
        assert parse_goal_type_from_text("目標達成する")[0] == GoalType.ACTION
        assert parse_goal_type_from_text("頑張る")[0] == GoalType.ACTION


class TestCalculatePeriodFromType:
    """calculate_period_from_type のテスト"""

    def test_monthly_period(self):
        """月次期間の計算"""
        start, end = calculate_period_from_type(
            PeriodType.MONTHLY,
            reference_date=date(2026, 1, 15)
        )
        assert start == date(2026, 1, 1)
        assert end == date(2026, 1, 31)

    def test_monthly_period_february(self):
        """2月の月次期間（うるう年考慮）"""
        start, end = calculate_period_from_type(
            PeriodType.MONTHLY,
            reference_date=date(2026, 2, 15)
        )
        assert start == date(2026, 2, 1)
        assert end == date(2026, 2, 28)

    def test_quarterly_period_q1(self):
        """四半期期間の計算（Q1）"""
        start, end = calculate_period_from_type(
            PeriodType.QUARTERLY,
            reference_date=date(2026, 2, 15)
        )
        assert start == date(2026, 1, 1)
        assert end == date(2026, 3, 31)

    def test_quarterly_period_q2(self):
        """四半期期間の計算（Q2）"""
        start, end = calculate_period_from_type(
            PeriodType.QUARTERLY,
            reference_date=date(2026, 5, 15)
        )
        assert start == date(2026, 4, 1)
        assert end == date(2026, 6, 30)

    def test_yearly_period(self):
        """年次期間の計算"""
        start, end = calculate_period_from_type(
            PeriodType.YEARLY,
            reference_date=date(2026, 6, 15)
        )
        assert start == date(2026, 1, 1)
        assert end == date(2026, 12, 31)

    def test_weekly_period(self):
        """週次期間の計算"""
        # 2026年1月15日は木曜日（weekday=3）
        start, end = calculate_period_from_type(
            PeriodType.WEEKLY,
            reference_date=date(2026, 1, 15)
        )
        # 週の始まり（月曜日）から日曜日まで
        # 木曜日から3日前が月曜日、そこから6日後が日曜日
        assert start == date(2026, 1, 12)  # 月曜日
        assert end == date(2026, 1, 18)    # 日曜日


@pytest.fixture
def mock_db_pool():
    """GoalService用のモックプールを作成"""
    mock_pool = MagicMock()
    mock_conn = MagicMock()
    mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
    mock_pool.connect.return_value.__exit__ = MagicMock(return_value=False)
    return mock_pool, mock_conn


class TestGoalService:
    """GoalService のテスト"""

    def test_init_without_pool(self):
        """GoalService の初期化（poolなし）"""
        service = GoalService()
        assert service._pool is None

    def test_init_with_pool(self, mock_db_pool):
        """GoalService の初期化（pool指定）"""
        mock_pool, _ = mock_db_pool
        service = GoalService(pool=mock_pool)
        assert service._pool is mock_pool

    def test_create_goal(self, mock_db_pool, sample_goal):
        """目標の作成"""
        mock_pool, mock_conn = mock_db_pool

        service = GoalService(pool=mock_pool)

        # 新しいUUIDを生成してテスト
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        goal = service.create_goal(
            organization_id=org_id,
            user_id=user_id,
            title=sample_goal["title"],
            goal_type=GoalType.NUMERIC,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            target_value=Decimal(str(sample_goal["target_value"])),
            unit=sample_goal["unit"],
        )

        # executeが呼ばれたことを確認
        assert mock_conn.execute.called
        # Goalオブジェクトが返されることを確認
        assert isinstance(goal, Goal)
        assert goal.title == sample_goal["title"]

    def test_create_goal_returns_goal_object(self, mock_db_pool):
        """create_goalがGoalオブジェクトを返す"""
        mock_pool, mock_conn = mock_db_pool

        service = GoalService(pool=mock_pool)

        goal = service.create_goal(
            organization_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            title="粗利300万円",
            goal_type=GoalType.NUMERIC,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            target_value=Decimal("3000000"),
            unit="円",
        )

        assert isinstance(goal, Goal)
        assert goal.title == "粗利300万円"
        assert goal.goal_type == GoalType.NUMERIC

    def test_goal_service_uses_pool_connect(self, mock_db_pool):
        """GoalServiceがpool.connectを使用する"""
        mock_pool, mock_conn = mock_db_pool

        service = GoalService(pool=mock_pool)

        service.create_goal(
            organization_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            title="テスト目標",
            goal_type=GoalType.NUMERIC,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )

        # pool.connectが呼ばれたことを確認
        mock_pool.connect.assert_called()


class TestGetGoalService:
    """get_goal_service ファクトリ関数のテスト"""

    def test_returns_goal_service_instance(self, mock_db_pool):
        """GoalServiceインスタンスを返す"""
        mock_pool, _ = mock_db_pool
        service = get_goal_service(pool=mock_pool)
        assert isinstance(service, GoalService)

    def test_returns_goal_service_without_pool(self):
        """pool引数なしでもGoalServiceインスタンスを返す"""
        service = get_goal_service()
        assert isinstance(service, GoalService)


class TestGoalServiceEdgeCases:
    """GoalService のエッジケーステスト"""

    def test_create_goal_with_deadline_type(self, mock_db_pool):
        """期限目標の作成"""
        mock_pool, mock_conn = mock_db_pool

        service = GoalService(pool=mock_pool)

        goal = service.create_goal(
            organization_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            title="プロジェクトリリース",
            goal_type=GoalType.DEADLINE,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            deadline=date(2026, 1, 31),
        )

        assert isinstance(goal, Goal)
        assert goal.goal_type == GoalType.DEADLINE

    def test_create_goal_with_action_type(self, mock_db_pool):
        """行動目標の作成"""
        mock_pool, mock_conn = mock_db_pool

        service = GoalService(pool=mock_pool)

        goal = service.create_goal(
            organization_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            title="毎日朝礼で発言する",
            goal_type=GoalType.ACTION,
            period_start=date(2026, 1, 13),
            period_end=date(2026, 1, 19),
            period_type=PeriodType.WEEKLY,
        )

        assert isinstance(goal, Goal)
        assert goal.goal_type == GoalType.ACTION

    def test_create_goal_default_classification(self, mock_db_pool):
        """目標作成時のデフォルトclassificationはinternal"""
        mock_pool, mock_conn = mock_db_pool

        service = GoalService(pool=mock_pool)

        goal = service.create_goal(
            organization_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            title="テスト目標",
            goal_type=GoalType.NUMERIC,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )

        assert goal.classification == Classification.INTERNAL

    def test_organization_id_included_in_goal(self, mock_db_pool):
        """organization_idがGoalオブジェクトに含まれる"""
        mock_pool, mock_conn = mock_db_pool
        org_id = uuid.uuid4()

        service = GoalService(pool=mock_pool)

        goal = service.create_goal(
            organization_id=org_id,
            user_id=uuid.uuid4(),
            title="テスト目標",
            goal_type=GoalType.NUMERIC,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )

        assert goal.organization_id == org_id


# =============================================================================
# v10.56.0: 目標削除・整理機能のテスト
# =============================================================================

from lib.goal import cancel_goals, get_duplicate_goals, get_expired_goals, get_pending_goals


class TestCancelGoals:
    """cancel_goals のテスト"""

    def test_cancel_goals_empty_list(self, mock_db_pool):
        """空のリストを渡した場合は何もしない"""
        mock_pool, mock_conn = mock_db_pool

        count, titles = cancel_goals(mock_pool, [], "org-123", "user-123", "user_request")

        assert count == 0
        assert titles == []

    def test_cancel_goals_updates_status(self, mock_db_pool):
        """目標のステータスをcancelledに変更する"""
        mock_pool, mock_conn = mock_db_pool

        # モックの設定
        goal_id = str(uuid.uuid4())
        mock_conn.execute.return_value.fetchall.return_value = [
            (goal_id, "テスト目標", "internal")
        ]
        mock_conn.execute.return_value.rowcount = 1

        count, titles = cancel_goals(
            mock_pool,
            [goal_id],
            "org-123",
            "user-123",
            "user_request"
        )

        # executeが呼ばれたことを確認
        assert mock_conn.execute.called


class TestGetDuplicateGoals:
    """get_duplicate_goals のテスト"""

    def test_get_duplicate_goals_no_duplicates(self, mock_db_pool):
        """重複がない場合は空リストを返す"""
        mock_pool, mock_conn = mock_db_pool
        mock_conn.execute.return_value.fetchall.return_value = []

        duplicates = get_duplicate_goals(mock_pool, "user-123", "org-123")

        assert duplicates == []

    def test_get_duplicate_goals_returns_grouped_data(self, mock_db_pool):
        """重複がある場合はグループ化して返す"""
        mock_pool, mock_conn = mock_db_pool

        # 重複データのモック
        mock_conn.execute.return_value.fetchall.return_value = [
            ("粗利300万円", date(2026, 1, 1), date(2026, 1, 31),
             [str(uuid.uuid4()), str(uuid.uuid4())],
             [3000000, 3000000],
             ["円", "円"],
             2)
        ]

        duplicates = get_duplicate_goals(mock_pool, "user-123", "org-123")

        assert len(duplicates) == 1
        assert duplicates[0]["title"] == "粗利300万円"
        assert duplicates[0]["count"] == 2


class TestGetExpiredGoals:
    """get_expired_goals のテスト"""

    def test_get_expired_goals_no_expired(self, mock_db_pool):
        """期限切れがない場合は空リストを返す"""
        mock_pool, mock_conn = mock_db_pool
        mock_conn.execute.return_value.fetchall.return_value = []

        expired = get_expired_goals(mock_pool, "user-123", "org-123")

        assert expired == []

    def test_get_expired_goals_returns_expired_list(self, mock_db_pool):
        """期限切れ目標のリストを返す"""
        mock_pool, mock_conn = mock_db_pool

        goal_id = str(uuid.uuid4())
        expired_date = date(2026, 1, 1)  # 過去の日付

        mock_conn.execute.return_value.fetchall.return_value = [
            (goal_id, "期限切れ目標", expired_date, "numeric", 100, 50, "件")
        ]

        expired = get_expired_goals(mock_pool, "user-123", "org-123")

        assert len(expired) == 1
        assert expired[0]["id"] == goal_id
        assert expired[0]["title"] == "期限切れ目標"


class TestGetPendingGoals:
    """get_pending_goals のテスト"""

    def test_get_pending_goals_no_pending(self, mock_db_pool):
        """未定目標がない場合は空リストを返す"""
        mock_pool, mock_conn = mock_db_pool
        mock_conn.execute.return_value.fetchall.return_value = []

        pending = get_pending_goals(mock_pool, "user-123", "org-123")

        assert pending == []

    def test_get_pending_goals_returns_pending_list(self, mock_db_pool):
        """進捗がない目標のリストを返す"""
        mock_pool, mock_conn = mock_db_pool

        goal_id = str(uuid.uuid4())

        mock_conn.execute.return_value.fetchall.return_value = [
            (goal_id, "新規目標", date(2026, 1, 1), date(2026, 1, 31),
             "numeric", 100, 0, "件", datetime(2026, 1, 15))
        ]

        pending = get_pending_goals(mock_pool, "user-123", "org-123")

        assert len(pending) == 1
        assert pending[0]["id"] == goal_id
        assert pending[0]["title"] == "新規目標"
