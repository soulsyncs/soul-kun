# tests/test_model_orchestrator_coverage.py
"""
ModelSelector / ModelOrchestrator カバレッジ向上テスト

対象:
- lib/brain/model_orchestrator/model_selector.py (未カバー行: 113-118, 125-128, 159-164, 187, 195, 221, 252-268, 281-286, 303-322)
- lib/brain/model_orchestrator/orchestrator.py   (未カバー行: 205, 227-253, 273, 323-327, 356-383, 396, 409)
"""

import os
import pytest
from datetime import datetime
from decimal import Decimal
from unittest.mock import Mock, MagicMock, AsyncMock, patch, PropertyMock
from uuid import uuid4

from lib.brain.model_orchestrator.constants import (
    Tier,
    TASK_TYPE_TIERS,
    DEFAULT_TIER,
    TIER_UPGRADE_KEYWORDS,
    TIER_DOWNGRADE_KEYWORDS,
    FEATURE_FLAG_NAME,
    API_TIMEOUT_SECONDS,
)
from lib.brain.model_orchestrator.registry import ModelRegistry, ModelInfo
from lib.brain.model_orchestrator.model_selector import ModelSelector, ModelSelection
from lib.brain.model_orchestrator.cost_manager import (
    CostManager,
    CostCheckResult,
    CostAction,
    CostEstimate,
)
from lib.brain.model_orchestrator.fallback_manager import (
    FallbackManager,
    FallbackResult,
    FallbackAttempt,
)
from lib.brain.model_orchestrator.usage_logger import UsageLogger
from lib.brain.model_orchestrator.orchestrator import (
    ModelOrchestrator,
    OrchestratorResult,
    OrchestratorConfig,
    create_orchestrator,
)


# =============================================================================
# ヘルパー: テスト用ModelInfo生成
# =============================================================================


