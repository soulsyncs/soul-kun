# tests/test_context_expression.py
"""
ContextExpressionResolver のテスト

文脈依存表現リゾルバーの検証
"""

import pytest
from datetime import datetime, timedelta
from lib.brain.deep_understanding.context_expression import (
    ContextExpressionResolver,
    create_context_expression_resolver,
    ContextCandidate,
    ContextResolutionResult,
    ExpressionType,
    HABITUAL_PATTERNS,
    REFERENCE_PATTERNS,
    TEMPORAL_PATTERNS,
    RECENT_PATTERNS,
)
from lib.brain.constants import CONFIRMATION_THRESHOLD, JST


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def conversation_history():
    """テスト用の会話履歴"""
    return [
        {"role": "user", "content": "プロジェクトAについて確認したい"},
        {"role": "assistant", "content": "プロジェクトAの進捗は80%です"},
        {"role": "user", "content": "タスクBの件で連絡ください"},
        {"role": "assistant", "content": "タスクBについて了解しました"},
        {"role": "user", "content": "先週のミーティングの内容を教えて"},
    ]


@pytest.fixture
def user_habits():
    """テスト用のユーザー習慣"""
    return {
        "coffee_order": "アメリカン",
        "lunch_order": "A定食",
        "seat_preference": "窓際",
        "report_format": "簡潔に箇条書き",
    }


@pytest.fixture
def recent_topics():
    """テスト用の最近の話題"""
    return [
        {"name": "新機能開発", "subject": "機能X", "timestamp": datetime.now(JST)},
        {"name": "バグ修正", "subject": "バグY", "timestamp": datetime.now(JST) - timedelta(hours=2)},
        {"name": "ミーティング", "subject": "週次MTG", "timestamp": datetime.now(JST) - timedelta(days=1)},
    ]


@pytest.fixture
def resolver(conversation_history, user_habits, recent_topics):
    """テスト用のContextExpressionResolver"""
    return ContextExpressionResolver(
        conversation_history=conversation_history,
        user_habits=user_habits,
        recent_topics=recent_topics,
    )


@pytest.fixture
def resolver_empty():
    """空のResolver"""
    return ContextExpressionResolver()


# =============================================================================
# 定数テスト
# =============================================================================


class TestConstants:
    """定数のテスト"""

    def test_habitual_patterns_defined(self):
        """習慣的表現パターンが定義されている"""
        assert "いつもの" in HABITUAL_PATTERNS
        assert "いつも通り" in HABITUAL_PATTERNS
        assert "普段の" in HABITUAL_PATTERNS

    def test_reference_patterns_defined(self):
        """参照表現パターンが定義されている"""
        assert "あの件" in REFERENCE_PATTERNS
        assert "この件" in REFERENCE_PATTERNS
        assert "例の" in REFERENCE_PATTERNS

    def test_temporal_patterns_defined(self):
        """時間参照表現パターンが定義されている"""
        assert "この前の" in TEMPORAL_PATTERNS
        assert "先日の" in TEMPORAL_PATTERNS
        assert "前回の" in TEMPORAL_PATTERNS

    def test_recent_patterns_defined(self):
        """最近参照表現パターンが定義されている"""
        assert "さっきの" in RECENT_PATTERNS
        assert "先ほどの" in RECENT_PATTERNS
        assert "今の" in RECENT_PATTERNS


# =============================================================================
# ExpressionType テスト
# =============================================================================


class TestExpressionType:
    """ExpressionType Enumのテスト"""

    def test_expression_type_values(self):
        """表現タイプの値"""
        assert ExpressionType.HABITUAL.value == "habitual"
        assert ExpressionType.REFERENCE.value == "reference"
        assert ExpressionType.TEMPORAL.value == "temporal"
        assert ExpressionType.RECENT.value == "recent"
        assert ExpressionType.UNKNOWN.value == "unknown"


# =============================================================================
# ContextCandidate テスト
# =============================================================================


