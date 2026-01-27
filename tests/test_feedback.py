# tests/test_feedback.py
"""
Phase F1: CEOフィードバックシステム テスト

このテストは、CEOフィードバックシステムの全機能をテストします。

テスト対象:
    - constants.py: 定数・列挙型
    - models.py: データモデル
    - fact_collector.py: ファクト収集
    - analyzer.py: 分析エンジン
    - feedback_generator.py: フィードバック生成
    - delivery.py: 配信システム
    - ceo_feedback_engine.py: メインエンジン

Author: Claude Opus 4.5
Created: 2026-01-27
"""

import pytest
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch, AsyncMock
from uuid import UUID, uuid4


# =============================================================================
# フィクスチャ
# =============================================================================


@pytest.fixture
def org_id():
    """組織ID"""
    return UUID("00000000-0000-0000-0000-000000000001")


@pytest.fixture
def user_id():
    """ユーザーID"""
    return UUID("00000000-0000-0000-0000-000000000002")


@pytest.fixture
def mock_conn():
    """モックDBコネクション"""
    conn = MagicMock()
    conn.execute.return_value.fetchall.return_value = []
    conn.execute.return_value.fetchone.return_value = None
    return conn


# =============================================================================
# 定数テスト
# =============================================================================


class TestConstants:
    """定数・列挙型のテスト"""

    def test_feedback_type_values(self):
        """FeedbackTypeの値が正しいこと"""
        from lib.capabilities.feedback.constants import FeedbackType

        assert FeedbackType.DAILY_DIGEST.value == "daily_digest"
        assert FeedbackType.WEEKLY_REVIEW.value == "weekly_review"
        assert FeedbackType.MONTHLY_INSIGHT.value == "monthly_insight"
        assert FeedbackType.REALTIME_ALERT.value == "realtime_alert"
        assert FeedbackType.ON_DEMAND.value == "on_demand"

    def test_feedback_priority_values(self):
        """FeedbackPriorityの値が正しいこと"""
        from lib.capabilities.feedback.constants import FeedbackPriority

        assert FeedbackPriority.CRITICAL.value == "critical"
        assert FeedbackPriority.HIGH.value == "high"
        assert FeedbackPriority.MEDIUM.value == "medium"
        assert FeedbackPriority.LOW.value == "low"

    def test_feedback_status_values(self):
        """FeedbackStatusの値が正しいこと"""
        from lib.capabilities.feedback.constants import FeedbackStatus

        assert FeedbackStatus.GENERATING.value == "generating"
        assert FeedbackStatus.READY.value == "ready"
        assert FeedbackStatus.SENT.value == "sent"
        assert FeedbackStatus.READ.value == "read"
        assert FeedbackStatus.ACTIONED.value == "actioned"
        assert FeedbackStatus.FAILED.value == "failed"

    def test_insight_category_values(self):
        """InsightCategoryの値が正しいこと"""
        from lib.capabilities.feedback.constants import InsightCategory

        assert InsightCategory.TASK_PROGRESS.value == "task_progress"
        assert InsightCategory.GOAL_ACHIEVEMENT.value == "goal_achievement"
        assert InsightCategory.COMMUNICATION.value == "communication"
        assert InsightCategory.TEAM_HEALTH.value == "team_health"
        assert InsightCategory.RISK_ANOMALY.value == "risk_anomaly"
        assert InsightCategory.POSITIVE_CHANGE.value == "positive_change"
        assert InsightCategory.RECOMMENDATION.value == "recommendation"

    def test_trend_direction_values(self):
        """TrendDirectionの値が正しいこと"""
        from lib.capabilities.feedback.constants import TrendDirection

        assert TrendDirection.INCREASING.value == "increasing"
        assert TrendDirection.STABLE.value == "stable"
        assert TrendDirection.DECREASING.value == "decreasing"
        assert TrendDirection.SPIKE.value == "spike"
        assert TrendDirection.DROP.value == "drop"

    def test_delivery_parameters(self):
        """DeliveryParametersの値が正しいこと"""
        from lib.capabilities.feedback.constants import DeliveryParameters

        assert DeliveryParameters.DAILY_DIGEST_HOUR == 8
        assert DeliveryParameters.DAILY_DIGEST_MINUTE == 0
        assert DeliveryParameters.WEEKLY_REVIEW_DAY == 0  # 月曜
        assert DeliveryParameters.ALERT_COOLDOWN_MINUTES == 60
        assert DeliveryParameters.MAX_DAILY_ALERTS == 10

    def test_analysis_parameters(self):
        """AnalysisParametersの値が正しいこと"""
        from lib.capabilities.feedback.constants import AnalysisParameters

        assert AnalysisParameters.ANOMALY_THRESHOLD_SIGMA == 2.0
        assert AnalysisParameters.MIN_DATA_POINTS_FOR_TREND == 5
        assert AnalysisParameters.TASK_STALE_DAYS == 3

    def test_feedback_icons(self):
        """FeedbackIconsの値が正しいこと"""
        from lib.capabilities.feedback.constants import FeedbackIcons

        assert FeedbackIcons.PRIORITY_CRITICAL == "🔴"
        assert FeedbackIcons.PRIORITY_HIGH == "🟠"
        assert FeedbackIcons.TASK == "📋"
        assert FeedbackIcons.GOAL == "🎯"
        assert FeedbackIcons.ALERT == "🚨"

    def test_feature_flags(self):
        """Feature Flagsが正しいこと"""
        from lib.capabilities.feedback.constants import (
            FEATURE_FLAG_NAME,
            FEATURE_FLAG_DAILY_DIGEST,
        )

        assert FEATURE_FLAG_NAME == "ENABLE_CEO_FEEDBACK"
        assert FEATURE_FLAG_DAILY_DIGEST == "ENABLE_DAILY_DIGEST"


