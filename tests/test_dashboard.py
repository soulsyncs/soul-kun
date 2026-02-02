"""
lib/brain/dashboard.py のテスト

対象:
- DashboardMetrics（プロパティ、check_alerts、to_dashboard_string）
- BrainDashboard（get_daily_metrics、get_weekly_summary、get_monthly_cost）
- create_dashboard
"""

import pytest
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from lib.brain.dashboard import (
    DEFAULT_THRESHOLDS,
    DashboardMetrics,
    BrainDashboard,
    create_dashboard,
)


# =============================================================================
# DEFAULT_THRESHOLDS テスト
# =============================================================================


class TestDefaultThresholds:
    """デフォルト閾値のテスト"""

    def test_response_time_warning(self):
        """応答時間の早期警告閾値"""
        assert DEFAULT_THRESHOLDS["response_time_warning_ms"] == 3000

    def test_response_time_critical(self):
        """応答時間の警告閾値"""
        assert DEFAULT_THRESHOLDS["response_time_critical_ms"] == 10000

    def test_error_rate_warning(self):
        """エラー率の早期警告閾値"""
        assert DEFAULT_THRESHOLDS["error_rate_warning"] == 0.03

    def test_error_rate_critical(self):
        """エラー率の警告閾値"""
        assert DEFAULT_THRESHOLDS["error_rate_critical"] == 0.05

    def test_daily_cost_warning(self):
        """日次コスト警告閾値"""
        assert DEFAULT_THRESHOLDS["daily_cost_warning"] == 5000.0

    def test_daily_cost_critical(self):
        """日次コスト警告閾値（重大）"""
        assert DEFAULT_THRESHOLDS["daily_cost_critical"] == 10000.0


# =============================================================================
# DashboardMetrics プロパティテスト
# =============================================================================


class TestDashboardMetricsProperties:
    """DashboardMetricsプロパティのテスト"""

    def test_error_rate_zero_conversations(self):
        """会話数0の場合のエラー率"""
        metrics = DashboardMetrics(
            organization_id="org-1",
            metric_date=date.today(),
            total_conversations=0,
            error_count=5,
        )
        assert metrics.error_rate == 0.0

    def test_error_rate_calculation(self):
        """エラー率の計算"""
        metrics = DashboardMetrics(
            organization_id="org-1",
            metric_date=date.today(),
            total_conversations=100,
            error_count=5,
        )
        assert metrics.error_rate == 5.0

    def test_confirm_rate_zero_conversations(self):
        """会話数0の場合の確認率"""
        metrics = DashboardMetrics(
            organization_id="org-1",
            metric_date=date.today(),
            total_conversations=0,
            confirm_count=10,
        )
        assert metrics.confirm_rate == 0.0

    def test_confirm_rate_calculation(self):
        """確認率の計算"""
        metrics = DashboardMetrics(
            organization_id="org-1",
            metric_date=date.today(),
            total_conversations=100,
            confirm_count=30,
        )
        assert metrics.confirm_rate == 30.0

    def test_block_rate_zero_conversations(self):
        """会話数0の場合のブロック率"""
        metrics = DashboardMetrics(
            organization_id="org-1",
            metric_date=date.today(),
            total_conversations=0,
            block_count=5,
        )
        assert metrics.block_rate == 0.0

    def test_block_rate_calculation(self):
        """ブロック率の計算"""
        metrics = DashboardMetrics(
            organization_id="org-1",
            metric_date=date.today(),
            total_conversations=100,
            block_count=10,
        )
        assert metrics.block_rate == 10.0

    def test_avg_cost_per_conversation_zero(self):
        """会話数0の場合の平均コスト"""
        metrics = DashboardMetrics(
            organization_id="org-1",
            metric_date=date.today(),
            total_conversations=0,
            total_cost_yen=Decimal("1000"),
        )
        assert metrics.avg_cost_per_conversation == Decimal("0")

    def test_avg_cost_per_conversation_calculation(self):
        """平均コストの計算"""
        metrics = DashboardMetrics(
            organization_id="org-1",
            metric_date=date.today(),
            total_conversations=100,
            total_cost_yen=Decimal("1000"),
        )
        assert metrics.avg_cost_per_conversation == Decimal("10")


# =============================================================================
# DashboardMetrics.check_alerts() テスト
# =============================================================================


