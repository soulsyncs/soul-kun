# tests/test_llm_brain_tool_converter.py
"""
LLM Brain - Tool Converter のテスト

SYSTEM_CAPABILITIESをAnthropic Tool形式に変換する機能をテストします。

設計書: docs/25_llm_native_brain_architecture.md セクション7.1b
"""

import pytest
from unittest.mock import patch, MagicMock

from lib.brain.tool_converter import (
    ToolConverter,
    ToolConversionConfig,
    get_tools_for_llm,
    get_tool_metadata,
    is_dangerous_operation,
    requires_confirmation,
)


# =============================================================================
# フィクスチャ
# =============================================================================


@pytest.fixture
def sample_capabilities():
    """テスト用のSYSTEM_CAPABILITIES"""
    return {
        "chatwork_task_create": {
            "name": "ChatWorkタスク作成",
            "description": "ChatWorkにタスクを作成する",
            "category": "task",
            "enabled": True,
            "trigger_examples": ["タスク追加して", "タスク作って", "やることリストに追加"],
            "params_schema": {
                "body": {
                    "type": "string",
                    "description": "タスクの内容",
                    "required": True,
                },
                "room_id": {
                    "type": "string",
                    "description": "ルームID",
                    "required": False,
                },
                "due_date": {
                    "type": "date",
                    "description": "期限日",
                    "note": "明日、来週月曜などの相対表現も可",
                },
            },
            "requires_confirmation": False,
            "brain_metadata": {
                "risk_level": "low",
            },
        },
        "delete_task": {
            "name": "タスク削除",
            "description": "タスクを削除する",
            "category": "task",
            "enabled": True,
            "trigger_examples": ["タスク消して", "削除して"],
            "params_schema": {
                "task_id": {
                    "type": "string",
                    "description": "タスクID",
                    "required": True,
                },
            },
            "requires_confirmation": True,
            "brain_metadata": {
                "risk_level": "medium",
            },
        },
        "send_to_all": {
            "name": "全員送信",
            "description": "全員にメッセージを送る",
            "category": "message",
            "enabled": True,
            "trigger_examples": ["全員に送って"],
            "params_schema": {
                "message": {
                    "type": "string",
                    "description": "送信メッセージ",
                    "required": True,
                },
            },
            "requires_confirmation": True,
            "brain_metadata": {
                "risk_level": "high",
            },
        },
        "disabled_feature": {
            "name": "無効機能",
            "description": "無効化されている機能",
            "category": "test",
            "enabled": False,
            "trigger_examples": ["テスト"],
            "params_schema": {},
        },
    }


@pytest.fixture
def converter():
    """デフォルト設定のToolConverter"""
    return ToolConverter()


@pytest.fixture
def converter_no_examples():
    """トリガー例を含めないToolConverter"""
    config = ToolConversionConfig(include_examples=False)
    return ToolConverter(config)


# =============================================================================
# ToolConverter 基本テスト
# =============================================================================


class TestToolConverterBasic:
    """ToolConverter基本機能のテスト"""

    def test_init_default_config(self):
        """デフォルト設定で初期化できること"""
        converter = ToolConverter()
        assert converter.config.include_examples is True
        assert converter.config.max_examples == 5
        assert converter.config.validate_schema is True

    def test_init_custom_config(self):
        """カスタム設定で初期化できること"""
        config = ToolConversionConfig(
            include_examples=False,
            max_examples=3,
            validate_schema=False,
        )
        converter = ToolConverter(config)
        assert converter.config.include_examples is False
        assert converter.config.max_examples == 3
        assert converter.config.validate_schema is False

    def test_type_mapping(self, converter):
        """型マッピングが正しいこと"""
        assert converter.TYPE_MAPPING["string"] == "string"
        assert converter.TYPE_MAPPING["int"] == "integer"
        assert converter.TYPE_MAPPING["float"] == "number"
        assert converter.TYPE_MAPPING["bool"] == "boolean"
        assert converter.TYPE_MAPPING["list"] == "array"
        assert converter.TYPE_MAPPING["dict"] == "object"
        assert converter.TYPE_MAPPING["date"] == "string"
        assert converter.TYPE_MAPPING["datetime"] == "string"


# =============================================================================
# convert_all テスト
# =============================================================================


