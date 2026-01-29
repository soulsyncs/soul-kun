# tests/test_person_alias.py
"""
PersonAliasResolver のテスト

人名エイリアスリゾルバーの検証
"""

import pytest
from lib.brain.deep_understanding.person_alias import (
    PersonAliasResolver,
    create_person_alias_resolver,
    PersonCandidate,
    PersonResolutionResult,
    PersonServiceAdapter,
    MatchType,
    HONORIFICS,
    COMMON_HONORIFICS,
)
from lib.brain.constants import CONFIRMATION_THRESHOLD


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def known_persons():
    """テスト用の既知人物リスト"""
    return [
        "田中太郎",
        "山田花子",
        "佐藤一郎",
        "鈴木次郎",
        "高橋三郎",
    ]


@pytest.fixture
def resolver(known_persons):
    """テスト用のPersonAliasResolver"""
    return PersonAliasResolver(
        known_persons=known_persons,
    )


@pytest.fixture
def resolver_empty():
    """空のResolver"""
    return PersonAliasResolver()


# =============================================================================
# 定数テスト
# =============================================================================


class TestConstants:
    """定数のテスト"""

    def test_honorifics_defined(self):
        """敬称リストが定義されている"""
        assert "さん" in HONORIFICS
        assert "くん" in HONORIFICS
        assert "君" in HONORIFICS
        assert "ちゃん" in HONORIFICS
        assert "氏" in HONORIFICS
        assert "様" in HONORIFICS

    def test_common_honorifics_defined(self):
        """一般的な敬称リストが定義されている"""
        assert "さん" in COMMON_HONORIFICS
        assert "くん" in COMMON_HONORIFICS
        assert "ちゃん" in COMMON_HONORIFICS


# =============================================================================
# MatchType テスト
# =============================================================================


class TestMatchType:
    """MatchType Enumのテスト"""

    def test_match_type_values(self):
        """マッチタイプの値"""
        assert MatchType.EXACT.value == "exact"
        assert MatchType.NORMALIZED.value == "normalized"
        assert MatchType.ALIAS.value == "alias"
        assert MatchType.PARTIAL.value == "partial"


# =============================================================================
# PersonCandidate テスト
# =============================================================================


class TestPersonCandidate:
    """PersonCandidateデータクラスのテスト"""

    def test_create_candidate(self):
        """候補の作成"""
        candidate = PersonCandidate(
            name="田中太郎",
            input_name="田中さん",
            match_type=MatchType.NORMALIZED,
        )
        assert candidate.name == "田中太郎"
        assert candidate.input_name == "田中さん"
        assert candidate.match_type == MatchType.NORMALIZED

    def test_auto_confidence_by_match_type(self):
        """マッチタイプによる自動確信度設定"""
        # EXACT → 1.0
        exact = PersonCandidate(
            name="田中太郎",
            input_name="田中太郎",
            match_type=MatchType.EXACT,
        )
        assert exact.confidence == 1.0

        # NORMALIZED → 0.95
        normalized = PersonCandidate(
            name="田中太郎",
            input_name="田中さん",
            match_type=MatchType.NORMALIZED,
        )
        assert normalized.confidence == 0.95

        # ALIAS → 0.85
        alias = PersonCandidate(
            name="田中太郎",
            input_name="田中",
            match_type=MatchType.ALIAS,
        )
        assert alias.confidence == 0.85

        # PARTIAL → 0.6
        partial = PersonCandidate(
            name="田中太郎",
            input_name="田中太",
            match_type=MatchType.PARTIAL,
        )
        assert partial.confidence == 0.6

    def test_explicit_confidence_not_overwritten(self):
        """明示的な確信度は上書きされない"""
        candidate = PersonCandidate(
            name="田中太郎",
            input_name="田中さん",
            match_type=MatchType.NORMALIZED,
            confidence=0.8,  # 明示的に指定
        )
        assert candidate.confidence == 0.8


# =============================================================================
# PersonResolutionResult テスト
# =============================================================================


class TestPersonResolutionResult:
    """PersonResolutionResultデータクラスのテスト"""

    def test_get_confirmation_options(self):
        """確認用選択肢の取得"""
        candidates = [
            PersonCandidate(name="田中太郎", input_name="田中", match_type=MatchType.PARTIAL),
            PersonCandidate(name="田中花子", input_name="田中", match_type=MatchType.PARTIAL),
        ]
        result = PersonResolutionResult(
            input_name="田中",
            needs_confirmation=True,
            candidates=candidates,
        )
        options = result.get_confirmation_options()
        assert len(options) == 2
        assert "田中太郎" in options
        assert "田中花子" in options

    def test_confirmation_options_max_four(self):
        """選択肢は最大4つ"""
        candidates = [
            PersonCandidate(name=f"候補{i}", input_name="x", match_type=MatchType.PARTIAL)
            for i in range(10)
        ]
        result = PersonResolutionResult(
            input_name="x",
            candidates=candidates,
        )
        options = result.get_confirmation_options()
        assert len(options) == 4


