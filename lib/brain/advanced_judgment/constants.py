# lib/brain/advanced_judgment/constants.py
"""
Phase 2J: 判断力強化（Advanced Judgment）- 定数定義

設計書: docs/17_brain_completion_roadmap.md セクション17.3 Phase 2J

このファイルには、高度な判断層で使用する定数と列挙型を定義します。

【Phase 2J の能力】
- 複数選択肢の比較評価
- トレードオフの明示化（「Aを取ればBを犠牲に」）
- リスク・リターンの定量評価
- 過去の判断との整合性チェック

【ユースケース】
- 「この案件、受けるべき？」への多角的回答
- 採用候補者の比較評価支援
- 投資判断のリスク分析

Author: Claude Opus 4.5
Created: 2026-01-27
"""

from enum import Enum, auto
from typing import Dict, List, Tuple, Any


# =============================================================================
# 判断タイプ関連の定数
# =============================================================================

class JudgmentType(Enum):
    """判断のタイプ"""

    # 比較評価型
    COMPARISON = "comparison"  # 複数選択肢の比較
    RANKING = "ranking"  # 順位付け
    BEST_CHOICE = "best_choice"  # 最適解の選択

    # リスク評価型
    RISK_ASSESSMENT = "risk_assessment"  # リスク分析
    OPPORTUNITY_ASSESSMENT = "opportunity_assessment"  # 機会分析
    RISK_RETURN_ANALYSIS = "risk_return_analysis"  # リスク・リターン分析

    # 意思決定型
    GO_NO_GO = "go_no_go"  # 実行可否判断
    APPROVAL_DECISION = "approval_decision"  # 承認判断
    RESOURCE_ALLOCATION = "resource_allocation"  # リソース配分

    # 人事評価型
    CANDIDATE_EVALUATION = "candidate_evaluation"  # 候補者評価
    PERFORMANCE_REVIEW = "performance_review"  # パフォーマンス評価

    # 投資・財務型
    INVESTMENT_DECISION = "investment_decision"  # 投資判断
    BUDGET_DECISION = "budget_decision"  # 予算判断
    ROI_ANALYSIS = "roi_analysis"  # ROI分析


class JudgmentComplexity(Enum):
    """判断の複雑さ"""

    # シンプル（2択など）
    SIMPLE = "simple"

    # 標準（3-5選択肢）
    MODERATE = "moderate"

    # 複雑（6選択肢以上、多次元評価）
    COMPLEX = "complex"

    # 非常に複雑（戦略的判断、長期影響）
    HIGHLY_COMPLEX = "highly_complex"


# =============================================================================
# 評価基準関連の定数
# =============================================================================

class CriterionCategory(Enum):
    """評価基準のカテゴリ"""

    # ビジネス系
    FINANCIAL = "financial"  # 財務・コスト
    REVENUE = "revenue"  # 収益性
    MARKET = "market"  # 市場性
    STRATEGIC = "strategic"  # 戦略的適合性

    # 技術系
    TECHNICAL = "technical"  # 技術的実現可能性
    SCALABILITY = "scalability"  # スケーラビリティ
    QUALITY = "quality"  # 品質
    MAINTAINABILITY = "maintainability"  # 保守性

    # 人材系
    SKILL_FIT = "skill_fit"  # スキル適合
    CULTURE_FIT = "culture_fit"  # カルチャーフィット
    GROWTH_POTENTIAL = "growth_potential"  # 成長可能性
    EXPERIENCE = "experience"  # 経験

    # リソース系
    TIME = "time"  # 時間
    COST = "cost"  # コスト
    HUMAN_RESOURCE = "human_resource"  # 人的リソース
    EXTERNAL_DEPENDENCY = "external_dependency"  # 外部依存

    # リスク系
    RISK = "risk"  # リスク
    COMPLIANCE = "compliance"  # コンプライアンス
    SECURITY = "security"  # セキュリティ

    # 顧客・価値系
    CUSTOMER_VALUE = "customer_value"  # 顧客価値
    USER_EXPERIENCE = "user_experience"  # ユーザー体験
    INNOVATION = "innovation"  # 革新性

    # その他
    OTHER = "other"  # その他


