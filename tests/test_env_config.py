"""
lib/brain/env_config.py のテスト

対象:
- is_brain_enabled
- is_log_execution_id_enabled
- is_system_prompt_v2_enabled
- get_required_env_vars
- validate_env_vars
"""

import os
import pytest
from unittest.mock import patch

from lib.brain.env_config import (
    ENV_BRAIN_ENABLED,
    ENV_LOG_EXECUTION_ID,
    ENV_SYSTEM_PROMPT_V2,
    is_brain_enabled,
    is_log_execution_id_enabled,
    is_system_prompt_v2_enabled,
    get_required_env_vars,
    validate_env_vars,
)


# =============================================================================
# 定数テスト
# =============================================================================


class TestConstants:
    """環境変数名定数のテスト"""

    def test_env_brain_enabled_value(self):
        """ENV_BRAIN_ENABLEDの値"""
        assert ENV_BRAIN_ENABLED == "USE_BRAIN_ARCHITECTURE"

    def test_env_log_execution_id_value(self):
        """ENV_LOG_EXECUTION_IDの値"""
        assert ENV_LOG_EXECUTION_ID == "LOG_EXECUTION_ID"

    def test_env_system_prompt_v2_value(self):
        """ENV_SYSTEM_PROMPT_V2の値"""
        assert ENV_SYSTEM_PROMPT_V2 == "ENABLE_SYSTEM_PROMPT_V2"


# =============================================================================
# is_brain_enabled() テスト
# =============================================================================


class TestIsBrainEnabled:
    """is_brain_enabled()のテスト"""

    def test_default_is_false(self):
        """デフォルトはfalse"""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop(ENV_BRAIN_ENABLED, None)
            assert is_brain_enabled() is False

    @pytest.mark.parametrize("value", ["true", "True", "TRUE"])
    def test_true_values(self, value):
        """trueの各表記"""
        with patch.dict(os.environ, {ENV_BRAIN_ENABLED: value}):
            assert is_brain_enabled() is True

    @pytest.mark.parametrize("value", ["1", "yes", "enabled"])
    def test_alternative_true_values(self, value):
        """代替のtrue値"""
        with patch.dict(os.environ, {ENV_BRAIN_ENABLED: value}):
            assert is_brain_enabled() is True

    def test_shadow_mode_is_enabled(self):
        """shadowモードは有効"""
        with patch.dict(os.environ, {ENV_BRAIN_ENABLED: "shadow"}):
            assert is_brain_enabled() is True

    def test_gradual_mode_is_enabled(self):
        """gradualモードは有効"""
        with patch.dict(os.environ, {ENV_BRAIN_ENABLED: "gradual"}):
            assert is_brain_enabled() is True

    @pytest.mark.parametrize("value", ["false", "False", "FALSE", "0", "no", "disabled", ""])
    def test_false_values(self, value):
        """falseの各表記"""
        with patch.dict(os.environ, {ENV_BRAIN_ENABLED: value}):
            assert is_brain_enabled() is False

    def test_invalid_value_is_false(self):
        """不正な値はfalse"""
        with patch.dict(os.environ, {ENV_BRAIN_ENABLED: "invalid"}):
            assert is_brain_enabled() is False


# =============================================================================
# is_log_execution_id_enabled() テスト
# =============================================================================


class TestIsLogExecutionIdEnabled:
    """is_log_execution_id_enabled()のテスト"""

    def test_default_is_false(self):
        """デフォルトはfalse"""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop(ENV_LOG_EXECUTION_ID, None)
            assert is_log_execution_id_enabled() is False

    @pytest.mark.parametrize("value", ["true", "True", "TRUE", "1", "yes"])
    def test_true_values(self, value):
        """trueの各表記"""
        with patch.dict(os.environ, {ENV_LOG_EXECUTION_ID: value}):
            assert is_log_execution_id_enabled() is True

    @pytest.mark.parametrize("value", ["false", "0", "no", ""])
    def test_false_values(self, value):
        """falseの各表記"""
        with patch.dict(os.environ, {ENV_LOG_EXECUTION_ID: value}):
            assert is_log_execution_id_enabled() is False


# =============================================================================
# is_system_prompt_v2_enabled() テスト
# =============================================================================


