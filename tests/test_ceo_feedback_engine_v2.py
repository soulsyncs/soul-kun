# tests/test_ceo_feedback_engine_v2.py
"""
CEOフィードバックエンジン包括的テスト v2

テスト対象: lib/capabilities/feedback/ceo_feedback_engine.py

テスト内容:
    1. 例外クラス（CEOFeedbackEngineError, FeatureDisabledError）
    2. CEOFeedbackSettings データクラス
    3. CEOFeedbackEngine 初期化
    4. 機能フラグチェック
    5. フィードバック生成フロー（モック使用）
    6. エラーハンドリング
    7. ファクトリー関数

Author: Claude Opus 4.5
Created: 2026-02-04
"""

import pytest
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock
from uuid import UUID, uuid4


# =============================================================================
# フィクスチャ
# =============================================================================


@pytest.fixture
def org_id():
    """テスト用組織ID"""
    return UUID("11111111-1111-1111-1111-111111111111")


@pytest.fixture
def recipient_user_id():
    """テスト用受信者ユーザーID"""
    return UUID("22222222-2222-2222-2222-222222222222")


@pytest.fixture
def recipient_name():
    """テスト用受信者名"""
    return "テスト社長"


@pytest.fixture
def chatwork_room_id():
    """テスト用ChatWorkルームID"""
    return 12345678


@pytest.fixture
def mock_conn():
    """モックDBコネクション"""
    conn = MagicMock()
    conn.execute.return_value.fetchall.return_value = []
    conn.execute.return_value.fetchone.return_value = None
    return conn


@pytest.fixture
def settings(recipient_user_id, recipient_name, chatwork_room_id):
    """テスト用CEOフィードバック設定"""
    from lib.capabilities.feedback.ceo_feedback_engine import CEOFeedbackSettings
    return CEOFeedbackSettings(
        recipient_user_id=recipient_user_id,
        recipient_name=recipient_name,
        chatwork_room_id=chatwork_room_id,
    )


@pytest.fixture
def settings_all_disabled(recipient_user_id, recipient_name):
    """全機能無効化されたテスト用設定"""
    from lib.capabilities.feedback.ceo_feedback_engine import CEOFeedbackSettings
    return CEOFeedbackSettings(
        recipient_user_id=recipient_user_id,
        recipient_name=recipient_name,
        enable_daily_digest=False,
        enable_weekly_review=False,
        enable_monthly_insight=False,
        enable_realtime_alert=False,
        enable_on_demand=False,
    )


@pytest.fixture
def mock_daily_facts(org_id):
    """モックDailyFacts"""
    from lib.capabilities.feedback.models import DailyFacts, TaskFact, TeamFact
    return DailyFacts(
        date=date.today(),
        organization_id=str(org_id),
        task_facts=[
            TaskFact(
                user_id="user1",
                user_name="田中",
                total_tasks=10,
                completed_tasks=7,
                overdue_tasks=1,
            )
        ],
        team_fact=TeamFact(
            organization_id=str(org_id),
            total_members=5,
            active_members=4,
        ),
    )


@pytest.fixture
def mock_analysis_result():
    """モックAnalysisResult"""
    from lib.capabilities.feedback.models import AnalysisResult, Anomaly
    from lib.capabilities.feedback.constants import FeedbackPriority
    return AnalysisResult(
        anomalies=[
            Anomaly(
                anomaly_type="task_overdue",
                subject="田中",
                description="期限超過タスクがあります",
                current_value=3.0,
                expected_value=0.0,
                deviation=2.5,
                severity=FeedbackPriority.MEDIUM,
            )
        ],
        trends=[],
        notable_changes=[],
        positive_findings=[],
    )


@pytest.fixture
def mock_ceo_feedback(org_id, recipient_user_id, recipient_name):
    """モックCEOFeedback"""
    from lib.capabilities.feedback.models import CEOFeedback, FeedbackItem
    from lib.capabilities.feedback.constants import (
        FeedbackType,
        FeedbackPriority,
        FeedbackStatus,
        InsightCategory,
    )
    return CEOFeedback(
        feedback_id="feedback-001",
        feedback_type=FeedbackType.DAILY_DIGEST,
        organization_id=str(org_id),
        recipient_user_id=str(recipient_user_id),
        recipient_name=recipient_name,
        items=[
            FeedbackItem(
                category=InsightCategory.TASK_PROGRESS,
                priority=FeedbackPriority.MEDIUM,
                title="タスク進捗",
                description="田中さんのタスクに期限超過があります",
            )
        ],
        summary="今日の注目ポイント",
        status=FeedbackStatus.READY,
        generated_at=datetime.now(),
    )


@pytest.fixture
def mock_delivery_result():
    """モックDeliveryResult"""
    from lib.capabilities.feedback.models import DeliveryResult
    return DeliveryResult(
        feedback_id="feedback-001",
        success=True,
        channel="chatwork",
        channel_target="12345678",
        message_id="msg-001",
        delivered_at=datetime.now(),
    )


@pytest.fixture
def mock_anomaly():
    """モックAnomaly"""
    from lib.capabilities.feedback.models import Anomaly
    from lib.capabilities.feedback.constants import FeedbackPriority
    return Anomaly(
        anomaly_type="sudden_activity_drop",
        subject="佐藤さん",
        description="活動量が急激に低下しました",
        current_value=2.0,
        expected_value=10.0,
        deviation=3.0,
        severity=FeedbackPriority.HIGH,
    )


# =============================================================================
# 例外クラステスト
# =============================================================================


class TestCEOFeedbackEngineError:
    """CEOFeedbackEngineErrorのテスト"""

    def test_basic_initialization(self):
        """基本的な初期化"""
        from lib.capabilities.feedback.ceo_feedback_engine import CEOFeedbackEngineError

        error = CEOFeedbackEngineError("テストエラー")
        assert str(error) == "テストエラー"
        assert error.message == "テストエラー"
        assert error.operation == ""
        assert error.details == {}
        assert error.original_exception is None

    def test_full_initialization(self):
        """全パラメータでの初期化"""
        from lib.capabilities.feedback.ceo_feedback_engine import CEOFeedbackEngineError

        original = ValueError("元エラー")
        error = CEOFeedbackEngineError(
            message="テストエラー",
            operation="daily_digest",
            details={"key": "value"},
            original_exception=original,
        )
        assert error.message == "テストエラー"
        assert error.operation == "daily_digest"
        assert error.details == {"key": "value"}
        assert error.original_exception is original

    def test_inheritance(self):
        """Exceptionを継承していること"""
        from lib.capabilities.feedback.ceo_feedback_engine import CEOFeedbackEngineError

        error = CEOFeedbackEngineError("test")
        assert isinstance(error, Exception)


