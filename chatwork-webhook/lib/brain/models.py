# lib/brain/models.py
"""
ソウルくんの脳 - データモデル定義

このファイルには、脳アーキテクチャで使用する全てのデータモデルを定義します。
各モデルは、脳の各層間でデータを受け渡すために使用されます。

設計書: docs/13_brain_architecture.md
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Optional, List, Dict, Any, Union
from uuid import UUID

if TYPE_CHECKING:
    from .episodic_memory import RecallResult


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
    # v10.56.2: 一覧表示後の文脈保持
    LIST_CONTEXT = "list_context"    # 一覧表示後（次の入力は番号指定と解釈）


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


@dataclass
class Confidence:
    """
    確信度（統一版）

    型安全な確信度表現。本番障害（型の不整合）を防ぐために導入。
    floatとの互換性を維持しつつ、明示的な型として扱う。

    SoT: このファイル（lib/brain/models.py）

    使用例:
        confidence = Confidence(0.85)
        confidence = Confidence(0.85, "意図が明確")

        # float として比較可能
        if confidence.overall > 0.7:
            ...

        # 辞書化
        data = confidence.to_dict()
    """

    overall: float = 0.0
    """総合確信度（0.0 - 1.0）"""

    reasoning: Optional[str] = None
    """確信度の根拠（オプション）"""

    intent_confidence: Optional[float] = None
    """意図理解の確信度（オプション）"""

    entity_confidence: Optional[float] = None
    """エンティティ解決の確信度（オプション）"""

    def __post_init__(self) -> None:
        """バリデーション"""
        if not isinstance(self.overall, (int, float)):
            raise TypeError(f"overall must be a number, got {type(self.overall).__name__}")
        if not 0.0 <= self.overall <= 1.0:
            raise ValueError(f"overall must be between 0.0 and 1.0, got {self.overall}")

    @property
    def level(self) -> ConfidenceLevel:
        """確信度レベルを取得"""
        return ConfidenceLevel.from_score(self.overall)

    @property
    def is_high(self) -> bool:
        """高確信度か（0.7以上）"""
        return self.overall >= 0.7

    @property
    def is_low(self) -> bool:
        """低確信度か（0.5未満）"""
        return self.overall < 0.5

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "overall": self.overall,
            "level": self.level.value,
            "reasoning": self.reasoning,
            "intent_confidence": self.intent_confidence,
            "entity_confidence": self.entity_confidence,
        }

    @classmethod
    def from_value(cls, value: Union[float, int, "Confidence", Dict[str, Any]]) -> "Confidence":
        """
        様々な型から Confidence を生成（後方互換性）

        Args:
            value: float, int, Confidence, または辞書

        Returns:
            Confidence インスタンス

        Raises:
            TypeError: サポートされていない型の場合
        """
        if isinstance(value, cls):
            return value
        if isinstance(value, (int, float)):
            return cls(overall=float(value))
        if isinstance(value, dict):
            return cls(
                overall=float(value.get("overall", 0.0)),
                reasoning=value.get("reasoning"),
                intent_confidence=value.get("intent_confidence"),
                entity_confidence=value.get("entity_confidence"),
            )
        raise TypeError(f"Cannot create Confidence from {type(value).__name__}")

    def __float__(self) -> float:
        """float への暗黙変換をサポート"""
        return self.overall

    def __lt__(self, other: Union[float, "Confidence"]) -> bool:
        """比較演算子 <"""
        other_val = other.overall if isinstance(other, Confidence) else float(other)
        return self.overall < other_val

    def __le__(self, other: Union[float, "Confidence"]) -> bool:
        """比較演算子 <="""
        other_val = other.overall if isinstance(other, Confidence) else float(other)
        return self.overall <= other_val

    def __gt__(self, other: Union[float, "Confidence"]) -> bool:
        """比較演算子 >"""
        other_val = other.overall if isinstance(other, Confidence) else float(other)
        return self.overall > other_val

    def __ge__(self, other: Union[float, "Confidence"]) -> bool:
        """比較演算子 >="""
        other_val = other.overall if isinstance(other, Confidence) else float(other)
        return self.overall >= other_val


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

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "message_id": self.message_id,
            "sender_name": self.sender_name,
        }


@dataclass
class SummaryData:
    """会話要約データ"""

    summary: str                 # 要約テキスト
    key_topics: List[str]        # 主要トピック
    mentioned_persons: List[str]  # 言及された人物
    mentioned_tasks: List[str]   # 言及されたタスク
    created_at: datetime

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "summary": self.summary,
            "key_topics": self.key_topics,
            "mentioned_persons": self.mentioned_persons,
            "mentioned_tasks": self.mentioned_tasks,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


@dataclass
class PreferenceData:
    """ユーザー嗜好データ"""

    response_style: Optional[str] = None      # 応答スタイル
    feature_usage: Dict[str, int] = field(default_factory=dict)  # 機能使用状況
    preferred_times: List[str] = field(default_factory=list)     # 好みの時間帯
    custom_keywords: Dict[str, str] = field(default_factory=dict)  # カスタムキーワード

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "response_style": self.response_style,
            "feature_usage": self.feature_usage,
            "preferred_times": self.preferred_times,
            "custom_keywords": self.custom_keywords,
        }


# PersonInfo.to_string() で使用するフォームデータ属性ラベル（モジュール定数）
_PERSON_FORM_ATTR_LABELS: tuple = (
    ("スキル（得意）", "得意"),
    ("稼働スタイル", "稼働"),
    ("キャパシティ", "余力"),
    ("連絡可能時間", "連絡可"),
    ("月間稼働", "月間"),
)


@dataclass
class PersonInfo:
    """
    人物情報（統一版）

    全コンポーネントで共通使用するPersonInfoの正式定義。
    SoT: このファイル（lib/brain/models.py）

    注意: 他のファイルでPersonInfoを定義しないこと。
    必ずこのクラスをimportして使用すること。
    """

    # 識別子（用途に応じて使い分け）
    person_id: str = ""              # 汎用ID
    user_id: Optional[str] = None    # ユーザーID（DB参照用）
    chatwork_account_id: Optional[str] = None  # Chatwork account_id

    # 基本情報
    name: str = ""                   # 名前（必須）
    description: Optional[str] = None  # 説明・メモ

    # 所属情報
    department: Optional[str] = None   # 部署
    role: Optional[str] = None         # 役割
    position: Optional[str] = None     # 役職（roleのエイリアス的用途）
    email: Optional[str] = None        # メールアドレス

    # スキル・専門性
    expertise: List[str] = field(default_factory=list)  # 専門分野

    # 責務（organization_expert用）
    responsibilities: List[str] = field(default_factory=list)

    # 拡張情報（任意のキーバリュー）
    attributes: Dict[str, Any] = field(default_factory=dict)  # 汎用属性

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換（PIIを含む完全版）

        注意: ログや外部出力には使わないこと。
        ログ・監査など外部出力には to_safe_dict() を使うこと（CLAUDE.md §9-4）。
        """
        return {
            "person_id": self.person_id,
            "user_id": self.user_id,
            "chatwork_account_id": self.chatwork_account_id,
            "name": self.name,
            "description": self.description,
            "department": self.department,
            "role": self.role,
            "position": self.position,
            "email": self.email,
            "expertise": self.expertise,
            "responsibilities": self.responsibilities,
            "attributes": self.attributes,
        }

    def to_safe_dict(self) -> Dict[str, Any]:
        """PIIをマスキングした安全な辞書形式に変換（ログ・外部出力用）

        CLAUDE.md §9-4「思考過程のPIIマスキング」に準拠。
        - name        → [PERSON]
        - email       → [EMAIL]
        - description → [REDACTED]（個人の経歴・説明文）
        - attributes  → [REDACTED]（稼働スタイル・余力などフォームデータ）

        注意: LLMへの入力・内部ロジックには to_dict() を使うこと。
        デバッグ時も to_dict() を使えば生の値を確認できる。
        このメソッドはログ記録・監査・外部出力専用。
        """
        return {
            "person_id": self.person_id,
            "user_id": self.user_id,
            "chatwork_account_id": self.chatwork_account_id,
            "name": "[PERSON]" if self.name else "",
            "description": "[REDACTED]" if self.description else None,
            "department": self.department,
            "role": self.role,
            "position": self.position,
            "email": "[EMAIL]" if self.email else None,
            "expertise": self.expertise,
            "responsibilities": self.responsibilities,
            "attributes": "[REDACTED]" if self.attributes else None,
        }

    def to_string(self) -> str:
        """表示用文字列を生成（フォームデータの属性も含む）"""
        parts = [self.name]
        if self.department:
            parts.append(f"({self.department})")
        if self.role or self.position:
            parts.append(f"[{self.role or self.position}]")
        if self.description:
            parts.append(f": {self.description}")
        # フォームから同期したパーソナルデータを表示
        attr_parts = [
            f"{label}: {self.attributes[key]}"
            for key, label in _PERSON_FORM_ATTR_LABELS
            if self.attributes.get(key)
        ]
        if attr_parts:
            parts.append(f" | {'; '.join(attr_parts)}")
        return "".join(parts)

    # 後方互換性のためのプロパティ
    @property
    def known_info(self) -> Dict[str, Any]:
        """後方互換性: attributesのエイリアス"""
        return self.attributes

    @property
    def chatwork_id(self) -> Optional[str]:
        """後方互換性: chatwork_account_idのエイリアス"""
        return self.chatwork_account_id

    @property
    def id(self) -> str:
        """後方互換性: person_idのエイリアス"""
        return self.person_id


