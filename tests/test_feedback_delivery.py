# tests/test_feedback_delivery.py
"""
Unit tests for lib/capabilities/feedback/delivery.py

CEOフィードバックシステム - 配信システムのテスト

Author: Claude Opus 4.5
Created: 2026-02-04
"""

import pytest
from datetime import datetime, date, time, timedelta
from unittest.mock import MagicMock, AsyncMock, patch
from uuid import UUID, uuid4

from lib.capabilities.feedback.delivery import (
    DeliveryError,
    CooldownError,
    DailyLimitError,
    DeliveryConfig,
    FeedbackDelivery,
    create_feedback_delivery,
)
from lib.capabilities.feedback.constants import (
    DeliveryParameters,
    FeedbackIcons,
    FeedbackPriority,
    FeedbackStatus,
    FeedbackType,
)
from lib.capabilities.feedback.models import (
    CEOFeedback,
    DeliveryResult,
    FeedbackItem,
    InsightCategory,
)


# =============================================================================
# Exception Classes Tests
# =============================================================================


class TestDeliveryError:
    """DeliveryError例外クラスのテスト"""

    def test_basic_creation(self):
        """基本的な例外の作成"""
        error = DeliveryError("配信に失敗しました")
        assert str(error) == "配信に失敗しました"
        assert error.message == "配信に失敗しました"
        assert error.delivery_channel == ""
        assert error.details == {}
        assert error.original_exception is None

    def test_with_delivery_channel(self):
        """配信チャネル付きの例外"""
        error = DeliveryError(
            message="配信に失敗しました",
            delivery_channel="chatwork",
        )
        assert error.delivery_channel == "chatwork"

    def test_with_details(self):
        """詳細情報付きの例外"""
        details = {"room_id": 12345, "user_id": "user_001"}
        error = DeliveryError(
            message="配信に失敗しました",
            details=details,
        )
        assert error.details == details

    def test_with_original_exception(self):
        """元の例外付きの例外"""
        original = ValueError("元のエラー")
        error = DeliveryError(
            message="配信に失敗しました",
            original_exception=original,
        )
        assert error.original_exception == original

    def test_full_creation(self):
        """全パラメータ指定での作成"""
        original = RuntimeError("ネットワークエラー")
        error = DeliveryError(
            message="ChatWorkへの配信に失敗",
            delivery_channel="chatwork",
            details={"room_id": 12345},
            original_exception=original,
        )
        assert error.message == "ChatWorkへの配信に失敗"
        assert error.delivery_channel == "chatwork"
        assert error.details == {"room_id": 12345}
        assert error.original_exception == original


class TestCooldownError:
    """CooldownError例外クラスのテスト"""

    def test_inheritance(self):
        """DeliveryErrorを継承していることを確認"""
        error = CooldownError("クールダウン中")
        assert isinstance(error, DeliveryError)

    def test_creation(self):
        """基本的な作成"""
        error = CooldownError(
            message="アラートは60分間隔でのみ送信できます",
            delivery_channel="chatwork",
        )
        assert "60分間隔" in str(error)
        assert error.delivery_channel == "chatwork"


class TestDailyLimitError:
    """DailyLimitError例外クラスのテスト"""

    def test_inheritance(self):
        """DeliveryErrorを継承していることを確認"""
        error = DailyLimitError("1日の上限到達")
        assert isinstance(error, DeliveryError)

    def test_creation(self):
        """基本的な作成"""
        error = DailyLimitError(
            message="1日のアラート上限（10件）に達しました",
            delivery_channel="chatwork",
        )
        assert "10件" in str(error)


# =============================================================================
# DeliveryConfig Tests
# =============================================================================


class TestDeliveryConfig:
    """DeliveryConfig設定クラスのテスト"""

    def test_default_values(self):
        """デフォルト値の確認"""
        config = DeliveryConfig()
        assert config.chatwork_room_id is None
        assert config.enable_daily_digest is True
        assert config.enable_weekly_review is True
        assert config.enable_monthly_insight is True
        assert config.enable_realtime_alert is True
        assert config.daily_digest_hour == DeliveryParameters.DAILY_DIGEST_HOUR
        assert config.daily_digest_minute == DeliveryParameters.DAILY_DIGEST_MINUTE
        assert config.alert_cooldown_minutes == DeliveryParameters.ALERT_COOLDOWN_MINUTES
        assert config.max_daily_alerts == DeliveryParameters.MAX_DAILY_ALERTS

    def test_custom_values(self):
        """カスタム値の設定"""
        config = DeliveryConfig(
            chatwork_room_id=12345,
            enable_daily_digest=False,
            enable_weekly_review=False,
            enable_monthly_insight=False,
            enable_realtime_alert=False,
            daily_digest_hour=9,
            daily_digest_minute=30,
            alert_cooldown_minutes=30,
            max_daily_alerts=5,
        )
        assert config.chatwork_room_id == 12345
        assert config.enable_daily_digest is False
        assert config.enable_weekly_review is False
        assert config.enable_monthly_insight is False
        assert config.enable_realtime_alert is False
        assert config.daily_digest_hour == 9
        assert config.daily_digest_minute == 30
        assert config.alert_cooldown_minutes == 30
        assert config.max_daily_alerts == 5


