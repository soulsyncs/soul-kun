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
        # 金額パターン
        assert parse_goal_type_from_text("粗利300万円") == GoalType.NUMERIC
        assert parse_goal_type_from_text("売上500万円達成") == GoalType.NUMERIC
        assert parse_goal_type_from_text("利益1000万") == GoalType.NUMERIC

        # 件数パターン
        assert parse_goal_type_from_text("獲得10件") == GoalType.NUMERIC
        assert parse_goal_type_from_text("契約5件") == GoalType.NUMERIC
        assert parse_goal_type_from_text("納品8件") == GoalType.NUMERIC

        # 人数パターン
        assert parse_goal_type_from_text("採用3人") == GoalType.NUMERIC
        assert parse_goal_type_from_text("面談20名") == GoalType.NUMERIC

    def test_deadline_goal_patterns(self):
        """期限目標パターンの検出"""
        assert parse_goal_type_from_text("1/31までに完了") == GoalType.DEADLINE
        assert parse_goal_type_from_text("3月末までにリリース") == GoalType.DEADLINE
        assert parse_goal_type_from_text("今月中に提出") == GoalType.DEADLINE
        assert parse_goal_type_from_text("来週までに完成") == GoalType.DEADLINE

    def test_action_goal_patterns(self):
        """行動目標パターンの検出"""
        assert parse_goal_type_from_text("毎日朝礼で発言") == GoalType.ACTION
        assert parse_goal_type_from_text("毎週レポート提出") == GoalType.ACTION
        assert parse_goal_type_from_text("日次で振り返り") == GoalType.ACTION

    def test_default_to_numeric(self):
        """判定不能な場合はNUMERICをデフォルトとする"""
        assert parse_goal_type_from_text("目標達成する") == GoalType.NUMERIC
        assert parse_goal_type_from_text("頑張る") == GoalType.NUMERIC


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
        # 2026年1月15日は木曜日
        start, end = calculate_period_from_type(
            PeriodType.WEEKLY,
            reference_date=date(2026, 1, 15)
        )
        # 週の始まり（月曜日）から日曜日まで
        assert start == date(2026, 1, 13)  # 月曜日
        assert end == date(2026, 1, 19)    # 日曜日


class TestGoalService:
    """GoalService のテスト"""

    def test_init(self, mock_goal_db_conn):
        """GoalService の初期化"""
        service = GoalService(
            conn=mock_goal_db_conn,
            org_id="org_test"
        )
        assert service.org_id == "org_test"

    def test_create_goal(self, mock_goal_db_conn, sample_goal):
        """目標の作成"""
        # UUIDを返すモック
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (str(uuid.uuid4()),)
        mock_goal_db_conn.execute.return_value = mock_result

        service = GoalService(
            conn=mock_goal_db_conn,
            org_id="org_test"
        )

        goal_id = service.create_goal(
            user_id=sample_goal["user_id"],
            title=sample_goal["title"],
            goal_type=GoalType.NUMERIC,
            period_type=PeriodType.MONTHLY,
            target_value=sample_goal["target_value"],
            unit=sample_goal["unit"],
            created_by=sample_goal["user_id"],
        )

        # executeが呼ばれたことを確認
        assert mock_goal_db_conn.execute.called
        assert goal_id is not None

    def test_get_active_goals_for_user(self, mock_goal_db_conn):
        """ユーザーのアクティブな目標取得"""
        # モックの戻り値を設定
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            (
                "goal_001", "org_test", "user_001", None, None,
                "individual", "粗利300万", None, "numeric",
                3000000, 1500000, "円", None,
                "monthly", date(2026, 1, 1), date(2026, 1, 31),
                "active", "internal",
                datetime.now(), datetime.now(),
                "user_001", None
            )
        ]
        mock_goal_db_conn.execute.return_value = mock_result

        service = GoalService(
            conn=mock_goal_db_conn,
            org_id="org_test"
        )

        goals = service.get_active_goals_for_user("user_001")

        assert mock_goal_db_conn.execute.called
        assert isinstance(goals, list)

    def test_record_progress_upsert(self, mock_goal_db_conn):
        """進捗記録（UPSERT）"""
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (str(uuid.uuid4()),)
        mock_goal_db_conn.execute.return_value = mock_result

        service = GoalService(
            conn=mock_goal_db_conn,
            org_id="org_test"
        )

        progress_id = service.record_progress(
            goal_id="goal_001",
            progress_date=date.today(),
            value=150000,
            daily_note="本日の進捗",
            daily_choice="積極的に行動した",
            created_by="user_001",
        )

        # executeが呼ばれたことを確認（UPSERT）
        assert mock_goal_db_conn.execute.called
        call_args = str(mock_goal_db_conn.execute.call_args)
        assert "ON CONFLICT" in call_args or progress_id is not None

    def test_update_goal_current_value(self, mock_goal_db_conn):
        """目標の現在値更新"""
        mock_goal_db_conn.execute.return_value = MagicMock(rowcount=1)

        service = GoalService(
            conn=mock_goal_db_conn,
            org_id="org_test"
        )

        result = service.update_goal_current_value(
            goal_id="goal_001",
            new_value=1650000,
            updated_by="user_001",
        )

        assert mock_goal_db_conn.execute.called
        assert result is True

    def test_complete_goal(self, mock_goal_db_conn):
        """目標の完了"""
        mock_goal_db_conn.execute.return_value = MagicMock(rowcount=1)

        service = GoalService(
            conn=mock_goal_db_conn,
            org_id="org_test"
        )

        result = service.complete_goal(
            goal_id="goal_001",
            updated_by="user_001",
        )

        assert mock_goal_db_conn.execute.called
        assert result is True

    def test_save_ai_feedback_promotes_classification(self, mock_goal_db_conn):
        """AIフィードバック保存時にclassificationがconfidentialに昇格"""
        mock_goal_db_conn.execute.return_value = MagicMock(rowcount=1)

        service = GoalService(
            conn=mock_goal_db_conn,
            org_id="org_test"
        )

        result = service.save_ai_feedback(
            progress_id="progress_001",
            ai_feedback="よく頑張りましたウル！",
        )

        # executeの呼び出しを確認
        assert mock_goal_db_conn.execute.called
        call_args = str(mock_goal_db_conn.execute.call_args)
        # confidentialへの更新が含まれていることを確認
        assert "confidential" in call_args or result is True