@dataclass
class TaskInfo:
    """
    タスク情報（統一版）

    全コンポーネントで共通使用するTaskInfoの正式定義。
    SoT: このファイル（lib/brain/models.py）

    注意: 他のファイルでTaskInfoを定義しないこと。
    必ずこのクラスをimportして使用すること。
    """

    # 識別子
    task_id: str = ""                  # タスクID

    # タスク内容
    title: Optional[str] = None        # タイトル（短い表示用）
    body: str = ""                     # タスク本文（詳細）
    summary: Optional[str] = None      # AI生成の要約

    # ステータス・優先度
    status: str = "open"               # open, done
    priority: str = "normal"           # high, normal, low

    # 期限
    due_date: Optional[datetime] = None   # 期限（datetimeとして統一）
    is_overdue: bool = False              # 期限切れフラグ

    # ルーム情報
    room_id: Optional[str] = None
    room_name: Optional[str] = None

    # 担当者情報
    assignee_id: Optional[str] = None       # 担当者ID
    assignee_name: Optional[str] = None     # 担当者名
    assigned_by_id: Optional[str] = None    # 依頼者ID
    assigned_by_name: Optional[str] = None  # 依頼者名

    # タイムスタンプ（task_expert用）
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "task_id": self.task_id,
            "title": self.title,
            "body": self.body,
            "summary": self.summary,
            "status": self.status,
            "priority": self.priority,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "is_overdue": self.is_overdue,
            "room_id": self.room_id,
            "room_name": self.room_name,
            "assignee_id": self.assignee_id,
            "assignee_name": self.assignee_name,
            "assigned_by_id": self.assigned_by_id,
            "assigned_by_name": self.assigned_by_name,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }

    def to_string(self) -> str:
        """表示用文字列を生成"""
        display_name = self.title or self.summary or (self.body[:40] if self.body else "")
        parts = [display_name]
        if self.due_date:
            parts.append(f"(期限: {self.due_date.strftime('%Y-%m-%d')})")
        if self.is_overdue:
            parts.append("[期限切れ]")
        if self.assignee_name:
            parts.append(f"担当: {self.assignee_name}")
        return " ".join(parts)

    # 後方互換性のためのプロパティ
    @property
    def limit_time(self) -> Optional[datetime]:
        """後方互換性: due_dateのエイリアス"""
        return self.due_date

    @property
    def assigned_to(self) -> Optional[str]:
        """後方互換性: assignee_nameのエイリアス"""
        return self.assignee_name

    @property
    def assigned_to_name(self) -> Optional[str]:
        """後方互換性: assignee_nameのエイリアス"""
        return self.assignee_name

    @property
    def days_until_due(self) -> Optional[int]:
        """期限までの日数（task_expert用）"""
        if self.due_date:
            delta = self.due_date - datetime.now()
            return delta.days
        return None


