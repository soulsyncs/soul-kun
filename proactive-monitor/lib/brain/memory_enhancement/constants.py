"""
Phase 2G: 記憶の強化（Memory Enhancement）- 定数定義

設計書: docs/17_brain_completion_roadmap.md セクション Phase 2G

エピソード記憶、知識グラフ、時系列記憶に関する定数とEnum定義。
"""

from enum import Enum
from typing import Dict, Set


# ============================================================================
# テーブル名
# ============================================================================

TABLE_BRAIN_EPISODES = "brain_episodes"
TABLE_BRAIN_EPISODE_ENTITIES = "brain_episode_entities"
TABLE_BRAIN_KNOWLEDGE_NODES = "brain_knowledge_nodes"
TABLE_BRAIN_KNOWLEDGE_EDGES = "brain_knowledge_edges"
TABLE_BRAIN_TEMPORAL_EVENTS = "brain_temporal_events"
TABLE_BRAIN_TEMPORAL_COMPARISONS = "brain_temporal_comparisons"
TABLE_BRAIN_MEMORY_CONSOLIDATIONS = "brain_memory_consolidations"


# ============================================================================
# エピソード関連 Enum
# ============================================================================

class EpisodeType(str, Enum):
    """エピソードの種類

    人間の記憶におけるエピソード記憶の分類に基づく。
    """
    # 達成・成功系
    ACHIEVEMENT = "achievement"         # 目標達成、タスク完了
    MILESTONE = "milestone"             # マイルストーン達成
    BREAKTHROUGH = "breakthrough"       # ブレイクスルー

    # 失敗・問題系
    FAILURE = "failure"                 # ミス、期限超過
    CONFLICT = "conflict"               # 対立、トラブル
    OBSTACLE = "obstacle"               # 障害発生

    # 判断・決定系
    DECISION = "decision"               # 重要な判断
    COMMITMENT = "commitment"           # コミットメント
    CHANGE = "change"                   # 方針変更

    # やりとり系
    INTERACTION = "interaction"         # 重要なやりとり
    FEEDBACK = "feedback"               # フィードバック受領
    REQUEST = "request"                 # 依頼・要望

    # 学習系
    LEARNING = "learning"               # 学習（CEO教え等）
    INSIGHT = "insight"                 # 気づき
    DISCOVERY = "discovery"             # 発見

    # 感情系
    EMOTION = "emotion"                 # 感情的な出来事
    CELEBRATION = "celebration"         # 祝い事
    CONCERN = "concern"                 # 懸念事項


class RecallTrigger(str, Enum):
    """想起のトリガー"""
    KEYWORD = "keyword"                 # キーワードマッチ
    SEMANTIC = "semantic"               # 意味的類似
    ENTITY = "entity"                   # エンティティマッチ
    TEMPORAL = "temporal"               # 時間的関連
    EMOTIONAL = "emotional"             # 感情的関連
    CAUSAL = "causal"                   # 因果関連
    SPATIAL = "spatial"                 # 場所関連（ルーム等）


class EntityType(str, Enum):
    """関連エンティティの種類"""
    PERSON = "person"                   # 人物
    TASK = "task"                       # タスク
    GOAL = "goal"                       # 目標
    ROOM = "room"                       # チャットルーム
    DOCUMENT = "document"               # ドキュメント
    PROJECT = "project"                 # プロジェクト
    ORGANIZATION = "organization"       # 組織
    MEETING = "meeting"                 # 会議
    EVENT = "event"                     # イベント


class EntityRelationship(str, Enum):
    """エンティティとの関係"""
    INVOLVED = "involved"               # 関与
    CAUSED = "caused"                   # 原因
    AFFECTED = "affected"               # 影響を受けた
    MENTIONED = "mentioned"             # 言及された
    OWNER = "owner"                     # 所有者
    ASSIGNEE = "assignee"               # 担当者
    WITNESS = "witness"                 # 目撃者


# ============================================================================
# 知識グラフ関連 Enum
# ============================================================================

