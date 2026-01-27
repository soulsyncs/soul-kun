# lib/brain/__init__.py
"""
ソウルくんの脳アーキテクチャ

このモジュールは、ソウルくんの中央処理装置（脳）を提供します。
全てのユーザー入力は、まずこの脳を通って処理されます。

設計書: docs/13_brain_architecture.md
設計書: docs/14_brain_refactoring_plan.md（Phase B: SYSTEM_CAPABILITIES拡張）
設計書: docs/18_phase2e_learning_foundation.md（Phase 2E: 学習基盤）

【7つの鉄則】
1. 全ての入力は脳を通る（バイパスルート禁止）
2. 脳は全ての記憶にアクセスできる
3. 脳が判断し、機能は実行するだけ
4. 機能拡張しても脳の構造は変わらない → カタログへの追加のみで対応
5. 確認は脳の責務
6. 状態管理は脳が統一管理
7. 速度より正確性を優先

【v10.33.0 変更点】Phase 2E: 学習基盤
- BrainLearning統合クラスを追加
- フィードバック検出（18パターン対応）
- 学習の保存・適用・管理機能
- 矛盾検出と解決（CEO教え優先）
- 権限レベル管理（ceo > manager > user > system）
- 有効性追跡（Phase 2N準備）

【v10.30.0 変更点】
- CAPABILITY_KEYWORDSとINTENT_KEYWORDSを非推奨化
- SYSTEM_CAPABILITIESのbrain_metadataから動的にキーワード辞書を構築
- validate_capabilities_handlers()で整合性チェックを追加
- 新機能追加時はSYSTEM_CAPABILITIESへの追加のみで対応可能に

使用例:
    from lib.brain import SoulkunBrain, BrainResponse

    brain = SoulkunBrain(pool=db_pool, org_id="org_soulsyncs")
    response = await brain.process_message(
        message="自分のタスク教えて",
        room_id="123456",
        account_id="7890",
        sender_name="菊地"
    )
    print(response.message)  # タスク一覧を表示

バリデーション使用例:
    from lib.brain import validate_capabilities_handlers, check_capabilities_coverage

    # 整合性チェック
    result = validate_capabilities_handlers(SYSTEM_CAPABILITIES, handlers)
    if not result.is_valid:
        for error in result.errors:
            print(f"ERROR: {error.action}: {error.message}")

    # カバレッジ確認
    coverage = check_capabilities_coverage(SYSTEM_CAPABILITIES)
    print(f"brain_metadata coverage: {coverage['percentage']:.1f}%")
"""

from lib.brain.models import (
    BrainContext,
    BrainResponse,
    UnderstandingResult,
    DecisionResult,
    HandlerResult,
    ConversationState,
    ConfirmationRequest,
    ActionCandidate,
    MemoryType,
    StateType,
    # Phase 2D: CEO Learning & Guardian
    TeachingCategory,
    ValidationStatus,
    ConflictType,
    AlertStatus,
    Severity,
    CEOTeaching,
    ConflictInfo,
    GuardianAlert,
    TeachingValidationResult,
    TeachingUsageContext,
    CEOTeachingContext,
)

from lib.brain.core import SoulkunBrain

from lib.brain.state_manager import BrainStateManager

from lib.brain.memory_access import (
    BrainMemoryAccess,
    ConversationMessage,
    ConversationSummaryData,
    UserPreferenceData,
    PersonInfo,
    TaskInfo,
    GoalInfo,
    KnowledgeInfo,
    InsightInfo,
)

from lib.brain.exceptions import (
    BrainError,
    UnderstandingError,
    DecisionError,
    ExecutionError,
    StateError,
    MemoryAccessError,
    ConfirmationTimeoutError,
)

from lib.brain.constants import (
    CANCEL_KEYWORDS,
    CONFIRMATION_THRESHOLD,
    SESSION_TIMEOUT_MINUTES,
    MAX_RETRY_COUNT,
)

from lib.brain.integration import (
    BrainIntegration,
    IntegrationResult,
    IntegrationConfig,
    IntegrationMode,
    BypassType,
    BypassDetectionResult,
    create_integration,
    is_brain_enabled,
    FEATURE_FLAG_NAME,
)

