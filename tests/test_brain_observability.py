# tests/test_brain_observability.py
"""
v10.46.0: 脳の観測機能（Observability Layer）のテスト

設計書: docs/13_brain_architecture.md
鉄則3: 脳が判断し、機能は実行するだけ
鉄則4: 機能拡張しても脳の構造は変わらない
"""

import logging
import pytest
from datetime import datetime

from lib.brain.observability import (
    ContextType,
    ObservabilityLog,
    BrainObservability,
    create_observability,
    get_observability,
    log_persona_path,
)


class TestContextType:
    """ContextType enumのテスト"""

    def test_context_type_values(self):
        """全コンテキストタイプの値が正しいか"""
        assert ContextType.PERSONA.value == "persona"
        assert ContextType.MVV.value == "mvv"
        assert ContextType.CEO_TEACHING.value == "ceo_teaching"
        assert ContextType.NG_PATTERN.value == "ng_pattern"
        assert ContextType.BASIC_NEED.value == "basic_need"
        assert ContextType.INTENT.value == "intent"
        assert ContextType.ROUTE.value == "route"

    def test_context_type_is_string_enum(self):
        """ContextTypeがstr継承であることを確認"""
        assert isinstance(ContextType.PERSONA.value, str)
        # str継承なので直接文字列として使える
        assert f"type={ContextType.PERSONA}" == "type=ContextType.PERSONA"


class TestObservabilityLog:
    """ObservabilityLogデータクラスのテスト"""

    def test_create_basic_log(self):
        """基本的なログエントリの作成"""
        log = ObservabilityLog(
            context_type=ContextType.PERSONA,
            path="test_path",
            applied=True,
            account_id="12345",
        )
        assert log.context_type == ContextType.PERSONA
        assert log.path == "test_path"
        assert log.applied is True
        assert log.account_id == "12345"
        assert log.org_id is None
        assert log.details is None

    def test_create_log_with_details(self):
        """詳細情報付きログエントリの作成"""
        log = ObservabilityLog(
            context_type=ContextType.INTENT,
            path="goal_registration",
            applied=True,
            account_id="12345",
            org_id="org_test",
            details={"intent": "register_goal", "confidence": 0.95},
        )
        assert log.org_id == "org_test"
        assert log.details["intent"] == "register_goal"
        assert log.details["confidence"] == 0.95

    def test_log_has_timestamp(self):
        """タイムスタンプが自動設定されること"""
        log = ObservabilityLog(
            context_type=ContextType.PERSONA,
            path="test",
            applied=True,
            account_id="12345",
        )
        assert isinstance(log.timestamp, datetime)

    def test_to_log_string_applied(self):
        """to_log_string: applied=Trueの場合"""
        log = ObservabilityLog(
            context_type=ContextType.PERSONA,
            path="get_ai_response",
            applied=True,
            account_id="12345",
        )
        result = log.to_log_string()
        assert "ctx=persona" in result
        assert "path=get_ai_response" in result
        assert "applied=yes" in result
        assert "account=12345" in result

    def test_to_log_string_not_applied(self):
        """to_log_string: applied=Falseの場合"""
        log = ObservabilityLog(
            context_type=ContextType.PERSONA,
            path="goal_registration",
            applied=False,
            account_id="67890",
        )
        result = log.to_log_string()
        assert "applied=no" in result
        assert "account=67890" in result

    def test_to_log_string_with_details(self):
        """to_log_string: 詳細情報がある場合"""
        log = ObservabilityLog(
            context_type=ContextType.INTENT,
            path="brain_process",
            applied=True,
            account_id="12345",
            details={"intent": "task_query", "confidence": 0.88},
        )
        result = log.to_log_string()
        assert "intent" in result
        assert "confidence" in result

    def test_emoji_mapping(self):
        """コンテキストタイプごとの絵文字"""
        persona_log = ObservabilityLog(
            context_type=ContextType.PERSONA,
            path="test",
            applied=True,
            account_id="12345",
        )
        intent_log = ObservabilityLog(
            context_type=ContextType.INTENT,
            path="test",
            applied=True,
            account_id="12345",
        )
        route_log = ObservabilityLog(
            context_type=ContextType.ROUTE,
            path="test",
            applied=True,
            account_id="12345",
        )

        assert persona_log.to_log_string().startswith("🎭")
        assert intent_log.to_log_string().startswith("🧠")
        assert route_log.to_log_string().startswith("🔀")

    def test_to_dict(self):
        """to_dict: 永続化用辞書の生成"""
        log = ObservabilityLog(
            context_type=ContextType.PERSONA,
            path="test",
            applied=True,
            account_id="12345",
            org_id="org_test",
            details={"addon": True},
        )
        result = log.to_dict()

        assert result["context_type"] == "persona"
        assert result["path"] == "test"
        assert result["applied"] is True
        assert result["account_id"] == "12345"
        assert result["org_id"] == "org_test"
        assert result["details"]["addon"] is True
        assert "timestamp" in result


