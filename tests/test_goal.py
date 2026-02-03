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


# =============================================================================
# v10.56.5: GoalService メソッドの統合テスト（カバレッジ改善）
# =============================================================================

class TestGoalServiceGetGoal:
    """GoalService.get_goal のテスト"""

    def test_get_goal_returns_goal_when_found(self, mock_db_pool):
        """目標が見つかった場合はGoalオブジェクトを返す"""
        mock_pool, mock_conn = mock_db_pool
        goal_id = uuid.uuid4()
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        # _row_to_goalに必要なデータをモック（属性アクセス形式）
        mock_row = MagicMock()
        mock_row.id = str(goal_id)
        mock_row.organization_id = str(org_id)
        mock_row.user_id = str(user_id)
        mock_row.department_id = None
        mock_row.parent_goal_id = None
        mock_row.goal_level = "individual"
        mock_row.title = "テスト目標"
        mock_row.description = "説明"
        mock_row.goal_type = "numeric"
        mock_row.target_value = 1000
        mock_row.current_value = 500
        mock_row.unit = "件"
        mock_row.deadline = None
        mock_row.period_type = "monthly"
        mock_row.period_start = date(2026, 1, 1)
        mock_row.period_end = date(2026, 1, 31)
        mock_row.status = "active"
        mock_row.classification = "internal"
        mock_row.created_at = datetime(2026, 1, 1)
        mock_row.updated_at = datetime(2026, 1, 1)
        mock_row.created_by = str(user_id)
        mock_row.updated_by = str(user_id)
        mock_conn.execute.return_value.fetchone.return_value = mock_row

        service = GoalService(pool=mock_pool)
        goal = service.get_goal(goal_id, org_id)

        assert goal is not None
        assert goal.title == "テスト目標"

    def test_get_goal_returns_none_when_not_found(self, mock_db_pool):
        """目標が見つからない場合はNoneを返す"""
        mock_pool, mock_conn = mock_db_pool
        mock_conn.execute.return_value.fetchone.return_value = None

        service = GoalService(pool=mock_pool)
        goal = service.get_goal(uuid.uuid4(), uuid.uuid4())

        assert goal is None


class TestGoalServiceGetGoalsForUser:
    """GoalService.get_goals_for_user のテスト"""

    def test_get_goals_for_user_basic(self, mock_db_pool):
        """基本的な目標一覧取得"""
        mock_pool, mock_conn = mock_db_pool
        mock_conn.execute.return_value.fetchall.return_value = []

        service = GoalService(pool=mock_pool)
        goals = service.get_goals_for_user(uuid.uuid4(), uuid.uuid4())

        assert goals == []
        assert mock_conn.execute.called

    def test_get_goals_for_user_with_status_filter(self, mock_db_pool):
        """ステータスフィルター付きの目標一覧取得"""
        mock_pool, mock_conn = mock_db_pool
        mock_conn.execute.return_value.fetchall.return_value = []

        service = GoalService(pool=mock_pool)
        goals = service.get_goals_for_user(
            uuid.uuid4(),
            uuid.uuid4(),
            status=GoalStatus.ACTIVE
        )

        assert goals == []
        # SQLクエリにstatusが含まれることを確認
        call_args = mock_conn.execute.call_args
        assert "status" in str(call_args)

    def test_get_goals_for_user_with_period_filter(self, mock_db_pool):
        """期間フィルター付きの目標一覧取得"""
        mock_pool, mock_conn = mock_db_pool
        mock_conn.execute.return_value.fetchall.return_value = []

        service = GoalService(pool=mock_pool)
        goals = service.get_goals_for_user(
            uuid.uuid4(),
            uuid.uuid4(),
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31)
        )

        assert goals == []


class TestGoalServiceGetActiveGoalsForUser:
    """GoalService.get_active_goals_for_user のテスト"""

    def test_get_active_goals_for_user(self, mock_db_pool):
        """アクティブな目標一覧取得"""
        mock_pool, mock_conn = mock_db_pool
        mock_conn.execute.return_value.fetchall.return_value = []

        service = GoalService(pool=mock_pool)
        goals = service.get_active_goals_for_user(uuid.uuid4(), uuid.uuid4())

        assert goals == []