from lib.brain.validation import (
    ValidationResult,
    ValidationError,
    validate_capabilities_handlers,
    validate_brain_metadata,
    check_capabilities_coverage,
)

# Phase 2D: CEO Learning & Guardian
from lib.brain.ceo_teaching_repository import (
    CEOTeachingRepository,
    ConflictRepository,
    GuardianAlertRepository,
    TeachingUsageRepository,
)

from lib.brain.ceo_learning import (
    CEOLearningService,
    ExtractedTeaching,
    ProcessingResult,
    format_teachings_for_prompt,
    should_include_teachings,
    CEO_ACCOUNT_IDS,
    TEACHING_CONFIDENCE_THRESHOLD,
    CATEGORY_KEYWORDS,
)

from lib.brain.guardian import (
    GuardianService,
    MVV_VALIDATION_CRITERIA,
    CHOICE_THEORY_CRITERIA,
    SDT_CRITERIA,
)

# Ultimate Brain - Phase 1: Chain-of-Thought & Self-Critique
from lib.brain.chain_of_thought import (
    ChainOfThought,
    create_chain_of_thought,
    # Enum
    InputType,
    StructureElement,
    # データモデル
    ThoughtStep,
    PossibleIntent,
    StructureAnalysis,
    ThoughtChain,
    # 定数
    INPUT_TYPE_PATTERNS,
    INTENT_KEYWORDS,
)

from lib.brain.self_critique import (
    SelfCritique,
    create_self_critique,
    # Enum
    QualityCriterion,
    IssueType,
    IssueSeverity,
    # データモデル
    QualityScore,
    DetectedIssue,
    CritiqueResult,
    RefinedResponse,
    # 定数
    QUALITY_THRESHOLDS,
    OVERALL_REFINEMENT_THRESHOLD,
)

# Phase 2E: Learning Foundation
from lib.brain.learning_foundation import (
    # 統合クラス
    BrainLearning,
    create_brain_learning,
    # Enum
    LearningCategory,
    LearningScope,
    AuthorityLevel as LearningAuthorityLevel,
    TriggerType,
    RelationshipType,
    DecisionImpact,
    ConflictResolutionStrategy,
    ConflictType as LearningConflictType,
    # データモデル
    Learning,
    LearningLog,
    FeedbackDetectionResult,
    ConversationContext as LearningConversationContext,
    ConflictInfo as LearningConflictInfo,
    Resolution,
    AppliedLearning,
    EffectivenessResult,
    ImprovementSuggestion,
    # パターン
    DetectionPattern,
    ALL_PATTERNS,
    PATTERNS_BY_NAME,
    PATTERNS_BY_CATEGORY,
    # クラス
    FeedbackDetector,
    LearningExtractor,
    LearningRepository,
    LearningApplier,
    LearningApplierWithCeoCheck,
    LearningManager,
    ConflictDetector as LearningConflictDetector,
    AuthorityResolver,
    AuthorityResolverWithDb,
    EffectivenessTracker,
    EffectivenessMetrics,
    LearningHealth,
    # 定数
    AUTHORITY_PRIORITY,
    CONFIDENCE_THRESHOLD_AUTO_LEARN,
    CONFIDENCE_THRESHOLD_CONFIRM,
    CONFIDENCE_THRESHOLD_MIN,
)