class CriterionImportance(Enum):
    """評価基準の重要度"""

    CRITICAL = "critical"  # 必須・絶対条件（重み: 1.0）
    HIGH = "high"  # 非常に重要（重み: 0.8）
    MEDIUM = "medium"  # 重要（重み: 0.6）
    LOW = "low"  # あれば良い（重み: 0.4）
    OPTIONAL = "optional"  # オプション（重み: 0.2）


# 評価基準の重要度に対応する重み
CRITERION_IMPORTANCE_WEIGHTS: Dict[str, float] = {
    CriterionImportance.CRITICAL.value: 1.0,
    CriterionImportance.HIGH.value: 0.8,
    CriterionImportance.MEDIUM.value: 0.6,
    CriterionImportance.LOW.value: 0.4,
    CriterionImportance.OPTIONAL.value: 0.2,
}


class ScoreLevel(Enum):
    """スコアレベル（5段階評価）"""

    EXCELLENT = "excellent"  # 5点 - 優秀
    GOOD = "good"  # 4点 - 良好
    ACCEPTABLE = "acceptable"  # 3点 - 許容範囲
    POOR = "poor"  # 2点 - 不十分
    UNACCEPTABLE = "unacceptable"  # 1点 - 不可


# スコアレベルに対応する数値
SCORE_LEVEL_VALUES: Dict[str, int] = {
    ScoreLevel.EXCELLENT.value: 5,
    ScoreLevel.GOOD.value: 4,
    ScoreLevel.ACCEPTABLE.value: 3,
    ScoreLevel.POOR.value: 2,
    ScoreLevel.UNACCEPTABLE.value: 1,
}


# =============================================================================
# トレードオフ関連の定数
# =============================================================================

class TradeoffType(Enum):
    """トレードオフのタイプ"""

    # 基本的なトレードオフ
    COST_QUALITY = "cost_quality"  # コスト vs 品質
    SPEED_QUALITY = "speed_quality"  # スピード vs 品質
    COST_SPEED = "cost_speed"  # コスト vs スピード

    # リソーストレードオフ
    SHORT_TERM_LONG_TERM = "short_term_long_term"  # 短期 vs 長期
    FLEXIBILITY_EFFICIENCY = "flexibility_efficiency"  # 柔軟性 vs 効率性
    RISK_REWARD = "risk_reward"  # リスク vs リターン

    # 戦略的トレードオフ
    GROWTH_PROFITABILITY = "growth_profitability"  # 成長 vs 収益性
    INNOVATION_STABILITY = "innovation_stability"  # 革新 vs 安定
    BREADTH_DEPTH = "breadth_depth"  # 広さ vs 深さ

    # 人事トレードオフ
    EXPERIENCE_POTENTIAL = "experience_potential"  # 経験 vs 将来性
    SPECIALIST_GENERALIST = "specialist_generalist"  # 専門性 vs 汎用性
    INTERNAL_EXTERNAL = "internal_external"  # 内部 vs 外部

    # カスタム
    CUSTOM = "custom"  # カスタムトレードオフ


class TradeoffSeverity(Enum):
    """トレードオフの深刻度"""

    # 両立可能
    NEGLIGIBLE = "negligible"  # 無視できる程度（両立可能）

    # 調整可能
    MINOR = "minor"  # 軽微（工夫次第で両立可能）
    MODERATE = "moderate"  # 中程度（ある程度の犠牲が必要）

    # 深刻
    SIGNIFICANT = "significant"  # 重大（明確な選択が必要）
    CRITICAL = "critical"  # 致命的（一方を諦める必要あり）


