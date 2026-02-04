# tests/test_fact_collector_v2.py
"""
FactCollector 包括的テスト

lib/capabilities/feedback/fact_collector.py のテスト
- FactCollectionError 例外
- UserInfo データクラス
- FactCollector 初期化
- タスクファクト収集（DBモック）
- 目標ファクト収集（DBモック）
- コミュニケーションファクト収集
- エラーハンドリング

Author: Claude Opus 4.5
Created: 2026-02-04
"""

import pytest
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, AsyncMock, patch
from uuid import UUID, uuid4

# Test target imports
from lib.capabilities.feedback.fact_collector import (
    FactCollectionError,
    UserInfo,
    FactCollector,
    create_fact_collector,
)
from lib.capabilities.feedback.constants import (
    AnalysisParameters,
    TrendDirection,
)
from lib.capabilities.feedback.models import (
    TaskFact,
    GoalFact,
    CommunicationFact,
    TeamFact,
    DailyFacts,
)


# =============================================================================
# テスト用ヘルパー
# =============================================================================


def create_mock_result(rows: List[tuple], single: bool = False):
    """SQLAlchemyクエリ結果のモックを作成"""
    mock_result = MagicMock()
    if single:
        mock_result.fetchone.return_value = rows[0] if rows else None
    else:
        mock_result.fetchall.return_value = rows
    return mock_result


def create_mock_connection():
    """SQLAlchemy Connection のモックを作成"""
    conn = MagicMock()
    conn.execute = MagicMock()
    return conn


# =============================================================================
# FactCollectionError テスト
# =============================================================================


class TestFactCollectionError:
    """FactCollectionError 例外クラスのテスト"""

    def test_basic_creation(self):
        """基本的なエラー作成"""
        error = FactCollectionError("テストエラー")
        assert str(error) == "テストエラー"
        assert error.message == "テストエラー"
        assert error.source == ""
        assert error.details == {}
        assert error.original_exception is None

    def test_with_source(self):
        """ソース指定ありのエラー作成"""
        error = FactCollectionError(
            message="収集エラー",
            source="collect_daily"
        )
        assert error.message == "収集エラー"
        assert error.source == "collect_daily"

    def test_with_details(self):
        """詳細情報ありのエラー作成"""
        details = {"target_date": "2026-02-04", "user_count": 10}
        error = FactCollectionError(
            message="収集エラー",
            source="collect_daily",
            details=details
        )
        assert error.details == details
        assert error.details["target_date"] == "2026-02-04"

    def test_with_original_exception(self):
        """元例外ありのエラー作成"""
        original = ValueError("元のエラー")
        error = FactCollectionError(
            message="ラップされたエラー",
            source="test",
            original_exception=original
        )
        assert error.original_exception is original
        assert isinstance(error.original_exception, ValueError)

    def test_inheritance(self):
        """Exception 継承の確認"""
        error = FactCollectionError("テスト")
        assert isinstance(error, Exception)

    def test_can_be_raised_and_caught(self):
        """raise/catchできることの確認"""
        with pytest.raises(FactCollectionError) as exc_info:
            raise FactCollectionError(
                message="テストエラー",
                source="test_source",
                details={"key": "value"}
            )

        assert "テストエラー" in str(exc_info.value)
        assert exc_info.value.source == "test_source"

    def test_details_default_to_empty_dict(self):
        """detailsがNoneの場合は空辞書になる"""
        error = FactCollectionError("test", details=None)
        assert error.details == {}


# =============================================================================
# UserInfo テスト
# =============================================================================


class TestUserInfo:
    """UserInfo データクラスのテスト"""

    def test_minimal_creation(self):
        """必須フィールドのみでの作成"""
        user = UserInfo(
            user_id="user123",
            name="山田太郎"
        )
        assert user.user_id == "user123"
        assert user.name == "山田太郎"
        assert user.chatwork_account_id is None
        assert user.department_id is None
        assert user.department_name is None
        assert user.is_active is True

    def test_full_creation(self):
        """全フィールド指定での作成"""
        user = UserInfo(
            user_id="user456",
            name="鈴木花子",
            chatwork_account_id="cw12345",
            department_id="dept001",
            department_name="営業部",
            is_active=False
        )
        assert user.user_id == "user456"
        assert user.name == "鈴木花子"
        assert user.chatwork_account_id == "cw12345"
        assert user.department_id == "dept001"
        assert user.department_name == "営業部"
        assert user.is_active is False

    def test_equality(self):
        """同一フィールドのUserInfoは等しい"""
        user1 = UserInfo(user_id="123", name="テスト")
        user2 = UserInfo(user_id="123", name="テスト")
        assert user1 == user2

    def test_inequality_different_id(self):
        """異なるIDのUserInfoは等しくない"""
        user1 = UserInfo(user_id="123", name="テスト")
        user2 = UserInfo(user_id="456", name="テスト")
        assert user1 != user2

    def test_is_dataclass(self):
        """dataclassであることの確認"""
        from dataclasses import is_dataclass
        assert is_dataclass(UserInfo)

    def test_default_is_active_true(self):
        """is_activeのデフォルトはTrue"""
        user = UserInfo(user_id="1", name="test")
        assert user.is_active is True


