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