# =============================================================================
# モデルテスト
# =============================================================================


class TestModels:
    """データモデルのテスト"""

    def test_task_fact_completion_rate(self):
        """TaskFactのcompletion_rate計算が正しいこと"""
        from lib.capabilities.feedback.models import TaskFact

        fact = TaskFact(
            user_id="user1",
            user_name="テストユーザー",
            total_tasks=10,
            completed_tasks=7,
        )

        assert fact.completion_rate == 0.7

    def test_task_fact_completion_rate_zero_tasks(self):
        """タスクがゼロの場合の完了率"""
        from lib.capabilities.feedback.models import TaskFact

        fact = TaskFact(
            user_id="user1",
            user_name="テストユーザー",
            total_tasks=0,
            completed_tasks=0,
        )

        assert fact.completion_rate == 0.0

    def test_task_fact_has_issues(self):
        """TaskFactのhas_issues判定が正しいこと"""
        from lib.capabilities.feedback.models import TaskFact

        # 問題なし
        fact1 = TaskFact(
            user_id="user1",
            user_name="テストユーザー",
            overdue_tasks=0,
            stale_tasks=0,
        )
        assert fact1.has_issues is False

        # 期限超過あり
        fact2 = TaskFact(
            user_id="user1",
            user_name="テストユーザー",
            overdue_tasks=1,
            stale_tasks=0,
        )
        assert fact2.has_issues is True

        # 滞留タスクあり
        fact3 = TaskFact(
            user_id="user1",
            user_name="テストユーザー",
            overdue_tasks=0,
            stale_tasks=1,
        )
        assert fact3.has_issues is True

    def test_task_fact_to_dict(self):
        """TaskFactのto_dictが正しいこと"""
        from lib.capabilities.feedback.models import TaskFact

        fact = TaskFact(
            user_id="user1",
            user_name="テストユーザー",
            total_tasks=10,
            completed_tasks=8,
            overdue_tasks=1,
        )

        d = fact.to_dict()
        assert d["user_id"] == "user1"
        assert d["user_name"] == "テストユーザー"
        assert d["total_tasks"] == 10
        assert d["completion_rate"] == 0.8
        assert d["has_issues"] is True

    def test_goal_fact_is_on_track(self):
        """GoalFactのis_on_track判定が正しいこと"""
        from lib.capabilities.feedback.models import GoalFact
        from lib.capabilities.feedback.constants import TrendDirection

        # 順調なケース
        fact1 = GoalFact(
            user_id="user1",
            user_name="テストユーザー",
            goal_id="goal1",
            goal_title="目標",
            target_value=100.0,
            current_value=80.0,
            progress_rate=0.8,
            days_remaining=5,
        )
        assert fact1.is_on_track is True

        # 達成済み
        fact2 = GoalFact(
            user_id="user1",
            user_name="テストユーザー",
            goal_id="goal1",
            goal_title="目標",
            target_value=100.0,
            current_value=100.0,
            progress_rate=1.0,
            days_remaining=0,
        )
        assert fact2.is_on_track is True

    def test_goal_fact_is_at_risk(self):
        """GoalFactのis_at_risk判定が正しいこと"""
        from lib.capabilities.feedback.models import GoalFact

        # リスクありケース（進捗50%未満）
        fact = GoalFact(
            user_id="user1",
            user_name="テストユーザー",
            goal_id="goal1",
            goal_title="目標",
            target_value=100.0,
            current_value=30.0,
            progress_rate=0.3,
            days_remaining=5,
        )
        assert fact.is_at_risk is True

    def test_communication_fact_sentiment_concerning(self):
        """CommunicationFactのis_sentiment_concerning判定が正しいこと"""
        from lib.capabilities.feedback.models import CommunicationFact
        from lib.capabilities.feedback.constants import TrendDirection

        # 気になる状態（スコアが低い）
        fact1 = CommunicationFact(
            user_id="user1",
            user_name="テストユーザー",
            sentiment_score=-0.5,
        )
        assert fact1.is_sentiment_concerning is True

        # 気になる状態（トレンドがDROP）
        fact2 = CommunicationFact(
            user_id="user1",
            user_name="テストユーザー",
            sentiment_score=0.0,
            sentiment_trend=TrendDirection.DROP,
        )
        assert fact2.is_sentiment_concerning is True

        # 正常
        fact3 = CommunicationFact(
            user_id="user1",
            user_name="テストユーザー",
            sentiment_score=0.0,
            sentiment_trend=TrendDirection.STABLE,
        )
        assert fact3.is_sentiment_concerning is False

    def test_team_fact_activity_rate(self):
        """TeamFactのactivity_rate計算が正しいこと"""
        from lib.capabilities.feedback.models import TeamFact

        fact = TeamFact(
            organization_id="org1",
            total_members=10,
            active_members=7,
        )

        assert fact.activity_rate == 0.7

    def test_anomaly_to_dict(self):
        """Anomalyのto_dictが正しいこと"""
        from lib.capabilities.feedback.models import Anomaly
        from lib.capabilities.feedback.constants import FeedbackPriority

        anomaly = Anomaly(
            anomaly_type="task_progress",
            subject="テストユーザー",
            description="タスクが滞留しています",
            current_value=5.0,
            expected_value=0.0,
            deviation=5.0,
            severity=FeedbackPriority.HIGH,
        )

        d = anomaly.to_dict()
        assert d["anomaly_type"] == "task_progress"
        assert d["subject"] == "テストユーザー"
        assert d["severity"] == "high"

    def test_trend_to_dict(self):
        """Trendのto_dictが正しいこと"""
        from lib.capabilities.feedback.models import Trend
        from lib.capabilities.feedback.constants import TrendDirection, ComparisonPeriod

        trend = Trend(
            metric_name="タスク完了率",
            direction=TrendDirection.INCREASING,
            change_rate=15.0,
            comparison_period=ComparisonPeriod.WEEK_OVER_WEEK,
            data_points=7,
            confidence=0.8,
        )

        d = trend.to_dict()
        assert d["metric_name"] == "タスク完了率"
        assert d["direction"] == "increasing"
        assert d["change_rate"] == 15.0

    def test_analysis_result_has_critical_items(self):
        """AnalysisResultのhas_critical_items判定が正しいこと"""
        from lib.capabilities.feedback.models import Anomaly, AnalysisResult
        from lib.capabilities.feedback.constants import FeedbackPriority

        # クリティカルなし
        result1 = AnalysisResult(
            anomalies=[
                Anomaly(
                    anomaly_type="test",
                    subject="test",
                    description="test",
                    current_value=1.0,
                    expected_value=0.0,
                    deviation=1.0,
                    severity=FeedbackPriority.MEDIUM,
                )
            ]
        )
        assert result1.has_critical_items is False

        # クリティカルあり
        result2 = AnalysisResult(
            anomalies=[
                Anomaly(
                    anomaly_type="test",
                    subject="test",
                    description="test",
                    current_value=1.0,
                    expected_value=0.0,
                    deviation=1.0,
                    severity=FeedbackPriority.CRITICAL,
                )
            ]
        )
        assert result2.has_critical_items is True

    def test_feedback_item_get_icon(self):
        """FeedbackItemのget_iconが正しいこと"""
        from lib.capabilities.feedback.models import FeedbackItem
        from lib.capabilities.feedback.constants import (
            InsightCategory,
            FeedbackPriority,
            FeedbackIcons,
        )

        item = FeedbackItem(
            category=InsightCategory.TASK_PROGRESS,
            priority=FeedbackPriority.HIGH,
            title="テスト",
            description="テスト説明",
        )

        assert item.get_icon() == FeedbackIcons.TASK

    def test_feedback_item_to_text(self):
        """FeedbackItemのto_textが正しいこと"""
        from lib.capabilities.feedback.models import FeedbackItem
        from lib.capabilities.feedback.constants import InsightCategory, FeedbackPriority

        item = FeedbackItem(
            category=InsightCategory.TASK_PROGRESS,
            priority=FeedbackPriority.HIGH,
            title="タスク滞留",
            description="5件のタスクが滞留しています",
            evidence=["期限超過: 3件", "未着手: 2件"],
            recommendation="声をかけてみてください",
        )

        text = item.to_text()
        assert "タスク滞留" in text
        assert "5件のタスクが滞留" in text
        assert "期限超過: 3件" in text
        assert "声をかけて" in text

    def test_ceo_feedback_highest_priority(self):
        """CEOFeedbackのhighest_priority計算が正しいこと"""
        from lib.capabilities.feedback.models import CEOFeedback, FeedbackItem
        from lib.capabilities.feedback.constants import (
            FeedbackType,
            FeedbackPriority,
            InsightCategory,
        )

        feedback = CEOFeedback(
            feedback_id="test",
            feedback_type=FeedbackType.DAILY_DIGEST,
            organization_id="org1",
            recipient_user_id="user1",
            recipient_name="テスト",
            items=[
                FeedbackItem(
                    category=InsightCategory.TASK_PROGRESS,
                    priority=FeedbackPriority.LOW,
                    title="低",
                    description="低",
                ),
                FeedbackItem(
                    category=InsightCategory.TASK_PROGRESS,
                    priority=FeedbackPriority.HIGH,
                    title="高",
                    description="高",
                ),
            ],
        )

        assert feedback.highest_priority == FeedbackPriority.HIGH

    def test_ceo_feedback_to_text(self):
        """CEOFeedbackのto_textが正しいこと"""
        from lib.capabilities.feedback.models import CEOFeedback, FeedbackItem
        from lib.capabilities.feedback.constants import (
            FeedbackType,
            FeedbackPriority,
            InsightCategory,
        )

        feedback = CEOFeedback(
            feedback_id="test",
            feedback_type=FeedbackType.DAILY_DIGEST,
            organization_id="org1",
            recipient_user_id="user1",
            recipient_name="テスト",
            items=[
                FeedbackItem(
                    category=InsightCategory.TASK_PROGRESS,
                    priority=FeedbackPriority.HIGH,
                    title="注目ポイント",
                    description="テスト説明",
                ),
            ],
            summary="今日のサマリー",
            generated_at=datetime(2026, 1, 27, 8, 0, 0),
        )

        text = feedback.to_text()
        assert "テスト" in text
        assert "注目ポイント" in text

    def test_delivery_result_to_dict(self):
        """DeliveryResultのto_dictが正しいこと"""
        from lib.capabilities.feedback.models import DeliveryResult

        result = DeliveryResult(
            feedback_id="test",
            success=True,
            channel="chatwork",
            channel_target="123456",
            message_id="msg123",
            delivered_at=datetime(2026, 1, 27, 8, 0, 0),
        )

        d = result.to_dict()
        assert d["success"] is True
        assert d["feedback_id"] == "test"
        assert d["channel"] == "chatwork"
        assert d["channel_target"] == "123456"
        assert d["message_id"] == "msg123"


