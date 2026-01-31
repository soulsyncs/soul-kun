# lib/brain/advanced_judgment/tradeoff_analyzer.py
"""
Phase 2J: 判断力強化（Advanced Judgment）- トレードオフ分析エンジン

設計書: docs/17_brain_completion_roadmap.md セクション17.3 Phase 2J

このファイルには、判断におけるトレードオフを検出・明示化するエンジンを定義します。

【機能】
- トレードオフの検出
- 「Aを取ればBを犠牲に」の明文化
- 影響度の定量評価
- 緩和策の提案

【トレードオフとは】
ある選択をすることで、別の価値を犠牲にする必要がある関係。
例: 「コストを下げると品質が下がる」「早く作ると完成度が下がる」

Author: Claude Opus 4.5
Created: 2026-01-27
"""

import logging
import time
import re
import json
from typing import Optional, List, Dict, Any, Callable, Tuple
from itertools import combinations

from .constants import (
    TradeoffType,
    TradeoffSeverity,
    CriterionCategory,
    COMMON_TRADEOFFS,
    MAX_TRADEOFF_DEPTH,
)
from .models import (
    JudgmentOption,
    OptionEvaluation,
    EvaluationCriterion,
    TradeoffFactor,
    Tradeoff,
    TradeoffAnalysisResult,
)


logger = logging.getLogger(__name__)


# =============================================================================
# LLMプロンプトテンプレート
# =============================================================================

TRADEOFF_ANALYSIS_PROMPT = """あなたは判断支援を行うAIアシスタントです。
以下の判断課題について、重要なトレードオフを分析してください。

## 判断課題
{question}

## 選択肢と評価結果
{evaluations_text}

## 評価基準
{criteria_text}

## タスク
1. 選択肢間や評価基準間の重要なトレードオフを特定してください
2. 各トレードオフについて、「Aを取ればBを犠牲にする」という関係を明確にしてください
3. トレードオフの深刻度を評価してください
4. 可能であれば緩和策を提案してください

## 出力形式（JSON）
{{
    "tradeoffs": [
        {{
            "type": "トレードオフタイプ（cost_quality, speed_quality, risk_reward等）",
            "factor_a": {{
                "name": "得られるもの",
                "description": "説明",
                "impact": 0.0-1.0
            }},
            "factor_b": {{
                "name": "犠牲になるもの",
                "description": "説明",
                "impact": 0.0-1.0
            }},
            "severity": "negligible/minor/moderate/significant/critical",
            "description": "トレードオフの説明",
            "mitigation_options": ["緩和策1", "緩和策2"]
        }}
    ],
    "summary": "全体的なトレードオフの概要",
    "recommendations": ["推奨1", "推奨2"]
}}"""


# =============================================================================
# トレードオフパターン定義
# =============================================================================

# 評価基準カテゴリ間のトレードオフ関係
CRITERION_TRADEOFF_PATTERNS: List[Tuple[str, str, str, str]] = [
    # (カテゴリA, カテゴリB, トレードオフタイプ, 説明)
    (CriterionCategory.COST.value, CriterionCategory.QUALITY.value,
     TradeoffType.COST_QUALITY.value, "コスト削減と品質向上"),
    (CriterionCategory.TIME.value, CriterionCategory.QUALITY.value,
     TradeoffType.SPEED_QUALITY.value, "スピードと品質"),
    (CriterionCategory.COST.value, CriterionCategory.TIME.value,
     TradeoffType.COST_SPEED.value, "コストとスピード"),
    (CriterionCategory.RISK.value, CriterionCategory.REVENUE.value,
     TradeoffType.RISK_REWARD.value, "リスクとリターン"),
    (CriterionCategory.FLEXIBILITY.value if hasattr(CriterionCategory, 'FLEXIBILITY') else CriterionCategory.OTHER.value,
     CriterionCategory.OTHER.value,
     TradeoffType.FLEXIBILITY_EFFICIENCY.value, "柔軟性と効率性"),
    (CriterionCategory.EXPERIENCE.value, CriterionCategory.GROWTH_POTENTIAL.value,
     TradeoffType.EXPERIENCE_POTENTIAL.value, "経験と将来性"),
]


# =============================================================================
# トレードオフ分析エンジン
# =============================================================================

