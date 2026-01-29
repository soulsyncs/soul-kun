# tests/test_dialogue_loop.py
"""
P5対話フロー無限ループバグ修正のテスト

v10.43.3: 以下のケースをテスト
1. 空オプション時のフォールバック
2. ループ検知（2回リトライ後にフォールバック）
3. 同一応答が3回以上連続しないことを保証

v10.47.0: SessionOrchestratorに移行
_handle_confirmation_responseがsession_orchestrator.pyに移動したため、
テストをSessionOrchestratorを直接テストするように変更。
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from lib.brain.models import (
    ConversationState,
    StateType,
    BrainContext,
    HandlerResult,
)
from lib.brain.session_orchestrator import SessionOrchestrator


class TestDialogueLoopPrevention:
    """対話ループ防止のテスト"""

    @pytest.fixture
    def mock_state_manager(self):
        """モックされたStateManagerを作成"""
        state_manager = MagicMock()
        state_manager.clear_state = AsyncMock()
        state_manager.update_state_step = AsyncMock()
        state_manager.update_step = AsyncMock()
        return state_manager

    @pytest.fixture
    def orchestrator(self, mock_state_manager):
        """モックされたSessionOrchestratorを作成"""
        orchestrator = SessionOrchestrator(
            handlers={},
            state_manager=mock_state_manager,
            understanding_func=AsyncMock(),
            decision_func=AsyncMock(),
            execution_func=AsyncMock(),
            is_cancel_func=MagicMock(return_value=False),
            elapsed_ms_func=lambda x: 100,
        )
        return orchestrator

    @pytest.mark.asyncio
    async def test_empty_options_triggers_fallback(self, orchestrator):
        """空オプション時にフォールバックが発動する"""
        # 空のオプションを持つ状態
        state = ConversationState(
            room_id="123",
            user_id="456",
            state_type=StateType.CONFIRMATION,
            state_step="confirmation",
            state_data={
                "pending_action": "test_action",
                "pending_params": {},
                "confirmation_options": [],  # 空!
            },
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        response = await orchestrator._handle_confirmation_response(
            message="なんでもいいよ",
            state=state,
            context=MagicMock(spec=BrainContext),
            room_id="123",
            account_id="456",
            sender_name="テスト",
            start_time=0.0,
        )

        # フォールバック応答であることを確認
        assert "うまく質問を理解できなかった" in response.message
        assert response.action_taken == "confirmation_fallback"
        assert response.new_state == "normal"
        orchestrator.state_manager.clear_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_loop_detection_after_max_retries(self, orchestrator):
        """最大リトライ後にループ検知が発動する"""
        # リトライカウント1の状態（次で2回目=ループ検知）
        state = ConversationState(
            room_id="123",
            user_id="456",
            state_type=StateType.CONFIRMATION,
            state_step="confirmation",
            state_data={
                "pending_action": "test_action",
                "pending_params": {},
                "confirmation_options": ["選択肢1", "選択肢2"],
                "confirmation_retry_count": 1,  # 既に1回リトライ済み
                "last_confirmation_response": "番号で教えてほしいウル🐺",
            },
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        response = await orchestrator._handle_confirmation_response(
            message="わからない",
            state=state,
            context=MagicMock(spec=BrainContext),
            room_id="123",
            account_id="456",
            sender_name="テスト",
            start_time=0.0,
        )

        # ループ検知フォールバック
        assert "うまく質問を理解できなかった" in response.message
        assert response.action_taken == "confirmation_loop_fallback"
        assert response.new_state == "normal"
        assert response.debug_info.get("loop_detected") is True

    @pytest.mark.asyncio
    async def test_first_retry_shows_options(self, orchestrator):
        """1回目のリトライ時はオプションを再表示する"""
        # リトライカウント0の状態（初回リトライ）
        state = ConversationState(
            room_id="123",
            user_id="456",
            state_type=StateType.CONFIRMATION,
            state_step="confirmation",
            state_data={
                "pending_action": "test_action",
                "pending_params": {},
                "confirmation_options": ["タスク作成", "キャンセル"],
                "confirmation_retry_count": 0,
            },
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        response = await orchestrator._handle_confirmation_response(
            message="え？",
            state=state,
            context=MagicMock(spec=BrainContext),
            room_id="123",
            account_id="456",
            sender_name="テスト",
            start_time=0.0,
        )

        # オプションが再表示される
        assert "番号で選んで" in response.message
        assert "1. タスク作成" in response.message
        assert "2. キャンセル" in response.message
        assert response.action_taken == "confirmation_retry"
        assert response.awaiting_confirmation is True

    @pytest.mark.asyncio
    async def test_valid_selection_succeeds(self, mock_state_manager):
        """有効な選択は正常に処理される"""
        # モック実行関数
        mock_execute = AsyncMock(return_value=HandlerResult(
            success=True,
            message="タスクを作成したウル！",
        ))

        orchestrator = SessionOrchestrator(
            handlers={"task_create": MagicMock()},
            state_manager=mock_state_manager,
            understanding_func=AsyncMock(),
            decision_func=AsyncMock(),
            execution_func=mock_execute,
            is_cancel_func=MagicMock(return_value=False),
            elapsed_ms_func=lambda x: 100,
        )

        state = ConversationState(
            room_id="123",
            user_id="456",
            state_type=StateType.CONFIRMATION,
            state_step="confirmation",
            state_data={
                "pending_action": "task_create",
                "pending_params": {"title": "テストタスク"},
                "confirmation_options": ["作成する", "やめる"],
            },
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        response = await orchestrator._handle_confirmation_response(
            message="1",
            state=state,
            context=MagicMock(spec=BrainContext),
            room_id="123",
            account_id="456",
            sender_name="テスト",
            start_time=0.0,
        )

        # 正常に実行される
        assert response.action_taken == "task_create"
        assert response.success is True
        mock_state_manager.clear_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_cancel_clears_state(self, orchestrator):
        """キャンセルで状態がクリアされる"""
        state = ConversationState(
            room_id="123",
            user_id="456",
            state_type=StateType.CONFIRMATION,
            state_step="confirmation",
            state_data={
                "pending_action": "test_action",
                "pending_params": {},
                "confirmation_options": ["OK", "やめる"],
            },
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        response = await orchestrator._handle_confirmation_response(
            message="やめる",
            state=state,
            context=MagicMock(spec=BrainContext),
            room_id="123",
            account_id="456",
            sender_name="テスト",
            start_time=0.0,
        )

        assert response.action_taken == "cancel_confirmation"
        assert response.new_state == "normal"
        orchestrator.state_manager.clear_state.assert_called_once()


class TestNoConsecutiveIdenticalResponses:
    """同一応答が連続しないことのテスト"""

    @pytest.mark.asyncio
    async def test_no_three_consecutive_identical_responses(self):
        """同一応答が3回以上連続しない"""
        # シミュレーション: 3回連続でNone（理解できない）を返す
        responses = []

        for retry_count in range(3):
            state = ConversationState(
                room_id="123",
                user_id="456",
                state_type=StateType.CONFIRMATION,
                state_step="confirmation",
                state_data={
                    "pending_action": "test_action",
                    "pending_params": {},
                    "confirmation_options": ["A", "B"],
                    "confirmation_retry_count": retry_count,
                },
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )

            mock_state_manager = MagicMock()
            mock_state_manager.clear_state = AsyncMock()
            mock_state_manager.update_state_step = AsyncMock()
            mock_state_manager.update_step = AsyncMock()

            orchestrator = SessionOrchestrator(
                handlers={},
                state_manager=mock_state_manager,
                understanding_func=AsyncMock(),
                decision_func=AsyncMock(),
                execution_func=AsyncMock(),
                is_cancel_func=MagicMock(return_value=False),
                elapsed_ms_func=lambda x: 100,
            )

            response = await orchestrator._handle_confirmation_response(
                message="???",
                state=state,
                context=MagicMock(spec=BrainContext),
                room_id="123",
                account_id="456",
                sender_name="テスト",
                start_time=0.0,
            )
            responses.append(response.message)

        # 3回目はフォールバック（異なるメッセージ）
        assert responses[0] != responses[2], "3回目は異なるメッセージであるべき"
        assert "うまく質問を理解できなかった" in responses[2], "3回目はフォールバックメッセージ"


class TestLoggingOnLoopDetection:
    """ループ検知時のログ出力テスト"""

    @pytest.mark.asyncio
    async def test_loop_detection_logs_warning(self):
        """ループ検知時に警告ログが出力される"""
        state = ConversationState(
            room_id="123",
            user_id="456",
            state_type=StateType.CONFIRMATION,
            state_step="confirmation",
            state_data={
                "pending_action": "test_action",
                "pending_params": {},
                "confirmation_options": [],  # 空オプション
            },
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        mock_state_manager = MagicMock()
        mock_state_manager.clear_state = AsyncMock()

        orchestrator = SessionOrchestrator(
            handlers={},
            state_manager=mock_state_manager,
            understanding_func=AsyncMock(),
            decision_func=AsyncMock(),
            execution_func=AsyncMock(),
            is_cancel_func=MagicMock(return_value=False),
            elapsed_ms_func=lambda x: 100,
        )

        with patch("lib.brain.session_orchestrator.logger") as mock_logger:
            await orchestrator._handle_confirmation_response(
                message="test",
                state=state,
                context=MagicMock(spec=BrainContext),
                room_id="123",
                account_id="456",
                sender_name="テスト",
                start_time=0.0,
            )

            # 警告ログが出力されたことを確認
            mock_logger.warning.assert_called()
            log_message = mock_logger.warning.call_args[0][0]
            assert "DIALOGUE_LOOP_DETECTED" in log_message