# =============================================================================
# 敬称除去テスト
# =============================================================================


class TestHonorificRemoval:
    """敬称除去テスト"""

    def test_remove_san(self, resolver):
        """「さん」の除去"""
        assert resolver.remove_honorific("田中さん") == "田中"

    def test_remove_kun(self, resolver):
        """「くん」の除去"""
        assert resolver.remove_honorific("山田くん") == "山田"

    def test_remove_kun_kanji(self, resolver):
        """「君」の除去"""
        assert resolver.remove_honorific("山田君") == "山田"

    def test_remove_chan(self, resolver):
        """「ちゃん」の除去"""
        assert resolver.remove_honorific("花子ちゃん") == "花子"

    def test_remove_sama(self, resolver):
        """「様」の除去"""
        assert resolver.remove_honorific("田中様") == "田中"

    def test_remove_shi(self, resolver):
        """「氏」の除去"""
        assert resolver.remove_honorific("田中氏") == "田中"

    def test_remove_sensei(self, resolver):
        """「先生」の除去"""
        assert resolver.remove_honorific("田中先生") == "田中"

    def test_remove_buchou(self, resolver):
        """「部長」の除去"""
        assert resolver.remove_honorific("田中部長") == "田中"

    def test_no_honorific(self, resolver):
        """敬称なしの場合はそのまま"""
        assert resolver.remove_honorific("田中太郎") == "田中太郎"

    def test_empty_string(self, resolver):
        """空文字の場合"""
        assert resolver.remove_honorific("") == ""

    def test_none(self, resolver):
        """Noneの場合"""
        assert resolver.remove_honorific(None) is None


# =============================================================================
# 名前正規化テスト
# =============================================================================


class TestNameNormalization:
    """名前正規化テスト"""

    def test_normalize_with_honorific(self, resolver):
        """敬称付き名前の正規化"""
        assert resolver.normalize_name("田中太郎さん") == "田中太郎"

    def test_normalize_with_reading(self, resolver):
        """読み仮名付き名前の正規化"""
        assert resolver.normalize_name("高野　義浩 (タカノ ヨシヒロ)") == "高野義浩"

    def test_normalize_with_reading_fullwidth(self, resolver):
        """全角括弧の読み仮名付き名前の正規化"""
        assert resolver.normalize_name("高野義浩（タカノ ヨシヒロ）") == "高野義浩"

    def test_normalize_with_spaces(self, resolver):
        """スペース付き名前の正規化"""
        assert resolver.normalize_name("田中　太郎") == "田中太郎"

    def test_normalize_with_halfwidth_space(self, resolver):
        """半角スペース付き名前の正規化"""
        assert resolver.normalize_name("田中 太郎") == "田中太郎"

    def test_normalize_complex(self, resolver):
        """複合的な正規化"""
        assert resolver.normalize_name("田中　太郎さん (タナカ タロウ)") == "田中太郎"


# =============================================================================
# エイリアス生成テスト
# =============================================================================


class TestAliasGeneration:
    """エイリアス生成テスト"""

    def test_generate_basic_aliases(self, resolver):
        """基本的なエイリアス生成"""
        aliases = resolver.generate_aliases("田中")
        assert "田中" in aliases  # 本体
        assert "田中さん" in aliases
        assert "田中くん" in aliases
        assert "田中ちゃん" in aliases

    def test_generate_aliases_for_full_name(self, resolver):
        """フルネームのエイリアス生成（名字・名前分割）"""
        aliases = resolver.generate_aliases("田中太郎")
        assert "田中太郎" in aliases
        assert "田中太郎さん" in aliases
        assert "田中" in aliases  # 名字のみ
        assert "太郎" in aliases  # 名前のみ

    def test_generate_aliases_for_short_name(self, resolver):
        """短い名前のエイリアス生成（分割なし）"""
        aliases = resolver.generate_aliases("太郎")
        assert "太郎" in aliases
        assert "太郎さん" in aliases
        # 3文字以下は分割しない
        assert len([a for a in aliases if len(a) < 2]) == 0

    def test_generate_aliases_empty(self, resolver):
        """空文字のエイリアス生成"""
        aliases = resolver.generate_aliases("")
        assert aliases == []


# =============================================================================
# resolve() テスト
# =============================================================================


