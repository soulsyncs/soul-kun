"""
Phase 2F: 結果からの学習 - テスト

設計書: docs/17_brain_completion_roadmap.md セクション Phase 2F
"""

import json
from datetime import datetime, timedelta
from typing import Any, Dict
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from lib.brain.outcome_learning import (
    # 統合クラス
    BrainOutcomeLearning,
    create_outcome_learning,
    # コンポーネント
    OutcomeTracker,
    ImplicitFeedbackDetector,
    PatternExtractor,
    OutcomeAnalyzer,
    OutcomeRepository,
    # Enum
    EventType,
    FeedbackSignal,
    OutcomeType,
    PatternScope,
    PatternType,
    # データモデル
    OutcomeEvent,
    ImplicitFeedback,
    OutcomePattern,
    OutcomeInsight,
    OutcomeStatistics,
    # 定数
    ADOPTED_THRESHOLD_HOURS,
    IGNORED_THRESHOLD_HOURS,
    MIN_SAMPLE_COUNT,
    MIN_SUCCESS_RATE,
    TRACKABLE_ACTIONS,
)


# ============================================================================
# フィクスチャ
# ============================================================================

@pytest.fixture
def organization_id():
    """テスト用組織ID"""
    return str(uuid4())


@pytest.fixture
def mock_conn():
    """モックDB接続"""
    conn = MagicMock()
    return conn


@pytest.fixture
def repository(organization_id):
    """テスト用リポジトリ"""
    return OutcomeRepository(organization_id)


@pytest.fixture
def tracker(organization_id, repository):
    """テスト用トラッカー"""
    return OutcomeTracker(organization_id, repository)


@pytest.fixture
def detector(organization_id):
    """テスト用検出器"""
    return ImplicitFeedbackDetector(organization_id)


@pytest.fixture
def extractor(organization_id, repository):
    """テスト用パターン抽出器"""
    return PatternExtractor(organization_id, repository)


@pytest.fixture
def analyzer(organization_id, repository):
    """テスト用分析器"""
    return OutcomeAnalyzer(organization_id, repository)


@pytest.fixture
def outcome_learning(organization_id):
    """テスト用統合クラス"""
    return BrainOutcomeLearning(organization_id)


# ============================================================================
# OutcomeEvent テスト
# ============================================================================

class TestOutcomeEvent:
    """OutcomeEventモデルのテスト"""

    def test_create_event(self, organization_id):
        """イベント作成"""
        event = OutcomeEvent(
            id=str(uuid4()),
            organization_id=organization_id,
            event_type=EventType.NOTIFICATION_SENT.value,
            target_account_id="12345",
            target_room_id="67890",
            event_details={"action": "send_reminder"},
            event_timestamp=datetime.now(),
        )

        assert event.event_type == EventType.NOTIFICATION_SENT.value
        assert event.target_account_id == "12345"
        assert event.outcome_detected is False

    def test_to_dict(self, organization_id):
        """辞書変換"""
        event = OutcomeEvent(
            id=str(uuid4()),
            organization_id=organization_id,
            event_type=EventType.GOAL_REMINDER.value,
            target_account_id="12345",
            event_details={"message": "test"},
        )

        result = event.to_dict()

        assert result["event_type"] == EventType.GOAL_REMINDER.value
        assert result["target_account_id"] == "12345"
        assert "event_details" in result

    def test_from_dict(self, organization_id):
        """辞書からの生成"""
        data = {
            "id": str(uuid4()),
            "organization_id": organization_id,
            "event_type": EventType.TASK_REMINDER.value,
            "target_account_id": "12345",
            "event_details": {},
            "outcome_detected": True,
            "outcome_type": OutcomeType.ADOPTED.value,
        }

        event = OutcomeEvent.from_dict(data)

        assert event.event_type == EventType.TASK_REMINDER.value
        assert event.outcome_detected is True
        assert event.outcome_type == OutcomeType.ADOPTED.value

    def test_is_positive_outcome(self, organization_id):
        """ポジティブ結果判定"""
        event = OutcomeEvent(
            id=str(uuid4()),
            organization_id=organization_id,
            event_type=EventType.NOTIFICATION_SENT.value,
            target_account_id="12345",
            event_details={},
            outcome_type=OutcomeType.ADOPTED.value,
        )

        assert event.is_positive_outcome is True
        assert event.is_negative_outcome is False

    def test_is_negative_outcome(self, organization_id):
        """ネガティブ結果判定"""
        event = OutcomeEvent(
            id=str(uuid4()),
            organization_id=organization_id,
            event_type=EventType.NOTIFICATION_SENT.value,
            target_account_id="12345",
            event_details={},
            outcome_type=OutcomeType.IGNORED.value,
        )

        assert event.is_positive_outcome is False
        assert event.is_negative_outcome is True