class TestFeatureDisabledError:
    """FeatureDisabledErrorのテスト"""

    def test_inheritance(self):
        """CEOFeedbackEngineErrorを継承していること"""
        from lib.capabilities.feedback.ceo_feedback_engine import (
            CEOFeedbackEngineError,
            FeatureDisabledError,
        )

        error = FeatureDisabledError("機能無効")
        assert isinstance(error, CEOFeedbackEngineError)
        assert isinstance(error, Exception)

    def test_with_operation(self):
        """operationパラメータ付き初期化"""
        from lib.capabilities.feedback.ceo_feedback_engine import FeatureDisabledError

        error = FeatureDisabledError(
            message="デイリーダイジェスト機能は無効化されています",
            operation="daily_digest",
        )
        assert error.message == "デイリーダイジェスト機能は無効化されています"
        assert error.operation == "daily_digest"


# =============================================================================
# CEOFeedbackSettingsテスト
# =============================================================================


class TestCEOFeedbackSettings:
    """CEOFeedbackSettingsデータクラスのテスト"""

    def test_basic_initialization(self, recipient_user_id, recipient_name):
        """基本的な初期化（必須パラメータのみ）"""
        from lib.capabilities.feedback.ceo_feedback_engine import CEOFeedbackSettings

        settings = CEOFeedbackSettings(
            recipient_user_id=recipient_user_id,
            recipient_name=recipient_name,
        )
        assert settings.recipient_user_id == recipient_user_id
        assert settings.recipient_name == recipient_name
        assert settings.chatwork_room_id is None
        # デフォルト値の確認
        assert settings.enable_daily_digest is True
        assert settings.enable_weekly_review is True
        assert settings.enable_monthly_insight is True
        assert settings.enable_realtime_alert is True
        assert settings.enable_on_demand is True

    def test_full_initialization(self, recipient_user_id, recipient_name, chatwork_room_id):
        """全パラメータでの初期化"""
        from lib.capabilities.feedback.ceo_feedback_engine import CEOFeedbackSettings

        settings = CEOFeedbackSettings(
            recipient_user_id=recipient_user_id,
            recipient_name=recipient_name,
            chatwork_room_id=chatwork_room_id,
            enable_daily_digest=False,
            enable_weekly_review=True,
            enable_monthly_insight=False,
            enable_realtime_alert=True,
            enable_on_demand=False,
        )
        assert settings.recipient_user_id == recipient_user_id
        assert settings.recipient_name == recipient_name
        assert settings.chatwork_room_id == chatwork_room_id
        assert settings.enable_daily_digest is False
        assert settings.enable_weekly_review is True
        assert settings.enable_monthly_insight is False
        assert settings.enable_realtime_alert is True
        assert settings.enable_on_demand is False

    def test_dataclass_behavior(self, recipient_user_id, recipient_name):
        """dataclassとしての挙動"""
        from lib.capabilities.feedback.ceo_feedback_engine import CEOFeedbackSettings

        settings1 = CEOFeedbackSettings(
            recipient_user_id=recipient_user_id,
            recipient_name=recipient_name,
        )
        settings2 = CEOFeedbackSettings(
            recipient_user_id=recipient_user_id,
            recipient_name=recipient_name,
        )
        # 同じ値なら等価
        assert settings1 == settings2


# =============================================================================
# CEOFeedbackEngine初期化テスト
# =============================================================================


class TestCEOFeedbackEngineInitialization:
    """CEOFeedbackEngineの初期化テスト"""

    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_fact_collector")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_analyzer")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_generator")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_delivery")
    def test_basic_initialization(
        self,
        mock_create_delivery,
        mock_create_generator,
        mock_create_analyzer,
        mock_create_collector,
        mock_conn,
        org_id,
        settings,
    ):
        """基本的な初期化"""
        from lib.capabilities.feedback.ceo_feedback_engine import CEOFeedbackEngine

        engine = CEOFeedbackEngine(
            conn=mock_conn,
            organization_id=org_id,
            settings=settings,
        )

        assert engine._conn is mock_conn
        assert engine._org_id == org_id
        assert engine._settings is settings

        # 各コンポーネントが初期化されていることを確認
        mock_create_collector.assert_called_once_with(mock_conn, org_id)
        mock_create_analyzer.assert_called_once()
        mock_create_generator.assert_called_once()
        mock_create_delivery.assert_called_once()

    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_fact_collector")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_analyzer")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_generator")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_delivery")
    def test_properties(
        self,
        mock_create_delivery,
        mock_create_generator,
        mock_create_analyzer,
        mock_create_collector,
        mock_conn,
        org_id,
        settings,
    ):
        """プロパティへのアクセス"""
        from lib.capabilities.feedback.ceo_feedback_engine import CEOFeedbackEngine

        engine = CEOFeedbackEngine(
            conn=mock_conn,
            organization_id=org_id,
            settings=settings,
        )

        assert engine.conn is mock_conn
        assert engine.organization_id == org_id
        assert engine.settings is settings


# =============================================================================
# 機能フラグチェックテスト
# =============================================================================


class TestFeatureFlagChecking:
    """機能フラグチェックのテスト"""

    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_fact_collector")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_analyzer")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_generator")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_delivery")
    @pytest.mark.asyncio
    async def test_daily_digest_disabled(
        self,
        mock_create_delivery,
        mock_create_generator,
        mock_create_analyzer,
        mock_create_collector,
        mock_conn,
        org_id,
        settings_all_disabled,
    ):
        """デイリーダイジェストが無効化されている場合"""
        from lib.capabilities.feedback.ceo_feedback_engine import (
            CEOFeedbackEngine,
            FeatureDisabledError,
        )

        engine = CEOFeedbackEngine(
            conn=mock_conn,
            organization_id=org_id,
            settings=settings_all_disabled,
        )

        with pytest.raises(FeatureDisabledError) as exc_info:
            await engine.generate_daily_digest()

        assert "デイリーダイジェスト機能は無効化されています" in str(exc_info.value)
        assert exc_info.value.operation == "daily_digest"

    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_fact_collector")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_analyzer")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_generator")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_delivery")
    @pytest.mark.asyncio
    async def test_weekly_review_disabled(
        self,
        mock_create_delivery,
        mock_create_generator,
        mock_create_analyzer,
        mock_create_collector,
        mock_conn,
        org_id,
        settings_all_disabled,
    ):
        """ウィークリーレビューが無効化されている場合"""
        from lib.capabilities.feedback.ceo_feedback_engine import (
            CEOFeedbackEngine,
            FeatureDisabledError,
        )

        engine = CEOFeedbackEngine(
            conn=mock_conn,
            organization_id=org_id,
            settings=settings_all_disabled,
        )

        with pytest.raises(FeatureDisabledError) as exc_info:
            await engine.generate_weekly_review()

        assert "ウィークリーレビュー機能は無効化されています" in str(exc_info.value)
        assert exc_info.value.operation == "weekly_review"

    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_fact_collector")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_analyzer")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_generator")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_delivery")
    @pytest.mark.asyncio
    async def test_realtime_alert_disabled(
        self,
        mock_create_delivery,
        mock_create_generator,
        mock_create_analyzer,
        mock_create_collector,
        mock_conn,
        org_id,
        settings_all_disabled,
        mock_anomaly,
    ):
        """リアルタイムアラートが無効化されている場合"""
        from lib.capabilities.feedback.ceo_feedback_engine import (
            CEOFeedbackEngine,
            FeatureDisabledError,
        )

        engine = CEOFeedbackEngine(
            conn=mock_conn,
            organization_id=org_id,
            settings=settings_all_disabled,
        )

        with pytest.raises(FeatureDisabledError) as exc_info:
            await engine.send_realtime_alert(mock_anomaly)

        assert "リアルタイムアラート機能は無効化されています" in str(exc_info.value)
        assert exc_info.value.operation == "realtime_alert"

    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_fact_collector")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_analyzer")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_generator")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_delivery")
    @pytest.mark.asyncio
    async def test_on_demand_disabled(
        self,
        mock_create_delivery,
        mock_create_generator,
        mock_create_analyzer,
        mock_create_collector,
        mock_conn,
        org_id,
        settings_all_disabled,
    ):
        """オンデマンド分析が無効化されている場合"""
        from lib.capabilities.feedback.ceo_feedback_engine import (
            CEOFeedbackEngine,
            FeatureDisabledError,
        )

        engine = CEOFeedbackEngine(
            conn=mock_conn,
            organization_id=org_id,
            settings=settings_all_disabled,
        )

        with pytest.raises(FeatureDisabledError) as exc_info:
            await engine.analyze_on_demand("最近チームどう？")

        assert "オンデマンド分析機能は無効化されています" in str(exc_info.value)
        assert exc_info.value.operation == "on_demand"


