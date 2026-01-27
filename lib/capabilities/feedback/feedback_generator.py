# lib/capabilities/feedback/feedback_generator.py
"""
Phase F1: CEOフィードバックシステム - フィードバック生成エンジン

このモジュールは、分析結果からCEO向けのフィードバックメッセージを生成します。

設計書: docs/20_next_generation_capabilities.md セクション8

フィードバック原則:
    1. 事実ファースト - 「〜と思います」ではなく「〜というデータがあります」
    2. 数字で語る - 具体的な数値変化を提示
    3. 比較を入れる - 先週比、先月比、過去パターンとの比較
    4. 仮説は仮説と明示 - 「〜かもしれません」と断定しない
    5. アクション提案 - 問題提起だけでなく「こうしては？」まで
    6. ポジティブも伝える - 良いことも報告

Author: Claude Opus 4.5
Created: 2026-01-27
"""

from dataclasses import dataclass, field
from datetime import datetime, date
import json
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from .constants import (
    DeliveryParameters,
    FeedbackIcons,
    FeedbackPriority,
    FeedbackStatus,
    FeedbackTemplates,
    FeedbackType,
    InsightCategory,
)
from .models import (
    AnalysisResult,
    Anomaly,
    CEOFeedback,
    DailyFacts,
    FeedbackItem,
    Trend,
)


# =============================================================================
# 例外クラス
# =============================================================================


class FeedbackGenerationError(Exception):
    """フィードバック生成エラー"""

    def __init__(
        self,
        message: str,
        feedback_type: str = "",
        details: Optional[Dict[str, Any]] = None,
        original_exception: Optional[Exception] = None,
    ):
        super().__init__(message)
        self.message = message
        self.feedback_type = feedback_type
        self.details = details or {}
        self.original_exception = original_exception


# =============================================================================
# FeedbackGenerator クラス
# =============================================================================


