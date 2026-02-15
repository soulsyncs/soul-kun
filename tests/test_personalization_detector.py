"""
lib/detection/personalization_detector.py のテスト

属人化検出器の網羅的なテスト。
カバレッジ80%以上を目指す。
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime, timezone, timedelta
from uuid import uuid4, UUID
from decimal import Decimal

from lib.detection.personalization_detector import PersonalizationDetector
from lib.detection.base import DetectionResult, InsightData
from lib.detection.constants import (
    PersonalizationRiskLevel,
    PersonalizationStatus,
    InsightType,
    SourceType,
    Importance,
    Classification,
    DetectionParameters,
)


# ================================================================
# フィクスチャ
# ================================================================

@pytest.fixture
def mock_conn():
    """モックDB接続"""
    return MagicMock()


@pytest.fixture
def org_id():
    """テスト用組織ID"""
    return uuid4()


@pytest.fixture
def detector(mock_conn, org_id):
    """PersonalizationDetectorインスタンス"""
    with patch.object(PersonalizationDetector, '__init__', lambda self, *args, **kwargs: None):
        d = PersonalizationDetector.__new__(PersonalizationDetector)
        d._conn = mock_conn
        d._org_id = org_id
        d._detector_type = SourceType.A2_PERSONALIZATION
        d._insight_type = InsightType.PERSONALIZATION_RISK
        d._personalization_threshold = 0.8
        d._min_responses = 5
        d._analysis_window_days = 30
        d._high_risk_days = 14
        d._critical_risk_days = 30
        d._logger = MagicMock()
        return d


# ================================================================
# 初期化テスト
# ================================================================

class TestPersonalizationDetectorInit:
    """初期化のテスト"""

    def test_init_default_values(self, mock_conn, org_id):
        """デフォルト値で初期化"""
        with patch('lib.detection.personalization_detector.BaseDetector.__init__'):
            detector = PersonalizationDetector(mock_conn, org_id)

            assert detector._personalization_threshold == DetectionParameters.PERSONALIZATION_THRESHOLD
            assert detector._min_responses == DetectionParameters.MIN_RESPONSES_FOR_PERSONALIZATION
            assert detector._analysis_window_days == DetectionParameters.PERSONALIZATION_WINDOW_DAYS
            assert detector._high_risk_days == DetectionParameters.HIGH_RISK_EXCLUSIVE_DAYS
            assert detector._critical_risk_days == DetectionParameters.CRITICAL_RISK_EXCLUSIVE_DAYS

    def test_init_custom_values(self, mock_conn, org_id):
        """カスタム値で初期化"""
        with patch('lib.detection.personalization_detector.BaseDetector.__init__'):
            detector = PersonalizationDetector(
                mock_conn,
                org_id,
                personalization_threshold=0.9,
                min_responses=10,
                analysis_window_days=60,
                high_risk_days=21,
                critical_risk_days=45,
            )

            assert detector._personalization_threshold == 0.9
            assert detector._min_responses == 10
            assert detector._analysis_window_days == 60
            assert detector._high_risk_days == 21
            assert detector._critical_risk_days == 45


# ================================================================
# 検出テスト
# ================================================================

class TestDetect:
    """detect メソッドのテスト"""

    @pytest.mark.asyncio
    async def test_detect_success(self, detector):
        """検出成功"""
        user_id = uuid4()
        detector.log_detection_start = MagicMock()
        detector.log_detection_complete = MagicMock()
        detector._get_response_statistics = AsyncMock(return_value={
            "general": {
                "total_responses": 10,
                "responders": {str(user_id): 9},
                "responder_names": {str(user_id): "田中太郎"},
                "consecutive_days": 30,
            }
        })
        detector._evaluate_personalization = MagicMock(return_value={
            'expert_user_id': user_id,
            'topic_category': 'general',
            'total_responses': 10,
            'expert_responses': 9,
            'personalization_ratio': Decimal('0.9'),
            'risk_level': PersonalizationRiskLevel.HIGH.value,
            'alternative_responders': [],
            'has_alternative': False,
            'consecutive_days': 30,
            'responder_name': '田中太郎',
        })
        detector._save_risk = AsyncMock(return_value={
            'id': uuid4(),
            'expert_user_id': user_id,
            'topic_category': 'general',
            'risk_level': PersonalizationRiskLevel.HIGH.value,
            'personalization_ratio': Decimal('0.9'),
            'has_alternative': False,
            'consecutive_days': 30,
            'responder_name': '田中太郎',
            'total_responses': 10,
            'expert_responses': 9,
        })
        detector.insight_exists_for_source = AsyncMock(return_value=False)
        detector.save_insight = AsyncMock(return_value=uuid4())
        detector._create_insight_data = MagicMock(return_value=MagicMock())

        result = await detector.detect()

        assert result.success is True
        assert result.detected_count == 1
        assert result.insight_created is True

    @pytest.mark.asyncio
    async def test_detect_no_stats(self, detector):
        """統計なしの場合"""
        detector.log_detection_start = MagicMock()
        detector.log_detection_complete = MagicMock()
        detector._get_response_statistics = AsyncMock(return_value={})

        result = await detector.detect()

        assert result.success is True
        assert result.detected_count == 0
        assert result.insight_created is False
        assert "分析対象の回答がありません" in result.details['message']

    @pytest.mark.asyncio
    async def test_detect_no_risk(self, detector):
        """リスクなしの場合"""
        detector.log_detection_start = MagicMock()
        detector.log_detection_complete = MagicMock()
        detector._get_response_statistics = AsyncMock(return_value={
            "general": {"total_responses": 10, "responders": {}}
        })
        detector._evaluate_personalization = MagicMock(return_value=None)

        result = await detector.detect()

        assert result.success is True
        assert result.detected_count == 0

    @pytest.mark.asyncio
    async def test_detect_exception(self, detector):
        """例外発生時"""
        detector.log_detection_start = MagicMock()
        detector.log_error = MagicMock()
        detector._get_response_statistics = AsyncMock(side_effect=Exception("DB Error"))

        result = await detector.detect()

        assert result.success is False
        assert "パーソナライゼーション検出中に内部エラーが発生しました" in result.error_message

    @pytest.mark.asyncio
    async def test_detect_low_risk_no_insight(self, detector):
        """低リスクの場合はインサイト作成しない"""
        user_id = uuid4()
        detector.log_detection_start = MagicMock()
        detector.log_detection_complete = MagicMock()
        detector._get_response_statistics = AsyncMock(return_value={
            "general": {
                "total_responses": 10,
                "responders": {str(user_id): 7},
                "responder_names": {str(user_id): "田中太郎"},
                "consecutive_days": 5,
            }
        })
        detector._evaluate_personalization = MagicMock(return_value={
            'expert_user_id': user_id,
            'topic_category': 'general',
            'risk_level': PersonalizationRiskLevel.LOW.value,
        })
        detector._save_risk = AsyncMock(return_value={
            'id': uuid4(),
            'risk_level': PersonalizationRiskLevel.LOW.value,
        })

        result = await detector.detect()

        assert result.success is True
        assert result.insight_created is False


# ================================================================
# 回答統計取得テスト
# ================================================================

class TestGetResponseStatistics:
    """_get_response_statistics のテスト"""

    @pytest.mark.asyncio
    async def test_get_stats_success(self, detector, mock_conn):
        """統計取得成功"""
        user_id = uuid4()
        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([
            (user_id, "田中太郎", 10),
            (uuid4(), "山田花子", 5),
        ])
        mock_conn.execute.return_value = mock_result

        stats = await detector._get_response_statistics()

        assert "general" in stats
        assert stats["general"]["total_responses"] == 15
        assert len(stats["general"]["responders"]) == 2

    @pytest.mark.asyncio
    async def test_get_stats_empty(self, detector, mock_conn):
        """結果が空の場合"""
        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([])
        mock_conn.execute.return_value = mock_result

        stats = await detector._get_response_statistics()

        assert stats == {}

    @pytest.mark.asyncio
    async def test_get_stats_null_user_id(self, detector, mock_conn):
        """user_idがNullの場合はスキップ"""
        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([
            (None, "Unknown", 5),
            (uuid4(), "田中太郎", 10),
        ])
        mock_conn.execute.return_value = mock_result

        stats = await detector._get_response_statistics()

        assert stats["general"]["total_responses"] == 10

    @pytest.mark.asyncio
    async def test_get_stats_db_error(self, detector, mock_conn):
        """DB例外"""
        mock_conn.execute.side_effect = Exception("DB Error")

        with pytest.raises(Exception):
            await detector._get_response_statistics()


# ================================================================
# 属人化評価テスト
# ================================================================

class TestEvaluatePersonalization:
    """_evaluate_personalization のテスト"""

    def test_evaluate_below_min_responses(self, detector):
        """最小回答数未満"""
        stats = {"total_responses": 3, "responders": {str(uuid4()): 3}}
        result = detector._evaluate_personalization("test", stats)
        assert result is None

    def test_evaluate_no_responders(self, detector):
        """回答者なし"""
        stats = {"total_responses": 10, "responders": {}}
        result = detector._evaluate_personalization("test", stats)
        assert result is None

    def test_evaluate_low_ratio(self, detector):
        """偏り率60%未満"""
        user1 = str(uuid4())
        user2 = str(uuid4())
        stats = {
            "total_responses": 10,
            "responders": {user1: 5, user2: 5},
            "responder_names": {user1: "A", user2: "B"},
            "consecutive_days": 30,
        }
        result = detector._evaluate_personalization("test", stats)
        assert result is None

    def test_evaluate_high_ratio_detected(self, detector):
        """高偏り率で検出"""
        user1 = str(uuid4())
        user2 = str(uuid4())
        stats = {
            "total_responses": 10,
            "responders": {user1: 8, user2: 2},
            "responder_names": {user1: "田中太郎", user2: "山田"},
            "consecutive_days": 30,
        }
        result = detector._evaluate_personalization("general", stats)

        assert result is not None
        assert result['expert_user_id'] == UUID(user1)
        assert result['personalization_ratio'] == Decimal('0.8')
        assert result['has_alternative'] is True
        assert len(result['alternative_responders']) == 1

    def test_evaluate_exclusive(self, detector):
        """独占状態（1人のみ）"""
        user1 = str(uuid4())
        stats = {
            "total_responses": 10,
            "responders": {user1: 10},
            "responder_names": {user1: "田中太郎"},
            "consecutive_days": 30,
        }
        result = detector._evaluate_personalization("general", stats)

        assert result is not None
        assert result['has_alternative'] is False
        assert result['risk_level'] == PersonalizationRiskLevel.CRITICAL.value


# ================================================================
# リスクレベル判定テスト
# ================================================================

class TestDetermineRiskLevel:
    """_determine_risk_level のテスト"""

    def test_critical_exclusive_long_term(self, detector):
        """独占状態で30日以上 → CRITICAL"""
        result = detector._determine_risk_level(
            ratio=1.0,
            exclusive=True,
            consecutive_days=30,
        )
        assert result == PersonalizationRiskLevel.CRITICAL.value

    def test_high_threshold_exceeded(self, detector):
        """閾値超過で14日以上 → HIGH"""
        result = detector._determine_risk_level(
            ratio=0.85,
            exclusive=False,
            consecutive_days=14,
        )
        assert result == PersonalizationRiskLevel.HIGH.value

    def test_medium_moderate(self, detector):
        """60%以上で7日以上 → MEDIUM"""
        result = detector._determine_risk_level(
            ratio=0.65,
            exclusive=False,
            consecutive_days=7,
        )
        assert result == PersonalizationRiskLevel.MEDIUM.value

    def test_low_short_term(self, detector):
        """短期間 → LOW"""
        result = detector._determine_risk_level(
            ratio=0.65,
            exclusive=False,
            consecutive_days=3,
        )
        assert result == PersonalizationRiskLevel.LOW.value


# ================================================================
# リスク保存テスト
# ================================================================

class TestSaveRisk:
    """_save_risk のテスト"""

    @pytest.mark.asyncio
    async def test_save_risk_success(self, detector, mock_conn):
        """リスク保存成功"""
        risk_id = uuid4()
        user_id = uuid4()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (risk_id, 15)
        mock_conn.execute.return_value = mock_result

        risk = {
            'expert_user_id': user_id,
            'topic_category': 'general',
            'total_responses': 10,
            'expert_responses': 8,
            'personalization_ratio': Decimal('0.8'),
            'consecutive_days': 14,
            'alternative_responders': [],
            'has_alternative': False,
            'risk_level': PersonalizationRiskLevel.HIGH.value,
        }

        result = await detector._save_risk(risk)

        assert result is not None
        assert result['id'] == risk_id
        assert result['consecutive_days'] == 15

    @pytest.mark.asyncio
    async def test_save_risk_no_row(self, detector, mock_conn):
        """行が返されない場合"""
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_conn.execute.return_value = mock_result

        risk = {
            'expert_user_id': uuid4(),
            'topic_category': 'general',
            'total_responses': 10,
            'expert_responses': 8,
            'personalization_ratio': Decimal('0.8'),
            'consecutive_days': 14,
            'alternative_responders': [],
            'has_alternative': False,
            'risk_level': PersonalizationRiskLevel.HIGH.value,
        }

        result = await detector._save_risk(risk)

        assert result is None

    @pytest.mark.asyncio
    async def test_save_risk_db_error(self, detector, mock_conn):
        """DB例外"""
        mock_conn.execute.side_effect = Exception("DB Error")

        risk = {
            'expert_user_id': uuid4(),
            'topic_category': 'general',
            'total_responses': 10,
            'expert_responses': 8,
            'personalization_ratio': Decimal('0.8'),
            'consecutive_days': 14,
            'alternative_responders': [],
            'has_alternative': False,
            'risk_level': PersonalizationRiskLevel.HIGH.value,
        }

        result = await detector._save_risk(risk)

        assert result is None
        detector._logger.error.assert_called()


# ================================================================
# インサイトデータ生成テスト
# ================================================================

class TestCreateInsightData:
    """_create_insight_data のテスト"""

    def test_create_insight_critical(self, detector):
        """CRITICALリスクのインサイト生成"""
        risk = {
            'id': uuid4(),
            'expert_user_id': uuid4(),
            'topic_category': 'general',
            'risk_level': PersonalizationRiskLevel.CRITICAL.value,
            'personalization_ratio': Decimal('1.0'),
            'has_alternative': False,
            'consecutive_days': 30,
            'responder_name': '田中太郎',
            'total_responses': 20,
            'expert_responses': 20,
        }

        insight = detector._create_insight_data(risk)

        assert isinstance(insight, InsightData)
        assert insight.importance == Importance.CRITICAL
        assert "100%" in insight.title
        assert "BCPリスク" in insight.description

    def test_create_insight_with_alternative(self, detector):
        """代替者ありのインサイト生成"""
        risk = {
            'id': uuid4(),
            'expert_user_id': uuid4(),
            'topic_category': 'general',
            'risk_level': PersonalizationRiskLevel.HIGH.value,
            'personalization_ratio': Decimal('0.85'),
            'has_alternative': True,
            'consecutive_days': 14,
            'responder_name': '田中太郎',
            'total_responses': 20,
            'expert_responses': 17,
        }

        insight = detector._create_insight_data(risk)

        assert insight.importance == Importance.HIGH
        assert "偏りが大きい" in insight.description

    def test_create_insight_no_responder_name(self, detector):
        """responder_nameなしの場合"""
        risk = {
            'id': uuid4(),
            'expert_user_id': uuid4(),
            'topic_category': 'general',
            'risk_level': PersonalizationRiskLevel.MEDIUM.value,
            'personalization_ratio': Decimal('0.7'),
            'has_alternative': False,
            'consecutive_days': 10,
            'total_responses': 10,
            'expert_responses': 7,
        }

        insight = detector._create_insight_data(risk)

        assert "特定の社員" in insight.description

    def test_create_insight_evidence(self, detector):
        """evidenceフィールドの確認"""
        user_id = uuid4()
        risk = {
            'id': uuid4(),
            'expert_user_id': user_id,
            'topic_category': 'general',
            'risk_level': PersonalizationRiskLevel.LOW.value,
            'personalization_ratio': Decimal('0.65'),
            'has_alternative': True,
            'consecutive_days': 5,
            'responder_name': '田中太郎',
            'total_responses': 20,
            'expert_responses': 13,
        }

        insight = detector._create_insight_data(risk)

        assert insight.evidence['expert_user_id'] == str(user_id)
        assert insight.evidence['personalization_ratio'] == 65
        assert insight.evidence['has_alternative'] is True
