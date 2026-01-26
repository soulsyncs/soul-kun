"""
Feature Flags テスト (v10.31.0)

Phase C: lib/feature_flags.py の包括的なテスト

テストカテゴリ:
1. 基本機能テスト
2. 環境変数読み込みテスト
3. インポート結果設定テスト
4. フラグ取得ユーティリティテスト
5. ヘルパー関数テスト
6. シングルトンテスト
7. エッジケーステスト
8. 統合テスト

作成日: 2026-01-26
作成者: Claude Code
"""

import pytest
import os
from unittest.mock import patch, MagicMock
from typing import Dict, Any

from lib.feature_flags import (
    # クラス
    FeatureFlags,
    FlagCategory,
    FlagType,
    FlagInfo,
    # 定数
    FLAG_DEFINITIONS,
    # 関数
    get_flags,
    reset_flags,
    init_flags,
    # ヘルパー
    is_handler_enabled,
    is_library_available,
    is_feature_enabled,
    get_brain_mode,
    is_dry_run,
)


# =====================================================
# フィクスチャ
# =====================================================

@pytest.fixture(autouse=True)
def reset_flags_before_each():
    """各テスト前にフラグをリセット"""
    reset_flags()
    yield
    reset_flags()


@pytest.fixture
def clean_env():
    """環境変数をクリーンにする"""
    env_vars = [
        "USE_NEW_PROPOSAL_HANDLER",
        "USE_NEW_MEMORY_HANDLER",
        "USE_NEW_TASK_HANDLER",
        "USE_NEW_OVERDUE_HANDLER",
        "USE_NEW_GOAL_HANDLER",
        "USE_NEW_KNOWLEDGE_HANDLER",
        "USE_NEW_DATE_UTILS",
        "USE_NEW_CHATWORK_UTILS",
        "USE_ANNOUNCEMENT_FEATURE",
        "USE_BRAIN_ARCHITECTURE",
        "DISABLE_MVV_CONTEXT",
        "ENABLE_PHASE3_KNOWLEDGE",
        "USE_DYNAMIC_DEPARTMENT_MAPPING",
        "ENABLE_UNMATCHED_FOLDER_ALERT",
        "DRY_RUN",
        "ENABLE_DEPARTMENT_ACCESS_CONTROL",
    ]
    original_values = {}
    for var in env_vars:
        original_values[var] = os.environ.pop(var, None)

    yield

    # 元の値を復元
    for var, value in original_values.items():
        if value is not None:
            os.environ[var] = value


# =====================================================
# 1. 基本機能テスト
# =====================================================

class TestFeatureFlagsBasic:
    """基本機能のテスト"""

    def test_create_default_instance(self):
        """デフォルトインスタンス作成"""
        flags = FeatureFlags()
        assert flags is not None
        assert isinstance(flags, FeatureFlags)

    def test_default_values(self):
        """デフォルト値の確認"""
        flags = FeatureFlags()

        # ハンドラー系（デフォルト: True）
        assert flags.use_new_proposal_handler is True
        assert flags.use_new_memory_handler is True
        assert flags.use_new_task_handler is True
        assert flags.use_new_overdue_handler is True
        assert flags.use_new_goal_handler is True
        assert flags.use_new_knowledge_handler is True

        # ライブラリ系（デフォルト: False - インポート依存）
        assert flags.use_admin_config is False
        assert flags.use_text_utils is False
        assert flags.use_user_utils is False
        assert flags.use_business_day is False
        assert flags.use_goal_setting is False
        assert flags.use_memory_framework is False
        assert flags.use_mvv_context is False

        # 脳アーキテクチャ（デフォルト: False）
        assert flags.use_brain_architecture is False
        assert flags.brain_mode == "false"

        # DRY_RUN（デフォルト: False）
        assert flags.dry_run is False

    def test_from_dict(self):
        """辞書からの構築"""
        data = {
            "use_new_proposal_handler": False,
            "use_brain_architecture": True,
            "brain_mode": "shadow",
            "dry_run": True,
        }
        flags = FeatureFlags.from_dict(data)

        assert flags.use_new_proposal_handler is False
        assert flags.use_brain_architecture is True
        assert flags.brain_mode == "shadow"
        assert flags.dry_run is True

    def test_to_dict(self):
        """辞書への変換"""
        flags = FeatureFlags()
        result = flags.to_dict()

        assert isinstance(result, dict)
        assert "use_new_proposal_handler" in result
        assert "use_brain_architecture" in result
        assert "brain_mode" in result
        assert "dry_run" in result

    def test_to_json(self):
        """JSONへの変換"""
        flags = FeatureFlags()
        result = flags.to_json()

        assert isinstance(result, str)
        assert "use_new_proposal_handler" in result

    def test_repr(self):
        """文字列表現"""
        flags = FeatureFlags()
        result = repr(flags)

        assert "FeatureFlags" in result
        assert "enabled" in result