# よくあるトレードオフパターン
COMMON_TRADEOFFS: Dict[str, Dict[str, Any]] = {
    "cost_quality": {
        "factor_a": "コスト削減",
        "factor_b": "品質向上",
        "description": "コストを下げると品質が犠牲になりやすい",
        "typical_severity": TradeoffSeverity.MODERATE.value,
    },
    "speed_quality": {
        "factor_a": "開発スピード",
        "factor_b": "品質・完成度",
        "description": "早く作ると品質が下がりやすい",
        "typical_severity": TradeoffSeverity.SIGNIFICANT.value,
    },
    "short_term_long_term": {
        "factor_a": "短期的な成果",
        "factor_b": "長期的な価値",
        "description": "今の利益を取ると将来の成長を犠牲にすることがある",
        "typical_severity": TradeoffSeverity.SIGNIFICANT.value,
    },
    "flexibility_efficiency": {
        "factor_a": "柔軟性",
        "factor_b": "効率性",
        "description": "柔軟にすると効率が下がることがある",
        "typical_severity": TradeoffSeverity.MODERATE.value,
    },
    "risk_reward": {
        "factor_a": "リスク回避",
        "factor_b": "高いリターン",
        "description": "リスクを避けると大きなリターンを逃すことがある",
        "typical_severity": TradeoffSeverity.SIGNIFICANT.value,
    },
    "growth_profitability": {
        "factor_a": "成長への投資",
        "factor_b": "現在の収益",
        "description": "成長のために投資すると短期的な収益が下がる",
        "typical_severity": TradeoffSeverity.MODERATE.value,
    },
    "experience_potential": {
        "factor_a": "即戦力（経験）",
        "factor_b": "将来性（ポテンシャル）",
        "description": "経験者は即戦力だが、若手は成長の余地が大きい",
        "typical_severity": TradeoffSeverity.MODERATE.value,
    },
}


# =============================================================================
# リスク関連の定数
# =============================================================================

class RiskCategory(Enum):
    """リスクのカテゴリ"""

    # ビジネスリスク
    MARKET_RISK = "market_risk"  # 市場リスク
    COMPETITIVE_RISK = "competitive_risk"  # 競合リスク
    REGULATORY_RISK = "regulatory_risk"  # 規制リスク
    REPUTATION_RISK = "reputation_risk"  # 評判リスク

    # 財務リスク
    FINANCIAL_RISK = "financial_risk"  # 財務リスク
    CREDIT_RISK = "credit_risk"  # 信用リスク
    LIQUIDITY_RISK = "liquidity_risk"  # 流動性リスク

    # オペレーショナルリスク
    OPERATIONAL_RISK = "operational_risk"  # 運用リスク
    TECHNOLOGY_RISK = "technology_risk"  # 技術リスク
    SECURITY_RISK = "security_risk"  # セキュリティリスク
    COMPLIANCE_RISK = "compliance_risk"  # コンプライアンスリスク

    # 人的リスク
    KEY_PERSON_RISK = "key_person_risk"  # キーパーソンリスク
    TALENT_RISK = "talent_risk"  # 人材リスク
    CULTURE_RISK = "culture_risk"  # カルチャーリスク

    # プロジェクトリスク
    SCHEDULE_RISK = "schedule_risk"  # スケジュールリスク
    SCOPE_RISK = "scope_risk"  # スコープリスク
    QUALITY_RISK = "quality_risk"  # 品質リスク
    RESOURCE_RISK = "resource_risk"  # リソースリスク

    # 外部リスク
    EXTERNAL_DEPENDENCY_RISK = "external_dependency_risk"  # 外部依存リスク
    VENDOR_RISK = "vendor_risk"  # ベンダーリスク
    GEOPOLITICAL_RISK = "geopolitical_risk"  # 地政学リスク

    # その他
    OTHER = "other"  # その他


class RiskProbability(Enum):
    """リスク発生確率"""

    RARE = "rare"  # ほぼ発生しない（<10%）
    UNLIKELY = "unlikely"  # 発生しにくい（10-30%）
    POSSIBLE = "possible"  # 発生の可能性あり（30-50%）
    LIKELY = "likely"  # 発生しやすい（50-70%）
    ALMOST_CERTAIN = "almost_certain"  # ほぼ確実（>70%）


class RiskImpact(Enum):
    """リスク影響度"""

    NEGLIGIBLE = "negligible"  # 無視できる程度
    MINOR = "minor"  # 軽微
    MODERATE = "moderate"  # 中程度
    MAJOR = "major"  # 重大
    SEVERE = "severe"  # 致命的


# リスク発生確率の数値マッピング（中央値）
RISK_PROBABILITY_VALUES: Dict[str, float] = {
    RiskProbability.RARE.value: 0.05,
    RiskProbability.UNLIKELY.value: 0.20,
    RiskProbability.POSSIBLE.value: 0.40,
    RiskProbability.LIKELY.value: 0.60,
    RiskProbability.ALMOST_CERTAIN.value: 0.85,
}

# リスク影響度の数値マッピング（1-5スケール）
RISK_IMPACT_VALUES: Dict[str, int] = {
    RiskImpact.NEGLIGIBLE.value: 1,
    RiskImpact.MINOR.value: 2,
    RiskImpact.MODERATE.value: 3,
    RiskImpact.MAJOR.value: 4,
    RiskImpact.SEVERE.value: 5,
}

