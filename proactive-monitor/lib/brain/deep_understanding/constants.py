# lib/brain/deep_understanding/constants.py
"""
Phase 2I: 理解力強化（Deep Understanding）- 定数定義

設計書: docs/17_brain_completion_roadmap.md セクション17.3 Phase 2I

このファイルには、深い理解層で使用する定数と列挙型を定義します。

【Phase 2I の能力】
- 暗黙の意図推測（「これ」が何を指すか）
- 組織文脈の理解（「いつものやつ」の解釈）
- 感情・ニュアンスの読み取り（「ちょっと急いでる」の緊急度判断）

Author: Claude Opus 4.5
Created: 2026-01-27
"""

from enum import Enum, auto
from typing import Any, Dict, List, Set


# =============================================================================
# 意図推測関連の定数
# =============================================================================

class ImplicitIntentType(Enum):
    """暗黙の意図タイプ"""

    # 指示代名詞による参照
    PRONOUN_REFERENCE = "pronoun_reference"  # これ、それ、あれ

    # 省略による参照
    ELLIPSIS_REFERENCE = "ellipsis_reference"  # 主語省略、目的語省略

    # 文脈依存の曖昧表現
    CONTEXT_DEPENDENT = "context_dependent"  # いつもの、例の

    # 組織固有の慣用表現
    ORGANIZATION_IDIOM = "organization_idiom"  # 社内用語

    # 暗黙の期待・要求
    IMPLICIT_REQUEST = "implicit_request"  # 婉曲的な依頼

    # 確認・同意の暗黙表現
    IMPLICIT_CONFIRMATION = "implicit_confirmation"  # 「そうですね」の真意

    # 否定の婉曲表現
    IMPLICIT_NEGATION = "implicit_negation"  # 「ちょっと難しいかも」


class ReferenceResolutionStrategy(Enum):
    """参照解決の戦略"""

    # 直前の発話から解決
    IMMEDIATE_CONTEXT = "immediate_context"

    # 会話履歴全体から解決
    CONVERSATION_HISTORY = "conversation_history"

    # 最近のタスクから解決
    RECENT_TASKS = "recent_tasks"

    # 人物情報から解決
    PERSON_INFO = "person_info"

    # 組織語彙から解決
    ORGANIZATION_VOCABULARY = "organization_vocabulary"

    # LLMによる推論
    LLM_INFERENCE = "llm_inference"


# 指示代名詞のマッピング
DEMONSTRATIVE_PRONOUNS: Dict[str, Dict[str, str]] = {
    # 近称（話し手に近い）
    "これ": {"distance": "near", "type": "thing"},
    "この": {"distance": "near", "type": "modifier"},
    "ここ": {"distance": "near", "type": "place"},
    "こちら": {"distance": "near", "type": "direction"},
    "こいつ": {"distance": "near", "type": "thing_casual"},
    "こっち": {"distance": "near", "type": "direction_casual"},

    # 中称（聞き手に近い）
    "それ": {"distance": "middle", "type": "thing"},
    "その": {"distance": "middle", "type": "modifier"},
    "そこ": {"distance": "middle", "type": "place"},
    "そちら": {"distance": "middle", "type": "direction"},
    "そいつ": {"distance": "middle", "type": "thing_casual"},
    "そっち": {"distance": "middle", "type": "direction_casual"},

    # 遠称（両者から遠い）
    "あれ": {"distance": "far", "type": "thing"},
    "あの": {"distance": "far", "type": "modifier"},
    "あそこ": {"distance": "far", "type": "place"},
    "あちら": {"distance": "far", "type": "direction"},
    "あいつ": {"distance": "far", "type": "thing_casual"},
    "あっち": {"distance": "far", "type": "direction_casual"},

    # 不定称
    "どれ": {"distance": "unknown", "type": "thing"},
    "どの": {"distance": "unknown", "type": "modifier"},
    "どこ": {"distance": "unknown", "type": "place"},
    "どちら": {"distance": "unknown", "type": "direction"},
}

