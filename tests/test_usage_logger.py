"""
lib/brain/model_orchestrator/usage_logger.py のテスト
"""

from datetime import datetime, date, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from lib.brain.model_orchestrator.usage_logger import (
    UsageLogger,
    UsageLogEntry,
    UsageStats,
)
from lib.brain.model_orchestrator.constants import Tier


class TestUsageLogEntry:
    """UsageLogEntryのテスト"""

    def test_create_entry(self):
        """エントリ作成テスト"""
        entry_id = uuid4()
        entry = UsageLogEntry(
            id=entry_id,
            organization_id="org-123",
            model_id="openai/gpt-5.2",
            task_type="chat",
            tier="premium",
            input_tokens=100,
            output_tokens=50,
            cost_jpy=Decimal("1.5"),
            room_id="room-456",
            user_id="user-789",
            latency_ms=250,
            was_fallback=False,
            original_model_id=None,
            fallback_reason=None,
            fallback_attempt=0,
            success=True,
            error_message=None,
            created_at=datetime.now(),
        )

        assert entry.id == entry_id
        assert entry.organization_id == "org-123"
        assert entry.model_id == "openai/gpt-5.2"
        assert entry.input_tokens == 100
        assert entry.output_tokens == 50
        assert entry.success is True

    def test_create_fallback_entry(self):
        """フォールバックエントリ作成テスト"""
        entry = UsageLogEntry(
            id=uuid4(),
            organization_id="org-123",
            model_id="openai/gpt-4o",
            task_type="chat",
            tier="standard",
            input_tokens=100,
            output_tokens=50,
            cost_jpy=Decimal("0.5"),
            room_id=None,
            user_id=None,
            latency_ms=500,
            was_fallback=True,
            original_model_id="openai/gpt-5.2",
            fallback_reason="rate_limit",
            fallback_attempt=1,
            success=True,
            error_message=None,
            created_at=datetime.now(),
        )

        assert entry.was_fallback is True
        assert entry.original_model_id == "openai/gpt-5.2"
        assert entry.fallback_reason == "rate_limit"

    def test_create_error_entry(self):
        """エラーエントリ作成テスト"""
        entry = UsageLogEntry(
            id=uuid4(),
            organization_id="org-123",
            model_id="openai/gpt-5.2",
            task_type="chat",
            tier="premium",
            input_tokens=100,
            output_tokens=0,
            cost_jpy=Decimal("0"),
            room_id=None,
            user_id=None,
            latency_ms=100,
            was_fallback=False,
            original_model_id=None,
            fallback_reason=None,
            fallback_attempt=0,
            success=False,
            error_message="API timeout",
            created_at=datetime.now(),
        )

        assert entry.success is False
        assert entry.error_message == "API timeout"


class TestUsageStats:
    """UsageStatsのテスト"""

    def test_create_stats(self):
        """統計作成テスト"""
        stats = UsageStats(
            total_requests=100,
            total_cost_jpy=Decimal("150.5"),
            total_input_tokens=10000,
            total_output_tokens=5000,
            success_rate=0.95,
            average_latency_ms=250.5,
            by_tier={"premium": 30, "standard": 50, "economy": 20},
            by_model={"openai/gpt-5.2": 30, "openai/gpt-4o": 70},
            by_task_type={"chat": 80, "analysis": 20},
        )

        assert stats.total_requests == 100
        assert stats.total_cost_jpy == Decimal("150.5")
        assert stats.success_rate == 0.95
        assert stats.by_tier["premium"] == 30

    def test_empty_stats(self):
        """空の統計テスト"""
        stats = UsageStats(
            total_requests=0,
            total_cost_jpy=Decimal("0"),
            total_input_tokens=0,
            total_output_tokens=0,
            success_rate=0.0,
            average_latency_ms=0.0,
            by_tier={},
            by_model={},
            by_task_type={},
        )

        assert stats.total_requests == 0
        assert stats.by_tier == {}


class TestUsageLogger:
    """UsageLoggerのテスト"""

    @pytest.fixture
    def mock_pool(self):
        """DBプールのモック"""
        pool = MagicMock()
        return pool

    @pytest.fixture
    def logger(self, mock_pool):
        """テスト対象のLogger"""
        return UsageLogger(mock_pool, "org-test-123")

    # =========================================================================
    # __init__
    # =========================================================================

    def test_init(self, mock_pool):
        """初期化テスト"""
        logger = UsageLogger(mock_pool, "org-456")
        assert logger._pool == mock_pool
        assert logger._organization_id == "org-456"

    # =========================================================================
    # log_usage
    # =========================================================================

    def test_log_usage_success(self, logger, mock_pool):
        """利用ログ記録成功テスト"""
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)

        mock_result = MagicMock()
        mock_result.fetchone.return_value = (uuid4(),)
        mock_conn.execute.return_value = mock_result

        result = logger.log_usage(
            model_id="openai/gpt-5.2",
            task_type="chat",
            tier=Tier.PREMIUM,
            input_tokens=100,
            output_tokens=50,
            cost_jpy=Decimal("1.5"),
            latency_ms=250,
            success=True,
        )

        assert result is not None
        mock_conn.execute.assert_called_once()

    def test_log_usage_with_all_params(self, logger, mock_pool):
        """全パラメータ指定でのログ記録テスト"""
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)

        mock_result = MagicMock()
        mock_result.fetchone.return_value = (uuid4(),)
        mock_conn.execute.return_value = mock_result

        result = logger.log_usage(
            model_id="openai/gpt-4o",
            task_type="analysis",
            tier=Tier.STANDARD,
            input_tokens=500,
            output_tokens=200,
            cost_jpy=Decimal("2.5"),
            latency_ms=800,
            success=True,
            room_id="room-123",
            user_id="user-456",
            was_fallback=True,
            original_model_id="openai/gpt-5.2",
            fallback_reason="rate_limit",
            fallback_attempt=1,
            request_content="Test content",
        )

        assert result is not None

    def test_log_usage_error(self, logger, mock_pool):
        """エラー時のログ記録テスト"""
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)

        mock_result = MagicMock()
        mock_result.fetchone.return_value = (uuid4(),)
        mock_conn.execute.return_value = mock_result

        result = logger.log_usage(
            model_id="openai/gpt-5.2",
            task_type="chat",
            tier=Tier.PREMIUM,
            input_tokens=100,
            output_tokens=0,
            cost_jpy=Decimal("0"),
            latency_ms=100,
            success=False,
            error_message="API error",
        )

        assert result is not None

    def test_log_usage_db_error(self, logger, mock_pool):
        """DB接続エラー時のログ記録テスト"""
        mock_pool.connect.return_value.__enter__ = MagicMock(
            side_effect=Exception("DB connection failed")
        )

        result = logger.log_usage(
            model_id="openai/gpt-5.2",
            task_type="chat",
            tier=Tier.PREMIUM,
            input_tokens=100,
            output_tokens=50,
            cost_jpy=Decimal("1.5"),
            latency_ms=250,
            success=True,
        )

        # エラー時はNoneを返す（エラーをログに記録）
        assert result is None

