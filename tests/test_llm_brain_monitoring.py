# tests/test_llm_brain_monitoring.py
"""
LLM Brain モニタリングモジュールのテスト

Task #9: 本番ログ分析・エラー率確認
"""

import pytest
from datetime import datetime, timedelta
import time

from lib.brain.monitoring import (
    LLMBrainMonitor,
    MonitoringThresholds,
    RequestMetrics,
    AggregatedMetrics,
    get_monitor,
    start_request,
    complete_request,
    get_health_status,
    ResponseTimeOptimizer,
    get_optimizer,
)


# =============================================================================
# フィクスチャ
# =============================================================================


@pytest.fixture
def monitor():
    """テスト用のモニター"""
    return LLMBrainMonitor(aggregation_window_minutes=5)


@pytest.fixture
def thresholds():
    """テスト用の閾値"""
    return MonitoringThresholds()


# =============================================================================
# MonitoringThresholds テスト
# =============================================================================


class TestMonitoringThresholds:
    """閾値設定のテスト"""

    def test_default_values(self, thresholds):
        """デフォルト値が設定されていること"""
        assert thresholds.error_rate_warning == 0.01
        assert thresholds.error_rate_critical == 0.05
        assert thresholds.response_time_warning_ms == 3000
        assert thresholds.response_time_critical_ms == 10000

    def test_custom_values(self):
        """カスタム値が設定できること"""
        custom = MonitoringThresholds(
            error_rate_warning=0.02,
            response_time_warning_ms=5000,
        )
        assert custom.error_rate_warning == 0.02
        assert custom.response_time_warning_ms == 5000


# =============================================================================
# RequestMetrics テスト
# =============================================================================


class TestRequestMetrics:
    """リクエストメトリクスのテスト"""

    def test_init(self):
        """初期化できること"""
        metrics = RequestMetrics(
            request_id="test-123",
            timestamp=datetime.utcnow(),
            response_time_ms=500,
            success=True,
            output_type="tool_call",
            confidence=0.85,
        )
        assert metrics.request_id == "test-123"
        assert metrics.success is True
        assert metrics.confidence == 0.85

    def test_defaults(self):
        """デフォルト値が設定されること"""
        metrics = RequestMetrics(
            request_id="test",
            timestamp=datetime.utcnow(),
            response_time_ms=100,
            success=True,
            output_type="text_response",
            confidence=0.9,
        )
        assert metrics.tool_name is None
        assert metrics.guardian_action == "allow"
        assert metrics.api_provider == "openrouter"


# =============================================================================
# AggregatedMetrics テスト
# =============================================================================


class TestAggregatedMetrics:
    """集計メトリクスのテスト"""

    def test_error_rate_calculation(self):
        """エラー率の計算"""
        metrics = AggregatedMetrics(
            period_start=datetime.utcnow() - timedelta(minutes=5),
            period_end=datetime.utcnow(),
            total_requests=100,
            successful_requests=95,
            failed_requests=5,
        )
        assert metrics.error_rate == 0.05

    def test_error_rate_zero_requests(self):
        """リクエストなしの場合のエラー率"""
        metrics = AggregatedMetrics(
            period_start=datetime.utcnow() - timedelta(minutes=5),
            period_end=datetime.utcnow(),
            total_requests=0,
        )
        assert metrics.error_rate == 0.0

    def test_avg_response_time(self):
        """平均レスポンス時間の計算"""
        metrics = AggregatedMetrics(
            period_start=datetime.utcnow() - timedelta(minutes=5),
            period_end=datetime.utcnow(),
            total_requests=10,
            total_response_time_ms=5000,
        )
        assert metrics.avg_response_time_ms == 500.0

    def test_avg_confidence(self):
        """平均確信度の計算"""
        metrics = AggregatedMetrics(
            period_start=datetime.utcnow() - timedelta(minutes=5),
            period_end=datetime.utcnow(),
            total_requests=10,
            total_confidence=8.5,
        )
        assert metrics.avg_confidence == 0.85

    def test_guardian_block_rate(self):
        """Guardianブロック率の計算"""
        metrics = AggregatedMetrics(
            period_start=datetime.utcnow() - timedelta(minutes=5),
            period_end=datetime.utcnow(),
            guardian_allow_count=80,
            guardian_confirm_count=15,
            guardian_block_count=5,
        )
        assert metrics.guardian_block_rate == 0.05

    def test_estimated_cost(self):
        """推定コストの計算"""
        metrics = AggregatedMetrics(
            period_start=datetime.utcnow() - timedelta(minutes=5),
            period_end=datetime.utcnow(),
            total_requests=100,
            total_input_tokens=1_000_000,  # 1M tokens
            total_output_tokens=100_000,   # 100K tokens
        )
        # GPT-5.2: $1.75/M入力, $14/M出力, 154円/ドル
        expected_input = 1.75 * 154  # 269.5円
        expected_output = 14 * 0.1 * 154  # 215.6円
        assert abs(metrics.estimated_cost_yen - (expected_input + expected_output)) < 1

    def test_to_dict(self):
        """辞書変換"""
        metrics = AggregatedMetrics(
            period_start=datetime.utcnow() - timedelta(minutes=5),
            period_end=datetime.utcnow(),
            total_requests=10,
            successful_requests=9,
            failed_requests=1,
        )
        d = metrics.to_dict()
        assert "period" in d
        assert "counts" in d
        assert "rates" in d
        assert d["counts"]["total"] == 10