# 人称代名詞
PERSONAL_PRONOUNS: Dict[str, Dict[str, str]] = {
    # 一人称
    "私": {"person": "first", "formality": "neutral"},
    "僕": {"person": "first", "formality": "casual"},
    "俺": {"person": "first", "formality": "very_casual"},
    "自分": {"person": "first", "formality": "neutral"},
    "わたくし": {"person": "first", "formality": "formal"},

    # 二人称
    "あなた": {"person": "second", "formality": "neutral"},
    "君": {"person": "second", "formality": "casual"},
    "お前": {"person": "second", "formality": "very_casual"},

    # 三人称
    "彼": {"person": "third", "formality": "neutral", "gender": "male"},
    "彼女": {"person": "third", "formality": "neutral", "gender": "female"},
    "あの人": {"person": "third", "formality": "neutral"},
    "その人": {"person": "third", "formality": "neutral"},
    "この人": {"person": "third", "formality": "neutral"},
}

# 曖昧な時間表現
VAGUE_TIME_EXPRESSIONS: Dict[str, Dict[str, Any]] = {
    # 相対的な時間
    "あとで": {"type": "relative", "urgency": "low", "range_hours": (1, 24)},
    "後ほど": {"type": "relative", "urgency": "low", "range_hours": (1, 8)},
    "そのうち": {"type": "relative", "urgency": "very_low", "range_hours": (24, 168)},
    "近いうちに": {"type": "relative", "urgency": "medium", "range_hours": (24, 72)},
    "いずれ": {"type": "relative", "urgency": "very_low", "range_hours": (168, 720)},
    "できれば今日中": {"type": "relative", "urgency": "medium", "range_hours": (0, 12)},
    "今週中": {"type": "relative", "urgency": "medium", "range_hours": (0, 168)},
    "来週中": {"type": "relative", "urgency": "low", "range_hours": (168, 336)},

    # 曖昧な期限
    "なる早": {"type": "deadline", "urgency": "high", "range_hours": (0, 24)},
    "なるべく早く": {"type": "deadline", "urgency": "high", "range_hours": (0, 24)},
    "できるだけ早く": {"type": "deadline", "urgency": "high", "range_hours": (0, 24)},
    "急ぎで": {"type": "deadline", "urgency": "high", "range_hours": (0, 8)},
    "至急": {"type": "deadline", "urgency": "very_high", "range_hours": (0, 4)},
    "大至急": {"type": "deadline", "urgency": "critical", "range_hours": (0, 2)},
    "いつでも": {"type": "deadline", "urgency": "very_low", "range_hours": (0, 720)},
    "余裕があれば": {"type": "deadline", "urgency": "very_low", "range_hours": (0, 720)},
}

# 婉曲的依頼パターン
INDIRECT_REQUEST_PATTERNS: List[str] = [
    r"(.*)(できたら|できれば|可能なら|よければ)(.*)(いただけ|もらえ|くれ)",
    r"(.*)(ちょっと|少し)(.*)(見て|確認して|チェックして)",
    r"(.*)(時間ある|手が空いた)(.*)とき(に|は)",
    r"(.*)(もし|仮に)(.*)(なら|だったら)",
    r"(.*)(頼め|お願いでき)(.*)(ますか|るかな)",
    r"(.*)(助けて|手伝って)(.*)(ほしい|くれない)",
]

# 婉曲的否定パターン
INDIRECT_NEGATION_PATTERNS: List[str] = [
    r"(ちょっと|少し)(難しい|厳しい|きつい)(かも|かな)",
    r"(うーん|んー).*(どうかな|微妙)",
    r"(今は|いまは).*(ちょっと|難しい)",
    r"(考えて|検討して)(おきます|みます)",
    r"(前向きに|善処)(します|検討)",
    r"(申し訳|すみません).*(ちょっと|今は)",
]


# =============================================================================
# 組織文脈理解関連の定数
# =============================================================================