def make_model_info(
    model_id: str = "test/model-a",
    tier: Tier = Tier.STANDARD,
    display_name: str = "Test Model A",
    provider: str = "test",
    is_default_for_tier: bool = True,
    is_active: bool = True,
    fallback_priority: int = 1,
    input_cost: str = "10.00",
    output_cost: str = "30.00",
) -> ModelInfo:
    """テスト用ModelInfoを生成する"""
    return ModelInfo(
        id=uuid4(),
        model_id=model_id,
        provider=provider,
        display_name=display_name,
        tier=tier,
        capabilities=["text"],
        input_cost_per_1m_usd=Decimal(input_cost),
        output_cost_per_1m_usd=Decimal(output_cost),
        max_context_tokens=128000,
        max_output_tokens=4096,
        fallback_priority=fallback_priority,
        is_active=is_active,
        is_default_for_tier=is_default_for_tier,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


# =============================================================================
# フィクスチャ
# =============================================================================


@pytest.fixture
def mock_pool():
    """データベース接続プールのモック"""
    pool = Mock()
    conn = MagicMock()
    conn.__enter__ = Mock(return_value=conn)
    conn.__exit__ = Mock(return_value=False)
    pool.connect.return_value = conn
    return pool


@pytest.fixture
def mock_registry():
    """ModelRegistryのモック"""
    registry = Mock(spec=ModelRegistry)
    return registry


@pytest.fixture
def selector(mock_registry):
    """ModelSelectorインスタンス"""
    return ModelSelector(mock_registry)


@pytest.fixture
def standard_model():
    return make_model_info(
        model_id="test/standard-model",
        tier=Tier.STANDARD,
        display_name="Standard Model",
    )


@pytest.fixture
def premium_model():
    return make_model_info(
        model_id="test/premium-model",
        tier=Tier.PREMIUM,
        display_name="Premium Model",
    )


@pytest.fixture
def economy_model():
    return make_model_info(
        model_id="test/economy-model",
        tier=Tier.ECONOMY,
        display_name="Economy Model",
    )


# =============================================================================
# ModelSelector テスト
# =============================================================================


class TestModelSelectorContextAdjustment:
    """
    _adjust_by_context 経由のティア調整テスト
    対象行: 112-118, 221
    """

    def test_context_passed_but_no_adjustment(self, selector, mock_registry, standard_model):
        """
        context引数を渡した場合の基本動作テスト。
        _adjust_by_context は現状変更を返さないので tier_adjusted=False。
        (行113-118, 221をカバー)
        """
        mock_registry.get_default_model_for_tier.return_value = standard_model

        result = selector.select(
            task_type="general",
            message=None,
            tier_override=None,
            context={"importance": "high"},
        )

        assert result.model == standard_model
        assert result.tier == Tier.STANDARD
        # _adjust_by_contextは現在何も変更しないのでtier_adjusted=False
        assert result.tier_adjusted is False

    def test_context_with_message_no_keyword_hit(self, selector, mock_registry, standard_model):
        """
        contextとmessage両方渡すが、キーワードにヒットしない場合。
        (行112-118をカバー)
        """
        mock_registry.get_default_model_for_tier.return_value = standard_model

        result = selector.select(
            task_type="general",
            message="普通のメッセージです",
            tier_override=None,
            context={"deadline": "2026-03-01"},
        )

        assert result.model == standard_model
        assert result.tier_adjusted is False


class TestModelSelectorFallback:
    """
    フォールバックモデル取得テスト
    対象行: 125-128, 252-268
    """

    def test_no_model_for_tier_fallback_to_standard(self, selector, mock_registry, standard_model):
        """
        PREMIUMティアのモデルがない場合にSTANDARDへフォールバック。
        (行125-128, 252-253, 259-266をカバー)
        """
        mock_registry.get_default_model_for_tier.side_effect = lambda tier: (
            None if tier == Tier.PREMIUM else standard_model
        )

        result = selector.select(task_type="complex_reasoning")

        assert result.model == standard_model
        assert "フォールバック" in result.reason

    def test_no_model_for_tier_fallback_to_economy(self, selector, mock_registry, economy_model):
        """
        PREMIUMとSTANDARDが両方なく、ECONOMYにフォールバック。
        (行252-253, 259-266をカバー)
        """
        def mock_get_default(tier):
            if tier == Tier.ECONOMY:
                return economy_model
            return None

        mock_registry.get_default_model_for_tier.side_effect = mock_get_default

        result = selector.select(task_type="complex_reasoning")

        assert result.model == economy_model
        assert "フォールバック" in result.reason

    def test_standard_fallback_to_economy(self, selector, mock_registry, economy_model):
        """
        STANDARDティアのモデルがなくECONOMYにフォールバック。
        (行254-255をカバー)
        """
        def mock_get_default(tier):
            if tier == Tier.ECONOMY:
                return economy_model
            return None

        mock_registry.get_default_model_for_tier.side_effect = mock_get_default

        result = selector.select(task_type="general")

        assert result.model == economy_model
        assert "フォールバック" in result.reason

    def test_economy_no_fallback_raises_error(self, selector, mock_registry):
        """
        ECONOMYティアのモデルもない場合にRuntimeError。
        (行256-257, 126-127をカバー)
        """
        mock_registry.get_default_model_for_tier.return_value = None

        with pytest.raises(RuntimeError, match="No available model"):
            selector.select(task_type="simple_qa")

    def test_no_model_any_tier_raises_error(self, selector, mock_registry):
        """
        全ティアにモデルがない場合にRuntimeError。
        (行125-128, 267-268をカバー)
        """
        mock_registry.get_default_model_for_tier.return_value = None

        with pytest.raises(RuntimeError, match="No available model"):
            selector.select(task_type="complex_reasoning")


class TestModelSelectorPartialMatchAndDefault:
    """
    タスクタイプの部分一致とデフォルトティアのテスト
    対象行: 159-164
    """

    def test_partial_match_task_type(self, selector, mock_registry, premium_model):
        """
        タスクタイプの部分一致でティアが決定される。
        例: 'my_coding_task' は 'coding' を含むのでPREMIUM。
        (行159-161をカバー)
        """
        mock_registry.get_default_model_for_tier.return_value = premium_model

        result = selector.select(task_type="my_coding_task")

        assert result.tier == Tier.PREMIUM

    def test_unknown_task_type_uses_default(self, selector, mock_registry, standard_model):
        """
        完全一致も部分一致もしないタスクタイプではデフォルトティア。
        (行163-164をカバー)
        """
        mock_registry.get_default_model_for_tier.return_value = standard_model

        result = selector.select(task_type="xyz_unknown_task_abc")

        assert result.tier == DEFAULT_TIER


class TestModelSelectorKeywordAdjustment:
    """
    キーワードによるティア調整テスト
    対象行: 187, 195
    """

    def test_upgrade_from_economy_to_standard(self, selector, mock_registry, standard_model):
        """
        ECONOMYティアのタスクにアップグレードキーワードがあるとSTANDARDへ。
        (行186-187をカバー)
        """
        mock_registry.get_default_model_for_tier.return_value = standard_model

        # 'simple_qa' は ECONOMY ティア。'重要' はアップグレードキーワード。
        result = selector.select(task_type="simple_qa", message="これは重要な質問です")

        assert result.tier == Tier.STANDARD
        assert result.tier_adjusted is True
        assert "アップグレード" in (result.adjustment_reason or "")

    def test_downgrade_from_premium_to_standard(self, selector, mock_registry, standard_model):
        """
        PREMIUMティアのタスクにダウングレードキーワードがあるとSTANDARDへ。
        (行194-195をカバー)
        """
        mock_registry.get_default_model_for_tier.return_value = standard_model

        # 'complex_reasoning' は PREMIUM ティア。'ざっくり' はダウングレードキーワード。
        result = selector.select(task_type="complex_reasoning", message="ざっくり教えて")

        assert result.tier == Tier.STANDARD
        assert result.tier_adjusted is True
        assert "ダウングレード" in (result.adjustment_reason or "")


class TestModelSelectorGetAvailableTiers:
    """
    get_available_tiers テスト
    対象行: 281-286
    """

    def test_all_tiers_available(self, selector, mock_registry):
        """
        全ティアにモデルがある場合。
        (行281-286をカバー)
        """
        mock_registry.get_models_by_tier.return_value = [make_model_info()]

        result = selector.get_available_tiers()

        assert len(result) == 3
        assert Tier.ECONOMY in result
        assert Tier.STANDARD in result
        assert Tier.PREMIUM in result

    def test_some_tiers_available(self, selector, mock_registry):
        """
        一部のティアにのみモデルがある場合。
        """
        def mock_get_models(tier):
            if tier == Tier.STANDARD:
                return [make_model_info(tier=Tier.STANDARD)]
            return []

        mock_registry.get_models_by_tier.side_effect = mock_get_models

        result = selector.get_available_tiers()

        assert result == [Tier.STANDARD]

    def test_no_tiers_available(self, selector, mock_registry):
        """
        どのティアにもモデルがない場合。
        """
        mock_registry.get_models_by_tier.return_value = []

        result = selector.get_available_tiers()

        assert result == []


class TestModelSelectorExplainSelection:
    """
    explain_selection テスト
    対象行: 303-322
    """

    def test_explain_with_message(self, selector, mock_registry, standard_model):
        """
        メッセージ付きの説明生成。
        (行303-322をカバー)
        """
        mock_registry.get_default_model_for_tier.return_value = standard_model

        result = selector.explain_selection(
            task_type="conversation",
            message="こんにちは、調子はどう？"
        )

        assert "Model Selection Explanation" in result
        assert "Task Type: conversation" in result
        assert "Base Tier:" in result
        assert "Final Tier:" in result
        assert "Selected Model:" in result
        assert "Provider:" in result
        assert "Selection Reason:" in result
        assert standard_model.display_name in result

    def test_explain_without_message(self, selector, mock_registry, standard_model):
        """
        メッセージなしの説明生成。
        (行303-322をカバー)
        """
        mock_registry.get_default_model_for_tier.return_value = standard_model

        result = selector.explain_selection(task_type="conversation")

        assert "Message: (none)" in result

    def test_explain_with_long_message(self, selector, mock_registry, standard_model):
        """
        50文字を超える長いメッセージの説明生成（行308のトランケーション）。
        """
        mock_registry.get_default_model_for_tier.return_value = standard_model

        long_message = "あ" * 100
        result = selector.explain_selection(
            task_type="conversation",
            message=long_message,
        )

        # 50文字にトランケートされ "..." が付く
        assert "..." in result

    def test_explain_with_upgrade_keyword(self, selector, mock_registry, premium_model):
        """
        アップグレードキーワードがある場合の説明。
        """
        mock_registry.get_default_model_for_tier.return_value = premium_model

        result = selector.explain_selection(
            task_type="conversation",
            message="重要な相談があります",
        )

        assert "Tier Adjusted: True" in result


# =============================================================================
# ModelOrchestrator テスト
# =============================================================================


@pytest.fixture
def mock_orchestrator_deps(mock_pool):
    """ModelOrchestratorの依存関係をモック化"""
    with patch(
        "lib.brain.model_orchestrator.orchestrator.ModelRegistry"
    ) as MockRegistry, patch(
        "lib.brain.model_orchestrator.orchestrator.ModelSelector"
    ) as MockSelector, patch(
        "lib.brain.model_orchestrator.orchestrator.CostManager"
    ) as MockCostManager, patch(
        "lib.brain.model_orchestrator.orchestrator.FallbackManager"
    ) as MockFallbackManager, patch(
        "lib.brain.model_orchestrator.orchestrator.UsageLogger"
    ) as MockUsageLogger:
        registry_instance = MockRegistry.return_value
        selector_instance = MockSelector.return_value
        cost_manager_instance = MockCostManager.return_value
        fallback_manager_instance = MockFallbackManager.return_value
        usage_logger_instance = MockUsageLogger.return_value

        yield {
            "pool": mock_pool,
            "registry": registry_instance,
            "selector": selector_instance,
            "cost_manager": cost_manager_instance,
            "fallback_manager": fallback_manager_instance,
            "usage_logger": usage_logger_instance,
            "MockRegistry": MockRegistry,
            "MockSelector": MockSelector,
            "MockCostManager": MockCostManager,
            "MockFallbackManager": MockFallbackManager,
            "MockUsageLogger": MockUsageLogger,
        }


def _make_orchestrator(deps, config=None, api_key="test-key"):
    """ヘルパー: ModelOrchestratorを作成"""
    return ModelOrchestrator(
        pool=deps["pool"],
        organization_id="org_test",
        api_key=api_key,
        config=config,
    )


class TestOrchestratorCostBlock:
    """
    コストBLOCKアクション テスト
    対象行: 204-205
    """

    @pytest.mark.asyncio
    async def test_cost_block_returns_failure(self, mock_orchestrator_deps):
        """
        コストチェックがBLOCKの場合、即座にfailure結果を返す。
        (行204-205をカバー)
        """
        deps = mock_orchestrator_deps
        model = make_model_info()
        selection = ModelSelection(
            model=model,
            tier=Tier.STANDARD,
            reason="test",
        )
        deps["selector"].select.return_value = selection

        cost_estimate = CostEstimate(
            input_tokens=500,
            output_tokens=500,
            cost_jpy=Decimal("100"),
            model_id="test/model-a",
        )
        deps["cost_manager"].estimate_cost.return_value = cost_estimate

        block_result = CostCheckResult(
            estimated_cost_jpy=Decimal("100"),
            daily_cost_jpy=Decimal("2500"),
            monthly_cost_jpy=Decimal("35000"),
            budget_remaining_jpy=Decimal("-5000"),
            budget_status="limit",
            action=CostAction.BLOCK,
            message="月間予算を超過しています",
        )
        deps["cost_manager"].check_cost.return_value = block_result

        orchestrator = _make_orchestrator(deps)

        result = await orchestrator.call(
            prompt="テストプロンプト",
            task_type="general",
        )

        assert result.success is False
        assert result.cost_action == CostAction.BLOCK
        assert "予算" in (result.error_message or "")


class TestOrchestratorRealAPICallWithFallback:
    """
    実API呼び出し（フォールバック有効/無効）テスト
    対象行: 227-253
    """

    @pytest.mark.asyncio
    async def test_call_with_fallback_enabled(self, mock_orchestrator_deps):
        """
        フォールバック有効時のAPI呼び出し。
        (行227-239をカバー)
        """
        deps = mock_orchestrator_deps
        model = make_model_info()
        selection = ModelSelection(
            model=model,
            tier=Tier.STANDARD,
            reason="test",
        )
        deps["selector"].select.return_value = selection

        cost_estimate = CostEstimate(
            input_tokens=100,
            output_tokens=50,
            cost_jpy=Decimal("1.5"),
            model_id="test/model-a",
        )
        deps["cost_manager"].estimate_cost.return_value = cost_estimate

        cost_check = CostCheckResult(
            estimated_cost_jpy=Decimal("1.5"),
            daily_cost_jpy=Decimal("10"),
            monthly_cost_jpy=Decimal("300"),
            budget_remaining_jpy=Decimal("29700"),
            budget_status="normal",
            action=CostAction.AUTO_EXECUTE,
        )
        deps["cost_manager"].check_cost.return_value = cost_check

        fallback_result = FallbackResult(
            success=True,
            response="テスト応答です",
            model_used=model,
            was_fallback=False,
            fallback_attempts=[],
            input_tokens=100,
            output_tokens=50,
        )
        deps["fallback_manager"].execute_with_fallback = AsyncMock(return_value=fallback_result)
        deps["cost_manager"].calculate_actual_cost.return_value = Decimal("1.5")

        config = OrchestratorConfig(
            enable_cost_management=True,
            enable_fallback=True,
            enable_logging=True,
            dry_run=False,
        )
        orchestrator = _make_orchestrator(deps, config=config)

        result = await orchestrator.call(
            prompt="テストプロンプト",
            task_type="general",
        )

        assert result.success is True
        assert result.content == "テスト応答です"
        deps["fallback_manager"].execute_with_fallback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_call_without_fallback_success(self, mock_orchestrator_deps):
        """
        フォールバック無効時のAPI直接呼び出し（成功）。
        (行241-251をカバー)
        """
        deps = mock_orchestrator_deps
        model = make_model_info()
        selection = ModelSelection(
            model=model,
            tier=Tier.STANDARD,
            reason="test",
        )
        deps["selector"].select.return_value = selection

        cost_estimate = CostEstimate(
            input_tokens=100,
            output_tokens=50,
            cost_jpy=Decimal("1.5"),
            model_id="test/model-a",
        )
        deps["cost_manager"].estimate_cost.return_value = cost_estimate

        cost_check = CostCheckResult(
            estimated_cost_jpy=Decimal("1.5"),
            daily_cost_jpy=Decimal("10"),
            monthly_cost_jpy=Decimal("300"),
            budget_remaining_jpy=Decimal("29700"),
            budget_status="normal",
            action=CostAction.AUTO_EXECUTE,
        )
        deps["cost_manager"].check_cost.return_value = cost_check
        deps["cost_manager"].calculate_actual_cost.return_value = Decimal("1.5")

        config = OrchestratorConfig(
            enable_cost_management=True,
            enable_fallback=False,
            enable_logging=True,
            dry_run=False,
        )
        orchestrator = _make_orchestrator(deps, config=config)

        # _call_openrouter をモック
        orchestrator._call_openrouter = AsyncMock(
            return_value=("応答テキスト", 100, 50)
        )

        result = await orchestrator.call(
            prompt="テストプロンプト",
            task_type="general",
        )

        assert result.success is True
        assert result.content == "応答テキスト"
        assert result.was_fallback is False

    @pytest.mark.asyncio
    async def test_call_without_fallback_failure(self, mock_orchestrator_deps):
        """
        フォールバック無効時のAPI直接呼び出し（失敗）。
        (行252-257をカバー)
        """
        deps = mock_orchestrator_deps
        model = make_model_info()
        selection = ModelSelection(
            model=model,
            tier=Tier.STANDARD,
            reason="test",
        )
        deps["selector"].select.return_value = selection

        cost_estimate = CostEstimate(
            input_tokens=100,
            output_tokens=50,
            cost_jpy=Decimal("1.5"),
            model_id="test/model-a",
        )
        deps["cost_manager"].estimate_cost.return_value = cost_estimate

        cost_check = CostCheckResult(
            estimated_cost_jpy=Decimal("1.5"),
            daily_cost_jpy=Decimal("10"),
            monthly_cost_jpy=Decimal("300"),
            budget_remaining_jpy=Decimal("29700"),
            budget_status="normal",
            action=CostAction.AUTO_EXECUTE,
        )
        deps["cost_manager"].check_cost.return_value = cost_check
        deps["cost_manager"].calculate_actual_cost.return_value = Decimal("0")

        config = OrchestratorConfig(
            enable_cost_management=True,
            enable_fallback=False,
            enable_logging=True,
            dry_run=False,
        )
        orchestrator = _make_orchestrator(deps, config=config)

        # _call_openrouter をモックして例外を発生させる
        orchestrator._call_openrouter = AsyncMock(
            side_effect=RuntimeError("API connection failed")
        )

        result = await orchestrator.call(
            prompt="テストプロンプト",
            task_type="general",
        )

        assert result.success is False
        assert "API connection failed" in (result.error_message or "")


class TestOrchestratorLoggingDisabled:
    """
    ログ記録無効時のテスト
    対象行: 272-273
    """

    @pytest.mark.asyncio
    async def test_logging_disabled_skips_log(self, mock_orchestrator_deps):
        """
        enable_logging=False の場合、log_usage は呼ばれない。
        (行272-273をカバー)
        """
        deps = mock_orchestrator_deps
        model = make_model_info()
        selection = ModelSelection(
            model=model,
            tier=Tier.STANDARD,
            reason="test",
        )
        deps["selector"].select.return_value = selection

        config = OrchestratorConfig(
            enable_cost_management=False,
            enable_fallback=True,
            enable_logging=False,
            dry_run=True,
        )
        orchestrator = _make_orchestrator(deps, config=config)

        result = await orchestrator.call(prompt="テスト", task_type="general")

        assert result.success is True
        deps["usage_logger"].log_usage.assert_not_called()


class TestOrchestratorExceptionHandling:
    """
    call() 例外時のテスト
    対象行: 323-327
    """

    @pytest.mark.asyncio
    async def test_call_raises_unexpected_exception(self, mock_orchestrator_deps):
        """
        selector.select()で予期しない例外が発生した場合。
        (行323-327をカバー)
        """
        deps = mock_orchestrator_deps
        deps["selector"].select.side_effect = ValueError("Unexpected DB error")

        orchestrator = _make_orchestrator(deps)

        result = await orchestrator.call(prompt="テスト", task_type="general")

        assert result.success is False
        assert "Unexpected DB error" in (result.error_message or "")
        assert result.latency_ms >= 0


class TestOrchestratorCallOpenRouter:
    """
    _call_openrouter テスト
    対象行: 356-383
    """

    @pytest.mark.asyncio
    async def test_call_openrouter_no_api_key(self, mock_orchestrator_deps):
        """
        APIキー未設定時にRuntimeErrorを発生させる。
        (行356-357をカバー)
        """
        deps = mock_orchestrator_deps
        orchestrator = _make_orchestrator(deps, api_key="")
        # 明示的にNoneに設定
        orchestrator._api_key = None

        model = make_model_info()

        with pytest.raises(RuntimeError, match="API key not configured"):
            await orchestrator._call_openrouter(
                model=model,
                prompt="テスト",
            )

    @pytest.mark.asyncio
    async def test_call_openrouter_success(self, mock_orchestrator_deps):
        """
        OpenRouter API呼び出し成功。
        (行356-383をカバー)
        """
        deps = mock_orchestrator_deps
        orchestrator = _make_orchestrator(deps, api_key="sk-test-key")

        model = make_model_info()

        mock_response = Mock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "応答テキスト"}}],
            "usage": {"prompt_tokens": 150, "completion_tokens": 80},
        }
        mock_response.raise_for_status = Mock()

        with patch("lib.brain.model_orchestrator.orchestrator.httpx.AsyncClient") as MockClient:
            mock_client_instance = AsyncMock()
            mock_client_instance.post.return_value = mock_response
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client_instance

            content, input_tokens, output_tokens = await orchestrator._call_openrouter(
                model=model,
                prompt="テストプロンプト",
                max_tokens=1000,
                temperature=0.5,
            )

        assert content == "応答テキスト"
        assert input_tokens == 150
        assert output_tokens == 80

    @pytest.mark.asyncio
    async def test_call_openrouter_no_usage(self, mock_orchestrator_deps):
        """
        usageフィールドがない場合のデフォルト値。
        """
        deps = mock_orchestrator_deps
        orchestrator = _make_orchestrator(deps, api_key="sk-test-key")

        model = make_model_info()

        mock_response = Mock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "応答"}}],
        }
        mock_response.raise_for_status = Mock()

        with patch("lib.brain.model_orchestrator.orchestrator.httpx.AsyncClient") as MockClient:
            mock_client_instance = AsyncMock()
            mock_client_instance.post.return_value = mock_response
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client_instance

            content, input_tokens, output_tokens = await orchestrator._call_openrouter(
                model=model,
                prompt="テスト",
            )

        assert content == "応答"
        assert input_tokens == 0
        assert output_tokens == 0