__all__ = [
    # メインクラス
    "SoulkunBrain",
    # 状態管理層
    "BrainStateManager",
    # 記憶アクセス層
    "BrainMemoryAccess",
    "ConversationMessage",
    "ConversationSummaryData",
    "UserPreferenceData",
    "PersonInfo",
    "TaskInfo",
    "GoalInfo",
    "KnowledgeInfo",
    "InsightInfo",
    # データモデル
    "BrainContext",
    "BrainResponse",
    "UnderstandingResult",
    "DecisionResult",
    "HandlerResult",
    "ConversationState",
    "ConfirmationRequest",
    "ActionCandidate",
    # Enum
    "MemoryType",
    "StateType",
    # 例外
    "BrainError",
    "UnderstandingError",
    "DecisionError",
    "ExecutionError",
    "StateError",
    "MemoryAccessError",
    "ConfirmationTimeoutError",
    # 定数
    "CANCEL_KEYWORDS",
    "CONFIRMATION_THRESHOLD",
    "SESSION_TIMEOUT_MINUTES",
    "MAX_RETRY_COUNT",
    # 統合層
    "BrainIntegration",
    "IntegrationResult",
    "IntegrationConfig",
    "IntegrationMode",
    "BypassType",
    "BypassDetectionResult",
    "create_integration",
    "is_brain_enabled",
    "FEATURE_FLAG_NAME",
    # バリデーション層（v10.30.0）
    "ValidationResult",
    "ValidationError",
    "validate_capabilities_handlers",
    "validate_brain_metadata",
    "check_capabilities_coverage",
    # Phase 2D: CEO Learning & Guardian（v10.32.0）
    # データモデル
    "TeachingCategory",
    "ValidationStatus",
    "ConflictType",
    "AlertStatus",
    "Severity",
    "CEOTeaching",
    "ConflictInfo",
    "GuardianAlert",
    "TeachingValidationResult",
    "TeachingUsageContext",
    "CEOTeachingContext",
    # リポジトリ
    "CEOTeachingRepository",
    "ConflictRepository",
    "GuardianAlertRepository",
    "TeachingUsageRepository",
    # CEO学習層
    "CEOLearningService",
    "ExtractedTeaching",
    "ProcessingResult",
    "format_teachings_for_prompt",
    "should_include_teachings",
    "CEO_ACCOUNT_IDS",
    "TEACHING_CONFIDENCE_THRESHOLD",
    "CATEGORY_KEYWORDS",
    # ガーディアン層
    "GuardianService",
    "MVV_VALIDATION_CRITERIA",
    "CHOICE_THEORY_CRITERIA",
    "SDT_CRITERIA",
    # Phase 2E: Learning Foundation（v10.33.0）
    # 統合クラス
    "BrainLearning",
    "create_brain_learning",
    # Enum
    "LearningCategory",
    "LearningScope",
    "LearningAuthorityLevel",
    "TriggerType",
    "RelationshipType",
    "DecisionImpact",
    "ConflictResolutionStrategy",
    "LearningConflictType",
    # データモデル
    "Learning",
    "LearningLog",
    "FeedbackDetectionResult",
    "LearningConversationContext",
    "LearningConflictInfo",
    "Resolution",
    "AppliedLearning",
    "EffectivenessResult",
    "ImprovementSuggestion",
    # パターン
    "DetectionPattern",
    "ALL_PATTERNS",
    "PATTERNS_BY_NAME",
    "PATTERNS_BY_CATEGORY",
    # クラス
    "FeedbackDetector",
    "LearningExtractor",
    "LearningRepository",
    "LearningApplier",
    "LearningApplierWithCeoCheck",
    "LearningManager",
    "LearningConflictDetector",
    "AuthorityResolver",
    "AuthorityResolverWithDb",
    "EffectivenessTracker",
    "EffectivenessMetrics",
    "LearningHealth",
    # 定数
    "AUTHORITY_PRIORITY",
    "CONFIDENCE_THRESHOLD_AUTO_LEARN",
    "CONFIDENCE_THRESHOLD_CONFIRM",
    "CONFIDENCE_THRESHOLD_MIN",
    # Ultimate Brain - Phase 1: Chain-of-Thought & Self-Critique
    # 思考連鎖
    "ChainOfThought",
    "create_chain_of_thought",
    "InputType",
    "StructureElement",
    "ThoughtStep",
    "PossibleIntent",
    "StructureAnalysis",
    "ThoughtChain",
    "INPUT_TYPE_PATTERNS",
    "INTENT_KEYWORDS",
    # 自己批判
    "SelfCritique",
    "create_self_critique",
    "QualityCriterion",
    "IssueType",
    "IssueSeverity",
    "QualityScore",
    "DetectedIssue",
    "CritiqueResult",
    "RefinedResponse",
    "QUALITY_THRESHOLDS",
    "OVERALL_REFINEMENT_THRESHOLD",
]

__version__ = "2.1.0"  # v10.34.0: Ultimate Brain Phase 1 - Chain-of-Thought & Self-Critique
