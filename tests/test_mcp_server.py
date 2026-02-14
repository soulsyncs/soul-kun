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


# =============================================================================
# read_resource ハッピーパステスト
# =============================================================================


class TestReadResource:
    """リソース読み取りのハッピーパステスト（DBモック使用）"""

    @pytest.mark.asyncio
    async def test_read_tasks_active(self):
        from server import read_resource
        mock_rows = [
            {"id": 1, "title": "タスクA", "status": "open", "assigned_to": "user1", "due_date": "2026-03-01"},
            {"id": 2, "title": "タスクB", "status": "in_progress", "assigned_to": None, "due_date": None},
        ]
        with patch("server._run_db_query", return_value=mock_rows) as mock_query:
            result = await read_resource("soulkun://tasks/active")
            data = json.loads(result)
            assert len(data) == 2
            assert data[0]["title"] == "タスクA"
            assert data[1]["status"] == "in_progress"
            # org_idフィルタ検証: SQLにorganization_idが含まれること（鉄則#1）
            mock_query.assert_called_once()
            sql_arg = mock_query.call_args[0][0]
            assert "organization_id" in sql_arg

    @pytest.mark.asyncio
    async def test_read_goals_active(self):
        from server import read_resource
        mock_rows = [
            {"id": 1, "title": "売上目標", "description": "Q1目標", "status": "active", "progress_percentage": 0.5},
        ]
        with patch("server._run_db_query", return_value=mock_rows) as mock_query:
            result = await read_resource("soulkun://goals/active")
            data = json.loads(result)
            assert len(data) == 1
            assert data[0]["progress_percentage"] == 0.5
            # org_idフィルタ検証（鉄則#1）
            mock_query.assert_called_once()
            assert "organization_id" in mock_query.call_args[0][0]

    @pytest.mark.asyncio
    async def test_read_persons(self):
        """personsリソース取得 + PII非漏洩検証（鉄則#8）"""
        from server import read_resource
        # モックデータにPIIフィールドを意図的に含めて、レスポンスに漏れないことを検証
        mock_rows = [
            {"id": 1, "display_name": "田中太郎", "department": "営業部", "position": "リーダー",
             "email": "tanaka@example.com", "phone": "090-1234-5678"},
        ]
        with patch("server._run_db_query", return_value=mock_rows) as mock_query:
            result = await read_resource("soulkun://persons")
            data = json.loads(result)
            assert len(data) == 1
            assert data[0]["display_name"] == "田中太郎"
            # org_idフィルタ検証（鉄則#1）
            mock_query.assert_called_once()
            sql_arg = mock_query.call_args[0][0]
            assert "organization_id" in sql_arg
            # PII検証: SQLのSELECT句にemail/phoneが含まれないことを確認（鉄則#8）
            sql_upper = sql_arg.upper()
            select_clause = sql_upper.split("FROM")[0]
            assert "EMAIL" not in select_clause
            assert "PHONE" not in select_clause

    @pytest.mark.asyncio
    async def test_read_departments(self):
        from server import read_resource
        mock_rows = [
            {"id": 1, "name": "営業部", "parent_id": None, "path": "営業部"},
        ]
        with patch("server._run_db_query", return_value=mock_rows) as mock_query:
            result = await read_resource("soulkun://departments")
            data = json.loads(result)
            assert len(data) == 1
            assert data[0]["name"] == "営業部"
            # org_idフィルタ検証（鉄則#1）
            mock_query.assert_called_once()
            assert "organization_id" in mock_query.call_args[0][0]

    @pytest.mark.asyncio
    async def test_read_person_by_id(self):
        from server import read_resource
        mock_rows = [
            {"id": 42, "display_name": "山田花子", "department": "管理部", "position": "課長"},
        ]
        with patch("server._run_db_query", return_value=mock_rows) as mock_query:
            result = await read_resource("soulkun://persons/42")
            data = json.loads(result)
            assert data["id"] == 42
            assert data["display_name"] == "山田花子"
            # org_idフィルタ検証（鉄則#1）
            mock_query.assert_called_once()
            assert "organization_id" in mock_query.call_args[0][0]

    @pytest.mark.asyncio
    async def test_read_person_not_found(self):
        from server import read_resource
        with patch("server._run_db_query", return_value=[]):
            result = await read_resource("soulkun://persons/999")
            data = json.loads(result)
            assert "error" in data
            assert "not found" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_read_task_by_id(self):
        from server import read_resource
        mock_rows = [
            {"id": 10, "title": "重要タスク", "status": "open", "assigned_to": "user1",
             "due_date": "2026-04-01", "description": "詳細説明"},
        ]
        with patch("server._run_db_query", return_value=mock_rows) as mock_query:
            result = await read_resource("soulkun://tasks/10")
            data = json.loads(result)
            assert data["title"] == "重要タスク"
            # org_idフィルタ検証（鉄則#1）
            mock_query.assert_called_once()
            assert "organization_id" in mock_query.call_args[0][0]

    @pytest.mark.asyncio
    async def test_read_unknown_uri(self):
        from server import read_resource
        result = await read_resource("soulkun://unknown/resource")
        data = json.loads(result)
        assert "error" in data
        assert "Unknown resource" in data["error"]

    @pytest.mark.asyncio
    async def test_read_resource_db_error_returns_generic_message(self):
        """DB障害時に内部エラーが漏れないこと（鉄則#8）"""
        from server import read_resource
        with patch("server._run_db_query", side_effect=Exception("Connection to 10.0.0.1 refused")):
            result = await read_resource("soulkun://tasks/active")
            data = json.loads(result)
            assert "error" in data
            assert "10.0.0.1" not in data["error"]
            assert "Check server logs" in data["error"]