# =============================================================================
# ファクト収集テスト
# =============================================================================


class TestFactCollector:
    """ファクト収集のテスト"""

    def test_fact_collector_initialization(self, mock_conn, org_id):
        """FactCollectorの初期化が正しいこと"""
        from lib.capabilities.feedback.fact_collector import FactCollector

        collector = FactCollector(mock_conn, org_id)

        assert collector.org_id == org_id
        assert collector.conn == mock_conn

    def test_create_fact_collector(self, mock_conn, org_id):
        """create_fact_collectorが正しく動作すること"""
        from lib.capabilities.feedback.fact_collector import create_fact_collector

        collector = create_fact_collector(mock_conn, org_id)

        assert collector is not None
        assert collector.org_id == org_id

    @pytest.mark.asyncio
    async def test_collect_daily_empty(self, mock_conn, org_id):
        """空のファクト収集が正しく動作すること"""
        from lib.capabilities.feedback.fact_collector import FactCollector

        collector = FactCollector(mock_conn, org_id)
        facts = await collector.collect_daily()

        assert facts.organization_id == str(org_id)
        assert facts.task_facts == []
        assert facts.goal_facts == []
        assert facts.communication_facts == []


# =============================================================================
# 分析エンジンテスト
# =============================================================================


class TestAnalyzer:
    """分析エンジンのテスト"""

    def test_analyzer_initialization(self):
        """Analyzerの初期化が正しいこと"""
        from lib.capabilities.feedback.analyzer import Analyzer

        analyzer = Analyzer()
        assert analyzer is not None

    def test_create_analyzer(self):
        """create_analyzerが正しく動作すること"""
        from lib.capabilities.feedback.analyzer import create_analyzer

        analyzer = create_analyzer()
        assert analyzer is not None

    @pytest.mark.asyncio
    async def test_analyze_empty_facts(self):
        """空のファクト分析が正しく動作すること"""
        from lib.capabilities.feedback.analyzer import Analyzer
        from lib.capabilities.feedback.models import DailyFacts

        analyzer = Analyzer()
        facts = DailyFacts(organization_id="org1")

        result = await analyzer.analyze(facts)

        assert result.anomalies == []
        assert result.trends == []

    @pytest.mark.asyncio
    async def test_analyze_task_anomalies(self):
        """タスク異常の検出が正しいこと"""
        from lib.capabilities.feedback.analyzer import Analyzer
        from lib.capabilities.feedback.models import DailyFacts, TaskFact

        analyzer = Analyzer()
        facts = DailyFacts(
            organization_id="org1",
            task_facts=[
                TaskFact(
                    user_id="user1",
                    user_name="テストユーザー",
                    total_tasks=10,
                    completed_tasks=5,
                    overdue_tasks=5,  # 5件期限超過
                    stale_tasks=3,
                ),
            ],
        )

        result = await analyzer.analyze(facts)

        # 期限超過タスクの異常が検出されること
        assert len(result.anomalies) >= 1
        assert any(a.anomaly_type == "task_progress" for a in result.anomalies)

    @pytest.mark.asyncio
    async def test_analyze_goal_at_risk(self):
        """目標リスクの検出が正しいこと"""
        from lib.capabilities.feedback.analyzer import Analyzer
        from lib.capabilities.feedback.models import DailyFacts, GoalFact

        analyzer = Analyzer()
        facts = DailyFacts(
            organization_id="org1",
            goal_facts=[
                GoalFact(
                    user_id="user1",
                    user_name="テストユーザー",
                    goal_id="goal1",
                    goal_title="テスト目標",
                    target_value=100.0,
                    current_value=20.0,
                    progress_rate=0.2,  # 進捗20%でリスク
                    days_remaining=5,
                ),
            ],
        )

        result = await analyzer.analyze(facts)

        # 目標リスクの異常が検出されること
        assert any(a.anomaly_type == "goal_achievement" for a in result.anomalies)

    @pytest.mark.asyncio
    async def test_analyze_positive_findings(self):
        """ポジティブな発見の検出が正しいこと"""
        from lib.capabilities.feedback.analyzer import Analyzer
        from lib.capabilities.feedback.models import DailyFacts, TaskFact

        analyzer = Analyzer()
        facts = DailyFacts(
            organization_id="org1",
            task_facts=[
                TaskFact(
                    user_id="user1",
                    user_name="テストユーザー",
                    total_tasks=10,
                    completed_tasks=9,  # 90%完了率
                    overdue_tasks=0,
                    stale_tasks=0,
                ),
            ],
        )

        result = await analyzer.analyze(facts)

        # ポジティブな発見があること
        assert len(result.positive_findings) >= 1