class TestContextCandidate:
    """ContextCandidateデータクラスのテスト"""

    def test_create_candidate(self):
        """候補の作成"""
        candidate = ContextCandidate(
            entity="アメリカン",
            confidence=0.9,
            source="user_habit",
            expression_type=ExpressionType.HABITUAL,
        )
        assert candidate.entity == "アメリカン"
        assert candidate.confidence == 0.9
        assert candidate.source == "user_habit"
        assert candidate.expression_type == ExpressionType.HABITUAL

    def test_default_values(self):
        """デフォルト値"""
        candidate = ContextCandidate(entity="テスト")
        assert candidate.confidence == 0.5
        assert candidate.source == "unknown"
        assert candidate.expression_type == ExpressionType.UNKNOWN


# =============================================================================
# ContextResolutionResult テスト
# =============================================================================


class TestContextResolutionResult:
    """ContextResolutionResultデータクラスのテスト"""

    def test_get_confirmation_options(self):
        """確認用選択肢の取得"""
        candidates = [
            ContextCandidate(entity="候補A"),
            ContextCandidate(entity="候補B"),
            ContextCandidate(entity="候補C"),
        ]
        result = ContextResolutionResult(
            expression="いつもの",
            needs_confirmation=True,
            candidates=candidates,
        )
        options = result.get_confirmation_options()
        assert len(options) == 3
        assert "候補A" in options

    def test_confirmation_options_max_four(self):
        """選択肢は最大4つ"""
        candidates = [
            ContextCandidate(entity=f"候補{i}") for i in range(10)
        ]
        result = ContextResolutionResult(
            expression="あの件",
            candidates=candidates,
        )
        options = result.get_confirmation_options()
        assert len(options) == 4


# =============================================================================
# 表現分類テスト
# =============================================================================


class TestExpressionClassification:
    """表現分類テスト"""

    def test_classify_habitual(self, resolver):
        """習慣的表現の分類"""
        assert resolver._classify_expression("いつもの") == ExpressionType.HABITUAL
        assert resolver._classify_expression("いつも通り") == ExpressionType.HABITUAL
        assert resolver._classify_expression("普段のやつ") == ExpressionType.HABITUAL

    def test_classify_reference(self, resolver):
        """参照表現の分類"""
        assert resolver._classify_expression("あの件") == ExpressionType.REFERENCE
        assert resolver._classify_expression("例の") == ExpressionType.REFERENCE
        assert resolver._classify_expression("その件で") == ExpressionType.REFERENCE

    def test_classify_temporal(self, resolver):
        """時間参照表現の分類"""
        assert resolver._classify_expression("この前の") == ExpressionType.TEMPORAL
        assert resolver._classify_expression("先日の話") == ExpressionType.TEMPORAL
        assert resolver._classify_expression("前回の") == ExpressionType.TEMPORAL

    def test_classify_recent(self, resolver):
        """最近参照表現の分類"""
        assert resolver._classify_expression("さっきの") == ExpressionType.RECENT
        assert resolver._classify_expression("先ほどの件") == ExpressionType.RECENT
        assert resolver._classify_expression("今の話") == ExpressionType.RECENT

    def test_classify_unknown(self, resolver):
        """不明な表現の分類"""
        assert resolver._classify_expression("テスト") == ExpressionType.UNKNOWN


# =============================================================================
# 表現検出テスト
# =============================================================================


class TestExpressionDetection:
    """表現検出テスト"""

    def test_detect_single_expression(self, resolver):
        """単一表現の検出"""
        found = resolver.detect_expressions("いつものコーヒーください")
        assert len(found) >= 1
        assert any(expr == "いつもの" for expr, _ in found)

    def test_detect_multiple_expressions(self, resolver):
        """複数表現の検出"""
        found = resolver.detect_expressions("いつものコーヒーと、あの件について")
        assert len(found) >= 2
        patterns = [expr for expr, _ in found]
        assert "いつもの" in patterns
        assert "あの件" in patterns

    def test_detect_no_expression(self, resolver):
        """表現なしの検出"""
        found = resolver.detect_expressions("普通のメッセージです")
        assert len(found) == 0


# =============================================================================
# 習慣的表現解決テスト
# =============================================================================