class TestDashboardMetricsCheckAlerts:
    """check_alerts()のテスト"""

    def test_no_alerts_when_all_ok(self):
        """全て正常な場合はアラートなし"""
        metrics = DashboardMetrics(
            organization_id="org-1",
            metric_date=date.today(),
            total_conversations=100,
            avg_response_time_ms=1000,
            error_count=1,
            confirm_count=10,
            block_count=5,
            total_cost_yen=Decimal("1000"),
        )
        alerts = metrics.check_alerts()
        assert alerts == []

    def test_response_time_warning_alert(self):
        """応答時間警告アラート"""
        metrics = DashboardMetrics(
            organization_id="org-1",
            metric_date=date.today(),
            total_conversations=100,
            avg_response_time_ms=5000,  # 3000ms以上
        )
        alerts = metrics.check_alerts()
        assert len(alerts) == 1
        assert alerts[0]["category"] == "response_time"
        assert alerts[0]["level"] == "info"

    def test_response_time_critical_alert(self):
        """応答時間重大アラート"""
        metrics = DashboardMetrics(
            organization_id="org-1",
            metric_date=date.today(),
            total_conversations=100,
            avg_response_time_ms=15000,  # 10000ms以上
        )
        alerts = metrics.check_alerts()
        response_alerts = [a for a in alerts if a["category"] == "response_time"]
        assert len(response_alerts) == 1
        assert response_alerts[0]["level"] == "warning"

    def test_error_rate_warning_alert(self):
        """エラー率早期警告アラート"""
        metrics = DashboardMetrics(
            organization_id="org-1",
            metric_date=date.today(),
            total_conversations=100,
            error_count=4,  # 4% > 3%
        )
        alerts = metrics.check_alerts()
        error_alerts = [a for a in alerts if a["category"] == "error_rate"]
        assert len(error_alerts) == 1
        assert error_alerts[0]["level"] == "info"

    def test_error_rate_critical_alert(self):
        """エラー率警告アラート"""
        metrics = DashboardMetrics(
            organization_id="org-1",
            metric_date=date.today(),
            total_conversations=100,
            error_count=6,  # 6% > 5%
        )
        alerts = metrics.check_alerts()
        error_alerts = [a for a in alerts if a["category"] == "error_rate"]
        assert len(error_alerts) == 1
        assert error_alerts[0]["level"] == "warning"

    def test_confirm_rate_info_alert(self):
        """確認率情報アラート"""
        metrics = DashboardMetrics(
            organization_id="org-1",
            metric_date=date.today(),
            total_conversations=100,
            confirm_count=35,  # 35% > 30%
        )
        alerts = metrics.check_alerts()
        confirm_alerts = [a for a in alerts if a["category"] == "confirm_rate"]
        assert len(confirm_alerts) == 1
        assert confirm_alerts[0]["level"] == "info"

    def test_block_rate_warning_alert(self):
        """ブロック率警告アラート"""
        metrics = DashboardMetrics(
            organization_id="org-1",
            metric_date=date.today(),
            total_conversations=100,
            block_count=15,  # 15% > 10%
        )
        alerts = metrics.check_alerts()
        block_alerts = [a for a in alerts if a["category"] == "block_rate"]
        assert len(block_alerts) == 1
        assert block_alerts[0]["level"] == "warning"

    def test_daily_cost_warning_alert(self):
        """日次コスト警告アラート"""
        metrics = DashboardMetrics(
            organization_id="org-1",
            metric_date=date.today(),
            total_conversations=100,
            total_cost_yen=Decimal("7000"),  # 7000 > 5000
        )
        alerts = metrics.check_alerts()
        cost_alerts = [a for a in alerts if a["category"] == "daily_cost"]
        assert len(cost_alerts) == 1
        assert cost_alerts[0]["level"] == "warning"

    def test_daily_cost_critical_alert(self):
        """日次コスト重大アラート"""
        metrics = DashboardMetrics(
            organization_id="org-1",
            metric_date=date.today(),
            total_conversations=100,
            total_cost_yen=Decimal("15000"),  # 15000 > 10000
        )
        alerts = metrics.check_alerts()
        cost_alerts = [a for a in alerts if a["category"] == "daily_cost"]
        assert len(cost_alerts) == 1
        assert cost_alerts[0]["level"] == "critical"

    def test_custom_thresholds(self):
        """カスタム閾値"""
        metrics = DashboardMetrics(
            organization_id="org-1",
            metric_date=date.today(),
            total_conversations=100,
            avg_response_time_ms=2000,  # デフォルトでは正常
        )
        custom_thresholds = {**DEFAULT_THRESHOLDS, "response_time_warning_ms": 1000}
        alerts = metrics.check_alerts(thresholds=custom_thresholds)
        response_alerts = [a for a in alerts if a["category"] == "response_time"]
        assert len(response_alerts) == 1

    def test_multiple_alerts(self):
        """複数のアラート"""
        metrics = DashboardMetrics(
            organization_id="org-1",
            metric_date=date.today(),
            total_conversations=100,
            avg_response_time_ms=15000,
            error_count=10,
            confirm_count=40,
            block_count=15,
            total_cost_yen=Decimal("15000"),
        )
        alerts = metrics.check_alerts()
        assert len(alerts) >= 4