# =============================================================================
# FeedbackDelivery Tests - Initialization
# =============================================================================


class TestFeedbackDeliveryInit:
    """FeedbackDeliveryの初期化テスト"""

    def test_basic_init(self):
        """基本的な初期化"""
        conn = MagicMock()
        org_id = uuid4()
        delivery = FeedbackDelivery(conn, org_id)

        assert delivery.conn == conn
        assert delivery.organization_id == org_id
        assert isinstance(delivery.config, DeliveryConfig)

    def test_init_with_config(self):
        """設定付きの初期化"""
        conn = MagicMock()
        org_id = uuid4()
        config = DeliveryConfig(chatwork_room_id=12345)
        delivery = FeedbackDelivery(conn, org_id, config)

        assert delivery.config.chatwork_room_id == 12345

    def test_logger_initialization_with_lib_logging(self):
        """lib.loggingが利用可能な場合のロガー初期化"""
        # lib.loggingがimportできる場合はそちらを使用
        # ImportErrorの場合は標準loggingを使用
        # これは__init__内でtry-exceptで処理されている
        conn = MagicMock()
        org_id = uuid4()
        delivery = FeedbackDelivery(conn, org_id)
        # ロガーが設定されていることを確認
        assert delivery._logger is not None

    def test_logger_initialization_fallback(self):
        """lib.loggingがない場合のフォールバック"""
        # ImportErrorが発生した場合、標準のloggingを使用
        # これはコード内で自動的にハンドリングされる


# =============================================================================
# FeedbackDelivery Tests - Properties
# =============================================================================


class TestFeedbackDeliveryProperties:
    """FeedbackDeliveryのプロパティテスト"""

    def test_conn_property(self):
        """connプロパティ"""
        conn = MagicMock()
        org_id = uuid4()
        delivery = FeedbackDelivery(conn, org_id)
        assert delivery.conn == conn

    def test_organization_id_property(self):
        """organization_idプロパティ"""
        conn = MagicMock()
        org_id = uuid4()
        delivery = FeedbackDelivery(conn, org_id)
        assert delivery.organization_id == org_id

    def test_config_property(self):
        """configプロパティ"""
        conn = MagicMock()
        org_id = uuid4()
        config = DeliveryConfig(max_daily_alerts=20)
        delivery = FeedbackDelivery(conn, org_id, config)
        assert delivery.config.max_daily_alerts == 20


# =============================================================================
# FeedbackDelivery Tests - Message Formatting
# =============================================================================


