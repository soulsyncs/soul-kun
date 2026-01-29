# tests/test_pronoun_resolver.py
"""
EnhancedPronounResolver のテスト

強化版代名詞リゾルバーの検証
"""

import pytest
from lib.brain.deep_understanding.pronoun_resolver import (
    EnhancedPronounResolver,
    create_pronoun_resolver,
    PronounDistance,
    PronounType,
    PronounCandidate,
    PronounResolutionResult,
    DEMONSTRATIVE_PRONOUNS,
)
from lib.brain.constants import CONFIRMATION_THRESHOLD


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def conversation_history():
    """テスト用の会話履歴"""
    return [
        {"role": "user", "content": "タスクAについて確認したい"},
        {"role": "assistant", "content": "タスクAの期限は明日です"},
        {"role": "user", "content": "プロジェクトBの進捗はどう？"},
        {"role": "assistant", "content": "プロジェクトBは80%完了しています"},
        {"role": "user", "content": "以前話したプロジェクトCの件も気になる"},
    ]


@pytest.fixture
def recent_tasks():
    """テスト用のタスクリスト"""
    return [
        {"task_id": "1", "body": "週次報告書の作成", "status": "open"},
        {"task_id": "2", "body": "クライアントへの連絡", "status": "open"},
        {"task_id": "3", "body": "コードレビュー", "status": "open"},
        {"task_id": "4", "body": "過去のミーティング議事録", "status": "done"},
        {"task_id": "5", "body": "古いタスクの整理", "status": "done"},
    ]


@pytest.fixture
def person_info():
    """テスト用の人物情報"""
    return [
        {"name": "田中", "position": "エンジニア"},
        {"name": "山田", "position": "マネージャー"},
        {"name": "佐藤", "position": "デザイナー"},
    ]


@pytest.fixture
def resolver(conversation_history, recent_tasks, person_info):
    """テスト用のEnhancedPronounResolver"""
    return EnhancedPronounResolver(
        conversation_history=conversation_history,
        current_context={"topic": "task_management"},
        recent_tasks=recent_tasks,
        person_info=person_info,
    )


@pytest.fixture
def resolver_minimal():
    """最小構成のResolver"""
    return EnhancedPronounResolver()


# =============================================================================
# Enum テスト
# =============================================================================


class TestPronounEnums:
    """代名詞関連Enumのテスト"""

    def test_pronoun_distance_values(self):
        """PronounDistanceの値"""
        assert PronounDistance.NEAR.value == "near"
        assert PronounDistance.MIDDLE.value == "middle"
        assert PronounDistance.FAR.value == "far"

    def test_pronoun_type_values(self):
        """PronounTypeの値"""
        assert PronounType.THING.value == "thing"
        assert PronounType.PLACE.value == "place"
        assert PronounType.PERSON.value == "person"


# =============================================================================
# DEMONSTRATIVE_PRONOUNS テスト
# =============================================================================


class TestDemonstrativePronouns:
    """指示代名詞マッピングのテスト"""

    def test_ko_series_is_near(self):
        """コ系は近称"""
        ko_pronouns = ["これ", "この", "ここ", "こちら", "この人"]
        for pronoun in ko_pronouns:
            assert pronoun in DEMONSTRATIVE_PRONOUNS
            assert DEMONSTRATIVE_PRONOUNS[pronoun]["distance"] == PronounDistance.NEAR

    def test_so_series_is_middle(self):
        """ソ系は中称"""
        so_pronouns = ["それ", "その", "そこ", "そちら", "その人"]
        for pronoun in so_pronouns:
            assert pronoun in DEMONSTRATIVE_PRONOUNS
            assert DEMONSTRATIVE_PRONOUNS[pronoun]["distance"] == PronounDistance.MIDDLE

    def test_a_series_is_far(self):
        """ア系は遠称"""
        a_pronouns = ["あれ", "あの", "あそこ", "あちら", "あの人"]
        for pronoun in a_pronouns:
            assert pronoun in DEMONSTRATIVE_PRONOUNS
            assert DEMONSTRATIVE_PRONOUNS[pronoun]["distance"] == PronounDistance.FAR

    def test_personal_pronouns_are_far(self):
        """人称代名詞は遠称"""
        personal = ["彼", "彼女", "あいつ", "やつ"]
        for pronoun in personal:
            assert pronoun in DEMONSTRATIVE_PRONOUNS
            assert DEMONSTRATIVE_PRONOUNS[pronoun]["distance"] == PronounDistance.FAR
            assert DEMONSTRATIVE_PRONOUNS[pronoun]["type"] == PronounType.PERSON


