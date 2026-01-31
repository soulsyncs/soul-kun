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

【v10.51.0 変更点】Lazy Import Pattern
- 依存関係のカスケード問題を解決
- 起動時間の短縮（545ms → 150ms目標）
- 必要な時にのみモジュールをインポート
- コアモジュールのみeager import

【7つの鉄則】
1. 全ての入力は脳を通る（バイパスルート禁止）
2. 脳は全ての記憶にアクセスできる
3. 脳が判断し、機能は実行するだけ
4. 機能拡張しても脳の構造は変わらない → カタログへの追加のみで対応
5. 確認は脳の責務
6. 状態管理は脳が統一管理
7. 速度より正確性を優先

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

from typing import Any

# =============================================================================
# バージョン定義（単一ソース）
# =============================================================================
# このバージョンはCloud Loggingの出力で使用される
# デプロイ時に手動更新すること
BRAIN_VERSION = "10.53.6"

# =============================================================================
# 即座にインポートするモジュール（コア機能）
# =============================================================================
# これらは起動時に必ず必要なため、eager importを維持

# データモデル（軽量）
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

# メインクラス
from lib.brain.core import SoulkunBrain

# 状態管理（必須）
from lib.brain.state_manager import BrainStateManager

# 記憶アクセス（必須）
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

# 例外（軽量）
from lib.brain.exceptions import (
    BrainError,
    UnderstandingError,
    DecisionError,
    ExecutionError,
    StateError,
    MemoryAccessError,
    ConfirmationTimeoutError,
)

# 定数（軽量・よく使う）
from lib.brain.constants import (
    CANCEL_KEYWORDS,
    CONFIRMATION_THRESHOLD,
    SESSION_TIMEOUT_MINUTES,
    MAX_RETRY_COUNT,
)

# =============================================================================
# Lazy Import定義（必要な時にのみインポート）
# =============================================================================
# これらのモジュールは依存関係が重いため、使用時にのみインポート