class TestConvertAll:
    """convert_all メソッドのテスト"""

    def test_convert_all_returns_list(self, converter, sample_capabilities):
        """変換結果がリストであること"""
        tools = converter.convert_all(sample_capabilities)
        assert isinstance(tools, list)

    def test_convert_all_excludes_disabled(self, converter, sample_capabilities):
        """無効な機能が除外されること"""
        tools = converter.convert_all(sample_capabilities)
        tool_names = [t["name"] for t in tools]
        assert "disabled_feature" not in tool_names

    def test_convert_all_includes_enabled(self, converter, sample_capabilities):
        """有効な機能が含まれること"""
        tools = converter.convert_all(sample_capabilities)
        tool_names = [t["name"] for t in tools]
        assert "chatwork_task_create" in tool_names
        assert "delete_task" in tool_names
        assert "send_to_all" in tool_names

    def test_convert_all_correct_count(self, converter, sample_capabilities):
        """変換数が正しいこと（有効な機能のみ）"""
        tools = converter.convert_all(sample_capabilities)
        # 4つの機能のうち1つは無効なので3つ
        assert len(tools) == 3

    def test_convert_all_empty_capabilities(self, converter):
        """空のSYSTEM_CAPABILITIESでエラーにならないこと"""
        tools = converter.convert_all({})
        assert tools == []


# =============================================================================
# convert_one テスト
# =============================================================================


class TestConvertOne:
    """convert_one メソッドのテスト"""

    def test_convert_one_basic_structure(self, converter, sample_capabilities):
        """変換結果の基本構造が正しいこと"""
        tool = converter.convert_one(
            "chatwork_task_create",
            sample_capabilities["chatwork_task_create"]
        )
        assert "name" in tool
        assert "description" in tool
        assert "input_schema" in tool

    def test_convert_one_name(self, converter, sample_capabilities):
        """nameがcapability keyと一致すること"""
        tool = converter.convert_one(
            "chatwork_task_create",
            sample_capabilities["chatwork_task_create"]
        )
        assert tool["name"] == "chatwork_task_create"

    def test_convert_one_description_includes_examples(self, converter, sample_capabilities):
        """descriptionにトリガー例が含まれること"""
        tool = converter.convert_one(
            "chatwork_task_create",
            sample_capabilities["chatwork_task_create"]
        )
        assert "タスク追加して" in tool["description"]
        assert "タスク作って" in tool["description"]

    def test_convert_one_description_no_examples(self, converter_no_examples, sample_capabilities):
        """トリガー例を含めない設定の場合、例が含まれないこと"""
        tool = converter_no_examples.convert_one(
            "chatwork_task_create",
            sample_capabilities["chatwork_task_create"]
        )
        assert "タスク追加して" not in tool["description"]

    def test_convert_one_input_schema_structure(self, converter, sample_capabilities):
        """input_schemaの構造が正しいこと"""
        tool = converter.convert_one(
            "chatwork_task_create",
            sample_capabilities["chatwork_task_create"]
        )
        schema = tool["input_schema"]
        assert schema["type"] == "object"
        assert "properties" in schema
        assert "required" in schema

    def test_convert_one_required_params(self, converter, sample_capabilities):
        """必須パラメータがrequiredリストに含まれること"""
        tool = converter.convert_one(
            "chatwork_task_create",
            sample_capabilities["chatwork_task_create"]
        )
        required = tool["input_schema"]["required"]
        assert "body" in required
        assert "room_id" not in required  # required: False

    def test_convert_one_type_conversion(self, converter, sample_capabilities):
        """型が正しく変換されること"""
        tool = converter.convert_one(
            "chatwork_task_create",
            sample_capabilities["chatwork_task_create"]
        )
        props = tool["input_schema"]["properties"]
        assert props["body"]["type"] == "string"
        # dateはstringに変換される
        assert props["due_date"]["type"] == "string"

    def test_convert_one_note_in_description(self, converter, sample_capabilities):
        """noteがdescriptionに含まれること"""
        tool = converter.convert_one(
            "chatwork_task_create",
            sample_capabilities["chatwork_task_create"]
        )
        props = tool["input_schema"]["properties"]
        assert "相対表現も可" in props["due_date"]["description"]

    def test_convert_one_date_format_hint(self, converter, sample_capabilities):
        """date型にフォーマットヒントが含まれること"""
        tool = converter.convert_one(
            "chatwork_task_create",
            sample_capabilities["chatwork_task_create"]
        )
        props = tool["input_schema"]["properties"]
        assert "YYYY-MM-DD" in props["due_date"]["description"]


# =============================================================================
# ヘルパー関数テスト
# =============================================================================