# =============================================================================
# フィードバック生成フローテスト
# =============================================================================


class TestFeedbackGenerationFlow:
    """フィードバック生成フローのテスト"""

    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_fact_collector")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_analyzer")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_generator")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_delivery")
    @pytest.mark.asyncio
    async def test_generate_daily_digest_with_delivery(
        self,
        mock_create_delivery,
        mock_create_generator,
        mock_create_analyzer,
        mock_create_collector,
        mock_conn,
        org_id,
        settings,
        mock_daily_facts,
        mock_analysis_result,
        mock_ceo_feedback,
        mock_delivery_result,
    ):
        """デイリーダイジェストの生成・配信フロー"""
        from lib.capabilities.feedback.ceo_feedback_engine import CEOFeedbackEngine

        # モックの設定
        mock_collector = AsyncMock()
        mock_collector.collect_daily = AsyncMock(return_value=mock_daily_facts)
        mock_create_collector.return_value = mock_collector

        mock_analyzer = AsyncMock()
        mock_analyzer.analyze = AsyncMock(return_value=mock_analysis_result)
        mock_create_analyzer.return_value = mock_analyzer

        mock_generator = AsyncMock()
        mock_generator.generate_daily_digest = AsyncMock(return_value=mock_ceo_feedback)
        mock_create_generator.return_value = mock_generator

        mock_delivery = AsyncMock()
        mock_delivery.deliver = AsyncMock(return_value=mock_delivery_result)
        mock_create_delivery.return_value = mock_delivery

        engine = CEOFeedbackEngine(
            conn=mock_conn,
            organization_id=org_id,
            settings=settings,
        )

        # 実行
        feedback, delivery_result = await engine.generate_daily_digest(deliver=True)

        # 検証
        assert feedback is mock_ceo_feedback
        assert delivery_result is mock_delivery_result

        # 各コンポーネントが正しく呼ばれたことを確認
        mock_collector.collect_daily.assert_called_once()
        mock_analyzer.analyze.assert_called_once_with(mock_daily_facts)
        mock_generator.generate_daily_digest.assert_called_once()
        mock_delivery.deliver.assert_called_once_with(mock_ceo_feedback)

    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_fact_collector")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_analyzer")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_generator")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_delivery")
    @pytest.mark.asyncio
    async def test_generate_daily_digest_without_delivery(
        self,
        mock_create_delivery,
        mock_create_generator,
        mock_create_analyzer,
        mock_create_collector,
        mock_conn,
        org_id,
        settings,
        mock_daily_facts,
        mock_analysis_result,
        mock_ceo_feedback,
    ):
        """デイリーダイジェストの生成のみ（配信なし）"""
        from lib.capabilities.feedback.ceo_feedback_engine import CEOFeedbackEngine

        # モックの設定
        mock_collector = AsyncMock()
        mock_collector.collect_daily = AsyncMock(return_value=mock_daily_facts)
        mock_create_collector.return_value = mock_collector

        mock_analyzer = AsyncMock()
        mock_analyzer.analyze = AsyncMock(return_value=mock_analysis_result)
        mock_create_analyzer.return_value = mock_analyzer

        mock_generator = AsyncMock()
        mock_generator.generate_daily_digest = AsyncMock(return_value=mock_ceo_feedback)
        mock_create_generator.return_value = mock_generator

        mock_delivery = AsyncMock()
        mock_create_delivery.return_value = mock_delivery

        engine = CEOFeedbackEngine(
            conn=mock_conn,
            organization_id=org_id,
            settings=settings,
        )

        # 実行（deliver=False）
        feedback, delivery_result = await engine.generate_daily_digest(deliver=False)

        # 検証
        assert feedback is mock_ceo_feedback
        assert delivery_result is None

        # 配信は呼ばれていない
        mock_delivery.deliver.assert_not_called()

    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_fact_collector")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_analyzer")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_generator")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_delivery")
    @pytest.mark.asyncio
    async def test_generate_daily_digest_with_target_date(
        self,
        mock_create_delivery,
        mock_create_generator,
        mock_create_analyzer,
        mock_create_collector,
        mock_conn,
        org_id,
        settings,
        mock_daily_facts,
        mock_analysis_result,
        mock_ceo_feedback,
    ):
        """指定日のデイリーダイジェスト生成"""
        from lib.capabilities.feedback.ceo_feedback_engine import CEOFeedbackEngine

        # モックの設定
        mock_collector = AsyncMock()
        mock_collector.collect_daily = AsyncMock(return_value=mock_daily_facts)
        mock_create_collector.return_value = mock_collector

        mock_analyzer = AsyncMock()
        mock_analyzer.analyze = AsyncMock(return_value=mock_analysis_result)
        mock_create_analyzer.return_value = mock_analyzer

        mock_generator = AsyncMock()
        mock_generator.generate_daily_digest = AsyncMock(return_value=mock_ceo_feedback)
        mock_create_generator.return_value = mock_generator

        mock_delivery = AsyncMock()
        mock_create_delivery.return_value = mock_delivery

        engine = CEOFeedbackEngine(
            conn=mock_conn,
            organization_id=org_id,
            settings=settings,
        )

        target_date = date(2026, 1, 15)
        await engine.generate_daily_digest(target_date=target_date, deliver=False)

        # 指定された日付で呼ばれたことを確認
        mock_collector.collect_daily.assert_called_once_with(target_date)

    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_fact_collector")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_analyzer")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_generator")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_delivery")
    @pytest.mark.asyncio
    async def test_generate_weekly_review_with_delivery(
        self,
        mock_create_delivery,
        mock_create_generator,
        mock_create_analyzer,
        mock_create_collector,
        mock_conn,
        org_id,
        settings,
        mock_daily_facts,
        mock_analysis_result,
        mock_ceo_feedback,
        mock_delivery_result,
    ):
        """ウィークリーレビューの生成・配信フロー"""
        from lib.capabilities.feedback.ceo_feedback_engine import CEOFeedbackEngine
        from lib.capabilities.feedback.constants import FeedbackType

        # フィードバックのタイプを変更
        mock_ceo_feedback.feedback_type = FeedbackType.WEEKLY_REVIEW

        # モックの設定
        mock_collector = AsyncMock()
        mock_collector.collect_weekly = AsyncMock(return_value=[mock_daily_facts])
        mock_create_collector.return_value = mock_collector

        mock_analyzer = AsyncMock()
        mock_analyzer.analyze = AsyncMock(return_value=mock_analysis_result)
        mock_create_analyzer.return_value = mock_analyzer

        mock_generator = AsyncMock()
        mock_generator.generate_weekly_review = AsyncMock(return_value=mock_ceo_feedback)
        mock_create_generator.return_value = mock_generator

        mock_delivery = AsyncMock()
        mock_delivery.deliver = AsyncMock(return_value=mock_delivery_result)
        mock_create_delivery.return_value = mock_delivery

        engine = CEOFeedbackEngine(
            conn=mock_conn,
            organization_id=org_id,
            settings=settings,
        )

        # 実行
        feedback, delivery_result = await engine.generate_weekly_review(deliver=True)

        # 検証
        assert feedback is mock_ceo_feedback
        assert delivery_result is mock_delivery_result

        mock_collector.collect_weekly.assert_called_once()
        mock_generator.generate_weekly_review.assert_called_once()
        mock_delivery.deliver.assert_called_once()

    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_fact_collector")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_analyzer")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_generator")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_delivery")
    @pytest.mark.asyncio
    async def test_generate_weekly_review_with_empty_facts(
        self,
        mock_create_delivery,
        mock_create_generator,
        mock_create_analyzer,
        mock_create_collector,
        mock_conn,
        org_id,
        settings,
        mock_ceo_feedback,
    ):
        """ウィークリーレビュー - 週のファクトが空の場合"""
        from lib.capabilities.feedback.ceo_feedback_engine import CEOFeedbackEngine
        from lib.capabilities.feedback.models import AnalysisResult

        # モックの設定 - 空のファクト
        mock_collector = AsyncMock()
        mock_collector.collect_weekly = AsyncMock(return_value=[])
        mock_create_collector.return_value = mock_collector

        mock_analyzer = AsyncMock()
        mock_create_analyzer.return_value = mock_analyzer

        mock_generator = AsyncMock()
        mock_generator.generate_weekly_review = AsyncMock(return_value=mock_ceo_feedback)
        mock_create_generator.return_value = mock_generator

        mock_delivery = AsyncMock()
        mock_create_delivery.return_value = mock_delivery

        engine = CEOFeedbackEngine(
            conn=mock_conn,
            organization_id=org_id,
            settings=settings,
        )

        await engine.generate_weekly_review(deliver=False)

        # 空のファクトでもフィードバック生成が呼ばれる
        mock_generator.generate_weekly_review.assert_called_once()
        # analyzerは呼ばれない（ファクトがないため）
        mock_analyzer.analyze.assert_not_called()

    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_fact_collector")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_analyzer")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_generator")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_delivery")
    @pytest.mark.asyncio
    async def test_send_realtime_alert(
        self,
        mock_create_delivery,
        mock_create_generator,
        mock_create_analyzer,
        mock_create_collector,
        mock_conn,
        org_id,
        settings,
        mock_anomaly,
        mock_ceo_feedback,
        mock_delivery_result,
    ):
        """リアルタイムアラートの送信"""
        from lib.capabilities.feedback.ceo_feedback_engine import CEOFeedbackEngine
        from lib.capabilities.feedback.constants import FeedbackType

        mock_ceo_feedback.feedback_type = FeedbackType.REALTIME_ALERT

        # モックの設定
        mock_collector = AsyncMock()
        mock_create_collector.return_value = mock_collector

        mock_analyzer = AsyncMock()
        mock_create_analyzer.return_value = mock_analyzer

        mock_generator = AsyncMock()
        mock_generator.generate_realtime_alert = AsyncMock(return_value=mock_ceo_feedback)
        mock_create_generator.return_value = mock_generator

        mock_delivery = AsyncMock()
        mock_delivery.deliver = AsyncMock(return_value=mock_delivery_result)
        mock_create_delivery.return_value = mock_delivery

        engine = CEOFeedbackEngine(
            conn=mock_conn,
            organization_id=org_id,
            settings=settings,
        )

        # 実行
        feedback, delivery_result = await engine.send_realtime_alert(mock_anomaly)

        # 検証
        assert feedback is mock_ceo_feedback
        assert delivery_result is mock_delivery_result

        mock_generator.generate_realtime_alert.assert_called_once_with(
            anomaly=mock_anomaly,
            facts=None,
        )
        mock_delivery.deliver.assert_called_once()

    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_fact_collector")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_analyzer")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_generator")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_delivery")
    @pytest.mark.asyncio
    async def test_send_realtime_alert_with_facts(
        self,
        mock_create_delivery,
        mock_create_generator,
        mock_create_analyzer,
        mock_create_collector,
        mock_conn,
        org_id,
        settings,
        mock_anomaly,
        mock_daily_facts,
        mock_ceo_feedback,
        mock_delivery_result,
    ):
        """リアルタイムアラートの送信（ファクト付き）"""
        from lib.capabilities.feedback.ceo_feedback_engine import CEOFeedbackEngine

        # モックの設定
        mock_generator = AsyncMock()
        mock_generator.generate_realtime_alert = AsyncMock(return_value=mock_ceo_feedback)
        mock_create_generator.return_value = mock_generator

        mock_delivery = AsyncMock()
        mock_delivery.deliver = AsyncMock(return_value=mock_delivery_result)
        mock_create_delivery.return_value = mock_delivery

        engine = CEOFeedbackEngine(
            conn=mock_conn,
            organization_id=org_id,
            settings=settings,
        )

        # ファクト付きで実行
        await engine.send_realtime_alert(mock_anomaly, facts=mock_daily_facts)

        mock_generator.generate_realtime_alert.assert_called_once_with(
            anomaly=mock_anomaly,
            facts=mock_daily_facts,
        )

    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_fact_collector")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_analyzer")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_generator")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_delivery")
    @pytest.mark.asyncio
    async def test_analyze_on_demand_with_delivery(
        self,
        mock_create_delivery,
        mock_create_generator,
        mock_create_analyzer,
        mock_create_collector,
        mock_conn,
        org_id,
        settings,
        mock_daily_facts,
        mock_analysis_result,
        mock_ceo_feedback,
        mock_delivery_result,
    ):
        """オンデマンド分析の実行（配信あり）"""
        from lib.capabilities.feedback.ceo_feedback_engine import CEOFeedbackEngine

        # モックの設定
        mock_collector = AsyncMock()
        mock_collector.collect_daily = AsyncMock(return_value=mock_daily_facts)
        mock_create_collector.return_value = mock_collector

        mock_analyzer = AsyncMock()
        mock_analyzer.analyze = AsyncMock(return_value=mock_analysis_result)
        mock_create_analyzer.return_value = mock_analyzer

        mock_generator = AsyncMock()
        mock_generator.generate_on_demand_analysis = AsyncMock(return_value=mock_ceo_feedback)
        mock_create_generator.return_value = mock_generator

        mock_delivery = AsyncMock()
        mock_delivery.deliver = AsyncMock(return_value=mock_delivery_result)
        mock_create_delivery.return_value = mock_delivery

        engine = CEOFeedbackEngine(
            conn=mock_conn,
            organization_id=org_id,
            settings=settings,
        )

        query = "最近チームの調子どう？"
        feedback, delivery_result = await engine.analyze_on_demand(query, deliver=True)

        # 検証
        assert feedback is mock_ceo_feedback
        assert delivery_result is mock_delivery_result

        mock_collector.collect_daily.assert_called_once()
        mock_analyzer.analyze.assert_called_once()
        mock_generator.generate_on_demand_analysis.assert_called_once_with(
            query=query,
            facts=mock_daily_facts,
            analysis=mock_analysis_result,
        )
        mock_delivery.deliver.assert_called_once()

    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_fact_collector")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_analyzer")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_generator")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_delivery")
    @pytest.mark.asyncio
    async def test_analyze_on_demand_without_delivery(
        self,
        mock_create_delivery,
        mock_create_generator,
        mock_create_analyzer,
        mock_create_collector,
        mock_conn,
        org_id,
        settings,
        mock_daily_facts,
        mock_analysis_result,
        mock_ceo_feedback,
    ):
        """オンデマンド分析の実行（配信なし - デフォルト）"""
        from lib.capabilities.feedback.ceo_feedback_engine import CEOFeedbackEngine

        # モックの設定
        mock_collector = AsyncMock()
        mock_collector.collect_daily = AsyncMock(return_value=mock_daily_facts)
        mock_create_collector.return_value = mock_collector

        mock_analyzer = AsyncMock()
        mock_analyzer.analyze = AsyncMock(return_value=mock_analysis_result)
        mock_create_analyzer.return_value = mock_analyzer

        mock_generator = AsyncMock()
        mock_generator.generate_on_demand_analysis = AsyncMock(return_value=mock_ceo_feedback)
        mock_create_generator.return_value = mock_generator

        mock_delivery = AsyncMock()
        mock_create_delivery.return_value = mock_delivery

        engine = CEOFeedbackEngine(
            conn=mock_conn,
            organization_id=org_id,
            settings=settings,
        )

        # deliver=Falseがデフォルト
        feedback, delivery_result = await engine.analyze_on_demand("調子どう？")

        assert feedback is mock_ceo_feedback
        assert delivery_result is None
        mock_delivery.deliver.assert_not_called()


