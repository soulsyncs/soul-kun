# lib/brain/advanced_judgment/risk_assessor.py
"""
Phase 2J: 判断力強化（Advanced Judgment）- リスク評価エンジン

設計書: docs/17_brain_completion_roadmap.md セクション17.3 Phase 2J

このファイルには、リスク・リターンを定量評価するエンジンを定義します。

【機能】
- リスク要因の特定
- 発生確率と影響度の評価
- リターンの期待値計算
- リスク・リターン比の算出
- リスク調整後リターンの計算

【ユースケース】
- 投資判断のリスク分析
- プロジェクトのリスク評価
- 意思決定のリスク・リターンバランス

Author: Claude Opus 4.5
Created: 2026-01-27
"""

import logging
import time
import re
import json
from typing import Optional, List, Dict, Any, Callable, Tuple

from .constants import (
    RiskCategory,
    RiskProbability,
    RiskImpact,
    ReturnType,
    ReturnCertainty,
    ReturnTimeframe,
    RISK_PROBABILITY_VALUES,
    RISK_IMPACT_VALUES,
    RISK_SCORE_THRESHOLDS,
    RETURN_CERTAINTY_DISCOUNT,
    RETURN_TIMEFRAME_MONTHS,
    MAX_RISK_FACTORS,
)
from .models import (
    JudgmentOption,
    OptionEvaluation,
    RiskFactor,
    RiskAssessment,
    ReturnFactor,
    ReturnAssessment,
    RiskReturnAnalysis,
)


logger = logging.getLogger(__name__)


# =============================================================================
# LLMプロンプトテンプレート
# =============================================================================

RISK_ASSESSMENT_PROMPT = """あなたはリスク分析を行うAIアシスタントです。
以下の判断課題について、リスクを分析してください。

## 判断課題
{question}

## 選択肢
{options_text}

## コンテキスト
{context_text}

## タスク
各選択肢について、主要なリスク要因を特定し、発生確率と影響度を評価してください。

発生確率:
- rare: ほぼ発生しない（<10%）
- unlikely: 発生しにくい（10-30%）
- possible: 発生の可能性あり（30-50%）
- likely: 発生しやすい（50-70%）
- almost_certain: ほぼ確実（>70%）

影響度:
- negligible: 無視できる程度
- minor: 軽微
- moderate: 中程度
- major: 重大
- severe: 致命的

## 出力形式（JSON）
{{
    "risks": [
        {{
            "name": "リスク名",
            "category": "リスクカテゴリ",
            "description": "説明",
            "probability": "rare/unlikely/possible/likely/almost_certain",
            "impact": "negligible/minor/moderate/major/severe",
            "mitigation_strategies": ["緩和策1", "緩和策2"],
            "related_options": ["選択肢名1"]
        }}
    ],
    "overall_assessment": "全体的なリスク評価の概要",
    "recommendations": ["推奨1", "推奨2"]
}}"""


RETURN_ASSESSMENT_PROMPT = """あなたはリターン分析を行うAIアシスタントです。
以下の判断課題について、期待されるリターンを分析してください。

## 判断課題
{question}

## 選択肢
{options_text}

## コンテキスト
{context_text}

## タスク
各選択肢について、期待されるリターンを特定し、確実性と時間軸を評価してください。

確実性:
- guaranteed: 確定（契約済み等）
- highly_likely: ほぼ確実
- expected: 期待できる
- possible: 可能性あり
- speculative: 投機的

時間軸:
- immediate: 即時（1ヶ月以内）
- short_term: 短期（1-3ヶ月）
- medium_term: 中期（3-12ヶ月）
- long_term: 長期（1-3年）
- very_long_term: 超長期（3年以上）

## 出力形式（JSON）
{{
    "returns": [
        {{
            "name": "リターン名",
            "type": "リターンタイプ",
            "description": "説明",
            "expected_value": 数値（金額や割合）,
            "unit": "単位（円、%等）",
            "certainty": "guaranteed/highly_likely/expected/possible/speculative",
            "timeframe": "immediate/short_term/medium_term/long_term/very_long_term",
            "related_options": ["選択肢名1"]
        }}
    ],
    "overall_assessment": "全体的なリターン評価の概要"
}}"""


# =============================================================================
# リスクキーワードマッピング
# =============================================================================