_LAZY_IMPORTS = {
    # ----------------------------------------------------------------
    # 統合層（v10.30.0）
    # ----------------------------------------------------------------
    "BrainIntegration": ("lib.brain.integration", "BrainIntegration"),
    "IntegrationResult": ("lib.brain.integration", "IntegrationResult"),
    "IntegrationConfig": ("lib.brain.integration", "IntegrationConfig"),
    "IntegrationMode": ("lib.brain.integration", "IntegrationMode"),
    "BypassType": ("lib.brain.integration", "BypassType"),
    "BypassDetectionResult": ("lib.brain.integration", "BypassDetectionResult"),
    "create_integration": ("lib.brain.integration", "create_integration"),
    "is_brain_enabled": ("lib.brain.integration", "is_brain_enabled"),
    "FEATURE_FLAG_NAME": ("lib.brain.integration", "FEATURE_FLAG_NAME"),

    # ----------------------------------------------------------------
    # バリデーション層（v10.30.0）
    # ----------------------------------------------------------------
    "ValidationResult": ("lib.brain.validation", "ValidationResult"),
    "ValidationError": ("lib.brain.validation", "ValidationError"),
    "validate_capabilities_handlers": ("lib.brain.validation", "validate_capabilities_handlers"),
    "validate_brain_metadata": ("lib.brain.validation", "validate_brain_metadata"),
    "check_capabilities_coverage": ("lib.brain.validation", "check_capabilities_coverage"),

    # ----------------------------------------------------------------
    # Phase 2D: CEO Learning & Guardian（v10.32.0）
    # ----------------------------------------------------------------
    # リポジトリ
    "CEOTeachingRepository": ("lib.brain.ceo_teaching_repository", "CEOTeachingRepository"),
    "ConflictRepository": ("lib.brain.ceo_teaching_repository", "ConflictRepository"),
    "GuardianAlertRepository": ("lib.brain.ceo_teaching_repository", "GuardianAlertRepository"),
    "TeachingUsageRepository": ("lib.brain.ceo_teaching_repository", "TeachingUsageRepository"),
    # CEO学習層
    "CEOLearningService": ("lib.brain.ceo_learning", "CEOLearningService"),
    "ExtractedTeaching": ("lib.brain.ceo_learning", "ExtractedTeaching"),
    "ProcessingResult": ("lib.brain.ceo_learning", "ProcessingResult"),
    "format_teachings_for_prompt": ("lib.brain.ceo_learning", "format_teachings_for_prompt"),
    "should_include_teachings": ("lib.brain.ceo_learning", "should_include_teachings"),
    "CEO_ACCOUNT_IDS": ("lib.brain.ceo_learning", "CEO_ACCOUNT_IDS"),
    "TEACHING_CONFIDENCE_THRESHOLD": ("lib.brain.ceo_learning", "TEACHING_CONFIDENCE_THRESHOLD"),
    "CATEGORY_KEYWORDS": ("lib.brain.ceo_learning", "CATEGORY_KEYWORDS"),
    # ガーディアン層
    "GuardianService": ("lib.brain.guardian", "GuardianService"),
    "GuardianActionType": ("lib.brain.guardian", "GuardianActionType"),
    "GuardianActionResult": ("lib.brain.guardian", "GuardianActionResult"),
    "MVV_VALIDATION_CRITERIA": ("lib.brain.guardian", "MVV_VALIDATION_CRITERIA"),
    "CHOICE_THEORY_CRITERIA": ("lib.brain.guardian", "CHOICE_THEORY_CRITERIA"),
    "SDT_CRITERIA": ("lib.brain.guardian", "SDT_CRITERIA"),

    # ----------------------------------------------------------------
    # v10.42.0 P1: Decision Layer Enforcement
    # ----------------------------------------------------------------
    "EnforcementAction": ("lib.brain.decision", "EnforcementAction"),
    "MVVCheckResult": ("lib.brain.decision", "MVVCheckResult"),

    # ----------------------------------------------------------------
    # v10.42.0 P3: Value Authority Layer
    # ----------------------------------------------------------------
    "ValueAuthority": ("lib.brain.value_authority", "ValueAuthority"),
    "ValueAuthorityResult": ("lib.brain.value_authority", "ValueAuthorityResult"),
    "ValueDecision": ("lib.brain.value_authority", "ValueDecision"),
    "create_value_authority": ("lib.brain.value_authority", "create_value_authority"),
    "LIFE_AXIS_VIOLATION_PATTERNS": ("lib.brain.value_authority", "LIFE_AXIS_VIOLATION_PATTERNS"),
    "GOAL_CONTRADICTION_PATTERNS": ("lib.brain.value_authority", "GOAL_CONTRADICTION_PATTERNS"),

    # ----------------------------------------------------------------
    # v10.43.0 P4: Memory Authority Layer
    # ----------------------------------------------------------------
    "MemoryAuthority": ("lib.brain.memory_authority", "MemoryAuthority"),
    "MemoryAuthorityResult": ("lib.brain.memory_authority", "MemoryAuthorityResult"),
    "MemoryDecision": ("lib.brain.memory_authority", "MemoryDecision"),
    "MemoryConflict": ("lib.brain.memory_authority", "MemoryConflict"),
    "create_memory_authority": ("lib.brain.memory_authority", "create_memory_authority"),
    "normalize_text": ("lib.brain.memory_authority", "normalize_text"),
    "extract_keywords": ("lib.brain.memory_authority", "extract_keywords"),
    "has_keyword_match": ("lib.brain.memory_authority", "has_keyword_match"),
    "calculate_overlap_score": ("lib.brain.memory_authority", "calculate_overlap_score"),
    "HARD_CONFLICT_PATTERNS": ("lib.brain.memory_authority", "HARD_CONFLICT_PATTERNS"),
    "SOFT_CONFLICT_PATTERNS": ("lib.brain.memory_authority", "SOFT_CONFLICT_PATTERNS"),
    "ALIGNMENT_PATTERNS": ("lib.brain.memory_authority", "ALIGNMENT_PATTERNS"),

    # ----------------------------------------------------------------
    # v10.43.1 P4: Memory Authority Observation Logger
    # ----------------------------------------------------------------
    "MemoryAuthorityLogger": ("lib.brain.memory_authority_logger", "MemoryAuthorityLogger"),
    "SoftConflictLog": ("lib.brain.memory_authority_logger", "SoftConflictLog"),
    "get_memory_authority_logger": ("lib.brain.memory_authority_logger", "get_memory_authority_logger"),
    "create_memory_authority_logger": ("lib.brain.memory_authority_logger", "create_memory_authority_logger"),

    # ----------------------------------------------------------------
    # Ultimate Brain - Phase 1: Chain-of-Thought & Self-Critique
    # ----------------------------------------------------------------
    "ChainOfThought": ("lib.brain.chain_of_thought", "ChainOfThought"),
    "create_chain_of_thought": ("lib.brain.chain_of_thought", "create_chain_of_thought"),
    "InputType": ("lib.brain.chain_of_thought", "InputType"),
    "StructureElement": ("lib.brain.chain_of_thought", "StructureElement"),
    "ThoughtStep": ("lib.brain.chain_of_thought", "ThoughtStep"),
    "PossibleIntent": ("lib.brain.chain_of_thought", "PossibleIntent"),
    "StructureAnalysis": ("lib.brain.chain_of_thought", "StructureAnalysis"),
    "ThoughtChain": ("lib.brain.chain_of_thought", "ThoughtChain"),
    "INPUT_TYPE_PATTERNS": ("lib.brain.chain_of_thought", "INPUT_TYPE_PATTERNS"),
    "INTENT_KEYWORDS": ("lib.brain.chain_of_thought", "INTENT_KEYWORDS"),
    # 自己批判
    "SelfCritique": ("lib.brain.self_critique", "SelfCritique"),
    "create_self_critique": ("lib.brain.self_critique", "create_self_critique"),
    "QualityCriterion": ("lib.brain.self_critique", "QualityCriterion"),
    "IssueType": ("lib.brain.self_critique", "IssueType"),
    "IssueSeverity": ("lib.brain.self_critique", "IssueSeverity"),
    "QualityScore": ("lib.brain.self_critique", "QualityScore"),
    "DetectedIssue": ("lib.brain.self_critique", "DetectedIssue"),
    "CritiqueResult": ("lib.brain.self_critique", "CritiqueResult"),
    "RefinedResponse": ("lib.brain.self_critique", "RefinedResponse"),
    "QUALITY_THRESHOLDS": ("lib.brain.self_critique", "QUALITY_THRESHOLDS"),
    "OVERALL_REFINEMENT_THRESHOLD": ("lib.brain.self_critique", "OVERALL_REFINEMENT_THRESHOLD"),

    # ----------------------------------------------------------------
    # Ultimate Brain - Phase 2: Confidence Calibration
    # ----------------------------------------------------------------
    "ConfidenceCalibrator": ("lib.brain.confidence", "ConfidenceCalibrator"),
    "create_confidence_calibrator": ("lib.brain.confidence", "create_confidence_calibrator"),
    "RiskLevel": ("lib.brain.confidence", "RiskLevel"),
    "ConfidenceAction": ("lib.brain.confidence", "ConfidenceAction"),
    "ConfidenceAdjustment": ("lib.brain.confidence", "ConfidenceAdjustment"),
    "CalibratedDecision": ("lib.brain.confidence", "CalibratedDecision"),
    "CONFIDENCE_THRESHOLDS": ("lib.brain.confidence", "CONFIDENCE_THRESHOLDS"),
    "AMBIGUOUS_PATTERNS": ("lib.brain.confidence", "AMBIGUOUS_PATTERNS"),
    "CONFIRMATION_TEMPLATES": ("lib.brain.confidence", "CONFIRMATION_TEMPLATES"),

    # ----------------------------------------------------------------
    # Ultimate Brain - Phase 2: Episodic Memory
    # ----------------------------------------------------------------
    "EpisodicMemory": ("lib.brain.episodic_memory", "EpisodicMemory"),
    "create_episodic_memory": ("lib.brain.episodic_memory", "create_episodic_memory"),
    "EpisodeType": ("lib.brain.episodic_memory", "EpisodeType"),
    "RecallTrigger": ("lib.brain.episodic_memory", "RecallTrigger"),
    "Episode": ("lib.brain.episodic_memory", "Episode"),
    "RecallResult": ("lib.brain.episodic_memory", "RecallResult"),
    "RelatedEntity": ("lib.brain.episodic_memory", "RelatedEntity"),
    "DECAY_RATE_PER_DAY": ("lib.brain.episodic_memory", "DECAY_RATE_PER_DAY"),
    "MAX_RECALL_COUNT": ("lib.brain.episodic_memory", "MAX_RECALL_COUNT"),
    "BASE_IMPORTANCE": ("lib.brain.episodic_memory", "BASE_IMPORTANCE"),
    "IMPORTANT_KEYWORDS": ("lib.brain.episodic_memory", "IMPORTANT_KEYWORDS"),

    # ----------------------------------------------------------------
    # Ultimate Brain - Phase 2: Proactive Monitoring
    # ----------------------------------------------------------------
    "ProactiveMonitor": ("lib.brain.proactive", "ProactiveMonitor"),
    "create_proactive_monitor": ("lib.brain.proactive", "create_proactive_monitor"),
    "ProactiveTriggerType": ("lib.brain.proactive", "TriggerType"),
    "ProactiveMessageType": ("lib.brain.proactive", "ProactiveMessageType"),
    "ActionPriority": ("lib.brain.proactive", "ActionPriority"),
    "ProactiveTrigger": ("lib.brain.proactive", "Trigger"),
    "ProactiveMessage": ("lib.brain.proactive", "ProactiveMessage"),
    "ProactiveAction": ("lib.brain.proactive", "ProactiveAction"),
    "UserContext": ("lib.brain.proactive", "UserContext"),
    "CheckResult": ("lib.brain.proactive", "CheckResult"),
    "GOAL_ABANDONED_DAYS": ("lib.brain.proactive", "GOAL_ABANDONED_DAYS"),
    "TASK_OVERLOAD_COUNT": ("lib.brain.proactive", "TASK_OVERLOAD_COUNT"),
    "EMOTION_DECLINE_DAYS": ("lib.brain.proactive", "EMOTION_DECLINE_DAYS"),
    "MESSAGE_COOLDOWN_HOURS": ("lib.brain.proactive", "MESSAGE_COOLDOWN_HOURS"),
    "TRIGGER_PRIORITY": ("lib.brain.proactive", "TRIGGER_PRIORITY"),
    "MESSAGE_TEMPLATES": ("lib.brain.proactive", "MESSAGE_TEMPLATES"),

    # ----------------------------------------------------------------
    # Ultimate Brain - Phase 3: Learning Loop
    # ----------------------------------------------------------------
    "LearningLoop": ("lib.brain.learning_loop", "LearningLoop"),
    "create_learning_loop": ("lib.brain.learning_loop", "create_learning_loop"),
    "FeedbackType": ("lib.brain.learning_loop", "FeedbackType"),
    "FailureCause": ("lib.brain.learning_loop", "FailureCause"),
    "ImprovementType": ("lib.brain.learning_loop", "ImprovementType"),
    "LearningStatus": ("lib.brain.learning_loop", "LearningStatus"),
    "Feedback": ("lib.brain.learning_loop", "Feedback"),
    "DecisionSnapshot": ("lib.brain.learning_loop", "DecisionSnapshot"),
    "FailureAnalysis": ("lib.brain.learning_loop", "FailureAnalysis"),
    "Improvement": ("lib.brain.learning_loop", "Improvement"),
    "LearningEntry": ("lib.brain.learning_loop", "LearningEntry"),
    "LearningStatistics": ("lib.brain.learning_loop", "LearningStatistics"),
    "LEARNING_HISTORY_RETENTION_DAYS": ("lib.brain.learning_loop", "LEARNING_HISTORY_RETENTION_DAYS"),
    "MIN_SAMPLES_FOR_IMPROVEMENT": ("lib.brain.learning_loop", "MIN_SAMPLES_FOR_IMPROVEMENT"),
    "THRESHOLD_MIN": ("lib.brain.learning_loop", "THRESHOLD_MIN"),
    "THRESHOLD_MAX": ("lib.brain.learning_loop", "THRESHOLD_MAX"),
    "THRESHOLD_ADJUSTMENT_STEP": ("lib.brain.learning_loop", "THRESHOLD_ADJUSTMENT_STEP"),
    "PATTERN_MIN_CONFIDENCE": ("lib.brain.learning_loop", "PATTERN_MIN_CONFIDENCE"),
    "DEFAULT_KEYWORD_WEIGHT": ("lib.brain.learning_loop", "DEFAULT_KEYWORD_WEIGHT"),
    "LEARNING_LOG_BUFFER_SIZE": ("lib.brain.learning_loop", "LEARNING_LOG_BUFFER_SIZE"),
    "ANALYSIS_DECISION_LOOKBACK": ("lib.brain.learning_loop", "ANALYSIS_DECISION_LOOKBACK"),
    "EFFECTIVENESS_MEASUREMENT_DAYS": ("lib.brain.learning_loop", "EFFECTIVENESS_MEASUREMENT_DAYS"),

    # ----------------------------------------------------------------
    # Ultimate Brain - Phase 3: Organization Graph
    # ----------------------------------------------------------------
    "OrganizationGraph": ("lib.brain.org_graph", "OrganizationGraph"),
    "create_organization_graph": ("lib.brain.org_graph", "create_organization_graph"),
    "OrgRelationshipType": ("lib.brain.org_graph", "RelationshipType"),
    "CommunicationStyle": ("lib.brain.org_graph", "CommunicationStyle"),
    "InteractionType": ("lib.brain.org_graph", "InteractionType"),
    "ExpertiseArea": ("lib.brain.org_graph", "ExpertiseArea"),
    "PersonNode": ("lib.brain.org_graph", "PersonNode"),
    "PersonRelationship": ("lib.brain.org_graph", "PersonRelationship"),
    "OrgInteraction": ("lib.brain.org_graph", "Interaction"),
    "OrganizationGraphStats": ("lib.brain.org_graph", "OrganizationGraphStats"),
    "RelationshipInsight": ("lib.brain.org_graph", "RelationshipInsight"),
    "INFLUENCE_SCORE_MIN": ("lib.brain.org_graph", "INFLUENCE_SCORE_MIN"),
    "INFLUENCE_SCORE_MAX": ("lib.brain.org_graph", "INFLUENCE_SCORE_MAX"),
    "INFLUENCE_SCORE_DEFAULT": ("lib.brain.org_graph", "INFLUENCE_SCORE_DEFAULT"),
    "TRUST_LEVEL_MIN": ("lib.brain.org_graph", "TRUST_LEVEL_MIN"),
    "TRUST_LEVEL_MAX": ("lib.brain.org_graph", "TRUST_LEVEL_MAX"),
    "TRUST_LEVEL_DEFAULT": ("lib.brain.org_graph", "TRUST_LEVEL_DEFAULT"),
    "RELATIONSHIP_STRENGTH_MIN": ("lib.brain.org_graph", "RELATIONSHIP_STRENGTH_MIN"),
    "RELATIONSHIP_STRENGTH_MAX": ("lib.brain.org_graph", "RELATIONSHIP_STRENGTH_MAX"),
    "RELATIONSHIP_STRENGTH_DEFAULT": ("lib.brain.org_graph", "RELATIONSHIP_STRENGTH_DEFAULT"),
    "INTERACTION_HISTORY_DAYS": ("lib.brain.org_graph", "INTERACTION_HISTORY_DAYS"),
    "STRENGTH_DECAY_RATE": ("lib.brain.org_graph", "STRENGTH_DECAY_RATE"),
    "TRUST_DECAY_RATE": ("lib.brain.org_graph", "TRUST_DECAY_RATE"),
    "MIN_INTERACTIONS_FOR_RELATIONSHIP": ("lib.brain.org_graph", "MIN_INTERACTIONS_FOR_RELATIONSHIP"),
    "STRENGTH_INCREMENT": ("lib.brain.org_graph", "STRENGTH_INCREMENT"),
    "TRUST_INCREMENT": ("lib.brain.org_graph", "TRUST_INCREMENT"),
    "GRAPH_CACHE_TTL": ("lib.brain.org_graph", "GRAPH_CACHE_TTL"),

    # ----------------------------------------------------------------
    # Phase 2E: Learning Foundation（v10.33.0）
    # ----------------------------------------------------------------
    "BrainLearning": ("lib.brain.learning_foundation", "BrainLearning"),
    "create_brain_learning": ("lib.brain.learning_foundation", "create_brain_learning"),
    "LearningCategory": ("lib.brain.learning_foundation", "LearningCategory"),
    "LearningScope": ("lib.brain.learning_foundation", "LearningScope"),
    "LearningAuthorityLevel": ("lib.brain.learning_foundation", "AuthorityLevel"),
    "TriggerType": ("lib.brain.learning_foundation", "TriggerType"),
    "RelationshipType": ("lib.brain.learning_foundation", "RelationshipType"),
    "DecisionImpact": ("lib.brain.learning_foundation", "DecisionImpact"),
    "ConflictResolutionStrategy": ("lib.brain.learning_foundation", "ConflictResolutionStrategy"),
    "LearningConflictType": ("lib.brain.learning_foundation", "ConflictType"),
    "Learning": ("lib.brain.learning_foundation", "Learning"),
    "LearningLog": ("lib.brain.learning_foundation", "LearningLog"),
    "FeedbackDetectionResult": ("lib.brain.learning_foundation", "FeedbackDetectionResult"),
    "LearningConversationContext": ("lib.brain.learning_foundation", "ConversationContext"),
    "LearningConflictInfo": ("lib.brain.learning_foundation", "ConflictInfo"),
    "Resolution": ("lib.brain.learning_foundation", "Resolution"),
    "AppliedLearning": ("lib.brain.learning_foundation", "AppliedLearning"),
    "EffectivenessResult": ("lib.brain.learning_foundation", "EffectivenessResult"),
    "ImprovementSuggestion": ("lib.brain.learning_foundation", "ImprovementSuggestion"),
    "DetectionPattern": ("lib.brain.learning_foundation", "DetectionPattern"),
    "ALL_PATTERNS": ("lib.brain.learning_foundation", "ALL_PATTERNS"),
    "PATTERNS_BY_NAME": ("lib.brain.learning_foundation", "PATTERNS_BY_NAME"),
    "PATTERNS_BY_CATEGORY": ("lib.brain.learning_foundation", "PATTERNS_BY_CATEGORY"),
    "FeedbackDetector": ("lib.brain.learning_foundation", "FeedbackDetector"),
    "LearningExtractor": ("lib.brain.learning_foundation", "LearningExtractor"),
    "LearningRepository": ("lib.brain.learning_foundation", "LearningRepository"),
    "LearningApplier": ("lib.brain.learning_foundation", "LearningApplier"),
    "LearningApplierWithCeoCheck": ("lib.brain.learning_foundation", "LearningApplierWithCeoCheck"),
    "LearningManager": ("lib.brain.learning_foundation", "LearningManager"),
    "LearningConflictDetector": ("lib.brain.learning_foundation", "ConflictDetector"),
    "AuthorityResolver": ("lib.brain.learning_foundation", "AuthorityResolver"),
    "AuthorityResolverWithDb": ("lib.brain.learning_foundation", "AuthorityResolverWithDb"),
    "EffectivenessTracker": ("lib.brain.learning_foundation", "EffectivenessTracker"),
    "EffectivenessMetrics": ("lib.brain.learning_foundation", "EffectivenessMetrics"),
    "LearningHealth": ("lib.brain.learning_foundation", "LearningHealth"),
    "AUTHORITY_PRIORITY": ("lib.brain.learning_foundation", "AUTHORITY_PRIORITY"),
    "CONFIDENCE_THRESHOLD_AUTO_LEARN": ("lib.brain.learning_foundation", "CONFIDENCE_THRESHOLD_AUTO_LEARN"),
    "CONFIDENCE_THRESHOLD_CONFIRM": ("lib.brain.learning_foundation", "CONFIDENCE_THRESHOLD_CONFIRM"),
    "CONFIDENCE_THRESHOLD_MIN": ("lib.brain.learning_foundation", "CONFIDENCE_THRESHOLD_MIN"),

    # ----------------------------------------------------------------
    # Phase 2F: Outcome Learning
    # ----------------------------------------------------------------
    "BrainOutcomeLearning": ("lib.brain.outcome_learning", "BrainOutcomeLearning"),
    "create_outcome_learning": ("lib.brain.outcome_learning", "create_outcome_learning"),
    "OutcomeTracker": ("lib.brain.outcome_learning", "OutcomeTracker"),
    "ImplicitFeedbackDetector": ("lib.brain.outcome_learning", "ImplicitFeedbackDetector"),
    "PatternExtractor": ("lib.brain.outcome_learning", "PatternExtractor"),
    "OutcomeAnalyzer": ("lib.brain.outcome_learning", "OutcomeAnalyzer"),
    "OutcomeRepository": ("lib.brain.outcome_learning", "OutcomeRepository"),
    "EventType": ("lib.brain.outcome_learning", "EventType"),
    "FeedbackSignal": ("lib.brain.outcome_learning", "FeedbackSignal"),
    "OutcomeType": ("lib.brain.outcome_learning", "OutcomeType"),
    "PatternScope": ("lib.brain.outcome_learning", "PatternScope"),
    "PatternType": ("lib.brain.outcome_learning", "PatternType"),
    "OutcomeEvent": ("lib.brain.outcome_learning", "OutcomeEvent"),
    "ImplicitFeedback": ("lib.brain.outcome_learning", "ImplicitFeedback"),
    "OutcomePattern": ("lib.brain.outcome_learning", "OutcomePattern"),
    "OutcomeInsight": ("lib.brain.outcome_learning", "OutcomeInsight"),
    "OutcomeStatistics": ("lib.brain.outcome_learning", "OutcomeStatistics"),

    # ----------------------------------------------------------------
    # Phase 0: Model Orchestrator（次世代能力）
    # ----------------------------------------------------------------
    "ModelOrchestrator": ("lib.brain.model_orchestrator", "ModelOrchestrator"),
    "OrchestratorResult": ("lib.brain.model_orchestrator", "OrchestratorResult"),
    "OrchestratorConfig": ("lib.brain.model_orchestrator", "OrchestratorConfig"),
    "create_orchestrator": ("lib.brain.model_orchestrator", "create_orchestrator"),
    "ModelRegistry": ("lib.brain.model_orchestrator", "ModelRegistry"),
    "ModelInfo": ("lib.brain.model_orchestrator", "ModelInfo"),
    "ModelSelector": ("lib.brain.model_orchestrator", "ModelSelector"),
    "ModelSelection": ("lib.brain.model_orchestrator", "ModelSelection"),
    "CostManager": ("lib.brain.model_orchestrator", "CostManager"),
    "CostCheckResult": ("lib.brain.model_orchestrator", "CostCheckResult"),
    "CostAction": ("lib.brain.model_orchestrator", "CostAction"),
    "CostEstimate": ("lib.brain.model_orchestrator", "CostEstimate"),
    "OrganizationSettings": ("lib.brain.model_orchestrator", "OrganizationSettings"),
    "FallbackManager": ("lib.brain.model_orchestrator", "FallbackManager"),
    "FallbackResult": ("lib.brain.model_orchestrator", "FallbackResult"),
    "FallbackAttempt": ("lib.brain.model_orchestrator", "FallbackAttempt"),
    "APIError": ("lib.brain.model_orchestrator", "APIError"),
    "UsageLogger": ("lib.brain.model_orchestrator", "UsageLogger"),
    "UsageLogEntry": ("lib.brain.model_orchestrator", "UsageLogEntry"),
    "UsageStats": ("lib.brain.model_orchestrator", "UsageStats"),
    "Tier": ("lib.brain.model_orchestrator", "Tier"),
    "BudgetStatus": ("lib.brain.model_orchestrator", "BudgetStatus"),
    "CostThreshold": ("lib.brain.model_orchestrator", "CostThreshold"),
    "MonthlyBudget": ("lib.brain.model_orchestrator", "MonthlyBudget"),
    "TASK_TYPE_TIERS": ("lib.brain.model_orchestrator", "TASK_TYPE_TIERS"),
    "DEFAULT_TIER": ("lib.brain.model_orchestrator", "DEFAULT_TIER"),
    "TIER_UPGRADE_KEYWORDS": ("lib.brain.model_orchestrator", "TIER_UPGRADE_KEYWORDS"),
    "TIER_DOWNGRADE_KEYWORDS": ("lib.brain.model_orchestrator", "TIER_DOWNGRADE_KEYWORDS"),
    "FALLBACK_CHAINS": ("lib.brain.model_orchestrator", "FALLBACK_CHAINS"),
    "MAX_RETRIES": ("lib.brain.model_orchestrator", "MAX_RETRIES"),
    "MODEL_ORCHESTRATOR_FLAG_NAME": ("lib.brain.model_orchestrator", "FEATURE_FLAG_NAME"),

    # ----------------------------------------------------------------
    # Phase 2I: Deep Understanding（理解力強化）
    # ----------------------------------------------------------------
    "DeepUnderstanding": ("lib.brain.deep_understanding", "DeepUnderstanding"),
    "create_deep_understanding": ("lib.brain.deep_understanding", "create_deep_understanding"),
    "IntentInferenceEngine": ("lib.brain.deep_understanding", "IntentInferenceEngine"),
    "EmotionReader": ("lib.brain.deep_understanding", "EmotionReader"),
    "VocabularyManager": ("lib.brain.deep_understanding", "VocabularyManager"),
    "HistoryAnalyzer": ("lib.brain.deep_understanding", "HistoryAnalyzer"),
    "create_intent_inference_engine": ("lib.brain.deep_understanding", "create_intent_inference_engine"),
    "create_emotion_reader": ("lib.brain.deep_understanding", "create_emotion_reader"),
    "create_vocabulary_manager": ("lib.brain.deep_understanding", "create_vocabulary_manager"),
    "create_history_analyzer": ("lib.brain.deep_understanding", "create_history_analyzer"),
    "ImplicitIntentType": ("lib.brain.deep_understanding", "ImplicitIntentType"),
    "ReferenceResolutionStrategy": ("lib.brain.deep_understanding", "ReferenceResolutionStrategy"),
    "OrganizationContextType": ("lib.brain.deep_understanding", "OrganizationContextType"),
    "VocabularyCategory": ("lib.brain.deep_understanding", "VocabularyCategory"),
    "EmotionCategory": ("lib.brain.deep_understanding", "EmotionCategory"),
    "DeepUrgencyLevel": ("lib.brain.deep_understanding", "UrgencyLevel"),
    "NuanceType": ("lib.brain.deep_understanding", "NuanceType"),
    "ContextRecoverySource": ("lib.brain.deep_understanding", "ContextRecoverySource"),
    "DeepUnderstandingInput": ("lib.brain.deep_understanding", "DeepUnderstandingInput"),
    "DeepUnderstandingOutput": ("lib.brain.deep_understanding", "DeepUnderstandingOutput"),
    "ResolvedReference": ("lib.brain.deep_understanding", "ResolvedReference"),
    "ImplicitIntent": ("lib.brain.deep_understanding", "ImplicitIntent"),
    "IntentInferenceResult": ("lib.brain.deep_understanding", "IntentInferenceResult"),
    "VocabularyEntry": ("lib.brain.deep_understanding", "VocabularyEntry"),
    "OrganizationContext": ("lib.brain.deep_understanding", "OrganizationContext"),
    "OrganizationContextResult": ("lib.brain.deep_understanding", "OrganizationContextResult"),
    "DetectedEmotion": ("lib.brain.deep_understanding", "DetectedEmotion"),
    "DetectedUrgency": ("lib.brain.deep_understanding", "DetectedUrgency"),
    "DetectedNuance": ("lib.brain.deep_understanding", "DetectedNuance"),
    "EmotionReadingResult": ("lib.brain.deep_understanding", "EmotionReadingResult"),
    "ContextFragment": ("lib.brain.deep_understanding", "ContextFragment"),
    "RecoveredContext": ("lib.brain.deep_understanding", "RecoveredContext"),
    "FEATURE_FLAG_DEEP_UNDERSTANDING": ("lib.brain.deep_understanding", "FEATURE_FLAG_DEEP_UNDERSTANDING"),
    "FEATURE_FLAG_IMPLICIT_INTENT": ("lib.brain.deep_understanding", "FEATURE_FLAG_IMPLICIT_INTENT"),
    "FEATURE_FLAG_ORGANIZATION_CONTEXT": ("lib.brain.deep_understanding", "FEATURE_FLAG_ORGANIZATION_CONTEXT"),
    "FEATURE_FLAG_EMOTION_READING": ("lib.brain.deep_understanding", "FEATURE_FLAG_EMOTION_READING"),
    "FEATURE_FLAG_VOCABULARY_LEARNING": ("lib.brain.deep_understanding", "FEATURE_FLAG_VOCABULARY_LEARNING"),

    # ----------------------------------------------------------------
    # v10.53.6: LLM Observability & Monitoring（設計書15章対応）
    # ----------------------------------------------------------------
    # LLM Observability
    "LLMBrainLog": ("lib.brain.llm_observability", "LLMBrainLog"),
    "LLMBrainObservability": ("lib.brain.llm_observability", "LLMBrainObservability"),
    "UserFeedback": ("lib.brain.llm_observability", "UserFeedback"),
    "ConfirmationStatus": ("lib.brain.llm_observability", "ConfirmationStatus"),
    "LLMLogType": ("lib.brain.llm_observability", "LLMLogType"),
    "create_llm_observability": ("lib.brain.llm_observability", "create_llm_observability"),
    "get_llm_observability": ("lib.brain.llm_observability", "get_llm_observability"),
    "save_user_feedback": ("lib.brain.llm_observability", "save_user_feedback"),
    # DB連携モニタリング
    "DailyDBMetrics": ("lib.brain.monitoring", "DailyDBMetrics"),
    "DBBrainMonitor": ("lib.brain.monitoring", "DBBrainMonitor"),
    "create_db_monitor": ("lib.brain.monitoring", "create_db_monitor"),
    "print_dashboard": ("lib.brain.monitoring", "print_dashboard"),
}

