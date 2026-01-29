# tests/test_truth_source.py
"""
Truth順位（TruthSource）のテスト

CLAUDE.md セクション3で定義されたデータソース優先順位の検証
"""

import pytest
from lib.brain.constants import (
    TruthSource,
    TruthSourceResult,
    TruthSourceConfig,
    QUERY_TYPE_SOURCE_MAP,
    DEFAULT_TRUTH_SOURCE_CONFIGS,
    DEFAULT_FEATURE_FLAGS,
    FEATURE_FLAG_TRUTH_RESOLVER,
    FEATURE_FLAG_ENHANCED_PRONOUN,
    FEATURE_FLAG_PERSON_ALIAS,
    FEATURE_FLAG_CONTEXT_EXPRESSION,
)


class TestTruthSourceEnum:
    """TruthSource Enumのテスト"""

    def test_truth_source_values(self):
        """Truth順位の値が正しく定義されている"""
        assert TruthSource.REALTIME_API.value == 1
        assert TruthSource.DATABASE.value == 2
        assert TruthSource.SPECIFICATION.value == 3
        assert TruthSource.MEMORY.value == 4

    def test_truth_source_priority_order(self):
        """優先度順のリストが正しい"""
        order = TruthSource.get_priority_order()
        assert len(order) == 4
        assert order[0] == TruthSource.REALTIME_API
        assert order[1] == TruthSource.DATABASE
        assert order[2] == TruthSource.SPECIFICATION
        assert order[3] == TruthSource.MEMORY

    def test_truth_source_comparison(self):
        """TruthSourceの比較演算が正しく動作する"""
        # 1位 < 2位
        assert TruthSource.REALTIME_API < TruthSource.DATABASE
        # 2位 < 3位
        assert TruthSource.DATABASE < TruthSource.SPECIFICATION
        # 1位 <= 1位
        assert TruthSource.REALTIME_API <= TruthSource.REALTIME_API
        # 3位 <= 4位
        assert TruthSource.SPECIFICATION <= TruthSource.MEMORY

    def test_no_guess_source_defined(self):
        """5位: 推測は定義されていない（禁止）"""
        source_names = [s.name for s in TruthSource]
        assert "GUESS" not in source_names
        assert "INFERENCE" not in source_names
        assert "ESTIMATION" not in source_names

    def test_all_sources_have_unique_values(self):
        """全てのソースが一意の値を持つ"""
        values = [s.value for s in TruthSource]
        assert len(values) == len(set(values))


class TestTruthSourceResult:
    """TruthSourceResult データクラスのテスト"""

    def test_create_basic_result(self):
        """基本的な結果の作成"""
        result = TruthSourceResult(
            source=TruthSource.DATABASE,
            data={"name": "田中"},
            confidence=0.9,
        )
        assert result.source == TruthSource.DATABASE
        assert result.data == {"name": "田中"}
        assert result.confidence == 0.9
        assert result.fallback_used is False

    def test_result_with_fallback(self):
        """フォールバック使用時の結果"""
        result = TruthSourceResult(
            source=TruthSource.DATABASE,
            data=["user1", "user2"],
            confidence=0.7,
            fallback_used=True,
            original_source=TruthSource.REALTIME_API,
        )
        assert result.fallback_used is True
        assert result.original_source == TruthSource.REALTIME_API
        assert result.is_from_preferred_source() is False

    def test_result_from_preferred_source(self):
        """推奨ソースからの取得判定"""
        # フォールバック未使用
        result1 = TruthSourceResult(
            source=TruthSource.REALTIME_API,
            data={},
        )
        assert result1.is_from_preferred_source() is True

        # フォールバック使用
        result2 = TruthSourceResult(
            source=TruthSource.DATABASE,
            data={},
            fallback_used=True,
        )
        assert result2.is_from_preferred_source() is False

    def test_result_with_metadata(self):
        """メタデータ付きの結果"""
        result = TruthSourceResult(
            source=TruthSource.REALTIME_API,
            data={"contacts": []},
            metadata={"api_version": "v2", "rate_limit_remaining": 100},
        )
        assert result.metadata["api_version"] == "v2"
        assert result.metadata["rate_limit_remaining"] == 100