# =============================================================================
# DashboardMetrics.to_dashboard_string() テスト
# =============================================================================


class TestDashboardMetricsToDashboardString:
    """to_dashboard_string()のテスト"""

    def test_contains_header(self):
        """ヘッダーを含む"""
        metrics = DashboardMetrics(
            organization_id="org-1",
            metric_date=date(2026, 2, 2),
        )
        result = metrics.to_dashboard_string()
        assert "ソウルくん脳モニター" in result
        assert "2026-02-02" in result

    def test_contains_statistics(self):
        """統計情報を含む"""
        metrics = DashboardMetrics(
            organization_id="org-1",
            metric_date=date.today(),
            total_conversations=100,
            unique_users=50,
        )
        result = metrics.to_dashboard_string()
        assert "100" in result
        assert "50" in result

    def test_contains_response_time(self):
        """応答時間を含む"""
        metrics = DashboardMetrics(
            organization_id="org-1",
            metric_date=date.today(),
            avg_response_time_ms=2500,
        )
        result = metrics.to_dashboard_string()
        assert "2.5秒" in result

    def test_contains_confidence(self):
        """確信度を含む"""
        metrics = DashboardMetrics(
            organization_id="org-1",
            metric_date=date.today(),
            avg_confidence=Decimal("0.85"),
        )
        result = metrics.to_dashboard_string()
        assert "0.85" in result

    def test_contains_guardian_stats(self):
        """Guardian判定統計を含む"""
        metrics = DashboardMetrics(
            organization_id="org-1",
            metric_date=date.today(),
            total_conversations=100,
            allow_count=80,
            confirm_count=15,
            block_count=5,
        )
        result = metrics.to_dashboard_string()
        assert "許可(allow)" in result
        assert "確認(confirm)" in result
        assert "拒否(block)" in result

    def test_contains_cost_info(self):
        """コスト情報を含む"""
        metrics = DashboardMetrics(
            organization_id="org-1",
            metric_date=date.today(),
            total_conversations=100,
            total_cost_yen=Decimal("5000"),
            total_input_tokens=10000,
            total_output_tokens=5000,
        )
        result = metrics.to_dashboard_string()
        assert "5,000" in result
        assert "10,000" in result
        assert "入力トークン" in result
        assert "出力トークン" in result

    def test_contains_alerts_when_present(self):
        """アラートがある場合は表示"""
        metrics = DashboardMetrics(
            organization_id="org-1",
            metric_date=date.today(),
            total_conversations=100,
            total_cost_yen=Decimal("15000"),
        )
        result = metrics.to_dashboard_string()
        assert "アラート" in result
        assert "日次コスト" in result

    def test_no_alerts_section_when_empty(self):
        """アラートがない場合はセクションなし"""
        metrics = DashboardMetrics(
            organization_id="org-1",
            metric_date=date.today(),
            total_conversations=100,
            total_cost_yen=Decimal("1000"),
        )
        result = metrics.to_dashboard_string()
        # アラートがない場合でもダッシュボードは生成される
        assert "ソウルくん脳モニター" in result


# =============================================================================
# BrainDashboard テスト
# =============================================================================


class TestBrainDashboard:
    """BrainDashboardのテスト"""

    def test_init_without_pool(self):
        """プールなしで初期化"""
        dashboard = BrainDashboard()
        assert dashboard.pool is None

    def test_init_with_pool(self):
        """プールありで初期化"""
        mock_pool = MagicMock()
        dashboard = BrainDashboard(pool=mock_pool)
        assert dashboard.pool == mock_pool