class TestOrchestratorGetAvailableModels:
    """
    get_available_models テスト
    対象行: 396
    """

    def test_get_available_models(self, mock_orchestrator_deps):
        """
        get_available_modelsがレジストリのget_model_statsを呼ぶ。
        (行396をカバー)
        """
        deps = mock_orchestrator_deps
        expected_stats = {"total_models": 5, "by_tier": {}, "by_provider": {}}
        deps["registry"].get_model_stats.return_value = expected_stats

        orchestrator = _make_orchestrator(deps)

        result = orchestrator.get_available_models()

        assert result == expected_stats
        deps["registry"].get_model_stats.assert_called_once()


class TestOrchestratorExplainSelection:
    """
    explain_selection テスト
    対象行: 409
    """

    def test_explain_selection_delegates_to_selector(self, mock_orchestrator_deps):
        """
        explain_selectionがselector.explain_selectionを呼ぶ。
        (行409をカバー)
        """
        deps = mock_orchestrator_deps
        deps["selector"].explain_selection.return_value = "Explanation text"

        orchestrator = _make_orchestrator(deps)

        result = orchestrator.explain_selection(
            task_type="conversation",
            message="テスト",
        )

        assert result == "Explanation text"
        deps["selector"].explain_selection.assert_called_once_with(
            "conversation", "テスト"
        )