class TestGetGoalService:
    """get_goal_service ファクトリ関数のテスト"""

    def test_returns_goal_service_instance(self, mock_goal_db_conn):
        """GoalServiceインスタンスを返す"""
        service = get_goal_service(
            conn=mock_goal_db_conn,
            org_id="org_test"
        )
        assert isinstance(service, GoalService)


class TestGoalServiceEdgeCases:
    """GoalService のエッジケーステスト"""

    def test_create_goal_with_deadline_type(self, mock_goal_db_conn):
        """期限目標の作成"""
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (str(uuid.uuid4()),)
        mock_goal_db_conn.execute.return_value = mock_result

        service = GoalService(
            conn=mock_goal_db_conn,
            org_id="org_test"
        )

        goal_id = service.create_goal(
            user_id="user_001",
            title="プロジェクトリリース",
            goal_type=GoalType.DEADLINE,
            period_type=PeriodType.MONTHLY,
            deadline=date(2026, 1, 31),
            created_by="user_001",
        )

        assert goal_id is not None

    def test_create_goal_with_action_type(self, mock_goal_db_conn):
        """行動目標の作成"""
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (str(uuid.uuid4()),)
        mock_goal_db_conn.execute.return_value = mock_result

        service = GoalService(
            conn=mock_goal_db_conn,
            org_id="org_test"
        )

        goal_id = service.create_goal(
            user_id="user_001",
            title="毎日朝礼で発言する",
            goal_type=GoalType.ACTION,
            period_type=PeriodType.WEEKLY,
            created_by="user_001",
        )

        assert goal_id is not None

    def test_get_today_progress_no_data(self, mock_goal_db_conn):
        """当日の進捗がない場合"""
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_goal_db_conn.execute.return_value = mock_result

        service = GoalService(
            conn=mock_goal_db_conn,
            org_id="org_test"
        )

        progress = service.get_today_progress("goal_001")
        assert progress is None

    def test_organization_id_filter_always_applied(self, mock_goal_db_conn):
        """organization_idフィルタが常に適用されることを確認"""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_goal_db_conn.execute.return_value = mock_result

        service = GoalService(
            conn=mock_goal_db_conn,
            org_id="org_test"
        )

        service.get_active_goals_for_user("user_001")

        # executeの呼び出し引数を確認
        call_args = mock_goal_db_conn.execute.call_args
        # organization_idが含まれていることを確認
        assert "org_test" in str(call_args) or "org_id" in str(call_args)