# =============================================================================
# エラーハンドリングテスト
# =============================================================================


class TestErrorHandling:
    """エラーハンドリングのテスト"""

    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_fact_collector")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_analyzer")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_generator")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_delivery")
    @pytest.mark.asyncio
    async def test_daily_digest_error_wrapping(
        self,
        mock_create_delivery,
        mock_create_generator,
        mock_create_analyzer,
        mock_create_collector,
        mock_conn,
        org_id,
        settings,
    ):
        """デイリーダイジェスト生成時のエラーラッピング"""
        from lib.capabilities.feedback.ceo_feedback_engine import (
            CEOFeedbackEngine,
            CEOFeedbackEngineError,
        )

        # ファクト収集でエラーを発生させる
        mock_collector = AsyncMock()
        mock_collector.collect_daily = AsyncMock(side_effect=ValueError("DB接続エラー"))
        mock_create_collector.return_value = mock_collector

        engine = CEOFeedbackEngine(
            conn=mock_conn,
            organization_id=org_id,
            settings=settings,
        )

        with pytest.raises(CEOFeedbackEngineError) as exc_info:
            await engine.generate_daily_digest()

        assert "デイリーダイジェストの生成に失敗しました" in str(exc_info.value)
        assert exc_info.value.operation == "daily_digest"
        assert isinstance(exc_info.value.original_exception, ValueError)

    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_fact_collector")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_analyzer")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_generator")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_delivery")
    @pytest.mark.asyncio
    async def test_weekly_review_error_wrapping(
        self,
        mock_create_delivery,
        mock_create_generator,
        mock_create_analyzer,
        mock_create_collector,
        mock_conn,
        org_id,
        settings,
    ):
        """ウィークリーレビュー生成時のエラーラッピング"""
        from lib.capabilities.feedback.ceo_feedback_engine import (
            CEOFeedbackEngine,
            CEOFeedbackEngineError,
        )

        # 週次ファクト収集でエラーを発生させる
        mock_collector = AsyncMock()
        mock_collector.collect_weekly = AsyncMock(side_effect=RuntimeError("タイムアウト"))
        mock_create_collector.return_value = mock_collector

        engine = CEOFeedbackEngine(
            conn=mock_conn,
            organization_id=org_id,
            settings=settings,
        )

        with pytest.raises(CEOFeedbackEngineError) as exc_info:
            await engine.generate_weekly_review()

        assert "ウィークリーレビューの生成に失敗しました" in str(exc_info.value)
        assert exc_info.value.operation == "weekly_review"

    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_fact_collector")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_analyzer")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_generator")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_delivery")
    @pytest.mark.asyncio
    async def test_realtime_alert_error_wrapping(
        self,
        mock_create_delivery,
        mock_create_generator,
        mock_create_analyzer,
        mock_create_collector,
        mock_conn,
        org_id,
        settings,
        mock_anomaly,
    ):
        """リアルタイムアラート送信時のエラーラッピング"""
        from lib.capabilities.feedback.ceo_feedback_engine import (
            CEOFeedbackEngine,
            CEOFeedbackEngineError,
        )

        # フィードバック生成でエラーを発生させる
        mock_generator = AsyncMock()
        mock_generator.generate_realtime_alert = AsyncMock(
            side_effect=Exception("生成エラー")
        )
        mock_create_generator.return_value = mock_generator

        engine = CEOFeedbackEngine(
            conn=mock_conn,
            organization_id=org_id,
            settings=settings,
        )

        with pytest.raises(CEOFeedbackEngineError) as exc_info:
            await engine.send_realtime_alert(mock_anomaly)

        assert "リアルタイムアラートの送信に失敗しました" in str(exc_info.value)
        assert exc_info.value.operation == "realtime_alert"

    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_fact_collector")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_analyzer")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_generator")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_delivery")
    @pytest.mark.asyncio
    async def test_on_demand_error_wrapping(
        self,
        mock_create_delivery,
        mock_create_generator,
        mock_create_analyzer,
        mock_create_collector,
        mock_conn,
        org_id,
        settings,
    ):
        """オンデマンド分析時のエラーラッピング"""
        from lib.capabilities.feedback.ceo_feedback_engine import (
            CEOFeedbackEngine,
            CEOFeedbackEngineError,
        )

        # 分析でエラーを発生させる
        mock_collector = AsyncMock()
        mock_collector.collect_daily = AsyncMock(return_value=MagicMock())
        mock_create_collector.return_value = mock_collector

        mock_analyzer = AsyncMock()
        mock_analyzer.analyze = AsyncMock(side_effect=KeyError("分析エラー"))
        mock_create_analyzer.return_value = mock_analyzer

        engine = CEOFeedbackEngine(
            conn=mock_conn,
            organization_id=org_id,
            settings=settings,
        )

        with pytest.raises(CEOFeedbackEngineError) as exc_info:
            await engine.analyze_on_demand("調子どう？")

        assert "オンデマンド分析の実行に失敗しました" in str(exc_info.value)
        assert exc_info.value.operation == "on_demand"

    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_fact_collector")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_analyzer")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_generator")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_delivery")
    @pytest.mark.asyncio
    async def test_feature_disabled_error_not_wrapped(
        self,
        mock_create_delivery,
        mock_create_generator,
        mock_create_analyzer,
        mock_create_collector,
        mock_conn,
        org_id,
        settings_all_disabled,
    ):
        """FeatureDisabledErrorはラップされずにそのまま投げられる"""
        from lib.capabilities.feedback.ceo_feedback_engine import (
            CEOFeedbackEngine,
            FeatureDisabledError,
            CEOFeedbackEngineError,
        )

        engine = CEOFeedbackEngine(
            conn=mock_conn,
            organization_id=org_id,
            settings=settings_all_disabled,
        )

        # FeatureDisabledErrorがそのまま投げられることを確認
        with pytest.raises(FeatureDisabledError):
            await engine.generate_daily_digest()


