"""
Phase 2 進化版 A4: 感情変化検出のユニットテスト

このモジュールは、lib/detection/emotion_detector.py のユニットテストを提供します。

テスト対象:
- EmotionDetector: 感情変化検出器
- リスクレベル判定ロジック
- 感情スコアリング
- SentimentLabel列挙型

Author: Claude Code（経営参謀・SE・PM）
Created: 2026-01-24
"""

import json
import pytest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, patch, AsyncMock
from uuid import UUID, uuid4

# ================================================================
# テスト対象のインポート
# ================================================================

from lib.detection.constants import (
    DetectionParameters,
    EmotionAlertType,
    EmotionRiskLevel,
    EmotionStatus,
    SentimentLabel,
    InsightType,
    SourceType,
    Importance,
    Classification,
)

from lib.detection.emotion_detector import (
    EmotionDetector,
    SENTIMENT_ANALYSIS_PROMPT,
)

from lib.detection.base import (
    InsightData,
    DetectionResult,
)


# ================================================================
# A4 定数のテスト
# ================================================================

class TestEmotionDetectionParameters:
    """A4感情検出パラメータのテスト"""

    def test_emotion_analysis_window_days_default(self):
        """分析期間のデフォルト値"""
        assert DetectionParameters.EMOTION_ANALYSIS_WINDOW_DAYS == 14

    def test_emotion_baseline_window_days_default(self):
        """ベースライン期間のデフォルト値"""
        assert DetectionParameters.EMOTION_BASELINE_WINDOW_DAYS == 30

    def test_min_messages_for_emotion_default(self):
        """最小メッセージ数のデフォルト値"""
        assert DetectionParameters.MIN_MESSAGES_FOR_EMOTION == 5

    def test_sentiment_drop_critical_default(self):
        """Critical悪化閾値のデフォルト値"""
        assert DetectionParameters.SENTIMENT_DROP_CRITICAL == 0.4

    def test_sentiment_drop_high_default(self):
        """High悪化閾値のデフォルト値"""
        assert DetectionParameters.SENTIMENT_DROP_HIGH == 0.3

    def test_sustained_negative_critical_days_default(self):
        """Critical継続日数のデフォルト値"""
        assert DetectionParameters.SUSTAINED_NEGATIVE_CRITICAL_DAYS == 7

    def test_sustained_negative_high_days_default(self):
        """High継続日数のデフォルト値"""
        assert DetectionParameters.SUSTAINED_NEGATIVE_HIGH_DAYS == 5

    def test_negative_score_threshold_default(self):
        """ネガティブ閾値のデフォルト値"""
        assert DetectionParameters.NEGATIVE_SCORE_THRESHOLD == -0.2

    def test_very_negative_score_threshold_default(self):
        """非常にネガティブ閾値のデフォルト値"""
        assert DetectionParameters.VERY_NEGATIVE_SCORE_THRESHOLD == -0.5


# ================================================================
# EmotionAlertType のテスト
# ================================================================

class TestEmotionAlertType:
    """EmotionAlertTypeのテスト"""

    def test_sudden_drop_value(self):
        """急激な悪化タイプの値"""
        assert EmotionAlertType.SUDDEN_DROP.value == "sudden_drop"

    def test_sustained_negative_value(self):
        """継続ネガティブタイプの値"""
        assert EmotionAlertType.SUSTAINED_NEGATIVE.value == "sustained_negative"

    def test_high_volatility_value(self):
        """高ボラティリティタイプの値"""
        assert EmotionAlertType.HIGH_VOLATILITY.value == "high_volatility"

    def test_recovery_value(self):
        """回復タイプの値"""
        assert EmotionAlertType.RECOVERY.value == "recovery"

    def test_all_types_are_strings(self):
        """全タイプが文字列であること"""
        for alert_type in EmotionAlertType:
            assert isinstance(alert_type.value, str)


# ================================================================
# EmotionRiskLevel のテスト
# ================================================================