class TradeoffAnalyzer:
    """
    トレードオフ分析エンジン

    判断におけるトレードオフを検出・明示化する。

    使用例:
        analyzer = TradeoffAnalyzer(
            get_ai_response_func=get_ai_response,
        )

        result = await analyzer.analyze(
            evaluations=option_evaluations,
            criteria=criteria,
            question="どの案件を優先すべきか？",
        )
    """

    def __init__(
        self,
        get_ai_response_func: Optional[Callable] = None,
        use_llm: bool = True,
    ):
        """
        Args:
            get_ai_response_func: AI応答生成関数（LLM分析用）
            use_llm: LLMを使用して分析するか
        """
        self.get_ai_response = get_ai_response_func
        self.use_llm = use_llm and get_ai_response_func is not None

        logger.info(
            f"TradeoffAnalyzer initialized: use_llm={self.use_llm}"
        )

    # =========================================================================
    # メイン分析メソッド
    # =========================================================================

    async def analyze(
        self,
        evaluations: List[OptionEvaluation],
        criteria: List[EvaluationCriterion],
        question: str = "",
        context: Optional[Dict[str, Any]] = None,
    ) -> TradeoffAnalysisResult:
        """
        トレードオフを分析

        Args:
            evaluations: 選択肢の評価結果
            criteria: 評価基準
            question: 判断の質問
            context: コンテキスト情報

        Returns:
            TradeoffAnalysisResult: 分析結果
        """
        start_time = time.time()
        context = context or {}

        logger.info(
            f"Analyzing tradeoffs for {len(evaluations)} options "
            f"with {len(criteria)} criteria"
        )

        # ルールベースのトレードオフ検出
        rule_based_tradeoffs = self._detect_tradeoffs_rule_based(
            evaluations, criteria
        )

        # LLMによる分析（有効な場合）
        if self.use_llm:
            llm_result = await self._analyze_with_llm(
                evaluations, criteria, question, context
            )
            # ルールベースとLLMの結果をマージ
            tradeoffs = self._merge_tradeoffs(rule_based_tradeoffs, llm_result.tradeoffs)
            summary = llm_result.summary
            recommendations = llm_result.recommendations
        else:
            tradeoffs = rule_based_tradeoffs
            summary = self._generate_summary(tradeoffs)
            recommendations = self._generate_recommendations(tradeoffs)

        # 重要度でソート
        tradeoffs = self._sort_by_severity(tradeoffs)

        # 最も重要なトレードオフを特定
        primary_tradeoff = tradeoffs[0] if tradeoffs else None

        # クリティカルなトレードオフをカウント
        critical_count = sum(
            1 for t in tradeoffs
            if t.severity in [
                TradeoffSeverity.CRITICAL.value,
                TradeoffSeverity.SIGNIFICANT.value,
            ]
        )

        # 信頼度の計算
        confidence = self._calculate_confidence(tradeoffs, evaluations)

        elapsed_ms = int((time.time() - start_time) * 1000)

        result = TradeoffAnalysisResult(
            tradeoffs=tradeoffs,
            primary_tradeoff=primary_tradeoff,
            total_count=len(tradeoffs),
            critical_count=critical_count,
            summary=summary,
            recommendations=recommendations,
            confidence=confidence,
            processing_time_ms=elapsed_ms,
        )

        logger.info(
            f"Tradeoff analysis completed in {elapsed_ms}ms: "
            f"found {len(tradeoffs)} tradeoffs, {critical_count} critical"
        )

        return result

    # =========================================================================
    # ルールベースのトレードオフ検出
    # =========================================================================

    def _detect_tradeoffs_rule_based(
        self,
        evaluations: List[OptionEvaluation],
        criteria: List[EvaluationCriterion],
    ) -> List[Tradeoff]:
        """ルールベースでトレードオフを検出"""
        tradeoffs = []

        # 1. 評価基準間のトレードオフを検出
        criterion_tradeoffs = self._detect_criterion_tradeoffs(criteria)
        tradeoffs.extend(criterion_tradeoffs)

        # 2. 選択肢間のトレードオフを検出
        option_tradeoffs = self._detect_option_tradeoffs(evaluations, criteria)
        tradeoffs.extend(option_tradeoffs)

        # 3. スコアパターンからトレードオフを検出
        score_pattern_tradeoffs = self._detect_score_pattern_tradeoffs(
            evaluations, criteria
        )
        tradeoffs.extend(score_pattern_tradeoffs)

        # 重複を除去
        tradeoffs = self._deduplicate_tradeoffs(tradeoffs)

        return tradeoffs

    def _detect_criterion_tradeoffs(
        self,
        criteria: List[EvaluationCriterion],
    ) -> List[Tradeoff]:
        """評価基準間のトレードオフを検出"""
        tradeoffs = []
        criterion_map = {c.id: c for c in criteria}
        category_map = {c.category: c for c in criteria}

        # 既知のトレードオフパターンを検出
        for cat_a, cat_b, tradeoff_type, desc in CRITERION_TRADEOFF_PATTERNS:
            if cat_a in category_map and cat_b in category_map:
                crit_a = category_map[cat_a]
                crit_b = category_map[cat_b]

                common_tradeoff = COMMON_TRADEOFFS.get(tradeoff_type, {})

                tradeoff = Tradeoff(
                    tradeoff_type=tradeoff_type,
                    factor_a=TradeoffFactor(
                        name=common_tradeoff.get("factor_a", crit_a.name),
                        description=crit_a.description,
                        related_criterion_ids=[crit_a.id],
                        impact=crit_a.weight,
                    ),
                    factor_b=TradeoffFactor(
                        name=common_tradeoff.get("factor_b", crit_b.name),
                        description=crit_b.description,
                        related_criterion_ids=[crit_b.id],
                        impact=crit_b.weight,
                    ),
                    severity=common_tradeoff.get(
                        "typical_severity",
                        TradeoffSeverity.MODERATE.value
                    ),
                    description=common_tradeoff.get("description", desc),
                    confidence=0.7,
                )
                tradeoff.natural_language = tradeoff.to_natural_language()
                tradeoffs.append(tradeoff)

        return tradeoffs

    def _detect_option_tradeoffs(
        self,
        evaluations: List[OptionEvaluation],
        criteria: List[EvaluationCriterion],
    ) -> List[Tradeoff]:
        """選択肢間のトレードオフを検出"""
        tradeoffs = []

        if len(evaluations) < 2:
            return tradeoffs

        criterion_map = {c.id: c for c in criteria}

        # 上位2つの選択肢間でトレードオフを検出
        top_evaluations = evaluations[:2]

        for crit in criteria:
            scores = []
            for eval_result in top_evaluations:
                score_obj = next(
                    (s for s in eval_result.criterion_scores if s.criterion_id == crit.id),
                    None
                )
                if score_obj:
                    scores.append((eval_result.option.name, score_obj.score))

            if len(scores) == 2:
                # スコアが逆転している場合はトレードオフ
                if (scores[0][1] > scores[1][1] and
                    top_evaluations[0].total_score < top_evaluations[1].total_score):
                    # オプションAはこの基準で勝っているが、総合では負けている
                    tradeoff = Tradeoff(
                        tradeoff_type=TradeoffType.CUSTOM.value,
                        factor_a=TradeoffFactor(
                            name=f"{scores[0][0]}の{crit.name}",
                            description=f"{scores[0][0]}は{crit.name}で優れている",
                            related_option_ids=[top_evaluations[0].option.id],
                            related_criterion_ids=[crit.id],
                            impact=crit.weight,
                        ),
                        factor_b=TradeoffFactor(
                            name="総合的な評価",
                            description=f"しかし総合評価では{scores[1][0]}が上",
                            related_option_ids=[top_evaluations[1].option.id],
                            impact=0.8,
                        ),
                        severity=TradeoffSeverity.MINOR.value,
                        description=f"{crit.name}を重視するか総合評価を重視するか",
                        confidence=0.5,
                    )
                    tradeoff.natural_language = tradeoff.to_natural_language()
                    tradeoffs.append(tradeoff)

        return tradeoffs

    def _detect_score_pattern_tradeoffs(
        self,
        evaluations: List[OptionEvaluation],
        criteria: List[EvaluationCriterion],
    ) -> List[Tradeoff]:
        """スコアパターンからトレードオフを検出"""
        tradeoffs = []

        if not evaluations:
            return tradeoffs

        criterion_map = {c.id: c for c in criteria}

        # 各評価について、高スコアと低スコアのペアを探す
        for evaluation in evaluations:
            high_scores = []
            low_scores = []

            for score in evaluation.criterion_scores:
                criterion = criterion_map.get(score.criterion_id)
                if not criterion:
                    continue

                if score.score >= 4:
                    high_scores.append((criterion, score))
                elif score.score <= 2:
                    low_scores.append((criterion, score))

            # 高スコアと低スコアのペアでトレードオフを作成
            for high_crit, high_score in high_scores:
                for low_crit, low_score in low_scores:
                    # 関連性のあるカテゴリペアをチェック
                    if self._is_related_tradeoff_pair(high_crit, low_crit):
                        tradeoff = Tradeoff(
                            tradeoff_type=TradeoffType.CUSTOM.value,
                            factor_a=TradeoffFactor(
                                name=high_crit.name,
                                description=f"{evaluation.option.name}は{high_crit.name}が強い（{high_score.score}/5）",
                                related_option_ids=[evaluation.option.id],
                                related_criterion_ids=[high_crit.id],
                                impact=(high_score.score / 5.0) * high_crit.weight,
                            ),
                            factor_b=TradeoffFactor(
                                name=low_crit.name,
                                description=f"一方で{low_crit.name}は弱い（{low_score.score}/5）",
                                related_option_ids=[evaluation.option.id],
                                related_criterion_ids=[low_crit.id],
                                impact=(1 - low_score.score / 5.0) * low_crit.weight,
                            ),
                            severity=self._calculate_tradeoff_severity(
                                high_score.score, low_score.score
                            ),
                            description=(
                                f"{evaluation.option.name}を選ぶと"
                                f"{high_crit.name}は得られるが{low_crit.name}は犠牲になる"
                            ),
                            confidence=0.6,
                        )
                        tradeoff.natural_language = tradeoff.to_natural_language()
                        tradeoffs.append(tradeoff)

        return tradeoffs

    def _is_related_tradeoff_pair(
        self,
        crit_a: EvaluationCriterion,
        crit_b: EvaluationCriterion,
    ) -> bool:
        """2つの評価基準がトレードオフの関係にあるか判定"""
        # 既知のトレードオフパターンをチェック
        for cat_a, cat_b, _, _ in CRITERION_TRADEOFF_PATTERNS:
            if ((crit_a.category == cat_a and crit_b.category == cat_b) or
                (crit_a.category == cat_b and crit_b.category == cat_a)):
                return True

        # カテゴリが異なれば潜在的なトレードオフの可能性あり
        return crit_a.category != crit_b.category

    def _calculate_tradeoff_severity(
        self,
        high_score: int,
        low_score: int,
    ) -> str:
        """スコア差からトレードオフの深刻度を計算

        スコアは1-5の範囲。差が大きいほど深刻なトレードオフ。

        Args:
            high_score: 高い方のスコア (1-5)
            low_score: 低い方のスコア (1-5)

        Returns:
            深刻度の文字列値

        マッピング:
            diff <= 1: NEGLIGIBLE (無視できる程度 - 両立可能)
            diff == 2: MINOR (軽微 - 工夫次第で両立可能)
            diff == 3: MODERATE (中程度 - ある程度の犠牲が必要)
            diff >= 4: CRITICAL (致命的 - 最大差、一方を完全に犠牲)

        Note:
            スコア1-5の場合、最大差は4 (5-1)。
            diff >= 4 は「一方を諦める必要がある」致命的なトレードオフ。
        """
        diff = high_score - low_score

        if diff <= 1:
            return TradeoffSeverity.NEGLIGIBLE.value
        elif diff == 2:
            return TradeoffSeverity.MINOR.value
        elif diff == 3:
            return TradeoffSeverity.MODERATE.value
        else:  # diff >= 4 (max possible diff for scores 1-5)
            return TradeoffSeverity.CRITICAL.value

    # =========================================================================
    # LLMによる分析
    # =========================================================================

    async def _analyze_with_llm(
        self,
        evaluations: List[OptionEvaluation],
        criteria: List[EvaluationCriterion],
        question: str,
        context: Dict[str, Any],
    ) -> TradeoffAnalysisResult:
        """LLMを使用して分析"""
        if not self.get_ai_response:
            return TradeoffAnalysisResult()

        try:
            # プロンプト構築
            evaluations_text = self._format_evaluations_for_prompt(evaluations)
            criteria_text = self._format_criteria_for_prompt(criteria)

            prompt = TRADEOFF_ANALYSIS_PROMPT.format(
                question=question,
                evaluations_text=evaluations_text,
                criteria_text=criteria_text,
            )

            # LLM呼び出し
            response = await self._call_llm(prompt)

            # レスポンスをパース
            return self._parse_llm_response(response, evaluations, criteria)

        except Exception as e:
            logger.error(f"LLM analysis error: {e}", exc_info=True)
            return TradeoffAnalysisResult()

    async def _call_llm(self, prompt: str) -> str:
        """LLMを呼び出し"""
        if not self.get_ai_response:
            return "{}"

        try:
            import asyncio
            if asyncio.iscoroutinefunction(self.get_ai_response):
                response = await self.get_ai_response([], prompt)
            else:
                response = self.get_ai_response([], prompt)

            return response if isinstance(response, str) else str(response)

        except Exception as e:
            logger.error(f"LLM call error: {e}")
            return "{}"

    def _format_evaluations_for_prompt(
        self,
        evaluations: List[OptionEvaluation],
    ) -> str:
        """評価結果をプロンプト用にフォーマット"""
        lines = []
        for evaluation in evaluations:
            lines.append(f"\n### {evaluation.option.name}")
            lines.append(f"総合スコア: {evaluation.total_score:.2f}")
            lines.append(f"強み: {', '.join(evaluation.strengths) if evaluation.strengths else 'なし'}")
            lines.append(f"弱み: {', '.join(evaluation.weaknesses) if evaluation.weaknesses else 'なし'}")

            lines.append("基準別スコア:")
            for score in evaluation.criterion_scores:
                lines.append(f"  - {score.criterion_id}: {score.score}/5")

        return "\n".join(lines)

    def _format_criteria_for_prompt(
        self,
        criteria: List[EvaluationCriterion],
    ) -> str:
        """評価基準をプロンプト用にフォーマット"""
        lines = []
        for crit in criteria:
            lines.append(f"- {crit.name}（カテゴリ: {crit.category}、重み: {crit.weight:.1f}）")
            if crit.description:
                lines.append(f"  説明: {crit.description}")
        return "\n".join(lines)

    def _parse_llm_response(
        self,
        response: str,
        evaluations: List[OptionEvaluation],
        criteria: List[EvaluationCriterion],
    ) -> TradeoffAnalysisResult:
        """LLMレスポンスをパース"""
        try:
            json_match = re.search(r'\{[\s\S]*\}', response)
            if not json_match:
                raise ValueError("No JSON found in response")

            data = json.loads(json_match.group())

            tradeoffs = []
            for t_data in data.get("tradeoffs", []):
                factor_a_data = t_data.get("factor_a", {})
                factor_b_data = t_data.get("factor_b", {})

                tradeoff = Tradeoff(
                    tradeoff_type=t_data.get("type", TradeoffType.CUSTOM.value),
                    factor_a=TradeoffFactor(
                        name=factor_a_data.get("name", ""),
                        description=factor_a_data.get("description", ""),
                        impact=factor_a_data.get("impact", 0.5),
                    ),
                    factor_b=TradeoffFactor(
                        name=factor_b_data.get("name", ""),
                        description=factor_b_data.get("description", ""),
                        impact=factor_b_data.get("impact", 0.5),
                    ),
                    severity=t_data.get("severity", TradeoffSeverity.MODERATE.value),
                    description=t_data.get("description", ""),
                    mitigation_options=t_data.get("mitigation_options", []),
                    confidence=0.8,
                )
                tradeoff.natural_language = tradeoff.to_natural_language()
                tradeoffs.append(tradeoff)

            return TradeoffAnalysisResult(
                tradeoffs=tradeoffs,
                summary=data.get("summary", ""),
                recommendations=data.get("recommendations", []),
                confidence=0.8,
            )

        except Exception as e:
            logger.error(f"Error parsing LLM response: {e}")
            return TradeoffAnalysisResult()

    # =========================================================================
    # ユーティリティ
    # =========================================================================

    def _merge_tradeoffs(
        self,
        rule_based: List[Tradeoff],
        llm_based: List[Tradeoff],
    ) -> List[Tradeoff]:
        """ルールベースとLLMのトレードオフをマージ"""
        merged = list(rule_based)

        # LLMの結果を追加（重複を避ける）
        for llm_tradeoff in llm_based:
            is_duplicate = False
            for existing in merged:
                if self._is_similar_tradeoff(existing, llm_tradeoff):
                    # 既存のものをLLMの情報で補強
                    if llm_tradeoff.description and not existing.description:
                        existing.description = llm_tradeoff.description
                    if llm_tradeoff.mitigation_options:
                        existing.mitigation_options.extend(llm_tradeoff.mitigation_options)
                    is_duplicate = True
                    break

            if not is_duplicate:
                merged.append(llm_tradeoff)

        return merged

    def _is_similar_tradeoff(
        self,
        tradeoff_a: Tradeoff,
        tradeoff_b: Tradeoff,
    ) -> bool:
        """2つのトレードオフが類似しているか判定"""
        # タイプが同じなら類似
        if tradeoff_a.tradeoff_type == tradeoff_b.tradeoff_type:
            return True

        # 名前が類似していれば類似
        name_a = (tradeoff_a.factor_a.name + tradeoff_a.factor_b.name).lower()
        name_b = (tradeoff_b.factor_a.name + tradeoff_b.factor_b.name).lower()

        # 単語の重複をチェック
        words_a = set(name_a.split())
        words_b = set(name_b.split())
        overlap = len(words_a & words_b)

        return overlap >= 2

    def _deduplicate_tradeoffs(
        self,
        tradeoffs: List[Tradeoff],
    ) -> List[Tradeoff]:
        """トレードオフの重複を除去"""
        unique = []
        for tradeoff in tradeoffs:
            is_duplicate = False
            for existing in unique:
                if self._is_similar_tradeoff(existing, tradeoff):
                    is_duplicate = True
                    break
            if not is_duplicate:
                unique.append(tradeoff)
        return unique

    def _sort_by_severity(
        self,
        tradeoffs: List[Tradeoff],
    ) -> List[Tradeoff]:
        """深刻度でソート"""
        severity_order = {
            TradeoffSeverity.CRITICAL.value: 0,
            TradeoffSeverity.SIGNIFICANT.value: 1,
            TradeoffSeverity.MODERATE.value: 2,
            TradeoffSeverity.MINOR.value: 3,
            TradeoffSeverity.NEGLIGIBLE.value: 4,
        }
        return sorted(
            tradeoffs,
            key=lambda t: severity_order.get(t.severity, 2)
        )

    def _generate_summary(
        self,
        tradeoffs: List[Tradeoff],
    ) -> str:
        """トレードオフのサマリーを生成"""
        if not tradeoffs:
            return "顕著なトレードオフは検出されませんでした。"

        critical = sum(
            1 for t in tradeoffs
            if t.severity == TradeoffSeverity.CRITICAL.value
        )
        significant = sum(
            1 for t in tradeoffs
            if t.severity == TradeoffSeverity.SIGNIFICANT.value
        )

        parts = [f"{len(tradeoffs)}件のトレードオフが検出されました。"]

        if critical > 0:
            parts.append(f"うち{critical}件は致命的なトレードオフです。")
        if significant > 0:
            parts.append(f"{significant}件は重大なトレードオフです。")

        if tradeoffs:
            primary = tradeoffs[0]
            parts.append(
                f"最も重要なトレードオフは「{primary.factor_a.name}」と"
                f"「{primary.factor_b.name}」の間です。"
            )

        return " ".join(parts)

    def _generate_recommendations(
        self,
        tradeoffs: List[Tradeoff],
    ) -> List[str]:
        """推奨事項を生成"""
        recommendations = []

        for tradeoff in tradeoffs[:3]:  # 上位3件
            if tradeoff.mitigation_options:
                recommendations.extend(tradeoff.mitigation_options)
            else:
                recommendations.append(
                    f"「{tradeoff.factor_a.name}」と「{tradeoff.factor_b.name}」の"
                    f"バランスを慎重に検討してください"
                )

        return recommendations[:5]  # 最大5件

    def _calculate_confidence(
        self,
        tradeoffs: List[Tradeoff],
        evaluations: List[OptionEvaluation],
    ) -> float:
        """分析の信頼度を計算"""
        if not tradeoffs:
            return 0.5

        # トレードオフの信頼度の平均
        tradeoff_confidence = sum(t.confidence for t in tradeoffs) / len(tradeoffs)

        # 評価の信頼度の平均
        if evaluations:
            eval_confidence = sum(e.confidence for e in evaluations) / len(evaluations)
        else:
            eval_confidence = 0.5

        return (tradeoff_confidence + eval_confidence) / 2


# =============================================================================
# ファクトリー関数
# =============================================================================

def create_tradeoff_analyzer(
    get_ai_response_func: Optional[Callable] = None,
    use_llm: bool = True,
) -> TradeoffAnalyzer:
    """
    TradeoffAnalyzerのインスタンスを作成

    Args:
        get_ai_response_func: AI応答生成関数
        use_llm: LLMを使用するか

    Returns:
        TradeoffAnalyzer: トレードオフ分析エンジン
    """
    return TradeoffAnalyzer(
        get_ai_response_func=get_ai_response_func,
        use_llm=use_llm,
    )


# =============================================================================
# エクスポート
# =============================================================================

__all__ = [
    "TradeoffAnalyzer",
    "create_tradeoff_analyzer",
    "TRADEOFF_ANALYSIS_PROMPT",
]