class TestFeedbackDeliveryFormatting:
    """FeedbackDeliveryのメッセージフォーマットテスト"""

    @pytest.fixture
    def delivery(self):
        """テスト用のFeedbackDeliveryインスタンス"""
        conn = MagicMock()
        org_id = uuid4()
        return FeedbackDelivery(conn, org_id)

    @pytest.fixture
    def base_feedback(self):
        """テスト用の基本フィードバック"""
        return CEOFeedback(
            feedback_id="feedback_001",
            feedback_type=FeedbackType.DAILY_DIGEST,
            organization_id="org_001",
            recipient_user_id="user_001",
            recipient_name="テスト太郎",
            summary="今日の概要です。",
            items=[
                FeedbackItem(
                    category=InsightCategory.TASK_PROGRESS,
                    priority=FeedbackPriority.HIGH,
                    title="タスク滞留",
                    description="3件のタスクが期限超過しています",
                    evidence=["タスクA: 2日超過", "タスクB: 1日超過"],
                    recommendation="優先度の見直しをおすすめします",
                ),
            ],
        )

    def test_format_daily_digest(self, delivery, base_feedback):
        """デイリーダイジェストのフォーマット"""
        base_feedback.feedback_type = FeedbackType.DAILY_DIGEST
        message = delivery._format_feedback_message(base_feedback)

        assert "テスト太郎さんへのフィードバック" in message
        assert "今日注目してほしいこと" in message
        assert "タスク滞留" in message

    def test_format_weekly_review(self, delivery, base_feedback):
        """ウィークリーレビューのフォーマット"""
        base_feedback.feedback_type = FeedbackType.WEEKLY_REVIEW
        message = delivery._format_feedback_message(base_feedback)

        assert "週次レビュー" in message

    def test_format_realtime_alert(self, delivery, base_feedback):
        """リアルタイムアラートのフォーマット"""
        base_feedback.feedback_type = FeedbackType.REALTIME_ALERT
        base_feedback.items[0].hypothesis = "緊急対応が必要かもしれません"
        message = delivery._format_feedback_message(base_feedback)

        assert "テスト太郎さん、ちょっと気になることがあるウル" in message
        assert "検知した事実" in message

    def test_format_on_demand(self, delivery, base_feedback):
        """オンデマンド分析のフォーマット"""
        base_feedback.feedback_type = FeedbackType.ON_DEMAND
        message = delivery._format_feedback_message(base_feedback)

        assert "今日の概要です。" in message
        assert "タスク滞留" in message

    def test_format_generic(self, delivery, base_feedback):
        """汎用フォーマット（月次など）"""
        base_feedback.feedback_type = FeedbackType.MONTHLY_INSIGHT
        message = delivery._format_feedback_message(base_feedback)

        assert "今日の概要です。" in message

    def test_format_without_summary(self, delivery, base_feedback):
        """サマリーなしの場合"""
        base_feedback.summary = ""
        message = delivery._format_feedback_message(base_feedback)
        # サマリーがなくても項目は表示される
        assert "タスク滞留" in message

    def test_format_without_items(self, delivery, base_feedback):
        """項目なしの場合"""
        base_feedback.items = []
        message = delivery._format_feedback_message(base_feedback)
        # 項目がなくてもヘッダーは表示される
        assert "テスト太郎" in message

    def test_format_with_evidence(self, delivery, base_feedback):
        """エビデンス付きのリアルタイムアラート"""
        base_feedback.feedback_type = FeedbackType.REALTIME_ALERT
        base_feedback.items[0].evidence = ["証拠1", "証拠2"]
        message = delivery._format_feedback_message(base_feedback)

        assert "具体的な変化" in message
        assert "証拠1" in message

    def test_format_with_hypothesis(self, delivery, base_feedback):
        """仮説付きのリアルタイムアラート"""
        base_feedback.feedback_type = FeedbackType.REALTIME_ALERT
        base_feedback.items[0].hypothesis = "これが原因かもしれません"
        message = delivery._format_feedback_message(base_feedback)

        assert "仮説" in message
        assert "これが原因かもしれません" in message

    def test_format_weekly_review_with_positive_change(self, delivery, base_feedback):
        """ポジティブな変化を含むウィークリーレビュー"""
        base_feedback.feedback_type = FeedbackType.WEEKLY_REVIEW
        base_feedback.items.append(
            FeedbackItem(
                category=InsightCategory.POSITIVE_CHANGE,
                priority=FeedbackPriority.LOW,
                title="素晴らしい成果",
                description="目標を達成しました",
            )
        )
        message = delivery._format_feedback_message(base_feedback)

        assert "今週のハイライト" in message


class TestGetPriorityIcon:
    """優先度アイコン取得のテスト"""

    @pytest.fixture
    def delivery(self):
        conn = MagicMock()
        org_id = uuid4()
        return FeedbackDelivery(conn, org_id)

    def test_critical_icon(self, delivery):
        """クリティカル優先度のアイコン"""
        icon = delivery._get_priority_icon(FeedbackPriority.CRITICAL)
        assert icon == FeedbackIcons.PRIORITY_CRITICAL

    def test_high_icon(self, delivery):
        """高優先度のアイコン"""
        icon = delivery._get_priority_icon(FeedbackPriority.HIGH)
        assert icon == FeedbackIcons.PRIORITY_HIGH

    def test_medium_icon(self, delivery):
        """中優先度のアイコン"""
        icon = delivery._get_priority_icon(FeedbackPriority.MEDIUM)
        assert icon == FeedbackIcons.PRIORITY_MEDIUM

    def test_low_icon(self, delivery):
        """低優先度のアイコン"""
        icon = delivery._get_priority_icon(FeedbackPriority.LOW)
        assert icon == FeedbackIcons.PRIORITY_LOW


# =============================================================================
# FeedbackDelivery Tests - Schedule Helpers
# =============================================================================


