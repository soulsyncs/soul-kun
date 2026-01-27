# lib/brain/agents/__init__.py
"""
ソウルくんの脳 - マルチエージェントシステム

Ultimate Brain Phase 3: Multi-Agent Architecture

このモジュールは専門家エージェント群とオーケストレーターを提供します。

エージェント一覧:
1. Orchestrator - 全エージェントを統括する脳
2. TaskExpert - タスク管理の専門家
3. GoalExpert - 目標達成支援の専門家
4. KnowledgeExpert - ナレッジ管理の専門家
5. HRExpert - 人事・労務の専門家
6. EmotionExpert - 感情ケアの専門家
7. OrganizationExpert - 組織構造の専門家

設計書: docs/19_ultimate_brain_architecture.md セクション5.3
"""

from __future__ import annotations

# =============================================================================
# 基盤クラス
# =============================================================================

from lib.brain.agents.base import (
    # Enums
    AgentType,
    AgentStatus,
    MessageType,
    MessagePriority,
    ExpertiseLevel,
    # Data classes
    AgentCapability,
    AgentMessage,
    AgentResponse,
    AgentContext,
    AgentStats,
    # Base class
    BaseAgent,
)

# =============================================================================
# オーケストレーター
# =============================================================================

from lib.brain.agents.orchestrator import (
    Orchestrator,
    create_orchestrator,
    # Constants
    AGENT_KEYWORDS,
    ACTION_AGENT_MAPPING,
)

# =============================================================================
# タスク専門家
# =============================================================================

from lib.brain.agents.task_expert import (
    TaskExpert,
    create_task_expert,
    # Data classes
    TaskInfo,
    TaskAnalysis,
    # Constants
    TASK_CREATE_KEYWORDS,
    TASK_SEARCH_KEYWORDS,
    TASK_COMPLETE_KEYWORDS,
)

# =============================================================================
# 目標専門家
# =============================================================================

from lib.brain.agents.goal_expert import (
    GoalExpert,
    create_goal_expert,
    # Data classes
    GoalInfo,
    GoalSession,
    MotivationAnalysis,
    # Constants
    GOAL_START_KEYWORDS,
    GOAL_PROGRESS_KEYWORDS,
    GOAL_STATUS_KEYWORDS,
    MOTIVATION_KEYWORDS,
    # Step constants
    GOAL_STEP_INTRO,
    GOAL_STEP_WHY,
    GOAL_STEP_WHAT,
    GOAL_STEP_HOW,
    GOAL_STEP_COMPLETE,
)

# =============================================================================
# ナレッジ専門家
# =============================================================================

from lib.brain.agents.knowledge_expert import (
    KnowledgeExpert,
    create_knowledge_expert,
    # Data classes
    KnowledgeItem,
    SearchResult,
    FAQItem,
    # Constants
    KNOWLEDGE_SEARCH_KEYWORDS,
    KNOWLEDGE_SAVE_KEYWORDS,
    KNOWLEDGE_DELETE_KEYWORDS,
    FAQ_KEYWORDS,
    DOCUMENT_KEYWORDS,
)

# =============================================================================
# HR専門家
# =============================================================================

from lib.brain.agents.hr_expert import (
    HRExpert,
    create_hr_expert,
    # Data classes
    RuleInfo,
    ProcedureInfo,
    BenefitInfo,
    ConsultationGuide,
    # Constants
    RULE_KEYWORDS,
    PROCEDURE_KEYWORDS,
    LEAVE_KEYWORDS,
    BENEFIT_KEYWORDS,
    CONSULTATION_KEYWORDS,
    EMPLOYMENT_KEYWORDS,
)

# =============================================================================
# 感情ケア専門家
# =============================================================================

from lib.brain.agents.emotion_expert import (
    EmotionExpert,
    create_emotion_expert,
    # Enums
    EmotionType,
    SupportType,
    UrgencyLevel,
    # Data classes
    EmotionState,
    SupportResponse,
    EmotionTrend,
    # Constants
    NEGATIVE_EMOTION_KEYWORDS,
    POSITIVE_EMOTION_KEYWORDS,
    ENCOURAGEMENT_KEYWORDS,
    URGENT_KEYWORDS,
)

# =============================================================================
# 組織専門家
# =============================================================================

