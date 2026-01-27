# lib/brain/advanced_judgment/__init__.py
"""
Phase 2J: 判断力強化（Advanced Judgment）パッケージ

設計書: docs/17_brain_completion_roadmap.md セクション17.3 Phase 2J

ソウルくんの判断力を強化する。
多角的思考、トレードオフ判断、リスク・リターンの定量評価、
過去の判断との整合性チェックを実現。

【Phase 2J の能力】
- 複数選択肢の比較評価
- トレードオフの明示化（「Aを取ればBを犠牲に」）
- リスク・リターンの定量評価
- 過去の判断との整合性チェック

【主要コンポーネント】
- AdvancedJudgment: 統合クラス（メインエントリーポイント）
- OptionEvaluator: 複数選択肢の比較評価
- TradeoffAnalyzer: トレードオフの明示化
- RiskAssessor: リスク・リターンの定量評価
- ConsistencyChecker: 過去の判断との整合性チェック

【ユースケース】
- 「この案件、受けるべき？」への多角的回答
- 採用候補者の比較評価支援
- 投資判断のリスク分析

使用例:
    from lib.brain.advanced_judgment import (
        AdvancedJudgment,
        AdvancedJudgmentInput,
        AdvancedJudgmentOutput,
        JudgmentOption,
        EvaluationCriterion,
        create_advanced_judgment,
    )

    # 高度な判断層の作成
    judgment = create_advanced_judgment(
        pool=db_pool,
        organization_id="org_001",
        get_ai_response_func=get_ai_response,
    )

    # 判断の実行
    result = await judgment.judge(
        AdvancedJudgmentInput(
            question="この案件を受けるべきか？",
            options=[
                JudgmentOption(name="受注する", description="案件を受注"),
                JudgmentOption(name="断る", description="案件を断る"),
                JudgmentOption(name="条件交渉", description="条件を交渉する"),
            ],
            criteria=[
                EvaluationCriterion(name="収益性", importance="high"),
                EvaluationCriterion(name="リスク", importance="high"),
            ],
            context={"budget": 1000000, "deadline": "2026-03-31"},
        )
    )

    # 結果の利用
    print(result.recommendation.natural_language_recommendation)
    print(result.tradeoff_analysis.summary)
    print(result.risk_return_analysis.recommendation)

Author: Claude Opus 4.5
Created: 2026-01-27
"""

__version__ = "1.0.0"
__author__ = "Claude Opus 4.5"


# =============================================================================
# 定数
# =============================================================================

from .constants import (
    # 判断タイプ
    JudgmentType,
    JudgmentComplexity,

    # 評価基準
    CriterionCategory,
    CriterionImportance,
    ScoreLevel,
    CRITERION_IMPORTANCE_WEIGHTS,
    SCORE_LEVEL_VALUES,

    # トレードオフ
    TradeoffType,
    TradeoffSeverity,
    COMMON_TRADEOFFS,

    # リスク
    RiskCategory,
    RiskProbability,
    RiskImpact,
    RISK_PROBABILITY_VALUES,
    RISK_IMPACT_VALUES,
    RISK_SCORE_THRESHOLDS,

    # リターン
    ReturnType,
    ReturnCertainty,
    ReturnTimeframe,
    RETURN_CERTAINTY_DISCOUNT,
    RETURN_TIMEFRAME_MONTHS,

    # 整合性
    ConsistencyLevel,
    ConsistencyDimension,
    CONSISTENCY_LEVEL_SCORES,

    # 推奨
    RecommendationType,
    ConfidenceLevel,
    RECOMMENDATION_SCORE_RANGES,
    CONFIDENCE_LEVEL_RANGES,

    # デフォルト評価基準
    DEFAULT_PROJECT_CRITERIA,
    DEFAULT_HIRING_CRITERIA,
    DEFAULT_INVESTMENT_CRITERIA,

    # 設定
    JUDGMENT_HISTORY_RETENTION_DAYS,
    MAX_SIMILAR_JUDGMENTS,
    SIMILARITY_THRESHOLD,
    DEFAULT_CRITERIA_COUNT,
    MAX_OPTIONS,
    MAX_CRITERIA,
    MAX_RISK_FACTORS,
    MAX_TRADEOFF_DEPTH,
    CONSISTENCY_CHECK_PERIOD_DAYS,

    # Feature Flags
    FEATURE_FLAG_ADVANCED_JUDGMENT,
    FEATURE_FLAG_OPTION_EVALUATION,
    FEATURE_FLAG_TRADEOFF_ANALYSIS,
    FEATURE_FLAG_RISK_ASSESSMENT,
    FEATURE_FLAG_CONSISTENCY_CHECK,

    # プロンプト
    JUDGMENT_ANALYSIS_PROMPT,
)


# =============================================================================
# データモデル
# =============================================================================