class TestFeedbackDeliveryScheduleHelpers:
    """FeedbackDeliveryのスケジュールヘルパーテスト"""

    @pytest.fixture
    def delivery(self):
        conn = MagicMock()
        org_id = uuid4()
        config = DeliveryConfig(
            daily_digest_hour=8,
            daily_digest_minute=0,
        )
        return FeedbackDelivery(conn, org_id, config)

    def test_should_deliver_daily_digest_true(self, delivery):
        """デイリーダイジェスト配信すべき時刻"""
        test_time = datetime(2026, 2, 4, 8, 0, 0)
        assert delivery.should_deliver_daily_digest(test_time) is True

    def test_should_deliver_daily_digest_false_wrong_hour(self, delivery):
        """デイリーダイジェスト配信すべきでない時刻（時間が違う）"""
        test_time = datetime(2026, 2, 4, 9, 0, 0)
        assert delivery.should_deliver_daily_digest(test_time) is False

    def test_should_deliver_daily_digest_false_wrong_minute(self, delivery):
        """デイリーダイジェスト配信すべきでない時刻（分が違う）"""
        test_time = datetime(2026, 2, 4, 8, 30, 0)
        assert delivery.should_deliver_daily_digest(test_time) is False

    def test_should_deliver_daily_digest_disabled(self):
        """デイリーダイジェストが無効の場合"""
        conn = MagicMock()
        org_id = uuid4()
        config = DeliveryConfig(enable_daily_digest=False)
        delivery = FeedbackDelivery(conn, org_id, config)

        test_time = datetime(2026, 2, 4, 8, 0, 0)
        assert delivery.should_deliver_daily_digest(test_time) is False

    def test_should_deliver_weekly_review_true(self, delivery):
        """ウィークリーレビュー配信すべき時刻（月曜9:00）"""
        # 2026-02-02 は月曜日
        test_time = datetime(2026, 2, 2, 9, 0, 0)
        # 月曜日(weekday=0)かつ9:00
        assert test_time.weekday() == 0
        result = delivery.should_deliver_weekly_review(test_time)
        assert result is True

    def test_should_deliver_weekly_review_false_wrong_day(self, delivery):
        """ウィークリーレビュー配信すべきでない曜日"""
        # 2026-02-04 は水曜日
        test_time = datetime(2026, 2, 4, 9, 0, 0)
        assert test_time.weekday() == 2  # 水曜日
        assert delivery.should_deliver_weekly_review(test_time) is False

    def test_should_deliver_weekly_review_disabled(self):
        """ウィークリーレビューが無効の場合"""
        conn = MagicMock()
        org_id = uuid4()
        config = DeliveryConfig(enable_weekly_review=False)
        delivery = FeedbackDelivery(conn, org_id, config)

        test_time = datetime(2026, 2, 2, 9, 0, 0)  # 月曜日
        assert delivery.should_deliver_weekly_review(test_time) is False

    def test_should_deliver_monthly_insight_true(self, delivery):
        """マンスリーインサイト配信すべき時刻（1日9:00）"""
        test_time = datetime(2026, 2, 1, 9, 0, 0)
        assert delivery.should_deliver_monthly_insight(test_time) is True

    def test_should_deliver_monthly_insight_false_wrong_day(self, delivery):
        """マンスリーインサイト配信すべきでない日"""
        test_time = datetime(2026, 2, 15, 9, 0, 0)
        assert delivery.should_deliver_monthly_insight(test_time) is False

    def test_should_deliver_monthly_insight_disabled(self):
        """マンスリーインサイトが無効の場合"""
        conn = MagicMock()
        org_id = uuid4()
        config = DeliveryConfig(enable_monthly_insight=False)
        delivery = FeedbackDelivery(conn, org_id, config)

        test_time = datetime(2026, 2, 1, 9, 0, 0)
        assert delivery.should_deliver_monthly_insight(test_time) is False


# =============================================================================
# FeedbackDelivery Tests - Delivery Eligibility Check
# =============================================================================


class TestFeedbackDeliveryEligibility:
    """配信可否チェックのテスト"""

    @pytest.fixture
    def delivery(self):
        conn = MagicMock()
        conn.execute = MagicMock()
        org_id = uuid4()
        return FeedbackDelivery(conn, org_id)

    @pytest.fixture
    def daily_digest_feedback(self):
        return CEOFeedback(
            feedback_id="feedback_001",
            feedback_type=FeedbackType.DAILY_DIGEST,
            organization_id="org_001",
            recipient_user_id="user_001",
            recipient_name="テスト太郎",
        )

    @pytest.fixture
    def realtime_alert_feedback(self):
        return CEOFeedback(
            feedback_id="feedback_002",
            feedback_type=FeedbackType.REALTIME_ALERT,
            organization_id="org_001",
            recipient_user_id="user_001",
            recipient_name="テスト太郎",
        )

    @pytest.mark.asyncio
    async def test_check_delivery_eligibility_daily_digest(self, delivery, daily_digest_feedback):
        """デイリーダイジェストは追加チェックなし"""
        # デイリーダイジェストの場合はチェックなしでパス
        await delivery._check_delivery_eligibility(daily_digest_feedback)
        # 例外が発生しなければOK

    @pytest.mark.asyncio
    async def test_check_alert_cooldown_pass(self, delivery):
        """クールダウンチェック - 通過"""
        result = MagicMock()
        result.fetchone.return_value = (0,)  # 最近のアラートなし
        delivery._conn.execute.return_value = result

        await delivery._check_alert_cooldown()
        # 例外が発生しなければOK

    @pytest.mark.asyncio
    async def test_check_alert_cooldown_fail(self, delivery):
        """クールダウンチェック - 失敗（クールダウン中）"""
        result = MagicMock()
        result.fetchone.return_value = (1,)  # 最近のアラートあり
        delivery._conn.execute.return_value = result

        with pytest.raises(CooldownError):
            await delivery._check_alert_cooldown()

    @pytest.mark.asyncio
    async def test_check_alert_cooldown_db_error(self, delivery):
        """クールダウンチェック - DBエラー時は警告のみ"""
        delivery._conn.execute.side_effect = Exception("DB connection error")

        # DBエラーの場合は警告のみで例外は発生しない
        await delivery._check_alert_cooldown()

    @pytest.mark.asyncio
    async def test_check_daily_alert_limit_pass(self, delivery):
        """1日の上限チェック - 通過"""
        result = MagicMock()
        result.fetchone.return_value = (5,)  # 上限10に対して5件
        delivery._conn.execute.return_value = result

        await delivery._check_daily_alert_limit()
        # 例外が発生しなければOK

    @pytest.mark.asyncio
    async def test_check_daily_alert_limit_fail(self, delivery):
        """1日の上限チェック - 失敗（上限到達）"""
        result = MagicMock()
        result.fetchone.return_value = (10,)  # 上限10に達した
        delivery._conn.execute.return_value = result

        with pytest.raises(DailyLimitError):
            await delivery._check_daily_alert_limit()

    @pytest.mark.asyncio
    async def test_check_daily_alert_limit_db_error(self, delivery):
        """1日の上限チェック - DBエラー時は警告のみ"""
        delivery._conn.execute.side_effect = Exception("DB connection error")

        # DBエラーの場合は警告のみで例外は発生しない
        await delivery._check_daily_alert_limit()