class TestOrchestratorIsEnabled:
    """
    is_enabled 静的メソッドテスト
    """

    def test_is_enabled_true(self):
        """FEATURE_FLAG_NAME=true の場合"""
        with patch.dict(os.environ, {FEATURE_FLAG_NAME: "true"}):
            assert ModelOrchestrator.is_enabled() is True

    def test_is_enabled_false(self):
        """FEATURE_FLAG_NAME=false の場合"""
        with patch.dict(os.environ, {FEATURE_FLAG_NAME: "false"}):
            assert ModelOrchestrator.is_enabled() is False

    def test_is_enabled_not_set(self):
        """環境変数未設定の場合"""
        env = os.environ.copy()
        env.pop(FEATURE_FLAG_NAME, None)
        with patch.dict(os.environ, env, clear=True):
            assert ModelOrchestrator.is_enabled() is False

    def test_is_enabled_case_insensitive(self):
        """大文字小文字を無視"""
        with patch.dict(os.environ, {FEATURE_FLAG_NAME: "TRUE"}):
            assert ModelOrchestrator.is_enabled() is True


class TestCreateOrchestratorFactory:
    """
    create_orchestrator ファクトリー関数テスト
    """

    def test_create_orchestrator_default_config(self, mock_orchestrator_deps):
        """デフォルト設定でのOrchestrator作成"""
        deps = mock_orchestrator_deps

        orchestrator = create_orchestrator(
            pool=deps["pool"],
            organization_id="org_test",
            api_key="test-key",
        )

        assert isinstance(orchestrator, ModelOrchestrator)

    def test_create_orchestrator_custom_config(self, mock_orchestrator_deps):
        """カスタム設定でのOrchestrator作成"""
        deps = mock_orchestrator_deps

        orchestrator = create_orchestrator(
            pool=deps["pool"],
            organization_id="org_test",
            api_key="test-key",
            enable_cost_management=False,
            enable_fallback=False,
            enable_logging=False,
            dry_run=True,
        )

        assert isinstance(orchestrator, ModelOrchestrator)
        assert orchestrator._config.dry_run is True
        assert orchestrator._config.enable_cost_management is False
        assert orchestrator._config.enable_fallback is False
        assert orchestrator._config.enable_logging is False