# =============================================================================
# スケジュール配信テスト
# =============================================================================


class TestScheduledTasks:
    """スケジュールされたタスクのテスト"""

    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_fact_collector")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_analyzer")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_generator")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_delivery")
    @pytest.mark.asyncio
    async def test_run_scheduled_tasks_daily_digest(
        self,
        mock_create_delivery,
        mock_create_generator,
        mock_create_analyzer,
        mock_create_collector,
        mock_conn,
        org_id,
        settings,
        mock_daily_facts,
        mock_analysis_result,
        mock_ceo_feedback,
        mock_delivery_result,
    ):
        """デイリーダイジェスト配信時刻でのスケジュールタスク"""
        from lib.capabilities.feedback.ceo_feedback_engine import CEOFeedbackEngine

        # モックの設定
        mock_collector = AsyncMock()
        mock_collector.collect_daily = AsyncMock(return_value=mock_daily_facts)
        mock_create_collector.return_value = mock_collector

        mock_analyzer = AsyncMock()
        mock_analyzer.analyze = AsyncMock(return_value=mock_analysis_result)
        mock_create_analyzer.return_value = mock_analyzer

        mock_generator = AsyncMock()
        mock_generator.generate_daily_digest = AsyncMock(return_value=mock_ceo_feedback)
        mock_create_generator.return_value = mock_generator

        mock_delivery = MagicMock()
        mock_delivery.should_deliver_daily_digest = MagicMock(return_value=True)
        mock_delivery.should_deliver_weekly_review = MagicMock(return_value=False)
        mock_delivery.should_deliver_monthly_insight = MagicMock(return_value=False)
        mock_delivery.deliver = AsyncMock(return_value=mock_delivery_result)
        mock_create_delivery.return_value = mock_delivery

        engine = CEOFeedbackEngine(
            conn=mock_conn,
            organization_id=org_id,
            settings=settings,
        )

        # 実行
        results = await engine.run_scheduled_tasks()

        # 検証
        assert len(results) == 1
        assert results[0] is mock_delivery_result
        mock_delivery.should_deliver_daily_digest.assert_called_once()

    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_fact_collector")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_analyzer")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_generator")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_delivery")
    @pytest.mark.asyncio
    async def test_run_scheduled_tasks_no_delivery_needed(
        self,
        mock_create_delivery,
        mock_create_generator,
        mock_create_analyzer,
        mock_create_collector,
        mock_conn,
        org_id,
        settings,
    ):
        """配信不要な時刻でのスケジュールタスク"""
        from lib.capabilities.feedback.ceo_feedback_engine import CEOFeedbackEngine

        mock_delivery = MagicMock()
        mock_delivery.should_deliver_daily_digest = MagicMock(return_value=False)
        mock_delivery.should_deliver_weekly_review = MagicMock(return_value=False)
        mock_delivery.should_deliver_monthly_insight = MagicMock(return_value=False)
        mock_create_delivery.return_value = mock_delivery

        engine = CEOFeedbackEngine(
            conn=mock_conn,
            organization_id=org_id,
            settings=settings,
        )

        results = await engine.run_scheduled_tasks()

        assert len(results) == 0

    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_fact_collector")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_analyzer")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_generator")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_delivery")
    @pytest.mark.asyncio
    async def test_run_scheduled_tasks_with_error(
        self,
        mock_create_delivery,
        mock_create_generator,
        mock_create_analyzer,
        mock_create_collector,
        mock_conn,
        org_id,
        settings,
    ):
        """スケジュールタスクでエラーが発生した場合"""
        from lib.capabilities.feedback.ceo_feedback_engine import CEOFeedbackEngine

        # ファクト収集でエラーを発生させる
        mock_collector = AsyncMock()
        mock_collector.collect_daily = AsyncMock(side_effect=Exception("エラー"))
        mock_create_collector.return_value = mock_collector

        mock_delivery = MagicMock()
        mock_delivery.should_deliver_daily_digest = MagicMock(return_value=True)
        mock_delivery.should_deliver_weekly_review = MagicMock(return_value=False)
        mock_delivery.should_deliver_monthly_insight = MagicMock(return_value=False)
        mock_create_delivery.return_value = mock_delivery

        engine = CEOFeedbackEngine(
            conn=mock_conn,
            organization_id=org_id,
            settings=settings,
        )

        # エラーが発生しても例外は投げられず、空のリストが返される
        results = await engine.run_scheduled_tasks()

        assert len(results) == 0