@dataclass
class GoalInfo:
    """
    目標情報（統一版）

    全コンポーネントで共通使用するGoalInfoの正式定義。
    SoT: このファイル（lib/brain/models.py）

    注意: 他のファイルでGoalInfoを定義しないこと。
    必ずこのクラスをimportして使用すること。
    """

    # 識別子
    goal_id: str = ""                  # 目標ID
    user_id: Optional[str] = None      # ユーザーID
    organization_id: Optional[str] = None  # 組織ID

    # 目標内容
    title: str = ""                    # タイトル（表示用）
    why: Optional[str] = None          # なぜその目標か（目的・動機）
    what: Optional[str] = None         # 何を達成するか（内容）
    how: Optional[str] = None          # どうやって達成するか（方法）

    # ステータス・進捗
    status: str = "active"             # active, completed, paused, abandoned
    progress: float = 0.0              # 進捗率 (0.0 - 100.0)

    # 期限
    deadline: Optional[datetime] = None   # 期限（datetimeとして統一）

    # タイムスタンプ（goal_expert用）
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "goal_id": self.goal_id,
            "user_id": self.user_id,
            "organization_id": self.organization_id,
            "title": self.title,
            "why": self.why,
            "what": self.what,
            "how": self.how,
            "status": self.status,
            "progress": self.progress,
            "deadline": self.deadline.isoformat() if self.deadline else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }

    def to_string(self) -> str:
        """表示用文字列を生成"""
        display_name = self.title or self.what or ""
        return f"{display_name} ({self.progress:.0f}%達成)"

    # 後方互換性のためのプロパティ
    @property
    def due_date(self) -> Optional[datetime]:
        """後方互換性: deadlineのエイリアス"""
        return self.deadline

    @property
    def id(self) -> str:
        """後方互換性: goal_idのエイリアス"""
        return self.goal_id

    @property
    def target_date(self) -> Optional[datetime]:
        """後方互換性: deadlineのエイリアス（goal_expert用）"""
        return self.deadline

    @property
    def progress_percentage(self) -> int:
        """後方互換性: progressをintで返す（goal_expert用）"""
        return int(self.progress)

    @property
    def is_stale(self) -> bool:
        """放置されているか（goal_expert用）"""
        if self.updated_at and self.status == "active":
            days_since_update = (datetime.now() - self.updated_at).days
            return days_since_update >= 7  # GOAL_STALE_DAYS
        return False

    @property
    def days_since_update(self) -> int:
        """最終更新からの日数（goal_expert用）"""
        if self.updated_at:
            return (datetime.now() - self.updated_at).days
        return 0


@dataclass
class GoalSessionInfo:
    """目標設定セッション情報"""

    session_id: str
    current_step: str            # intro, why, what, how
    retry_count: int = 0
    created_at: datetime = field(default_factory=datetime.now)
    data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "session_id": self.session_id,
            "current_step": self.current_step,
            "retry_count": self.retry_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "data": self.data,
        }


@dataclass
class KnowledgeChunk:
    """知識チャンク"""

    chunk_id: str
    content: str                 # チャンク内容
    source: str                  # 出典
    relevance_score: float       # 関連度スコア
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "chunk_id": self.chunk_id,
            "content": self.content,
            "source": self.source,
            "relevance_score": self.relevance_score,
            "metadata": self.metadata,
        }


