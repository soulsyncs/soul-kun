# lib/brain/__init__.py
"""
ソウルくんの脳アーキテクチャ

このモジュールは、ソウルくんの中央処理装置（脳）を提供します。
全てのユーザー入力は、まずこの脳を通って処理されます。

設計書: docs/13_brain_architecture.md

【7つの鉄則】
1. 全ての入力は脳を通る（バイパスルート禁止）
2. 脳は全ての記憶にアクセスできる
3. 脳が判断し、機能は実行するだけ
4. 機能拡張しても脳の構造は変わらない
5. 確認は脳の責務
6. 状態管理は脳が統一管理
7. 速度より正確性を優先

使用例:
    from lib.brain import SoulkunBrain, BrainResponse

    brain = SoulkunBrain(pool=db_pool, org_id="org_soulsyncs")
    response = await brain.process_message(
        message="自分のタスク教えて",
        room_id="123456",
        account_id="7890",
        sender_name="菊地"
    )
    print(response.message)  # タスク一覧を表示
"""

from lib.brain.models import (
    BrainContext,
    BrainResponse,
    UnderstandingResult,
    DecisionResult,
    HandlerResult,
    ConversationState,
    ConfirmationRequest,
    ActionCandidate,
    MemoryType,
    StateType,
)

from lib.brain.core import SoulkunBrain

from lib.brain.state_manager import BrainStateManager

from lib.brain.memory_access import (
    BrainMemoryAccess,
    ConversationMessage,
    ConversationSummaryData,
    UserPreferenceData,
    PersonInfo,
    TaskInfo,
    GoalInfo,
    KnowledgeInfo,
    InsightInfo,
)

from lib.brain.exceptions import (
    BrainError,
    UnderstandingError,
    DecisionError,
    ExecutionError,
    StateError,
    MemoryAccessError,
    ConfirmationTimeoutError,
)

from lib.brain.constants import (
    CANCEL_KEYWORDS,
    CONFIRMATION_THRESHOLD,
    SESSION_TIMEOUT_MINUTES,
    MAX_RETRY_COUNT,
)

__all__ = [
    # メインクラス
    "SoulkunBrain",
    # 状態管理層
    "BrainStateManager",
    # 記憶アクセス層
    "BrainMemoryAccess",
    "ConversationMessage",
    "ConversationSummaryData",
    "UserPreferenceData",
    "PersonInfo",
    "TaskInfo",
    "GoalInfo",
    "KnowledgeInfo",
    "InsightInfo",
    # データモデル
    "BrainContext",
    "BrainResponse",
    "UnderstandingResult",
    "DecisionResult",
    "HandlerResult",
    "ConversationState",
    "ConfirmationRequest",
    "ActionCandidate",
    # Enum
    "MemoryType",
    "StateType",
    # 例外
    "BrainError",
    "UnderstandingError",
    "DecisionError",
    "ExecutionError",
    "StateError",
    "MemoryAccessError",
    "ConfirmationTimeoutError",
    # 定数
    "CANCEL_KEYWORDS",
    "CONFIRMATION_THRESHOLD",
    "SESSION_TIMEOUT_MINUTES",
    "MAX_RETRY_COUNT",
]

__version__ = "1.0.0"