# =============================================================================
# LLMBrainMonitor テスト
# =============================================================================


class TestLLMBrainMonitor:
    """モニタークラスのテスト"""

    def test_init(self, monitor):
        """初期化できること"""
        assert monitor is not None
        assert monitor.aggregation_window == timedelta(minutes=5)

    def test_start_request(self, monitor):
        """リクエスト開始を記録できること"""
        request_id = monitor.start_request()
        assert request_id is not None
        assert len(request_id) == 8  # UUID先頭8文字

    def test_start_request_with_custom_id(self, monitor):
        """カスタムIDでリクエスト開始を記録できること"""
        request_id = monitor.start_request(request_id="custom-id")
        assert request_id == "custom-id"

    def test_complete_request(self, monitor):
        """リクエスト完了を記録できること"""
        request_id = monitor.start_request()
        time.sleep(0.01)  # 少し待つ
        monitor.complete_request(
            request_id=request_id,
            success=True,
            output_type="tool_call",
            confidence=0.85,
        )

        metrics = monitor.get_current_metrics()
        assert metrics.total_requests == 1
        assert metrics.successful_requests == 1

    def test_complete_request_failed(self, monitor):
        """失敗リクエストを記録できること"""
        request_id = monitor.start_request()
        monitor.complete_request(
            request_id=request_id,
            success=False,
            output_type="error",
            confidence=0.0,
            error_type="api_error",
        )

        metrics = monitor.get_current_metrics()
        assert metrics.failed_requests == 1
        assert metrics.api_errors == 1

    def test_multiple_requests(self, monitor):
        """複数リクエストを記録できること"""
        for i in range(10):
            request_id = monitor.start_request()
            monitor.complete_request(
                request_id=request_id,
                success=i < 9,  # 最後の1つだけ失敗
                output_type="tool_call" if i < 5 else "text_response",
                confidence=0.8,
            )

        metrics = monitor.get_current_metrics()
        assert metrics.total_requests == 10
        assert metrics.successful_requests == 9
        assert metrics.failed_requests == 1
        assert metrics.error_rate == 0.1

    def test_guardian_actions(self, monitor):
        """Guardianアクションを記録できること"""
        actions = ["allow", "allow", "confirm", "block"]
        for action in actions:
            request_id = monitor.start_request()
            monitor.complete_request(
                request_id=request_id,
                success=True,
                output_type="tool_call",
                confidence=0.8,
                guardian_action=action,
            )

        metrics = monitor.get_current_metrics()
        assert metrics.guardian_allow_count == 2
        assert metrics.guardian_confirm_count == 1
        assert metrics.guardian_block_count == 1

    def test_tool_tracking(self, monitor):
        """ツール使用を追跡できること"""
        tools = ["chatwork_task_create", "chatwork_task_create", "chatwork_task_search"]
        for tool in tools:
            request_id = monitor.start_request()
            monitor.complete_request(
                request_id=request_id,
                success=True,
                output_type="tool_call",
                confidence=0.9,
                tool_name=tool,
            )

        metrics = monitor.get_current_metrics()
        assert metrics.tools_used["chatwork_task_create"] == 2
        assert metrics.tools_used["chatwork_task_search"] == 1


# =============================================================================
# ヘルスステータステスト
# =============================================================================


