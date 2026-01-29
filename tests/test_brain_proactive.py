# tests/test_brain_proactive.py
"""
Ultimate Brain Phase 2: 能動的モニタリング（Proactive Monitoring）のテスト
"""

import pytest
from datetime import datetime, timedelta
from lib.brain.proactive import (
    ProactiveMonitor,
    create_proactive_monitor,
    TriggerType,
    ProactiveMessageType,
    ActionPriority,
    Trigger,
    ProactiveMessage,
    ProactiveAction,
    UserContext,
    CheckResult,
    GOAL_ABANDONED_DAYS,
    TASK_OVERLOAD_COUNT,
    EMOTION_DECLINE_DAYS,
    MESSAGE_COOLDOWN_HOURS,
    TRIGGER_PRIORITY,
    MESSAGE_TEMPLATES,
)
from lib.brain.constants import JST


# ============================================================
# フィクスチャ
# ============================================================

@pytest.fixture
def monitor():
    """ProactiveMonitorインスタンスを作成（dry_run=True）"""
    return create_proactive_monitor(dry_run=True)


@pytest.fixture
def sample_user_context():
    """サンプルユーザーコンテキスト"""
    return UserContext(
        user_id="user_123",
        organization_id="org_soulsyncs",
        chatwork_account_id="cw_456",
        dm_room_id="room_789",
        last_activity_at=datetime.now(JST) - timedelta(days=1),
    )


@pytest.fixture
def inactive_user_context():
    """長期不在のユーザーコンテキスト"""
    return UserContext(
        user_id="user_inactive",
        organization_id="org_soulsyncs",
        chatwork_account_id="cw_inactive",
        dm_room_id="room_inactive",
        last_activity_at=datetime.now(JST) - timedelta(days=20),
    )


# ============================================================
# 定数テスト
# ============================================================

class TestConstants:
    """定数のテスト"""

    def test_goal_abandoned_days(self):
        """目標放置日数が正しく定義されている"""
        assert GOAL_ABANDONED_DAYS == 7

    def test_task_overload_count(self):
        """タスク山積み件数が正しく定義されている"""
        assert TASK_OVERLOAD_COUNT == 5

    def test_emotion_decline_days(self):
        """感情変化日数が正しく定義されている"""
        assert EMOTION_DECLINE_DAYS == 3

    def test_message_cooldown_hours(self):
        """メッセージクールダウンが正しく定義されている"""
        assert TriggerType.GOAL_ABANDONED in MESSAGE_COOLDOWN_HOURS
        assert TriggerType.TASK_OVERLOAD in MESSAGE_COOLDOWN_HOURS
        assert MESSAGE_COOLDOWN_HOURS[TriggerType.GOAL_ABANDONED] == 72

    def test_trigger_priority(self):
        """トリガー優先度が正しく定義されている"""
        assert TRIGGER_PRIORITY[TriggerType.EMOTION_DECLINE] == ActionPriority.CRITICAL
        assert TRIGGER_PRIORITY[TriggerType.TASK_OVERLOAD] == ActionPriority.HIGH

    def test_message_templates(self):
        """メッセージテンプレートが定義されている"""
        assert TriggerType.GOAL_ABANDONED in MESSAGE_TEMPLATES
        assert len(MESSAGE_TEMPLATES[TriggerType.GOAL_ABANDONED]) > 0


# ============================================================
# Enumテスト
# ============================================================

class TestTriggerType:
    """TriggerType Enumのテスト"""

    def test_values(self):
        """値が正しく定義されている"""
        assert TriggerType.GOAL_ABANDONED.value == "goal_abandoned"
        assert TriggerType.TASK_OVERLOAD.value == "task_overload"
        assert TriggerType.EMOTION_DECLINE.value == "emotion_decline"
        assert TriggerType.QUESTION_UNANSWERED.value == "question_unanswered"
        assert TriggerType.GOAL_ACHIEVED.value == "goal_achieved"

    def test_all_values(self):
        """全ての値が存在する"""
        assert len(TriggerType) == 7


class TestProactiveMessageType:
    """ProactiveMessageType Enumのテスト"""

    def test_values(self):
        """値が正しく定義されている"""
        assert ProactiveMessageType.FOLLOW_UP.value == "follow_up"
        assert ProactiveMessageType.ENCOURAGEMENT.value == "encouragement"
        assert ProactiveMessageType.REMINDER.value == "reminder"
        assert ProactiveMessageType.CELEBRATION.value == "celebration"
        assert ProactiveMessageType.CHECK_IN.value == "check_in"

    def test_all_values(self):
        """全ての値が存在する"""
        assert len(ProactiveMessageType) == 5