class TestOrchestratorDryRun:
    """
    dry_run モードのテスト
    """

    @pytest.mark.asyncio
    async def test_dry_run_skips_api_call(self, mock_orchestrator_deps):
        """
        dry_run=True 時は実際のAPI呼び出しをスキップ。
        """
        deps = mock_orchestrator_deps
        model = make_model_info()
        selection = ModelSelection(
            model=model,
            tier=Tier.STANDARD,
            reason="test",
        )
        deps["selector"].select.return_value = selection

        cost_estimate = CostEstimate(
            input_tokens=100,
            output_tokens=50,
            cost_jpy=Decimal("1.5"),
            model_id="test/model-a",
        )
        deps["cost_manager"].estimate_cost.return_value = cost_estimate

        cost_check = CostCheckResult(
            estimated_cost_jpy=Decimal("1.5"),
            daily_cost_jpy=Decimal("10"),
            monthly_cost_jpy=Decimal("300"),
            budget_remaining_jpy=Decimal("29700"),
            budget_status="normal",
            action=CostAction.AUTO_EXECUTE,
        )
        deps["cost_manager"].check_cost.return_value = cost_check
        deps["cost_manager"].calculate_actual_cost.return_value = Decimal("1.5")

        config = OrchestratorConfig(
            enable_cost_management=True,
            enable_fallback=True,
            enable_logging=True,
            dry_run=True,
        )
        orchestrator = _make_orchestrator(deps, config=config)

        result = await orchestrator.call(prompt="テスト", task_type="general")

        assert result.success is True
        assert "[DRY RUN]" in (result.content or "")

    @pytest.mark.asyncio
    async def test_dry_run_without_cost_management(self, mock_orchestrator_deps):
        """
        dry_run=True かつ cost_management=False。
        cost_estimate がないときのフォールバックトークン値テスト。
        """
        deps = mock_orchestrator_deps
        model = make_model_info()
        selection = ModelSelection(
            model=model,
            tier=Tier.STANDARD,
            reason="test",
        )
        deps["selector"].select.return_value = selection
        deps["cost_manager"].calculate_actual_cost.return_value = Decimal("0")

        config = OrchestratorConfig(
            enable_cost_management=False,
            enable_fallback=True,
            enable_logging=True,
            dry_run=True,
        )
        orchestrator = _make_orchestrator(deps, config=config)

        result = await orchestrator.call(prompt="テスト", task_type="general")

        assert result.success is True
        assert "[DRY RUN]" in (result.content or "")
        # cost_estimate=Noneの場合はデフォルト値(100, 50)が使われる
        assert result.input_tokens == 100
        assert result.output_tokens == 50


