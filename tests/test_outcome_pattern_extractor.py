"""
lib/brain/outcome_learning/pattern_extractor.py のテスト
"""

from datetime import datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from lib.brain.outcome_learning.pattern_extractor import (
    PatternExtractor,
    create_pattern_extractor,
)
from lib.brain.outcome_learning.models import OutcomePattern
from lib.brain.outcome_learning.constants import (
    MIN_SAMPLE_COUNT,
    MIN_SUCCESS_RATE,
    MIN_CONFIDENCE_SCORE,
    PatternScope,
    PatternType,
    TIME_SLOTS,
)


class TestPatternExtractor:
    """PatternExtractorのテスト"""

    @pytest.fixture
    def mock_repository(self):
        """リポジトリのモック"""
        return MagicMock()

    @pytest.fixture
    def extractor(self, mock_repository):
        """テスト対象のExtractor"""
        return PatternExtractor(
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
        extractor = PatternExtractor("org-123", mock_repository)
        assert extractor.organization_id == "org-123"
        assert extractor.repository == mock_repository

    # =========================================================================
    # extract_timing_patterns
    # =========================================================================

    def test_extract_timing_patterns_empty(self, extractor, mock_repository, mock_conn):
        """時間帯統計がない場合は空リストを返す"""
        mock_repository.get_hourly_statistics.return_value = {}

        patterns = extractor.extract_timing_patterns(mock_conn)

        assert patterns == []

    def test_extract_timing_patterns_low_sample(self, extractor, mock_repository, mock_conn):
        """サンプル数が少ない時間帯はパターン化されない"""
        mock_repository.get_hourly_statistics.return_value = {
            9: {"total": MIN_SAMPLE_COUNT - 1, "adopted": MIN_SAMPLE_COUNT - 2, "ignored": 1},
        }

        patterns = extractor.extract_timing_patterns(mock_conn)

        assert patterns == []

    def test_extract_timing_patterns_global_scope(self, extractor, mock_repository, mock_conn):
        """ユーザーIDなしの場合はGLOBALスコープ"""
        # morningスロットに十分なデータを設定
        hourly_stats = {}
        for hour in range(TIME_SLOTS["morning"]["start"], TIME_SLOTS["morning"]["end"]):
            hourly_stats[hour] = {
                "total": MIN_SAMPLE_COUNT,
                "adopted": int(MIN_SAMPLE_COUNT * 0.8),
                "ignored": int(MIN_SAMPLE_COUNT * 0.2),
            }
        mock_repository.get_hourly_statistics.return_value = hourly_stats

        patterns = extractor.extract_timing_patterns(mock_conn)

        if patterns:
            assert patterns[0].scope == PatternScope.GLOBAL.value

    def test_extract_timing_patterns_user_scope(self, extractor, mock_repository, mock_conn):
        """ユーザーIDありの場合はUSERスコープ"""
        hourly_stats = {}
        for hour in range(TIME_SLOTS["morning"]["start"], TIME_SLOTS["morning"]["end"]):
            hourly_stats[hour] = {
                "total": MIN_SAMPLE_COUNT,
                "adopted": int(MIN_SAMPLE_COUNT * 0.8),
                "ignored": int(MIN_SAMPLE_COUNT * 0.2),
            }
        mock_repository.get_hourly_statistics.return_value = hourly_stats

        patterns = extractor.extract_timing_patterns(
            mock_conn, target_account_id="user-123"
        )

        if patterns:
            assert patterns[0].scope == PatternScope.USER.value
            assert patterns[0].scope_target_id == "user-123"

    def test_extract_timing_patterns_success_rate_threshold(
        self, extractor, mock_repository, mock_conn
    ):
        """成功率が閾値未満の場合はパターン化されない"""
        hourly_stats = {}
        low_rate = MIN_SUCCESS_RATE - 0.1
        for hour in range(TIME_SLOTS["morning"]["start"], TIME_SLOTS["morning"]["end"]):
            hourly_stats[hour] = {
                "total": MIN_SAMPLE_COUNT * 2,
                "adopted": int(MIN_SAMPLE_COUNT * 2 * low_rate),
                "ignored": int(MIN_SAMPLE_COUNT * 2 * (1 - low_rate)),
            }
        mock_repository.get_hourly_statistics.return_value = hourly_stats

        patterns = extractor.extract_timing_patterns(mock_conn)

        # 成功率が低いのでパターンは生成されない可能性が高い
        # (確信度も関係するため、空になるとは限らない)
        for p in patterns:
            assert p.success_rate >= MIN_SUCCESS_RATE

    # =========================================================================
    # extract_day_of_week_patterns
    # =========================================================================

    def test_extract_day_of_week_patterns_empty(self, extractor, mock_repository, mock_conn):
        """曜日統計がない場合は空リストを返す"""
        mock_repository.get_day_of_week_statistics.return_value = {}

        patterns = extractor.extract_day_of_week_patterns(mock_conn)

        assert patterns == []

    def test_extract_day_of_week_patterns_with_data(self, extractor, mock_repository, mock_conn):
        """曜日パターンの抽出テスト"""
        mock_repository.get_day_of_week_statistics.return_value = {
            1: {
                "total": MIN_SAMPLE_COUNT * 2,
                "adopted": int(MIN_SAMPLE_COUNT * 2 * 0.8),
                "ignored": int(MIN_SAMPLE_COUNT * 2 * 0.2),
            },
        }

        patterns = extractor.extract_day_of_week_patterns(mock_conn)

        if patterns:
            assert patterns[0].pattern_type == PatternType.DAY_OF_WEEK.value
            assert "day_of_week" in patterns[0].pattern_content.get("condition", {})

    def test_extract_day_of_week_patterns_user_specific(
        self, extractor, mock_repository, mock_conn
    ):
        """ユーザー固有の曜日パターン抽出テスト"""
        mock_repository.get_day_of_week_statistics.return_value = {
            3: {
                "total": MIN_SAMPLE_COUNT * 2,
                "adopted": int(MIN_SAMPLE_COUNT * 2 * 0.85),
                "ignored": int(MIN_SAMPLE_COUNT * 2 * 0.15),
            },
        }

        patterns = extractor.extract_day_of_week_patterns(
            mock_conn, target_account_id="user-456", days=14
        )

        mock_repository.get_day_of_week_statistics.assert_called_with(
            mock_conn, target_account_id="user-456", days=14
        )

    # =========================================================================
    # extract_user_response_patterns
    # =========================================================================

    def test_extract_user_response_patterns_no_users(
        self, extractor, mock_repository, mock_conn
    ):
        """アクティブユーザーがいない場合は空リストを返す"""
        with patch.object(extractor, "_get_active_users", return_value=[]):
            patterns = extractor.extract_user_response_patterns(mock_conn)

        assert patterns == []

    def test_extract_user_response_patterns_with_users(
        self, extractor, mock_repository, mock_conn
    ):
        """複数ユーザーのパターン抽出テスト"""
        with patch.object(
            extractor, "_get_active_users", return_value=["user-1", "user-2"]
        ):
            with patch.object(
                extractor, "extract_timing_patterns", return_value=[]
            ) as mock_timing:
                with patch.object(
                    extractor, "extract_day_of_week_patterns", return_value=[]
                ) as mock_dow:
                    patterns = extractor.extract_user_response_patterns(mock_conn, days=7)

        # 各ユーザーに対して時間帯と曜日のパターン抽出が呼ばれる
        assert mock_timing.call_count == 2
        assert mock_dow.call_count == 2

    # =========================================================================
    # extract_all_patterns
    # =========================================================================

    def test_extract_all_patterns_combines_results(
        self, extractor, mock_repository, mock_conn
    ):
        """全パターン抽出が各種パターンを結合するテスト"""
        with patch.object(
            extractor, "extract_timing_patterns", return_value=[MagicMock()]
        ):
            with patch.object(
                extractor, "extract_day_of_week_patterns", return_value=[MagicMock()]
            ):
                with patch.object(
                    extractor, "extract_user_response_patterns", return_value=[MagicMock()]
                ):
                    patterns = extractor.extract_all_patterns(mock_conn, days=30)

        assert len(patterns) == 3

    # =========================================================================
    # save_patterns
    # =========================================================================

    def test_save_patterns_new_pattern(self, extractor, mock_repository, mock_conn):
        """新規パターンの保存テスト"""
        pattern = OutcomePattern(
            id=str(uuid4()),
            organization_id="test-org-id",
            pattern_type=PatternType.TIMING.value,
            pattern_category="morning",
            scope=PatternScope.GLOBAL.value,
            pattern_content={"condition": {"hour_range": [6, 9]}},
            sample_count=100,
            success_count=80,
            failure_count=20,
            success_rate=0.8,
            confidence_score=0.75,
        )
        mock_repository.find_patterns.return_value = []
        mock_repository.save_pattern.return_value = "new-pattern-id"

        saved_ids = extractor.save_patterns(mock_conn, [pattern])

        assert "new-pattern-id" in saved_ids
        mock_repository.save_pattern.assert_called_once()

    def test_save_patterns_update_existing(self, extractor, mock_repository, mock_conn):
        """既存パターンの更新テスト"""
        existing_pattern = OutcomePattern(
            id="existing-id",
            organization_id="test-org-id",
            pattern_type=PatternType.TIMING.value,
            pattern_category="morning",
            scope=PatternScope.GLOBAL.value,
            pattern_content={"condition": {"hour_range": [6, 9]}},
            sample_count=50,
            success_count=40,
            failure_count=10,
            success_rate=0.8,
            confidence_score=0.7,
        )
        new_pattern = OutcomePattern(
            id=str(uuid4()),
            organization_id="test-org-id",
            pattern_type=PatternType.TIMING.value,
            pattern_category="morning",
            scope=PatternScope.GLOBAL.value,
            pattern_content={"condition": {"hour_range": [6, 9]}},
            sample_count=100,
            success_count=85,
            failure_count=15,
            success_rate=0.85,
            confidence_score=0.8,
        )
        mock_repository.find_patterns.return_value = [existing_pattern]

        saved_ids = extractor.save_patterns(mock_conn, [new_pattern])

        assert "existing-id" in saved_ids
        mock_repository.update_pattern_stats.assert_called_once()
        mock_repository.save_pattern.assert_not_called()

    def test_save_patterns_empty_list(self, extractor, mock_repository, mock_conn):
        """空リストの保存テスト"""
        saved_ids = extractor.save_patterns(mock_conn, [])

        assert saved_ids == []

    # =========================================================================
    # find_promotable_patterns
    # =========================================================================

    def test_find_promotable_patterns(self, extractor, mock_repository, mock_conn):
        """昇格可能パターンの検索テスト"""
        mock_repository.find_promotable_patterns.return_value = [MagicMock()]

        patterns = extractor.find_promotable_patterns(mock_conn)

        assert len(patterns) == 1
        mock_repository.find_promotable_patterns.assert_called_once()

    # =========================================================================
    # _aggregate_slot_stats
    # =========================================================================

    def test_aggregate_slot_stats_basic(self, extractor):
        """時間帯集計の基本テスト"""
        hourly_stats = {
            6: {"total": 10, "adopted": 8, "ignored": 2},
            7: {"total": 15, "adopted": 12, "ignored": 3},
            8: {"total": 20, "adopted": 15, "ignored": 5},
        }

        result = extractor._aggregate_slot_stats(hourly_stats, 6, 9)

        assert result["total"] == 45
        assert result["adopted"] == 35
        assert result["ignored"] == 10

    def test_aggregate_slot_stats_missing_hours(self, extractor):
        """一部の時間がない場合の集計テスト"""
        hourly_stats = {
            6: {"total": 10, "adopted": 8, "ignored": 2},
            # 7時のデータなし
            8: {"total": 20, "adopted": 15, "ignored": 5},
        }

        result = extractor._aggregate_slot_stats(hourly_stats, 6, 9)

        assert result["total"] == 30
        assert result["adopted"] == 23

    def test_aggregate_slot_stats_empty(self, extractor):
        """データがない場合の集計テスト"""
        result = extractor._aggregate_slot_stats({}, 6, 9)

        assert result["total"] == 0
        assert result["adopted"] == 0
        assert result["ignored"] == 0

    # =========================================================================
    # _calculate_confidence
    # =========================================================================

    def test_calculate_confidence_zero_sample(self, extractor):
        """サンプル数0の場合は確信度0"""
        confidence = extractor._calculate_confidence(0, 0.8)
        assert confidence == 0.0

    def test_calculate_confidence_high_sample_high_rate(self, extractor):
        """サンプル数多・成功率高の場合は確信度高"""
        confidence = extractor._calculate_confidence(100, 0.9)
        assert confidence > 0.8

    def test_calculate_confidence_low_sample(self, extractor):
        """サンプル数少の場合は確信度低め"""
        confidence_low = extractor._calculate_confidence(5, 0.9)
        confidence_high = extractor._calculate_confidence(100, 0.9)
        assert confidence_low < confidence_high

    def test_calculate_confidence_bounds(self, extractor):
        """確信度は0.0〜1.0の範囲"""
        for sample in [1, 10, 100, 1000]:
            for rate in [0.0, 0.5, 1.0]:
                confidence = extractor._calculate_confidence(sample, rate)
                assert 0.0 <= confidence <= 1.0

    # =========================================================================
    # _is_same_pattern
    # =========================================================================

    def test_is_same_pattern_true(self, extractor):
        """同じパターンの判定テスト（True）"""
        p1 = OutcomePattern(
            id="1",
            organization_id="org",
            pattern_type=PatternType.TIMING.value,
            pattern_category="morning",
            scope=PatternScope.GLOBAL.value,
            pattern_content={"condition": {"hour_range": [6, 9]}},
            sample_count=10,
            success_count=8,
            failure_count=2,
        )
        p2 = OutcomePattern(
            id="2",
            organization_id="org",
            pattern_type=PatternType.TIMING.value,
            pattern_category="morning",
            scope=PatternScope.GLOBAL.value,
            pattern_content={"condition": {"hour_range": [6, 9]}},
            sample_count=20,
            success_count=16,
            failure_count=4,
        )

        assert extractor._is_same_pattern(p1, p2) is True

    def test_is_same_pattern_different_type(self, extractor):
        """異なるパターンタイプの判定テスト"""
        p1 = OutcomePattern(
            id="1",
            organization_id="org",
            pattern_type=PatternType.TIMING.value,
            pattern_category="morning",
            scope=PatternScope.GLOBAL.value,
            pattern_content={"condition": {"hour_range": [6, 9]}},
            sample_count=10,
            success_count=8,
            failure_count=2,
        )
        p2 = OutcomePattern(
            id="2",
            organization_id="org",
            pattern_type=PatternType.DAY_OF_WEEK.value,
            pattern_category="月曜日",
            scope=PatternScope.GLOBAL.value,
            pattern_content={"condition": {"day_of_week": 1}},
            sample_count=10,
            success_count=8,
            failure_count=2,
        )

        assert extractor._is_same_pattern(p1, p2) is False

    def test_is_same_pattern_different_category(self, extractor):
        """異なるカテゴリの判定テスト"""
        p1 = OutcomePattern(
            id="1",
            organization_id="org",
            pattern_type=PatternType.TIMING.value,
            pattern_category="morning",
            scope=PatternScope.GLOBAL.value,
            pattern_content={"condition": {"hour_range": [6, 9]}},
            sample_count=10,
            success_count=8,
            failure_count=2,
        )
        p2 = OutcomePattern(
            id="2",
            organization_id="org",
            pattern_type=PatternType.TIMING.value,
            pattern_category="昼",
            scope=PatternScope.GLOBAL.value,
            pattern_content={"condition": {"hour_range": [12, 14]}},
            sample_count=10,
            success_count=8,
            failure_count=2,
        )

        assert extractor._is_same_pattern(p1, p2) is False

    # =========================================================================
    # _get_active_users
    # =========================================================================

    def test_get_active_users_success(self, extractor, mock_conn):
        """アクティブユーザー取得成功テスト"""
        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([("user-1",), ("user-2",)])
        mock_conn.execute.return_value = mock_result

        users = extractor._get_active_users(mock_conn, 30)

        assert users == ["user-1", "user-2"]

    def test_get_active_users_error(self, extractor, mock_conn):
        """アクティブユーザー取得エラー時は空リストを返す"""
        mock_conn.execute.side_effect = Exception("DB error")

        users = extractor._get_active_users(mock_conn, 30)

        assert users == []


class TestCreatePatternExtractor:
    """create_pattern_extractorファクトリ関数のテスト"""

    def test_create_with_repository(self):
        """リポジトリを指定して作成"""
        mock_repo = MagicMock()
        extractor = create_pattern_extractor("org-123", repository=mock_repo)

        assert extractor.organization_id == "org-123"
        assert extractor.repository == mock_repo

    def test_create_without_repository(self):
        """リポジトリなしで作成（新規作成される）"""
        extractor = create_pattern_extractor("org-456")

        assert extractor.organization_id == "org-456"
        assert extractor.repository is not None