# =============================================================================
# FactCollector 初期化テスト
# =============================================================================


class TestFactCollectorInit:
    """FactCollector 初期化のテスト"""

    def test_basic_init(self):
        """基本的な初期化"""
        conn = create_mock_connection()
        org_id = uuid4()

        collector = FactCollector(conn=conn, org_id=org_id)

        assert collector.conn is conn
        assert collector.org_id == org_id
        assert collector._stale_days == AnalysisParameters.TASK_STALE_DAYS

    def test_init_with_custom_stale_days(self):
        """カスタムstale_daysでの初期化"""
        conn = create_mock_connection()
        org_id = uuid4()

        collector = FactCollector(conn=conn, org_id=org_id, stale_days=7)

        assert collector._stale_days == 7

    def test_properties(self):
        """プロパティのテスト"""
        conn = create_mock_connection()
        org_id = uuid4()

        collector = FactCollector(conn=conn, org_id=org_id)

        assert collector.conn is conn
        assert collector.org_id == org_id

    def test_logger_init_success(self):
        """ロガー初期化成功"""
        conn = create_mock_connection()
        org_id = uuid4()

        # lib.loggingがインポートできる場合、そのロガーが使われる
        with patch('lib.logging.get_logger') as mock_get_logger:
            mock_logger = MagicMock()
            mock_get_logger.return_value = mock_logger

            collector = FactCollector(conn=conn, org_id=org_id)

            # ロガーが初期化されていることを確認
            assert collector._logger is not None

    def test_logger_init_fallback(self):
        """ロガーインポート失敗時のフォールバック"""
        conn = create_mock_connection()
        org_id = uuid4()

        # get_loggerのインポートが失敗してもエラーにならない
        with patch.dict('sys.modules', {'lib.logging': None}):
            collector = FactCollector(conn=conn, org_id=org_id)
            assert collector._logger is not None


# =============================================================================
# create_fact_collector ファクトリー関数テスト
# =============================================================================


class TestCreateFactCollector:
    """create_fact_collector ファクトリー関数のテスト"""

    def test_basic_creation(self):
        """基本的なファクトリー作成"""
        conn = create_mock_connection()
        org_id = uuid4()

        collector = create_fact_collector(conn=conn, org_id=org_id)

        assert isinstance(collector, FactCollector)
        assert collector.conn is conn
        assert collector.org_id == org_id

    def test_with_custom_stale_days(self):
        """カスタムstale_daysでのファクトリー作成"""
        conn = create_mock_connection()
        org_id = uuid4()

        collector = create_fact_collector(conn=conn, org_id=org_id, stale_days=5)

        assert collector._stale_days == 5


# =============================================================================
# タスクファクト収集テスト
# =============================================================================