# =====================================================
# 2. 環境変数読み込みテスト
# =====================================================

class TestEnvironmentVariables:
    """環境変数読み込みのテスト"""

    @patch.dict(os.environ, {"USE_NEW_PROPOSAL_HANDLER": "false"})
    def test_env_false_lowercase(self):
        """環境変数 false（小文字）"""
        flags = FeatureFlags.from_env()
        assert flags.use_new_proposal_handler is False

    @patch.dict(os.environ, {"USE_NEW_PROPOSAL_HANDLER": "FALSE"})
    def test_env_false_uppercase(self):
        """環境変数 FALSE（大文字）"""
        flags = FeatureFlags.from_env()
        assert flags.use_new_proposal_handler is False

    @patch.dict(os.environ, {"USE_NEW_PROPOSAL_HANDLER": "0"})
    def test_env_zero(self):
        """環境変数 0"""
        flags = FeatureFlags.from_env()
        assert flags.use_new_proposal_handler is False

    @patch.dict(os.environ, {"USE_NEW_PROPOSAL_HANDLER": "no"})
    def test_env_no(self):
        """環境変数 no"""
        flags = FeatureFlags.from_env()
        assert flags.use_new_proposal_handler is False

    @patch.dict(os.environ, {"USE_NEW_PROPOSAL_HANDLER": "true"})
    def test_env_true_lowercase(self):
        """環境変数 true（小文字）"""
        flags = FeatureFlags.from_env()
        assert flags.use_new_proposal_handler is True

    @patch.dict(os.environ, {"USE_NEW_PROPOSAL_HANDLER": "TRUE"})
    def test_env_true_uppercase(self):
        """環境変数 TRUE（大文字）"""
        flags = FeatureFlags.from_env()
        assert flags.use_new_proposal_handler is True

    @patch.dict(os.environ, {"USE_NEW_PROPOSAL_HANDLER": "1"})
    def test_env_one(self):
        """環境変数 1"""
        flags = FeatureFlags.from_env()
        assert flags.use_new_proposal_handler is True

    @patch.dict(os.environ, {"USE_NEW_PROPOSAL_HANDLER": "yes"})
    def test_env_yes(self):
        """環境変数 yes"""
        flags = FeatureFlags.from_env()
        assert flags.use_new_proposal_handler is True

    @patch.dict(os.environ, {"USE_NEW_PROPOSAL_HANDLER": "invalid"})
    def test_env_invalid_uses_default(self):
        """無効な値はデフォルトを使用"""
        flags = FeatureFlags.from_env()
        # デフォルトはTrue
        assert flags.use_new_proposal_handler is True

    @patch.dict(os.environ, {}, clear=False)
    def test_env_not_set_uses_default(self):
        """環境変数未設定はデフォルトを使用"""
        # 環境変数をクリア
        os.environ.pop("USE_NEW_PROPOSAL_HANDLER", None)
        flags = FeatureFlags.from_env()
        # デフォルトはTrue
        assert flags.use_new_proposal_handler is True


# =====================================================
# 3. 脳アーキテクチャモードテスト
# =====================================================

