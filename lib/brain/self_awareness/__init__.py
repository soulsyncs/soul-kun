"""
Phase 2H: 自己認識（Self-Awareness）モジュール

設計書: docs/17_brain_completion_roadmap.md セクション Phase 2H

能力の自己評価、限界の認識、改善点の自己発見を提供する。

使用例:
    from lib.brain.self_awareness import BrainSelfAwareness, create_self_awareness

    # 統合クラスを使用
    awareness = create_self_awareness(organization_id)

    # 確信度評価
    assessment = awareness.assess_confidence(
        category=AbilityCategory.KNOWLEDGE_SEARCH,
        context={"query": "...", "results": [...]},
    )

    # 能力スコア更新
    awareness.record_interaction_result(
        conn=conn,
        category=AbilityCategory.TASK_MANAGEMENT,
        success=True,
    )

    # 自己診断実行
    diagnosis = awareness.run_self_diagnosis(conn)
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.engine import Connection

from .constants import (
    # Enums
    AbilityCategory,
    AbilityLevel,
    ConfidenceLevel,
    DiagnosisType,
    EscalationReason,
    ImprovementType,
    LimitationType,
    # Thresholds
    ABILITY_LEVEL_THRESHOLDS,
    ABILITY_SCORE_DEFAULT,
    AUTO_ESCALATION_ENABLED,
    CONFIDENCE_LEVEL_THRESHOLDS,
    CONFIDENCE_THRESHOLD_HIGH,
    CONFIDENCE_THRESHOLD_LOW,
    CONFIDENCE_THRESHOLD_MEDIUM,
    CONFIRMATION_TEMPLATES,
    DEFAULT_ABILITY_SCORES,
    DIAGNOSIS_MIN_INTERACTIONS,
    DIAGNOSIS_REPORT_MAX_ITEMS,
    ESCALATION_CONFIDENCE_THRESHOLD,
    ESCALATION_DOMAINS,
    IMPROVEMENT_THRESHOLD,
    REGRESSION_THRESHOLD,
    SCORE_UPDATE_WEIGHT_FAILURE,
    SCORE_UPDATE_WEIGHT_SUCCESS,
    UNCERTAINTY_KEYWORDS,
    # Tables
    TABLE_BRAIN_ABILITIES,
    TABLE_BRAIN_ABILITY_SCORES,
    TABLE_BRAIN_IMPROVEMENT_LOGS,
    TABLE_BRAIN_LIMITATIONS,
    TABLE_BRAIN_SELF_DIAGNOSES,
)
from .models import (
    Ability,
    AbilityScore,
    AbilitySummary,
    ConfidenceAssessment,
    ImprovementLog,
    Limitation,
    SelfDiagnosis,
)


logger = logging.getLogger(__name__)


class BrainSelfAwareness:
    """自己認識統合クラス

    Phase 2Hの全機能を統合して提供する。

    主な機能:
    1. 確信度評価（assess_confidence）
    2. 能力スコア管理（record_interaction_result, get_ability_score）
    3. 限界管理（record_limitation, get_limitations）
    4. 自己診断（run_self_diagnosis）
    """

    def __init__(
        self,
        organization_id: str,
    ):
        """初期化

        Args:
            organization_id: 組織ID
        """
        self.organization_id = organization_id

        # インメモリキャッシュ（DBロード前の一時保存）
        self._ability_scores_cache: Dict[str, AbilityScore] = {}
        self._limitations_cache: Dict[str, Limitation] = {}

        # v11.2.0 P15: org_idは生値でなく先頭8文字のみログ出力（CLAUDE.md §9-3 PII保護）
        logger.info(f"BrainSelfAwareness initialized for org: {(organization_id or '')[:8]}...")

    # ========================================================================
    # 確信度評価
    # ========================================================================

    def assess_confidence(
        self,
        category: AbilityCategory,
        context: Optional[Dict[str, Any]] = None,
        message: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> ConfidenceAssessment:
        """確信度を評価

        Args:
            category: 能力カテゴリ
            context: コンテキスト情報
            message: 回答メッセージ（不確実性キーワードチェック用）
            user_id: ユーザーID

        Returns:
            確信度評価結果
        """
        context = context or {}

        # 1. 知識の確信度を計算
        knowledge_confidence = self._calculate_knowledge_confidence(category, context)

        # 2. 文脈理解の確信度を計算
        context_confidence = self._calculate_context_confidence(context)

        # 3. 過去の正確性を取得
        historical_accuracy = self._get_historical_accuracy(category, user_id)

        # 4. メッセージ内の不確実性をチェック
        uncertainty_factors = []
        if message:
            uncertainty_factors = self._detect_uncertainty_in_message(message)
            # 不確実性キーワードがあればスコアを下げる
            if uncertainty_factors:
                knowledge_confidence *= 0.8

        # 5. 確信度評価を作成
        assessment = ConfidenceAssessment(
            knowledge_confidence=knowledge_confidence,
            context_confidence=context_confidence,
            historical_accuracy=historical_accuracy,
            uncertainty_factors=uncertainty_factors,
        )

        # 6. エスカレーション判定
        if assessment.needs_escalation and AUTO_ESCALATION_ENABLED:
            assessment.escalation_reason = EscalationReason.LOW_CONFIDENCE
            assessment.escalation_target = self._determine_escalation_target(category, context)

        # 7. 確認メッセージを設定
        assessment.confidence_message = CONFIRMATION_TEMPLATES.get(
            assessment.confidence_level, ""
        )

        return assessment

    def _calculate_knowledge_confidence(
        self,
        category: AbilityCategory,
        context: Dict[str, Any],
    ) -> float:
        """知識の確信度を計算"""
        # 基本スコアはカテゴリのデフォルト
        base_score = DEFAULT_ABILITY_SCORES.get(category, 0.5)

        # コンテキストから追加情報があれば調整
        if context.get("has_source"):
            base_score += 0.1  # ソースがあれば上げる
        if context.get("is_recent"):
            base_score += 0.05  # 最新情報なら上げる
        if context.get("is_verified"):
            base_score += 0.1  # 検証済みなら上げる

        return min(1.0, max(0.0, base_score))

    def _calculate_context_confidence(
        self,
        context: Dict[str, Any],
    ) -> float:
        """文脈理解の確信度を計算"""
        score = 0.5

        # コンテキストの充実度で判定
        if context.get("has_history"):
            score += 0.15
        if context.get("clear_intent"):
            score += 0.2
        if context.get("specific_request"):
            score += 0.1

        # 曖昧な要素があれば下げる
        if context.get("ambiguous"):
            score -= 0.2
        if context.get("conflicting"):
            score -= 0.3

        return min(1.0, max(0.0, score))

    def _get_historical_accuracy(
        self,
        category: AbilityCategory,
        user_id: Optional[str],
    ) -> float:
        """過去の正確性を取得"""
        # キャッシュからスコアを取得
        cache_key = f"{category.value}:{user_id or 'org'}"
        if cache_key in self._ability_scores_cache:
            return self._ability_scores_cache[cache_key].success_rate

        # デフォルト値を返す
        return DEFAULT_ABILITY_SCORES.get(category, 0.5)

    def _detect_uncertainty_in_message(
        self,
        message: str,
    ) -> List[str]:
        """メッセージ内の不確実性を検出"""
        found = []
        for keyword in UNCERTAINTY_KEYWORDS:
            if keyword in message:
                found.append(keyword)
        return found

    def _determine_escalation_target(
        self,
        category: AbilityCategory,
        context: Dict[str, Any],
    ) -> Optional[str]:
        """エスカレーション先を決定"""
        # コンテキストのドメインからエスカレーション先を判定
        domain = context.get("domain", "")
        for domain_key, target in ESCALATION_DOMAINS.items():
            if domain_key in domain:
                return target

        # カテゴリからデフォルトを返す
        category_escalation = {
            AbilityCategory.TASK_MANAGEMENT: "manager",
            AbilityCategory.KNOWLEDGE_SEARCH: "knowledge_admin",
            AbilityCategory.GOAL_SUPPORT: "hr_expert",
        }
        return category_escalation.get(category, "admin")

    # ========================================================================
    # 能力スコア管理
    # ========================================================================

    def record_interaction_result(
        self,
        conn: Optional[Connection],
        category: AbilityCategory,
        success: bool,
        user_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> AbilityScore:
        """インタラクション結果を記録し、能力スコアを更新

        Args:
            conn: DB接続（Noneならキャッシュのみ更新）
            category: 能力カテゴリ
            success: 成功したか
            user_id: ユーザーID
            context: コンテキスト情報

        Returns:
            更新された能力スコア
        """
        cache_key = f"{category.value}:{user_id or 'org'}"

        # キャッシュから取得または新規作成
        if cache_key in self._ability_scores_cache:
            score = self._ability_scores_cache[cache_key]
        else:
            score = AbilityScore(
                organization_id=self.organization_id,
                user_id=user_id,
                category=category,
                score=DEFAULT_ABILITY_SCORES.get(category, ABILITY_SCORE_DEFAULT),
            )
            self._ability_scores_cache[cache_key] = score

        # スコア更新
        weight = SCORE_UPDATE_WEIGHT_SUCCESS if success else SCORE_UPDATE_WEIGHT_FAILURE
        score.update_score(success, weight)

        logger.debug(
            f"Updated ability score: category={category.value}, "
            f"success={success}, new_score={score.score:.3f}"
        )

        return score

    def get_ability_score(
        self,
        category: AbilityCategory,
        user_id: Optional[str] = None,
    ) -> AbilityScore:
        """能力スコアを取得

        Args:
            category: 能力カテゴリ
            user_id: ユーザーID

        Returns:
            能力スコア
        """
        cache_key = f"{category.value}:{user_id or 'org'}"

        if cache_key in self._ability_scores_cache:
            return self._ability_scores_cache[cache_key]

        # 新規作成
        score = AbilityScore(
            organization_id=self.organization_id,
            user_id=user_id,
            category=category,
            score=DEFAULT_ABILITY_SCORES.get(category, ABILITY_SCORE_DEFAULT),
        )
        self._ability_scores_cache[cache_key] = score
        return score

    def get_ability_summary(
        self,
        user_id: Optional[str] = None,
    ) -> AbilitySummary:
        """能力サマリーを取得

        Args:
            user_id: ユーザーID（None=組織全体）

        Returns:
            能力サマリー
        """
        # カテゴリ別スコアを収集
        category_scores = {}
        strengths = []
        weaknesses = []

        for category in AbilityCategory:
            score = self.get_ability_score(category, user_id)
            category_scores[category.value] = score.score

            if score.is_strong:
                strengths.append({
                    "category": category.value,
                    "score": score.score,
                    "level": score.level.value,
                })
            elif score.is_weak:
                weaknesses.append({
                    "category": category.value,
                    "score": score.score,
                    "level": score.level.value,
                })

        # 全体スコアを計算
        overall_score = sum(category_scores.values()) / len(category_scores) if category_scores else 0.5

        # 全体レベルを判定
        overall_level = AbilityLevel.DEVELOPING
        for level, (low, high) in ABILITY_LEVEL_THRESHOLDS.items():
            if low <= overall_score < high:
                overall_level = level
                break

        return AbilitySummary(
            organization_id=self.organization_id,
            user_id=user_id,
            overall_score=overall_score,
            overall_level=overall_level,
            category_scores=category_scores,
            strengths=strengths,
            weaknesses=weaknesses,
            total_abilities=len(category_scores),
        )

    # ========================================================================
    # 限界管理
    # ========================================================================

    def record_limitation(
        self,
        limitation_type: LimitationType,
        description: str,
        category: Optional[AbilityCategory] = None,
        keywords: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
        escalation_target: Optional[str] = None,
    ) -> Limitation:
        """限界を記録

        Args:
            limitation_type: 限界タイプ
            description: 説明
            category: 関連する能力カテゴリ
            keywords: キーワード
            context: コンテキスト
            escalation_target: エスカレーション先

        Returns:
            限界情報
        """
        # 既存の限界を検索
        cache_key = f"{limitation_type.value}:{description[:50]}"
        if cache_key in self._limitations_cache:
            limitation = self._limitations_cache[cache_key]
            limitation.increment_occurrence()
            return limitation

        # 新規作成
        limitation = Limitation(
            organization_id=self.organization_id,
            limitation_type=limitation_type,
            description=description,
            category=category,
            keywords=keywords or [],
            context=context or {},
            escalation_target=escalation_target,
        )
        self._limitations_cache[cache_key] = limitation

        logger.info(f"Recorded limitation: type={limitation_type.value}, desc={description[:50]}")

        return limitation

    def get_limitations(
        self,
        limitation_type: Optional[LimitationType] = None,
        category: Optional[AbilityCategory] = None,
        limit: int = 10,
    ) -> List[Limitation]:
        """限界リストを取得

        Args:
            limitation_type: フィルタ - 限界タイプ
            category: フィルタ - 能力カテゴリ
            limit: 最大件数

        Returns:
            限界リスト
        """
        limitations = list(self._limitations_cache.values())

        # フィルタ適用
        if limitation_type:
            limitations = [l for l in limitations if l.limitation_type == limitation_type]
        if category:
            limitations = [l for l in limitations if l.category == category]

        # 発生回数で降順ソート
        limitations.sort(key=lambda x: x.occurrence_count, reverse=True)

        return limitations[:limit]

    # ========================================================================
    # 自己診断
    # ========================================================================

    def run_self_diagnosis(
        self,
        conn: Optional[Connection] = None,
        diagnosis_type: DiagnosisType = DiagnosisType.DAILY,
    ) -> SelfDiagnosis:
        """自己診断を実行

        Args:
            conn: DB接続
            diagnosis_type: 診断タイプ

        Returns:
            診断結果
        """
        # 能力サマリーを取得
        summary = self.get_ability_summary()

        # 限界を取得
        limitations = self.get_limitations(limit=DIAGNOSIS_REPORT_MAX_ITEMS)

        # 診断結果を作成
        diagnosis = SelfDiagnosis(
            organization_id=self.organization_id,
            diagnosis_type=diagnosis_type,
            overall_score=summary.overall_score,
            strong_abilities=[s["category"] for s in summary.strengths],
            weak_abilities=[w["category"] for w in summary.weaknesses],
            frequent_limitations=[l.to_dict() for l in limitations[:5]],
        )

        # 推奨事項を生成
        diagnosis.recommendations = self._generate_recommendations(summary, limitations)
        diagnosis.focus_areas = [w["category"] for w in summary.weaknesses[:3]]

        logger.info(
            f"Self diagnosis completed: overall_score={summary.overall_score:.3f}, "
            f"strengths={len(summary.strengths)}, weaknesses={len(summary.weaknesses)}"
        )

        return diagnosis

    def _generate_recommendations(
        self,
        summary: AbilitySummary,
        limitations: List[Limitation],
    ) -> List[str]:
        """推奨事項を生成"""
        recommendations = []

        # 弱い分野についての推奨
        for weakness in summary.weaknesses[:3]:
            category = weakness["category"]
            recommendations.append(
                f"「{category}」の改善に注力することをお勧めします"
            )

        # 頻出する限界についての推奨
        for limitation in limitations[:2]:
            if limitation.occurrence_count >= 3:
                recommendations.append(
                    f"「{limitation.description[:30]}...」への対応策の検討をお勧めします"
                )

        return recommendations

    # ========================================================================
    # 便利メソッド
    # ========================================================================

    def should_add_confirmation(
        self,
        category: AbilityCategory,
        context: Optional[Dict[str, Any]] = None,
    ) -> tuple[bool, str]:
        """確認メッセージを追加すべきか判定

        Args:
            category: 能力カテゴリ
            context: コンテキスト

        Returns:
            (追加すべきか, 追加するメッセージ)
        """
        assessment = self.assess_confidence(category, context)

        if assessment.needs_confirmation:
            return True, assessment.confidence_message

        return False, ""

    def should_escalate(
        self,
        category: AbilityCategory,
        context: Optional[Dict[str, Any]] = None,
    ) -> tuple[bool, Optional[str], Optional[str]]:
        """エスカレーションすべきか判定

        Args:
            category: 能力カテゴリ
            context: コンテキスト

        Returns:
            (エスカレーションすべきか, 理由, エスカレーション先)
        """
        assessment = self.assess_confidence(category, context)

        if assessment.needs_escalation:
            return (
                True,
                assessment.escalation_reason.value if assessment.escalation_reason else None,
                assessment.escalation_target,
            )

        return False, None, None

    def get_confidence_message(
        self,
        category: AbilityCategory,
        context: Optional[Dict[str, Any]] = None,
        message: Optional[str] = None,
    ) -> str:
        """確信度に応じたメッセージを取得

        Args:
            category: 能力カテゴリ
            context: コンテキスト
            message: 回答メッセージ

        Returns:
            確認メッセージ（不要な場合は空文字）
        """
        assessment = self.assess_confidence(category, context, message)
        return assessment.confidence_message


# ============================================================================
# ファクトリ関数
# ============================================================================

def create_self_awareness(organization_id: str) -> BrainSelfAwareness:
    """BrainSelfAwarenessを生成

    Args:
        organization_id: 組織ID

    Returns:
        BrainSelfAwarenessインスタンス
    """
    return BrainSelfAwareness(organization_id)


# ============================================================================
# エクスポート
# ============================================================================

__all__ = [
    # 統合クラス
    "BrainSelfAwareness",
    "create_self_awareness",
    # モデル
    "Ability",
    "AbilityScore",
    "AbilitySummary",
    "ConfidenceAssessment",
    "ImprovementLog",
    "Limitation",
    "SelfDiagnosis",
    # Enums
    "AbilityCategory",
    "AbilityLevel",
    "ConfidenceLevel",
    "DiagnosisType",
    "EscalationReason",
    "ImprovementType",
    "LimitationType",
    # 定数
    "ABILITY_LEVEL_THRESHOLDS",
    "ABILITY_SCORE_DEFAULT",
    "AUTO_ESCALATION_ENABLED",
    "CONFIDENCE_LEVEL_THRESHOLDS",
    "CONFIDENCE_THRESHOLD_HIGH",
    "CONFIDENCE_THRESHOLD_LOW",
    "CONFIDENCE_THRESHOLD_MEDIUM",
    "CONFIRMATION_TEMPLATES",
    "DEFAULT_ABILITY_SCORES",
    "ESCALATION_CONFIDENCE_THRESHOLD",
    "ESCALATION_DOMAINS",
    "UNCERTAINTY_KEYWORDS",
    # テーブル
    "TABLE_BRAIN_ABILITIES",
    "TABLE_BRAIN_ABILITY_SCORES",
    "TABLE_BRAIN_IMPROVEMENT_LOGS",
    "TABLE_BRAIN_LIMITATIONS",
    "TABLE_BRAIN_SELF_DIAGNOSES",
]
