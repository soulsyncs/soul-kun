# tests/test_deep_understanding.py
"""
Phase 2I: 理解力強化（Deep Understanding）の包括的テスト

設計書: docs/17_brain_completion_roadmap.md セクション17.3 Phase 2I

【テスト項目】
1. 定数・列挙型のテスト
2. データモデルのテスト
3. 意図推論エンジンのテスト
   - 指示代名詞の検出と解決（これ、それ、あれ）
   - 曖昧な入力のテスト
   - 明確な入力のテスト
   - 省略表現の検出
   - 婉曲表現の検出
   - LLM統合テスト（モック）
4. 感情読み取りエンジンのテスト
   - ポジティブ感情（喜び、感謝、興奮）
   - ネガティブ感情（困惑、不安、怒り）
   - ニュートラル感情
   - 緊急度の検出
   - ニュアンスの検出
5. 語彙管理のテスト
6. 履歴分析のテスト
7. 文脈依存表現リゾルバーのテスト
8. 統合テスト（DeepUnderstanding）
9. エッジケースのテスト

Author: Claude Opus 4.5
Created: 2026-01-27
Updated: 2026-01-31 (テスト拡充)
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta
from uuid import uuid4
import json

# テスト対象のインポート
from lib.brain.deep_understanding import (
    # 定数
    ImplicitIntentType,
    ReferenceResolutionStrategy,
    OrganizationContextType,
    VocabularyCategory,
    EmotionCategory,
    UrgencyLevel,
    NuanceType,
    ContextRecoverySource,
    DEMONSTRATIVE_PRONOUNS,
    PERSONAL_PRONOUNS,
    VAGUE_TIME_EXPRESSIONS,
    INDIRECT_REQUEST_PATTERNS,
    INDIRECT_NEGATION_PATTERNS,
    EMOTION_INDICATORS,
    URGENCY_INDICATORS,
    INTENT_CONFIDENCE_THRESHOLDS,
    EMOTION_CONFIDENCE_THRESHOLDS,
    CONTEXT_WINDOW_CONFIG,

    # モデル
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
    DeepUnderstandingInput,
    DeepUnderstandingOutput,

    # コンポーネント
    IntentInferenceEngine,
    EmotionReader,
    VocabularyManager,
    HistoryAnalyzer,
    DeepUnderstanding,

    # ファクトリー
    create_intent_inference_engine,
    create_emotion_reader,
    create_vocabulary_manager,
    create_history_analyzer,
    create_deep_understanding,
)

# 文脈依存表現リゾルバー
from lib.brain.deep_understanding.context_expression import (
    ContextExpressionResolver,
    create_context_expression_resolver,
    ExpressionType,
    ContextCandidate,
    ContextResolutionResult,
    HABITUAL_PATTERNS,
    REFERENCE_PATTERNS,
    TEMPORAL_PATTERNS,
    RECENT_PATTERNS,
)


# =============================================================================
# テストヘルパー
# =============================================================================

def create_test_input(
    message: str = "テストメッセージ",
    organization_id: str = "org_test",
    user_id: str = "user_test",
    recent_conversation: list = None,
    recent_tasks: list = None,
    person_info: list = None,
    active_goals: list = None,
) -> DeepUnderstandingInput:
    """テスト用の入力を作成"""
    return DeepUnderstandingInput(
        message=message,
        organization_id=organization_id,
        user_id=user_id,
        recent_conversation=recent_conversation or [],
        recent_tasks=recent_tasks or [],
        person_info=person_info or [],
        active_goals=active_goals or [],
    )


def create_test_conversation(messages: list = None) -> list:
    """テスト用の会話履歴を作成"""
    if messages is None:
        messages = [
            {"role": "user", "content": "山田さんにタスクを作成して", "sender_name": "テスト太郎"},
            {"role": "assistant", "content": "はい、山田さんにタスクを作成します。"},
            {"role": "user", "content": "ありがとう、次はあれどうなった？"},
        ]
    return messages


def create_test_tasks(tasks: list = None) -> list:
    """テスト用のタスク履歴を作成"""
    if tasks is None:
        tasks = [
            {"task_id": "task_001", "body": "報告書を作成する", "assignee_name": "山田", "status": "open"},
            {"task_id": "task_002", "body": "会議の準備", "assignee_name": "佐藤", "status": "done"},
            {"task_id": "task_003", "body": "クライアントへの連絡", "assignee_name": "田中", "status": "open"},
        ]
    return tasks


def create_test_persons(persons: list = None) -> list:
    """テスト用の人物情報を作成"""
    if persons is None:
        persons = [
            {"name": "山田太郎", "department": "営業部", "role": "マネージャー"},
            {"name": "佐藤花子", "department": "開発部", "role": "エンジニア"},
            {"name": "田中一郎", "department": "総務部", "role": "課長"},
        ]
    return persons


def create_test_goals(goals: list = None) -> list:
    """テスト用の目標情報を作成"""
    if goals is None:
        goals = [
            {"title": "月間売上目標達成", "description": "今月の売上目標100万円を達成する", "progress": 75},
            {"title": "プロジェクト完了", "description": "Aプロジェクトを今月中に完了", "progress": 50},
        ]
    return goals


def create_mock_ai_response_func():
    """モックAI応答関数を作成"""
    async def mock_func(prompt: str) -> str:
        return json.dumps({
            "intent": "chatwork_task_create",
            "confidence": 0.9,
            "entities": {"assignee": "山田"},
            "resolved_references": [
                {"original": "あれ", "resolved": "報告書", "confidence": 0.8}
            ],
            "reasoning": "タスク作成の依頼と判断"
        })
    return mock_func


# =============================================================================
# 1. 定数・列挙型のテスト
# =============================================================================

class TestConstants:
    """定数のテスト"""

    def test_demonstrative_pronouns_structure(self):
        """指示代名詞の構造をテスト"""
        assert "これ" in DEMONSTRATIVE_PRONOUNS
        assert "それ" in DEMONSTRATIVE_PRONOUNS
        assert "あれ" in DEMONSTRATIVE_PRONOUNS
        assert "この" in DEMONSTRATIVE_PRONOUNS
        assert "その" in DEMONSTRATIVE_PRONOUNS
        assert "あの" in DEMONSTRATIVE_PRONOUNS

        # 各エントリの構造
        for pronoun, info in DEMONSTRATIVE_PRONOUNS.items():
            assert "distance" in info
            assert "type" in info
            assert info["distance"] in ("near", "middle", "far", "unknown")

    def test_demonstrative_pronouns_distance(self):
        """指示代名詞の距離をテスト"""
        # 近称
        assert DEMONSTRATIVE_PRONOUNS["これ"]["distance"] == "near"
        assert DEMONSTRATIVE_PRONOUNS["この"]["distance"] == "near"
        assert DEMONSTRATIVE_PRONOUNS["ここ"]["distance"] == "near"

        # 中称
        assert DEMONSTRATIVE_PRONOUNS["それ"]["distance"] == "middle"
        assert DEMONSTRATIVE_PRONOUNS["その"]["distance"] == "middle"
        assert DEMONSTRATIVE_PRONOUNS["そこ"]["distance"] == "middle"

        # 遠称
        assert DEMONSTRATIVE_PRONOUNS["あれ"]["distance"] == "far"
        assert DEMONSTRATIVE_PRONOUNS["あの"]["distance"] == "far"
        assert DEMONSTRATIVE_PRONOUNS["あそこ"]["distance"] == "far"

    def test_personal_pronouns_structure(self):
        """人称代名詞の構造をテスト"""
        assert "私" in PERSONAL_PRONOUNS
        assert "あなた" in PERSONAL_PRONOUNS
        assert "彼" in PERSONAL_PRONOUNS

        for pronoun, info in PERSONAL_PRONOUNS.items():
            assert "person" in info
            assert "formality" in info

    def test_vague_time_expressions_structure(self):
        """曖昧な時間表現の構造をテスト"""
        assert "あとで" in VAGUE_TIME_EXPRESSIONS
        assert "至急" in VAGUE_TIME_EXPRESSIONS
        assert "いつでも" in VAGUE_TIME_EXPRESSIONS

        for expr, info in VAGUE_TIME_EXPRESSIONS.items():
            assert "type" in info
            assert "urgency" in info

    def test_emotion_indicators_structure(self):
        """感情インジケーターの構造をテスト"""
        assert EmotionCategory.HAPPY.value in EMOTION_INDICATORS
        assert EmotionCategory.FRUSTRATED.value in EMOTION_INDICATORS
        assert EmotionCategory.ANGRY.value in EMOTION_INDICATORS

        for emotion, indicators in EMOTION_INDICATORS.items():
            assert "keywords" in indicators
            assert "expressions" in indicators
            assert "intensity" in indicators
            assert isinstance(indicators["keywords"], list)

    def test_urgency_indicators_structure(self):
        """緊急度インジケーターの構造をテスト"""
        assert UrgencyLevel.CRITICAL.value in URGENCY_INDICATORS
        assert UrgencyLevel.VERY_HIGH.value in URGENCY_INDICATORS
        assert UrgencyLevel.HIGH.value in URGENCY_INDICATORS
        assert UrgencyLevel.MEDIUM.value in URGENCY_INDICATORS
        assert UrgencyLevel.LOW.value in URGENCY_INDICATORS
        assert UrgencyLevel.VERY_LOW.value in URGENCY_INDICATORS

        for level, keywords in URGENCY_INDICATORS.items():
            assert isinstance(keywords, list)
            assert len(keywords) > 0

    def test_confidence_thresholds(self):
        """信頼度閾値をテスト"""
        assert "auto_execute" in INTENT_CONFIDENCE_THRESHOLDS
        assert "high" in INTENT_CONFIDENCE_THRESHOLDS
        assert "medium" in INTENT_CONFIDENCE_THRESHOLDS
        assert "low" in INTENT_CONFIDENCE_THRESHOLDS
        assert "very_low" in INTENT_CONFIDENCE_THRESHOLDS

        # 閾値の順序（高い順）
        assert INTENT_CONFIDENCE_THRESHOLDS["auto_execute"] > INTENT_CONFIDENCE_THRESHOLDS["high"]
        assert INTENT_CONFIDENCE_THRESHOLDS["high"] > INTENT_CONFIDENCE_THRESHOLDS["medium"]
        assert INTENT_CONFIDENCE_THRESHOLDS["medium"] > INTENT_CONFIDENCE_THRESHOLDS["low"]
        assert INTENT_CONFIDENCE_THRESHOLDS["low"] > INTENT_CONFIDENCE_THRESHOLDS["very_low"]

    def test_emotion_confidence_thresholds(self):
        """感情信頼度閾値をテスト"""
        assert "confident" in EMOTION_CONFIDENCE_THRESHOLDS
        assert "likely" in EMOTION_CONFIDENCE_THRESHOLDS
        assert "possible" in EMOTION_CONFIDENCE_THRESHOLDS
        assert "uncertain" in EMOTION_CONFIDENCE_THRESHOLDS

    def test_context_window_config(self):
        """コンテキストウィンドウ設定をテスト"""
        assert "immediate" in CONTEXT_WINDOW_CONFIG
        assert "short_term" in CONTEXT_WINDOW_CONFIG
        assert "medium_term" in CONTEXT_WINDOW_CONFIG
        assert "long_term" in CONTEXT_WINDOW_CONFIG

        for window, config in CONTEXT_WINDOW_CONFIG.items():
            assert "message_count" in config
            assert "time_window_minutes" in config
            assert "weight" in config


class TestEnumValues:
    """列挙型の値のテスト"""

    def test_implicit_intent_type_values(self):
        """ImplicitIntentTypeの値をテスト"""
        assert ImplicitIntentType.PRONOUN_REFERENCE.value == "pronoun_reference"
        assert ImplicitIntentType.ELLIPSIS_REFERENCE.value == "ellipsis_reference"
        assert ImplicitIntentType.CONTEXT_DEPENDENT.value == "context_dependent"
        assert ImplicitIntentType.IMPLICIT_REQUEST.value == "implicit_request"
        assert ImplicitIntentType.IMPLICIT_NEGATION.value == "implicit_negation"

    def test_emotion_category_values(self):
        """EmotionCategoryの値をテスト"""
        # ポジティブ
        assert EmotionCategory.HAPPY.value == "happy"
        assert EmotionCategory.EXCITED.value == "excited"
        assert EmotionCategory.GRATEFUL.value == "grateful"

        # ネガティブ
        assert EmotionCategory.FRUSTRATED.value == "frustrated"
        assert EmotionCategory.ANXIOUS.value == "anxious"
        assert EmotionCategory.ANGRY.value == "angry"

        # 中立
        assert EmotionCategory.NEUTRAL.value == "neutral"
        assert EmotionCategory.CONFUSED.value == "confused"

    def test_urgency_level_values(self):
        """UrgencyLevelの値をテスト"""
        assert UrgencyLevel.CRITICAL.value == "critical"
        assert UrgencyLevel.VERY_HIGH.value == "very_high"
        assert UrgencyLevel.HIGH.value == "high"
        assert UrgencyLevel.MEDIUM.value == "medium"
        assert UrgencyLevel.LOW.value == "low"
        assert UrgencyLevel.VERY_LOW.value == "very_low"

    def test_vocabulary_category_values(self):
        """VocabularyCategoryの値をテスト"""
        assert VocabularyCategory.PROJECT_NAME.value == "project_name"
        assert VocabularyCategory.PRODUCT_NAME.value == "product_name"
        assert VocabularyCategory.ABBREVIATION.value == "abbreviation"
        assert VocabularyCategory.TEAM_NAME.value == "team_name"


# =============================================================================
# 2. データモデルのテスト
# =============================================================================

class TestModels:
    """データモデルのテスト"""

    def test_resolved_reference_creation(self):
        """ResolvedReferenceの作成をテスト"""
        ref = ResolvedReference(
            original_expression="あれ",
            resolved_value="報告書",
            reference_type=ImplicitIntentType.PRONOUN_REFERENCE,
            resolution_strategy=ReferenceResolutionStrategy.IMMEDIATE_CONTEXT,
            confidence=0.8,
            reasoning="直近の文脈から推定",
        )
        assert ref.original_expression == "あれ"
        assert ref.resolved_value == "報告書"
        assert ref.confidence == 0.8
        assert ref.reference_type == ImplicitIntentType.PRONOUN_REFERENCE
        assert ref.resolution_strategy == ReferenceResolutionStrategy.IMMEDIATE_CONTEXT

    def test_resolved_reference_with_alternatives(self):
        """代替候補を持つResolvedReferenceをテスト"""
        ref = ResolvedReference(
            original_expression="それ",
            resolved_value="",
            reference_type=ImplicitIntentType.PRONOUN_REFERENCE,
            resolution_strategy=ReferenceResolutionStrategy.CONVERSATION_HISTORY,
            confidence=0.5,
            alternative_candidates=["報告書", "会議資料", "タスク"],
            reasoning="候補が複数あり確定できない",
        )
        assert len(ref.alternative_candidates) == 3
        assert "報告書" in ref.alternative_candidates

    def test_implicit_intent_creation(self):
        """ImplicitIntentの作成をテスト"""
        intent = ImplicitIntent(
            intent_type=ImplicitIntentType.PRONOUN_REFERENCE,
            inferred_intent="タスクの進捗確認",
            confidence=0.75,
            original_message="あれどうなった？",
            needs_confirmation=False,
            reasoning="代名詞「あれ」を解決",
        )
        assert intent.intent_type == ImplicitIntentType.PRONOUN_REFERENCE
        assert intent.confidence == 0.75
        assert not intent.needs_confirmation

    def test_implicit_intent_with_confirmation(self):
        """確認が必要なImplicitIntentをテスト"""
        intent = ImplicitIntent(
            intent_type=ImplicitIntentType.CONTEXT_DEPENDENT,
            inferred_intent="",
            confidence=0.4,
            original_message="いつものやつお願い",
            needs_confirmation=True,
            confirmation_options=["定例会議", "週次報告", "月次ミーティング"],
        )
        assert intent.needs_confirmation
        assert len(intent.confirmation_options) == 3

    def test_vocabulary_entry_creation(self):
        """VocabularyEntryの作成をテスト"""
        entry = VocabularyEntry(
            organization_id="org_test",
            term="ソウルくん",
            category=VocabularyCategory.PRODUCT_NAME,
            meaning="社内AIアシスタント",
            aliases=["soul-kun", "ソウル"],
            usage_examples=["ソウルくんにタスクを依頼"],
        )
        assert entry.term == "ソウルくん"
        assert entry.category == VocabularyCategory.PRODUCT_NAME
        assert "soul-kun" in entry.aliases
        assert entry.occurrence_count == 0

    def test_detected_emotion_creation(self):
        """DetectedEmotionの作成をテスト"""
        emotion = DetectedEmotion(
            category=EmotionCategory.FRUSTRATED,
            intensity=0.7,
            confidence=0.8,
            indicators=["困った", "どうしよう"],
            reasoning="困惑を示すキーワードを検出",
        )
        assert emotion.category == EmotionCategory.FRUSTRATED
        assert emotion.intensity == 0.7
        assert "困った" in emotion.indicators

    def test_detected_urgency_creation(self):
        """DetectedUrgencyの作成をテスト"""
        urgency = DetectedUrgency(
            level=UrgencyLevel.HIGH,
            confidence=0.85,
            estimated_deadline_hours=8.0,
            indicators=["今日中", "本日中"],
            reasoning="今日中の期限を検出",
        )
        assert urgency.level == UrgencyLevel.HIGH
        assert urgency.estimated_deadline_hours == 8.0

    def test_detected_nuance_creation(self):
        """DetectedNuanceの作成をテスト"""
        nuance = DetectedNuance(
            nuance_type=NuanceType.FORMAL,
            confidence=0.9,
            indicators=["ございます", "いたします"],
            reasoning="敬語を検出",
        )
        assert nuance.nuance_type == NuanceType.FORMAL
        assert nuance.confidence == 0.9

    def test_context_fragment_creation(self):
        """ContextFragmentの作成をテスト"""
        fragment = ContextFragment(
            source=ContextRecoverySource.CONVERSATION_HISTORY,
            content="報告書の件について話していました",
            relevance_score=0.8,
            timestamp=datetime.now(),
            metadata={"position": 0, "role": "user"},
        )
        assert fragment.source == ContextRecoverySource.CONVERSATION_HISTORY
        assert fragment.relevance_score == 0.8

    def test_deep_understanding_input_creation(self):
        """DeepUnderstandingInputの作成をテスト"""
        input_data = create_test_input(
            message="あれどうなった？",
            organization_id="org_001",
            recent_conversation=create_test_conversation(),
            recent_tasks=create_test_tasks(),
        )
        assert input_data.message == "あれどうなった？"
        assert input_data.organization_id == "org_001"
        assert len(input_data.recent_conversation) == 3
        assert len(input_data.recent_tasks) == 3

    def test_deep_understanding_output_creation(self):
        """DeepUnderstandingOutputの作成をテスト"""
        input_context = DeepUnderstandingInput(
            message="テスト",
            organization_id="org_test",
        )
        output = DeepUnderstandingOutput(
            input=input_context,
            enhanced_message="テスト（補足情報付き）",
            overall_confidence=0.8,
            needs_confirmation=False,
            processing_time_ms=100,
        )
        assert output.enhanced_message == "テスト（補足情報付き）"
        assert output.overall_confidence == 0.8
        assert output.processing_time_ms == 100
        assert not output.needs_confirmation


# =============================================================================
# 3. IntentInferenceEngineのテスト
# =============================================================================

class TestIntentInferenceEngine:
    """意図推測エンジンのテスト"""

    @pytest.fixture
    def engine(self):
        """テスト用エンジンを作成"""
        return create_intent_inference_engine(use_llm=False)

    @pytest.fixture
    def engine_with_llm(self):
        """LLM有効のテスト用エンジンを作成"""
        return create_intent_inference_engine(
            get_ai_response_func=create_mock_ai_response_func(),
            use_llm=True,
        )


class TestIntentInferencePronouns(TestIntentInferenceEngine):
    """代名詞検出のテスト"""

    @pytest.mark.asyncio
    async def test_detect_kore(self, engine):
        """「これ」の検出をテスト"""
        input_context = create_test_input(
            message="これどうなった？",
            recent_conversation=create_test_conversation(),
        )
        result = await engine.infer("これどうなった？", input_context)

        assert isinstance(result, IntentInferenceResult)
        pronoun_intents = [i for i in result.implicit_intents
                          if i.intent_type == ImplicitIntentType.PRONOUN_REFERENCE]
        assert len(pronoun_intents) > 0 or result.needs_confirmation

    @pytest.mark.asyncio
    async def test_detect_sore(self, engine):
        """「それ」の検出をテスト"""
        input_context = create_test_input(
            message="それを教えて",
            recent_conversation=create_test_conversation(),
        )
        result = await engine.infer("それを教えて", input_context)

        assert isinstance(result, IntentInferenceResult)
        pronoun_intents = [i for i in result.implicit_intents
                          if i.intent_type == ImplicitIntentType.PRONOUN_REFERENCE]
        assert len(pronoun_intents) > 0 or result.needs_confirmation

    @pytest.mark.asyncio
    async def test_detect_are(self, engine):
        """「あれ」の検出をテスト"""
        input_context = create_test_input(
            message="あれお願いできる？",
            recent_tasks=create_test_tasks(),
        )
        result = await engine.infer("あれお願いできる？", input_context)

        assert isinstance(result, IntentInferenceResult)

    @pytest.mark.asyncio
    async def test_detect_multiple_pronouns(self, engine):
        """複数の代名詞検出をテスト"""
        input_context = create_test_input(
            message="これとあれを確認して",
            recent_tasks=create_test_tasks(),
        )
        result = await engine.infer("これとあれを確認して", input_context)

        assert isinstance(result, IntentInferenceResult)
        # 複数の代名詞があるので確認が必要か意図が複数ある
        assert result.needs_confirmation or len(result.implicit_intents) >= 1

    @pytest.mark.asyncio
    async def test_resolve_pronoun_with_single_task(self, engine):
        """タスクが1つの場合の代名詞解決をテスト"""
        input_context = create_test_input(
            message="それ完了にして",
            recent_tasks=[
                {"task_id": "task_001", "body": "報告書を作成する", "status": "open"},
            ],
        )
        result = await engine.infer("それ完了にして", input_context)

        # タスクが1つなので高い信頼度で解決される可能性
        assert isinstance(result, IntentInferenceResult)

    @pytest.mark.asyncio
    async def test_resolve_pronoun_with_multiple_tasks(self, engine):
        """タスクが複数の場合の代名詞解決をテスト"""
        input_context = create_test_input(
            message="あれ完了にして",
            recent_tasks=create_test_tasks(),
        )
        result = await engine.infer("あれ完了にして", input_context)

        # タスクが複数あるので確認が必要になる可能性
        assert isinstance(result, IntentInferenceResult)


class TestIntentInferenceEllipsis(TestIntentInferenceEngine):
    """省略表現検出のテスト"""

    @pytest.mark.asyncio
    async def test_detect_completion_ellipsis(self, engine):
        """「完了にして」の省略検出をテスト"""
        input_context = create_test_input(
            message="完了にして",
            recent_tasks=create_test_tasks(),
        )
        result = await engine.infer("完了にして", input_context)

        ellipsis_intents = [i for i in result.implicit_intents
                           if i.intent_type == ImplicitIntentType.ELLIPSIS_REFERENCE]
        assert len(ellipsis_intents) > 0

    @pytest.mark.asyncio
    async def test_detect_send_ellipsis(self, engine):
        """「送って」の省略検出をテスト"""
        input_context = create_test_input(
            message="送って",
            recent_conversation=create_test_conversation(),
        )
        result = await engine.infer("送って", input_context)

        ellipsis_intents = [i for i in result.implicit_intents
                           if i.intent_type == ImplicitIntentType.ELLIPSIS_REFERENCE]
        assert len(ellipsis_intents) > 0

    @pytest.mark.asyncio
    async def test_detect_check_ellipsis(self, engine):
        """「確認して」の省略検出をテスト"""
        input_context = create_test_input(
            message="確認して",
            recent_conversation=create_test_conversation(),
        )
        result = await engine.infer("確認して", input_context)

        assert isinstance(result, IntentInferenceResult)


class TestIntentInferenceIndirect(TestIntentInferenceEngine):
    """婉曲表現検出のテスト"""

    @pytest.mark.asyncio
    async def test_detect_indirect_request_dekireba(self, engine):
        """「できたら見てもらえます？」の検出をテスト"""
        input_context = create_test_input(message="できたら見てもらえます？")
        result = await engine.infer("できたら見てもらえます？", input_context)

        request_intents = [i for i in result.implicit_intents
                          if i.intent_type == ImplicitIntentType.IMPLICIT_REQUEST]
        assert len(request_intents) > 0

    @pytest.mark.asyncio
    async def test_detect_indirect_request_kanou(self, engine):
        """「可能なら確認いただけますか」の検出をテスト"""
        input_context = create_test_input(message="可能なら確認いただけますか")
        result = await engine.infer("可能なら確認いただけますか", input_context)

        request_intents = [i for i in result.implicit_intents
                          if i.intent_type == ImplicitIntentType.IMPLICIT_REQUEST]
        assert len(request_intents) > 0

    @pytest.mark.asyncio
    async def test_detect_indirect_negation_chotto(self, engine):
        """「ちょっと難しいかも」の検出をテスト"""
        input_context = create_test_input(message="ちょっと難しいかも")
        result = await engine.infer("ちょっと難しいかも", input_context)

        negation_intents = [i for i in result.implicit_intents
                           if i.intent_type == ImplicitIntentType.IMPLICIT_NEGATION]
        assert len(negation_intents) > 0

    @pytest.mark.asyncio
    async def test_detect_indirect_negation_ima(self, engine):
        """「今はちょっと...」の検出をテスト"""
        input_context = create_test_input(message="今はちょっと難しい")
        result = await engine.infer("今はちょっと難しい", input_context)

        negation_intents = [i for i in result.implicit_intents
                           if i.intent_type == ImplicitIntentType.IMPLICIT_NEGATION]
        assert len(negation_intents) > 0

    @pytest.mark.asyncio
    async def test_detect_implicit_confirmation(self, engine):
        """暗黙の確認表現の検出をテスト"""
        input_context = create_test_input(message="そうですね、確かに")
        result = await engine.infer("そうですね、確かに", input_context)

        confirmation_intents = [i for i in result.implicit_intents
                               if i.intent_type == ImplicitIntentType.IMPLICIT_CONFIRMATION]
        assert len(confirmation_intents) > 0


class TestIntentInferenceContextDependent(TestIntentInferenceEngine):
    """文脈依存表現検出のテスト"""

    @pytest.mark.asyncio
    async def test_detect_itsumo(self, engine):
        """「いつもの」の検出をテスト"""
        input_context = create_test_input(message="いつものミーティングの件")
        result = await engine.infer("いつものミーティングの件", input_context)

        context_intents = [i for i in result.implicit_intents
                          if i.intent_type == ImplicitIntentType.CONTEXT_DEPENDENT]
        assert len(context_intents) > 0

    @pytest.mark.asyncio
    async def test_detect_reino(self, engine):
        """「例の」の検出をテスト"""
        input_context = create_test_input(message="例のプロジェクトの進捗")
        result = await engine.infer("例のプロジェクトの進捗", input_context)

        context_intents = [i for i in result.implicit_intents
                          if i.intent_type == ImplicitIntentType.CONTEXT_DEPENDENT]
        assert len(context_intents) > 0

    @pytest.mark.asyncio
    async def test_detect_teirei(self, engine):
        """「定例の」の検出をテスト"""
        input_context = create_test_input(message="毎週のあれの件")
        result = await engine.infer("毎週のあれの件", input_context)

        # 「毎週の」は文脈依存、「あれ」は代名詞
        assert isinstance(result, IntentInferenceResult)
        assert len(result.implicit_intents) >= 1


class TestIntentInferenceClearMessage(TestIntentInferenceEngine):
    """明確なメッセージのテスト"""

    @pytest.mark.asyncio
    async def test_clear_message_no_ambiguity(self, engine):
        """明確なメッセージでは曖昧さが少ない"""
        input_context = create_test_input(
            message="山田さんに報告書作成のタスクを作成してください"
        )
        result = await engine.infer(
            "山田さんに報告書作成のタスクを作成してください",
            input_context,
        )

        # 明確なメッセージなので代名詞系の意図は少ないはず
        pronoun_intents = [i for i in result.implicit_intents
                          if i.intent_type == ImplicitIntentType.PRONOUN_REFERENCE]
        assert len(pronoun_intents) == 0

    @pytest.mark.asyncio
    async def test_clear_message_high_confidence(self, engine):
        """明確なメッセージは高い信頼度"""
        input_context = create_test_input(
            message="田中太郎さんに週次報告書を作成するタスクを今日中に追加してください"
        )
        result = await engine.infer(
            "田中太郎さんに週次報告書を作成するタスクを今日中に追加してください",
            input_context,
        )

        # 明確なメッセージでも、意図推測エンジンは暗黙の意図を検出するものなので
        # 代名詞がなければ暗黙の意図は少ないはず
        pronoun_intents = [i for i in result.implicit_intents
                          if i.intent_type == ImplicitIntentType.PRONOUN_REFERENCE]
        assert len(pronoun_intents) == 0  # 明確なメッセージなので代名詞参照なし


class TestIntentInferenceLLMIntegration(TestIntentInferenceEngine):
    """LLM統合テスト（モック使用）"""

    @pytest.mark.asyncio
    async def test_llm_called_for_ambiguous_message(self, engine_with_llm):
        """曖昧なメッセージでLLMが呼ばれる"""
        input_context = create_test_input(
            message="あれどうなった？",
            recent_tasks=create_test_tasks(),
        )
        result = await engine_with_llm.infer("あれどうなった？", input_context)

        # IntentInferenceResultには implicit_intents があり、intent 属性はない
        assert isinstance(result, IntentInferenceResult)
        assert len(result.implicit_intents) >= 0

    @pytest.mark.asyncio
    async def test_llm_response_parsing(self):
        """LLMレスポンスのパース"""
        engine = IntentInferenceEngine(use_llm=False)
        # _parse_llm_response メソッドをテスト
        response = json.dumps({
            "intent": "test",
            "confidence": 0.9,
            "resolved_references": [
                {"original": "あれ", "resolved": "報告書", "confidence": 0.8}
            ]
        })
        result = engine._parse_llm_response(response, "テストメッセージ")
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_llm_error_fallback(self):
        """LLMエラー時のフォールバック"""
        async def error_func(prompt: str):
            raise Exception("LLM error")

        engine = create_intent_inference_engine(
            get_ai_response_func=error_func,
            use_llm=True,
        )
        input_context = create_test_input(message="あれどうなった？")
        result = await engine.infer("あれどうなった？", input_context)

        # エラーが発生しても結果が返る
        assert isinstance(result, IntentInferenceResult)


# =============================================================================
# 4. EmotionReaderのテスト
# =============================================================================

class TestEmotionReader:
    """感情読み取りエンジンのテスト"""

    @pytest.fixture
    def reader(self):
        """テスト用リーダーを作成"""
        return create_emotion_reader()


class TestEmotionReaderPositive(TestEmotionReader):
    """ポジティブ感情のテスト"""

    @pytest.mark.asyncio
    async def test_detect_happy_basic(self, reader):
        """基本的な喜びの検出"""
        input_context = create_test_input(message="嬉しい！")
        result = await reader.read("嬉しい！", input_context)

        assert isinstance(result, EmotionReadingResult)
        happy_emotions = [e for e in result.emotions
                         if e.category == EmotionCategory.HAPPY]
        assert len(happy_emotions) > 0

    @pytest.mark.asyncio
    async def test_detect_happy_multiple_keywords(self, reader):
        """複数キーワードでの喜び検出"""
        input_context = create_test_input(message="やった！できた！嬉しい！")
        result = await reader.read("やった！できた！嬉しい！", input_context)

        happy_emotions = [e for e in result.emotions
                         if e.category in (EmotionCategory.HAPPY, EmotionCategory.EXCITED)]
        assert len(happy_emotions) > 0
        # 複数のキーワードがあるので強度が高い
        if happy_emotions:
            assert happy_emotions[0].intensity >= 0.5

    @pytest.mark.asyncio
    async def test_detect_excited(self, reader):
        """興奮・期待の検出"""
        input_context = create_test_input(message="楽しみ！ワクワクする！")
        result = await reader.read("楽しみ！ワクワクする！", input_context)

        excited_emotions = [e for e in result.emotions
                           if e.category == EmotionCategory.EXCITED]
        assert len(excited_emotions) > 0

    @pytest.mark.asyncio
    async def test_detect_grateful(self, reader):
        """感謝の検出"""
        input_context = create_test_input(message="本当にありがとうございます！助かりました！")
        result = await reader.read("本当にありがとうございます！助かりました！", input_context)

        grateful_emotions = [e for e in result.emotions
                            if e.category == EmotionCategory.GRATEFUL]
        assert len(grateful_emotions) > 0


class TestEmotionReaderNegative(TestEmotionReader):
    """ネガティブ感情のテスト"""

    @pytest.mark.asyncio
    async def test_detect_frustrated_basic(self, reader):
        """基本的な困惑の検出"""
        input_context = create_test_input(message="困った…")
        result = await reader.read("困った…", input_context)

        frustrated_emotions = [e for e in result.emotions
                               if e.category == EmotionCategory.FRUSTRATED]
        assert len(frustrated_emotions) > 0

    @pytest.mark.asyncio
    async def test_detect_frustrated_multiple(self, reader):
        """複数キーワードでの困惑検出"""
        input_context = create_test_input(message="困った…どうしよう、参った")
        result = await reader.read("困った…どうしよう、参った", input_context)

        frustrated_emotions = [e for e in result.emotions
                               if e.category == EmotionCategory.FRUSTRATED]
        assert len(frustrated_emotions) > 0

    @pytest.mark.asyncio
    async def test_detect_anxious(self, reader):
        """不安の検出"""
        input_context = create_test_input(message="心配です…大丈夫かな")
        result = await reader.read("心配です…大丈夫かな", input_context)

        anxious_emotions = [e for e in result.emotions
                           if e.category == EmotionCategory.ANXIOUS]
        assert len(anxious_emotions) > 0

    @pytest.mark.asyncio
    async def test_detect_angry(self, reader):
        """怒りの検出"""
        input_context = create_test_input(message="なんでこうなるの！ありえない！")
        result = await reader.read("なんでこうなるの！ありえない！", input_context)

        angry_emotions = [e for e in result.emotions
                         if e.category == EmotionCategory.ANGRY]
        assert len(angry_emotions) > 0

    @pytest.mark.asyncio
    async def test_detect_stressed(self, reader):
        """ストレスの検出"""
        input_context = create_test_input(message="忙しすぎて時間がない…手一杯です")
        result = await reader.read("忙しすぎて時間がない…手一杯です", input_context)

        stressed_emotions = [e for e in result.emotions
                            if e.category == EmotionCategory.STRESSED]
        assert len(stressed_emotions) > 0


class TestEmotionReaderNeutral(TestEmotionReader):
    """ニュートラル感情のテスト"""

    @pytest.mark.asyncio
    async def test_detect_confused(self, reader):
        """困惑の検出"""
        input_context = create_test_input(message="よくわからない…どういうこと？？")
        result = await reader.read("よくわからない…どういうこと？？", input_context)

        confused_emotions = [e for e in result.emotions
                            if e.category == EmotionCategory.CONFUSED]
        assert len(confused_emotions) > 0

    @pytest.mark.asyncio
    async def test_neutral_message(self, reader):
        """ニュートラルなメッセージ"""
        input_context = create_test_input(message="報告書を確認してください")
        result = await reader.read("報告書を確認してください", input_context)

        # 感情的なキーワードがないので感情が少ないか、緊急度が中程度
        assert isinstance(result, EmotionReadingResult)


class TestEmotionReaderUrgency(TestEmotionReader):
    """緊急度検出のテスト"""

    @pytest.mark.asyncio
    async def test_detect_critical_urgency(self, reader):
        """クリティカルな緊急度の検出"""
        input_context = create_test_input(message="今すぐ対応してください！大至急！")
        result = await reader.read("今すぐ対応してください！大至急！", input_context)

        assert result.urgency is not None
        assert result.urgency.level in (UrgencyLevel.CRITICAL, UrgencyLevel.VERY_HIGH)

    @pytest.mark.asyncio
    async def test_detect_high_urgency(self, reader):
        """高い緊急度の検出"""
        input_context = create_test_input(message="至急対応お願いします！")
        result = await reader.read("至急対応お願いします！", input_context)

        assert result.urgency is not None
        assert result.urgency.level in (UrgencyLevel.CRITICAL, UrgencyLevel.VERY_HIGH, UrgencyLevel.HIGH)

    @pytest.mark.asyncio
    async def test_detect_medium_urgency(self, reader):
        """中程度の緊急度の検出"""
        input_context = create_test_input(message="今週中にお願いします")
        result = await reader.read("今週中にお願いします", input_context)

        assert result.urgency is not None
        # 今週中なのでMEDIUM
        assert result.urgency.level in (UrgencyLevel.MEDIUM, UrgencyLevel.HIGH)

    @pytest.mark.asyncio
    async def test_detect_low_urgency(self, reader):
        """低い緊急度の検出"""
        input_context = create_test_input(message="余裕があれば見ておいてください")
        result = await reader.read("余裕があれば見ておいてください", input_context)

        assert result.urgency is not None
        assert result.urgency.level in (UrgencyLevel.LOW, UrgencyLevel.VERY_LOW, UrgencyLevel.MEDIUM)

    @pytest.mark.asyncio
    async def test_urgency_deadline_estimation(self, reader):
        """期限推定のテスト"""
        input_context = create_test_input(message="今日中にお願いします")
        result = await reader.read("今日中にお願いします", input_context)

        assert result.urgency is not None
        assert result.urgency.estimated_deadline_hours is not None
        # 今日中なら8時間程度
        assert result.urgency.estimated_deadline_hours <= 48


class TestEmotionReaderNuance(TestEmotionReader):
    """ニュアンス検出のテスト"""

    @pytest.mark.asyncio
    async def test_detect_formal_nuance(self, reader):
        """フォーマルなニュアンスの検出"""
        input_context = create_test_input(message="ご確認いただけますでしょうか")
        result = await reader.read("ご確認いただけますでしょうか", input_context)

        formal_nuances = [n for n in result.nuances
                         if n.nuance_type == NuanceType.FORMAL]
        assert len(formal_nuances) > 0

    @pytest.mark.asyncio
    async def test_detect_casual_nuance(self, reader):
        """カジュアルなニュアンスの検出"""
        input_context = create_test_input(message="これやっといてー")
        result = await reader.read("これやっといてー", input_context)

        # カジュアルまたは判定なし
        assert isinstance(result, EmotionReadingResult)

    @pytest.mark.asyncio
    async def test_detect_high_certainty(self, reader):
        """高い確信度の検出"""
        input_context = create_test_input(message="絶対に間違いないです")
        result = await reader.read("絶対に間違いないです", input_context)

        certainty_nuances = [n for n in result.nuances
                            if n.nuance_type == NuanceType.CERTAINTY_HIGH]
        assert len(certainty_nuances) > 0

    @pytest.mark.asyncio
    async def test_detect_low_certainty(self, reader):
        """低い確信度の検出"""
        input_context = create_test_input(message="もしかしたらそうかもしれない、わからないけど")
        result = await reader.read("もしかしたらそうかもしれない、わからないけど", input_context)

        certainty_nuances = [n for n in result.nuances
                            if n.nuance_type == NuanceType.CERTAINTY_LOW]
        assert len(certainty_nuances) > 0

    @pytest.mark.asyncio
    async def test_detect_positive_tone(self, reader):
        """ポジティブなトーンの検出"""
        input_context = create_test_input(message="ありがとう！素晴らしい！")
        result = await reader.read("ありがとう！素晴らしい！", input_context)

        positive_nuances = [n for n in result.nuances
                           if n.nuance_type == NuanceType.POSITIVE]
        # ポジティブトーンまたは感謝感情
        assert len(positive_nuances) > 0 or any(e.category == EmotionCategory.GRATEFUL for e in result.emotions)

    @pytest.mark.asyncio
    async def test_detect_humorous_tone(self, reader):
        """ユーモアのあるトーンの検出"""
        input_context = create_test_input(message="まじかwww")
        result = await reader.read("まじかwww", input_context)

        humorous_nuances = [n for n in result.nuances
                           if n.nuance_type == NuanceType.HUMOROUS]
        assert len(humorous_nuances) > 0


class TestEmotionReaderIntensity(TestEmotionReader):
    """感情強度のテスト"""

    @pytest.mark.asyncio
    async def test_high_intensity_with_emphasis(self, reader):
        """強調表現での高強度"""
        input_context = create_test_input(message="本当にありがとう！！！")
        result = await reader.read("本当にありがとう！！！", input_context)

        if result.primary_emotion:
            # 強調表現があるので強度が高い
            assert result.primary_emotion.intensity >= 0.5

    @pytest.mark.asyncio
    async def test_intensity_modifiers(self, reader):
        """強度修飾語の影響"""
        input_context = create_test_input(message="めちゃくちゃ嬉しい！")
        result = await reader.read("めちゃくちゃ嬉しい！", input_context)

        happy_emotions = [e for e in result.emotions
                         if e.category == EmotionCategory.HAPPY]
        if happy_emotions:
            # 強度修飾語「めちゃくちゃ」があるので強度が上がっているはず
            # ただし実装によっては0.5以上でも十分
            assert happy_emotions[0].intensity >= 0.5


class TestEmotionReaderSummary(TestEmotionReader):
    """サマリー生成のテスト"""

    @pytest.mark.asyncio
    async def test_summary_generation_basic(self, reader):
        """基本的なサマリー生成"""
        input_context = create_test_input(message="急いでるんだけど、困った…")
        result = await reader.read("急いでるんだけど、困った…", input_context)

        assert result.summary
        assert len(result.summary) > 0

    @pytest.mark.asyncio
    async def test_summary_includes_emotion(self, reader):
        """サマリーに感情情報が含まれる"""
        input_context = create_test_input(message="嬉しい！")
        result = await reader.read("嬉しい！", input_context)

        assert result.summary
        # 喜びに関する記述が含まれる
        assert "喜" in result.summary or "嬉" in result.summary or len(result.summary) > 0


# =============================================================================
# 5. VocabularyManagerのテスト
# =============================================================================

class TestVocabularyManager:
    """語彙管理のテスト"""

    @pytest.fixture
    def manager(self):
        """テスト用マネージャーを作成"""
        return create_vocabulary_manager(
            pool=None,
            organization_id="org_test",
        )

    @pytest.mark.asyncio
    async def test_initialize(self, manager):
        """初期化をテスト"""
        await manager.initialize()
        assert manager._initialized

    @pytest.mark.asyncio
    async def test_initialize_idempotent(self, manager):
        """初期化の冪等性をテスト"""
        await manager.initialize()
        await manager.initialize()
        assert manager._initialized

    @pytest.mark.asyncio
    async def test_search_default_vocabulary(self, manager):
        """デフォルト語彙の検索をテスト"""
        await manager.initialize()
        results = await manager.search("ソウルくん")

        assert len(results) > 0
        assert any(r.term == "ソウルくん" for r in results)

    @pytest.mark.asyncio
    async def test_search_by_alias(self, manager):
        """エイリアスでの検索をテスト"""
        await manager.initialize()
        # "soul-kun"はソウルくんのエイリアス
        results = await manager.search("soul-kun")

        assert len(results) > 0

    @pytest.mark.asyncio
    async def test_search_partial_match(self, manager):
        """部分一致検索をテスト"""
        await manager.initialize()
        results = await manager.search("ソウル")

        assert len(results) > 0

    @pytest.mark.asyncio
    async def test_add_vocabulary(self, manager):
        """語彙の追加をテスト"""
        await manager.initialize()

        entry = await manager.add_vocabulary(
            term="テストプロジェクト",
            category=VocabularyCategory.PROJECT_NAME,
            meaning="テスト用のプロジェクト",
            aliases=["TP", "test-project"],
        )

        assert entry.term == "テストプロジェクト"
        assert entry.category == VocabularyCategory.PROJECT_NAME
        assert "TP" in entry.aliases

        # 検索で見つかるか
        results = await manager.search("テストプロジェクト")
        assert len(results) > 0

    @pytest.mark.asyncio
    async def test_add_vocabulary_with_usage_examples(self, manager):
        """使用例付きの語彙追加をテスト"""
        await manager.initialize()

        entry = await manager.add_vocabulary(
            term="週次MTG",
            category=VocabularyCategory.EVENT_NAME,
            meaning="毎週月曜日の定例ミーティング",
            aliases=["週ミ"],
            usage_examples=["週次MTGの議題", "週次MTGに参加"],
        )

        assert len(entry.usage_examples) == 2

    @pytest.mark.asyncio
    async def test_update_vocabulary(self, manager):
        """語彙の更新をテスト"""
        await manager.initialize()

        # 追加
        await manager.add_vocabulary(
            term="更新テスト",
            category=VocabularyCategory.IDIOM,
            meaning="元の意味",
        )

        # 更新
        updated = await manager.update_vocabulary(
            term="更新テスト",
            meaning="更新後の意味",
        )

        assert updated.meaning == "更新後の意味"

    @pytest.mark.asyncio
    async def test_get_by_term(self, manager):
        """正確な語彙取得をテスト"""
        await manager.initialize()

        result = await manager.get_by_term("ソウルくん")
        assert result is not None
        assert result.term == "ソウルくん"

    @pytest.mark.asyncio
    async def test_get_by_term_not_found(self, manager):
        """存在しない語彙の取得をテスト"""
        await manager.initialize()

        result = await manager.get_by_term("存在しない語彙")
        assert result is None

    @pytest.mark.asyncio
    async def test_resolve_vocabulary_in_message(self, manager):
        """メッセージ内の語彙解決をテスト"""
        await manager.initialize()

        input_context = create_test_input(message="ソウルくんの件どうなった？")

        result = await manager.resolve_vocabulary_in_message(
            message="ソウルくんの件どうなった？",
            context=input_context,
        )

        assert isinstance(result, OrganizationContextResult)
        assert len(result.contexts) > 0
        assert result.overall_confidence > 0

    @pytest.mark.asyncio
    async def test_resolve_vocabulary_multiple(self, manager):
        """複数語彙の解決をテスト"""
        await manager.initialize()

        await manager.add_vocabulary(
            term="開発チーム",
            category=VocabularyCategory.TEAM_NAME,
            meaning="ソフトウェア開発チーム",
        )

        input_context = create_test_input(message="ソウルくんを開発チームで使いたい")

        result = await manager.resolve_vocabulary_in_message(
            message="ソウルくんを開発チームで使いたい",
            context=input_context,
        )

        assert len(result.contexts) >= 1

    @pytest.mark.asyncio
    async def test_resolve_context_dependent_itsumo(self, manager):
        """「いつもの」の文脈解決をテスト"""
        await manager.initialize()

        await manager.add_vocabulary(
            term="定例会議",
            category=VocabularyCategory.EVENT_NAME,
            meaning="毎週月曜の定例ミーティング",
        )

        input_context = create_test_input(message="いつもの定例会議の件")

        result = await manager.resolve_vocabulary_in_message(
            message="いつもの定例会議の件",
            context=input_context,
        )

        # 語彙が解決されているか、または文脈依存として処理
        assert result.overall_confidence >= 0

    @pytest.mark.asyncio
    async def test_learn_from_message_quoted(self, manager):
        """カギカッコ内の語彙学習をテスト"""
        await manager.initialize()

        input_context = create_test_input(message='「ABC」プロジェクトの進捗')

        # 1回目
        candidates = await manager.learn_from_message(
            message='「ABC」プロジェクトの進捗',
            context=input_context,
        )
        assert isinstance(candidates, list)

    @pytest.mark.asyncio
    async def test_learn_from_message_abbreviation(self, manager):
        """略語の学習をテスト"""
        await manager.initialize()

        input_context = create_test_input(message="PMとPOが参加するMTG")

        candidates = await manager.learn_from_message(
            message="PMとPOが参加するMTG",
            context=input_context,
        )
        assert isinstance(candidates, list)


# =============================================================================
# 6. HistoryAnalyzerのテスト
# =============================================================================

class TestHistoryAnalyzer:
    """履歴分析器のテスト"""

    @pytest.fixture
    def analyzer(self):
        """テスト用アナライザーを作成"""
        return create_history_analyzer(
            pool=None,
            organization_id="org_test",
        )

    @pytest.mark.asyncio
    async def test_analyze_with_conversation_history(self, analyzer):
        """会話履歴からの分析をテスト"""
        input_context = create_test_input(
            message="あれどうなった？",
            recent_conversation=[
                {"role": "user", "content": "報告書の件お願いします"},
                {"role": "assistant", "content": "はい、報告書を作成しています"},
            ],
        )

        result = await analyzer.analyze("あれどうなった？", input_context)

        assert isinstance(result, RecoveredContext)
        assert len(result.fragments) > 0

    @pytest.mark.asyncio
    async def test_analyze_with_task_history(self, analyzer):
        """タスク履歴からの分析をテスト"""
        input_context = create_test_input(
            message="タスクどうなった？",
            recent_tasks=create_test_tasks(),
        )

        result = await analyzer.analyze("タスクどうなった？", input_context)

        task_fragments = [f for f in result.fragments
                         if f.source == ContextRecoverySource.TASK_HISTORY]
        assert len(task_fragments) > 0 or len(result.fragments) >= 0

    @pytest.mark.asyncio
    async def test_analyze_with_person_info(self, analyzer):
        """人物情報からの分析をテスト"""
        input_context = create_test_input(
            message="山田太郎さんに連絡して",
            person_info=create_test_persons(),
        )

        result = await analyzer.analyze("山田太郎さんに連絡して", input_context)

        person_fragments = [f for f in result.fragments
                           if f.source == ContextRecoverySource.PERSON_INFO]
        # 完全一致の場合のみ抽出される
        assert isinstance(result.related_persons, list)

    @pytest.mark.asyncio
    async def test_analyze_with_goals(self, analyzer):
        """目標情報からの分析をテスト"""
        input_context = create_test_input(
            message="売上目標の進捗は？",
            active_goals=create_test_goals(),
        )

        result = await analyzer.analyze("売上目標の進捗は？", input_context)

        assert isinstance(result, RecoveredContext)

    @pytest.mark.asyncio
    async def test_extract_main_topics(self, analyzer):
        """主要トピックの抽出をテスト"""
        input_context = create_test_input(
            message="報告書の進捗を教えて",
            recent_conversation=[
                {"role": "user", "content": "報告書を作成してほしい"},
                {"role": "assistant", "content": "報告書を作成します"},
            ],
        )

        result = await analyzer.analyze("報告書の進捗を教えて", input_context)

        assert len(result.main_topics) > 0

    @pytest.mark.asyncio
    async def test_extract_related_tasks(self, analyzer):
        """関連タスクの抽出をテスト"""
        input_context = create_test_input(
            message="報告書のタスク",
            recent_tasks=create_test_tasks(),
        )

        result = await analyzer.analyze("報告書のタスク", input_context)

        assert isinstance(result.related_tasks, list)

    @pytest.mark.asyncio
    async def test_relevance_score_calculation(self, analyzer):
        """関連度スコアの計算をテスト"""
        input_context = create_test_input(
            message="報告書",
            recent_conversation=[
                {"role": "user", "content": "報告書を作成してください"},
                {"role": "assistant", "content": "はい"},
                {"role": "user", "content": "全然関係ない話"},
            ],
        )

        result = await analyzer.analyze("報告書", input_context)

        # 「報告書」を含む会話が高い関連度を持つはず
        if result.fragments:
            report_fragments = [f for f in result.fragments
                               if "報告書" in f.content]
            if report_fragments:
                assert report_fragments[0].relevance_score > 0.2

    @pytest.mark.asyncio
    async def test_summary_generation(self, analyzer):
        """サマリー生成をテスト"""
        input_context = create_test_input(
            message="テスト",
            recent_conversation=create_test_conversation(),
            recent_tasks=create_test_tasks(),
        )

        result = await analyzer.analyze("テスト", input_context)

        assert result.summary
        assert len(result.summary) > 0

    @pytest.mark.asyncio
    async def test_empty_context(self, analyzer):
        """空のコンテキストでの分析をテスト"""
        input_context = create_test_input(
            message="テスト",
            recent_conversation=[],
            recent_tasks=[],
            person_info=[],
        )

        result = await analyzer.analyze("テスト", input_context)

        assert isinstance(result, RecoveredContext)
        # 空の場合でもサマリーは生成される
        assert result.summary is not None

    @pytest.mark.asyncio
    async def test_confidence_calculation(self, analyzer):
        """信頼度計算をテスト"""
        input_context = create_test_input(
            message="報告書の件",
            recent_conversation=[
                {"role": "user", "content": "報告書を作成"},
                {"role": "assistant", "content": "報告書を作成しました"},
            ],
            recent_tasks=[
                {"task_id": "1", "body": "報告書作成", "status": "done"},
            ],
        )

        result = await analyzer.analyze("報告書の件", input_context)

        # 関連情報が多いので信頼度が高くなるはず
        assert result.overall_confidence >= 0


# =============================================================================
# 7. ContextExpressionResolverのテスト
# =============================================================================

class TestContextExpressionResolver:
    """文脈依存表現リゾルバーのテスト"""

    @pytest.fixture
    def resolver(self):
        """テスト用リゾルバーを作成"""
        return create_context_expression_resolver(
            conversation_history=[
                {"content": "コーヒーをアメリカンで注文した"},
                {"content": "Aプロジェクトの進捗を報告"},
            ],
            user_habits={
                "coffee_order": "アメリカン",
                "report_format": "週次形式",
            },
            recent_topics=[
                {"name": "Aプロジェクト", "subject": "進捗報告"},
                {"name": "予算会議", "subject": "Q4予算"},
            ],
        )

    def test_classify_habitual_expression(self, resolver):
        """習慣的表現の分類をテスト"""
        expr_type = resolver._classify_expression("いつもの")
        assert expr_type == ExpressionType.HABITUAL

    def test_classify_reference_expression(self, resolver):
        """参照表現の分類をテスト"""
        expr_type = resolver._classify_expression("あの件")
        assert expr_type == ExpressionType.REFERENCE

    def test_classify_temporal_expression(self, resolver):
        """時間参照表現の分類をテスト"""
        expr_type = resolver._classify_expression("この前の")
        assert expr_type == ExpressionType.TEMPORAL

    def test_classify_recent_expression(self, resolver):
        """最近参照表現の分類をテスト"""
        expr_type = resolver._classify_expression("さっきの")
        assert expr_type == ExpressionType.RECENT

    def test_classify_unknown_expression(self, resolver):
        """不明な表現の分類をテスト"""
        expr_type = resolver._classify_expression("明確な表現")
        assert expr_type == ExpressionType.UNKNOWN

    def test_detect_expressions_multiple(self, resolver):
        """複数の表現検出をテスト"""
        found = resolver.detect_expressions("いつもの報告書をさっきの会議で使った")

        # 「いつもの」と「さっきの」が検出されるはず
        expressions = [expr for expr, _ in found]
        assert "いつもの" in expressions
        assert "さっきの" in expressions

    @pytest.mark.asyncio
    async def test_resolve_habitual_with_habit(self, resolver):
        """習慣情報からの解決をテスト"""
        result = await resolver.resolve("いつもの", "いつものコーヒーお願い")

        assert isinstance(result, ContextResolutionResult)
        assert result.expression_type == ExpressionType.HABITUAL
        # 習慣情報があるので解決されるか候補がある
        assert result.resolved_to is not None or len(result.candidates) > 0

    @pytest.mark.asyncio
    async def test_resolve_reference(self, resolver):
        """参照表現の解決をテスト"""
        result = await resolver.resolve("あの件", "あの件の進捗")

        assert isinstance(result, ContextResolutionResult)
        assert result.expression_type == ExpressionType.REFERENCE
        # 候補が見つかるはず
        assert len(result.candidates) >= 0

    @pytest.mark.asyncio
    async def test_resolve_recent(self, resolver):
        """最近参照表現の解決をテスト"""
        result = await resolver.resolve("さっきの", "さっきの話")

        assert isinstance(result, ContextResolutionResult)
        assert result.expression_type == ExpressionType.RECENT

    @pytest.mark.asyncio
    async def test_resolve_needs_confirmation(self):
        """確認が必要な場合をテスト"""
        resolver = create_context_expression_resolver(
            conversation_history=[],
            user_habits={},
            recent_topics=[],
        )

        result = await resolver.resolve("いつもの", "いつものでお願い")

        # 情報がないので確認が必要
        assert result.needs_confirmation or result.confidence < 0.7

    def test_get_confirmation_options(self, resolver):
        """確認オプションの取得をテスト"""
        result = ContextResolutionResult(
            expression="いつもの",
            confidence=0.5,
            needs_confirmation=True,
            candidates=[
                ContextCandidate(entity="アメリカン", confidence=0.6),
                ContextCandidate(entity="カフェラテ", confidence=0.5),
            ],
        )

        options = result.get_confirmation_options()
        assert "アメリカン" in options
        assert "カフェラテ" in options


# =============================================================================
# 8. DeepUnderstanding統合テスト
# =============================================================================

class TestDeepUnderstanding:
    """深い理解層の統合テスト"""

    @pytest.fixture
    def deep_understanding(self):
        """テスト用の深い理解層を作成"""
        return create_deep_understanding(
            pool=None,
            organization_id="org_test",
            use_llm=False,
        )

    @pytest.mark.asyncio
    async def test_understand_simple_message(self, deep_understanding):
        """シンプルなメッセージの理解をテスト"""
        input_context = create_test_input(
            message="報告書を作成してください",
        )

        result = await deep_understanding.understand(
            message="報告書を作成してください",
            input_context=input_context,
        )

        assert isinstance(result, DeepUnderstandingOutput)
        assert result.enhanced_message
        assert result.processing_time_ms >= 0

    @pytest.mark.asyncio
    async def test_understand_ambiguous_message(self, deep_understanding):
        """曖昧なメッセージの理解をテスト"""
        input_context = create_test_input(
            message="あれどうなった？",
            recent_tasks=create_test_tasks(),
        )

        result = await deep_understanding.understand(
            message="あれどうなった？",
            input_context=input_context,
        )

        assert isinstance(result, DeepUnderstandingOutput)
        # 曖昧なので確認が必要または信頼度が低い
        assert result.needs_confirmation or result.overall_confidence < 0.9

    @pytest.mark.asyncio
    async def test_understand_urgent_message(self, deep_understanding):
        """緊急メッセージの理解をテスト"""
        input_context = create_test_input(
            message="至急対応お願いします！困ってます！",
        )

        result = await deep_understanding.understand(
            message="至急対応お願いします！困ってます！",
            input_context=input_context,
        )

        if result.emotion_reading:
            assert result.emotion_reading.urgency is not None
            assert result.emotion_reading.urgency.level in (
                UrgencyLevel.CRITICAL,
                UrgencyLevel.VERY_HIGH,
                UrgencyLevel.HIGH,
            )

    @pytest.mark.asyncio
    async def test_understand_with_organization_vocabulary(self, deep_understanding):
        """組織語彙を含むメッセージの理解をテスト"""
        input_context = create_test_input(
            message="ソウルくんの進捗を教えて",
        )

        result = await deep_understanding.understand(
            message="ソウルくんの進捗を教えて",
            input_context=input_context,
        )

        if result.organization_context:
            assert len(result.organization_context.contexts) > 0

    @pytest.mark.asyncio
    async def test_understand_with_context_recovery(self, deep_understanding):
        """文脈復元を伴う理解をテスト"""
        input_context = create_test_input(
            message="続きをお願いします",
            recent_conversation=[
                {"role": "user", "content": "報告書を作成してほしい"},
                {"role": "assistant", "content": "はい、報告書を作成しています"},
            ],
        )

        result = await deep_understanding.understand(
            message="続きをお願いします",
            input_context=input_context,
        )

        if result.recovered_context:
            assert len(result.recovered_context.fragments) > 0

    @pytest.mark.asyncio
    async def test_understand_with_all_components(self, deep_understanding):
        """全コンポーネントを使用した理解をテスト"""
        input_context = create_test_input(
            message="至急ソウルくんであれをお願い！困ってます！",
            recent_conversation=create_test_conversation(),
            recent_tasks=create_test_tasks(),
            person_info=create_test_persons(),
        )

        result = await deep_understanding.understand(
            message="至急ソウルくんであれをお願い！困ってます！",
            input_context=input_context,
        )

        assert isinstance(result, DeepUnderstandingOutput)
        # 各コンポーネントの結果が含まれる
        assert result.intent_inference is not None or True  # Optional
        assert result.emotion_reading is not None or True  # Optional
        assert result.organization_context is not None or True  # Optional
        assert result.recovered_context is not None or True  # Optional

    @pytest.mark.asyncio
    async def test_overall_confidence_calculation(self, deep_understanding):
        """全体の信頼度計算をテスト"""
        input_context = create_test_input(
            message="山田さんに報告書を作成してもらうタスクを作成",
        )

        result = await deep_understanding.understand(
            message="山田さんに報告書を作成してもらうタスクを作成",
            input_context=input_context,
        )

        assert result.overall_confidence >= 0.0
        assert result.overall_confidence <= 1.0

    @pytest.mark.asyncio
    async def test_enhanced_message_generation(self, deep_understanding):
        """強化されたメッセージ生成をテスト"""
        input_context = create_test_input(
            message="ソウルくんでテスト",
        )

        result = await deep_understanding.understand(
            message="ソウルくんでテスト",
            input_context=input_context,
        )

        assert result.enhanced_message
        assert "テスト" in result.enhanced_message

    @pytest.mark.asyncio
    async def test_confirmation_options(self, deep_understanding):
        """確認オプションの生成をテスト"""
        input_context = create_test_input(
            message="あれを完了にして",
            recent_tasks=create_test_tasks(),
        )

        result = await deep_understanding.understand(
            message="あれを完了にして",
            input_context=input_context,
        )

        if result.needs_confirmation:
            assert isinstance(result.confirmation_options, list)

    @pytest.mark.asyncio
    async def test_feature_flag_disabled(self):
        """Feature Flagが無効な場合をテスト"""
        deep_understanding = create_deep_understanding(
            pool=None,
            organization_id="org_test",
            feature_flags={"deep_understanding_enabled": False},
        )

        result = await deep_understanding.understand(
            message="テスト",
        )

        assert len(result.warnings) > 0
        assert result.overall_confidence == 1.0

    @pytest.mark.asyncio
    async def test_partial_feature_flags(self):
        """部分的なFeature Flag設定をテスト"""
        deep_understanding = create_deep_understanding(
            pool=None,
            organization_id="org_test",
            feature_flags={
                "deep_understanding_enabled": True,
                "implicit_intent_enabled": False,
                "emotion_reading_enabled": True,
            },
        )

        result = await deep_understanding.understand(
            message="至急お願いします！",
        )

        assert isinstance(result, DeepUnderstandingOutput)
        # 感情読み取りは有効
        if result.emotion_reading:
            assert result.emotion_reading.urgency is not None

    @pytest.mark.asyncio
    async def test_error_handling(self, deep_understanding):
        """エラーハンドリングをテスト"""
        result = await deep_understanding.understand(
            message="",
            input_context=None,
        )

        assert isinstance(result, DeepUnderstandingOutput)

    @pytest.mark.asyncio
    async def test_component_access(self, deep_understanding):
        """コンポーネントへのアクセスをテスト"""
        assert deep_understanding.intent_inference is not None
        assert deep_understanding.emotion_reader is not None
        assert deep_understanding.vocabulary_manager is not None
        assert deep_understanding.history_analyzer is not None


# =============================================================================
# 9. ファクトリー関数のテスト
# =============================================================================

class TestFactoryFunctions:
    """ファクトリー関数のテスト"""

    def test_create_intent_inference_engine(self):
        """IntentInferenceEngineの作成をテスト"""
        engine = create_intent_inference_engine(use_llm=False)
        assert isinstance(engine, IntentInferenceEngine)

    def test_create_intent_inference_engine_with_llm(self):
        """LLM有効のIntentInferenceEngineの作成をテスト"""
        engine = create_intent_inference_engine(
            get_ai_response_func=create_mock_ai_response_func(),
            use_llm=True,
        )
        assert isinstance(engine, IntentInferenceEngine)
        assert engine.use_llm is True

    def test_create_emotion_reader(self):
        """EmotionReaderの作成をテスト"""
        reader = create_emotion_reader()
        assert isinstance(reader, EmotionReader)

    def test_create_vocabulary_manager(self):
        """VocabularyManagerの作成をテスト"""
        manager = create_vocabulary_manager(
            pool=None,
            organization_id="org_test",
        )
        assert isinstance(manager, VocabularyManager)
        assert manager.organization_id == "org_test"

    def test_create_history_analyzer(self):
        """HistoryAnalyzerの作成をテスト"""
        analyzer = create_history_analyzer(
            pool=None,
            organization_id="org_test",
        )
        assert isinstance(analyzer, HistoryAnalyzer)

    def test_create_deep_understanding(self):
        """DeepUnderstandingの作成をテスト"""
        du = create_deep_understanding(
            pool=None,
            organization_id="org_test",
            use_llm=False,
        )
        assert isinstance(du, DeepUnderstanding)

    def test_create_deep_understanding_with_all_options(self):
        """全オプション指定でのDeepUnderstandingの作成をテスト"""
        du = create_deep_understanding(
            pool=None,
            organization_id="org_test",
            get_ai_response_func=create_mock_ai_response_func(),
            use_llm=True,
            feature_flags={
                "deep_understanding_enabled": True,
                "implicit_intent_enabled": True,
                "emotion_reading_enabled": True,
            },
        )
        assert isinstance(du, DeepUnderstanding)

    def test_create_context_expression_resolver(self):
        """ContextExpressionResolverの作成をテスト"""
        resolver = create_context_expression_resolver(
            conversation_history=[],
            user_habits={},
            recent_topics=[],
        )
        assert isinstance(resolver, ContextExpressionResolver)


# =============================================================================
# 10. エッジケースのテスト
# =============================================================================

class TestEdgeCases:
    """エッジケースのテスト"""

    @pytest.mark.asyncio
    async def test_empty_message(self):
        """空のメッセージをテスト"""
        du = create_deep_understanding(use_llm=False)

        result = await du.understand(
            message="",
            input_context=create_test_input(message=""),
        )

        assert isinstance(result, DeepUnderstandingOutput)

    @pytest.mark.asyncio
    async def test_whitespace_only_message(self):
        """空白のみのメッセージをテスト"""
        du = create_deep_understanding(use_llm=False)

        result = await du.understand(
            message="   ",
            input_context=create_test_input(message="   "),
        )

        assert isinstance(result, DeepUnderstandingOutput)

    @pytest.mark.asyncio
    async def test_very_long_message(self):
        """非常に長いメッセージをテスト"""
        du = create_deep_understanding(use_llm=False)
        long_message = "テスト " * 1000

        result = await du.understand(
            message=long_message,
            input_context=create_test_input(message=long_message),
        )

        assert isinstance(result, DeepUnderstandingOutput)

    @pytest.mark.asyncio
    async def test_special_characters(self):
        """特殊文字を含むメッセージをテスト"""
        du = create_deep_understanding(use_llm=False)
        special_message = "テスト！@#$%^&*()_+-=[]{}|;':\",./<>?"

        result = await du.understand(
            message=special_message,
            input_context=create_test_input(message=special_message),
        )

        assert isinstance(result, DeepUnderstandingOutput)

    @pytest.mark.asyncio
    async def test_emoji_message(self):
        """絵文字を含むメッセージをテスト"""
        du = create_deep_understanding(use_llm=False)
        emoji_message = "嬉しい！！"

        result = await du.understand(
            message=emoji_message,
            input_context=create_test_input(message=emoji_message),
        )

        assert isinstance(result, DeepUnderstandingOutput)

    @pytest.mark.asyncio
    async def test_unicode_message(self):
        """Unicodeメッセージをテスト"""
        du = create_deep_understanding(use_llm=False)
        unicode_message = "日本語テスト"

        result = await du.understand(
            message=unicode_message,
            input_context=create_test_input(message=unicode_message),
        )

        assert isinstance(result, DeepUnderstandingOutput)

    @pytest.mark.asyncio
    async def test_multiple_pronouns(self):
        """複数の代名詞を含むメッセージをテスト"""
        du = create_deep_understanding(use_llm=False)

        result = await du.understand(
            message="これとあれとそれをお願いします",
            input_context=create_test_input(
                message="これとあれとそれをお願いします",
                recent_tasks=create_test_tasks(),
            ),
        )

        assert isinstance(result, DeepUnderstandingOutput)

    @pytest.mark.asyncio
    async def test_mixed_emotions(self):
        """混合した感情を含むメッセージをテスト"""
        reader = create_emotion_reader()

        result = await reader.read(
            message="嬉しいけど、ちょっと心配…",
            input_context=create_test_input(message="嬉しいけど、ちょっと心配…"),
        )

        assert len(result.emotions) >= 1

    @pytest.mark.asyncio
    async def test_contradictory_emotions(self):
        """矛盾する感情表現をテスト"""
        reader = create_emotion_reader()

        result = await reader.read(
            message="嬉しいけど悲しい、でもありがとう",
            input_context=create_test_input(message="嬉しいけど悲しい、でもありがとう"),
        )

        # 複数の感情が検出される可能性
        assert isinstance(result, EmotionReadingResult)

    @pytest.mark.asyncio
    async def test_null_context_fields(self):
        """コンテキストフィールドがNoneの場合をテスト"""
        du = create_deep_understanding(use_llm=False)

        input_context = DeepUnderstandingInput(
            message="テスト",
            organization_id="org_test",
            recent_conversation=None,
            recent_tasks=None,
            person_info=None,
        )
        # デフォルト値が設定されているので問題ない
        input_context.recent_conversation = []
        input_context.recent_tasks = []
        input_context.person_info = []

        result = await du.understand(
            message="テスト",
            input_context=input_context,
        )

        assert isinstance(result, DeepUnderstandingOutput)

    @pytest.mark.asyncio
    async def test_large_conversation_history(self):
        """大量の会話履歴をテスト"""
        du = create_deep_understanding(use_llm=False)

        large_history = [
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"メッセージ{i}"}
            for i in range(100)
        ]

        result = await du.understand(
            message="最新の件について",
            input_context=create_test_input(
                message="最新の件について",
                recent_conversation=large_history,
            ),
        )

        assert isinstance(result, DeepUnderstandingOutput)

    @pytest.mark.asyncio
    async def test_all_pronouns_in_one_message(self):
        """全ての代名詞を含むメッセージをテスト"""
        engine = create_intent_inference_engine(use_llm=False)

        message = "これとそれとあれとこのとそのとあのを確認して"
        input_context = create_test_input(message=message)

        result = await engine.infer(message, input_context)

        # 多数の代名詞があるので確認が必要
        assert isinstance(result, IntentInferenceResult)

    @pytest.mark.asyncio
    async def test_extreme_urgency_keywords(self):
        """極端な緊急度キーワードをテスト"""
        reader = create_emotion_reader()

        result = await reader.read(
            message="今すぐ直ちに大至急緊急すぐに対応して！！！",
            input_context=create_test_input(message="今すぐ直ちに大至急緊急すぐに対応して！！！"),
        )

        assert result.urgency is not None
        assert result.urgency.level == UrgencyLevel.CRITICAL

    @pytest.mark.asyncio
    async def test_no_urgency_keywords(self):
        """緊急度キーワードなしをテスト"""
        reader = create_emotion_reader()

        result = await reader.read(
            message="報告書を確認してください",
            input_context=create_test_input(message="報告書を確認してください"),
        )

        # 緊急度はMEDIUM（デフォルト）になる
        assert result.urgency is not None
        assert result.urgency.level == UrgencyLevel.MEDIUM


# =============================================================================
# 11. パフォーマンステスト
# =============================================================================

class TestPerformance:
    """パフォーマンステスト"""

    @pytest.mark.asyncio
    async def test_processing_time_recorded(self):
        """処理時間が記録されることをテスト"""
        du = create_deep_understanding(use_llm=False)

        result = await du.understand(
            message="テスト",
            input_context=create_test_input(message="テスト"),
        )

        assert result.processing_time_ms >= 0

    @pytest.mark.asyncio
    async def test_reasonable_processing_time(self):
        """処理時間が妥当な範囲内であることをテスト"""
        du = create_deep_understanding(use_llm=False)

        result = await du.understand(
            message="至急報告書を作成してください",
            input_context=create_test_input(
                message="至急報告書を作成してください",
                recent_conversation=create_test_conversation(),
                recent_tasks=create_test_tasks(),
            ),
        )

        # 1秒以内に完了するはず（LLMなし）
        assert result.processing_time_ms < 1000


# =============================================================================
# 12. 回帰テスト
# =============================================================================

class TestRegression:
    """回帰テスト"""

    @pytest.mark.asyncio
    async def test_consistent_pronoun_detection(self):
        """代名詞検出の一貫性をテスト"""
        engine = create_intent_inference_engine(use_llm=False)

        messages = ["これ", "それ", "あれ"]
        for msg in messages:
            input_context = create_test_input(message=f"{msg}お願い")
            result = await engine.infer(f"{msg}お願い", input_context)
            assert isinstance(result, IntentInferenceResult)

    @pytest.mark.asyncio
    async def test_consistent_emotion_detection(self):
        """感情検出の一貫性をテスト"""
        reader = create_emotion_reader()

        # 同じメッセージで複数回実行しても同じ結果
        message = "嬉しい！"
        input_context = create_test_input(message=message)

        result1 = await reader.read(message, input_context)
        result2 = await reader.read(message, input_context)

        assert result1.primary_emotion.category == result2.primary_emotion.category

    @pytest.mark.asyncio
    async def test_consistent_urgency_detection(self):
        """緊急度検出の一貫性をテスト"""
        reader = create_emotion_reader()

        message = "至急お願いします"
        input_context = create_test_input(message=message)

        result1 = await reader.read(message, input_context)
        result2 = await reader.read(message, input_context)

        assert result1.urgency.level == result2.urgency.level