class TestEmotionRiskLevel:
    """EmotionRiskLevelのテスト"""

    def test_critical_value(self):
        """Criticalレベルの値"""
        assert EmotionRiskLevel.CRITICAL.value == "critical"

    def test_high_value(self):
        """Highレベルの値"""
        assert EmotionRiskLevel.HIGH.value == "high"

    def test_medium_value(self):
        """Mediumレベルの値"""
        assert EmotionRiskLevel.MEDIUM.value == "medium"

    def test_low_value(self):
        """Lowレベルの値"""
        assert EmotionRiskLevel.LOW.value == "low"


# ================================================================
# SentimentLabel のテスト
# ================================================================

class TestSentimentLabel:
    """SentimentLabelのテスト"""

    def test_very_positive_value(self):
        """非常にポジティブラベルの値"""
        assert SentimentLabel.VERY_POSITIVE.value == "very_positive"

    def test_positive_value(self):
        """ポジティブラベルの値"""
        assert SentimentLabel.POSITIVE.value == "positive"

    def test_neutral_value(self):
        """ニュートラルラベルの値"""
        assert SentimentLabel.NEUTRAL.value == "neutral"

    def test_negative_value(self):
        """ネガティブラベルの値"""
        assert SentimentLabel.NEGATIVE.value == "negative"

    def test_very_negative_value(self):
        """非常にネガティブラベルの値"""
        assert SentimentLabel.VERY_NEGATIVE.value == "very_negative"

    def test_from_score_very_positive(self):
        """スコア0.6以上で非常にポジティブ"""
        assert SentimentLabel.from_score(0.6) == SentimentLabel.VERY_POSITIVE
        assert SentimentLabel.from_score(0.8) == SentimentLabel.VERY_POSITIVE
        assert SentimentLabel.from_score(1.0) == SentimentLabel.VERY_POSITIVE

    def test_from_score_positive(self):
        """スコア0.2〜0.6でポジティブ"""
        assert SentimentLabel.from_score(0.2) == SentimentLabel.POSITIVE
        assert SentimentLabel.from_score(0.4) == SentimentLabel.POSITIVE
        assert SentimentLabel.from_score(0.59) == SentimentLabel.POSITIVE

    def test_from_score_neutral(self):
        """スコア-0.2〜0.2でニュートラル"""
        assert SentimentLabel.from_score(0.0) == SentimentLabel.NEUTRAL
        assert SentimentLabel.from_score(0.19) == SentimentLabel.NEUTRAL
        assert SentimentLabel.from_score(-0.19) == SentimentLabel.NEUTRAL

    def test_from_score_negative(self):
        """スコア-0.5より大きく-0.2未満でネガティブ"""
        assert SentimentLabel.from_score(-0.21) == SentimentLabel.NEGATIVE
        assert SentimentLabel.from_score(-0.3) == SentimentLabel.NEGATIVE
        assert SentimentLabel.from_score(-0.49) == SentimentLabel.NEGATIVE

    def test_from_score_very_negative(self):
        """スコア-0.5未満で非常にネガティブ"""
        assert SentimentLabel.from_score(-0.51) == SentimentLabel.VERY_NEGATIVE
        assert SentimentLabel.from_score(-0.7) == SentimentLabel.VERY_NEGATIVE
        assert SentimentLabel.from_score(-1.0) == SentimentLabel.VERY_NEGATIVE


# ================================================================
# EmotionStatus のテスト
# ================================================================

class TestEmotionStatus:
    """EmotionStatusのテスト"""

    def test_active_value(self):
        """アクティブステータスの値"""
        assert EmotionStatus.ACTIVE.value == "active"

    def test_resolved_value(self):
        """解決済みステータスの値"""
        assert EmotionStatus.RESOLVED.value == "resolved"

    def test_dismissed_value(self):
        """無視ステータスの値"""
        assert EmotionStatus.DISMISSED.value == "dismissed"


# ================================================================
# EmotionDetector リスクレベル判定のテスト
# ================================================================