from lib.brain.agents.organization_expert import (
    OrganizationExpert,
    create_organization_expert,
    # Enums
    RelationshipType,
    CommunicationChannel,
    QueryType,
    # Data classes
    PersonInfo,
    DepartmentInfo,
    RelationshipInfo,
    RecommendationResult,
    CommunicationRoute,
    # Constants
    ORG_CHART_KEYWORDS,
    PERSON_KEYWORDS,
    RELATIONSHIP_KEYWORDS,
    RECOMMENDATION_KEYWORDS,
    COMMUNICATION_KEYWORDS,
    EXPERTISE_KEYWORDS,
)


# =============================================================================
# エクスポート
# =============================================================================

__all__ = [
    # ===== 基盤 =====
    # Enums
    "AgentType",
    "AgentStatus",
    "MessageType",
    "MessagePriority",
    "ExpertiseLevel",
    # Data classes
    "AgentCapability",
    "AgentMessage",
    "AgentResponse",
    "AgentContext",
    "AgentStats",
    # Base class
    "BaseAgent",

    # ===== オーケストレーター =====
    "Orchestrator",
    "create_orchestrator",
    "AGENT_KEYWORDS",
    "ACTION_AGENT_MAPPING",

    # ===== タスク専門家 =====
    "TaskExpert",
    "create_task_expert",
    "TaskInfo",
    "TaskAnalysis",
    "TASK_CREATE_KEYWORDS",
    "TASK_SEARCH_KEYWORDS",
    "TASK_COMPLETE_KEYWORDS",

    # ===== 目標専門家 =====
    "GoalExpert",
    "create_goal_expert",
    "GoalInfo",
    "GoalSession",
    "MotivationAnalysis",
    "GOAL_START_KEYWORDS",
    "GOAL_PROGRESS_KEYWORDS",
    "GOAL_STATUS_KEYWORDS",
    "MOTIVATION_KEYWORDS",
    "GOAL_STEP_INTRO",
    "GOAL_STEP_WHY",
    "GOAL_STEP_WHAT",
    "GOAL_STEP_HOW",
    "GOAL_STEP_COMPLETE",

    # ===== ナレッジ専門家 =====
    "KnowledgeExpert",
    "create_knowledge_expert",
    "KnowledgeItem",
    "SearchResult",
    "FAQItem",
    "KNOWLEDGE_SEARCH_KEYWORDS",
    "KNOWLEDGE_SAVE_KEYWORDS",
    "KNOWLEDGE_DELETE_KEYWORDS",
    "FAQ_KEYWORDS",
    "DOCUMENT_KEYWORDS",

    # ===== HR専門家 =====
    "HRExpert",
    "create_hr_expert",
    "RuleInfo",
    "ProcedureInfo",
    "BenefitInfo",
    "ConsultationGuide",
    "RULE_KEYWORDS",
    "PROCEDURE_KEYWORDS",
    "LEAVE_KEYWORDS",
    "BENEFIT_KEYWORDS",
    "CONSULTATION_KEYWORDS",
    "EMPLOYMENT_KEYWORDS",

    # ===== 感情ケア専門家 =====
    "EmotionExpert",
    "create_emotion_expert",
    "EmotionType",
    "SupportType",
    "UrgencyLevel",
    "EmotionState",
    "SupportResponse",
    "EmotionTrend",
    "NEGATIVE_EMOTION_KEYWORDS",
    "POSITIVE_EMOTION_KEYWORDS",
    "ENCOURAGEMENT_KEYWORDS",
    "URGENT_KEYWORDS",

    # ===== 組織専門家 =====
    "OrganizationExpert",
    "create_organization_expert",
    "RelationshipType",
    "CommunicationChannel",
    "QueryType",
    "PersonInfo",
    "DepartmentInfo",
    "RelationshipInfo",
    "RecommendationResult",
    "CommunicationRoute",
    "ORG_CHART_KEYWORDS",
    "PERSON_KEYWORDS",
    "RELATIONSHIP_KEYWORDS",
    "RECOMMENDATION_KEYWORDS",
    "COMMUNICATION_KEYWORDS",
    "EXPERTISE_KEYWORDS",
]


# =============================================================================
# バージョン情報
# =============================================================================

__version__ = "1.0.0"  # v10.37.0: Ultimate Brain Phase 3 - Multi-Agent System