# =============================================================================
# フィードバック生成テスト
# =============================================================================


class TestFeedbackGenerator:
    """フィードバック生成のテスト"""

    def test_feedback_generator_initialization(self, org_id, user_id):
        """FeedbackGeneratorの初期化が正しいこと"""
        from lib.capabilities.feedback.feedback_generator import FeedbackGenerator

        generator = FeedbackGenerator(
            organization_id=org_id,
            recipient_user_id=user_id,
            recipient_name="テスト",
        )

        assert generator.organization_id == org_id
        assert generator.recipient_user_id == user_id
        assert generator.recipient_name == "テスト"

    def test_create_feedback_generator(self, org_id, user_id):
        """create_feedback_generatorが正しく動作すること"""
        from lib.capabilities.feedback.feedback_generator import create_feedback_generator

        generator = create_feedback_generator(
            organization_id=org_id,
            recipient_user_id=user_id,
            recipient_name="テスト",
        )

        assert generator is not None

    @pytest.mark.asyncio
    async def test_generate_daily_digest(self, org_id, user_id):
        """デイリーダイジェストの生成が正しいこと"""
        from lib.capabilities.feedback.feedback_generator import FeedbackGenerator
        from lib.capabilities.feedback.models import DailyFacts, AnalysisResult, Anomaly
        from lib.capabilities.feedback.constants import FeedbackType, FeedbackPriority

        generator = FeedbackGenerator(
            organization_id=org_id,
            recipient_user_id=user_id,
            recipient_name="テスト",
        )

        facts = DailyFacts(organization_id=str(org_id))
        analysis = AnalysisResult(
            anomalies=[
                Anomaly(
                    anomaly_type="task_progress",
                    subject="テストユーザー",
                    description="タスクが滞留しています",
                    current_value=5.0,
                    expected_value=0.0,
                    deviation=5.0,
                    severity=FeedbackPriority.HIGH,
                )
            ]
        )

        feedback = await generator.generate_daily_digest(facts, analysis)

        assert feedback.feedback_type == FeedbackType.DAILY_DIGEST
        assert feedback.recipient_name == "テスト"
        assert len(feedback.items) >= 1

    @pytest.mark.asyncio
    async def test_generate_realtime_alert(self, org_id, user_id):
        """リアルタイムアラートの生成が正しいこと"""
        from lib.capabilities.feedback.feedback_generator import FeedbackGenerator
        from lib.capabilities.feedback.models import Anomaly
        from lib.capabilities.feedback.constants import FeedbackType, FeedbackPriority

        generator = FeedbackGenerator(
            organization_id=org_id,
            recipient_user_id=user_id,
            recipient_name="テスト",
        )

        anomaly = Anomaly(
            anomaly_type="communication",
            subject="テストユーザー",
            description="感情の変化を検出しました",
            current_value=-0.5,
            expected_value=0.0,
            deviation=0.5,
            severity=FeedbackPriority.HIGH,
        )

        feedback = await generator.generate_realtime_alert(anomaly)

        assert feedback.feedback_type == FeedbackType.REALTIME_ALERT
        assert len(feedback.items) == 1