# =============================================================================
# ユーティリティメソッドテスト
# =============================================================================


class TestUtilityMethods:
    """ユーティリティメソッドのテスト"""

    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_fact_collector")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_analyzer")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_generator")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_delivery")
    @pytest.mark.asyncio
    async def test_get_recent_feedbacks(
        self,
        mock_create_delivery,
        mock_create_generator,
        mock_create_analyzer,
        mock_create_collector,
        mock_conn,
        org_id,
        settings,
    ):
        """最近のフィードバック取得"""
        from lib.capabilities.feedback.ceo_feedback_engine import CEOFeedbackEngine
        from datetime import datetime

        # DBからのモック応答
        mock_rows = [
            (
                "id-1",
                "feedback-1",
                "daily_digest",
                "chatwork",
                "12345",
                datetime(2026, 2, 1, 8, 0),
                datetime(2026, 2, 1, 8, 0),
            ),
            (
                "id-2",
                "feedback-2",
                "weekly_review",
                "chatwork",
                "12345",
                datetime(2026, 1, 27, 9, 0),
                datetime(2026, 1, 27, 9, 0),
            ),
        ]
        mock_conn.execute.return_value.fetchall.return_value = mock_rows

        engine = CEOFeedbackEngine(
            conn=mock_conn,
            organization_id=org_id,
            settings=settings,
        )

        feedbacks = await engine.get_recent_feedbacks(limit=10)

        assert len(feedbacks) == 2
        assert feedbacks[0]["feedback_id"] == "feedback-1"
        assert feedbacks[0]["feedback_type"] == "daily_digest"
        assert feedbacks[1]["feedback_id"] == "feedback-2"
        assert feedbacks[1]["feedback_type"] == "weekly_review"

    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_fact_collector")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_analyzer")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_generator")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_delivery")
    @pytest.mark.asyncio
    async def test_get_recent_feedbacks_error(
        self,
        mock_create_delivery,
        mock_create_generator,
        mock_create_analyzer,
        mock_create_collector,
        mock_conn,
        org_id,
        settings,
    ):
        """最近のフィードバック取得 - エラー時は空リスト"""
        from lib.capabilities.feedback.ceo_feedback_engine import CEOFeedbackEngine

        mock_conn.execute.side_effect = Exception("DBエラー")

        engine = CEOFeedbackEngine(
            conn=mock_conn,
            organization_id=org_id,
            settings=settings,
        )

        feedbacks = await engine.get_recent_feedbacks()

        assert feedbacks == []

    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_fact_collector")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_analyzer")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_generator")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_delivery")
    @pytest.mark.asyncio
    async def test_check_health_healthy(
        self,
        mock_create_delivery,
        mock_create_generator,
        mock_create_analyzer,
        mock_create_collector,
        mock_conn,
        org_id,
        settings,
    ):
        """ヘルスチェック - 正常"""
        from lib.capabilities.feedback.ceo_feedback_engine import CEOFeedbackEngine

        engine = CEOFeedbackEngine(
            conn=mock_conn,
            organization_id=org_id,
            settings=settings,
        )

        health = await engine.check_health()

        assert health["status"] == "healthy"
        assert health["components"]["database"] == "ok"
        assert "settings" in health["components"]
        assert health["components"]["settings"]["daily_digest"] == "enabled"
        assert "checked_at" in health

    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_fact_collector")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_analyzer")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_generator")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_delivery")
    @pytest.mark.asyncio
    async def test_check_health_unhealthy(
        self,
        mock_create_delivery,
        mock_create_generator,
        mock_create_analyzer,
        mock_create_collector,
        mock_conn,
        org_id,
        settings,
    ):
        """ヘルスチェック - 異常（DB接続エラー）"""
        from lib.capabilities.feedback.ceo_feedback_engine import CEOFeedbackEngine

        mock_conn.execute.side_effect = Exception("Connection refused")

        engine = CEOFeedbackEngine(
            conn=mock_conn,
            organization_id=org_id,
            settings=settings,
        )

        health = await engine.check_health()

        assert health["status"] == "unhealthy"
        assert "error" in health["components"]["database"]

    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_fact_collector")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_analyzer")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_generator")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_delivery")
    @pytest.mark.asyncio
    async def test_check_health_with_disabled_features(
        self,
        mock_create_delivery,
        mock_create_generator,
        mock_create_analyzer,
        mock_create_collector,
        mock_conn,
        org_id,
        settings_all_disabled,
    ):
        """ヘルスチェック - 無効化された機能の確認"""
        from lib.capabilities.feedback.ceo_feedback_engine import CEOFeedbackEngine

        engine = CEOFeedbackEngine(
            conn=mock_conn,
            organization_id=org_id,
            settings=settings_all_disabled,
        )

        health = await engine.check_health()

        assert health["components"]["settings"]["daily_digest"] == "disabled"
        assert health["components"]["settings"]["weekly_review"] == "disabled"
        assert health["components"]["settings"]["realtime_alert"] == "disabled"
        assert health["components"]["settings"]["on_demand"] == "disabled"