class TestHelperFunctions:
    """ヘルパー関数のテスト"""

    def test_get_tool_metadata(self):
        """get_tool_metadataが正しくメタデータを返すこと"""
        # 実際のSYSTEM_CAPABILITIESを使用
        metadata = get_tool_metadata("chatwork_task_create")
        assert metadata is not None
        assert "description" in metadata

    def test_get_tool_metadata_not_found(self):
        """存在しないToolでNoneを返すこと"""
        metadata = get_tool_metadata("nonexistent_tool_12345")
        assert metadata is None

    @patch('lib.brain.tool_converter.get_tool_metadata')
    def test_is_dangerous_operation_high(self, mock_get_metadata):
        """高リスク操作が危険と判定されること"""
        mock_get_metadata.return_value = {
            "brain_metadata": {"risk_level": "high"}
        }
        is_dangerous, level = is_dangerous_operation("send_to_all")
        assert is_dangerous is True
        assert level == "high"

    @patch('lib.brain.tool_converter.get_tool_metadata')
    def test_is_dangerous_operation_low(self, mock_get_metadata):
        """低リスク操作が危険でないと判定されること"""
        mock_get_metadata.return_value = {
            "brain_metadata": {"risk_level": "low"}
        }
        is_dangerous, level = is_dangerous_operation("task_create")
        assert is_dangerous is False
        assert level == "low"

    @patch('lib.brain.tool_converter.get_tool_metadata')
    def test_is_dangerous_operation_unknown(self, mock_get_metadata):
        """不明な操作はunknownを返すこと"""
        mock_get_metadata.return_value = None
        is_dangerous, level = is_dangerous_operation("unknown")
        assert is_dangerous is False
        assert level == "unknown"

    @patch('lib.brain.tool_converter.get_tool_metadata')
    def test_requires_confirmation_true(self, mock_get_metadata):
        """確認が必要な操作でTrueを返すこと"""
        mock_get_metadata.return_value = {
            "requires_confirmation": True
        }
        assert requires_confirmation("delete_task") is True

    @patch('lib.brain.tool_converter.get_tool_metadata')
    def test_requires_confirmation_false(self, mock_get_metadata):
        """確認が不要な操作でFalseを返すこと"""
        mock_get_metadata.return_value = {
            "requires_confirmation": False
        }
        assert requires_confirmation("task_create") is False

    @patch('lib.brain.tool_converter.get_tool_metadata')
    def test_requires_confirmation_unknown(self, mock_get_metadata):
        """不明な操作はTrueを返すこと（安全側に倒す）"""
        mock_get_metadata.return_value = None
        assert requires_confirmation("unknown") is True


# =============================================================================
# get_tools_for_llm 統合テスト
# =============================================================================


class TestGetToolsForLLM:
    """get_tools_for_llm関数の統合テスト"""

    def test_get_tools_for_llm_returns_list(self):
        """リストが返されること"""
        tools = get_tools_for_llm()
        assert isinstance(tools, list)

    def test_get_tools_for_llm_not_empty(self):
        """空でないリストが返されること"""
        tools = get_tools_for_llm()
        assert len(tools) > 0

    def test_get_tools_for_llm_valid_structure(self):
        """各Toolが有効な構造を持つこと"""
        tools = get_tools_for_llm()
        for tool in tools:
            assert "name" in tool
            assert "description" in tool
            assert "input_schema" in tool
            assert tool["input_schema"]["type"] == "object"
            assert "properties" in tool["input_schema"]
            assert "required" in tool["input_schema"]

    def test_get_tools_for_llm_includes_chatwork_task_create(self):
        """chatwork_task_createが含まれること"""
        tools = get_tools_for_llm()
        tool_names = [t["name"] for t in tools]
        assert "chatwork_task_create" in tool_names


# =============================================================================
# convert_all 追加テスト（line 99: convert_one失敗時の警告）
# =============================================================================


class TestConvertAllFailedConversion:
    """convert_all でconvert_oneが失敗した場合のテスト"""

    def test_convert_all_logs_warning_on_failed_conversion(self, converter):
        """convert_oneがNoneを返した場合に警告ログが出ること（line 99）"""
        # _build_descriptionが例外を投げるようにしてconvert_oneがNoneを返す状況を作る
        cap = {
            "broken_tool": {
                "enabled": True,
                "description": "broken",
                "params_schema": {},
            },
        }
        # convert_oneをモックしてNoneを返す
        with patch.object(converter, 'convert_one', return_value=None):
            tools = converter.convert_all(cap)
        assert tools == []

    def test_convert_all_skips_failed_and_includes_successful(self, converter):
        """一部が失敗しても、成功したToolは含まれること"""
        caps = {
            "good_tool": {
                "enabled": True,
                "description": "Good tool",
                "params_schema": {
                    "param1": {"type": "string", "description": "test"},
                },
            },
            "bad_tool": {
                "enabled": True,
                "description": "Bad tool",
                "params_schema": {},
            },
        }
        original_convert_one = converter.convert_one

        def side_effect(key, cap):
            if key == "bad_tool":
                return None
            return original_convert_one(key, cap)

        with patch.object(converter, 'convert_one', side_effect=side_effect):
            tools = converter.convert_all(caps)
        assert len(tools) == 1
        assert tools[0]["name"] == "good_tool"


# =============================================================================
# convert_one 追加テスト（lines 131-132, 140-142）
# =============================================================================