class NodeType(str, Enum):
    """知識ノードの種類"""
    # 概念
    CONCEPT = "concept"                 # 抽象概念（「効率」「品質」等）
    CATEGORY = "category"               # カテゴリ（「営業」「開発」等）

    # エンティティ
    PERSON = "person"                   # 人物
    ORGANIZATION = "organization"       # 組織・部署
    LOCATION = "location"               # 場所
    PRODUCT = "product"                 # 製品・サービス
    PROJECT = "project"                 # プロジェクト

    # アクション・プロセス
    ACTION = "action"                   # 行動（「報告する」「確認する」等）
    PROCESS = "process"                 # プロセス（「承認フロー」等）

    # 属性・状態
    ATTRIBUTE = "attribute"             # 属性（「重要」「緊急」等）
    STATE = "state"                     # 状態（「進行中」「完了」等）

    # 時間・イベント
    EVENT = "event"                     # イベント
    PERIOD = "period"                   # 期間（「Q1」「来週」等）

    # ルール・知識
    RULE = "rule"                       # ルール・方針
    FACT = "fact"                       # 事実
    PREFERENCE = "preference"           # 嗜好


class EdgeType(str, Enum):
    """知識エッジの種類（関係タイプ）"""
    # 階層関係
    IS_A = "is_a"                       # AはBの一種（継承）
    PART_OF = "part_of"                 # AはBの一部
    HAS_A = "has_a"                     # AはBを持つ
    BELONGS_TO = "belongs_to"           # AはBに所属

    # 関連関係
    RELATED_TO = "related_to"           # 関連（汎用）
    SIMILAR_TO = "similar_to"           # 類似
    OPPOSITE_OF = "opposite_of"         # 反対
    SYNONYM_OF = "synonym_of"           # 同義

    # 因果関係
    CAUSES = "causes"                   # AはBを引き起こす
    PREVENTS = "prevents"               # AはBを防ぐ
    ENABLES = "enables"                 # AはBを可能にする
    REQUIRES = "requires"               # AにはBが必要

    # 時間関係
    BEFORE = "before"                   # AはBより前
    AFTER = "after"                     # AはBより後
    DURING = "during"                   # AはBの間
    FOLLOWS = "follows"                 # AはBに続く

    # 空間関係
    LOCATED_IN = "located_in"           # AはBにある
    NEAR = "near"                       # AはBの近く

    # 人間関係
    KNOWS = "knows"                     # AはBを知っている
    WORKS_WITH = "works_with"           # AはBと働く
    PEERS_WITH = "peers_with"           # AはBと同僚
    REPORTS_TO = "reports_to"           # AはBに報告
    SUPERVISES = "supervises"           # AはBを監督
    RESPONSIBLE_FOR = "responsible_for" # AはBの責任者

    # 属性関係
    HAS_ATTRIBUTE = "has_attribute"     # AにはB属性がある
    HAS_STATE = "has_state"             # AはB状態
    HAS_VALUE = "has_value"             # AにはB値がある


class KnowledgeSource(str, Enum):
    """知識の出所"""
    CONVERSATION = "conversation"       # 会話から抽出
    DOCUMENT = "document"               # ドキュメントから抽出
    MANUAL = "manual"                   # 手動入力
    INFERRED = "inferred"               # 推論
    SYSTEM = "system"                   # システム生成
    CEO_TEACHING = "ceo_teaching"       # CEO教え
    LEARNED = "learned"                 # 学習から取得


# ============================================================================
# 時系列記憶関連 Enum
# ============================================================================

class TemporalEventType(str, Enum):
    """時系列イベントの種類"""
    # 会議・コミュニケーション
    MEETING = "meeting"                 # 会議
    CALL = "call"                       # 通話
    PRESENTATION = "presentation"       # プレゼン

    # タスク・目標
    TASK_CREATED = "task_created"       # タスク作成
    TASK_COMPLETED = "task_completed"   # タスク完了
    TASK_OVERDUE = "task_overdue"       # タスク期限超過
    GOAL_PROGRESS = "goal_progress"     # 目標進捗
    GOAL_ACHIEVED = "goal_achieved"     # 目標達成

    # メトリクス
    METRIC_UPDATE = "metric_update"     # メトリクス更新
    KPI_REPORT = "kpi_report"           # KPIレポート

    # 状態変化
    STATUS_CHANGE = "status_change"     # ステータス変更
    PHASE_CHANGE = "phase_change"       # フェーズ変更

    # イベント
    ANNOUNCEMENT = "announcement"       # アナウンス
    DEADLINE = "deadline"               # 締め切り
    MILESTONE = "milestone"             # マイルストーン