# リスクスコア計算用マトリックス
# リスクスコア = 発生確率 × 影響度
# 結果: LOW (1-4), MEDIUM (5-9), HIGH (10-15), CRITICAL (16-25)
RISK_SCORE_THRESHOLDS = {
    "low": (0, 4),
    "medium": (5, 9),
    "high": (10, 15),
    "critical": (16, 25),
}


# =============================================================================
# リターン関連の定数
# =============================================================================

class ReturnType(Enum):
    """リターンのタイプ"""

    # 財務的リターン
    REVENUE_INCREASE = "revenue_increase"  # 収益増加
    COST_REDUCTION = "cost_reduction"  # コスト削減
    PROFIT_INCREASE = "profit_increase"  # 利益増加
    CASH_FLOW_IMPROVEMENT = "cash_flow_improvement"  # キャッシュフロー改善

    # 戦略的リターン
    MARKET_SHARE = "market_share"  # 市場シェア
    COMPETITIVE_ADVANTAGE = "competitive_advantage"  # 競争優位性
    BRAND_VALUE = "brand_value"  # ブランド価値

    # 運営効率
    EFFICIENCY_IMPROVEMENT = "efficiency_improvement"  # 効率改善
    PRODUCTIVITY_INCREASE = "productivity_increase"  # 生産性向上
    QUALITY_IMPROVEMENT = "quality_improvement"  # 品質向上

    # 人材・組織
    EMPLOYEE_SATISFACTION = "employee_satisfaction"  # 従業員満足度
    SKILL_DEVELOPMENT = "skill_development"  # スキル向上
    TEAM_CAPABILITY = "team_capability"  # チーム能力

    # 顧客・市場
    CUSTOMER_SATISFACTION = "customer_satisfaction"  # 顧客満足度
    CUSTOMER_ACQUISITION = "customer_acquisition"  # 新規顧客獲得
    CUSTOMER_RETENTION = "customer_retention"  # 顧客維持

    # その他
    OTHER = "other"  # その他


class ReturnCertainty(Enum):
    """リターンの確実性"""

    GUARANTEED = "guaranteed"  # 確定（契約済み等）
    HIGHLY_LIKELY = "highly_likely"  # ほぼ確実
    EXPECTED = "expected"  # 期待できる
    POSSIBLE = "possible"  # 可能性あり
    SPECULATIVE = "speculative"  # 投機的


class ReturnTimeframe(Enum):
    """リターンの時間軸"""

    IMMEDIATE = "immediate"  # 即時（1ヶ月以内）
    SHORT_TERM = "short_term"  # 短期（1-3ヶ月）
    MEDIUM_TERM = "medium_term"  # 中期（3-12ヶ月）
    LONG_TERM = "long_term"  # 長期（1-3年）
    VERY_LONG_TERM = "very_long_term"  # 超長期（3年以上）


# リターン確実性の数値マッピング（割引係数）
RETURN_CERTAINTY_DISCOUNT: Dict[str, float] = {
    ReturnCertainty.GUARANTEED.value: 1.0,
    ReturnCertainty.HIGHLY_LIKELY.value: 0.9,
    ReturnCertainty.EXPECTED.value: 0.7,
    ReturnCertainty.POSSIBLE.value: 0.5,
    ReturnCertainty.SPECULATIVE.value: 0.3,
}

# リターン時間軸の数値マッピング（月数の中央値）
RETURN_TIMEFRAME_MONTHS: Dict[str, int] = {
    ReturnTimeframe.IMMEDIATE.value: 1,
    ReturnTimeframe.SHORT_TERM.value: 2,
    ReturnTimeframe.MEDIUM_TERM.value: 6,
    ReturnTimeframe.LONG_TERM.value: 24,
    ReturnTimeframe.VERY_LONG_TERM.value: 48,
}


# =============================================================================
# 整合性チェック関連の定数
# =============================================================================

class ConsistencyLevel(Enum):
    """過去判断との整合性レベル"""

    FULLY_CONSISTENT = "fully_consistent"  # 完全に一貫
    MOSTLY_CONSISTENT = "mostly_consistent"  # 概ね一貫
    PARTIALLY_CONSISTENT = "partially_consistent"  # 部分的に一貫
    INCONSISTENT = "inconsistent"  # 矛盾あり
    CONTRADICTORY = "contradictory"  # 完全に矛盾


