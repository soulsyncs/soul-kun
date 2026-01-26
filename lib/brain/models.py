# lib/brain/models.py
"""
ソウルくんの脳 - データモデル定義

このファイルには、脳アーキテクチャで使用する全てのデータモデルを定義します。
各モデルは、脳の各層間でデータを受け渡すために使用されます。

設計書: docs/13_brain_architecture.md
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any
from uuid import UUID


# =============================================================================
# 列挙型（Enum）
# =============================================================================


class MemoryType(str, Enum):
    """記憶の種類"""

    CURRENT_STATE = "current_state"           # 現在の状態
    RECENT_CONVERSATION = "recent_conversation"  # 直近の会話
    CONVERSATION_SUMMARY = "conversation_summary"  # 会話要約
    USER_PREFERENCES = "user_preferences"     # ユーザー嗜好
    PERSON_INFO = "person_info"              # 人物情報
    RECENT_TASKS = "recent_tasks"            # タスク情報
    ACTIVE_GOALS = "active_goals"            # 目標情報
    RELEVANT_KNOWLEDGE = "relevant_knowledge"  # 会社知識
    INSIGHTS = "insights"                    # インサイト
    CONVERSATION_SEARCH = "conversation_search"  # 会話検索


class StateType(str, Enum):
    """会話状態の種類"""

    NORMAL = "normal"                # 通常状態（状態なし）
    GOAL_SETTING = "goal_setting"    # 目標設定対話中
    ANNOUNCEMENT = "announcement"    # アナウンス確認中
    CONFIRMATION = "confirmation"    # 確認待ち
    TASK_PENDING = "task_pending"    # タスク作成待ち
    MULTI_ACTION = "multi_action"    # 複数アクション実行中


class UrgencyLevel(str, Enum):
    """緊急度レベル"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ConfidenceLevel(str, Enum):
    """確信度レベル"""

    VERY_LOW = "very_low"    # 0.0 - 0.3
    LOW = "low"              # 0.3 - 0.5
    MEDIUM = "medium"        # 0.5 - 0.7
    HIGH = "high"            # 0.7 - 0.9
    VERY_HIGH = "very_high"  # 0.9 - 1.0

    @classmethod
    def from_score(cls, score: float) -> "ConfidenceLevel":
        """スコアから確信度レベルを判定"""
        if score < 0.3:
            return cls.VERY_LOW
        elif score < 0.5:
            return cls.LOW
        elif score < 0.7:
            return cls.MEDIUM
        elif score < 0.9:
            return cls.HIGH
        else:
            return cls.VERY_HIGH


# =============================================================================
# 記憶層のモデル
# =============================================================================


@dataclass
class ConversationMessage:
    """会話メッセージ"""

    role: str                    # "user" or "assistant"
    content: str                 # メッセージ内容
    timestamp: datetime          # 送信時刻
    message_id: Optional[str] = None
    sender_name: Optional[str] = None


@dataclass
class SummaryData:
    """会話要約データ"""

    summary: str                 # 要約テキスト
    key_topics: List[str]        # 主要トピック
    mentioned_persons: List[str]  # 言及された人物
    mentioned_tasks: List[str]   # 言及されたタスク
    created_at: datetime


@dataclass
class PreferenceData:
    """ユーザー嗜好データ"""

    response_style: Optional[str] = None      # 応答スタイル
    feature_usage: Dict[str, int] = field(default_factory=dict)  # 機能使用状況
    preferred_times: List[str] = field(default_factory=list)     # 好みの時間帯
    custom_keywords: Dict[str, str] = field(default_factory=dict)  # カスタムキーワード


@dataclass
class PersonInfo:
    """人物情報"""

    person_id: str
    name: str                    # 名前
    chatwork_account_id: Optional[str] = None
    department: Optional[str] = None
    role: Optional[str] = None
    known_info: Dict[str, Any] = field(default_factory=dict)  # その他の情報


@dataclass
class TaskInfo:
    """タスク情報"""

    task_id: str
    body: str                    # タスク内容
    summary: Optional[str] = None  # AI生成の要約
    assignee_name: Optional[str] = None
    due_date: Optional[datetime] = None
    status: str = "open"         # open, done
    room_id: Optional[str] = None
    room_name: Optional[str] = None


@dataclass
class GoalInfo:
    """目標情報"""

    goal_id: str
    why: Optional[str] = None    # なぜその目標か
    what: Optional[str] = None   # 何を達成するか
    how: Optional[str] = None    # どうやって達成するか
    due_date: Optional[datetime] = None
    status: str = "active"


@dataclass
class GoalSessionInfo:
    """目標設定セッション情報"""

    session_id: str
    current_step: str            # intro, why, what, how
    retry_count: int = 0
    created_at: datetime = field(default_factory=datetime.now)
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class KnowledgeChunk:
    """知識チャンク"""

    chunk_id: str
    content: str                 # チャンク内容
    source: str                  # 出典
    relevance_score: float       # 関連度スコア
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class InsightInfo:
    """インサイト情報"""

    insight_id: str
    insight_type: str            # frequent_question, stagnant_task, etc.
    title: str
    description: str
    severity: str                # critical, high, medium, low
    created_at: datetime