class TestTaskFactCollection:
    """タスクファクト収集のテスト"""

    @pytest.fixture
    def collector(self):
        """テスト用Collector"""
        conn = create_mock_connection()
        org_id = uuid4()
        return FactCollector(conn=conn, org_id=org_id)

    @pytest.fixture
    def sample_users(self):
        """サンプルユーザーリスト"""
        return [
            UserInfo(
                user_id="user1",
                name="山田太郎",
                chatwork_account_id="cw001"
            ),
            UserInfo(
                user_id="user2",
                name="鈴木花子",
                chatwork_account_id="cw002"
            ),
            UserInfo(
                user_id="user3",
                name="田中一郎",
                chatwork_account_id=None  # ChatWorkなし
            ),
        ]

    @pytest.mark.asyncio
    async def test_collect_task_facts_basic(self, collector, sample_users):
        """タスクファクト収集の基本テスト"""
        # モック設定: タスク集計クエリの結果
        task_summary_result = create_mock_result([
            (10, 7, 2, 1, 3)  # total, completed, overdue, stale, oldest_overdue
        ], single=True)

        # 今日のタスククエリ結果
        today_task_result = create_mock_result([
            (2, 3)  # created_today, completed_today
        ], single=True)

        collector._conn.execute.side_effect = [
            task_summary_result,
            today_task_result,
            task_summary_result,
            today_task_result,
        ]

        target_date = date.today()
        facts = await collector._collect_task_facts(sample_users, target_date)

        # ChatWorkアカウントのある2人分のファクト
        assert len(facts) == 2

        # 最初のユーザーのファクト確認
        fact = facts[0]
        assert fact.user_id == "user1"
        assert fact.user_name == "山田太郎"
        assert fact.total_tasks == 10
        assert fact.completed_tasks == 7
        assert fact.overdue_tasks == 2
        assert fact.stale_tasks == 1

    @pytest.mark.asyncio
    async def test_collect_task_facts_no_chatwork(self, collector):
        """ChatWorkアカウントなしユーザーはスキップ"""
        users = [
            UserInfo(user_id="user1", name="テスト", chatwork_account_id=None)
        ]

        target_date = date.today()
        facts = await collector._collect_task_facts(users, target_date)

        assert len(facts) == 0
        # DBクエリが呼ばれていないことを確認
        collector._conn.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_collect_task_facts_no_tasks(self, collector):
        """タスクがない場合はNone"""
        users = [
            UserInfo(user_id="user1", name="テスト", chatwork_account_id="cw001")
        ]

        # タスク数0の結果
        task_result = create_mock_result([
            (0, 0, 0, 0, 0)
        ], single=True)
        collector._conn.execute.return_value = task_result

        target_date = date.today()
        facts = await collector._collect_task_facts(users, target_date)

        assert len(facts) == 0

    @pytest.mark.asyncio
    async def test_collect_task_facts_db_error(self, collector):
        """DB例外時はユーザーをスキップ"""
        users = [
            UserInfo(user_id="user1", name="テスト", chatwork_account_id="cw001")
        ]

        collector._conn.execute.side_effect = Exception("DB接続エラー")

        target_date = date.today()
        # エラーが発生してもリストを返す（空リスト）
        facts = await collector._collect_task_facts(users, target_date)

        assert len(facts) == 0

    @pytest.mark.asyncio
    async def test_get_user_task_fact_none_result(self, collector):
        """クエリ結果がNoneの場合"""
        user = UserInfo(user_id="user1", name="テスト", chatwork_account_id="cw001")

        # fetchone が None を返す
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        collector._conn.execute.return_value = mock_result

        target_date = date.today()
        fact = await collector._get_user_task_fact(user, target_date)

        assert fact is None

    @pytest.mark.asyncio
    async def test_get_user_task_fact_with_today_query_error(self, collector):
        """今日のタスククエリがエラーでも基本データは返す"""
        user = UserInfo(user_id="user1", name="テスト", chatwork_account_id="cw001")

        # 1回目: 基本クエリ成功
        task_result = create_mock_result([
            (5, 3, 1, 0, 2)
        ], single=True)

        # 2回目: 今日のタスククエリ失敗
        def side_effect(*args, **kwargs):
            if collector._conn.execute.call_count == 1:
                return task_result
            else:
                raise Exception("今日のタスククエリエラー")

        collector._conn.execute.side_effect = side_effect

        target_date = date.today()
        fact = await collector._get_user_task_fact(user, target_date)

        # 基本データは取得できる
        assert fact is not None
        assert fact.total_tasks == 5
        assert fact.completed_tasks == 3
        # 今日のタスクはデフォルト値
        assert fact.tasks_created_today == 0
        assert fact.tasks_completed_today == 0


# =============================================================================
# 目標ファクト収集テスト
# =============================================================================


class TestGoalFactCollection:
    """目標ファクト収集のテスト"""

    @pytest.fixture
    def collector(self):
        """テスト用Collector"""
        conn = create_mock_connection()
        org_id = uuid4()
        return FactCollector(conn=conn, org_id=org_id)

    @pytest.fixture
    def sample_users(self):
        """サンプルユーザーリスト"""
        return [
            UserInfo(user_id="user1", name="山田太郎"),
            UserInfo(user_id="user2", name="鈴木花子"),
        ]

    @pytest.mark.asyncio
    async def test_collect_goal_facts_basic(self, collector, sample_users):
        """目標ファクト収集の基本テスト"""
        # 目標クエリ結果
        goal_rows = [
            (
                uuid4(),  # goal_id
                "user1",  # user_id
                "山田太郎",  # user_name
                "粗利300万円",  # title
                Decimal("3000000"),  # target_value
                Decimal("1500000"),  # current_value
                date.today() + timedelta(days=15),  # deadline
                None,  # period_end
                datetime.now() - timedelta(days=2),  # updated_at
            ),
            (
                uuid4(),
                "user2",
                "鈴木花子",
                "新規顧客10件",
                Decimal("10"),
                Decimal("7"),
                None,
                date.today() + timedelta(days=20),
                datetime.now() - timedelta(days=1),
            ),
        ]

        goal_result = create_mock_result(goal_rows)
        collector._conn.execute.return_value = goal_result

        target_date = date.today()
        facts = await collector._collect_goal_facts(sample_users, target_date)

        assert len(facts) == 2

        # 最初の目標ファクト確認
        fact1 = facts[0]
        assert fact1.user_id == "user1"
        assert fact1.user_name == "山田太郎"
        assert fact1.goal_title == "粗利300万円"
        assert fact1.target_value == 3000000.0
        assert fact1.current_value == 1500000.0
        assert fact1.progress_rate == 0.5  # 1500000 / 3000000
        assert fact1.days_remaining == 15

    @pytest.mark.asyncio
    async def test_collect_goal_facts_empty(self, collector, sample_users):
        """目標がない場合"""
        goal_result = create_mock_result([])
        collector._conn.execute.return_value = goal_result

        target_date = date.today()
        facts = await collector._collect_goal_facts(sample_users, target_date)

        assert len(facts) == 0

    @pytest.mark.asyncio
    async def test_collect_goal_facts_db_error(self, collector, sample_users):
        """DB例外時は空リスト"""
        collector._conn.execute.side_effect = Exception("DBエラー")

        target_date = date.today()
        facts = await collector._collect_goal_facts(sample_users, target_date)

        assert len(facts) == 0

    @pytest.mark.asyncio
    async def test_collect_goal_facts_zero_target(self, collector, sample_users):
        """目標値が0の場合は進捗率0"""
        goal_rows = [
            (
                uuid4(),
                "user1",
                "山田太郎",
                "テスト目標",
                Decimal("0"),  # target_value = 0
                Decimal("100"),
                date.today() + timedelta(days=10),
                None,
                datetime.now(),
            ),
        ]

        goal_result = create_mock_result(goal_rows)
        collector._conn.execute.return_value = goal_result

        target_date = date.today()
        facts = await collector._collect_goal_facts(sample_users, target_date)

        assert len(facts) == 1
        assert facts[0].progress_rate == 0.0

    @pytest.mark.asyncio
    async def test_collect_goal_facts_null_values(self, collector, sample_users):
        """NULL値の処理"""
        goal_rows = [
            (
                uuid4(),
                "user1",
                None,  # user_name = NULL
                "テスト目標",
                None,  # target_value = NULL
                None,  # current_value = NULL
                None,  # deadline = NULL
                None,  # period_end = NULL
                None,  # updated_at = NULL
            ),
        ]

        goal_result = create_mock_result(goal_rows)
        collector._conn.execute.return_value = goal_result

        target_date = date.today()
        facts = await collector._collect_goal_facts(sample_users, target_date)

        assert len(facts) == 1
        fact = facts[0]
        assert fact.user_name == "不明"
        assert fact.target_value == 0.0
        assert fact.current_value == 0.0
        assert fact.days_remaining == 0

    @pytest.mark.asyncio
    async def test_collect_goal_facts_old_updated(self, collector, sample_users):
        """更新が古い場合のトレンド判定"""
        goal_rows = [
            (
                uuid4(),
                "user1",
                "山田太郎",
                "テスト目標",
                Decimal("100"),
                Decimal("50"),
                date.today() + timedelta(days=10),
                None,
                datetime.now() - timedelta(days=10),  # 10日前に更新
            ),
        ]

        goal_result = create_mock_result(goal_rows)
        collector._conn.execute.return_value = goal_result

        target_date = date.today()
        facts = await collector._collect_goal_facts(sample_users, target_date)

        assert len(facts) == 1
        # 7日以上更新がないのでSTABLE
        assert facts[0].trend == TrendDirection.STABLE


