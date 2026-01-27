"""
Model Orchestrator パッケージ

全AI呼び出しを統括するModel Orchestratorを提供します。

Phase 0: 次世代能力設計書
設計書: docs/20_next_generation_capabilities.md

使用例:
    from lib.brain.model_orchestrator import ModelOrchestrator, create_orchestrator

    # Orchestratorを作成
    orchestrator = create_orchestrator(
        pool=db_pool,
        organization_id="org_123",
    )

    # AI呼び出し
    result = await orchestrator.call(
        prompt="質問に回答してください",
        task_type="conversation",
    )

    if result.success:
        print(result.content)
        print(f"コスト: ¥{result.cost_jpy:.2f}")
"""

__version__ = "1.0.0"
__author__ = "Claude Opus 4.5"

# メインクラス
from .orchestrator import (
    ModelOrchestrator,
    OrchestratorResult,
    OrchestratorConfig,
    create_orchestrator,
)

# サブコンポーネント
from .registry import (
    ModelRegistry,
    ModelInfo,
)

from .model_selector import (
    ModelSelector,
    ModelSelection,
)

from .cost_manager import (
    CostManager,
    CostCheckResult,
    CostAction,
    CostEstimate,
    OrganizationSettings,
)

from .fallback_manager import (
    FallbackManager,
    FallbackResult,
    FallbackAttempt,
    APIError,
)

from .usage_logger import (
    UsageLogger,
    UsageLogEntry,
    UsageStats,
)

# 定数
from .constants import (
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
)

# 公開API
__all__ = [
    # バージョン
    "__version__",

    # メインクラス
    "ModelOrchestrator",
    "OrchestratorResult",
    "OrchestratorConfig",
    "create_orchestrator",

    # サブコンポーネント
    "ModelRegistry",
    "ModelInfo",
    "ModelSelector",
    "ModelSelection",
    "CostManager",
    "CostCheckResult",
    "CostAction",
    "CostEstimate",
    "OrganizationSettings",
    "FallbackManager",
    "FallbackResult",
    "FallbackAttempt",
    "APIError",
    "UsageLogger",
    "UsageLogEntry",
    "UsageStats",

    # 定数
    "Tier",
    "BudgetStatus",
    "CostThreshold",
    "MonthlyBudget",
    "TASK_TYPE_TIERS",
    "DEFAULT_TIER",
    "TIER_UPGRADE_KEYWORDS",
    "TIER_DOWNGRADE_KEYWORDS",
    "FALLBACK_CHAINS",
    "MAX_RETRIES",
    "FEATURE_FLAG_NAME",
]
