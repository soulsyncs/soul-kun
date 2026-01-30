# lib/brain/__init__.py
"""
ソウルくんの脳アーキテクチャ

このモジュールは、ソウルくんの中央処理装置（脳）を提供します。
全てのユーザー入力は、まずこの脳を通って処理されます。

設計書: docs/13_brain_architecture.md
設計書: docs/14_brain_refactoring_plan.md（Phase B: SYSTEM_CAPABILITIES拡張）
設計書: docs/17_brain_completion_roadmap.md（Phase 2I: 理解力強化）
設計書: docs/18_phase2e_learning_foundation.md（Phase 2E: 学習基盤）
設計書: docs/19_ultimate_brain_architecture.md（Ultimate Brain: 高度な認知能力）

【v10.37.0 変更点】Phase 3: Multi-Agent System
- 専門家エージェント群を追加（7種類）
  - Orchestrator: 全エージェントを統括する脳
  - TaskExpert: タスク管理の専門家
  - GoalExpert: 目標達成支援の専門家
  - KnowledgeExpert: ナレッジ管理の専門家
  - HRExpert: 人事・労務の専門家
  - EmotionExpert: 感情ケアの専門家
  - OrganizationExpert: 組織構造の専門家
- エージェント間通信プロトコル（AgentMessage, AgentResponse）
- 能力ベースのルーティング（キーワードスコアリング）
- 並列実行サポート

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

# =============================================================================
# バージョン定義（単一ソース）
# =============================================================================
# このバージョンはCloud Loggingの出力で使用される
# デプロイ時に手動更新すること
BRAIN_VERSION = "10.48.1"

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
    # v10.42.0 P0: Guardian Gate
    GuardianActionType,
    GuardianActionResult,
    MVV_VALIDATION_CRITERIA,
    CHOICE_THEORY_CRITERIA,
    SDT_CRITERIA,
)

# v10.42.0 P1: Decision Layer Enforcement
from lib.brain.decision import (
    EnforcementAction,
    MVVCheckResult,
)

# v10.42.0 P3: Value Authority Layer
from lib.brain.value_authority import (
    ValueAuthority,
    ValueAuthorityResult,
    ValueDecision,
    create_value_authority,
    LIFE_AXIS_VIOLATION_PATTERNS,
    GOAL_CONTRADICTION_PATTERNS,
)

# v10.43.0 P4: Memory Authority Layer
from lib.brain.memory_authority import (
    MemoryAuthority,
    MemoryAuthorityResult,
    MemoryDecision,
    MemoryConflict,
    create_memory_authority,
    normalize_text,
    extract_keywords,
    has_keyword_match,
    calculate_overlap_score,
    HARD_CONFLICT_PATTERNS,
    SOFT_CONFLICT_PATTERNS,
    ALIGNMENT_PATTERNS,
)

# v10.43.1 P4: Memory Authority Observation Logger
from lib.brain.memory_authority_logger import (
    MemoryAuthorityLogger,
    SoftConflictLog,
    get_memory_authority_logger,
    create_memory_authority_logger,
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

# Ultimate Brain - Phase 2: Confidence Calibration
from lib.brain.confidence import (
    ConfidenceCalibrator,
    create_confidence_calibrator,
    # Enum
    RiskLevel,
    ConfidenceAction,
    # データモデル
    ConfidenceAdjustment,
    CalibratedDecision,
    # 定数
    CONFIDENCE_THRESHOLDS,
    AMBIGUOUS_PATTERNS,
    CONFIRMATION_TEMPLATES,
)

# Ultimate Brain - Phase 2: Episodic Memory
from lib.brain.episodic_memory import (
    EpisodicMemory,
    create_episodic_memory,
    # Enum
    EpisodeType,
    RecallTrigger,
    # データモデル
    Episode,
    RecallResult,
    RelatedEntity,
    # 定数
    DECAY_RATE_PER_DAY,
    MAX_RECALL_COUNT,
    BASE_IMPORTANCE,
    IMPORTANT_KEYWORDS,
)

# Ultimate Brain - Phase 2: Proactive Monitoring
from lib.brain.proactive import (
    ProactiveMonitor,
    create_proactive_monitor,
    # Enum
    TriggerType as ProactiveTriggerType,
    ProactiveMessageType,
    ActionPriority,
    # データモデル
    Trigger as ProactiveTrigger,
    ProactiveMessage,
    ProactiveAction,
    UserContext,
    CheckResult,
    # 定数
    GOAL_ABANDONED_DAYS,
    TASK_OVERLOAD_COUNT,
    EMOTION_DECLINE_DAYS,
    MESSAGE_COOLDOWN_HOURS,
    TRIGGER_PRIORITY,
    MESSAGE_TEMPLATES,
)

# Ultimate Brain - Phase 3: Learning Loop
from lib.brain.learning_loop import (
    LearningLoop,
    create_learning_loop,
    # Enum
    FeedbackType,
    FailureCause,
    ImprovementType,
    LearningStatus,
    # データモデル
    Feedback,
    DecisionSnapshot,
    FailureAnalysis,
    Improvement,
    LearningEntry,
    LearningStatistics,
    # 定数
    LEARNING_HISTORY_RETENTION_DAYS,
    MIN_SAMPLES_FOR_IMPROVEMENT,
    THRESHOLD_MIN,
    THRESHOLD_MAX,
    THRESHOLD_ADJUSTMENT_STEP,
    PATTERN_MIN_CONFIDENCE,
    DEFAULT_KEYWORD_WEIGHT,
    LEARNING_LOG_BUFFER_SIZE,
    ANALYSIS_DECISION_LOOKBACK,
    EFFECTIVENESS_MEASUREMENT_DAYS,
)

# Ultimate Brain - Phase 3: Organization Graph
from lib.brain.org_graph import (
    OrganizationGraph,
    create_organization_graph,
    # Enum
    RelationshipType as OrgRelationshipType,
    CommunicationStyle,
    InteractionType,
    ExpertiseArea,
    # データモデル
    PersonNode,
    PersonRelationship,
    Interaction as OrgInteraction,
    OrganizationGraphStats,
    RelationshipInsight,
    # 定数
    INFLUENCE_SCORE_MIN,
    INFLUENCE_SCORE_MAX,
    INFLUENCE_SCORE_DEFAULT,
    TRUST_LEVEL_MIN,
    TRUST_LEVEL_MAX,
    TRUST_LEVEL_DEFAULT,
    RELATIONSHIP_STRENGTH_MIN,
    RELATIONSHIP_STRENGTH_MAX,
    RELATIONSHIP_STRENGTH_DEFAULT,
    INTERACTION_HISTORY_DAYS,
    STRENGTH_DECAY_RATE,
    TRUST_DECAY_RATE,
    MIN_INTERACTIONS_FOR_RELATIONSHIP,
    STRENGTH_INCREMENT,
    TRUST_INCREMENT,
    GRAPH_CACHE_TTL,
)

# Ultimate Brain - Phase 3: Multi-Agent System
from lib.brain import agents

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

# Phase 2F: Outcome Learning
from lib.brain.outcome_learning import (
    # 統合クラス
    BrainOutcomeLearning,
    create_outcome_learning,
    # コンポーネント
    OutcomeTracker,
    ImplicitFeedbackDetector,
    PatternExtractor,
    OutcomeAnalyzer,
    OutcomeRepository,
    # Enum
    EventType,
    FeedbackSignal,
    OutcomeType,
    PatternScope,
    PatternType,
    # データモデル
    OutcomeEvent,
    ImplicitFeedback,
    OutcomePattern,
    OutcomeInsight,
    OutcomeStatistics,
)

# Phase 0: Model Orchestrator（次世代能力）
from lib.brain.model_orchestrator import (
    # メインクラス
    ModelOrchestrator,
    OrchestratorResult,
    OrchestratorConfig,
    create_orchestrator,
    # サブコンポーネント
    ModelRegistry,
    ModelInfo,
    ModelSelector,
    ModelSelection,
    CostManager,
    CostCheckResult,
    CostAction,
    CostEstimate,
    OrganizationSettings,
    FallbackManager,
    FallbackResult,
    FallbackAttempt,
    APIError,
    UsageLogger,
    UsageLogEntry,
    UsageStats,
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
    FEATURE_FLAG_NAME as MODEL_ORCHESTRATOR_FLAG_NAME,
)

# Phase 2I: Deep Understanding（理解力強化）
from lib.brain.deep_understanding import (
    # 統合クラス
    DeepUnderstanding,
    create_deep_understanding,
    # コンポーネント
    IntentInferenceEngine,
    EmotionReader,
    VocabularyManager,
    HistoryAnalyzer,
    # ファクトリー
    create_intent_inference_engine,
    create_emotion_reader,
    create_vocabulary_manager,
    create_history_analyzer,
    # Enum
    ImplicitIntentType,
    ReferenceResolutionStrategy,
    OrganizationContextType,
    VocabularyCategory,
    EmotionCategory,
    UrgencyLevel as DeepUrgencyLevel,
    NuanceType,
    ContextRecoverySource,
    # データモデル
    DeepUnderstandingInput,
    DeepUnderstandingOutput,
    ResolvedReference,
    ImplicitIntent,
    IntentInferenceResult,
    VocabularyEntry,
    OrganizationContext,
    OrganizationContextResult,
    DetectedEmotion,
    DetectedUrgency,
    DetectedNuance,
    EmotionReadingResult,
    ContextFragment,
    RecoveredContext,
    # Feature Flags
    FEATURE_FLAG_DEEP_UNDERSTANDING,
    FEATURE_FLAG_IMPLICIT_INTENT,
    FEATURE_FLAG_ORGANIZATION_CONTEXT,
    FEATURE_FLAG_EMOTION_READING,
    FEATURE_FLAG_VOCABULARY_LEARNING,
)

# v10.40.2: Handler Wrappers（main.pyから移行）
from lib.brain.handler_wrappers import (
    # ビルダー関数
    build_bypass_handlers,
    build_brain_handlers,
    build_session_handlers,
    get_session_management_functions,
    # v10.40.3: ポーリング処理
    validate_polling_message,
    should_skip_polling_message,
    process_polling_message,
    process_polling_room,
)

__all__ = [
    # バージョン
    "BRAIN_VERSION",
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
    # v10.42.0 P0: Guardian Gate
    "GuardianActionType",
    "GuardianActionResult",
    "MVV_VALIDATION_CRITERIA",
    "CHOICE_THEORY_CRITERIA",
    "SDT_CRITERIA",
    # v10.42.0 P1: Decision Layer Enforcement
    "EnforcementAction",
    "MVVCheckResult",
    # v10.42.0 P3: Value Authority Layer
    "ValueAuthority",
    "ValueAuthorityResult",
    "ValueDecision",
    "create_value_authority",
    "LIFE_AXIS_VIOLATION_PATTERNS",
    "GOAL_CONTRADICTION_PATTERNS",
    # v10.43.0 P4: Memory Authority Layer
    "MemoryAuthority",
    "MemoryAuthorityResult",
    "MemoryDecision",
    "MemoryConflict",
    "create_memory_authority",
    "normalize_text",
    "extract_keywords",
    "has_keyword_match",
    "calculate_overlap_score",
    "HARD_CONFLICT_PATTERNS",
    "SOFT_CONFLICT_PATTERNS",
    "ALIGNMENT_PATTERNS",
    # v10.43.1 P4: Memory Authority Observation Logger
    "MemoryAuthorityLogger",
    "SoftConflictLog",
    "get_memory_authority_logger",
    "create_memory_authority_logger",
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
    # Ultimate Brain - Phase 2: Confidence Calibration
    "ConfidenceCalibrator",
    "create_confidence_calibrator",
    "RiskLevel",
    "ConfidenceAction",
    "ConfidenceAdjustment",
    "CalibratedDecision",
    "CONFIDENCE_THRESHOLDS",
    "AMBIGUOUS_PATTERNS",
    "CONFIRMATION_TEMPLATES",
    # Ultimate Brain - Phase 2: Episodic Memory
    "EpisodicMemory",
    "create_episodic_memory",
    "EpisodeType",
    "RecallTrigger",
    "Episode",
    "RecallResult",
    "RelatedEntity",
    "DECAY_RATE_PER_DAY",
    "MAX_RECALL_COUNT",
    "BASE_IMPORTANCE",
    "IMPORTANT_KEYWORDS",
    # Ultimate Brain - Phase 2: Proactive Monitoring
    "ProactiveMonitor",
    "create_proactive_monitor",
    "ProactiveTriggerType",
    "ProactiveMessageType",
    "ActionPriority",
    "ProactiveTrigger",
    "ProactiveMessage",
    "ProactiveAction",
    "UserContext",
    "CheckResult",
    "GOAL_ABANDONED_DAYS",
    "TASK_OVERLOAD_COUNT",
    "EMOTION_DECLINE_DAYS",
    "MESSAGE_COOLDOWN_HOURS",
    "TRIGGER_PRIORITY",
    "MESSAGE_TEMPLATES",
    # Ultimate Brain - Phase 3: Learning Loop
    "LearningLoop",
    "create_learning_loop",
    "FeedbackType",
    "FailureCause",
    "ImprovementType",
    "LearningStatus",
    "Feedback",
    "DecisionSnapshot",
    "FailureAnalysis",
    "Improvement",
    "LearningEntry",
    "LearningStatistics",
    "LEARNING_HISTORY_RETENTION_DAYS",
    "MIN_SAMPLES_FOR_IMPROVEMENT",
    "THRESHOLD_MIN",
    "THRESHOLD_MAX",
    "THRESHOLD_ADJUSTMENT_STEP",
    "PATTERN_MIN_CONFIDENCE",
    "DEFAULT_KEYWORD_WEIGHT",
    "LEARNING_LOG_BUFFER_SIZE",
    "ANALYSIS_DECISION_LOOKBACK",
    "EFFECTIVENESS_MEASUREMENT_DAYS",
    # Ultimate Brain - Phase 3: Organization Graph
    "OrganizationGraph",
    "create_organization_graph",
    "OrgRelationshipType",
    "CommunicationStyle",
    "InteractionType",
    "ExpertiseArea",
    "PersonNode",
    "PersonRelationship",
    "OrgInteraction",
    "OrganizationGraphStats",
    "RelationshipInsight",
    "INFLUENCE_SCORE_MIN",
    "INFLUENCE_SCORE_MAX",
    "INFLUENCE_SCORE_DEFAULT",
    "TRUST_LEVEL_MIN",
    "TRUST_LEVEL_MAX",
    "TRUST_LEVEL_DEFAULT",
    "RELATIONSHIP_STRENGTH_MIN",
    "RELATIONSHIP_STRENGTH_MAX",
    "RELATIONSHIP_STRENGTH_DEFAULT",
    "INTERACTION_HISTORY_DAYS",
    "STRENGTH_DECAY_RATE",
    "TRUST_DECAY_RATE",
    "MIN_INTERACTIONS_FOR_RELATIONSHIP",
    "STRENGTH_INCREMENT",
    "TRUST_INCREMENT",
    "GRAPH_CACHE_TTL",
    # Ultimate Brain - Phase 3: Multi-Agent System
    "agents",
    # Phase 2F: Outcome Learning
    "BrainOutcomeLearning",
    "create_outcome_learning",
    "OutcomeTracker",
    "ImplicitFeedbackDetector",
    "PatternExtractor",
    "OutcomeAnalyzer",
    "OutcomeRepository",
    "EventType",
    "FeedbackSignal",
    "OutcomeType",
    "PatternScope",
    "PatternType",
    "OutcomeEvent",
    "ImplicitFeedback",
    "OutcomePattern",
    "OutcomeInsight",
    "OutcomeStatistics",
    # Phase 0: Model Orchestrator（次世代能力）
    "ModelOrchestrator",
    "OrchestratorResult",
    "OrchestratorConfig",
    "create_orchestrator",
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
    "MODEL_ORCHESTRATOR_FLAG_NAME",
    # Phase 2I: Deep Understanding（理解力強化）
    # 統合クラス
    "DeepUnderstanding",
    "create_deep_understanding",
    # コンポーネント
    "IntentInferenceEngine",
    "EmotionReader",
    "VocabularyManager",
    "HistoryAnalyzer",
    # ファクトリー
    "create_intent_inference_engine",
    "create_emotion_reader",
    "create_vocabulary_manager",
    "create_history_analyzer",
    # Enum
    "ImplicitIntentType",
    "ReferenceResolutionStrategy",
    "OrganizationContextType",
    "VocabularyCategory",
    "EmotionCategory",
    "DeepUrgencyLevel",
    "NuanceType",
    "ContextRecoverySource",
    # データモデル
    "DeepUnderstandingInput",
    "DeepUnderstandingOutput",
    "ResolvedReference",
    "ImplicitIntent",
    "IntentInferenceResult",
    "VocabularyEntry",
    "OrganizationContext",
    "OrganizationContextResult",
    "DetectedEmotion",
    "DetectedUrgency",
    "DetectedNuance",
    "EmotionReadingResult",
    "ContextFragment",
    "RecoveredContext",
    # Feature Flags
    "FEATURE_FLAG_DEEP_UNDERSTANDING",
    "FEATURE_FLAG_IMPLICIT_INTENT",
    "FEATURE_FLAG_ORGANIZATION_CONTEXT",
    "FEATURE_FLAG_EMOTION_READING",
    "FEATURE_FLAG_VOCABULARY_LEARNING",
    # v10.40.2: Handler Wrappers
    "build_bypass_handlers",
    "build_brain_handlers",
    "build_session_handlers",
    "get_session_management_functions",
    # v10.40.3: ポーリング処理
    "validate_polling_message",
    "should_skip_polling_message",
    "process_polling_message",
    "process_polling_room",
]

__version__ = BRAIN_VERSION  # 単一ソースから取得