class TestConvertOneEdgeCases:
    """convert_one のエッジケーステスト"""

    def test_convert_one_invalid_schema_returns_none(self):
        """スキーマ検証失敗時にNoneを返すこと（lines 131-132）"""
        converter = ToolConverter()
        cap = {
            "description": "test",
            "params_schema": {},
        }
        # _validate_schemaをモックしてFalseを返す
        with patch.object(converter, '_validate_schema', return_value=False):
            result = converter.convert_one("broken_schema_tool", cap)
        assert result is None

    def test_convert_one_exception_returns_none(self):
        """変換中に例外が発生した場合にNoneを返すこと（lines 140-142）"""
        converter = ToolConverter()
        cap = {
            "description": "test",
            "params_schema": {},
        }
        # _build_descriptionが例外を投げる
        with patch.object(converter, '_build_description', side_effect=RuntimeError("test error")):
            result = converter.convert_one("error_tool", cap)
        assert result is None

    def test_convert_one_skip_validation_when_disabled(self):
        """validate_schemaがFalseの場合、検証をスキップすること"""
        config = ToolConversionConfig(validate_schema=False)
        converter = ToolConverter(config)
        cap = {
            "description": "test",
            "params_schema": {},
        }
        result = converter.convert_one("test_tool", cap)
        assert result is not None
        assert result["name"] == "test_tool"


# =============================================================================
# _convert_params_schema 追加テスト（lines 201, 213）
# =============================================================================


class TestConvertParamsSchemaExtended:
    """_convert_params_schema の追加テスト"""

    def test_enum_param(self):
        """enumがparams_schemaに含まれる場合に反映されること（line 201）"""
        converter = ToolConverter()
        schema = {
            "status": {
                "type": "string",
                "description": "ステータス",
                "enum": ["open", "done", "cancelled"],
            },
        }
        result = converter._convert_params_schema(schema)
        assert result["properties"]["status"]["enum"] == ["open", "done", "cancelled"]

    def test_default_value_param(self):
        """デフォルト値がparams_schemaに含まれる場合に反映されること"""
        converter = ToolConverter()
        schema = {
            "limit": {
                "type": "int",
                "description": "件数",
                "default": 10,
            },
        }
        result = converter._convert_params_schema(schema)
        assert result["properties"]["limit"]["default"] == 10

    def test_datetime_format_hint(self):
        """datetime型にフォーマットヒントが含まれること（line 213）"""
        converter = ToolConverter()
        schema = {
            "scheduled_at": {
                "type": "datetime",
                "description": "予定日時",
            },
        }
        result = converter._convert_params_schema(schema)
        desc = result["properties"]["scheduled_at"]["description"]
        assert "YYYY-MM-DDTHH:MM:SS" in desc

    def test_time_format_hint(self):
        """time型にフォーマットヒントが含まれること"""
        converter = ToolConverter()
        schema = {
            "start_time": {
                "type": "time",
                "description": "開始時刻",
            },
        }
        result = converter._convert_params_schema(schema)
        desc = result["properties"]["start_time"]["description"]
        assert "HH:MM" in desc

    def test_array_type_with_items_schema(self):
        """配列型でitems_schemaがある場合にitemsが変換されること"""
        converter = ToolConverter()
        schema = {
            "assignees": {
                "type": "list",
                "description": "担当者リスト",
                "items_schema": {
                    "name": "担当者名",
                    "account_id": "アカウントID",
                },
            },
        }
        result = converter._convert_params_schema(schema)
        prop = result["properties"]["assignees"]
        assert prop["type"] == "array"
        assert prop["items"]["type"] == "object"
        assert "name" in prop["items"]["properties"]
        assert prop["items"]["properties"]["name"]["description"] == "担当者名"

    def test_array_type_without_items_schema(self):
        """配列型でitems_schemaがない場合にデフォルトのstring配列になること"""
        converter = ToolConverter()
        schema = {
            "tags": {
                "type": "list",
                "description": "タグリスト",
            },
        }
        result = converter._convert_params_schema(schema)
        prop = result["properties"]["tags"]
        assert prop["type"] == "array"
        assert prop["items"] == {"type": "string"}


# =============================================================================
# _validate_schema テスト（lines 270, 272, 277-278）
# =============================================================================


class TestValidateSchema:
    """_validate_schema メソッドのテスト"""

    def test_valid_schema(self):
        """正常なスキーマがTrueを返すこと"""
        converter = ToolConverter()
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "名前"},
            },
            "required": ["name"],
        }
        assert converter._validate_schema(schema) is True

    def test_missing_type_returns_false(self):
        """typeがないスキーマがFalseを返すこと（line 270）"""
        converter = ToolConverter()
        schema = {
            "properties": {
                "name": {"type": "string"},
            },
            "required": [],
        }
        assert converter._validate_schema(schema) is False

    def test_missing_properties_returns_false(self):
        """propertiesがないスキーマがFalseを返すこと（line 272）"""
        converter = ToolConverter()
        schema = {
            "type": "object",
            "required": [],
        }
        assert converter._validate_schema(schema) is False

    def test_property_missing_type_returns_false(self):
        """プロパティにtypeがない場合にFalseを返すこと（lines 277-278）"""
        converter = ToolConverter()
        schema = {
            "type": "object",
            "properties": {
                "name": {"description": "名前"},  # typeがない
            },
            "required": [],
        }
        assert converter._validate_schema(schema) is False

    def test_empty_properties_valid(self):
        """propertiesが空のスキーマがTrueを返すこと"""
        converter = ToolConverter()
        schema = {
            "type": "object",
            "properties": {},
            "required": [],
        }
        assert converter._validate_schema(schema) is True