# =============================================================================
# コミュニケーションファクト収集テスト
# =============================================================================


class TestCommunicationFactCollection:
    """コミュニケーションファクト収集のテスト"""

    @pytest.fixture
    def collector(self):
        """テスト用Collector"""
        conn = create_mock_connection()
        org_id = uuid4()
        return FactCollector(conn=conn, org_id=org_id)

    @pytest.fixture
    def sample_users(self):
        """サンプルユーザーリスト"""
        return [
            UserInfo(user_id="user1", name="山田太郎"),
            UserInfo(user_id="user2", name="鈴木花子"),
        ]

    @pytest.mark.asyncio
    async def test_collect_communication_facts_basic(self, collector, sample_users):
        """コミュニケーションファクト収集の基本テスト"""
        # メッセージ数クエリ結果
        message_result = create_mock_result([
            (5, 20)  # count_today, count_week
        ], single=True)

        # 感情スコアクエリ結果
        emotion_result = create_mock_result([
            (0.5,)  # avg_sentiment
        ], single=True)

        call_count = 0
        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count % 2 == 1:
                return message_result
            else:
                return emotion_result

        collector._conn.execute.side_effect = side_effect

        target_date = date.today()
        facts = await collector._collect_communication_facts(sample_users, target_date)

        assert len(facts) == 2

        fact = facts[0]
        assert fact.user_id == "user1"
        assert fact.user_name == "山田太郎"
        assert fact.message_count_today == 5
        assert fact.message_count_week == 20
        assert fact.sentiment_score == 0.5
        assert fact.sentiment_trend == TrendDirection.INCREASING

    @pytest.mark.asyncio
    async def test_collect_communication_facts_no_messages(self, collector, sample_users):
        """メッセージがない場合はスキップ"""
        message_result = create_mock_result([
            (0, 0)  # 両方0
        ], single=True)

        collector._conn.execute.return_value = message_result

        target_date = date.today()
        facts = await collector._collect_communication_facts(sample_users, target_date)

        assert len(facts) == 0

    @pytest.mark.asyncio
    async def test_collect_communication_facts_negative_sentiment(self, collector, sample_users):
        """ネガティブな感情スコア"""
        message_result = create_mock_result([
            (3, 10)
        ], single=True)

        emotion_result = create_mock_result([
            (-0.5,)  # ネガティブ
        ], single=True)

        call_count = 0
        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count % 2 == 1:
                return message_result
            else:
                return emotion_result

        collector._conn.execute.side_effect = side_effect

        target_date = date.today()
        facts = await collector._collect_communication_facts(sample_users, target_date)

        assert len(facts) == 2
        fact = facts[0]
        assert fact.sentiment_score == -0.5
        assert fact.sentiment_trend == TrendDirection.DECREASING

    @pytest.mark.asyncio
    async def test_collect_communication_facts_db_error(self, collector, sample_users):
        """DB例外時はユーザーをスキップ"""
        collector._conn.execute.side_effect = Exception("DBエラー")

        target_date = date.today()
        facts = await collector._collect_communication_facts(sample_users, target_date)

        assert len(facts) == 0

    @pytest.mark.asyncio
    async def test_get_user_communication_fact_table_not_exists(self, collector):
        """conversation_logsテーブルがない場合"""
        user = UserInfo(user_id="user1", name="テスト")
        target_start = datetime.now()
        target_end = target_start + timedelta(days=1)
        week_start = date.today() - timedelta(days=7)

        # テーブルなしエラー
        collector._conn.execute.side_effect = Exception("relation does not exist")

        fact = await collector._get_user_communication_fact(
            user, target_start, target_end, week_start
        )

        # メッセージ数0なのでNone
        assert fact is None

    @pytest.mark.asyncio
    async def test_communication_sentiment_neutral(self, collector, sample_users):
        """中立的な感情スコア（-0.3 < score < 0.3）"""
        message_result = create_mock_result([
            (5, 20)
        ], single=True)

        emotion_result = create_mock_result([
            (0.1,)  # 中立
        ], single=True)

        call_count = 0
        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count % 2 == 1:
                return message_result
            else:
                return emotion_result

        collector._conn.execute.side_effect = side_effect

        target_date = date.today()
        facts = await collector._collect_communication_facts(sample_users[:1], target_date)

        assert len(facts) == 1
        assert facts[0].sentiment_trend == TrendDirection.STABLE