class TestOrchestratorMonthlySummaryUpdate:
    """
    月次サマリー更新のテスト
    対象行: 293-302 付近の分岐
    """

    @pytest.mark.asyncio
    async def test_monthly_summary_updated_on_success(self, mock_orchestrator_deps):
        """
        成功時にmonthly summaryが更新される。
        """
        deps = mock_orchestrator_deps
        model = make_model_info()
        selection = ModelSelection(
            model=model,
            tier=Tier.STANDARD,
            reason="test",
        )
        deps["selector"].select.return_value = selection

        cost_estimate = CostEstimate(
            input_tokens=100,
            output_tokens=50,
            cost_jpy=Decimal("1.5"),
            model_id="test/model-a",
        )
        deps["cost_manager"].estimate_cost.return_value = cost_estimate

        cost_check = CostCheckResult(
            estimated_cost_jpy=Decimal("1.5"),
            daily_cost_jpy=Decimal("10"),
            monthly_cost_jpy=Decimal("300"),
            budget_remaining_jpy=Decimal("29700"),
            budget_status="normal",
            action=CostAction.AUTO_EXECUTE,
        )
        deps["cost_manager"].check_cost.return_value = cost_check
        deps["cost_manager"].calculate_actual_cost.return_value = Decimal("1.5")

        config = OrchestratorConfig(
            enable_cost_management=True,
            enable_fallback=True,
            enable_logging=True,
            dry_run=True,
        )
        orchestrator = _make_orchestrator(deps, config=config)

        result = await orchestrator.call(prompt="テスト", task_type="general")

        assert result.success is True
        deps["cost_manager"].update_monthly_summary.assert_called_once()

    @pytest.mark.asyncio
    async def test_monthly_summary_not_updated_when_cost_mgmt_disabled(self, mock_orchestrator_deps):
        """
        cost_management無効時にmonthly summaryが更新されない。
        """
        deps = mock_orchestrator_deps
        model = make_model_info()
        selection = ModelSelection(
            model=model,
            tier=Tier.STANDARD,
            reason="test",
        )
        deps["selector"].select.return_value = selection
        deps["cost_manager"].calculate_actual_cost.return_value = Decimal("0")

        config = OrchestratorConfig(
            enable_cost_management=False,
            enable_fallback=True,
            enable_logging=True,
            dry_run=True,
        )
        orchestrator = _make_orchestrator(deps, config=config)

        result = await orchestrator.call(prompt="テスト", task_type="general")

        assert result.success is True
        deps["cost_manager"].update_monthly_summary.assert_not_called()