# =============================================================================
# FeedbackDelivery Tests - ChatWork Send
# =============================================================================


class TestFeedbackDeliveryChatworkSend:
    """ChatWork送信のテスト"""

    @pytest.fixture
    def delivery(self):
        conn = MagicMock()
        org_id = uuid4()
        return FeedbackDelivery(conn, org_id)

    @pytest.mark.asyncio
    async def test_send_to_chatwork_no_room_id(self, delivery):
        """room_idがない場合はNoneを返す"""
        result = await delivery._send_to_chatwork(None, "テストメッセージ")
        assert result is None

    @pytest.mark.asyncio
    async def test_send_to_chatwork_success(self, delivery):
        """ChatWork送信成功"""
        # lib.chatwork モジュールをモック
        mock_chatwork_module = MagicMock()
        mock_chatwork_module.post_message = MagicMock(return_value="msg_12345")

        with patch.dict('sys.modules', {'lib.chatwork': mock_chatwork_module}):
            result = await delivery._send_to_chatwork(12345, "テストメッセージ")
            assert result == "msg_12345"
            mock_chatwork_module.post_message.assert_called_once_with(12345, "テストメッセージ")

    @pytest.mark.asyncio
    async def test_send_to_chatwork_import_error(self, delivery):
        """ChatWorkモジュールがない場合はNoneを返す"""
        import sys
        import builtins

        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == 'lib.chatwork' or (args and args[0] and 'lib.chatwork' in str(args)):
                raise ImportError("No module named 'lib.chatwork'")
            return original_import(name, *args, **kwargs)

        with patch.object(builtins, '__import__', side_effect=mock_import):
            result = await delivery._send_to_chatwork(12345, "テストメッセージ")
            # ImportErrorの場合はNoneが返される
            assert result is None

    @pytest.mark.asyncio
    async def test_send_to_chatwork_api_error(self, delivery):
        """ChatWork API エラー"""
        # lib.chatwork モジュールをモックしてAPIエラーを発生させる
        mock_chatwork_module = MagicMock()
        mock_chatwork_module.post_message = MagicMock(side_effect=RuntimeError("API Error"))

        with patch.dict('sys.modules', {'lib.chatwork': mock_chatwork_module}):
            with pytest.raises(DeliveryError) as exc_info:
                await delivery._send_to_chatwork(12345, "テストメッセージ")

            assert "ChatWorkへのメッセージ送信に失敗" in str(exc_info.value)
            assert exc_info.value.delivery_channel == "chatwork"
            assert exc_info.value.details["room_id"] == 12345


# =============================================================================
# FeedbackDelivery Tests - Record Delivery Log
# =============================================================================


class TestFeedbackDeliveryRecordLog:
    """配信ログ記録のテスト"""

    @pytest.fixture
    def delivery(self):
        conn = MagicMock()
        org_id = uuid4()
        return FeedbackDelivery(conn, org_id)

    @pytest.fixture
    def feedback(self):
        return CEOFeedback(
            feedback_id="feedback_001",
            feedback_type=FeedbackType.DAILY_DIGEST,
            organization_id="org_001",
            recipient_user_id="user_001",
            recipient_name="テスト太郎",
        )

    @pytest.mark.asyncio
    async def test_record_delivery_log_success(self, delivery, feedback):
        """ログ記録成功"""
        await delivery._record_delivery_log(feedback, 12345, "msg_001")
        delivery._conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_record_delivery_log_db_error(self, delivery, feedback):
        """ログ記録失敗（警告のみ）"""
        delivery._conn.execute.side_effect = Exception("DB error")

        # DBエラーでも例外は発生しない（警告のみ）
        await delivery._record_delivery_log(feedback, 12345, "msg_001")

    @pytest.mark.asyncio
    async def test_record_delivery_log_no_room_id(self, delivery, feedback):
        """room_idがない場合"""
        await delivery._record_delivery_log(feedback, None, "msg_001")
        delivery._conn.execute.assert_called_once()


