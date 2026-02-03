"""
lib/detection/bottleneck_detector.py のテスト

ボトルネック検出器の網羅的なテスト。
カバレッジ80%以上を目指す。
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime, timezone, timedelta
from uuid import uuid4, UUID
import json

from lib.detection.bottleneck_detector import BottleneckDetector
from lib.detection.base import DetectionResult, InsightData
from lib.detection.constants import (
    BottleneckType,
    BottleneckRiskLevel,
    BottleneckStatus,
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
    """BottleneckDetectorインスタンス"""
    with patch.object(BottleneckDetector, '__init__', lambda self, *args, **kwargs: None):
        d = BottleneckDetector.__new__(BottleneckDetector)
        d._conn = mock_conn
        d._org_id = org_id
        d._detector_type = SourceType.A3_BOTTLENECK
        d._insight_type = InsightType.BOTTLENECK
        d._overdue_critical_days = 7
        d._overdue_high_days = 3
        d._overdue_medium_days = 1
        d._stale_task_days = 7
        d._task_concentration_threshold = 10
        d._concentration_ratio_threshold = 2.0
        d._logger = MagicMock()
        return d


# ================================================================
# 初期化テスト
# ================================================================

class TestBottleneckDetectorInit:
    """初期化のテスト"""

    def test_init_default_values(self, mock_conn, org_id):
        """デフォルト値で初期化"""
        with patch('lib.detection.bottleneck_detector.BaseDetector.__init__'):
            detector = BottleneckDetector(mock_conn, org_id)

            assert detector._overdue_critical_days == DetectionParameters.OVERDUE_CRITICAL_DAYS
            assert detector._overdue_high_days == DetectionParameters.OVERDUE_HIGH_DAYS
            assert detector._overdue_medium_days == DetectionParameters.OVERDUE_MEDIUM_DAYS
            assert detector._stale_task_days == DetectionParameters.STALE_TASK_DAYS
            assert detector._task_concentration_threshold == DetectionParameters.TASK_CONCENTRATION_THRESHOLD
            assert detector._concentration_ratio_threshold == DetectionParameters.CONCENTRATION_RATIO_THRESHOLD

    def test_init_custom_values(self, mock_conn, org_id):
        """カスタム値で初期化"""
        with patch('lib.detection.bottleneck_detector.BaseDetector.__init__'):
            detector = BottleneckDetector(
                mock_conn,
                org_id,
                overdue_critical_days=14,
                overdue_high_days=7,
                overdue_medium_days=3,
                stale_task_days=14,
                task_concentration_threshold=20,
                concentration_ratio_threshold=3.0,
            )

            assert detector._overdue_critical_days == 14
            assert detector._overdue_high_days == 7
            assert detector._overdue_medium_days == 3
            assert detector._stale_task_days == 14
            assert detector._task_concentration_threshold == 20
            assert detector._concentration_ratio_threshold == 3.0


class TestGetOrgIdForChatworkTasks:
    """_get_org_id_for_chatwork_tasks のテスト"""

    def test_returns_soul_syncs(self, detector):
        """'soul_syncs'を返す"""
        result = detector._get_org_id_for_chatwork_tasks()
        assert result == "soul_syncs"


# ================================================================
# 検出テスト
# ================================================================

class TestDetect:
    """detect メソッドのテスト"""

    @pytest.mark.asyncio
    async def test_detect_success(self, detector):
        """検出成功"""
        # モック設定
        detector.log_detection_start = MagicMock()
        detector.log_detection_complete = MagicMock()
        detector._detect_overdue_tasks = AsyncMock(return_value=[
            {
                'bottleneck_type': BottleneckType.OVERDUE_TASK.value,
                'risk_level': BottleneckRiskLevel.HIGH.value,
                'target_type': 'task',
                'target_id': '123',
                'target_name': 'Test Task',
            }
        ])
        detector._detect_stale_tasks = AsyncMock(return_value=[])
        detector._detect_task_concentration = AsyncMock(return_value=[])
        detector._save_alert = AsyncMock(return_value={
            'id': uuid4(),
            'bottleneck_type': BottleneckType.OVERDUE_TASK.value,
            'risk_level': BottleneckRiskLevel.HIGH.value,
            'target_type': 'task',
            'target_id': '123',
            'target_name': 'Test Task',
        })
        detector.insight_exists_for_source = AsyncMock(return_value=False)
        detector.save_insight = AsyncMock(return_value=uuid4())
        detector._create_insight_data = MagicMock(return_value=MagicMock())

        result = await detector.detect()

        assert result.success is True
        assert result.detected_count == 1
        assert result.insight_created is True
        assert result.details['overdue_tasks'] == 1
        assert result.details['stale_tasks'] == 0
        assert result.details['concentration_alerts'] == 0
        assert result.details['insights_created'] == 1

    @pytest.mark.asyncio
    async def test_detect_no_alerts(self, detector):
        """アラートなしの場合"""
        detector.log_detection_start = MagicMock()
        detector.log_detection_complete = MagicMock()
        detector._detect_overdue_tasks = AsyncMock(return_value=[])
        detector._detect_stale_tasks = AsyncMock(return_value=[])
        detector._detect_task_concentration = AsyncMock(return_value=[])

        result = await detector.detect()

        assert result.success is True
        assert result.detected_count == 0
        assert result.insight_created is False

    @pytest.mark.asyncio
    async def test_detect_exception(self, detector):
        """例外発生時"""
        detector.log_detection_start = MagicMock()
        detector.log_error = MagicMock()
        detector._detect_overdue_tasks = AsyncMock(side_effect=Exception("DB Error"))

        result = await detector.detect()

        assert result.success is False
        assert "DB Error" in result.error_message

    @pytest.mark.asyncio
    async def test_detect_multiple_risk_levels(self, detector):
        """複数リスクレベルのアラート"""
        alerts = [
            {'bottleneck_type': 'overdue_task', 'risk_level': 'critical', 'target_type': 'task', 'target_id': '1', 'target_name': 'Task1'},
            {'bottleneck_type': 'overdue_task', 'risk_level': 'high', 'target_type': 'task', 'target_id': '2', 'target_name': 'Task2'},
            {'bottleneck_type': 'stale_task', 'risk_level': 'medium', 'target_type': 'task', 'target_id': '3', 'target_name': 'Task3'},
            {'bottleneck_type': 'stale_task', 'risk_level': 'low', 'target_type': 'task', 'target_id': '4', 'target_name': 'Task4'},
        ]

        detector.log_detection_start = MagicMock()
        detector.log_detection_complete = MagicMock()
        detector._detect_overdue_tasks = AsyncMock(return_value=alerts[:2])
        detector._detect_stale_tasks = AsyncMock(return_value=alerts[2:])
        detector._detect_task_concentration = AsyncMock(return_value=[])

        saved_alerts = []
        for i, alert in enumerate(alerts):
            saved = dict(alert)
            saved['id'] = uuid4()
            saved_alerts.append(saved)

        detector._save_alert = AsyncMock(side_effect=saved_alerts)
        detector.insight_exists_for_source = AsyncMock(return_value=False)
        detector.save_insight = AsyncMock(return_value=uuid4())
        detector._create_insight_data = MagicMock(return_value=MagicMock())

        result = await detector.detect()

        assert result.success is True
        assert result.detected_count == 4
        assert result.details['risk_levels']['critical'] == 1
        assert result.details['risk_levels']['high'] == 1
        assert result.details['risk_levels']['medium'] == 1
        assert result.details['risk_levels']['low'] == 1


# ================================================================
# 期限超過タスク検出テスト
# ================================================================

class TestDetectOverdueTasks:
    """_detect_overdue_tasks のテスト"""

    @pytest.mark.asyncio
    async def test_detect_overdue_critical(self, detector, mock_conn):
        """緊急レベルの期限超過タスクを検出"""
        # 10日超過 → critical
        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([
            (123, "タスク本文", "タスク要約", 1700000000, 456, "担当者", 789, "ルーム名", 10)
        ])
        mock_conn.execute.return_value = mock_result

        alerts = await detector._detect_overdue_tasks()

        assert len(alerts) == 1
        assert alerts[0]['risk_level'] == BottleneckRiskLevel.CRITICAL.value
        assert alerts[0]['bottleneck_type'] == BottleneckType.OVERDUE_TASK.value
        assert alerts[0]['overdue_days'] == 10

    @pytest.mark.asyncio
    async def test_detect_overdue_high(self, detector, mock_conn):
        """高リスクの期限超過タスクを検出"""
        # 5日超過 → high
        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([
            (123, "タスク本文", "タスク要約", 1700000000, 456, "担当者", 789, "ルーム名", 5)
        ])
        mock_conn.execute.return_value = mock_result

        alerts = await detector._detect_overdue_tasks()

        assert len(alerts) == 1
        assert alerts[0]['risk_level'] == BottleneckRiskLevel.HIGH.value

    @pytest.mark.asyncio
    async def test_detect_overdue_medium(self, detector, mock_conn):
        """中リスクの期限超過タスクを検出"""
        # 2日超過 → medium
        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([
            (123, "タスク本文", "タスク要約", 1700000000, 456, "担当者", 789, "ルーム名", 2)
        ])
        mock_conn.execute.return_value = mock_result

        alerts = await detector._detect_overdue_tasks()

        assert len(alerts) == 1
        assert alerts[0]['risk_level'] == BottleneckRiskLevel.MEDIUM.value

    @pytest.mark.asyncio
    async def test_detect_overdue_low(self, detector, mock_conn):
        """低リスクの期限超過タスクを検出"""
        # 0日超過 → low
        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([
            (123, "タスク本文", "タスク要約", 1700000000, 456, "担当者", 789, "ルーム名", 0)
        ])
        mock_conn.execute.return_value = mock_result

        alerts = await detector._detect_overdue_tasks()

        assert len(alerts) == 1
        assert alerts[0]['risk_level'] == BottleneckRiskLevel.LOW.value

    @pytest.mark.asyncio
    async def test_detect_overdue_no_summary(self, detector, mock_conn):
        """要約なしの場合、本文から生成"""
        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([
            (123, "これは長い本文です" * 10, None, 1700000000, 456, "担当者", 789, "ルーム名", 10)
        ])
        mock_conn.execute.return_value = mock_result

        alerts = await detector._detect_overdue_tasks()

        assert len(alerts) == 1
        assert len(alerts[0]['target_name']) <= 50

    @pytest.mark.asyncio
    async def test_detect_overdue_no_body(self, detector, mock_conn):
        """本文もなしの場合"""
        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([
            (123, None, None, 1700000000, 456, "担当者", 789, "ルーム名", 10)
        ])
        mock_conn.execute.return_value = mock_result

        alerts = await detector._detect_overdue_tasks()

        assert len(alerts) == 1
        assert alerts[0]['target_name'] == "タスク"

    @pytest.mark.asyncio
    async def test_detect_overdue_db_error(self, detector, mock_conn):
        """DB例外"""
        mock_conn.execute.side_effect = Exception("DB Error")

        with pytest.raises(Exception):
            await detector._detect_overdue_tasks()


# ================================================================
# 長期未完了タスク検出テスト
# ================================================================

class TestDetectStaleTasks:
    """_detect_stale_tasks のテスト"""

    @pytest.mark.asyncio
    async def test_detect_stale_medium(self, detector, mock_conn):
        """14日以上の長期未完了タスク → medium"""
        mock_result = MagicMock()
        created_at = datetime.now(timezone.utc) - timedelta(days=20)
        mock_result.__iter__ = lambda self: iter([
            (123, "タスク本文", "タスク要約", created_at, None, 456, "担当者", 789, "ルーム名", 20)
        ])
        mock_conn.execute.return_value = mock_result

        alerts = await detector._detect_stale_tasks()

        assert len(alerts) == 1
        assert alerts[0]['risk_level'] == BottleneckRiskLevel.MEDIUM.value
        assert alerts[0]['bottleneck_type'] == BottleneckType.STALE_TASK.value

    @pytest.mark.asyncio
    async def test_detect_stale_low(self, detector, mock_conn):
        """14日未満の長期未完了タスク → low"""
        mock_result = MagicMock()
        created_at = datetime.now(timezone.utc) - timedelta(days=10)
        mock_result.__iter__ = lambda self: iter([
            (123, "タスク本文", "タスク要約", created_at, None, 456, "担当者", 789, "ルーム名", 10)
        ])
        mock_conn.execute.return_value = mock_result

        alerts = await detector._detect_stale_tasks()

        assert len(alerts) == 1
        assert alerts[0]['risk_level'] == BottleneckRiskLevel.LOW.value

    @pytest.mark.asyncio
    async def test_detect_stale_empty(self, detector, mock_conn):
        """長期未完了タスクなし"""
        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([])
        mock_conn.execute.return_value = mock_result

        alerts = await detector._detect_stale_tasks()

        assert len(alerts) == 0

    @pytest.mark.asyncio
    async def test_detect_stale_db_error(self, detector, mock_conn):
        """DB例外"""
        mock_conn.execute.side_effect = Exception("DB Error")

        with pytest.raises(Exception):
            await detector._detect_stale_tasks()


# ================================================================
# タスク集中検出テスト
# ================================================================

class TestDetectTaskConcentration:
    """_detect_task_concentration のテスト"""

    @pytest.mark.asyncio
    async def test_detect_concentration_critical(self, detector, mock_conn):
        """20件以上のタスク集中 → critical"""
        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([
            (456, "田中太郎", 25, [1, 2, 3, 4, 5])
        ])
        mock_conn.execute.return_value = mock_result

        alerts = await detector._detect_task_concentration()

        assert len(alerts) == 1
        assert alerts[0]['risk_level'] == BottleneckRiskLevel.CRITICAL.value
        assert alerts[0]['bottleneck_type'] == BottleneckType.TASK_CONCENTRATION.value
        assert alerts[0]['task_count'] == 25

    @pytest.mark.asyncio
    async def test_detect_concentration_high(self, detector, mock_conn):
        """15件以上のタスク集中 → high"""
        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([
            (456, "田中太郎", 17, [1, 2, 3])
        ])
        mock_conn.execute.return_value = mock_result

        alerts = await detector._detect_task_concentration()

        assert len(alerts) == 1
        assert alerts[0]['risk_level'] == BottleneckRiskLevel.HIGH.value

    @pytest.mark.asyncio
    async def test_detect_concentration_medium(self, detector, mock_conn):
        """10-14件のタスク集中 → medium"""
        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([
            (456, "田中太郎", 12, [1, 2])
        ])
        mock_conn.execute.return_value = mock_result

        alerts = await detector._detect_task_concentration()

        assert len(alerts) == 1
        assert alerts[0]['risk_level'] == BottleneckRiskLevel.MEDIUM.value

    @pytest.mark.asyncio
    async def test_detect_concentration_no_name(self, detector, mock_conn):
        """担当者名なしの場合"""
        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([
            (456, None, 15, [1, 2])
        ])
        mock_conn.execute.return_value = mock_result

        alerts = await detector._detect_task_concentration()

        assert len(alerts) == 1
        assert alerts[0]['target_name'] == "不明"

    @pytest.mark.asyncio
    async def test_detect_concentration_empty_task_ids(self, detector, mock_conn):
        """task_idsがNoneの場合"""
        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([
            (456, "田中太郎", 15, None)
        ])
        mock_conn.execute.return_value = mock_result

        alerts = await detector._detect_task_concentration()

        assert len(alerts) == 1
        assert alerts[0]['related_task_ids'] == []

    @pytest.mark.asyncio
    async def test_detect_concentration_db_error(self, detector, mock_conn):
        """DB例外"""
        mock_conn.execute.side_effect = Exception("DB Error")

        with pytest.raises(Exception):
            await detector._detect_task_concentration()


# ================================================================
# アラート保存テスト
# ================================================================

class TestSaveAlert:
    """_save_alert のテスト"""

    @pytest.mark.asyncio
    async def test_save_alert_success(self, detector, mock_conn):
        """アラート保存成功"""
        alert_id = uuid4()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (alert_id,)
        mock_conn.execute.return_value = mock_result

        alert = {
            'bottleneck_type': BottleneckType.OVERDUE_TASK.value,
            'risk_level': BottleneckRiskLevel.HIGH.value,
            'target_type': 'task',
            'target_id': '123',
            'target_name': 'Test Task',
            'overdue_days': 5,
            'related_task_ids': ['123'],
            'sample_tasks': [{'task_id': 123}],
        }

        result = await detector._save_alert(alert)

        assert result is not None
        assert result['id'] == alert_id

    @pytest.mark.asyncio
    async def test_save_alert_no_row_returned(self, detector, mock_conn):
        """行が返されない場合"""
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_conn.execute.return_value = mock_result

        alert = {
            'bottleneck_type': BottleneckType.OVERDUE_TASK.value,
            'risk_level': BottleneckRiskLevel.HIGH.value,
            'target_type': 'task',
            'target_id': '123',
        }

        result = await detector._save_alert(alert)

        assert result is None

    @pytest.mark.asyncio
    async def test_save_alert_db_error(self, detector, mock_conn):
        """DB例外"""
        mock_conn.execute.side_effect = Exception("DB Error")

        alert = {
            'bottleneck_type': BottleneckType.OVERDUE_TASK.value,
            'risk_level': BottleneckRiskLevel.HIGH.value,
            'target_type': 'task',
            'target_id': '123',
        }

        result = await detector._save_alert(alert)

        assert result is None
        detector._logger.error.assert_called()


# ================================================================
# インサイトデータ生成テスト
# ================================================================

class TestCreateInsightData:
    """_create_insight_data のテスト"""

    def test_create_insight_overdue_task(self, detector):
        """期限超過タスクのインサイト生成"""
        alert = {
            'id': uuid4(),
            'bottleneck_type': BottleneckType.OVERDUE_TASK.value,
            'risk_level': BottleneckRiskLevel.CRITICAL.value,
            'target_type': 'task',
            'target_id': '123',
            'target_name': 'テストタスク',
            'overdue_days': 10,
            'related_task_ids': ['123'],
        }

        insight = detector._create_insight_data(alert)

        assert isinstance(insight, InsightData)
        assert insight.importance == Importance.CRITICAL
        assert "期限超過" in insight.title
        assert "10日" in insight.title
        assert "テストタスク" in insight.description

    def test_create_insight_stale_task(self, detector):
        """長期未完了タスクのインサイト生成"""
        alert = {
            'id': uuid4(),
            'bottleneck_type': BottleneckType.STALE_TASK.value,
            'risk_level': BottleneckRiskLevel.MEDIUM.value,
            'target_type': 'task',
            'target_id': '123',
            'target_name': 'テストタスク',
            'stale_days': 20,
            'related_task_ids': ['123'],
        }

        insight = detector._create_insight_data(alert)

        assert insight.importance == Importance.MEDIUM
        assert "未完了" in insight.title
        assert "20日" in insight.title

    def test_create_insight_task_concentration(self, detector):
        """タスク集中のインサイト生成"""
        alert = {
            'id': uuid4(),
            'bottleneck_type': BottleneckType.TASK_CONCENTRATION.value,
            'risk_level': BottleneckRiskLevel.HIGH.value,
            'target_type': 'user',
            'target_id': '456',
            'target_name': '田中太郎',
            'task_count': 25,
            'related_task_ids': ['1', '2', '3'],
        }

        insight = detector._create_insight_data(alert)

        assert insight.importance == Importance.HIGH
        assert "集中" in insight.title
        assert "25件" in insight.title
        assert "田中太郎" in insight.description

    def test_create_insight_unknown_type(self, detector):
        """不明なボトルネックタイプ"""
        alert = {
            'id': uuid4(),
            'bottleneck_type': 'unknown_type',
            'risk_level': BottleneckRiskLevel.LOW.value,
            'target_type': 'task',
            'target_id': '123',
            'target_name': 'テスト',
        }

        insight = detector._create_insight_data(alert)

        assert insight.importance == Importance.LOW
        assert "ボトルネック" in insight.title

    def test_create_insight_long_target_name(self, detector):
        """長いターゲット名（30文字で切り詰め）"""
        alert = {
            'id': uuid4(),
            'bottleneck_type': BottleneckType.OVERDUE_TASK.value,
            'risk_level': BottleneckRiskLevel.HIGH.value,
            'target_type': 'task',
            'target_id': '123',
            'target_name': 'これは非常に長いタスク名です' * 5,
            'overdue_days': 5,
        }

        insight = detector._create_insight_data(alert)

        # タイトル内のターゲット名は30文字まで
        assert len(insight.title) < 100

    def test_create_insight_no_target_name(self, detector):
        """ターゲット名なし"""
        alert = {
            'id': uuid4(),
            'bottleneck_type': BottleneckType.OVERDUE_TASK.value,
            'risk_level': BottleneckRiskLevel.HIGH.value,
            'target_type': 'task',
            'target_id': '123',
            'overdue_days': 5,
        }

        insight = detector._create_insight_data(alert)

        assert "不明" in insight.title or insight.title is not None

    def test_create_insight_evidence(self, detector):
        """evidenceフィールドの確認"""
        alert = {
            'id': uuid4(),
            'bottleneck_type': BottleneckType.OVERDUE_TASK.value,
            'risk_level': BottleneckRiskLevel.HIGH.value,
            'target_type': 'task',
            'target_id': '123',
            'target_name': 'テスト',
            'overdue_days': 5,
            'task_count': None,
            'stale_days': None,
            'related_task_ids': ['123', '456'],
        }

        insight = detector._create_insight_data(alert)

        assert insight.evidence['bottleneck_type'] == BottleneckType.OVERDUE_TASK.value
        assert insight.evidence['target_type'] == 'task'
        assert insight.evidence['overdue_days'] == 5
        assert insight.evidence['related_task_ids'] == ['123', '456']