# =============================================================================
# _convert_type テスト
# =============================================================================


class TestConvertType:
    """_convert_type メソッドのテスト"""

    def test_unknown_type_defaults_to_string(self):
        """不明な型がstringにデフォルト変換されること"""
        converter = ToolConverter()
        assert converter._convert_type("unknown_type") == "string"

    def test_case_insensitive(self):
        """型名の大小文字を区別しないこと"""
        converter = ToolConverter()
        assert converter._convert_type("STRING") == "string"
        assert converter._convert_type("Int") == "integer"
        assert converter._convert_type("BOOLEAN") == "boolean"


# =============================================================================
# ToolMetadata テスト（line 322）
# =============================================================================


class TestToolMetadata:
    """ToolMetadataデータクラスのテスト"""

    def test_to_dict(self):
        """to_dictが全フィールドを含む辞書を返すこと（line 322）"""
        from lib.brain.tool_converter import ToolMetadata
        metadata = ToolMetadata(
            name="test_tool",
            category="task",
            risk_level="medium",
            requires_confirmation=True,
            required_permission_level=3,
            dependencies=["dep1", "dep2"],
            version="2.0.0",
            deprecated=True,
            deprecation_message="Use new_tool instead",
        )
        d = metadata.to_dict()
        assert d["name"] == "test_tool"
        assert d["category"] == "task"
        assert d["risk_level"] == "medium"
        assert d["requires_confirmation"] is True
        assert d["required_permission_level"] == 3
        assert d["dependencies"] == ["dep1", "dep2"]
        assert d["version"] == "2.0.0"
        assert d["deprecated"] is True
        assert d["deprecation_message"] == "Use new_tool instead"

    def test_defaults(self):
        """デフォルト値が正しいこと"""
        from lib.brain.tool_converter import ToolMetadata
        metadata = ToolMetadata(name="simple_tool")
        assert metadata.category == "general"
        assert metadata.risk_level == "low"
        assert metadata.requires_confirmation is False
        assert metadata.required_permission_level == 1
        assert metadata.dependencies == []
        assert metadata.version == "1.0.0"
        assert metadata.deprecated is False
        assert metadata.deprecation_message is None

    def test_to_dict_with_defaults(self):
        """デフォルト値でのto_dictが正しいこと"""
        from lib.brain.tool_converter import ToolMetadata
        metadata = ToolMetadata(name="default_tool")
        d = metadata.to_dict()
        assert d["name"] == "default_tool"
        assert d["deprecation_message"] is None
        assert d["dependencies"] == []


# =============================================================================
# ToolMetadataRegistry テスト（lines 378-413, 417-465, 469-482）
# =============================================================================