class TestBrainObservability:
    """BrainObservabilityクラスのテスト"""

    def test_create_instance(self):
        """インスタンス作成"""
        obs = BrainObservability(org_id="org_test")
        assert obs.org_id == "org_test"
        assert obs.enable_cloud_logging is True
        assert obs.enable_persistence is False

    def test_log_context_output(self, caplog):
        """log_context: Cloud Loggingへの出力"""
        with caplog.at_level(logging.INFO, logger="lib.brain.observability"):
            obs = BrainObservability(org_id="org_test", enable_cloud_logging=True)
            obs.log_context(
                context_type=ContextType.PERSONA,
                path="test_path",
                applied=True,
                account_id="12345",
                details={"addon": True},
            )

        assert "ctx=persona" in caplog.text
        assert "path=test_path" in caplog.text
        assert "applied=yes" in caplog.text
        assert "account=12345" in caplog.text

    def test_log_context_disabled(self, caplog):
        """log_context: Cloud Logging無効時は出力なし"""
        with caplog.at_level(logging.INFO, logger="lib.brain.observability"):
            obs = BrainObservability(org_id="org_test", enable_cloud_logging=False)
            obs.log_context(
                context_type=ContextType.PERSONA,
                path="test_path",
                applied=True,
                account_id="12345",
            )

        # INFO レベルのログは出力されない
        assert "ctx=persona" not in caplog.text

    def test_log_persona(self, caplog):
        """log_persona: Persona専用メソッド"""
        with caplog.at_level(logging.INFO, logger="lib.brain.observability"):
            obs = BrainObservability(org_id="org_test")
            obs.log_persona(
                path="get_ai_response",
                injected=True,
                addon=True,
                account_id="12345",
            )

        assert "ctx=persona" in caplog.text
        assert "applied=yes" in caplog.text
        assert "'addon': True" in caplog.text

    def test_log_intent(self, caplog):
        """log_intent: 意図判定ログ"""
        with caplog.at_level(logging.INFO, logger="lib.brain.observability"):
            obs = BrainObservability(org_id="org_test")
            obs.log_intent(
                intent="goal_registration",
                route="goal_handler",
                confidence=0.95,
                account_id="12345",
                raw_message="目標を設定したい",
            )

        assert "ctx=intent" in caplog.text
        assert "path=goal_handler" in caplog.text
        assert "'intent': 'goal_registration'" in caplog.text
        assert "'confidence': 0.95" in caplog.text

    def test_log_intent_truncates_message(self, caplog):
        """log_intent: 長いメッセージは40文字で切り捨て"""
        with caplog.at_level(logging.INFO, logger="lib.brain.observability"):
            obs = BrainObservability(org_id="org_test")
            long_message = "a" * 100
            obs.log_intent(
                intent="test",
                route="test_handler",
                confidence=0.5,
                account_id="12345",
                raw_message=long_message,
            )

        # 40文字までしか含まれない
        assert "a" * 40 in caplog.text
        assert "a" * 41 not in caplog.text

    def test_log_execution(self, caplog):
        """log_execution: 実行結果ログ"""
        with caplog.at_level(logging.INFO, logger="lib.brain.observability"):
            obs = BrainObservability(org_id="org_test")
            obs.log_execution(
                action="goal_handler",
                success=True,
                account_id="12345",
                execution_time_ms=150,
            )

        assert "ctx=route" in caplog.text
        assert "path=goal_handler" in caplog.text
        assert "'success': True" in caplog.text
        assert "'time_ms': 150" in caplog.text

    def test_log_execution_with_error(self, caplog):
        """log_execution: エラー時のログ"""
        with caplog.at_level(logging.INFO, logger="lib.brain.observability"):
            obs = BrainObservability(org_id="org_test")
            obs.log_execution(
                action="goal_handler",
                success=False,
                account_id="12345",
                execution_time_ms=50,
                error_code="HANDLER_ERROR",
            )

        assert "'success': False" in caplog.text
        assert "'error': 'HANDLER_ERROR'" in caplog.text

    def test_persistence_buffer(self):
        """永続化バッファへの追加"""
        obs = BrainObservability(
            org_id="org_test",
            enable_cloud_logging=False,
            enable_persistence=True,
        )
        obs.log_context(
            context_type=ContextType.PERSONA,
            path="test",
            applied=True,
            account_id="12345",
        )

        assert len(obs._log_buffer) == 1
        assert obs._log_buffer[0].context_type == ContextType.PERSONA

    def test_persistence_buffer_max_size(self):
        """永続化バッファの最大サイズ制限"""
        obs = BrainObservability(
            org_id="org_test",
            enable_cloud_logging=False,
            enable_persistence=True,
        )

        # 1001件追加（最大1000件）
        for i in range(1001):
            obs.log_context(
                context_type=ContextType.PERSONA,
                path=f"test_{i}",
                applied=True,
                account_id="12345",
            )

        # 最大1000件に制限される
        assert len(obs._log_buffer) <= 1000
        # 最古のログが削除され、最新が保持される
        assert obs._log_buffer[-1].path == "test_1000"