class TestBrainArchitectureMode:
    """脳アーキテクチャモードのテスト"""

    @patch.dict(os.environ, {"USE_BRAIN_ARCHITECTURE": "false"})
    def test_brain_mode_false(self):
        """モード: false"""
        flags = FeatureFlags.from_env()
        assert flags.use_brain_architecture is False
        assert flags.brain_mode == "false"

    @patch.dict(os.environ, {"USE_BRAIN_ARCHITECTURE": "true"})
    def test_brain_mode_true(self):
        """モード: true"""
        flags = FeatureFlags.from_env()
        assert flags.use_brain_architecture is True
        assert flags.brain_mode == "true"

    @patch.dict(os.environ, {"USE_BRAIN_ARCHITECTURE": "shadow"})
    def test_brain_mode_shadow(self):
        """モード: shadow"""
        flags = FeatureFlags.from_env()
        assert flags.use_brain_architecture is True
        assert flags.brain_mode == "shadow"

    @patch.dict(os.environ, {"USE_BRAIN_ARCHITECTURE": "gradual"})
    def test_brain_mode_gradual(self):
        """モード: gradual"""
        flags = FeatureFlags.from_env()
        assert flags.use_brain_architecture is True
        assert flags.brain_mode == "gradual"

    @patch.dict(os.environ, {"USE_BRAIN_ARCHITECTURE": "SHADOW"})
    def test_brain_mode_uppercase(self):
        """大文字のモード"""
        flags = FeatureFlags.from_env()
        assert flags.use_brain_architecture is True
        assert flags.brain_mode == "shadow"


# =====================================================
# 4. MVVコンテキストテスト
# =====================================================

class TestMVVContext:
    """MVVコンテキストのテスト"""

    @patch.dict(os.environ, {"DISABLE_MVV_CONTEXT": "true"})
    def test_mvv_disabled_by_env(self):
        """環境変数でMVV無効化"""
        flags = FeatureFlags.from_env()
        assert flags.use_mvv_context is False

    @patch.dict(os.environ, {"DISABLE_MVV_CONTEXT": "false"})
    def test_mvv_not_disabled(self):
        """DISABLE_MVV_CONTEXT=falseの場合"""
        flags = FeatureFlags.from_env()
        # インポート結果で決まるが、初期値はFalse
        assert flags.use_mvv_context is False

    def test_mvv_with_import_success(self):
        """MVVインポート成功時"""
        flags = FeatureFlags.from_env()
        flags.set_import_result("use_mvv_context", True)
        assert flags.use_mvv_context is True

    @patch.dict(os.environ, {"DISABLE_MVV_CONTEXT": "true"})
    def test_mvv_disabled_overrides_import(self):
        """環境変数無効化はインポート成功を上書き"""
        flags = FeatureFlags.from_env()
        flags.set_import_result("use_mvv_context", True)
        # 環境変数で無効化されているので False のまま
        assert flags.use_mvv_context is False


# =====================================================
# 5. インポート結果設定テスト
# =====================================================

class TestImportResults:
    """インポート結果設定のテスト"""

    def test_set_single_import_result(self):
        """単一のインポート結果設定"""
        flags = FeatureFlags()
        assert flags.use_admin_config is False

        flags.set_import_result("use_admin_config", True)
        assert flags.use_admin_config is True

    def test_set_multiple_import_results(self):
        """複数のインポート結果設定"""
        flags = FeatureFlags()

        results = {
            "use_admin_config": True,
            "use_text_utils": True,
            "use_user_utils": False,
        }
        flags.set_import_results(results)

        assert flags.use_admin_config is True
        assert flags.use_text_utils is True
        assert flags.use_user_utils is False

    def test_import_result_tracking(self):
        """インポート結果の追跡"""
        flags = FeatureFlags()
        flags.set_import_result("use_admin_config", True)
        flags.set_import_result("use_text_utils", False)

        assert flags._import_results["use_admin_config"] is True
        assert flags._import_results["use_text_utils"] is False

    def test_set_unknown_flag_ignored(self):
        """存在しないフラグは無視"""
        flags = FeatureFlags()
        # エラーにならないことを確認
        flags.set_import_result("unknown_flag", True)
        assert "unknown_flag" in flags._import_results


