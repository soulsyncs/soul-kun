# lib/brain/deep_understanding/__init__.py
"""
Phase 2I: 理解力強化（Deep Understanding）パッケージ

設計書: docs/17_brain_completion_roadmap.md セクション17.3 Phase 2I

ソウルくんの理解力を強化する。
暗黙の意図推測、組織文脈の理解、感情・ニュアンスの読み取りを実現。

【Phase 2I の能力】
- 暗黙の意図推測（「これ」が何を指すか）
- 組織文脈の理解（「いつものやつ」の解釈）
- 感情・ニュアンスの読み取り（「ちょっと急いでる」の緊急度判断）

【主要コンポーネント】
- DeepUnderstanding: 統合クラス（メインエントリーポイント）
- IntentInferenceEngine: 暗黙の意図推測
- EmotionReader: 感情・ニュアンスの読み取り
- VocabularyManager: 組織固有語彙辞書
- HistoryAnalyzer: 会話履歴からの文脈復元

使用例:
    from lib.brain.deep_understanding import (
        DeepUnderstanding,
        DeepUnderstandingInput,
        DeepUnderstandingOutput,
        create_deep_understanding,
    )

    # 深い理解層の作成
    deep_understanding = create_deep_understanding(
        pool=db_pool,
        organization_id="org_001",
        get_ai_response_func=get_ai_response,
    )

    # メッセージの理解
    result = await deep_understanding.understand(
        message="あれどうなった？急いでるんだけど",
        input_context=DeepUnderstandingInput(
            message="あれどうなった？急いでるんだけど",
            organization_id="org_001",
            recent_conversation=[...],
            recent_tasks=[...],
        ),
    )

    # 結果の利用
    print(result.enhanced_message)  # 解決済み参照を含むメッセージ
    print(result.emotion_reading.urgency)  # 緊急度
    print(result.intent_inference.primary_intent)  # 主要な意図

Author: Claude Opus 4.5
Created: 2026-01-27
"""

__version__ = "1.0.0"
__author__ = "Claude Opus 4.5"


# =============================================================================
# 定数
# =============================================================================

from .constants import (
    # 列挙型
    ImplicitIntentType,
    ReferenceResolutionStrategy,
    OrganizationContextType,
    VocabularyCategory,
    EmotionCategory,
    UrgencyLevel,
    NuanceType,
    ContextRecoverySource,

    # 定数
    DEMONSTRATIVE_PRONOUNS,
    PERSONAL_PRONOUNS,
    VAGUE_TIME_EXPRESSIONS,
    INDIRECT_REQUEST_PATTERNS,
    INDIRECT_NEGATION_PATTERNS,
    DEFAULT_ORGANIZATION_VOCABULARY,
    EMOTION_INDICATORS,
    URGENCY_INDICATORS,
    CONTEXT_WINDOW_CONFIG,
    INTENT_CONFIDENCE_THRESHOLDS,
    EMOTION_CONFIDENCE_THRESHOLDS,
    MAX_CONTEXT_RECOVERY_ATTEMPTS,
    MAX_VOCABULARY_ENTRIES_PER_ORG,
    MIN_OCCURRENCE_FOR_VOCABULARY_LEARNING,

    # Feature Flags
    FEATURE_FLAG_DEEP_UNDERSTANDING,
    FEATURE_FLAG_IMPLICIT_INTENT,
    FEATURE_FLAG_ORGANIZATION_CONTEXT,
    FEATURE_FLAG_EMOTION_READING,
    FEATURE_FLAG_VOCABULARY_LEARNING,
)


# =============================================================================
# データモデル
# =============================================================================

from .models import (
    # 意図推測
    ResolvedReference,
    ImplicitIntent,
    IntentInferenceResult,

    # 組織文脈
    VocabularyEntry,
    OrganizationContext,
    OrganizationContextResult,

    # 感情・ニュアンス
    DetectedEmotion,
    DetectedUrgency,
    DetectedNuance,
    EmotionReadingResult,

    # 文脈復元
    ContextFragment,
    RecoveredContext,

    # 統合
    DeepUnderstandingInput,
    DeepUnderstandingOutput,

    # DB永続化
    VocabularyEntryDB,
    DeepUnderstandingLogDB,
)


# =============================================================================
# コンポーネント
# =============================================================================

from .intent_inference import (
    IntentInferenceEngine,
    create_intent_inference_engine,
)

from .emotion_reader import (
    EmotionReader,
    create_emotion_reader,
)

from .vocabulary_manager import (
    VocabularyManager,
    create_vocabulary_manager,
)

from .history_analyzer import (
    HistoryAnalyzer,
    create_history_analyzer,
)

from .deep_understanding import (
    DeepUnderstanding,
    create_deep_understanding,
)


# =============================================================================
# 公開API
# =============================================================================

__all__ = [
    # バージョン
    "__version__",

    # 定数 - 列挙型
    "ImplicitIntentType",
    "ReferenceResolutionStrategy",
    "OrganizationContextType",
    "VocabularyCategory",
    "EmotionCategory",
    "UrgencyLevel",
    "NuanceType",
    "ContextRecoverySource",

    # 定数
    "DEMONSTRATIVE_PRONOUNS",
    "PERSONAL_PRONOUNS",
    "VAGUE_TIME_EXPRESSIONS",
    "INDIRECT_REQUEST_PATTERNS",
    "INDIRECT_NEGATION_PATTERNS",
    "DEFAULT_ORGANIZATION_VOCABULARY",
    "EMOTION_INDICATORS",
    "URGENCY_INDICATORS",
    "CONTEXT_WINDOW_CONFIG",
    "INTENT_CONFIDENCE_THRESHOLDS",
    "EMOTION_CONFIDENCE_THRESHOLDS",
    "MAX_CONTEXT_RECOVERY_ATTEMPTS",
    "MAX_VOCABULARY_ENTRIES_PER_ORG",
    "MIN_OCCURRENCE_FOR_VOCABULARY_LEARNING",

    # Feature Flags
    "FEATURE_FLAG_DEEP_UNDERSTANDING",
    "FEATURE_FLAG_IMPLICIT_INTENT",
    "FEATURE_FLAG_ORGANIZATION_CONTEXT",
    "FEATURE_FLAG_EMOTION_READING",
    "FEATURE_FLAG_VOCABULARY_LEARNING",

    # モデル - 意図推測
    "ResolvedReference",
    "ImplicitIntent",
    "IntentInferenceResult",

    # モデル - 組織文脈
    "VocabularyEntry",
    "OrganizationContext",
    "OrganizationContextResult",

    # モデル - 感情・ニュアンス
    "DetectedEmotion",
    "DetectedUrgency",
    "DetectedNuance",
    "EmotionReadingResult",

    # モデル - 文脈復元
    "ContextFragment",
    "RecoveredContext",

    # モデル - 統合
    "DeepUnderstandingInput",
    "DeepUnderstandingOutput",

    # モデル - DB永続化
    "VocabularyEntryDB",
    "DeepUnderstandingLogDB",

    # コンポーネント - 意図推測
    "IntentInferenceEngine",
    "create_intent_inference_engine",

    # コンポーネント - 感情読み取り
    "EmotionReader",
    "create_emotion_reader",

    # コンポーネント - 語彙管理
    "VocabularyManager",
    "create_vocabulary_manager",

    # コンポーネント - 履歴分析
    "HistoryAnalyzer",
    "create_history_analyzer",

    # コンポーネント - 統合
    "DeepUnderstanding",
    "create_deep_understanding",
]