class TestEmotionDetectorRiskLevel:
    """EmotionDetectorのリスクレベル判定テスト"""

    @pytest.fixture
    def mock_conn(self):
        """モックDB接続"""
        return MagicMock()

    @pytest.fixture
    def detector(self, mock_conn):
        """テスト用EmotionDetector"""
        org_id = uuid4()
        return EmotionDetector(mock_conn, org_id)

    def test_critical_sudden_drop_with_consecutive_days(self, detector):
        """Critical: 急激な悪化(0.4+) + 3日以上継続"""
        result = detector._determine_risk_level(
            baseline_score=0.5,
            current_score=0.0,  # drop = 0.5
            consecutive_negative_days=3
        )
        assert result == EmotionRiskLevel.CRITICAL

    def test_critical_very_negative_sustained(self, detector):
        """Critical: 非常にネガティブ(-0.5以下) + 7日以上継続"""
        result = detector._determine_risk_level(
            baseline_score=0.0,
            current_score=-0.6,
            consecutive_negative_days=7
        )
        assert result == EmotionRiskLevel.CRITICAL

    def test_high_moderate_drop_with_days(self, detector):
        """High: 中程度の悪化(0.3+) + 2日以上継続"""
        result = detector._determine_risk_level(
            baseline_score=0.3,
            current_score=-0.1,  # drop = 0.4
            consecutive_negative_days=2
        )
        # Critical requires 3+ days, so with 2 days it's HIGH
        assert result == EmotionRiskLevel.HIGH

    def test_high_negative_sustained(self, detector):
        """High: ネガティブ(-0.3以下) + 5日以上継続"""
        result = detector._determine_risk_level(
            baseline_score=0.0,
            current_score=-0.35,
            consecutive_negative_days=5
        )
        assert result == EmotionRiskLevel.HIGH

    def test_medium_small_drop(self, detector):
        """Medium: 悪化(0.2+)"""
        result = detector._determine_risk_level(
            baseline_score=0.3,
            current_score=0.05,  # drop = 0.25
            consecutive_negative_days=1
        )
        assert result == EmotionRiskLevel.MEDIUM

    def test_medium_negative_with_days(self, detector):
        """Medium: ネガティブ(-0.2以下) + 3日以上継続"""
        result = detector._determine_risk_level(
            baseline_score=0.0,
            current_score=-0.25,
            consecutive_negative_days=3
        )
        assert result == EmotionRiskLevel.MEDIUM

    def test_low_minor_fluctuation(self, detector):
        """Low: 軽微な変化"""
        result = detector._determine_risk_level(
            baseline_score=0.1,
            current_score=0.0,  # drop = 0.1
            consecutive_negative_days=1
        )
        assert result == EmotionRiskLevel.LOW

    def test_low_no_change(self, detector):
        """Low: 変化なし"""
        result = detector._determine_risk_level(
            baseline_score=0.0,
            current_score=0.0,
            consecutive_negative_days=0
        )
        assert result == EmotionRiskLevel.LOW


# ================================================================
# EmotionDetector 連続ネガティブ日数計算のテスト
# ================================================================

class TestEmotionDetectorConsecutiveDays:
    """EmotionDetectorの連続ネガティブ日数計算テスト"""

    @pytest.fixture
    def mock_conn(self):
        """モックDB接続"""
        return MagicMock()

    @pytest.fixture
    def detector(self, mock_conn):
        """テスト用EmotionDetector"""
        org_id = uuid4()
        return EmotionDetector(mock_conn, org_id)

    def test_empty_scores_returns_zero(self, detector):
        """空のスコアリストで0日"""
        result = detector._calculate_consecutive_negative_days([])
        assert result == 0

    def test_all_negative_scores(self, detector):
        """全てネガティブの場合"""
        now = datetime.now(timezone.utc)
        scores = [
            {'sentiment_score': -0.3, 'message_time': now},
            {'sentiment_score': -0.4, 'message_time': now - timedelta(days=1)},
            {'sentiment_score': -0.5, 'message_time': now - timedelta(days=2)},
        ]
        result = detector._calculate_consecutive_negative_days(scores)
        assert result == 3

    def test_mixed_scores_breaks_at_positive(self, detector):
        """ポジティブで連続が途切れる"""
        now = datetime.now(timezone.utc)
        scores = [
            {'sentiment_score': -0.3, 'message_time': now},
            {'sentiment_score': 0.1, 'message_time': now - timedelta(days=1)},  # positive, breaks
            {'sentiment_score': -0.5, 'message_time': now - timedelta(days=2)},
        ]
        result = detector._calculate_consecutive_negative_days(scores)
        assert result == 1  # Only the first day counts

    def test_neutral_score_breaks_streak(self, detector):
        """ニュートラルで連続が途切れる"""
        now = datetime.now(timezone.utc)
        scores = [
            {'sentiment_score': -0.3, 'message_time': now},
            {'sentiment_score': -0.1, 'message_time': now - timedelta(days=1)},  # above threshold
        ]
        result = detector._calculate_consecutive_negative_days(scores)
        assert result == 1


