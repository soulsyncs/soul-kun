# lib/brain/advanced_judgment/consistency_checker.py
"""
Phase 2J: 判断力強化（Advanced Judgment）- 整合性チェックエンジン

設計書: docs/17_brain_completion_roadmap.md セクション17.3 Phase 2J

このファイルには、過去の判断との整合性をチェックするエンジンを定義します。

【機能】
- 過去判断履歴の参照
- 類似判断の検索
- 整合性スコアの計算
- 矛盾点の指摘
- 一貫性のある判断支援

【整合性チェックの次元】
- 価値観との整合: 組織のMVVに沿っているか
- 方針との整合: 既存の方針・ルールに従っているか
- 先例との整合: 過去の類似判断と一貫しているか
- コミットメントとの整合: 過去の約束と矛盾しないか

Author: Claude Opus 4.5
Created: 2026-01-27
"""

import logging
import time
import re
import json
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Callable
from difflib import SequenceMatcher

from .constants import (
    ConsistencyLevel,
    ConsistencyDimension,
    JudgmentType,
    CONSISTENCY_LEVEL_SCORES,
    CONSISTENCY_CHECK_PERIOD_DAYS,
    MAX_SIMILAR_JUDGMENTS,
    SIMILARITY_THRESHOLD,
)
from .models import (
    JudgmentOption,
    OptionEvaluation,
    PastJudgment,
    ConsistencyIssue,
    ConsistencyCheckResult,
    JudgmentRecommendation,
    AdvancedJudgmentInput,
)


logger = logging.getLogger(__name__)


# =============================================================================
# LLMプロンプトテンプレート
# =============================================================================

CONSISTENCY_CHECK_PROMPT = """あなたは判断の整合性をチェックするAIアシスタントです。
現在の判断と過去の判断の整合性を分析してください。

## 現在の判断課題
{current_question}

## 選択肢と推奨
{current_recommendation}

## 過去の類似判断
{past_judgments_text}

## 組織の価値観・方針
{values_text}

## タスク
1. 現在の判断が過去の判断と一貫しているか確認してください
2. 矛盾や不整合があれば指摘してください
3. 整合性を高めるための推奨事項を提示してください

## 出力形式（JSON）
{{
    "consistency_level": "fully_consistent/mostly_consistent/partially_consistent/inconsistent/contradictory",
    "issues": [
        {{
            "dimension": "precedent_consistency/value_alignment/policy_compliance/commitment_consistency",
            "description": "問題の説明",
            "severity": 0.0-1.0,
            "recommendation": "対応策"
        }}
    ],
    "overall_assessment": "全体的な整合性評価",
    "recommendations": ["推奨1", "推奨2"]
}}"""


# =============================================================================
# 整合性チェックエンジン
# =============================================================================