class TestToolMetadataRegistry:
    """ToolMetadataRegistryのテスト"""

    def _make_registry(self):
        """テスト用のレジストリを作成（_ensure_loadedをバイパス）"""
        from lib.brain.tool_converter import ToolMetadataRegistry, ToolMetadata
        registry = ToolMetadataRegistry()
        registry._loaded = True  # 自動ロードをスキップ
        return registry

    def test_init(self):
        """初期化が正しいこと（lines 379-380）"""
        from lib.brain.tool_converter import ToolMetadataRegistry
        registry = ToolMetadataRegistry()
        assert registry._metadata == {}
        assert registry._loaded is False

    def test_register(self):
        """メタデータの登録（lines 384-385）"""
        from lib.brain.tool_converter import ToolMetadata
        registry = self._make_registry()
        metadata = ToolMetadata(name="test_tool", category="task")
        registry.register(metadata)
        assert "test_tool" in registry._metadata
        assert registry._metadata["test_tool"].category == "task"

    def test_get_existing(self):
        """登録済みメタデータの取得（lines 389-390）"""
        from lib.brain.tool_converter import ToolMetadata
        registry = self._make_registry()
        metadata = ToolMetadata(name="my_tool", risk_level="high")
        registry.register(metadata)
        result = registry.get("my_tool")
        assert result is not None
        assert result.risk_level == "high"

    def test_get_nonexistent(self):
        """未登録のメタデータはNoneを返すこと"""
        registry = self._make_registry()
        result = registry.get("nonexistent_tool")
        assert result is None

    def test_get_by_category(self):
        """カテゴリ別のツール取得（lines 394-395）"""
        from lib.brain.tool_converter import ToolMetadata
        registry = self._make_registry()
        registry.register(ToolMetadata(name="task1", category="task"))
        registry.register(ToolMetadata(name="task2", category="task"))
        registry.register(ToolMetadata(name="search1", category="search"))
        result = registry.get_by_category("task")
        assert len(result) == 2
        names = [m.name for m in result]
        assert "task1" in names
        assert "task2" in names

    def test_get_by_category_empty(self):
        """該当カテゴリがない場合に空リストを返すこと"""
        registry = self._make_registry()
        result = registry.get_by_category("nonexistent")
        assert result == []

    def test_get_high_risk_tools(self):
        """高リスクツールの取得（lines 399-400）"""
        from lib.brain.tool_converter import ToolMetadata
        registry = self._make_registry()
        registry.register(ToolMetadata(name="safe_tool", risk_level="low"))
        registry.register(ToolMetadata(name="risky_tool", risk_level="high"))
        registry.register(ToolMetadata(name="critical_tool", risk_level="critical"))
        registry.register(ToolMetadata(name="medium_tool", risk_level="medium"))
        result = registry.get_high_risk_tools()
        assert len(result) == 2
        names = [m.name for m in result]
        assert "risky_tool" in names
        assert "critical_tool" in names

    def test_get_deprecated_tools(self):
        """非推奨ツールの取得（lines 404-405）"""
        from lib.brain.tool_converter import ToolMetadata
        registry = self._make_registry()
        registry.register(ToolMetadata(name="old_tool", deprecated=True, deprecation_message="Use new"))
        registry.register(ToolMetadata(name="new_tool", deprecated=False))
        result = registry.get_deprecated_tools()
        assert len(result) == 1
        assert result[0].name == "old_tool"

    def test_get_deprecated_tools_none(self):
        """非推奨ツールがない場合に空リストを返すこと"""
        from lib.brain.tool_converter import ToolMetadata
        registry = self._make_registry()
        registry.register(ToolMetadata(name="good_tool", deprecated=False))
        result = registry.get_deprecated_tools()
        assert result == []

    def test_infer_risk_level_delete(self):
        """delete系ツールのリスクレベル推測（lines 409-413）"""
        registry = self._make_registry()
        assert registry.infer_risk_level("delete_task") == "high"

    def test_infer_risk_level_remove(self):
        """remove系ツールのリスクレベル推測"""
        registry = self._make_registry()
        assert registry.infer_risk_level("remove_member") == "high"

    def test_infer_risk_level_update(self):
        """update系ツールのリスクレベル推測"""
        registry = self._make_registry()
        assert registry.infer_risk_level("update_profile") == "medium"

    def test_infer_risk_level_create(self):
        """create系ツールのリスクレベル推測"""
        registry = self._make_registry()
        assert registry.infer_risk_level("create_task") == "medium"

    def test_infer_risk_level_send(self):
        """send系ツールのリスクレベル推測"""
        registry = self._make_registry()
        assert registry.infer_risk_level("send_message") == "medium"

    def test_infer_risk_level_search(self):
        """search系ツールのリスクレベル推測"""
        registry = self._make_registry()
        assert registry.infer_risk_level("search_knowledge") == "low"

    def test_infer_risk_level_get(self):
        """get系ツールのリスクレベル推測"""
        registry = self._make_registry()
        assert registry.infer_risk_level("get_user") == "low"

    def test_infer_risk_level_unknown(self):
        """不明なツール名はlowを返すこと"""
        registry = self._make_registry()
        assert registry.infer_risk_level("something_unique") == "low"

    def test_infer_category_task(self):
        """task系ツールのカテゴリ推測（lines 417-437）"""
        registry = self._make_registry()
        assert registry.infer_category("chatwork_task_create") == "task"

    def test_infer_category_goal(self):
        """goal系ツールのカテゴリ推測"""
        registry = self._make_registry()
        assert registry.infer_category("goal_progress") == "goal"

    def test_infer_category_message(self):
        """message系ツールのカテゴリ推測"""
        registry = self._make_registry()
        assert registry.infer_category("send_message") == "message"

    def test_infer_category_message_post(self):
        """post系ツールのカテゴリ推測"""
        registry = self._make_registry()
        assert registry.infer_category("post_announcement") == "message"

    def test_infer_category_message_announce(self):
        """announce系ツールのカテゴリ推測"""
        registry = self._make_registry()
        assert registry.infer_category("announce_news") == "message"

    def test_infer_category_memory(self):
        """memory系ツールのカテゴリ推測"""
        registry = self._make_registry()
        assert registry.infer_category("memory_store") == "memory"

    def test_infer_category_remember(self):
        """remember系ツールのカテゴリ推測"""
        registry = self._make_registry()
        assert registry.infer_category("remember_this") == "memory"

    def test_infer_category_forget(self):
        """forget系ツールのカテゴリ推測（forgetはget含むがmemoryが優先）"""
        registry = self._make_registry()
        assert registry.infer_category("forget_info") == "memory"

    def test_infer_category_search(self):
        """search系ツールのカテゴリ推測"""
        registry = self._make_registry()
        assert registry.infer_category("search_docs") == "search"

    def test_infer_category_find(self):
        """find系ツールのカテゴリ推測"""
        registry = self._make_registry()
        assert registry.infer_category("find_person") == "search"

    def test_infer_category_list(self):
        """list系ツールのカテゴリ推測"""
        registry = self._make_registry()
        assert registry.infer_category("list_members") == "search"

    def test_infer_category_admin(self):
        """admin系ツールのカテゴリ推測"""
        registry = self._make_registry()
        assert registry.infer_category("admin_panel") == "admin"

    def test_infer_category_config(self):
        """config系ツールのカテゴリ推測"""
        registry = self._make_registry()
        assert registry.infer_category("config_update") == "admin"

    def test_infer_category_setting(self):
        """setting系ツールのカテゴリ推測"""
        registry = self._make_registry()
        assert registry.infer_category("setting_change") == "admin"

    def test_infer_category_external_api(self):
        """api系ツールのカテゴリ推測"""
        registry = self._make_registry()
        assert registry.infer_category("api_call") == "external"

    def test_infer_category_webhook(self):
        """webhook系ツールのカテゴリ推測"""
        registry = self._make_registry()
        assert registry.infer_category("webhook_handler") == "external"

    def test_infer_category_external(self):
        """external系ツールのカテゴリ推測"""
        registry = self._make_registry()
        assert registry.infer_category("external_sync") == "external"

    def test_infer_category_report(self):
        """report系ツールのカテゴリ推測"""
        registry = self._make_registry()
        assert registry.infer_category("report_daily") == "report"

    def test_infer_category_summary(self):
        """summary系ツールのカテゴリ推測"""
        registry = self._make_registry()
        assert registry.infer_category("summary_weekly") == "report"

    def test_infer_category_analytics(self):
        """analytics系ツールのカテゴリ推測"""
        registry = self._make_registry()
        assert registry.infer_category("analytics_dashboard") == "report"

    def test_infer_category_general(self):
        """不明なツール名はgeneralを返すこと"""
        registry = self._make_registry()
        assert registry.infer_category("something_unique_xyz") == "general"

    def test_get_all(self):
        """全メタデータの取得（lines 469-470）"""
        from lib.brain.tool_converter import ToolMetadata
        registry = self._make_registry()
        registry.register(ToolMetadata(name="tool1"))
        registry.register(ToolMetadata(name="tool2"))
        registry.register(ToolMetadata(name="tool3"))
        result = registry.get_all()
        assert len(result) == 3
        names = [m.name for m in result]
        assert "tool1" in names
        assert "tool2" in names
        assert "tool3" in names

    def test_get_tool_summary(self):
        """ツールサマリーの取得（lines 474-482）"""
        from lib.brain.tool_converter import ToolMetadata
        registry = self._make_registry()
        registry.register(ToolMetadata(name="task1", category="task", risk_level="low"))
        registry.register(ToolMetadata(name="task2", category="task", risk_level="high"))
        registry.register(ToolMetadata(name="search1", category="search", risk_level="low"))
        registry.register(ToolMetadata(name="old_tool", category="task", deprecated=True))
        summary = registry.get_tool_summary()
        assert summary["total_tools"] == 4
        assert "task" in summary["by_category"]
        assert len(summary["by_category"]["task"]) == 3  # task1, task2, old_tool
        assert len(summary["by_category"]["search"]) == 1
        assert summary["high_risk_count"] == 1
        assert summary["deprecated_count"] == 1
        assert "task" in summary["categories"]

    def test_get_tool_summary_empty(self):
        """空レジストリのサマリー"""
        registry = self._make_registry()
        summary = registry.get_tool_summary()
        assert summary["total_tools"] == 0
        assert summary["by_category"] == {}
        assert summary["high_risk_count"] == 0
        assert summary["deprecated_count"] == 0


