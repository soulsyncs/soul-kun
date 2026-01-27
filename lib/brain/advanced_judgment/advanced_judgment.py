# lib/brain/advanced_judgment/advanced_judgment.py
"""
Phase 2J: 判断力強化（Advanced Judgment）- 統合クラス

設計書: docs/17_brain_completion_roadmap.md セクション17.3 Phase 2J

このファイルには、高度な判断層の全コンポーネントを統合するメインクラスを定義します。

【Phase 2J の能力】
- 複数選択肢の比較評価
- トレードオフの明示化（「Aを取ればBを犠牲に」）
- リスク・リターンの定量評価
- 過去の判断との整合性チェック

【統合フロー】
1. 入力の検証と前処理
2. 選択肢の評価（OptionEvaluator）
3. トレードオフ分析（TradeoffAnalyzer）
4. リスク・リターン評価（RiskAssessor）
5. 整合性チェック（ConsistencyChecker）
6. 総合的な推奨の生成
7. ログ記録と結果の返却

Author: Claude Opus 4.5
Created: 2026-01-27
"""

import logging
import time
import json
from typing import Optional, List, Dict, Any, Callable

from .constants import (
    JudgmentType,
    JudgmentComplexity,
    RecommendationType,
    ConfidenceLevel,
    RECOMMENDATION_SCORE_RANGES,
    CONFIDENCE_LEVEL_RANGES,
    FEATURE_FLAG_ADVANCED_JUDGMENT,
    FEATURE_FLAG_OPTION_EVALUATION,
    FEATURE_FLAG_TRADEOFF_ANALYSIS,
    FEATURE_FLAG_RISK_ASSESSMENT,
    FEATURE_FLAG_CONSISTENCY_CHECK,
)
from .models import (
    JudgmentOption,
    OptionEvaluation,
    EvaluationCriterion,
    TradeoffAnalysisResult,
    RiskReturnAnalysis,
    ConsistencyCheckResult,
    JudgmentRecommendation,
    AdvancedJudgmentInput,
    AdvancedJudgmentOutput,
    PastJudgment,
)
from .option_evaluator import OptionEvaluator, create_option_evaluator
from .tradeoff_analyzer import TradeoffAnalyzer, create_tradeoff_analyzer
from .risk_assessor import RiskAssessor, create_risk_assessor
from .consistency_checker import ConsistencyChecker, create_consistency_checker


logger = logging.getLogger(__name__)


# =============================================================================
# 高度な判断層 統合クラス
# =============================================================================

