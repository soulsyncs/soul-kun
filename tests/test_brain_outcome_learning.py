"""
lib/brain/outcome_learning/__init__.py (BrainOutcomeLearning) のテスト
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from lib.brain.outcome_learning import (
    BrainOutcomeLearning,
    create_outcome_learning,
    OutcomeEvent,
    OutcomePattern,
    OutcomeInsight,
    OutcomeStatistics,
    TRACKABLE_ACTIONS,
)
from lib.brain.outcome_learning.constants import OutcomeType


class TestBrainOutcomeLearning:
    """BrainOutcomeLearningのテスト"""

    @pytest.fixture
    def mock_conn(self):
        """DBコネクションのモック"""
        return MagicMock()

    @pytest.fixture
    def outcome_learning(self):
        """テスト対象のBrainOutcomeLearning"""
        with patch("lib.brain.outcome_learning.OutcomeRepository"):
            with patch("lib.brain.outcome_learning.OutcomeTracker"):
                with patch("lib.brain.outcome_learning.ImplicitFeedbackDetector"):
                    with patch("lib.brain.outcome_learning.PatternExtractor"):
                        with patch("lib.brain.outcome_learning.OutcomeAnalyzer"):
                            return BrainOutcomeLearning("test-org-id")

    def test_init_creates_components(self):
        """初期化時にコンポーネントが作成されるテスト"""
        with patch("lib.brain.outcome_learning.OutcomeRepository") as MockRepo:
            with patch("lib.brain.outcome_learning.OutcomeTracker") as MockTracker:
                with patch("lib.brain.outcome_learning.ImplicitFeedbackDetector") as MockDetector:
                    with patch("lib.brain.outcome_learning.PatternExtractor") as MockExtractor:
                        with patch("lib.brain.outcome_learning.OutcomeAnalyzer") as MockAnalyzer:
                            learning = BrainOutcomeLearning("org-123")
                            assert learning.organization_id == "org-123"
                            MockRepo.assert_called_once_with("org-123")

    def test_is_trackable_action_delegates_to_tracker(self, outcome_learning):
        """is_trackable_actionがtrackerに委譲されるテスト"""
        outcome_learning._tracker.is_trackable_action.return_value = True
        result = outcome_learning.is_trackable_action("send_reminder")
        outcome_learning._tracker.is_trackable_action.assert_called_with("send_reminder")
        assert result is True

    def test_record_action_delegates_to_tracker(self, outcome_learning, mock_conn):
        """record_actionがtrackerに委譲されるテスト"""
        outcome_learning._tracker.record_action.return_value = "event-123"
        event_id = outcome_learning.record_action(
            conn=mock_conn,
            action="send_reminder",
            target_account_id="user-456",
        )
        assert event_id == "event-123"

    def test_process_pending_outcomes_no_pending(self, outcome_learning, mock_conn):
        """未処理イベントがない場合のテスト"""
        outcome_learning._repository.find_pending_events.return_value = []
        processed = outcome_learning.process_pending_outcomes(mock_conn)
        assert processed == 0

    def test_process_pending_outcomes_with_feedback(self, outcome_learning, mock_conn):
        """フィードバックが検出される場合のテスト"""
        mock_event = MagicMock()
        mock_event.id = "event-1"
        outcome_learning._repository.find_pending_events.return_value = [mock_event]
        mock_feedback = MagicMock()
        mock_feedback.outcome_type = OutcomeType.ADOPTED.value
        mock_feedback.feedback_signal = "message_read"
        mock_feedback.confidence = 0.8
        mock_feedback.evidence = {}
        mock_feedback.detected_at = datetime.now()
        outcome_learning._detector.detect.return_value = mock_feedback
        outcome_learning._tracker.update_outcome.return_value = True
        processed = outcome_learning.process_pending_outcomes(mock_conn)
        assert processed == 1

    def test_get_pending_events(self, outcome_learning, mock_conn):
        """未処理イベント取得テスト"""
        mock_events = [MagicMock()]
        outcome_learning._repository.find_pending_events.return_value = mock_events
        events = outcome_learning.get_pending_events(mock_conn)
        assert events == mock_events

    def test_extract_patterns_with_save(self, outcome_learning, mock_conn):
        """パターン抽出と保存テスト"""
        mock_patterns = [MagicMock()]
        outcome_learning._extractor.extract_all_patterns.return_value = mock_patterns
        patterns = outcome_learning.extract_patterns(mock_conn, save=True)
        outcome_learning._extractor.save_patterns.assert_called_with(mock_conn, mock_patterns)
        assert patterns == mock_patterns

    def test_extract_patterns_empty_no_save(self, outcome_learning, mock_conn):
        """パターンが空の場合は保存しないテスト"""
        outcome_learning._extractor.extract_all_patterns.return_value = []
        patterns = outcome_learning.extract_patterns(mock_conn, save=True)
        outcome_learning._extractor.save_patterns.assert_not_called()

    def test_extract_timing_patterns(self, outcome_learning, mock_conn):
        """時間帯パターン抽出テスト"""
        mock_patterns = [MagicMock()]
        outcome_learning._extractor.extract_timing_patterns.return_value = mock_patterns
        patterns = outcome_learning.extract_timing_patterns(mock_conn, target_account_id="user-123")
        assert patterns == mock_patterns

    def test_find_applicable_patterns(self, outcome_learning, mock_conn):
        """適用可能パターン検索テスト"""
        mock_patterns = [MagicMock()]
        outcome_learning._repository.find_applicable_patterns.return_value = mock_patterns
        patterns = outcome_learning.find_applicable_patterns(mock_conn, target_account_id="user-456")
        assert patterns == mock_patterns

    def test_find_promotable_patterns(self, outcome_learning, mock_conn):
        """昇格可能パターン検索テスト"""
        mock_patterns = [MagicMock()]
        outcome_learning._extractor.find_promotable_patterns.return_value = mock_patterns
        patterns = outcome_learning.find_promotable_patterns(mock_conn)
        assert patterns == mock_patterns

    def test_promote_pattern_to_learning_not_found(self, outcome_learning, mock_conn):
        """パターンが見つからない場合のテスト"""
        outcome_learning._repository.find_patterns.return_value = []
        result = outcome_learning.promote_pattern_to_learning(mock_conn, "pattern-123")
        assert result is None

    def test_promote_pattern_to_learning_not_promotable(self, outcome_learning, mock_conn):
        """昇格不可のパターンのテスト"""
        mock_pattern = MagicMock()
        mock_pattern.id = "pattern-123"
        mock_pattern.is_promotable = False
        outcome_learning._repository.find_patterns.return_value = [mock_pattern]
        result = outcome_learning.promote_pattern_to_learning(mock_conn, "pattern-123")
        assert result is None

    def test_generate_insights(self, outcome_learning, mock_conn):
        """インサイト生成テスト"""
        mock_insights = [MagicMock()]
        outcome_learning._analyzer.generate_insights.return_value = mock_insights
        insights = outcome_learning.generate_insights(mock_conn)
        assert insights == mock_insights

    def test_analyze_user_responsiveness(self, outcome_learning, mock_conn):
        """ユーザー反応傾向分析テスト"""
        mock_result = {"account_id": "user-123", "adoption_rate": 0.75}
        outcome_learning._analyzer.analyze_user_responsiveness.return_value = mock_result
        result = outcome_learning.analyze_user_responsiveness(mock_conn, account_id="user-123")
        assert result == mock_result

    def test_get_statistics(self, outcome_learning, mock_conn):
        """統計取得テスト"""
        mock_stats = MagicMock()
        outcome_learning._repository.get_statistics.return_value = mock_stats
        stats = outcome_learning.get_statistics(mock_conn)
        assert stats == mock_stats


class TestCreateOutcomeLearning:
    """create_outcome_learningファクトリ関数のテスト"""

    def test_create_outcome_learning(self):
        """ファクトリ関数のテスト"""
        with patch("lib.brain.outcome_learning.OutcomeRepository"):
            with patch("lib.brain.outcome_learning.OutcomeTracker"):
                with patch("lib.brain.outcome_learning.ImplicitFeedbackDetector"):
                    with patch("lib.brain.outcome_learning.PatternExtractor"):
                        with patch("lib.brain.outcome_learning.OutcomeAnalyzer"):
                            learning = create_outcome_learning("org-test")
        assert learning.organization_id == "org-test"


class TestExports:
    """モジュールエクスポートのテスト"""

    def test_exports_are_available(self):
        """必要なクラス・関数がエクスポートされているテスト"""
        from lib.brain.outcome_learning import (
            BrainOutcomeLearning,
            create_outcome_learning,
            OutcomeTracker,
            PatternExtractor,
            OutcomeAnalyzer,
            OutcomeRepository,
            OutcomeEvent,
            OutcomePattern,
            OutcomeInsight,
            OutcomeStatistics,
        )
        assert BrainOutcomeLearning is not None
