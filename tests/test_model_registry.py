"""
lib/brain/model_orchestrator/registry.py のテスト
"""

from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from lib.brain.model_orchestrator.registry import ModelRegistry, ModelInfo
from lib.brain.model_orchestrator.constants import Tier, DEFAULT_USD_TO_JPY_RATE


class TestModelInfo:
    """ModelInfoのテスト"""

    @pytest.fixture
    def model_info(self):
        """テスト用ModelInfo"""
        return ModelInfo(
            id=uuid4(),
            model_id="anthropic/claude-opus-4-5-20251101",
            provider="anthropic",
            display_name="Claude Opus 4.5",
            tier=Tier.PREMIUM,
            capabilities=["text", "vision", "code"],
            input_cost_per_1m_usd=Decimal("15.00"),
            output_cost_per_1m_usd=Decimal("75.00"),
            max_context_tokens=200000,
            max_output_tokens=4096,
            fallback_priority=1,
            is_active=True,
            is_default_for_tier=True,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

    def test_calculate_cost_jpy_basic(self, model_info):
        """コスト計算の基本テスト"""
        cost = model_info.calculate_cost_jpy(
            input_tokens=1000,
            output_tokens=500,
        )
        # input: 1000/1M * 15 = 0.015 USD
        # output: 500/1M * 75 = 0.0375 USD
        # total: 0.0525 USD * 150 = 7.875 JPY
        expected = (Decimal("0.015") + Decimal("0.0375")) * DEFAULT_USD_TO_JPY_RATE
        assert cost == expected

    def test_calculate_cost_jpy_custom_rate(self, model_info):
        """カスタム為替レートでのコスト計算テスト"""
        custom_rate = Decimal("160.00")
        cost = model_info.calculate_cost_jpy(
            input_tokens=1000000,
            output_tokens=1000000,
            usd_to_jpy_rate=custom_rate,
        )
        # input: 1M/1M * 15 = 15 USD
        # output: 1M/1M * 75 = 75 USD
        # total: 90 USD * 160 = 14400 JPY
        expected = Decimal("90.00") * custom_rate
        assert cost == expected

    def test_calculate_cost_jpy_zero_tokens(self, model_info):
        """トークン0のコスト計算テスト"""
        cost = model_info.calculate_cost_jpy(input_tokens=0, output_tokens=0)
        assert cost == Decimal("0")


class TestModelRegistry:
    """ModelRegistryのテスト"""

    @pytest.fixture
    def mock_pool(self):
        """DBプールのモック"""
        pool = MagicMock()
        return pool

    @pytest.fixture
    def registry(self, mock_pool):
        """テスト対象のRegistry"""
        return ModelRegistry(mock_pool)

    @pytest.fixture
    def sample_row(self):
        """サンプルDBレコード"""
        return (
            uuid4(),  # id
            "openai/gpt-5.2",  # model_id
            "openai",  # provider
            "GPT-5.2",  # display_name
            "premium",  # tier
            ["text", "vision"],  # capabilities
            Decimal("10.00"),  # input_cost
            Decimal("30.00"),  # output_cost
            128000,  # max_context
            4096,  # max_output
            1,  # fallback_priority
            True,  # is_active
            True,  # is_default_for_tier
            datetime.now(),  # created_at
            datetime.now(),  # updated_at
        )

    # =========================================================================
    # キャッシュ管理
    # =========================================================================

    def test_is_cache_valid_no_timestamp(self, registry):
        """キャッシュタイムスタンプがない場合は無効"""
        assert registry._is_cache_valid() is False

    def test_is_cache_valid_fresh(self, registry):
        """キャッシュが新しい場合は有効"""
        registry._cache_timestamp = datetime.now()
        assert registry._is_cache_valid() is True

    def test_is_cache_valid_expired(self, registry):
        """キャッシュが古い場合は無効"""
        registry._cache_timestamp = datetime.now() - timedelta(seconds=ModelRegistry.CACHE_TTL_SECONDS + 10)
        assert registry._is_cache_valid() is False

    def test_invalidate_cache(self, registry):
        """キャッシュ無効化テスト"""
        registry._cache = {"key": "value"}
        registry._cache_timestamp = datetime.now()

        registry._invalidate_cache()

        assert registry._cache == {}
        assert registry._cache_timestamp is None

    def test_refresh_cache(self, registry, mock_pool, sample_row):
        """キャッシュリフレッシュテスト"""
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [sample_row]
        mock_conn.execute.return_value = mock_result

        registry._cache = {"old": "data"}
        registry._cache_timestamp = datetime.now()

        registry.refresh_cache()

        assert "old" not in registry._cache
        assert "all_models" in registry._cache

    # =========================================================================
    # get_all_models
    # =========================================================================

    def test_get_all_models_from_db(self, registry, mock_pool, sample_row):
        """DBからモデル一覧取得テスト"""
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [sample_row]
        mock_conn.execute.return_value = mock_result

        models = registry.get_all_models()

        assert len(models) == 1
        assert models[0].model_id == "openai/gpt-5.2"

    def test_get_all_models_from_cache(self, registry):
        """キャッシュからモデル一覧取得テスト"""
        cached_models = [MagicMock()]
        registry._cache = {"all_models": cached_models}
        registry._cache_timestamp = datetime.now()

        models = registry.get_all_models()

        assert models == cached_models

    def test_get_all_models_error(self, registry, mock_pool):
        """エラー発生時のテスト"""
        mock_pool.connect.return_value.__enter__ = MagicMock(side_effect=Exception("DB Error"))

        with pytest.raises(Exception):
            registry.get_all_models()

    # =========================================================================
    # get_model
    # =========================================================================

    def test_get_model_found(self, registry, mock_pool, sample_row):
        """モデル取得成功テスト"""
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)
        mock_result = MagicMock()
        mock_result.fetchone.return_value = sample_row
        mock_conn.execute.return_value = mock_result

        model = registry.get_model("openai/gpt-5.2")

        assert model is not None
        assert model.model_id == "openai/gpt-5.2"

    def test_get_model_not_found(self, registry, mock_pool):
        """モデルが見つからない場合のテスト"""
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_conn.execute.return_value = mock_result

        model = registry.get_model("nonexistent/model")

        assert model is None

    def test_get_model_from_cache(self, registry):
        """キャッシュからモデル取得テスト"""
        cached_model = MagicMock()
        registry._cache = {"model:test/model": cached_model}
        registry._cache_timestamp = datetime.now()

        model = registry.get_model("test/model")

        assert model == cached_model

    # =========================================================================
    # get_models_by_tier
    # =========================================================================

    def test_get_models_by_tier(self, registry, mock_pool, sample_row):
        """ティア別モデル取得テスト"""
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [sample_row]
        mock_conn.execute.return_value = mock_result

        models = registry.get_models_by_tier(Tier.PREMIUM)

        assert len(models) == 1

    def test_get_models_by_tier_from_cache(self, registry):
        """キャッシュからティア別モデル取得テスト"""
        cached_models = [MagicMock()]
        registry._cache = {"tier:premium": cached_models}
        registry._cache_timestamp = datetime.now()

        models = registry.get_models_by_tier(Tier.PREMIUM)

        assert models == cached_models

    # =========================================================================
    # get_default_model_for_tier
    # =========================================================================

    def test_get_default_model_for_tier_found(self, registry, mock_pool, sample_row):
        """デフォルトモデル取得成功テスト"""
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)
        mock_result = MagicMock()
        mock_result.fetchone.return_value = sample_row
        mock_conn.execute.return_value = mock_result

        model = registry.get_default_model_for_tier(Tier.PREMIUM)

        assert model is not None

    def test_get_default_model_for_tier_fallback(self, registry, mock_pool, sample_row):
        """デフォルトがない場合のフォールバックテスト"""
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_result.fetchall.return_value = [sample_row]
        mock_conn.execute.return_value = mock_result

        with patch.object(registry, "get_models_by_tier") as mock_get_by_tier:
            mock_model = MagicMock()
            mock_get_by_tier.return_value = [mock_model]

            model = registry.get_default_model_for_tier(Tier.PREMIUM)

        assert model == mock_model

    def test_get_default_model_for_tier_from_cache(self, registry):
        """キャッシュからデフォルトモデル取得テスト"""
        cached_model = MagicMock()
        registry._cache = {"default:premium": cached_model}
        registry._cache_timestamp = datetime.now()

        model = registry.get_default_model_for_tier(Tier.PREMIUM)

        assert model == cached_model

    # =========================================================================
    # get_fallback_chain
    # =========================================================================

    def test_get_fallback_chain_premium(self, registry):
        """プレミアムティアのフォールバックチェーンテスト"""
        premium_models = [MagicMock(tier=Tier.PREMIUM)]
        standard_models = [MagicMock(tier=Tier.STANDARD)]
        economy_models = [MagicMock(tier=Tier.ECONOMY)]

        with patch.object(registry, "get_models_by_tier") as mock_get:
            mock_get.side_effect = [premium_models, standard_models, economy_models]

            chain = registry.get_fallback_chain(Tier.PREMIUM)

        assert len(chain) == 3
        assert mock_get.call_count == 3

    def test_get_fallback_chain_standard(self, registry):
        """スタンダードティアのフォールバックチェーンテスト"""
        standard_models = [MagicMock(tier=Tier.STANDARD)]
        economy_models = [MagicMock(tier=Tier.ECONOMY)]

        with patch.object(registry, "get_models_by_tier") as mock_get:
            mock_get.side_effect = [standard_models, economy_models]

            chain = registry.get_fallback_chain(Tier.STANDARD)

        assert len(chain) == 2

    def test_get_fallback_chain_economy(self, registry):
        """エコノミーティアのフォールバックチェーンテスト"""
        economy_models = [MagicMock(tier=Tier.ECONOMY)]

        with patch.object(registry, "get_models_by_tier") as mock_get:
            mock_get.return_value = economy_models

            chain = registry.get_fallback_chain(Tier.ECONOMY)

        assert len(chain) == 1

    # =========================================================================
    # _row_to_model_info
    # =========================================================================

    def test_row_to_model_info(self, registry, sample_row):
        """DBレコードからModelInfo変換テスト"""
        model = registry._row_to_model_info(sample_row)

        assert model.model_id == "openai/gpt-5.2"
        assert model.provider == "openai"
        assert model.tier == Tier.PREMIUM
        assert model.capabilities == ["text", "vision"]

    def test_row_to_model_info_json_capabilities(self, registry):
        """capabilitiesがJSON文字列の場合のテスト"""
        row = (
            uuid4(),
            "test/model",
            "test",
            "Test Model",
            "standard",
            '["text", "code"]',  # JSON文字列
            Decimal("5.00"),
            Decimal("15.00"),
            64000,
            4096,
            1,
            True,
            False,
            datetime.now(),
            datetime.now(),
        )

        model = registry._row_to_model_info(row)

        assert model.capabilities == ["text", "code"]

    def test_row_to_model_info_null_values(self, registry):
        """NULL値がある場合のテスト"""
        row = (
            uuid4(),
            "test/model",
            "test",
            "Test Model",
            "economy",
            ["text"],
            Decimal("1.00"),
            Decimal("3.00"),
            None,  # max_context_tokens
            None,  # max_output_tokens
            None,  # fallback_priority
            True,
            False,
            datetime.now(),
            datetime.now(),
        )

        model = registry._row_to_model_info(row)

        assert model.max_context_tokens == 128000  # デフォルト値
        assert model.max_output_tokens == 4096  # デフォルト値
        assert model.fallback_priority == 100  # デフォルト値

    # =========================================================================
    # get_model_stats
    # =========================================================================

    def test_get_model_stats(self, registry):
        """モデル統計取得テスト"""
        mock_models = [
            MagicMock(tier=Tier.PREMIUM, provider="anthropic"),
            MagicMock(tier=Tier.PREMIUM, provider="openai"),
            MagicMock(tier=Tier.STANDARD, provider="openai"),
        ]

        with patch.object(registry, "get_all_models", return_value=mock_models):
            stats = registry.get_model_stats()

        assert stats["total_models"] == 3
        assert stats["by_tier"]["premium"] == 2
        assert stats["by_tier"]["standard"] == 1
        assert stats["by_provider"]["anthropic"] == 1
        assert stats["by_provider"]["openai"] == 2

    def test_get_model_stats_empty(self, registry):
        """モデルがない場合の統計テスト"""
        with patch.object(registry, "get_all_models", return_value=[]):
            stats = registry.get_model_stats()

        assert stats["total_models"] == 0
        assert stats["by_tier"] == {}
        assert stats["by_provider"] == {}