class TestTruthSourceConfig:
    """TruthSourceConfig データクラスのテスト"""

    def test_create_default_config(self):
        """デフォルト値での設定作成"""
        config = TruthSourceConfig(source=TruthSource.DATABASE)
        assert config.source == TruthSource.DATABASE
        assert config.enabled is True
        assert config.timeout_seconds == 5.0
        assert config.retry_count == 2
        assert config.fallback_allowed is True
        assert config.cache_ttl_seconds == 0

    def test_create_custom_config(self):
        """カスタム値での設定作成"""
        config = TruthSourceConfig(
            source=TruthSource.REALTIME_API,
            enabled=True,
            timeout_seconds=3.0,
            retry_count=1,
            fallback_allowed=True,
            cache_ttl_seconds=60,
        )
        assert config.timeout_seconds == 3.0
        assert config.retry_count == 1
        assert config.cache_ttl_seconds == 60


class TestQueryTypeSourceMap:
    """QUERY_TYPE_SOURCE_MAP のテスト"""

    def test_api_priority_queries(self):
        """API優先のクエリタイプ"""
        api_priority_types = [
            "dm_contacts",
            "room_members",
            "current_tasks",
            "user_status",
            "unread_messages",
        ]
        for query_type in api_priority_types:
            assert query_type in QUERY_TYPE_SOURCE_MAP
            assert QUERY_TYPE_SOURCE_MAP[query_type] == TruthSource.REALTIME_API

    def test_db_priority_queries(self):
        """DB優先のクエリタイプ"""
        db_priority_types = [
            "user_profile",
            "task_history",
            "organization_info",
            "person_info",
            "goal_info",
            "knowledge_base",
        ]
        for query_type in db_priority_types:
            assert query_type in QUERY_TYPE_SOURCE_MAP
            assert QUERY_TYPE_SOURCE_MAP[query_type] == TruthSource.DATABASE

    def test_spec_priority_queries(self):
        """設計書優先のクエリタイプ"""
        spec_priority_types = [
            "system_spec",
            "feature_definition",
            "api_reference",
        ]
        for query_type in spec_priority_types:
            assert query_type in QUERY_TYPE_SOURCE_MAP
            assert QUERY_TYPE_SOURCE_MAP[query_type] == TruthSource.SPECIFICATION

    def test_memory_priority_queries(self):
        """Memory優先のクエリタイプ"""
        memory_priority_types = [
            "user_preference",
            "conversation_context",
            "recent_topic",
            "user_mood",
        ]
        for query_type in memory_priority_types:
            assert query_type in QUERY_TYPE_SOURCE_MAP
            assert QUERY_TYPE_SOURCE_MAP[query_type] == TruthSource.MEMORY

    def test_all_sources_are_valid(self):
        """全てのマッピング値が有効なTruthSource"""
        for query_type, source in QUERY_TYPE_SOURCE_MAP.items():
            assert isinstance(source, TruthSource), f"{query_type}の値が無効"

    def test_dm_contacts_uses_api(self):
        """DMできる相手のクエリはAPI優先（CLAUDE.md適用例）"""
        # CLAUDE.md セクション3の適用例:
        # 「DMできる相手は誰？」→ 1位: ChatWork API
        assert QUERY_TYPE_SOURCE_MAP["dm_contacts"] == TruthSource.REALTIME_API


