"""
lib/brain/env_config.py のテスト

対象:
- is_brain_enabled
- is_log_execution_id_enabled
- is_system_prompt_v2_enabled
- get_required_env_vars
- get_missing_required_vars
- validate_env_vars
"""

import os
import pytest
from unittest.mock import patch

from lib.brain.env_config import (
    ENV_BRAIN_ENABLED,
    ENV_LOG_EXECUTION_ID,
    ENV_SYSTEM_PROMPT_V2,
    ENV_OPENROUTER_API_KEY,
    ENV_LLM_BRAIN_MODEL,
    ENV_DEFAULT_AI_MODEL,
    ENV_ENVIRONMENT,
    ENV_ALERT_ROOM_ID,
    ENV_MEETING_GCS_BUCKET,
    ENV_OPERATIONS_GCS_BUCKET,
    ENV_PINECONE_INDEX_NAME,
    is_brain_enabled,
    is_log_execution_id_enabled,
    is_system_prompt_v2_enabled,
    get_required_env_vars,
    get_missing_required_vars,
    validate_env_vars,
)

# テスト用の全必須変数モック（get_missing_required_vars をクリーンにするため）
_ALL_REQUIRED_VARS = {
    ENV_BRAIN_ENABLED: "true",
    ENV_LOG_EXECUTION_ID: "true",
    ENV_ENVIRONMENT: "production",
    ENV_LLM_BRAIN_MODEL: "openai/gpt-5.2",
    ENV_DEFAULT_AI_MODEL: "google/gemini-3-flash-preview",
    ENV_OPENROUTER_API_KEY: "test-key",
    ENV_ALERT_ROOM_ID: "123456",
    ENV_MEETING_GCS_BUCKET: "soulkun-meetings",
    ENV_OPERATIONS_GCS_BUCKET: "soulkun-operations",
    ENV_PINECONE_INDEX_NAME: "soulkun-knowledge",
}


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
        with patch.dict(os.environ, {ENV_BRAIN_ENABLED: "true"}):
            result = get_required_env_vars()
            assert ENV_BRAIN_ENABLED in result
            assert result[ENV_BRAIN_ENABLED] == "true"

    def test_contains_log_execution_id(self):
        """LOG_EXECUTION_IDを含む"""
        with patch.dict(os.environ, {ENV_LOG_EXECUTION_ID: "true"}):
            result = get_required_env_vars()
            assert ENV_LOG_EXECUTION_ID in result
            assert result[ENV_LOG_EXECUTION_ID] == "true"

    def test_all_values_are_strings(self):
        """全ての値は文字列"""
        result = get_required_env_vars()
        for key, value in result.items():
            assert isinstance(key, str)
            assert isinstance(value, str)

    def test_contains_all_critical_vars(self):
        """新規追加した必須変数が全て含まれる"""
        result = get_required_env_vars()
        critical = [ENV_LLM_BRAIN_MODEL, ENV_DEFAULT_AI_MODEL, ENV_ENVIRONMENT,
                    ENV_ALERT_ROOM_ID, ENV_PINECONE_INDEX_NAME]
        for var in critical:
            assert var in result, f"{var} が get_required_env_vars() に含まれていない"


class TestGetMissingRequiredVars:
    """get_missing_required_vars()のテスト"""

    def test_returns_empty_when_all_set(self):
        """全変数が設定されている場合は空リスト"""
        with patch.dict(os.environ, _ALL_REQUIRED_VARS):
            result = get_missing_required_vars()
            assert result == []

    def test_detects_missing_openrouter_key(self):
        """OPENROUTER_API_KEY が未設定なら検出"""
        env = {k: v for k, v in _ALL_REQUIRED_VARS.items() if k != ENV_OPENROUTER_API_KEY}
        with patch.dict(os.environ, env, clear=True):
            result = get_missing_required_vars()
            assert ENV_OPENROUTER_API_KEY in result

    def test_detects_missing_llm_brain_model(self):
        """LLM_BRAIN_MODEL が未設定なら検出"""
        env = {k: v for k, v in _ALL_REQUIRED_VARS.items() if k != ENV_LLM_BRAIN_MODEL}
        with patch.dict(os.environ, env, clear=True):
            result = get_missing_required_vars()
            assert ENV_LLM_BRAIN_MODEL in result

    def test_returns_list(self):
        """リストを返す"""
        result = get_missing_required_vars()
        assert isinstance(result, list)


# =============================================================================
# validate_env_vars() テスト
# =============================================================================


class TestValidateEnvVars:
    """validate_env_vars()のテスト（非推奨変数チェックのみ）"""

    def test_no_warnings_when_clean(self):
        """非推奨変数が未設定なら空リスト"""
        with patch.dict(os.environ, {}, clear=True):
            # 非推奨変数を削除（他の変数が未設定でもここでは警告しない）
            os.environ.pop("ENABLE_LLM_BRAIN", None)
            result = validate_env_vars()
            assert result == []

    def test_warning_for_deprecated_enable_llm_brain(self):
        """ENABLE_LLM_BRAINが設定されている場合は警告"""
        with patch.dict(os.environ, {"ENABLE_LLM_BRAIN": "true"}):
            result = validate_env_vars()
            # 少なくとも1件 ENABLE_LLM_BRAIN の警告が含まれる
            deprecated_warnings = [w for w in result if "ENABLE_LLM_BRAIN" in w]
            assert len(deprecated_warnings) == 1
            assert "非推奨" in deprecated_warnings[0]
            assert ENV_BRAIN_ENABLED in deprecated_warnings[0]

    def test_returns_list(self):
        """リストを返す"""
        result = validate_env_vars()
        assert isinstance(result, list)

    def test_multiple_deprecated_vars(self):
        """複数の非推奨変数がある場合"""
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
            # 非推奨変数の警告は出る（validate_env_vars は deprecated チェックのみ）
            warnings = validate_env_vars()
            deprecated_warnings = [w for w in warnings if "ENABLE_LLM_BRAIN" in w]
            assert len(deprecated_warnings) == 1

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