class TestFactoryFunctions:
    """ファクトリ関数のテスト"""

    def test_create_observability(self):
        """create_observability: インスタンス作成"""
        obs = create_observability(org_id="org_test")
        assert isinstance(obs, BrainObservability)
        assert obs.org_id == "org_test"

    def test_get_observability_singleton(self):
        """get_observability: シングルトンパターン"""
        # グローバル状態をリセット
        import lib.brain.observability as obs_module
        obs_module._default_observability = None

        obs1 = get_observability(org_id="org_test")
        obs2 = get_observability(org_id="org_other")

        # 同じインスタンスが返される（シングルトン）
        assert obs1 is obs2


class TestBackwardCompatibility:
    """後方互換性のテスト"""

    def test_log_persona_path_function(self, caplog):
        """log_persona_path: 後方互換関数"""
        # グローバル状態をリセット
        import lib.brain.observability as obs_module
        obs_module._default_observability = None

        with caplog.at_level(logging.INFO, logger="lib.brain.observability"):
            log_persona_path(
                path="get_ai_response",
                injected=True,
                addon=True,
                account_id="12345",
            )

        assert "ctx=persona" in caplog.text
        assert "path=get_ai_response" in caplog.text
        assert "applied=yes" in caplog.text

    def test_log_persona_path_with_extra(self, caplog):
        """log_persona_path: extra引数付き"""
        import lib.brain.observability as obs_module
        obs_module._default_observability = None

        with caplog.at_level(logging.INFO, logger="lib.brain.observability"):
            log_persona_path(
                path="goal_registration",
                injected=False,
                addon=False,
                account_id="12345",
                extra="direct_response",
            )

        assert "applied=no" in caplog.text
        assert "'extra': 'direct_response'" in caplog.text