# ============================================================================
# OutcomePattern テスト
# ============================================================================

class TestOutcomePattern:
    """OutcomePatternモデルのテスト"""

    def test_create_pattern(self, organization_id):
        """パターン作成"""
        pattern = OutcomePattern(
            id=str(uuid4()),
            organization_id=organization_id,
            pattern_type=PatternType.TIMING.value,
            pattern_category="morning",
            scope=PatternScope.USER.value,
            scope_target_id="12345",
            pattern_content={
                "type": "timing",
                "condition": {"hour_range": [9, 12]},
                "effect": "high_response_rate",
            },
            sample_count=20,
            success_count=15,
            failure_count=5,
            success_rate=0.75,
            confidence_score=0.7,
        )

        assert pattern.pattern_type == PatternType.TIMING.value
        assert pattern.success_rate == 0.75

    def test_get_description_timing(self, organization_id):
        """説明取得（時間帯）"""
        pattern = OutcomePattern(
            id=str(uuid4()),
            organization_id=organization_id,
            pattern_type=PatternType.TIMING.value,
            pattern_content={
                "condition": {"hour_range": [9, 12]},
            },
        )

        desc = pattern.get_description()
        assert "9時" in desc
        assert "12時" in desc

    def test_is_promotable(self, organization_id):
        """昇格可能判定"""
        pattern = OutcomePattern(
            id=str(uuid4()),
            organization_id=organization_id,
            pattern_type=PatternType.TIMING.value,
            pattern_content={},
            sample_count=25,
            confidence_score=0.75,
        )

        assert pattern.is_promotable is True

    def test_is_not_promotable_low_confidence(self, organization_id):
        """昇格不可（低確信度）"""
        pattern = OutcomePattern(
            id=str(uuid4()),
            organization_id=organization_id,
            pattern_type=PatternType.TIMING.value,
            pattern_content={},
            sample_count=25,
            confidence_score=0.5,
        )

        assert pattern.is_promotable is False

    def test_is_not_promotable_low_samples(self, organization_id):
        """昇格不可（サンプル不足）"""
        pattern = OutcomePattern(
            id=str(uuid4()),
            organization_id=organization_id,
            pattern_type=PatternType.TIMING.value,
            pattern_content={},
            sample_count=10,
            confidence_score=0.75,
        )

        assert pattern.is_promotable is False


# ============================================================================
# OutcomeTracker テスト
# ============================================================================

class TestOutcomeTracker:
    """OutcomeTrackerのテスト"""

    def test_is_trackable_action(self, tracker):
        """追跡対象アクション判定"""
        assert tracker.is_trackable_action("send_notification") is True
        assert tracker.is_trackable_action("send_reminder") is True
        assert tracker.is_trackable_action("goal_reminder_sent") is True
        assert tracker.is_trackable_action("unknown_action") is False

    def test_record_action(self, tracker, mock_conn):
        """アクション記録"""
        with patch.object(tracker.repository, 'save_event', return_value=str(uuid4())):
            event_id = tracker.record_action(
                conn=mock_conn,
                action="send_reminder",
                target_account_id="12345",
                target_room_id="67890",
                action_params={"message": "Test message"},
            )

            assert event_id is not None

    def test_record_action_not_trackable(self, tracker, mock_conn):
        """追跡対象外アクション"""
        event_id = tracker.record_action(
            conn=mock_conn,
            action="unknown_action",
            target_account_id="12345",
        )

        assert event_id is None


# ============================================================================
# ImplicitFeedbackDetector テスト
# ============================================================================

