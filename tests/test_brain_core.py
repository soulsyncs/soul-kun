# tests/test_brain_core.py
"""
ソウルくんの脳 - コアクラスのテスト

SoulkunBrainクラスの基本機能をテストします。
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, timedelta

from lib.brain.core import SoulkunBrain, create_brain
from lib.brain.models import (
    BrainContext,
    BrainResponse,
    UnderstandingResult,
    DecisionResult,
    HandlerResult,
    ConversationState,
    StateType,
    ConfidenceLevel,
    MemoryType,
)
from lib.brain.constants import (
    CANCEL_KEYWORDS,
    CONFIRMATION_THRESHOLD,
    SESSION_TIMEOUT_MINUTES,
)
from lib.brain.exceptions import (
    BrainError,
    UnderstandingError,
    DecisionError,
    ExecutionError,
)


# =============================================================================
# フィクスチャ
# =============================================================================


@pytest.fixture
def mock_pool():
    """モックDBプール"""
    return MagicMock()


@pytest.fixture
def test_capabilities():
    """テスト用のSYSTEM_CAPABILITIES"""
    return {
        "chatwork_task_create": {
            "name": "ChatWorkタスク作成",
            "description": "タスクを作成する",
            "category": "task",
            "enabled": True,
            "trigger_examples": ["タスク追加して", "タスク作って"],
            "params_schema": {},
        },
        "chatwork_task_search": {
            "name": "タスク検索",
            "description": "タスクを検索する",
            "category": "task",
            "enabled": True,
            "trigger_examples": ["タスク教えて", "タスク一覧"],
            "params_schema": {},
        },
        "chatwork_task_complete": {
            "name": "タスク完了",
            "description": "タスクを完了にする",
            "category": "task",
            "enabled": True,
            "trigger_examples": ["完了にして", "終わった"],
            "params_schema": {},
        },
    }


@pytest.fixture
def brain(mock_pool, test_capabilities):
    """テスト用のSoulkunBrainインスタンス"""
    return SoulkunBrain(
        pool=mock_pool,
        org_id="org_test",
        handlers={},
        capabilities=test_capabilities,
    )


@pytest.fixture
def brain_with_handlers(mock_pool, test_capabilities):
    """ハンドラー付きのSoulkunBrainインスタンス"""
    async def mock_task_search_handler(**kwargs):
        return HandlerResult(
            success=True,
            message="タスクが3件見つかったウル🐺",
            data={"count": 3},
        )

    async def mock_task_create_handler(**kwargs):
        return HandlerResult(
            success=True,
            message="タスクを作成したウル🐺",
            data={"task_id": "12345"},
        )

    handlers = {
        "chatwork_task_search": mock_task_search_handler,
        "chatwork_task_create": mock_task_create_handler,
    }

    return SoulkunBrain(
        pool=mock_pool,
        org_id="org_test",
        handlers=handlers,
        capabilities=test_capabilities,
    )


# =============================================================================
# 基本的なテスト
# =============================================================================


class TestSoulkunBrainInit:
    """SoulkunBrainの初期化テスト"""

    def test_init_basic(self, mock_pool):
        """基本的な初期化"""
        brain = SoulkunBrain(
            pool=mock_pool,
            org_id="org_test",
        )
        assert brain.org_id == "org_test"
        assert brain.pool == mock_pool
        assert brain.handlers == {}
        assert brain.capabilities == {}

    def test_init_with_handlers(self, mock_pool):
        """ハンドラー付きの初期化"""
        handlers = {"test_action": lambda: None}
        brain = SoulkunBrain(
            pool=mock_pool,
            org_id="org_test",
            handlers=handlers,
        )
        assert "test_action" in brain.handlers

    def test_create_brain_factory(self, mock_pool):
        """ファクトリー関数のテスト"""
        brain = create_brain(
            pool=mock_pool,
            org_id="org_factory_test",
        )
        assert isinstance(brain, SoulkunBrain)
        assert brain.org_id == "org_factory_test"


# =============================================================================
# キャンセル検出のテスト
# =============================================================================


class TestCancelDetection:
    """キャンセル検出のテスト"""

    @pytest.mark.parametrize("message", [
        "やめる",
        "やめて",
        "キャンセル",
        "cancel",
        "中止",
        "やっぱりいいや",
        "もういい",
        "終わり",
    ])
    def test_is_cancel_request_positive(self, brain, message):
        """キャンセルと判定されるメッセージ"""
        assert brain._is_cancel_request(message) is True

    @pytest.mark.parametrize("message", [
        "タスクを教えて",
        "自分のタスク",
        "こんにちは",
        "ありがとう",
    ])
    def test_is_cancel_request_negative(self, brain, message):
        """キャンセルと判定されないメッセージ"""
        assert brain._is_cancel_request(message) is False


# =============================================================================
# 確認応答の解析テスト
# =============================================================================


class TestConfirmationResponseParsing:
    """確認応答の解析テスト"""

    def test_parse_number_response(self, brain):
        """数字での応答"""
        options = ["はい", "いいえ"]
        assert brain._parse_confirmation_response("1", options) == 0
        assert brain._parse_confirmation_response("2", options) == 1
        assert brain._parse_confirmation_response("3", options) is None  # 範囲外

    def test_parse_positive_response(self, brain):
        """肯定的な応答"""
        options = ["はい", "いいえ"]
        assert brain._parse_confirmation_response("はい", options) == 0
        assert brain._parse_confirmation_response("ok", options) == 0
        assert brain._parse_confirmation_response("うん", options) == 0

    def test_parse_negative_response(self, brain):
        """否定的な応答"""
        options = ["はい", "いいえ"]
        assert brain._parse_confirmation_response("いいえ", options) == "cancel"
        assert brain._parse_confirmation_response("no", options) == "cancel"

    def test_parse_cancel_response(self, brain):
        """キャンセル応答"""
        options = ["はい", "いいえ"]
        assert brain._parse_confirmation_response("やめる", options) == "cancel"
        assert brain._parse_confirmation_response("キャンセル", options) == "cancel"


# =============================================================================
# 理解層のテスト
# =============================================================================


class TestUnderstanding:
    """理解層のテスト"""

    @pytest.mark.asyncio
    async def test_understand_task_search(self, brain):
        """タスク検索の意図を理解"""
        context = BrainContext(organization_id="org_test")
        result = await brain._understand("自分のタスクを教えて", context)

        assert result.intent == "chatwork_task_search"
        assert result.intent_confidence >= 0.7

    @pytest.mark.asyncio
    async def test_understand_task_create(self, brain):
        """タスク作成の意図を理解"""
        context = BrainContext(organization_id="org_test")
        result = await brain._understand("崇樹にタスクを追加して", context)

        assert result.intent == "chatwork_task_create"
        assert result.intent_confidence >= 0.7

    @pytest.mark.asyncio
    async def test_understand_goal_setting(self, brain):
        """目標設定の意図を理解"""
        context = BrainContext(organization_id="org_test")
        result = await brain._understand("目標を設定したい", context)

        assert result.intent == "goal_registration"  # v10.29.6: SYSTEM_CAPABILITIESと名前を統一
        assert result.intent_confidence >= 0.7

    @pytest.mark.asyncio
    async def test_understand_general_conversation(self, brain):
        """一般的な会話"""
        context = BrainContext(organization_id="org_test")
        result = await brain._understand("こんにちは", context)

        assert result.intent == "general_conversation"

    @pytest.mark.asyncio
    async def test_understand_task_complete(self, brain):
        """タスク完了の意図を理解"""
        context = BrainContext(organization_id="org_test")
        result = await brain._understand("タスクを完了にして", context)

        assert result.intent == "chatwork_task_complete"
        assert result.intent_confidence >= 0.7

    @pytest.mark.asyncio
    async def test_understand_goal_progress(self, brain):
        """目標進捗報告の意図を理解"""
        context = BrainContext(organization_id="org_test")
        result = await brain._understand("目標の進捗を報告したい", context)

        assert result.intent == "goal_progress_report"
        assert result.intent_confidence >= 0.7

    @pytest.mark.asyncio
    async def test_understand_save_memory(self, brain):
        """記憶保存の意図を理解"""
        context = BrainContext(organization_id="org_test")
        result = await brain._understand("菊地さんの趣味はゴルフって覚えて", context)

        assert result.intent == "save_memory"
        assert result.intent_confidence >= 0.7

    @pytest.mark.asyncio
    async def test_understand_query_org_chart(self, brain):
        """組織図クエリの意図を理解"""
        context = BrainContext(organization_id="org_test")
        result = await brain._understand("管理部の担当者は誰？", context)

        assert result.intent == "query_org_chart"
        # 新理解層では secondary-only match は confidence_boost - 0.15 = 0.6
        assert result.intent_confidence >= 0.6

    @pytest.mark.asyncio
    async def test_understand_announcement(self, brain):
        """アナウンスの意図を理解"""
        context = BrainContext(organization_id="org_test")
        result = await brain._understand("全員にアナウンスして", context)

        assert result.intent == "announcement_create"
        assert result.intent_confidence >= 0.7

    @pytest.mark.asyncio
    async def test_understand_knowledge_query(self, brain):
        """ナレッジクエリの意図を理解"""
        context = BrainContext(organization_id="org_test")
        result = await brain._understand("就業規則について教えて", context)

        assert result.intent == "query_knowledge"
        assert result.intent_confidence >= 0.7

    @pytest.mark.asyncio
    async def test_understand_daily_reflection(self, brain):
        """振り返りの意図を理解"""
        context = BrainContext(organization_id="org_test")
        result = await brain._understand("今日の振り返りをしたい", context)

        assert result.intent == "daily_reflection"
        assert result.intent_confidence >= 0.7


# =============================================================================
# 判断層のテスト
# =============================================================================


class TestDecision:
    """判断層のテスト"""

    @pytest.mark.asyncio
    async def test_decide_high_confidence(self, brain):
        """タスク検索機能が正しく選択される"""
        context = BrainContext(organization_id="org_test")
        # エンティティを含めることでcontext_scoreも加算される
        understanding = UnderstandingResult(
            raw_message="タスク教えて一覧",  # タスク検索のキーワードを含む
            intent="chatwork_task_search",
            intent_confidence=0.9,
            entities={"person": "テスト"},  # コンテキストスコア加算用
        )

        result = await brain._decide(understanding, context)

        # BrainDecisionがキーワードスコアリングで判断
        # "タスク教えて" はchatwork_task_searchのプライマリキーワード
        assert result.action == "chatwork_task_search"
        # スコアリング: keyword(0.5*0.4) + intent(1.0*0.3) + context(0.5*0.3) = 0.65
        assert result.confidence >= 0.6

    @pytest.mark.asyncio
    async def test_decide_low_confidence(self, brain):
        """確信度が低い場合は確認が必要"""
        context = BrainContext(organization_id="org_test")
        # キーワードがないメッセージ→スコアが低い→確認が必要
        understanding = UnderstandingResult(
            raw_message="あれどうなった",
            intent="unknown",
            intent_confidence=0.5,
        )

        result = await brain._decide(understanding, context)

        # マッチする機能がないのでgeneral_response
        # general_responseは確認不要（スキップテストに変更）
        # Phase E: 機能にマッチしない場合は汎用応答を返す
        assert result.action == "general_response"
        assert result.confidence == 0.3


# =============================================================================
# 実行層のテスト
# =============================================================================


class TestExecution:
    """実行層のテスト"""

    @pytest.mark.asyncio
    async def test_execute_with_handler(self, brain_with_handlers):
        """ハンドラーが存在する場合の実行"""
        context = BrainContext(organization_id="org_test")
        decision = DecisionResult(
            action="chatwork_task_search",
            params={},
            confidence=0.9,
        )

        result = await brain_with_handlers._execute(
            decision=decision,
            context=context,
            room_id="123",
            account_id="456",
            sender_name="テスト",
        )

        assert result.success is True
        assert "3件" in result.message

    @pytest.mark.asyncio
    async def test_execute_without_handler(self, brain):
        """ハンドラーが存在しない場合のフォールバック"""
        context = BrainContext(organization_id="org_test")
        decision = DecisionResult(
            action="unknown_action",
            params={},
            confidence=0.9,
        )

        result = await brain._execute(
            decision=decision,
            context=context,
            room_id="123",
            account_id="456",
            sender_name="テスト",
        )

        # ハンドラーがなくてもエラーにはならない（汎用応答を返す）
        assert result.success is True


# =============================================================================
# 状態管理のテスト
# =============================================================================


class TestStateManagement:
    """状態管理のテスト"""

    @pytest.mark.asyncio
    async def test_get_current_state_none(self, brain):
        """状態がない場合はNoneを返す"""
        state = await brain._get_current_state("room123", "user456")
        assert state is None

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Phase C pre-existing issue: mock_pool doesn't properly handle async operations. See test_brain_state_manager.py for proper state management tests.")
    async def test_transition_to_state(self, brain):
        """状態遷移"""
        state = await brain._transition_to_state(
            room_id="room123",
            user_id="user456",
            state_type=StateType.GOAL_SETTING,
            step="why",
            timeout_minutes=30,
        )

        assert state.state_type == StateType.GOAL_SETTING
        assert state.state_step == "why"
        assert state.expires_at is not None


# =============================================================================
# process_message のテスト
# =============================================================================


class TestProcessMessage:
    """process_messageのテスト"""

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Phase E: mock_pool async handling issue with state transitions. State management mocks need to be properly configured for async context managers.")
    async def test_process_message_basic(self, brain_with_handlers):
        """基本的なメッセージ処理"""
        # "タスク教えて" はchatwork_task_searchのプライマリキーワード
        response = await brain_with_handlers.process_message(
            message="タスク教えて一覧",
            room_id="room123",
            account_id="user456",
            sender_name="テストユーザー",
        )

        assert isinstance(response, BrainResponse)
        assert response.success is True
        # BrainDecisionがキーワードスコアリングでchatwork_task_searchを選択
        assert response.action_taken == "chatwork_task_search"

    @pytest.mark.asyncio
    async def test_process_message_cancel(self, brain):
        """キャンセルメッセージの処理"""
        # まず状態を設定（モック）
        brain._get_current_state = AsyncMock(return_value=ConversationState(
            organization_id="org_test",
            room_id="room123",
            user_id="user456",
            state_type=StateType.GOAL_SETTING,
            expires_at=datetime.now() + timedelta(hours=1),
        ))
        brain._clear_state = AsyncMock()

        response = await brain.process_message(
            message="やめる",
            room_id="room123",
            account_id="user456",
            sender_name="テストユーザー",
        )

        assert response.action_taken == "cancel_session"
        assert response.state_changed is True
        brain._clear_state.assert_called_once()


# =============================================================================
# データモデルのテスト
# =============================================================================


class TestModels:
    """データモデルのテスト"""

    def test_conversation_state_is_active(self):
        """ConversationStateのis_activeプロパティ"""
        # アクティブな状態
        active_state = ConversationState(
            state_type=StateType.GOAL_SETTING,
            expires_at=datetime.now() + timedelta(hours=1),
        )
        assert active_state.is_active is True

        # 通常状態（アクティブでない）
        normal_state = ConversationState(
            state_type=StateType.NORMAL,
        )
        assert normal_state.is_active is False

        # 期限切れ（アクティブでない）
        expired_state = ConversationState(
            state_type=StateType.GOAL_SETTING,
            expires_at=datetime.now() - timedelta(hours=1),
        )
        assert expired_state.is_active is False

    def test_confidence_level_from_score(self):
        """ConfidenceLevelのfrom_score"""
        assert ConfidenceLevel.from_score(0.1) == ConfidenceLevel.VERY_LOW
        assert ConfidenceLevel.from_score(0.4) == ConfidenceLevel.LOW
        assert ConfidenceLevel.from_score(0.6) == ConfidenceLevel.MEDIUM
        assert ConfidenceLevel.from_score(0.8) == ConfidenceLevel.HIGH
        assert ConfidenceLevel.from_score(0.95) == ConfidenceLevel.VERY_HIGH

    def test_brain_context_to_prompt(self):
        """BrainContextのto_prompt_context"""
        context = BrainContext(
            organization_id="org_test",
            sender_name="テストユーザー",
        )
        prompt = context.to_prompt_context()
        assert "テストユーザー" in prompt

    def test_handler_result_defaults(self):
        """HandlerResultのデフォルト値"""
        result = HandlerResult(
            success=True,
            message="テストメッセージ",
        )
        assert result.data == {}
        assert result.suggestions == []
        assert result.next_action is None

    def test_confirmation_request_to_message(self):
        """ConfirmationRequestのto_message"""
        from lib.brain.models import ConfirmationRequest

        request = ConfirmationRequest(
            question="どれを選ぶウル？",
            options=["オプション1", "オプション2"],
        )
        message = request.to_message()
        assert "どれを選ぶウル？" in message
        assert "1. オプション1" in message
        assert "2. オプション2" in message


# =============================================================================
# 例外のテスト
# =============================================================================


class TestExceptions:
    """例外クラスのテスト"""

    def test_brain_error_to_dict(self):
        """BrainErrorのto_dict"""
        error = BrainError(
            message="テストエラー",
            error_code="TEST_ERROR",
            details={"key": "value"},
        )
        error_dict = error.to_dict()
        assert error_dict["error_type"] == "BrainError"
        assert error_dict["error_code"] == "TEST_ERROR"
        assert error_dict["message"] == "テストエラー"
        assert error_dict["details"]["key"] == "value"

    def test_understanding_error(self):
        """UnderstandingErrorのテスト"""
        error = UnderstandingError(
            message="意図を理解できません",
            raw_message="あれどうなった",
            reason="代名詞が解決できない",
        )
        assert error.error_code == "UNDERSTANDING_ERROR"
        assert "あれどうなった" in str(error.details)

    def test_execution_error(self):
        """ExecutionErrorのテスト"""
        error = ExecutionError(
            message="ハンドラー実行エラー",
            action="test_action",
            handler="test_handler",
        )
        assert error.error_code == "EXECUTION_ERROR"
        assert error.details["action"] == "test_action"


# =============================================================================
# 定数のテスト
# =============================================================================


class TestConstants:
    """定数のテスト"""

    def test_cancel_keywords_not_empty(self):
        """キャンセルキーワードが空でないこと"""
        assert len(CANCEL_KEYWORDS) > 0
        assert "やめる" in CANCEL_KEYWORDS
        assert "キャンセル" in CANCEL_KEYWORDS

    def test_confirmation_threshold_range(self):
        """確認閾値が適切な範囲内であること"""
        assert 0.0 < CONFIRMATION_THRESHOLD < 1.0

    def test_session_timeout_positive(self):
        """セッションタイムアウトが正の値であること"""
        assert SESSION_TIMEOUT_MINUTES > 0