# =============================================================================
# ファクトリー関数テスト
# =============================================================================


class TestFactoryFunctions:
    """ファクトリー関数のテスト"""

    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_fact_collector")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_analyzer")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_generator")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_delivery")
    def test_create_ceo_feedback_engine(
        self,
        mock_create_delivery,
        mock_create_generator,
        mock_create_analyzer,
        mock_create_collector,
        mock_conn,
        org_id,
        recipient_user_id,
        recipient_name,
        chatwork_room_id,
    ):
        """create_ceo_feedback_engine関数"""
        from lib.capabilities.feedback.ceo_feedback_engine import (
            create_ceo_feedback_engine,
            CEOFeedbackEngine,
        )

        engine = create_ceo_feedback_engine(
            conn=mock_conn,
            organization_id=org_id,
            recipient_user_id=recipient_user_id,
            recipient_name=recipient_name,
            chatwork_room_id=chatwork_room_id,
        )

        assert isinstance(engine, CEOFeedbackEngine)
        assert engine.organization_id == org_id
        assert engine.settings.recipient_user_id == recipient_user_id
        assert engine.settings.recipient_name == recipient_name
        assert engine.settings.chatwork_room_id == chatwork_room_id

    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_fact_collector")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_analyzer")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_generator")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_delivery")
    def test_create_ceo_feedback_engine_without_room_id(
        self,
        mock_create_delivery,
        mock_create_generator,
        mock_create_analyzer,
        mock_create_collector,
        mock_conn,
        org_id,
        recipient_user_id,
        recipient_name,
    ):
        """create_ceo_feedback_engine関数（ルームIDなし）"""
        from lib.capabilities.feedback.ceo_feedback_engine import (
            create_ceo_feedback_engine,
        )

        engine = create_ceo_feedback_engine(
            conn=mock_conn,
            organization_id=org_id,
            recipient_user_id=recipient_user_id,
            recipient_name=recipient_name,
        )

        assert engine.settings.chatwork_room_id is None

    @pytest.mark.asyncio
    async def test_get_ceo_feedback_engine_for_organization_found(
        self,
        mock_conn,
        org_id,
    ):
        """get_ceo_feedback_engine_for_organization - CEOが見つかる場合"""
        from lib.capabilities.feedback.ceo_feedback_engine import (
            get_ceo_feedback_engine_for_organization,
        )

        # CEOが見つかるモック応答
        mock_conn.execute.return_value.fetchone.side_effect = [
            # 1回目: CEO検索
            (str(uuid4()), "山田CEO", "cw_account_1"),
            # 2回目: DMルーム検索
            (99999,),
        ]

        with patch(
            "lib.capabilities.feedback.ceo_feedback_engine.create_ceo_feedback_engine"
        ) as mock_create:
            mock_engine = MagicMock()
            mock_create.return_value = mock_engine

            engine = await get_ceo_feedback_engine_for_organization(mock_conn, org_id)

            assert engine is mock_engine
            mock_create.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_ceo_feedback_engine_for_organization_not_found(
        self,
        mock_conn,
        org_id,
    ):
        """get_ceo_feedback_engine_for_organization - CEOが見つからない場合"""
        from lib.capabilities.feedback.ceo_feedback_engine import (
            get_ceo_feedback_engine_for_organization,
        )

        # CEOが見つからないモック応答
        mock_conn.execute.return_value.fetchone.return_value = None

        engine = await get_ceo_feedback_engine_for_organization(mock_conn, org_id)

        assert engine is None

    @pytest.mark.asyncio
    async def test_get_ceo_feedback_engine_for_organization_error(
        self,
        mock_conn,
        org_id,
    ):
        """get_ceo_feedback_engine_for_organization - エラー時はNone"""
        from lib.capabilities.feedback.ceo_feedback_engine import (
            get_ceo_feedback_engine_for_organization,
        )

        mock_conn.execute.side_effect = Exception("DBエラー")

        engine = await get_ceo_feedback_engine_for_organization(mock_conn, org_id)

        assert engine is None


