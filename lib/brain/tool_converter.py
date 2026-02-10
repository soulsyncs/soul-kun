# lib/brain/tool_converter.py
"""
SYSTEM_CAPABILITIESをAnthropic Tool形式に変換する

設計書: docs/25_llm_native_brain_architecture.md セクション7.1b

【目的】
既存の SYSTEM_CAPABILITIES を活用し、LLM Brain用のTool定義を自動生成する。
これにより、新機能追加時も handlers/registry.py への追加だけで対応できる。

【変換マッピング】
| SYSTEM_CAPABILITIES フィールド | Anthropic Tool フィールド |
|------------------------------|---------------------------|
| key                          | name                      |
| description + trigger_examples| description               |
| params_schema                | input_schema.properties   |
| enabled                      | 変換対象判定              |
| requires_confirmation        | Guardian Layer用          |
| required_level               | Authorization Gate用      |

Author: Claude Opus 4.5
Created: 2026-01-30
"""

from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)


@dataclass
class ToolConversionConfig:
    """変換設定"""
    include_examples: bool = True           # トリガー例を含めるか
    max_examples: int = 5                   # 含めるトリガー例の最大数
    include_handler_metadata: bool = True   # ハンドラーメタデータを含めるか
    validate_schema: bool = True            # スキーマ検証を行うか


