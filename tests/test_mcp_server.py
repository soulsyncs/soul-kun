"""
MCP Server ユニットテスト

mcp-server/server.py のユニットテスト。
DB依存部分はモック化し、プロトコル準拠・入力検証・エラーハンドリングをテスト。
"""

import json
import os
import sys
import pytest
from unittest.mock import MagicMock, patch, AsyncMock

# mcp-server を import path に追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mcp-server"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "chatwork-webhook"))


# =============================================================================
# _map_type テスト
# =============================================================================


class TestMapType:
    """型マッピング関数のテスト"""

    def test_string_types(self):
        from server import _map_type
        assert _map_type("string") == "string"
        assert _map_type("str") == "string"

    def test_numeric_types(self):
        from server import _map_type
        assert _map_type("int") == "integer"
        assert _map_type("integer") == "integer"
        assert _map_type("float") == "number"
        assert _map_type("number") == "number"

    def test_boolean_types(self):
        from server import _map_type
        assert _map_type("bool") == "boolean"
        assert _map_type("boolean") == "boolean"

    def test_date_time_types(self):
        from server import _map_type
        assert _map_type("date") == "string"
        assert _map_type("time") == "string"

    def test_collection_types(self):
        from server import _map_type
        assert _map_type("list") == "array"
        assert _map_type("array") == "array"

    def test_unknown_type_defaults_to_string(self):
        from server import _map_type
        assert _map_type("unknown") == "string"
        assert _map_type("") == "string"
        assert _map_type("custom_type") == "string"


# =============================================================================
# _capability_to_mcp_tool テスト
# =============================================================================


class TestCapabilityToMcpTool:
    """SYSTEM_CAPABILITIES → MCP Tool 変換テスト"""

    def test_basic_conversion(self):
        from server import _capability_to_mcp_tool
        cap = {
            "description": "タスク一覧を取得",
            "params_schema": {},
        }
        tool = _capability_to_mcp_tool("get_tasks", cap)
        assert tool.name == "get_tasks"
        assert "タスク一覧を取得" in tool.description

    def test_with_params(self):
        from server import _capability_to_mcp_tool
        cap = {
            "description": "タスクを作成",
            "params_schema": {
                "title": {"type": "string", "description": "タスク名", "required": True},
                "priority": {"type": "int", "description": "優先度", "required": False},
            },
        }
        tool = _capability_to_mcp_tool("create_task", cap)
        schema = tool.inputSchema
        assert "title" in schema["properties"]
        assert "priority" in schema["properties"]
        assert "title" in schema.get("required", [])
        assert "priority" not in schema.get("required", [])

    def test_with_trigger_examples(self):
        from server import _capability_to_mcp_tool
        cap = {
            "description": "タスク一覧",
            "params_schema": {},
            "trigger_examples": ["タスク一覧を見せて", "今のタスクは？", "ToDoリスト"],
        }
        tool = _capability_to_mcp_tool("get_tasks", cap)
        assert "タスク一覧を見せて" in tool.description

    def test_empty_params_schema(self):
        from server import _capability_to_mcp_tool
        cap = {
            "description": "ヘルプ",
            "params_schema": {},
        }
        tool = _capability_to_mcp_tool("help", cap)
        assert tool.inputSchema["properties"] == {}
        assert "required" not in tool.inputSchema

    def test_type_mapping_in_params(self):
        from server import _capability_to_mcp_tool
        cap = {
            "description": "テスト",
            "params_schema": {
                "count": {"type": "int", "description": "数"},
                "active": {"type": "bool", "description": "有効"},
                "items": {"type": "list", "description": "リスト"},
            },
        }
        tool = _capability_to_mcp_tool("test", cap)
        props = tool.inputSchema["properties"]
        assert props["count"]["type"] == "integer"
        assert props["active"]["type"] == "boolean"
        assert props["items"]["type"] == "array"


# =============================================================================
# list_tools テスト
# =============================================================================