@dataclass
class InsightInfo:
    """インサイト情報"""

    insight_id: str
    insight_type: str            # frequent_question, stagnant_task, etc.
    title: str
    description: str
    severity: str                # critical, high, medium, low
    created_at: datetime

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "insight_id": self.insight_id,
            "insight_type": self.insight_type,
            "title": self.title,
            "description": self.description,
            "severity": self.severity,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


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
        if self.expires_at:
            # v10.39.4: タイムゾーン対応（DBはUTC、比較もUTCで）
            now = datetime.now(timezone.utc)
            expires = self.expires_at if self.expires_at.tzinfo else self.expires_at.replace(tzinfo=timezone.utc)
            if now > expires:
                return False
        return True

    @property
    def is_expired(self) -> bool:
        """期限切れかどうか"""
        if self.expires_at is None:
            return False
        # v10.39.4: タイムゾーン対応
        now = datetime.now(timezone.utc)
        expires = self.expires_at if self.expires_at.tzinfo else self.expires_at.replace(tzinfo=timezone.utc)
        return now > expires

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "state_id": self.state_id,
            "organization_id": self.organization_id,
            "room_id": self.room_id,
            "user_id": self.user_id,
            "state_type": self.state_type.value if isinstance(self.state_type, StateType) else self.state_type,
            "state_step": self.state_step,
            "state_data": self.state_data,
            "reference_type": self.reference_type,
            "reference_id": self.reference_id,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "is_active": self.is_active,
            "is_expired": self.is_expired,
        }


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

    # CEO教え関連（Phase 2D）
    ceo_teachings: Optional["CEOTeachingContext"] = None

    # Phase 2E: 学習基盤からの適用学習（LLMプロンプト用テキスト）
    phase2e_learnings: Optional[str] = None

    # タスクD: エピソード記憶（想起された過去の出来事）
    # 型: List[RecallResult] — TYPE_CHECKINGのため実行時はList[Any]として動作
    recent_episodes: List[Any] = field(default_factory=list)

    # v10.42.0 P2: ユーザーの人生軸・価値観・長期目標
    # UserLongTermMemory.get_all()の結果を格納
    user_life_axis: Optional[List[Dict[str, Any]]] = None

    # Phase M: マルチモーダルコンテキスト（画像・PDF・音声・URL処理結果）
    # lib.capabilities.multimodal.brain_integration.MultimodalBrainContext
    multimodal_context: Optional[Any] = None

    # Phase G: 生成リクエスト（文書・画像・動画生成）
    # lib.capabilities.generation.models.GenerationRequest
    generation_request: Optional[Any] = None

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

    def has_multimodal_content(self) -> bool:
        """
        マルチモーダルコンテンツ（画像・PDF・音声等）があるか

        Returns:
            マルチモーダルコンテンツがあればTrue
        """
        if self.multimodal_context is None:
            return False
        # MultimodalBrainContextのhas_multimodal_contentプロパティを使用
        return getattr(self.multimodal_context, 'has_multimodal_content', False)

    def has_generation_request(self) -> bool:
        """
        生成リクエストがあるか

        Returns:
            生成リクエストがあればTrue
        """
        return self.generation_request is not None

    def get_multimodal_summary(self) -> str:
        """
        マルチモーダルコンテンツの要約を取得

        Returns:
            要約文字列、なければ空文字
        """
        if not self.has_multimodal_content():
            return ""
        # MultimodalBrainContextのto_prompt_contextメソッドを使用
        ctx = self.multimodal_context
        if ctx is not None and hasattr(ctx, 'to_prompt_context'):
            result = ctx.to_prompt_context()
            return str(result) if result is not None else ""
        return ""

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

        # CEO教え（Phase 2D）
        if self.ceo_teachings and self.ceo_teachings.relevant_teachings:
            ceo_context = self.ceo_teachings.to_prompt_context()
            if ceo_context:
                parts.append(ceo_context)

        # マルチモーダルコンテキスト（Phase M）
        multimodal_summary = self.get_multimodal_summary()
        if multimodal_summary:
            parts.append(multimodal_summary)

        # 記憶している人物
        if self.person_info:
            names = [p.name for p in self.person_info[:5]]
            parts.append(f"【記憶している人物】{', '.join(names)}")

        return "\n".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        """
        辞書形式に変換（シリアライズ用）

        type_safety.safe_to_dict() を使用して安全にJSON化可能な形式に変換する。

        Returns:
            BrainContextの内容を辞書として返す
        """
        from lib.brain.type_safety import safe_to_dict

        return {
            "current_state": safe_to_dict(self.current_state) if self.current_state else None,
            "recent_conversation": safe_to_dict(self.recent_conversation),
            "conversation_summary": safe_to_dict(self.conversation_summary) if self.conversation_summary else None,
            "user_preferences": safe_to_dict(self.user_preferences) if self.user_preferences else None,
            "sender_name": self.sender_name,
            "sender_account_id": self.sender_account_id,
            # PIIマスキング: person_info はログ出力のため to_safe_dict() を使用（CLAUDE.md §9-4）
            "person_info": [p.to_safe_dict() for p in self.person_info] if isinstance(self.person_info, list) else safe_to_dict(self.person_info),
            "recent_tasks": safe_to_dict(self.recent_tasks),
            "active_goals": safe_to_dict(self.active_goals),
            "goal_session": safe_to_dict(self.goal_session) if self.goal_session else None,
            "insights": safe_to_dict(self.insights),
            "organization_id": self.organization_id,
            "room_id": self.room_id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }


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

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "original": self.original,
            "resolved": self.resolved,
            "entity_type": self.entity_type,
            "source": self.source,
            "confidence": self.confidence,
        }


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

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "raw_message": self.raw_message,
            "intent": self.intent,
            "intent_confidence": self.intent_confidence,
            "confidence_level": self.confidence_level.value,
            "entities": self.entities,
            "resolved_ambiguities": [e.to_dict() for e in self.resolved_ambiguities],
            "needs_confirmation": self.needs_confirmation,
            "confirmation_reason": self.confirmation_reason,
            "confirmation_options": self.confirmation_options,
            "reasoning": self.reasoning,
            "processing_time_ms": self.processing_time_ms,
        }


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

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "action": self.action,
            "score": self.score,
            "params": self.params,
            "reasoning": self.reasoning,
        }


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

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "action": self.action,
            "params": self.params,
            "confidence": self.confidence,
            "needs_confirmation": self.needs_confirmation,
            "confirmation_question": self.confirmation_question,
            "confirmation_options": self.confirmation_options,
            "other_candidates": [c.to_dict() for c in self.other_candidates],
            "reasoning": self.reasoning,
            "processing_time_ms": self.processing_time_ms,
        }


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

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "success": self.success,
            "message": self.message,
            "data": self.data,
            "next_action": self.next_action,
            "next_params": self.next_params,
            "update_state": self.update_state,
            "suggestions": self.suggestions,
            "error_code": self.error_code,
            "error_details": self.error_details,
        }


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

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "question": self.question,
            "options": self.options,
            "default_option": self.default_option,
            "timeout_seconds": self.timeout_seconds,
            "on_confirm_action": self.on_confirm_action,
            "on_confirm_params": self.on_confirm_params,
        }


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

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "message": self.message,
            "action_taken": self.action_taken,
            "action_params": self.action_params,
            "success": self.success,
            "suggestions": self.suggestions,
            "state_changed": self.state_changed,
            "new_state": self.new_state,
            "awaiting_confirmation": self.awaiting_confirmation,
            "debug_info": self.debug_info,
            "total_time_ms": self.total_time_ms,
        }


