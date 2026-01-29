# tests/test_truth_resolver.py
"""
TruthResolver のテスト

CLAUDE.md セクション3で定義されたデータソース優先順位に基づいた
データ取得リゾルバーの検証
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from lib.brain.truth_resolver import (
    TruthResolver,
    create_truth_resolver,
    GuessNotAllowedError,
    TruthResolverError,
)
from lib.brain.constants import (
    TruthSource,
    TruthSourceResult,
    TruthSourceConfig,
    QUERY_TYPE_SOURCE_MAP,
    FEATURE_FLAG_TRUTH_RESOLVER,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_chatwork_client():
    """モックChatWorkクライアント"""
    client = MagicMock()
    client.get_contacts = AsyncMock(return_value=[
        {"account_id": "1", "name": "田中"},
        {"account_id": "2", "name": "山田"},
    ])
    client.get_room_members = AsyncMock(return_value=[
        {"account_id": "1", "name": "田中"},
    ])
    client.get_my_tasks = AsyncMock(return_value=[
        {"task_id": "100", "body": "タスク1"},
    ])
    return client


@pytest.fixture
def mock_db_accessor():
    """モックDBアクセサー"""
    accessor = MagicMock()
    accessor.get_user_profile = AsyncMock(return_value={
        "user_id": "123",
        "name": "田中崇樹",
        "department": "開発部",
    })
    accessor.get_task_history = AsyncMock(return_value=[
        {"task_id": "1", "body": "過去のタスク"},
    ])
    accessor.get_person_info = AsyncMock(return_value={
        "name": "田中崇樹",
        "position": "エンジニア",
    })
    return accessor


@pytest.fixture
def mock_memory_accessor():
    """モックMemoryアクセサー"""
    accessor = MagicMock()
    accessor.get_user_preferences = AsyncMock(return_value={
        "favorite_food": "寿司",
        "communication_style": "casual",
    })
    accessor.get_conversation_context = AsyncMock(return_value={
        "recent_topics": ["タスク管理", "目標設定"],
    })
    return accessor


@pytest.fixture
def resolver(mock_chatwork_client, mock_db_accessor, mock_memory_accessor):
    """テスト用のTruthResolver"""
    return TruthResolver(
        org_id="org_test",
        api_clients={"chatwork": mock_chatwork_client},
        db_accessor=mock_db_accessor,
        memory_accessor=mock_memory_accessor,
        feature_flags={FEATURE_FLAG_TRUTH_RESOLVER: True},
    )


@pytest.fixture
def resolver_no_api(mock_db_accessor, mock_memory_accessor):
    """APIなしのTruthResolver"""
    return TruthResolver(
        org_id="org_test",
        api_clients={},
        db_accessor=mock_db_accessor,
        memory_accessor=mock_memory_accessor,
        feature_flags={FEATURE_FLAG_TRUTH_RESOLVER: True},
    )


# =============================================================================
# TruthResolver 基本テスト
# =============================================================================


class TestTruthResolverInit:
    """TruthResolver 初期化テスト"""

    def test_init_with_all_accessors(
        self, mock_chatwork_client, mock_db_accessor, mock_memory_accessor
    ):
        """全アクセサーで初期化"""
        resolver = TruthResolver(
            org_id="org_test",
            api_clients={"chatwork": mock_chatwork_client},
            db_accessor=mock_db_accessor,
            memory_accessor=mock_memory_accessor,
        )
        assert resolver.org_id == "org_test"
        assert "chatwork" in resolver._api_clients

    def test_init_with_no_accessors(self):
        """アクセサーなしで初期化"""
        resolver = TruthResolver(org_id="org_test")
        assert resolver.org_id == "org_test"
        assert resolver._api_clients == {}
        assert resolver._db_accessor is None

    def test_factory_function(self, mock_chatwork_client):
        """ファクトリー関数でのインスタンス作成"""
        resolver = create_truth_resolver(
            org_id="org_test",
            api_clients={"chatwork": mock_chatwork_client},
        )
        assert isinstance(resolver, TruthResolver)
        assert resolver.org_id == "org_test"


# =============================================================================
# Truth順位に基づく取得テスト
# =============================================================================


class TestTruthSourcePriority:
    """Truth順位に基づくデータ取得テスト"""

    @pytest.mark.asyncio
    async def test_api_first_for_dm_contacts(self, resolver, mock_chatwork_client):
        """
        「DMできる相手は誰？」→ 1位: API優先

        CLAUDE.md セクション3の適用例
        """
        result = await resolver.resolve("dm_contacts", {})

        assert result.source == TruthSource.REALTIME_API
        assert result.fallback_used is False
        assert len(result.data) == 2
        mock_chatwork_client.get_contacts.assert_called_once()

    @pytest.mark.asyncio
    async def test_db_first_for_user_profile(self, resolver, mock_db_accessor):
        """
        「ユーザープロファイル取得」→ 2位: DB優先
        """
        result = await resolver.resolve("user_profile", {"user_id": "123"})

        assert result.source == TruthSource.DATABASE
        assert result.fallback_used is False
        assert result.data["name"] == "田中崇樹"
        mock_db_accessor.get_user_profile.assert_called_once()

    @pytest.mark.asyncio
    async def test_memory_first_for_user_preference(self, resolver, mock_memory_accessor):
        """
        「ユーザーの好み取得」→ 4位: Memory優先
        """
        result = await resolver.resolve("user_preference", {"user_id": "123"})

        assert result.source == TruthSource.MEMORY
        assert result.fallback_used is False
        assert result.data["favorite_food"] == "寿司"
        mock_memory_accessor.get_user_preferences.assert_called_once()

    @pytest.mark.asyncio
    async def test_unknown_query_defaults_to_db(self, resolver, mock_db_accessor):
        """未知のクエリタイプはDB（2位）にデフォルト"""
        # DBアクセサーに汎用メソッドを追加
        mock_db_accessor.get_unknown_data = AsyncMock(return_value={"data": "test"})

        # 未知のクエリタイプの場合
        preferred = resolver._get_preferred_source("unknown_query_type")
        assert preferred == TruthSource.DATABASE


# =============================================================================
# フォールバックテスト
# =============================================================================


class TestFallbackBehavior:
    """フォールバック動作テスト"""

    @pytest.mark.asyncio
    async def test_fallback_to_db_when_api_fails(
        self, resolver, mock_chatwork_client, mock_db_accessor
    ):
        """API失敗時はDBにフォールバック"""
        # APIを失敗させる
        mock_chatwork_client.get_contacts.side_effect = Exception("API Error")

        # DBにフォールバック用データを設定
        mock_db_accessor.get_cached_contacts = AsyncMock(
            return_value=[{"account_id": "1", "name": "田中（キャッシュ）"}]
        )

        # カスタムフェッチャーを登録してDBフォールバックをテスト
        resolver.register_custom_fetcher(
            TruthSource.DATABASE,
            "dm_contacts",
            mock_db_accessor.get_cached_contacts,
        )

        result = await resolver.resolve("dm_contacts", {})

        assert result.source == TruthSource.DATABASE
        assert result.fallback_used is True
        assert result.original_source == TruthSource.REALTIME_API

    @pytest.mark.asyncio
    async def test_no_fallback_when_disabled(self, resolver, mock_chatwork_client):
        """フォールバック無効時は失敗で終了"""
        mock_chatwork_client.get_contacts.side_effect = Exception("API Error")

        with pytest.raises(GuessNotAllowedError):
            await resolver.resolve("dm_contacts", {}, allow_fallback=False)

    @pytest.mark.asyncio
    async def test_confidence_decreases_on_fallback(self, resolver, mock_chatwork_client, mock_db_accessor):
        """フォールバック時は確信度が下がる"""
        mock_chatwork_client.get_contacts.side_effect = Exception("API Error")
        mock_db_accessor.get_cached_contacts = AsyncMock(return_value=[])
        resolver.register_custom_fetcher(
            TruthSource.DATABASE,
            "dm_contacts",
            mock_db_accessor.get_cached_contacts,
        )

        result = await resolver.resolve("dm_contacts", {})

        # フォールバックした場合、確信度は1.0未満
        assert result.confidence < 1.0
        assert result.fallback_used is True


# =============================================================================
# 推測禁止テスト
# =============================================================================


class TestGuessNotAllowed:
    """推測禁止（5位禁止）テスト"""

    @pytest.mark.asyncio
    async def test_raises_when_all_sources_fail(self, resolver, mock_chatwork_client):
        """全ソース失敗時はGuessNotAllowedError"""
        # 全てのソースを失敗させる
        mock_chatwork_client.get_contacts.side_effect = Exception("API Error")
        resolver._db_accessor = None
        resolver._memory_accessor = None

        with pytest.raises(GuessNotAllowedError) as exc_info:
            await resolver.resolve("dm_contacts", {})

        assert exc_info.value.query_type == "dm_contacts"
        assert TruthSource.REALTIME_API in exc_info.value.attempted_sources

    @pytest.mark.asyncio
    async def test_error_message_mentions_guess_forbidden(self, resolver, mock_chatwork_client):
        """エラーメッセージに推測禁止が含まれる"""
        mock_chatwork_client.get_contacts.side_effect = Exception("API Error")
        resolver._db_accessor = None
        resolver._memory_accessor = None

        with pytest.raises(GuessNotAllowedError) as exc_info:
            await resolver.resolve("dm_contacts", {})

        error_msg = str(exc_info.value)
        assert "禁止" in error_msg or "推測" in error_msg


# =============================================================================
# 必須ソース指定テスト
# =============================================================================


class TestRequiredSource:
    """必須ソース指定テスト"""

    def test_required_source_overrides_default(self, resolver):
        """required_sourceが指定されたら推奨ソースがオーバーライドされる"""
        # 通常はAPI優先
        default_preferred = resolver._get_preferred_source("dm_contacts")
        assert default_preferred == TruthSource.REALTIME_API

        # required_sourceでDB強制
        overridden = resolver._get_preferred_source("dm_contacts", TruthSource.DATABASE)
        assert overridden == TruthSource.DATABASE

    @pytest.mark.asyncio
    async def test_max_source_level_limits_fallback(self, resolver, mock_chatwork_client):
        """max_source_levelでフォールバック範囲を制限"""
        mock_chatwork_client.get_contacts.side_effect = Exception("API Error")

        # DBまでしかフォールバックしない
        sources = resolver._build_source_list(
            TruthSource.REALTIME_API,
            max_source_level=TruthSource.DATABASE,
            allow_fallback=True,
        )

        assert TruthSource.REALTIME_API in sources
        assert TruthSource.DATABASE in sources
        assert TruthSource.SPECIFICATION not in sources
        assert TruthSource.MEMORY not in sources


# =============================================================================
# カスタムフェッチャーテスト
# =============================================================================


class TestCustomFetcher:
    """カスタムフェッチャーテスト"""

    @pytest.mark.asyncio
    async def test_register_custom_fetcher(self, resolver):
        """カスタムフェッチャーの登録と使用"""
        custom_data = {"custom": "data"}
        custom_fetcher = AsyncMock(return_value=custom_data)

        resolver.register_custom_fetcher(
            TruthSource.DATABASE,
            "custom_query",
            custom_fetcher,
        )

        # カスタムクエリを実行
        # 注: resolve()がカスタムフェッチャーを使うには
        # QUERY_TYPE_SOURCE_MAPにcustom_queryを追加するか、
        # required_sourceを指定する必要がある
        result = await resolver.resolve(
            "custom_query",
            {"param": "value"},
            required_source=TruthSource.DATABASE,
        )

        custom_fetcher.assert_called_once_with({"param": "value"})
        assert result.data == custom_data


# =============================================================================
# メタデータテスト
# =============================================================================


class TestResultMetadata:
    """結果メタデータテスト"""

    @pytest.mark.asyncio
    async def test_result_includes_timestamp(self, resolver, mock_chatwork_client):
        """結果にタイムスタンプが含まれる"""
        result = await resolver.resolve("dm_contacts", {})

        assert result.timestamp is not None
        # ISO形式であることを確認
        datetime.fromisoformat(result.timestamp)

    @pytest.mark.asyncio
    async def test_result_includes_query_type(self, resolver, mock_chatwork_client):
        """結果にクエリタイプが含まれる"""
        result = await resolver.resolve("dm_contacts", {})

        assert result.metadata["query_type"] == "dm_contacts"

    @pytest.mark.asyncio
    async def test_result_includes_elapsed_time(self, resolver, mock_chatwork_client):
        """結果に経過時間が含まれる"""
        result = await resolver.resolve("dm_contacts", {})

        assert "elapsed_ms" in result.metadata
        assert result.metadata["elapsed_ms"] >= 0


# =============================================================================
# Feature Flag テスト
# =============================================================================


class TestFeatureFlag:
    """Feature Flagテスト"""

    def test_is_enabled_returns_true_when_flag_set(self, resolver):
        """フラグ設定時はTrue"""
        assert resolver.is_enabled() is True

    def test_is_enabled_returns_false_by_default(self):
        """デフォルトはFalse"""
        resolver = TruthResolver(org_id="org_test")
        assert resolver.is_enabled() is False


# =============================================================================
# ソースリスト構築テスト
# =============================================================================


class TestBuildSourceList:
    """ソースリスト構築テスト"""

    def test_no_fallback_returns_single_source(self, resolver):
        """フォールバック無効時は単一ソース"""
        sources = resolver._build_source_list(
            TruthSource.REALTIME_API,
            max_source_level=None,
            allow_fallback=False,
        )
        assert sources == [TruthSource.REALTIME_API]

    def test_fallback_enabled_returns_multiple_sources(self, resolver):
        """フォールバック有効時は複数ソース"""
        sources = resolver._build_source_list(
            TruthSource.REALTIME_API,
            max_source_level=None,
            allow_fallback=True,
        )
        assert len(sources) == 4
        assert sources[0] == TruthSource.REALTIME_API
        assert sources[-1] == TruthSource.MEMORY

    def test_max_source_level_limits_list(self, resolver):
        """max_source_levelでリストを制限"""
        sources = resolver._build_source_list(
            TruthSource.REALTIME_API,
            max_source_level=TruthSource.DATABASE,
            allow_fallback=True,
        )
        assert TruthSource.REALTIME_API in sources
        assert TruthSource.DATABASE in sources
        assert TruthSource.SPECIFICATION not in sources


# =============================================================================
# 確信度計算テスト
# =============================================================================


class TestConfidenceCalculation:
    """確信度計算テスト"""

    def test_same_source_returns_full_confidence(self, resolver):
        """同じソースなら確信度1.0"""
        confidence = resolver._calculate_confidence(
            TruthSource.REALTIME_API,
            TruthSource.REALTIME_API,
        )
        assert confidence == 1.0

    def test_one_level_fallback_reduces_confidence(self, resolver):
        """1段階フォールバックで確信度低下"""
        confidence = resolver._calculate_confidence(
            TruthSource.DATABASE,  # actual
            TruthSource.REALTIME_API,  # preferred
        )
        assert 0.5 < confidence < 1.0

    def test_multiple_level_fallback_further_reduces(self, resolver):
        """複数段階フォールバックでさらに低下"""
        confidence_1 = resolver._calculate_confidence(
            TruthSource.DATABASE,  # 1段階
            TruthSource.REALTIME_API,
        )
        confidence_2 = resolver._calculate_confidence(
            TruthSource.MEMORY,  # 3段階
            TruthSource.REALTIME_API,
        )
        assert confidence_2 < confidence_1


# =============================================================================
# CLAUDE.md ユースケーステスト
# =============================================================================


class TestCLAUDEMDUseCases:
    """CLAUDE.md セクション3の適用例テスト"""

    @pytest.mark.asyncio
    async def test_dm_contacts_uses_api(self, resolver, mock_chatwork_client):
        """
        「DMできる相手は誰？」
        正しいデータソース: 1位: ChatWork API
        理由: 接続情報はAPIが持っている
        """
        result = await resolver.resolve("dm_contacts", {})
        assert result.source == TruthSource.REALTIME_API

    @pytest.mark.asyncio
    async def test_task_history_uses_db(self, resolver, mock_db_accessor):
        """
        「田中さんの今日のタスクは？」
        正しいデータソース: 2位: DB
        理由: タスクはDBに保存されている
        """
        result = await resolver.resolve("task_history", {"user_id": "123"})
        assert result.source == TruthSource.DATABASE

    @pytest.mark.asyncio
    async def test_user_preference_uses_memory(self, resolver, mock_memory_accessor):
        """
        「田中さんの好きな食べ物は？」
        正しいデータソース: 4位: Memory
        理由: 会話で覚えた情報
        """
        result = await resolver.resolve("user_preference", {"user_id": "123"})
        assert result.source == TruthSource.MEMORY

    @pytest.mark.asyncio
    async def test_guess_is_forbidden(self, resolver, mock_chatwork_client):
        """
        「たぶんこうだと思う」
        正しい対応: 禁止（GuessNotAllowedError）
        """
        # 全ソースを失敗させる
        mock_chatwork_client.get_contacts.side_effect = Exception("API Error")
        resolver._db_accessor = None
        resolver._memory_accessor = None

        with pytest.raises(GuessNotAllowedError):
            await resolver.resolve("dm_contacts", {})
