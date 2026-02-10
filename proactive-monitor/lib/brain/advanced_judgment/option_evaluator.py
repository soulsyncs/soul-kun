# lib/brain/advanced_judgment/option_evaluator.py
"""
Phase 2J: 判断力強化（Advanced Judgment）- 選択肢評価エンジン

設計書: docs/17_brain_completion_roadmap.md セクション17.3 Phase 2J

このファイルには、複数の選択肢を評価基準に基づいて比較・評価するエンジンを定義します。

【機能】
- 複数選択肢の比較評価
- 重み付けスコアリング
- 順位付けとランキング
- 強み・弱みの特定

【ユースケース】
- 「この案件、受けるべき？」への多角的回答
- 採用候補者の比較評価支援
- 投資判断のサポート

Author: Claude Opus 4.5
Created: 2026-01-27
"""

import logging
import time
import re
import json
from typing import Optional, List, Dict, Any, Callable, Tuple

from .constants import (
    JudgmentType,
    CriterionCategory,
    CriterionImportance,
    ScoreLevel,
    CRITERION_IMPORTANCE_WEIGHTS,
    SCORE_LEVEL_VALUES,
    DEFAULT_PROJECT_CRITERIA,
    DEFAULT_HIRING_CRITERIA,
    DEFAULT_INVESTMENT_CRITERIA,
    MAX_OPTIONS,
    MAX_CRITERIA,
    DEFAULT_CRITERIA_COUNT,
)
from .models import (
    JudgmentOption,
    OptionScore,
    OptionEvaluation,
    EvaluationCriterion,
    CriteriaSet,
    AdvancedJudgmentInput,
)


logger = logging.getLogger(__name__)


# =============================================================================
# LLMプロンプトテンプレート
# =============================================================================

OPTION_EVALUATION_PROMPT = """あなたは判断支援を行うAIアシスタントです。
以下の選択肢を評価基準に基づいて評価してください。

## 判断課題
{question}

## 選択肢
{options_text}

## 評価基準
{criteria_text}

## コンテキスト
{context_text}

## タスク
各選択肢を各評価基準に基づいて1-5のスコアで評価してください。
- 5: 優秀（非常に良い）
- 4: 良好（良い）
- 3: 許容範囲（普通）
- 2: 不十分（やや悪い）
- 1: 不可（悪い）

また、各選択肢の強みと弱みを特定してください。

## 出力形式（JSON）
{{
    "evaluations": [
        {{
            "option_id": "選択肢ID",
            "option_name": "選択肢名",
            "scores": {{
                "基準ID": {{
                    "score": 1-5,
                    "reasoning": "スコアの理由"
                }}
            }},
            "strengths": ["強み1", "強み2"],
            "weaknesses": ["弱み1", "弱み2"],
            "summary": "総合評価コメント"
        }}
    ]
}}"""


# =============================================================================
# 選択肢評価エンジン
# =============================================================================