class TestDefaultTruthSourceConfigs:
    """DEFAULT_TRUTH_SOURCE_CONFIGS のテスト"""

    def test_all_sources_have_config(self):
        """全てのTruthSourceに設定がある"""
        for source in TruthSource:
            assert source in DEFAULT_TRUTH_SOURCE_CONFIGS

    def test_api_config(self):
        """API設定の検証"""
        config = DEFAULT_TRUTH_SOURCE_CONFIGS[TruthSource.REALTIME_API]
        assert config.enabled is True
        assert config.timeout_seconds == 5.0
        assert config.fallback_allowed is True
        assert config.cache_ttl_seconds == 60  # 1分キャッシュ

    def test_db_config(self):
        """DB設定の検証"""
        config = DEFAULT_TRUTH_SOURCE_CONFIGS[TruthSource.DATABASE]
        assert config.enabled is True
        assert config.timeout_seconds == 10.0
        assert config.retry_count == 3
        assert config.cache_ttl_seconds == 300  # 5分キャッシュ

    def test_specification_config(self):
        """設計書設定の検証（フォールバック不可）"""
        config = DEFAULT_TRUTH_SOURCE_CONFIGS[TruthSource.SPECIFICATION]
        assert config.fallback_allowed is False  # 仕様書は代替不可

    def test_memory_config(self):
        """Memory設定の検証（キャッシュなし）"""
        config = DEFAULT_TRUTH_SOURCE_CONFIGS[TruthSource.MEMORY]
        assert config.fallback_allowed is False  # 最終手段
        assert config.cache_ttl_seconds == 0  # キャッシュなし


class TestFeatureFlags:
    """Feature Flags のテスト"""

    def test_feature_flag_names(self):
        """Feature Flag名が正しく定義されている"""
        assert FEATURE_FLAG_TRUTH_RESOLVER == "truth_resolver_enabled"
        assert FEATURE_FLAG_ENHANCED_PRONOUN == "enhanced_pronoun_resolver"
        assert FEATURE_FLAG_PERSON_ALIAS == "person_alias_resolver"
        assert FEATURE_FLAG_CONTEXT_EXPRESSION == "context_expression_resolver"

    def test_default_feature_flags_exist(self):
        """デフォルトのFeature Flagsが存在する"""
        assert FEATURE_FLAG_TRUTH_RESOLVER in DEFAULT_FEATURE_FLAGS
        assert FEATURE_FLAG_ENHANCED_PRONOUN in DEFAULT_FEATURE_FLAGS
        assert FEATURE_FLAG_PERSON_ALIAS in DEFAULT_FEATURE_FLAGS
        assert FEATURE_FLAG_CONTEXT_EXPRESSION in DEFAULT_FEATURE_FLAGS

    def test_default_feature_flags_are_false(self):
        """デフォルトでは全てのFeature Flagsが無効"""
        for flag_name, flag_value in DEFAULT_FEATURE_FLAGS.items():
            assert flag_value is False, f"{flag_name}はデフォルトで無効であるべき"


class TestTruthSourceUseCases:
    """Truth順位のユースケーステスト（CLAUDE.md セクション3の適用例）"""

    def test_dm_contacts_scenario(self):
        """
        ユースケース: 「DMできる相手は誰？」
        正しいデータソース: 1位: ChatWork API
        理由: 接続情報はAPIが持っている
        """
        query_type = "dm_contacts"
        expected_source = TruthSource.REALTIME_API
        assert QUERY_TYPE_SOURCE_MAP[query_type] == expected_source

    def test_user_tasks_scenario(self):
        """
        ユースケース: 「田中さんの今日のタスクは？」
        正しいデータソース: 2位: DB
        理由: タスクはDBに保存されている
        """
        query_type = "task_history"
        expected_source = TruthSource.DATABASE
        assert QUERY_TYPE_SOURCE_MAP[query_type] == expected_source

    def test_user_preference_scenario(self):
        """
        ユースケース: 「田中さんの好きな食べ物は？」
        正しいデータソース: 4位: Memory
        理由: 会話で覚えた情報
        """
        query_type = "user_preference"
        expected_source = TruthSource.MEMORY
        assert QUERY_TYPE_SOURCE_MAP[query_type] == expected_source

    def test_guess_is_forbidden(self):
        """
        ユースケース: 「たぶんこうだと思う」
        正しい対応: 5位: 禁止（推測はせず、確認を取る）
        """
        # 推測用のTruthSourceが存在しないことを確認
        source_values = [s.value for s in TruthSource]
        assert 5 not in source_values  # 5位は存在しない