class ConsistencyDimension(Enum):
    """整合性をチェックする次元"""

    # 価値・方針
    VALUE_ALIGNMENT = "value_alignment"  # 価値観との整合
    POLICY_COMPLIANCE = "policy_compliance"  # 方針との整合
    STRATEGY_ALIGNMENT = "strategy_alignment"  # 戦略との整合

    # 過去判断
    PRECEDENT_CONSISTENCY = "precedent_consistency"  # 先例との整合
    SIMILAR_CASE_CONSISTENCY = "similar_case_consistency"  # 類似事例との整合

    # ステークホルダー
    STAKEHOLDER_EXPECTATION = "stakeholder_expectation"  # ステークホルダー期待
    COMMITMENT_CONSISTENCY = "commitment_consistency"  # コミットメントとの整合

    # 論理
    LOGICAL_CONSISTENCY = "logical_consistency"  # 論理的整合性
    TEMPORAL_CONSISTENCY = "temporal_consistency"  # 時間的整合性


# 整合性レベルの数値マッピング
CONSISTENCY_LEVEL_SCORES: Dict[str, float] = {
    ConsistencyLevel.FULLY_CONSISTENT.value: 1.0,
    ConsistencyLevel.MOSTLY_CONSISTENT.value: 0.8,
    ConsistencyLevel.PARTIALLY_CONSISTENT.value: 0.5,
    ConsistencyLevel.INCONSISTENT.value: 0.2,
    ConsistencyLevel.CONTRADICTORY.value: 0.0,
}


# =============================================================================
# 推奨アクション関連の定数
# =============================================================================

class RecommendationType(Enum):
    """推奨のタイプ"""

    STRONG_RECOMMEND = "strong_recommend"  # 強く推奨
    RECOMMEND = "recommend"  # 推奨
    CONDITIONAL_RECOMMEND = "conditional_recommend"  # 条件付き推奨
    NEUTRAL = "neutral"  # 中立
    CONDITIONAL_NOT_RECOMMEND = "conditional_not_recommend"  # 条件付き非推奨
    NOT_RECOMMEND = "not_recommend"  # 非推奨
    STRONG_NOT_RECOMMEND = "strong_not_recommend"  # 強く非推奨


class ConfidenceLevel(Enum):
    """判断の確信度"""

    VERY_HIGH = "very_high"  # 非常に高い（90%以上）
    HIGH = "high"  # 高い（70-90%）
    MEDIUM = "medium"  # 中程度（50-70%）
    LOW = "low"  # 低い（30-50%）
    VERY_LOW = "very_low"  # 非常に低い（30%未満）


# 推奨タイプに対応するスコア範囲
RECOMMENDATION_SCORE_RANGES: Dict[str, Tuple[float, float]] = {
    RecommendationType.STRONG_RECOMMEND.value: (0.85, 1.0),
    RecommendationType.RECOMMEND.value: (0.70, 0.85),
    RecommendationType.CONDITIONAL_RECOMMEND.value: (0.55, 0.70),
    RecommendationType.NEUTRAL.value: (0.45, 0.55),
    RecommendationType.CONDITIONAL_NOT_RECOMMEND.value: (0.30, 0.45),
    RecommendationType.NOT_RECOMMEND.value: (0.15, 0.30),
    RecommendationType.STRONG_NOT_RECOMMEND.value: (0.0, 0.15),
}

# 確信度に対応するスコア範囲
CONFIDENCE_LEVEL_RANGES: Dict[str, Tuple[float, float]] = {
    ConfidenceLevel.VERY_HIGH.value: (0.90, 1.0),
    ConfidenceLevel.HIGH.value: (0.70, 0.90),
    ConfidenceLevel.MEDIUM.value: (0.50, 0.70),
    ConfidenceLevel.LOW.value: (0.30, 0.50),
    ConfidenceLevel.VERY_LOW.value: (0.0, 0.30),
}


# =============================================================================
# デフォルト評価基準
# =============================================================================