class TestGoalServiceUpdateGoalCurrentValue:
    """GoalService.update_goal_current_value のテスト"""

    def test_update_goal_current_value_success(self, mock_db_pool):
        """現在値の更新成功"""
        mock_pool, mock_conn = mock_db_pool
        goal_id = uuid.uuid4()
        org_id = uuid.uuid4()

        # 最初のクエリ（目標取得）のモック
        mock_conn.execute.return_value.fetchone.return_value = ("internal", "テスト目標", 100)
        # 更新クエリのモック
        mock_conn.execute.return_value.rowcount = 1

        service = GoalService(pool=mock_pool)
        result = service.update_goal_current_value(
            goal_id=goal_id,
            organization_id=org_id,
            current_value=Decimal("200")
        )

        assert result is True
        assert mock_conn.commit.called

    def test_update_goal_current_value_with_audit_log(self, mock_db_pool):
        """機密目標の更新時に監査ログを記録"""
        mock_pool, mock_conn = mock_db_pool
        goal_id = uuid.uuid4()
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        # 機密目標のモック
        mock_conn.execute.return_value.fetchone.return_value = ("confidential", "機密目標", 100)
        mock_conn.execute.return_value.rowcount = 1

        service = GoalService(pool=mock_pool)
        result = service.update_goal_current_value(
            goal_id=goal_id,
            organization_id=org_id,
            current_value=Decimal("200"),
            updated_by=user_id
        )

        assert result is True

    def test_update_goal_current_value_not_found(self, mock_db_pool):
        """目標が見つからない場合"""
        mock_pool, mock_conn = mock_db_pool
        mock_conn.execute.return_value.fetchone.return_value = None
        mock_conn.execute.return_value.rowcount = 0

        service = GoalService(pool=mock_pool)
        result = service.update_goal_current_value(
            goal_id=uuid.uuid4(),
            organization_id=uuid.uuid4(),
            current_value=Decimal("200")
        )

        assert result is False


class TestGoalServiceCompleteGoal:
    """GoalService.complete_goal のテスト"""

    def test_complete_goal_success(self, mock_db_pool):
        """目標完了の成功"""
        mock_pool, mock_conn = mock_db_pool
        goal_id = uuid.uuid4()
        org_id = uuid.uuid4()

        mock_conn.execute.return_value.fetchone.return_value = ("internal", "テスト目標")
        mock_conn.execute.return_value.rowcount = 1

        service = GoalService(pool=mock_pool)
        result = service.complete_goal(goal_id=goal_id, organization_id=org_id)

        assert result is True
        assert mock_conn.commit.called

    def test_complete_goal_with_audit_log(self, mock_db_pool):
        """機密目標の完了時に監査ログを記録"""
        mock_pool, mock_conn = mock_db_pool
        goal_id = uuid.uuid4()
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        mock_conn.execute.return_value.fetchone.return_value = ("restricted", "機密目標")
        mock_conn.execute.return_value.rowcount = 1

        service = GoalService(pool=mock_pool)
        result = service.complete_goal(
            goal_id=goal_id,
            organization_id=org_id,
            updated_by=user_id
        )

        assert result is True

    def test_complete_goal_not_found(self, mock_db_pool):
        """目標が見つからない場合"""
        mock_pool, mock_conn = mock_db_pool
        mock_conn.execute.return_value.fetchone.return_value = None
        mock_conn.execute.return_value.rowcount = 0

        service = GoalService(pool=mock_pool)
        result = service.complete_goal(
            goal_id=uuid.uuid4(),
            organization_id=uuid.uuid4()
        )

        assert result is False


class TestGoalServiceRecordProgress:
    """GoalService.record_progress のテスト"""

    def test_record_progress_with_value(self, mock_db_pool):
        """数値付きの進捗記録"""
        mock_pool, mock_conn = mock_db_pool
        goal_id = uuid.uuid4()
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        # 複数のDB呼び出しに対応するモック
        # 1回目: 目標の機密区分取得、2回目: 累積値計算、3回目以降: UPSERT等
        mock_result_goal = MagicMock()
        mock_result_goal.fetchone.return_value = ("internal", "テスト目標")

        mock_result_sum = MagicMock()
        mock_result_sum.fetchone.return_value = (Decimal("100"),)  # 前日までの累計

        mock_conn.execute.side_effect = [mock_result_goal, mock_result_sum, MagicMock(), MagicMock(), MagicMock()]

        service = GoalService(pool=mock_pool)
        progress = service.record_progress(
            goal_id=goal_id,
            organization_id=org_id,
            progress_date=date(2026, 1, 15),
            value=Decimal("50"),
            daily_note="今日の進捗",
            user_id=user_id
        )

        assert progress is not None
        assert progress.value == Decimal("50")

    def test_record_progress_without_value(self, mock_db_pool):
        """数値なしの進捗記録（日報のみ）"""
        mock_pool, mock_conn = mock_db_pool
        goal_id = uuid.uuid4()
        org_id = uuid.uuid4()

        mock_conn.execute.return_value.fetchone.return_value = ("internal", "テスト目標")

        service = GoalService(pool=mock_pool)
        progress = service.record_progress(
            goal_id=goal_id,
            organization_id=org_id,
            progress_date=date(2026, 1, 15),
            daily_note="今日の振り返り",
            daily_choice="順調"
        )

        assert progress is not None

    def test_record_progress_confidential_goal_logs_audit(self, mock_db_pool):
        """機密目標の進捗記録時に監査ログを記録"""
        mock_pool, mock_conn = mock_db_pool
        goal_id = uuid.uuid4()
        org_id = uuid.uuid4()

        # 複数のDB呼び出しに対応するモック（機密目標）
        mock_result_goal = MagicMock()
        mock_result_goal.fetchone.return_value = ("confidential", "機密目標")

        mock_result_sum = MagicMock()
        mock_result_sum.fetchone.return_value = (Decimal("0"),)

        mock_conn.execute.side_effect = [mock_result_goal, mock_result_sum, MagicMock(), MagicMock(), MagicMock(), MagicMock()]

        service = GoalService(pool=mock_pool)
        progress = service.record_progress(
            goal_id=goal_id,
            organization_id=org_id,
            progress_date=date(2026, 1, 15),
            value=Decimal("100")
        )

        assert progress is not None