# =============================================================================
# _ensure_loaded テスト（lines 441-465）
# =============================================================================


class TestEnsureLoaded:
    """_ensure_loaded メソッドのテスト"""

    def test_ensure_loaded_success(self):
        """SYSTEM_CAPABILITIESからの自動ロード成功（lines 441-461）"""
        from lib.brain.tool_converter import ToolMetadataRegistry
        mock_caps = {
            "chatwork_task_create": {
                "enabled": True,
                "category": "task",
                "requires_confirmation": False,
                "required_level": 2,
            },
            "send_message": {
                "enabled": True,
                # categoryがないのでinfer_categoryを使う
                "requires_confirmation": True,
                "required_level": 1,
            },
            "disabled_feature": {
                "enabled": False,
                "category": "test",
            },
        }
        registry = ToolMetadataRegistry()
        with patch('lib.brain.tool_converter.ToolMetadataRegistry._ensure_loaded') as mock_load:
            # 実際の_ensure_loadedの代わりに直接テスト
            pass

        # 直接テストする方法：patchしてSYSTEM_CAPABILITIESを差し替え
        registry = ToolMetadataRegistry()
        with patch.dict('sys.modules', {}):
            with patch('handlers.registry.SYSTEM_CAPABILITIES', mock_caps, create=True):
                registry._ensure_loaded()

        assert registry._loaded is True
        assert "chatwork_task_create" in registry._metadata
        assert "send_message" in registry._metadata
        # disabled は除外される
        assert "disabled_feature" not in registry._metadata

    def test_ensure_loaded_skip_if_already_loaded(self):
        """既にロード済みの場合はスキップすること（line 441-442）"""
        from lib.brain.tool_converter import ToolMetadataRegistry
        registry = ToolMetadataRegistry()
        registry._loaded = True
        registry._metadata = {"existing": "data"}
        registry._ensure_loaded()
        # 何も変わらない
        assert registry._metadata == {"existing": "data"}

    def test_ensure_loaded_handles_import_error(self):
        """import失敗時にエラーハンドリングすること（lines 463-465）"""
        from lib.brain.tool_converter import ToolMetadataRegistry
        registry = ToolMetadataRegistry()
        # handlers.registryのインポートが例外を投げる状況をシミュレート
        with patch.dict('sys.modules', {'handlers': None, 'handlers.registry': None}):
            registry._ensure_loaded()
        # エラーでも_loadedはTrueになる（再ロード防止）
        assert registry._loaded is True

    def test_ensure_loaded_infers_category_when_missing(self):
        """categoryが未設定の場合にinfer_categoryが使われること"""
        from lib.brain.tool_converter import ToolMetadataRegistry
        mock_caps = {
            "search_knowledge": {
                "enabled": True,
                # categoryなし
                "requires_confirmation": False,
                "required_level": 1,
            },
        }
        registry = ToolMetadataRegistry()
        with patch('handlers.registry.SYSTEM_CAPABILITIES', mock_caps, create=True):
            registry._ensure_loaded()
        assert registry._metadata["search_knowledge"].category == "search"


