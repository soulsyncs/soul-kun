# lib/brain/tool_executor.py
"""
Tool Executor - Function Callingで選択されたToolを実行する薄いラッパー

LangGraph の execute_tool ノードから DecisionResult アダプターを分離し、
ToolCall → handler の実行を一元管理する。

設計書: docs/25_llm_native_brain_architecture.md セクション5.6

【設計方針】
- ToolCall（新形式）を直接受け取り、既存の BrainExecution 実行層に委譲
- LangGraph ノード（execute_tool.py）を DecisionResult 変換から解放
- 将来的に BrainExecution を直接置き換え可能な拡張点

Author: Claude Sonnet 4.6
Created: 2026-02-22
"""

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from lib.brain.core import SoulkunBrain

from lib.brain.llm_brain import ToolCall
from lib.brain.models import DecisionResult
from lib.brain.execution import ExecutionResult

logger = logging.getLogger(__name__)


@dataclass
class ToolExecutionOutcome:
    """
    ToolExecutor.execute() の戻り値

    result: 実行層の実行結果（BrainExecution が返す ExecutionResult）
    decision: 実行に使われた DecisionResult（LangGraph state["decision"] 用）
    """
    result: ExecutionResult
    decision: DecisionResult


class ToolExecutor:
    """
    Tool実行層 - Function Callingで選択されたToolを実行

    設計書: docs/25_llm_native_brain_architecture.md セクション5.6

    【責務】
    - ToolCall（LLM Brain が生成した新形式）を受け取る
    - 内部で DecisionResult（既存実行層の形式）へ変換
    - brain._execute() に委譲して ExecutionResult を取得
    - 変換後の decision を ToolExecutionOutcome に含めて返却
      （LangGraph state["decision"] への格納に使用）

    【使用場所】
    - lib/brain/graph/nodes/execute_tool.py（LangGraph ノード）

    NOTE: このクラスに到達する ToolCall は GuardianLayer/ApprovalGate で
    承認済みのものだけです。再確認フローは発生しません。
    """

    def __init__(self, brain: "SoulkunBrain") -> None:
        self._brain = brain

    async def execute(
        self,
        tool_call: ToolCall,
        context: Any,  # BrainContext (循環import回避のため Any)
        room_id: str,
        account_id: str,
        sender_name: str,
        confidence: float = 0.8,
    ) -> ToolExecutionOutcome:
        """
        ToolCallを実行して ToolExecutionOutcome を返す。

        内部で DecisionResult に変換して brain._execute() に委譲する。
        変換後の DecisionResult を outcome.decision に含めて返すため、
        呼び出し元（LangGraph ノード）が state["decision"] に設定できる。

        Args:
            tool_call: LLM Brainが選択したToolとパラメータ
            context: BrainContext (room/user/conversation情報)
            room_id: 実行対象のルームID
            account_id: 実行者のアカウントID
            sender_name: 実行者の表示名
            confidence: 確信度（デフォルト 0.8）

        Returns:
            ToolExecutionOutcome: 実行結果と decision のペア
        """
        # ToolCall → DecisionResult 変換（アダプター）
        decision = DecisionResult(
            action=tool_call.tool_name,
            params=tool_call.parameters,
            confidence=confidence,
            needs_confirmation=False,  # Guardian/ApprovalGateで確認済み
        )
        logger.debug(
            "[tool_executor] executing: tool=%s confidence=%.2f",
            tool_call.tool_name,
            confidence,
        )

        # 既存の BrainExecution 実行層に委譲
        result = await self._brain._execute(
            decision=decision,
            context=context,
            room_id=room_id,
            account_id=account_id,
            sender_name=sender_name,
        )

        return ToolExecutionOutcome(result=result, decision=decision)
