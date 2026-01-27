"""
Phase 2H: 自己認識（Self-Awareness）- 定数定義

設計書: docs/17_brain_completion_roadmap.md セクション Phase 2H

能力の自己評価、限界の認識、改善点の自己発見に関する定数とEnum定義。
"""

from enum import Enum
from typing import Dict, Set


# ============================================================================
# テーブル名
# ============================================================================

TABLE_BRAIN_ABILITIES = "brain_abilities"
TABLE_BRAIN_ABILITY_SCORES = "brain_ability_scores"
TABLE_BRAIN_LIMITATIONS = "brain_limitations"
TABLE_BRAIN_IMPROVEMENT_LOGS = "brain_improvement_logs"
TABLE_BRAIN_SELF_DIAGNOSES = "brain_self_diagnoses"


# ============================================================================
# 能力カテゴリ Enum
# ============================================================================

class AbilityCategory(str, Enum):
    """能力カテゴリ

    ソウルくんが持つ能力の大分類。
    """
    # コア能力
    TASK_MANAGEMENT = "task_management"       # タスク管理
    KNOWLEDGE_SEARCH = "knowledge_search"     # ナレッジ検索
    GOAL_SUPPORT = "goal_support"             # 目標達成支援
    COMMUNICATION = "communication"           # コミュニケーション

    # 分析能力
    PATTERN_DETECTION = "pattern_detection"   # パターン検出
    EMOTION_ANALYSIS = "emotion_analysis"     # 感情分析
    BOTTLENECK_DETECTION = "bottleneck_detection"  # ボトルネック検出

    # 学習能力
    LEARNING_FROM_FEEDBACK = "learning_from_feedback"  # フィードバック学習
    OUTCOME_LEARNING = "outcome_learning"     # 結果からの学習
    CEO_TEACHING = "ceo_teaching"             # CEO教え理解

    # 対人能力
    PERSONALIZATION = "personalization"       # 個人化
    CONTEXT_UNDERSTANDING = "context_understanding"  # 文脈理解
    TONE_ADAPTATION = "tone_adaptation"       # トーン適応

    # その他
    GENERAL = "general"                       # 汎用


class AbilityLevel(str, Enum):
    """能力レベル"""
    EXPERT = "expert"           # 得意（0.8-1.0）
    PROFICIENT = "proficient"   # 普通（0.6-0.8）
    DEVELOPING = "developing"   # 発展中（0.4-0.6）
    NOVICE = "novice"           # 苦手（0.2-0.4）
    UNKNOWN = "unknown"         # 不明（データ不足）


class LimitationType(str, Enum):
    """限界タイプ"""
    # 知識的限界
    KNOWLEDGE_GAP = "knowledge_gap"           # 知識がない
    OUTDATED_INFO = "outdated_info"           # 情報が古い
    DOMAIN_SPECIFIC = "domain_specific"       # 専門外

    # 機能的限界
    CAPABILITY_LIMIT = "capability_limit"     # 機能的にできない
    PERMISSION_LIMIT = "permission_limit"     # 権限がない
    RESOURCE_LIMIT = "resource_limit"         # リソース不足

    # 判断的限界
    UNCERTAINTY = "uncertainty"               # 不確実
    AMBIGUITY = "ambiguity"                   # 曖昧
    ETHICAL_CONCERN = "ethical_concern"       # 倫理的懸念

    # コンテキスト的限界
    MISSING_CONTEXT = "missing_context"       # 文脈不足
    CONFLICTING_INFO = "conflicting_info"     # 矛盾する情報


class ImprovementType(str, Enum):
    """改善タイプ"""
    ACCURACY = "accuracy"                     # 正確性向上
    SPEED = "speed"                           # 速度向上
    COVERAGE = "coverage"                     # カバレッジ拡大
    CONSISTENCY = "consistency"               # 一貫性向上
    PERSONALIZATION = "personalization"       # パーソナライズ向上


class DiagnosisType(str, Enum):
    """診断タイプ"""
    DAILY = "daily"                           # 日次診断
    WEEKLY = "weekly"                         # 週次診断
    MONTHLY = "monthly"                       # 月次診断
    ON_DEMAND = "on_demand"                   # オンデマンド診断


class ConfidenceLevel(str, Enum):
    """確信度レベル"""
    HIGH = "high"               # 高い（0.8-1.0）- そのまま回答
    MEDIUM = "medium"           # 中程度（0.5-0.8）- 確認推奨
    LOW = "low"                 # 低い（0.3-0.5）- 慎重に回答
    VERY_LOW = "very_low"       # 非常に低い（0-0.3）- エスカレーション


class EscalationReason(str, Enum):
    """エスカレーション理由"""
    LOW_CONFIDENCE = "low_confidence"         # 確信度が低い
    DOMAIN_EXPERTISE = "domain_expertise"     # 専門家が必要
    SENSITIVE_TOPIC = "sensitive_topic"       # デリケートな話題
    HIGH_IMPACT = "high_impact"               # 影響が大きい
    USER_REQUEST = "user_request"             # ユーザー要求


# ============================================================================
# 閾値・パラメータ定数
# ============================================================================

# 能力スコア
ABILITY_SCORE_MIN: float = 0.0
ABILITY_SCORE_MAX: float = 1.0
ABILITY_SCORE_DEFAULT: float = 0.5