class ComparisonType(str, Enum):
    """比較タイプ"""
    INCREASE = "increase"               # 増加
    DECREASE = "decrease"               # 減少
    SAME = "same"                       # 同じ
    FIRST = "first"                     # 初回（比較対象なし）
    BETTER = "better"                   # 改善
    WORSE = "worse"                     # 悪化


class TrendType(str, Enum):
    """トレンドタイプ"""
    IMPROVING = "improving"             # 改善傾向
    DECLINING = "declining"             # 悪化傾向
    STABLE = "stable"                   # 安定
    VOLATILE = "volatile"               # 変動大
    UNKNOWN = "unknown"                 # 不明


# ============================================================================
# 記憶統合関連 Enum
# ============================================================================

class ConsolidationType(str, Enum):
    """統合タイプ"""
    DAILY = "daily"                     # 日次
    WEEKLY = "weekly"                   # 週次
    MONTHLY = "monthly"                 # 月次
    MANUAL = "manual"                   # 手動
    TRIGGERED = "triggered"             # イベントトリガー


class ConsolidationAction(str, Enum):
    """統合アクション"""
    MERGE = "merge"                     # 統合
    FORGET = "forget"                   # 忘却
    PROMOTE = "promote"                 # 昇格（知識化）
    STRENGTHEN = "strengthen"           # 強化
    DECAY = "decay"                     # 減衰


# ============================================================================
# 閾値・パラメータ定数
# ============================================================================

# エピソード記憶
EPISODE_IMPORTANCE_MIN: float = 0.0
EPISODE_IMPORTANCE_MAX: float = 1.0
EPISODE_IMPORTANCE_DEFAULT: float = 0.5

EPISODE_DECAY_MIN: float = 0.0
EPISODE_DECAY_MAX: float = 1.0
EPISODE_DECAY_DEFAULT: float = 1.0

EMOTIONAL_VALENCE_MIN: float = -1.0
EMOTIONAL_VALENCE_MAX: float = 1.0
EMOTIONAL_VALENCE_DEFAULT: float = 0.0

# 忘却関連
DECAY_RATE_PER_DAY: float = 0.02          # 日あたりの減衰率
RECALL_IMPORTANCE_BOOST: float = 0.05      # 想起時の重要度回復
FORGET_THRESHOLD: float = 0.2              # この閾値以下で忘却候補
MIN_IMPORTANCE_FOR_RETENTION: float = 0.3  # 保持に必要な最低重要度

# 想起関連
MAX_RECALL_COUNT: int = 10                 # 最大想起数
RECALL_RELEVANCE_THRESHOLD: float = 0.3    # 想起の関連度閾値
KEYWORD_MATCH_WEIGHT: float = 1.0          # キーワードマッチの重み
ENTITY_MATCH_WEIGHT: float = 0.8           # エンティティマッチの重み
TEMPORAL_MATCH_WEIGHT: float = 0.6         # 時間マッチの重み
SEMANTIC_MATCH_WEIGHT: float = 0.9         # 意味マッチの重み

# 知識グラフ
KNOWLEDGE_CONFIDENCE_MIN: float = 0.0
KNOWLEDGE_CONFIDENCE_MAX: float = 1.0
KNOWLEDGE_CONFIDENCE_DEFAULT: float = 0.5

EDGE_WEIGHT_MIN: float = 0.0
EDGE_WEIGHT_MAX: float = 1.0
EDGE_WEIGHT_DEFAULT: float = 0.5

NODE_ACTIVATION_DECAY: float = 0.1         # ノード活性度の減衰率
EDGE_EVIDENCE_THRESHOLD: int = 3           # エッジ確定に必要なエビデンス数