class OrganizationContextType(Enum):
    """組織文脈のタイプ"""

    # 社内プロセス
    INTERNAL_PROCESS = "internal_process"  # 「いつもの手続き」

    # 定例イベント
    RECURRING_EVENT = "recurring_event"  # 「毎週のあれ」

    # 人物・役割
    PERSON_ROLE = "person_role"  # 「あの人」「担当者」

    # プロジェクト
    PROJECT = "project"  # 「例のプロジェクト」

    # ドキュメント
    DOCUMENT = "document"  # 「あの資料」

    # 場所・会議室
    LOCATION = "location"  # 「いつもの部屋」

    # 社内用語
    INTERNAL_TERM = "internal_term"  # 社内略語、コードネーム


class VocabularyCategory(Enum):
    """組織語彙のカテゴリ"""

    # プロジェクト名
    PROJECT_NAME = "project_name"

    # 製品・サービス名
    PRODUCT_NAME = "product_name"

    # 社内略語
    ABBREVIATION = "abbreviation"

    # 部署・チーム名
    TEAM_NAME = "team_name"

    # 役職・役割
    ROLE_NAME = "role_name"

    # 社内イベント
    EVENT_NAME = "event_name"

    # 社内システム
    SYSTEM_NAME = "system_name"

    # その他の慣用表現
    IDIOM = "idiom"


# デフォルトの組織語彙（ソウルシンクス固有）
DEFAULT_ORGANIZATION_VOCABULARY: Dict[str, Dict[str, Any]] = {
    # 例：ソウルシンクス固有の語彙
    "ソウルくん": {
        "category": VocabularyCategory.PRODUCT_NAME.value,
        "meaning": "社内AIアシスタントシステム",
        "aliases": ["soul-kun", "soulkun"],
    },
    "カズさん": {
        "category": VocabularyCategory.ROLE_NAME.value,
        "meaning": "CEO、最高意思決定者",
        "aliases": ["社長", "代表"],
    },
    "全体会議": {
        "category": VocabularyCategory.EVENT_NAME.value,
        "meaning": "週次の全社ミーティング",
        "aliases": ["全体MTG", "オールハンズ"],
    },
}


# =============================================================================
# 感情・ニュアンス関連の定数
# =============================================================================

class EmotionCategory(Enum):
    """感情カテゴリ"""

    # ポジティブ
    HAPPY = "happy"  # 嬉しい、楽しい
    EXCITED = "excited"  # ワクワク、期待
    GRATEFUL = "grateful"  # 感謝
    RELIEVED = "relieved"  # 安心
    PROUD = "proud"  # 誇らしい

    # ネガティブ
    FRUSTRATED = "frustrated"  # イライラ、困惑
    ANXIOUS = "anxious"  # 不安、心配
    SAD = "sad"  # 悲しい
    ANGRY = "angry"  # 怒り
    DISAPPOINTED = "disappointed"  # がっかり
    STRESSED = "stressed"  # ストレス

    # 中立・その他
    NEUTRAL = "neutral"  # 中立
    CONFUSED = "confused"  # 困惑
    CURIOUS = "curious"  # 興味
    UNCERTAIN = "uncertain"  # 不確か


class UrgencyLevel(Enum):
    """緊急度レベル"""

    CRITICAL = "critical"  # 今すぐ対応必須
    VERY_HIGH = "very_high"  # 数時間以内
    HIGH = "high"  # 本日中
    MEDIUM = "medium"  # 今週中
    LOW = "low"  # いつでも
    VERY_LOW = "very_low"  # 余裕があれば


class NuanceType(Enum):
    """ニュアンスのタイプ"""

    # 確信度
    CERTAINTY_HIGH = "certainty_high"  # 確信あり
    CERTAINTY_MEDIUM = "certainty_medium"  # 中程度
    CERTAINTY_LOW = "certainty_low"  # 不確か

    # 丁寧さ
    FORMAL = "formal"  # フォーマル
    CASUAL = "casual"  # カジュアル
    URGENT = "urgent"  # 急いでいる

    # トーン
    POSITIVE = "positive"  # ポジティブ
    NEGATIVE = "negative"  # ネガティブ
    SARCASTIC = "sarcastic"  # 皮肉
    HUMOROUS = "humorous"  # ユーモア