# =============================================================================
# Phase 2D: CEO Learning & Guardian Layer Models
# 設計書: docs/15_phase2d_ceo_learning.md
# =============================================================================


class TeachingCategory(str, Enum):
    """
    CEO教えのカテゴリ

    CEOからの「教え」を分類するための15カテゴリ。
    """

    # MVV関連（ミッション・ビジョン・バリュー）
    MVV_MISSION = "mvv_mission"      # ミッションに関する教え
    MVV_VISION = "mvv_vision"        # ビジョンに関する教え
    MVV_VALUES = "mvv_values"        # バリューに関する教え

    # 組織論関連
    CHOICE_THEORY = "choice_theory"  # 選択理論に関する教え
    SDT = "sdt"                      # 自己決定理論に関する教え
    SERVANT = "servant"              # サーバントリーダーシップに関する教え
    PSYCH_SAFETY = "psych_safety"    # 心理的安全性に関する教え

    # 業務関連
    BIZ_SALES = "biz_sales"          # 営業・販売に関する教え
    BIZ_HR = "biz_hr"                # 人事・採用に関する教え
    BIZ_ACCOUNTING = "biz_accounting"  # 経理・財務に関する教え
    BIZ_GENERAL = "biz_general"      # その他業務全般

    # 人・文化関連
    CULTURE = "culture"              # 組織文化に関する教え
    COMMUNICATION = "communication"  # コミュニケーションに関する教え
    STAFF_GUIDANCE = "staff_guidance"  # スタッフへの指導に関する教え

    # その他
    OTHER = "other"                  # 分類できないもの


class ValidationStatus(str, Enum):
    """
    教えの検証ステータス

    Guardian層による検証の結果を表す。
    """

    PENDING = "pending"              # 検証中
    VERIFIED = "verified"            # 検証済み（矛盾なし）
    ALERT_PENDING = "alert_pending"  # アラート待ち（CEOの確認待ち）
    OVERRIDDEN = "overridden"        # CEOが上書き許可（矛盾あるが保存）


class ConflictType(str, Enum):
    """
    矛盾の種類

    教えがどのような基準と矛盾しているかを表す。
    """

    MVV = "mvv"                      # MVV（ミッション・ビジョン・バリュー）との矛盾
    CHOICE_THEORY = "choice_theory"  # 選択理論との矛盾
    SDT = "sdt"                      # 自己決定理論との矛盾
    GUIDELINES = "guidelines"        # 行動指針との矛盾
    EXISTING = "existing"            # 既存の教えとの矛盾