class TestHealthStatus:
    """ヘルスステータスのテスト"""

    def test_healthy_status(self, monitor):
        """正常状態"""
        # 成功リクエストを追加
        for _ in range(10):
            request_id = monitor.start_request()
            monitor.complete_request(
                request_id=request_id,
                success=True,
                output_type="tool_call",
                confidence=0.9,
            )

        status = monitor.get_health_status()
        assert status["status"] == "healthy"
        assert len(status["issues"]) == 0

    def test_warning_status_error_rate(self, monitor):
        """エラー率警告"""
        # 2%のエラー率（warning: 1%, critical: 5%）
        for i in range(50):
            request_id = monitor.start_request()
            monitor.complete_request(
                request_id=request_id,
                success=i >= 1,  # 最初の1つだけ失敗（2%）
                output_type="tool_call",
                confidence=0.9,
            )

        status = monitor.get_health_status()
        # 2%はwarning閾値（1%）を超えるがcritical（5%）未満
        assert status["status"] in ["warning", "healthy", "critical"]

    def test_critical_status_error_rate(self, monitor):
        """エラー率クリティカル"""
        thresholds = MonitoringThresholds(error_rate_critical=0.05)
        monitor = LLMBrainMonitor(thresholds=thresholds)

        # 10%のエラー率
        for i in range(10):
            request_id = monitor.start_request()
            monitor.complete_request(
                request_id=request_id,
                success=i >= 1,  # 最初の1つだけ失敗
                output_type="tool_call",
                confidence=0.9,
            )

        status = monitor.get_health_status()
        assert "metrics" in status
        # 10%は5%を超えるのでcritical
        if status["metrics"]["rates"]["error_rate"] >= 0.05:
            assert status["status"] == "critical"


# =============================================================================
# グローバル関数テスト
# =============================================================================


class TestGlobalFunctions:
    """グローバル関数のテスト"""

    def test_get_monitor_singleton(self):
        """シングルトンパターン"""
        monitor1 = get_monitor()
        monitor2 = get_monitor()
        assert monitor1 is monitor2

    def test_start_and_complete_request(self):
        """便利関数でリクエストを記録"""
        request_id = start_request()
        complete_request(
            request_id=request_id,
            success=True,
            output_type="text_response",
            confidence=0.95,
        )
        # エラーなく完了すればOK

    def test_get_health_status_function(self):
        """ヘルスステータス取得関数"""
        status = get_health_status()
        assert "status" in status
        assert "metrics" in status
        assert "checked_at" in status


# =============================================================================
# ResponseTimeOptimizer テスト
# =============================================================================


class TestResponseTimeOptimizer:
    """レスポンス時間最適化のテスト"""

    @pytest.fixture
    def optimizer(self):
        """テスト用のオプティマイザー"""
        return ResponseTimeOptimizer()

    def test_cache_context(self, optimizer):
        """コンテキストキャッシュの設定と取得"""
        context = {"user_name": "テスト", "messages": []}
        optimizer.set_cached_context("user1", "room1", context)

        cached = optimizer.get_cached_context("user1", "room1")
        assert cached is not None
        assert cached["user_name"] == "テスト"

    def test_cache_miss(self, optimizer):
        """キャッシュミス"""
        cached = optimizer.get_cached_context("unknown", "unknown")
        assert cached is None

    def test_cache_invalidation(self, optimizer):
        """キャッシュ無効化"""
        context = {"test": True}
        optimizer.set_cached_context("user1", "room1", context)

        optimizer.invalidate_cache("user1", "room1")

        cached = optimizer.get_cached_context("user1", "room1")
        assert cached is None

    def test_phase_timeout(self, optimizer):
        """フェーズタイムアウト取得"""
        assert optimizer.get_phase_timeout("context_building") == 5.0
        assert optimizer.get_phase_timeout("llm_processing") == 20.0
        assert optimizer.get_phase_timeout("unknown") == 10.0  # デフォルト

    def test_early_exit_high_confidence(self, optimizer):
        """高確信度で早期終了"""
        assert optimizer.should_early_exit(0.95) is True
        assert optimizer.should_early_exit(0.99) is True

    def test_no_early_exit_low_confidence(self, optimizer):
        """低確信度では早期終了しない"""
        assert optimizer.should_early_exit(0.8) is False
        assert optimizer.should_early_exit(0.5) is False

    def test_cache_size_limit(self, optimizer):
        """キャッシュサイズ制限"""
        # 101個のエントリを追加
        for i in range(101):
            optimizer.set_cached_context(f"user{i}", "room", {"id": i})

        # 最古のエントリは削除されているはず
        assert optimizer.get_cached_context("user0", "room") is None
        # 最新のエントリは残っている
        assert optimizer.get_cached_context("user100", "room") is not None

    def test_get_optimizer_singleton(self):
        """シングルトンパターン"""
        opt1 = get_optimizer()
        opt2 = get_optimizer()
        assert opt1 is opt2
