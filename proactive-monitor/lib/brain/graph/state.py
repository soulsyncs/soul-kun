# lib/brain/graph/state.py
"""
LangGraph State 定義

Brain処理グラフを流れるデータの型定義。
各ノードはこのStateを受け取り、部分的な更新を返す。
"""

from typing import TypedDict, Optional, Dict, Any, List
from datetime import datetime


class BrainGraphState(TypedDict, total=False):
    """Brain LLM処理グラフの状態"""

    # === 入力（process_messageから渡される） ===
    message: str
    room_id: str
    account_id: str
    sender_name: str
    start_time: float
    organization_id: str

    # === コンテキスト ===
    # BrainContext（最小メタ情報）
    context: Any
    # ContextBuilder.build() の結果
    llm_context: Any
    # LLM用Toolカタログ
    tools: List[Any]

    # === 状態チェック ===
    current_state: Any  # Optional[ConversationState]
    has_active_session: bool
    has_pending_confirmation: bool

    # === LLM Brain結果 ===
    llm_result: Any  # LLMBrainResult
    confidence_value: float

    # === Guardian結果 ===
    guardian_result: Any  # GuardianResult
    guardian_action: str  # "allow", "block", "confirm", "modify"
    approval_result: Any  # Optional[ApprovalCheckResult] — Step 0-1 承認ゲート判定

    # === 実行 ===
    tool_calls_to_execute: Optional[List[Any]]
    decision: Any  # DecisionResult
    execution_result: Any  # HandlerResult
    needs_synthesis: bool

    # === 出力 ===
    response: Any  # BrainResponse