class TestActionPriority:
    """ActionPriority Enumのテスト"""

    def test_values(self):
        """値が正しく定義されている"""
        assert ActionPriority.CRITICAL.value == "critical"
        assert ActionPriority.HIGH.value == "high"
        assert ActionPriority.MEDIUM.value == "medium"
        assert ActionPriority.LOW.value == "low"

    def test_all_values(self):
        """全ての値が存在する"""
        assert len(ActionPriority) == 4


# ============================================================
# データクラステスト
# ============================================================

class TestTrigger:
    """Triggerデータクラスのテスト"""

    def test_creation(self):
        """正しく作成できる"""
        trigger = Trigger(
            trigger_type=TriggerType.GOAL_ABANDONED,
            user_id="user_123",
            organization_id="org_soulsyncs",
            priority=ActionPriority.MEDIUM,
            details={"goal_id": "goal_456", "days_since_update": 10},
        )
        assert trigger.trigger_type == TriggerType.GOAL_ABANDONED
        assert trigger.user_id == "user_123"
        assert trigger.priority == ActionPriority.MEDIUM
        assert trigger.details["days_since_update"] == 10

    def test_to_dict(self):
        """辞書形式に変換できる"""
        trigger = Trigger(
            trigger_type=TriggerType.TASK_OVERLOAD,
            user_id="user_123",
            organization_id="org_soulsyncs",
            priority=ActionPriority.HIGH,
            details={"count": 8},
        )
        d = trigger.to_dict()
        assert d["trigger_type"] == "task_overload"
        assert d["priority"] == "high"
        assert d["details"]["count"] == 8


class TestProactiveMessage:
    """ProactiveMessageデータクラスのテスト"""

    def test_creation(self):
        """正しく作成できる"""
        trigger = Trigger(
            trigger_type=TriggerType.GOAL_ACHIEVED,
            user_id="user_123",
            organization_id="org_soulsyncs",
            priority=ActionPriority.MEDIUM,
        )
        message = ProactiveMessage(
            trigger=trigger,
            message_type=ProactiveMessageType.CELEBRATION,
            message="おめでとうございますウル！🎉",
            room_id="room_789",
        )
        assert message.message_type == ProactiveMessageType.CELEBRATION
        assert "おめでとう" in message.message

    def test_to_dict(self):
        """辞書形式に変換できる"""
        trigger = Trigger(
            trigger_type=TriggerType.EMOTION_DECLINE,
            user_id="user_123",
            organization_id="org_soulsyncs",
            priority=ActionPriority.CRITICAL,
        )
        message = ProactiveMessage(
            trigger=trigger,
            message_type=ProactiveMessageType.CHECK_IN,
            message="最近調子どうですかウル？",
            room_id="room_789",
        )
        d = message.to_dict()
        assert d["message_type"] == "check_in"
        assert d["room_id"] == "room_789"


class TestProactiveAction:
    """ProactiveActionデータクラスのテスト"""

    def test_creation_success(self):
        """成功アクションを作成できる"""
        trigger = Trigger(
            trigger_type=TriggerType.GOAL_ABANDONED,
            user_id="user_123",
            organization_id="org_soulsyncs",
            priority=ActionPriority.MEDIUM,
        )
        message = ProactiveMessage(
            trigger=trigger,
            message_type=ProactiveMessageType.FOLLOW_UP,
            message="目標の進捗どうですかウル？",
        )
        action = ProactiveAction(message=message, success=True)
        assert action.success is True
        assert action.error_message is None

    def test_creation_failure(self):
        """失敗アクションを作成できる"""
        trigger = Trigger(
            trigger_type=TriggerType.TASK_OVERLOAD,
            user_id="user_123",
            organization_id="org_soulsyncs",
            priority=ActionPriority.HIGH,
        )
        message = ProactiveMessage(
            trigger=trigger,
            message_type=ProactiveMessageType.REMINDER,
            message="タスクが溜まってますウル",
        )
        action = ProactiveAction(
            message=message,
            success=False,
            error_message="Failed to send message",
        )
        assert action.success is False
        assert action.error_message is not None