# =============================================================================
# call_tool ハッピーパステスト
# =============================================================================


class TestCallToolHappyPath:
    """ツール実行のハッピーパステスト（Brain経由）"""

    @pytest.mark.asyncio
    async def test_call_tool_success_via_brain(self):
        import sys
        from server import call_tool
        import server

        server._capabilities = {
            "get_tasks": {"description": "タスク一覧", "params_schema": {}, "enabled": True},
        }

        mock_result = MagicMock()
        mock_result.to_chatwork_message.return_value = "タスク一覧: 3件あります"

        # lib.brain.llm はカスタム __getattr__ のため直接patchできない
        # sys.modulesにモックモジュールを注入してローカルimportに対応
        mock_llm_module = MagicMock()
        mock_integration_module = MagicMock()
        MockBrain = MagicMock()
        instance = AsyncMock()
        instance.process_message.return_value = mock_result
        MockBrain.return_value = instance
        mock_integration_module.BrainIntegration = MockBrain

        try:
            with patch.dict(sys.modules, {
                "lib.brain.llm": mock_llm_module,
                "lib.brain.integration": mock_integration_module,
            }), \
                 patch("server._get_db_pool", return_value=MagicMock()), \
                 patch("server._load_handlers", return_value={}):

                result = await call_tool("get_tasks", {})
                assert len(result) == 1
                assert "タスク一覧: 3件" in result[0].text
                # BrainIntegrationが使われたことを確認（bypass禁止）
                MockBrain.assert_called_once()
                instance.process_message.assert_awaited_once()
        finally:
            server._capabilities = None

    @pytest.mark.asyncio
    async def test_call_tool_with_arguments(self):
        import sys
        from server import call_tool
        import server

        server._capabilities = {
            "create_task": {"description": "タスク作成", "params_schema": {"title": {"type": "string"}}, "enabled": True},
        }

        mock_result = MagicMock()
        mock_result.to_chatwork_message.return_value = "タスク「新機能」を作成しました"

        mock_llm_module = MagicMock()
        mock_integration_module = MagicMock()
        MockBrain = MagicMock()
        instance = AsyncMock()
        instance.process_message.return_value = mock_result
        MockBrain.return_value = instance
        mock_integration_module.BrainIntegration = MockBrain

        try:
            with patch.dict(sys.modules, {
                "lib.brain.llm": mock_llm_module,
                "lib.brain.integration": mock_integration_module,
            }), \
                 patch("server._get_db_pool", return_value=MagicMock()), \
                 patch("server._load_handlers", return_value={}):

                result = await call_tool("create_task", {"title": "新機能"})
                assert "新機能" in result[0].text
                # process_messageに引数が含まれていること
                call_args = instance.process_message.call_args
                assert "新機能" in call_args.kwargs.get("message", call_args[1].get("message", ""))
        finally:
            server._capabilities = None


# =============================================================================
# get_prompt ハッピーパステスト
# =============================================================================


class TestGetPrompt:
    """プロンプト取得のテスト"""

    @pytest.mark.asyncio
    async def test_get_prompt_ceo_feedback(self):
        from server import get_prompt
        result = await get_prompt("ceo_feedback", {"topic": "新規事業"})
        assert result.description == "CEOフィードバック"
        assert len(result.messages) == 1
        assert "新規事業" in result.messages[0].content.text
        assert "ミッション" in result.messages[0].content.text

    @pytest.mark.asyncio
    async def test_get_prompt_weekly_summary(self):
        from server import get_prompt
        result = await get_prompt("weekly_summary", {})
        assert result.description == "週次サマリー"
        assert "今週の成果" in result.messages[0].content.text

    @pytest.mark.asyncio
    async def test_get_prompt_deep_research(self):
        from server import get_prompt
        result = await get_prompt("deep_research", {"query": "AI活用"})
        assert result.description == "ディープリサーチ"
        assert "AI活用" in result.messages[0].content.text
        assert "推奨アクション" in result.messages[0].content.text

    @pytest.mark.asyncio
    async def test_get_prompt_unknown_raises(self):
        from server import get_prompt
        with pytest.raises(ValueError, match="Unknown prompt"):
            await get_prompt("nonexistent_prompt", {})

    @pytest.mark.asyncio
    async def test_get_prompt_ceo_feedback_empty_topic(self):
        from server import get_prompt
        result = await get_prompt("ceo_feedback", {})
        # topic空でもエラーにならないこと
        assert result.description == "CEOフィードバック"