# =============================================================================
# チームファクト集計テスト
# =============================================================================


class TestTeamFactAggregation:
    """チームファクト集計のテスト"""

    @pytest.fixture
    def collector(self):
        """テスト用Collector"""
        conn = create_mock_connection()
        org_id = uuid4()
        return FactCollector(conn=conn, org_id=org_id)

    @pytest.mark.asyncio
    async def test_aggregate_team_fact_basic(self, collector):
        """チームファクト集計の基本テスト"""
        task_facts = [
            TaskFact(
                user_id="user1",
                user_name="山田太郎",
                total_tasks=10,
                completed_tasks=8,
                overdue_tasks=1,
                stale_tasks=0,
                tasks_created_today=2,
                tasks_completed_today=3,
            ),
            TaskFact(
                user_id="user2",
                user_name="鈴木花子",
                total_tasks=5,
                completed_tasks=3,
                overdue_tasks=2,
                stale_tasks=0,
                tasks_created_today=0,
                tasks_completed_today=1,
            ),
        ]

        goal_facts = [
            GoalFact(
                user_id="user1",
                user_name="山田太郎",
                goal_id="goal1",
                goal_title="粗利目標",
                target_value=100,
                current_value=30,  # is_at_risk = True
                progress_rate=0.3,
                days_remaining=5,
            ),
        ]

        communication_facts = [
            CommunicationFact(
                user_id="user3",
                user_name="田中一郎",
                message_count_today=5,
                message_count_week=20,
            ),
        ]

        team_fact = await collector._aggregate_team_fact(
            task_facts=task_facts,
            goal_facts=goal_facts,
            communication_facts=communication_facts,
            total_members=5,
        )

        assert team_fact.total_members == 5
        assert team_fact.active_members == 3  # user1, user2 (tasks), user3 (communication)
        assert team_fact.total_overdue_tasks == 3  # 1 + 2
        assert team_fact.total_goals_at_risk == 1
        # 平均タスク完了率: (0.8 + 0.6) / 2 = 0.7
        assert abs(team_fact.avg_task_completion_rate - 0.7) < 0.01

    @pytest.mark.asyncio
    async def test_aggregate_team_fact_empty(self, collector):
        """空のファクトリスト"""
        team_fact = await collector._aggregate_team_fact(
            task_facts=[],
            goal_facts=[],
            communication_facts=[],
            total_members=0,
        )

        assert team_fact.total_members == 0
        assert team_fact.active_members == 0
        assert team_fact.avg_task_completion_rate == 0.0
        assert team_fact.total_overdue_tasks == 0
        assert team_fact.total_goals_at_risk == 0

    @pytest.mark.asyncio
    async def test_aggregate_team_fact_top_performers(self, collector):
        """トップパフォーマーの抽出"""
        task_facts = [
            TaskFact(
                user_id="user1",
                user_name="高達成者A",
                total_tasks=10,
                completed_tasks=9,  # 90%
            ),
            TaskFact(
                user_id="user2",
                user_name="高達成者B",
                total_tasks=10,
                completed_tasks=8,  # 80%
            ),
            TaskFact(
                user_id="user3",
                user_name="低達成者",
                total_tasks=10,
                completed_tasks=5,  # 50%
            ),
        ]

        team_fact = await collector._aggregate_team_fact(
            task_facts=task_facts,
            goal_facts=[],
            communication_facts=[],
            total_members=3,
        )

        # 80%以上のユーザーがトップパフォーマー
        assert "高達成者A" in team_fact.top_performers
        assert "高達成者B" in team_fact.top_performers
        assert "低達成者" not in team_fact.top_performers

    @pytest.mark.asyncio
    async def test_aggregate_team_fact_needs_attention(self, collector):
        """注意が必要なメンバーの抽出"""
        task_facts = [
            TaskFact(
                user_id="user1",
                user_name="期限超過多い人",
                total_tasks=10,
                completed_tasks=5,
                overdue_tasks=5,  # >= 3
                stale_tasks=2,
            ),
            TaskFact(
                user_id="user2",
                user_name="滞留タスク多い人",
                total_tasks=10,
                completed_tasks=5,
                overdue_tasks=0,
                stale_tasks=6,  # >= 5
            ),
            TaskFact(
                user_id="user3",
                user_name="問題なし",
                total_tasks=10,
                completed_tasks=8,
                overdue_tasks=1,
                stale_tasks=2,
            ),
        ]

        communication_facts = [
            CommunicationFact(
                user_id="user4",
                user_name="感情面で気になる人",
                message_count_today=5,
                message_count_week=20,
                sentiment_score=-0.5,
                sentiment_trend=TrendDirection.DROP,
            ),
        ]

        team_fact = await collector._aggregate_team_fact(
            task_facts=task_facts,
            goal_facts=[],
            communication_facts=communication_facts,
            total_members=4,
        )

        assert "期限超過多い人" in team_fact.members_needing_attention
        assert "滞留タスク多い人" in team_fact.members_needing_attention
        assert "感情面で気になる人" in team_fact.members_needing_attention
        assert "問題なし" not in team_fact.members_needing_attention