# 案件受注判断用のデフォルト評価基準
DEFAULT_PROJECT_CRITERIA: List[Dict[str, Any]] = [
    {
        "name": "収益性",
        "category": CriterionCategory.REVENUE.value,
        "importance": CriterionImportance.HIGH.value,
        "description": "期待される収益・利益率",
    },
    {
        "name": "戦略的適合性",
        "category": CriterionCategory.STRATEGIC.value,
        "importance": CriterionImportance.HIGH.value,
        "description": "自社の戦略・方向性との適合",
    },
    {
        "name": "技術的実現可能性",
        "category": CriterionCategory.TECHNICAL.value,
        "importance": CriterionImportance.CRITICAL.value,
        "description": "自社の技術力で実現可能か",
    },
    {
        "name": "リソース確保可能性",
        "category": CriterionCategory.HUMAN_RESOURCE.value,
        "importance": CriterionImportance.HIGH.value,
        "description": "必要な人員・リソースを確保できるか",
    },
    {
        "name": "リスク",
        "category": CriterionCategory.RISK.value,
        "importance": CriterionImportance.HIGH.value,
        "description": "プロジェクトに伴うリスク",
    },
    {
        "name": "顧客との関係",
        "category": CriterionCategory.CUSTOMER_VALUE.value,
        "importance": CriterionImportance.MEDIUM.value,
        "description": "顧客との関係性・将来性",
    },
]

# 採用判断用のデフォルト評価基準
DEFAULT_HIRING_CRITERIA: List[Dict[str, Any]] = [
    {
        "name": "スキル適合",
        "category": CriterionCategory.SKILL_FIT.value,
        "importance": CriterionImportance.CRITICAL.value,
        "description": "必要なスキル・経験を持っているか",
    },
    {
        "name": "カルチャーフィット",
        "category": CriterionCategory.CULTURE_FIT.value,
        "importance": CriterionImportance.HIGH.value,
        "description": "組織のカルチャーに合うか",
    },
    {
        "name": "成長可能性",
        "category": CriterionCategory.GROWTH_POTENTIAL.value,
        "importance": CriterionImportance.HIGH.value,
        "description": "今後の成長が期待できるか",
    },
    {
        "name": "コミュニケーション",
        "category": CriterionCategory.OTHER.value,
        "importance": CriterionImportance.HIGH.value,
        "description": "コミュニケーション能力",
    },
    {
        "name": "チーム適合",
        "category": CriterionCategory.CULTURE_FIT.value,
        "importance": CriterionImportance.MEDIUM.value,
        "description": "配属予定チームとの相性",
    },
]

# 投資判断用のデフォルト評価基準
DEFAULT_INVESTMENT_CRITERIA: List[Dict[str, Any]] = [
    {
        "name": "期待リターン",
        "category": CriterionCategory.REVENUE.value,
        "importance": CriterionImportance.CRITICAL.value,
        "description": "期待される収益・リターン",
    },
    {
        "name": "リスク水準",
        "category": CriterionCategory.RISK.value,
        "importance": CriterionImportance.CRITICAL.value,
        "description": "投資に伴うリスクの大きさ",
    },
    {
        "name": "戦略的価値",
        "category": CriterionCategory.STRATEGIC.value,
        "importance": CriterionImportance.HIGH.value,
        "description": "戦略的な価値・シナジー",
    },
    {
        "name": "流動性",
        "category": CriterionCategory.FINANCIAL.value,
        "importance": CriterionImportance.MEDIUM.value,
        "description": "投資の流動性・換金性",
    },
    {
        "name": "時間軸",
        "category": CriterionCategory.TIME.value,
        "importance": CriterionImportance.MEDIUM.value,
        "description": "リターンが得られるまでの期間",
    },
]


# =============================================================================
# 設定関連の定数
# =============================================================================

# 判断履歴の保持期間（日数）
JUDGMENT_HISTORY_RETENTION_DAYS = 365

# 類似判断検索時の最大件数
MAX_SIMILAR_JUDGMENTS = 10

# 類似度の閾値
SIMILARITY_THRESHOLD = 0.6

# デフォルトの評価基準数
DEFAULT_CRITERIA_COUNT = 5

# 最大選択肢数
MAX_OPTIONS = 20

# 最大評価基準数
MAX_CRITERIA = 30

# 最大リスク要因数
MAX_RISK_FACTORS = 50

# トレードオフ分析の最大深度
MAX_TRADEOFF_DEPTH = 3

# 整合性チェックの参照期間（日数）
CONSISTENCY_CHECK_PERIOD_DAYS = 180