class AlertStatus(str, Enum):
    """
    アラートのステータス

    ガーディアンアラートの処理状態を表す。
    """

    PENDING = "pending"              # CEOの回答待ち
    ACKNOWLEDGED = "acknowledged"    # CEOが確認済み（教えを取り消し）
    OVERRIDDEN = "overridden"        # CEOが上書き許可（矛盾あるが保存）
    RETRACTED = "retracted"          # CEOが撤回（教えを修正する）


class Severity(str, Enum):
    """
    矛盾の深刻度

    検出された矛盾がどれほど深刻かを表す。
    """

    HIGH = "high"                    # 高深刻度（MVV・組織論の根幹に関わる）
    MEDIUM = "medium"                # 中深刻度（解釈の余地あり）
    LOW = "low"                      # 低深刻度（軽微な不整合）


# -----------------------------------------------------------------------------
# CEO教え関連のデータクラス
# -----------------------------------------------------------------------------


@dataclass
class CEOTeaching:
    """
    CEOからの教え

    CEOとの対話から抽出された「教え」を表す。
    スタッフへの応答時に参照される。
    """

    # 識別情報
    id: Optional[str] = None
    organization_id: str = ""
    ceo_user_id: Optional[str] = None  # Phase 4A: BPaaS展開時のCEOユーザーID

    # 教えの内容
    statement: str = ""              # 主張（何を言っているか）
    reasoning: Optional[str] = None  # 理由（なぜそう言っているか）
    context: Optional[str] = None    # 文脈（どんな状況で）
    target: Optional[str] = None     # 対象（全員/マネージャー/特定部署等）

    # 分類
    category: TeachingCategory = TeachingCategory.OTHER
    subcategory: Optional[str] = None
    keywords: List[str] = field(default_factory=list)

    # 検証結果
    validation_status: ValidationStatus = ValidationStatus.PENDING
    mvv_alignment_score: Optional[float] = None   # 0.0-1.0
    theory_alignment_score: Optional[float] = None  # 0.0-1.0

    # 優先度・活性化
    priority: int = 5                # 1-10（高いほど優先）
    is_active: bool = True
    supersedes: Optional[str] = None  # 上書きする過去の教えID

    # 利用統計
    usage_count: int = 0
    last_used_at: Optional[datetime] = None
    helpful_count: int = 0

    # ソース情報
    source_room_id: Optional[str] = None
    source_message_id: Optional[str] = None
    extracted_at: datetime = field(default_factory=datetime.now)

    # メタデータ
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def is_relevant_to(self, topic: str) -> bool:
        """
        指定されたトピックに関連があるかを判定

        Args:
            topic: 判定対象のトピック

        Returns:
            関連があればTrue
        """
        topic_lower = topic.lower()
        # キーワードマッチ
        for keyword in self.keywords:
            if keyword.lower() in topic_lower or topic_lower in keyword.lower():
                return True
        # 主張内容マッチ
        if topic_lower in self.statement.lower():
            return True
        return False

    def to_prompt_context(self) -> str:
        """
        LLMプロンプト用のコンテキスト文字列を生成

        Returns:
            プロンプトに含める教えの要約
        """
        parts = [f"【{self.category.value}】{self.statement}"]
        if self.reasoning:
            parts.append(f"  理由: {self.reasoning}")
        if self.target:
            parts.append(f"  対象: {self.target}")
        return "\n".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "ceo_user_id": self.ceo_user_id,
            "statement": self.statement,
            "reasoning": self.reasoning,
            "context": self.context,
            "target": self.target,
            "category": self.category.value if isinstance(self.category, TeachingCategory) else self.category,
            "subcategory": self.subcategory,
            "keywords": self.keywords,
            "validation_status": self.validation_status.value if isinstance(self.validation_status, ValidationStatus) else self.validation_status,
            "mvv_alignment_score": self.mvv_alignment_score,
            "theory_alignment_score": self.theory_alignment_score,
            "priority": self.priority,
            "is_active": self.is_active,
            "supersedes": self.supersedes,
            "usage_count": self.usage_count,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "helpful_count": self.helpful_count,
            "source_room_id": self.source_room_id,
            "source_message_id": self.source_message_id,
            "extracted_at": self.extracted_at.isoformat() if self.extracted_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


@dataclass
class ConflictInfo:
    """
    教えの矛盾情報

    Guardian層が検出した矛盾の詳細を表す。
    """

    id: Optional[str] = None
    organization_id: str = ""
    teaching_id: str = ""

    # 矛盾情報
    conflict_type: ConflictType = ConflictType.MVV
    conflict_subtype: Optional[str] = None  # 例: 'mission', 'vision', 'autonomy'
    description: str = ""            # 矛盾の説明
    reference: str = ""              # 参照した基準（原文引用）
    severity: Severity = Severity.MEDIUM

    # 関連教え（既存教えとの矛盾の場合）
    conflicting_teaching_id: Optional[str] = None

    # メタデータ
    created_at: datetime = field(default_factory=datetime.now)

    def to_alert_summary(self) -> str:
        """
        アラート用の要約を生成

        Returns:
            人間が読みやすい矛盾の説明
        """
        severity_emoji = {
            Severity.HIGH: "🔴",
            Severity.MEDIUM: "🟡",
            Severity.LOW: "🟢"
        }
        return f"{severity_emoji.get(self.severity, '⚪')} [{self.conflict_type.value}] {self.description}"

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "teaching_id": self.teaching_id,
            "conflict_type": self.conflict_type.value if isinstance(self.conflict_type, ConflictType) else self.conflict_type,
            "conflict_subtype": self.conflict_subtype,
            "description": self.description,
            "reference": self.reference,
            "severity": self.severity.value if isinstance(self.severity, Severity) else self.severity,
            "conflicting_teaching_id": self.conflicting_teaching_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