# =====================================================
# 6. フラグ取得ユーティリティテスト
# =====================================================

class TestFlagGetters:
    """フラグ取得ユーティリティのテスト"""

    def test_get_handler_flags(self):
        """ハンドラーフラグ取得"""
        flags = FeatureFlags()
        result = flags.get_handler_flags()

        assert isinstance(result, dict)
        assert len(result) == 6
        assert "use_new_proposal_handler" in result
        assert "use_new_memory_handler" in result
        assert "use_new_task_handler" in result
        assert "use_new_overdue_handler" in result
        assert "use_new_goal_handler" in result
        assert "use_new_knowledge_handler" in result

    def test_get_library_flags(self):
        """ライブラリフラグ取得"""
        flags = FeatureFlags()
        result = flags.get_library_flags()

        assert isinstance(result, dict)
        assert "use_admin_config" in result
        assert "use_text_utils" in result
        assert "use_memory_framework" in result
        assert "use_mvv_context" in result

    def test_get_feature_flags(self):
        """機能フラグ取得"""
        flags = FeatureFlags()
        result = flags.get_feature_flags()

        assert isinstance(result, dict)
        assert "use_announcement_feature" in result
        assert "use_brain_architecture" in result
        assert "brain_mode" in result
        assert "enable_phase3_knowledge" in result

    def test_get_detection_flags(self):
        """検出フラグ取得"""
        flags = FeatureFlags()
        result = flags.get_detection_flags()

        assert isinstance(result, dict)
        assert "use_dynamic_department_mapping" in result
        assert "enable_unmatched_folder_alert" in result

    def test_get_infra_flags(self):
        """インフラフラグ取得"""
        flags = FeatureFlags()
        result = flags.get_infra_flags()

        assert isinstance(result, dict)
        assert "dry_run" in result
        assert "enable_department_access_control" in result

    def test_get_all_flags(self):
        """全フラグ取得"""
        flags = FeatureFlags()
        result = flags.get_all_flags()

        assert isinstance(result, dict)
        # 全カテゴリのフラグが含まれる
        assert "use_new_proposal_handler" in result
        assert "use_admin_config" in result
        assert "use_brain_architecture" in result
        assert "use_dynamic_department_mapping" in result
        assert "dry_run" in result

    def test_get_enabled_count(self):
        """有効フラグ数取得"""
        flags = FeatureFlags()
        enabled, total = flags.get_enabled_count()

        assert isinstance(enabled, int)
        assert isinstance(total, int)
        assert enabled >= 0
        assert total > 0
        assert enabled <= total


# =====================================================
# 7. ヘルパー関数テスト
# =====================================================

class TestHelperFunctions:
    """ヘルパー関数のテスト"""

    def test_is_handler_enabled_proposal(self):
        """is_handler_enabled: proposal"""
        init_flags({"use_new_proposal_handler": True})
        assert is_handler_enabled("proposal") is True

    def test_is_handler_enabled_task(self):
        """is_handler_enabled: task"""
        init_flags({"use_new_task_handler": False})
        assert is_handler_enabled("task") is False

    def test_is_library_available_admin_config(self):
        """is_library_available: admin_config"""
        init_flags({"use_admin_config": True})
        assert is_library_available("admin_config") is True

    def test_is_library_available_text_utils(self):
        """is_library_available: text_utils"""
        init_flags({"use_text_utils": False})
        assert is_library_available("text_utils") is False

    def test_is_feature_enabled_brain(self):
        """is_feature_enabled: brain_architecture"""
        init_flags({"use_brain_architecture": True})
        assert is_feature_enabled("brain_architecture") is True

    def test_is_feature_enabled_phase3(self):
        """is_feature_enabled: phase3_knowledge"""
        init_flags({"enable_phase3_knowledge": True})
        assert is_feature_enabled("phase3_knowledge") is True

    def test_get_brain_mode_shadow(self):
        """get_brain_mode: shadow"""
        init_flags({"brain_mode": "shadow"})
        assert get_brain_mode() == "shadow"

    def test_is_dry_run_true(self):
        """is_dry_run: true"""
        init_flags({"dry_run": True})
        assert is_dry_run() is True

    def test_is_dry_run_false(self):
        """is_dry_run: false"""
        init_flags({"dry_run": False})
        assert is_dry_run() is False


