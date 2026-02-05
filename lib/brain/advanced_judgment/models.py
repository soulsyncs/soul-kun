# lib/brain/advanced_judgment/models.py
"""
Phase 2J: 判断力強化（Advanced Judgment）- データモデル

設計書: docs/17_brain_completion_roadmap.md セクション17.3 Phase 2J

このファイルには、高度な判断層で使用するデータモデルを定義します。

【Phase 2J の能力】
- 複数選択肢の比較評価
- トレードオフの明示化（「Aを取ればBを犠牲に」）
- リスク・リターンの定量評価
- 過去の判断との整合性チェック

Author: Claude Opus 4.5
Created: 2026-01-27
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import UUID, uuid4

from .constants import (
    JudgmentType,
    JudgmentComplexity,
    CriterionCategory,
    CriterionImportance,
    ScoreLevel,
    TradeoffType,
    TradeoffSeverity,
    RiskCategory,
    RiskProbability,
    RiskImpact,
    ReturnType,
    ReturnCertainty,
    ReturnTimeframe,
    ConsistencyLevel,
    ConsistencyDimension,
    RecommendationType,
    ConfidenceLevel,
)


# =============================================================================
# 選択肢関連のモデル
# =============================================================================

@dataclass
class JudgmentOption:
    """
    判断における選択肢

    例: 「案件を受ける」「案件を断る」「条件交渉する」
    """
    # 識別子
    id: str = field(default_factory=lambda: str(uuid4()))

    # 選択肢名
    name: str = ""

    # 説明
    description: str = ""

    # ラベル（短い表示名）
    label: Optional[str] = None

    # メタデータ
    metadata: Dict[str, Any] = field(default_factory=dict)

    # 順序（表示順）
    order: int = 0

    # 有効フラグ
    is_active: bool = True

    def __post_init__(self):
        """ラベルが未設定の場合は名前を使用"""
        if self.label is None:
            self.label = self.name


@dataclass
class OptionScore:
    """
    選択肢に対する単一基準のスコア
    """
    # 対象の選択肢ID
    option_id: str = ""

    # 評価基準ID
    criterion_id: str = ""

    # スコア（1-5）
    score: int = 3

    # スコアレベル
    score_level: str = ScoreLevel.ACCEPTABLE.value

    # 根拠・理由
    reasoning: str = ""

    # 信頼度
    confidence: float = 0.7

    # メタデータ
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OptionEvaluation:
    """
    選択肢の総合評価
    """
    # 対象の選択肢
    option: JudgmentOption = field(default_factory=JudgmentOption)

    # 各基準のスコア
    criterion_scores: List[OptionScore] = field(default_factory=list)

    # 総合スコア（重み付け平均）
    total_score: float = 0.0

    # 正規化スコア（0-1）
    normalized_score: float = 0.0

    # 順位
    rank: int = 0

    # 強み
    strengths: List[str] = field(default_factory=list)

    # 弱み
    weaknesses: List[str] = field(default_factory=list)

    # 概要コメント
    summary: str = ""

    # 信頼度
    confidence: float = 0.7


# =============================================================================
# 評価基準関連のモデル
# =============================================================================

@dataclass
class EvaluationCriterion:
    """
    評価基準

    例: 「収益性」「技術的実現可能性」「リスク」
    """
    # 識別子
    id: str = field(default_factory=lambda: str(uuid4()))

    # 基準名
    name: str = ""

    # カテゴリ
    category: str = CriterionCategory.OTHER.value

    # 重要度
    importance: str = CriterionImportance.MEDIUM.value

    # 重み（0-1）
    weight: float = 0.6

    # 説明
    description: str = ""

    # スコアリング方法
    # higher_is_better: Trueなら高スコアが良い、Falseなら低スコアが良い
    higher_is_better: bool = True

    # スコアのガイドライン（各スコアレベルの定義）
    score_guidelines: Dict[int, str] = field(default_factory=dict)

    # メタデータ
    metadata: Dict[str, Any] = field(default_factory=dict)

    # 有効フラグ
    is_active: bool = True

    def __post_init__(self):
        """重要度から重みを計算"""
        from .constants import CRITERION_IMPORTANCE_WEIGHTS
        if self.weight == 0.6 and self.importance in CRITERION_IMPORTANCE_WEIGHTS:
            self.weight = CRITERION_IMPORTANCE_WEIGHTS[self.importance]


@dataclass
class CriteriaSet:
    """
    評価基準のセット
    """
    # 識別子
    id: str = field(default_factory=lambda: str(uuid4()))

    # セット名
    name: str = ""

    # 説明
    description: str = ""

    # 判断タイプ（このセットが適用される判断タイプ）
    judgment_type: Optional[str] = None

    # 含まれる評価基準
    criteria: List[EvaluationCriterion] = field(default_factory=list)

    # メタデータ
    metadata: Dict[str, Any] = field(default_factory=dict)


# =============================================================================
# トレードオフ関連のモデル
# =============================================================================

@dataclass
class TradeoffFactor:
    """
    トレードオフの要素（片方の側）
    """
    # 要素名
    name: str = ""

    # 説明
    description: str = ""

    # 関連する選択肢ID
    related_option_ids: List[str] = field(default_factory=list)

    # 関連する評価基準ID
    related_criterion_ids: List[str] = field(default_factory=list)

    # 影響度（0-1）
    impact: float = 0.5


@dataclass
class Tradeoff:
    """
    トレードオフ

    「Aを取ればBを犠牲にする」という関係
    """
    # 識別子
    id: str = field(default_factory=lambda: str(uuid4()))

    # トレードオフタイプ
    tradeoff_type: str = TradeoffType.CUSTOM.value

    # 要素A（得られるもの）
    factor_a: TradeoffFactor = field(default_factory=TradeoffFactor)

    # 要素B（犠牲になるもの）
    factor_b: TradeoffFactor = field(default_factory=TradeoffFactor)

    # 深刻度
    severity: str = TradeoffSeverity.MODERATE.value

    # 説明
    description: str = ""

    # 自然言語での表現
    # 例: 「コストを下げるためには、品質を犠牲にする必要があります」
    natural_language: str = ""

    # 緩和策
    mitigation_options: List[str] = field(default_factory=list)

    # 信頼度
    confidence: float = 0.7

    # メタデータ
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_natural_language(self) -> str:
        """トレードオフを自然言語で表現"""
        if self.natural_language:
            return self.natural_language

        severity_text = {
            TradeoffSeverity.NEGLIGIBLE.value: "わずかに",
            TradeoffSeverity.MINOR.value: "やや",
            TradeoffSeverity.MODERATE.value: "",
            TradeoffSeverity.SIGNIFICANT.value: "大きく",
            TradeoffSeverity.CRITICAL.value: "致命的に",
        }

        return (
            f"「{self.factor_a.name}」を取ると、"
            f"「{self.factor_b.name}」が{severity_text.get(self.severity, '')}犠牲になります"
        )


@dataclass
class TradeoffAnalysisResult:
    """
    トレードオフ分析の結果
    """
    # 検出されたトレードオフのリスト
    tradeoffs: List[Tradeoff] = field(default_factory=list)

    # 最も重要なトレードオフ
    primary_tradeoff: Optional[Tradeoff] = None

    # トレードオフの総数
    total_count: int = 0

    # 深刻なトレードオフの数
    critical_count: int = 0

    # 概要
    summary: str = ""

    # 推奨される対応
    recommendations: List[str] = field(default_factory=list)

    # 信頼度
    confidence: float = 0.7

    # 処理時間（ミリ秒）
    processing_time_ms: int = 0


# =============================================================================
# リスク関連のモデル
# =============================================================================

@dataclass
class RiskFactor:
    """
    リスク要因
    """
    # 識別子
    id: str = field(default_factory=lambda: str(uuid4()))

    # リスク名
    name: str = ""

    # カテゴリ
    category: str = RiskCategory.OTHER.value

    # 説明
    description: str = ""

    # 発生確率
    probability: str = RiskProbability.POSSIBLE.value

    # 発生確率（数値）
    probability_value: float = 0.4

    # 影響度
    impact: str = RiskImpact.MODERATE.value

    # 影響度（数値）
    impact_value: int = 3

    # リスクスコア（発生確率 × 影響度）
    risk_score: float = 0.0

    # リスクレベル（LOW, MEDIUM, HIGH, CRITICAL）
    risk_level: str = "medium"

    # 緩和策
    mitigation_strategies: List[str] = field(default_factory=list)

    # 関連する選択肢ID
    related_option_ids: List[str] = field(default_factory=list)

    # 信頼度
    confidence: float = 0.7

    # メタデータ
    metadata: Dict[str, Any] = field(default_factory=dict)

    def calculate_risk_score(self) -> float:
        """リスクスコアを計算"""
        from .constants import RISK_PROBABILITY_VALUES, RISK_IMPACT_VALUES
        prob = RISK_PROBABILITY_VALUES.get(self.probability, 0.4)
        impact = RISK_IMPACT_VALUES.get(self.impact, 3)
        self.probability_value = prob
        self.impact_value = impact
        self.risk_score = prob * impact * 5  # 0-25のスケール
        self._update_risk_level()
        return self.risk_score

    def _update_risk_level(self):
        """リスクレベルを更新"""
        from .constants import RISK_SCORE_THRESHOLDS
        for level, (min_score, max_score) in RISK_SCORE_THRESHOLDS.items():
            if min_score <= self.risk_score <= max_score:
                self.risk_level = level
                break


@dataclass
class RiskAssessment:
    """
    リスク評価結果
    """
    # リスク要因のリスト
    risks: List[RiskFactor] = field(default_factory=list)

    # 全体のリスクスコア（加重平均）
    overall_risk_score: float = 0.0

    # 全体のリスクレベル
    overall_risk_level: str = "medium"

    # 最も重大なリスク
    top_risks: List[RiskFactor] = field(default_factory=list)

    # カテゴリ別のリスク数
    risks_by_category: Dict[str, int] = field(default_factory=dict)

    # リスクレベル別の数
    risks_by_level: Dict[str, int] = field(default_factory=dict)

    # 概要
    summary: str = ""

    # 推奨される緩和策
    recommended_mitigations: List[str] = field(default_factory=list)

    # 信頼度
    confidence: float = 0.7

    # 処理時間（ミリ秒）
    processing_time_ms: int = 0


# =============================================================================
# リターン関連のモデル
# =============================================================================

@dataclass
class ReturnFactor:
    """
    リターン要因
    """
    # 識別子
    id: str = field(default_factory=lambda: str(uuid4()))

    # リターン名
    name: str = ""

    # タイプ
    return_type: str = ReturnType.OTHER.value

    # 説明
    description: str = ""

    # 期待値（金額、パーセント等）
    expected_value: float = 0.0

    # 単位
    unit: str = ""

    # 確実性
    certainty: str = ReturnCertainty.EXPECTED.value

    # 確実性に基づく割引係数
    certainty_discount: float = 0.7

    # 時間軸
    timeframe: str = ReturnTimeframe.MEDIUM_TERM.value

    # 実現までの月数
    months_to_realize: int = 6

    # 調整後の期待値（確実性で割引）
    adjusted_value: float = 0.0

    # 関連する選択肢ID
    related_option_ids: List[str] = field(default_factory=list)

    # 信頼度
    confidence: float = 0.7

    # メタデータ
    metadata: Dict[str, Any] = field(default_factory=dict)

    def calculate_adjusted_value(self) -> float:
        """確実性で調整した期待値を計算"""
        from .constants import RETURN_CERTAINTY_DISCOUNT
        discount = RETURN_CERTAINTY_DISCOUNT.get(self.certainty, 0.5)
        self.certainty_discount = discount
        self.adjusted_value = self.expected_value * discount
        return self.adjusted_value


@dataclass
class ReturnAssessment:
    """
    リターン評価結果
    """
    # リターン要因のリスト
    returns: List[ReturnFactor] = field(default_factory=list)

    # 期待総リターン（調整後）
    total_expected_return: float = 0.0

    # リターンタイプ別の合計
    returns_by_type: Dict[str, float] = field(default_factory=dict)

    # 時間軸別の期待値
    returns_by_timeframe: Dict[str, float] = field(default_factory=dict)

    # 最も大きなリターン
    top_returns: List[ReturnFactor] = field(default_factory=list)

    # 概要
    summary: str = ""

    # 信頼度
    confidence: float = 0.7

    # 処理時間（ミリ秒）
    processing_time_ms: int = 0


@dataclass
class RiskReturnAnalysis:
    """
    リスク・リターン分析の統合結果
    """
    # リスク評価
    risk_assessment: RiskAssessment = field(default_factory=RiskAssessment)

    # リターン評価
    return_assessment: ReturnAssessment = field(default_factory=ReturnAssessment)

    # リスク・リターン比
    risk_return_ratio: float = 0.0

    # リスク調整後リターン
    risk_adjusted_return: float = 0.0

    # 推奨
    recommendation: str = ""

    # 概要
    summary: str = ""

    # 信頼度
    confidence: float = 0.7


# =============================================================================
# 整合性チェック関連のモデル
# =============================================================================

@dataclass
class PastJudgment:
    """
    過去の判断記録
    """
    # 識別子
    id: str = field(default_factory=lambda: str(uuid4()))

    # 判断タイプ
    judgment_type: str = JudgmentType.COMPARISON.value

    # 判断の質問・課題
    question: str = ""

    # 選択された選択肢
    chosen_option: str = ""

    # 選択肢リスト
    options: List[str] = field(default_factory=list)

    # 判断理由
    reasoning: str = ""

    # 結果（後から記録）
    outcome: Optional[str] = None

    # 結果スコア（0.0-1.0、後から記録）
    outcome_score: Optional[float] = None

    # 判断日時
    judged_at: datetime = field(default_factory=datetime.now)

    # 組織ID
    organization_id: str = ""

    # ユーザーID
    user_id: Optional[str] = None

    # メタデータ
    metadata: Dict[str, Any] = field(default_factory=dict)

    # タグ（検索用）
    tags: List[str] = field(default_factory=list)


@dataclass
class ConsistencyIssue:
    """
    整合性の問題点
    """
    # 問題の次元
    dimension: str = ConsistencyDimension.PRECEDENT_CONSISTENCY.value

    # 問題の説明
    description: str = ""

    # 関連する過去判断
    related_judgment: Optional[PastJudgment] = None

    # 深刻度（0-1）
    severity: float = 0.5

    # 推奨される対応
    recommendation: str = ""


@dataclass
class ConsistencyCheckResult:
    """
    整合性チェックの結果
    """
    # 全体の整合性レベル
    consistency_level: str = ConsistencyLevel.MOSTLY_CONSISTENT.value

    # 整合性スコア（0-1）
    consistency_score: float = 0.8

    # 検出された問題
    issues: List[ConsistencyIssue] = field(default_factory=list)

    # 類似の過去判断
    similar_judgments: List[PastJudgment] = field(default_factory=list)

    # 次元別の整合性スコア
    scores_by_dimension: Dict[str, float] = field(default_factory=dict)

    # 概要
    summary: str = ""

    # 推奨事項
    recommendations: List[str] = field(default_factory=list)

    # 信頼度
    confidence: float = 0.7

    # 処理時間（ミリ秒）
    processing_time_ms: int = 0


# =============================================================================
# 統合モデル（入力・出力）
# =============================================================================

@dataclass
class AdvancedJudgmentInput:
    """
    高度な判断層への入力
    """
    # 判断の質問・課題
    question: str = ""

    # 判断タイプ
    judgment_type: str = JudgmentType.COMPARISON.value

    # 選択肢のリスト
    options: List[JudgmentOption] = field(default_factory=list)

    # 評価基準（指定がない場合はデフォルトを使用）
    criteria: Optional[List[EvaluationCriterion]] = None

    # コンテキスト情報
    context: Dict[str, Any] = field(default_factory=dict)

    # 組織ID
    organization_id: str = ""

    # ユーザーID
    user_id: Optional[str] = None

    # ChatWorkアカウントID
    chatwork_account_id: Optional[str] = None

    # ルームID
    room_id: Optional[str] = None

    # 会話履歴
    conversation_history: List[Dict[str, Any]] = field(default_factory=list)

    # 追加の制約条件
    constraints: List[str] = field(default_factory=list)

    # 必須要件
    must_have_requirements: List[str] = field(default_factory=list)

    # 除外条件
    exclusion_criteria: List[str] = field(default_factory=list)

    # メタデータ
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class JudgmentRecommendation:
    """
    判断の推奨
    """
    # 推奨する選択肢
    recommended_option: Optional[JudgmentOption] = None

    # 推奨タイプ
    recommendation_type: str = RecommendationType.NEUTRAL.value

    # 推奨スコア（0-1）
    recommendation_score: float = 0.5

    # 確信度
    confidence: str = ConfidenceLevel.MEDIUM.value

    # 確信度（数値）
    confidence_score: float = 0.5

    # 推奨理由
    reasoning: str = ""

    # 自然言語での推奨文
    natural_language_recommendation: str = ""

    # 条件・注意点
    conditions: List[str] = field(default_factory=list)

    # 代替案
    alternatives: List[JudgmentOption] = field(default_factory=list)

    # 次のステップ
    next_steps: List[str] = field(default_factory=list)


@dataclass
class AdvancedJudgmentOutput:
    """
    高度な判断層からの出力
    """
    # 入力（参照用）
    input: AdvancedJudgmentInput = field(default_factory=AdvancedJudgmentInput)

    # 判断タイプ
    judgment_type: str = JudgmentType.COMPARISON.value

    # 判断の複雑さ
    complexity: str = JudgmentComplexity.MODERATE.value

    # 選択肢の評価結果
    option_evaluations: List[OptionEvaluation] = field(default_factory=list)

    # トレードオフ分析結果
    tradeoff_analysis: Optional[TradeoffAnalysisResult] = None

    # リスク・リターン分析
    risk_return_analysis: Optional[RiskReturnAnalysis] = None

    # 整合性チェック結果
    consistency_check: Optional[ConsistencyCheckResult] = None

    # 最終的な推奨
    recommendation: JudgmentRecommendation = field(
        default_factory=JudgmentRecommendation
    )

    # 判断に使用した評価基準
    criteria_used: List[EvaluationCriterion] = field(default_factory=list)

    # 概要（自然言語）
    summary: str = ""

    # 詳細な分析レポート
    detailed_report: str = ""

    # 全体の信頼度
    overall_confidence: float = 0.7

    # 確認が必要か
    needs_confirmation: bool = False

    # 確認理由
    confirmation_reason: Optional[str] = None

    # 警告
    warnings: List[str] = field(default_factory=list)

    # エラー
    errors: List[str] = field(default_factory=list)

    # 処理時間（ミリ秒）
    processing_time_ms: int = 0

    # 作成日時
    created_at: datetime = field(default_factory=datetime.now)

    # メタデータ
    metadata: Dict[str, Any] = field(default_factory=dict)


# =============================================================================
# DB永続化用モデル
# =============================================================================

@dataclass
class JudgmentHistoryDB:
    """
    判断履歴（DB保存用）
    """
    # 主キー
    id: Optional[UUID] = None

    # 組織ID
    organization_id: str = ""

    # ユーザーID
    user_id: Optional[str] = None

    # ChatWorkアカウントID
    chatwork_account_id: Optional[str] = None

    # ルームID
    room_id: Optional[str] = None

    # 判断タイプ
    judgment_type: str = JudgmentType.COMPARISON.value

    # 判断の質問
    question: str = ""

    # 選択肢（JSON）
    options_json: str = "[]"

    # 評価基準（JSON）
    criteria_json: str = "[]"

    # 選択肢評価（JSON）
    evaluations_json: str = "[]"

    # トレードオフ分析（JSON）
    tradeoffs_json: str = "{}"

    # リスク評価（JSON）
    risk_assessment_json: str = "{}"

    # リターン評価（JSON）
    return_assessment_json: str = "{}"

    # 整合性チェック（JSON）
    consistency_check_json: str = "{}"

    # 推奨（JSON）
    recommendation_json: str = "{}"

    # 推奨選択肢
    recommended_option: Optional[str] = None

    # 実際に選択された選択肢
    actual_choice: Optional[str] = None

    # 結果（後から記録）
    outcome: Optional[str] = None

    # 結果評価スコア（後から記録）
    outcome_score: Optional[float] = None

    # 全体の信頼度
    overall_confidence: float = 0.7

    # 処理時間（ミリ秒）
    processing_time_ms: int = 0

    # メタデータ（JSON）
    metadata_json: str = "{}"

    # 作成日時
    created_at: Optional[datetime] = None

    # 更新日時
    updated_at: Optional[datetime] = None


@dataclass
class EvaluationCriterionDB:
    """
    評価基準（DB保存用・テンプレート）
    """
    # 主キー
    id: Optional[UUID] = None

    # 組織ID
    organization_id: str = ""

    # 基準名
    name: str = ""

    # カテゴリ
    category: str = CriterionCategory.OTHER.value

    # 重要度
    importance: str = CriterionImportance.MEDIUM.value

    # 重み
    weight: float = 0.6

    # 説明
    description: str = ""

    # 判断タイプ（このテンプレートが適用される判断タイプ）
    judgment_type: Optional[str] = None

    # スコアガイドライン（JSON）
    score_guidelines_json: str = "{}"

    # メタデータ（JSON）
    metadata_json: str = "{}"

    # 使用回数
    usage_count: int = 0

    # 有効フラグ
    is_active: bool = True

    # 作成日時
    created_at: Optional[datetime] = None

    # 更新日時
    updated_at: Optional[datetime] = None


# =============================================================================
# エクスポート
# =============================================================================

__all__ = [
    # 選択肢関連
    "JudgmentOption",
    "OptionScore",
    "OptionEvaluation",

    # 評価基準関連
    "EvaluationCriterion",
    "CriteriaSet",

    # トレードオフ関連
    "TradeoffFactor",
    "Tradeoff",
    "TradeoffAnalysisResult",

    # リスク関連
    "RiskFactor",
    "RiskAssessment",

    # リターン関連
    "ReturnFactor",
    "ReturnAssessment",
    "RiskReturnAnalysis",

    # 整合性チェック関連
    "PastJudgment",
    "ConsistencyIssue",
    "ConsistencyCheckResult",

    # 統合モデル
    "AdvancedJudgmentInput",
    "JudgmentRecommendation",
    "AdvancedJudgmentOutput",

    # DB永続化用
    "JudgmentHistoryDB",
    "EvaluationCriterionDB",
]
