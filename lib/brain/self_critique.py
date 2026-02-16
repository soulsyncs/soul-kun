"""
Ultimate Brain Architecture - Phase 1: 自己批判 (Self-Critique)

設計書: docs/19_ultimate_brain_architecture.md
セクション: 3.2 自己批判・推敲

回答を送信前に自己評価し、品質を担保する。
途切れた文章、矛盾した回答、不適切なトーンを防ぐ。
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from .constants import JST


# ============================================================================
# Enum定義
# ============================================================================

class QualityCriterion(Enum):
    """品質基準"""
    RELEVANCE = "relevance"           # 質問に答えているか
    COMPLETENESS = "completeness"     # 必要な情報が揃っているか
    CONSISTENCY = "consistency"       # 矛盾がないか
    TONE = "tone"                     # トーンが適切か
    ACTIONABILITY = "actionability"   # 次のアクションが明確か
    SAFETY = "safety"                 # 安全か（機密情報、不適切表現）


class IssueType(Enum):
    """問題タイプ"""
    INCOMPLETE_SENTENCE = "incomplete_sentence"   # 文が途切れている
    CONTRADICTION = "contradiction"               # 矛盾している
    MISSING_INFO = "missing_info"                 # 情報が不足している
    WRONG_TONE = "wrong_tone"                     # トーンが不適切
    UNCLEAR_ACTION = "unclear_action"             # 次のアクションが不明確
    SENSITIVE_INFO = "sensitive_info"             # 機密情報を含む
    TOO_LONG = "too_long"                         # 長すぎる
    TOO_SHORT = "too_short"                       # 短すぎる
    OFF_TOPIC = "off_topic"                       # 話題がずれている


class IssueSeverity(Enum):
    """問題の深刻度"""
    CRITICAL = "critical"   # 必ず修正が必要
    HIGH = "high"           # 修正推奨
    MEDIUM = "medium"       # できれば修正
    LOW = "low"             # 軽微


# ============================================================================
# データクラス
# ============================================================================

@dataclass
class QualityScore:
    """品質スコア"""
    criterion: QualityCriterion
    score: float  # 0.0 〜 1.0
    reasoning: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DetectedIssue:
    """検出された問題"""
    issue_type: IssueType
    severity: IssueSeverity
    description: str
    location: Optional[str] = None  # 問題のある箇所
    suggestion: Optional[str] = None  # 改善提案


@dataclass
class CritiqueResult:
    """批判結果"""
    scores: List[QualityScore]
    issues: List[DetectedIssue]
    overall_score: float
    needs_refinement: bool
    refinement_priority: List[IssueType]


@dataclass
class RefinedResponse:
    """改善された回答"""
    original: str
    refined: str
    improvements: List[DetectedIssue]
    refinement_applied: bool
    refinement_time_ms: float


# ============================================================================
# 定数
# ============================================================================

# 品質基準の閾値
QUALITY_THRESHOLDS = {
    QualityCriterion.RELEVANCE: 0.7,
    QualityCriterion.COMPLETENESS: 0.6,
    QualityCriterion.CONSISTENCY: 0.8,
    QualityCriterion.TONE: 0.7,
    QualityCriterion.ACTIONABILITY: 0.5,
    QualityCriterion.SAFETY: 0.9,
}

# 全体スコアの閾値（これ以下なら改善必須）
OVERALL_REFINEMENT_THRESHOLD = 0.7

# ソウルくんらしい表現パターン
SOULKUN_TONE_PATTERNS = [
    r"ウル[🐺！!]?",
    r"だよ",
    r"だね",
    r"〜ね",
    r"かな",
    r"思う",
]

# 不適切なトーンパターン
INAPPROPRIATE_TONE_PATTERNS = [
    r"です。$",          # 硬すぎる終わり方
    r"ございます",        # 過度に丁寧
    r"いたします",        # 過度に丁寧
    r"してください。$",   # 命令調
    r"しなさい",          # 命令調
    r"べきです",          # 断定的すぎる
]

# 文章の途切れを示すパターン
INCOMPLETE_SENTENCE_PATTERNS = [
    r"[をにがはでとへもの]$",           # 助詞で終わる
    r"[、]$",                           # 読点で終わる
    r"[あいうえおかきくけこ]っ$",       # 促音で終わる（「思っ」など）
    r"というこ$",                       # 「ということ」が切れている
    r"ですの$",                         # 「ですので」が切れている
]

# 機密情報パターン
SENSITIVE_INFO_PATTERNS = [
    r"\d{3}-?\d{4}-?\d{4}",              # 電話番号
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+", # メールアドレス
    r"〒?\d{3}-?\d{4}",                  # 郵便番号
    r"パスワード[:：]?\s*\S+",           # パスワード
    r"API[キー鍵][:：]?\s*\S+",          # APIキー
    r"秘密[:：]?\s*\S+",                 # 秘密情報
]

# 回答の長さの目安
LENGTH_GUIDELINES = {
    "min": 10,        # 最小文字数
    "ideal_min": 30,  # 理想的な最小
    "ideal_max": 200, # 理想的な最大
    "max": 500,       # 最大文字数（これ以上は長すぎる）
}


# ============================================================================
# SelfCritiqueクラス
# ============================================================================

class SelfCritique:
    """
    自己批判エンジン

    回答を送信前に評価し、品質を担保する。
    問題があれば改善提案を行う。
    """

    def __init__(self, llm_client=None):
        """
        初期化

        Args:
            llm_client: LLMクライアント（オプション、高度な改善用）
        """
        self.llm_client = llm_client

    def critique(
        self,
        response: str,
        original_message: str,
        context: Optional[Dict[str, Any]] = None
    ) -> CritiqueResult:
        """
        回答を批判的に評価

        Args:
            response: 生成された回答
            original_message: 元のユーザーメッセージ
            context: コンテキスト情報

        Returns:
            CritiqueResult: 批判結果
        """
        context = context or {}
        scores = []
        issues = []

        # 各品質基準で評価
        relevance_score = self._evaluate_relevance(response, original_message, context)
        scores.append(relevance_score)

        completeness_score = self._evaluate_completeness(response, original_message, context)
        scores.append(completeness_score)

        consistency_score = self._evaluate_consistency(response, context)
        scores.append(consistency_score)

        tone_score = self._evaluate_tone(response)
        scores.append(tone_score)

        actionability_score = self._evaluate_actionability(response, original_message)
        scores.append(actionability_score)

        safety_score = self._evaluate_safety(response)
        scores.append(safety_score)

        # 問題を検出
        issues.extend(self._detect_issues(response, scores, original_message, context))

        # 全体スコアを計算（重み付き平均）
        weights = {
            QualityCriterion.RELEVANCE: 0.25,
            QualityCriterion.COMPLETENESS: 0.15,
            QualityCriterion.CONSISTENCY: 0.20,
            QualityCriterion.TONE: 0.15,
            QualityCriterion.ACTIONABILITY: 0.10,
            QualityCriterion.SAFETY: 0.15,
        }

        overall_score = sum(
            score.score * weights.get(score.criterion, 0.1)
            for score in scores
        )

        # 改善が必要か判断
        needs_refinement = (
            overall_score < OVERALL_REFINEMENT_THRESHOLD
            or any(issue.severity == IssueSeverity.CRITICAL for issue in issues)
        )

        # 改善の優先順位
        refinement_priority = self._determine_refinement_priority(issues)

        return CritiqueResult(
            scores=scores,
            issues=issues,
            overall_score=overall_score,
            needs_refinement=needs_refinement,
            refinement_priority=refinement_priority,
        )

    def refine(
        self,
        response: str,
        critique_result: CritiqueResult,
        original_message: str,
        context: Optional[Dict[str, Any]] = None
    ) -> RefinedResponse:
        """
        批判結果に基づいて回答を改善

        Args:
            response: 元の回答
            critique_result: 批判結果
            original_message: 元のユーザーメッセージ
            context: コンテキスト情報

        Returns:
            RefinedResponse: 改善された回答
        """
        start_time = datetime.now(JST)
        refined = response

        if not critique_result.needs_refinement:
            return RefinedResponse(
                original=response,
                refined=response,
                improvements=[],
                refinement_applied=False,
                refinement_time_ms=0,
            )

        applied_improvements = []

        # 優先度順に改善を適用
        for issue_type in critique_result.refinement_priority:
            matching_issues = [
                issue for issue in critique_result.issues
                if issue.issue_type == issue_type
            ]

            for issue in matching_issues:
                refined_text, applied = self._apply_fix(refined, issue, original_message, context)
                if applied:
                    refined = refined_text
                    applied_improvements.append(issue)

        # 改善後の時間を計算
        end_time = datetime.now(JST)
        refinement_time_ms = (end_time - start_time).total_seconds() * 1000

        return RefinedResponse(
            original=response,
            refined=refined,
            improvements=applied_improvements,
            refinement_applied=len(applied_improvements) > 0,
            refinement_time_ms=refinement_time_ms,
        )

    def evaluate_and_refine(
        self,
        response: str,
        original_message: str,
        context: Optional[Dict[str, Any]] = None
    ) -> RefinedResponse:
        """
        評価と改善を一括で実行

        Args:
            response: 生成された回答
            original_message: 元のユーザーメッセージ
            context: コンテキスト情報

        Returns:
            RefinedResponse: 改善された回答
        """
        critique_result = self.critique(response, original_message, context)
        return self.refine(response, critique_result, original_message, context)

    # ========================================================================
    # 品質評価メソッド
    # ========================================================================

    def _evaluate_relevance(
        self,
        response: str,
        original_message: str,
        context: Dict[str, Any]
    ) -> QualityScore:
        """
        関連性を評価

        質問に答えているかどうか
        """
        score = 1.0
        reasoning_parts = []

        # 質問キーワードが回答に反映されているか
        question_keywords = self._extract_keywords(original_message)
        response_lower = response.lower()

        matched_keywords = [kw for kw in question_keywords if kw in response_lower]
        keyword_match_ratio = len(matched_keywords) / max(len(question_keywords), 1)

        if keyword_match_ratio < 0.3:
            score -= 0.3
            reasoning_parts.append(f"キーワードの反映が少ない: {len(matched_keywords)}/{len(question_keywords)}")
        elif keyword_match_ratio >= 0.6:
            reasoning_parts.append(f"キーワードがよく反映されている: {len(matched_keywords)}/{len(question_keywords)}")

        # 質問形式への対応
        if "？" in original_message or "?" in original_message:
            # 質問には何らかの回答が含まれるべき
            answer_indicators = ["は", "です", "だよ", "ウル", "思う", "かな"]
            if not any(ind in response for ind in answer_indicators):
                score -= 0.2
                reasoning_parts.append("質問に対する回答が不明確")
            else:
                reasoning_parts.append("質問に回答している")

        # コンテキストとの整合性
        if context.get("expected_topic"):
            if context["expected_topic"].lower() not in response_lower:
                score -= 0.2
                reasoning_parts.append(f"期待されるトピック「{context['expected_topic']}」に言及なし")

        return QualityScore(
            criterion=QualityCriterion.RELEVANCE,
            score=max(0.0, min(1.0, score)),
            reasoning="; ".join(reasoning_parts) if reasoning_parts else "関連性は問題なし",
            details={"keyword_match_ratio": keyword_match_ratio, "matched_keywords": matched_keywords},
        )

    def _evaluate_completeness(
        self,
        response: str,
        original_message: str,
        context: Dict[str, Any]
    ) -> QualityScore:
        """
        完全性を評価

        必要な情報が揃っているか
        """
        score = 1.0
        reasoning_parts = []

        # 長さチェック
        response_length = len(response)
        if response_length < LENGTH_GUIDELINES["min"]:
            score -= 0.4
            reasoning_parts.append(f"短すぎる: {response_length}文字（最小{LENGTH_GUIDELINES['min']}文字）")
        elif response_length < LENGTH_GUIDELINES["ideal_min"]:
            score -= 0.2
            reasoning_parts.append(f"やや短い: {response_length}文字")
        elif response_length > LENGTH_GUIDELINES["max"]:
            score -= 0.3
            reasoning_parts.append(f"長すぎる: {response_length}文字（最大{LENGTH_GUIDELINES['max']}文字）")
        elif response_length > LENGTH_GUIDELINES["ideal_max"]:
            score -= 0.1
            reasoning_parts.append(f"やや長い: {response_length}文字")
        else:
            reasoning_parts.append(f"適切な長さ: {response_length}文字")

        # 文の途切れチェック
        for pattern in INCOMPLETE_SENTENCE_PATTERNS:
            if re.search(pattern, response):
                score -= 0.5
                reasoning_parts.append(f"文が途切れている（パターン: {pattern}）")
                break

        # 複数の質問への対応
        question_marks = original_message.count("？") + original_message.count("?")
        if question_marks > 1:
            # 複数の質問がある場合、それぞれに答えているか
            sentences = re.split(r"[。！!]", response)
            if len(sentences) < question_marks:
                score -= 0.2
                reasoning_parts.append(f"複数の質問（{question_marks}個）に対し回答が少ない（{len(sentences)}文）")

        return QualityScore(
            criterion=QualityCriterion.COMPLETENESS,
            score=max(0.0, min(1.0, score)),
            reasoning="; ".join(reasoning_parts) if reasoning_parts else "完全性は問題なし",
            details={"response_length": response_length},
        )

    def _evaluate_consistency(
        self,
        response: str,
        context: Dict[str, Any]
    ) -> QualityScore:
        """
        一貫性を評価

        矛盾がないか、前の発言と整合しているか
        """
        score = 1.0
        reasoning_parts = []

        # 回答内の矛盾チェック
        contradiction_pairs = [
            ("できる", "できない"),
            ("ある", "ない"),
            ("した", "していない"),
            ("はい", "いいえ"),
            ("必要", "不要"),
        ]

        for positive, negative in contradiction_pairs:
            if positive in response and negative in response:
                # 同じ文脈で両方出てきたら矛盾の可能性
                score -= 0.3
                reasoning_parts.append(f"潜在的な矛盾: 「{positive}」と「{negative}」が両方存在")

        # 前の発言との整合性
        if context.get("previous_response"):
            prev = context["previous_response"]
            # 前と真逆のことを言っていないか（簡易チェック）
            prev_positive = "できる" in prev or "ある" in prev or "はい" in prev
            curr_negative = "できない" in response or "ない" in response or "いいえ" in response

            if prev_positive and curr_negative:
                # 文脈次第では問題ないが、フラグを立てる
                reasoning_parts.append("前回の発言と異なる内容（意図的かもしれない）")

        if not reasoning_parts:
            reasoning_parts.append("一貫性は問題なし")

        return QualityScore(
            criterion=QualityCriterion.CONSISTENCY,
            score=max(0.0, min(1.0, score)),
            reasoning="; ".join(reasoning_parts),
            details={},
        )

    def _evaluate_tone(self, response: str) -> QualityScore:
        """
        トーンを評価

        ソウルくんらしい口調か
        """
        score = 1.0
        reasoning_parts = []

        # ソウルくんらしい表現があるか
        soulkun_matches = sum(
            1 for pattern in SOULKUN_TONE_PATTERNS
            if re.search(pattern, response)
        )

        if soulkun_matches == 0:
            score -= 0.3
            reasoning_parts.append("ソウルくんらしい表現がない（ウル、〜だね等）")
        elif soulkun_matches >= 2:
            reasoning_parts.append(f"ソウルくんらしい表現が{soulkun_matches}個ある")

        # 不適切なトーンがないか
        inappropriate_matches = []
        for pattern in INAPPROPRIATE_TONE_PATTERNS:
            if re.search(pattern, response):
                inappropriate_matches.append(pattern)

        if inappropriate_matches:
            score -= 0.2 * len(inappropriate_matches)
            reasoning_parts.append(f"不適切なトーン: {len(inappropriate_matches)}パターン検出")

        return QualityScore(
            criterion=QualityCriterion.TONE,
            score=max(0.0, min(1.0, score)),
            reasoning="; ".join(reasoning_parts) if reasoning_parts else "トーンは適切",
            details={"soulkun_matches": soulkun_matches, "inappropriate_matches": inappropriate_matches},
        )

    def _evaluate_actionability(
        self,
        response: str,
        original_message: str
    ) -> QualityScore:
        """
        行動可能性を評価

        次のアクションが明確か
        """
        score = 1.0
        reasoning_parts = []

        # 依頼への回答の場合、次のアクションが明確か
        request_indicators = ["して", "したい", "お願い", "ください", "頼む"]
        is_request = any(ind in original_message for ind in request_indicators)

        if is_request:
            # 依頼に対しては何らかのアクション表明が必要
            action_indicators = [
                "する", "した", "やる", "やった", "完了", "終わった",
                "できる", "できない", "わかった", "了解", "承知",
            ]
            has_action = any(ind in response for ind in action_indicators)

            if not has_action:
                score -= 0.3
                reasoning_parts.append("依頼に対するアクション表明がない")
            else:
                reasoning_parts.append("アクションを表明している")

        # 質問形式で終わっているか（確認を求めている）
        if response.rstrip().endswith(("？", "?")):
            reasoning_parts.append("確認を求める形で終わっている（次のアクションを促している）")

        if not reasoning_parts:
            reasoning_parts.append("行動可能性は問題なし")

        return QualityScore(
            criterion=QualityCriterion.ACTIONABILITY,
            score=max(0.0, min(1.0, score)),
            reasoning="; ".join(reasoning_parts),
            details={"is_request": is_request},
        )

    def _evaluate_safety(self, response: str) -> QualityScore:
        """
        安全性を評価

        機密情報や不適切な表現がないか
        """
        score = 1.0
        reasoning_parts = []
        detected_patterns = []

        # 機密情報パターンチェック
        for pattern in SENSITIVE_INFO_PATTERNS:
            if re.search(pattern, response):
                score -= 0.5
                detected_patterns.append(pattern)

        if detected_patterns:
            reasoning_parts.append(f"機密情報の可能性: {len(detected_patterns)}パターン検出")
        else:
            reasoning_parts.append("機密情報は検出されず")

        return QualityScore(
            criterion=QualityCriterion.SAFETY,
            score=max(0.0, min(1.0, score)),
            reasoning="; ".join(reasoning_parts),
            details={"detected_patterns": detected_patterns},
        )

    # ========================================================================
    # 問題検出メソッド
    # ========================================================================

    def _detect_issues(
        self,
        response: str,
        scores: List[QualityScore],
        original_message: str,
        context: Dict[str, Any]
    ) -> List[DetectedIssue]:
        """
        問題を検出
        """
        issues = []

        # スコアベースの問題検出
        for score in scores:
            threshold = QUALITY_THRESHOLDS.get(score.criterion, 0.7)
            if score.score < threshold:
                severity = self._determine_severity(score.score, threshold)
                issues.append(DetectedIssue(
                    issue_type=self._criterion_to_issue_type(score.criterion),
                    severity=severity,
                    description=score.reasoning,
                    suggestion=self._generate_suggestion(score.criterion, score),
                ))

        # パターンベースの問題検出
        pattern_issues = self._detect_pattern_issues(response, original_message)
        issues.extend(pattern_issues)

        return issues

    def _detect_pattern_issues(
        self,
        response: str,
        original_message: str
    ) -> List[DetectedIssue]:
        """
        パターンベースで問題を検出
        """
        issues = []

        # 文の途切れ
        for pattern in INCOMPLETE_SENTENCE_PATTERNS:
            match = re.search(pattern, response)
            if match:
                issues.append(DetectedIssue(
                    issue_type=IssueType.INCOMPLETE_SENTENCE,
                    severity=IssueSeverity.CRITICAL,
                    description=f"文が途切れている: 「{response[-20:]}」",
                    location=match.group(),
                    suggestion="文を完結させる",
                ))
                break  # 最初の1つだけ

        # 長すぎる
        if len(response) > LENGTH_GUIDELINES["max"]:
            issues.append(DetectedIssue(
                issue_type=IssueType.TOO_LONG,
                severity=IssueSeverity.MEDIUM,
                description=f"回答が長すぎる: {len(response)}文字",
                suggestion=f"{LENGTH_GUIDELINES['ideal_max']}文字程度に要約する",
            ))

        # 短すぎる
        if len(response) < LENGTH_GUIDELINES["min"]:
            issues.append(DetectedIssue(
                issue_type=IssueType.TOO_SHORT,
                severity=IssueSeverity.HIGH,
                description=f"回答が短すぎる: {len(response)}文字",
                suggestion="もう少し詳しく回答する",
            ))

        return issues

    def _determine_severity(self, score: float, threshold: float) -> IssueSeverity:
        """
        スコアから深刻度を判定
        """
        gap = threshold - score
        if gap > 0.4:
            return IssueSeverity.CRITICAL
        elif gap > 0.2:
            return IssueSeverity.HIGH
        elif gap > 0.1:
            return IssueSeverity.MEDIUM
        else:
            return IssueSeverity.LOW

    def _criterion_to_issue_type(self, criterion: QualityCriterion) -> IssueType:
        """
        品質基準から問題タイプに変換
        """
        mapping = {
            QualityCriterion.RELEVANCE: IssueType.OFF_TOPIC,
            QualityCriterion.COMPLETENESS: IssueType.MISSING_INFO,
            QualityCriterion.CONSISTENCY: IssueType.CONTRADICTION,
            QualityCriterion.TONE: IssueType.WRONG_TONE,
            QualityCriterion.ACTIONABILITY: IssueType.UNCLEAR_ACTION,
            QualityCriterion.SAFETY: IssueType.SENSITIVE_INFO,
        }
        return mapping.get(criterion, IssueType.MISSING_INFO)

    def _generate_suggestion(
        self,
        criterion: QualityCriterion,
        score: QualityScore
    ) -> str:
        """
        改善提案を生成
        """
        suggestions = {
            QualityCriterion.RELEVANCE: "質問のキーワードを回答に含める",
            QualityCriterion.COMPLETENESS: "必要な情報を追加する",
            QualityCriterion.CONSISTENCY: "矛盾を解消する",
            QualityCriterion.TONE: "「ウル」「〜だね」などソウルくんらしい表現を追加",
            QualityCriterion.ACTIONABILITY: "次のアクションを明確にする",
            QualityCriterion.SAFETY: "機密情報を削除する",
        }
        return suggestions.get(criterion, "品質を改善する")

    def _determine_refinement_priority(
        self,
        issues: List[DetectedIssue]
    ) -> List[IssueType]:
        """
        改善の優先順位を決定
        """
        # 深刻度順にソート
        severity_order = {
            IssueSeverity.CRITICAL: 0,
            IssueSeverity.HIGH: 1,
            IssueSeverity.MEDIUM: 2,
            IssueSeverity.LOW: 3,
        }

        sorted_issues = sorted(
            issues,
            key=lambda i: severity_order.get(i.severity, 99)
        )

        # 重複を除いて問題タイプのリストを返す
        seen = set()
        priority = []
        for issue in sorted_issues:
            if issue.issue_type not in seen:
                seen.add(issue.issue_type)
                priority.append(issue.issue_type)

        return priority

    # ========================================================================
    # 改善適用メソッド
    # ========================================================================

    def _apply_fix(
        self,
        response: str,
        issue: DetectedIssue,
        original_message: str,
        context: Optional[Dict[str, Any]]
    ) -> Tuple[str, bool]:
        """
        問題を修正

        Args:
            response: 現在の回答
            issue: 問題
            original_message: 元のメッセージ
            context: コンテキスト

        Returns:
            (修正後の回答, 修正が適用されたか)
        """
        if issue.issue_type == IssueType.INCOMPLETE_SENTENCE:
            return self._fix_incomplete_sentence(response), True

        elif issue.issue_type == IssueType.WRONG_TONE:
            return self._fix_tone(response), True

        elif issue.issue_type == IssueType.TOO_SHORT:
            return self._fix_too_short(response, original_message), True

        elif issue.issue_type == IssueType.SENSITIVE_INFO:
            return self._fix_sensitive_info(response), True

        # その他の問題はLLMが必要（現在は未対応）
        return response, False

    def _fix_incomplete_sentence(self, response: str) -> str:
        """
        途切れた文を修正（トーン付与はLLMに任せる）
        """
        # 助詞で終わっている場合、適切な終わり方を追加
        if re.search(r"[をにがはでとへもの]$", response):
            response = response.rstrip("をにがはでとへもの")
            response += "..."

        # 読点で終わっている場合
        if response.endswith("、"):
            response = response.rstrip("、")
            response += "。"

        return response

    def _fix_tone(self, response: str) -> str:
        """
        トーンを修正（ウル付与はLLMのシステムプロンプトで頻度制御するため、
        ここでは硬い表現を柔らかくするだけに留める）
        """
        # 硬い終わり方を柔らかくする
        if response.endswith("です。"):
            response = response[:-2] + "だよ。"
        elif response.endswith("ます。"):
            response = response[:-1] + "！"

        return response

    def _fix_too_short(self, response: str, original_message: str) -> str:
        """
        短すぎる回答を修正（トーン付与はLLMに任せる）
        """
        # 最低限の補足を追加
        if len(response) < 10:
            if "？" in original_message or "?" in original_message:
                response += " 詳しく知りたいことがあれば聞いてね！"
            else:
                response += " 他に何かあれば言ってね！"

        return response

    def _fix_sensitive_info(self, response: str) -> str:
        """
        機密情報を削除
        """
        for pattern in SENSITIVE_INFO_PATTERNS:
            response = re.sub(pattern, "[機密情報]", response)

        return response

    # ========================================================================
    # ユーティリティ
    # ========================================================================

    def _extract_keywords(self, message: str) -> List[str]:
        """
        メッセージからキーワードを抽出
        """
        # 簡易的なキーワード抽出
        # 助詞や記号を除いた名詞的な単語を抽出
        words = re.findall(r"[一-龠ぁ-んァ-ン]+", message)
        # 短すぎる単語と助詞を除外
        stopwords = {"の", "は", "が", "を", "に", "で", "と", "も", "や", "へ", "から", "まで", "より"}
        keywords = [w for w in words if len(w) > 1 and w not in stopwords]
        return keywords


# ============================================================================
# ファクトリ関数
# ============================================================================

def create_self_critique(llm_client=None) -> SelfCritique:
    """
    SelfCritiqueインスタンスを作成

    Args:
        llm_client: LLMクライアント（オプション）

    Returns:
        SelfCritique インスタンス
    """
    return SelfCritique(llm_client=llm_client)