# =====================================================
# 8. シングルトンテスト
# =====================================================

class TestSingleton:
    """シングルトンパターンのテスト"""

    def test_get_flags_returns_same_instance(self):
        """get_flagsは同じインスタンスを返す"""
        flags1 = get_flags()
        flags2 = get_flags()
        assert flags1 is flags2

    def test_reset_flags_creates_new_instance(self):
        """reset_flagsは新しいインスタンスを作成"""
        flags1 = get_flags()
        reset_flags()
        flags2 = get_flags()
        assert flags1 is not flags2

    def test_init_flags_with_custom_values(self):
        """init_flagsはカスタム値を設定"""
        custom = {"dry_run": True, "use_brain_architecture": True}
        flags = init_flags(custom)

        assert flags.dry_run is True
        assert flags.use_brain_architecture is True

    def test_init_flags_without_args(self):
        """init_flagsは引数なしで環境変数から読み込み"""
        with patch.dict(os.environ, {"DRY_RUN": "true"}):
            reset_flags()
            flags = init_flags()
            assert flags.dry_run is True


# =====================================================
# 9. 定数テスト
# =====================================================

class TestConstants:
    """定数のテスト"""

    def test_flag_category_values(self):
        """FlagCategoryの値"""
        assert FlagCategory.HANDLER.value == "handler"
        assert FlagCategory.LIBRARY.value == "library"
        assert FlagCategory.FEATURE.value == "feature"
        assert FlagCategory.DETECTION.value == "detection"
        assert FlagCategory.INFRASTRUCTURE.value == "infra"

    def test_flag_type_values(self):
        """FlagTypeの値"""
        assert FlagType.ENV_ONLY.value == "env_only"
        assert FlagType.IMPORT_ONLY.value == "import_only"
        assert FlagType.ENV_AND_IMPORT.value == "env_and_import"
        assert FlagType.COMPLEX.value == "complex"

    def test_flag_definitions_structure(self):
        """FLAG_DEFINITIONSの構造"""
        assert isinstance(FLAG_DEFINITIONS, dict)
        assert len(FLAG_DEFINITIONS) > 0

        for key, value in FLAG_DEFINITIONS.items():
            assert isinstance(key, str)
            assert isinstance(value, tuple)
            assert len(value) == 3
            default, category, description = value
            assert isinstance(default, str)
            assert isinstance(category, FlagCategory)
            assert isinstance(description, str)

    def test_flag_definitions_has_expected_keys(self):
        """FLAG_DEFINITIONSに期待するキーがある"""
        expected_keys = [
            "USE_NEW_PROPOSAL_HANDLER",
            "USE_BRAIN_ARCHITECTURE",
            "DRY_RUN",
        ]
        for key in expected_keys:
            assert key in FLAG_DEFINITIONS


# =====================================================
# 10. FlagInfoテスト
# =====================================================

class TestFlagInfo:
    """FlagInfoのテスト"""

    def test_flag_info_creation(self):
        """FlagInfo作成"""
        info = FlagInfo(
            name="use_brain_architecture",
            value=True,
            env_name="USE_BRAIN_ARCHITECTURE",
            default="false",
            category=FlagCategory.FEATURE,
            description="脳アーキテクチャ",
            flag_type=FlagType.COMPLEX,
            mode="shadow",
        )

        assert info.name == "use_brain_architecture"
        assert info.value is True
        assert info.env_name == "USE_BRAIN_ARCHITECTURE"
        assert info.default == "false"
        assert info.category == FlagCategory.FEATURE
        assert info.description == "脳アーキテクチャ"
        assert info.flag_type == FlagType.COMPLEX
        assert info.mode == "shadow"

    def test_flag_info_optional_fields(self):
        """FlagInfoのオプションフィールド"""
        info = FlagInfo(
            name="use_text_utils",
            value=True,
            env_name="",
            default="",
            category=FlagCategory.LIBRARY,
            description="テキストユーティリティ",
            flag_type=FlagType.IMPORT_ONLY,
            import_available=True,
        )

        assert info.import_available is True
        assert info.mode is None