@dataclass
class GuardianAlert:
    """
    ガーディアンアラート

    CEOに確認を求めるアラートを表す。
    """

    id: Optional[str] = None
    organization_id: str = ""
    teaching_id: str = ""

    # アラート内容
    conflict_summary: str = ""       # 矛盾の要約
    alert_message: str = ""          # CEOへのメッセージ（ソウルくん口調）
    alternative_suggestion: Optional[str] = None  # 代替案

    # 矛盾情報リスト
    conflicts: List[ConflictInfo] = field(default_factory=list)

    # ステータス
    status: AlertStatus = AlertStatus.PENDING
    ceo_response: Optional[str] = None        # CEOの回答
    ceo_reasoning: Optional[str] = None       # CEOの判断理由
    resolved_at: Optional[datetime] = None

    # 通知情報
    notified_at: Optional[datetime] = None
    notification_room_id: Optional[str] = None
    notification_message_id: Optional[str] = None

    # メタデータ
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    @property
    def is_resolved(self) -> bool:
        """解決済みかどうか"""
        return self.status != AlertStatus.PENDING

    @property
    def max_severity(self) -> Severity:
        """矛盾の最大深刻度"""
        if not self.conflicts:
            return Severity.LOW
        severities = [c.severity for c in self.conflicts]
        if Severity.HIGH in severities:
            return Severity.HIGH
        if Severity.MEDIUM in severities:
            return Severity.MEDIUM
        return Severity.LOW

    def generate_alert_message(self, teaching: CEOTeaching) -> str:
        """
        ソウルくん口調のアラートメッセージを生成

        Args:
            teaching: 検証対象の教え

        Returns:
            CEOに送信するメッセージ
        """
        severity_text = {
            Severity.HIGH: "ちょっと気になることがあるウル...",
            Severity.MEDIUM: "確認させてほしいウル",
            Severity.LOW: "念のため確認ウル"
        }

        parts = [
            f"🐺 {severity_text.get(self.max_severity, '確認ウル')}",
            "",
            f"さっきの「{teaching.statement[:50]}...」について、",
            self.conflict_summary,
            ""
        ]

        if self.alternative_suggestion:
            parts.extend([
                "こんな言い方はどうウル？",
                f"→ {self.alternative_suggestion}",
                ""
            ])

        parts.extend([
            "どうするか教えてほしいウル：",
            "1️⃣ そのまま保存（ソウルくんの考えを上書き）",
            "2️⃣ 取り消し（今回は保存しない）",
            "3️⃣ 言い直す（別の表現に変える）"
        ])

        return "\n".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "teaching_id": self.teaching_id,
            "conflict_summary": self.conflict_summary,
            "alert_message": self.alert_message,
            "alternative_suggestion": self.alternative_suggestion,
            "conflicts": [c.to_dict() for c in self.conflicts],
            "status": self.status.value if isinstance(self.status, AlertStatus) else self.status,
            "ceo_response": self.ceo_response,
            "ceo_reasoning": self.ceo_reasoning,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "notified_at": self.notified_at.isoformat() if self.notified_at else None,
            "notification_room_id": self.notification_room_id,
            "notification_message_id": self.notification_message_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "is_resolved": self.is_resolved,
            "max_severity": self.max_severity.value,
        }


@dataclass
class TeachingValidationResult:
    """
    教えの検証結果

    Guardian層による検証の完全な結果を表す。
    """

    # 検証対象
    teaching: CEOTeaching

    # 結果
    is_valid: bool = True            # 矛盾がなければTrue
    validation_status: ValidationStatus = ValidationStatus.VERIFIED

    # 発見された矛盾
    conflicts: List[ConflictInfo] = field(default_factory=list)

    # スコア
    mvv_alignment_score: float = 1.0      # MVVとの整合性（0.0-1.0）
    theory_alignment_score: float = 1.0   # 組織論との整合性（0.0-1.0）
    overall_score: float = 1.0            # 総合スコア

    # 推奨アクション
    recommended_action: str = "save"      # save, alert, reject
    alternative_suggestion: Optional[str] = None

    # 処理情報
    validation_time_ms: int = 0
    validated_at: datetime = field(default_factory=datetime.now)

    def should_alert(self) -> bool:
        """アラートを発生させるべきか"""
        if not self.is_valid:
            return True
        # 高深刻度の矛盾がある場合
        for conflict in self.conflicts:
            if conflict.severity == Severity.HIGH:
                return True
        # スコアが低い場合
        if self.overall_score < 0.5:
            return True
        return False

    def get_alert_reason(self) -> str:
        """アラートの理由を取得"""
        if not self.conflicts:
            return "検証結果に問題がありました"
        # 最も深刻な矛盾を選択
        high_conflicts = [c for c in self.conflicts if c.severity == Severity.HIGH]
        if high_conflicts:
            return high_conflicts[0].description
        return self.conflicts[0].description

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "teaching": self.teaching.to_dict() if self.teaching else None,
            "is_valid": self.is_valid,
            "validation_status": self.validation_status.value if isinstance(self.validation_status, ValidationStatus) else self.validation_status,
            "conflicts": [c.to_dict() for c in self.conflicts],
            "mvv_alignment_score": self.mvv_alignment_score,
            "theory_alignment_score": self.theory_alignment_score,
            "overall_score": self.overall_score,
            "recommended_action": self.recommended_action,
            "alternative_suggestion": self.alternative_suggestion,
            "validation_time_ms": self.validation_time_ms,
            "validated_at": self.validated_at.isoformat() if self.validated_at else None,
        }


