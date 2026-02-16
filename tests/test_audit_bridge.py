"""
監査ログ橋渡し（audit_bridge）テスト — Step 0-2

audit_bridge.pyのPII除去とログ記録をテスト:
- PIIキーの除去
- 長い文字列の切り詰め
- log_tool_execution()のfire-and-forget動作
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from lib.brain.audit_bridge import _sanitize_params, log_tool_execution


class TestSanitizeParams:
    """パラメータPII除去のテスト"""

    def test_none_params(self):
        """Noneは空辞書を返す"""
        assert _sanitize_params(None) == {}

    def test_empty_params(self):
        """空辞書はそのまま"""
        assert _sanitize_params({}) == {}

    def test_pii_keys_redacted(self):
        """PIIキーは[REDACTED]に置換される"""
        params = {
            "message": "田中さんへの返信",
            "name": "田中太郎",
            "email": "tanaka@example.com",
            "room_id": "12345",
        }
        result = _sanitize_params(params)
        assert result["message"] == "[REDACTED]"
        assert result["name"] == "[REDACTED]"
        assert result["email"] == "[REDACTED]"
        assert result["room_id"] == "12345"

    def test_long_strings_truncated(self):
        """200文字超の文字列は切り詰め"""
        params = {
            "query": "a" * 300,
        }
        result = _sanitize_params(params)
        assert result["query"].endswith("...[TRUNCATED]")
        assert len(result["query"]) < 300

    def test_safe_params_preserved(self):
        """安全なパラメータはそのまま保持"""
        params = {
            "room_id": "123",
            "account_id": "456",
            "action": "goal_registration",
            "amount": 50000,
        }
        result = _sanitize_params(params)
        assert result == params

    def test_body_key_redacted(self):
        """bodyキーもPIIとして除去"""
        params = {"body": "本文テスト"}
        result = _sanitize_params(params)
        assert result["body"] == "[REDACTED]"

    def test_sender_name_redacted(self):
        """sender_nameもPIIとして除去"""
        params = {"sender_name": "鈴木一郎"}
        result = _sanitize_params(params)
        assert result["sender_name"] == "[REDACTED]"


class TestLogToolExecution:
    """log_tool_execution()のテスト"""

    @pytest.mark.asyncio
    async def test_success_log(self):
        """成功ログの記録"""
        with patch("lib.brain.audit_bridge.log_audit_async", new_callable=AsyncMock) as mock_audit:
            mock_audit.return_value = True
            result = await log_tool_execution(
                organization_id="test-org",
                tool_name="chatwork_task_create",
                account_id="user-001",
                success=True,
                risk_level="low",
            )
            assert result is True
            mock_audit.assert_called_once()
            call_kwargs = mock_audit.call_args[1]
            assert call_kwargs["action"] == "tool_execute_chatwork_task_create"
            assert call_kwargs["resource_type"] == "brain_tool"

    @pytest.mark.asyncio
    async def test_failure_log_includes_error_code(self):
        """失敗ログにエラーコードが含まれる"""
        with patch("lib.brain.audit_bridge.log_audit_async", new_callable=AsyncMock) as mock_audit:
            mock_audit.return_value = True
            result = await log_tool_execution(
                organization_id="test-org",
                tool_name="goal_delete",
                account_id="user-001",
                success=False,
                risk_level="medium",
                error_code="HANDLER_NOT_FOUND",
            )
            assert result is True
            call_kwargs = mock_audit.call_args[1]
            assert call_kwargs["details"]["error_code"] == "HANDLER_NOT_FOUND"
            assert call_kwargs["details"]["risk_level"] == "medium"

    @pytest.mark.asyncio
    async def test_params_are_sanitized(self):
        """パラメータがPII除去される"""
        with patch("lib.brain.audit_bridge.log_audit_async", new_callable=AsyncMock) as mock_audit:
            mock_audit.return_value = True
            await log_tool_execution(
                organization_id="test-org",
                tool_name="send_message",
                account_id="user-001",
                success=True,
                parameters={"message": "秘密のメッセージ", "room_id": "123"},
            )
            call_kwargs = mock_audit.call_args[1]
            params = call_kwargs["details"]["parameters"]
            assert params["message"] == "[REDACTED]"
            assert params["room_id"] == "123"

    @pytest.mark.asyncio
    async def test_exception_returns_false(self):
        """例外発生時はFalseを返す（fire-and-forget安全性）"""
        with patch("lib.brain.audit_bridge.log_audit_async", new_callable=AsyncMock) as mock_audit:
            mock_audit.side_effect = Exception("Logging failed")
            result = await log_tool_execution(
                organization_id="test-org",
                tool_name="test_tool",
                account_id="user-001",
                success=True,
            )
            assert result is False