# =============================================================================
# get_tool_metadata_registry テスト（lines 498-500）
# =============================================================================


class TestGetToolMetadataRegistry:
    """get_tool_metadata_registry関数のテスト"""

    def test_returns_singleton(self):
        """シングルトンインスタンスを返すこと（lines 498-500）"""
        import lib.brain.tool_converter as tc
        # グローバルをリセット
        original = tc._metadata_registry
        tc._metadata_registry = None
        try:
            registry1 = tc.get_tool_metadata_registry()
            registry2 = tc.get_tool_metadata_registry()
            assert registry1 is registry2
            assert isinstance(registry1, tc.ToolMetadataRegistry)
        finally:
            tc._metadata_registry = original

    def test_creates_new_if_none(self):
        """Noneの場合に新規作成すること"""
        import lib.brain.tool_converter as tc
        original = tc._metadata_registry
        tc._metadata_registry = None
        try:
            registry = tc.get_tool_metadata_registry()
            assert registry is not None
            assert tc._metadata_registry is registry
        finally:
            tc._metadata_registry = original

    def test_returns_existing_if_set(self):
        """既存のインスタンスがある場合はそれを返すこと"""
        import lib.brain.tool_converter as tc
        original = tc._metadata_registry
        mock_registry = tc.ToolMetadataRegistry()
        tc._metadata_registry = mock_registry
        try:
            result = tc.get_tool_metadata_registry()
            assert result is mock_registry
        finally:
            tc._metadata_registry = original


# =============================================================================
# _build_description 追加テスト
# =============================================================================


class TestBuildDescription:
    """_build_description メソッドの追加テスト"""

    def test_category_in_description(self):
        """カテゴリ情報が説明に含まれること"""
        converter = ToolConverter()
        cap = {
            "description": "テスト機能",
            "category": "task",
            "trigger_examples": [],
        }
        desc = converter._build_description(cap)
        assert "カテゴリ: task" in desc

    def test_no_category(self):
        """カテゴリがない場合は含まれないこと"""
        converter = ToolConverter()
        cap = {
            "description": "テスト機能",
            "trigger_examples": [],
        }
        desc = converter._build_description(cap)
        assert "カテゴリ" not in desc

    def test_max_examples_limit(self):
        """max_examplesの制限が適用されること"""
        config = ToolConversionConfig(include_examples=True, max_examples=2)
        converter = ToolConverter(config)
        cap = {
            "description": "テスト",
            "trigger_examples": ["例1", "例2", "例3", "例4"],
        }
        desc = converter._build_description(cap)
        assert "例1" in desc
        assert "例2" in desc
        assert "例3" not in desc

    def test_no_description_key(self):
        """descriptionキーがない場合でもエラーにならないこと"""
        converter = ToolConverter()
        cap = {}
        desc = converter._build_description(cap)
        assert isinstance(desc, str)