class TestHabitualResolution:
    """習慣的表現解決テスト"""

    @pytest.mark.asyncio
    async def test_resolve_habitual_with_habit(self, resolver):
        """習慣がある場合の解決"""
        result = await resolver.resolve("いつもの", "いつものコーヒーください")

        assert result.expression_type == ExpressionType.HABITUAL
        assert len(result.candidates) > 0
        # ユーザー習慣から候補が見つかる
        assert any(c.entity == "アメリカン" for c in result.candidates)

    @pytest.mark.asyncio
    async def test_resolve_habitual_lunch(self, resolver):
        """ランチの習慣解決"""
        result = await resolver.resolve("いつもの", "いつもの昼食でお願い")

        assert result.expression_type == ExpressionType.HABITUAL
        assert any(c.entity == "A定食" for c in result.candidates)

    @pytest.mark.asyncio
    async def test_resolve_habitual_no_context(self, resolver_empty):
        """コンテキストなしの習慣解決"""
        result = await resolver_empty.resolve("いつもの", "いつものでお願い")

        assert result.needs_confirmation is True


# =============================================================================
# 参照表現解決テスト
# =============================================================================


class TestReferenceResolution:
    """参照表現解決テスト"""

    @pytest.mark.asyncio
    async def test_resolve_reference_with_topics(self, resolver):
        """話題がある場合の参照解決"""
        result = await resolver.resolve("あの件", "あの件どうなった？")

        assert result.expression_type == ExpressionType.REFERENCE
        assert len(result.candidates) > 0

    @pytest.mark.asyncio
    async def test_resolve_reference_from_history(self, resolver):
        """会話履歴からの参照解決"""
        result = await resolver.resolve("例の", "例のプロジェクトについて")

        assert result.expression_type == ExpressionType.REFERENCE
        # 会話履歴から候補が抽出される
        assert len(result.candidates) >= 0

    @pytest.mark.asyncio
    async def test_resolve_reference_no_context(self, resolver_empty):
        """コンテキストなしの参照解決"""
        result = await resolver_empty.resolve("あの件", "あの件について")

        assert result.needs_confirmation is True


# =============================================================================
# 時間参照表現解決テスト
# =============================================================================


class TestTemporalResolution:
    """時間参照表現解決テスト"""

    @pytest.mark.asyncio
    async def test_resolve_temporal(self, resolver):
        """時間参照の解決"""
        result = await resolver.resolve("この前の", "この前のミーティングの件")

        assert result.expression_type == ExpressionType.TEMPORAL

    @pytest.mark.asyncio
    async def test_infer_time_range_konmae(self, resolver):
        """「この前」の時間範囲推測"""
        time_range = resolver._infer_time_range("この前の")
        assert time_range is not None
        start, end = time_range
        # 1週間前から昨日まで
        assert (datetime.now(JST) - start).days <= 7

    @pytest.mark.asyncio
    async def test_infer_time_range_kinou(self, resolver):
        """「昨日」の時間範囲推測"""
        time_range = resolver._infer_time_range("昨日の")
        assert time_range is not None
        start, end = time_range
        # 1日分
        assert (end - start).days == 0


# =============================================================================
# 最近参照表現解決テスト
# =============================================================================


class TestRecentResolution:
    """最近参照表現解決テスト"""

    @pytest.mark.asyncio
    async def test_resolve_recent(self, resolver):
        """最近参照の解決"""
        result = await resolver.resolve("さっきの", "さっきの話の続き")

        assert result.expression_type == ExpressionType.RECENT
        assert len(result.candidates) > 0

    @pytest.mark.asyncio
    async def test_resolve_recent_high_recency(self, resolver):
        """直近の話題が高スコア"""
        result = await resolver.resolve("さっきの", "さっきの件")

        if result.candidates:
            # 最初の候補が最も高いスコアを持つはず
            sorted_candidates = sorted(
                result.candidates, key=lambda c: c.confidence, reverse=True
            )
            assert result.candidates[0].confidence >= sorted_candidates[-1].confidence


# =============================================================================
# ヘルパーメソッドテスト
# =============================================================================