class TestGoalServiceGetProgressForGoal:
    """GoalService.get_progress_for_goal のテスト"""

    def test_get_progress_for_goal_returns_list(self, mock_db_pool):
        """目標の進捗一覧を取得"""
        mock_pool, mock_conn = mock_db_pool
        goal_id = uuid.uuid4()
        org_id = uuid.uuid4()

        mock_conn.execute.return_value.fetchall.return_value = []

        service = GoalService(pool=mock_pool)
        progress_list = service.get_progress_for_goal(
            goal_id=goal_id,
            organization_id=org_id
        )

        assert progress_list == []

    def test_get_progress_for_goal_with_date_filter(self, mock_db_pool):
        """日付フィルター付きの進捗取得"""
        mock_pool, mock_conn = mock_db_pool
        goal_id = uuid.uuid4()
        org_id = uuid.uuid4()

        mock_conn.execute.return_value.fetchall.return_value = []

        service = GoalService(pool=mock_pool)
        progress_list = service.get_progress_for_goal(
            goal_id=goal_id,
            organization_id=org_id,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31)
        )

        assert progress_list == []


class TestGoalServiceGetTodayProgress:
    """GoalService.get_today_progress のテスト"""

    def test_get_today_progress_returns_progress(self, mock_db_pool):
        """本日の進捗を取得"""
        mock_pool, mock_conn = mock_db_pool
        goal_id = uuid.uuid4()
        org_id = uuid.uuid4()

        mock_conn.execute.return_value.fetchone.return_value = None

        service = GoalService(pool=mock_pool)
        progress = service.get_today_progress(
            goal_id=goal_id,
            organization_id=org_id
        )

        assert progress is None

    def test_get_today_progress_found(self, mock_db_pool):
        """本日の進捗が存在する場合"""
        mock_pool, mock_conn = mock_db_pool
        goal_id = uuid.uuid4()
        org_id = uuid.uuid4()
        progress_id = uuid.uuid4()

        # 進捗データのモック（属性アクセス形式）
        mock_row = MagicMock()
        mock_row.id = str(progress_id)
        mock_row.goal_id = str(goal_id)
        mock_row.organization_id = str(org_id)
        mock_row.progress_date = date.today()
        mock_row.value = Decimal("50")
        mock_row.cumulative_value = Decimal("150")
        mock_row.daily_note = "今日の進捗"
        mock_row.daily_choice = "順調"
        mock_row.ai_feedback = None
        mock_row.ai_feedback_sent_at = None
        mock_row.classification = "internal"
        mock_row.created_at = datetime.now()
        mock_row.updated_at = datetime.now()
        mock_row.created_by = None
        mock_row.updated_by = None
        mock_conn.execute.return_value.fetchone.return_value = mock_row

        service = GoalService(pool=mock_pool)
        progress = service.get_today_progress(
            goal_id=goal_id,
            organization_id=org_id
        )

        assert progress is not None
        assert progress.daily_note == "今日の進捗"