class TestIsSystemPromptV2Enabled:
    """is_system_prompt_v2_enabled()のテスト"""

    def test_default_is_false(self):
        """デフォルトはfalse"""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop(ENV_SYSTEM_PROMPT_V2, None)
            assert is_system_prompt_v2_enabled() is False

    @pytest.mark.parametrize("value", ["true", "True", "TRUE", "1", "yes"])
    def test_true_values(self, value):
        """trueの各表記"""
        with patch.dict(os.environ, {ENV_SYSTEM_PROMPT_V2: value}):
            assert is_system_prompt_v2_enabled() is True

    @pytest.mark.parametrize("value", ["false", "0", "no", ""])
    def test_false_values(self, value):
        """falseの各表記"""
        with patch.dict(os.environ, {ENV_SYSTEM_PROMPT_V2: value}):
            assert is_system_prompt_v2_enabled() is False


# =============================================================================
# get_required_env_vars() テスト
# =============================================================================


class TestGetRequiredEnvVars:
    """get_required_env_vars()のテスト"""

    def test_returns_dict(self):
        """辞書を返す"""
        result = get_required_env_vars()
        assert isinstance(result, dict)

    def test_contains_brain_enabled(self):
        """USE_BRAIN_ARCHITECTUREを含む"""
        result = get_required_env_vars()
        assert ENV_BRAIN_ENABLED in result
        assert result[ENV_BRAIN_ENABLED] == "true"

    def test_contains_log_execution_id(self):
        """LOG_EXECUTION_IDを含む"""
        result = get_required_env_vars()
        assert ENV_LOG_EXECUTION_ID in result
        assert result[ENV_LOG_EXECUTION_ID] == "true"

    def test_all_values_are_strings(self):
        """全ての値は文字列"""
        result = get_required_env_vars()
        for key, value in result.items():
            assert isinstance(key, str)
            assert isinstance(value, str)


# =============================================================================
# validate_env_vars() テスト
# =============================================================================


class TestValidateEnvVars:
    """validate_env_vars()のテスト"""

    def test_no_warnings_when_clean(self):
        """問題がない場合は空リスト"""
        with patch.dict(os.environ, {}, clear=True):
            # 非推奨変数を削除
            os.environ.pop("ENABLE_LLM_BRAIN", None)
            result = validate_env_vars()
            assert result == []

    def test_warning_for_deprecated_enable_llm_brain(self):
        """ENABLE_LLM_BRAINが設定されている場合は警告"""
        with patch.dict(os.environ, {"ENABLE_LLM_BRAIN": "true"}):
            result = validate_env_vars()
            assert len(result) == 1
            assert "ENABLE_LLM_BRAIN" in result[0]
            assert "非推奨" in result[0]
            assert ENV_BRAIN_ENABLED in result[0]

    def test_returns_list(self):
        """リストを返す"""
        result = validate_env_vars()
        assert isinstance(result, list)

    def test_multiple_deprecated_vars(self):
        """複数の非推奨変数がある場合"""
        # 現在はENABLE_LLM_BRAINのみだが、将来の拡張性をテスト
        with patch.dict(os.environ, {"ENABLE_LLM_BRAIN": "true"}):
            result = validate_env_vars()
            assert len(result) >= 1


# =============================================================================
# 統合テスト
# =============================================================================


class TestEnvConfigIntegration:
    """統合テスト"""

    def test_brain_enabled_with_correct_env_var(self):
        """正しい環境変数名でBrainを有効化"""
        with patch.dict(os.environ, {ENV_BRAIN_ENABLED: "true"}):
            assert is_brain_enabled() is True
            # 非推奨変数の警告は出ない
            warnings = validate_env_vars()
            assert "ENABLE_LLM_BRAIN" not in str(warnings)

    def test_old_env_var_does_not_enable_brain(self):
        """古い環境変数名ではBrainは有効にならない"""
        with patch.dict(os.environ, {"ENABLE_LLM_BRAIN": "true"}, clear=True):
            os.environ.pop(ENV_BRAIN_ENABLED, None)
            # 古い変数は無視される
            assert is_brain_enabled() is False
            # 警告は出る
            warnings = validate_env_vars()
            assert len(warnings) == 1

    def test_required_vars_all_have_defaults(self):
        """必須変数は全てデフォルトで安全な値"""
        required = get_required_env_vars()
        for var_name in required.keys():
            # 環境変数が設定されていない場合でもエラーにならない
            with patch.dict(os.environ, {}, clear=True):
                os.environ.pop(var_name, None)
                # 各関数が例外を投げないことを確認
                if var_name == ENV_BRAIN_ENABLED:
                    assert is_brain_enabled() is False
                elif var_name == ENV_LOG_EXECUTION_ID:
                    assert is_log_execution_id_enabled() is False
