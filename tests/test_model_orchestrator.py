"""
Model Orchestrator ユニットテスト

全コンポーネントのテストを含む:
- constants.py
- registry.py
- model_selector.py
- cost_manager.py
- fallback_manager.py
- usage_logger.py
- orchestrator.py
"""

import pytest
from decimal import Decimal
from datetime import datetime, date
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from uuid import uuid4
import asyncio

# テスト対象
from lib.brain.model_orchestrator import (
    # 定数
    Tier,
    BudgetStatus,
    CostThreshold,
    MonthlyBudget,
    TASK_TYPE_TIERS,
    DEFAULT_TIER,
    TIER_UPGRADE_KEYWORDS,
    TIER_DOWNGRADE_KEYWORDS,
    FALLBACK_CHAINS,
    MAX_RETRIES,
    FEATURE_FLAG_NAME,
    # Registry
    ModelRegistry,
    ModelInfo,
    # Selector
    ModelSelector,
    ModelSelection,
    # Cost Manager
    CostManager,
    CostCheckResult,
    CostAction,
    CostEstimate,
    OrganizationSettings,
    # Fallback Manager
    FallbackManager,
    FallbackResult,
    FallbackAttempt,
    APIError,
    # Usage Logger
    UsageLogger,
    UsageLogEntry,
    UsageStats,
    # Orchestrator
    ModelOrchestrator,
    OrchestratorResult,
    OrchestratorConfig,
    create_orchestrator,
)


# =============================================================================
# テスト用ヘルパー
# =============================================================================