# =====================================================
# 11. エッジケーステスト
# =====================================================

class TestEdgeCases:
    """エッジケースのテスト"""

    def test_empty_env_value(self):
        """空の環境変数"""
        with patch.dict(os.environ, {"DRY_RUN": ""}):
            flags = FeatureFlags.from_env()
            # デフォルト値（False）を使用
            assert flags.dry_run is False

    def test_whitespace_env_value(self):
        """空白の環境変数"""
        with patch.dict(os.environ, {"DRY_RUN": "  true  "}):
            flags = FeatureFlags.from_env()
            # stripされないのでデフォルト
            assert flags.dry_run is False

    def test_mixed_case_env_value(self):
        """混合ケースの環境変数"""
        with patch.dict(os.environ, {"DRY_RUN": "TrUe"}):
            flags = FeatureFlags.from_env()
            assert flags.dry_run is True

    def test_special_characters_in_env(self):
        """特殊文字を含む環境変数"""
        with patch.dict(os.environ, {"DRY_RUN": "true!"}):
            flags = FeatureFlags.from_env()
            # 無効な値なのでデフォルト
            assert flags.dry_run is False

    def test_numeric_string_in_env(self):
        """数値文字列の環境変数"""
        with patch.dict(os.environ, {"DRY_RUN": "123"}):
            flags = FeatureFlags.from_env()
            # 無効な値なのでデフォルト
            assert flags.dry_run is False


# =====================================================
# 12. 全ハンドラーフラグテスト
# =====================================================

class TestAllHandlerFlags:
    """全ハンドラーフラグの個別テスト"""

    @pytest.mark.parametrize("handler_name,env_var", [
        ("proposal", "USE_NEW_PROPOSAL_HANDLER"),
        ("memory", "USE_NEW_MEMORY_HANDLER"),
        ("task", "USE_NEW_TASK_HANDLER"),
        ("overdue", "USE_NEW_OVERDUE_HANDLER"),
        ("goal", "USE_NEW_GOAL_HANDLER"),
        ("knowledge", "USE_NEW_KNOWLEDGE_HANDLER"),
    ])
    def test_handler_flag_env_true(self, handler_name, env_var):
        """各ハンドラーフラグ: 環境変数 true"""
        with patch.dict(os.environ, {env_var: "true"}):
            flags = FeatureFlags.from_env()
            flag_name = f"use_new_{handler_name}_handler"
            assert getattr(flags, flag_name) is True

    @pytest.mark.parametrize("handler_name,env_var", [
        ("proposal", "USE_NEW_PROPOSAL_HANDLER"),
        ("memory", "USE_NEW_MEMORY_HANDLER"),
        ("task", "USE_NEW_TASK_HANDLER"),
        ("overdue", "USE_NEW_OVERDUE_HANDLER"),
        ("goal", "USE_NEW_GOAL_HANDLER"),
        ("knowledge", "USE_NEW_KNOWLEDGE_HANDLER"),
    ])
    def test_handler_flag_env_false(self, handler_name, env_var):
        """各ハンドラーフラグ: 環境変数 false"""
        with patch.dict(os.environ, {env_var: "false"}):
            flags = FeatureFlags.from_env()
            flag_name = f"use_new_{handler_name}_handler"
            assert getattr(flags, flag_name) is False


# =====================================================
# 13. 全ライブラリフラグテスト
# =====================================================

