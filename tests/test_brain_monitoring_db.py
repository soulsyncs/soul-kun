# tests/test_brain_monitoring_db.py
"""
Brain Monitoring DB連携テスト

設計書: docs/25_llm_native_brain_architecture.md セクション15

【テスト対象】
- DailyDBMetrics データクラス
- DBBrainMonitor クラス
- アラートチェック
- ダッシュボード出力

Author: Claude Opus 4.5
Created: 2026-01-31
"""

import pytest
from datetime import datetime, date
from unittest.mock import MagicMock, AsyncMock

from lib.brain.monitoring import (
    DailyDBMetrics,
    DBBrainMonitor,
    create_db_monitor,
    MonitoringThresholds,
    DEFAULT_THRESHOLDS,
)


class TestDailyDBMetrics:
    """DailyDBMetrics のテスト"""

    def test_create_empty_metrics(self):
        """空のメトリクス作成"""
        metrics = DailyDBMetrics(
            organization_id="org_test",
            metric_date=datetime.now(),
        )

        assert metrics.total_conversations == 0
        assert metrics.error_rate == 0.0
        assert metrics.confirm_rate == 0.0
        assert metrics.block_rate == 0.0

    def test_error_rate_calculation(self):
        """エラー率計算"""
        metrics = DailyDBMetrics(
            organization_id="org_test",
            metric_date=datetime.now(),
            total_conversations=100,
            error_count=5,
        )

        assert metrics.error_rate == 5.0  # 5%

    def test_confirm_rate_calculation(self):
        """確認モード率計算"""
        metrics = DailyDBMetrics(
            organization_id="org_test",
            metric_date=datetime.now(),
            total_conversations=100,
            confirm_count=30,
        )

        assert metrics.confirm_rate == 30.0  # 30%

    def test_block_rate_calculation(self):
        """ブロック率計算"""
        metrics = DailyDBMetrics(
            organization_id="org_test",
            metric_date=datetime.now(),
            total_conversations=100,
            block_count=10,
        )

        assert metrics.block_rate == 10.0  # 10%

    def test_check_alerts_no_alerts(self):
        """アラートなし"""
        metrics = DailyDBMetrics(
            organization_id="org_test",
            metric_date=datetime.now(),
            total_conversations=100,
            avg_response_time_ms=2000,  # 2秒（閾値内）
            error_count=2,  # 2%（閾値内）
            confirm_count=20,  # 20%（閾値内）
            block_count=5,  # 5%（閾値内）
            total_cost_yen=3000,  # 3000円（閾値内）
        )

        alerts = metrics.check_alerts()
        assert len(alerts) == 0

    def test_check_alerts_response_time(self):
        """応答時間アラート"""
        metrics = DailyDBMetrics(
            organization_id="org_test",
            metric_date=datetime.now(),
            total_conversations=100,
            avg_response_time_ms=15000,  # 15秒（閾値超過）
        )

        alerts = metrics.check_alerts()
        response_time_alerts = [a for a in alerts if a["category"] == "response_time"]

        assert len(response_time_alerts) == 1
        assert response_time_alerts[0]["level"] == "warning"
        assert "15000" in response_time_alerts[0]["message"]

    def test_check_alerts_error_rate(self):
        """エラー率アラート"""
        metrics = DailyDBMetrics(
            organization_id="org_test",
            metric_date=datetime.now(),
            total_conversations=100,
            error_count=10,  # 10%（閾値超過）
        )

        alerts = metrics.check_alerts()
        error_alerts = [a for a in alerts if a["category"] == "error_rate"]

        assert len(error_alerts) == 1
        assert error_alerts[0]["level"] == "warning"

    def test_check_alerts_confirm_rate(self):
        """確認モード率アラート（情報レベル）"""
        metrics = DailyDBMetrics(
            organization_id="org_test",
            metric_date=datetime.now(),
            total_conversations=100,
            confirm_count=35,  # 35%（閾値超過）
        )

        alerts = metrics.check_alerts()
        confirm_alerts = [a for a in alerts if a["category"] == "confirm_rate"]

        assert len(confirm_alerts) == 1
        assert confirm_alerts[0]["level"] == "info"

    def test_check_alerts_block_rate(self):
        """ブロック率アラート"""
        metrics = DailyDBMetrics(
            organization_id="org_test",
            metric_date=datetime.now(),
            total_conversations=100,
            block_count=15,  # 15%（閾値超過）
        )

        alerts = metrics.check_alerts()
        block_alerts = [a for a in alerts if a["category"] == "block_rate"]

        assert len(block_alerts) == 1
        assert block_alerts[0]["level"] == "warning"

    def test_check_alerts_daily_cost(self):
        """日次コストアラート"""
        metrics = DailyDBMetrics(
            organization_id="org_test",
            metric_date=datetime.now(),
            total_conversations=100,
            total_cost_yen=6000,  # 6000円（閾値超過）
        )

        alerts = metrics.check_alerts()
        cost_alerts = [a for a in alerts if a["category"] == "daily_cost"]

        assert len(cost_alerts) == 1
        assert cost_alerts[0]["level"] == "warning"

    def test_to_dashboard_string(self):
        """ダッシュボード文字列生成"""
        metrics = DailyDBMetrics(
            organization_id="org_test",
            metric_date=datetime(2026, 1, 31),
            total_conversations=150,
            unique_users=25,
            avg_response_time_ms=2300,
            avg_confidence=0.85,
            allow_count=130,
            confirm_count=12,
            block_count=2,
            success_count=145,
            error_count=5,
            total_cost_yen=1234,
            total_input_tokens=100000,
            total_output_tokens=5000,
            slow_request_count=3,
        )

        dashboard = metrics.to_dashboard_string()

        assert "ソウルくん脳モニター" in dashboard
        assert "2026-01-31" in dashboard
        assert "150" in dashboard  # 総会話数
        assert "2.3秒" in dashboard  # 平均応答時間
        assert "0.85" in dashboard  # 確信度
        assert "1,234" in dashboard  # コスト

    def test_to_dashboard_string_with_alerts(self):
        """アラート付きダッシュボード"""
        metrics = DailyDBMetrics(
            organization_id="org_test",
            metric_date=datetime(2026, 1, 31),
            total_conversations=100,
            avg_response_time_ms=15000,  # 閾値超過
            total_cost_yen=6000,  # 閾値超過
        )

        dashboard = metrics.to_dashboard_string()

        assert "アラート" in dashboard
        assert "WARNING" in dashboard