# ================================================================
# EmotionDetector InsightData生成のテスト
# ================================================================

class TestEmotionDetectorInsightData:
    """EmotionDetectorのInsightData生成テスト"""

    @pytest.fixture
    def mock_conn(self):
        """モックDB接続"""
        return MagicMock()

    @pytest.fixture
    def detector(self, mock_conn):
        """テスト用EmotionDetector"""
        org_id = uuid4()
        return EmotionDetector(mock_conn, org_id)

    def test_sudden_drop_insight(self, detector):
        """急激な悪化アラートのInsightData"""
        alert = {
            'id': uuid4(),
            'alert_type': EmotionAlertType.SUDDEN_DROP.value,
            'risk_level': EmotionRiskLevel.CRITICAL.value,
            'user_name': 'テストユーザー',
            'score_change': 0.5,
            'consecutive_negative_days': 3,
        }

        insight = detector._create_insight_data(alert)

        assert insight.insight_type == InsightType.EMOTION_CHANGE
        assert insight.source_type == SourceType.A4_EMOTION
        assert insight.importance == Importance.CRITICAL
        assert 'テストユーザー' in insight.title
        assert '急激な変化' in insight.title
        assert insight.classification == Classification.CONFIDENTIAL

    def test_sustained_negative_insight(self, detector):
        """継続ネガティブアラートのInsightData"""
        alert = {
            'id': uuid4(),
            'alert_type': EmotionAlertType.SUSTAINED_NEGATIVE.value,
            'risk_level': EmotionRiskLevel.HIGH.value,
            'user_name': '山田太郎',
            'consecutive_negative_days': 5,
        }

        insight = detector._create_insight_data(alert)

        assert insight.importance == Importance.HIGH
        assert '山田太郎' in insight.title
        assert '5日間' in insight.title
        assert insight.classification == Classification.CONFIDENTIAL

    def test_recovery_insight(self, detector):
        """回復アラートのInsightData"""
        alert = {
            'id': uuid4(),
            'alert_type': EmotionAlertType.RECOVERY.value,
            'risk_level': EmotionRiskLevel.LOW.value,
            'user_name': '佐藤花子',
        }

        insight = detector._create_insight_data(alert)

        assert insight.importance == Importance.LOW
        assert '佐藤花子' in insight.title
        assert '回復' in insight.title

    def test_insight_always_confidential(self, detector):
        """InsightDataは常にCONFIDENTIAL分類"""
        for alert_type in EmotionAlertType:
            alert = {
                'id': uuid4(),
                'alert_type': alert_type.value,
                'risk_level': EmotionRiskLevel.MEDIUM.value,
                'user_name': 'テスト',
            }
            insight = detector._create_insight_data(alert)
            assert insight.classification == Classification.CONFIDENTIAL


# ================================================================
# 感情分析プロンプトのテスト
# ================================================================