from .models import (
    # 選択肢関連
    JudgmentOption,
    OptionScore,
    OptionEvaluation,

    # 評価基準関連
    EvaluationCriterion,
    CriteriaSet,

    # トレードオフ関連
    TradeoffFactor,
    Tradeoff,
    TradeoffAnalysisResult,

    # リスク関連
    RiskFactor,
    RiskAssessment,

    # リターン関連
    ReturnFactor,
    ReturnAssessment,
    RiskReturnAnalysis,

    # 整合性チェック関連
    PastJudgment,
    ConsistencyIssue,
    ConsistencyCheckResult,

    # 統合モデル
    AdvancedJudgmentInput,
    JudgmentRecommendation,
    AdvancedJudgmentOutput,

    # DB永続化用
    JudgmentHistoryDB,
    EvaluationCriterionDB,
)


# =============================================================================
# コンポーネント
# =============================================================================

from .option_evaluator import (
    OptionEvaluator,
    create_option_evaluator,
)

from .tradeoff_analyzer import (
    TradeoffAnalyzer,
    create_tradeoff_analyzer,
)

from .risk_assessor import (
    RiskAssessor,
    create_risk_assessor,
)

from .consistency_checker import (
    ConsistencyChecker,
    create_consistency_checker,
)

from .advanced_judgment import (
    AdvancedJudgment,
    create_advanced_judgment,
)


# =============================================================================
# 公開API
# =============================================================================

__all__ = [
    # バージョン
    "__version__",

    # 定数 - 判断タイプ
    "JudgmentType",
    "JudgmentComplexity",

    # 定数 - 評価基準
    "CriterionCategory",
    "CriterionImportance",
    "ScoreLevel",
    "CRITERION_IMPORTANCE_WEIGHTS",
    "SCORE_LEVEL_VALUES",

    # 定数 - トレードオフ
    "TradeoffType",
    "TradeoffSeverity",
    "COMMON_TRADEOFFS",

    # 定数 - リスク
    "RiskCategory",
    "RiskProbability",
    "RiskImpact",
    "RISK_PROBABILITY_VALUES",
    "RISK_IMPACT_VALUES",
    "RISK_SCORE_THRESHOLDS",

    # 定数 - リターン
    "ReturnType",
    "ReturnCertainty",
    "ReturnTimeframe",
    "RETURN_CERTAINTY_DISCOUNT",
    "RETURN_TIMEFRAME_MONTHS",

    # 定数 - 整合性
    "ConsistencyLevel",
    "ConsistencyDimension",
    "CONSISTENCY_LEVEL_SCORES",

    # 定数 - 推奨
    "RecommendationType",
    "ConfidenceLevel",
    "RECOMMENDATION_SCORE_RANGES",
    "CONFIDENCE_LEVEL_RANGES",

    # 定数 - デフォルト評価基準
    "DEFAULT_PROJECT_CRITERIA",
    "DEFAULT_HIRING_CRITERIA",
    "DEFAULT_INVESTMENT_CRITERIA",

    # 定数 - 設定
    "JUDGMENT_HISTORY_RETENTION_DAYS",
    "MAX_SIMILAR_JUDGMENTS",
    "SIMILARITY_THRESHOLD",
    "DEFAULT_CRITERIA_COUNT",
    "MAX_OPTIONS",
    "MAX_CRITERIA",
    "MAX_RISK_FACTORS",
    "MAX_TRADEOFF_DEPTH",
    "CONSISTENCY_CHECK_PERIOD_DAYS",

    # 定数 - Feature Flags
    "FEATURE_FLAG_ADVANCED_JUDGMENT",
    "FEATURE_FLAG_OPTION_EVALUATION",
    "FEATURE_FLAG_TRADEOFF_ANALYSIS",
    "FEATURE_FLAG_RISK_ASSESSMENT",
    "FEATURE_FLAG_CONSISTENCY_CHECK",

    # 定数 - プロンプト
    "JUDGMENT_ANALYSIS_PROMPT",

    # モデル - 選択肢関連
    "JudgmentOption",
    "OptionScore",
    "OptionEvaluation",

    # モデル - 評価基準関連
    "EvaluationCriterion",
    "CriteriaSet",

    # モデル - トレードオフ関連
    "TradeoffFactor",
    "Tradeoff",
    "TradeoffAnalysisResult",

    # モデル - リスク関連
    "RiskFactor",
    "RiskAssessment",

    # モデル - リターン関連
    "ReturnFactor",
    "ReturnAssessment",
    "RiskReturnAnalysis",

    # モデル - 整合性チェック関連
    "PastJudgment",
    "ConsistencyIssue",
    "ConsistencyCheckResult",

    # モデル - 統合
    "AdvancedJudgmentInput",
    "JudgmentRecommendation",
    "AdvancedJudgmentOutput",

    # モデル - DB永続化用
    "JudgmentHistoryDB",
    "EvaluationCriterionDB",

    # コンポーネント - 選択肢評価
    "OptionEvaluator",
    "create_option_evaluator",

    # コンポーネント - トレードオフ分析
    "TradeoffAnalyzer",
    "create_tradeoff_analyzer",

    # コンポーネント - リスク評価
    "RiskAssessor",
    "create_risk_assessor",

    # コンポーネント - 整合性チェック
    "ConsistencyChecker",
    "create_consistency_checker",

    # コンポーネント - 統合
    "AdvancedJudgment",
    "create_advanced_judgment",
]