class TestResolve:
    """resolve()メソッドのテスト"""

    @pytest.mark.asyncio
    async def test_resolve_exact_match(self, resolver):
        """完全一致での解決"""
        result = await resolver.resolve("田中太郎")

        assert result.resolved_to == "田中太郎"
        assert result.confidence == 1.0
        assert result.needs_confirmation is False
        assert result.match_type == MatchType.EXACT

    @pytest.mark.asyncio
    async def test_resolve_with_honorific(self, resolver):
        """敬称付きでの解決"""
        result = await resolver.resolve("田中太郎さん")

        assert result.resolved_to == "田中太郎"
        assert result.match_type == MatchType.NORMALIZED
        assert result.needs_confirmation is False

    @pytest.mark.asyncio
    async def test_resolve_partial_match(self, resolver):
        """部分一致での解決（名字のみ）"""
        result = await resolver.resolve("田中")

        # 田中太郎が候補になる
        assert len(result.candidates) >= 1
        assert any(c.name == "田中太郎" for c in result.candidates)

    @pytest.mark.asyncio
    async def test_resolve_multiple_candidates(self):
        """複数候補がある場合は確認必要"""
        # 同じ名字の人物が複数いる場合
        resolver = PersonAliasResolver(
            known_persons=["田中太郎", "田中花子", "田中次郎"],
        )

        result = await resolver.resolve("田中")

        assert result.needs_confirmation is True
        assert len(result.candidates) >= 2

    @pytest.mark.asyncio
    async def test_resolve_no_match(self):
        """マッチなしの場合"""
        resolver = PersonAliasResolver(
            known_persons=["田中太郎"],
        )

        result = await resolver.resolve("鈴木")

        assert result.resolved_to is None
        assert result.needs_confirmation is True

    @pytest.mark.asyncio
    async def test_resolve_empty_input(self, resolver):
        """空入力の場合"""
        result = await resolver.resolve("")

        assert result.resolved_to is None
        assert result.needs_confirmation is True

    @pytest.mark.asyncio
    async def test_resolve_whitespace_input(self, resolver):
        """空白のみの入力"""
        result = await resolver.resolve("   ")

        assert result.resolved_to is None
        assert result.needs_confirmation is True


# =============================================================================
# 確認モードテスト
# =============================================================================


class TestConfirmationMode:
    """確認モードテスト"""

    @pytest.mark.asyncio
    async def test_confirmation_threshold_applied(self):
        """確認閾値が適用される"""
        assert CONFIRMATION_THRESHOLD == 0.7
        resolver = PersonAliasResolver()
        assert resolver.CONFIRMATION_THRESHOLD == 0.7

    @pytest.mark.asyncio
    async def test_high_confidence_no_confirmation(self, resolver):
        """高確信度では確認不要"""
        result = await resolver.resolve("田中太郎")

        assert result.confidence == 1.0
        assert result.needs_confirmation is False

    @pytest.mark.asyncio
    async def test_low_confidence_needs_confirmation(self):
        """低確信度では確認必要"""
        resolver = PersonAliasResolver(
            known_persons=["田中太郎"],
        )

        result = await resolver.resolve("田中太")  # 部分一致

        assert result.confidence < 0.7
        assert result.needs_confirmation is True


# =============================================================================
# 同期版テスト
# =============================================================================


class TestSyncResolve:
    """同期版resolve_syncのテスト"""

    def test_resolve_sync(self, resolver):
        """同期版のresolve"""
        result = resolver.resolve_sync("田中太郎さん")

        assert isinstance(result, PersonResolutionResult)
        assert result.resolved_to == "田中太郎"


# =============================================================================
# ファクトリー関数テスト
# =============================================================================


class TestFactoryFunction:
    """ファクトリー関数テスト"""

    def test_create_resolver(self):
        """ファクトリー関数でResolverを作成"""
        resolver = create_person_alias_resolver(
            known_persons=["田中太郎"],
        )

        assert isinstance(resolver, PersonAliasResolver)

    @pytest.mark.asyncio
    async def test_resolver_from_factory_works(self):
        """ファクトリーで作成したResolverが動作する"""
        resolver = create_person_alias_resolver(
            known_persons=["田中太郎", "山田花子"],
        )

        result = await resolver.resolve("田中さん")
        assert result.resolved_to == "田中太郎"


# =============================================================================
# PersonServiceAdapter テスト
# =============================================================================


class TestPersonServiceAdapter:
    """PersonServiceAdapterのテスト"""

    def test_adapter_creation(self):
        """アダプターの作成"""
        # モックPersonServiceを作成
        class MockPersonService:
            def search_person_by_partial_name(self, name):
                return ["田中太郎"]

            def get_all_persons_summary(self):
                return [{"name": "田中太郎", "attributes": None}]

        adapter = PersonServiceAdapter(MockPersonService())
        assert adapter.search_by_name("田中") == ["田中太郎"]
        assert adapter.get_all_names() == ["田中太郎"]

    def test_adapter_caching(self):
        """アダプターのキャッシュ機能"""
        call_count = 0

        class MockPersonService:
            def get_all_persons_summary(self_inner):
                nonlocal call_count
                call_count += 1
                return [{"name": "田中太郎", "attributes": None}]

        adapter = PersonServiceAdapter(MockPersonService())

        # 1回目の呼び出し
        adapter.get_all_names()
        assert call_count == 1

        # 2回目の呼び出し（キャッシュを使用）
        adapter.get_all_names()
        assert call_count == 1  # 増えない

        # キャッシュクリア後
        adapter.clear_cache()
        adapter.get_all_names()
        assert call_count == 2