class TestSentimentAnalysisPrompt:
    """感情分析プロンプトのテスト"""

    def test_prompt_exists(self):
        """プロンプトが存在すること"""
        assert SENTIMENT_ANALYSIS_PROMPT is not None
        assert len(SENTIMENT_ANALYSIS_PROMPT) > 100

    def test_prompt_contains_json_instruction(self):
        """JSONフォーマット指示が含まれること"""
        assert 'JSON' in SENTIMENT_ANALYSIS_PROMPT or 'json' in SENTIMENT_ANALYSIS_PROMPT

    def test_prompt_contains_score_range(self):
        """スコア範囲の説明が含まれること"""
        assert '-1.0' in SENTIMENT_ANALYSIS_PROMPT
        assert '1.0' in SENTIMENT_ANALYSIS_PROMPT

    def test_prompt_contains_label_options(self):
        """ラベルオプションが含まれること"""
        assert 'negative' in SENTIMENT_ANALYSIS_PROMPT
        assert 'positive' in SENTIMENT_ANALYSIS_PROMPT
        assert 'neutral' in SENTIMENT_ANALYSIS_PROMPT


# ================================================================
# EmotionDetector 初期化のテスト
# ================================================================

class TestEmotionDetectorInit:
    """EmotionDetectorの初期化テスト"""

    @pytest.fixture
    def mock_conn(self):
        """モックDB接続"""
        return MagicMock()

    def test_default_parameters(self, mock_conn):
        """デフォルトパラメータで初期化"""
        org_id = uuid4()
        detector = EmotionDetector(mock_conn, org_id)

        assert detector._analysis_window_days == DetectionParameters.EMOTION_ANALYSIS_WINDOW_DAYS
        assert detector._baseline_window_days == DetectionParameters.EMOTION_BASELINE_WINDOW_DAYS
        assert detector._min_messages == DetectionParameters.MIN_MESSAGES_FOR_EMOTION

    def test_custom_parameters(self, mock_conn):
        """カスタムパラメータで初期化"""
        org_id = uuid4()
        detector = EmotionDetector(
            mock_conn,
            org_id,
            analysis_window_days=7,
            baseline_window_days=14,
            min_messages=3,
        )

        assert detector._analysis_window_days == 7
        assert detector._baseline_window_days == 14
        assert detector._min_messages == 3

    def test_detector_type_is_a4_emotion(self, mock_conn):
        """検出器タイプがA4_EMOTIONであること"""
        org_id = uuid4()
        detector = EmotionDetector(mock_conn, org_id)

        assert detector._detector_type == SourceType.A4_EMOTION

    def test_insight_type_is_emotion_change(self, mock_conn):
        """インサイトタイプがEMOTION_CHANGEであること"""
        org_id = uuid4()
        detector = EmotionDetector(mock_conn, org_id)

        assert detector._insight_type == InsightType.EMOTION_CHANGE


# ================================================================
# 感情分析レスポンスパースのテスト
# ================================================================