# 時系列記憶
TEMPORAL_COMPARISON_WINDOW_DAYS: int = 30  # 比較ウィンドウ（日）
TREND_MIN_DATA_POINTS: int = 3             # トレンド判定に必要な最小データ点
TREND_IMPROVING_THRESHOLD: float = 0.1     # 改善判定閾値
TREND_DECLINING_THRESHOLD: float = -0.1    # 悪化判定閾値

# 記憶統合
CONSOLIDATION_SIMILARITY_THRESHOLD: float = 0.8  # 統合対象の類似度閾値
CONSOLIDATION_MIN_EPISODES: int = 2              # 統合に必要な最小エピソード数
KNOWLEDGE_PROMOTION_THRESHOLD: float = 0.7       # 知識昇格の閾値
KNOWLEDGE_PROMOTION_MIN_EVIDENCE: int = 3        # 知識昇格に必要な最小エビデンス数


# ============================================================================
# エピソードタイプ別の基本重要度
# ============================================================================

BASE_IMPORTANCE: Dict[EpisodeType, float] = {
    # 達成・成功系（高重要度）
    EpisodeType.ACHIEVEMENT: 0.8,
    EpisodeType.MILESTONE: 0.85,
    EpisodeType.BREAKTHROUGH: 0.9,

    # 失敗・問題系（中〜高重要度）
    EpisodeType.FAILURE: 0.7,
    EpisodeType.CONFLICT: 0.75,
    EpisodeType.OBSTACLE: 0.65,

    # 判断・決定系（高重要度）
    EpisodeType.DECISION: 0.8,
    EpisodeType.COMMITMENT: 0.75,
    EpisodeType.CHANGE: 0.7,

    # やりとり系（中重要度）
    EpisodeType.INTERACTION: 0.4,
    EpisodeType.FEEDBACK: 0.6,
    EpisodeType.REQUEST: 0.5,

    # 学習系（高重要度）
    EpisodeType.LEARNING: 0.9,
    EpisodeType.INSIGHT: 0.85,
    EpisodeType.DISCOVERY: 0.8,

    # 感情系（中重要度）
    EpisodeType.EMOTION: 0.5,
    EpisodeType.CELEBRATION: 0.6,
    EpisodeType.CONCERN: 0.55,
}


# ============================================================================
# 重要キーワード
# ============================================================================

IMPORTANT_KEYWORDS: Set[str] = {
    # 達成関連
    "目標", "達成", "完了", "成功", "クリア", "突破",

    # 問題関連
    "問題", "失敗", "エラー", "バグ", "障害", "トラブル",

    # 改善関連
    "解決", "改善", "修正", "対応", "対策",

    # 学習関連
    "学習", "気づき", "発見", "理解", "納得",

    # 判断関連
    "決定", "決断", "選択", "判断", "方針",

    # 緊急関連
    "重要", "緊急", "至急", "優先", "注意",

    # 感情関連
    "ありがとう", "すごい", "困った", "助けて", "嬉しい", "残念",

    # ビジネス関連
    "売上", "利益", "コスト", "納期", "品質",
}


# ============================================================================
# キーワード抽出パターン
# ============================================================================

KEYWORD_PATTERNS = [
    (r"「([^」]+)」", "quoted"),           # 引用
    (r"【([^】]+)】", "bracketed"),        # 角括弧
    (r"『([^』]+)』", "double_quoted"),    # 二重引用
    (r"#(\w+)", "hashtag"),               # ハッシュタグ
    (r"@(\w+)", "mention"),               # メンション
]


# ============================================================================
# 曜日・時間帯名
# ============================================================================

DAY_OF_WEEK_NAMES: Dict[int, str] = {
    0: "月曜日",
    1: "火曜日",
    2: "水曜日",
    3: "木曜日",
    4: "金曜日",
    5: "土曜日",
    6: "日曜日",
}

TIME_SLOT_NAMES: Dict[str, Dict[str, int]] = {
    "早朝": {"start": 5, "end": 7},
    "朝": {"start": 7, "end": 9},
    "午前": {"start": 9, "end": 12},
    "昼": {"start": 12, "end": 14},
    "午後": {"start": 14, "end": 17},
    "夕方": {"start": 17, "end": 19},
    "夜": {"start": 19, "end": 22},
    "深夜": {"start": 22, "end": 5},
}
