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

    # =========================================================================
    # log_usage: UUID parse fallback (lines 216-218)
    # =========================================================================

    def test_log_usage_uuid_parse_value_error_non_uuid_row(self, logger, mock_pool):
        """行216-218: row[0]が不正な文字列でValueError -> isinstance(row[0], UUID)=False -> None"""
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)

        mock_result = MagicMock()
        # row[0]が不正な文字列 -> UUID(str(row[0])) raises ValueError
        mock_result.fetchone.return_value = ("not-a-valid-uuid-string",)
        mock_conn.execute.return_value = mock_result

        result = logger.log_usage(
            model_id="openai/gpt-4o",
            task_type="chat",
            tier=Tier.STANDARD,
            input_tokens=100,
            output_tokens=50,
            cost_jpy=Decimal("1.0"),
            latency_ms=100,
            success=True,
        )
        # ValueError caught -> "not-a-valid-uuid-string" is not UUID -> log_id = None
        assert result is None

    def test_log_usage_uuid_parse_type_error(self, logger, mock_pool):
        """行216-218: row[0]でTypeErrorが発生する場合"""
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)

        mock_result = MagicMock()
        # str() が TypeError を投げるオブジェクトを用意
        bad_obj = MagicMock()
        bad_obj.__str__ = MagicMock(side_effect=TypeError("cannot convert to str"))
        mock_result.fetchone.return_value = (bad_obj,)
        mock_conn.execute.return_value = mock_result

        result = logger.log_usage(
            model_id="openai/gpt-4o",
            task_type="chat",
            tier=Tier.STANDARD,
            input_tokens=100,
            output_tokens=50,
            cost_jpy=Decimal("1.0"),
            latency_ms=100,
            success=True,
        )
        # TypeError caught -> bad_obj is not UUID -> log_id = None
        assert result is None

    def test_log_usage_uuid_parse_fallback_returns_uuid_instance(self, logger, mock_pool):
        """行218: row[0]がすでにUUIDインスタンスだがstr変換でValueError -> isinstance(UUID)=True -> そのまま返す"""
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)

        real_uuid = uuid4()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (real_uuid,)
        mock_conn.execute.return_value = mock_result

        # 通常はUUID(str(real_uuid))は成功するので正常パスを通る
        result = logger.log_usage(
            model_id="openai/gpt-4o",
            task_type="chat",
            tier=Tier.STANDARD,
            input_tokens=100,
            output_tokens=50,
            cost_jpy=Decimal("1.0"),
            latency_ms=100,
            success=True,
        )
        assert result == real_uuid

    def test_log_usage_fetchone_returns_none(self, logger, mock_pool):
        """fetchone が None を返した場合（RETURNINGで行がない場合）"""
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)

        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_conn.execute.return_value = mock_result

        result = logger.log_usage(
            model_id="openai/gpt-4o",
            task_type="chat",
            tier=Tier.STANDARD,
            input_tokens=100,
            output_tokens=50,
            cost_jpy=Decimal("1.0"),
            latency_ms=100,
            success=True,
        )
        assert result is None

    def test_log_usage_without_request_content_no_hash(self, logger, mock_pool):
        """request_content がない場合はハッシュが None"""
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)

        mock_result = MagicMock()
        mock_result.fetchone.return_value = (uuid4(),)
        mock_conn.execute.return_value = mock_result

        logger.log_usage(
            model_id="openai/gpt-4o",
            task_type="chat",
            tier=Tier.STANDARD,
            input_tokens=100,
            output_tokens=50,
            cost_jpy=Decimal("1.0"),
            latency_ms=100,
            success=True,
        )

        call_args = mock_conn.execute.call_args
        params = call_args[0][1]
        assert params["request_hash"] is None

    def test_log_usage_with_request_content_generates_hash(self, logger, mock_pool):
        """request_content が提供されたらハッシュが生成される"""
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)

        mock_result = MagicMock()
        mock_result.fetchone.return_value = (uuid4(),)
        mock_conn.execute.return_value = mock_result

        logger.log_usage(
            model_id="openai/gpt-4o",
            task_type="chat",
            tier=Tier.STANDARD,
            input_tokens=100,
            output_tokens=50,
            cost_jpy=Decimal("1.0"),
            latency_ms=100,
            success=True,
            request_content="test request content",
        )

        call_args = mock_conn.execute.call_args
        params = call_args[0][1]
        assert params["request_hash"] is not None
        assert len(params["request_hash"]) == 64

    # =========================================================================
    # get_daily_stats (lines 245-336)
    # =========================================================================

    def test_get_daily_stats_default_date(self, logger, mock_pool):
        """target_date=None で今日の統計を取得"""
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)

        # 基本統計
        stats_result = MagicMock()
        stats_result.fetchone.return_value = (10, Decimal("50.5"), 1000, 500, 0.9, 150.5)

        # ティア別
        tier_result = MagicMock()
        tier_result.fetchall.return_value = [("standard", 7), ("premium", 3)]

        # モデル別
        model_result = MagicMock()
        model_result.fetchall.return_value = [("gpt-4o", 8), ("o1", 2)]

        # タスクタイプ別
        task_result = MagicMock()
        task_result.fetchall.return_value = [("chat", 6), ("analysis", 4)]

        mock_conn.execute.side_effect = [stats_result, tier_result, model_result, task_result]

        result = logger.get_daily_stats()

        assert isinstance(result, UsageStats)
        assert result.total_requests == 10
        assert result.total_cost_jpy == Decimal("50.5")
        assert result.total_input_tokens == 1000
        assert result.total_output_tokens == 500
        assert result.success_rate == 0.9
        assert result.average_latency_ms == 150.5
        assert result.by_tier == {"standard": 7, "premium": 3}
        assert result.by_model == {"gpt-4o": 8, "o1": 2}
        assert result.by_task_type == {"chat": 6, "analysis": 4}

    def test_get_daily_stats_with_specific_date(self, logger, mock_pool):
        """特定の日付を指定"""
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)

        target = date(2026, 1, 15)

        stats_result = MagicMock()
        stats_result.fetchone.return_value = (5, Decimal("20.0"), 500, 250, 1.0, 100.0)

        tier_result = MagicMock()
        tier_result.fetchall.return_value = [("economy", 5)]

        model_result = MagicMock()
        model_result.fetchall.return_value = [("gpt-4o-mini", 5)]

        task_result = MagicMock()
        task_result.fetchall.return_value = [("simple_qa", 5)]

        mock_conn.execute.side_effect = [stats_result, tier_result, model_result, task_result]

        result = logger.get_daily_stats(target_date=target)

        assert result.total_requests == 5
        first_call_params = mock_conn.execute.call_args_list[0][0][1]
        assert first_call_params["target_date"] == "2026-01-15"

    def test_get_daily_stats_null_values(self, logger, mock_pool):
        """DB値がNull（None）のフォールバック"""
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)

        stats_result = MagicMock()
        stats_result.fetchone.return_value = (0, None, None, None, None, None)

        tier_result = MagicMock()
        tier_result.fetchall.return_value = []

        model_result = MagicMock()
        model_result.fetchall.return_value = []

        task_result = MagicMock()
        task_result.fetchall.return_value = []

        mock_conn.execute.side_effect = [stats_result, tier_result, model_result, task_result]

        result = logger.get_daily_stats(target_date=date(2026, 1, 1))

        assert result.total_requests == 0
        assert result.total_cost_jpy == Decimal("0")
        assert result.total_input_tokens == 0
        assert result.total_output_tokens == 0
        assert result.success_rate == 0.0
        assert result.average_latency_ms == 0.0

    def test_get_daily_stats_stats_row_is_none(self, logger, mock_pool):
        """stats_row が None の場合 ValueError -> catch -> empty stats"""
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)

        stats_result = MagicMock()
        stats_result.fetchone.return_value = None

        tier_result = MagicMock()
        tier_result.fetchall.return_value = []

        model_result = MagicMock()
        model_result.fetchall.return_value = []

        task_result = MagicMock()
        task_result.fetchall.return_value = []

        mock_conn.execute.side_effect = [stats_result, tier_result, model_result, task_result]

        result = logger.get_daily_stats(target_date=date(2026, 1, 1))

        assert result.total_requests == 0
        assert result.total_cost_jpy == Decimal("0")
        assert result.by_tier == {}

    def test_get_daily_stats_db_exception(self, logger, mock_pool):
        """DB例外時はゼロ統計を返す"""
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)

        mock_conn.execute.side_effect = Exception("DB error")

        result = logger.get_daily_stats(target_date=date(2026, 1, 1))

        assert result.total_requests == 0
        assert result.total_cost_jpy == Decimal("0")
        assert result.by_tier == {}
        assert result.by_model == {}
        assert result.by_task_type == {}

    def test_get_daily_stats_multiple_tiers_and_models(self, logger, mock_pool):
        """複数ティア、モデル、タスクタイプがある場合"""
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)

        stats_result = MagicMock()
        stats_result.fetchone.return_value = (20, Decimal("100.0"), 2000, 1000, 0.85, 200.0)

        tier_result = MagicMock()
        tier_result.fetchall.return_value = [("economy", 5), ("standard", 10), ("premium", 5)]

        model_result = MagicMock()
        model_result.fetchall.return_value = [("gpt-4o", 10), ("gpt-4o-mini", 5), ("o1", 5)]

        task_result = MagicMock()
        task_result.fetchall.return_value = [("chat", 10), ("analysis", 5), ("coding", 5)]

        mock_conn.execute.side_effect = [stats_result, tier_result, model_result, task_result]

        result = logger.get_daily_stats(target_date=date(2026, 2, 1))

        assert result.total_requests == 20
        assert len(result.by_tier) == 3
        assert result.by_tier["economy"] == 5
        assert len(result.by_model) == 3
        assert len(result.by_task_type) == 3

    # =========================================================================
    # get_recent_logs (lines 363-426)
    # =========================================================================

    def test_get_recent_logs_default_params(self, logger, mock_pool):
        """デフォルトパラメータでログ取得"""
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)

        test_uuid = uuid4()
        org_uuid = uuid4()
        now = datetime.now()

        result_mock = MagicMock()
        result_mock.fetchall.return_value = [
            (
                test_uuid, org_uuid, "gpt-4o", "chat", "standard",
                100, 50, Decimal("1.5"), "room-1", "user-1",
                200, False, None, None, 0,
                True, None, now,
            ),
        ]
        mock_conn.execute.return_value = result_mock

        logs = logger.get_recent_logs()

        assert len(logs) == 1
        entry = logs[0]
        assert isinstance(entry, UsageLogEntry)
        assert entry.id == test_uuid
        assert entry.model_id == "gpt-4o"
        assert entry.task_type == "chat"
        assert entry.input_tokens == 100
        assert entry.output_tokens == 50
        assert entry.cost_jpy == Decimal("1.5")
        assert entry.room_id == "room-1"
        assert entry.success is True
        assert entry.created_at == now

    def test_get_recent_logs_success_only_true(self, logger, mock_pool):
        """success_only=True のフィルタリング"""
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)

        result_mock = MagicMock()
        result_mock.fetchall.return_value = []
        mock_conn.execute.return_value = result_mock

        logs = logger.get_recent_logs(success_only=True)

        # SQLに "AND success = TRUE" が含まれる
        call_args = mock_conn.execute.call_args
        query_text = str(call_args[0][0])
        assert "AND success = TRUE" in query_text
        assert logs == []

    def test_get_recent_logs_success_only_false(self, logger, mock_pool):
        """success_only=False の場合フィルタなし"""
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)

        result_mock = MagicMock()
        result_mock.fetchall.return_value = []
        mock_conn.execute.return_value = result_mock

        logger.get_recent_logs(success_only=False)

        call_args = mock_conn.execute.call_args
        query_text = str(call_args[0][0])
        assert "AND success = TRUE" not in query_text

    def test_get_recent_logs_custom_limit(self, logger, mock_pool):
        """limit パラメータ"""
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)

        result_mock = MagicMock()
        result_mock.fetchall.return_value = []
        mock_conn.execute.return_value = result_mock

        logger.get_recent_logs(limit=10)

        call_args = mock_conn.execute.call_args
        params = call_args[0][1]
        assert params["limit"] == 10

    def test_get_recent_logs_multiple_rows(self, logger, mock_pool):
        """複数行のレスポンス"""
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)

        now = datetime.now()
        rows = []
        for i in range(3):
            rows.append((
                uuid4(), uuid4(), f"model-{i}", f"task-{i}", "standard",
                100 + i, 50 + i, Decimal(f"{1.0 + i}"), f"room-{i}", f"user-{i}",
                200 + i, False, None, None, None,
                True, None, now,
            ))

        result_mock = MagicMock()
        result_mock.fetchall.return_value = rows
        mock_conn.execute.return_value = result_mock

        logs = logger.get_recent_logs()

        assert len(logs) == 3
        assert logs[0].model_id == "model-0"
        assert logs[1].model_id == "model-1"
        assert logs[2].model_id == "model-2"
        # fallback_attempt が None の場合は 0
        assert logs[0].fallback_attempt == 0

    def test_get_recent_logs_with_fallback_data(self, logger, mock_pool):
        """フォールバック情報付きのログ"""
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)

        now = datetime.now()
        result_mock = MagicMock()
        result_mock.fetchall.return_value = [
            (
                uuid4(), uuid4(), "gpt-4o", "chat", "standard",
                100, 50, Decimal("1.5"), "room-1", "user-1",
                200, True, "o1", "rate_limit", 2,
                True, None, now,
            ),
        ]
        mock_conn.execute.return_value = result_mock

        logs = logger.get_recent_logs()

        assert logs[0].was_fallback is True
        assert logs[0].original_model_id == "o1"
        assert logs[0].fallback_reason == "rate_limit"
        assert logs[0].fallback_attempt == 2

    def test_get_recent_logs_with_error(self, logger, mock_pool):
        """エラー付きログエントリ"""
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)

        now = datetime.now()
        result_mock = MagicMock()
        result_mock.fetchall.return_value = [
            (
                uuid4(), uuid4(), "gpt-4o", "chat", "standard",
                100, 0, Decimal("0"), None, None,
                100, False, None, None, 0,
                False, "API timeout", now,
            ),
        ]
        mock_conn.execute.return_value = result_mock

        logs = logger.get_recent_logs()

        assert logs[0].success is False
        assert logs[0].error_message == "API timeout"

    def test_get_recent_logs_db_exception(self, logger, mock_pool):
        """DB例外時は空リストを返す"""
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)

        mock_conn.execute.side_effect = Exception("DB error")

        logs = logger.get_recent_logs()

        assert logs == []

    def test_get_recent_logs_empty_result(self, logger, mock_pool):
        """結果なしの場合"""
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)

        result_mock = MagicMock()
        result_mock.fetchall.return_value = []
        mock_conn.execute.return_value = result_mock

        logs = logger.get_recent_logs()

        assert logs == []

    # =========================================================================
    # get_error_summary (lines 442-506)
    # =========================================================================

    def test_get_error_summary_default_days(self, logger, mock_pool):
        """デフォルトの7日間でエラーサマリー取得"""
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)

        model_result = MagicMock()
        model_result.fetchall.return_value = [
            ("gpt-4o", 5, 3),
            ("o1", 2, 1),
        ]

        errors_result = MagicMock()
        errors_result.fetchall.return_value = [
            ("Rate limited", 4),
            ("Timeout", 3),
        ]

        mock_conn.execute.side_effect = [model_result, errors_result]

        result = logger.get_error_summary()

        assert result["period_days"] == 7
        assert len(result["by_model"]) == 2
        assert result["by_model"][0]["model_id"] == "gpt-4o"
        assert result["by_model"][0]["error_count"] == 5
        assert result["by_model"][0]["unique_errors"] == 3
        assert len(result["top_errors"]) == 2
        assert result["top_errors"][0]["message"] == "Rate limited"
        assert result["top_errors"][0]["count"] == 4

    def test_get_error_summary_custom_days(self, logger, mock_pool):
        """カスタム日数"""
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)

        model_result = MagicMock()
        model_result.fetchall.return_value = []

        errors_result = MagicMock()
        errors_result.fetchall.return_value = []

        mock_conn.execute.side_effect = [model_result, errors_result]

        result = logger.get_error_summary(days=30)

        assert result["period_days"] == 30
        first_call_params = mock_conn.execute.call_args_list[0][0][1]
        assert first_call_params["days"] == 30

    def test_get_error_summary_no_errors(self, logger, mock_pool):
        """エラーがない場合"""
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)

        model_result = MagicMock()
        model_result.fetchall.return_value = []

        errors_result = MagicMock()
        errors_result.fetchall.return_value = []

        mock_conn.execute.side_effect = [model_result, errors_result]

        result = logger.get_error_summary()

        assert result["by_model"] == []
        assert result["top_errors"] == []

    def test_get_error_summary_db_exception(self, logger, mock_pool):
        """DB例外時はフォールバック結果を返す"""
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)

        mock_conn.execute.side_effect = Exception("DB error")

        result = logger.get_error_summary()

        assert result["by_model"] == []
        assert result["top_errors"] == []
        assert result["period_days"] == 7

    def test_get_error_summary_db_exception_custom_days(self, logger, mock_pool):
        """DB例外時もperiod_daysが保持される"""
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)

        mock_conn.execute.side_effect = Exception("DB error")

        result = logger.get_error_summary(days=14)

        assert result["period_days"] == 14

    def test_get_error_summary_org_id_passed(self, logger, mock_pool):
        """organization_id がパラメータとして渡される"""
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)

        model_result = MagicMock()
        model_result.fetchall.return_value = []

        errors_result = MagicMock()
        errors_result.fetchall.return_value = []

        mock_conn.execute.side_effect = [model_result, errors_result]

        logger.get_error_summary()

        first_call_params = mock_conn.execute.call_args_list[0][0][1]
        assert first_call_params["org_id"] == "org-test-123"

    # =========================================================================
    # get_fallback_summary (lines 526-564)
    # =========================================================================

    def test_get_fallback_summary_default_days(self, logger, mock_pool):
        """デフォルトの7日間でフォールバックサマリー取得"""
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)

        result_mock = MagicMock()
        result_mock.fetchall.return_value = [
            ("o1", "gpt-4o", 5, 0.8),
            ("gpt-4o", "gpt-4o-mini", 3, 1.0),
        ]
        mock_conn.execute.return_value = result_mock

        result = logger.get_fallback_summary()

        assert result["period_days"] == 7
        assert len(result["fallback_patterns"]) == 2
        assert result["fallback_patterns"][0]["original_model"] == "o1"
        assert result["fallback_patterns"][0]["fallback_model"] == "gpt-4o"
        assert result["fallback_patterns"][0]["count"] == 5
        assert result["fallback_patterns"][0]["success_rate"] == 0.8
        assert result["fallback_patterns"][1]["original_model"] == "gpt-4o"

    def test_get_fallback_summary_custom_days(self, logger, mock_pool):
        """カスタム日数"""
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)

        result_mock = MagicMock()
        result_mock.fetchall.return_value = []
        mock_conn.execute.return_value = result_mock

        result = logger.get_fallback_summary(days=14)

        assert result["period_days"] == 14
        call_params = mock_conn.execute.call_args[0][1]
        assert call_params["days"] == 14

    def test_get_fallback_summary_no_fallbacks(self, logger, mock_pool):
        """フォールバックなし"""
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)

        result_mock = MagicMock()
        result_mock.fetchall.return_value = []
        mock_conn.execute.return_value = result_mock

        result = logger.get_fallback_summary()

        assert result["fallback_patterns"] == []

    def test_get_fallback_summary_null_success_rate(self, logger, mock_pool):
        """success_rate が None の場合"""
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)

        result_mock = MagicMock()
        result_mock.fetchall.return_value = [
            ("o1", "gpt-4o", 1, None),
        ]
        mock_conn.execute.return_value = result_mock

        result = logger.get_fallback_summary()

        assert result["fallback_patterns"][0]["success_rate"] == 0.0

    def test_get_fallback_summary_db_exception(self, logger, mock_pool):
        """DB例外時はフォールバック結果を返す"""
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)

        mock_conn.execute.side_effect = Exception("DB error")

        result = logger.get_fallback_summary()

        assert result["fallback_patterns"] == []
        assert result["period_days"] == 7

    def test_get_fallback_summary_db_exception_custom_days(self, logger, mock_pool):
        """DB例外時もperiod_daysが保持される"""
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)

        mock_conn.execute.side_effect = Exception("DB error")

        result = logger.get_fallback_summary(days=30)

        assert result["period_days"] == 30

    def test_get_fallback_summary_org_id_passed(self, logger, mock_pool):
        """organization_id がパラメータとして渡される"""
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)

        result_mock = MagicMock()
        result_mock.fetchall.return_value = []
        mock_conn.execute.return_value = result_mock

        logger.get_fallback_summary()

        call_params = mock_conn.execute.call_args[0][1]
        assert call_params["org_id"] == "org-test-123"

