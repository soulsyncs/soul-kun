"""
lib/brain/outcome_learning/analyzer.py のテスト
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from lib.brain.outcome_learning.analyzer import OutcomeAnalyzer, create_outcome_analyzer
from lib.brain.outcome_learning.models import OutcomeStatistics, OutcomeInsight
from lib.brain.outcome_learning.constants import MIN_SAMPLE_COUNT, MIN_SUCCESS_RATE


class TestOutcomeAnalyzer:
    """OutcomeAnalyzerのテスト"""

    @pytest.fixture
    def mock_repository(self):
        """リポジトリのモック"""
        return MagicMock()

    @pytest.fixture
    def analyzer(self, mock_repository):
        """テスト対象のAnalyzer"""
        return OutcomeAnalyzer(
            organization_id="test-org-id",
            repository=mock_repository,
        )

    @pytest.fixture
    def mock_conn(self):
        """DBコネクションのモック"""
        return MagicMock()

    # =========================================================================
    # __init__
    # =========================================================================

    def test_init(self, mock_repository):
        """初期化テスト"""
        analyzer = OutcomeAnalyzer("org-123", mock_repository)
        assert analyzer.organization_id == "org-123"
        assert analyzer.repository == mock_repository

    # =========================================================================
    # analyze_user_responsiveness
    # =========================================================================

    def test_analyze_user_responsiveness_basic(self, analyzer, mock_repository, mock_conn):
        """ユーザー反応傾向分析の基本テスト"""
        # モックの設定
        mock_stats = OutcomeStatistics(
            total_events=100,
            adopted_count=60,
            delayed_count=20,
            ignored_count=20,
            adoption_rate=0.6,
            ignore_rate=0.2,
        )
        mock_repository.get_statistics.return_value = mock_stats
        mock_repository.get_hourly_statistics.return_value = {
            9: {"total": 30, "adopted": 20, "ignored": 10},
            14: {"total": 40, "adopted": 30, "ignored": 10},
        }
        mock_repository.get_day_of_week_statistics.return_value = {
            1: {"total": 25, "adopted": 15, "ignored": 10},  # 月曜日
            3: {"total": 30, "adopted": 25, "ignored": 5},   # 水曜日
        }

        result = analyzer.analyze_user_responsiveness(mock_conn, "user-123", days=30)

        assert result["account_id"] == "user-123"
        assert result["period_days"] == 30
        assert result["total_events"] == 100
        assert result["adoption_rate"] == 0.6
        assert result["ignore_rate"] == 0.2
        assert "best_hour" in result
        assert "best_day" in result
        assert "responsiveness_score" in result

    def test_analyze_user_responsiveness_empty_data(self, analyzer, mock_repository, mock_conn):
        """データがない場合のテスト"""
        mock_stats = OutcomeStatistics(
            total_events=0,
            adopted_count=0,
            delayed_count=0,
            ignored_count=0,
        )
        mock_repository.get_statistics.return_value = mock_stats
        mock_repository.get_hourly_statistics.return_value = {}
        mock_repository.get_day_of_week_statistics.return_value = {}

        result = analyzer.analyze_user_responsiveness(mock_conn, "user-123")

        assert result["total_events"] == 0
        assert result["best_hour"] is None
        assert result["best_day"] is None
        assert result["responsiveness_score"] == 0.5  # デフォルト値

    # =========================================================================
    # analyze_timing_effectiveness
    # =========================================================================

    def test_analyze_timing_effectiveness_basic(self, analyzer, mock_repository, mock_conn):
        """時間帯別効果分析の基本テスト"""
        mock_repository.get_hourly_statistics.return_value = {
            9: {"total": 30, "adopted": 25, "ignored": 5},
            10: {"total": 20, "adopted": 10, "ignored": 10},
            14: {"total": 40, "adopted": 35, "ignored": 5},
        }

        result = analyzer.analyze_timing_effectiveness(mock_conn, days=30)

        assert result["period_days"] == 30
        assert "hourly_analysis" in result
        assert 9 in result["hourly_analysis"]
        assert result["hourly_analysis"][9]["success_rate"] == pytest.approx(25/30)
        assert "best_hours" in result

    def test_analyze_timing_effectiveness_with_account_id(self, analyzer, mock_repository, mock_conn):
        """特定ユーザーの時間帯別効果分析テスト"""
        mock_repository.get_hourly_statistics.return_value = {
            11: {"total": 15, "adopted": 12, "ignored": 3},
        }

        result = analyzer.analyze_timing_effectiveness(
            mock_conn, account_id="user-456", days=14
        )

        assert result["account_id"] == "user-456"
        assert result["period_days"] == 14
        mock_repository.get_hourly_statistics.assert_called_with(
            mock_conn, target_account_id="user-456", days=14
        )

    def test_analyze_timing_effectiveness_filters_low_sample(self, analyzer, mock_repository, mock_conn):
        """サンプル数が少ない時間帯はbest_hoursから除外"""
        mock_repository.get_hourly_statistics.return_value = {
            9: {"total": MIN_SAMPLE_COUNT - 1, "adopted": MIN_SAMPLE_COUNT - 2, "ignored": 1},
            14: {"total": MIN_SAMPLE_COUNT + 10, "adopted": MIN_SAMPLE_COUNT + 5, "ignored": 5},
        }

        result = analyzer.analyze_timing_effectiveness(mock_conn)

        # best_hoursにはサンプル数が十分な時間帯のみ含まれる
        best_hour_hours = [h["hour"] for h in result["best_hours"]]
        assert 9 not in best_hour_hours
        assert 14 in best_hour_hours

    # =========================================================================
    # generate_insights
    # =========================================================================

    def test_generate_insights_low_adoption_rate(self, analyzer, mock_repository, mock_conn):
        """採用率が低い場合のインサイト生成テスト"""
        mock_stats = OutcomeStatistics(
            total_events=MIN_SAMPLE_COUNT + 10,
            adopted_count=10,
            delayed_count=5,
            ignored_count=MIN_SAMPLE_COUNT - 5,
        )
        mock_repository.get_statistics.return_value = mock_stats
        mock_repository.get_hourly_statistics.return_value = {}
        mock_repository.get_day_of_week_statistics.return_value = {}

        insights = analyzer.generate_insights(mock_conn, days=30)

        # 採用率が低いインサイトが含まれる
        insight_types = [i.insight_type for i in insights]
        assert "low_adoption_rate" in insight_types

    def test_generate_insights_best_timing(self, analyzer, mock_repository, mock_conn):
        """最も効果的な時間帯のインサイト生成テスト"""
        mock_stats = OutcomeStatistics(
            total_events=MIN_SAMPLE_COUNT - 1,  # 全体は条件を満たさない
            adopted_count=5,
            delayed_count=2,
            ignored_count=2,
        )
        mock_repository.get_statistics.return_value = mock_stats
        mock_repository.get_hourly_statistics.return_value = {
            10: {"total": MIN_SAMPLE_COUNT + 5, "adopted": MIN_SAMPLE_COUNT, "ignored": 5},
        }
        mock_repository.get_day_of_week_statistics.return_value = {}

        insights = analyzer.generate_insights(mock_conn)

        # 成功率が高い場合、best_timingインサイトが生成される
        insight_types = [i.insight_type for i in insights]
        if MIN_SAMPLE_COUNT / (MIN_SAMPLE_COUNT + 5) >= MIN_SUCCESS_RATE:
            assert "best_timing" in insight_types

    def test_generate_insights_best_day_of_week(self, analyzer, mock_repository, mock_conn):
        """最も効果的な曜日のインサイト生成テスト"""
        mock_stats = OutcomeStatistics(
            total_events=MIN_SAMPLE_COUNT - 1,
            adopted_count=5,
            delayed_count=2,
            ignored_count=2,
        )
        mock_repository.get_statistics.return_value = mock_stats
        mock_repository.get_hourly_statistics.return_value = {}
        mock_repository.get_day_of_week_statistics.return_value = {
            2: {"total": MIN_SAMPLE_COUNT + 10, "adopted": MIN_SAMPLE_COUNT + 5, "ignored": 5},
        }

        insights = analyzer.generate_insights(mock_conn)

        insight_types = [i.insight_type for i in insights]
        # 成功率が閾値以上ならインサイトが生成される
        success_rate = (MIN_SAMPLE_COUNT + 5) / (MIN_SAMPLE_COUNT + 10)
        if success_rate >= MIN_SUCCESS_RATE:
            assert "best_day_of_week" in insight_types

    def test_generate_insights_empty_data(self, analyzer, mock_repository, mock_conn):
        """データがない場合のインサイト生成テスト"""
        mock_stats = OutcomeStatistics(
            total_events=0,
            adopted_count=0,
            delayed_count=0,
            ignored_count=0,
        )
        mock_repository.get_statistics.return_value = mock_stats
        mock_repository.get_hourly_statistics.return_value = {}
        mock_repository.get_day_of_week_statistics.return_value = {}

        insights = analyzer.generate_insights(mock_conn)

        assert insights == []

    # =========================================================================
    # _find_best_hour
    # =========================================================================

    def test_find_best_hour_returns_highest_rate(self, analyzer):
        """最も成功率の高い時間帯を返すテスト"""
        hourly_stats = {
            9: {"total": MIN_SAMPLE_COUNT, "adopted": MIN_SAMPLE_COUNT - 5, "ignored": 5},
            14: {"total": MIN_SAMPLE_COUNT, "adopted": MIN_SAMPLE_COUNT - 2, "ignored": 2},
            17: {"total": MIN_SAMPLE_COUNT, "adopted": MIN_SAMPLE_COUNT - 8, "ignored": 8},
        }

        result = analyzer._find_best_hour(hourly_stats)

        assert result is not None
        assert result["hour"] == 14  # 最も成功率が高い

    def test_find_best_hour_filters_low_sample(self, analyzer):
        """サンプル数が少ない時間帯は除外されるテスト"""
        hourly_stats = {
            9: {"total": MIN_SAMPLE_COUNT - 1, "adopted": MIN_SAMPLE_COUNT - 2, "ignored": 1},
            14: {"total": MIN_SAMPLE_COUNT, "adopted": MIN_SAMPLE_COUNT - 5, "ignored": 5},
        }

        result = analyzer._find_best_hour(hourly_stats)

        assert result is not None
        assert result["hour"] == 14

    def test_find_best_hour_empty(self, analyzer):
        """時間帯データがない場合はNoneを返すテスト"""
        result = analyzer._find_best_hour({})
        assert result is None

    # =========================================================================
    # _find_best_day
    # =========================================================================

    def test_find_best_day_returns_highest_rate(self, analyzer):
        """最も成功率の高い曜日を返すテスト"""
        dow_stats = {
            1: {"total": MIN_SAMPLE_COUNT, "adopted": MIN_SAMPLE_COUNT - 3, "ignored": 3},
            3: {"total": MIN_SAMPLE_COUNT, "adopted": MIN_SAMPLE_COUNT - 1, "ignored": 1},
            5: {"total": MIN_SAMPLE_COUNT, "adopted": MIN_SAMPLE_COUNT - 5, "ignored": 5},
        }

        result = analyzer._find_best_day(dow_stats)

        assert result is not None
        assert result["day_of_week"] == 3  # 水曜日が最も成功率が高い

    def test_find_best_day_filters_low_sample(self, analyzer):
        """サンプル数が少ない曜日は除外されるテスト"""
        dow_stats = {
            1: {"total": MIN_SAMPLE_COUNT - 1, "adopted": MIN_SAMPLE_COUNT - 2, "ignored": 1},
            3: {"total": MIN_SAMPLE_COUNT, "adopted": MIN_SAMPLE_COUNT - 5, "ignored": 5},
        }

        result = analyzer._find_best_day(dow_stats)

        assert result is not None
        assert result["day_of_week"] == 3

    def test_find_best_day_empty(self, analyzer):
        """曜日データがない場合はNoneを返すテスト"""
        result = analyzer._find_best_day({})
        assert result is None

    def test_find_best_day_includes_day_name(self, analyzer):
        """曜日名が含まれるテスト"""
        dow_stats = {
            0: {"total": MIN_SAMPLE_COUNT, "adopted": MIN_SAMPLE_COUNT - 2, "ignored": 2},
        }

        result = analyzer._find_best_day(dow_stats)

        assert result is not None
        assert "day_name" in result

    # =========================================================================
    # _calculate_responsiveness_score
    # =========================================================================

    def test_calculate_responsiveness_score_zero_events(self, analyzer):
        """イベント数が0の場合のスコア計算テスト"""
        stats = OutcomeStatistics(
            total_events=0,
            adopted_count=0,
            delayed_count=0,
            ignored_count=0,
        )

        score = analyzer._calculate_responsiveness_score(stats)

        assert score == 0.5  # デフォルト値

    def test_calculate_responsiveness_score_all_adopted(self, analyzer):
        """全て採用された場合のスコア計算テスト"""
        stats = OutcomeStatistics(
            total_events=10,
            adopted_count=10,
            delayed_count=0,
            ignored_count=0,
        )

        score = analyzer._calculate_responsiveness_score(stats)

        assert score == 1.0

    def test_calculate_responsiveness_score_all_ignored(self, analyzer):
        """全て無視された場合のスコア計算テスト"""
        stats = OutcomeStatistics(
            total_events=10,
            adopted_count=0,
            delayed_count=0,
            ignored_count=10,
        )

        score = analyzer._calculate_responsiveness_score(stats)

        assert score == 0.0

    def test_calculate_responsiveness_score_mixed(self, analyzer):
        """混合パターンのスコア計算テスト"""
        stats = OutcomeStatistics(
            total_events=10,
            adopted_count=4,
            delayed_count=4,
            ignored_count=2,
        )

        score = analyzer._calculate_responsiveness_score(stats)

        # adopted=1.0, delayed=0.5, ignored=0.0 の重み付け
        expected = (4 * 1.0 + 4 * 0.5 + 2 * 0.0) / (10 * 1.0)
        assert score == pytest.approx(expected)

    # =========================================================================
    # _generate_timing_recommendation
    # =========================================================================

    def test_generate_timing_recommendation_high_success(self, analyzer):
        """成功率が高い場合の推奨メッセージテスト"""
        best_hours = [(10, {"total": MIN_SAMPLE_COUNT, "success_rate": 0.75})]

        result = analyzer._generate_timing_recommendation(best_hours)

        assert result is not None
        assert "10時" in result
        assert "効果的" in result

    def test_generate_timing_recommendation_medium_success(self, analyzer):
        """成功率が中程度の場合の推奨メッセージテスト"""
        best_hours = [(14, {"total": MIN_SAMPLE_COUNT, "success_rate": 0.55})]

        result = analyzer._generate_timing_recommendation(best_hours)

        assert result is not None
        assert "14時" in result

    def test_generate_timing_recommendation_low_success(self, analyzer):
        """成功率が低い場合は推奨なしテスト"""
        best_hours = [(9, {"total": MIN_SAMPLE_COUNT, "success_rate": 0.3})]

        result = analyzer._generate_timing_recommendation(best_hours)

        assert result is None

    def test_generate_timing_recommendation_low_sample(self, analyzer):
        """サンプル数が少ない場合は推奨なしテスト"""
        best_hours = [(9, {"total": MIN_SAMPLE_COUNT - 1, "success_rate": 0.9})]

        result = analyzer._generate_timing_recommendation(best_hours)

        assert result is None

    def test_generate_timing_recommendation_empty(self, analyzer):
        """データがない場合は推奨なしテスト"""
        result = analyzer._generate_timing_recommendation([])
        assert result is None


class TestCreateOutcomeAnalyzer:
    """create_outcome_analyzerファクトリ関数のテスト"""

    def test_create_with_repository(self):
        """リポジトリを指定して作成"""
        mock_repo = MagicMock()
        analyzer = create_outcome_analyzer("org-123", repository=mock_repo)

        assert analyzer.organization_id == "org-123"
        assert analyzer.repository == mock_repo

    def test_create_without_repository(self):
        """リポジトリなしで作成（新規作成される）"""
        analyzer = create_outcome_analyzer("org-456")

        assert analyzer.organization_id == "org-456"
        assert analyzer.repository is not None