class TestDBBrainMonitor:
    """DBBrainMonitor のテスト"""

    def test_create_monitor_without_pool(self):
        """プールなしでモニター作成"""
        monitor = DBBrainMonitor()

        assert monitor.pool is None

    @pytest.mark.asyncio
    async def test_get_daily_metrics_no_pool(self):
        """プールなしでメトリクス取得"""
        monitor = DBBrainMonitor()

        metrics = await monitor.get_daily_metrics(
            "org_test",
            datetime.now(),
        )

        assert metrics.organization_id == "org_test"
        assert metrics.total_conversations == 0

    @pytest.mark.asyncio
    async def test_get_daily_metrics_from_aggregated_table(self):
        """集計テーブルからメトリクス取得"""
        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        # 集計テーブルにデータがある場合
        mock_conn.fetchrow.return_value = {
            "total_conversations": 150,
            "unique_users": 25,
            "avg_response_time_ms": 2300,
            "p50_response_time_ms": 2000,
            "p95_response_time_ms": 5000,
            "p99_response_time_ms": 8000,
            "max_response_time_ms": 12000,
            "avg_confidence": 0.85,
            "min_confidence": 0.6,
            "tool_call_count": 100,
            "text_response_count": 40,
            "clarification_count": 10,
            "allow_count": 130,
            "confirm_count": 12,
            "block_count": 2,
            "success_count": 145,
            "error_count": 5,
            "total_input_tokens": 100000,
            "total_output_tokens": 5000,
            "total_cost_yen": 1234.56,
            "slow_request_count": 3,
        }

        monitor = DBBrainMonitor(pool=mock_pool)

        metrics = await monitor.get_daily_metrics(
            "org_test",
            datetime.now(),
        )

        assert metrics.total_conversations == 150
        assert metrics.unique_users == 25
        assert metrics.avg_response_time_ms == 2300
        assert metrics.avg_confidence == 0.85

    @pytest.mark.asyncio
    async def test_get_daily_metrics_realtime_aggregation(self):
        """リアルタイム集計でメトリクス取得"""
        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        # 最初のクエリ（集計テーブル）はデータなし
        # 2回目のクエリ（リアルタイム集計）はデータあり
        mock_conn.fetchrow.side_effect = [
            None,  # 集計テーブルにデータなし
            {  # リアルタイム集計結果
                "total_conversations": 50,
                "unique_users": 10,
                "avg_response_time_ms": 3000,
                "p50_response_time_ms": 2500,
                "p95_response_time_ms": 6000,
                "p99_response_time_ms": 9000,
                "max_response_time_ms": 15000,
                "avg_confidence": 0.80,
                "min_confidence": 0.5,
                "tool_call_count": 30,
                "text_response_count": 15,
                "clarification_count": 5,
                "allow_count": 40,
                "confirm_count": 8,
                "block_count": 2,
                "success_count": 45,
                "error_count": 5,
                "total_input_tokens": 50000,
                "total_output_tokens": 2500,
                "total_cost_yen": 617.28,
                "slow_request_count": 2,
            },
        ]

        monitor = DBBrainMonitor(pool=mock_pool)

        metrics = await monitor.get_daily_metrics(
            "org_test",
            datetime.now(),
        )

        assert metrics.total_conversations == 50
        assert mock_conn.fetchrow.call_count == 2

    @pytest.mark.asyncio
    async def test_get_monthly_cost(self):
        """月次コスト取得"""
        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        mock_conn.fetchrow.return_value = {
            "total_conversations": 5000,
            "total_input_tokens": 100000000,
            "total_output_tokens": 1250000,
            "total_cost_yen": 28500.0,
            "avg_cost_per_conversation": 5.7,
        }

        monitor = DBBrainMonitor(pool=mock_pool)

        result = await monitor.get_monthly_cost("org_test", 2026, 1)

        assert result["year"] == 2026
        assert result["month"] == 1
        assert result["total_conversations"] == 5000
        assert result["total_cost_yen"] == 28500.0

    @pytest.mark.asyncio
    async def test_get_monthly_cost_no_pool(self):
        """プールなしで月次コスト取得"""
        monitor = DBBrainMonitor()

        result = await monitor.get_monthly_cost("org_test", 2026, 1)

        assert "error" in result

    @pytest.mark.asyncio
    async def test_trigger_daily_aggregation(self):
        """日次集計トリガー"""
        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        monitor = DBBrainMonitor(pool=mock_pool)

        result = await monitor.trigger_daily_aggregation(
            "org_test",
            datetime.now(),
        )

        assert result is True
        mock_conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_trigger_daily_aggregation_no_pool(self):
        """プールなしで日次集計トリガー"""
        monitor = DBBrainMonitor()

        result = await monitor.trigger_daily_aggregation(
            "org_test",
            datetime.now(),
        )

        assert result is False