# =============================================================================
# 組織ユーザー取得テスト
# =============================================================================


class TestGetOrganizationUsers:
    """組織ユーザー取得のテスト"""

    @pytest.fixture
    def collector(self):
        """テスト用Collector"""
        conn = create_mock_connection()
        org_id = uuid4()
        return FactCollector(conn=conn, org_id=org_id)

    @pytest.mark.asyncio
    async def test_get_organization_users_basic(self, collector):
        """組織ユーザー取得の基本テスト"""
        user_rows = [
            (uuid4(), "山田太郎", "cw001", uuid4(), "営業部"),
            (uuid4(), "鈴木花子", "cw002", uuid4(), "開発部"),
            (uuid4(), None, None, None, None),  # 名前なし
        ]

        user_result = create_mock_result(user_rows)
        collector._conn.execute.return_value = user_result

        users = await collector._get_organization_users()

        assert len(users) == 3
        assert users[0].name == "山田太郎"
        assert users[0].chatwork_account_id == "cw001"
        assert users[0].department_name == "営業部"

        # 名前がNullの場合は「不明」
        assert users[2].name == "不明"

    @pytest.mark.asyncio
    async def test_get_organization_users_empty(self, collector):
        """ユーザーがいない場合"""
        user_result = create_mock_result([])
        collector._conn.execute.return_value = user_result

        users = await collector._get_organization_users()

        assert len(users) == 0

    @pytest.mark.asyncio
    async def test_get_organization_users_db_error(self, collector):
        """DB例外時は空リスト"""
        collector._conn.execute.side_effect = Exception("DBエラー")

        users = await collector._get_organization_users()

        assert len(users) == 0


# =============================================================================
# 既存インサイト取得テスト
# =============================================================================


class TestGetExistingInsights:
    """既存インサイト取得のテスト"""

    @pytest.fixture
    def collector(self):
        """テスト用Collector"""
        conn = create_mock_connection()
        org_id = uuid4()
        return FactCollector(conn=conn, org_id=org_id)

    @pytest.mark.asyncio
    async def test_get_existing_insights_basic(self, collector):
        """既存インサイト取得の基本テスト"""
        insight_rows = [
            (
                uuid4(),  # id
                "task_overdue",  # insight_type
                "a1_task",  # source_type
                "high",  # importance
                "期限超過タスク",  # title
                "タスクが期限を超過しています",  # description
                "期限を確認してください",  # recommended_action
                {"user_id": "user1"},  # evidence
                "new",  # status
                datetime.now(),  # created_at
            ),
        ]

        insight_result = create_mock_result(insight_rows)
        collector._conn.execute.return_value = insight_result

        target_date = date.today()
        insights = await collector._get_existing_insights(target_date)

        assert len(insights) == 1
        insight = insights[0]
        assert insight["insight_type"] == "task_overdue"
        assert insight["importance"] == "high"
        assert insight["title"] == "期限超過タスク"

    @pytest.mark.asyncio
    async def test_get_existing_insights_empty(self, collector):
        """インサイトがない場合"""
        insight_result = create_mock_result([])
        collector._conn.execute.return_value = insight_result

        target_date = date.today()
        insights = await collector._get_existing_insights(target_date)

        assert len(insights) == 0

    @pytest.mark.asyncio
    async def test_get_existing_insights_db_error(self, collector):
        """DB例外時は空リスト"""
        collector._conn.execute.side_effect = Exception("DBエラー")

        target_date = date.today()
        insights = await collector._get_existing_insights(target_date)

        assert len(insights) == 0

    @pytest.mark.asyncio
    async def test_get_existing_insights_null_evidence(self, collector):
        """evidenceがNULLの場合は空辞書"""
        insight_rows = [
            (
                uuid4(),
                "test",
                "test",
                "medium",
                "テスト",
                "説明",
                "アクション",
                None,  # evidence = NULL
                "new",
                datetime.now(),
            ),
        ]

        insight_result = create_mock_result(insight_rows)
        collector._conn.execute.return_value = insight_result

        target_date = date.today()
        insights = await collector._get_existing_insights(target_date)

        assert len(insights) == 1
        assert insights[0]["evidence"] == {}

    @pytest.mark.asyncio
    async def test_get_existing_insights_null_created_at(self, collector):
        """created_atがNULLの場合"""
        insight_rows = [
            (
                uuid4(),
                "test",
                "test",
                "medium",
                "テスト",
                "説明",
                "アクション",
                {},
                "new",
                None,  # created_at = NULL
            ),
        ]

        insight_result = create_mock_result(insight_rows)
        collector._conn.execute.return_value = insight_result

        target_date = date.today()
        insights = await collector._get_existing_insights(target_date)

        assert len(insights) == 1
        assert insights[0]["created_at"] is None