# キャッシュ（一度インポートしたモジュールを再利用）
_LAZY_CACHE: dict[str, Any] = {}

# agents サブモジュール用の特別処理
_agents_module = None


def __getattr__(name: str) -> Any:
    """
    Lazy Import実装

    このモジュールに存在しない属性にアクセスされた時に呼ばれる。
    _LAZY_IMPORTSに定義されている場合、その時点で初めてインポートする。
    """
    global _agents_module

    # agents サブモジュールの特別処理
    if name == "agents":
        if _agents_module is None:
            from lib.brain import agents as _agents
            _agents_module = _agents
        return _agents_module

    if name in _LAZY_CACHE:
        return _LAZY_CACHE[name]

    if name in _LAZY_IMPORTS:
        module_path, attr_name = _LAZY_IMPORTS[name]
        try:
            import importlib
            module = importlib.import_module(module_path)
            value = getattr(module, attr_name)
            _LAZY_CACHE[name] = value
            return value
        except ImportError as e:
            raise ImportError(
                f"Cannot import '{name}' from '{module_path}': {e}. "
                f"Make sure the required dependencies are installed."
            ) from e
        except AttributeError as e:
            raise AttributeError(
                f"Module '{module_path}' has no attribute '{attr_name}': {e}"
            ) from e

    raise AttributeError(f"module 'lib.brain' has no attribute '{name}'")


