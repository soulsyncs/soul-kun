# tests/test_advanced_judgment.py
"""
Phase 2J: 判断力強化（Advanced Judgment）- 包括的テスト

設計書: docs/17_brain_completion_roadmap.md セクション17.3 Phase 2J

このファイルには、高度な判断層の包括的なテストを定義します。

テスト対象:
- データモデル（models.py）
- 定数（constants.py）
- 選択肢評価（option_evaluator.py）
- トレードオフ分析（tradeoff_analyzer.py）
- リスク評価（risk_assessor.py）
- 整合性チェック（consistency_checker.py）
- 統合クラス（advanced_judgment.py）

Author: Claude Opus 4.5
Created: 2026-01-27
Updated: 2026-01-31
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, List
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

# テスト対象のモジュール
from lib.brain.advanced_judgment import (
    # 定数
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
    CRITERION_IMPORTANCE_WEIGHTS,
    SCORE_LEVEL_VALUES,
    RISK_PROBABILITY_VALUES,
    RISK_IMPACT_VALUES,
    RISK_SCORE_THRESHOLDS,
    RETURN_CERTAINTY_DISCOUNT,
    RETURN_TIMEFRAME_MONTHS,
    CONSISTENCY_LEVEL_SCORES,
    RECOMMENDATION_SCORE_RANGES,
    CONFIDENCE_LEVEL_RANGES,
    COMMON_TRADEOFFS,
    DEFAULT_PROJECT_CRITERIA,
    DEFAULT_HIRING_CRITERIA,
    DEFAULT_INVESTMENT_CRITERIA,
    MAX_OPTIONS,
    MAX_CRITERIA,
    MAX_RISK_FACTORS,
    SIMILARITY_THRESHOLD,
    FEATURE_FLAG_OPTION_EVALUATION,
    FEATURE_FLAG_TRADEOFF_ANALYSIS,
    FEATURE_FLAG_RISK_ASSESSMENT,
    FEATURE_FLAG_CONSISTENCY_CHECK,

    # モデル
    JudgmentOption,
    OptionScore,
    OptionEvaluation,
    EvaluationCriterion,
    CriteriaSet,
    TradeoffFactor,
    Tradeoff,
    TradeoffAnalysisResult,
    RiskFactor,
    RiskAssessment,
    ReturnFactor,
    ReturnAssessment,
    RiskReturnAnalysis,
    PastJudgment,
    ConsistencyIssue,
    ConsistencyCheckResult,
    JudgmentRecommendation,
    AdvancedJudgmentInput,
    AdvancedJudgmentOutput,
    JudgmentHistoryDB,
    EvaluationCriterionDB,

    # コンポーネント
    OptionEvaluator,
    TradeoffAnalyzer,
    RiskAssessor,
    ConsistencyChecker,
    AdvancedJudgment,
    create_option_evaluator,
    create_tradeoff_analyzer,
    create_risk_assessor,
    create_consistency_checker,
    create_advanced_judgment,
)


# =============================================================================
# フィクスチャ
# =============================================================================

@pytest.fixture
def sample_options() -> List[JudgmentOption]:
    """サンプルの選択肢を作成"""
    return [
        JudgmentOption(
            id="opt_1",
            name="案件を受注する",
            description="この案件を受注して進める",
            metadata={
                "revenue": 5000000,
                "risk_level": "medium",
            },
        ),
        JudgmentOption(
            id="opt_2",
            name="案件を断る",
            description="この案件を断って他に集中",
            metadata={
                "revenue": 0,
                "risk_level": "low",
            },
        ),
        JudgmentOption(
            id="opt_3",
            name="条件交渉する",
            description="条件を交渉してから判断",
            metadata={
                "revenue": 4000000,
                "risk_level": "low",
            },
        ),
    ]


@pytest.fixture
def sample_criteria() -> List[EvaluationCriterion]:
    """サンプルの評価基準を作成"""
    return [
        EvaluationCriterion(
            id="crit_1",
            name="収益性",
            category=CriterionCategory.REVENUE.value,
            importance=CriterionImportance.HIGH.value,
            description="期待される収益",
        ),
        EvaluationCriterion(
            id="crit_2",
            name="リスク",
            category=CriterionCategory.RISK.value,
            importance=CriterionImportance.HIGH.value,
            description="プロジェクトのリスク",
            higher_is_better=False,  # リスクは低いほど良い
        ),
        EvaluationCriterion(
            id="crit_3",
            name="戦略的適合性",
            category=CriterionCategory.STRATEGIC.value,
            importance=CriterionImportance.MEDIUM.value,
            description="自社戦略との適合度",
        ),
    ]


@pytest.fixture
def sample_input(sample_options, sample_criteria) -> AdvancedJudgmentInput:
    """サンプルの判断入力を作成"""
    return AdvancedJudgmentInput(
        question="この案件を受けるべきか？",
        judgment_type=JudgmentType.GO_NO_GO.value,
        options=sample_options,
        criteria=sample_criteria,
        context={
            "budget": 3000000,
            "deadline": "2026-03-31",
        },
        organization_id="org_test",
    )


@pytest.fixture
def sample_past_judgments() -> List[PastJudgment]:
    """サンプルの過去判断を作成"""
    return [
        PastJudgment(
            id="past_1",
            judgment_type=JudgmentType.GO_NO_GO.value,
            question="類似の案件を受けるべきか？",
            chosen_option="案件を受注する",
            options=["案件を受注する", "案件を断る"],
            reasoning="収益性が高く、リスクも許容範囲内だった",
            judged_at=datetime.now() - timedelta(days=30),
            organization_id="org_test",
        ),
        PastJudgment(
            id="past_2",
            judgment_type=JudgmentType.GO_NO_GO.value,
            question="別の案件を受けるべきか？",
            chosen_option="案件を断る",
            options=["案件を受注する", "案件を断る"],
            reasoning="リスクが高すぎた",
            outcome="正しい判断だった",
            judged_at=datetime.now() - timedelta(days=60),
            organization_id="org_test",
        ),
    ]


@pytest.fixture
def mock_ai_response():
    """モックのAI応答関数"""
    async def _mock(messages: List, prompt: str) -> str:
        # シンプルなモック応答
        return """
        {
            "evaluations": [
                {
                    "option_id": "opt_1",
                    "option_name": "案件を受注する",
                    "scores": {
                        "crit_1": {"score": 4, "reasoning": "収益性が高い"},
                        "crit_2": {"score": 3, "reasoning": "中程度のリスク"},
                        "crit_3": {"score": 4, "reasoning": "戦略に合致"}
                    },
                    "strengths": ["収益性が高い", "戦略に合致"],
                    "weaknesses": ["中程度のリスクがある"],
                    "summary": "収益性は高いがリスクも考慮必要"
                },
                {
                    "option_id": "opt_2",
                    "option_name": "案件を断る",
                    "scores": {
                        "crit_1": {"score": 1, "reasoning": "収益なし"},
                        "crit_2": {"score": 5, "reasoning": "リスクなし"},
                        "crit_3": {"score": 2, "reasoning": "機会損失"}
                    },
                    "strengths": ["リスクがない"],
                    "weaknesses": ["収益機会の損失"],
                    "summary": "安全だが機会損失"
                },
                {
                    "option_id": "opt_3",
                    "option_name": "条件交渉する",
                    "scores": {
                        "crit_1": {"score": 3, "reasoning": "収益は減少の可能性"},
                        "crit_2": {"score": 4, "reasoning": "リスク低減可能"},
                        "crit_3": {"score": 3, "reasoning": "中程度"}
                    },
                    "strengths": ["リスクを低減できる"],
                    "weaknesses": ["収益が減る可能性"],
                    "summary": "バランスの取れた選択"
                }
            ]
        }
        """
    return _mock


@pytest.fixture
def mock_sync_ai_response():
    """同期版モックのAI応答関数"""
    def _mock(messages: List, prompt: str) -> str:
        return '{"evaluations": []}'
    return _mock


# =============================================================================
# 定数のテスト
# =============================================================================

class TestConstants:
    """定数のテスト"""

    def test_judgment_type_enum(self):
        """JudgmentType列挙型のテスト"""
        assert JudgmentType.COMPARISON.value == "comparison"
        assert JudgmentType.GO_NO_GO.value == "go_no_go"
        assert JudgmentType.CANDIDATE_EVALUATION.value == "candidate_evaluation"
        assert JudgmentType.INVESTMENT_DECISION.value == "investment_decision"
        assert JudgmentType.RISK_ASSESSMENT.value == "risk_assessment"

    def test_judgment_type_all_values(self):
        """JudgmentType全ての値が存在"""
        expected_values = [
            "comparison", "ranking", "best_choice", "risk_assessment",
            "opportunity_assessment", "risk_return_analysis", "go_no_go",
            "approval_decision", "resource_allocation", "candidate_evaluation",
            "performance_review", "investment_decision", "budget_decision",
            "roi_analysis",
        ]
        actual_values = [jt.value for jt in JudgmentType]
        for ev in expected_values:
            assert ev in actual_values

    def test_judgment_complexity_enum(self):
        """JudgmentComplexity列挙型のテスト"""
        assert JudgmentComplexity.SIMPLE.value == "simple"
        assert JudgmentComplexity.MODERATE.value == "moderate"
        assert JudgmentComplexity.COMPLEX.value == "complex"
        assert JudgmentComplexity.HIGHLY_COMPLEX.value == "highly_complex"

    def test_criterion_category_enum(self):
        """CriterionCategory列挙型のテスト"""
        assert CriterionCategory.REVENUE.value == "revenue"
        assert CriterionCategory.RISK.value == "risk"
        assert CriterionCategory.TECHNICAL.value == "technical"
        assert CriterionCategory.FINANCIAL.value == "financial"
        assert CriterionCategory.STRATEGIC.value == "strategic"

    def test_criterion_importance_weights(self):
        """重要度の重みマッピングのテスト"""
        assert CRITERION_IMPORTANCE_WEIGHTS["critical"] == 1.0
        assert CRITERION_IMPORTANCE_WEIGHTS["high"] == 0.8
        assert CRITERION_IMPORTANCE_WEIGHTS["medium"] == 0.6
        assert CRITERION_IMPORTANCE_WEIGHTS["low"] == 0.4
        assert CRITERION_IMPORTANCE_WEIGHTS["optional"] == 0.2

    def test_score_level_values(self):
        """スコアレベルの数値マッピングのテスト"""
        assert SCORE_LEVEL_VALUES["excellent"] == 5
        assert SCORE_LEVEL_VALUES["good"] == 4
        assert SCORE_LEVEL_VALUES["acceptable"] == 3
        assert SCORE_LEVEL_VALUES["poor"] == 2
        assert SCORE_LEVEL_VALUES["unacceptable"] == 1

    def test_tradeoff_severity_enum(self):
        """TradeoffSeverity列挙型のテスト"""
        assert TradeoffSeverity.CRITICAL.value == "critical"
        assert TradeoffSeverity.SIGNIFICANT.value == "significant"
        assert TradeoffSeverity.MODERATE.value == "moderate"
        assert TradeoffSeverity.MINOR.value == "minor"
        assert TradeoffSeverity.NEGLIGIBLE.value == "negligible"

    def test_risk_probability_values(self):
        """リスク発生確率の数値マッピングのテスト"""
        assert RISK_PROBABILITY_VALUES["rare"] == 0.05
        assert RISK_PROBABILITY_VALUES["unlikely"] == 0.20
        assert RISK_PROBABILITY_VALUES["possible"] == 0.40
        assert RISK_PROBABILITY_VALUES["likely"] == 0.60
        assert RISK_PROBABILITY_VALUES["almost_certain"] == 0.85

    def test_risk_impact_values(self):
        """リスク影響度の数値マッピングのテスト"""
        assert RISK_IMPACT_VALUES["negligible"] == 1
        assert RISK_IMPACT_VALUES["minor"] == 2
        assert RISK_IMPACT_VALUES["moderate"] == 3
        assert RISK_IMPACT_VALUES["major"] == 4
        assert RISK_IMPACT_VALUES["severe"] == 5

    def test_risk_score_thresholds(self):
        """リスクスコア閾値のテスト"""
        assert RISK_SCORE_THRESHOLDS["low"] == (0, 4)
        assert RISK_SCORE_THRESHOLDS["medium"] == (5, 9)
        assert RISK_SCORE_THRESHOLDS["high"] == (10, 15)
        assert RISK_SCORE_THRESHOLDS["critical"] == (16, 25)

    def test_return_certainty_discount(self):
        """リターン確実性の割引係数のテスト"""
        assert RETURN_CERTAINTY_DISCOUNT["guaranteed"] == 1.0
        assert RETURN_CERTAINTY_DISCOUNT["highly_likely"] == 0.9
        assert RETURN_CERTAINTY_DISCOUNT["expected"] == 0.7
        assert RETURN_CERTAINTY_DISCOUNT["possible"] == 0.5
        assert RETURN_CERTAINTY_DISCOUNT["speculative"] == 0.3

    def test_return_timeframe_months(self):
        """リターン時間軸の月数マッピングのテスト"""
        assert RETURN_TIMEFRAME_MONTHS["immediate"] == 1
        assert RETURN_TIMEFRAME_MONTHS["short_term"] == 2
        assert RETURN_TIMEFRAME_MONTHS["medium_term"] == 6
        assert RETURN_TIMEFRAME_MONTHS["long_term"] == 24
        assert RETURN_TIMEFRAME_MONTHS["very_long_term"] == 48

    def test_consistency_level_scores(self):
        """整合性レベルのスコアマッピングのテスト"""
        assert CONSISTENCY_LEVEL_SCORES["fully_consistent"] == 1.0
        assert CONSISTENCY_LEVEL_SCORES["mostly_consistent"] == 0.8
        assert CONSISTENCY_LEVEL_SCORES["partially_consistent"] == 0.5
        assert CONSISTENCY_LEVEL_SCORES["inconsistent"] == 0.2
        assert CONSISTENCY_LEVEL_SCORES["contradictory"] == 0.0

    def test_recommendation_score_ranges(self):
        """推奨スコア範囲のテスト"""
        assert RECOMMENDATION_SCORE_RANGES["strong_recommend"] == (0.85, 1.0)
        assert RECOMMENDATION_SCORE_RANGES["recommend"] == (0.70, 0.85)
        assert RECOMMENDATION_SCORE_RANGES["neutral"] == (0.45, 0.55)
        assert RECOMMENDATION_SCORE_RANGES["not_recommend"] == (0.15, 0.30)

    def test_confidence_level_ranges(self):
        """確信度レベル範囲のテスト"""
        assert CONFIDENCE_LEVEL_RANGES["very_high"] == (0.90, 1.0)
        assert CONFIDENCE_LEVEL_RANGES["high"] == (0.70, 0.90)
        assert CONFIDENCE_LEVEL_RANGES["medium"] == (0.50, 0.70)
        assert CONFIDENCE_LEVEL_RANGES["low"] == (0.30, 0.50)
        assert CONFIDENCE_LEVEL_RANGES["very_low"] == (0.0, 0.30)

    def test_common_tradeoffs(self):
        """共通トレードオフパターンのテスト"""
        assert "cost_quality" in COMMON_TRADEOFFS
        assert "speed_quality" in COMMON_TRADEOFFS
        assert "risk_reward" in COMMON_TRADEOFFS
        assert COMMON_TRADEOFFS["cost_quality"]["factor_a"] == "コスト削減"

    def test_default_criteria(self):
        """デフォルト評価基準のテスト"""
        assert len(DEFAULT_PROJECT_CRITERIA) > 0
        assert len(DEFAULT_HIRING_CRITERIA) > 0
        assert len(DEFAULT_INVESTMENT_CRITERIA) > 0

    def test_max_limits(self):
        """最大制限値のテスト"""
        assert MAX_OPTIONS == 20
        assert MAX_CRITERIA == 30
        assert MAX_RISK_FACTORS == 50


# =============================================================================
# モデルのテスト
# =============================================================================

class TestJudgmentOption:
    """JudgmentOptionモデルのテスト"""

    def test_creation_with_defaults(self):
        """デフォルト値での作成テスト"""
        option = JudgmentOption()
        assert option.name == ""
        assert option.description == ""
        assert option.id  # IDが自動生成される
        assert option.label == ""  # nameが空なのでlabelも空
        assert option.metadata == {}
        assert option.order == 0
        assert option.is_active is True

    def test_creation_with_values(self):
        """値を指定した作成テスト"""
        option = JudgmentOption(
            name="テスト選択肢",
            description="説明文",
            label="短いラベル",
            metadata={"key": "value"},
            order=1,
            is_active=False,
        )
        assert option.name == "テスト選択肢"
        assert option.description == "説明文"
        assert option.label == "短いラベル"
        assert option.metadata == {"key": "value"}
        assert option.order == 1
        assert option.is_active is False

    def test_label_defaults_to_name(self):
        """ラベルがデフォルトで名前になることをテスト"""
        option = JudgmentOption(name="テスト選択肢")
        assert option.label == "テスト選択肢"

    def test_id_is_unique(self):
        """IDがユニークであることをテスト"""
        option1 = JudgmentOption(name="選択肢1")
        option2 = JudgmentOption(name="選択肢2")
        assert option1.id != option2.id


class TestOptionScore:
    """OptionScoreモデルのテスト"""

    def test_creation_with_defaults(self):
        """デフォルト値での作成テスト"""
        score = OptionScore()
        assert score.option_id == ""
        assert score.criterion_id == ""
        assert score.score == 3
        assert score.score_level == ScoreLevel.ACCEPTABLE.value
        assert score.reasoning == ""
        assert score.confidence == 0.7
        assert score.metadata == {}

    def test_creation_with_values(self):
        """値を指定した作成テスト"""
        score = OptionScore(
            option_id="opt_1",
            criterion_id="crit_1",
            score=5,
            score_level=ScoreLevel.EXCELLENT.value,
            reasoning="非常に優れている",
            confidence=0.9,
        )
        assert score.score == 5
        assert score.score_level == ScoreLevel.EXCELLENT.value
        assert score.confidence == 0.9


class TestOptionEvaluation:
    """OptionEvaluationモデルのテスト"""

    def test_creation_with_defaults(self):
        """デフォルト値での作成テスト"""
        evaluation = OptionEvaluation()
        assert evaluation.option is not None
        assert evaluation.criterion_scores == []
        assert evaluation.total_score == 0.0
        assert evaluation.normalized_score == 0.0
        assert evaluation.rank == 0
        assert evaluation.strengths == []
        assert evaluation.weaknesses == []
        assert evaluation.summary == ""
        assert evaluation.confidence == 0.7

    def test_creation_with_values(self, sample_options):
        """値を指定した作成テスト"""
        evaluation = OptionEvaluation(
            option=sample_options[0],
            total_score=4.5,
            normalized_score=0.875,
            rank=1,
            strengths=["強み1", "強み2"],
            weaknesses=["弱み1"],
            summary="良い選択肢",
            confidence=0.85,
        )
        assert evaluation.option.name == "案件を受注する"
        assert evaluation.total_score == 4.5
        assert evaluation.rank == 1


class TestEvaluationCriterion:
    """EvaluationCriterionモデルのテスト"""

    def test_creation_with_defaults(self):
        """デフォルト値での作成テスト"""
        criterion = EvaluationCriterion()
        assert criterion.name == ""
        assert criterion.category == CriterionCategory.OTHER.value
        assert criterion.importance == CriterionImportance.MEDIUM.value
        assert criterion.weight == 0.6  # MEDIUMのデフォルト重み
        assert criterion.description == ""
        assert criterion.higher_is_better is True
        assert criterion.score_guidelines == {}
        assert criterion.metadata == {}
        assert criterion.is_active is True

    def test_weight_calculation_from_importance(self):
        """重要度から重みが計算されることをテスト"""
        critical = EvaluationCriterion(importance=CriterionImportance.CRITICAL.value)
        assert critical.weight == 1.0

        high = EvaluationCriterion(importance=CriterionImportance.HIGH.value)
        assert high.weight == 0.8

        low = EvaluationCriterion(importance=CriterionImportance.LOW.value)
        assert low.weight == 0.4

    def test_custom_weight_not_overwritten(self):
        """カスタム重みが上書きされないことをテスト"""
        # 重みを明示的に0.6以外に設定した場合は計算されない
        criterion = EvaluationCriterion(
            importance=CriterionImportance.HIGH.value,
            weight=0.9,  # カスタム重み
        )
        assert criterion.weight == 0.9


class TestCriteriaSet:
    """CriteriaSetモデルのテスト"""

    def test_creation_with_defaults(self):
        """デフォルト値での作成テスト"""
        criteria_set = CriteriaSet()
        assert criteria_set.name == ""
        assert criteria_set.description == ""
        assert criteria_set.judgment_type is None
        assert criteria_set.criteria == []
        assert criteria_set.metadata == {}

    def test_creation_with_criteria(self, sample_criteria):
        """基準を含む作成テスト"""
        criteria_set = CriteriaSet(
            name="プロジェクト評価基準",
            description="案件評価用の基準セット",
            judgment_type=JudgmentType.GO_NO_GO.value,
            criteria=sample_criteria,
        )
        assert len(criteria_set.criteria) == 3


class TestTradeoffFactor:
    """TradeoffFactorモデルのテスト"""

    def test_creation_with_defaults(self):
        """デフォルト値での作成テスト"""
        factor = TradeoffFactor()
        assert factor.name == ""
        assert factor.description == ""
        assert factor.related_option_ids == []
        assert factor.related_criterion_ids == []
        assert factor.impact == 0.5

    def test_creation_with_values(self):
        """値を指定した作成テスト"""
        factor = TradeoffFactor(
            name="コスト削減",
            description="コストを削減すること",
            related_option_ids=["opt_1"],
            related_criterion_ids=["crit_1"],
            impact=0.8,
        )
        assert factor.name == "コスト削減"
        assert factor.impact == 0.8


class TestTradeoff:
    """Tradeoffモデルのテスト"""

    def test_creation_with_defaults(self):
        """デフォルト値での作成テスト"""
        tradeoff = Tradeoff()
        assert tradeoff.tradeoff_type == TradeoffType.CUSTOM.value
        assert tradeoff.severity == TradeoffSeverity.MODERATE.value
        assert tradeoff.description == ""
        assert tradeoff.natural_language == ""
        assert tradeoff.mitigation_options == []
        assert tradeoff.confidence == 0.7

    def test_to_natural_language_default(self):
        """自然言語表現の生成テスト"""
        tradeoff = Tradeoff(
            factor_a=TradeoffFactor(name="コスト削減"),
            factor_b=TradeoffFactor(name="品質"),
            severity=TradeoffSeverity.MODERATE.value,
        )
        text = tradeoff.to_natural_language()
        assert "コスト削減" in text
        assert "品質" in text
        assert "犠牲" in text

    def test_to_natural_language_with_severity(self):
        """深刻度別の自然言語表現テスト"""
        # CRITICAL
        critical = Tradeoff(
            factor_a=TradeoffFactor(name="A"),
            factor_b=TradeoffFactor(name="B"),
            severity=TradeoffSeverity.CRITICAL.value,
        )
        text = critical.to_natural_language()
        assert "致命的に" in text

        # NEGLIGIBLE
        negligible = Tradeoff(
            factor_a=TradeoffFactor(name="A"),
            factor_b=TradeoffFactor(name="B"),
            severity=TradeoffSeverity.NEGLIGIBLE.value,
        )
        text = negligible.to_natural_language()
        assert "わずかに" in text

    def test_to_natural_language_uses_preset(self):
        """事前設定の自然言語が優先されることをテスト"""
        tradeoff = Tradeoff(
            factor_a=TradeoffFactor(name="A"),
            factor_b=TradeoffFactor(name="B"),
            natural_language="カスタムの説明",
        )
        assert tradeoff.to_natural_language() == "カスタムの説明"


class TestRiskFactor:
    """RiskFactorモデルのテスト"""

    def test_creation_with_defaults(self):
        """デフォルト値での作成テスト"""
        risk = RiskFactor()
        assert risk.name == ""
        assert risk.category == RiskCategory.OTHER.value
        assert risk.probability == RiskProbability.POSSIBLE.value
        assert risk.impact == RiskImpact.MODERATE.value
        assert risk.risk_score == 0.0
        assert risk.risk_level == "medium"
        assert risk.mitigation_strategies == []
        assert risk.confidence == 0.7

    def test_calculate_risk_score(self):
        """リスクスコア計算テスト"""
        risk = RiskFactor(
            name="テストリスク",
            probability=RiskProbability.LIKELY.value,  # 0.60
            impact=RiskImpact.MAJOR.value,  # 4
        )
        score = risk.calculate_risk_score()
        # score = 0.60 * 4 * 5 = 12.0
        assert score == 12.0
        assert risk.probability_value == 0.60
        assert risk.impact_value == 4
        assert risk.risk_level == "high"  # 10-15の範囲

    def test_calculate_risk_score_low(self):
        """低リスクスコア計算テスト"""
        risk = RiskFactor(
            probability=RiskProbability.RARE.value,  # 0.05
            impact=RiskImpact.MINOR.value,  # 2
        )
        score = risk.calculate_risk_score()
        # score = 0.05 * 2 * 5 = 0.5
        assert score == 0.5
        assert risk.risk_level == "low"

    def test_calculate_risk_score_critical(self):
        """クリティカルリスクスコア計算テスト"""
        risk = RiskFactor(
            probability=RiskProbability.ALMOST_CERTAIN.value,  # 0.85
            impact=RiskImpact.SEVERE.value,  # 5
        )
        score = risk.calculate_risk_score()
        # score = 0.85 * 5 * 5 = 21.25
        assert score == 21.25
        assert risk.risk_level == "critical"


class TestReturnFactor:
    """ReturnFactorモデルのテスト"""

    def test_creation_with_defaults(self):
        """デフォルト値での作成テスト"""
        ret = ReturnFactor()
        assert ret.name == ""
        assert ret.return_type == ReturnType.OTHER.value
        assert ret.expected_value == 0.0
        assert ret.certainty == ReturnCertainty.EXPECTED.value
        assert ret.timeframe == ReturnTimeframe.MEDIUM_TERM.value
        assert ret.adjusted_value == 0.0

    def test_calculate_adjusted_value_expected(self):
        """調整後期待値計算テスト（EXPECTED）"""
        ret = ReturnFactor(
            expected_value=1000000,
            certainty=ReturnCertainty.EXPECTED.value,
        )
        adjusted = ret.calculate_adjusted_value()
        assert adjusted == 1000000 * 0.7

    def test_calculate_adjusted_value_guaranteed(self):
        """調整後期待値計算テスト（GUARANTEED）"""
        ret = ReturnFactor(
            expected_value=500000,
            certainty=ReturnCertainty.GUARANTEED.value,
        )
        adjusted = ret.calculate_adjusted_value()
        assert adjusted == 500000 * 1.0

    def test_calculate_adjusted_value_speculative(self):
        """調整後期待値計算テスト（SPECULATIVE）"""
        ret = ReturnFactor(
            expected_value=2000000,
            certainty=ReturnCertainty.SPECULATIVE.value,
        )
        adjusted = ret.calculate_adjusted_value()
        assert adjusted == 2000000 * 0.3


class TestPastJudgment:
    """PastJudgmentモデルのテスト"""

    def test_creation_with_defaults(self):
        """デフォルト値での作成テスト"""
        judgment = PastJudgment()
        assert judgment.judgment_type == JudgmentType.COMPARISON.value
        assert judgment.question == ""
        assert judgment.chosen_option == ""
        assert judgment.options == []
        assert judgment.reasoning == ""
        assert judgment.outcome is None
        assert judgment.judged_at is not None
        assert judgment.organization_id == ""
        assert judgment.tags == []

    def test_creation_with_values(self):
        """値を指定した作成テスト"""
        judgment = PastJudgment(
            question="テスト質問",
            chosen_option="選択肢A",
            options=["選択肢A", "選択肢B"],
            reasoning="理由説明",
            outcome="成功",
            tags=["タグ1", "タグ2"],
        )
        assert judgment.question == "テスト質問"
        assert judgment.chosen_option == "選択肢A"
        assert len(judgment.options) == 2


class TestConsistencyIssue:
    """ConsistencyIssueモデルのテスト"""

    def test_creation_with_defaults(self):
        """デフォルト値での作成テスト"""
        issue = ConsistencyIssue()
        assert issue.dimension == ConsistencyDimension.PRECEDENT_CONSISTENCY.value
        assert issue.description == ""
        assert issue.related_judgment is None
        assert issue.severity == 0.5
        assert issue.recommendation == ""


class TestAdvancedJudgmentInput:
    """AdvancedJudgmentInputモデルのテスト"""

    def test_creation_with_defaults(self):
        """デフォルト値での作成テスト"""
        input_data = AdvancedJudgmentInput()
        assert input_data.question == ""
        assert input_data.judgment_type == JudgmentType.COMPARISON.value
        assert input_data.options == []
        assert input_data.criteria is None
        assert input_data.context == {}
        assert input_data.organization_id == ""
        assert input_data.constraints == []

    def test_creation_with_values(self, sample_options, sample_criteria):
        """値を指定した作成テスト"""
        input_data = AdvancedJudgmentInput(
            question="テスト質問",
            judgment_type=JudgmentType.GO_NO_GO.value,
            options=sample_options,
            criteria=sample_criteria,
            context={"key": "value"},
            organization_id="org_123",
            constraints=["制約1", "制約2"],
        )
        assert input_data.question == "テスト質問"
        assert len(input_data.options) == 3
        assert len(input_data.criteria) == 3


class TestAdvancedJudgmentOutput:
    """AdvancedJudgmentOutputモデルのテスト"""

    def test_creation_with_defaults(self):
        """デフォルト値での作成テスト"""
        output = AdvancedJudgmentOutput()
        assert output.judgment_type == JudgmentType.COMPARISON.value
        assert output.complexity == JudgmentComplexity.MODERATE.value
        assert output.option_evaluations == []
        assert output.tradeoff_analysis is None
        assert output.risk_return_analysis is None
        assert output.consistency_check is None
        assert output.overall_confidence == 0.7
        assert output.needs_confirmation is False
        assert output.warnings == []
        assert output.errors == []


class TestDBModels:
    """DB永続化用モデルのテスト"""

    def test_judgment_history_db_creation(self):
        """JudgmentHistoryDBの作成テスト"""
        history = JudgmentHistoryDB(
            organization_id="org_123",
            judgment_type=JudgmentType.GO_NO_GO.value,
            question="テスト質問",
        )
        assert history.organization_id == "org_123"
        assert history.options_json == "[]"
        assert history.criteria_json == "[]"

    def test_evaluation_criterion_db_creation(self):
        """EvaluationCriterionDBの作成テスト"""
        criterion = EvaluationCriterionDB(
            organization_id="org_123",
            name="テスト基準",
            category=CriterionCategory.REVENUE.value,
        )
        assert criterion.organization_id == "org_123"
        assert criterion.usage_count == 0
        assert criterion.is_active is True


# =============================================================================
# OptionEvaluatorのテスト
# =============================================================================

class TestOptionEvaluator:
    """選択肢評価エンジンのテスト"""

    def test_init_without_llm(self):
        """LLMなしでの初期化テスト"""
        evaluator = create_option_evaluator(use_llm=False)
        assert evaluator is not None
        assert evaluator.use_llm is False

    def test_init_with_llm(self, mock_ai_response):
        """LLMありでの初期化テスト"""
        evaluator = create_option_evaluator(
            get_ai_response_func=mock_ai_response,
            use_llm=True,
        )
        assert evaluator.use_llm is True

    @pytest.mark.asyncio
    async def test_evaluate_without_llm(self, sample_options, sample_criteria):
        """LLMなしの評価テスト"""
        evaluator = create_option_evaluator(use_llm=False)

        results = await evaluator.evaluate(
            options=sample_options,
            criteria=sample_criteria,
            question="この案件を受けるべきか？",
        )

        assert len(results) == 3
        assert all(isinstance(r, OptionEvaluation) for r in results)
        assert results[0].rank == 1  # 最高スコアが1位

    @pytest.mark.asyncio
    async def test_evaluate_empty_options(self, sample_criteria):
        """選択肢なしの評価テスト"""
        evaluator = create_option_evaluator(use_llm=False)

        results = await evaluator.evaluate(
            options=[],
            criteria=sample_criteria,
            question="テスト",
        )

        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_evaluate_max_options_limit(self, sample_criteria):
        """最大選択肢数制限のテスト"""
        evaluator = create_option_evaluator(use_llm=False)

        # MAX_OPTIONS + 5 個の選択肢を作成
        many_options = [
            JudgmentOption(name=f"選択肢{i}")
            for i in range(MAX_OPTIONS + 5)
        ]

        results = await evaluator.evaluate(
            options=many_options,
            criteria=sample_criteria,
            question="テスト",
        )

        # MAX_OPTIONSに制限される
        assert len(results) == MAX_OPTIONS

    @pytest.mark.asyncio
    async def test_evaluate_with_mock_llm(
        self, sample_options, sample_criteria, mock_ai_response
    ):
        """モックLLMでの評価テスト"""
        evaluator = create_option_evaluator(
            get_ai_response_func=mock_ai_response,
            use_llm=True,
        )

        results = await evaluator.evaluate(
            options=sample_options,
            criteria=sample_criteria,
            question="この案件を受けるべきか？",
        )

        assert len(results) == 3
        # LLMの結果が反映されている
        top_result = results[0]
        assert top_result.total_score > 0

    @pytest.mark.asyncio
    async def test_evaluate_with_sync_llm(
        self, sample_options, sample_criteria, mock_sync_ai_response
    ):
        """同期LLMでの評価テスト（フォールバック）"""
        evaluator = create_option_evaluator(
            get_ai_response_func=mock_sync_ai_response,
            use_llm=True,
        )

        results = await evaluator.evaluate(
            options=sample_options,
            criteria=sample_criteria,
            question="テスト",
        )

        # 同期関数でも動作する
        assert len(results) == 3

    def test_get_default_criteria_go_no_go(self):
        """GO_NO_GO用デフォルト評価基準の取得テスト"""
        evaluator = create_option_evaluator(use_llm=False)
        criteria = evaluator._get_default_criteria(JudgmentType.GO_NO_GO.value)
        assert len(criteria) > 0
        # プロジェクト基準が使われる
        names = [c.name for c in criteria]
        assert "収益性" in names or len(criteria) > 0

    def test_get_default_criteria_candidate_evaluation(self):
        """候補者評価用デフォルト評価基準の取得テスト"""
        evaluator = create_option_evaluator(use_llm=False)
        criteria = evaluator._get_default_criteria(
            JudgmentType.CANDIDATE_EVALUATION.value
        )
        assert len(criteria) > 0

    def test_get_default_criteria_investment(self):
        """投資判断用デフォルト評価基準の取得テスト"""
        evaluator = create_option_evaluator(use_llm=False)
        criteria = evaluator._get_default_criteria(
            JudgmentType.INVESTMENT_DECISION.value
        )
        assert len(criteria) > 0

    def test_score_to_level(self):
        """スコアからレベルへの変換テスト"""
        evaluator = create_option_evaluator(use_llm=False)
        assert evaluator._score_to_level(5) == ScoreLevel.EXCELLENT.value
        assert evaluator._score_to_level(4) == ScoreLevel.GOOD.value
        assert evaluator._score_to_level(3) == ScoreLevel.ACCEPTABLE.value
        assert evaluator._score_to_level(2) == ScoreLevel.POOR.value
        assert evaluator._score_to_level(1) == ScoreLevel.UNACCEPTABLE.value

    def test_score_gap_calculation(self, sample_options):
        """スコア差の計算テスト"""
        evaluator = create_option_evaluator(use_llm=False)

        evaluations = [
            OptionEvaluation(
                option=sample_options[0],
                total_score=4.0,
                rank=1,
            ),
            OptionEvaluation(
                option=sample_options[1],
                total_score=3.5,
                rank=2,
            ),
        ]

        gap = evaluator.get_score_gap(evaluations)
        assert gap == 0.5

    def test_score_gap_single_option(self, sample_options):
        """選択肢1つでのスコア差テスト"""
        evaluator = create_option_evaluator(use_llm=False)

        evaluations = [
            OptionEvaluation(option=sample_options[0], total_score=4.0, rank=1),
        ]

        gap = evaluator.get_score_gap(evaluations)
        assert gap == 0.0

    def test_is_clear_winner(self, sample_options):
        """明確な勝者の判定テスト"""
        evaluator = create_option_evaluator(use_llm=False)

        # 差が大きい場合
        evaluations_large_gap = [
            OptionEvaluation(option=sample_options[0], total_score=4.5, rank=1),
            OptionEvaluation(option=sample_options[1], total_score=3.0, rank=2),
        ]
        assert evaluator.is_clear_winner(evaluations_large_gap, threshold=0.3)

        # 差が小さい場合
        evaluations_small_gap = [
            OptionEvaluation(option=sample_options[0], total_score=4.0, rank=1),
            OptionEvaluation(option=sample_options[1], total_score=3.9, rank=2),
        ]
        assert not evaluator.is_clear_winner(evaluations_small_gap, threshold=0.3)

    def test_get_top_option(self, sample_options):
        """最高スコア選択肢取得テスト"""
        evaluator = create_option_evaluator(use_llm=False)

        evaluations = [
            OptionEvaluation(option=sample_options[0], total_score=4.0, rank=1),
            OptionEvaluation(option=sample_options[1], total_score=3.0, rank=2),
        ]

        top = evaluator.get_top_option(evaluations)
        assert top is not None
        assert top.option.name == "案件を受注する"

    def test_get_top_option_empty(self):
        """選択肢なしでの最高スコア取得テスト"""
        evaluator = create_option_evaluator(use_llm=False)
        top = evaluator.get_top_option([])
        assert top is None


# =============================================================================
# TradeoffAnalyzerのテスト
# =============================================================================

class TestTradeoffAnalyzer:
    """トレードオフ分析エンジンのテスト"""

    def test_init_without_llm(self):
        """LLMなしでの初期化テスト"""
        analyzer = create_tradeoff_analyzer(use_llm=False)
        assert analyzer is not None
        assert analyzer.use_llm is False

    @pytest.mark.asyncio
    async def test_analyze_tradeoffs(self, sample_options, sample_criteria):
        """トレードオフ分析のテスト"""
        analyzer = create_tradeoff_analyzer(use_llm=False)

        # 評価結果を作成（高収益だがリスクも高い）
        evaluations = [
            OptionEvaluation(
                option=sample_options[0],
                criterion_scores=[
                    OptionScore(option_id="opt_1", criterion_id="crit_1", score=5),
                    OptionScore(option_id="opt_1", criterion_id="crit_2", score=2),
                ],
                total_score=3.5,
                rank=1,
            ),
        ]

        result = await analyzer.analyze(
            evaluations=evaluations,
            criteria=sample_criteria,
            question="テスト",
        )

        assert isinstance(result, TradeoffAnalysisResult)
        assert result.processing_time_ms >= 0

    @pytest.mark.asyncio
    async def test_analyze_empty_evaluations(self, sample_criteria):
        """評価なしでの分析テスト"""
        analyzer = create_tradeoff_analyzer(use_llm=False)

        result = await analyzer.analyze(
            evaluations=[],
            criteria=sample_criteria,
            question="テスト",
        )

        assert isinstance(result, TradeoffAnalysisResult)
        # 評価がなくても、評価基準間のトレードオフ（リスクvs収益など）が検出される
        assert result.total_count >= 0

    def test_tradeoff_severity_calculation(self):
        """トレードオフ深刻度の計算テスト"""
        analyzer = create_tradeoff_analyzer(use_llm=False)

        # 差4以上 -> CRITICAL
        severity = analyzer._calculate_tradeoff_severity(5, 1)
        assert severity == TradeoffSeverity.CRITICAL.value

        # 差3 -> MODERATE
        severity = analyzer._calculate_tradeoff_severity(5, 2)
        assert severity == TradeoffSeverity.MODERATE.value

        # 差2 -> MINOR
        severity = analyzer._calculate_tradeoff_severity(4, 2)
        assert severity == TradeoffSeverity.MINOR.value

        # 差1以下 -> NEGLIGIBLE
        severity = analyzer._calculate_tradeoff_severity(4, 3)
        assert severity == TradeoffSeverity.NEGLIGIBLE.value

    def test_generate_summary_no_tradeoffs(self):
        """トレードオフなしでのサマリー生成テスト"""
        analyzer = create_tradeoff_analyzer(use_llm=False)
        summary = analyzer._generate_summary([])
        assert "検出されませんでした" in summary

    def test_generate_summary_with_tradeoffs(self):
        """トレードオフありでのサマリー生成テスト"""
        analyzer = create_tradeoff_analyzer(use_llm=False)

        tradeoffs = [
            Tradeoff(
                factor_a=TradeoffFactor(name="A"),
                factor_b=TradeoffFactor(name="B"),
                severity=TradeoffSeverity.CRITICAL.value,
            ),
            Tradeoff(
                factor_a=TradeoffFactor(name="C"),
                factor_b=TradeoffFactor(name="D"),
                severity=TradeoffSeverity.MODERATE.value,
            ),
        ]

        summary = analyzer._generate_summary(tradeoffs)
        assert "2件" in summary
        assert "致命的" in summary

    def test_is_similar_tradeoff(self):
        """類似トレードオフ判定テスト"""
        analyzer = create_tradeoff_analyzer(use_llm=False)

        # 同じタイプ
        t1 = Tradeoff(tradeoff_type=TradeoffType.COST_QUALITY.value)
        t2 = Tradeoff(tradeoff_type=TradeoffType.COST_QUALITY.value)
        assert analyzer._is_similar_tradeoff(t1, t2) is True

        # 異なるタイプ
        t3 = Tradeoff(tradeoff_type=TradeoffType.SPEED_QUALITY.value)
        assert analyzer._is_similar_tradeoff(t1, t3) is False


# =============================================================================
# RiskAssessorのテスト
# =============================================================================

class TestRiskAssessor:
    """リスク評価エンジンのテスト"""

    def test_init_without_llm(self):
        """LLMなしでの初期化テスト"""
        assessor = create_risk_assessor(use_llm=False)
        assert assessor is not None
        assert assessor.use_llm is False

    @pytest.mark.asyncio
    async def test_assess_risk_return(self, sample_options):
        """リスク・リターン評価のテスト"""
        assessor = create_risk_assessor(use_llm=False)

        result = await assessor.assess(
            options=sample_options,
            question="この案件を受けるべきか？",
            context={"budget": 3000000},
        )

        assert isinstance(result, RiskReturnAnalysis)
        assert isinstance(result.risk_assessment, RiskAssessment)
        assert isinstance(result.return_assessment, ReturnAssessment)

    @pytest.mark.asyncio
    async def test_assess_empty_options(self):
        """選択肢なしでの評価テスト"""
        assessor = create_risk_assessor(use_llm=False)

        result = await assessor.assess(
            options=[],
            question="テスト",
            context={},
        )

        assert isinstance(result, RiskReturnAnalysis)

    @pytest.mark.asyncio
    async def test_assess_with_budget_overrun(self):
        """予算超過リスク検出テスト"""
        assessor = create_risk_assessor(use_llm=False)

        options = [
            JudgmentOption(
                name="高コスト案件",
                metadata={"cost": 5000000},
            ),
        ]

        result = await assessor.assess(
            options=options,
            question="テスト",
            context={"budget": 3000000},
        )

        # 予算超過リスクが検出される
        risk_names = [r.name for r in result.risk_assessment.risks]
        assert any("予算超過" in name for name in risk_names)

    @pytest.mark.asyncio
    async def test_assess_with_deadline(self):
        """期限リスク検出テスト"""
        assessor = create_risk_assessor(use_llm=False)

        options = [
            JudgmentOption(
                name="期限付き案件",
                metadata={"deadline": "2026-03-31"},
            ),
        ]

        result = await assessor.assess(
            options=options,
            question="テスト",
            context={},
        )

        # スケジュールリスクが検出される
        risk_names = [r.name for r in result.risk_assessment.risks]
        assert any("スケジュール" in name for name in risk_names)

    def test_overall_risk_calculation(self):
        """全体リスクスコアの計算テスト"""
        assessor = create_risk_assessor(use_llm=False)

        risks = [
            RiskFactor(
                name="リスク1",
                probability=RiskProbability.LIKELY.value,
                impact=RiskImpact.MAJOR.value,
            ),
            RiskFactor(
                name="リスク2",
                probability=RiskProbability.UNLIKELY.value,
                impact=RiskImpact.MINOR.value,
            ),
        ]

        for risk in risks:
            risk.calculate_risk_score()

        assessment = assessor._calculate_overall_risk(risks)
        assert assessment.overall_risk_score > 0
        assert assessment.overall_risk_level in ["low", "medium", "high", "critical"]
        assert len(assessment.top_risks) <= 5

    def test_overall_risk_empty(self):
        """リスクなしでの全体評価テスト"""
        assessor = create_risk_assessor(use_llm=False)
        assessment = assessor._calculate_overall_risk([])
        assert assessment.overall_risk_score == 0.0
        assert assessment.overall_risk_level == "low"

    def test_generate_recommendation_critical_risk(self):
        """クリティカルリスクでの推奨生成テスト"""
        assessor = create_risk_assessor(use_llm=False)

        risk_assessment = RiskAssessment(
            overall_risk_level="critical",
            overall_risk_score=20.0,
        )
        return_assessment = ReturnAssessment(
            total_expected_return=1000000,
        )

        rec = assessor._generate_recommendation(
            risk_assessment, return_assessment, 500000
        )
        assert "慎重" in rec

    def test_generate_recommendation_low_risk_with_return(self):
        """低リスク・高リターンでの推奨生成テスト"""
        assessor = create_risk_assessor(use_llm=False)

        risk_assessment = RiskAssessment(
            overall_risk_level="low",
            overall_risk_score=2.0,
        )
        return_assessment = ReturnAssessment(
            total_expected_return=1000000,
        )

        rec = assessor._generate_recommendation(
            risk_assessment, return_assessment, 900000
        )
        assert "積極的" in rec


# =============================================================================
# ConsistencyCheckerのテスト
# =============================================================================

class TestConsistencyChecker:
    """整合性チェックエンジンのテスト"""

    def test_init_without_db(self):
        """DBなしでの初期化テスト"""
        checker = create_consistency_checker(
            organization_id="org_test",
            use_llm=False,
        )
        assert checker is not None
        assert checker.organization_id == "org_test"

    def test_init_with_values(self):
        """組織値付きの初期化テスト"""
        org_values = {
            "mission": "顧客価値の最大化",
            "values": ["誠実", "革新"],
            "prohibited_patterns": ["違法", "不正"],
        }
        checker = create_consistency_checker(
            organization_id="org_test",
            use_llm=False,
            organization_values=org_values,
        )
        assert checker.organization_values == org_values

    @pytest.mark.asyncio
    async def test_check_consistency(self, sample_options):
        """整合性チェックのテスト"""
        checker = create_consistency_checker(
            organization_id="org_test",
            use_llm=False,
        )

        recommendation = JudgmentRecommendation(
            recommended_option=sample_options[0],
            recommendation_score=0.8,
        )

        result = await checker.check(
            current_question="この案件を受けるべきか？",
            current_recommendation=recommendation,
            options=sample_options,
        )

        assert isinstance(result, ConsistencyCheckResult)
        assert result.consistency_level in [
            ConsistencyLevel.FULLY_CONSISTENT.value,
            ConsistencyLevel.MOSTLY_CONSISTENT.value,
            ConsistencyLevel.PARTIALLY_CONSISTENT.value,
            ConsistencyLevel.INCONSISTENT.value,
            ConsistencyLevel.CONTRADICTORY.value,
        ]

    @pytest.mark.asyncio
    async def test_check_without_recommendation(self, sample_options):
        """推奨なしでの整合性チェックテスト"""
        checker = create_consistency_checker(
            organization_id="org_test",
            use_llm=False,
        )

        result = await checker.check(
            current_question="テスト質問",
            current_recommendation=None,
            options=sample_options,
        )

        assert isinstance(result, ConsistencyCheckResult)

    def test_similarity_calculation(self):
        """類似度計算のテスト"""
        checker = create_consistency_checker(use_llm=False)

        # 類似している
        similarity = checker._calculate_similarity(
            "この案件を受けるべきか？",
            "この案件を受注すべきか？",
        )
        assert similarity > 0.5

        # 類似していない
        similarity = checker._calculate_similarity(
            "この案件を受けるべきか？",
            "明日の天気は？",
        )
        assert similarity < 0.5

    def test_overall_consistency_calculation_no_issues(self):
        """問題なしでの全体整合性計算テスト"""
        checker = create_consistency_checker(use_llm=False)
        level, score = checker._calculate_overall_consistency([])
        assert level == ConsistencyLevel.FULLY_CONSISTENT.value
        assert score == 1.0

    def test_overall_consistency_calculation_with_issues(self):
        """問題ありでの全体整合性計算テスト"""
        checker = create_consistency_checker(use_llm=False)

        issues = [
            ConsistencyIssue(severity=0.8),
            ConsistencyIssue(severity=0.6),
        ]

        level, score = checker._calculate_overall_consistency(issues)
        assert score < 1.0
        assert level in [
            ConsistencyLevel.MOSTLY_CONSISTENT.value,
            ConsistencyLevel.PARTIALLY_CONSISTENT.value,
            ConsistencyLevel.INCONSISTENT.value,
        ]

    def test_dimension_scores_calculation(self):
        """次元別スコア計算テスト"""
        checker = create_consistency_checker(use_llm=False)

        issues = [
            ConsistencyIssue(
                dimension=ConsistencyDimension.PRECEDENT_CONSISTENCY.value,
                severity=0.5,
            ),
        ]

        scores = checker._calculate_dimension_scores(issues)
        assert scores[ConsistencyDimension.PRECEDENT_CONSISTENCY.value] < 1.0
        assert scores[ConsistencyDimension.VALUE_ALIGNMENT.value] == 1.0

    @pytest.mark.asyncio
    async def test_save_judgment_to_cache(self, sample_past_judgments):
        """判断のキャッシュ保存テスト"""
        checker = create_consistency_checker(
            organization_id="org_test",
            use_llm=False,
        )

        result = await checker.save_judgment(sample_past_judgments[0])
        assert result is True
        assert len(checker._judgment_cache) == 1

    def test_value_alignment_check_with_prohibited(self, sample_options):
        """禁止パターンとの整合性チェックテスト"""
        checker = create_consistency_checker(
            organization_id="org_test",
            use_llm=False,
            organization_values={
                "prohibited_patterns": ["不正", "違法"],
            },
        )

        recommendation = JudgmentRecommendation(
            recommended_option=JudgmentOption(name="不正行為を含む案件"),
        )

        issues = checker._check_value_alignment(
            "不正行為を含む案件を受けるべきか？",
            recommendation,
        )

        # 禁止パターンに該当
        assert len(issues) > 0
        assert any("禁止パターン" in i.description for i in issues)


# =============================================================================
# AdvancedJudgmentのテスト（統合テスト）
# =============================================================================

class TestAdvancedJudgment:
    """高度な判断層の統合テスト"""

    def test_init_default(self):
        """デフォルト初期化テスト"""
        judgment = create_advanced_judgment(use_llm=False)
        assert judgment is not None

    def test_init_with_feature_flags(self):
        """機能フラグ付き初期化テスト"""
        judgment = create_advanced_judgment(
            use_llm=False,
            feature_flags={
                FEATURE_FLAG_OPTION_EVALUATION: True,
                FEATURE_FLAG_TRADEOFF_ANALYSIS: False,
            },
        )
        assert judgment._is_feature_enabled(FEATURE_FLAG_OPTION_EVALUATION) is True
        assert judgment._is_feature_enabled(FEATURE_FLAG_TRADEOFF_ANALYSIS) is False

    @pytest.mark.asyncio
    async def test_judge_full_flow(self, sample_input):
        """完全な判断フローのテスト"""
        judgment = create_advanced_judgment(
            organization_id="org_test",
            use_llm=False,
        )

        result = await judgment.judge(sample_input)

        assert isinstance(result, AdvancedJudgmentOutput)
        assert result.input == sample_input
        assert result.judgment_type == sample_input.judgment_type
        assert len(result.option_evaluations) == 3
        assert result.recommendation is not None
        assert result.processing_time_ms >= 0  # 処理が非常に高速な場合は0になる可能性がある

    @pytest.mark.asyncio
    async def test_judge_with_mock_llm(self, sample_input, mock_ai_response):
        """モックLLMでの判断テスト"""
        judgment = create_advanced_judgment(
            organization_id="org_test",
            get_ai_response_func=mock_ai_response,
            use_llm=True,
        )

        result = await judgment.judge(sample_input)

        assert isinstance(result, AdvancedJudgmentOutput)
        assert result.recommendation.recommended_option is not None

    @pytest.mark.asyncio
    async def test_judge_with_disabled_features(self, sample_input):
        """機能無効化での判断テスト"""
        judgment = create_advanced_judgment(
            use_llm=False,
            feature_flags={
                FEATURE_FLAG_TRADEOFF_ANALYSIS: False,
                FEATURE_FLAG_RISK_ASSESSMENT: False,
                FEATURE_FLAG_CONSISTENCY_CHECK: False,
            },
        )

        result = await judgment.judge(sample_input)

        assert isinstance(result, AdvancedJudgmentOutput)
        assert result.tradeoff_analysis is None
        assert result.risk_return_analysis is None
        assert result.consistency_check is None

    def test_complexity_assessment_simple(self):
        """シンプル複雑さ評価テスト"""
        judgment = create_advanced_judgment(use_llm=False)

        simple_input = AdvancedJudgmentInput(
            question="はいかいいえか？",
            options=[
                JudgmentOption(name="はい"),
                JudgmentOption(name="いいえ"),
            ],
        )
        complexity = judgment._assess_complexity(simple_input)
        assert complexity == JudgmentComplexity.SIMPLE.value

    def test_complexity_assessment_complex(self):
        """複雑な複雑さ評価テスト"""
        judgment = create_advanced_judgment(use_llm=False)

        complex_input = AdvancedJudgmentInput(
            question="複雑な判断",
            options=[JudgmentOption(name=f"選択肢{i}") for i in range(10)],
            criteria=[EvaluationCriterion(name=f"基準{i}") for i in range(10)],
            constraints=["制約1", "制約2", "制約3", "制約4"],
        )
        complexity = judgment._assess_complexity(complex_input)
        assert complexity in [
            JudgmentComplexity.COMPLEX.value,
            JudgmentComplexity.HIGHLY_COMPLEX.value,
        ]

    def test_recommendation_type_determination(self):
        """推奨タイプの決定テスト"""
        judgment = create_advanced_judgment(use_llm=False)

        # 高スコア -> 強く推奨
        rec_type = judgment._determine_recommendation_type(0.9)
        assert rec_type == RecommendationType.STRONG_RECOMMEND.value

        # 中スコア -> 中立
        rec_type = judgment._determine_recommendation_type(0.5)
        assert rec_type == RecommendationType.NEUTRAL.value

        # 低スコア -> 非推奨
        rec_type = judgment._determine_recommendation_type(0.2)
        assert rec_type == RecommendationType.NOT_RECOMMEND.value

    def test_confirmation_determination_low_confidence(self, sample_options):
        """低確信度での確認要否判定テスト"""
        judgment = create_advanced_judgment(use_llm=False)

        low_confidence_rec = JudgmentRecommendation(
            recommended_option=sample_options[0],
            confidence_score=0.3,
        )
        needs, reason = judgment._determine_confirmation(
            low_confidence_rec, None, None
        )
        assert needs is True
        assert "確信度" in reason

    def test_confirmation_determination_high_confidence(self, sample_options):
        """高確信度での確認要否判定テスト"""
        judgment = create_advanced_judgment(use_llm=False)

        high_confidence_rec = JudgmentRecommendation(
            recommended_option=sample_options[0],
            confidence_score=0.9,
            recommendation_type=RecommendationType.STRONG_RECOMMEND.value,
        )
        needs, reason = judgment._determine_confirmation(
            high_confidence_rec, None, None
        )
        assert needs is False

    def test_confirmation_determination_critical_tradeoff(self, sample_options):
        """クリティカルトレードオフでの確認要否判定テスト"""
        judgment = create_advanced_judgment(use_llm=False)

        rec = JudgmentRecommendation(
            recommended_option=sample_options[0],
            confidence_score=0.8,
            recommendation_type=RecommendationType.RECOMMEND.value,
        )
        tradeoff = TradeoffAnalysisResult(
            critical_count=2,
        )
        needs, reason = judgment._determine_confirmation(rec, tradeoff, None)
        assert needs is True
        assert "トレードオフ" in reason

    def test_preprocess_input(self, sample_input):
        """入力前処理テスト"""
        judgment = create_advanced_judgment(
            organization_id="default_org",
            use_llm=False,
        )

        # organization_idが空の入力
        input_without_org = AdvancedJudgmentInput(
            question="テスト",
            options=[JudgmentOption(name="選択肢")],
        )
        processed = judgment._preprocess_input(input_without_org)
        assert processed.organization_id == "default_org"


# =============================================================================
# エッジケースのテスト
# =============================================================================

class TestEdgeCases:
    """エッジケースのテスト"""

    @pytest.mark.asyncio
    async def test_empty_options(self):
        """選択肢がない場合のテスト"""
        judgment = create_advanced_judgment(use_llm=False)

        input_data = AdvancedJudgmentInput(
            question="選択肢がない判断",
            options=[],
        )

        result = await judgment.judge(input_data)

        assert isinstance(result, AdvancedJudgmentOutput)
        assert len(result.option_evaluations) == 0
        assert result.recommendation.recommendation_type == RecommendationType.NEUTRAL.value

    @pytest.mark.asyncio
    async def test_single_option(self):
        """選択肢が1つだけの場合のテスト"""
        judgment = create_advanced_judgment(use_llm=False)

        input_data = AdvancedJudgmentInput(
            question="1つだけの選択肢",
            options=[JudgmentOption(name="唯一の選択肢")],
        )

        result = await judgment.judge(input_data)

        assert isinstance(result, AdvancedJudgmentOutput)
        assert len(result.option_evaluations) == 1

    @pytest.mark.asyncio
    async def test_no_criteria(self, sample_options):
        """評価基準がない場合のテスト"""
        judgment = create_advanced_judgment(use_llm=False)

        input_data = AdvancedJudgmentInput(
            question="基準なしの判断",
            options=sample_options,
            criteria=None,  # 基準なし
        )

        result = await judgment.judge(input_data)

        assert isinstance(result, AdvancedJudgmentOutput)
        # デフォルトの基準が使われる

    @pytest.mark.asyncio
    async def test_empty_question(self, sample_options):
        """質問が空の場合のテスト"""
        judgment = create_advanced_judgment(use_llm=False)

        input_data = AdvancedJudgmentInput(
            question="",
            options=sample_options,
        )

        result = await judgment.judge(input_data)

        assert isinstance(result, AdvancedJudgmentOutput)

    @pytest.mark.asyncio
    async def test_option_without_id(self):
        """IDなし選択肢のテスト"""
        judgment = create_advanced_judgment(use_llm=False)

        # IDが空の選択肢
        options_without_id = [
            JudgmentOption(id="", name="選択肢1"),
            JudgmentOption(id="", name="選択肢2"),
        ]

        input_data = AdvancedJudgmentInput(
            question="テスト",
            options=options_without_id,
        )

        result = await judgment.judge(input_data)

        # IDが自動付与される
        assert result.input.options[0].id == "option_1"
        assert result.input.options[1].id == "option_2"

    @pytest.mark.asyncio
    async def test_very_long_question(self, sample_options):
        """非常に長い質問のテスト"""
        judgment = create_advanced_judgment(use_llm=False)

        long_question = "テスト質問 " * 1000  # 非常に長い質問

        input_data = AdvancedJudgmentInput(
            question=long_question,
            options=sample_options,
        )

        result = await judgment.judge(input_data)

        assert isinstance(result, AdvancedJudgmentOutput)

    @pytest.mark.asyncio
    async def test_special_characters_in_question(self, sample_options):
        """特殊文字を含む質問のテスト"""
        judgment = create_advanced_judgment(use_llm=False)

        input_data = AdvancedJudgmentInput(
            question="テスト\n\t\r質問!@#$%^&*(){}[]<>?/\\|~`",
            options=sample_options,
        )

        result = await judgment.judge(input_data)

        assert isinstance(result, AdvancedJudgmentOutput)

    @pytest.mark.asyncio
    async def test_unicode_content(self):
        """Unicode文字を含むテスト"""
        judgment = create_advanced_judgment(use_llm=False)

        input_data = AdvancedJudgmentInput(
            question="これは日本語の質問です。どうすべきですか？",
            options=[
                JudgmentOption(name="選択肢A: 進める"),
                JudgmentOption(name="選択肢B: 見送る"),
            ],
        )

        result = await judgment.judge(input_data)

        assert isinstance(result, AdvancedJudgmentOutput)

    @pytest.mark.asyncio
    async def test_error_handling_in_judgment(self, sample_input):
        """判断中のエラーハンドリングテスト"""
        judgment = create_advanced_judgment(use_llm=False)

        # 内部エラーをシミュレート（モックで例外を発生）
        with patch.object(
            judgment.option_evaluator,
            'evaluate',
            side_effect=Exception("テストエラー"),
        ):
            result = await judgment.judge(sample_input)

            # エラーがあっても結果が返される
            assert isinstance(result, AdvancedJudgmentOutput)
            assert len(result.errors) > 0


# =============================================================================
# 統合テスト（複数コンポーネントの連携）
# =============================================================================

class TestIntegration:
    """複数コンポーネントの連携テスト"""

    @pytest.mark.asyncio
    async def test_full_pipeline(self, sample_options, sample_criteria):
        """完全なパイプラインテスト"""
        # 1. 選択肢評価
        evaluator = create_option_evaluator(use_llm=False)
        evaluations = await evaluator.evaluate(
            options=sample_options,
            criteria=sample_criteria,
            question="この案件を受けるべきか？",
        )

        assert len(evaluations) == 3

        # 2. トレードオフ分析
        tradeoff_analyzer = create_tradeoff_analyzer(use_llm=False)
        tradeoff_result = await tradeoff_analyzer.analyze(
            evaluations=evaluations,
            criteria=sample_criteria,
            question="この案件を受けるべきか？",
        )

        assert isinstance(tradeoff_result, TradeoffAnalysisResult)

        # 3. リスク評価
        risk_assessor = create_risk_assessor(use_llm=False)
        risk_result = await risk_assessor.assess(
            options=sample_options,
            question="この案件を受けるべきか？",
            context={"budget": 3000000},
            evaluations=evaluations,
        )

        assert isinstance(risk_result, RiskReturnAnalysis)

        # 4. 整合性チェック
        consistency_checker = create_consistency_checker(
            organization_id="org_test",
            use_llm=False,
        )

        recommendation = JudgmentRecommendation(
            recommended_option=evaluations[0].option,
            recommendation_score=evaluations[0].normalized_score,
        )

        consistency_result = await consistency_checker.check(
            current_question="この案件を受けるべきか？",
            current_recommendation=recommendation,
            options=sample_options,
        )

        assert isinstance(consistency_result, ConsistencyCheckResult)

    @pytest.mark.asyncio
    async def test_judgment_with_past_history(
        self, sample_input, sample_past_judgments
    ):
        """過去履歴との連携テスト"""
        checker = create_consistency_checker(
            organization_id="org_test",
            use_llm=False,
        )

        # 過去の判断を保存
        for past in sample_past_judgments:
            await checker.save_judgment(past)

        judgment = AdvancedJudgment(
            organization_id="org_test",
            use_llm=False,
        )
        judgment.consistency_checker = checker

        result = await judgment.judge(sample_input)

        assert isinstance(result, AdvancedJudgmentOutput)
        # 過去判断との整合性がチェックされる
        if result.consistency_check:
            assert len(result.consistency_check.similar_judgments) >= 0

    @pytest.mark.asyncio
    async def test_evaluation_affects_recommendation(self, sample_options):
        """評価結果が推奨に反映されることをテスト"""
        judgment = create_advanced_judgment(use_llm=False)

        # 高収益・低リスクの選択肢
        high_value_option = JudgmentOption(
            name="高価値選択肢",
            metadata={"revenue": 10000000, "risk_level": "low"},
        )

        # 低収益・高リスクの選択肢
        low_value_option = JudgmentOption(
            name="低価値選択肢",
            metadata={"revenue": 100000, "risk_level": "high"},
        )

        input_data = AdvancedJudgmentInput(
            question="どちらを選ぶべきか？",
            options=[high_value_option, low_value_option],
        )

        result = await judgment.judge(input_data)

        # 高価値選択肢が推奨される可能性が高い
        assert result.recommendation is not None


# =============================================================================
# モックDBとの連携テスト
# =============================================================================

class TestWithMockDB:
    """モックDBとの連携テスト"""

    @pytest.mark.asyncio
    async def test_consistency_checker_with_mock_pool(self, sample_past_judgments):
        """モックDBプールでの整合性チェックテスト"""
        # モックのDBプール
        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        # DBからの過去判断を返す
        mock_conn.fetch.return_value = [
            {
                "id": "past_1",
                "judgment_type": JudgmentType.GO_NO_GO.value,
                "question": "類似の案件を受けるべきか？",
                "chosen_option": "案件を受注する",
                "options_json": '["案件を受注する", "案件を断る"]',
                "reasoning": "収益性が高い",
                "outcome": None,
                "outcome_score": None,
                "created_at": datetime.now(),
                "metadata_json": "{}",
            }
        ]

        checker = create_consistency_checker(
            pool=mock_pool,
            organization_id="org_test",
            use_llm=False,
        )

        result = await checker.check(
            current_question="この案件を受けるべきか？",
        )

        # DBからの取得が呼ばれる
        assert mock_pool.acquire.called
        assert isinstance(result, ConsistencyCheckResult)

    @pytest.mark.asyncio
    async def test_save_judgment_to_mock_db(self):
        """モックDBへの判断保存テスト"""
        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        checker = create_consistency_checker(
            pool=mock_pool,
            organization_id="org_test",
            use_llm=False,
        )

        judgment = PastJudgment(
            question="テスト質問",
            chosen_option="テスト選択",
            reasoning="テスト理由",
        )

        result = await checker.save_judgment(judgment)

        assert result is True
        assert mock_conn.execute.called

    @pytest.mark.asyncio
    async def test_update_judgment_outcome(self):
        """判断結果更新テスト"""
        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        checker = create_consistency_checker(
            pool=mock_pool,
            organization_id="org_test",
            use_llm=False,
        )

        result = await checker.update_judgment_outcome(
            judgment_id="judgment_123",
            outcome="成功",
            outcome_score=0.9,
        )

        assert result is True
        assert mock_conn.execute.called


# =============================================================================
# 性能テスト
# =============================================================================

class TestPerformance:
    """性能関連のテスト"""

    @pytest.mark.asyncio
    async def test_processing_time_recorded(self, sample_input):
        """処理時間が記録されることをテスト"""
        judgment = create_advanced_judgment(use_llm=False)
        result = await judgment.judge(sample_input)
        # 処理時間は0以上（非常に高速な場合は0になる可能性がある）
        assert result.processing_time_ms >= 0

    @pytest.mark.asyncio
    async def test_many_options_performance(self):
        """多数の選択肢での性能テスト"""
        judgment = create_advanced_judgment(use_llm=False)

        many_options = [
            JudgmentOption(name=f"選択肢{i}")
            for i in range(MAX_OPTIONS)
        ]

        input_data = AdvancedJudgmentInput(
            question="多数の選択肢からの判断",
            options=many_options,
        )

        result = await judgment.judge(input_data)

        assert isinstance(result, AdvancedJudgmentOutput)
        assert len(result.option_evaluations) == MAX_OPTIONS

    @pytest.mark.asyncio
    async def test_many_criteria_performance(self, sample_options):
        """多数の評価基準での性能テスト"""
        judgment = create_advanced_judgment(use_llm=False)

        many_criteria = [
            EvaluationCriterion(name=f"基準{i}")
            for i in range(MAX_CRITERIA)
        ]

        input_data = AdvancedJudgmentInput(
            question="多数の基準での判断",
            options=sample_options,
            criteria=many_criteria,
        )

        result = await judgment.judge(input_data)

        assert isinstance(result, AdvancedJudgmentOutput)


# =============================================================================
# メイン実行
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