# 感情を示すキーワード（拡張版）
EMOTION_INDICATORS: Dict[str, Dict[str, List[str]]] = {
    EmotionCategory.HAPPY.value: {
        "keywords": ["嬉しい", "うれしい", "やった", "よかった", "最高", "ラッキー"],
        "expressions": ["！", "♪", "(*^^*)", "(^-^)"],
        "intensity": ["とても", "すごく", "めっちゃ", "本当に"],
    },
    EmotionCategory.EXCITED.value: {
        "keywords": ["楽しみ", "ワクワク", "待ち遠しい", "期待", "興奮"],
        "expressions": ["！！", "！！！", "(*ﾟ▽ﾟ*)"],
        "intensity": ["すごく", "めちゃくちゃ", "本当に"],
    },
    EmotionCategory.GRATEFUL.value: {
        "keywords": ["ありがとう", "感謝", "助かる", "おかげ", "恩"],
        "expressions": ["m(_ _)m", "🙏"],
        "intensity": ["本当に", "心から", "誠に"],
    },
    EmotionCategory.FRUSTRATED.value: {
        "keywords": ["困った", "困る", "どうしよう", "参った", "まいった", "厳しい"],
        "expressions": ["…", "。。。", "(´・ω・`)"],
        "intensity": ["かなり", "とても", "本当に"],
    },
    EmotionCategory.ANXIOUS.value: {
        "keywords": ["心配", "不安", "大丈夫", "気になる", "怖い"],
        "expressions": ["…", "？？"],
        "intensity": ["すごく", "とても", "少し"],
    },
    EmotionCategory.ANGRY.value: {
        "keywords": ["なんで", "どうして", "ふざけ", "ありえない", "許せない", "イライラ"],
        "expressions": ["！！", "💢"],
        "intensity": ["本当に", "マジで", "いい加減"],
    },
    EmotionCategory.STRESSED.value: {
        "keywords": ["忙しい", "時間ない", "余裕ない", "手一杯", "パンク", "しんどい"],
        "expressions": ["…", "(汗)", "💦"],
        "intensity": ["かなり", "めちゃくちゃ", "超"],
    },
    EmotionCategory.CONFUSED.value: {
        "keywords": ["わからない", "分からない", "理解できない", "意味不明", "どういう"],
        "expressions": ["？", "？？", "？？？"],
        "intensity": ["全く", "さっぱり", "いまいち"],
    },
}

# 緊急度を示すキーワード（拡張版）
URGENCY_INDICATORS: Dict[str, List[str]] = {
    UrgencyLevel.CRITICAL.value: [
        "今すぐ", "直ちに", "大至急", "緊急", "すぐに", "即座に",
        "待ったなし", "一刻も早く", "火急の",
    ],
    UrgencyLevel.VERY_HIGH.value: [
        "至急", "急いで", "なる早", "できるだけ早く", "早急に",
        "速やかに", "急ぎで",
    ],
    UrgencyLevel.HIGH.value: [
        "今日中", "本日中", "午前中", "午後一", "COB",
        "夕方まで", "終業まで",
    ],
    UrgencyLevel.MEDIUM.value: [
        "今週中", "週内", "数日中", "近いうちに", "そろそろ",
    ],
    UrgencyLevel.LOW.value: [
        "いつでも", "余裕があれば", "手が空いたら", "都合が良い時",
        "急がない", "ゆっくり",
    ],
    UrgencyLevel.VERY_LOW.value: [
        "いずれ", "そのうち", "時間がある時", "優先度低",
        "後回しで", "backlog",
    ],
}


# =============================================================================
# 文脈復元関連の定数
# =============================================================================

class ContextRecoverySource(Enum):
    """文脈復元のソース"""

    # 会話履歴
    CONVERSATION_HISTORY = "conversation_history"

    # タスク履歴
    TASK_HISTORY = "task_history"

    # エピソード記憶
    EPISODIC_MEMORY = "episodic_memory"

    # 組織ナレッジ
    ORGANIZATION_KNOWLEDGE = "organization_knowledge"

    # 人物情報
    PERSON_INFO = "person_info"

    # カレンダー・予定
    CALENDAR = "calendar"