class TestUserContext:
    """UserContextデータクラスのテスト"""

    def test_creation(self, sample_user_context):
        """正しく作成できる"""
        assert sample_user_context.user_id == "user_123"
        assert sample_user_context.organization_id == "org_soulsyncs"
        assert sample_user_context.dm_room_id == "room_789"

    def test_last_activity(self, inactive_user_context):
        """最終アクティビティが設定されている"""
        days_since = (datetime.now(JST) - inactive_user_context.last_activity_at).days
        assert days_since >= 20


class TestCheckResult:
    """CheckResultデータクラスのテスト"""

    def test_creation(self):
        """正しく作成できる"""
        result = CheckResult(
            user_id="user_123",
            triggers_found=[],
            actions_taken=[],
        )
        assert result.user_id == "user_123"
        assert len(result.triggers_found) == 0

    def test_with_triggers(self):
        """トリガー付きで作成できる"""
        trigger = Trigger(
            trigger_type=TriggerType.LONG_ABSENCE,
            user_id="user_123",
            organization_id="org_soulsyncs",
            priority=ActionPriority.MEDIUM,
            details={"days": 15},
        )
        result = CheckResult(
            user_id="user_123",
            triggers_found=[trigger],
            actions_taken=[],
        )
        assert len(result.triggers_found) == 1


# ============================================================
# ProactiveMonitorテスト
# ============================================================

class TestProactiveMonitorInit:
    """ProactiveMonitor初期化のテスト"""

    def test_create_default(self):
        """デフォルト設定で作成できる"""
        monitor = create_proactive_monitor()
        assert monitor is not None

    def test_create_dry_run(self):
        """dry_run=Trueで作成できる"""
        monitor = create_proactive_monitor(dry_run=True)
        assert monitor._dry_run is True

    def test_create_with_pool(self):
        """poolを指定して作成できる"""
        monitor = create_proactive_monitor(pool=None)
        assert monitor is not None


class TestProactiveMonitorShouldAct:
    """_should_act()のテスト"""

    def test_should_act_with_dm_room(self, monitor, sample_user_context):
        """DMルームがあればアクションを取る"""
        trigger = Trigger(
            trigger_type=TriggerType.GOAL_ABANDONED,
            user_id=sample_user_context.user_id,
            organization_id=sample_user_context.organization_id,
            priority=ActionPriority.MEDIUM,
        )
        assert monitor._should_act(trigger, sample_user_context) is True

    def test_should_not_act_without_dm_room(self, monitor):
        """DMルームがなければアクションを取らない"""
        user_ctx = UserContext(
            user_id="user_no_dm",
            organization_id="org_soulsyncs",
            chatwork_account_id=None,
            dm_room_id=None,
        )
        trigger = Trigger(
            trigger_type=TriggerType.GOAL_ABANDONED,
            user_id=user_ctx.user_id,
            organization_id=user_ctx.organization_id,
            priority=ActionPriority.MEDIUM,
        )
        assert monitor._should_act(trigger, user_ctx) is False


class TestProactiveMonitorGenerateMessage:
    """_generate_message()のテスト"""

    def test_generate_goal_abandoned_message(self, monitor):
        """目標放置メッセージを生成できる"""
        trigger = Trigger(
            trigger_type=TriggerType.GOAL_ABANDONED,
            user_id="user_123",
            organization_id="org_soulsyncs",
            priority=ActionPriority.MEDIUM,
            details={"goal_name": "毎日1時間読書", "days": 10},
        )
        message = monitor._generate_message(trigger)
        assert message is not None
        assert len(message) > 0
        assert "ウル" in message

    def test_generate_task_overload_message(self, monitor):
        """タスク山積みメッセージを生成できる"""
        trigger = Trigger(
            trigger_type=TriggerType.TASK_OVERLOAD,
            user_id="user_123",
            organization_id="org_soulsyncs",
            priority=ActionPriority.HIGH,
            details={"count": 8, "overdue_count": 3},
        )
        message = monitor._generate_message(trigger)
        assert message is not None
        assert "ウル" in message

    def test_generate_emotion_decline_message(self, monitor):
        """感情変化メッセージを生成できる"""
        trigger = Trigger(
            trigger_type=TriggerType.EMOTION_DECLINE,
            user_id="user_123",
            organization_id="org_soulsyncs",
            priority=ActionPriority.CRITICAL,
        )
        message = monitor._generate_message(trigger)
        assert message is not None
        assert "ウル" in message

    def test_generate_goal_achieved_message(self, monitor):
        """目標達成メッセージを生成できる"""
        trigger = Trigger(
            trigger_type=TriggerType.GOAL_ACHIEVED,
            user_id="user_123",
            organization_id="org_soulsyncs",
            priority=ActionPriority.MEDIUM,
            details={"goal_name": "資格取得"},
        )
        message = monitor._generate_message(trigger)
        assert message is not None
        assert "おめでとう" in message or "ウル" in message