# =============================================================================
# collect_daily 統合テスト
# =============================================================================


class TestCollectDaily:
    """collect_daily 統合テスト"""

    @pytest.fixture
    def collector(self):
        """テスト用Collector"""
        conn = create_mock_connection()
        org_id = uuid4()
        return FactCollector(conn=conn, org_id=org_id)

    @pytest.mark.asyncio
    async def test_collect_daily_basic(self, collector):
        """日次ファクト収集の基本テスト"""
        # ユーザー取得
        user_rows = [
            (uuid4(), "山田太郎", "cw001", uuid4(), "営業部"),
        ]

        # タスククエリ結果
        task_summary = [(5, 3, 1, 0, 2)]
        task_today = [(1, 2)]

        # 目標クエリ結果（空）
        goal_rows = []

        # メッセージ数クエリ結果
        message_rows = [(0, 0)]

        # 既存インサイト（空）
        insight_rows = []

        # モック設定
        call_count = 0
        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # ユーザー取得
                return create_mock_result(user_rows)
            elif call_count == 2:
                # タスク集計
                return create_mock_result(task_summary, single=True)
            elif call_count == 3:
                # 今日のタスク
                return create_mock_result(task_today, single=True)
            elif call_count == 4:
                # 目標
                return create_mock_result(goal_rows)
            elif call_count == 5:
                # メッセージ
                return create_mock_result(message_rows, single=True)
            else:
                # 既存インサイト
                return create_mock_result(insight_rows)

        collector._conn.execute.side_effect = side_effect

        facts = await collector.collect_daily()

        assert isinstance(facts, DailyFacts)
        assert facts.date == date.today()
        assert facts.organization_id == str(collector.org_id)
        assert len(facts.task_facts) == 1
        assert facts.team_fact is not None

    @pytest.mark.asyncio
    async def test_collect_daily_with_target_date(self, collector):
        """指定日での日次ファクト収集"""
        target_date = date(2026, 2, 1)

        # 空の結果を返す
        empty_result = create_mock_result([])
        collector._conn.execute.return_value = empty_result

        facts = await collector.collect_daily(target_date=target_date)

        assert facts.date == target_date

    @pytest.mark.asyncio
    async def test_collect_daily_error_handling(self, collector):
        """日次ファクト収集のエラーハンドリング

        Note: _get_organization_users, _collect_goal_facts, _get_existing_insights
        はそれぞれ例外を捕捉して空リストを返すため、
        FactCollectionErrorが発生するのは _aggregate_team_fact 等の
        内部処理でエラーが起きた場合のみ。

        ここでは _aggregate_team_fact にモックを設定してエラーを発生させる。
        """
        # ユーザー取得は空リスト（エラーをキャッチ）
        empty_result = create_mock_result([])
        collector._conn.execute.return_value = empty_result

        # _aggregate_team_fact でエラーを発生させる
        with patch.object(collector, '_aggregate_team_fact', side_effect=Exception("集計エラー")):
            with pytest.raises(FactCollectionError) as exc_info:
                await collector.collect_daily()

            error = exc_info.value
            assert error.source == "collect_daily"
            assert "日次ファクト収集に失敗しました" in error.message
            assert error.original_exception is not None


# =============================================================================
# collect_weekly テスト
# =============================================================================