# =============================================================================
# __all__ 定義（IDEサポート・型ヒント用）
# =============================================================================

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
    # 統合層 (lazy)
    "BrainIntegration",
    "IntegrationResult",
    "IntegrationConfig",
    "IntegrationMode",
    "BypassType",
    "BypassDetectionResult",
    "create_integration",
    "is_brain_enabled",
    "FEATURE_FLAG_NAME",
    # バリデーション層（v10.30.0）(lazy)
    "ValidationResult",
    "ValidationError",
    "validate_capabilities_handlers",
    "validate_brain_metadata",
    "check_capabilities_coverage",
    # Phase 2D: CEO Learning & Guardian（v10.32.0）(lazy)
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
    "CEOTeachingRepository",
    "ConflictRepository",
    "GuardianAlertRepository",
    "TeachingUsageRepository",
    "CEOLearningService",
    "ExtractedTeaching",
    "ProcessingResult",
    "format_teachings_for_prompt",
    "should_include_teachings",
    "CEO_ACCOUNT_IDS",
    "TEACHING_CONFIDENCE_THRESHOLD",
    "CATEGORY_KEYWORDS",
    "GuardianService",
    "GuardianActionType",
    "GuardianActionResult",
    "MVV_VALIDATION_CRITERIA",
    "CHOICE_THEORY_CRITERIA",
    "SDT_CRITERIA",
    # v10.42.0 P1: Decision Layer Enforcement (lazy)
    "EnforcementAction",
    "MVVCheckResult",
    # v10.42.0 P3: Value Authority Layer (lazy)
    "ValueAuthority",
    "ValueAuthorityResult",
    "ValueDecision",
    "create_value_authority",
    "LIFE_AXIS_VIOLATION_PATTERNS",
    "GOAL_CONTRADICTION_PATTERNS",
    # v10.43.0 P4: Memory Authority Layer (lazy)
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
    # v10.43.1 P4: Memory Authority Observation Logger (lazy)
    "MemoryAuthorityLogger",
    "SoftConflictLog",
    "get_memory_authority_logger",
    "create_memory_authority_logger",
    # Phase 2E: Learning Foundation（v10.33.0）(lazy)
    "BrainLearning",
    "create_brain_learning",
    "LearningCategory",
    "LearningScope",
    "LearningAuthorityLevel",
    "TriggerType",
    "RelationshipType",
    "DecisionImpact",
    "ConflictResolutionStrategy",
    "LearningConflictType",
    "Learning",
    "LearningLog",
    "FeedbackDetectionResult",
    "LearningConversationContext",
    "LearningConflictInfo",
    "Resolution",
    "AppliedLearning",
    "EffectivenessResult",
    "ImprovementSuggestion",
    "DetectionPattern",
    "ALL_PATTERNS",
    "PATTERNS_BY_NAME",
    "PATTERNS_BY_CATEGORY",
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
    "AUTHORITY_PRIORITY",
    "CONFIDENCE_THRESHOLD_AUTO_LEARN",
    "CONFIDENCE_THRESHOLD_CONFIRM",
    "CONFIDENCE_THRESHOLD_MIN",
    # Ultimate Brain - Phase 1: Chain-of-Thought & Self-Critique (lazy)
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
    # Ultimate Brain - Phase 2: Confidence Calibration (lazy)
    "ConfidenceCalibrator",
    "create_confidence_calibrator",
    "RiskLevel",
    "ConfidenceAction",
    "ConfidenceAdjustment",
    "CalibratedDecision",
    "CONFIDENCE_THRESHOLDS",
    "AMBIGUOUS_PATTERNS",
    "CONFIRMATION_TEMPLATES",
    # Ultimate Brain - Phase 2: Episodic Memory (lazy)
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
    # Ultimate Brain - Phase 2: Proactive Monitoring (lazy)
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
    # Ultimate Brain - Phase 3: Learning Loop (lazy)
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
    # Ultimate Brain - Phase 3: Organization Graph (lazy)
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
    # Ultimate Brain - Phase 3: Multi-Agent System (lazy)
    "agents",
    # Phase 2F: Outcome Learning (lazy)
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
    # Phase 0: Model Orchestrator（次世代能力）(lazy)
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
    # Phase 2I: Deep Understanding（理解力強化）(lazy)
    "DeepUnderstanding",
    "create_deep_understanding",
    "IntentInferenceEngine",
    "EmotionReader",
    "VocabularyManager",
    "HistoryAnalyzer",
    "create_intent_inference_engine",
    "create_emotion_reader",
    "create_vocabulary_manager",
    "create_history_analyzer",
    "ImplicitIntentType",
    "ReferenceResolutionStrategy",
    "OrganizationContextType",
    "VocabularyCategory",
    "EmotionCategory",
    "DeepUrgencyLevel",
    "NuanceType",
    "ContextRecoverySource",
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
    "FEATURE_FLAG_DEEP_UNDERSTANDING",
    "FEATURE_FLAG_IMPLICIT_INTENT",
    "FEATURE_FLAG_ORGANIZATION_CONTEXT",
    "FEATURE_FLAG_EMOTION_READING",
    "FEATURE_FLAG_VOCABULARY_LEARNING",
]