class ConsistencyChecker:
    """
    整合性チェックエンジン

    過去の判断との整合性をチェックする。

    使用例:
        checker = ConsistencyChecker(
            pool=db_pool,
            organization_id="org_001",
            get_ai_response_func=get_ai_response,
        )

        result = await checker.check(
            current_question="この案件を受けるべきか？",
            current_recommendation=recommendation,
            options=options,
        )
    """

    def __init__(
        self,
        pool: Optional[Any] = None,
        organization_id: str = "",
        get_ai_response_func: Optional[Callable] = None,
        use_llm: bool = True,
        organization_values: Optional[Dict[str, Any]] = None,
    ):
        """
        Args:
            pool: データベース接続プール
            organization_id: 組織ID
            get_ai_response_func: AI応答生成関数
            use_llm: LLMを使用するか
            organization_values: 組織の価値観・方針
        """
        self.pool = pool
        self.organization_id = organization_id
        self.get_ai_response = get_ai_response_func
        self.use_llm = use_llm and get_ai_response_func is not None
        self.organization_values = organization_values or {}

        # 過去判断のキャッシュ（メモリ内、DBがない場合のフォールバック）
        self._judgment_cache: List[PastJudgment] = []

        logger.info(
            f"ConsistencyChecker initialized: "
            f"org_id={organization_id}, use_llm={self.use_llm}"
        )

    # =========================================================================
    # メイン整合性チェックメソッド
    # =========================================================================

    async def check(
        self,
        current_question: str,
        current_recommendation: Optional[JudgmentRecommendation] = None,
        options: Optional[List[JudgmentOption]] = None,
        input_data: Optional[AdvancedJudgmentInput] = None,
    ) -> ConsistencyCheckResult:
        """
        整合性をチェック

        Args:
            current_question: 現在の判断課題
            current_recommendation: 現在の推奨
            options: 選択肢リスト
            input_data: 判断入力データ

        Returns:
            ConsistencyCheckResult: 整合性チェック結果
        """
        start_time = time.time()

        logger.info(f"Checking consistency for: {current_question[:50]}...")

        # 過去の判断を取得
        past_judgments = await self._get_similar_judgments(
            current_question, options
        )

        # 各次元での整合性をチェック
        issues = []

        # 1. 先例との整合性
        precedent_issues = self._check_precedent_consistency(
            current_question, current_recommendation, past_judgments
        )
        issues.extend(precedent_issues)

        # 2. 価値観との整合性
        value_issues = self._check_value_alignment(
            current_question, current_recommendation
        )
        issues.extend(value_issues)

        # 3. 方針との整合性
        policy_issues = self._check_policy_compliance(
            current_question, current_recommendation
        )
        issues.extend(policy_issues)

        # 4. コミットメントとの整合性
        commitment_issues = self._check_commitment_consistency(
            current_question, current_recommendation, past_judgments
        )
        issues.extend(commitment_issues)

        # LLMによる追加分析
        if self.use_llm and past_judgments:
            llm_result = await self._analyze_with_llm(
                current_question, current_recommendation, past_judgments
            )
            if llm_result:
                issues = self._merge_issues(issues, llm_result.issues)

        # 全体の整合性レベルとスコアを計算
        consistency_level, consistency_score = self._calculate_overall_consistency(
            issues
        )

        # 次元別スコアを計算
        scores_by_dimension = self._calculate_dimension_scores(issues)

        # サマリーと推奨事項を生成
        summary = self._generate_summary(
            consistency_level, issues, past_judgments
        )
        recommendations = self._generate_recommendations(issues)

        # 信頼度
        confidence = self._calculate_confidence(issues, past_judgments)

        elapsed_ms = int((time.time() - start_time) * 1000)

        result = ConsistencyCheckResult(
            consistency_level=consistency_level,
            consistency_score=consistency_score,
            issues=issues,
            similar_judgments=past_judgments,
            scores_by_dimension=scores_by_dimension,
            summary=summary,
            recommendations=recommendations,
            confidence=confidence,
            processing_time_ms=elapsed_ms,
        )

        logger.info(
            f"Consistency check completed in {elapsed_ms}ms: "
            f"level={consistency_level}, score={consistency_score:.2f}, "
            f"issues={len(issues)}"
        )

        return result

    # =========================================================================
    # 過去判断の取得
    # =========================================================================

    async def _get_similar_judgments(
        self,
        question: str,
        options: Optional[List[JudgmentOption]],
    ) -> List[PastJudgment]:
        """類似の過去判断を取得"""
        # DBから取得を試みる
        if self.pool:
            db_judgments = await self._fetch_judgments_from_db(question)
            if db_judgments:
                return db_judgments

        # キャッシュから検索
        similar = []
        for past in self._judgment_cache:
            similarity = self._calculate_similarity(question, past.question)
            if similarity >= SIMILARITY_THRESHOLD:
                similar.append((past, similarity))

        # 類似度でソートして上位を返す
        similar.sort(key=lambda x: x[1], reverse=True)
        return [j for j, _ in similar[:MAX_SIMILAR_JUDGMENTS]]

    async def _fetch_judgments_from_db(
        self,
        question: str,
    ) -> List[PastJudgment]:
        """DBから過去の判断を取得"""
        if not self.pool:
            return []

        try:
            # 期間でフィルタ
            cutoff_date = datetime.now() - timedelta(days=CONSISTENCY_CHECK_PERIOD_DAYS)

            async with self.pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT id, judgment_type, question, actual_choice AS chosen_option, options_json,
                           reasoning, outcome, outcome_score, created_at, metadata_json
                    FROM judgment_history
                    WHERE organization_id = $1
                      AND created_at >= $2
                    ORDER BY created_at DESC
                    LIMIT $3
                    """,
                    self.organization_id,
                    cutoff_date,
                    MAX_SIMILAR_JUDGMENTS * 3,  # 多めに取得して類似度でフィルタ
                )

            judgments = []
            for row in rows:
                try:
                    judgment = PastJudgment(
                        id=str(row["id"]),
                        judgment_type=row["judgment_type"],
                        question=row["question"],
                        chosen_option=row["chosen_option"] or "",
                        options=json.loads(row["options_json"]) if row["options_json"] else [],
                        reasoning=row["reasoning"] or "",
                        outcome=row["outcome"],
                        judged_at=row["created_at"],
                        organization_id=self.organization_id,
                        metadata=json.loads(row["metadata_json"]) if row["metadata_json"] else {},
                    )

                    # 類似度チェック
                    similarity = self._calculate_similarity(question, judgment.question)
                    if similarity >= SIMILARITY_THRESHOLD:
                        judgments.append(judgment)

                except Exception as e:
                    logger.warning(f"Error parsing judgment row: {e}")
                    continue

            return judgments[:MAX_SIMILAR_JUDGMENTS]

        except Exception as e:
            logger.error(f"Error fetching judgments from DB: {e}")
            return []

    def _calculate_similarity(
        self,
        text1: str,
        text2: str,
    ) -> float:
        """2つのテキストの類似度を計算"""
        # 簡易的な類似度計算（SequenceMatcher使用）
        return SequenceMatcher(None, text1.lower(), text2.lower()).ratio()

    # =========================================================================
    # 先例との整合性チェック
    # =========================================================================

    def _check_precedent_consistency(
        self,
        question: str,
        recommendation: Optional[JudgmentRecommendation],
        past_judgments: List[PastJudgment],
    ) -> List[ConsistencyIssue]:
        """先例との整合性をチェック"""
        issues: List[ConsistencyIssue] = []

        if not past_judgments or not recommendation:
            return issues

        # 類似の過去判断と比較
        for past in past_judgments:
            similarity = self._calculate_similarity(question, past.question)

            if similarity >= 0.7:  # 高い類似度
                # 結論が異なる場合
                if (recommendation.recommended_option and
                    past.chosen_option and
                    recommendation.recommended_option.name != past.chosen_option):

                    # 過去の結果が良かった場合は警告
                    severity = 0.5
                    if past.outcome_score and past.outcome_score > 0.7:
                        severity = 0.7

                    issues.append(ConsistencyIssue(
                        dimension=ConsistencyDimension.PRECEDENT_CONSISTENCY.value,
                        description=(
                            f"類似の判断「{past.question[:50]}...」では"
                            f"「{past.chosen_option}」が選ばれましたが、"
                            f"今回は「{recommendation.recommended_option.name}」が推奨されています"
                        ),
                        related_judgment=past,
                        severity=severity,
                        recommendation=(
                            f"過去の判断（{past.judged_at.strftime('%Y-%m-%d')}）との"
                            f"違いを確認してください"
                        ),
                    ))

        return issues

    # =========================================================================
    # 価値観との整合性チェック
    # =========================================================================

    def _check_value_alignment(
        self,
        question: str,
        recommendation: Optional[JudgmentRecommendation],
    ) -> List[ConsistencyIssue]:
        """価値観との整合性をチェック"""
        issues: List[ConsistencyIssue] = []

        if not self.organization_values:
            return issues

        # 組織の価値観から禁止事項を取得
        prohibited_patterns = self.organization_values.get("prohibited_patterns", [])
        mission = self.organization_values.get("mission", "")
        values = self.organization_values.get("values", [])

        question_lower = question.lower()
        rec_text = ""
        if recommendation and recommendation.recommended_option:
            rec_text = recommendation.recommended_option.name.lower()

        # 禁止パターンとの照合
        for pattern in prohibited_patterns:
            if pattern.lower() in question_lower or pattern.lower() in rec_text:
                issues.append(ConsistencyIssue(
                    dimension=ConsistencyDimension.VALUE_ALIGNMENT.value,
                    description=f"判断内容に禁止パターン「{pattern}」が含まれています",
                    severity=0.8,
                    recommendation="組織の価値観との整合性を確認してください",
                ))

        # ミッションとの整合
        if mission:
            # 簡易チェック: キーワードの重複
            mission_words = set(mission.lower().split())
            question_words = set(question_lower.split())
            overlap = mission_words & question_words

            if len(overlap) == 0 and len(mission_words) > 3:
                issues.append(ConsistencyIssue(
                    dimension=ConsistencyDimension.VALUE_ALIGNMENT.value,
                    description="判断内容とミッションとの関連性が明確ではありません",
                    severity=0.3,
                    recommendation=f"ミッション「{mission}」との関連を検討してください",
                ))

        return issues

    # =========================================================================
    # 方針との整合性チェック
    # =========================================================================

    def _check_policy_compliance(
        self,
        question: str,
        recommendation: Optional[JudgmentRecommendation],
    ) -> List[ConsistencyIssue]:
        """方針との整合性をチェック"""
        issues: List[ConsistencyIssue] = []

        if not self.organization_values:
            return issues

        policies = self.organization_values.get("policies", [])

        for policy in policies:
            policy_name = policy.get("name", "")
            policy_rules = policy.get("rules", [])

            for rule in policy_rules:
                rule_text = rule.get("text", "").lower()
                condition = rule.get("condition", "").lower()

                # 条件に該当するかチェック
                if condition and condition in question.lower():
                    # ルールとの整合性をチェック
                    if recommendation and recommendation.recommended_option:
                        rec_name = recommendation.recommended_option.name.lower()
                        if rule.get("required_action", "").lower() not in rec_name:
                            issues.append(ConsistencyIssue(
                                dimension=ConsistencyDimension.POLICY_COMPLIANCE.value,
                                description=(
                                    f"方針「{policy_name}」のルール"
                                    f"「{rule_text}」に準拠していない可能性があります"
                                ),
                                severity=0.6,
                                recommendation=f"方針「{policy_name}」を確認してください",
                            ))

        return issues

    # =========================================================================
    # コミットメントとの整合性チェック
    # =========================================================================

    def _check_commitment_consistency(
        self,
        question: str,
        recommendation: Optional[JudgmentRecommendation],
        past_judgments: List[PastJudgment],
    ) -> List[ConsistencyIssue]:
        """コミットメントとの整合性をチェック"""
        issues = []

        # 過去の判断で「コミット」「約束」「必ず」等が含まれるものを検出
        commitment_keywords = ["コミット", "約束", "必ず", "保証", "確約", "お約束"]

        for past in past_judgments:
            reasoning = past.reasoning.lower() if past.reasoning else ""
            has_commitment = any(kw in reasoning for kw in commitment_keywords)

            if has_commitment:
                # コミットメントがあった過去判断と矛盾がないかチェック
                if recommendation and recommendation.recommended_option:
                    # 結論が正反対の場合
                    past_positive = any(
                        p in past.chosen_option.lower()
                        for p in ["進める", "採用", "承認", "yes"]
                    )
                    rec_positive = any(
                        p in recommendation.recommended_option.name.lower()
                        for p in ["進める", "採用", "承認", "yes"]
                    )

                    if past_positive != rec_positive:
                        issues.append(ConsistencyIssue(
                            dimension=ConsistencyDimension.COMMITMENT_CONSISTENCY.value,
                            description=(
                                f"過去の判断「{past.question[:30]}...」で"
                                f"コミットメントがありましたが、"
                                f"今回の推奨と方向性が異なります"
                            ),
                            related_judgment=past,
                            severity=0.7,
                            recommendation="過去のコミットメントとの整合性を確認してください",
                        ))

        return issues

    # =========================================================================
    # LLMによる分析
    # =========================================================================

    async def _analyze_with_llm(
        self,
        question: str,
        recommendation: Optional[JudgmentRecommendation],
        past_judgments: List[PastJudgment],
    ) -> Optional[ConsistencyCheckResult]:
        """LLMを使用して整合性を分析"""
        if not self.get_ai_response:
            return None

        try:
            # プロンプト構築
            current_rec_text = ""
            if recommendation and recommendation.recommended_option:
                current_rec_text = (
                    f"推奨: {recommendation.recommended_option.name}\n"
                    f"理由: {recommendation.reasoning}"
                )

            past_judgments_text = self._format_past_judgments(past_judgments)
            values_text = self._format_organization_values()

            prompt = CONSISTENCY_CHECK_PROMPT.format(
                current_question=question,
                current_recommendation=current_rec_text or "なし",
                past_judgments_text=past_judgments_text or "なし",
                values_text=values_text or "なし",
            )

            response = await self._call_llm(prompt)
            return self._parse_llm_response(response)

        except Exception as e:
            logger.error(f"LLM consistency analysis error: {e}")
            return None

    def _format_past_judgments(
        self,
        judgments: List[PastJudgment],
    ) -> str:
        """過去の判断をプロンプト用にフォーマット"""
        if not judgments:
            return ""

        lines = []
        for i, j in enumerate(judgments[:5], 1):
            lines.append(f"\n### 過去判断{i}（{j.judged_at.strftime('%Y-%m-%d')}）")
            lines.append(f"課題: {j.question}")
            lines.append(f"選択: {j.chosen_option}")
            if j.reasoning:
                lines.append(f"理由: {j.reasoning}")
            if j.outcome:
                lines.append(f"結果: {j.outcome}")

        return "\n".join(lines)

    def _format_organization_values(self) -> str:
        """組織の価値観をプロンプト用にフォーマット"""
        if not self.organization_values:
            return ""

        lines = []

        if "mission" in self.organization_values:
            lines.append(f"ミッション: {self.organization_values['mission']}")

        if "values" in self.organization_values:
            lines.append("価値観:")
            for v in self.organization_values["values"]:
                lines.append(f"  - {v}")

        if "policies" in self.organization_values:
            lines.append("方針:")
            for p in self.organization_values["policies"]:
                lines.append(f"  - {p.get('name', '')}: {p.get('description', '')}")

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

    def _parse_llm_response(
        self,
        response: str,
    ) -> Optional[ConsistencyCheckResult]:
        """LLMレスポンスをパース"""
        try:
            json_match = re.search(r'\{[\s\S]*\}', response)
            if not json_match:
                return None

            data = json.loads(json_match.group())

            issues = []
            for i_data in data.get("issues", []):
                issues.append(ConsistencyIssue(
                    dimension=i_data.get(
                        "dimension",
                        ConsistencyDimension.PRECEDENT_CONSISTENCY.value
                    ),
                    description=i_data.get("description", ""),
                    severity=float(i_data.get("severity", 0.5)),
                    recommendation=i_data.get("recommendation", ""),
                ))

            return ConsistencyCheckResult(
                consistency_level=data.get(
                    "consistency_level",
                    ConsistencyLevel.MOSTLY_CONSISTENT.value
                ),
                issues=issues,
                summary=data.get("overall_assessment", ""),
                recommendations=data.get("recommendations", []),
                confidence=0.8,
            )

        except Exception as e:
            logger.error(f"Error parsing LLM response: {e}")
            return None

    # =========================================================================
    # スコア計算
    # =========================================================================

    def _calculate_overall_consistency(
        self,
        issues: List[ConsistencyIssue],
    ) -> tuple:
        """全体の整合性レベルとスコアを計算"""
        if not issues:
            return (ConsistencyLevel.FULLY_CONSISTENT.value, 1.0)

        # 深刻度の平均を計算
        avg_severity = sum(i.severity for i in issues) / len(issues)
        max_severity = max(i.severity for i in issues)

        # 重み付け: 平均60%、最大40%
        combined_severity = avg_severity * 0.6 + max_severity * 0.4

        # スコア = 1 - 深刻度
        consistency_score = 1.0 - combined_severity

        # レベルを決定
        if consistency_score >= 0.9:
            level = ConsistencyLevel.FULLY_CONSISTENT.value
        elif consistency_score >= 0.7:
            level = ConsistencyLevel.MOSTLY_CONSISTENT.value
        elif consistency_score >= 0.5:
            level = ConsistencyLevel.PARTIALLY_CONSISTENT.value
        elif consistency_score >= 0.2:
            level = ConsistencyLevel.INCONSISTENT.value
        else:
            level = ConsistencyLevel.CONTRADICTORY.value

        return (level, consistency_score)

    def _calculate_dimension_scores(
        self,
        issues: List[ConsistencyIssue],
    ) -> Dict[str, float]:
        """次元別の整合性スコアを計算"""
        scores: Dict[str, float] = {}

        # 全次元を初期化
        for dim in ConsistencyDimension:
            scores[dim.value] = 1.0

        # 各問題の深刻度をスコアに反映
        for issue in issues:
            issue_dim = issue.dimension
            current_score = scores.get(issue_dim, 1.0)
            # 深刻度をスコアから引く（ただし0未満にはならない）
            scores[issue_dim] = max(0.0, current_score - issue.severity)

        return scores

    def _merge_issues(
        self,
        rule_based: List[ConsistencyIssue],
        llm_based: List[ConsistencyIssue],
    ) -> List[ConsistencyIssue]:
        """ルールベースとLLMの問題をマージ"""
        merged = list(rule_based)

        for llm_issue in llm_based:
            is_duplicate = False
            for existing in merged:
                # 同じ次元で説明が類似していれば重複
                if (existing.dimension == llm_issue.dimension and
                    self._calculate_similarity(
                        existing.description, llm_issue.description
                    ) > 0.5):
                    # より詳細な説明を採用
                    if len(llm_issue.description) > len(existing.description):
                        existing.description = llm_issue.description
                    if len(llm_issue.recommendation) > len(existing.recommendation):
                        existing.recommendation = llm_issue.recommendation
                    is_duplicate = True
                    break

            if not is_duplicate:
                merged.append(llm_issue)

        return merged

    # =========================================================================
    # サマリーと推奨
    # =========================================================================

    def _generate_summary(
        self,
        level: str,
        issues: List[ConsistencyIssue],
        past_judgments: List[PastJudgment],
    ) -> str:
        """整合性チェックのサマリーを生成"""
        level_text = {
            ConsistencyLevel.FULLY_CONSISTENT.value: "完全に一貫しています",
            ConsistencyLevel.MOSTLY_CONSISTENT.value: "概ね一貫しています",
            ConsistencyLevel.PARTIALLY_CONSISTENT.value: "部分的に一貫しています",
            ConsistencyLevel.INCONSISTENT.value: "一貫性に問題があります",
            ConsistencyLevel.CONTRADICTORY.value: "過去の判断と矛盾しています",
        }

        parts = [
            f"過去の判断との整合性は{level_text.get(level, '不明')}。",
        ]

        if past_judgments:
            parts.append(f"類似の過去判断が{len(past_judgments)}件見つかりました。")

        if issues:
            parts.append(f"{len(issues)}件の整合性の問題が検出されました。")

            # 最も深刻な問題
            sorted_issues = sorted(issues, key=lambda i: i.severity, reverse=True)
            if sorted_issues:
                parts.append(
                    f"最も注意が必要なのは「{sorted_issues[0].description[:50]}...」です。"
                )

        return " ".join(parts)

    def _generate_recommendations(
        self,
        issues: List[ConsistencyIssue],
    ) -> List[str]:
        """推奨事項を生成"""
        recommendations = []

        # 問題からの推奨
        for issue in sorted(issues, key=lambda i: i.severity, reverse=True)[:3]:
            if issue.recommendation:
                recommendations.append(issue.recommendation)

        # 重複を除去
        return list(dict.fromkeys(recommendations))[:5]

    def _calculate_confidence(
        self,
        issues: List[ConsistencyIssue],
        past_judgments: List[PastJudgment],
    ) -> float:
        """信頼度を計算"""
        base_confidence = 0.5

        # 過去判断が多いほど信頼度が上がる
        if past_judgments:
            base_confidence += min(len(past_judgments) * 0.1, 0.3)

        # LLMを使用している場合は信頼度アップ
        if self.use_llm:
            base_confidence += 0.1

        # 組織の価値観が設定されている場合は信頼度アップ
        if self.organization_values:
            base_confidence += 0.1

        return min(base_confidence, 1.0)

    # =========================================================================
    # 判断履歴の保存
    # =========================================================================

    async def save_judgment(
        self,
        judgment: PastJudgment,
    ) -> bool:
        """判断を履歴に保存"""
        # キャッシュに追加
        self._judgment_cache.append(judgment)

        # キャッシュサイズ制限
        if len(self._judgment_cache) > MAX_SIMILAR_JUDGMENTS * 10:
            self._judgment_cache = self._judgment_cache[-MAX_SIMILAR_JUDGMENTS * 5:]

        # DBに保存
        if self.pool:
            try:
                async with self.pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO judgment_history (
                            organization_id, judgment_type, question,
                            actual_choice, options_json, reasoning,
                            metadata_json, created_at
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                        """,
                        self.organization_id,
                        judgment.judgment_type,
                        judgment.question,
                        judgment.chosen_option,
                        json.dumps(judgment.options, ensure_ascii=False),
                        judgment.reasoning,
                        json.dumps(judgment.metadata, ensure_ascii=False),
                        judgment.judged_at,
                    )
                return True
            except Exception as e:
                logger.error(f"Error saving judgment to DB: {e}")
                return False

        return True

    async def update_judgment_outcome(
        self,
        judgment_id: str,
        outcome: str,
        outcome_score: float,
    ) -> bool:
        """判断結果を更新（フィードバック用）"""
        if not self.pool:
            return False

        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE judgment_history
                    SET outcome = $1, outcome_score = $2, updated_at = NOW()
                    WHERE id = $3 AND organization_id = $4
                    """,
                    outcome,
                    outcome_score,
                    judgment_id,
                    self.organization_id,
                )
            return True
        except Exception as e:
            logger.error(f"Error updating judgment outcome: {e}")
            return False


# =============================================================================
# ファクトリー関数
# =============================================================================

def create_consistency_checker(
    pool: Optional[Any] = None,
    organization_id: str = "",
    get_ai_response_func: Optional[Callable] = None,
    use_llm: bool = True,
    organization_values: Optional[Dict[str, Any]] = None,
) -> ConsistencyChecker:
    """
    ConsistencyCheckerのインスタンスを作成

    Args:
        pool: データベース接続プール
        organization_id: 組織ID
        get_ai_response_func: AI応答生成関数
        use_llm: LLMを使用するか
        organization_values: 組織の価値観・方針

    Returns:
        ConsistencyChecker: 整合性チェックエンジン
    """
    return ConsistencyChecker(
        pool=pool,
        organization_id=organization_id,
        get_ai_response_func=get_ai_response_func,
        use_llm=use_llm,
        organization_values=organization_values,
    )


# =============================================================================
# エクスポート
# =============================================================================

__all__ = [
    "ConsistencyChecker",
    "create_consistency_checker",
    "CONSISTENCY_CHECK_PROMPT",
]