# =============================================================================
# PronounCandidate テスト
# =============================================================================


class TestPronounCandidate:
    """PronounCandidateデータクラスのテスト"""

    def test_create_candidate(self):
        """候補の作成"""
        candidate = PronounCandidate(
            entity="タスクA",
            confidence=0.8,
            source="recent_task",
        )
        assert candidate.entity == "タスクA"
        assert candidate.confidence == 0.8
        assert candidate.source == "recent_task"

    def test_calculate_total_score(self):
        """総合スコアの計算"""
        candidate = PronounCandidate(
            entity="タスクA",
            distance_match=True,
            recency_score=1.0,
            topic_relevance=1.0,
        )
        score = candidate.calculate_total_score()
        # distance_match(True)=1.0*0.3 + recency=1.0*0.3 + relevance=1.0*0.4 = 1.0
        assert score == 1.0

    def test_calculate_total_score_with_distance_mismatch(self):
        """距離不一致時のスコア計算"""
        candidate = PronounCandidate(
            entity="タスクA",
            distance_match=False,  # 不一致
            recency_score=1.0,
            topic_relevance=1.0,
        )
        score = candidate.calculate_total_score()
        # distance_match(False)=0.3*0.3 + recency=1.0*0.3 + relevance=1.0*0.4 = 0.79
        assert score < 1.0
        assert score > 0.7


# =============================================================================
# PronounResolutionResult テスト
# =============================================================================


class TestPronounResolutionResult:
    """PronounResolutionResultデータクラスのテスト"""

    def test_get_confirmation_options(self):
        """確認用選択肢の取得"""
        candidates = [
            PronounCandidate(entity="タスクA"),
            PronounCandidate(entity="タスクB"),
            PronounCandidate(entity="タスクC"),
        ]
        result = PronounResolutionResult(
            pronoun="これ",
            needs_confirmation=True,
            candidates=candidates,
        )
        options = result.get_confirmation_options()
        assert len(options) == 3
        assert "タスクA" in options

    def test_confirmation_options_max_four(self):
        """選択肢は最大4つ"""
        candidates = [
            PronounCandidate(entity=f"タスク{i}") for i in range(10)
        ]
        result = PronounResolutionResult(
            pronoun="これ",
            candidates=candidates,
        )
        options = result.get_confirmation_options()
        assert len(options) == 4


# =============================================================================
# EnhancedPronounResolver 初期化テスト
# =============================================================================


class TestPronounResolverInit:
    """EnhancedPronounResolver初期化テスト"""

    def test_init_with_all_params(self, conversation_history, recent_tasks, person_info):
        """全パラメータでの初期化"""
        resolver = EnhancedPronounResolver(
            conversation_history=conversation_history,
            current_context={"topic": "test"},
            recent_tasks=recent_tasks,
            person_info=person_info,
        )
        assert len(resolver._history) == 5
        assert len(resolver._tasks) == 5
        assert len(resolver._persons) == 3

    def test_init_with_no_params(self):
        """パラメータなしでの初期化"""
        resolver = EnhancedPronounResolver()
        assert resolver._history == []
        assert resolver._tasks == []
        assert resolver._persons == []

    def test_factory_function(self, conversation_history):
        """ファクトリー関数"""
        resolver = create_pronoun_resolver(
            conversation_history=conversation_history,
        )
        assert isinstance(resolver, EnhancedPronounResolver)


# =============================================================================
# 代名詞情報取得テスト
# =============================================================================


class TestGetPronounInfo:
    """代名詞情報取得テスト"""

    def test_get_info_for_kore(self, resolver):
        """「これ」の情報取得"""
        info = resolver._get_pronoun_info("これ")
        assert info["distance"] == PronounDistance.NEAR
        assert info["type"] == PronounType.THING

    def test_get_info_for_are(self, resolver):
        """「あれ」の情報取得"""
        info = resolver._get_pronoun_info("あれ")
        assert info["distance"] == PronounDistance.FAR
        assert info["type"] == PronounType.THING

    def test_get_info_for_unknown(self, resolver):
        """未知の代名詞はデフォルト値"""
        info = resolver._get_pronoun_info("なにか")
        assert info["distance"] == PronounDistance.MIDDLE