# Feature Flags
FEATURE_FLAG_ADVANCED_JUDGMENT = "advanced_judgment_enabled"
FEATURE_FLAG_OPTION_EVALUATION = "option_evaluation_enabled"
FEATURE_FLAG_TRADEOFF_ANALYSIS = "tradeoff_analysis_enabled"
FEATURE_FLAG_RISK_ASSESSMENT = "risk_assessment_enabled"
FEATURE_FLAG_CONSISTENCY_CHECK = "consistency_check_enabled"


# =============================================================================
# プロンプトテンプレート
# =============================================================================

# 判断支援のLLMプロンプト
JUDGMENT_ANALYSIS_PROMPT = """あなたは判断支援を行うAIアシスタントです。
以下の判断課題について、多角的な分析を提供してください。

## 判断課題
{judgment_question}

## 選択肢
{options}

## 評価基準
{criteria}

## コンテキスト
{context}

## タスク
1. 各選択肢を評価基準に基づいて評価してください
2. 重要なトレードオフを特定してください
3. 主なリスクとリターンを分析してください
4. 総合的な推奨を提示してください

## 出力形式（JSON）
{{
    "option_evaluations": [
        {{
            "option": "選択肢名",
            "scores": {{"基準名": スコア(1-5)}},
            "strengths": ["強み1", "強み2"],
            "weaknesses": ["弱み1", "弱み2"]
        }}
    ],
    "tradeoffs": [
        {{
            "type": "トレードオフタイプ",
            "description": "説明",
            "severity": "深刻度"
        }}
    ],
    "risks": [
        {{
            "category": "リスクカテゴリ",
            "description": "説明",
            "probability": "発生確率",
            "impact": "影響度"
        }}
    ],
    "recommendation": {{
        "choice": "推奨選択肢",
        "type": "推奨タイプ",
        "confidence": 0.0-1.0,
        "reasoning": "理由"
    }}
}}"""


# =============================================================================
# エクスポート
# =============================================================================

__all__ = [
    # 判断タイプ
    "JudgmentType",
    "JudgmentComplexity",

    # 評価基準
    "CriterionCategory",
    "CriterionImportance",
    "ScoreLevel",
    "CRITERION_IMPORTANCE_WEIGHTS",
    "SCORE_LEVEL_VALUES",

    # トレードオフ
    "TradeoffType",
    "TradeoffSeverity",
    "COMMON_TRADEOFFS",

    # リスク
    "RiskCategory",
    "RiskProbability",
    "RiskImpact",
    "RISK_PROBABILITY_VALUES",
    "RISK_IMPACT_VALUES",
    "RISK_SCORE_THRESHOLDS",

    # リターン
    "ReturnType",
    "ReturnCertainty",
    "ReturnTimeframe",
    "RETURN_CERTAINTY_DISCOUNT",
    "RETURN_TIMEFRAME_MONTHS",

    # 整合性
    "ConsistencyLevel",
    "ConsistencyDimension",
    "CONSISTENCY_LEVEL_SCORES",

    # 推奨
    "RecommendationType",
    "ConfidenceLevel",
    "RECOMMENDATION_SCORE_RANGES",
    "CONFIDENCE_LEVEL_RANGES",

    # デフォルト評価基準
    "DEFAULT_PROJECT_CRITERIA",
    "DEFAULT_HIRING_CRITERIA",
    "DEFAULT_INVESTMENT_CRITERIA",

    # 設定
    "JUDGMENT_HISTORY_RETENTION_DAYS",
    "MAX_SIMILAR_JUDGMENTS",
    "SIMILARITY_THRESHOLD",
    "DEFAULT_CRITERIA_COUNT",
    "MAX_OPTIONS",
    "MAX_CRITERIA",
    "MAX_RISK_FACTORS",
    "MAX_TRADEOFF_DEPTH",
    "CONSISTENCY_CHECK_PERIOD_DAYS",

    # Feature Flags
    "FEATURE_FLAG_ADVANCED_JUDGMENT",
    "FEATURE_FLAG_OPTION_EVALUATION",
    "FEATURE_FLAG_TRADEOFF_ANALYSIS",
    "FEATURE_FLAG_RISK_ASSESSMENT",
    "FEATURE_FLAG_CONSISTENCY_CHECK",

    # プロンプト
    "JUDGMENT_ANALYSIS_PROMPT",
]
