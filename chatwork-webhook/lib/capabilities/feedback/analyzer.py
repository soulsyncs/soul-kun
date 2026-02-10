# lib/capabilities/feedback/analyzer.py
"""
Phase F1: CEOフィードバックシステム - 分析エンジン

このモジュールは、収集されたファクトを分析し、
トレンド、異常、注目すべき変化を検出します。

設計書: docs/20_next_generation_capabilities.md セクション8

アーキテクチャ:
    Analyzer
    ├─ トレンド分析 (Trend Analysis)
    ├─ 異常検知 (Anomaly Detection)
    ├─ パターンマッチング (Pattern Matching)
    └─ ポジティブ発見 (Positive Findings)

Author: Claude Opus 4.5
Created: 2026-01-27
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from statistics import mean, stdev
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from .constants import (
    AnalysisParameters,
    ComparisonPeriod,
    FeedbackPriority,
    InsightCategory,
    TrendDirection,
)
from .models import (
    Anomaly,
    AnalysisResult,
    CommunicationFact,
    DailyFacts,
    GoalFact,
    TaskFact,
    TeamFact,
    Trend,
)


# =============================================================================
# 例外クラス
# =============================================================================


class AnalysisError(Exception):
    """分析エラー"""

    def __init__(
        self,
        message: str,
        analysis_type: str = "",
        details: Optional[Dict[str, Any]] = None,
        original_exception: Optional[Exception] = None,
    ):
        super().__init__(message)
        self.message = message
        self.analysis_type = analysis_type
        self.details = details or {}
        self.original_exception = original_exception


# =============================================================================
# 分析結果の内部データクラス
# =============================================================================


@dataclass
class DetectedAnomaly:
    """検出された異常（内部用）"""
    category: InsightCategory
    subject: str
    description: str
    current_value: float
    expected_value: float
    deviation: float
    severity: FeedbackPriority
    evidence: List[str] = field(default_factory=list)


@dataclass
class DetectedTrend:
    """検出されたトレンド（内部用）"""
    category: InsightCategory
    metric_name: str
    direction: TrendDirection
    change_rate: float
    comparison_period: ComparisonPeriod
    data_points: int
    confidence: float
    description: str


@dataclass
class NotableChange:
    """注目すべき変化（内部用）"""
    category: InsightCategory
    subject: str
    description: str
    change_type: str  # 'improvement', 'deterioration', 'new', 'resolved'
    severity: FeedbackPriority
    evidence: List[str] = field(default_factory=list)


@dataclass
class PositiveFinding:
    """ポジティブな発見（内部用）"""
    category: InsightCategory
    subject: str
    description: str
    achievement_type: str  # 'goal_achieved', 'high_performance', 'improvement'
    evidence: List[str] = field(default_factory=list)


# =============================================================================
# Analyzer クラス
# =============================================================================


class Analyzer:
    """
    分析エンジン

    収集されたファクトを分析し、トレンド、異常、注目すべき変化を検出。

    使用例:
        >>> analyzer = Analyzer()
        >>> result = await analyzer.analyze(daily_facts)
        >>> print(f"異常: {len(result.anomalies)}件")
        >>> print(f"トレンド: {len(result.trends)}件")

    フィードバック原則:
        1. 事実ファースト - データに基づく分析
        2. 数字で語る - 具体的な数値を提示
        3. 比較を入れる - 前週比、前月比との比較
        4. 仮説は仮説と明示 - 断定しない
        5. アクション提案 - 問題提起だけでなく提案まで
        6. ポジティブも伝える - 良いことも報告
    """

    def __init__(
        self,
        anomaly_threshold_sigma: float = AnalysisParameters.ANOMALY_THRESHOLD_SIGMA,
        min_data_points_for_trend: int = AnalysisParameters.MIN_DATA_POINTS_FOR_TREND,
        task_stale_days: int = AnalysisParameters.TASK_STALE_DAYS,
        task_concentration_ratio: float = AnalysisParameters.TASK_CONCENTRATION_RATIO,
        goal_warning_threshold: float = AnalysisParameters.GOAL_PROGRESS_WARNING_THRESHOLD,
        goal_danger_threshold: float = AnalysisParameters.GOAL_PROGRESS_DANGER_THRESHOLD,
        tone_change_threshold: float = AnalysisParameters.TONE_CHANGE_THRESHOLD,
    ) -> None:
        """
        Analyzerを初期化

        Args:
            anomaly_threshold_sigma: 異常検知の閾値（標準偏差の何倍）
            min_data_points_for_trend: トレンド判定に必要な最小データポイント数
            task_stale_days: タスク滞留と判定する日数
            task_concentration_ratio: タスク集中の閾値（平均の何倍）
            goal_warning_threshold: 目標達成率の警告閾値
            goal_danger_threshold: 目標達成率の危険閾値
            tone_change_threshold: トーン変化の閾値
        """
        self._anomaly_threshold_sigma = anomaly_threshold_sigma
        self._min_data_points_for_trend = min_data_points_for_trend
        self._task_stale_days = task_stale_days
        self._task_concentration_ratio = task_concentration_ratio
        self._goal_warning_threshold = goal_warning_threshold
        self._goal_danger_threshold = goal_danger_threshold
        self._tone_change_threshold = tone_change_threshold

        # ロガーの初期化
        try:
            from lib.logging import get_logger
            self._logger = get_logger("feedback.analyzer")
        except ImportError:
            import logging
            self._logger = logging.getLogger("feedback.analyzer")  # type: ignore[assignment]

    # =========================================================================
    # メイン分析メソッド
    # =========================================================================

    async def analyze(
        self,
        facts: DailyFacts,
        historical_facts: Optional[List[DailyFacts]] = None,
    ) -> AnalysisResult:
        """
        ファクトを分析

        収集されたファクトを分析し、トレンド、異常、注目すべき変化を検出。

        Args:
            facts: 分析対象のファクト
            historical_facts: 比較用の過去ファクト（オプション）

        Returns:
            AnalysisResult: 分析結果

        Raises:
            AnalysisError: 分析に失敗した場合
        """
        self._logger.info(
            "Starting fact analysis",
            extra={
                "organization_id": facts.organization_id,
                "date": facts.date.isoformat(),
            }
        )

        try:
            # 1. タスク分析
            task_anomalies, task_positives = await self._analyze_tasks(facts.task_facts)

            # 2. 目標分析
            goal_anomalies, goal_positives = await self._analyze_goals(facts.goal_facts)

            # 3. コミュニケーション分析
            comm_anomalies, comm_changes = await self._analyze_communication(
                facts.communication_facts
            )

            # 4. チーム全体分析
            team_anomalies, team_positives = await self._analyze_team(facts.team_fact)

            # 5. 既存インサイトからの注目点抽出
            insight_changes = await self._analyze_existing_insights(facts.existing_insights)

            # 6. トレンド分析（過去データがある場合）
            trends = []
            if historical_facts:
                trends = await self._analyze_trends(facts, historical_facts)

            # 結果を統合
            all_anomalies = task_anomalies + goal_anomalies + comm_anomalies + team_anomalies
            all_positives = task_positives + goal_positives + team_positives

            # Anomaly モデルに変換
            anomaly_models = [
                Anomaly(
                    anomaly_type=a.category.value,
                    subject=a.subject,
                    description=a.description,
                    current_value=a.current_value,
                    expected_value=a.expected_value,
                    deviation=a.deviation,
                    severity=a.severity,
                )
                for a in all_anomalies
            ]

            # Trend モデルに変換
            trend_models = [
                Trend(
                    metric_name=t.metric_name,
                    direction=t.direction,
                    change_rate=t.change_rate,
                    comparison_period=t.comparison_period,
                    data_points=t.data_points,
                    confidence=t.confidence,
                )
                for t in trends
            ]

            # 注目すべき変化をまとめる
            notable_changes = [
                {
                    "category": c.category.value,
                    "subject": c.subject,
                    "description": c.description,
                    "change_type": c.change_type,
                    "severity": c.severity.value,
                    "evidence": c.evidence,
                }
                for c in (comm_changes + insight_changes)
            ]

            # ポジティブな発見をまとめる
            positive_findings = [
                {
                    "category": p.category.value,
                    "subject": p.subject,
                    "description": p.description,
                    "achievement_type": p.achievement_type,
                    "evidence": p.evidence,
                }
                for p in all_positives
            ]

            result = AnalysisResult(
                anomalies=anomaly_models,
                trends=trend_models,
                notable_changes=notable_changes,
                positive_findings=positive_findings,
                analyzed_at=datetime.now(),
            )

            self._logger.info(
                "Fact analysis completed",
                extra={
                    "organization_id": facts.organization_id,
                    "anomalies": len(anomaly_models),
                    "trends": len(trend_models),
                    "notable_changes": len(notable_changes),
                    "positive_findings": len(positive_findings),
                }
            )

            return result

        except Exception as e:
            self._logger.error(
                "Fact analysis failed",
                extra={
                    "organization_id": facts.organization_id,
                    "error": str(e),
                }
            )
            raise AnalysisError(
                message="ファクト分析に失敗しました",
                analysis_type="analyze",
                details={"date": facts.date.isoformat()},
                original_exception=e,
            )

    # =========================================================================
    # タスク分析
    # =========================================================================

    async def _analyze_tasks(
        self,
        task_facts: List[TaskFact],
    ) -> Tuple[List[DetectedAnomaly], List[PositiveFinding]]:
        """
        タスクファクトを分析

        Args:
            task_facts: タスクファクトのリスト

        Returns:
            Tuple[List[DetectedAnomaly], List[PositiveFinding]]: 異常とポジティブな発見
        """
        anomalies: List[DetectedAnomaly] = []
        positives: List[PositiveFinding] = []

        if not task_facts:
            return anomalies, positives

        # 全体の統計を計算
        completion_rates = [tf.completion_rate for tf in task_facts]
        overdue_counts = [tf.overdue_tasks for tf in task_facts]
        stale_counts = [tf.stale_tasks for tf in task_facts]

        avg_completion_rate = mean(completion_rates) if completion_rates else 0.0
        avg_overdue = mean(overdue_counts) if overdue_counts else 0.0

        # 各ユーザーを分析
        for tf in task_facts:
            # 1. 期限超過タスクが多いユーザー
            if tf.overdue_tasks >= 3:
                severity = FeedbackPriority.HIGH if tf.overdue_tasks >= 5 else FeedbackPriority.MEDIUM
                anomalies.append(DetectedAnomaly(
                    category=InsightCategory.TASK_PROGRESS,
                    subject=tf.user_name,
                    description=f"{tf.user_name}さんのタスクが{tf.overdue_tasks}件期限超過しています",
                    current_value=float(tf.overdue_tasks),
                    expected_value=0.0,
                    deviation=float(tf.overdue_tasks),
                    severity=severity,
                    evidence=[
                        f"期限超過タスク: {tf.overdue_tasks}件",
                        f"最長超過日数: {tf.oldest_overdue_days}日",
                    ],
                ))

            # 2. 滞留タスクが多いユーザー
            if tf.stale_tasks >= 5:
                severity = FeedbackPriority.MEDIUM
                anomalies.append(DetectedAnomaly(
                    category=InsightCategory.TASK_PROGRESS,
                    subject=tf.user_name,
                    description=f"{tf.user_name}さんのタスクが{tf.stale_tasks}件滞留中（{self._task_stale_days}日以上未更新）",
                    current_value=float(tf.stale_tasks),
                    expected_value=0.0,
                    deviation=float(tf.stale_tasks),
                    severity=severity,
                    evidence=[
                        f"滞留タスク: {tf.stale_tasks}件",
                        f"総タスク数: {tf.total_tasks}件",
                    ],
                ))

            # 3. 高いタスク完了率（ポジティブ）
            if tf.completion_rate >= 0.9 and tf.total_tasks >= 5:
                positives.append(PositiveFinding(
                    category=InsightCategory.POSITIVE_CHANGE,
                    subject=tf.user_name,
                    description=f"{tf.user_name}さんのタスク完了率が{tf.completion_rate:.0%}と高水準です",
                    achievement_type="high_performance",
                    evidence=[
                        f"完了率: {tf.completion_rate:.0%}",
                        f"完了タスク: {tf.completed_tasks}/{tf.total_tasks}件",
                    ],
                ))

            # 4. 今日の活躍（多くのタスク完了）
            if tf.tasks_completed_today >= 3:
                positives.append(PositiveFinding(
                    category=InsightCategory.POSITIVE_CHANGE,
                    subject=tf.user_name,
                    description=f"{tf.user_name}さんが今日{tf.tasks_completed_today}件のタスクを完了しました",
                    achievement_type="improvement",
                    evidence=[
                        f"今日完了: {tf.tasks_completed_today}件",
                    ],
                ))

        # 5. タスク集中の検出（特定ユーザーにタスクが偏っている）
        if len(task_facts) >= 3:
            total_tasks_list = [tf.total_tasks for tf in task_facts]
            avg_tasks = mean(total_tasks_list)

            for tf in task_facts:
                if avg_tasks > 0 and tf.total_tasks > avg_tasks * self._task_concentration_ratio:
                    anomalies.append(DetectedAnomaly(
                        category=InsightCategory.RISK_ANOMALY,
                        subject=tf.user_name,
                        description=f"{tf.user_name}さんにタスクが集中しています（平均の{tf.total_tasks / avg_tasks:.1f}倍）",
                        current_value=float(tf.total_tasks),
                        expected_value=avg_tasks,
                        deviation=(tf.total_tasks - avg_tasks) / avg_tasks,
                        severity=FeedbackPriority.MEDIUM,
                        evidence=[
                            f"タスク数: {tf.total_tasks}件",
                            f"チーム平均: {avg_tasks:.1f}件",
                        ],
                    ))

        return anomalies, positives

    # =========================================================================
    # 目標分析
    # =========================================================================

    async def _analyze_goals(
        self,
        goal_facts: List[GoalFact],
    ) -> Tuple[List[DetectedAnomaly], List[PositiveFinding]]:
        """
        目標ファクトを分析

        Args:
            goal_facts: 目標ファクトのリスト

        Returns:
            Tuple[List[DetectedAnomaly], List[PositiveFinding]]: 異常とポジティブな発見
        """
        anomalies = []
        positives = []

        for gf in goal_facts:
            # 1. 目標達成（ポジティブ）
            if gf.progress_rate >= 1.0:
                positives.append(PositiveFinding(
                    category=InsightCategory.GOAL_ACHIEVEMENT,
                    subject=gf.user_name,
                    description=f"{gf.user_name}さんが目標「{gf.goal_title[:30]}」を達成しました！",
                    achievement_type="goal_achieved",
                    evidence=[
                        f"達成率: {gf.progress_rate:.0%}",
                        f"目標値: {gf.target_value}, 実績: {gf.current_value}",
                    ],
                ))
                continue

            # 2. 目標達成率が危険水準
            if gf.is_at_risk:
                severity = FeedbackPriority.HIGH if gf.progress_rate < self._goal_danger_threshold else FeedbackPriority.MEDIUM
                anomalies.append(DetectedAnomaly(
                    category=InsightCategory.GOAL_ACHIEVEMENT,
                    subject=gf.user_name,
                    description=f"{gf.user_name}さんの目標「{gf.goal_title[:30]}」の進捗が{gf.progress_rate:.0%}で遅れています",
                    current_value=gf.progress_rate,
                    expected_value=0.7,  # 期待値は70%程度
                    deviation=0.7 - gf.progress_rate,
                    severity=severity,
                    evidence=[
                        f"進捗率: {gf.progress_rate:.0%}",
                        f"残り日数: {gf.days_remaining}日",
                        f"現在値: {gf.current_value}/{gf.target_value}",
                    ],
                ))

            # 3. 順調な進捗（ポジティブ）
            elif gf.is_on_track and gf.progress_rate >= 0.7:
                positives.append(PositiveFinding(
                    category=InsightCategory.GOAL_ACHIEVEMENT,
                    subject=gf.user_name,
                    description=f"{gf.user_name}さんの目標「{gf.goal_title[:30]}」が順調です（{gf.progress_rate:.0%}）",
                    achievement_type="improvement",
                    evidence=[
                        f"進捗率: {gf.progress_rate:.0%}",
                        f"残り日数: {gf.days_remaining}日",
                    ],
                ))

        return anomalies, positives

    # =========================================================================
    # コミュニケーション分析
    # =========================================================================

    async def _analyze_communication(
        self,
        communication_facts: List[CommunicationFact],
    ) -> Tuple[List[DetectedAnomaly], List[NotableChange]]:
        """
        コミュニケーションファクトを分析

        Args:
            communication_facts: コミュニケーションファクトのリスト

        Returns:
            Tuple[List[DetectedAnomaly], List[NotableChange]]: 異常と注目すべき変化
        """
        anomalies = []
        changes = []

        for cf in communication_facts:
            # 1. 感情面で気になる状態
            if cf.is_sentiment_concerning:
                severity = FeedbackPriority.MEDIUM
                if cf.sentiment_score < -0.5:
                    severity = FeedbackPriority.HIGH

                anomalies.append(DetectedAnomaly(
                    category=InsightCategory.COMMUNICATION,
                    subject=cf.user_name,
                    description=f"{cf.user_name}さんのメッセージのトーンが変化しています",
                    current_value=cf.sentiment_score,
                    expected_value=0.0,
                    deviation=abs(cf.sentiment_score),
                    severity=severity,
                    evidence=[
                        f"感情スコア: {cf.sentiment_score:.2f}",
                        f"トレンド: {cf.sentiment_trend.value}",
                    ],
                ))

            # 2. メッセージ数の急減（活動低下の可能性）
            if cf.message_count_week > 0:
                daily_avg = cf.message_count_week / 7
                if daily_avg >= 3 and cf.message_count_today == 0:
                    changes.append(NotableChange(
                        category=InsightCategory.TEAM_HEALTH,
                        subject=cf.user_name,
                        description=f"{cf.user_name}さんの今日の活動が見られません（週平均{daily_avg:.1f}件/日）",
                        change_type="deterioration",
                        severity=FeedbackPriority.LOW,
                        evidence=[
                            f"今日のメッセージ: {cf.message_count_today}件",
                            f"週平均: {daily_avg:.1f}件/日",
                        ],
                    ))

        return anomalies, changes

    # =========================================================================
    # チーム分析
    # =========================================================================

    async def _analyze_team(
        self,
        team_fact: Optional[TeamFact],
    ) -> Tuple[List[DetectedAnomaly], List[PositiveFinding]]:
        """
        チーム全体のファクトを分析

        Args:
            team_fact: チーム全体のファクト

        Returns:
            Tuple[List[DetectedAnomaly], List[PositiveFinding]]: 異常とポジティブな発見
        """
        anomalies: List[DetectedAnomaly] = []
        positives: List[PositiveFinding] = []

        if not team_fact:
            return anomalies, positives

        # 1. 期限超過タスクが多い
        if team_fact.total_overdue_tasks >= 10:
            severity = FeedbackPriority.HIGH if team_fact.total_overdue_tasks >= 20 else FeedbackPriority.MEDIUM
            anomalies.append(DetectedAnomaly(
                category=InsightCategory.TEAM_HEALTH,
                subject="チーム全体",
                description=f"チーム全体で{team_fact.total_overdue_tasks}件のタスクが期限超過しています",
                current_value=float(team_fact.total_overdue_tasks),
                expected_value=0.0,
                deviation=float(team_fact.total_overdue_tasks),
                severity=severity,
                evidence=[
                    f"期限超過タスク: {team_fact.total_overdue_tasks}件",
                    f"注意が必要なメンバー: {', '.join(team_fact.members_needing_attention[:3])}",
                ],
            ))

        # 2. リスクのある目標が多い
        if team_fact.total_goals_at_risk >= 3:
            anomalies.append(DetectedAnomaly(
                category=InsightCategory.GOAL_ACHIEVEMENT,
                subject="チーム全体",
                description=f"チーム全体で{team_fact.total_goals_at_risk}件の目標がリスク状態です",
                current_value=float(team_fact.total_goals_at_risk),
                expected_value=0.0,
                deviation=float(team_fact.total_goals_at_risk),
                severity=FeedbackPriority.MEDIUM,
                evidence=[
                    f"リスク状態の目標: {team_fact.total_goals_at_risk}件",
                ],
            ))

        # 3. 活動率が低い
        if team_fact.activity_rate < 0.5 and team_fact.total_members >= 3:
            anomalies.append(DetectedAnomaly(
                category=InsightCategory.TEAM_HEALTH,
                subject="チーム全体",
                description=f"チームの活動率が{team_fact.activity_rate:.0%}と低めです",
                current_value=team_fact.activity_rate,
                expected_value=0.8,
                deviation=0.8 - team_fact.activity_rate,
                severity=FeedbackPriority.LOW,
                evidence=[
                    f"アクティブメンバー: {team_fact.active_members}/{team_fact.total_members}人",
                ],
            ))

        # 4. 高いタスク完了率（ポジティブ）
        if team_fact.avg_task_completion_rate >= 0.8:
            positives.append(PositiveFinding(
                category=InsightCategory.POSITIVE_CHANGE,
                subject="チーム全体",
                description=f"チームのタスク完了率が{team_fact.avg_task_completion_rate:.0%}と高水準です",
                achievement_type="high_performance",
                evidence=[
                    f"平均完了率: {team_fact.avg_task_completion_rate:.0%}",
                    f"トップパフォーマー: {', '.join(team_fact.top_performers[:3])}",
                ],
            ))

        # 5. トップパフォーマーの紹介（ポジティブ）
        if team_fact.top_performers:
            positives.append(PositiveFinding(
                category=InsightCategory.POSITIVE_CHANGE,
                subject="トップパフォーマー",
                description=f"今日の活躍: {', '.join(team_fact.top_performers[:3])}さん",
                achievement_type="high_performance",
                evidence=[
                    f"高い完了率を達成",
                ],
            ))

        return anomalies, positives

    # =========================================================================
    # 既存インサイト分析
    # =========================================================================

    async def _analyze_existing_insights(
        self,
        existing_insights: List[Dict[str, Any]],
    ) -> List[NotableChange]:
        """
        既存のインサイトから注目点を抽出

        Args:
            existing_insights: 既存インサイトのリスト

        Returns:
            List[NotableChange]: 注目すべき変化
        """
        changes = []

        # Critical/Highのインサイトを注目点として抽出
        for insight in existing_insights:
            importance = insight.get("importance", "low")
            if importance in ("critical", "high"):
                severity = FeedbackPriority.CRITICAL if importance == "critical" else FeedbackPriority.HIGH

                # カテゴリを判定
                source_type = insight.get("source_type", "")
                category = InsightCategory.RISK_ANOMALY
                if "pattern" in source_type:
                    category = InsightCategory.TASK_PROGRESS
                elif "emotion" in source_type:
                    category = InsightCategory.COMMUNICATION
                elif "bottleneck" in source_type:
                    category = InsightCategory.TEAM_HEALTH

                changes.append(NotableChange(
                    category=category,
                    subject=insight.get("title", "不明"),
                    description=insight.get("description", ""),
                    change_type="new",
                    severity=severity,
                    evidence=[
                        f"検出日: {insight.get('created_at', '')}",
                        f"推奨アクション: {insight.get('recommended_action', 'なし')}",
                    ],
                ))

        return changes

    # =========================================================================
    # トレンド分析
    # =========================================================================

    async def _analyze_trends(
        self,
        current_facts: DailyFacts,
        historical_facts: List[DailyFacts],
    ) -> List[DetectedTrend]:
        """
        トレンドを分析

        Args:
            current_facts: 現在のファクト
            historical_facts: 過去のファクトのリスト

        Returns:
            List[DetectedTrend]: 検出されたトレンド
        """
        trends: List[DetectedTrend] = []

        if len(historical_facts) < self._min_data_points_for_trend:
            return trends

        # タスク完了率のトレンド
        completion_rates = []
        for hf in historical_facts:
            if hf.team_fact:
                completion_rates.append(hf.team_fact.avg_task_completion_rate)

        if current_facts.team_fact:
            completion_rates.append(current_facts.team_fact.avg_task_completion_rate)

        if len(completion_rates) >= self._min_data_points_for_trend:
            trend = self._calculate_trend(
                data_points=completion_rates,
                metric_name="タスク完了率",
                category=InsightCategory.TASK_PROGRESS,
            )
            if trend:
                trends.append(trend)

        # 期限超過タスク数のトレンド
        overdue_counts = []
        for hf in historical_facts:
            if hf.team_fact:
                overdue_counts.append(float(hf.team_fact.total_overdue_tasks))

        if current_facts.team_fact:
            overdue_counts.append(float(current_facts.team_fact.total_overdue_tasks))

        if len(overdue_counts) >= self._min_data_points_for_trend:
            trend = self._calculate_trend(
                data_points=overdue_counts,
                metric_name="期限超過タスク数",
                category=InsightCategory.RISK_ANOMALY,
                reverse_direction=True,  # 増加は悪化を意味する
            )
            if trend:
                trends.append(trend)

        return trends

    def _calculate_trend(
        self,
        data_points: List[float],
        metric_name: str,
        category: InsightCategory,
        reverse_direction: bool = False,
    ) -> Optional[DetectedTrend]:
        """
        トレンドを計算

        Args:
            data_points: データポイントのリスト
            metric_name: 指標名
            category: カテゴリ
            reverse_direction: 方向を反転するか（増加が悪化を意味する場合）

        Returns:
            DetectedTrend: 検出されたトレンド（変化がない場合はNone）
        """
        if len(data_points) < 2:
            return None

        # 変化率を計算
        first_half = mean(data_points[:len(data_points)//2])
        second_half = mean(data_points[len(data_points)//2:])

        if first_half == 0:
            return None

        change_rate = (second_half - first_half) / first_half

        # 変化が小さい場合はスキップ
        if abs(change_rate) < 0.1:
            return None

        # 方向を判定
        direction = TrendDirection.STABLE
        if change_rate > 0.2:
            direction = TrendDirection.SPIKE if change_rate > 0.5 else TrendDirection.INCREASING
        elif change_rate < -0.2:
            direction = TrendDirection.DROP if change_rate < -0.5 else TrendDirection.DECREASING

        if reverse_direction:
            if direction == TrendDirection.INCREASING:
                direction = TrendDirection.DECREASING
            elif direction == TrendDirection.DECREASING:
                direction = TrendDirection.INCREASING
            elif direction == TrendDirection.SPIKE:
                direction = TrendDirection.DROP
            elif direction == TrendDirection.DROP:
                direction = TrendDirection.SPIKE

        # 確信度を計算（データポイント数に基づく）
        confidence = min(len(data_points) / 10, 1.0)

        # 説明文を生成
        direction_text = {
            TrendDirection.INCREASING: "上昇傾向",
            TrendDirection.DECREASING: "下降傾向",
            TrendDirection.SPIKE: "急上昇",
            TrendDirection.DROP: "急下降",
            TrendDirection.STABLE: "横ばい",
        }.get(direction, "")

        return DetectedTrend(
            category=category,
            metric_name=metric_name,
            direction=direction,
            change_rate=change_rate * 100,  # パーセント表示
            comparison_period=ComparisonPeriod.WEEK_OVER_WEEK,
            data_points=len(data_points),
            confidence=confidence,
            description=f"{metric_name}が{direction_text}（{change_rate:+.0%}）",
        )


# =============================================================================
# ファクトリー関数
# =============================================================================


def create_analyzer(
    anomaly_threshold_sigma: float = AnalysisParameters.ANOMALY_THRESHOLD_SIGMA,
    min_data_points_for_trend: int = AnalysisParameters.MIN_DATA_POINTS_FOR_TREND,
) -> Analyzer:
    """
    Analyzerを作成

    Args:
        anomaly_threshold_sigma: 異常検知の閾値
        min_data_points_for_trend: トレンド判定に必要な最小データポイント数

    Returns:
        Analyzer: 分析エンジン
    """
    return Analyzer(
        anomaly_threshold_sigma=anomaly_threshold_sigma,
        min_data_points_for_trend=min_data_points_for_trend,
    )