class TestBrainDashboardGetDailyMetrics:
    """get_daily_metrics()のテスト"""

    @pytest.mark.asyncio
    async def test_returns_empty_metrics_without_pool(self):
        """プールがない場合は空のメトリクス"""
        dashboard = BrainDashboard(pool=None)
        result = await dashboard.get_daily_metrics("org-1")
        assert result.organization_id == "org-1"
        assert result.total_conversations == 0

    @pytest.mark.asyncio
    async def test_uses_today_as_default_date(self):
        """デフォルトは今日"""
        dashboard = BrainDashboard(pool=None)
        result = await dashboard.get_daily_metrics("org-1")
        assert result.metric_date == date.today()

    @pytest.mark.asyncio
    async def test_uses_specified_date(self):
        """指定した日付を使用"""
        dashboard = BrainDashboard(pool=None)
        target_date = date(2026, 1, 15)
        result = await dashboard.get_daily_metrics("org-1", target_date=target_date)
        assert result.metric_date == target_date

    @pytest.mark.asyncio
    async def test_fetches_from_daily_metrics_table(self):
        """日次メトリクステーブルから取得"""
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value={
            'total_conversations': 100,
            'unique_users': 50,
            'avg_response_time_ms': 2000,
            'p50_response_time_ms': 1500,
            'p95_response_time_ms': 4000,
            'p99_response_time_ms': 8000,
            'max_response_time_ms': 10000,
            'avg_confidence': Decimal("0.85"),
            'min_confidence': Decimal("0.50"),
            'tool_call_count': 60,
            'text_response_count': 30,
            'clarification_count': 10,
            'allow_count': 80,
            'confirm_count': 15,
            'block_count': 5,
            'success_count': 95,
            'error_count': 5,
            'total_input_tokens': 50000,
            'total_output_tokens': 25000,
            'total_cost_yen': Decimal("3000"),
            'slow_request_count': 2,
        })

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_conn), __aexit__=AsyncMock()))

        dashboard = BrainDashboard(pool=mock_pool)
        result = await dashboard.get_daily_metrics("org-1")

        assert result.total_conversations == 100
        assert result.unique_users == 50
        assert result.avg_response_time_ms == 2000

    @pytest.mark.asyncio
    async def test_handles_db_error(self):
        """DBエラー時は空のメトリクス"""
        # プールのacquire()が例外を投げる場合
        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(side_effect=Exception("Connection error"))

        dashboard = BrainDashboard(pool=mock_pool)
        result = await dashboard.get_daily_metrics("org-1")

        # エラー時は空のメトリクスを返す
        assert result.total_conversations == 0
        assert result.organization_id == "org-1"


class TestBrainDashboardGetWeeklySummary:
    """get_weekly_summary()のテスト"""

    @pytest.mark.asyncio
    async def test_returns_error_without_pool(self):
        """プールがない場合はエラー"""
        dashboard = BrainDashboard(pool=None)
        result = await dashboard.get_weekly_summary("org-1")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_calculates_date_range(self):
        """日付範囲を計算"""
        dashboard = BrainDashboard(pool=None)
        end_date = date(2026, 2, 7)
        result = await dashboard.get_weekly_summary("org-1", end_date=end_date)
        assert result["end_date"] == "2026-02-07"
        assert result["start_date"] == "2026-02-01"

    @pytest.mark.asyncio
    async def test_fetches_weekly_data(self):
        """週次データを取得"""
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value={
            'total_conversations': 700,
            'total_users': 100,
            'avg_response_time_ms': 2000,
            'avg_error_rate': Decimal("2.5"),
            'avg_confirm_rate': Decimal("20.0"),
            'avg_block_rate': Decimal("5.0"),
            'total_cost_yen': Decimal("20000"),
            'days_with_data': 7,
        })

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_conn), __aexit__=AsyncMock()))

        dashboard = BrainDashboard(pool=mock_pool)
        result = await dashboard.get_weekly_summary("org-1")

        assert result["total_conversations"] == 700
        assert result["days_with_data"] == 7


class TestBrainDashboardGetMonthlyCost:
    """get_monthly_cost()のテスト"""

    @pytest.mark.asyncio
    async def test_returns_error_without_pool(self):
        """プールがない場合はエラー"""
        dashboard = BrainDashboard(pool=None)
        result = await dashboard.get_monthly_cost("org-1", 2026, 2)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_fetches_monthly_data(self):
        """月次データを取得"""
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value={
            'total_conversations': 3000,
            'total_input_tokens': 1500000,
            'total_output_tokens': 750000,
            'total_cost_yen': Decimal("90000"),
        })

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_conn), __aexit__=AsyncMock()))

        dashboard = BrainDashboard(pool=mock_pool)
        result = await dashboard.get_monthly_cost("org-1", 2026, 1)

        assert result["total_conversations"] == 3000
        assert result["total_cost_yen"] == 90000.0
        assert result["avg_cost_per_conversation"] == 30.0


# =============================================================================
# create_dashboard() テスト
# =============================================================================


class TestCreateDashboard:
    """create_dashboard()のテスト"""

    def test_returns_brain_dashboard(self):
        """BrainDashboardを返す"""
        result = create_dashboard()
        assert isinstance(result, BrainDashboard)

    def test_without_pool(self):
        """プールなしで作成"""
        result = create_dashboard()
        assert result.pool is None

    def test_with_pool(self):
        """プールありで作成"""
        mock_pool = MagicMock()
        result = create_dashboard(pool=mock_pool)
        assert result.pool == mock_pool
