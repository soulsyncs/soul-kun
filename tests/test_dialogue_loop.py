# tests/test_dialogue_loop.py
"""
P5対話フロー無限ループバグ修正のテスト

v10.43.3: 以下のケースをテスト
1. 空オプション時のフォールバック
2. ループ検知（2回リトライ後にフォールバック）
3. 同一応答が3回以上連続しないことを保証
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from lib.brain.models import (
    ConversationState,
    StateType,
    BrainContext,
)


class TestDialogueLoopPrevention:
    """対話ループ防止のテスト"""

    @pytest.fixture
    def mock_brain(self):
        """モックされたSoulkunBrainを作成"""
        with patch("lib.brain.core.SoulkunBrain") as MockBrain:
            brain = MockBrain.return_value
            brain._elapsed_ms = MagicMock(return_value=100)
            brain._clear_state = AsyncMock()
            brain._update_state_step = AsyncMock()
            brain._parse_confirmation_response = MagicMock(return_value=None)
            yield brain

    @pytest.mark.asyncio
    async def test_empty_options_triggers_fallback(self):
        """空オプション時にフォールバックが発動する"""
        from lib.brain.core import SoulkunBrain
        from lib.brain.models import BrainResponse

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

        # モックBrainを作成
        with patch.object(SoulkunBrain, "__init__", return_value=None):
            brain = SoulkunBrain.__new__(SoulkunBrain)
            brain.state_manager = MagicMock()
            brain.state_manager.clear_state = AsyncMock()

            # _handle_confirmation_responseを直接テスト
            brain._elapsed_ms = lambda x: 100
            brain._clear_state = AsyncMock()

            response = await brain._handle_confirmation_response(
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
            brain._clear_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_loop_detection_after_max_retries(self):
        """最大リトライ後にループ検知が発動する"""
        from lib.brain.core import SoulkunBrain

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

        with patch.object(SoulkunBrain, "__init__", return_value=None):
            brain = SoulkunBrain.__new__(SoulkunBrain)
            brain._elapsed_ms = lambda x: 100
            brain._clear_state = AsyncMock()
            brain._parse_confirmation_response = MagicMock(return_value=None)

            response = await brain._handle_confirmation_response(
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
    async def test_first_retry_shows_options(self):
        """1回目のリトライ時はオプションを再表示する"""
        from lib.brain.core import SoulkunBrain

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

        with patch.object(SoulkunBrain, "__init__", return_value=None):
            brain = SoulkunBrain.__new__(SoulkunBrain)
            brain._elapsed_ms = lambda x: 100
            brain._update_state_step = AsyncMock()
            brain._parse_confirmation_response = MagicMock(return_value=None)

            response = await brain._handle_confirmation_response(
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
    async def test_valid_selection_succeeds(self):
        """有効な選択は正常に処理される"""
        from lib.brain.core import SoulkunBrain
        from lib.brain.models import DecisionResult, HandlerResult

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

        with patch.object(SoulkunBrain, "__init__", return_value=None):
            brain = SoulkunBrain.__new__(SoulkunBrain)
            brain._elapsed_ms = lambda x: 100
            brain._clear_state = AsyncMock()
            brain._parse_confirmation_response = MagicMock(return_value=0)  # 最初の選択肢
            brain._execute = AsyncMock(return_value=HandlerResult(
                success=True,
                message="タスクを作成したウル！",
            ))

            response = await brain._handle_confirmation_response(
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
            brain._clear_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_cancel_clears_state(self):
        """キャンセルで状態がクリアされる"""
        from lib.brain.core import SoulkunBrain

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

        with patch.object(SoulkunBrain, "__init__", return_value=None):
            brain = SoulkunBrain.__new__(SoulkunBrain)
            brain._elapsed_ms = lambda x: 100
            brain._clear_state = AsyncMock()
            brain._parse_confirmation_response = MagicMock(return_value="cancel")

            response = await brain._handle_confirmation_response(
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
            brain._clear_state.assert_called_once()


class TestNoConsecutiveIdenticalResponses:
    """同一応答が連続しないことのテスト"""

    @pytest.mark.asyncio
    async def test_no_three_consecutive_identical_responses(self):
        """同一応答が3回以上連続しない"""
        from lib.brain.core import SoulkunBrain

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

            with patch.object(SoulkunBrain, "__init__", return_value=None):
                brain = SoulkunBrain.__new__(SoulkunBrain)
                brain._elapsed_ms = lambda x: 100
                brain._clear_state = AsyncMock()
                brain._update_state_step = AsyncMock()
                brain._parse_confirmation_response = MagicMock(return_value=None)

                response = await brain._handle_confirmation_response(
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
        from lib.brain.core import SoulkunBrain
        import logging

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

        with patch.object(SoulkunBrain, "__init__", return_value=None):
            brain = SoulkunBrain.__new__(SoulkunBrain)
            brain._elapsed_ms = lambda x: 100
            brain._clear_state = AsyncMock()

            with patch("lib.brain.core.logger") as mock_logger:
                await brain._handle_confirmation_response(
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