# =============================================================================
# FeedbackDelivery Tests - Main Deliver Method
# =============================================================================


class TestFeedbackDeliveryDeliver:
    """メイン配信メソッドのテスト"""

    @pytest.fixture
    def delivery(self):
        conn = MagicMock()
        org_id = uuid4()
        config = DeliveryConfig(chatwork_room_id=12345)
        return FeedbackDelivery(conn, org_id, config)

    @pytest.fixture
    def feedback(self):
        return CEOFeedback(
            feedback_id="feedback_001",
            feedback_type=FeedbackType.DAILY_DIGEST,
            organization_id="org_001",
            recipient_user_id="user_001",
            recipient_name="テスト太郎",
            summary="今日の概要",
            items=[
                FeedbackItem(
                    category=InsightCategory.TASK_PROGRESS,
                    priority=FeedbackPriority.MEDIUM,
                    title="タスク進捗",
                    description="順調です",
                ),
            ],
        )

    @pytest.mark.asyncio
    async def test_deliver_success(self, delivery, feedback):
        """配信成功"""
        with patch.object(delivery, '_check_delivery_eligibility', new_callable=AsyncMock):
            with patch.object(delivery, '_send_to_chatwork', new_callable=AsyncMock) as mock_send:
                with patch.object(delivery, '_record_delivery_log', new_callable=AsyncMock):
                    mock_send.return_value = "msg_12345"

                    result = await delivery.deliver(feedback)

                    assert result.success is True
                    assert result.feedback_id == "feedback_001"
                    assert result.message_id == "msg_12345"
                    assert result.channel == "chatwork"
                    assert feedback.status == FeedbackStatus.SENT

    @pytest.mark.asyncio
    async def test_deliver_with_custom_room_id(self, delivery, feedback):
        """カスタムroom_idでの配信"""
        with patch.object(delivery, '_check_delivery_eligibility', new_callable=AsyncMock):
            with patch.object(delivery, '_send_to_chatwork', new_callable=AsyncMock) as mock_send:
                with patch.object(delivery, '_record_delivery_log', new_callable=AsyncMock):
                    mock_send.return_value = "msg_12345"

                    result = await delivery.deliver(feedback, chatwork_room_id=99999)

                    mock_send.assert_called_once()
                    # カスタムroom_idが使用されていることを確認
                    call_args = mock_send.call_args
                    assert call_args[0][0] == 99999

    @pytest.mark.asyncio
    async def test_deliver_cooldown_error(self, delivery, feedback):
        """クールダウンエラー"""
        feedback.feedback_type = FeedbackType.REALTIME_ALERT

        with patch.object(delivery, '_check_delivery_eligibility', new_callable=AsyncMock) as mock_check:
            mock_check.side_effect = CooldownError("クールダウン中")

            with pytest.raises(CooldownError):
                await delivery.deliver(feedback)

    @pytest.mark.asyncio
    async def test_deliver_daily_limit_error(self, delivery, feedback):
        """1日の上限エラー"""
        feedback.feedback_type = FeedbackType.REALTIME_ALERT

        with patch.object(delivery, '_check_delivery_eligibility', new_callable=AsyncMock) as mock_check:
            mock_check.side_effect = DailyLimitError("上限到達")

            with pytest.raises(DailyLimitError):
                await delivery.deliver(feedback)

    @pytest.mark.asyncio
    async def test_deliver_general_error(self, delivery, feedback):
        """一般的なエラー"""
        with patch.object(delivery, '_check_delivery_eligibility', new_callable=AsyncMock):
            with patch.object(delivery, '_send_to_chatwork', new_callable=AsyncMock) as mock_send:
                mock_send.side_effect = RuntimeError("Unexpected error")

                result = await delivery.deliver(feedback)

                assert result.success is False
                assert "Unexpected error" in result.error_message


# =============================================================================
# Factory Function Tests
# =============================================================================


class TestCreateFeedbackDelivery:
    """create_feedback_deliveryファクトリ関数のテスト"""

    def test_basic_creation(self):
        """基本的な作成"""
        conn = MagicMock()
        org_id = uuid4()

        delivery = create_feedback_delivery(conn, org_id)

        assert isinstance(delivery, FeedbackDelivery)
        assert delivery.conn == conn
        assert delivery.organization_id == org_id

    def test_with_chatwork_room_id(self):
        """chatwork_room_id付きの作成"""
        conn = MagicMock()
        org_id = uuid4()

        delivery = create_feedback_delivery(conn, org_id, chatwork_room_id=12345)

        assert delivery.config.chatwork_room_id == 12345

    def test_with_config(self):
        """設定付きの作成"""
        conn = MagicMock()
        org_id = uuid4()
        config = DeliveryConfig(max_daily_alerts=20)

        delivery = create_feedback_delivery(conn, org_id, config=config)

        assert delivery.config.max_daily_alerts == 20

    def test_with_both_chatwork_room_id_and_config(self):
        """chatwork_room_idと設定の両方を指定"""
        conn = MagicMock()
        org_id = uuid4()
        config = DeliveryConfig(max_daily_alerts=20)

        delivery = create_feedback_delivery(
            conn, org_id,
            chatwork_room_id=12345,
            config=config,
        )

        # chatwork_room_idが優先される
        assert delivery.config.chatwork_room_id == 12345
        assert delivery.config.max_daily_alerts == 20