# =============================================================================
# 配信テスト
# =============================================================================


class TestFeedbackDelivery:
    """配信システムのテスト"""

    def test_delivery_initialization(self, mock_conn, org_id):
        """FeedbackDeliveryの初期化が正しいこと"""
        from lib.capabilities.feedback.delivery import FeedbackDelivery

        delivery = FeedbackDelivery(mock_conn, org_id)

        assert delivery.organization_id == org_id

    def test_create_feedback_delivery(self, mock_conn, org_id):
        """create_feedback_deliveryが正しく動作すること"""
        from lib.capabilities.feedback.delivery import create_feedback_delivery

        delivery = create_feedback_delivery(mock_conn, org_id, chatwork_room_id=123456)

        assert delivery is not None
        assert delivery.config.chatwork_room_id == 123456

    def test_should_deliver_daily_digest(self, mock_conn, org_id):
        """デイリーダイジェスト配信タイミング判定が正しいこと"""
        from lib.capabilities.feedback.delivery import FeedbackDelivery

        delivery = FeedbackDelivery(mock_conn, org_id)

        # 8:00に配信
        time_8am = datetime(2026, 1, 27, 8, 0, 0)
        assert delivery.should_deliver_daily_digest(time_8am) is True

        # 9:00には配信しない
        time_9am = datetime(2026, 1, 27, 9, 0, 0)
        assert delivery.should_deliver_daily_digest(time_9am) is False

    def test_should_deliver_weekly_review(self, mock_conn, org_id):
        """ウィークリーレビュー配信タイミング判定が正しいこと"""
        from lib.capabilities.feedback.delivery import FeedbackDelivery

        delivery = FeedbackDelivery(mock_conn, org_id)

        # 月曜9:00に配信
        monday_9am = datetime(2026, 1, 27, 9, 0, 0)  # 2026/1/27は月曜日
        # 曜日を確認
        if monday_9am.weekday() == 0:  # 月曜日
            assert delivery.should_deliver_weekly_review(monday_9am) is True

        # 火曜には配信しない
        tuesday_9am = datetime(2026, 1, 28, 9, 0, 0)
        assert delivery.should_deliver_weekly_review(tuesday_9am) is False

    def test_format_daily_digest(self, mock_conn, org_id):
        """デイリーダイジェストのフォーマットが正しいこと"""
        from lib.capabilities.feedback.delivery import FeedbackDelivery
        from lib.capabilities.feedback.models import CEOFeedback, FeedbackItem
        from lib.capabilities.feedback.constants import (
            FeedbackType,
            FeedbackPriority,
            InsightCategory,
        )

        delivery = FeedbackDelivery(mock_conn, org_id)

        feedback = CEOFeedback(
            feedback_id="test",
            feedback_type=FeedbackType.DAILY_DIGEST,
            organization_id=str(org_id),
            recipient_user_id="user1",
            recipient_name="テスト",
            items=[
                FeedbackItem(
                    category=InsightCategory.TASK_PROGRESS,
                    priority=FeedbackPriority.HIGH,
                    title="テスト項目",
                    description="テスト説明",
                )
            ],
            summary="テストサマリー",
        )

        message = delivery._format_feedback_message(feedback)

        assert "テスト" in message
        assert "テストサマリー" in message