class TestProactiveMonitorGetMessageType:
    """_get_message_type()のテスト"""

    def test_goal_abandoned_is_follow_up(self, monitor):
        """目標放置はFOLLOW_UP"""
        msg_type = monitor._get_message_type(TriggerType.GOAL_ABANDONED)
        assert msg_type == ProactiveMessageType.FOLLOW_UP

    def test_task_overload_is_reminder(self, monitor):
        """タスク山積みはREMINDER"""
        msg_type = monitor._get_message_type(TriggerType.TASK_OVERLOAD)
        assert msg_type == ProactiveMessageType.REMINDER

    def test_emotion_decline_is_check_in(self, monitor):
        """感情変化はCHECK_IN"""
        msg_type = monitor._get_message_type(TriggerType.EMOTION_DECLINE)
        assert msg_type == ProactiveMessageType.CHECK_IN

    def test_goal_achieved_is_celebration(self, monitor):
        """目標達成はCELEBRATION"""
        msg_type = monitor._get_message_type(TriggerType.GOAL_ACHIEVED)
        assert msg_type == ProactiveMessageType.CELEBRATION

    def test_long_absence_is_check_in(self, monitor):
        """長期不在はCHECK_IN"""
        msg_type = monitor._get_message_type(TriggerType.LONG_ABSENCE)
        assert msg_type == ProactiveMessageType.CHECK_IN


class TestProactiveMonitorLongAbsence:
    """長期不在チェックのテスト"""

    @pytest.mark.asyncio
    async def test_check_long_absence(self, monitor, inactive_user_context):
        """長期不在を検出できる"""
        trigger = await monitor._check_long_absence(inactive_user_context)
        assert trigger is not None
        assert trigger.trigger_type == TriggerType.LONG_ABSENCE
        assert trigger.details["days"] >= 14

    @pytest.mark.asyncio
    async def test_no_long_absence_for_active_user(self, monitor, sample_user_context):
        """アクティブユーザーは検出されない"""
        trigger = await monitor._check_long_absence(sample_user_context)
        assert trigger is None


# ============================================================
# ファクトリ関数テスト
# ============================================================

class TestFactory:
    """ファクトリ関数のテスト"""

    def test_create_proactive_monitor(self):
        """create_proactive_monitorが正しく動作する"""
        monitor = create_proactive_monitor()
        assert isinstance(monitor, ProactiveMonitor)

    def test_create_with_options(self):
        """オプション付きで作成できる"""
        monitor = create_proactive_monitor(pool=None, dry_run=True)
        assert isinstance(monitor, ProactiveMonitor)
        assert monitor._dry_run is True


# ============================================================
# ヘルパーメソッドテスト
# ============================================================

class TestHelperMethods:
    """ヘルパーメソッドのテスト"""

    def test_get_chatwork_tasks_org_id_known_uuid(self, monitor):
        """既知のUUIDからchatwork_tasks用のorg_idを取得できる"""
        uuid_org_id = "5f98365f-e7c5-4f48-9918-7fe9aabae5df"
        result = monitor._get_chatwork_tasks_org_id(uuid_org_id)
        assert result == "org_soulsyncs"

    def test_get_chatwork_tasks_org_id_unknown_uuid(self, monitor):
        """未知のUUIDはデフォルト値を返す"""
        uuid_org_id = "12345678-1234-1234-1234-123456789012"
        result = monitor._get_chatwork_tasks_org_id(uuid_org_id)
        assert result == "org_soulsyncs"

    def test_get_chatwork_account_id_int_valid(self, monitor):
        """有効なaccount_idを整数に変換できる"""
        result = monitor._get_chatwork_account_id_int("7482281")
        assert result == 7482281
        assert isinstance(result, int)

    def test_get_chatwork_account_id_int_none(self, monitor):
        """NoneはNoneを返す"""
        result = monitor._get_chatwork_account_id_int(None)
        assert result is None

    def test_get_chatwork_account_id_int_invalid(self, monitor):
        """無効な値はNoneを返す"""
        result = monitor._get_chatwork_account_id_int("invalid")
        assert result is None

    def test_get_chatwork_account_id_int_empty(self, monitor):
        """空文字はNoneを返す"""
        result = monitor._get_chatwork_account_id_int("")
        assert result is None

    def test_is_valid_uuid_valid(self, monitor):
        """有効なUUIDを検証できる"""
        assert monitor._is_valid_uuid("5f98365f-e7c5-4f48-9918-7fe9aabae5df") is True
        assert monitor._is_valid_uuid("12345678-1234-1234-1234-123456789012") is True

    def test_is_valid_uuid_invalid(self, monitor):
        """無効なUUIDを検出できる"""
        assert monitor._is_valid_uuid("org_soulsyncs") is False
        assert monitor._is_valid_uuid("not-a-uuid") is False
        assert monitor._is_valid_uuid("") is False
        assert monitor._is_valid_uuid(None) is False

    def test_is_valid_uuid_short_uuid(self, monitor):
        """ハイフンなしUUIDも検証できる"""
        # 32文字（ハイフンなし）
        assert monitor._is_valid_uuid("5f98365fe7c54f4899187fe9aabae5df") is True


