# tests/test_llm_brain_state_manager.py
"""
LLM Brain - State Manager のテスト

LLMセッション状態管理の機能をテストします。

設計書: docs/25_llm_native_brain_architecture.md セクション5.1.5
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, timedelta
import uuid

from lib.brain.state_manager import (
    LLMSessionMode,
    LLMSessionState,
    LLMPendingAction,
    LLMStateManager,
    BrainStateManager,
)


# =============================================================================
# フィクスチャ
# =============================================================================


@pytest.fixture
def sample_pending_action():
    """テスト用のLLMPendingAction"""
    return LLMPendingAction(
        action_id=str(uuid.uuid4()),
        tool_name="chatwork_task_create",
        parameters={"body": "テストタスク", "room_id": "123"},
        confirmation_question="タスクを作成しますか？",
        confirmation_type="low_confidence",
        original_message="タスク追加して",
        original_reasoning="タスク追加の意図を検出",
        confidence=0.6,
    )


@pytest.fixture
def sample_session_state(sample_pending_action):
    """テスト用のLLMSessionState"""
    return LLMSessionState(
        session_id=str(uuid.uuid4()),
        user_id="user_001",
        room_id="room_123",
        organization_id="org_test",
        mode=LLMSessionMode.NORMAL,
    )


@pytest.fixture
def mock_brain_state_manager():
    """モックのBrainStateManager"""
    mock = MagicMock(spec=BrainStateManager)
    mock.org_id = "org_test"
    mock.get_current_state = AsyncMock(return_value=None)
    mock.transition_to = AsyncMock()
    mock.clear_state = AsyncMock()
    return mock


@pytest.fixture
def llm_state_manager(mock_brain_state_manager):
    """テスト用のLLMStateManager"""
    return LLMStateManager(brain_state_manager=mock_brain_state_manager)


# =============================================================================
# LLMSessionMode 列挙型テスト
# =============================================================================


class TestLLMSessionMode:
    """LLMSessionMode列挙型のテスト"""

    def test_values(self):
        """値が正しいこと"""
        assert LLMSessionMode.NORMAL.value == "normal"
        assert LLMSessionMode.CONFIRMATION_PENDING.value == "confirmation_pending"
        assert LLMSessionMode.MULTI_STEP_FLOW.value == "multi_step_flow"
        assert LLMSessionMode.ERROR_RECOVERY.value == "error_recovery"

    def test_all_modes(self):
        """全てのモードが定義されていること"""
        assert len(list(LLMSessionMode)) == 4


# =============================================================================
# LLMPendingAction データクラステスト
# =============================================================================


class TestLLMPendingAction:
    """LLMPendingActionデータクラスのテスト"""

    def test_init(self, sample_pending_action):
        """初期化できること"""
        assert sample_pending_action.tool_name == "chatwork_task_create"
        assert sample_pending_action.parameters == {"body": "テストタスク", "room_id": "123"}
        assert sample_pending_action.confirmation_type == "low_confidence"

    def test_is_expired_false_when_new(self):
        """新しく作成されたアクションは期限切れでないこと"""
        action = LLMPendingAction(
            action_id=str(uuid.uuid4()),
            tool_name="test",
            parameters={},
            confirmation_question="test?",
            confirmation_type="test",
            original_message="test",
        )
        assert action.is_expired() is False

    def test_is_expired_true_when_old(self):
        """10分以上前に作成されたアクションは期限切れであること"""
        action = LLMPendingAction(
            action_id=str(uuid.uuid4()),
            tool_name="test",
            parameters={},
            confirmation_question="test?",
            confirmation_type="test",
            original_message="test",
            created_at=datetime.utcnow() - timedelta(minutes=15),
        )
        assert action.is_expired() is True

    def test_is_expired_with_custom_expires_at(self):
        """カスタム有効期限が機能すること"""
        # 未来の有効期限
        action = LLMPendingAction(
            action_id=str(uuid.uuid4()),
            tool_name="test",
            parameters={},
            confirmation_question="test?",
            confirmation_type="test",
            original_message="test",
            expires_at=datetime.utcnow() + timedelta(minutes=30),
        )
        assert action.is_expired() is False

        # 過去の有効期限
        action2 = LLMPendingAction(
            action_id=str(uuid.uuid4()),
            tool_name="test",
            parameters={},
            confirmation_question="test?",
            confirmation_type="test",
            original_message="test",
            expires_at=datetime.utcnow() - timedelta(minutes=1),
        )
        assert action2.is_expired() is True

    def test_to_dict(self, sample_pending_action):
        """to_dictが正しい形式を返すこと"""
        d = sample_pending_action.to_dict()
        assert "action_id" in d
        assert d["tool_name"] == "chatwork_task_create"
        assert d["parameters"] == {"body": "テストタスク", "room_id": "123"}
        assert d["confirmation_type"] == "low_confidence"
        assert "created_at" in d


# =============================================================================
# LLMSessionState データクラステスト
# =============================================================================


class TestLLMSessionState:
    """LLMSessionStateデータクラスのテスト"""

    def test_init(self, sample_session_state):
        """初期化できること"""
        assert sample_session_state.user_id == "user_001"
        assert sample_session_state.room_id == "room_123"
        assert sample_session_state.mode == LLMSessionMode.NORMAL

    def test_init_defaults(self):
        """デフォルト値で初期化できること"""
        session = LLMSessionState(
            session_id=str(uuid.uuid4()),
            user_id="user_001",
            room_id="room_123",
            organization_id="org_test",
        )
        assert session.mode == LLMSessionMode.NORMAL
        assert session.pending_action is None
        assert session.conversation_context == {}

    def test_mode_transition(self, sample_session_state):
        """モード遷移できること"""
        assert sample_session_state.mode == LLMSessionMode.NORMAL
        sample_session_state.mode = LLMSessionMode.CONFIRMATION_PENDING
        assert sample_session_state.mode == LLMSessionMode.CONFIRMATION_PENDING

    def test_set_pending_action(self, sample_session_state, sample_pending_action):
        """pending_actionを設定できること"""
        sample_session_state.pending_action = sample_pending_action
        assert sample_session_state.pending_action is not None
        assert sample_session_state.pending_action.tool_name == "chatwork_task_create"

    def test_to_dict(self, sample_session_state):
        """to_dictが正しい形式を返すこと"""
        d = sample_session_state.to_dict()
        assert "session_id" in d
        assert d["user_id"] == "user_001"
        assert d["room_id"] == "room_123"
        assert d["mode"] == "normal"

    def test_to_dict_with_pending_action(self, sample_session_state, sample_pending_action):
        """pending_actionを含むto_dictが正しい形式を返すこと"""
        sample_session_state.pending_action = sample_pending_action
        d = sample_session_state.to_dict()
        assert d["pending_action"] is not None
        assert d["pending_action"]["tool_name"] == "chatwork_task_create"


# =============================================================================
# LLMStateManager 初期化テスト
# =============================================================================


class TestLLMStateManagerInit:
    """LLMStateManager初期化のテスト"""

    def test_init(self, mock_brain_state_manager):
        """初期化できること"""
        manager = LLMStateManager(brain_state_manager=mock_brain_state_manager)
        assert manager.brain_state_manager is mock_brain_state_manager

    def test_approval_keywords(self, llm_state_manager):
        """承認キーワードが定義されていること"""
        assert len(llm_state_manager.APPROVAL_KEYWORDS) > 0
        assert "はい" in llm_state_manager.APPROVAL_KEYWORDS
        assert "yes" in llm_state_manager.APPROVAL_KEYWORDS

    def test_denial_keywords(self, llm_state_manager):
        """拒否キーワードが定義されていること"""
        assert len(llm_state_manager.DENIAL_KEYWORDS) > 0
        assert "いいえ" in llm_state_manager.DENIAL_KEYWORDS
        assert "no" in llm_state_manager.DENIAL_KEYWORDS


# =============================================================================
# LLMStateManager.get_llm_session テスト
# =============================================================================


class TestLLMStateManagerGetSession:
    """LLMStateManager.get_llm_sessionメソッドのテスト"""

    @pytest.mark.asyncio
    async def test_get_session_returns_none_when_no_state(self, llm_state_manager):
        """状態がない場合はNoneを返すこと"""
        result = await llm_state_manager.get_llm_session(
            user_id="user_001",
            room_id="room_123",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_get_session_returns_session_when_exists(
        self,
        llm_state_manager,
        mock_brain_state_manager,
    ):
        """状態がある場合はセッションを返すこと"""
        # モックの状態を設定
        mock_state = MagicMock()
        mock_state.state_data = {
            "llm_session": {
                "session_id": "sess_001",
                "user_id": "user_001",
                "room_id": "room_123",
                "organization_id": "org_test",
                "mode": "confirmation_pending",
                "pending_action": {
                    "action_id": "act_001",
                    "tool_name": "test",
                    "parameters": {},
                    "confirmation_question": "test?",
                    "confirmation_type": "test",
                    "original_message": "test",
                },
            }
        }
        mock_brain_state_manager.get_current_state.return_value = mock_state

        result = await llm_state_manager.get_llm_session(
            user_id="user_001",
            room_id="room_123",
        )

        assert result is not None
        assert result.mode == LLMSessionMode.CONFIRMATION_PENDING


# =============================================================================
# LLMStateManager.set_pending_action テスト
# =============================================================================


class TestLLMStateManagerSetPendingAction:
    """LLMStateManager.set_pending_actionメソッドのテスト"""

    @pytest.mark.asyncio
    async def test_set_pending_action_creates_session(
        self,
        llm_state_manager,
        sample_pending_action,
    ):
        """pending_actionを設定するとセッションが作成されること"""
        result = await llm_state_manager.set_pending_action(
            user_id="user_001",
            room_id="room_123",
            pending_action=sample_pending_action,
        )

        assert result is not None
        assert result.mode == LLMSessionMode.CONFIRMATION_PENDING
        assert result.pending_action is not None
        assert result.pending_action.tool_name == "chatwork_task_create"


# =============================================================================
# LLMStateManager.clear_pending_action テスト
# =============================================================================


class TestLLMStateManagerClearPendingAction:
    """LLMStateManager.clear_pending_actionメソッドのテスト"""

    @pytest.mark.asyncio
    async def test_clear_pending_action(
        self,
        llm_state_manager,
        sample_pending_action,
    ):
        """pending_actionをクリアできること"""
        # 確認待ちセッションを設定
        session_with_pending = LLMSessionState(
            session_id=str(uuid.uuid4()),
            user_id="user_001",
            room_id="room_123",
            organization_id="org_test",
            mode=LLMSessionMode.CONFIRMATION_PENDING,
            pending_action=sample_pending_action,
        )

        # get_llm_sessionのモックを設定
        with patch.object(
            llm_state_manager,
            "get_llm_session",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = session_with_pending

            # _save_llm_sessionもモック
            with patch.object(
                llm_state_manager,
                "_save_llm_session",
                new_callable=AsyncMock,
            ):
                result = await llm_state_manager.clear_pending_action(
                    user_id="user_001",
                    room_id="room_123",
                )

                # クリア後はpending_actionがNone、modeがNORMALであること
                assert result is not None
                assert result.pending_action is None
                assert result.mode == LLMSessionMode.NORMAL


# =============================================================================
# LLMStateManager.handle_confirmation_response テスト
# =============================================================================


class TestLLMStateManagerHandleConfirmation:
    """LLMStateManager.handle_confirmation_responseメソッドのテスト"""

    @pytest.mark.asyncio
    async def test_handle_approval(
        self,
        llm_state_manager,
        sample_pending_action,
    ):
        """承認レスポンスを処理できること"""
        # セッションを設定
        session = LLMSessionState(
            session_id=str(uuid.uuid4()),
            user_id="user_001",
            room_id="room_123",
            organization_id="org_test",
            mode=LLMSessionMode.CONFIRMATION_PENDING,
            pending_action=sample_pending_action,
        )

        with patch.object(
            llm_state_manager,
            "get_llm_session",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = session

            # handle_confirmation_responseはタプル(approved, pending_action)を返す
            approved, pending_action = await llm_state_manager.handle_confirmation_response(
                user_id="user_001",
                room_id="room_123",
                response="はい",
            )

            assert approved is True
            assert pending_action is not None
            assert pending_action.tool_name == "chatwork_task_create"

    @pytest.mark.asyncio
    async def test_handle_denial(
        self,
        llm_state_manager,
        sample_pending_action,
    ):
        """拒否レスポンスを処理できること"""
        session = LLMSessionState(
            session_id=str(uuid.uuid4()),
            user_id="user_001",
            room_id="room_123",
            organization_id="org_test",
            mode=LLMSessionMode.CONFIRMATION_PENDING,
            pending_action=sample_pending_action,
        )

        with patch.object(
            llm_state_manager,
            "get_llm_session",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = session

            approved, pending_action = await llm_state_manager.handle_confirmation_response(
                user_id="user_001",
                room_id="room_123",
                response="いいえ",
            )

            assert approved is False
            assert pending_action is not None

    @pytest.mark.asyncio
    async def test_handle_no_pending_action(self, llm_state_manager):
        """pending_actionがない場合の処理"""
        with patch.object(
            llm_state_manager,
            "get_llm_session",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = None

            approved, pending_action = await llm_state_manager.handle_confirmation_response(
                user_id="user_001",
                room_id="room_123",
                response="はい",
            )

            # セッションがない場合はFalse, Noneが返る
            assert approved is False
            assert pending_action is None


# =============================================================================
# LLMStateManager - キーワード判定テスト
# =============================================================================


class TestLLMStateManagerKeywordDetection:
    """キーワード判定のテスト"""

    def test_is_approval_response_true(self, llm_state_manager):
        """承認キーワードを検出できること"""
        assert llm_state_manager._is_approval_response("はい")
        assert llm_state_manager._is_approval_response("yes")
        assert llm_state_manager._is_approval_response("OK")
        assert llm_state_manager._is_approval_response("いいよ")
        assert llm_state_manager._is_approval_response("1")

    def test_is_approval_response_false(self, llm_state_manager):
        """非承認キーワードを検出しないこと"""
        assert not llm_state_manager._is_approval_response("いいえ")
        assert not llm_state_manager._is_approval_response("no")
        assert not llm_state_manager._is_approval_response("わからない")

    def test_is_approval_response_false_for_denial_keywords(self, llm_state_manager):
        """拒否キーワードがある場合にFalseを返すこと"""
        # _is_approval_responseは拒否キーワードがあればFalseを返す
        assert not llm_state_manager._is_approval_response("いいえ")
        assert not llm_state_manager._is_approval_response("no")
        assert not llm_state_manager._is_approval_response("やめて")
        assert not llm_state_manager._is_approval_response("キャンセル")
        assert not llm_state_manager._is_approval_response("2")

    def test_is_confirmation_response(self, llm_state_manager):
        """is_confirmation_responseが確認応答を判定できること"""
        # 承認キーワード
        assert llm_state_manager.is_confirmation_response("はい")
        assert llm_state_manager.is_confirmation_response("yes")
        # 拒否キーワード
        assert llm_state_manager.is_confirmation_response("いいえ")
        assert llm_state_manager.is_confirmation_response("no")
        # 確認応答ではないメッセージ
        assert not llm_state_manager.is_confirmation_response("明日の予定は？")
        assert not llm_state_manager.is_confirmation_response("タスク追加して")