class AdvancedJudgment:
    """
    高度な判断層 統合クラス

    複数の分析コンポーネントを統合し、多角的な判断支援を提供する。

    使用例:
        judgment = AdvancedJudgment(
            pool=db_pool,
            organization_id="org_001",
            get_ai_response_func=get_ai_response,
        )

        result = await judgment.judge(
            AdvancedJudgmentInput(
                question="この案件を受けるべきか？",
                options=[option1, option2, option3],
                criteria=[criterion1, criterion2],
                context={"budget": 1000000},
            )
        )
    """

    def __init__(
        self,
        pool: Optional[Any] = None,
        organization_id: str = "",
        get_ai_response_func: Optional[Callable] = None,
        use_llm: bool = True,
        organization_values: Optional[Dict[str, Any]] = None,
        feature_flags: Optional[Dict[str, bool]] = None,
    ):
        """
        Args:
            pool: データベース接続プール
            organization_id: 組織ID
            get_ai_response_func: AI応答生成関数
            use_llm: LLMを使用するか
            organization_values: 組織の価値観・方針
            feature_flags: 機能フラグ
        """
        self.pool = pool
        self.organization_id = organization_id
        self.get_ai_response = get_ai_response_func
        self.use_llm = use_llm
        self.organization_values = organization_values or {}
        self.feature_flags = feature_flags or {}

        # コンポーネントの初期化
        self._init_components()

        logger.info(
            f"AdvancedJudgment initialized: "
            f"org_id={organization_id}, use_llm={use_llm}"
        )

    def _init_components(self):
        """コンポーネントを初期化"""
        # 選択肢評価エンジン
        self.option_evaluator = create_option_evaluator(
            get_ai_response_func=self.get_ai_response,
            use_llm=self.use_llm,
        )

        # トレードオフ分析エンジン
        self.tradeoff_analyzer = create_tradeoff_analyzer(
            get_ai_response_func=self.get_ai_response,
            use_llm=self.use_llm,
        )

        # リスク評価エンジン
        self.risk_assessor = create_risk_assessor(
            get_ai_response_func=self.get_ai_response,
            use_llm=self.use_llm,
        )

        # 整合性チェックエンジン
        self.consistency_checker = create_consistency_checker(
            pool=self.pool,
            organization_id=self.organization_id,
            get_ai_response_func=self.get_ai_response,
            use_llm=self.use_llm,
            organization_values=self.organization_values,
        )

    # =========================================================================
    # メイン判断メソッド
    # =========================================================================

    async def judge(
        self,
        input_data: AdvancedJudgmentInput,
    ) -> AdvancedJudgmentOutput:
        """
        高度な判断を実行

        Args:
            input_data: 判断への入力

        Returns:
            AdvancedJudgmentOutput: 判断結果
        """
        start_time = time.time()

        logger.info(
            f"Starting advanced judgment: "
            f"question='{input_data.question[:50]}...', "
            f"options={len(input_data.options)}"
        )

        try:
            # 1. 入力の検証と前処理
            input_data = self._preprocess_input(input_data)

            # 2. 判断の複雑さを評価
            complexity = self._assess_complexity(input_data)

            # 3. 選択肢の評価
            option_evaluations = await self._evaluate_options(input_data)

            # 4. トレードオフ分析
            tradeoff_analysis = await self._analyze_tradeoffs(
                option_evaluations, input_data
            )

            # 5. リスク・リターン評価
            risk_return_analysis = await self._assess_risk_return(
                input_data, option_evaluations
            )

            # 6. 整合性チェック
            consistency_check = await self._check_consistency(
                input_data, option_evaluations
            )

            # 7. 総合的な推奨を生成
            recommendation = self._generate_recommendation(
                option_evaluations,
                tradeoff_analysis,
                risk_return_analysis,
                consistency_check,
                input_data,
            )

            # 8. 確認が必要かどうかを判定
            needs_confirmation, confirmation_reason = self._determine_confirmation(
                recommendation, tradeoff_analysis, consistency_check
            )

            # 9. サマリーとレポートを生成
            summary = self._generate_summary(
                recommendation,
                option_evaluations,
                tradeoff_analysis,
                risk_return_analysis,
                consistency_check,
            )
            detailed_report = self._generate_detailed_report(
                input_data,
                option_evaluations,
                tradeoff_analysis,
                risk_return_analysis,
                consistency_check,
                recommendation,
            )

            # 10. 全体の信頼度を計算
            overall_confidence = self._calculate_overall_confidence(
                option_evaluations,
                tradeoff_analysis,
                risk_return_analysis,
                consistency_check,
            )

            elapsed_ms = int((time.time() - start_time) * 1000)

            output = AdvancedJudgmentOutput(
                input=input_data,
                judgment_type=input_data.judgment_type,
                complexity=complexity,
                option_evaluations=option_evaluations,
                tradeoff_analysis=tradeoff_analysis,
                risk_return_analysis=risk_return_analysis,
                consistency_check=consistency_check,
                recommendation=recommendation,
                criteria_used=input_data.criteria or [],
                summary=summary,
                detailed_report=detailed_report,
                overall_confidence=overall_confidence,
                needs_confirmation=needs_confirmation,
                confirmation_reason=confirmation_reason,
                warnings=[],
                errors=[],
                processing_time_ms=elapsed_ms,
            )

            # 11. ログ記録
            await self._log_judgment(output)

            logger.info(
                f"Advanced judgment completed in {elapsed_ms}ms: "
                f"recommendation={recommendation.recommendation_type}, "
                f"confidence={overall_confidence:.2f}"
            )

            return output

        except Exception as e:
            logger.error(f"Advanced judgment error: {e}", exc_info=True)

            elapsed_ms = int((time.time() - start_time) * 1000)

            return AdvancedJudgmentOutput(
                input=input_data,
                judgment_type=input_data.judgment_type,
                complexity=JudgmentComplexity.MODERATE.value,
                errors=[str(e)],
                processing_time_ms=elapsed_ms,
            )

    # =========================================================================
    # 入力の前処理
    # =========================================================================

    def _preprocess_input(
        self,
        input_data: AdvancedJudgmentInput,
    ) -> AdvancedJudgmentInput:
        """入力を前処理"""
        # 組織IDの設定
        if not input_data.organization_id:
            input_data.organization_id = self.organization_id

        # 選択肢がない場合は空のリストを設定
        if not input_data.options:
            input_data.options = []

        # 選択肢にIDを付与
        for i, option in enumerate(input_data.options):
            if not option.id:
                option.id = f"option_{i+1}"

        return input_data

    def _assess_complexity(
        self,
        input_data: AdvancedJudgmentInput,
    ) -> str:
        """判断の複雑さを評価"""
        option_count = len(input_data.options)
        criteria_count = len(input_data.criteria) if input_data.criteria else 0
        constraint_count = len(input_data.constraints)

        # 複雑さの基準
        complexity_score = 0

        # 選択肢の数
        if option_count <= 2:
            complexity_score += 1
        elif option_count <= 5:
            complexity_score += 2
        else:
            complexity_score += 3

        # 評価基準の数
        if criteria_count > 5:
            complexity_score += 1

        # 制約条件の数
        if constraint_count > 3:
            complexity_score += 1

        # 複雑さレベルを決定
        if complexity_score <= 2:
            return JudgmentComplexity.SIMPLE.value
        elif complexity_score <= 3:
            return JudgmentComplexity.MODERATE.value
        elif complexity_score <= 4:
            return JudgmentComplexity.COMPLEX.value
        else:
            return JudgmentComplexity.HIGHLY_COMPLEX.value

    # =========================================================================
    # 各コンポーネントの呼び出し
    # =========================================================================

    async def _evaluate_options(
        self,
        input_data: AdvancedJudgmentInput,
    ) -> List[OptionEvaluation]:
        """選択肢を評価"""
        if not self._is_feature_enabled(FEATURE_FLAG_OPTION_EVALUATION):
            return []

        if not input_data.options:
            return []

        return await self.option_evaluator.evaluate(
            options=input_data.options,
            criteria=input_data.criteria,
            question=input_data.question,
            judgment_type=input_data.judgment_type,
            context=input_data.context,
        )

    async def _analyze_tradeoffs(
        self,
        evaluations: List[OptionEvaluation],
        input_data: AdvancedJudgmentInput,
    ) -> Optional[TradeoffAnalysisResult]:
        """トレードオフを分析"""
        if not self._is_feature_enabled(FEATURE_FLAG_TRADEOFF_ANALYSIS):
            return None

        if not evaluations:
            return None

        criteria = input_data.criteria or []

        return await self.tradeoff_analyzer.analyze(
            evaluations=evaluations,
            criteria=criteria,
            question=input_data.question,
            context=input_data.context,
        )

    async def _assess_risk_return(
        self,
        input_data: AdvancedJudgmentInput,
        evaluations: List[OptionEvaluation],
    ) -> Optional[RiskReturnAnalysis]:
        """リスク・リターンを評価"""
        if not self._is_feature_enabled(FEATURE_FLAG_RISK_ASSESSMENT):
            return None

        return await self.risk_assessor.assess(
            options=input_data.options,
            question=input_data.question,
            context=input_data.context,
            evaluations=evaluations,
        )

    async def _check_consistency(
        self,
        input_data: AdvancedJudgmentInput,
        evaluations: List[OptionEvaluation],
    ) -> Optional[ConsistencyCheckResult]:
        """整合性をチェック"""
        if not self._is_feature_enabled(FEATURE_FLAG_CONSISTENCY_CHECK):
            return None

        # 暫定的な推奨を作成（整合性チェック用）
        temp_recommendation = None
        if evaluations:
            top_eval = evaluations[0]
            temp_recommendation = JudgmentRecommendation(
                recommended_option=top_eval.option,
                recommendation_score=top_eval.normalized_score,
            )

        return await self.consistency_checker.check(
            current_question=input_data.question,
            current_recommendation=temp_recommendation,
            options=input_data.options,
            input_data=input_data,
        )

    # =========================================================================
    # 推奨の生成
    # =========================================================================

    def _generate_recommendation(
        self,
        evaluations: List[OptionEvaluation],
        tradeoff_analysis: Optional[TradeoffAnalysisResult],
        risk_return_analysis: Optional[RiskReturnAnalysis],
        consistency_check: Optional[ConsistencyCheckResult],
        input_data: AdvancedJudgmentInput,
    ) -> JudgmentRecommendation:
        """総合的な推奨を生成"""
        if not evaluations:
            return JudgmentRecommendation(
                recommendation_type=RecommendationType.NEUTRAL.value,
                reasoning="評価対象の選択肢がありません",
            )

        # 最高スコアの選択肢を取得
        top_eval = evaluations[0]
        recommended_option = top_eval.option

        # 基本スコア（選択肢評価から）
        base_score = top_eval.normalized_score

        # 調整係数
        adjustment = 0.0

        # トレードオフによる調整
        if tradeoff_analysis:
            if tradeoff_analysis.critical_count > 0:
                adjustment -= 0.1 * min(tradeoff_analysis.critical_count, 3)

        # リスクによる調整
        if risk_return_analysis:
            risk_level = risk_return_analysis.risk_assessment.overall_risk_level
            risk_adjustments = {
                "low": 0.05,
                "medium": 0.0,
                "high": -0.1,
                "critical": -0.2,
            }
            adjustment += risk_adjustments.get(risk_level, 0.0)

        # 整合性による調整
        if consistency_check:
            consistency_score = consistency_check.consistency_score
            if consistency_score < 0.5:
                adjustment -= (0.5 - consistency_score) * 0.2

        # 最終スコア
        final_score = max(0.0, min(1.0, base_score + adjustment))

        # 推奨タイプを決定
        recommendation_type = self._determine_recommendation_type(final_score)

        # 確信度を決定
        confidence, confidence_score = self._determine_confidence(
            evaluations, tradeoff_analysis, risk_return_analysis, consistency_check
        )

        # 推奨理由を生成
        reasoning = self._build_reasoning(
            top_eval, tradeoff_analysis, risk_return_analysis, consistency_check
        )

        # 自然言語での推奨文
        natural_language = self._generate_natural_language_recommendation(
            recommended_option, recommendation_type, reasoning
        )

        # 条件・注意点
        conditions = self._extract_conditions(
            tradeoff_analysis, risk_return_analysis, consistency_check
        )

        # 代替案
        alternatives = [e.option for e in evaluations[1:4]] if len(evaluations) > 1 else []

        # 次のステップ
        next_steps = self._suggest_next_steps(
            recommendation_type, risk_return_analysis, consistency_check
        )

        return JudgmentRecommendation(
            recommended_option=recommended_option,
            recommendation_type=recommendation_type,
            recommendation_score=final_score,
            confidence=confidence,
            confidence_score=confidence_score,
            reasoning=reasoning,
            natural_language_recommendation=natural_language,
            conditions=conditions,
            alternatives=alternatives,
            next_steps=next_steps,
        )

    def _determine_recommendation_type(
        self,
        score: float,
    ) -> str:
        """スコアから推奨タイプを決定"""
        for rec_type, (min_score, max_score) in RECOMMENDATION_SCORE_RANGES.items():
            if min_score <= score <= max_score:
                return rec_type
        return RecommendationType.NEUTRAL.value

    def _determine_confidence(
        self,
        evaluations: List[OptionEvaluation],
        tradeoff_analysis: Optional[TradeoffAnalysisResult],
        risk_return_analysis: Optional[RiskReturnAnalysis],
        consistency_check: Optional[ConsistencyCheckResult],
    ) -> tuple:
        """確信度を決定"""
        confidences = []

        # 評価の信頼度
        if evaluations:
            confidences.append(evaluations[0].confidence)

        # トレードオフ分析の信頼度
        if tradeoff_analysis:
            confidences.append(tradeoff_analysis.confidence)

        # リスク評価の信頼度
        if risk_return_analysis:
            confidences.append(risk_return_analysis.confidence)

        # 整合性チェックの信頼度
        if consistency_check:
            confidences.append(consistency_check.confidence)

        if not confidences:
            return (ConfidenceLevel.LOW.value, 0.3)

        avg_confidence = sum(confidences) / len(confidences)

        # 確信度レベルを決定
        for level, (min_score, max_score) in CONFIDENCE_LEVEL_RANGES.items():
            if min_score <= avg_confidence <= max_score:
                return (level, avg_confidence)

        return (ConfidenceLevel.MEDIUM.value, avg_confidence)

    def _build_reasoning(
        self,
        top_eval: OptionEvaluation,
        tradeoff_analysis: Optional[TradeoffAnalysisResult],
        risk_return_analysis: Optional[RiskReturnAnalysis],
        consistency_check: Optional[ConsistencyCheckResult],
    ) -> str:
        """推奨理由を構築"""
        parts = []

        # 選択肢評価の理由
        parts.append(
            f"「{top_eval.option.name}」が総合スコア{top_eval.total_score:.2f}で最高評価"
        )

        if top_eval.strengths:
            parts.append(f"強み: {', '.join(top_eval.strengths[:2])}")

        # トレードオフの考慮
        if tradeoff_analysis and tradeoff_analysis.tradeoffs:
            parts.append(
                f"トレードオフ{tradeoff_analysis.total_count}件を考慮"
            )

        # リスクの考慮
        if risk_return_analysis:
            risk_level = risk_return_analysis.risk_assessment.overall_risk_level
            parts.append(f"リスクレベル: {risk_level}")

        # 整合性の考慮
        if consistency_check:
            parts.append(
                f"過去判断との整合性: {consistency_check.consistency_level}"
            )

        return "。".join(parts) + "。"

    def _generate_natural_language_recommendation(
        self,
        option: JudgmentOption,
        recommendation_type: str,
        reasoning: str,
    ) -> str:
        """自然言語での推奨文を生成"""
        type_phrases = {
            RecommendationType.STRONG_RECOMMEND.value: "強く推奨します",
            RecommendationType.RECOMMEND.value: "推奨します",
            RecommendationType.CONDITIONAL_RECOMMEND.value: "条件付きで推奨します",
            RecommendationType.NEUTRAL.value: "どちらとも言えません",
            RecommendationType.CONDITIONAL_NOT_RECOMMEND.value: "条件次第では非推奨です",
            RecommendationType.NOT_RECOMMEND.value: "推奨しません",
            RecommendationType.STRONG_NOT_RECOMMEND.value: "強く推奨しません",
        }

        phrase = type_phrases.get(recommendation_type, "判断が難しいです")

        return f"「{option.name}」を{phrase}。{reasoning}"

    def _extract_conditions(
        self,
        tradeoff_analysis: Optional[TradeoffAnalysisResult],
        risk_return_analysis: Optional[RiskReturnAnalysis],
        consistency_check: Optional[ConsistencyCheckResult],
    ) -> List[str]:
        """条件・注意点を抽出"""
        conditions = []

        # トレードオフからの注意点
        if tradeoff_analysis and tradeoff_analysis.primary_tradeoff:
            t = tradeoff_analysis.primary_tradeoff
            conditions.append(
                f"「{t.factor_a.name}」を取ると「{t.factor_b.name}」が犠牲になります"
            )

        # リスクからの注意点
        if risk_return_analysis:
            for risk in risk_return_analysis.risk_assessment.top_risks[:2]:
                conditions.append(f"リスク: {risk.name}")

        # 整合性からの注意点
        if consistency_check:
            for issue in consistency_check.issues[:2]:
                conditions.append(issue.description)

        return conditions[:5]

    def _suggest_next_steps(
        self,
        recommendation_type: str,
        risk_return_analysis: Optional[RiskReturnAnalysis],
        consistency_check: Optional[ConsistencyCheckResult],
    ) -> List[str]:
        """次のステップを提案"""
        steps = []

        # 推奨タイプに応じたステップ
        if recommendation_type in [
            RecommendationType.STRONG_RECOMMEND.value,
            RecommendationType.RECOMMEND.value,
        ]:
            steps.append("計画を具体化して実行に移してください")
        elif recommendation_type == RecommendationType.CONDITIONAL_RECOMMEND.value:
            steps.append("条件を確認してから実行を検討してください")
        elif recommendation_type in [
            RecommendationType.NOT_RECOMMEND.value,
            RecommendationType.STRONG_NOT_RECOMMEND.value,
        ]:
            steps.append("他の選択肢を検討してください")

        # リスク緩和策
        if risk_return_analysis:
            mitigations = risk_return_analysis.risk_assessment.recommended_mitigations
            for m in mitigations[:2]:
                steps.append(m)

        # 整合性からの推奨
        if consistency_check:
            for rec in consistency_check.recommendations[:2]:
                steps.append(rec)

        return steps[:5]

    # =========================================================================
    # 確認要否の判定
    # =========================================================================

    def _determine_confirmation(
        self,
        recommendation: JudgmentRecommendation,
        tradeoff_analysis: Optional[TradeoffAnalysisResult],
        consistency_check: Optional[ConsistencyCheckResult],
    ) -> tuple:
        """確認が必要かどうかを判定"""
        needs_confirmation = False
        reasons = []

        # 確信度が低い場合
        if recommendation.confidence_score < 0.5:
            needs_confirmation = True
            reasons.append("判断の確信度が低いため")

        # 重大なトレードオフがある場合
        if tradeoff_analysis and tradeoff_analysis.critical_count > 0:
            needs_confirmation = True
            reasons.append("重大なトレードオフがあるため")

        # 整合性に問題がある場合
        if consistency_check and consistency_check.consistency_score < 0.5:
            needs_confirmation = True
            reasons.append("過去の判断との整合性に問題があるため")

        # 推奨が中立の場合
        if recommendation.recommendation_type == RecommendationType.NEUTRAL.value:
            needs_confirmation = True
            reasons.append("どちらとも言えないため")

        confirmation_reason = "、".join(reasons) if reasons else None

        return (needs_confirmation, confirmation_reason)

    # =========================================================================
    # サマリーとレポート
    # =========================================================================

    def _generate_summary(
        self,
        recommendation: JudgmentRecommendation,
        evaluations: List[OptionEvaluation],
        tradeoff_analysis: Optional[TradeoffAnalysisResult],
        risk_return_analysis: Optional[RiskReturnAnalysis],
        consistency_check: Optional[ConsistencyCheckResult],
    ) -> str:
        """サマリーを生成"""
        parts = []

        # 推奨
        if recommendation.recommended_option:
            parts.append(recommendation.natural_language_recommendation)

        # トレードオフ
        if tradeoff_analysis and tradeoff_analysis.total_count > 0:
            parts.append(
                f"トレードオフ: {tradeoff_analysis.total_count}件検出"
            )

        # リスク
        if risk_return_analysis:
            parts.append(
                f"リスク: {risk_return_analysis.risk_assessment.overall_risk_level}"
            )

        return " ".join(parts)

    def _generate_detailed_report(
        self,
        input_data: AdvancedJudgmentInput,
        evaluations: List[OptionEvaluation],
        tradeoff_analysis: Optional[TradeoffAnalysisResult],
        risk_return_analysis: Optional[RiskReturnAnalysis],
        consistency_check: Optional[ConsistencyCheckResult],
        recommendation: JudgmentRecommendation,
    ) -> str:
        """詳細レポートを生成"""
        lines = ["# 判断分析レポート", ""]

        # 課題
        lines.append(f"## 判断課題")
        lines.append(f"{input_data.question}")
        lines.append("")

        # 選択肢評価
        lines.append("## 選択肢評価")
        for eval_result in evaluations:
            lines.append(f"### {eval_result.option.name}")
            lines.append(f"- 総合スコア: {eval_result.total_score:.2f}")
            lines.append(f"- 順位: {eval_result.rank}")
            if eval_result.strengths:
                lines.append(f"- 強み: {', '.join(eval_result.strengths)}")
            if eval_result.weaknesses:
                lines.append(f"- 弱み: {', '.join(eval_result.weaknesses)}")
            lines.append("")

        # トレードオフ
        if tradeoff_analysis and tradeoff_analysis.tradeoffs:
            lines.append("## トレードオフ分析")
            for t in tradeoff_analysis.tradeoffs[:5]:
                lines.append(f"- {t.to_natural_language()}")
            lines.append("")

        # リスク・リターン
        if risk_return_analysis:
            lines.append("## リスク・リターン分析")
            lines.append(f"- 全体リスクレベル: {risk_return_analysis.risk_assessment.overall_risk_level}")
            lines.append(f"- 期待リターン: {risk_return_analysis.return_assessment.total_expected_return:,.0f}")
            lines.append(f"- リスク調整後リターン: {risk_return_analysis.risk_adjusted_return:,.0f}")
            lines.append("")

        # 整合性
        if consistency_check:
            lines.append("## 過去判断との整合性")
            lines.append(f"- 整合性レベル: {consistency_check.consistency_level}")
            lines.append(f"- 整合性スコア: {consistency_check.consistency_score:.2f}")
            if consistency_check.issues:
                lines.append("- 検出された問題:")
                for issue in consistency_check.issues[:3]:
                    lines.append(f"  - {issue.description}")
            lines.append("")

        # 推奨
        lines.append("## 最終推奨")
        lines.append(recommendation.natural_language_recommendation)
        if recommendation.conditions:
            lines.append("### 注意点")
            for cond in recommendation.conditions:
                lines.append(f"- {cond}")
        if recommendation.next_steps:
            lines.append("### 次のステップ")
            for step in recommendation.next_steps:
                lines.append(f"- {step}")

        return "\n".join(lines)

    # =========================================================================
    # 信頼度計算
    # =========================================================================

    def _calculate_overall_confidence(
        self,
        evaluations: List[OptionEvaluation],
        tradeoff_analysis: Optional[TradeoffAnalysisResult],
        risk_return_analysis: Optional[RiskReturnAnalysis],
        consistency_check: Optional[ConsistencyCheckResult],
    ) -> float:
        """全体の信頼度を計算"""
        confidences = []

        if evaluations:
            eval_confidences = [e.confidence for e in evaluations]
            confidences.append(sum(eval_confidences) / len(eval_confidences))

        if tradeoff_analysis:
            confidences.append(tradeoff_analysis.confidence)

        if risk_return_analysis:
            confidences.append(risk_return_analysis.confidence)

        if consistency_check:
            confidences.append(consistency_check.confidence)

        if not confidences:
            return 0.5

        return sum(confidences) / len(confidences)

    # =========================================================================
    # ログ記録
    # =========================================================================

    async def _log_judgment(
        self,
        output: AdvancedJudgmentOutput,
    ):
        """判断をログに記録"""
        if not self.pool:
            return

        try:
            # 判断履歴として保存
            judgment = PastJudgment(
                judgment_type=output.judgment_type,
                question=output.input.question,
                chosen_option=(
                    output.recommendation.recommended_option.name
                    if output.recommendation.recommended_option else ""
                ),
                options=[o.name for o in output.input.options],
                reasoning=output.recommendation.reasoning,
                organization_id=output.input.organization_id,
                user_id=output.input.user_id,
                metadata={
                    "recommendation_type": output.recommendation.recommendation_type,
                    "confidence": output.overall_confidence,
                    "processing_time_ms": output.processing_time_ms,
                },
            )

            await self.consistency_checker.save_judgment(judgment)

        except Exception as e:
            logger.error(f"Error logging judgment: {e}")

    # =========================================================================
    # ユーティリティ
    # =========================================================================

    def _is_feature_enabled(
        self,
        feature_name: str,
    ) -> bool:
        """機能が有効かどうかを確認"""
        # 明示的に無効化されていなければ有効とみなす
        return self.feature_flags.get(feature_name, True)


# =============================================================================
# ファクトリー関数
# =============================================================================

def create_advanced_judgment(
    pool: Optional[Any] = None,
    organization_id: str = "",
    get_ai_response_func: Optional[Callable] = None,
    use_llm: bool = True,
    organization_values: Optional[Dict[str, Any]] = None,
    feature_flags: Optional[Dict[str, bool]] = None,
) -> AdvancedJudgment:
    """
    AdvancedJudgmentのインスタンスを作成

    Args:
        pool: データベース接続プール
        organization_id: 組織ID
        get_ai_response_func: AI応答生成関数
        use_llm: LLMを使用するか
        organization_values: 組織の価値観・方針
        feature_flags: 機能フラグ

    Returns:
        AdvancedJudgment: 高度な判断層
    """
    return AdvancedJudgment(
        pool=pool,
        organization_id=organization_id,
        get_ai_response_func=get_ai_response_func,
        use_llm=use_llm,
        organization_values=organization_values,
        feature_flags=feature_flags,
    )


# =============================================================================
# エクスポート
# =============================================================================

__all__ = [
    "AdvancedJudgment",
    "create_advanced_judgment",
]