class TestImplicitFeedbackDetector:
    """ImplicitFeedbackDetectorのテスト"""

    def test_detect_already_processed(self, detector, mock_conn, organization_id):
        """既に処理済みのイベント"""
        event = OutcomeEvent(
            id=str(uuid4()),
            organization_id=organization_id,
            event_type=EventType.NOTIFICATION_SENT.value,
            target_account_id="12345",
            event_details={},
            outcome_detected=True,
        )

        feedback = detector.detect(mock_conn, event)
        assert feedback is None

    def test_detect_from_time_elapsed_adopted(self, detector, mock_conn, organization_id):
        """時間経過から採用を検出"""
        event = OutcomeEvent(
            id=str(uuid4()),
            organization_id=organization_id,
            event_type=EventType.NOTIFICATION_SENT.value,
            target_account_id="12345",
            target_room_id="67890",
            event_details={},
            event_timestamp=datetime.now() - timedelta(hours=2),
        )

        # ユーザー反応をモック
        with patch.object(
            detector,
            '_check_user_response',
            return_value=True
        ):
            feedback = detector.detect(mock_conn, event)

            assert feedback is not None
            assert feedback.outcome_type == OutcomeType.ADOPTED.value

    def test_detect_from_time_elapsed_ignored(self, detector, mock_conn, organization_id):
        """時間経過から無視を検出"""
        event = OutcomeEvent(
            id=str(uuid4()),
            organization_id=organization_id,
            event_type=EventType.NOTIFICATION_SENT.value,
            target_account_id="12345",
            event_details={},
            event_timestamp=datetime.now() - timedelta(hours=50),
        )

        # ユーザー反応なしをモック
        with patch.object(
            detector,
            '_check_user_response',
            return_value=False
        ):
            feedback = detector.detect(mock_conn, event)

            assert feedback is not None
            assert feedback.outcome_type == OutcomeType.IGNORED.value


# ============================================================================
# PatternExtractor テスト
# ============================================================================

class TestPatternExtractor:
    """PatternExtractorのテスト"""

    def test_calculate_confidence(self, extractor):
        """確信度計算"""
        # サンプル数少ない
        conf1 = extractor._calculate_confidence(sample_count=5, success_rate=0.8)
        # サンプル数多い
        conf2 = extractor._calculate_confidence(sample_count=50, success_rate=0.8)

        assert conf2 > conf1  # サンプル数が多いほど確信度が高い

    def test_calculate_confidence_zero_samples(self, extractor):
        """確信度計算（サンプル0）"""
        conf = extractor._calculate_confidence(sample_count=0, success_rate=0.0)
        assert conf == 0.0

    def test_aggregate_slot_stats(self, extractor):
        """時間帯統計集計"""
        hourly_stats = {
            9: {"total": 10, "adopted": 8, "ignored": 2},
            10: {"total": 15, "adopted": 12, "ignored": 3},
            11: {"total": 5, "adopted": 4, "ignored": 1},
        }

        result = extractor._aggregate_slot_stats(hourly_stats, start_hour=9, end_hour=12)

        assert result["total"] == 30
        assert result["adopted"] == 24
        assert result["ignored"] == 6

    def test_is_same_pattern(self, extractor, organization_id):
        """同一パターン判定"""
        pattern1 = OutcomePattern(
            id=str(uuid4()),
            organization_id=organization_id,
            pattern_type=PatternType.TIMING.value,
            pattern_category="morning",
            pattern_content={"condition": {"hour_range": [9, 12]}},
        )
        pattern2 = OutcomePattern(
            id=str(uuid4()),
            organization_id=organization_id,
            pattern_type=PatternType.TIMING.value,
            pattern_category="morning",
            pattern_content={"condition": {"hour_range": [9, 12]}},
        )
        pattern3 = OutcomePattern(
            id=str(uuid4()),
            organization_id=organization_id,
            pattern_type=PatternType.TIMING.value,
            pattern_category="afternoon",
            pattern_content={"condition": {"hour_range": [12, 15]}},
        )

        assert extractor._is_same_pattern(pattern1, pattern2) is True
        assert extractor._is_same_pattern(pattern1, pattern3) is False


# ============================================================================
# OutcomeAnalyzer テスト
# ============================================================================

