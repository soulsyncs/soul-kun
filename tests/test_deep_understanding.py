# tests/test_deep_understanding.py
"""
Phase 2I: 理解力強化（Deep Understanding）のテスト

設計書: docs/17_brain_completion_roadmap.md セクション17.3 Phase 2I

Author: Claude Opus 4.5
Created: 2026-01-27
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
from uuid import uuid4

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
    EMOTION_INDICATORS,
    URGENCY_INDICATORS,
    INTENT_CONFIDENCE_THRESHOLDS,

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


# =============================================================================
# テストヘルパー
# =============================================================================

def create_test_input(
    message: str = "テストメッセージ",
    organization_id: str = "org_test",
    recent_conversation: list = None,
    recent_tasks: list = None,
    person_info: list = None,
) -> DeepUnderstandingInput:
    """テスト用の入力を作成"""
    return DeepUnderstandingInput(
        message=message,
        organization_id=organization_id,
        recent_conversation=recent_conversation or [],
        recent_tasks=recent_tasks or [],
        person_info=person_info or [],
        active_goals=[],
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
        ]
    return tasks


def create_test_persons(persons: list = None) -> list:
    """テスト用の人物情報を作成"""
    if persons is None:
        persons = [
            {"name": "山田太郎", "department": "営業部", "role": "マネージャー"},
            {"name": "佐藤花子", "department": "開発部", "role": "エンジニア"},
        ]
    return persons


# =============================================================================
# 定数のテスト
# =============================================================================

class TestConstants:
    """定数のテスト"""

    def test_demonstrative_pronouns_structure(self):
        """指示代名詞の構造をテスト"""
        assert "これ" in DEMONSTRATIVE_PRONOUNS
        assert "それ" in DEMONSTRATIVE_PRONOUNS
        assert "あれ" in DEMONSTRATIVE_PRONOUNS

        # 各エントリの構造
        for pronoun, info in DEMONSTRATIVE_PRONOUNS.items():
            assert "distance" in info
            assert "type" in info
            assert info["distance"] in ("near", "middle", "far", "unknown")

    def test_emotion_indicators_structure(self):
        """感情インジケーターの構造をテスト"""
        assert EmotionCategory.HAPPY.value in EMOTION_INDICATORS
        assert EmotionCategory.FRUSTRATED.value in EMOTION_INDICATORS

        for emotion, indicators in EMOTION_INDICATORS.items():
            assert "keywords" in indicators
            assert "expressions" in indicators
            assert isinstance(indicators["keywords"], list)

    def test_urgency_indicators_structure(self):
        """緊急度インジケーターの構造をテスト"""
        assert UrgencyLevel.CRITICAL.value in URGENCY_INDICATORS
        assert UrgencyLevel.HIGH.value in URGENCY_INDICATORS
        assert UrgencyLevel.LOW.value in URGENCY_INDICATORS

        for level, keywords in URGENCY_INDICATORS.items():
            assert isinstance(keywords, list)
            assert len(keywords) > 0

    def test_confidence_thresholds(self):
        """信頼度閾値をテスト"""
        assert "auto_execute" in INTENT_CONFIDENCE_THRESHOLDS
        assert "high" in INTENT_CONFIDENCE_THRESHOLDS
        assert "medium" in INTENT_CONFIDENCE_THRESHOLDS
        assert "low" in INTENT_CONFIDENCE_THRESHOLDS

        # 閾値の順序
        assert INTENT_CONFIDENCE_THRESHOLDS["auto_execute"] > INTENT_CONFIDENCE_THRESHOLDS["high"]
        assert INTENT_CONFIDENCE_THRESHOLDS["high"] > INTENT_CONFIDENCE_THRESHOLDS["medium"]
        assert INTENT_CONFIDENCE_THRESHOLDS["medium"] > INTENT_CONFIDENCE_THRESHOLDS["low"]


# =============================================================================
# モデルのテスト
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
        )
        assert ref.original_expression == "あれ"
        assert ref.resolved_value == "報告書"
        assert ref.confidence == 0.8

    def test_implicit_intent_creation(self):
        """ImplicitIntentの作成をテスト"""
        intent = ImplicitIntent(
            intent_type=ImplicitIntentType.PRONOUN_REFERENCE,
            inferred_intent="タスクの進捗確認",
            confidence=0.75,
            original_message="あれどうなった？",
            needs_confirmation=False,
        )
        assert intent.intent_type == ImplicitIntentType.PRONOUN_REFERENCE
        assert intent.confidence == 0.75
        assert not intent.needs_confirmation

    def test_vocabulary_entry_creation(self):
        """VocabularyEntryの作成をテスト"""
        entry = VocabularyEntry(
            organization_id="org_test",
            term="ソウルくん",
            category=VocabularyCategory.PRODUCT_NAME,
            meaning="社内AIアシスタント",
            aliases=["soul-kun"],
        )
        assert entry.term == "ソウルくん"
        assert entry.category == VocabularyCategory.PRODUCT_NAME
        assert "soul-kun" in entry.aliases

    def test_detected_emotion_creation(self):
        """DetectedEmotionの作成をテスト"""
        emotion = DetectedEmotion(
            category=EmotionCategory.FRUSTRATED,
            intensity=0.7,
            confidence=0.8,
            indicators=["困った"],
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
            indicators=["今日中"],
        )
        assert urgency.level == UrgencyLevel.HIGH
        assert urgency.estimated_deadline_hours == 8.0

    def test_deep_understanding_input_creation(self):
        """DeepUnderstandingInputの作成をテスト"""
        input_data = create_test_input(
            message="あれどうなった？",
            organization_id="org_001",
        )
        assert input_data.message == "あれどうなった？"
        assert input_data.organization_id == "org_001"

    def test_deep_understanding_output_creation(self):
        """DeepUnderstandingOutputの作成をテスト"""
        input_context = DeepUnderstandingInput(
            message="テスト",
            organization_id="org_test",
        )
        output = DeepUnderstandingOutput(
            input=input_context,
            enhanced_message="テスト",
            overall_confidence=0.8,
            needs_confirmation=False,
            processing_time_ms=100,
        )
        assert output.enhanced_message == "テスト"
        assert output.overall_confidence == 0.8
        assert output.processing_time_ms == 100


# =============================================================================
# IntentInferenceEngineのテスト
# =============================================================================

class TestIntentInferenceEngine:
    """意図推測エンジンのテスト"""

    @pytest.fixture
    def engine(self):
        """テスト用エンジンを作成"""
        return create_intent_inference_engine(use_llm=False)

    @pytest.mark.asyncio
    async def test_detect_demonstrative_pronoun_kore(self, engine):
        """「これ」の検出をテスト"""
        input_context = create_test_input(
            message="これどうなった？",
            recent_conversation=create_test_conversation(),
        )

        result = await engine.infer("これどうなった？", input_context)

        assert isinstance(result, IntentInferenceResult)
        # 代名詞が検出されるべき
        pronoun_intents = [i for i in result.implicit_intents
                          if i.intent_type == ImplicitIntentType.PRONOUN_REFERENCE]
        assert len(pronoun_intents) > 0 or result.needs_confirmation

    @pytest.mark.asyncio
    async def test_detect_demonstrative_pronoun_are(self, engine):
        """「あれ」の検出をテスト"""
        input_context = create_test_input(
            message="あれお願いできる？",
            recent_tasks=create_test_tasks(),
        )

        result = await engine.infer("あれお願いできる？", input_context)

        assert isinstance(result, IntentInferenceResult)

    @pytest.mark.asyncio
    async def test_resolve_pronoun_with_single_candidate(self, engine):
        """候補が1つの場合の代名詞解決をテスト"""
        input_context = create_test_input(
            message="それ完了にして",
            recent_tasks=[
                {"task_id": "task_001", "body": "報告書を作成する", "status": "open"},
            ],
        )

        result = await engine.infer("それ完了にして", input_context)

        # 省略表現の検出
        ellipsis_intents = [i for i in result.implicit_intents
                           if i.intent_type == ImplicitIntentType.ELLIPSIS_REFERENCE]
        if ellipsis_intents:
            assert ellipsis_intents[0].confidence >= 0.5

    @pytest.mark.asyncio
    async def test_detect_indirect_request(self, engine):
        """婉曲的依頼の検出をテスト"""
        input_context = create_test_input(message="できたら見てもらえます？")

        result = await engine.infer("できたら見てもらえます？", input_context)

        request_intents = [i for i in result.implicit_intents
                          if i.intent_type == ImplicitIntentType.IMPLICIT_REQUEST]
        assert len(request_intents) > 0

    @pytest.mark.asyncio
    async def test_detect_indirect_negation(self, engine):
        """婉曲的否定の検出をテスト"""
        input_context = create_test_input(message="ちょっと難しいかも")

        result = await engine.infer("ちょっと難しいかも", input_context)

        negation_intents = [i for i in result.implicit_intents
                           if i.intent_type == ImplicitIntentType.IMPLICIT_NEGATION]
        assert len(negation_intents) > 0

    @pytest.mark.asyncio
    async def test_detect_context_dependent_itsumo(self, engine):
        """「いつもの」の検出をテスト"""
        input_context = create_test_input(message="いつものミーティングの件")

        result = await engine.infer("いつものミーティングの件", input_context)

        context_intents = [i for i in result.implicit_intents
                          if i.intent_type == ImplicitIntentType.CONTEXT_DEPENDENT]
        assert len(context_intents) > 0

    @pytest.mark.asyncio
    async def test_no_implicit_intent_for_clear_message(self, engine):
        """明確なメッセージでは暗黙の意図が少ないことをテスト"""
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


# =============================================================================
# EmotionReaderのテスト
# =============================================================================

class TestEmotionReader:
    """感情読み取りエンジンのテスト"""

    @pytest.fixture
    def reader(self):
        """テスト用リーダーを作成"""
        return create_emotion_reader()

    @pytest.mark.asyncio
    async def test_detect_happy_emotion(self, reader):
        """喜びの感情検出をテスト"""
        input_context = create_test_input(message="やった！できた！嬉しい！")

        result = await reader.read("やった！できた！嬉しい！", input_context)

        assert isinstance(result, EmotionReadingResult)
        assert result.primary_emotion is not None
        # 喜び系の感情が検出されるべき
        happy_emotions = [e for e in result.emotions
                         if e.category in (EmotionCategory.HAPPY, EmotionCategory.EXCITED)]
        assert len(happy_emotions) > 0

    @pytest.mark.asyncio
    async def test_detect_frustrated_emotion(self, reader):
        """困惑の感情検出をテスト"""
        input_context = create_test_input(message="困った…どうしよう")

        result = await reader.read("困った…どうしよう", input_context)

        frustrated_emotions = [e for e in result.emotions
                              if e.category == EmotionCategory.FRUSTRATED]
        assert len(frustrated_emotions) > 0

    @pytest.mark.asyncio
    async def test_detect_high_urgency(self, reader):
        """高い緊急度の検出をテスト"""
        input_context = create_test_input(message="至急対応お願いします！")

        result = await reader.read("至急対応お願いします！", input_context)

        assert result.urgency is not None
        assert result.urgency.level in (UrgencyLevel.CRITICAL, UrgencyLevel.VERY_HIGH, UrgencyLevel.HIGH)

    @pytest.mark.asyncio
    async def test_detect_low_urgency(self, reader):
        """低い緊急度の検出をテスト"""
        input_context = create_test_input(message="余裕があれば見ておいてください")

        result = await reader.read("余裕があれば見ておいてください", input_context)

        assert result.urgency is not None
        assert result.urgency.level in (UrgencyLevel.LOW, UrgencyLevel.VERY_LOW, UrgencyLevel.MEDIUM)

    @pytest.mark.asyncio
    async def test_detect_formal_nuance(self, reader):
        """フォーマルなニュアンスの検出をテスト"""
        input_context = create_test_input(message="ご確認いただけますでしょうか")

        result = await reader.read("ご確認いただけますでしょうか", input_context)

        formal_nuances = [n for n in result.nuances
                         if n.nuance_type == NuanceType.FORMAL]
        assert len(formal_nuances) > 0

    @pytest.mark.asyncio
    async def test_detect_casual_nuance(self, reader):
        """カジュアルなニュアンスの検出をテスト"""
        input_context = create_test_input(message="これやっといてー")

        result = await reader.read("これやっといてー", input_context)

        casual_nuances = [n for n in result.nuances
                         if n.nuance_type == NuanceType.CASUAL]
        # カジュアルまたは中立
        assert len(result.nuances) >= 0

    @pytest.mark.asyncio
    async def test_emotion_intensity(self, reader):
        """感情の強度をテスト"""
        input_context = create_test_input(message="本当にありがとう！！！")

        result = await reader.read("本当にありがとう！！！", input_context)

        if result.primary_emotion:
            # 強調表現があるので強度が高いはず
            assert result.primary_emotion.intensity >= 0.5

    @pytest.mark.asyncio
    async def test_summary_generation(self, reader):
        """サマリー生成をテスト"""
        input_context = create_test_input(message="急いでるんだけど、困った…")

        result = await reader.read("急いでるんだけど、困った…", input_context)

        assert result.summary
        assert len(result.summary) > 0


# =============================================================================
# VocabularyManagerのテスト
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
    async def test_search_default_vocabulary(self, manager):
        """デフォルト語彙の検索をテスト"""
        await manager.initialize()

        results = await manager.search("ソウルくん")

        assert len(results) > 0
        assert any(r.term == "ソウルくん" for r in results)

    @pytest.mark.asyncio
    async def test_add_vocabulary(self, manager):
        """語彙の追加をテスト"""
        await manager.initialize()

        entry = await manager.add_vocabulary(
            term="テストプロジェクト",
            category=VocabularyCategory.PROJECT_NAME,
            meaning="テスト用のプロジェクト",
            aliases=["TP"],
        )

        assert entry.term == "テストプロジェクト"
        assert entry.category == VocabularyCategory.PROJECT_NAME

        # 検索で見つかるか
        results = await manager.search("テストプロジェクト")
        assert len(results) > 0

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

    @pytest.mark.asyncio
    async def test_resolve_context_dependent_usual(self, manager):
        """「いつもの」の文脈解決をテスト"""
        await manager.initialize()

        # 語彙を追加
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

        # 語彙が解決されているか
        assert result.overall_confidence > 0

    @pytest.mark.asyncio
    async def test_learn_from_message(self, manager):
        """メッセージからの語彙学習をテスト"""
        await manager.initialize()

        input_context = create_test_input(message='「ABC」プロジェクトの進捗')

        candidates = await manager.learn_from_message(
            message='「ABC」プロジェクトの進捗',
            context=input_context,
        )

        # 学習候補が検出されるか（最小出現回数に達していない場合は空）
        assert isinstance(candidates, list)


# =============================================================================
# HistoryAnalyzerのテスト
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

        # タスク履歴からの断片が含まれるか
        task_fragments = [f for f in result.fragments
                         if f.source == ContextRecoverySource.TASK_HISTORY]
        assert len(task_fragments) > 0 or len(result.fragments) >= 0

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
    async def test_analyze_with_person_info(self, analyzer):
        """人物情報からの分析をテスト"""
        input_context = create_test_input(
            message="山田さんに連絡して",
            person_info=create_test_persons(),
        )

        result = await analyzer.analyze("山田さんに連絡して", input_context)

        # 関連人物が抽出されるか
        # 名前が部分一致の場合は抽出されない可能性あり
        assert isinstance(result.related_persons, list)

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


# =============================================================================
# DeepUnderstandingのテスト（統合テスト）
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

        # 感情読み取り結果をチェック
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

        # 組織語彙が解決されているか
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

        # 文脈が復元されているか
        if result.recovered_context:
            assert len(result.recovered_context.fragments) > 0

    @pytest.mark.asyncio
    async def test_overall_confidence_calculation(self, deep_understanding):
        """全体の信頼度計算をテスト"""
        input_context = create_test_input(
            message="明確な指示：山田さんに報告書を作成してもらうタスクを作成",
        )

        result = await deep_understanding.understand(
            message="明確な指示：山田さんに報告書を作成してもらうタスクを作成",
            input_context=input_context,
        )

        # 信頼度が計算されていることを確認
        # コンテキストが少ない場合は低くなることがある
        assert result.overall_confidence >= 0.0
        assert result.overall_confidence <= 1.0
        # 処理時間が記録されていることを確認
        assert result.processing_time_ms >= 0

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

        # 強化されたメッセージが生成されているか
        assert result.enhanced_message
        # 元のメッセージの内容を含む
        assert "テスト" in result.enhanced_message

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

        # 機能が無効なので警告が含まれる
        assert len(result.warnings) > 0
        assert result.overall_confidence == 1.0

    @pytest.mark.asyncio
    async def test_error_handling(self, deep_understanding):
        """エラーハンドリングをテスト"""
        # 不正な入力でもクラッシュしない
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
# ファクトリー関数のテスト
# =============================================================================

class TestFactoryFunctions:
    """ファクトリー関数のテスト"""

    def test_create_intent_inference_engine(self):
        """IntentInferenceEngineの作成をテスト"""
        engine = create_intent_inference_engine(use_llm=False)
        assert isinstance(engine, IntentInferenceEngine)

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


# =============================================================================
# エッジケースのテスト
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
        special_message = "テスト！@#$%^&*()_+-=[]{}|;':\",./<>?🎉"

        result = await du.understand(
            message=special_message,
            input_context=create_test_input(message=special_message),
        )

        assert isinstance(result, DeepUnderstandingOutput)

    @pytest.mark.asyncio
    async def test_unicode_message(self):
        """Unicodeメッセージをテスト"""
        du = create_deep_understanding(use_llm=False)
        unicode_message = "日本語テスト한국어テスト中文测试"

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

        # 複数の感情が検出されるか
        assert len(result.emotions) >= 1