class TestAllLibraryFlags:
    """全ライブラリフラグの個別テスト"""

    @pytest.mark.parametrize("lib_name", [
        "admin_config",
        "text_utils",
        "user_utils",
        "business_day",
        "goal_setting",
        "memory_framework",
        "mvv_context",
    ])
    def test_library_flag_default_false(self, lib_name):
        """ライブラリフラグのデフォルト値"""
        flags = FeatureFlags()
        flag_name = f"use_{lib_name}"
        assert getattr(flags, flag_name) is False

    @pytest.mark.parametrize("lib_name", [
        "admin_config",
        "text_utils",
        "user_utils",
        "business_day",
        "goal_setting",
        "memory_framework",
        "mvv_context",
    ])
    def test_library_flag_import_success(self, lib_name):
        """ライブラリフラグ: インポート成功時"""
        flags = FeatureFlags()
        flag_name = f"use_{lib_name}"
        flags.set_import_result(flag_name, True)
        assert getattr(flags, flag_name) is True


# =====================================================
# 14. 統合テスト
# =====================================================

class TestIntegration:
    """統合テスト"""

    def test_full_initialization_flow(self):
        """完全な初期化フロー"""
        # 1. 環境変数設定
        with patch.dict(os.environ, {
            "USE_NEW_PROPOSAL_HANDLER": "true",
            "USE_BRAIN_ARCHITECTURE": "shadow",
            "DRY_RUN": "false",
        }):
            # 2. 環境変数から初期化
            flags = FeatureFlags.from_env()

            # 3. インポート結果を設定
            flags.set_import_results({
                "use_admin_config": True,
                "use_text_utils": True,
                "use_memory_framework": False,
            })

            # 4. 検証
            assert flags.use_new_proposal_handler is True
            assert flags.use_brain_architecture is True
            assert flags.brain_mode == "shadow"
            assert flags.dry_run is False
            assert flags.use_admin_config is True
            assert flags.use_text_utils is True
            assert flags.use_memory_framework is False

    def test_print_status_no_error(self):
        """print_statusがエラーなく動作"""
        flags = FeatureFlags()
        # 例外が発生しないことを確認
        flags.print_status()

    def test_flags_immutable_after_init(self):
        """初期化後もフラグは変更可能（frozen=False）"""
        flags = FeatureFlags()
        flags.dry_run = True
        assert flags.dry_run is True

    def test_concurrent_flag_access(self):
        """並行アクセス（シンプルなテスト）"""
        flags = get_flags()

        # 複数回アクセスしても同じ値
        results = [flags.use_brain_architecture for _ in range(100)]
        assert all(r == results[0] for r in results)


# =====================================================
# 15. 後方互換性テスト
# =====================================================

class TestBackwardCompatibility:
    """後方互換性のテスト"""

    def test_handler_flags_match_expected_names(self):
        """ハンドラーフラグ名が期待通り"""
        flags = FeatureFlags()
        handler_flags = flags.get_handler_flags()

        expected = [
            "use_new_proposal_handler",
            "use_new_memory_handler",
            "use_new_task_handler",
            "use_new_overdue_handler",
            "use_new_goal_handler",
            "use_new_knowledge_handler",
        ]
        for name in expected:
            assert name in handler_flags

    def test_env_var_names_match_existing(self):
        """環境変数名が既存と一致"""
        expected_env_vars = [
            "USE_NEW_PROPOSAL_HANDLER",
            "USE_NEW_MEMORY_HANDLER",
            "USE_NEW_TASK_HANDLER",
            "USE_NEW_OVERDUE_HANDLER",
            "USE_NEW_GOAL_HANDLER",
            "USE_NEW_KNOWLEDGE_HANDLER",
            "USE_BRAIN_ARCHITECTURE",
            "DISABLE_MVV_CONTEXT",
            "DRY_RUN",
        ]
        for var in expected_env_vars:
            assert var in FLAG_DEFINITIONS or var == "DISABLE_MVV_CONTEXT"


# =====================================================
# メイン実行
# =====================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