# 能力レベル閾値
ABILITY_LEVEL_THRESHOLDS: Dict[AbilityLevel, tuple] = {
    AbilityLevel.EXPERT: (0.8, 1.0),
    AbilityLevel.PROFICIENT: (0.6, 0.8),
    AbilityLevel.DEVELOPING: (0.4, 0.6),
    AbilityLevel.NOVICE: (0.2, 0.4),
    AbilityLevel.UNKNOWN: (0.0, 0.2),
}

# 確信度閾値
CONFIDENCE_THRESHOLD_HIGH: float = 0.8
CONFIDENCE_THRESHOLD_MEDIUM: float = 0.5
CONFIDENCE_THRESHOLD_LOW: float = 0.3

# 確信度レベル閾値
CONFIDENCE_LEVEL_THRESHOLDS: Dict[ConfidenceLevel, tuple] = {
    ConfidenceLevel.HIGH: (0.8, 1.0),
    ConfidenceLevel.MEDIUM: (0.5, 0.8),
    ConfidenceLevel.LOW: (0.3, 0.5),
    ConfidenceLevel.VERY_LOW: (0.0, 0.3),
}

# エスカレーション
ESCALATION_CONFIDENCE_THRESHOLD: float = 0.3  # この確信度以下でエスカレーション
AUTO_ESCALATION_ENABLED: bool = True

# 改善追跡
IMPROVEMENT_TRACKING_WINDOW_DAYS: int = 30  # 改善追跡ウィンドウ（日）
MIN_SAMPLES_FOR_TREND: int = 5              # トレンド判定に必要な最小サンプル数
IMPROVEMENT_THRESHOLD: float = 0.1          # 改善判定閾値
REGRESSION_THRESHOLD: float = -0.1          # 悪化判定閾値

# 自己診断
DIAGNOSIS_MIN_INTERACTIONS: int = 10        # 診断に必要な最小インタラクション数
DIAGNOSIS_REPORT_MAX_ITEMS: int = 10        # 診断レポートの最大項目数

# スコア更新
SCORE_UPDATE_WEIGHT_SUCCESS: float = 0.1    # 成功時のスコア更新重み
SCORE_UPDATE_WEIGHT_FAILURE: float = 0.15   # 失敗時のスコア更新重み（重め）
SCORE_DECAY_RATE: float = 0.01              # スコア減衰率（日）


# ============================================================================
# カテゴリ別デフォルト能力スコア
# ============================================================================

DEFAULT_ABILITY_SCORES: Dict[AbilityCategory, float] = {
    AbilityCategory.TASK_MANAGEMENT: 0.7,
    AbilityCategory.KNOWLEDGE_SEARCH: 0.6,
    AbilityCategory.GOAL_SUPPORT: 0.65,
    AbilityCategory.COMMUNICATION: 0.7,
    AbilityCategory.PATTERN_DETECTION: 0.5,
    AbilityCategory.EMOTION_ANALYSIS: 0.5,
    AbilityCategory.BOTTLENECK_DETECTION: 0.5,
    AbilityCategory.LEARNING_FROM_FEEDBACK: 0.6,
    AbilityCategory.OUTCOME_LEARNING: 0.5,
    AbilityCategory.CEO_TEACHING: 0.6,
    AbilityCategory.PERSONALIZATION: 0.5,
    AbilityCategory.CONTEXT_UNDERSTANDING: 0.55,
    AbilityCategory.TONE_ADAPTATION: 0.6,
    AbilityCategory.GENERAL: 0.5,
}


# ============================================================================
# 不確実性を示すキーワード
# ============================================================================

UNCERTAINTY_KEYWORDS: Set[str] = {
    # 明示的な不確実性
    "かもしれません", "可能性があります", "おそらく", "たぶん",
    "思います", "推測", "不明", "わかりません",

    # 条件付き
    "場合によっては", "状況次第", "ケースバイケース",

    # 確認推奨
    "確認してください", "ご確認ください", "確認をお勧め",
}


# ============================================================================
# 専門家エスカレーション対象
# ============================================================================

ESCALATION_DOMAINS: Dict[str, str] = {
    "法務": "legal_expert",
    "税務": "tax_expert",
    "労務": "hr_expert",
    "技術": "tech_expert",
    "経理": "accounting_expert",
    "営業戦略": "sales_expert",
}


# ============================================================================
# 確認メッセージテンプレート
# ============================================================================

CONFIRMATION_TEMPLATES: Dict[ConfidenceLevel, str] = {
    ConfidenceLevel.HIGH: "",  # 確認不要
    ConfidenceLevel.MEDIUM: "（念のため確認をお勧めしますウル）",
    ConfidenceLevel.LOW: "（この点については確信が持てないので、確認いただけると助かりますウル）",
    ConfidenceLevel.VERY_LOW: "（申し訳ありませんが、この分野は苦手なので、専門の方に確認いただくことをお勧めしますウル）",
}


# ============================================================================
# 能力向上メッセージ
# ============================================================================

IMPROVEMENT_MESSAGES: Dict[str, str] = {
    "accuracy_improved": "正確性が向上しました",
    "speed_improved": "応答速度が向上しました",
    "coverage_improved": "対応範囲が広がりました",
    "consistency_improved": "一貫性が向上しました",
    "personalization_improved": "個人化が向上しました",
}