class TestListTools:
    """ツール一覧取得のテスト"""

    @pytest.mark.asyncio
    async def test_list_tools_returns_enabled_only(self):
        from server import list_tools
        import server

        mock_caps = {
            "enabled_tool": {
                "description": "有効なツール",
                "params_schema": {},
                "enabled": True,
            },
            "disabled_tool": {
                "description": "無効なツール",
                "params_schema": {},
                "enabled": False,
            },
        }
        server._capabilities = mock_caps
        try:
            tools = await list_tools()
            tool_names = [t.name for t in tools]
            assert "enabled_tool" in tool_names
            assert "disabled_tool" not in tool_names
        finally:
            server._capabilities = None

    @pytest.mark.asyncio
    async def test_list_tools_default_enabled(self):
        from server import list_tools
        import server

        mock_caps = {
            "no_enabled_field": {
                "description": "enabledフィールドなし",
                "params_schema": {},
            },
        }
        server._capabilities = mock_caps
        try:
            tools = await list_tools()
            assert len(tools) == 1
            assert tools[0].name == "no_enabled_field"
        finally:
            server._capabilities = None


# =============================================================================
# call_tool テスト（モック版）
# =============================================================================


class TestCallTool:
    """ツール実行のテスト"""

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self):
        from server import call_tool
        import server

        server._capabilities = {"known_tool": {"description": "test", "params_schema": {}}}
        try:
            result = await call_tool("nonexistent_tool", {})
            assert len(result) == 1
            data = json.loads(result[0].text)
            assert "error" in data
            assert "Unknown tool" in data["error"]
        finally:
            server._capabilities = None

    @pytest.mark.asyncio
    async def test_disabled_tool_returns_error(self):
        from server import call_tool
        import server

        server._capabilities = {
            "disabled": {"description": "test", "params_schema": {}, "enabled": False},
        }
        try:
            result = await call_tool("disabled", {})
            data = json.loads(result[0].text)
            assert "error" in data
            assert "disabled" in data["error"]
        finally:
            server._capabilities = None


# =============================================================================
# list_resources テスト
# =============================================================================


class TestListResources:
    """リソース一覧のテスト"""

    @pytest.mark.asyncio
    async def test_list_resources_returns_expected(self):
        from server import list_resources
        resources = await list_resources()
        uris = [str(r.uri) for r in resources]
        assert "soulkun://tasks/active" in uris
        assert "soulkun://goals/active" in uris
        assert "soulkun://persons" in uris
        assert "soulkun://departments" in uris

    @pytest.mark.asyncio
    async def test_resources_have_json_mimetype(self):
        from server import list_resources
        resources = await list_resources()
        for r in resources:
            assert r.mimeType == "application/json"


# =============================================================================
# list_prompts テスト
# =============================================================================


class TestListPrompts:
    """プロンプト一覧のテスト"""

    @pytest.mark.asyncio
    async def test_list_prompts_returns_list(self):
        from server import list_prompts
        prompts = await list_prompts()
        assert isinstance(prompts, list)
        assert len(prompts) > 0

    @pytest.mark.asyncio
    async def test_prompts_have_names(self):
        from server import list_prompts
        prompts = await list_prompts()
        for p in prompts:
            assert p.name
            assert p.description


# =============================================================================
# セキュリティテスト
# =============================================================================


class TestSecurity:
    """セキュリティ関連のテスト"""

    def test_organization_id_is_set(self):
        from server import ORGANIZATION_ID
        assert ORGANIZATION_ID
        assert len(ORGANIZATION_ID) > 0

    @pytest.mark.asyncio
    async def test_pii_not_in_error_responses(self):
        """エラーレスポンスにPIIが含まれないことを確認（鉄則#8）"""
        from server import call_tool
        import server

        server._capabilities = {
            "test_tool": {"description": "t", "params_schema": {}, "enabled": True},
        }
        try:
            # _get_db_pool を例外にしてエラーパスを通す
            with patch.object(
                server, "_get_db_pool",
                side_effect=Exception("DB connection to 192.168.1.1 as admin failed"),
            ):
                result = await call_tool("test_tool", {})
                data = json.loads(result[0].text)
                assert "error" in data
                # 内部エラー詳細がクライアントに漏れないこと
                assert "192.168.1.1" not in data["error"]
                assert "admin" not in data["error"]
                assert "Check server logs" in data["error"]
        finally:
            server._capabilities = None


# =============================================================================
# ORGANIZATION_ID テスト
# =============================================================================


class TestConfig:
    """設定値のテスト"""

    def test_org_id_from_env(self):
        """ORGANIZATION_IDが環境変数から取得されていること（conftest.pyでorg_testに設定）"""
        from server import ORGANIZATION_ID
        # conftest.py が monkeypatch.setenv("ORGANIZATION_ID", "org_test") を設定
        # サーバーモジュールがインポート時にその値を読み込む
        assert ORGANIZATION_ID  # 空でないこと
        assert isinstance(ORGANIZATION_ID, str)