class OptionEvaluator:
    """
    選択肢評価エンジン

    複数の選択肢を評価基準に基づいて比較・評価する。

    使用例:
        evaluator = OptionEvaluator(
            get_ai_response_func=get_ai_response,
        )

        result = await evaluator.evaluate(
            options=[option1, option2, option3],
            criteria=[criterion1, criterion2, criterion3],
            question="どの案件を優先すべきか？",
            context={"budget": 1000000},
        )
    """

    def __init__(
        self,
        get_ai_response_func: Optional[Callable] = None,
        use_llm: bool = True,
    ):
        """
        Args:
            get_ai_response_func: AI応答生成関数（LLM評価用）
            use_llm: LLMを使用して評価するか（Falseの場合はルールベースのみ）
        """
        self.get_ai_response = get_ai_response_func
        self.use_llm = use_llm and get_ai_response_func is not None

        logger.info(
            f"OptionEvaluator initialized: use_llm={self.use_llm}"
        )

    # =========================================================================
    # メイン評価メソッド
    # =========================================================================

    async def evaluate(
        self,
        options: List[JudgmentOption],
        criteria: Optional[List[EvaluationCriterion]] = None,
        question: str = "",
        judgment_type: str = JudgmentType.COMPARISON.value,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[OptionEvaluation]:
        """
        選択肢を評価

        Args:
            options: 評価対象の選択肢リスト
            criteria: 評価基準リスト（Noneの場合はデフォルトを使用）
            question: 判断の質問
            judgment_type: 判断タイプ
            context: コンテキスト情報

        Returns:
            List[OptionEvaluation]: 評価結果のリスト（スコア順）
        """
        start_time = time.time()

        # バリデーション
        if not options:
            logger.warning("No options provided for evaluation")
            return []

        if len(options) > MAX_OPTIONS:
            logger.warning(
                f"Too many options ({len(options)}), limiting to {MAX_OPTIONS}"
            )
            options = options[:MAX_OPTIONS]

        # 評価基準の準備
        if criteria is None or len(criteria) == 0:
            criteria = self._get_default_criteria(judgment_type)

        if len(criteria) > MAX_CRITERIA:
            logger.warning(
                f"Too many criteria ({len(criteria)}), limiting to {MAX_CRITERIA}"
            )
            criteria = criteria[:MAX_CRITERIA]

        context = context or {}

        logger.info(
            f"Evaluating {len(options)} options with {len(criteria)} criteria"
        )

        # 評価実行
        if self.use_llm:
            evaluations = await self._evaluate_with_llm(
                options, criteria, question, context
            )
        else:
            evaluations = self._evaluate_rule_based(
                options, criteria, question, context
            )

        # 総合スコアの計算とランキング
        evaluations = self._calculate_total_scores(evaluations, criteria)
        evaluations = self._rank_options(evaluations)

        elapsed_ms = int((time.time() - start_time) * 1000)
        logger.info(
            f"Option evaluation completed in {elapsed_ms}ms: "
            f"top_option={evaluations[0].option.name if evaluations else 'N/A'}"
        )

        return evaluations

    # =========================================================================
    # デフォルト評価基準の取得
    # =========================================================================

    def _get_default_criteria(
        self,
        judgment_type: str,
    ) -> List[EvaluationCriterion]:
        """判断タイプに応じたデフォルト評価基準を取得"""
        criteria_configs = []

        if judgment_type in [
            JudgmentType.GO_NO_GO.value,
            JudgmentType.APPROVAL_DECISION.value,
        ]:
            criteria_configs = DEFAULT_PROJECT_CRITERIA
        elif judgment_type == JudgmentType.CANDIDATE_EVALUATION.value:
            criteria_configs = DEFAULT_HIRING_CRITERIA
        elif judgment_type in [
            JudgmentType.INVESTMENT_DECISION.value,
            JudgmentType.ROI_ANALYSIS.value,
        ]:
            criteria_configs = DEFAULT_INVESTMENT_CRITERIA
        else:
            # 汎用のデフォルト基準
            criteria_configs = DEFAULT_PROJECT_CRITERIA[:DEFAULT_CRITERIA_COUNT]

        return [
            EvaluationCriterion(
                name=cfg["name"],
                category=cfg["category"],
                importance=cfg["importance"],
                description=cfg.get("description", ""),
            )
            for cfg in criteria_configs
        ]

    # =========================================================================
    # LLMによる評価
    # =========================================================================

    async def _evaluate_with_llm(
        self,
        options: List[JudgmentOption],
        criteria: List[EvaluationCriterion],
        question: str,
        context: Dict[str, Any],
    ) -> List[OptionEvaluation]:
        """LLMを使用して評価"""
        if not self.get_ai_response:
            logger.warning("LLM not available, falling back to rule-based")
            return self._evaluate_rule_based(options, criteria, question, context)

        try:
            # プロンプト構築
            options_text = self._format_options_for_prompt(options)
            criteria_text = self._format_criteria_for_prompt(criteria)
            context_text = self._format_context_for_prompt(context)

            prompt = OPTION_EVALUATION_PROMPT.format(
                question=question,
                options_text=options_text,
                criteria_text=criteria_text,
                context_text=context_text,
            )

            # LLM呼び出し
            response = await self._call_llm(prompt)

            # レスポンスをパース
            evaluations = self._parse_llm_response(response, options, criteria)

            return evaluations

        except Exception as e:
            logger.error(f"LLM evaluation error: {type(e).__name__}", exc_info=True)
            return self._evaluate_rule_based(options, criteria, question, context)

    async def _call_llm(self, prompt: str) -> str:
        """LLMを呼び出し"""
        if not self.get_ai_response:
            return "{}"

        try:
            # 関数が同期か非同期かを判定
            import asyncio
            if asyncio.iscoroutinefunction(self.get_ai_response):
                response = await self.get_ai_response([], prompt)
            else:
                response = self.get_ai_response([], prompt)

            return response if isinstance(response, str) else str(response)

        except Exception as e:
            logger.error(f"LLM call error: {type(e).__name__}")
            return "{}"

    def _format_options_for_prompt(
        self,
        options: List[JudgmentOption],
    ) -> str:
        """選択肢をプロンプト用にフォーマット"""
        lines = []
        for i, opt in enumerate(options, 1):
            lines.append(f"{i}. {opt.name}")
            if opt.description:
                lines.append(f"   説明: {opt.description}")
            lines.append(f"   ID: {opt.id}")
        return "\n".join(lines)

    def _format_criteria_for_prompt(
        self,
        criteria: List[EvaluationCriterion],
    ) -> str:
        """評価基準をプロンプト用にフォーマット"""
        lines = []
        for i, crit in enumerate(criteria, 1):
            importance_text = {
                CriterionImportance.CRITICAL.value: "必須",
                CriterionImportance.HIGH.value: "高",
                CriterionImportance.MEDIUM.value: "中",
                CriterionImportance.LOW.value: "低",
                CriterionImportance.OPTIONAL.value: "オプション",
            }.get(crit.importance, "中")

            lines.append(f"{i}. {crit.name}（重要度: {importance_text}）")
            if crit.description:
                lines.append(f"   説明: {crit.description}")
            lines.append(f"   ID: {crit.id}")
        return "\n".join(lines)

    def _format_context_for_prompt(
        self,
        context: Dict[str, Any],
    ) -> str:
        """コンテキストをプロンプト用にフォーマット"""
        if not context:
            return "特になし"

        lines = []
        for key, value in context.items():
            lines.append(f"- {key}: {value}")
        return "\n".join(lines)

    def _parse_llm_response(
        self,
        response: str,
        options: List[JudgmentOption],
        criteria: List[EvaluationCriterion],
    ) -> List[OptionEvaluation]:
        """LLMレスポンスをパース"""
        evaluations = []

        try:
            # JSONを抽出
            json_match = re.search(r'\{[\s\S]*\}', response)
            if not json_match:
                raise ValueError("No JSON found in response")

            data = json.loads(json_match.group())
            llm_evaluations = data.get("evaluations", [])

            # オプションIDからオプションへのマップ
            option_map = {opt.id: opt for opt in options}
            option_name_map = {opt.name: opt for opt in options}

            # 基準IDから基準へのマップ
            criterion_map = {crit.id: crit for crit in criteria}
            criterion_name_map = {crit.name: crit for crit in criteria}

            for llm_eval in llm_evaluations:
                # 対象オプションを特定
                option_id = llm_eval.get("option_id", "")
                option_name = llm_eval.get("option_name", "")

                option = option_map.get(option_id) or option_name_map.get(option_name)
                if not option:
                    continue

                # スコアを抽出
                criterion_scores = []
                scores_data = llm_eval.get("scores", {})

                for crit_key, score_data in scores_data.items():
                    criterion = criterion_map.get(crit_key) or criterion_name_map.get(crit_key)
                    if not criterion:
                        continue

                    score_value = score_data.get("score", 3) if isinstance(score_data, dict) else score_data
                    score_value = max(1, min(5, int(score_value)))

                    reasoning = score_data.get("reasoning", "") if isinstance(score_data, dict) else ""

                    criterion_scores.append(OptionScore(
                        option_id=option.id,
                        criterion_id=criterion.id,
                        score=score_value,
                        score_level=self._score_to_level(score_value),
                        reasoning=reasoning,
                    ))

                evaluations.append(OptionEvaluation(
                    option=option,
                    criterion_scores=criterion_scores,
                    strengths=llm_eval.get("strengths", []),
                    weaknesses=llm_eval.get("weaknesses", []),
                    summary=llm_eval.get("summary", ""),
                ))

        except Exception as e:
            logger.error(f"Error parsing LLM response: {type(e).__name__}")
            # フォールバック: ルールベース評価を返す
            return self._evaluate_rule_based(options, criteria, "", {})

        # LLMが評価しなかったオプションをフォールバック
        evaluated_ids = {e.option.id for e in evaluations}
        for option in options:
            if option.id not in evaluated_ids:
                evaluations.append(self._create_default_evaluation(option, criteria))

        return evaluations

    def _score_to_level(self, score: int) -> str:
        """スコアをスコアレベルに変換"""
        level_map = {
            5: ScoreLevel.EXCELLENT.value,
            4: ScoreLevel.GOOD.value,
            3: ScoreLevel.ACCEPTABLE.value,
            2: ScoreLevel.POOR.value,
            1: ScoreLevel.UNACCEPTABLE.value,
        }
        return level_map.get(score, ScoreLevel.ACCEPTABLE.value)

    # =========================================================================
    # ルールベース評価
    # =========================================================================

    def _evaluate_rule_based(
        self,
        options: List[JudgmentOption],
        criteria: List[EvaluationCriterion],
        question: str,
        context: Dict[str, Any],
    ) -> List[OptionEvaluation]:
        """ルールベースで評価"""
        evaluations = []

        for option in options:
            evaluation = self._create_default_evaluation(option, criteria)

            # メタデータからスコアを推測
            self._apply_metadata_scoring(evaluation, option, criteria, context)

            # キーワードベースで強み・弱みを推測
            self._infer_strengths_weaknesses(evaluation, option, criteria)

            evaluations.append(evaluation)

        return evaluations

    def _create_default_evaluation(
        self,
        option: JudgmentOption,
        criteria: List[EvaluationCriterion],
    ) -> OptionEvaluation:
        """デフォルトの評価を作成"""
        criterion_scores = []

        for criterion in criteria:
            criterion_scores.append(OptionScore(
                option_id=option.id,
                criterion_id=criterion.id,
                score=3,  # デフォルトは中間値
                score_level=ScoreLevel.ACCEPTABLE.value,
                reasoning="デフォルト評価",
                confidence=0.3,
            ))

        return OptionEvaluation(
            option=option,
            criterion_scores=criterion_scores,
            strengths=[],
            weaknesses=[],
            summary=f"{option.name}の評価",
            confidence=0.3,
        )

    def _apply_metadata_scoring(
        self,
        evaluation: OptionEvaluation,
        option: JudgmentOption,
        criteria: List[EvaluationCriterion],
        context: Dict[str, Any],
    ):
        """メタデータからスコアを適用"""
        metadata = option.metadata

        # 収益性関連
        if "revenue" in metadata or "profit" in metadata:
            revenue = metadata.get("revenue", metadata.get("profit", 0))
            for score in evaluation.criterion_scores:
                criterion = next(
                    (c for c in criteria if c.id == score.criterion_id),
                    None
                )
                if criterion and criterion.category == CriterionCategory.REVENUE.value:
                    # 収益が高いほど高スコア
                    if isinstance(revenue, (int, float)):
                        if revenue > 1000000:
                            score.score = 5
                        elif revenue > 500000:
                            score.score = 4
                        elif revenue > 100000:
                            score.score = 3
                        else:
                            score.score = 2
                        score.score_level = self._score_to_level(score.score)
                        score.reasoning = f"収益: {revenue}"
                        score.confidence = 0.7

        # リスク関連
        if "risk_level" in metadata:
            risk = metadata["risk_level"]
            for score in evaluation.criterion_scores:
                criterion = next(
                    (c for c in criteria if c.id == score.criterion_id),
                    None
                )
                if criterion and criterion.category == CriterionCategory.RISK.value:
                    # リスク基準は「higher_is_better=False」の場合が多い
                    risk_score_map = {
                        "low": 5,
                        "medium": 3,
                        "high": 2,
                        "critical": 1,
                    }
                    score.score = risk_score_map.get(str(risk).lower(), 3)
                    score.score_level = self._score_to_level(score.score)
                    score.reasoning = f"リスクレベル: {risk}"
                    score.confidence = 0.6

    def _infer_strengths_weaknesses(
        self,
        evaluation: OptionEvaluation,
        option: JudgmentOption,
        criteria: List[EvaluationCriterion],
    ):
        """強み・弱みを推測"""
        strengths = []
        weaknesses = []

        for score in evaluation.criterion_scores:
            criterion = next(
                (c for c in criteria if c.id == score.criterion_id),
                None
            )
            if not criterion:
                continue

            if score.score >= 4:
                strengths.append(f"{criterion.name}が優れている")
            elif score.score <= 2:
                weaknesses.append(f"{criterion.name}に課題あり")

        evaluation.strengths = strengths
        evaluation.weaknesses = weaknesses

    # =========================================================================
    # スコア計算とランキング
    # =========================================================================

    def _calculate_total_scores(
        self,
        evaluations: List[OptionEvaluation],
        criteria: List[EvaluationCriterion],
    ) -> List[OptionEvaluation]:
        """総合スコアを計算"""
        criterion_map = {c.id: c for c in criteria}

        for evaluation in evaluations:
            weighted_sum = 0.0
            total_weight = 0.0

            for score in evaluation.criterion_scores:
                criterion = criterion_map.get(score.criterion_id)
                if not criterion:
                    continue

                weight = criterion.weight
                total_weight += weight

                # higher_is_better=Falseの場合はスコアを反転
                actual_score = score.score
                if not criterion.higher_is_better:
                    actual_score = 6 - actual_score  # 1→5, 5→1

                weighted_sum += actual_score * weight

            if total_weight > 0:
                evaluation.total_score = weighted_sum / total_weight
                evaluation.normalized_score = (evaluation.total_score - 1) / 4  # 0-1正規化
            else:
                evaluation.total_score = 3.0
                evaluation.normalized_score = 0.5

            # 信頼度を更新
            confidences = [s.confidence for s in evaluation.criterion_scores if s.confidence > 0]
            if confidences:
                evaluation.confidence = sum(confidences) / len(confidences)

        return evaluations

    def _rank_options(
        self,
        evaluations: List[OptionEvaluation],
    ) -> List[OptionEvaluation]:
        """選択肢をランキング"""
        # スコア順にソート
        evaluations.sort(key=lambda e: e.total_score, reverse=True)

        # 順位を設定
        for i, evaluation in enumerate(evaluations, 1):
            evaluation.rank = i

        return evaluations

    # =========================================================================
    # ユーティリティ
    # =========================================================================

    def get_top_option(
        self,
        evaluations: List[OptionEvaluation],
    ) -> Optional[OptionEvaluation]:
        """最高スコアの選択肢を取得"""
        if not evaluations:
            return None
        return evaluations[0]

    def get_score_gap(
        self,
        evaluations: List[OptionEvaluation],
    ) -> float:
        """1位と2位のスコア差を取得"""
        if len(evaluations) < 2:
            return 0.0
        return evaluations[0].total_score - evaluations[1].total_score

    def is_clear_winner(
        self,
        evaluations: List[OptionEvaluation],
        threshold: float = 0.3,
    ) -> bool:
        """明確な勝者がいるか判定"""
        gap = self.get_score_gap(evaluations)
        return gap >= threshold


# =============================================================================
# ファクトリー関数
# =============================================================================

def create_option_evaluator(
    get_ai_response_func: Optional[Callable] = None,
    use_llm: bool = True,
) -> OptionEvaluator:
    """
    OptionEvaluatorのインスタンスを作成

    Args:
        get_ai_response_func: AI応答生成関数
        use_llm: LLMを使用するか

    Returns:
        OptionEvaluator: 選択肢評価エンジン
    """
    return OptionEvaluator(
        get_ai_response_func=get_ai_response_func,
        use_llm=use_llm,
    )


# =============================================================================
# エクスポート
# =============================================================================

__all__ = [
    "OptionEvaluator",
    "create_option_evaluator",
    "OPTION_EVALUATION_PROMPT",
]