class TestSentimentResponseParsing:
    """感情分析レスポンスのパースをテスト"""

    @pytest.fixture
    def mock_conn(self):
        """モックDB接続"""
        return MagicMock()

    @pytest.fixture
    def detector(self, mock_conn):
        """テスト用EmotionDetector"""
        org_id = uuid4()
        return EmotionDetector(mock_conn, org_id)

    @pytest.mark.asyncio
    async def test_parse_valid_json_response(self, detector):
        """正常なJSONレスポンスのパース"""
        with patch.object(detector, '_call_openrouter_api') as mock_api:
            mock_api.return_value = json.dumps({
                "sentiment_score": -0.3,
                "sentiment_label": "negative",
                "detected_emotions": ["frustration"],
                "confidence": 0.8
            })

            result = await detector._analyze_sentiment("テストメッセージ")

            assert result is not None
            assert result['sentiment_score'] == -0.3
            assert result['sentiment_label'] == 'negative'
            assert 'frustration' in result['detected_emotions']
            assert result['confidence'] == 0.8

    @pytest.mark.asyncio
    async def test_parse_response_with_markdown(self, detector):
        """Markdownコードブロック付きレスポンスのパース"""
        with patch.object(detector, '_call_openrouter_api') as mock_api:
            mock_api.return_value = """```json
{
    "sentiment_score": 0.5,
    "sentiment_label": "positive",
    "detected_emotions": ["happiness"],
    "confidence": 0.9
}
```"""

            result = await detector._analyze_sentiment("テストメッセージ")

            assert result is not None
            assert result['sentiment_score'] == 0.5
            assert result['sentiment_label'] == 'positive'

    @pytest.mark.asyncio
    async def test_parse_invalid_json_returns_none(self, detector):
        """不正なJSONはNoneを返す"""
        with patch.object(detector, '_call_openrouter_api') as mock_api:
            mock_api.return_value = "これは有効なJSONではありません"

            result = await detector._analyze_sentiment("テストメッセージ")

            assert result is None

    @pytest.mark.asyncio
    async def test_score_clamped_to_range(self, detector):
        """スコアは-1.0〜1.0の範囲に制限される"""
        with patch.object(detector, '_call_openrouter_api') as mock_api:
            mock_api.return_value = json.dumps({
                "sentiment_score": 2.5,  # 範囲外
                "sentiment_label": "positive",
                "confidence": 0.5
            })

            result = await detector._analyze_sentiment("テストメッセージ")

            assert result is not None
            assert result['sentiment_score'] == 1.0  # clamped to max

    @pytest.mark.asyncio
    async def test_api_error_returns_none(self, detector):
        """API呼び出しエラー時はNoneを返す"""
        with patch.object(detector, '_call_openrouter_api') as mock_api:
            mock_api.return_value = None

            result = await detector._analyze_sentiment("テストメッセージ")

            assert result is None


# ================================================================
# 感情分析結果のバリデーションテスト
# ================================================================

class TestSentimentValidation:
    """感情分析結果のバリデーションテスト"""

    def test_sentiment_label_valid_values(self):
        """有効な感情ラベルの値"""
        valid_labels = ['very_negative', 'negative', 'neutral', 'positive', 'very_positive']
        for label in SentimentLabel:
            assert label.value in valid_labels

    def test_score_to_label_consistency(self):
        """スコアからラベルへの変換の一貫性"""
        test_cases = [
            (0.8, SentimentLabel.VERY_POSITIVE),
            (0.4, SentimentLabel.POSITIVE),
            (0.0, SentimentLabel.NEUTRAL),
            (-0.3, SentimentLabel.NEGATIVE),
            (-0.7, SentimentLabel.VERY_NEGATIVE),
        ]
        for score, expected_label in test_cases:
            assert SentimentLabel.from_score(score) == expected_label


# ================================================================
# プライバシー・機密分類のテスト
# ================================================================

class TestPrivacyAndClassification:
    """プライバシーと機密分類のテスト"""

    @pytest.fixture
    def mock_conn(self):
        """モックDB接続"""
        return MagicMock()

    @pytest.fixture
    def detector(self, mock_conn):
        """テスト用EmotionDetector"""
        org_id = uuid4()
        return EmotionDetector(mock_conn, org_id)

    def test_insight_classification_always_confidential(self, detector):
        """InsightDataは常にCONFIDENTIAL"""
        for alert_type in EmotionAlertType:
            for risk_level in EmotionRiskLevel:
                alert = {
                    'id': uuid4(),
                    'alert_type': alert_type.value,
                    'risk_level': risk_level.value,
                    'user_name': 'テスト',
                }
                insight = detector._create_insight_data(alert)
                assert insight.classification == Classification.CONFIDENTIAL

    def test_evidence_does_not_contain_message_body(self, detector):
        """evidenceにメッセージ本文が含まれないこと"""
        alert = {
            'id': uuid4(),
            'alert_type': EmotionAlertType.SUDDEN_DROP.value,
            'risk_level': EmotionRiskLevel.HIGH.value,
            'user_name': 'テスト',
            'score_change': 0.3,
            'consecutive_negative_days': 2,
        }
        insight = detector._create_insight_data(alert)

        evidence = insight.evidence
        # メッセージ本文を示すキーがないことを確認
        assert 'message' not in evidence
        assert 'body' not in evidence
        assert 'text' not in evidence
        assert 'content' not in evidence