class TestOutcomeAnalyzer:
    """OutcomeAnalyzerのテスト"""

    def test_calculate_responsiveness_score(self, analyzer):
        """反応性スコア計算"""
        stats = OutcomeStatistics(
            total_events=100,
            adopted_count=60,
            ignored_count=30,
            delayed_count=10,
        )

        score = analyzer._calculate_responsiveness_score(stats)

        assert 0.0 <= score <= 1.0
        assert score > 0.5  # 採用率が高いので0.5より高い

    def test_calculate_responsiveness_score_no_events(self, analyzer):
        """反応性スコア計算（イベントなし）"""
        stats = OutcomeStatistics(total_events=0)

        score = analyzer._calculate_responsiveness_score(stats)

        assert score == 0.5  # デフォルト

    def test_find_best_hour(self, analyzer):
        """最適時間帯特定"""
        hourly_stats = {
            9: {"total": 20, "adopted": 18, "ignored": 2},   # 90%
            10: {"total": 15, "adopted": 10, "ignored": 5},  # 67%
            11: {"total": 10, "adopted": 5, "ignored": 5},   # 50%
        }

        best = analyzer._find_best_hour(hourly_stats)

        assert best is not None
        assert best["hour"] == 9
        assert best["success_rate"] == 0.9

    def test_find_best_hour_insufficient_samples(self, analyzer):
        """最適時間帯特定（サンプル不足）"""
        hourly_stats = {
            9: {"total": 5, "adopted": 4, "ignored": 1},  # サンプル不足
        }

        best = analyzer._find_best_hour(hourly_stats)

        assert best is None  # MIN_SAMPLE_COUNT未満


# ============================================================================
# BrainOutcomeLearning 統合テスト
# ============================================================================

class TestBrainOutcomeLearning:
    """BrainOutcomeLearning統合クラスのテスト"""

    def test_create_outcome_learning(self, organization_id):
        """インスタンス作成"""
        ol = create_outcome_learning(organization_id)

        assert ol is not None
        assert ol.organization_id == organization_id

    def test_is_trackable_action(self, outcome_learning):
        """追跡対象アクション判定"""
        assert outcome_learning.is_trackable_action("send_notification") is True
        assert outcome_learning.is_trackable_action("send_reminder") is True
        assert outcome_learning.is_trackable_action("unknown") is False

    def test_record_action(self, outcome_learning, mock_conn):
        """アクション記録"""
        with patch.object(
            outcome_learning._repository,
            'save_event',
            return_value=str(uuid4())
        ):
            event_id = outcome_learning.record_action(
                conn=mock_conn,
                action="send_reminder",
                target_account_id="12345",
                action_params={"message": "Test"},
            )

            assert event_id is not None


# ============================================================================
# 定数テスト
# ============================================================================

class TestConstants:
    """定数のテスト"""

    def test_trackable_actions(self):
        """追跡対象アクション"""
        assert "send_notification" in TRACKABLE_ACTIONS
        assert "send_reminder" in TRACKABLE_ACTIONS
        assert "goal_reminder_sent" in TRACKABLE_ACTIONS
        assert "task_reminder_sent" in TRACKABLE_ACTIONS
        assert "proactive_check_in" in TRACKABLE_ACTIONS

    def test_thresholds(self):
        """閾値の妥当性"""
        assert ADOPTED_THRESHOLD_HOURS > 0
        assert IGNORED_THRESHOLD_HOURS > ADOPTED_THRESHOLD_HOURS
        assert MIN_SAMPLE_COUNT > 0
        assert 0.0 < MIN_SUCCESS_RATE < 1.0


# ============================================================================
# Enum テスト
# ============================================================================

class TestEnums:
    """Enumのテスト"""

    def test_event_type_values(self):
        """EventTypeの値"""
        assert EventType.NOTIFICATION_SENT.value == "notification_sent"
        assert EventType.GOAL_REMINDER.value == "goal_reminder"
        assert EventType.TASK_REMINDER.value == "task_reminder"

    def test_outcome_type_values(self):
        """OutcomeTypeの値"""
        assert OutcomeType.ADOPTED.value == "adopted"
        assert OutcomeType.IGNORED.value == "ignored"
        assert OutcomeType.DELAYED.value == "delayed"
        assert OutcomeType.REJECTED.value == "rejected"

    def test_pattern_type_values(self):
        """PatternTypeの値"""
        assert PatternType.TIMING.value == "timing"
        assert PatternType.DAY_OF_WEEK.value == "day_of_week"
        assert PatternType.COMMUNICATION_STYLE.value == "communication_style"