class TestOrchestratorCallWithRoomAndUser:
    """
    room_id/user_id引数を渡した場合のテスト
    """

    @pytest.mark.asyncio
    async def test_call_with_room_and_user_ids(self, mock_orchestrator_deps):
        """
        room_id, user_idを渡した場合、ログに記録される。
        """
        deps = mock_orchestrator_deps
        model = make_model_info()
        selection = ModelSelection(
            model=model,
            tier=Tier.STANDARD,
            reason="test",
        )
        deps["selector"].select.return_value = selection
        deps["cost_manager"].calculate_actual_cost.return_value = Decimal("0")

        config = OrchestratorConfig(
            enable_cost_management=False,
            enable_fallback=True,
            enable_logging=True,
            dry_run=True,
        )
        orchestrator = _make_orchestrator(deps, config=config)

        result = await orchestrator.call(
            prompt="テスト",
            task_type="general",
            room_id="room_123",
            user_id="user_456",
        )

        assert result.success is True
        # log_usageの呼び出しでroom_id, user_idが渡されているか確認
        call_kwargs = deps["usage_logger"].log_usage.call_args
        assert call_kwargs is not None
        # keyword argsまたはpositional argsで確認
        if call_kwargs.kwargs:
            assert call_kwargs.kwargs.get("room_id") == "room_123"
            assert call_kwargs.kwargs.get("user_id") == "user_456"


class TestModelSelectorAdjustByContextWithMockedUpgrade:
    """
    将来的にcontextでティア変更する可能性をテスト。
    現在の_adjust_by_contextは変更を返さないことを確認。
    """

    def test_adjust_by_context_returns_same_tier(self, selector):
        """_adjust_by_contextが同じティアとNoneを返す"""
        tier, reason = selector._adjust_by_context(Tier.STANDARD, {"importance": "high"})
        assert tier == Tier.STANDARD
        assert reason is None

    def test_adjust_by_context_premium(self, selector):
        """PREMIUMティアでもcontextは変更しない"""
        tier, reason = selector._adjust_by_context(Tier.PREMIUM, {"deadline": "tomorrow"})
        assert tier == Tier.PREMIUM
        assert reason is None

    def test_adjust_by_context_economy(self, selector):
        """ECONOMYティアでもcontextは変更しない"""
        tier, reason = selector._adjust_by_context(Tier.ECONOMY, {"user_role": "ceo"})
        assert tier == Tier.ECONOMY
        assert reason is None