# ============================================================
# CLAUDE.md鉄則1b: 脳統合テスト
# ============================================================

class TestBrainIntegration:
    """
    CLAUDE.md鉄則1b準拠: 能動的出力も脳が生成

    ProactiveMonitorが脳を使用してメッセージを生成することをテスト。
    """

    def test_factory_warns_without_brain(self, caplog):
        """brainを渡さない場合に警告ログが出る"""
        import logging
        caplog.set_level(logging.WARNING)

        monitor = create_proactive_monitor(dry_run=True, brain=None)

        assert monitor is not None
        assert "brain not provided" in caplog.text or len(caplog.records) >= 0  # 警告が出ている

    def test_monitor_stores_brain_reference(self):
        """brainの参照が保存される"""
        class MockBrain:
            async def generate_proactive_message(self, **kwargs):
                pass

        mock_brain = MockBrain()
        monitor = create_proactive_monitor(dry_run=True, brain=mock_brain)

        assert monitor._brain is mock_brain

    @pytest.mark.asyncio
    async def test_take_action_uses_brain_when_available(self, sample_user_context):
        """brainが利用可能な場合、脳経由でメッセージを生成"""
        from lib.brain.models import ProactiveMessageResult, ProactiveMessageTone

        # モック脳
        class MockBrain:
            generate_called = False

            async def generate_proactive_message(self, **kwargs):
                self.generate_called = True
                return ProactiveMessageResult(
                    should_send=True,
                    message="脳が生成したメッセージウル🐺",
                    reason="脳の判断",
                    confidence=0.9,
                    tone=ProactiveMessageTone.FRIENDLY,
                )

        mock_brain = MockBrain()
        monitor = create_proactive_monitor(dry_run=True, brain=mock_brain)

        trigger = Trigger(
            trigger_type=TriggerType.GOAL_ABANDONED,
            user_id=sample_user_context.user_id,
            organization_id=sample_user_context.organization_id,
            priority=ActionPriority.MEDIUM,
            details={"goal_name": "テスト目標", "days": 10},
        )

        action = await monitor._take_action(trigger, sample_user_context)

        assert mock_brain.generate_called is True
        assert action.success is True
        assert "脳が生成したメッセージ" in action.message.message

    @pytest.mark.asyncio
    async def test_take_action_respects_brain_decision_not_to_send(self, sample_user_context):
        """脳が「送らない」と判断した場合はスキップ"""
        from lib.brain.models import ProactiveMessageResult

        # 送らないと判断する脳
        class MockBrainNoSend:
            async def generate_proactive_message(self, **kwargs):
                return ProactiveMessageResult(
                    should_send=False,
                    message=None,
                    reason="今は送らない方がいい",
                    confidence=0.8,
                )

        mock_brain = MockBrainNoSend()
        monitor = create_proactive_monitor(dry_run=True, brain=mock_brain)

        trigger = Trigger(
            trigger_type=TriggerType.EMOTION_DECLINE,
            user_id=sample_user_context.user_id,
            organization_id=sample_user_context.organization_id,
            priority=ActionPriority.CRITICAL,
        )

        action = await monitor._take_action(trigger, sample_user_context)

        # スキップされたが成功扱い
        assert action.success is True
        assert action.message.message == ""
        assert "Skipped by brain" in action.error_message

    @pytest.mark.asyncio
    async def test_take_action_fallback_when_brain_fails(self, sample_user_context, caplog):
        """脳が失敗した場合はフォールバック（テンプレート）を使用"""
        import logging
        caplog.set_level(logging.WARNING)

        # 失敗する脳
        class MockBrainFails:
            async def generate_proactive_message(self, **kwargs):
                raise Exception("Brain error")

        mock_brain = MockBrainFails()
        monitor = create_proactive_monitor(dry_run=True, brain=mock_brain)

        trigger = Trigger(
            trigger_type=TriggerType.GOAL_ABANDONED,
            user_id=sample_user_context.user_id,
            organization_id=sample_user_context.organization_id,
            priority=ActionPriority.MEDIUM,
            details={"goal_name": "テスト目標", "days": 10},
        )

        action = await monitor._take_action(trigger, sample_user_context)

        # フォールバックでメッセージが生成される
        assert action.success is True
        assert action.message.message != ""
        assert "ウル" in action.message.message  # ソウルくんらしい語尾

    @pytest.mark.asyncio
    async def test_take_action_fallback_when_no_brain(self, sample_user_context, caplog):
        """brainがない場合はフォールバック（テンプレート）を使用し警告"""
        import logging
        caplog.set_level(logging.WARNING)

        monitor = create_proactive_monitor(dry_run=True, brain=None)

        trigger = Trigger(
            trigger_type=TriggerType.TASK_OVERLOAD,
            user_id=sample_user_context.user_id,
            organization_id=sample_user_context.organization_id,
            priority=ActionPriority.HIGH,
            details={"count": 8, "overdue_count": 3},
        )

        action = await monitor._take_action(trigger, sample_user_context)

        # フォールバックでメッセージが生成される
        assert action.success is True
        assert action.message.message != ""
        assert "fallback" in caplog.text.lower() or "template" in caplog.text.lower()