class TestCollectWeekly:
    """collect_weekly テスト"""

    @pytest.fixture
    def collector(self):
        """テスト用Collector"""
        conn = create_mock_connection()
        org_id = uuid4()
        return FactCollector(conn=conn, org_id=org_id)

    @pytest.mark.asyncio
    async def test_collect_weekly_basic(self, collector):
        """週次ファクト収集の基本テスト"""
        # 空の結果を返す
        empty_result = create_mock_result([])
        collector._conn.execute.return_value = empty_result

        # 今日が水曜日の場合、月曜から水曜の3日分
        today = date.today()
        week_start = today - timedelta(days=today.weekday())

        weekly_facts = await collector.collect_weekly(week_start=week_start)

        # 今日までの日数分のファクト
        expected_days = today.weekday() + 1  # 月曜=0なので+1
        assert len(weekly_facts) == expected_days

    @pytest.mark.asyncio
    async def test_collect_weekly_default_start(self, collector):
        """デフォルト週開始日での収集"""
        empty_result = create_mock_result([])
        collector._conn.execute.return_value = empty_result

        weekly_facts = await collector.collect_weekly()

        # 少なくとも1日分はある（今日）
        assert len(weekly_facts) >= 1

    @pytest.mark.asyncio
    async def test_collect_weekly_future_dates_skipped(self, collector):
        """未来の日付はスキップされる"""
        empty_result = create_mock_result([])
        collector._conn.execute.return_value = empty_result

        # 先週の月曜から始める（全7日分）
        today = date.today()
        last_week_start = today - timedelta(days=today.weekday() + 7)

        weekly_facts = await collector.collect_weekly(week_start=last_week_start)

        # 全7日分取得できる
        assert len(weekly_facts) == 7


# =============================================================================
# モデル連携テスト
# =============================================================================


class TestModelIntegration:
    """FactCollector とモデルの連携テスト"""

    def test_task_fact_completion_rate(self):
        """TaskFactのcompletion_rate計算"""
        fact = TaskFact(
            user_id="user1",
            user_name="テスト",
            total_tasks=10,
            completed_tasks=7,
        )
        assert abs(fact.completion_rate - 0.7) < 0.01

    def test_task_fact_completion_rate_zero_total(self):
        """total_tasks=0の場合のcompletion_rate"""
        fact = TaskFact(
            user_id="user1",
            user_name="テスト",
            total_tasks=0,
            completed_tasks=0,
        )
        assert fact.completion_rate == 0.0

    def test_task_fact_has_issues(self):
        """TaskFactのhas_issues判定"""
        fact_with_overdue = TaskFact(
            user_id="user1",
            user_name="テスト",
            overdue_tasks=1,
        )
        assert fact_with_overdue.has_issues is True

        fact_with_stale = TaskFact(
            user_id="user1",
            user_name="テスト",
            stale_tasks=1,
        )
        assert fact_with_stale.has_issues is True

        fact_no_issues = TaskFact(
            user_id="user1",
            user_name="テスト",
        )
        assert fact_no_issues.has_issues is False

    def test_goal_fact_is_at_risk(self):
        """GoalFactのis_at_risk判定"""
        # リスクあり: progress_rate < 0.5 かつ on_track でない
        fact_at_risk = GoalFact(
            user_id="user1",
            user_name="テスト",
            goal_id="g1",
            goal_title="目標",
            target_value=100,
            current_value=20,
            progress_rate=0.2,
            days_remaining=5,
        )
        assert fact_at_risk.is_at_risk is True

        # リスクなし: progress_rate >= 0.5
        fact_ok = GoalFact(
            user_id="user1",
            user_name="テスト",
            goal_id="g1",
            goal_title="目標",
            target_value=100,
            current_value=60,
            progress_rate=0.6,
            days_remaining=5,
        )
        assert fact_ok.is_at_risk is False

    def test_communication_fact_is_sentiment_concerning(self):
        """CommunicationFactのis_sentiment_concerning判定"""
        # 懸念あり: sentiment_score < -0.3
        fact_concerning = CommunicationFact(
            user_id="user1",
            user_name="テスト",
            sentiment_score=-0.5,
        )
        assert fact_concerning.is_sentiment_concerning is True

        # 懸念あり: sentiment_trend == DROP
        fact_drop = CommunicationFact(
            user_id="user1",
            user_name="テスト",
            sentiment_score=0.0,
            sentiment_trend=TrendDirection.DROP,
        )
        assert fact_drop.is_sentiment_concerning is True

        # 懸念なし
        fact_ok = CommunicationFact(
            user_id="user1",
            user_name="テスト",
            sentiment_score=0.1,
            sentiment_trend=TrendDirection.STABLE,
        )
        assert fact_ok.is_sentiment_concerning is False

    def test_team_fact_activity_rate(self):
        """TeamFactのactivity_rate計算"""
        fact = TeamFact(
            organization_id="org1",
            total_members=10,
            active_members=7,
        )
        assert abs(fact.activity_rate - 0.7) < 0.01

        # total_members=0の場合
        fact_zero = TeamFact(
            organization_id="org1",
            total_members=0,
            active_members=0,
        )
        assert fact_zero.activity_rate == 0.0

    def test_daily_facts_to_dict(self):
        """DailyFactsのto_dict"""
        facts = DailyFacts(
            date=date(2026, 2, 4),
            organization_id="org123",
            task_facts=[
                TaskFact(user_id="u1", user_name="テスト")
            ],
        )

        result = facts.to_dict()

        assert result["date"] == "2026-02-04"
        assert result["organization_id"] == "org123"
        assert len(result["task_facts"]) == 1