class TestMonitoringThresholds:
    """MonitoringThresholds のテスト"""

    def test_default_thresholds(self):
        """デフォルト閾値"""
        thresholds = DEFAULT_THRESHOLDS

        # 設計書15.1の値と一致
        assert thresholds.response_time_critical_ms == 10000  # 10秒
        assert thresholds.error_rate_critical == 0.05  # 5%
        assert thresholds.guardian_confirm_rate_info == 0.30  # 30%
        assert thresholds.guardian_block_rate_warning == 0.10  # 10%
        assert thresholds.daily_cost_warning == 5000.0  # 5,000円

    def test_custom_thresholds(self):
        """カスタム閾値"""
        thresholds = MonitoringThresholds(
            error_rate_warning=0.02,
            response_time_warning_ms=5000,
        )

        assert thresholds.error_rate_warning == 0.02
        assert thresholds.response_time_warning_ms == 5000


class TestFactoryFunctions:
    """ファクトリ関数のテスト"""

    def test_create_db_monitor(self):
        """DBモニター作成"""
        monitor = create_db_monitor()

        assert isinstance(monitor, DBBrainMonitor)
        assert monitor.pool is None

    def test_create_db_monitor_with_pool(self):
        """プール付きDBモニター作成"""
        mock_pool = MagicMock()
        monitor = create_db_monitor(pool=mock_pool)

        assert monitor.pool is mock_pool