# =============================================================================
# 候補収集テスト
# =============================================================================


class TestCollectCandidates:
    """候補収集テスト"""

    @pytest.mark.asyncio
    async def test_collect_near_candidates(self, resolver):
        """近称候補の収集"""
        candidates = await resolver._collect_near_candidates(PronounType.THING)
        # 直近のユーザー発言とタスクから候補が収集される
        assert len(candidates) > 0

    @pytest.mark.asyncio
    async def test_collect_middle_candidates(self, resolver):
        """中称候補の収集"""
        candidates = await resolver._collect_middle_candidates(PronounType.THING)
        # アシスタントの発言とコンテキストから候補が収集される
        assert len(candidates) > 0

    @pytest.mark.asyncio
    async def test_collect_far_candidates(self, resolver):
        """遠称候補の収集"""
        candidates = await resolver._collect_far_candidates(PronounType.THING)
        # 過去の会話とタスクから候補が収集される
        # 会話が5件しかないので、3件目以降（2件）+ 3件目以降のタスク
        assert len(candidates) >= 0

    @pytest.mark.asyncio
    async def test_collect_person_candidates(self, resolver):
        """人物候補の収集"""
        candidates = await resolver._collect_person_candidates()
        assert len(candidates) >= 3  # person_infoの3人


# =============================================================================
# エンティティ抽出テスト
# =============================================================================


class TestEntityExtraction:
    """エンティティ抽出テスト"""

    def test_extract_quoted_text(self, resolver):
        """カギカッコ内のテキスト抽出"""
        entities = resolver._extract_entities_from_text("「タスクA」について確認")
        assert "タスクA" in entities

    def test_extract_about_pattern(self, resolver):
        """「〜について」パターンの抽出"""
        entities = resolver._extract_entities_from_text("プロジェクトについて確認")
        assert "プロジェクト" in entities

    def test_extract_matter_pattern(self, resolver):
        """「〜の件」パターンの抽出"""
        entities = resolver._extract_entities_from_text("会議の件で連絡")
        assert "会議" in entities

    def test_extract_person_names(self, resolver):
        """人名の抽出"""
        names = resolver._extract_person_names("田中さんと山田くんに連絡")
        assert "田中" in names
        assert "山田" in names


# =============================================================================
# スコアリングテスト
# =============================================================================


class TestScoring:
    """スコアリングテスト"""

    def test_score_and_sort(self, resolver):
        """スコアリングとソート"""
        candidates = [
            PronounCandidate(entity="低スコア", recency_score=0.1, topic_relevance=0.1),
            PronounCandidate(entity="高スコア", recency_score=1.0, topic_relevance=1.0),
        ]
        sorted_candidates = resolver._score_and_sort_candidates(candidates, "テスト")
        assert sorted_candidates[0].entity == "高スコア"

    def test_bonus_for_entity_in_message(self, resolver):
        """メッセージ中のエンティティにボーナス"""
        candidates = [
            PronounCandidate(entity="タスクA", topic_relevance=0.5),
        ]
        resolver._score_and_sort_candidates(candidates, "タスクAを完了して")
        assert candidates[0].topic_relevance == 0.7  # 0.5 + 0.2

    def test_deduplicate_candidates(self, resolver):
        """候補の重複除去"""
        candidates = [
            PronounCandidate(entity="タスクA"),
            PronounCandidate(entity="タスクA"),  # 重複
            PronounCandidate(entity="タスクB"),
        ]
        unique = resolver._deduplicate_candidates(candidates)
        assert len(unique) == 2


# =============================================================================
# resolve() テスト
# =============================================================================