# =============================================================================
# 状態管理のモデル
# =============================================================================


@dataclass
class ConversationState:
    """会話状態"""

    state_id: Optional[str] = None
    organization_id: str = ""
    room_id: str = ""
    user_id: str = ""
    state_type: StateType = StateType.NORMAL
    state_step: Optional[str] = None    # 状態内のステップ（例: why, what, how）
    state_data: Dict[str, Any] = field(default_factory=dict)
    reference_type: Optional[str] = None  # 参照先タイプ（goal_session, announcement等）
    reference_id: Optional[str] = None    # 参照先ID
    expires_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    @property
    def is_active(self) -> bool:
        """アクティブな状態かどうか"""
        if self.state_type == StateType.NORMAL:
            return False
        if self.expires_at and datetime.now() > self.expires_at:
            return False
        return True

    @property
    def is_expired(self) -> bool:
        """期限切れかどうか"""
        if self.expires_at is None:
            return False
        return datetime.now() > self.expires_at


# =============================================================================
# 統合コンテキスト（脳が参照する全情報）
# =============================================================================


@dataclass
class BrainContext:
    """
    脳が参照する統合コンテキスト

    全ての記憶を統合した情報。脳はこれを参照して判断を行う。
    """

    # 現在の状態（最優先）
    current_state: Optional[ConversationState] = None

    # 会話関連
    recent_conversation: List[ConversationMessage] = field(default_factory=list)
    conversation_summary: Optional[SummaryData] = None

    # ユーザー関連
    user_preferences: Optional[PreferenceData] = None
    sender_name: str = ""
    sender_account_id: str = ""

    # 人物・タスク関連
    person_info: List[PersonInfo] = field(default_factory=list)
    recent_tasks: List[TaskInfo] = field(default_factory=list)

    # 目標関連
    active_goals: List[GoalInfo] = field(default_factory=list)
    goal_session: Optional[GoalSessionInfo] = None

    # 知識関連（遅延取得）
    relevant_knowledge: Optional[List[KnowledgeChunk]] = None

    # インサイト関連
    insights: List[InsightInfo] = field(default_factory=list)

    # メタデータ
    organization_id: str = ""
    room_id: str = ""
    timestamp: datetime = field(default_factory=datetime.now)

    def has_active_session(self) -> bool:
        """マルチステップセッションが進行中か"""
        return self.current_state is not None and self.current_state.is_active

    def get_recent_task_names(self) -> List[str]:
        """直近のタスク名リストを取得"""
        result = []
        for t in self.recent_tasks[:5]:
            if isinstance(t, dict):
                summary = t.get('summary') or t.get('body', '')[:50]
            else:
                summary = t.summary or (t.body[:50] if hasattr(t, 'body') else '')
            result.append(summary)
        return result

    def get_known_persons(self) -> List[str]:
        """記憶している人物名リストを取得"""
        return [p.name for p in self.person_info]

    def to_prompt_context(self) -> str:
        """
        LLMプロンプト用のコンテキスト文字列を生成

        脳の理解層・判断層がLLMを呼び出す際に使用する。
        """
        parts = []

        # 現在の状態
        if self.current_state and self.current_state.is_active:
            parts.append(f"【現在の状態】{self.current_state.state_type.value}")
            if self.current_state.state_step:
                parts.append(f"  ステップ: {self.current_state.state_step}")

        # 送信者情報
        parts.append(f"【送信者】{self.sender_name}")

        # 直近の会話
        if self.recent_conversation:
            parts.append("【直近の会話】")
            for msg in self.recent_conversation[-5:]:  # 最新5件
                role = "ユーザー" if msg.role == "user" else "ソウルくん"
                parts.append(f"  {role}: {msg.content[:100]}")

        # 会話要約
        if self.conversation_summary:
            parts.append(f"【過去の話題】{', '.join(self.conversation_summary.key_topics[:3])}")

        # ユーザー嗜好
        if self.user_preferences and self.user_preferences.response_style:
            parts.append(f"【応答スタイル】{self.user_preferences.response_style}")

        # 直近のタスク
        if self.recent_tasks:
            parts.append("【関連タスク】")
            for task in self.recent_tasks[:3]:
                if isinstance(task, dict):
                    task_name = task.get('summary') or task.get('body', '')[:40]
                    task_status = task.get('status', 'unknown')
                else:
                    task_name = task.summary or (task.body[:40] if hasattr(task, 'body') else '')
                    task_status = task.status if hasattr(task, 'status') else 'unknown'
                parts.append(f"  - {task_name} ({task_status})")

        # 目標
        if self.active_goals:
            parts.append("【進行中の目標】")
            for goal in self.active_goals[:2]:
                parts.append(f"  - {goal.what}")

        # 記憶している人物
        if self.person_info:
            names = [p.name for p in self.person_info[:5]]
            parts.append(f"【記憶している人物】{', '.join(names)}")

        return "\n".join(parts)