@dataclass
class TeachingUsageContext:
    """
    教え使用コンテキスト

    教えを応答に使用する際の詳細情報を表す。
    """

    teaching_id: str
    organization_id: str = ""

    # 使用コンテキスト
    room_id: str = ""
    account_id: str = ""
    user_message: str = ""
    response_excerpt: Optional[str] = None

    # 選択理由
    relevance_score: float = 0.0     # 関連度（0.0-1.0）
    selection_reasoning: Optional[str] = None

    # フィードバック（後から更新）
    was_helpful: Optional[bool] = None
    feedback: Optional[str] = None

    # メタデータ
    used_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "teaching_id": self.teaching_id,
            "organization_id": self.organization_id,
            "room_id": self.room_id,
            "account_id": self.account_id,
            "user_message": self.user_message,
            "response_excerpt": self.response_excerpt,
            "relevance_score": self.relevance_score,
            "selection_reasoning": self.selection_reasoning,
            "was_helpful": self.was_helpful,
            "feedback": self.feedback,
            "used_at": self.used_at.isoformat() if self.used_at else None,
        }


@dataclass
class CEOTeachingContext:
    """
    CEO教えの統合コンテキスト

    BrainContextに追加するCEO教え関連の情報をまとめたもの。
    """

    # アクティブな教え（関連度順）
    relevant_teachings: List[CEOTeaching] = field(default_factory=list)

    # 未解決のアラート
    pending_alerts: List[GuardianAlert] = field(default_factory=list)

    # 現在のCEO判定
    is_ceo_user: bool = False
    ceo_user_id: Optional[str] = None

    # 統計情報
    total_teachings_count: int = 0
    active_teachings_count: int = 0

    def get_top_teachings(self, count: int = 3) -> List[CEOTeaching]:
        """上位N件の関連教えを取得"""
        return self.relevant_teachings[:count]

    def has_pending_alerts(self) -> bool:
        """未解決アラートがあるか"""
        return len(self.pending_alerts) > 0

    def to_prompt_context(self) -> str:
        """LLMプロンプト用のコンテキストを生成"""
        if not self.relevant_teachings:
            return ""

        parts = ["【会社の教え】"]
        for teaching in self.relevant_teachings[:3]:
            parts.append(f"・{teaching.statement}")
            if teaching.reasoning:
                parts.append(f"  （{teaching.reasoning}）")

        return "\n".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "relevant_teachings": [t.to_dict() for t in self.relevant_teachings],
            "pending_alerts": [a.to_dict() for a in self.pending_alerts],
            "is_ceo_user": self.is_ceo_user,
            "ceo_user_id": self.ceo_user_id,
            "total_teachings_count": self.total_teachings_count,
            "active_teachings_count": self.active_teachings_count,
        }


# =============================================================================
# 能動的メッセージ（Proactive Message）のモデル
# =============================================================================


class ProactiveMessageTone(str, Enum):
    """能動的メッセージのトーン"""

    FRIENDLY = "friendly"           # フレンドリー
    ENCOURAGING = "encouraging"     # 励まし
    CONCERNED = "concerned"         # 心配・気遣い
    CELEBRATORY = "celebratory"     # お祝い
    REMINDER = "reminder"           # リマインド
    SUPPORTIVE = "supportive"       # サポート


@dataclass
class ProactiveMessageResult:
    """
    脳による能動的メッセージ生成結果

    Proactive Monitorがトリガーを検出した後、
    脳がメッセージ内容を判断・生成した結果。

    CLAUDE.md鉄則1b: 能動的出力も脳が生成
    """

    should_send: bool
    """送信すべきか（脳の判断）"""

    message: Optional[str] = None
    """生成されたメッセージ（should_send=Trueの場合）"""

    reason: str = ""
    """判断理由（ログ・デバッグ用）"""

    confidence: float = 0.0
    """判断の確信度（0.0-1.0）"""

    tone: ProactiveMessageTone = ProactiveMessageTone.FRIENDLY
    """選択されたトーン"""

    context_used: Dict[str, Any] = field(default_factory=dict)
    """判断に使用したコンテキスト（デバッグ用）"""

    debug_info: Dict[str, Any] = field(default_factory=dict)
    """その他のデバッグ情報"""

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "should_send": self.should_send,
            "message": self.message,
            "reason": self.reason,
            "confidence": self.confidence,
            "tone": self.tone.value if isinstance(self.tone, ProactiveMessageTone) else self.tone,
            "context_used": self.context_used,
            "debug_info": self.debug_info,
        }