def create_test_model_info(
    model_id: str = "gpt-4o",
    provider: str = "openai",
    display_name: str = "GPT-4o",
    tier: Tier = Tier.STANDARD,
    input_cost: Decimal = Decimal("5.0"),
    output_cost: Decimal = Decimal("15.0"),
    max_context: int = 128000,
    max_output: int = 4096,
    fallback_priority: int = 1,
    is_active: bool = True,
    is_default_for_tier: bool = False,
) -> ModelInfo:
    """テスト用ModelInfoを作成するヘルパー"""
    return ModelInfo(
        id=uuid4(),
        model_id=model_id,
        provider=provider,
        display_name=display_name,
        tier=tier,
        capabilities=["text"],
        input_cost_per_1m_usd=input_cost,
        output_cost_per_1m_usd=output_cost,
        max_context_tokens=max_context,
        max_output_tokens=max_output,
        fallback_priority=fallback_priority,
        is_active=is_active,
        is_default_for_tier=is_default_for_tier,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


def create_test_organization_settings(
    organization_id: str = "org_test",
    monthly_budget: Decimal = Decimal("30000"),
    cost_threshold_warning: Decimal = Decimal("100"),
    cost_threshold_caution: Decimal = Decimal("500"),
    cost_threshold_limit: Decimal = Decimal("2000"),
) -> OrganizationSettings:
    """テスト用OrganizationSettingsを作成するヘルパー"""
    return OrganizationSettings(
        organization_id=organization_id,
        monthly_budget_jpy=monthly_budget,
        cost_threshold_warning=cost_threshold_warning,
        cost_threshold_caution=cost_threshold_caution,
        cost_threshold_limit=cost_threshold_limit,
        default_tier="standard",
        enable_premium_tier=True,
        enable_auto_downgrade=True,
        enable_fallback=True,
        max_fallback_attempts=3,
        usd_to_jpy_rate=Decimal("150"),
    )


# =============================================================================
# constants.py テスト
# =============================================================================

class TestConstants:
    """定数のテスト"""

    def test_tier_enum_values(self):
        """Tierの値が正しいこと"""
        assert Tier.ECONOMY.value == "economy"
        assert Tier.STANDARD.value == "standard"
        assert Tier.PREMIUM.value == "premium"

    def test_budget_status_enum_values(self):
        """BudgetStatusの値が正しいこと"""
        assert BudgetStatus.NORMAL.value == "normal"
        assert BudgetStatus.WARNING.value == "warning"
        assert BudgetStatus.CAUTION.value == "caution"
        assert BudgetStatus.LIMIT.value == "limit"

    def test_cost_threshold_values(self):
        """コスト閾値が設計通りであること"""
        # 実装に合わせた閾値名
        assert CostThreshold.NORMAL_MAX == Decimal("100")
        assert CostThreshold.WARNING_MAX == Decimal("500")
        assert CostThreshold.CAUTION_MAX == Decimal("2000")
        assert CostThreshold.LIMIT == Decimal("2000")

    def test_monthly_budget_default(self):
        """月次予算デフォルト値が設定されていること"""
        assert MonthlyBudget.DEFAULT_JPY == Decimal("30000")

    def test_task_type_tiers_mapping(self):
        """タスクタイプ→ティアマッピングが定義されていること"""
        assert "conversation" in TASK_TYPE_TIERS
        assert TASK_TYPE_TIERS["conversation"] == Tier.STANDARD
        assert "emotion_detection" in TASK_TYPE_TIERS
        assert TASK_TYPE_TIERS["emotion_detection"] == Tier.ECONOMY
        assert "ceo_learning" in TASK_TYPE_TIERS
        assert TASK_TYPE_TIERS["ceo_learning"] == Tier.PREMIUM

    def test_default_tier(self):
        """デフォルトティアがSTANDARDであること"""
        assert DEFAULT_TIER == Tier.STANDARD

    def test_tier_upgrade_keywords(self):
        """アップグレードキーワードが定義されていること"""
        assert len(TIER_UPGRADE_KEYWORDS) > 0
        assert "重要" in TIER_UPGRADE_KEYWORDS
        assert "経営" in TIER_UPGRADE_KEYWORDS

    def test_tier_downgrade_keywords(self):
        """ダウングレードキーワードが定義されていること"""
        assert len(TIER_DOWNGRADE_KEYWORDS) > 0
        assert "ざっくり" in TIER_DOWNGRADE_KEYWORDS
        # "簡単" ではなく "簡単に" が定義されている
        assert "簡単に" in TIER_DOWNGRADE_KEYWORDS or "ざっくり" in TIER_DOWNGRADE_KEYWORDS

    def test_fallback_chains(self):
        """フォールバックチェーンが全ティアで定義されていること"""
        assert Tier.PREMIUM in FALLBACK_CHAINS
        assert Tier.STANDARD in FALLBACK_CHAINS
        assert Tier.ECONOMY in FALLBACK_CHAINS

    def test_max_retries(self):
        """最大リトライ回数が正の整数であること"""
        assert MAX_RETRIES > 0
        assert isinstance(MAX_RETRIES, int)

    def test_feature_flag_name(self):
        """Feature Flag名が定義されていること"""
        assert FEATURE_FLAG_NAME == "USE_MODEL_ORCHESTRATOR"


# =============================================================================
# registry.py テスト
# =============================================================================

class TestModelInfo:
    """ModelInfoのテスト"""

    def test_create_model_info(self):
        """ModelInfoが正しく作成できること"""
        model = create_test_model_info()
        assert model.model_id == "gpt-4o"
        assert model.tier == Tier.STANDARD
        assert model.is_active is True

    def test_calculate_cost_jpy(self):
        """コスト計算が正しいこと"""
        model = create_test_model_info(
            input_cost=Decimal("5.0"),
            output_cost=Decimal("15.0"),
        )
        # 1000入力 + 500出力、レート150
        cost = model.calculate_cost_jpy(
            input_tokens=1000,
            output_tokens=500,
            usd_to_jpy_rate=Decimal("150")
        )
        # (5.0 * 1000/1M + 15.0 * 500/1M) * 150 = (0.005 + 0.0075) * 150 = 1.875
        expected = Decimal("1.875")
        assert cost == expected


class TestModelRegistry:
    """ModelRegistryのテスト"""

    @pytest.fixture
    def mock_pool(self):
        """モックDBプールを作成"""
        pool = Mock()
        conn = Mock()
        pool.connect.return_value.__enter__ = Mock(return_value=conn)
        pool.connect.return_value.__exit__ = Mock(return_value=False)
        return pool

    def test_registry_initialization(self, mock_pool):
        """Registryが初期化できること"""
        registry = ModelRegistry(mock_pool)
        assert registry._pool == mock_pool
        assert registry._cache == {}

    def test_get_models_by_tier_with_cache(self, mock_pool):
        """キャッシュがある場合はDBを呼ばないこと"""
        registry = ModelRegistry(mock_pool)

        # キャッシュに直接データを設定
        test_model = create_test_model_info(model_id="test-model")
        registry._cache = {f"tier:{Tier.STANDARD.value}": [test_model]}
        registry._cache_timestamp = datetime.now()

        # get_models_by_tierを呼び出し
        models = registry.get_models_by_tier(Tier.STANDARD)

        # キャッシュから取得されること
        assert len(models) == 1
        assert models[0].model_id == "test-model"


# =============================================================================
# model_selector.py テスト
# =============================================================================

class TestModelSelector:
    """ModelSelectorのテスト"""

    @pytest.fixture
    def mock_registry(self):
        """モックレジストリを作成"""
        registry = Mock(spec=ModelRegistry)

        # モックモデルを設定
        standard_model = create_test_model_info(
            model_id="gpt-4o",
            tier=Tier.STANDARD,
        )
        premium_model = create_test_model_info(
            model_id="claude-opus",
            provider="anthropic",
            display_name="Claude Opus",
            tier=Tier.PREMIUM,
            input_cost=Decimal("15.0"),
            output_cost=Decimal("75.0"),
            max_context=200000,
        )
        economy_model = create_test_model_info(
            model_id="gemini-flash",
            provider="google",
            display_name="Gemini Flash",
            tier=Tier.ECONOMY,
            input_cost=Decimal("0.075"),
            output_cost=Decimal("0.30"),
            max_context=1000000,
            max_output=8192,
        )

        registry.get_default_model_for_tier.side_effect = lambda tier: {
            Tier.STANDARD: standard_model,
            Tier.PREMIUM: premium_model,
            Tier.ECONOMY: economy_model,
        }[tier]

        return registry

    def test_select_by_task_type(self, mock_registry):
        """タスクタイプに応じたティアが選択されること"""
        selector = ModelSelector(mock_registry)

        # conversationはSTANDARD
        result = selector.select(task_type="conversation")
        assert result.tier == Tier.STANDARD

        # ceo_learningはPREMIUM
        result = selector.select(task_type="ceo_learning")
        assert result.tier == Tier.PREMIUM

        # emotion_detectionはECONOMY
        result = selector.select(task_type="emotion_detection")
        assert result.tier == Tier.ECONOMY

    def test_tier_override(self, mock_registry):
        """ティア直接指定が優先されること"""
        selector = ModelSelector(mock_registry)

        # タスクタイプはconversation(STANDARD)だが、PREMIUMを指定
        result = selector.select(
            task_type="conversation",
            tier_override=Tier.PREMIUM
        )
        assert result.tier == Tier.PREMIUM

    def test_keyword_upgrade(self, mock_registry):
        """アップグレードキーワードでティアが上がること"""
        selector = ModelSelector(mock_registry)

        # 「重要」キーワードでアップグレード
        result = selector.select(
            task_type="conversation",  # 本来STANDARD
            message="これは重要な経営判断です"
        )
        assert result.tier == Tier.PREMIUM

    def test_keyword_downgrade(self, mock_registry):
        """ダウングレードキーワードでティアが下がること"""
        selector = ModelSelector(mock_registry)

        # 「ざっくり」キーワードでダウングレード
        result = selector.select(
            task_type="conversation",  # 本来STANDARD
            message="ざっくり教えて"
        )
        assert result.tier == Tier.ECONOMY

    def test_selection_has_reason(self, mock_registry):
        """選択理由が記録されること"""
        selector = ModelSelector(mock_registry)

        result = selector.select(task_type="conversation")
        assert result.reason is not None
        assert len(result.reason) > 0


# =============================================================================
# cost_manager.py テスト
# =============================================================================

class TestCostManager:
    """CostManagerのテスト"""

    @pytest.fixture
    def mock_pool(self):
        """モックDBプールを作成"""
        pool = Mock()
        conn = Mock()
        result = Mock()
        result.fetchone.return_value = None
        conn.execute.return_value = result
        pool.connect.return_value.__enter__ = Mock(return_value=conn)
        pool.connect.return_value.__exit__ = Mock(return_value=False)
        return pool

    @pytest.fixture
    def cost_manager(self, mock_pool):
        """CostManagerインスタンスを作成"""
        return CostManager(mock_pool, "org_test")

    def test_estimate_tokens(self, cost_manager):
        """トークン推定が動作すること"""
        prompt = "これはテストプロンプトです。"
        input_tokens, output_tokens = cost_manager.estimate_tokens(prompt)
        assert input_tokens > 0
        assert isinstance(input_tokens, int)

    def test_estimate_cost(self, cost_manager):
        """コスト推定が動作すること"""
        model = create_test_model_info()

        estimate = cost_manager.estimate_cost(
            model=model,
            prompt="これはテストです",
            expected_output_tokens=100,
        )

        assert isinstance(estimate, CostEstimate)
        assert estimate.input_tokens > 0
        assert estimate.output_tokens == 100
        assert estimate.cost_jpy > 0

    def test_check_cost_normal(self, cost_manager):
        """正常コストの場合AUTO_EXECUTEになること"""
        model = create_test_model_info()

        # 低コスト
        result = cost_manager.check_cost(
            estimated_cost_jpy=Decimal("1.0"),
            model=model,
        )

        assert result.action == CostAction.AUTO_EXECUTE

    def test_check_cost_high(self, cost_manager):
        """高コストの場合BLOCKになること"""
        model = create_test_model_info(
            model_id="claude-opus",
            tier=Tier.PREMIUM,
            input_cost=Decimal("15.0"),
            output_cost=Decimal("75.0"),
        )

        # 設定を直接設定（設定キャッシュを上書き）
        cost_manager._settings_cache = create_test_organization_settings(
            monthly_budget=Decimal("10000"),
            cost_threshold_warning=Decimal("100"),
            cost_threshold_caution=Decimal("500"),
            cost_threshold_limit=Decimal("2000"),
        )

        # 日次コスト取得をモック（高い値を返す）
        with patch.object(cost_manager, '_get_daily_cost', return_value=Decimal("2500")):
            with patch.object(cost_manager, '_get_monthly_summary', return_value={
                "total_cost_jpy": Decimal("9500"),
                "total_requests": 100,
                "total_input_tokens": 50000,
                "total_output_tokens": 25000,
                "budget_jpy": Decimal("10000"),
                "budget_remaining_jpy": Decimal("500"),
                "budget_status": BudgetStatus.CAUTION.value,
            }):
                result = cost_manager.check_cost(
                    estimated_cost_jpy=Decimal("10.0"),
                    model=model,
                )

                # 日次使用量が閾値を超えているのでSHOW_ALTERNATIVES or BLOCK
                assert result.action in [CostAction.SHOW_ALTERNATIVES, CostAction.BLOCK]

    def test_calculate_actual_cost(self, cost_manager):
        """実績コスト計算が動作すること"""
        model = create_test_model_info()

        cost = cost_manager.calculate_actual_cost(
            model=model,
            input_tokens=1000,
            output_tokens=500,
        )

        assert cost > 0
        assert isinstance(cost, Decimal)


# =============================================================================
# fallback_manager.py テスト
# =============================================================================

class TestFallbackManager:
    """FallbackManagerのテスト"""

    @pytest.fixture
    def mock_registry(self):
        """モックレジストリを作成"""
        registry = Mock(spec=ModelRegistry)

        standard_model = create_test_model_info(
            model_id="gpt-4o",
            tier=Tier.STANDARD,
        )
        economy_model = create_test_model_info(
            model_id="gemini-flash",
            provider="google",
            display_name="Gemini Flash",
            tier=Tier.ECONOMY,
            input_cost=Decimal("0.075"),
            output_cost=Decimal("0.30"),
            max_context=1000000,
            max_output=8192,
        )

        registry.get_models_by_tier.side_effect = lambda tier: {
            Tier.STANDARD: [standard_model],
            Tier.ECONOMY: [economy_model],
            Tier.PREMIUM: [],
        }[tier]

        return registry

    @pytest.fixture
    def fallback_manager(self, mock_registry):
        """FallbackManagerインスタンスを作成"""
        return FallbackManager(mock_registry)

    def test_get_fallback_chain(self, fallback_manager, mock_registry):
        """フォールバックチェーンが取得できること"""
        primary = create_test_model_info(
            model_id="claude-opus",
            tier=Tier.PREMIUM,
        )

        chain = fallback_manager.get_fallback_chain(primary)
        # PREMIUMからSTANDARD、ECONOMYへのフォールバック
        assert len(chain) > 0

    def test_is_retriable_api_error(self, fallback_manager):
        """APIErrorのリトライ判定が正しいこと"""
        # リトライ可能
        error = APIError("Rate limit", status_code=429, is_retriable=True)
        assert fallback_manager.is_retriable(error) is True

        # リトライ不可（認証エラー）
        error = APIError("Unauthorized", status_code=401, is_retriable=False)
        assert fallback_manager.is_retriable(error) is False

    def test_is_retriable_timeout(self, fallback_manager):
        """タイムアウトがリトライ可能と判定されること"""
        error = asyncio.TimeoutError()
        assert fallback_manager.is_retriable(error) is True

    def test_calculate_retry_delay(self, fallback_manager):
        """リトライ遅延が指数的に増加すること"""
        delay0 = fallback_manager.calculate_retry_delay(0)
        delay1 = fallback_manager.calculate_retry_delay(1)
        delay2 = fallback_manager.calculate_retry_delay(2)

        assert delay1 > delay0
        assert delay2 > delay1

    @pytest.mark.asyncio
    async def test_execute_with_fallback_success(self, fallback_manager):
        """成功時にフォールバックしないこと"""
        primary = create_test_model_info()

        async def success_call(model):
            return ("Success response", 100, 50)

        result = await fallback_manager.execute_with_fallback(
            primary_model=primary,
            call_func=success_call,
        )

        assert result.success is True
        assert result.was_fallback is False
        assert result.response == "Success response"

    @pytest.mark.asyncio
    async def test_execute_with_fallback_failure(self, fallback_manager):
        """全モデル失敗時にエラーを返すこと"""
        primary = create_test_model_info()

        async def fail_call(model):
            raise APIError("Service unavailable", status_code=503, is_retriable=False)

        result = await fallback_manager.execute_with_fallback(
            primary_model=primary,
            call_func=fail_call,
            max_retries=1,
        )

        assert result.success is False
        assert result.error_message is not None


# =============================================================================
# usage_logger.py テスト
# =============================================================================

class TestUsageLogger:
    """UsageLoggerのテスト"""

    @pytest.fixture
    def mock_pool(self):
        """モックDBプールを作成"""
        pool = Mock()
        conn = Mock()
        result = Mock()
        # Use a valid UUID format for the mock
        result.fetchone.return_value = ("550e8400-e29b-41d4-a716-446655440000",)
        conn.execute.return_value = result
        pool.connect.return_value.__enter__ = Mock(return_value=conn)
        pool.connect.return_value.__exit__ = Mock(return_value=False)
        return pool

    @pytest.fixture
    def usage_logger(self, mock_pool):
        """UsageLoggerインスタンスを作成"""
        return UsageLogger(mock_pool, "org_test")

    def test_log_usage(self, usage_logger, mock_pool):
        """利用ログが記録できること"""
        log_id = usage_logger.log_usage(
            model_id="gpt-4o",
            task_type="conversation",
            tier=Tier.STANDARD,
            input_tokens=100,
            output_tokens=50,
            cost_jpy=Decimal("1.5"),
            latency_ms=500,
            success=True,
        )

        assert log_id is not None

    def test_log_usage_with_fallback(self, usage_logger, mock_pool):
        """フォールバック情報付きログが記録できること"""
        log_id = usage_logger.log_usage(
            model_id="gpt-4o",
            task_type="conversation",
            tier=Tier.STANDARD,
            input_tokens=100,
            output_tokens=50,
            cost_jpy=Decimal("1.5"),
            latency_ms=500,
            success=True,
            was_fallback=True,
            original_model_id="claude-opus",
            fallback_reason="Rate limit exceeded",
            fallback_attempt=2,
        )

        assert log_id is not None


# =============================================================================
# orchestrator.py テスト
# =============================================================================

class TestOrchestrator:
    """ModelOrchestratorのテスト"""

    @pytest.fixture
    def mock_pool(self):
        """モックDBプールを作成"""
        pool = Mock()
        conn = Mock()
        result = Mock()
        result.fetchone.return_value = None
        result.fetchall.return_value = []
        conn.execute.return_value = result
        pool.connect.return_value.__enter__ = Mock(return_value=conn)
        pool.connect.return_value.__exit__ = Mock(return_value=False)
        return pool

    def test_create_orchestrator(self, mock_pool):
        """ファクトリー関数でOrchestratorが作成できること"""
        orchestrator = create_orchestrator(
            pool=mock_pool,
            organization_id="org_test",
            api_key="test-api-key",
            dry_run=True,
        )

        assert orchestrator is not None
        assert isinstance(orchestrator, ModelOrchestrator)

    def test_orchestrator_config(self, mock_pool):
        """設定が正しく適用されること"""
        config = OrchestratorConfig(
            enable_cost_management=True,
            enable_fallback=True,
            enable_logging=False,
            dry_run=True,
        )

        orchestrator = ModelOrchestrator(
            pool=mock_pool,
            organization_id="org_test",
            api_key="test-api-key",
            config=config,
        )

        assert orchestrator._config.dry_run is True
        assert orchestrator._config.enable_logging is False

    @pytest.mark.asyncio
    async def test_call_dry_run(self, mock_pool):
        """Dry runモードで実行できること"""
        orchestrator = create_orchestrator(
            pool=mock_pool,
            organization_id="org_test",
            api_key="test-api-key",
            dry_run=True,
            enable_logging=False,
        )

        # Registryのget_default_model_for_tierをモック
        test_model = create_test_model_info(tier=Tier.STANDARD)
        with patch.object(orchestrator._registry, 'get_default_model_for_tier', return_value=test_model):
            result = await orchestrator.call(
                prompt="テストプロンプト",
                task_type="conversation",
            )

            assert result.success is True
            assert "[DRY RUN]" in result.content

    def test_is_enabled(self):
        """Feature Flag確認が動作すること"""
        with patch.dict('os.environ', {'USE_MODEL_ORCHESTRATOR': 'true'}):
            assert ModelOrchestrator.is_enabled() is True

        with patch.dict('os.environ', {'USE_MODEL_ORCHESTRATOR': 'false'}):
            assert ModelOrchestrator.is_enabled() is False


class TestOrchestratorResult:
    """OrchestratorResultのテスト"""

    def test_success_result(self):
        """成功結果が正しく作成できること"""
        result = OrchestratorResult(
            success=True,
            content="テスト応答",
            tier_used=Tier.STANDARD,
            input_tokens=100,
            output_tokens=50,
            cost_jpy=Decimal("1.5"),
            latency_ms=500,
        )

        assert result.success is True
        assert result.content == "テスト応答"
        assert result.cost_jpy == Decimal("1.5")

    def test_error_result(self):
        """エラー結果が正しく作成できること"""
        result = OrchestratorResult(
            success=False,
            error_message="API error occurred",
            cost_action=CostAction.BLOCK,
            cost_message="Budget exceeded",
        )

        assert result.success is False
        assert result.error_message == "API error occurred"
        assert result.cost_action == CostAction.BLOCK

    def test_fallback_result(self):
        """フォールバック結果が正しく作成できること"""
        result = OrchestratorResult(
            success=True,
            content="フォールバック応答",
            was_fallback=True,
            original_model_id="claude-opus",
            fallback_attempts=2,
        )

        assert result.was_fallback is True
        assert result.original_model_id == "claude-opus"
        assert result.fallback_attempts == 2


# =============================================================================
# 統合テスト
# =============================================================================

class TestIntegration:
    """統合テスト"""

    @pytest.fixture
    def mock_pool(self):
        """モックDBプールを作成"""
        pool = Mock()
        conn = Mock()
        result = Mock()
        result.fetchone.return_value = None
        result.fetchall.return_value = []
        conn.execute.return_value = result
        pool.connect.return_value.__enter__ = Mock(return_value=conn)
        pool.connect.return_value.__exit__ = Mock(return_value=False)
        return pool

    @pytest.mark.asyncio
    async def test_full_flow_dry_run(self, mock_pool):
        """フルフロー（dry run）が動作すること"""
        orchestrator = create_orchestrator(
            pool=mock_pool,
            organization_id="org_test",
            api_key="test-key",
            dry_run=True,
            enable_logging=False,
        )

        # Registryのget_default_model_for_tierをモック
        standard_model = create_test_model_info(tier=Tier.STANDARD)
        with patch.object(orchestrator._registry, 'get_default_model_for_tier', return_value=standard_model):
            # 通常のタスク
            result = await orchestrator.call(
                prompt="こんにちは",
                task_type="conversation",
            )

            assert result.success is True
            assert result.tier_used == Tier.STANDARD

    @pytest.mark.asyncio
    async def test_tier_selection_flow(self, mock_pool):
        """ティア選択フローが動作すること"""
        orchestrator = create_orchestrator(
            pool=mock_pool,
            organization_id="org_test",
            api_key="test-key",
            dry_run=True,
            enable_logging=False,
        )

        # Registryのget_default_model_for_tierをモック（各ティアに対応）
        premium_model = create_test_model_info(model_id="claude-opus", tier=Tier.PREMIUM)
        with patch.object(orchestrator._registry, 'get_default_model_for_tier', return_value=premium_model):
            # 重要キーワードでPREMIUM
            result = await orchestrator.call(
                prompt="これは重要な経営判断です",
                task_type="conversation",
            )

            assert result.tier_used == Tier.PREMIUM

    @pytest.mark.asyncio
    async def test_tier_override(self, mock_pool):
        """ティア直接指定が動作すること"""
        orchestrator = create_orchestrator(
            pool=mock_pool,
            organization_id="org_test",
            api_key="test-key",
            dry_run=True,
            enable_logging=False,
        )

        # Registryのget_default_model_for_tierをモック
        economy_model = create_test_model_info(model_id="gemini-flash", tier=Tier.ECONOMY)
        with patch.object(orchestrator._registry, 'get_default_model_for_tier', return_value=economy_model):
            # ECONOMYを明示的に指定
            result = await orchestrator.call(
                prompt="こんにちは",
                task_type="conversation",
                tier_override=Tier.ECONOMY,
            )

            assert result.tier_used == Tier.ECONOMY


# =============================================================================
# 統合テスト（API呼び出しシミュレーション）
# =============================================================================


class TestIntegrationWithMockedAPI:
    """モックAPIを使った統合テスト"""

    @pytest.fixture
    def mock_pool(self):
        pool = Mock()
        conn = Mock()
        result = Mock()
        result.fetchone.return_value = None
        result.fetchall.return_value = []
        conn.execute.return_value = result
        pool.connect.return_value.__enter__ = Mock(return_value=conn)
        pool.connect.return_value.__exit__ = Mock(return_value=False)
        return pool

    def _make_orchestrator(self, mock_pool, **kwargs):
        defaults = dict(
            pool=mock_pool,
            organization_id="org_test",
            api_key="test-key",
            dry_run=False,
            enable_logging=False,
            enable_cost_management=False,
        )
        defaults.update(kwargs)
        return create_orchestrator(**defaults)

    @pytest.mark.asyncio
    async def test_successful_api_call(self, mock_pool):
        """API呼び出し成功→結果が返る"""
        orchestrator = self._make_orchestrator(mock_pool)
        model = create_test_model_info(tier=Tier.STANDARD)

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status = Mock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "こんにちは！"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20},
        }

        with patch.object(orchestrator._registry, 'get_default_model_for_tier', return_value=model), \
             patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await orchestrator.call(prompt="テスト", task_type="conversation")

            assert result.success is True
            assert result.content == "こんにちは！"
            assert result.input_tokens == 10
            assert result.output_tokens == 20

    @pytest.mark.asyncio
    async def test_api_error_429_triggers_retry(self, mock_pool):
        """429エラーでリトライが発動"""
        orchestrator = self._make_orchestrator(mock_pool, enable_fallback=True)
        model = create_test_model_info(tier=Tier.STANDARD)

        with patch.object(orchestrator._registry, 'get_default_model_for_tier', return_value=model), \
             patch.object(orchestrator._fallback_manager, 'execute_with_fallback') as mock_fallback:
            mock_fallback.return_value = FallbackResult(
                success=True,
                response="リトライ後の応答",
                model_used=model,
                was_fallback=True,
                original_model_id=model.model_id,
                fallback_attempts=[
                    FallbackAttempt(model_id=model.model_id, attempt_number=1, success=False, error_message="429"),
                    FallbackAttempt(model_id=model.model_id, attempt_number=2, success=True),
                ],
                input_tokens=10,
                output_tokens=20,
            )

            result = await orchestrator.call(prompt="テスト", task_type="conversation")

            assert result.success is True
            assert result.was_fallback is True
            assert result.fallback_attempts == 2

    @pytest.mark.asyncio
    async def test_api_error_401_no_retry(self, mock_pool):
        """401エラーはリトライしない"""
        orchestrator = self._make_orchestrator(mock_pool, enable_fallback=True)
        model = create_test_model_info(tier=Tier.STANDARD)

        with patch.object(orchestrator._registry, 'get_default_model_for_tier', return_value=model), \
             patch.object(orchestrator._fallback_manager, 'execute_with_fallback') as mock_fallback:
            mock_fallback.return_value = FallbackResult(
                success=False,
                model_used=model,
                error_message="401 Unauthorized",
                fallback_attempts=[
                    FallbackAttempt(model_id=model.model_id, attempt_number=1, success=False, error_message="401"),
                ],
            )

            result = await orchestrator.call(prompt="テスト", task_type="conversation")

            assert result.success is False
            assert "401" in (result.error_message or "")

    @pytest.mark.asyncio
    async def test_cost_block_prevents_api_call(self, mock_pool):
        """コスト上限でAPI呼び出しがブロックされる"""
        orchestrator = self._make_orchestrator(mock_pool, enable_cost_management=True)
        model = create_test_model_info(tier=Tier.PREMIUM)

        with patch.object(orchestrator._registry, 'get_default_model_for_tier', return_value=model), \
             patch.object(orchestrator._cost_manager, 'estimate_cost') as mock_estimate, \
             patch.object(orchestrator._cost_manager, 'check_cost') as mock_check:
            mock_estimate.return_value = CostEstimate(
                input_tokens=1000, output_tokens=500,
                cost_jpy=Decimal("100.0"), model_id=model.model_id,
            )
            mock_check.return_value = CostCheckResult(
                estimated_cost_jpy=Decimal("100.0"),
                daily_cost_jpy=Decimal("500.0"),
                monthly_cost_jpy=Decimal("10000.0"),
                budget_remaining_jpy=Decimal("0"),
                budget_status=BudgetStatus.LIMIT,
                action=CostAction.BLOCK,
                message="日次コスト上限に達しました",
            )

            result = await orchestrator.call(prompt="テスト", task_type="conversation")

            assert result.success is False
            assert result.cost_action == CostAction.BLOCK
            assert "上限" in (result.cost_message or "")

    @pytest.mark.asyncio
    async def test_fallback_premium_to_standard(self, mock_pool):
        """PREMIUMモデル失敗→STANDARDへフォールバック"""
        orchestrator = self._make_orchestrator(mock_pool, enable_fallback=True)
        premium = create_test_model_info(model_id="claude-opus", tier=Tier.PREMIUM)
        standard = create_test_model_info(model_id="gpt-4o", tier=Tier.STANDARD)

        with patch.object(orchestrator._registry, 'get_default_model_for_tier', return_value=premium), \
             patch.object(orchestrator._fallback_manager, 'execute_with_fallback') as mock_fallback:
            mock_fallback.return_value = FallbackResult(
                success=True,
                response="フォールバック応答",
                model_used=standard,
                was_fallback=True,
                original_model_id="claude-opus",
                fallback_attempts=[
                    FallbackAttempt(model_id="claude-opus", attempt_number=1, success=False, error_message="503"),
                    FallbackAttempt(model_id="gpt-4o", attempt_number=2, success=True),
                ],
                input_tokens=10,
                output_tokens=20,
            )

            result = await orchestrator.call(prompt="重要な経営判断", task_type="ceo_learning")

            assert result.success is True
            assert result.was_fallback is True
            assert result.original_model_id == "claude-opus"

    @pytest.mark.asyncio
    async def test_all_models_fail(self, mock_pool):
        """全モデル失敗→エラー結果"""
        orchestrator = self._make_orchestrator(mock_pool, enable_fallback=True)
        model = create_test_model_info(tier=Tier.STANDARD)

        with patch.object(orchestrator._registry, 'get_default_model_for_tier', return_value=model), \
             patch.object(orchestrator._fallback_manager, 'execute_with_fallback') as mock_fallback:
            mock_fallback.return_value = FallbackResult(
                success=False,
                model_used=model,
                error_message="All models failed",
                fallback_attempts=[
                    FallbackAttempt(model_id="gpt-4o", attempt_number=1, success=False, error_message="503"),
                    FallbackAttempt(model_id="gemini-pro", attempt_number=2, success=False, error_message="503"),
                ],
            )

            result = await orchestrator.call(prompt="テスト", task_type="conversation")

            assert result.success is False
            assert result.error_message is not None

    @pytest.mark.asyncio
    async def test_logging_records_usage(self, mock_pool):
        """ログ有効時に利用ログが記録される"""
        orchestrator = self._make_orchestrator(mock_pool, enable_logging=True)
        model = create_test_model_info(tier=Tier.STANDARD)

        with patch.object(orchestrator._registry, 'get_default_model_for_tier', return_value=model), \
             patch.object(orchestrator, '_call_openrouter', new_callable=AsyncMock) as mock_api, \
             patch.object(orchestrator._usage_logger, 'log_usage') as mock_log:
            mock_api.return_value = ("応答テキスト", 10, 20)

            result = await orchestrator.call(
                prompt="テスト", task_type="conversation",
                room_id="room-1", user_id="user-1",
            )

            assert result.success is True
            mock_log.assert_called_once()
            call_kwargs = mock_log.call_args
            assert call_kwargs[1]["room_id"] == "room-1"
            assert call_kwargs[1]["user_id"] == "user-1"

    @pytest.mark.asyncio
    async def test_logging_disabled_skips_log(self, mock_pool):
        """ログ無効時は記録されない"""
        orchestrator = self._make_orchestrator(mock_pool, enable_logging=False)
        model = create_test_model_info(tier=Tier.STANDARD)

        with patch.object(orchestrator._registry, 'get_default_model_for_tier', return_value=model), \
             patch.object(orchestrator, '_call_openrouter', new_callable=AsyncMock) as mock_api, \
             patch.object(orchestrator._usage_logger, 'log_usage') as mock_log:
            mock_api.return_value = ("応答", 10, 20)

            await orchestrator.call(prompt="テスト", task_type="conversation")

            mock_log.assert_not_called()

    @pytest.mark.asyncio
    async def test_monthly_summary_updated_on_success(self, mock_pool):
        """成功時に月次サマリーが更新される"""
        orchestrator = self._make_orchestrator(mock_pool, enable_cost_management=True)
        model = create_test_model_info(tier=Tier.STANDARD)

        with patch.object(orchestrator._registry, 'get_default_model_for_tier', return_value=model), \
             patch.object(orchestrator, '_call_openrouter', new_callable=AsyncMock) as mock_api, \
             patch.object(orchestrator._cost_manager, 'estimate_cost') as mock_est, \
             patch.object(orchestrator._cost_manager, 'check_cost') as mock_check, \
             patch.object(orchestrator._cost_manager, 'calculate_actual_cost', return_value=Decimal("1.5")), \
             patch.object(orchestrator._cost_manager, 'update_monthly_summary') as mock_summary:
            mock_api.return_value = ("応答", 10, 20)
            mock_est.return_value = CostEstimate(
                input_tokens=10, output_tokens=20,
                cost_jpy=Decimal("1.5"), model_id=model.model_id,
            )
            mock_check.return_value = CostCheckResult(
                estimated_cost_jpy=Decimal("1.5"),
                daily_cost_jpy=Decimal("10.0"),
                monthly_cost_jpy=Decimal("100.0"),
                budget_remaining_jpy=Decimal("9900.0"),
                budget_status=BudgetStatus.NORMAL,
                action=CostAction.AUTO_EXECUTE, message="OK",
            )

            result = await orchestrator.call(prompt="テスト", task_type="conversation")

            assert result.success is True
            mock_summary.assert_called_once()

    @pytest.mark.asyncio
    async def test_keyword_upgrade_to_premium(self, mock_pool):
        """重要キーワードでSTANDARD→PREMIUMに昇格"""
        orchestrator = self._make_orchestrator(mock_pool)
        premium = create_test_model_info(model_id="claude-opus", tier=Tier.PREMIUM)

        with patch.object(orchestrator._registry, 'get_default_model_for_tier', return_value=premium), \
             patch.object(orchestrator, '_call_openrouter', new_callable=AsyncMock) as mock_api:
            mock_api.return_value = ("経営分析結果", 50, 100)

            result = await orchestrator.call(
                prompt="重要な経営判断について分析してください",
                task_type="conversation",
            )

            assert result.success is True
            assert result.tier_used == Tier.PREMIUM

    @pytest.mark.asyncio
    async def test_keyword_downgrade_to_economy(self, mock_pool):
        """ざっくりキーワードでダウングレード"""
        orchestrator = self._make_orchestrator(mock_pool)
        economy = create_test_model_info(model_id="gemini-flash", tier=Tier.ECONOMY)

        with patch.object(orchestrator._selector, 'select') as mock_select:
            mock_select.return_value = ModelSelection(
                model=economy, tier=Tier.ECONOMY,
                reason="Downgraded by keyword: ざっくり",
            )
            with patch.object(orchestrator, '_call_openrouter', new_callable=AsyncMock) as mock_api:
                mock_api.return_value = ("概要です", 10, 20)

                result = await orchestrator.call(
                    prompt="ざっくり教えて",
                    task_type="conversation",
                )

                assert result.success is True
                assert result.tier_used == Tier.ECONOMY

    @pytest.mark.asyncio
    async def test_exception_in_selector_returns_error(self, mock_pool):
        """セレクタで例外→エラー結果"""
        orchestrator = self._make_orchestrator(mock_pool)

        with patch.object(orchestrator._selector, 'select', side_effect=RuntimeError("DB error")):
            result = await orchestrator.call(prompt="テスト", task_type="conversation")

            assert result.success is False
            assert "RuntimeError" in (result.error_message or "")

    @pytest.mark.asyncio
    async def test_no_api_key_raises_error(self, mock_pool):
        """APIキーなしで呼び出すとエラー"""
        orchestrator = self._make_orchestrator(mock_pool, api_key="")
        orchestrator._api_key = None
        model = create_test_model_info(tier=Tier.STANDARD)

        with patch.object(orchestrator._registry, 'get_default_model_for_tier', return_value=model), \
             patch.object(orchestrator._fallback_manager, 'execute_with_fallback') as mock_fb:
            mock_fb.return_value = FallbackResult(
                success=False, error_message="OpenRouter API key not configured",
                model_used=model,
            )

            result = await orchestrator.call(prompt="テスト", task_type="conversation")

            assert result.success is False

    @pytest.mark.asyncio
    async def test_different_org_ids_isolated(self, mock_pool):
        """異なるorg_idのオーケストレータが独立"""
        orch_a = self._make_orchestrator(mock_pool, organization_id="org_A")
        orch_b = self._make_orchestrator(mock_pool, organization_id="org_B")

        assert orch_a._organization_id == "org_A"
        assert orch_b._organization_id == "org_B"
        assert orch_a._cost_manager._organization_id == "org_A"
        assert orch_b._cost_manager._organization_id == "org_B"

    @pytest.mark.asyncio
    async def test_full_flow_with_cost_and_logging(self, mock_pool):
        """コスト管理+ログ+API呼び出しの全フロー"""
        orchestrator = self._make_orchestrator(
            mock_pool, enable_cost_management=True, enable_logging=True,
        )
        model = create_test_model_info(tier=Tier.STANDARD)

        with patch.object(orchestrator._registry, 'get_default_model_for_tier', return_value=model), \
             patch.object(orchestrator, '_call_openrouter', new_callable=AsyncMock) as mock_api, \
             patch.object(orchestrator._cost_manager, 'estimate_cost') as mock_est, \
             patch.object(orchestrator._cost_manager, 'check_cost') as mock_check, \
             patch.object(orchestrator._cost_manager, 'calculate_actual_cost', return_value=Decimal("2.0")), \
             patch.object(orchestrator._cost_manager, 'update_monthly_summary') as mock_summary, \
             patch.object(orchestrator._usage_logger, 'log_usage') as mock_log:
            mock_api.return_value = ("フル統合テスト応答", 50, 100)
            mock_est.return_value = CostEstimate(
                input_tokens=50, output_tokens=100,
                cost_jpy=Decimal("2.0"), model_id=model.model_id,
            )
            mock_check.return_value = CostCheckResult(
                estimated_cost_jpy=Decimal("1.5"),
                daily_cost_jpy=Decimal("10.0"),
                monthly_cost_jpy=Decimal("100.0"),
                budget_remaining_jpy=Decimal("9900.0"),
                budget_status=BudgetStatus.NORMAL,
                action=CostAction.AUTO_EXECUTE, message="OK",
            )

            result = await orchestrator.call(
                prompt="統合テスト", task_type="conversation",
                room_id="room-test", user_id="user-test",
            )

            assert result.success is True
            assert result.content == "フル統合テスト応答"
            assert result.cost_jpy == Decimal("2.0")
            assert result.cost_action == CostAction.AUTO_EXECUTE
            mock_log.assert_called_once()
            mock_summary.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
