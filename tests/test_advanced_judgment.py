# tests/test_advanced_judgment.py
"""
Phase 2J: 判断力強化（Advanced Judgment）- テスト

設計書: docs/17_brain_completion_roadmap.md セクション17.3 Phase 2J

このファイルには、高度な判断層のテストを定義します。

Author: Claude Opus 4.5
Created: 2026-01-27
"""

import pytest
import asyncio
from datetime import datetime
from typing import Dict, Any, List

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
    RecommendationType,
    ConfidenceLevel,
    CRITERION_IMPORTANCE_WEIGHTS,
    SCORE_LEVEL_VALUES,

    # モデル
    JudgmentOption,
    OptionScore,
    OptionEvaluation,
    EvaluationCriterion,
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

    def test_criterion_category_enum(self):
        """CriterionCategory列挙型のテスト"""
        assert CriterionCategory.REVENUE.value == "revenue"
        assert CriterionCategory.RISK.value == "risk"
        assert CriterionCategory.TECHNICAL.value == "technical"

    def test_criterion_importance_weights(self):
        """重要度の重みマッピングのテスト"""
        assert CRITERION_IMPORTANCE_WEIGHTS["critical"] == 1.0
        assert CRITERION_IMPORTANCE_WEIGHTS["high"] == 0.8
        assert CRITERION_IMPORTANCE_WEIGHTS["medium"] == 0.6

    def test_score_level_values(self):
        """スコアレベルの数値マッピングのテスト"""
        assert SCORE_LEVEL_VALUES["excellent"] == 5
        assert SCORE_LEVEL_VALUES["good"] == 4
        assert SCORE_LEVEL_VALUES["acceptable"] == 3

    def test_tradeoff_severity_enum(self):
        """TradeoffSeverity列挙型のテスト"""
        assert TradeoffSeverity.CRITICAL.value == "critical"
        assert TradeoffSeverity.MODERATE.value == "moderate"
        assert TradeoffSeverity.NEGLIGIBLE.value == "negligible"


# =============================================================================
# モデルのテスト
# =============================================================================

class TestModels:
    """データモデルのテスト"""

    def test_judgment_option_creation(self):
        """JudgmentOptionの作成テスト"""
        option = JudgmentOption(
            name="テスト選択肢",
            description="説明",
        )
        assert option.name == "テスト選択肢"
        assert option.description == "説明"
        assert option.id  # IDが自動生成される
        assert option.label == "テスト選択肢"  # ラベルはデフォルトで名前

    def test_evaluation_criterion_weight_calculation(self):
        """EvaluationCriterionの重み計算テスト"""
        criterion = EvaluationCriterion(
            name="テスト基準",
            importance=CriterionImportance.HIGH.value,
        )
        assert criterion.weight == 0.8

    def test_risk_factor_score_calculation(self):
        """RiskFactorのスコア計算テスト"""
        risk = RiskFactor(
            name="テストリスク",
            probability=RiskProbability.LIKELY.value,
            impact=RiskImpact.MAJOR.value,
        )
        score = risk.calculate_risk_score()
        assert score > 0
        assert risk.risk_level in ["low", "medium", "high", "critical"]

    def test_return_factor_adjusted_value(self):
        """ReturnFactorの調整後期待値テスト"""
        ret = ReturnFactor(
            name="テストリターン",
            expected_value=1000000,
            certainty=ReturnCertainty.EXPECTED.value,
        )
        adjusted = ret.calculate_adjusted_value()
        assert adjusted == 1000000 * 0.7  # EXPECTED = 0.7

    def test_tradeoff_natural_language(self):
        """Tradeoffの自然言語表現テスト"""
        tradeoff = Tradeoff(
            factor_a=TradeoffFactor(name="コスト削減"),
            factor_b=TradeoffFactor(name="品質"),
            severity=TradeoffSeverity.MODERATE.value,
        )
        text = tradeoff.to_natural_language()
        assert "コスト削減" in text
        assert "品質" in text
        assert "犠牲" in text