# =============================================================================
# 理解層のモデル
# =============================================================================


@dataclass
class ResolvedEntity:
    """解決されたエンティティ"""

    original: str                # 元の表現
    resolved: str                # 解決後の表現
    entity_type: str             # person, task, time, etc.
    source: str                  # 解決に使った情報源
    confidence: float = 1.0


@dataclass
class UnderstandingResult:
    """
    理解層の出力

    ユーザーの入力を理解した結果。
    """

    # 元のメッセージ
    raw_message: str

    # 推論した意図
    intent: str                  # 例: "search_tasks", "create_task", "ask_knowledge"
    intent_confidence: float     # 0.0 - 1.0

    # 解決されたエンティティ
    entities: Dict[str, Any] = field(default_factory=dict)
    # {
    #   "person": "菊地",
    #   "task": "経費精算",
    #   "time": "2026-01-27T00:00:00",
    #   "urgency": "high"
    # }

    # 曖昧性の解決結果
    resolved_ambiguities: List[ResolvedEntity] = field(default_factory=list)

    # 確認が必要か
    needs_confirmation: bool = False
    confirmation_reason: Optional[str] = None
    confirmation_options: List[str] = field(default_factory=list)

    # 推論の理由（デバッグ用）
    reasoning: str = ""

    # 処理時間
    processing_time_ms: int = 0

    @property
    def confidence_level(self) -> ConfidenceLevel:
        """確信度レベルを取得"""
        return ConfidenceLevel.from_score(self.intent_confidence)


# =============================================================================
# 判断層のモデル
# =============================================================================


@dataclass
class ActionCandidate:
    """アクション候補"""

    action: str                  # アクション名（SYSTEM_CAPABILITIESのキー）
    score: float                 # マッチスコア
    params: Dict[str, Any] = field(default_factory=dict)
    reasoning: str = ""          # この候補を選んだ理由


@dataclass
class DecisionResult:
    """
    判断層の出力

    どのアクションを実行するかの決定結果。
    """

    # 選択されたアクション
    action: str                  # アクション名
    params: Dict[str, Any] = field(default_factory=dict)

    # 確信度
    confidence: float = 0.0

    # 確認が必要か
    needs_confirmation: bool = False
    confirmation_question: Optional[str] = None
    confirmation_options: List[str] = field(default_factory=list)

    # 他の候補（デバッグ用）
    other_candidates: List[ActionCandidate] = field(default_factory=list)

    # 判断の理由
    reasoning: str = ""

    # 処理時間
    processing_time_ms: int = 0


# =============================================================================
# 実行層のモデル
# =============================================================================


@dataclass
class HandlerResult:
    """
    ハンドラーの実行結果

    各機能ハンドラーが返す標準化された結果。
    """

    # 成功/失敗
    success: bool
    message: str                 # 表示するメッセージ
    data: Dict[str, Any] = field(default_factory=dict)  # 追加データ

    # 次のアクション（連続実行用）
    next_action: Optional[str] = None
    next_params: Optional[Dict[str, Any]] = None

    # 状態変更
    update_state: Optional[Dict[str, Any]] = None

    # 提案（先読み）
    suggestions: List[str] = field(default_factory=list)

    # エラー情報（失敗時）
    error_code: Optional[str] = None
    error_details: Optional[str] = None


# =============================================================================
# 確認リクエスト
# =============================================================================


@dataclass
class ConfirmationRequest:
    """確認リクエスト"""

    question: str                # 確認の質問
    options: List[str]           # 選択肢
    default_option: Optional[str] = None  # デフォルト選択肢
    timeout_seconds: int = 300   # タイムアウト（5分）

    # 確認後の処理
    on_confirm_action: str = ""  # 確認OKの場合のアクション
    on_confirm_params: Dict[str, Any] = field(default_factory=dict)

    def to_message(self) -> str:
        """ChatWorkメッセージに変換"""
        options_str = "\n".join(
            f"{i}. {opt}" for i, opt in enumerate(self.options, 1)
        )
        return f"""🤔 確認させてほしいウル！

{self.question}

{options_str}

番号で教えてほしいウル🐺"""


# =============================================================================
# 脳の最終出力
# =============================================================================


@dataclass
class BrainResponse:
    """
    脳の最終レスポンス

    process_message()の戻り値。
    """

    # 表示するメッセージ
    message: str

    # 実行されたアクション
    action_taken: str = "none"
    action_params: Dict[str, Any] = field(default_factory=dict)

    # 成功/失敗
    success: bool = True

    # 提案（先読み）
    suggestions: List[str] = field(default_factory=list)

    # 状態変更があったか
    state_changed: bool = False
    new_state: Optional[str] = None

    # 確認モード中か
    awaiting_confirmation: bool = False

    # デバッグ情報
    debug_info: Dict[str, Any] = field(default_factory=dict)

    # 処理時間
    total_time_ms: int = 0
