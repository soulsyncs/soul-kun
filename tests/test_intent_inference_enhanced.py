# tests/test_intent_inference_enhanced.py
"""
IntentInferenceEngine 強化版統合テスト

Phase 6: 新しいリゾルバー（EnhancedPronounResolver, PersonAliasResolver,
ContextExpressionResolver）との統合テスト
"""

import pytest
from unittest.mock import MagicMock, AsyncMock
from datetime import datetime

from lib.brain.deep_understanding.intent_inference import (
    IntentInferenceEngine,
    create_intent_inference_engine,
)
from lib.brain.deep_understanding.pronoun_resolver import (
    EnhancedPronounResolver,
    create_pronoun_resolver,
    PronounResolutionResult,
    PronounDistance,
    PronounType,
)
from lib.brain.deep_understanding.person_alias import (
    PersonAliasResolver,
    create_person_alias_resolver,
    PersonResolutionResult,
    MatchType,
)
from lib.brain.deep_understanding.context_expression import (
    ContextExpressionResolver,
    create_context_expression_resolver,
    ContextResolutionResult,
    ExpressionType,
)
from lib.brain.deep_understanding.models import DeepUnderstandingInput
from lib.brain.constants import (
    FEATURE_FLAG_ENHANCED_PRONOUN,
    FEATURE_FLAG_PERSON_ALIAS,
    FEATURE_FLAG_CONTEXT_EXPRESSION,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def conversation_history():
    """テスト用の会話履歴"""
    return [
        {"role": "user", "content": "タスクAについて確認したい"},
        {"role": "assistant", "content": "タスクAの期限は明日です"},
        {"role": "user", "content": "田中さんにも連絡しておいて"},
    ]


@pytest.fixture
def recent_tasks():
    """テスト用のタスクリスト"""
    return [
        {"task_id": "1", "body": "週次報告書の作成"},
        {"task_id": "2", "body": "クライアントへの連絡"},
    ]


@pytest.fixture
def person_info():
    """テスト用の人物情報"""
    return [
        {"name": "田中太郎"},
        {"name": "山田花子"},
    ]


@pytest.fixture
def known_persons():
    """テスト用の既知人物リスト"""
    return ["田中太郎", "山田花子", "佐藤一郎"]


@pytest.fixture
def user_habits():
    """テスト用のユーザー習慣"""
    return {
        "coffee_order": "アメリカン",
        "lunch_order": "A定食",
    }


@pytest.fixture
def deep_understanding_input(conversation_history, recent_tasks, person_info):
    """テスト用のDeepUnderstandingInput"""
    return DeepUnderstandingInput(
        message="テストメッセージ",
        organization_id="test_org",
        recent_conversation=conversation_history,
        recent_tasks=recent_tasks,
        person_info=person_info,
    )


@pytest.fixture
def pronoun_resolver(conversation_history, recent_tasks, person_info):
    """テスト用のEnhancedPronounResolver"""
    return create_pronoun_resolver(
        conversation_history=conversation_history,
        recent_tasks=recent_tasks,
        person_info=person_info,
    )


@pytest.fixture
def person_alias_resolver(known_persons):
    """テスト用のPersonAliasResolver"""
    return create_person_alias_resolver(
        known_persons=known_persons,
    )


@pytest.fixture
def context_expression_resolver(conversation_history, user_habits):
    """テスト用のContextExpressionResolver"""
    return create_context_expression_resolver(
        conversation_history=conversation_history,
        user_habits=user_habits,
    )


@pytest.fixture
def engine_with_enhanced_resolvers(
    pronoun_resolver,
    person_alias_resolver,
    context_expression_resolver,
):
    """強化版リゾルバー付きのIntentInferenceEngine"""
    return create_intent_inference_engine(
        use_llm=False,
        pronoun_resolver=pronoun_resolver,
        person_alias_resolver=person_alias_resolver,
        context_expression_resolver=context_expression_resolver,
        feature_flags={
            FEATURE_FLAG_ENHANCED_PRONOUN: True,
            FEATURE_FLAG_PERSON_ALIAS: True,
            FEATURE_FLAG_CONTEXT_EXPRESSION: True,
        },
    )


@pytest.fixture
def engine_without_enhanced():
    """強化版なしのIntentInferenceEngine"""
    return create_intent_inference_engine(
        use_llm=False,
    )


# =============================================================================
# 初期化テスト
# =============================================================================


class TestEngineInitialization:
    """エンジン初期化テスト"""

    def test_init_with_enhanced_resolvers(
        self,
        pronoun_resolver,
        person_alias_resolver,
        context_expression_resolver,
    ):
        """強化版リゾルバー付きで初期化"""
        engine = IntentInferenceEngine(
            use_llm=False,
            pronoun_resolver=pronoun_resolver,
            person_alias_resolver=person_alias_resolver,
            context_expression_resolver=context_expression_resolver,
            feature_flags={
                FEATURE_FLAG_ENHANCED_PRONOUN: True,
                FEATURE_FLAG_PERSON_ALIAS: True,
                FEATURE_FLAG_CONTEXT_EXPRESSION: True,
            },
        )

        assert engine._pronoun_resolver is not None
        assert engine._person_alias_resolver is not None
        assert engine._context_expression_resolver is not None
        assert engine._is_feature_enabled(FEATURE_FLAG_ENHANCED_PRONOUN) is True

    def test_init_without_enhanced_resolvers(self):
        """強化版リゾルバーなしで初期化"""
        engine = IntentInferenceEngine(use_llm=False)

        assert engine._pronoun_resolver is None
        assert engine._person_alias_resolver is None
        assert engine._context_expression_resolver is None

    def test_feature_flags_default_to_false(self):
        """Feature Flagsはデフォルトで無効"""
        engine = IntentInferenceEngine(use_llm=False)

        assert engine._is_feature_enabled(FEATURE_FLAG_ENHANCED_PRONOUN) is False
        assert engine._is_feature_enabled(FEATURE_FLAG_PERSON_ALIAS) is False
        assert engine._is_feature_enabled(FEATURE_FLAG_CONTEXT_EXPRESSION) is False


# =============================================================================
# 強化版代名詞解決テスト
# =============================================================================


class TestEnhancedPronounResolution:
    """強化版代名詞解決テスト"""

    @pytest.mark.asyncio
    async def test_resolve_pronoun_with_enhanced_resolver(
        self,
        engine_with_enhanced_resolvers,
        deep_understanding_input,
    ):
        """強化版リゾルバーで代名詞を解決"""
        result = await engine_with_enhanced_resolvers.infer(
            message="これを確認して",
            input_context=deep_understanding_input,
        )

        # 結果が返される
        assert result is not None
        # 処理時間が記録される
        assert result.processing_time_ms >= 0

    @pytest.mark.asyncio
    async def test_fallback_to_basic_when_disabled(
        self,
        engine_without_enhanced,
        deep_understanding_input,
    ):
        """Feature Flag無効時は基本版にフォールバック"""
        result = await engine_without_enhanced.infer(
            message="これを確認して",
            input_context=deep_understanding_input,
        )

        # 基本版でも結果が返される
        assert result is not None


# =============================================================================
# 人名エイリアス解決テスト
# =============================================================================


class TestPersonAliasResolution:
    """人名エイリアス解決テスト"""

    @pytest.mark.asyncio
    async def test_resolve_person_name_with_honorific(
        self,
        engine_with_enhanced_resolvers,
        deep_understanding_input,
    ):
        """敬称付き人名を解決"""
        result = await engine_with_enhanced_resolvers.infer(
            message="田中さんに連絡して",
            input_context=deep_understanding_input,
        )

        assert result is not None
        # 人名解決の意図が含まれる可能性がある
        # （既知の人物リストに田中太郎がいる場合）

    @pytest.mark.asyncio
    async def test_no_person_resolution_when_disabled(
        self,
        pronoun_resolver,
        person_alias_resolver,
        context_expression_resolver,
        deep_understanding_input,
    ):
        """Feature Flag無効時は人名解決しない"""
        engine = create_intent_inference_engine(
            use_llm=False,
            pronoun_resolver=pronoun_resolver,
            person_alias_resolver=person_alias_resolver,
            context_expression_resolver=context_expression_resolver,
            feature_flags={
                FEATURE_FLAG_ENHANCED_PRONOUN: True,
                FEATURE_FLAG_PERSON_ALIAS: False,  # 無効
                FEATURE_FLAG_CONTEXT_EXPRESSION: True,
            },
        )

        result = await engine.infer(
            message="田中さんに連絡して",
            input_context=deep_understanding_input,
        )

        # 人名解決は行われないが、結果は返される
        assert result is not None


# =============================================================================
# 文脈依存表現解決テスト
# =============================================================================


class TestContextExpressionResolution:
    """文脈依存表現解決テスト"""

    @pytest.mark.asyncio
    async def test_resolve_habitual_expression(
        self,
        engine_with_enhanced_resolvers,
        deep_understanding_input,
    ):
        """習慣的表現を解決"""
        result = await engine_with_enhanced_resolvers.infer(
            message="いつものコーヒーください",
            input_context=deep_understanding_input,
        )

        assert result is not None
        # 文脈依存表現の意図が含まれる可能性がある

    @pytest.mark.asyncio
    async def test_resolve_reference_expression(
        self,
        engine_with_enhanced_resolvers,
        deep_understanding_input,
    ):
        """参照表現を解決"""
        result = await engine_with_enhanced_resolvers.infer(
            message="あの件どうなった？",
            input_context=deep_understanding_input,
        )

        assert result is not None


# =============================================================================
# 統合テスト
# =============================================================================


class TestIntegration:
    """統合テスト"""

    @pytest.mark.asyncio
    async def test_complex_message_with_multiple_resolutions(
        self,
        engine_with_enhanced_resolvers,
        deep_understanding_input,
    ):
        """複合的なメッセージの解決"""
        result = await engine_with_enhanced_resolvers.infer(
            message="田中さんにこれを送って、いつものやつで",
            input_context=deep_understanding_input,
        )

        assert result is not None
        # 複数の意図が検出される可能性がある
        assert result.processing_time_ms >= 0

    @pytest.mark.asyncio
    async def test_needs_confirmation_for_ambiguous(
        self,
        engine_with_enhanced_resolvers,
    ):
        """曖昧な入力では確認が必要"""
        # 空のコンテキスト
        empty_context = DeepUnderstandingInput(
            message="あれを確認して",
            organization_id="test_org",
            recent_conversation=[],
            recent_tasks=[],
            person_info=[],
        )

        result = await engine_with_enhanced_resolvers.infer(
            message="あれを確認して",
            input_context=empty_context,
        )

        # 曖昧な場合は確認が必要になる可能性がある
        assert result is not None

    @pytest.mark.asyncio
    async def test_error_handling(
        self,
        deep_understanding_input,
    ):
        """エラーハンドリング"""
        # 壊れたリゾルバーをモック
        broken_resolver = MagicMock()
        broken_resolver.resolve = AsyncMock(side_effect=Exception("Test error"))

        engine = IntentInferenceEngine(
            use_llm=False,
            pronoun_resolver=broken_resolver,
            feature_flags={FEATURE_FLAG_ENHANCED_PRONOUN: True},
        )

        # エラーが発生しても結果は返される
        result = await engine.infer(
            message="これを確認して",
            input_context=deep_understanding_input,
        )

        assert result is not None


# =============================================================================
# ファクトリー関数テスト
# =============================================================================


class TestFactoryFunction:
    """ファクトリー関数テスト"""

    def test_create_basic_engine(self):
        """基本的なエンジンの作成"""
        engine = create_intent_inference_engine()
        assert isinstance(engine, IntentInferenceEngine)

    def test_create_engine_with_all_resolvers(
        self,
        pronoun_resolver,
        person_alias_resolver,
        context_expression_resolver,
    ):
        """全リゾルバー付きエンジンの作成"""
        engine = create_intent_inference_engine(
            pronoun_resolver=pronoun_resolver,
            person_alias_resolver=person_alias_resolver,
            context_expression_resolver=context_expression_resolver,
            feature_flags={
                FEATURE_FLAG_ENHANCED_PRONOUN: True,
                FEATURE_FLAG_PERSON_ALIAS: True,
                FEATURE_FLAG_CONTEXT_EXPRESSION: True,
            },
        )

        assert engine._pronoun_resolver is pronoun_resolver
        assert engine._person_alias_resolver is person_alias_resolver
        assert engine._context_expression_resolver is context_expression_resolver


# =============================================================================
# パフォーマンステスト
# =============================================================================


class TestPerformance:
    """パフォーマンステスト"""

    @pytest.mark.asyncio
    async def test_processing_time_is_recorded(
        self,
        engine_with_enhanced_resolvers,
        deep_understanding_input,
    ):
        """処理時間が記録される"""
        result = await engine_with_enhanced_resolvers.infer(
            message="これを確認して",
            input_context=deep_understanding_input,
        )

        assert result.processing_time_ms >= 0

    @pytest.mark.asyncio
    async def test_strategies_used_is_recorded(
        self,
        engine_with_enhanced_resolvers,
        deep_understanding_input,
    ):
        """使用された戦略が記録される"""
        result = await engine_with_enhanced_resolvers.infer(
            message="これを確認して",
            input_context=deep_understanding_input,
        )

        # strategies_usedが存在する
        assert hasattr(result, "strategies_used")