# 会話履歴の参照範囲
CONTEXT_WINDOW_CONFIG = {
    # 直近の発話（高優先度）
    "immediate": {
        "message_count": 3,
        "time_window_minutes": 10,
        "weight": 1.0,
    },
    # 短期コンテキスト（中優先度）
    "short_term": {
        "message_count": 10,
        "time_window_minutes": 60,
        "weight": 0.7,
    },
    # 中期コンテキスト（低優先度）
    "medium_term": {
        "message_count": 30,
        "time_window_minutes": 360,
        "weight": 0.4,
    },
    # 長期コンテキスト（最低優先度）
    "long_term": {
        "message_count": 100,
        "time_window_minutes": 1440,
        "weight": 0.2,
    },
}


# =============================================================================
# 設定関連の定数
# =============================================================================

# 意図推測の信頼度閾値
INTENT_CONFIDENCE_THRESHOLDS = {
    "auto_execute": 0.9,  # 自動実行可能
    "high": 0.8,  # 高信頼度
    "medium": 0.6,  # 中程度
    "low": 0.4,  # 低信頼度
    "very_low": 0.2,  # 非常に低い（確認必須）
}

# 感情検出の信頼度閾値
EMOTION_CONFIDENCE_THRESHOLDS = {
    "confident": 0.8,
    "likely": 0.6,
    "possible": 0.4,
    "uncertain": 0.2,
}

# 文脈復元の最大試行回数
MAX_CONTEXT_RECOVERY_ATTEMPTS = 3

# 組織語彙の最大エントリ数（組織あたり）
MAX_VOCABULARY_ENTRIES_PER_ORG = 10000

# 語彙学習の最小出現回数
MIN_OCCURRENCE_FOR_VOCABULARY_LEARNING = 3

# Feature Flags
FEATURE_FLAG_DEEP_UNDERSTANDING = "deep_understanding_enabled"
FEATURE_FLAG_IMPLICIT_INTENT = "implicit_intent_enabled"
FEATURE_FLAG_ORGANIZATION_CONTEXT = "organization_context_enabled"
FEATURE_FLAG_EMOTION_READING = "emotion_reading_enabled"
FEATURE_FLAG_VOCABULARY_LEARNING = "vocabulary_learning_enabled"


# =============================================================================
# エクスポート
# =============================================================================

__all__ = [
    # 列挙型
    "ImplicitIntentType",
    "ReferenceResolutionStrategy",
    "OrganizationContextType",
    "VocabularyCategory",
    "EmotionCategory",
    "UrgencyLevel",
    "NuanceType",
    "ContextRecoverySource",

    # 定数
    "DEMONSTRATIVE_PRONOUNS",
    "PERSONAL_PRONOUNS",
    "VAGUE_TIME_EXPRESSIONS",
    "INDIRECT_REQUEST_PATTERNS",
    "INDIRECT_NEGATION_PATTERNS",
    "DEFAULT_ORGANIZATION_VOCABULARY",
    "EMOTION_INDICATORS",
    "URGENCY_INDICATORS",
    "CONTEXT_WINDOW_CONFIG",
    "INTENT_CONFIDENCE_THRESHOLDS",
    "EMOTION_CONFIDENCE_THRESHOLDS",
    "MAX_CONTEXT_RECOVERY_ATTEMPTS",
    "MAX_VOCABULARY_ENTRIES_PER_ORG",
    "MIN_OCCURRENCE_FOR_VOCABULARY_LEARNING",

    # Feature Flags
    "FEATURE_FLAG_DEEP_UNDERSTANDING",
    "FEATURE_FLAG_IMPLICIT_INTENT",
    "FEATURE_FLAG_ORGANIZATION_CONTEXT",
    "FEATURE_FLAG_EMOTION_READING",
    "FEATURE_FLAG_VOCABULARY_LEARNING",
]