class TestGoalServiceSaveAiFeedback:
    """GoalService.save_ai_feedback のテスト"""

    def test_save_ai_feedback_success(self, mock_db_pool):
        """AIフィードバックの保存成功"""
        mock_pool, mock_conn = mock_db_pool
        goal_id = uuid.uuid4()
        org_id = uuid.uuid4()
        progress_id = uuid.uuid4()

        # 更新成功のモック
        mock_result = MagicMock()
        mock_result.rowcount = 1

        # progress_idを取得するクエリのモック
        mock_progress_result = MagicMock()
        mock_progress_result.fetchone.return_value = (str(progress_id),)

        mock_conn.execute.side_effect = [mock_result, mock_progress_result, MagicMock()]

        service = GoalService(pool=mock_pool)
        result = service.save_ai_feedback(
            goal_id=goal_id,
            organization_id=org_id,
            progress_date=date(2026, 1, 15),
            ai_feedback="良い進捗です！"
        )

        assert result is True
        assert mock_conn.commit.called

    def test_save_ai_feedback_not_found(self, mock_db_pool):
        """進捗が見つからない場合"""
        mock_pool, mock_conn = mock_db_pool
        goal_id = uuid.uuid4()
        org_id = uuid.uuid4()

        # 更新対象なしのモック
        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_conn.execute.return_value = mock_result

        service = GoalService(pool=mock_pool)
        result = service.save_ai_feedback(
            goal_id=goal_id,
            organization_id=org_id,
            progress_date=date(2026, 1, 15),
            ai_feedback="フィードバック"
        )

        assert result is False

    def test_save_ai_feedback_with_user_id(self, mock_db_pool):
        """user_idを指定してAIフィードバックを保存"""
        mock_pool, mock_conn = mock_db_pool
        goal_id = uuid.uuid4()
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        progress_id = uuid.uuid4()

        # 更新成功のモック
        mock_result = MagicMock()
        mock_result.rowcount = 1

        # progress_idを取得するクエリのモック
        mock_progress_result = MagicMock()
        mock_progress_result.fetchone.return_value = (str(progress_id),)

        mock_conn.execute.side_effect = [mock_result, mock_progress_result, MagicMock()]

        service = GoalService(pool=mock_pool)
        result = service.save_ai_feedback(
            goal_id=goal_id,
            organization_id=org_id,
            progress_date=date(2026, 1, 15),
            ai_feedback="素晴らしい！",
            user_id=user_id
        )

        assert result is True


class TestGoalServiceRowConversion:
    """GoalService._row_to_goal, _row_to_progress のテスト"""

    def test_row_to_goal_with_attributes(self, mock_db_pool):
        """属性アクセス形式のRowオブジェクトの変換"""
        mock_pool, mock_conn = mock_db_pool
        service = GoalService(pool=mock_pool)

        mock_row = MagicMock()
        mock_row.id = str(uuid.uuid4())
        mock_row.organization_id = str(uuid.uuid4())
        mock_row.user_id = str(uuid.uuid4())
        mock_row.department_id = None
        mock_row.parent_goal_id = None
        mock_row.goal_level = "individual"
        mock_row.title = "テスト目標"
        mock_row.description = None
        mock_row.goal_type = "numeric"
        mock_row.target_value = 1000
        mock_row.current_value = 500
        mock_row.unit = "件"
        mock_row.deadline = None
        mock_row.period_type = "monthly"
        mock_row.period_start = date(2026, 1, 1)
        mock_row.period_end = date(2026, 1, 31)
        mock_row.status = "active"
        mock_row.classification = "internal"
        mock_row.created_at = datetime(2026, 1, 1)
        mock_row.updated_at = datetime(2026, 1, 1)
        mock_row.created_by = None
        mock_row.updated_by = None

        goal = service._row_to_goal(mock_row)

        assert goal.title == "テスト目標"
        assert goal.goal_type == GoalType.NUMERIC
        assert goal.status == GoalStatus.ACTIVE

    def test_row_to_progress_with_attributes(self, mock_db_pool):
        """属性アクセス形式のRowオブジェクトのProgress変換"""
        mock_pool, mock_conn = mock_db_pool
        service = GoalService(pool=mock_pool)

        mock_row = MagicMock()
        mock_row.id = str(uuid.uuid4())
        mock_row.goal_id = str(uuid.uuid4())
        mock_row.organization_id = str(uuid.uuid4())
        mock_row.progress_date = date(2026, 1, 15)
        mock_row.value = 50
        mock_row.cumulative_value = 150
        mock_row.daily_note = "進捗メモ"
        mock_row.daily_choice = "順調"
        mock_row.ai_feedback = None
        mock_row.ai_feedback_sent_at = None
        mock_row.classification = "internal"
        mock_row.created_at = datetime(2026, 1, 15)
        mock_row.updated_at = datetime(2026, 1, 15)
        mock_row.created_by = None
        mock_row.updated_by = None

        progress = service._row_to_progress(mock_row)

        assert progress.daily_note == "進捗メモ"
        assert progress.daily_choice == "順調"