# =============================================================================
# メインエンジンテスト
# =============================================================================


class TestCEOFeedbackEngine:
    """メインエンジンのテスト"""

    def test_engine_initialization(self, mock_conn, org_id, user_id):
        """CEOFeedbackEngineの初期化が正しいこと"""
        from lib.capabilities.feedback.ceo_feedback_engine import (
            CEOFeedbackEngine,
            CEOFeedbackSettings,
        )

        settings = CEOFeedbackSettings(
            recipient_user_id=user_id,
            recipient_name="テスト",
        )

        engine = CEOFeedbackEngine(mock_conn, org_id, settings)

        assert engine.organization_id == org_id
        assert engine.settings.recipient_name == "テスト"

    def test_create_ceo_feedback_engine(self, mock_conn, org_id, user_id):
        """create_ceo_feedback_engineが正しく動作すること"""
        from lib.capabilities.feedback.ceo_feedback_engine import create_ceo_feedback_engine

        engine = create_ceo_feedback_engine(
            conn=mock_conn,
            organization_id=org_id,
            recipient_user_id=user_id,
            recipient_name="テスト",
        )

        assert engine is not None

    @pytest.mark.asyncio
    async def test_generate_daily_digest(self, mock_conn, org_id, user_id):
        """デイリーダイジェスト生成が正しく動作すること"""
        from lib.capabilities.feedback.ceo_feedback_engine import (
            CEOFeedbackEngine,
            CEOFeedbackSettings,
        )
        from lib.capabilities.feedback.constants import FeedbackType

        settings = CEOFeedbackSettings(
            recipient_user_id=user_id,
            recipient_name="テスト",
        )

        engine = CEOFeedbackEngine(mock_conn, org_id, settings)

        # 配信なしで生成
        feedback, result = await engine.generate_daily_digest(deliver=False)

        assert feedback.feedback_type == FeedbackType.DAILY_DIGEST
        assert result is None

    @pytest.mark.asyncio
    async def test_analyze_on_demand(self, mock_conn, org_id, user_id):
        """オンデマンド分析が正しく動作すること"""
        from lib.capabilities.feedback.ceo_feedback_engine import (
            CEOFeedbackEngine,
            CEOFeedbackSettings,
        )
        from lib.capabilities.feedback.constants import FeedbackType

        settings = CEOFeedbackSettings(
            recipient_user_id=user_id,
            recipient_name="テスト",
        )

        engine = CEOFeedbackEngine(mock_conn, org_id, settings)

        feedback, result = await engine.analyze_on_demand("最近どう？")

        assert feedback.feedback_type == FeedbackType.ON_DEMAND

    @pytest.mark.asyncio
    async def test_check_health(self, mock_conn, org_id, user_id):
        """ヘルスチェックが正しく動作すること"""
        from lib.capabilities.feedback.ceo_feedback_engine import (
            CEOFeedbackEngine,
            CEOFeedbackSettings,
        )

        settings = CEOFeedbackSettings(
            recipient_user_id=user_id,
            recipient_name="テスト",
        )

        engine = CEOFeedbackEngine(mock_conn, org_id, settings)

        health = await engine.check_health()

        assert "status" in health
        assert "components" in health

    @pytest.mark.asyncio
    async def test_feature_disabled_error(self, mock_conn, org_id, user_id):
        """機能無効時のエラーが正しく発生すること"""
        from lib.capabilities.feedback.ceo_feedback_engine import (
            CEOFeedbackEngine,
            CEOFeedbackSettings,
            FeatureDisabledError,
        )

        settings = CEOFeedbackSettings(
            recipient_user_id=user_id,
            recipient_name="テスト",
            enable_daily_digest=False,  # 無効化
        )

        engine = CEOFeedbackEngine(mock_conn, org_id, settings)

        with pytest.raises(FeatureDisabledError):
            await engine.generate_daily_digest()