class FeedbackGenerator:
    """
    フィードバック生成エンジン

    分析結果からCEO向けのフィードバックメッセージを生成。

    使用例:
        >>> generator = FeedbackGenerator(org_id, recipient_id, recipient_name)
        >>> feedback = await generator.generate_daily_digest(facts, analysis)
        >>> print(feedback.to_text())

    Attributes:
        org_id: 組織ID
        recipient_user_id: 受信者ユーザーID
        recipient_name: 受信者の名前
    """

    def __init__(
        self,
        organization_id: UUID,
        recipient_user_id: UUID,
        recipient_name: str,
        max_items_per_digest: int = DeliveryParameters.DAILY_DIGEST_MAX_ITEMS,
    ) -> None:
        """
        FeedbackGeneratorを初期化

        Args:
            organization_id: 組織ID
            recipient_user_id: 受信者ユーザーID
            recipient_name: 受信者の名前
            max_items_per_digest: 1つのダイジェストに含める最大項目数
        """
        self._org_id = organization_id
        self._recipient_user_id = recipient_user_id
        self._recipient_name = recipient_name
        self._max_items = max_items_per_digest

        # ロガーの初期化
        try:
            from lib.logging import get_logger
            self._logger = get_logger("feedback.generator")
        except ImportError:
            import logging
            self._logger = logging.getLogger("feedback.generator")

    # =========================================================================
    # プロパティ
    # =========================================================================

    @property
    def organization_id(self) -> UUID:
        """組織IDを取得"""
        return self._org_id

    @property
    def recipient_user_id(self) -> UUID:
        """受信者ユーザーIDを取得"""
        return self._recipient_user_id

    @property
    def recipient_name(self) -> str:
        """受信者の名前を取得"""
        return self._recipient_name

    # =========================================================================
    # デイリーダイジェスト生成
    # =========================================================================

    async def generate_daily_digest(
        self,
        facts: DailyFacts,
        analysis: AnalysisResult,
    ) -> CEOFeedback:
        """
        デイリーダイジェストを生成

        毎朝8:00に配信する「今日注目すべきこと」を生成。

        Args:
            facts: 収集されたファクト
            analysis: 分析結果

        Returns:
            CEOFeedback: 生成されたフィードバック

        Raises:
            FeedbackGenerationError: 生成に失敗した場合
        """
        self._logger.info(
            "Generating daily digest",
            extra={
                "organization_id": str(self._org_id),
                "recipient": self._recipient_name,
            }
        )

        try:
            feedback_id = str(uuid4())
            items = []

            # 1. 異常から項目を生成（優先度順）
            for anomaly in sorted(
                analysis.anomalies,
                key=lambda a: self._priority_order(a.severity),
            ):
                if len(items) >= self._max_items:
                    break
                item = self._anomaly_to_item(anomaly)
                items.append(item)

            # 2. 注目すべき変化から項目を追加
            for change in analysis.notable_changes:
                if len(items) >= self._max_items:
                    break
                item = self._change_to_item(change)
                items.append(item)

            # 3. ポジティブな発見から項目を追加（最低1件は含める）
            positive_count = sum(1 for i in items if i.category == InsightCategory.POSITIVE_CHANGE)
            if positive_count == 0 and analysis.positive_findings:
                for finding in analysis.positive_findings[:2]:
                    if len(items) >= self._max_items:
                        break
                    item = self._positive_to_item(finding)
                    items.append(item)

            # 4. サマリーを生成
            summary = self._generate_summary(facts, analysis)

            # 5. CEOFeedbackを構築
            feedback = CEOFeedback(
                feedback_id=feedback_id,
                feedback_type=FeedbackType.DAILY_DIGEST,
                organization_id=str(self._org_id),
                recipient_user_id=str(self._recipient_user_id),
                recipient_name=self._recipient_name,
                items=items,
                summary=summary,
                status=FeedbackStatus.READY,
                generated_at=datetime.now(),
                source_facts=facts,
                source_analysis=analysis,
            )

            self._logger.info(
                "Daily digest generated",
                extra={
                    "organization_id": str(self._org_id),
                    "feedback_id": feedback_id,
                    "item_count": len(items),
                }
            )

            return feedback

        except Exception as e:
            self._logger.error(
                "Failed to generate daily digest",
                extra={
                    "organization_id": str(self._org_id),
                    "error": str(e),
                }
            )
            raise FeedbackGenerationError(
                message="デイリーダイジェストの生成に失敗しました",
                feedback_type="daily_digest",
                original_exception=e,
            )

    # =========================================================================
    # ウィークリーレビュー生成
    # =========================================================================

    async def generate_weekly_review(
        self,
        weekly_facts: List[DailyFacts],
        weekly_analysis: AnalysisResult,
        week_start: date,
        week_end: date,
    ) -> CEOFeedback:
        """
        ウィークリーレビューを生成

        毎週月曜9:00に配信する「先週の振り返り + 今週の注目点」を生成。

        Args:
            weekly_facts: 週のファクトリスト
            weekly_analysis: 週の分析結果
            week_start: 週の開始日
            week_end: 週の終了日

        Returns:
            CEOFeedback: 生成されたフィードバック
        """
        self._logger.info(
            "Generating weekly review",
            extra={
                "organization_id": str(self._org_id),
                "week_start": week_start.isoformat(),
            }
        )

        try:
            feedback_id = str(uuid4())
            items = []

            # 1. 週のハイライト（ポジティブ）
            for finding in weekly_analysis.positive_findings[:2]:
                item = self._positive_to_item(finding)
                item.title = f"✨ {item.title}"
                items.append(item)

            # 2. 注目すべき課題
            for anomaly in sorted(
                weekly_analysis.anomalies,
                key=lambda a: self._priority_order(a.severity),
            )[:3]:
                item = self._anomaly_to_item(anomaly)
                items.append(item)

            # 3. トレンド分析
            for trend in weekly_analysis.trends[:2]:
                item = self._trend_to_item(trend)
                items.append(item)

            # 4. サマリーを生成
            summary = self._generate_weekly_summary(weekly_facts, weekly_analysis, week_start, week_end)

            # 5. CEOFeedbackを構築
            feedback = CEOFeedback(
                feedback_id=feedback_id,
                feedback_type=FeedbackType.WEEKLY_REVIEW,
                organization_id=str(self._org_id),
                recipient_user_id=str(self._recipient_user_id),
                recipient_name=self._recipient_name,
                items=items,
                summary=summary,
                status=FeedbackStatus.READY,
                generated_at=datetime.now(),
                source_analysis=weekly_analysis,
            )

            return feedback

        except Exception as e:
            self._logger.error(
                "Failed to generate weekly review",
                extra={
                    "organization_id": str(self._org_id),
                    "error": str(e),
                }
            )
            raise FeedbackGenerationError(
                message="ウィークリーレビューの生成に失敗しました",
                feedback_type="weekly_review",
                original_exception=e,
            )

    # =========================================================================
    # リアルタイムアラート生成
    # =========================================================================

    async def generate_realtime_alert(
        self,
        anomaly: Anomaly,
        facts: Optional[DailyFacts] = None,
    ) -> CEOFeedback:
        """
        リアルタイムアラートを生成

        重要な変化を即座に通知するアラートを生成。

        Args:
            anomaly: 検出された異常
            facts: 関連するファクト（オプション）

        Returns:
            CEOFeedback: 生成されたフィードバック
        """
        self._logger.info(
            "Generating realtime alert",
            extra={
                "organization_id": str(self._org_id),
                "anomaly_type": anomaly.anomaly_type,
            }
        )

        try:
            feedback_id = str(uuid4())

            # アラート項目を生成
            item = self._anomaly_to_item(anomaly)
            item.priority = FeedbackPriority.CRITICAL  # アラートは常に高優先度

            # アクション提案を強化
            item.recommendation = self._generate_alert_recommendation(anomaly)

            # CEOFeedbackを構築
            feedback = CEOFeedback(
                feedback_id=feedback_id,
                feedback_type=FeedbackType.REALTIME_ALERT,
                organization_id=str(self._org_id),
                recipient_user_id=str(self._recipient_user_id),
                recipient_name=self._recipient_name,
                items=[item],
                summary="",  # アラートにはサマリーなし
                status=FeedbackStatus.READY,
                generated_at=datetime.now(),
                source_facts=facts,
            )

            return feedback

        except Exception as e:
            self._logger.error(
                "Failed to generate realtime alert",
                extra={
                    "organization_id": str(self._org_id),
                    "error": str(e),
                }
            )
            raise FeedbackGenerationError(
                message="リアルタイムアラートの生成に失敗しました",
                feedback_type="realtime_alert",
                original_exception=e,
            )

    # =========================================================================
    # オンデマンド分析生成
    # =========================================================================

    async def generate_on_demand_analysis(
        self,
        query: str,
        facts: DailyFacts,
        analysis: AnalysisResult,
    ) -> CEOFeedback:
        """
        オンデマンド分析を生成

        「最近どう？」などの質問に対する深掘り分析を生成。

        Args:
            query: ユーザーの質問
            facts: 収集されたファクト
            analysis: 分析結果

        Returns:
            CEOFeedback: 生成されたフィードバック
        """
        self._logger.info(
            "Generating on-demand analysis",
            extra={
                "organization_id": str(self._org_id),
                "query": query[:50],
            }
        )

        try:
            feedback_id = str(uuid4())
            items = []

            # クエリに基づいて関連する項目を選択
            query_lower = query.lower()

            # タスク関連のクエリ
            if any(word in query_lower for word in ["タスク", "仕事", "進捗", "やること"]):
                for anomaly in analysis.anomalies:
                    if anomaly.anomaly_type in ("task_progress", "team_health"):
                        items.append(self._anomaly_to_item(anomaly))

            # 目標関連のクエリ
            elif any(word in query_lower for word in ["目標", "ゴール", "達成", "kpi"]):
                for anomaly in analysis.anomalies:
                    if anomaly.anomaly_type == "goal_achievement":
                        items.append(self._anomaly_to_item(anomaly))
                for finding in analysis.positive_findings:
                    if finding.get("category") == "goal_achievement":
                        items.append(self._positive_to_item(finding))

            # チーム関連のクエリ
            elif any(word in query_lower for word in ["チーム", "メンバー", "みんな", "全体"]):
                for anomaly in analysis.anomalies:
                    if anomaly.anomaly_type in ("team_health", "communication"):
                        items.append(self._anomaly_to_item(anomaly))

            # 一般的なクエリ（全体概要）
            else:
                # 優先度の高い項目を追加
                for anomaly in sorted(
                    analysis.anomalies,
                    key=lambda a: self._priority_order(a.severity),
                )[:3]:
                    items.append(self._anomaly_to_item(anomaly))

                # ポジティブな発見も追加
                for finding in analysis.positive_findings[:2]:
                    items.append(self._positive_to_item(finding))

            # サマリーを生成
            summary = self._generate_on_demand_summary(query, facts, analysis)

            # CEOFeedbackを構築
            feedback = CEOFeedback(
                feedback_id=feedback_id,
                feedback_type=FeedbackType.ON_DEMAND,
                organization_id=str(self._org_id),
                recipient_user_id=str(self._recipient_user_id),
                recipient_name=self._recipient_name,
                items=items[:self._max_items],
                summary=summary,
                status=FeedbackStatus.READY,
                generated_at=datetime.now(),
                source_facts=facts,
                source_analysis=analysis,
            )

            return feedback

        except Exception as e:
            self._logger.error(
                "Failed to generate on-demand analysis",
                extra={
                    "organization_id": str(self._org_id),
                    "error": str(e),
                }
            )
            raise FeedbackGenerationError(
                message="オンデマンド分析の生成に失敗しました",
                feedback_type="on_demand",
                original_exception=e,
            )

    # =========================================================================
    # 項目変換ヘルパー
    # =========================================================================

    def _anomaly_to_item(self, anomaly: Anomaly) -> FeedbackItem:
        """
        異常からFeedbackItemを生成

        Args:
            anomaly: 検出された異常

        Returns:
            FeedbackItem: フィードバック項目
        """
        category = self._map_anomaly_type_to_category(anomaly.anomaly_type)

        # 仮説を生成
        hypothesis = self._generate_hypothesis(anomaly)

        # 推奨アクションを生成
        recommendation = self._generate_recommendation(anomaly)

        return FeedbackItem(
            category=category,
            priority=anomaly.severity,
            title=anomaly.subject,
            description=anomaly.description,
            evidence=[
                f"現在値: {anomaly.current_value}",
                f"期待値: {anomaly.expected_value}",
            ],
            hypothesis=hypothesis,
            recommendation=recommendation,
            related_users=[anomaly.subject] if anomaly.subject else [],
            related_metrics={
                "current_value": anomaly.current_value,
                "expected_value": anomaly.expected_value,
                "deviation": anomaly.deviation,
            },
        )

    def _change_to_item(self, change: Dict[str, Any]) -> FeedbackItem:
        """
        注目すべき変化からFeedbackItemを生成

        Args:
            change: 変化データ

        Returns:
            FeedbackItem: フィードバック項目
        """
        category_str = change.get("category", "risk_anomaly")
        category = InsightCategory(category_str) if category_str in [c.value for c in InsightCategory] else InsightCategory.RISK_ANOMALY

        severity_str = change.get("severity", "medium")
        severity = FeedbackPriority(severity_str) if severity_str in [p.value for p in FeedbackPriority] else FeedbackPriority.MEDIUM

        return FeedbackItem(
            category=category,
            priority=severity,
            title=change.get("subject", "変化検出"),
            description=change.get("description", ""),
            evidence=change.get("evidence", []),
            related_users=[change.get("subject", "")] if change.get("subject") else [],
        )

    def _positive_to_item(self, finding: Dict[str, Any]) -> FeedbackItem:
        """
        ポジティブな発見からFeedbackItemを生成

        Args:
            finding: ポジティブな発見データ

        Returns:
            FeedbackItem: フィードバック項目
        """
        return FeedbackItem(
            category=InsightCategory.POSITIVE_CHANGE,
            priority=FeedbackPriority.LOW,  # ポジティブな発見は低優先度
            title=finding.get("subject", "良い傾向"),
            description=finding.get("description", ""),
            evidence=finding.get("evidence", []),
            related_users=[finding.get("subject", "")] if finding.get("subject") else [],
        )

    def _trend_to_item(self, trend: Trend) -> FeedbackItem:
        """
        トレンドからFeedbackItemを生成

        Args:
            trend: 検出されたトレンド

        Returns:
            FeedbackItem: フィードバック項目
        """
        # 方向に基づいてカテゴリを決定
        if trend.direction in (TrendDirection.SPIKE, TrendDirection.DROP):
            priority = FeedbackPriority.HIGH
        elif trend.direction in (TrendDirection.INCREASING, TrendDirection.DECREASING):
            priority = FeedbackPriority.MEDIUM
        else:
            priority = FeedbackPriority.LOW

        direction_text = {
            TrendDirection.INCREASING: "📈 上昇傾向",
            TrendDirection.DECREASING: "📉 下降傾向",
            TrendDirection.SPIKE: "⬆️ 急上昇",
            TrendDirection.DROP: "⬇️ 急下降",
            TrendDirection.STABLE: "➡️ 横ばい",
        }.get(trend.direction, "")

        return FeedbackItem(
            category=InsightCategory.RECOMMENDATION,
            priority=priority,
            title=f"{trend.metric_name} {direction_text}",
            description=f"{trend.metric_name}が{trend.comparison_period.value}比で{trend.change_rate:+.1f}%変化しています",
            evidence=[
                f"変化率: {trend.change_rate:+.1f}%",
                f"データポイント: {trend.data_points}件",
                f"確信度: {trend.confidence:.0%}",
            ],
            related_metrics={
                "change_rate": trend.change_rate,
                "direction": trend.direction.value,
            },
        )

    # =========================================================================
    # サマリー生成ヘルパー
    # =========================================================================

    def _generate_summary(
        self,
        facts: DailyFacts,
        analysis: AnalysisResult,
    ) -> str:
        """
        デイリーダイジェストのサマリーを生成

        Args:
            facts: ファクト
            analysis: 分析結果

        Returns:
            str: サマリーテキスト
        """
        parts = []

        # チーム状況のサマリー
        if facts.team_fact:
            tf = facts.team_fact
            parts.append(f"{self._recipient_name}さん、おはようございますウル！")

            if tf.active_members > 0:
                parts.append(f"今日は{tf.active_members}/{tf.total_members}人が活動中です。")

            if tf.total_overdue_tasks > 0:
                parts.append(f"チーム全体で{tf.total_overdue_tasks}件のタスクが期限超過しています。")

        # 異常の数をサマリー
        critical_count = sum(1 for a in analysis.anomalies if a.severity == FeedbackPriority.CRITICAL)
        high_count = sum(1 for a in analysis.anomalies if a.severity == FeedbackPriority.HIGH)

        if critical_count > 0:
            parts.append(f"🔴 緊急の注意事項が{critical_count}件あります。")
        elif high_count > 0:
            parts.append(f"🟠 注意が必要な事項が{high_count}件あります。")
        else:
            parts.append("特に緊急の問題はありません。")

        # ポジティブな発見があれば追加
        if analysis.positive_findings:
            parts.append(f"また、良いニュースも{len(analysis.positive_findings)}件ありますウル！")

        return "\n".join(parts)

    def _generate_weekly_summary(
        self,
        weekly_facts: List[DailyFacts],
        analysis: AnalysisResult,
        week_start: date,
        week_end: date,
    ) -> str:
        """
        ウィークリーレビューのサマリーを生成
        """
        parts = [
            f"{self._recipient_name}さん、先週（{week_start.strftime('%m/%d')}〜{week_end.strftime('%m/%d')}）の振り返りですウル！",
            "",
        ]

        # 週のハイライト
        if analysis.positive_findings:
            parts.append("【今週のハイライト】")
            for finding in analysis.positive_findings[:2]:
                parts.append(f"・{finding.get('description', '')}")
            parts.append("")

        # 注意が必要な事項
        if analysis.anomalies:
            parts.append("【注意が必要な事項】")
            for anomaly in analysis.anomalies[:3]:
                parts.append(f"・{anomaly.description}")
            parts.append("")

        parts.append("詳細は以下をご確認ください。")

        return "\n".join(parts)

    def _generate_on_demand_summary(
        self,
        query: str,
        facts: DailyFacts,
        analysis: AnalysisResult,
    ) -> str:
        """
        オンデマンド分析のサマリーを生成
        """
        parts = [
            f"「{query}」についてお答えしますウル！",
            "",
        ]

        # 全体的な状況
        if facts.team_fact:
            tf = facts.team_fact
            parts.append(f"現在、チームの平均タスク完了率は{tf.avg_task_completion_rate:.0%}です。")

            if tf.members_needing_attention:
                parts.append(f"注意が必要なメンバー: {', '.join(tf.members_needing_attention[:3])}さん")

        return "\n".join(parts)

    # =========================================================================
    # 仮説・推奨アクション生成ヘルパー
    # =========================================================================

    def _generate_hypothesis(self, anomaly: Anomaly) -> str:
        """
        異常に対する仮説を生成

        Args:
            anomaly: 検出された異常

        Returns:
            str: 仮説テキスト
        """
        hypotheses = {
            "task_progress": "何かブロッカーがあるか、優先順位の調整が必要かもしれません",
            "goal_achievement": "目標設定の見直しか、サポートが必要かもしれません",
            "communication": "何か悩みを抱えているか、業務負荷が高い可能性があります",
            "team_health": "チーム全体のワークロードを見直す必要があるかもしれません",
            "risk_anomaly": "早めに状況を確認することをお勧めします",
        }
        return hypotheses.get(anomaly.anomaly_type, "状況の確認をお勧めします")

    def _generate_recommendation(self, anomaly: Anomaly) -> str:
        """
        異常に対する推奨アクションを生成

        Args:
            anomaly: 検出された異常

        Returns:
            str: 推奨アクションテキスト
        """
        recommendations = {
            "task_progress": "本人に声をかけて状況を確認してみてください",
            "goal_achievement": "1on1で進捗の確認と課題の洗い出しを行ってみてください",
            "communication": "さりげなく様子を見て、必要であれば話を聞いてあげてください",
            "team_health": "チームミーティングでワークロードの調整を検討してください",
            "risk_anomaly": "該当者に連絡を取り、状況を確認してください",
        }
        return recommendations.get(anomaly.anomaly_type, "状況を確認してください")

    def _generate_alert_recommendation(self, anomaly: Anomaly) -> str:
        """
        アラート用の強い推奨アクションを生成
        """
        if anomaly.severity == FeedbackPriority.CRITICAL:
            return f"⚠️ 今すぐ{anomaly.subject}に連絡を取り、状況を確認してください"
        return f"早めに{anomaly.subject}と話す機会を設けてください"

    # =========================================================================
    # ユーティリティ
    # =========================================================================

    def _priority_order(self, priority: FeedbackPriority) -> int:
        """優先度をソート用の数値に変換"""
        order = {
            FeedbackPriority.CRITICAL: 0,
            FeedbackPriority.HIGH: 1,
            FeedbackPriority.MEDIUM: 2,
            FeedbackPriority.LOW: 3,
        }
        return order.get(priority, 4)

    def _map_anomaly_type_to_category(self, anomaly_type: str) -> InsightCategory:
        """異常タイプをカテゴリにマッピング"""
        mapping = {
            "task_progress": InsightCategory.TASK_PROGRESS,
            "goal_achievement": InsightCategory.GOAL_ACHIEVEMENT,
            "communication": InsightCategory.COMMUNICATION,
            "team_health": InsightCategory.TEAM_HEALTH,
            "risk_anomaly": InsightCategory.RISK_ANOMALY,
        }
        return mapping.get(anomaly_type, InsightCategory.RISK_ANOMALY)


# =============================================================================
# ファクトリー関数
# =============================================================================


def create_feedback_generator(
    organization_id: UUID,
    recipient_user_id: UUID,
    recipient_name: str,
    max_items: int = DeliveryParameters.DAILY_DIGEST_MAX_ITEMS,
) -> FeedbackGenerator:
    """
    FeedbackGeneratorを作成

    Args:
        organization_id: 組織ID
        recipient_user_id: 受信者ユーザーID
        recipient_name: 受信者の名前
        max_items: 最大項目数

    Returns:
        FeedbackGenerator: フィードバック生成エンジン
    """
    return FeedbackGenerator(
        organization_id=organization_id,
        recipient_user_id=recipient_user_id,
        recipient_name=recipient_name,
        max_items_per_digest=max_items,
    )
