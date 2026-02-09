# lib/brain/autonomous/tool_registry.py
"""
Phase AA: ツールレジストリ

自律エージェントが使用可能なツールを管理する。
既存の機能（handlers/）をツールとして登録し、
Brainが自律的にツールを選択・実行できるようにする。

CLAUDE.md §1: 全機能はBrainを通る
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# =========================================================================
# データモデル
# =========================================================================


@dataclass
class AvailableTool:
    """利用可能なツール"""
    name: str
    description: str
    category: str = "general"  # research, communication, analysis, management
    required_params: List[str] = field(default_factory=list)
    optional_params: List[str] = field(default_factory=list)
    handler: Optional[Callable] = None
    requires_confirmation: bool = False
    max_execution_time_sec: int = 60

    def to_dict(self) -> Dict[str, Any]:
        """辞書に変換（LLMへの提示用）"""
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "required_params": self.required_params,
            "optional_params": self.optional_params,
            "requires_confirmation": self.requires_confirmation,
        }


# =========================================================================
# ツールレジストリ
# =========================================================================


class ToolRegistry:
    """
    ツールレジストリ

    自律エージェントが使用可能なツールを登録・検索・実行する。
    """

    def __init__(self):
        self._tools: Dict[str, AvailableTool] = {}

    def register(self, tool: AvailableTool) -> None:
        """
        ツールを登録

        Args:
            tool: 登録するツール
        """
        self._tools[tool.name] = tool
        logger.debug("Tool registered: %s", tool.name)

    def get(self, name: str) -> Optional[AvailableTool]:
        """
        ツールを取得

        Args:
            name: ツール名

        Returns:
            ツール（見つからない場合はNone）
        """
        return self._tools.get(name)

    def list_tools(
        self,
        category: Optional[str] = None,
    ) -> List[AvailableTool]:
        """
        ツール一覧を取得

        Args:
            category: カテゴリでフィルタ

        Returns:
            ツールのリスト
        """
        tools = list(self._tools.values())
        if category:
            tools = [t for t in tools if t.category == category]
        return tools

    def list_for_llm(self) -> List[Dict[str, Any]]:
        """LLMに提示するためのツール一覧"""
        return [tool.to_dict() for tool in self._tools.values()]

    @property
    def count(self) -> int:
        """登録済みツール数"""
        return len(self._tools)


# =========================================================================
# デフォルトツール登録
# =========================================================================


def create_default_registry() -> ToolRegistry:
    """
    デフォルトのツールレジストリを作成

    既存の機能（handlers/）からツールを登録する。

    Returns:
        初期ツールが登録済みのレジストリ
    """
    registry = ToolRegistry()

    # リサーチ系
    registry.register(AvailableTool(
        name="knowledge_search",
        description="社内ナレッジを検索する",
        category="research",
        required_params=["query"],
        optional_params=["department_id", "classification"],
    ))

    # コミュニケーション系
    registry.register(AvailableTool(
        name="send_message",
        description="ChatWorkにメッセージを送信する",
        category="communication",
        required_params=["room_id", "message"],
        requires_confirmation=True,
    ))

    registry.register(AvailableTool(
        name="send_reminder",
        description="リマインダーを送信する",
        category="communication",
        required_params=["room_id", "user_id", "message"],
        requires_confirmation=True,
    ))

    # 分析系
    registry.register(AvailableTool(
        name="generate_report",
        description="日報・週報などのレポートを生成する",
        category="analysis",
        required_params=["report_type"],
        optional_params=["date_range", "user_id"],
    ))

    registry.register(AvailableTool(
        name="goal_analysis",
        description="目標の進捗を分析する",
        category="analysis",
        required_params=["user_id"],
        optional_params=["goal_id"],
    ))

    # 管理系
    registry.register(AvailableTool(
        name="task_create",
        description="タスクを作成する",
        category="management",
        required_params=["title", "room_id"],
        optional_params=["assignee", "due_date", "description"],
    ))

    registry.register(AvailableTool(
        name="task_update",
        description="タスクのステータスを更新する",
        category="management",
        required_params=["task_id", "status"],
    ))

    logger.info("Default tool registry created: %d tools", registry.count)
    return registry