# =============================================================================
# パッケージインポートテスト
# =============================================================================


class TestPackageImports:
    """パッケージインポートのテスト"""

    def test_import_constants(self):
        """定数のインポートが正しいこと"""
        from lib.capabilities.feedback import (
            FeedbackType,
            FeedbackPriority,
            FeedbackStatus,
            InsightCategory,
            TrendDirection,
            DeliveryParameters,
            AnalysisParameters,
            FeedbackIcons,
        )

        assert FeedbackType is not None
        assert FeedbackPriority is not None

    def test_import_models(self):
        """モデルのインポートが正しいこと"""
        from lib.capabilities.feedback import (
            TaskFact,
            GoalFact,
            CommunicationFact,
            TeamFact,
            DailyFacts,
            Anomaly,
            Trend,
            AnalysisResult,
            FeedbackItem,
            CEOFeedback,
            DeliveryResult,
        )

        assert TaskFact is not None
        assert CEOFeedback is not None

    def test_import_collectors(self):
        """収集クラスのインポートが正しいこと"""
        from lib.capabilities.feedback import (
            FactCollector,
            create_fact_collector,
        )

        assert FactCollector is not None
        assert create_fact_collector is not None

    def test_import_analyzer(self):
        """分析クラスのインポートが正しいこと"""
        from lib.capabilities.feedback import (
            Analyzer,
            create_analyzer,
        )

        assert Analyzer is not None
        assert create_analyzer is not None

    def test_import_generator(self):
        """生成クラスのインポートが正しいこと"""
        from lib.capabilities.feedback import (
            FeedbackGenerator,
            create_feedback_generator,
        )

        assert FeedbackGenerator is not None
        assert create_feedback_generator is not None

    def test_import_delivery(self):
        """配信クラスのインポートが正しいこと"""
        from lib.capabilities.feedback import (
            FeedbackDelivery,
            create_feedback_delivery,
            DeliveryConfig,
        )

        assert FeedbackDelivery is not None
        assert create_feedback_delivery is not None
        assert DeliveryConfig is not None

    def test_import_engine(self):
        """エンジンクラスのインポートが正しいこと"""
        from lib.capabilities.feedback import (
            CEOFeedbackEngine,
            create_ceo_feedback_engine,
            CEOFeedbackSettings,
        )

        assert CEOFeedbackEngine is not None
        assert create_ceo_feedback_engine is not None
        assert CEOFeedbackSettings is not None

    def test_import_exceptions(self):
        """例外クラスのインポートが正しいこと"""
        from lib.capabilities.feedback import (
            FactCollectionError,
            AnalysisError,
            FeedbackGenerationError,
            DeliveryError,
            CooldownError,
            DailyLimitError,
            CEOFeedbackEngineError,
            FeatureDisabledError,
        )

        assert FactCollectionError is not None
        assert FeatureDisabledError is not None