# =============================================================================
# OptionEvaluatorのテスト
# =============================================================================

class TestOptionEvaluator:
    """選択肢評価エンジンのテスト"""

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

    def test_get_default_criteria(self):
        """デフォルト評価基準の取得テスト"""
        evaluator = create_option_evaluator(use_llm=False)

        # プロジェクト用
        criteria = evaluator._get_default_criteria(JudgmentType.GO_NO_GO.value)
        assert len(criteria) > 0

        # 採用用
        criteria = evaluator._get_default_criteria(JudgmentType.CANDIDATE_EVALUATION.value)
        assert len(criteria) > 0

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


# =============================================================================
# TradeoffAnalyzerのテスト
# =============================================================================

class TestTradeoffAnalyzer:
    """トレードオフ分析エンジンのテスト"""

    @pytest.mark.asyncio
    async def test_analyze_tradeoffs(self, sample_options, sample_criteria):
        """トレードオフ分析のテスト"""
        analyzer = create_tradeoff_analyzer(use_llm=False)

        # 評価結果を作成
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
        # リスクと収益のトレードオフが検出される可能性

    def test_tradeoff_severity_calculation(self):
        """トレードオフ深刻度の計算テスト"""
        analyzer = create_tradeoff_analyzer(use_llm=False)

        # 大きな差
        severity = analyzer._calculate_tradeoff_severity(5, 1)
        assert severity == TradeoffSeverity.CRITICAL.value

        # 小さな差
        severity = analyzer._calculate_tradeoff_severity(4, 3)
        assert severity == TradeoffSeverity.NEGLIGIBLE.value


# =============================================================================
# RiskAssessorのテスト
# =============================================================================

class TestRiskAssessor:
    """リスク評価エンジンのテスト"""

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


# =============================================================================
# ConsistencyCheckerのテスト
# =============================================================================

class TestConsistencyChecker:
    """整合性チェックエンジンのテスト"""

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

    def test_similarity_calculation(self):
        """類似度計算のテスト"""
        checker = create_consistency_checker(use_llm=False)

        similarity = checker._calculate_similarity(
            "この案件を受けるべきか？",
            "この案件を受注すべきか？",
        )
        assert similarity > 0.5  # 類似している

        similarity = checker._calculate_similarity(
            "この案件を受けるべきか？",
            "明日の天気は？",
        )
        assert similarity < 0.5  # 類似していない


# =============================================================================
# AdvancedJudgmentのテスト（統合テスト）
# =============================================================================

class TestAdvancedJudgment:
    """高度な判断層の統合テスト"""

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
        assert result.processing_time_ms >= 0  # テスト環境では高速処理のため0msも許容

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

    def test_complexity_assessment(self, sample_input):
        """複雑さ評価のテスト"""
        judgment = create_advanced_judgment(use_llm=False)

        # シンプル: 2選択肢
        simple_input = AdvancedJudgmentInput(
            question="はいかいいえか？",
            options=[
                JudgmentOption(name="はい"),
                JudgmentOption(name="いいえ"),
            ],
        )
        complexity = judgment._assess_complexity(simple_input)
        assert complexity == JudgmentComplexity.SIMPLE.value

        # 複雑: 多数の選択肢と基準
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

    def test_confirmation_determination(self, sample_options):
        """確認要否の判定テスト"""
        judgment = create_advanced_judgment(use_llm=False)

        # 確信度が低い場合は確認必要
        low_confidence_rec = JudgmentRecommendation(
            recommended_option=sample_options[0],
            confidence_score=0.3,
        )
        needs, reason = judgment._determine_confirmation(
            low_confidence_rec, None, None
        )
        assert needs is True

        # 確信度が高い場合は確認不要
        high_confidence_rec = JudgmentRecommendation(
            recommended_option=sample_options[0],
            confidence_score=0.9,
            recommendation_type=RecommendationType.STRONG_RECOMMEND.value,
        )
        needs, reason = judgment._determine_confirmation(
            high_confidence_rec, None, None
        )
        assert needs is False


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


# =============================================================================
# メイン実行
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