class ToolConverter:
    """
    SYSTEM_CAPABILITIESをAnthropic Tool形式に変換する

    設計書: docs/25_llm_native_brain_architecture.md セクション7.1b

    【使用例】
    converter = ToolConverter()
    tools = converter.convert_all(SYSTEM_CAPABILITIES)
    # tools は Anthropic API の tools パラメータに渡せる形式
    """

    # 型変換マッピング
    TYPE_MAPPING = {
        "string": "string",
        "str": "string",
        "int": "integer",
        "integer": "integer",
        "float": "number",
        "number": "number",
        "bool": "boolean",
        "boolean": "boolean",
        "list": "array",
        "array": "array",
        "dict": "object",
        "object": "object",
        "date": "string",      # 日付はstring（フォーマット指定で対応）
        "datetime": "string",
        "time": "string",      # 時刻もstring
    }

    def __init__(self, config: Optional[ToolConversionConfig] = None):
        self.config = config or ToolConversionConfig()

    def convert_all(
        self,
        capabilities: Dict[str, Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        全てのCapabilityをTool定義に変換

        Args:
            capabilities: SYSTEM_CAPABILITIES辞書

        Returns:
            Anthropic API形式のToolリスト
        """
        tools = []
        for key, capability in capabilities.items():
            # 無効な機能はスキップ
            if not capability.get("enabled", True):
                logger.debug(f"Skipping disabled capability: {key}")
                continue

            tool = self.convert_one(key, capability)
            if tool:
                tools.append(tool)
            else:
                logger.warning(f"Failed to convert capability: {key}")

        logger.info(f"Converted {len(tools)} capabilities to tools")
        return tools

    def convert_one(
        self,
        capability_key: str,
        capability: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """
        単一のCapabilityをTool定義に変換

        Args:
            capability_key: Capability名（例: "chatwork_task_create"）
            capability: Capability定義

        Returns:
            Anthropic Tool形式の辞書、失敗時はNone
        """
        try:
            # 説明文を構築
            description = self._build_description(capability)

            # パラメータスキーマを変換
            input_schema = self._convert_params_schema(
                capability.get("params_schema", {})
            )

            # スキーマ検証
            if self.config.validate_schema:
                if not self._validate_schema(input_schema):
                    logger.warning(f"Invalid schema for {capability_key}")
                    return None

            return {
                "name": capability_key,
                "description": description,
                "input_schema": input_schema,
            }

        except Exception as e:
            logger.error(f"Error converting {capability_key}: {type(e).__name__}")
            return None

    def _build_description(self, capability: Dict[str, Any]) -> str:
        """
        説明文を構築

        descriptionに加え、trigger_examplesを追記してLLMの理解を助ける
        """
        lines = [capability.get("description", "")]

        if self.config.include_examples:
            examples = capability.get("trigger_examples", [])
            if examples:
                lines.append("")
                lines.append("【使用例】")
                for ex in examples[:self.config.max_examples]:
                    lines.append(f"- 「{type(ex).__name__}」")

        # カテゴリ情報を追加
        category = capability.get("category")
        if category:
            lines.append("")
            lines.append(f"カテゴリ: {category}")

        return "\n".join(lines)

    def _convert_params_schema(
        self,
        params_schema: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        パラメータスキーマをJSON Schema形式に変換

        Args:
            params_schema: SYSTEM_CAPABILITIESのparams_schema

        Returns:
            JSON Schema形式の辞書
        """
        properties = {}
        required = []

        for param_name, param_def in params_schema.items():
            # 型変換
            soulkun_type = param_def.get("type", "string")
            json_type = self._convert_type(soulkun_type)

            property_def: Dict[str, Any] = {
                "type": json_type,
                "description": param_def.get("description", ""),
            }

            # 追加の注記があれば説明に追加
            note = param_def.get("note")
            if note:
                property_def["description"] += f"\n注意: {note}"

            # enumがあれば追加
            if "enum" in param_def:
                property_def["enum"] = param_def["enum"]

            # デフォルト値があれば追加
            if "default" in param_def:
                property_def["default"] = param_def["default"]

            # 日付/時刻の場合はフォーマットを追加
            if soulkun_type == "date":
                property_def["description"] += "\nフォーマット: YYYY-MM-DD"
            elif soulkun_type == "time":
                property_def["description"] += "\nフォーマット: HH:MM"
            elif soulkun_type == "datetime":
                property_def["description"] += "\nフォーマット: YYYY-MM-DDTHH:MM:SS"

            # 配列型の場合はitemsスキーマを追加（OpenAI/GPT必須）
            if json_type == "array":
                items_schema = param_def.get("items_schema")
                if items_schema:
                    # items_schemaをJSON Schema形式に変換
                    items_properties = {}
                    for item_key, item_desc in items_schema.items():
                        items_properties[item_key] = {
                            "type": "string",
                            "description": item_desc if isinstance(item_desc, str) else str(item_desc),
                        }
                    property_def["items"] = {
                        "type": "object",
                        "properties": items_properties,
                    }
                else:
                    # items_schemaがない場合はデフォルトで文字列配列
                    property_def["items"] = {"type": "string"}

            properties[param_name] = property_def

            # 必須判定
            if param_def.get("required", False):
                required.append(param_name)

        return {
            "type": "object",
            "properties": properties,
            "required": required,
        }

    def _convert_type(self, soulkun_type: str) -> str:
        """
        型をJSON Schema形式に変換

        Args:
            soulkun_type: SYSTEM_CAPABILITIESの型名

        Returns:
            JSON Schemaの型名
        """
        return self.TYPE_MAPPING.get(soulkun_type.lower(), "string")

    def _validate_schema(self, schema: Dict[str, Any]) -> bool:
        """
        スキーマの妥当性を検証

        Args:
            schema: 生成したJSON Schema

        Returns:
            妥当であればTrue
        """
        # 必須チェック
        if "type" not in schema:
            return False
        if "properties" not in schema:
            return False

        # 各プロパティの検証
        for prop_name, prop_def in schema.get("properties", {}).items():
            if "type" not in prop_def:
                logger.warning(f"Property {prop_name} missing type")
                return False

        return True


def get_tools_for_llm() -> List[Dict[str, Any]]:
    """
    LLM Brainに渡すTool定義を取得するファクトリ関数

    【使用例】
    tools = get_tools_for_llm()
    # tools を LLMBrain.process() に渡す

    Returns:
        Anthropic API形式のToolリスト
    """
    from handlers.registry import SYSTEM_CAPABILITIES

    converter = ToolConverter()
    return converter.convert_all(SYSTEM_CAPABILITIES)


# =============================================================================
# Task #12: Tool Converter機能拡張
# =============================================================================

@dataclass
class ToolMetadata:
    """
    Tool拡張メタデータ

    Guardian LayerやAuthorization Gateが使用する追加情報
    """
    name: str
    category: str = "general"
    risk_level: str = "low"  # low, medium, high, critical
    requires_confirmation: bool = False
    required_permission_level: int = 1  # 1-6
    dependencies: List[str] = field(default_factory=list)  # 依存するTool名
    version: str = "1.0.0"
    deprecated: bool = False
    deprecation_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "risk_level": self.risk_level,
            "requires_confirmation": self.requires_confirmation,
            "required_permission_level": self.required_permission_level,
            "dependencies": self.dependencies,
            "version": self.version,
            "deprecated": self.deprecated,
            "deprecation_message": self.deprecation_message,
        }


class ToolMetadataRegistry:
    """
    Tool拡張メタデータのレジストリ

    Task #12: Tool Converter機能拡張

    【目的】
    - Tool のカテゴリ分類
    - リスクレベル管理
    - 依存関係マッピング
    - バージョン管理
    """

    # カテゴリ定義
    CATEGORIES = {
        "task": "タスク管理",
        "goal": "目標管理",
        "message": "メッセージ送信",
        "search": "検索・照会",
        "memory": "記憶管理",
        "admin": "管理機能",
        "external": "外部連携",
        "report": "レポート生成",
    }

    # デフォルトのリスクレベルマッピング
    DEFAULT_RISK_LEVELS = {
        # 高リスク（削除・変更系）
        "delete": "high",
        "remove": "high",
        "update": "medium",
        "modify": "medium",
        # 中リスク（作成・送信系）
        "create": "medium",
        "send": "medium",
        "post": "medium",
        # 低リスク（検索・取得系）
        "search": "low",
        "get": "low",
        "list": "low",
        "find": "low",
    }

    def __init__(self):
        self._metadata: Dict[str, ToolMetadata] = {}
        self._loaded = False

    def register(self, metadata: ToolMetadata) -> None:
        """Toolメタデータを登録"""
        self._metadata[metadata.name] = metadata
        logger.debug(f"Registered tool metadata: {metadata.name}")

    def get(self, tool_name: str) -> Optional[ToolMetadata]:
        """Toolメタデータを取得"""
        self._ensure_loaded()
        return self._metadata.get(tool_name)

    def get_by_category(self, category: str) -> List[ToolMetadata]:
        """カテゴリ別にToolを取得"""
        self._ensure_loaded()
        return [m for m in self._metadata.values() if m.category == category]

    def get_high_risk_tools(self) -> List[ToolMetadata]:
        """高リスクToolを取得"""
        self._ensure_loaded()
        return [m for m in self._metadata.values() if m.risk_level in ["high", "critical"]]

    def get_deprecated_tools(self) -> List[ToolMetadata]:
        """非推奨Toolを取得"""
        self._ensure_loaded()
        return [m for m in self._metadata.values() if m.deprecated]

    def infer_risk_level(self, tool_name: str) -> str:
        """Tool名からリスクレベルを推測"""
        tool_lower = tool_name.lower()
        for keyword, risk in self.DEFAULT_RISK_LEVELS.items():
            if keyword in tool_lower:
                return risk
        return "low"

    def infer_category(self, tool_name: str) -> str:
        """Tool名からカテゴリを推測"""
        tool_lower = tool_name.lower()

        if "task" in tool_lower:
            return "task"
        elif "goal" in tool_lower:
            return "goal"
        elif any(k in tool_lower for k in ["message", "send", "post", "announce"]):
            return "message"
        # memory を search より先にチェック（"forget"が"get"を含むため）
        elif any(k in tool_lower for k in ["memory", "remember", "forget"]):
            return "memory"
        elif any(k in tool_lower for k in ["search", "find", "get", "list"]):
            return "search"
        elif any(k in tool_lower for k in ["admin", "config", "setting"]):
            return "admin"
        elif any(k in tool_lower for k in ["api", "webhook", "external"]):
            return "external"
        elif any(k in tool_lower for k in ["report", "summary", "analytics"]):
            return "report"
        else:
            return "general"

    def _ensure_loaded(self) -> None:
        """SYSTEM_CAPABILITIESから自動ロード"""
        if self._loaded:
            return

        try:
            from handlers.registry import SYSTEM_CAPABILITIES

            for key, cap in SYSTEM_CAPABILITIES.items():
                if not cap.get("enabled", True):
                    continue

                metadata = ToolMetadata(
                    name=key,
                    category=cap.get("category", self.infer_category(key)),
                    risk_level=self.infer_risk_level(key),
                    requires_confirmation=cap.get("requires_confirmation", False),
                    required_permission_level=cap.get("required_level", 1),
                )
                self.register(metadata)

            self._loaded = True
            logger.info(f"Loaded {len(self._metadata)} tool metadata entries")

        except Exception as e:
            logger.warning(f"Failed to load SYSTEM_CAPABILITIES: {type(e).__name__}")
            self._loaded = True  # エラー時も再ロードしない

    def get_all(self) -> List[ToolMetadata]:
        """全Toolメタデータを取得"""
        self._ensure_loaded()
        return list(self._metadata.values())

    def get_tool_summary(self) -> Dict[str, Any]:
        """Toolサマリーを取得"""
        self._ensure_loaded()

        categories: Dict[str, List[str]] = {}
        for m in self._metadata.values():
            if m.category not in categories:
                categories[m.category] = []
            categories[m.category].append(m.name)

        return {
            "total_tools": len(self._metadata),
            "by_category": categories,
            "high_risk_count": len(self.get_high_risk_tools()),
            "deprecated_count": len(self.get_deprecated_tools()),
            "categories": list(self.CATEGORIES.keys()),
        }


# グローバルレジストリインスタンス
_metadata_registry: Optional[ToolMetadataRegistry] = None


def get_tool_metadata_registry() -> ToolMetadataRegistry:
    """Toolメタデータレジストリを取得（シングルトン）"""
    global _metadata_registry
    if _metadata_registry is None:
        _metadata_registry = ToolMetadataRegistry()
    return _metadata_registry


def get_tool_metadata(tool_name: str) -> Optional[Dict[str, Any]]:
    """
    Tool名からメタデータを取得

    Guardian Layerで使用（requires_confirmation, risk_level等）

    Args:
        tool_name: Tool名（例: "chatwork_task_create"）

    Returns:
        Capability定義、存在しない場合はNone
    """
    from handlers.registry import SYSTEM_CAPABILITIES

    result: Optional[Dict[str, Any]] = SYSTEM_CAPABILITIES.get(tool_name)
    return result


def is_dangerous_operation(tool_name: str) -> tuple[bool, str]:
    """
    危険操作かどうかを判定

    Args:
        tool_name: Tool名

    Returns:
        (is_dangerous, risk_level)のタプル
    """
    metadata = get_tool_metadata(tool_name)
    if not metadata:
        return (False, "unknown")

    brain_metadata = metadata.get("brain_metadata", {})
    risk_level = brain_metadata.get("risk_level", "low")

    is_dangerous = risk_level in ["high", "critical"]
    return (is_dangerous, risk_level)


def requires_confirmation(tool_name: str) -> bool:
    """
    確認が必要な操作かどうかを判定

    Args:
        tool_name: Tool名

    Returns:
        確認が必要ならTrue
    """
    metadata = get_tool_metadata(tool_name)
    if not metadata:
        return True  # 不明な場合は安全側に倒す

    requires: bool = metadata.get("requires_confirmation", False)
    return requires