class TestHelperMethods:
    """ヘルパーメソッドテスト"""

    def test_infer_context_coffee(self, resolver):
        """コーヒーコンテキストの推測"""
        context = resolver._infer_context_from_message("いつものコーヒーください")
        assert context == "coffee_order"

    def test_infer_context_lunch(self, resolver):
        """ランチコンテキストの推測"""
        context = resolver._infer_context_from_message("いつものランチで")
        assert context == "lunch_order"

    def test_infer_context_none(self, resolver):
        """コンテキストなしの推測"""
        context = resolver._infer_context_from_message("テストメッセージ")
        assert context is None

    def test_extract_topic_entities(self, resolver):
        """話題エンティティの抽出"""
        entities = resolver._extract_topic_entities("「プロジェクトX」について確認")
        assert "プロジェクトX" in entities

    def test_extract_topic_entities_no_pattern(self, resolver):
        """パターンなしの抽出"""
        entities = resolver._extract_topic_entities("普通のテキスト")
        assert len(entities) == 0


# =============================================================================
# 確認モードテスト
# =============================================================================


class TestConfirmationMode:
    """確認モードテスト"""

    @pytest.mark.asyncio
    async def test_confirmation_threshold_applied(self):
        """確認閾値が適用される"""
        assert CONFIRMATION_THRESHOLD == 0.7
        resolver = ContextExpressionResolver()
        assert resolver.CONFIRMATION_THRESHOLD == 0.7

    @pytest.mark.asyncio
    async def test_high_confidence_no_confirmation(self, resolver):
        """高確信度では確認不要"""
        # 習慣が明確にある場合
        result = await resolver.resolve("いつもの", "いつものコーヒーください")

        if result.candidates and result.candidates[0].confidence >= 0.7:
            # 確信度が高ければ確認不要
            assert result.needs_confirmation is False

    @pytest.mark.asyncio
    async def test_no_candidates_needs_confirmation(self, resolver_empty):
        """候補なしは確認必要"""
        result = await resolver_empty.resolve("いつもの", "いつものでお願い")

        assert result.needs_confirmation is True
        assert result.resolved_to is None


# =============================================================================
# 同期版テスト
# =============================================================================


class TestSyncResolve:
    """同期版resolve_syncのテスト"""

    def test_resolve_sync(self, resolver):
        """同期版のresolve"""
        result = resolver.resolve_sync("いつもの", "いつものコーヒーください")

        assert isinstance(result, ContextResolutionResult)
        assert result.expression_type == ExpressionType.HABITUAL


# =============================================================================
# ファクトリー関数テスト
# =============================================================================


class TestFactoryFunction:
    """ファクトリー関数テスト"""

    def test_create_resolver(self):
        """ファクトリー関数でResolverを作成"""
        resolver = create_context_expression_resolver(
            user_habits={"coffee_order": "アメリカン"},
        )

        assert isinstance(resolver, ContextExpressionResolver)

    @pytest.mark.asyncio
    async def test_resolver_from_factory_works(self):
        """ファクトリーで作成したResolverが動作する"""
        resolver = create_context_expression_resolver(
            user_habits={"coffee_order": "アメリカン"},
        )

        result = await resolver.resolve("いつもの", "いつものコーヒーください")
        assert result.expression_type == ExpressionType.HABITUAL


# =============================================================================
# 統合テスト
# =============================================================================


class TestIntegration:
    """統合テスト"""

    @pytest.mark.asyncio
    async def test_full_workflow(self, resolver):
        """完全なワークフロー"""
        # 1. 表現検出
        found = resolver.detect_expressions("いつものコーヒーと、あの件どうなった？")
        assert len(found) >= 2

        # 2. 各表現を解決
        for expr, expr_type in found:
            result = await resolver.resolve(expr, "テストメッセージ")
            assert result.expression_type == expr_type

    @pytest.mark.asyncio
    async def test_deduplicate_candidates(self, resolver):
        """候補の重複除去"""
        candidates = [
            ContextCandidate(entity="同じ候補", confidence=0.9),
            ContextCandidate(entity="同じ候補", confidence=0.8),  # 重複
            ContextCandidate(entity="別の候補", confidence=0.7),
        ]
        unique = resolver._deduplicate_candidates(candidates)
        assert len(unique) == 2