# =============================================================================
# 統合シナリオテスト
# =============================================================================


class TestIntegrationScenarios:
    """統合シナリオテスト"""

    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_fact_collector")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_analyzer")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_generator")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_delivery")
    @pytest.mark.asyncio
    async def test_full_daily_workflow(
        self,
        mock_create_delivery,
        mock_create_generator,
        mock_create_analyzer,
        mock_create_collector,
        mock_conn,
        org_id,
        settings,
        mock_daily_facts,
        mock_analysis_result,
        mock_ceo_feedback,
        mock_delivery_result,
    ):
        """完全なデイリーワークフロー"""
        from lib.capabilities.feedback.ceo_feedback_engine import CEOFeedbackEngine

        # モックの設定
        mock_collector = AsyncMock()
        mock_collector.collect_daily = AsyncMock(return_value=mock_daily_facts)
        mock_create_collector.return_value = mock_collector

        mock_analyzer = AsyncMock()
        mock_analyzer.analyze = AsyncMock(return_value=mock_analysis_result)
        mock_create_analyzer.return_value = mock_analyzer

        mock_generator = AsyncMock()
        mock_generator.generate_daily_digest = AsyncMock(return_value=mock_ceo_feedback)
        mock_create_generator.return_value = mock_generator

        mock_delivery = MagicMock()
        mock_delivery.deliver = AsyncMock(return_value=mock_delivery_result)
        mock_delivery.should_deliver_daily_digest = MagicMock(return_value=True)
        mock_delivery.should_deliver_weekly_review = MagicMock(return_value=False)
        mock_delivery.should_deliver_monthly_insight = MagicMock(return_value=False)
        mock_create_delivery.return_value = mock_delivery

        engine = CEOFeedbackEngine(
            conn=mock_conn,
            organization_id=org_id,
            settings=settings,
        )

        # ヘルスチェック
        health = await engine.check_health()
        assert health["status"] == "healthy"

        # デイリーダイジェスト生成
        feedback, delivery_result = await engine.generate_daily_digest()
        assert feedback is not None
        assert delivery_result is not None
        assert delivery_result.success is True

        # 呼び出し順序の確認
        mock_collector.collect_daily.assert_called()
        mock_analyzer.analyze.assert_called()
        mock_generator.generate_daily_digest.assert_called()
        mock_delivery.deliver.assert_called()

    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_fact_collector")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_analyzer")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_generator")
    @patch("lib.capabilities.feedback.ceo_feedback_engine.create_feedback_delivery")
    @pytest.mark.asyncio
    async def test_multiple_feedback_types_in_sequence(
        self,
        mock_create_delivery,
        mock_create_generator,
        mock_create_analyzer,
        mock_create_collector,
        mock_conn,
        org_id,
        settings,
        mock_daily_facts,
        mock_analysis_result,
        mock_ceo_feedback,
        mock_delivery_result,
        mock_anomaly,
    ):
        """複数のフィードバックタイプを順番に実行"""
        from lib.capabilities.feedback.ceo_feedback_engine import CEOFeedbackEngine
        from lib.capabilities.feedback.constants import FeedbackType

        # モックの設定
        mock_collector = AsyncMock()
        mock_collector.collect_daily = AsyncMock(return_value=mock_daily_facts)
        mock_collector.collect_weekly = AsyncMock(return_value=[mock_daily_facts])
        mock_create_collector.return_value = mock_collector

        mock_analyzer = AsyncMock()
        mock_analyzer.analyze = AsyncMock(return_value=mock_analysis_result)
        mock_create_analyzer.return_value = mock_analyzer

        mock_generator = AsyncMock()
        mock_generator.generate_daily_digest = AsyncMock(return_value=mock_ceo_feedback)
        mock_generator.generate_weekly_review = AsyncMock(return_value=mock_ceo_feedback)
        mock_generator.generate_realtime_alert = AsyncMock(return_value=mock_ceo_feedback)
        mock_generator.generate_on_demand_analysis = AsyncMock(return_value=mock_ceo_feedback)
        mock_create_generator.return_value = mock_generator

        mock_delivery = MagicMock()
        mock_delivery.deliver = AsyncMock(return_value=mock_delivery_result)
        mock_create_delivery.return_value = mock_delivery

        engine = CEOFeedbackEngine(
            conn=mock_conn,
            organization_id=org_id,
            settings=settings,
        )

        # デイリーダイジェスト
        await engine.generate_daily_digest(deliver=False)

        # ウィークリーレビュー
        await engine.generate_weekly_review(deliver=False)

        # リアルタイムアラート
        await engine.send_realtime_alert(mock_anomaly)

        # オンデマンド分析
        await engine.analyze_on_demand("最近どう？", deliver=False)

        # 各メソッドが呼ばれたことを確認
        mock_generator.generate_daily_digest.assert_called_once()
        mock_generator.generate_weekly_review.assert_called_once()
        mock_generator.generate_realtime_alert.assert_called_once()
        mock_generator.generate_on_demand_analysis.assert_called_once()