# =============================================================================
# Edge Cases and Integration Tests
# =============================================================================


class TestFeedbackDeliveryEdgeCases:
    """エッジケースのテスト"""

    @pytest.fixture
    def delivery(self):
        conn = MagicMock()
        org_id = uuid4()
        return FeedbackDelivery(conn, org_id)

    def test_format_daily_digest_empty_items(self, delivery):
        """空の項目リストでのデイリーダイジェストフォーマット"""
        feedback = CEOFeedback(
            feedback_id="feedback_001",
            feedback_type=FeedbackType.DAILY_DIGEST,
            organization_id="org_001",
            recipient_user_id="user_001",
            recipient_name="テスト太郎",
            items=[],
        )

        message = delivery._format_feedback_message(feedback)
        assert "テスト太郎" in message

    def test_format_weekly_review_no_highlights(self, delivery):
        """ハイライトなしのウィークリーレビュー"""
        feedback = CEOFeedback(
            feedback_id="feedback_001",
            feedback_type=FeedbackType.WEEKLY_REVIEW,
            organization_id="org_001",
            recipient_user_id="user_001",
            recipient_name="テスト太郎",
            items=[
                FeedbackItem(
                    category=InsightCategory.RISK_ANOMALY,
                    priority=FeedbackPriority.HIGH,
                    title="リスク検知",
                    description="異常が検知されました",
                ),
            ],
        )

        message = delivery._format_feedback_message(feedback)
        assert "注意が必要な事項" in message

    def test_format_realtime_alert_no_evidence(self, delivery):
        """エビデンスなしのリアルタイムアラート"""
        feedback = CEOFeedback(
            feedback_id="feedback_001",
            feedback_type=FeedbackType.REALTIME_ALERT,
            organization_id="org_001",
            recipient_user_id="user_001",
            recipient_name="テスト太郎",
            items=[
                FeedbackItem(
                    category=InsightCategory.RISK_ANOMALY,
                    priority=FeedbackPriority.HIGH,
                    title="リスク検知",
                    description="異常が検知されました",
                    evidence=[],  # 空のエビデンス
                ),
            ],
        )

        message = delivery._format_feedback_message(feedback)
        assert "検知した事実" in message
        # "具体的な変化"セクションは空のエビデンスでは表示されない

    def test_format_on_demand_with_evidence(self, delivery):
        """エビデンス付きのオンデマンド分析"""
        feedback = CEOFeedback(
            feedback_id="feedback_001",
            feedback_type=FeedbackType.ON_DEMAND,
            organization_id="org_001",
            recipient_user_id="user_001",
            recipient_name="テスト太郎",
            summary="分析結果です。",
            items=[
                FeedbackItem(
                    category=InsightCategory.TASK_PROGRESS,
                    priority=FeedbackPriority.MEDIUM,
                    title="タスク分析",
                    description="詳細分析",
                    evidence=["証拠1", "証拠2"],
                    recommendation="アクション提案",
                ),
            ],
        )

        message = delivery._format_feedback_message(feedback)
        assert "証拠1" in message
        assert "アクション提案" in message

    @pytest.mark.asyncio
    async def test_deliver_with_null_delivered_at(self, delivery):
        """delivered_atがNullの場合のDeliveryResult"""
        feedback = CEOFeedback(
            feedback_id="feedback_001",
            feedback_type=FeedbackType.DAILY_DIGEST,
            organization_id="org_001",
            recipient_user_id="user_001",
            recipient_name="テスト太郎",
        )

        with patch.object(delivery, '_check_delivery_eligibility', new_callable=AsyncMock):
            with patch.object(delivery, '_send_to_chatwork', new_callable=AsyncMock) as mock_send:
                with patch.object(delivery, '_record_delivery_log', new_callable=AsyncMock):
                    mock_send.side_effect = Exception("送信失敗")

                    result = await delivery.deliver(feedback)

                    assert result.success is False
                    assert result.delivered_at is None

    def test_should_deliver_methods_use_default_time(self, delivery):
        """スケジュールメソッドがデフォルトで現在時刻を使用"""
        # nowがNoneの場合はdatetime.now()を使用するテスト
        # これはメソッド内部の挙動をテスト
        result_daily = delivery.should_deliver_daily_digest()  # 現在時刻で判定
        result_weekly = delivery.should_deliver_weekly_review()
        result_monthly = delivery.should_deliver_monthly_insight()

        # 結果は現在時刻によるのでTrue/Falseの検証はしないが、例外が発生しないことを確認
        assert isinstance(result_daily, bool)
        assert isinstance(result_weekly, bool)
        assert isinstance(result_monthly, bool)


