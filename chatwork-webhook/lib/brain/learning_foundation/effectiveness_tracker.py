"""
Phase 2E: 学習基盤 - 有効性追跡層

設計書: docs/18_phase2e_learning_foundation.md v1.1.0
セクション: 7. Phase 2N準備（有効性追跡）

学習の有効性を追跡し、改善提案を生成する。
Phase 2Nで本格実装予定の機能の基盤を提供する。
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.engine import Connection

from .constants import (
    AuthorityLevel,
    DecisionImpact,
    LearningCategory,
    DEFAULT_CONFIDENCE_DECAY_RATE,
)
from .models import (
    EffectivenessResult,
    ImprovementSuggestion,
    Learning,
    LearningLog,
)
from .repository import LearningRepository


@dataclass
class EffectivenessMetrics:
    """有効性メトリクス"""
    apply_count: int = 0
    positive_feedback_count: int = 0
    negative_feedback_count: int = 0
    feedback_ratio: float = 0.0  # positive / (positive + negative)
    days_since_creation: int = 0
    days_since_last_apply: Optional[int] = None
    confidence_score: float = 1.0  # 減衰後の確信度


@dataclass
class LearningHealth:
    """学習の健全性"""
    learning_id: str
    category: str
    status: str  # healthy, warning, critical, stale
    metrics: EffectivenessMetrics
    issues: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)


class EffectivenessTracker:
    """有効性追跡クラス

    学習の有効性を追跡し、
    改善提案を生成する。

    Phase 2Nで本格実装予定の機能の基盤。
    """

    def __init__(
        self,
        organization_id: str,
        repository: Optional[LearningRepository] = None,
        confidence_decay_rate: float = DEFAULT_CONFIDENCE_DECAY_RATE,
    ):
        """初期化

        Args:
            organization_id: 組織ID
            repository: リポジトリ
            confidence_decay_rate: 確信度減衰率（1日あたり）
        """
        self.organization_id = organization_id
        self.repository = repository or LearningRepository(organization_id)
        self.confidence_decay_rate = confidence_decay_rate

    # ========================================================================
    # 有効性計算
    # ========================================================================

    def calculate_effectiveness(
        self,
        learning: Learning,
        logs: Optional[List[LearningLog]] = None,
    ) -> EffectivenessResult:
        """学習の有効性を計算

        Args:
            learning: 学習
            logs: 適用ログ（指定しない場合はカウンタから計算）

        Returns:
            有効性結果
        """
        # メトリクスを計算
        metrics = self._calculate_metrics(learning)

        # スコアを計算
        score = self._calculate_score(metrics)

        # 改善提案を生成
        suggestions = self._generate_suggestions(learning, metrics)

        # 推奨アクションを決定
        recommendation = self._determine_recommendation(score, metrics)

        if not learning.id:
            raise ValueError("learning.id is required for effectiveness calculation")

        return EffectivenessResult(
            learning_id=learning.id,
            total_applications=metrics.apply_count,
            successful_applications=metrics.positive_feedback_count,
            failed_applications=metrics.negative_feedback_count,
            positive_feedbacks=metrics.positive_feedback_count,
            negative_feedbacks=metrics.negative_feedback_count,
            effectiveness_score=score,
            recommendation=recommendation,
        )

    def calculate_effectiveness_batch(
        self,
        conn: Connection,
        learnings: Optional[List[Learning]] = None,
    ) -> List[EffectivenessResult]:
        """複数学習の有効性を一括計算

        Args:
            conn: DB接続
            learnings: 学習のリスト（指定しない場合は全件）

        Returns:
            有効性結果のリスト
        """
        if learnings is None:
            learnings, _ = self.repository.find_all(conn, active_only=True)

        results = []
        for learning in learnings:
            result = self.calculate_effectiveness(learning)
            results.append(result)

        return results

    def _calculate_metrics(
        self,
        learning: Learning,
    ) -> EffectivenessMetrics:
        """メトリクスを計算

        Args:
            learning: 学習

        Returns:
            メトリクス
        """
        now = datetime.now()

        # 適用回数
        apply_count = learning.applied_count or 0

        # フィードバック（success/failure countをpositive/negativeとして使用）
        positive = learning.success_count or 0
        negative = learning.failure_count or 0
        total_feedback = positive + negative
        feedback_ratio = positive / total_feedback if total_feedback > 0 else 0.0

        # 経過日数
        created_at = learning.created_at or now
        days_since_creation = (now - created_at).days

        # 最終適用からの日数（updated_atで近似）
        updated_at = learning.updated_at or created_at
        days_since_last_apply = (now - updated_at).days

        # 確信度の減衰
        decay = self.confidence_decay_rate * days_since_creation
        confidence_score = max(0.0, 1.0 - decay)

        return EffectivenessMetrics(
            apply_count=apply_count,
            positive_feedback_count=positive,
            negative_feedback_count=negative,
            feedback_ratio=feedback_ratio,
            days_since_creation=days_since_creation,
            days_since_last_apply=days_since_last_apply,
            confidence_score=confidence_score,
        )

    def _calculate_score(
        self,
        metrics: EffectivenessMetrics,
    ) -> float:
        """有効性スコアを計算

        スコア計算式:
        - 基本スコア: フィードバック比率 * 0.4 + 使用頻度スコア * 0.3 + 確信度 * 0.3
        - 使用頻度スコア: min(1.0, apply_count / 10)  # 10回で最大

        Args:
            metrics: メトリクス

        Returns:
            有効性スコア（0.0〜1.0）
        """
        # フィードバック比率（フィードバックがない場合は0.5とする）
        if metrics.positive_feedback_count + metrics.negative_feedback_count == 0:
            feedback_score = 0.5
        else:
            feedback_score = metrics.feedback_ratio

        # 使用頻度スコア
        frequency_score = min(1.0, metrics.apply_count / 10.0)

        # 確信度
        confidence_score = metrics.confidence_score

        # 総合スコア
        score = (
            feedback_score * 0.4 +
            frequency_score * 0.3 +
            confidence_score * 0.3
        )

        return round(score, 3)

    def _determine_recommendation(
        self,
        score: float,
        metrics: EffectivenessMetrics,
    ) -> str:
        """推奨アクションを決定

        Args:
            score: 有効性スコア
            metrics: メトリクス

        Returns:
            推奨アクション: 'keep', 'review', 'deactivate'
        """
        # 適用されていない学習は'review'
        if metrics.apply_count == 0 and metrics.days_since_creation > 30:
            return "review"

        # スコアが低い場合は'deactivate'を検討
        if score < 0.3:
            return "deactivate"

        # スコアが中程度の場合は'review'
        if score < 0.5:
            return "review"

        # 高スコアは'keep'
        return "keep"

    def _generate_suggestions(
        self,
        learning: Learning,
        metrics: EffectivenessMetrics,
    ) -> List[ImprovementSuggestion]:
        """改善提案を生成

        Args:
            learning: 学習
            metrics: メトリクス

        Returns:
            改善提案のリスト
        """
        suggestions = []

        learning_id = learning.id or ""

        # フィードバック比率が低い
        if metrics.feedback_ratio < 0.5 and metrics.negative_feedback_count >= 3:
            suggestions.append(ImprovementSuggestion(
                suggestion_type="review_content",
                description=f"ネガティブフィードバックが多いです（{metrics.negative_feedback_count}件）。内容を見直すことをお勧めします。",
                priority="high",
                learning_id=learning_id,
            ))

        # 長期間使用されていない
        if metrics.days_since_last_apply and metrics.days_since_last_apply > 90:
            suggestions.append(ImprovementSuggestion(
                suggestion_type="check_relevance",
                description=f"{metrics.days_since_last_apply}日間適用されていません。まだ必要な学習か確認してください。",
                priority="medium",
                learning_id=learning_id,
            ))

        # 一度も使用されていない
        if metrics.apply_count == 0 and metrics.days_since_creation > 30:
            suggestions.append(ImprovementSuggestion(
                suggestion_type="unused",
                description="30日以上経過していますが一度も適用されていません。トリガー条件を見直すか、削除を検討してください。",
                priority="medium",
                learning_id=learning_id,
            ))

        # 確信度が低下
        if metrics.confidence_score < 0.5:
            suggestions.append(ImprovementSuggestion(
                suggestion_type="refresh",
                description="時間経過により確信度が低下しています。内容が現在も正しいか確認してください。",
                priority="low",
                learning_id=learning_id,
            ))

        return suggestions

    # ========================================================================
    # 健全性チェック
    # ========================================================================

    def check_health(
        self,
        learning: Learning,
    ) -> LearningHealth:
        """学習の健全性をチェック

        Args:
            learning: 学習

        Returns:
            健全性結果
        """
        metrics = self._calculate_metrics(learning)
        issues = []
        suggestions = []

        # ステータス判定
        status = "healthy"

        # Critical条件
        if metrics.feedback_ratio < 0.3 and metrics.negative_feedback_count >= 5:
            status = "critical"
            issues.append("ネガティブフィードバックが非常に多い")
            suggestions.append("内容を大幅に見直すか、削除を検討してください")

        # Warning条件
        elif metrics.feedback_ratio < 0.5 and metrics.negative_feedback_count >= 3:
            status = "warning"
            issues.append("ネガティブフィードバックが多い")
            suggestions.append("内容を見直してください")

        # Stale条件
        elif metrics.days_since_last_apply and metrics.days_since_last_apply > 180:
            status = "stale"
            issues.append("長期間使用されていない")
            suggestions.append("まだ必要か確認してください")

        # 未使用
        elif metrics.apply_count == 0 and metrics.days_since_creation > 60:
            status = "warning"
            issues.append("一度も使用されていない")
            suggestions.append("トリガー条件を見直してください")

        return LearningHealth(
            learning_id=learning.id or "",  # Empty string fallback for health check display
            category=learning.category,
            status=status,
            metrics=metrics,
            issues=issues,
            suggestions=suggestions,
        )

    def check_health_batch(
        self,
        conn: Connection,
        learnings: Optional[List[Learning]] = None,
    ) -> Dict[str, List[LearningHealth]]:
        """複数学習の健全性を一括チェック

        Args:
            conn: DB接続
            learnings: 学習のリスト

        Returns:
            ステータス別の健全性結果
        """
        if learnings is None:
            learnings, _ = self.repository.find_all(conn, active_only=True)

        result: Dict[str, List[LearningHealth]] = {
            "healthy": [],
            "warning": [],
            "critical": [],
            "stale": [],
        }

        for learning in learnings:
            health = self.check_health(learning)
            if health.status in result:
                result[health.status].append(health)

        return result

    # ========================================================================
    # フィードバック記録
    # ========================================================================

    def record_feedback(
        self,
        conn: Connection,
        learning_id: str,
        impact: DecisionImpact,
        context: Optional[str] = None,
    ) -> bool:
        """フィードバックを記録

        Args:
            conn: DB接続
            learning_id: 学習ID
            impact: 判断への影響度
            context: コンテキスト情報

        Returns:
            成功したかどうか
        """
        is_positive = impact == DecisionImpact.POSITIVE
        return self.repository.update_feedback_count(conn, learning_id, is_positive)

    def record_positive_feedback(
        self,
        conn: Connection,
        learning_id: str,
    ) -> bool:
        """ポジティブフィードバックを記録

        Args:
            conn: DB接続
            learning_id: 学習ID

        Returns:
            成功したかどうか
        """
        return self.record_feedback(conn, learning_id, DecisionImpact.POSITIVE)

    def record_negative_feedback(
        self,
        conn: Connection,
        learning_id: str,
    ) -> bool:
        """ネガティブフィードバックを記録

        Args:
            conn: DB接続
            learning_id: 学習ID

        Returns:
            成功したかどうか
        """
        return self.record_feedback(conn, learning_id, DecisionImpact.NEGATIVE)

    # ========================================================================
    # スコア更新
    # ========================================================================

    def update_effectiveness_scores(
        self,
        conn: Connection,
    ) -> int:
        """全学習の有効性スコアを更新

        Args:
            conn: DB接続

        Returns:
            更新した件数
        """
        learnings, _ = self.repository.find_all(conn, active_only=True)
        updated = 0

        for learning in learnings:
            if not learning.id:
                continue
            result = self.calculate_effectiveness(learning)
            success = self.repository.update_effectiveness_score(
                conn, learning.id, result.effectiveness_score
            )
            if success:
                updated += 1

        return updated

    # ========================================================================
    # レポート生成
    # ========================================================================

    def generate_summary_report(
        self,
        conn: Connection,
    ) -> Dict[str, Any]:
        """サマリーレポートを生成

        Args:
            conn: DB接続

        Returns:
            サマリーレポート
        """
        health_by_status = self.check_health_batch(conn)

        # 統計
        total = sum(len(v) for v in health_by_status.values())
        healthy = len(health_by_status["healthy"])
        warning = len(health_by_status["warning"])
        critical = len(health_by_status["critical"])
        stale = len(health_by_status["stale"])

        # 全体のスコア
        learnings, _ = self.repository.find_all(conn, active_only=True)
        if learnings:
            scores = [
                self.calculate_effectiveness(l).effectiveness_score
                for l in learnings
            ]
            avg_score = sum(scores) / len(scores)
        else:
            avg_score = 0.0

        return {
            "total_learnings": total,
            "by_status": {
                "healthy": healthy,
                "warning": warning,
                "critical": critical,
                "stale": stale,
            },
            "health_ratio": round(healthy / total, 2) if total > 0 else 0,
            "average_effectiveness_score": round(avg_score, 3),
            "critical_learnings": [
                {
                    "id": h.learning_id,
                    "category": h.category,
                    "issues": h.issues,
                }
                for h in health_by_status["critical"]
            ],
            "improvement_suggestions_count": sum(
                len(h.suggestions)
                for status_list in health_by_status.values()
                for h in status_list
            ),
        }

    def format_summary_report(
        self,
        report: Dict[str, Any],
    ) -> str:
        """サマリーレポートをフォーマット

        Args:
            report: generate_summary_report()の結果

        Returns:
            フォーマットされたレポート
        """
        lines = ["📊 学習の有効性レポートだウル🐺\n"]

        lines.append(f"📚 全学習数: {report['total_learnings']}件")
        lines.append(f"💚 健全: {report['by_status']['healthy']}件")
        lines.append(f"💛 注意: {report['by_status']['warning']}件")
        lines.append(f"❤️ 要対応: {report['by_status']['critical']}件")
        lines.append(f"🔘 未使用: {report['by_status']['stale']}件")
        lines.append(f"\n📈 平均有効性スコア: {report['average_effectiveness_score']:.1%}")
        lines.append(f"🏥 健全率: {report['health_ratio']:.0%}")

        if report['critical_learnings']:
            lines.append("\n⚠️ 要対応の学習:")
            for item in report['critical_learnings'][:5]:
                issues = ", ".join(item['issues'])
                lines.append(f"  • [{item['category']}] {issues}")

        if report['improvement_suggestions_count'] > 0:
            lines.append(
                f"\n💡 改善提案: {report['improvement_suggestions_count']}件"
            )

        return "\n".join(lines)


# ============================================================================
# ファクトリ関数
# ============================================================================

def create_effectiveness_tracker(
    organization_id: str,
    repository: Optional[LearningRepository] = None,
    confidence_decay_rate: float = DEFAULT_CONFIDENCE_DECAY_RATE,
) -> EffectivenessTracker:
    """有効性追跡器を作成

    Args:
        organization_id: 組織ID
        repository: リポジトリ
        confidence_decay_rate: 確信度減衰率

    Returns:
        EffectivenessTracker インスタンス
    """
    return EffectivenessTracker(
        organization_id, repository, confidence_decay_rate
    )