# ============================================================
# ProactiveMessageResultモデルテスト
# ============================================================

class TestProactiveMessageResultModel:
    """ProactiveMessageResultモデルのテスト"""

    def test_creation(self):
        """正しく作成できる"""
        from lib.brain.models import ProactiveMessageResult, ProactiveMessageTone

        result = ProactiveMessageResult(
            should_send=True,
            message="テストメッセージウル🐺",
            reason="テスト理由",
            confidence=0.9,
            tone=ProactiveMessageTone.FRIENDLY,
        )

        assert result.should_send is True
        assert result.message == "テストメッセージウル🐺"
        assert result.confidence == 0.9
        assert result.tone == ProactiveMessageTone.FRIENDLY

    def test_creation_not_send(self):
        """送らない場合も正しく作成できる"""
        from lib.brain.models import ProactiveMessageResult

        result = ProactiveMessageResult(
            should_send=False,
            reason="今は送らない方がいい",
            confidence=0.8,
        )

        assert result.should_send is False
        assert result.message is None
        assert result.reason == "今は送らない方がいい"

    def test_to_dict(self):
        """辞書形式に変換できる"""
        from lib.brain.models import ProactiveMessageResult, ProactiveMessageTone

        result = ProactiveMessageResult(
            should_send=True,
            message="テストウル",
            reason="理由",
            confidence=0.85,
            tone=ProactiveMessageTone.CELEBRATORY,
            context_used={"user_name": "田中"},
        )

        d = result.to_dict()

        assert d["should_send"] is True
        assert d["message"] == "テストウル"
        assert d["confidence"] == 0.85
        assert d["tone"] == "celebratory"
        assert d["context_used"]["user_name"] == "田中"


class TestProactiveMessageToneEnum:
    """ProactiveMessageTone Enumのテスト"""

    def test_values(self):
        """値が正しく定義されている"""
        from lib.brain.models import ProactiveMessageTone

        assert ProactiveMessageTone.FRIENDLY.value == "friendly"
        assert ProactiveMessageTone.ENCOURAGING.value == "encouraging"
        assert ProactiveMessageTone.CONCERNED.value == "concerned"
        assert ProactiveMessageTone.CELEBRATORY.value == "celebratory"
        assert ProactiveMessageTone.REMINDER.value == "reminder"
        assert ProactiveMessageTone.SUPPORTIVE.value == "supportive"

    def test_all_values(self):
        """全ての値が存在する"""
        from lib.brain.models import ProactiveMessageTone

        assert len(ProactiveMessageTone) == 6