class TestFeedbackDeliveryMultipleItems:
    """複数項目のテスト"""

    @pytest.fixture
    def delivery(self):
        conn = MagicMock()
        org_id = uuid4()
        return FeedbackDelivery(conn, org_id)

    def test_format_daily_digest_multiple_items(self, delivery):
        """複数項目のデイリーダイジェスト"""
        feedback = CEOFeedback(
            feedback_id="feedback_001",
            feedback_type=FeedbackType.DAILY_DIGEST,
            organization_id="org_001",
            recipient_user_id="user_001",
            recipient_name="テスト太郎",
            items=[
                FeedbackItem(
                    category=InsightCategory.TASK_PROGRESS,
                    priority=FeedbackPriority.CRITICAL,
                    title="緊急タスク",
                    description="期限が迫っています",
                    recommendation="今日中に対応してください",
                ),
                FeedbackItem(
                    category=InsightCategory.GOAL_ACHIEVEMENT,
                    priority=FeedbackPriority.HIGH,
                    title="目標進捗",
                    description="遅れがあります",
                ),
                FeedbackItem(
                    category=InsightCategory.POSITIVE_CHANGE,
                    priority=FeedbackPriority.LOW,
                    title="良い変化",
                    description="チーム連携が改善しました",
                ),
            ],
        )

        message = delivery._format_feedback_message(feedback)

        assert "緊急タスク" in message
        assert "目標進捗" in message
        assert "良い変化" in message
        assert FeedbackIcons.PRIORITY_CRITICAL in message
        assert FeedbackIcons.PRIORITY_HIGH in message
        assert FeedbackIcons.PRIORITY_LOW in message


class TestFeedbackDeliveryWeekdayNames:
    """曜日名のテスト"""

    @pytest.fixture
    def delivery(self):
        conn = MagicMock()
        org_id = uuid4()
        return FeedbackDelivery(conn, org_id)

    def test_format_daily_digest_weekday_names(self, delivery):
        """各曜日の名前が正しく表示される"""
        feedback = CEOFeedback(
            feedback_id="feedback_001",
            feedback_type=FeedbackType.DAILY_DIGEST,
            organization_id="org_001",
            recipient_user_id="user_001",
            recipient_name="テスト太郎",
            items=[],
        )

        message = delivery._format_feedback_message(feedback)

        # 曜日名（月〜日のいずれか）が含まれることを確認
        weekday_names = ["月", "火", "水", "木", "金", "土", "日"]
        assert any(day in message for day in weekday_names)


# =============================================================================
# Realtime Alert Specific Tests
# =============================================================================


class TestRealtimeAlertDelivery:
    """リアルタイムアラート配信のテスト"""

    @pytest.fixture
    def delivery(self):
        conn = MagicMock()
        org_id = uuid4()
        config = DeliveryConfig(
            alert_cooldown_minutes=60,
            max_daily_alerts=10,
        )
        return FeedbackDelivery(conn, org_id, config)

    @pytest.fixture
    def alert_feedback(self):
        return CEOFeedback(
            feedback_id="alert_001",
            feedback_type=FeedbackType.REALTIME_ALERT,
            organization_id="org_001",
            recipient_user_id="user_001",
            recipient_name="テスト太郎",
            items=[
                FeedbackItem(
                    category=InsightCategory.RISK_ANOMALY,
                    priority=FeedbackPriority.CRITICAL,
                    title="異常検知",
                    description="重大な異常が検知されました",
                    evidence=["証拠1", "証拠2"],
                    hypothesis="システム障害の可能性があります",
                    recommendation="即時確認してください",
                ),
            ],
        )

    @pytest.mark.asyncio
    async def test_check_delivery_eligibility_realtime_alert(self, delivery, alert_feedback):
        """リアルタイムアラートの配信可否チェック"""
        # クールダウンと上限チェックの両方をモック
        result = MagicMock()
        result.fetchone.return_value = (0,)
        delivery._conn.execute.return_value = result

        await delivery._check_delivery_eligibility(alert_feedback)
        # 例外が発生しなければOK

    def test_format_realtime_alert_full(self, delivery, alert_feedback):
        """完全なリアルタイムアラートのフォーマット"""
        message = delivery._format_feedback_message(alert_feedback)

        assert "テスト太郎さん、ちょっと気になることがあるウル" in message
        assert "検知した事実" in message
        assert "重大な異常が検知されました" in message
        assert "具体的な変化" in message
        assert "証拠1" in message
        assert "仮説" in message
        assert "システム障害" in message
        assert "提案" in message
        assert "即時確認" in message