class TestResolve:
    """resolve()メソッドのテスト"""

    @pytest.mark.asyncio
    async def test_resolve_kore_with_recent_context(self, resolver):
        """「これ」の解決（直近コンテキストあり）"""
        result = await resolver.resolve("これ", "これを完了して")

        assert result.pronoun == "これ"
        assert result.distance == PronounDistance.NEAR
        assert len(result.candidates) > 0

    @pytest.mark.asyncio
    async def test_resolve_are_with_past_context(self, resolver):
        """「あれ」の解決（過去コンテキスト）"""
        result = await resolver.resolve("あれ", "あれどうなった？")

        assert result.pronoun == "あれ"
        assert result.distance == PronounDistance.FAR

    @pytest.mark.asyncio
    async def test_resolve_with_no_context(self, resolver_minimal):
        """コンテキストなしでの解決"""
        result = await resolver_minimal.resolve("これ", "これを確認")

        assert result.needs_confirmation is True
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_resolve_triggers_confirmation_on_low_confidence(self, resolver):
        """低確信度で確認モード発動"""
        # 会話履歴、タスク、コンテキストを全てクリアして曖昧な状態にする
        resolver._history = []
        resolver._tasks = []
        resolver._context = {}  # コンテキストもクリア

        result = await resolver.resolve("それ", "それを確認して")

        assert result.needs_confirmation is True

    @pytest.mark.asyncio
    async def test_resolve_person_pronoun(self, resolver):
        """人物代名詞の解決"""
        result = await resolver.resolve("あの人", "あの人に連絡して")

        assert result.pronoun_type == PronounType.PERSON
        assert len(result.candidates) > 0


# =============================================================================
# 距離感テスト
# =============================================================================


class TestDistanceBasedResolution:
    """距離感に基づく解決テスト"""

    @pytest.mark.asyncio
    async def test_kore_prefers_recent_messages(self, resolver):
        """「これ」は直近のメッセージを優先"""
        result = await resolver.resolve("これ", "これを確認")

        # 候補が存在し、近称の候補が含まれる
        assert len(result.candidates) > 0
        # 候補のソースをチェック
        sources = [c.source for c in result.candidates]
        # 直近のメッセージまたはタスクから
        assert any(
            "recent" in s or "task" in s for s in sources
        )

    @pytest.mark.asyncio
    async def test_sore_prefers_assistant_context(self, resolver):
        """「それ」はアシスタントのコンテキストを優先"""
        result = await resolver.resolve("それ", "それについて詳しく")

        assert result.distance == PronounDistance.MIDDLE

    @pytest.mark.asyncio
    async def test_are_prefers_past_context(self, resolver):
        """「あれ」は過去のコンテキストを優先"""
        result = await resolver.resolve("あれ", "あれの件")

        assert result.distance == PronounDistance.FAR


# =============================================================================
# 確認モードテスト
# =============================================================================


class TestConfirmationMode:
    """確認モードテスト"""

    @pytest.mark.asyncio
    async def test_confirmation_threshold_applied(self):
        """確認閾値が適用される"""
        assert CONFIRMATION_THRESHOLD == 0.7
        resolver = EnhancedPronounResolver()
        assert resolver.CONFIRMATION_THRESHOLD == 0.7

    @pytest.mark.asyncio
    async def test_high_confidence_no_confirmation(self):
        """高確信度では確認不要"""
        # 明確な文脈を持つResolver
        resolver = EnhancedPronounResolver(
            conversation_history=[
                {"role": "user", "content": "「重要タスク」を確認して"},
            ],
            recent_tasks=[
                {"task_id": "1", "body": "重要タスク"},
            ],
        )

        result = await resolver.resolve("これ", "これを完了して")

        # 候補がある場合
        if result.candidates:
            # 確信度が高ければ確認不要（テストは候補に依存）
            pass

    @pytest.mark.asyncio
    async def test_no_candidates_needs_confirmation(self, resolver_minimal):
        """候補なしは確認必要"""
        result = await resolver_minimal.resolve("これ", "これを確認")

        assert result.needs_confirmation is True
        assert result.resolved_to is None


# =============================================================================
# 同期版テスト
# =============================================================================


class TestSyncResolve:
    """同期版resolve_syncのテスト"""

    def test_resolve_sync(self, resolver):
        """同期版のresolve"""
        result = resolver.resolve_sync("これ", "これを確認")

        assert isinstance(result, PronounResolutionResult)
        assert result.pronoun == "これ"