RISK_KEYWORDS: Dict[str, List[str]] = {
    RiskCategory.MARKET_RISK.value: [
        "市場", "競争", "需要", "価格変動", "景気", "経済",
    ],
    RiskCategory.TECHNOLOGY_RISK.value: [
        "技術", "システム", "バグ", "障害", "互換性", "セキュリティ",
    ],
    RiskCategory.FINANCIAL_RISK.value: [
        "コスト", "予算", "キャッシュフロー", "資金", "収益",
    ],
    RiskCategory.SCHEDULE_RISK.value: [
        "スケジュール", "期限", "遅延", "納期", "時間",
    ],
    RiskCategory.RESOURCE_RISK.value: [
        "リソース", "人員", "スキル", "能力", "採用",
    ],
    RiskCategory.OPERATIONAL_RISK.value: [
        "運用", "オペレーション", "プロセス", "手順",
    ],
    RiskCategory.COMPLIANCE_RISK.value: [
        "法規制", "コンプライアンス", "法律", "規制",
    ],
    RiskCategory.KEY_PERSON_RISK.value: [
        "キーパーソン", "依存", "属人化", "退職",
    ],
}


# =============================================================================
# リスク評価エンジン
# =============================================================================

class RiskAssessor:
    """
    リスク評価エンジン

    リスク・リターンを定量評価する。

    使用例:
        assessor = RiskAssessor(
            get_ai_response_func=get_ai_response,
        )

        result = await assessor.assess(
            options=[option1, option2],
            question="この投資を行うべきか？",
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
            get_ai_response_func: AI応答生成関数（LLM分析用）
            use_llm: LLMを使用して分析するか
        """
        self.get_ai_response = get_ai_response_func
        self.use_llm = use_llm and get_ai_response_func is not None

        logger.info(
            f"RiskAssessor initialized: use_llm={self.use_llm}"
        )

    # =========================================================================
    # メイン評価メソッド
    # =========================================================================

    async def assess(
        self,
        options: List[JudgmentOption],
        question: str = "",
        context: Optional[Dict[str, Any]] = None,
        evaluations: Optional[List[OptionEvaluation]] = None,
    ) -> RiskReturnAnalysis:
        """
        リスク・リターンを評価

        Args:
            options: 評価対象の選択肢
            question: 判断の質問
            context: コンテキスト情報
            evaluations: 選択肢の評価結果（あれば利用）

        Returns:
            RiskReturnAnalysis: リスク・リターン分析結果
        """
        start_time = time.time()
        context = context or {}

        logger.info(f"Assessing risk/return for {len(options)} options")

        # リスク評価
        risk_assessment = await self._assess_risks(
            options, question, context, evaluations
        )

        # リターン評価
        return_assessment = await self._assess_returns(
            options, question, context, evaluations
        )

        # リスク・リターン分析の統合
        analysis = self._integrate_analysis(
            risk_assessment, return_assessment
        )

        elapsed_ms = int((time.time() - start_time) * 1000)
        logger.info(
            f"Risk/return assessment completed in {elapsed_ms}ms: "
            f"overall_risk={analysis.risk_assessment.overall_risk_level}, "
            f"total_return={analysis.return_assessment.total_expected_return:.2f}"
        )

        return analysis

    # =========================================================================
    # リスク評価
    # =========================================================================

    async def _assess_risks(
        self,
        options: List[JudgmentOption],
        question: str,
        context: Dict[str, Any],
        evaluations: Optional[List[OptionEvaluation]],
    ) -> RiskAssessment:
        """リスクを評価"""
        # ルールベースのリスク検出
        rule_based_risks = self._detect_risks_rule_based(
            options, context, evaluations
        )

        # LLMによるリスク分析
        if self.use_llm:
            llm_risks = await self._analyze_risks_with_llm(
                options, question, context
            )
            risks = self._merge_risks(rule_based_risks, llm_risks)
        else:
            risks = rule_based_risks

        # リスクスコアを計算
        for risk in risks:
            risk.calculate_risk_score()

        # 全体のリスク評価を計算
        return self._calculate_overall_risk(risks)

    def _detect_risks_rule_based(
        self,
        options: List[JudgmentOption],
        context: Dict[str, Any],
        evaluations: Optional[List[OptionEvaluation]],
    ) -> List[RiskFactor]:
        """ルールベースでリスクを検出"""
        risks = []

        # コンテキストからリスクを検出
        context_text = json.dumps(context, ensure_ascii=False).lower()

        for category, keywords in RISK_KEYWORDS.items():
            for keyword in keywords:
                if keyword in context_text:
                    risks.append(RiskFactor(
                        name=f"{keyword}に関するリスク",
                        category=category,
                        description=f"コンテキストで「{keyword}」が言及されています",
                        probability=RiskProbability.POSSIBLE.value,
                        impact=RiskImpact.MODERATE.value,
                        confidence=0.4,
                    ))
                    break  # カテゴリごとに1つだけ

        # オプションのメタデータからリスクを検出
        for option in options:
            metadata = option.metadata

            # 予算超過リスク
            if "cost" in metadata and "budget" in context:
                cost = metadata.get("cost", 0)
                budget = context.get("budget", float("inf"))
                if cost > budget:
                    risks.append(RiskFactor(
                        name="予算超過リスク",
                        category=RiskCategory.FINANCIAL_RISK.value,
                        description=f"コスト({cost})が予算({budget})を超過",
                        probability=RiskProbability.ALMOST_CERTAIN.value,
                        impact=RiskImpact.MAJOR.value,
                        related_option_ids=[option.id],
                        confidence=0.9,
                    ))

            # 期限リスク
            if "deadline" in metadata or "deadline" in context:
                risks.append(RiskFactor(
                    name="スケジュールリスク",
                    category=RiskCategory.SCHEDULE_RISK.value,
                    description="期限に関する制約があります",
                    probability=RiskProbability.POSSIBLE.value,
                    impact=RiskImpact.MODERATE.value,
                    related_option_ids=[option.id],
                    confidence=0.5,
                ))

            # リスクレベルが明示されている場合
            if "risk_level" in metadata:
                risk_level = str(metadata["risk_level"]).lower()
                probability_map = {
                    "low": RiskProbability.UNLIKELY.value,
                    "medium": RiskProbability.POSSIBLE.value,
                    "high": RiskProbability.LIKELY.value,
                    "critical": RiskProbability.ALMOST_CERTAIN.value,
                }
                impact_map = {
                    "low": RiskImpact.MINOR.value,
                    "medium": RiskImpact.MODERATE.value,
                    "high": RiskImpact.MAJOR.value,
                    "critical": RiskImpact.SEVERE.value,
                }
                risks.append(RiskFactor(
                    name=f"{option.name}の全般的リスク",
                    category=RiskCategory.OTHER.value,
                    description=f"メタデータでリスクレベル「{risk_level}」が指定",
                    probability=probability_map.get(risk_level, RiskProbability.POSSIBLE.value),
                    impact=impact_map.get(risk_level, RiskImpact.MODERATE.value),
                    related_option_ids=[option.id],
                    confidence=0.8,
                ))

        # 評価結果からリスクを推測
        if evaluations:
            for evaluation in evaluations:
                # 低スコアの基準をリスクとして扱う
                for score in evaluation.criterion_scores:
                    if score.score <= 2:
                        risks.append(RiskFactor(
                            name=f"{score.criterion_id}のリスク",
                            category=RiskCategory.OPERATIONAL_RISK.value,
                            description=f"評価スコアが低い（{score.score}/5）",
                            probability=RiskProbability.LIKELY.value,
                            impact=RiskImpact.MODERATE.value,
                            related_option_ids=[evaluation.option.id],
                            confidence=0.6,
                        ))

        return risks[:MAX_RISK_FACTORS]

    async def _analyze_risks_with_llm(
        self,
        options: List[JudgmentOption],
        question: str,
        context: Dict[str, Any],
    ) -> List[RiskFactor]:
        """LLMでリスクを分析"""
        if not self.get_ai_response:
            return []

        try:
            options_text = self._format_options_for_prompt(options)
            context_text = self._format_context_for_prompt(context)

            prompt = RISK_ASSESSMENT_PROMPT.format(
                question=question,
                options_text=options_text,
                context_text=context_text,
            )

            response = await self._call_llm(prompt)
            return self._parse_risk_response(response, options)

        except Exception as e:
            logger.error(f"LLM risk analysis error: {e}")
            return []

    def _parse_risk_response(
        self,
        response: str,
        options: List[JudgmentOption],
    ) -> List[RiskFactor]:
        """リスク分析のLLMレスポンスをパース"""
        risks: List[RiskFactor] = []

        try:
            json_match = re.search(r'\{[\s\S]*\}', response)
            if not json_match:
                return risks

            data = json.loads(json_match.group())
            option_name_map: Dict[str, str] = {o.name: o.id for o in options}

            for r_data in data.get("risks", []):
                # 関連する選択肢のIDを取得
                related_ids = []
                for opt_name in r_data.get("related_options", []):
                    if opt_name in option_name_map:
                        related_ids.append(option_name_map[opt_name])

                risk = RiskFactor(
                    name=r_data.get("name", "不明なリスク"),
                    category=r_data.get("category", RiskCategory.OTHER.value),
                    description=r_data.get("description", ""),
                    probability=r_data.get("probability", RiskProbability.POSSIBLE.value),
                    impact=r_data.get("impact", RiskImpact.MODERATE.value),
                    mitigation_strategies=r_data.get("mitigation_strategies", []),
                    related_option_ids=related_ids,
                    confidence=0.8,
                )
                risks.append(risk)

        except Exception as e:
            logger.error(f"Error parsing risk response: {e}")

        return risks

    def _merge_risks(
        self,
        rule_based: List[RiskFactor],
        llm_based: List[RiskFactor],
    ) -> List[RiskFactor]:
        """ルールベースとLLMのリスクをマージ"""
        merged = list(rule_based)

        for llm_risk in llm_based:
            is_duplicate = False
            for existing in merged:
                # 同じカテゴリで名前が類似していれば重複とみなす
                if (existing.category == llm_risk.category and
                    (existing.name in llm_risk.name or llm_risk.name in existing.name)):
                    # 既存のものをLLMの情報で補強
                    if llm_risk.description and len(llm_risk.description) > len(existing.description):
                        existing.description = llm_risk.description
                    if llm_risk.mitigation_strategies:
                        existing.mitigation_strategies.extend(llm_risk.mitigation_strategies)
                    existing.confidence = max(existing.confidence, llm_risk.confidence)
                    is_duplicate = True
                    break

            if not is_duplicate:
                merged.append(llm_risk)

        return merged[:MAX_RISK_FACTORS]

    def _calculate_overall_risk(
        self,
        risks: List[RiskFactor],
    ) -> RiskAssessment:
        """全体のリスク評価を計算"""
        if not risks:
            return RiskAssessment(
                risks=[],
                overall_risk_score=0.0,
                overall_risk_level="low",
                summary="リスクは検出されませんでした。",
                confidence=0.5,
            )

        # 各リスクのスコアを計算
        total_score = 0.0
        for risk in risks:
            risk.calculate_risk_score()
            total_score += risk.risk_score

        # 平均リスクスコア
        avg_score = total_score / len(risks)

        # 最大リスクスコア（最悪ケース）
        max_score = max(r.risk_score for r in risks)

        # 全体スコア = 平均と最大の加重平均
        overall_score = (avg_score * 0.6 + max_score * 0.4)

        # 全体レベルを決定
        overall_level = "low"
        for level, (min_score, max_score_threshold) in RISK_SCORE_THRESHOLDS.items():
            if min_score <= overall_score <= max_score_threshold:
                overall_level = level
                break

        # カテゴリ別カウント
        risks_by_category: Dict[str, int] = {}
        for risk in risks:
            risks_by_category[risk.category] = risks_by_category.get(risk.category, 0) + 1

        # レベル別カウント
        risks_by_level: Dict[str, int] = {}
        for risk in risks:
            risks_by_level[risk.risk_level] = risks_by_level.get(risk.risk_level, 0) + 1

        # 上位リスク
        top_risks = sorted(risks, key=lambda r: r.risk_score, reverse=True)[:5]

        # 推奨される緩和策を収集
        recommended_mitigations = []
        for risk in top_risks:
            recommended_mitigations.extend(risk.mitigation_strategies[:2])
        recommended_mitigations = list(set(recommended_mitigations))[:5]

        # サマリー生成
        summary = self._generate_risk_summary(risks, overall_level, top_risks)

        # 信頼度
        confidences = [r.confidence for r in risks]
        confidence = sum(confidences) / len(confidences) if confidences else 0.5

        return RiskAssessment(
            risks=risks,
            overall_risk_score=overall_score,
            overall_risk_level=overall_level,
            top_risks=top_risks,
            risks_by_category=risks_by_category,
            risks_by_level=risks_by_level,
            summary=summary,
            recommended_mitigations=recommended_mitigations,
            confidence=confidence,
        )

    def _generate_risk_summary(
        self,
        risks: List[RiskFactor],
        overall_level: str,
        top_risks: List[RiskFactor],
    ) -> str:
        """リスク評価のサマリーを生成"""
        level_text = {
            "low": "低い",
            "medium": "中程度",
            "high": "高い",
            "critical": "非常に高い",
        }

        parts = [
            f"全体のリスクレベルは{level_text.get(overall_level, '中程度')}です。",
            f"{len(risks)}件のリスク要因が特定されました。",
        ]

        if top_risks:
            top_risk = top_risks[0]
            parts.append(
                f"最も重大なリスクは「{top_risk.name}」"
                f"（発生確率: {top_risk.probability}、影響度: {top_risk.impact}）です。"
            )

        return " ".join(parts)

    # =========================================================================
    # リターン評価
    # =========================================================================

    async def _assess_returns(
        self,
        options: List[JudgmentOption],
        question: str,
        context: Dict[str, Any],
        evaluations: Optional[List[OptionEvaluation]],
    ) -> ReturnAssessment:
        """リターンを評価"""
        # ルールベースのリターン検出
        rule_based_returns = self._detect_returns_rule_based(
            options, context, evaluations
        )

        # LLMによるリターン分析
        if self.use_llm:
            llm_returns = await self._analyze_returns_with_llm(
                options, question, context
            )
            returns = self._merge_returns(rule_based_returns, llm_returns)
        else:
            returns = rule_based_returns

        # 調整後リターンを計算
        for ret in returns:
            ret.calculate_adjusted_value()

        # 全体のリターン評価を計算
        return self._calculate_overall_return(returns)

    def _detect_returns_rule_based(
        self,
        options: List[JudgmentOption],
        context: Dict[str, Any],
        evaluations: Optional[List[OptionEvaluation]],
    ) -> List[ReturnFactor]:
        """ルールベースでリターンを検出"""
        returns = []

        for option in options:
            metadata = option.metadata

            # 収益が明示されている場合
            if "revenue" in metadata or "profit" in metadata:
                value = metadata.get("revenue", metadata.get("profit", 0))
                returns.append(ReturnFactor(
                    name=f"{option.name}の収益",
                    return_type=ReturnType.REVENUE_INCREASE.value,
                    description="期待される収益",
                    expected_value=float(value) if isinstance(value, (int, float, str)) else 0,
                    unit="円",
                    certainty=ReturnCertainty.EXPECTED.value,
                    timeframe=ReturnTimeframe.MEDIUM_TERM.value,
                    related_option_ids=[option.id],
                    confidence=0.7,
                ))

            # コスト削減が明示されている場合
            if "cost_reduction" in metadata:
                value = metadata["cost_reduction"]
                returns.append(ReturnFactor(
                    name=f"{option.name}のコスト削減",
                    return_type=ReturnType.COST_REDUCTION.value,
                    description="期待されるコスト削減",
                    expected_value=float(value) if isinstance(value, (int, float, str)) else 0,
                    unit="円",
                    certainty=ReturnCertainty.EXPECTED.value,
                    timeframe=ReturnTimeframe.SHORT_TERM.value,
                    related_option_ids=[option.id],
                    confidence=0.6,
                ))

            # ROIが明示されている場合
            if "roi" in metadata:
                value = metadata["roi"]
                returns.append(ReturnFactor(
                    name=f"{option.name}のROI",
                    return_type=ReturnType.PROFIT_INCREASE.value,
                    description="期待されるROI",
                    expected_value=float(value) if isinstance(value, (int, float, str)) else 0,
                    unit="%",
                    certainty=ReturnCertainty.EXPECTED.value,
                    timeframe=ReturnTimeframe.MEDIUM_TERM.value,
                    related_option_ids=[option.id],
                    confidence=0.6,
                ))

        return returns

    async def _analyze_returns_with_llm(
        self,
        options: List[JudgmentOption],
        question: str,
        context: Dict[str, Any],
    ) -> List[ReturnFactor]:
        """LLMでリターンを分析"""
        if not self.get_ai_response:
            return []

        try:
            options_text = self._format_options_for_prompt(options)
            context_text = self._format_context_for_prompt(context)

            prompt = RETURN_ASSESSMENT_PROMPT.format(
                question=question,
                options_text=options_text,
                context_text=context_text,
            )

            response = await self._call_llm(prompt)
            return self._parse_return_response(response, options)

        except Exception as e:
            logger.error(f"LLM return analysis error: {e}")
            return []

    def _parse_return_response(
        self,
        response: str,
        options: List[JudgmentOption],
    ) -> List[ReturnFactor]:
        """リターン分析のLLMレスポンスをパース"""
        returns: List[ReturnFactor] = []

        try:
            json_match = re.search(r'\{[\s\S]*\}', response)
            if not json_match:
                return returns

            data = json.loads(json_match.group())
            option_name_map: Dict[str, str] = {o.name: o.id for o in options}

            for r_data in data.get("returns", []):
                related_ids = []
                for opt_name in r_data.get("related_options", []):
                    if opt_name in option_name_map:
                        related_ids.append(option_name_map[opt_name])

                ret = ReturnFactor(
                    name=r_data.get("name", "不明なリターン"),
                    return_type=r_data.get("type", ReturnType.OTHER.value),
                    description=r_data.get("description", ""),
                    expected_value=float(r_data.get("expected_value", 0)),
                    unit=r_data.get("unit", ""),
                    certainty=r_data.get("certainty", ReturnCertainty.EXPECTED.value),
                    timeframe=r_data.get("timeframe", ReturnTimeframe.MEDIUM_TERM.value),
                    related_option_ids=related_ids,
                    confidence=0.7,
                )
                returns.append(ret)

        except Exception as e:
            logger.error(f"Error parsing return response: {e}")

        return returns

    def _merge_returns(
        self,
        rule_based: List[ReturnFactor],
        llm_based: List[ReturnFactor],
    ) -> List[ReturnFactor]:
        """ルールベースとLLMのリターンをマージ"""
        merged = list(rule_based)

        for llm_ret in llm_based:
            is_duplicate = False
            for existing in merged:
                if (existing.return_type == llm_ret.return_type and
                    existing.related_option_ids == llm_ret.related_option_ids):
                    # 既存のものをLLMの情報で補強
                    if llm_ret.description and len(llm_ret.description) > len(existing.description):
                        existing.description = llm_ret.description
                    is_duplicate = True
                    break

            if not is_duplicate:
                merged.append(llm_ret)

        return merged

    def _calculate_overall_return(
        self,
        returns: List[ReturnFactor],
    ) -> ReturnAssessment:
        """全体のリターン評価を計算"""
        if not returns:
            return ReturnAssessment(
                returns=[],
                total_expected_return=0.0,
                summary="期待されるリターンは特定されませんでした。",
                confidence=0.5,
            )

        # 総リターン（調整後）
        total_return = sum(r.adjusted_value for r in returns)

        # タイプ別リターン
        returns_by_type: Dict[str, float] = {}
        for ret in returns:
            returns_by_type[ret.return_type] = (
                returns_by_type.get(ret.return_type, 0) + ret.adjusted_value
            )

        # 時間軸別リターン
        returns_by_timeframe: Dict[str, float] = {}
        for ret in returns:
            returns_by_timeframe[ret.timeframe] = (
                returns_by_timeframe.get(ret.timeframe, 0) + ret.adjusted_value
            )

        # 上位リターン
        top_returns = sorted(returns, key=lambda r: r.adjusted_value, reverse=True)[:5]

        # サマリー生成
        summary = self._generate_return_summary(returns, total_return, top_returns)

        # 信頼度
        confidences = [r.confidence for r in returns]
        confidence = sum(confidences) / len(confidences) if confidences else 0.5

        return ReturnAssessment(
            returns=returns,
            total_expected_return=total_return,
            returns_by_type=returns_by_type,
            returns_by_timeframe=returns_by_timeframe,
            top_returns=top_returns,
            summary=summary,
            confidence=confidence,
        )

    def _generate_return_summary(
        self,
        returns: List[ReturnFactor],
        total_return: float,
        top_returns: List[ReturnFactor],
    ) -> str:
        """リターン評価のサマリーを生成"""
        parts = [
            f"{len(returns)}件のリターン要因が特定されました。",
            f"期待総リターン（確実性調整後）: {total_return:,.0f}",
        ]

        if top_returns:
            top = top_returns[0]
            parts.append(
                f"最大のリターンは「{top.name}」"
                f"（期待値: {top.expected_value:,.0f}{top.unit}、"
                f"確実性: {top.certainty}）です。"
            )

        return " ".join(parts)

    # =========================================================================
    # リスク・リターン統合分析
    # =========================================================================

    def _integrate_analysis(
        self,
        risk_assessment: RiskAssessment,
        return_assessment: ReturnAssessment,
    ) -> RiskReturnAnalysis:
        """リスク・リターン分析を統合"""
        # リスク・リターン比を計算
        if return_assessment.total_expected_return > 0:
            risk_return_ratio = (
                risk_assessment.overall_risk_score /
                return_assessment.total_expected_return
            )
        else:
            risk_return_ratio = float("inf") if risk_assessment.overall_risk_score > 0 else 0

        # リスク調整後リターンを計算
        # 簡易計算: リターン × (1 - リスクスコア / 25)
        risk_factor = 1 - min(risk_assessment.overall_risk_score / 25, 0.9)
        risk_adjusted_return = return_assessment.total_expected_return * risk_factor

        # 推奨を生成
        recommendation = self._generate_recommendation(
            risk_assessment, return_assessment, risk_adjusted_return
        )

        # サマリーを生成
        summary = self._generate_analysis_summary(
            risk_assessment, return_assessment, risk_adjusted_return
        )

        # 信頼度
        confidence = (risk_assessment.confidence + return_assessment.confidence) / 2

        return RiskReturnAnalysis(
            risk_assessment=risk_assessment,
            return_assessment=return_assessment,
            risk_return_ratio=risk_return_ratio,
            risk_adjusted_return=risk_adjusted_return,
            recommendation=recommendation,
            summary=summary,
            confidence=confidence,
        )

    def _generate_recommendation(
        self,
        risk_assessment: RiskAssessment,
        return_assessment: ReturnAssessment,
        risk_adjusted_return: float,
    ) -> str:
        """推奨を生成"""
        risk_level = risk_assessment.overall_risk_level
        has_return = return_assessment.total_expected_return > 0

        if risk_level == "critical":
            return "リスクが非常に高いため、慎重な検討が必要です。リスク緩和策を講じてから進めることを推奨します。"
        elif risk_level == "high":
            if has_return and risk_adjusted_return > 0:
                return "リスクは高いですが、リターンも期待できます。リスク緩和策を講じた上で進めることを検討してください。"
            else:
                return "リスクが高く、期待リターンとのバランスが取れていません。再検討を推奨します。"
        elif risk_level == "medium":
            if has_return:
                return "リスクとリターンのバランスは適切です。計画通り進めることを推奨します。"
            else:
                return "リスクは中程度ですが、リターンが不明確です。リターンを明確にした上で判断することを推奨します。"
        else:  # low
            if has_return:
                return "リスクが低く、リターンも期待できます。積極的に進めることを推奨します。"
            else:
                return "リスクは低いですが、リターンが不明確です。進めても問題ありませんが、期待値を確認してください。"

    def _generate_analysis_summary(
        self,
        risk_assessment: RiskAssessment,
        return_assessment: ReturnAssessment,
        risk_adjusted_return: float,
    ) -> str:
        """分析サマリーを生成"""
        parts = [
            f"リスク評価: {risk_assessment.summary}",
            f"リターン評価: {return_assessment.summary}",
            f"リスク調整後リターン: {risk_adjusted_return:,.0f}",
        ]
        return " ".join(parts)

    # =========================================================================
    # ユーティリティ
    # =========================================================================

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
            if opt.metadata:
                lines.append(f"   詳細: {json.dumps(opt.metadata, ensure_ascii=False)}")
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


# =============================================================================
# ファクトリー関数
# =============================================================================

def create_risk_assessor(
    get_ai_response_func: Optional[Callable] = None,
    use_llm: bool = True,
) -> RiskAssessor:
    """
    RiskAssessorのインスタンスを作成

    Args:
        get_ai_response_func: AI応答生成関数
        use_llm: LLMを使用するか

    Returns:
        RiskAssessor: リスク評価エンジン
    """
    return RiskAssessor(
        get_ai_response_func=get_ai_response_func,
        use_llm=use_llm,
    )


# =============================================================================
# エクスポート
# =============================================================================

__all__ = [
    "RiskAssessor",
    "create_risk_assessor",
    "RISK_ASSESSMENT_PROMPT",
    "RETURN_ASSESSMENT_PROMPT",
]
