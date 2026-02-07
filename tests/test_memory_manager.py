# tests/test_memory_manager.py
"""
BrainMemoryManager のテスト

テスト対象: lib/brain/memory_manager.py

未カバー行を重点的にテスト:
- 86-87: update_memory_safely の例外ハンドリング
- 122-123: log_decision_safely の例外ハンドリング
- 151-189: log_soft_conflict_safely の全体
- 226-244: process_ceo_message_safely の全体
- 277-281: get_ceo_teachings_context の例外ハンドリング
"""

import pytest
from unittest.mock import Mock, AsyncMock, MagicMock, patch
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

from lib.brain.memory_manager import BrainMemoryManager
from lib.brain.models import (
    BrainContext,
    UnderstandingResult,
    DecisionResult,
    HandlerResult,
    CEOTeachingContext,
    CEOTeaching,
)
from lib.brain.memory_authority import MemoryAuthorityResult, MemoryDecision


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_learning():
    """BrainLearning のモック"""
    learning = MagicMock()
    learning.update_memory = AsyncMock()
    learning.log_decision = AsyncMock()
    return learning


@pytest.fixture
def mock_ceo_learning():
    """CEOLearningService のモック"""
    ceo_learning = MagicMock()
    ceo_learning.process_ceo_message = AsyncMock()
    ceo_learning.get_ceo_teaching_context = MagicMock()
    return ceo_learning


@pytest.fixture
def manager(mock_learning, mock_ceo_learning):
    """BrainMemoryManager インスタンス"""
    return BrainMemoryManager(
        learning=mock_learning,
        ceo_learning=mock_ceo_learning,
        organization_id="org-test-123",
    )


@pytest.fixture
def sample_handler_result():
    """サンプル HandlerResult"""
    return HandlerResult(
        success=True,
        message="OK",
        data={},
    )


@pytest.fixture
def sample_brain_context():
    """サンプル BrainContext"""
    return BrainContext()


@pytest.fixture
def sample_understanding():
    """サンプル UnderstandingResult"""
    return UnderstandingResult(
        raw_message="テストメッセージ",
        intent="general_conversation",
        intent_confidence=0.9,
    )


@pytest.fixture
def sample_decision():
    """サンプル DecisionResult"""
    return DecisionResult(
        action="general_conversation",
        params={},
        confidence=0.9,
    )


@pytest.fixture
def sample_ma_result_with_conflicts():
    """矛盾ありの MemoryAuthorityResult"""
    return MemoryAuthorityResult(
        decision=MemoryDecision.REQUIRE_CONFIRMATION,
        original_action="create_task",
        reasons=["既存方針と矛盾", "優先度の不一致"],
        conflicts=[
            {
                "memory_type": "policy",
                "excerpt": "タスクは朝に作成する方針",
                "why_conflict": "夜にタスク作成を試みている",
                "severity": "soft",
            },
            {
                "memory_type": "preference",
                "excerpt": "緊急度が低いタスクは翌日に回す",
                "why_conflict": "緊急度低のタスクを即時作成",
                "severity": "soft",
            },
        ],
        confidence=0.75,
    )


@pytest.fixture
def sample_ma_result_no_conflicts():
    """矛盾なしの MemoryAuthorityResult"""
    return MemoryAuthorityResult(
        decision=MemoryDecision.APPROVE,
        original_action="create_task",
        reasons=[],
        conflicts=[],
        confidence=1.0,
    )


# =============================================================================
# 初期化テスト
# =============================================================================


class TestBrainMemoryManagerInit:
    """初期化テスト"""

    def test_init_stores_dependencies(self, mock_learning, mock_ceo_learning):
        mgr = BrainMemoryManager(
            learning=mock_learning,
            ceo_learning=mock_ceo_learning,
            organization_id="org-abc",
        )
        assert mgr.learning is mock_learning
        assert mgr.ceo_learning is mock_ceo_learning
        assert mgr.organization_id == "org-abc"

    def test_init_default_organization_id(self, mock_learning, mock_ceo_learning):
        mgr = BrainMemoryManager(
            learning=mock_learning,
            ceo_learning=mock_ceo_learning,
        )
        assert mgr.organization_id == ""


# =============================================================================
# update_memory_safely テスト (lines 63-87)
# =============================================================================


class TestUpdateMemorySafely:
    """update_memory_safely のテスト"""

    @pytest.mark.asyncio
    async def test_update_memory_safely_success(
        self, manager, mock_learning, sample_handler_result, sample_brain_context
    ):
        """正常系: learning.update_memory が呼ばれる"""
        await manager.update_memory_safely(
            message="テストメッセージ",
            result=sample_handler_result,
            context=sample_brain_context,
            room_id="room-1",
            account_id="user-1",
            sender_name="田中太郎",
        )

        mock_learning.update_memory.assert_awaited_once_with(
            message="テストメッセージ",
            result=sample_handler_result,
            context=sample_brain_context,
            room_id="room-1",
            account_id="user-1",
            sender_name="田中太郎",
        )

    @pytest.mark.asyncio
    async def test_update_memory_safely_exception_suppressed(
        self, manager, mock_learning, sample_handler_result, sample_brain_context
    ):
        """行86-87: 例外が発生してもsuppressされる"""
        mock_learning.update_memory.side_effect = Exception("DB connection error")

        # 例外が投げられないことを確認
        await manager.update_memory_safely(
            message="テストメッセージ",
            result=sample_handler_result,
            context=sample_brain_context,
            room_id="room-1",
            account_id="user-1",
            sender_name="田中太郎",
        )

        mock_learning.update_memory.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_memory_safely_exception_logged(
        self, manager, mock_learning, sample_handler_result, sample_brain_context
    ):
        """行87: 例外メッセージがlogger.warningに記録される"""
        mock_learning.update_memory.side_effect = RuntimeError("timeout")

        with patch("lib.brain.memory_manager.logger") as mock_logger:
            await manager.update_memory_safely(
                message="msg",
                result=sample_handler_result,
                context=sample_brain_context,
                room_id="room-1",
                account_id="user-1",
                sender_name="Name",
            )
            mock_logger.warning.assert_called_once()
            assert "Error updating memory" in mock_logger.warning.call_args[0][0]


# =============================================================================
# log_decision_safely テスト (lines 93-123)
# =============================================================================


class TestLogDecisionSafely:
    """log_decision_safely のテスト"""

    @pytest.mark.asyncio
    async def test_log_decision_safely_success(
        self, manager, mock_learning, sample_understanding, sample_decision, sample_handler_result
    ):
        """正常系: learning.log_decision が呼ばれる"""
        await manager.log_decision_safely(
            message="テストメッセージ",
            understanding=sample_understanding,
            decision=sample_decision,
            result=sample_handler_result,
            room_id="room-1",
            account_id="user-1",
            understanding_time_ms=100,
            execution_time_ms=200,
            total_time_ms=300,
        )

        mock_learning.log_decision.assert_awaited_once_with(
            message="テストメッセージ",
            understanding=sample_understanding,
            decision=sample_decision,
            result=sample_handler_result,
            room_id="room-1",
            account_id="user-1",
            understanding_time_ms=100,
            execution_time_ms=200,
            total_time_ms=300,
        )

    @pytest.mark.asyncio
    async def test_log_decision_safely_default_times(
        self, manager, mock_learning, sample_understanding, sample_decision, sample_handler_result
    ):
        """デフォルトのタイム値（0）が使われる"""
        await manager.log_decision_safely(
            message="msg",
            understanding=sample_understanding,
            decision=sample_decision,
            result=sample_handler_result,
            room_id="room-1",
            account_id="user-1",
        )

        call_kwargs = mock_learning.log_decision.call_args[1]
        assert call_kwargs["understanding_time_ms"] == 0
        assert call_kwargs["execution_time_ms"] == 0
        assert call_kwargs["total_time_ms"] == 0

    @pytest.mark.asyncio
    async def test_log_decision_safely_exception_suppressed(
        self, manager, mock_learning, sample_understanding, sample_decision, sample_handler_result
    ):
        """行122-123: 例外が発生してもsuppressされる"""
        mock_learning.log_decision.side_effect = Exception("DB write failed")

        await manager.log_decision_safely(
            message="msg",
            understanding=sample_understanding,
            decision=sample_decision,
            result=sample_handler_result,
            room_id="room-1",
            account_id="user-1",
        )

        mock_learning.log_decision.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_log_decision_safely_exception_logged(
        self, manager, mock_learning, sample_understanding, sample_decision, sample_handler_result
    ):
        """行123: 例外メッセージがlogger.warningに記録される"""
        mock_learning.log_decision.side_effect = ValueError("invalid data")

        with patch("lib.brain.memory_manager.logger") as mock_logger:
            await manager.log_decision_safely(
                message="msg",
                understanding=sample_understanding,
                decision=sample_decision,
                result=sample_handler_result,
                room_id="room-1",
                account_id="user-1",
            )
            mock_logger.warning.assert_called_once()
            assert "Error logging decision" in mock_logger.warning.call_args[0][0]


# =============================================================================
# log_soft_conflict_safely テスト (lines 129-189)
# =============================================================================


class TestLogSoftConflictSafely:
    """log_soft_conflict_safely のテスト"""

    @pytest.mark.asyncio
    async def test_log_soft_conflict_safely_with_conflicts(
        self, manager, sample_ma_result_with_conflicts
    ):
        """正常系: 矛盾ありの場合にma_loggerが呼ばれる"""
        mock_ma_logger = MagicMock()
        mock_ma_logger.log_soft_conflict_async = AsyncMock(return_value="sc_123")

        with patch(
            "lib.brain.memory_manager.get_memory_authority_logger",
            return_value=mock_ma_logger,
        ):
            await manager.log_soft_conflict_safely(
                action="create_task",
                ma_result=sample_ma_result_with_conflicts,
                room_id="room-1",
                account_id="user-1",
                organization_id="org-1",
                message_excerpt="タスクを作成して",
            )

        mock_ma_logger.log_soft_conflict_async.assert_awaited_once()
        call_kwargs = mock_ma_logger.log_soft_conflict_async.call_args[1]
        assert call_kwargs["action"] == "create_task"
        assert call_kwargs["room_id"] == "room-1"
        assert call_kwargs["account_id"] == "user-1"
        assert call_kwargs["organization_id"] == "org-1"
        assert call_kwargs["message_excerpt"] == "タスクを作成して"
        assert call_kwargs["confidence"] == 0.75

    @pytest.mark.asyncio
    async def test_log_soft_conflict_safely_detected_memory_reference(
        self, manager, sample_ma_result_with_conflicts
    ):
        """矛盾のexcerptからdetected_memory_referenceが構築される"""
        mock_ma_logger = MagicMock()
        mock_ma_logger.log_soft_conflict_async = AsyncMock(return_value="sc_123")

        with patch(
            "lib.brain.memory_manager.get_memory_authority_logger",
            return_value=mock_ma_logger,
        ):
            await manager.log_soft_conflict_safely(
                action="create_task",
                ma_result=sample_ma_result_with_conflicts,
                room_id="room-1",
                account_id="user-1",
                organization_id="org-1",
                message_excerpt="test",
            )

        call_kwargs = mock_ma_logger.log_soft_conflict_async.call_args[1]
        # 2つのconflictのexcerptが " | " で結合される
        assert "タスクは朝に作成する方針" in call_kwargs["detected_memory_reference"]
        assert " | " in call_kwargs["detected_memory_reference"]
        assert "緊急度が低いタスクは翌日に回す" in call_kwargs["detected_memory_reference"]

    @pytest.mark.asyncio
    async def test_log_soft_conflict_safely_conflict_reason(
        self, manager, sample_ma_result_with_conflicts
    ):
        """reasonsからconflict_reasonが構築される"""
        mock_ma_logger = MagicMock()
        mock_ma_logger.log_soft_conflict_async = AsyncMock(return_value="sc_123")

        with patch(
            "lib.brain.memory_manager.get_memory_authority_logger",
            return_value=mock_ma_logger,
        ):
            await manager.log_soft_conflict_safely(
                action="create_task",
                ma_result=sample_ma_result_with_conflicts,
                room_id="room-1",
                account_id="user-1",
                organization_id="org-1",
                message_excerpt="test",
            )

        call_kwargs = mock_ma_logger.log_soft_conflict_async.call_args[1]
        assert "既存方針と矛盾" in call_kwargs["conflict_reason"]
        assert " / " in call_kwargs["conflict_reason"]
        assert "優先度の不一致" in call_kwargs["conflict_reason"]

    @pytest.mark.asyncio
    async def test_log_soft_conflict_safely_conflict_details(
        self, manager, sample_ma_result_with_conflicts
    ):
        """conflict_detailsが正しく構築される"""
        mock_ma_logger = MagicMock()
        mock_ma_logger.log_soft_conflict_async = AsyncMock(return_value="sc_123")

        with patch(
            "lib.brain.memory_manager.get_memory_authority_logger",
            return_value=mock_ma_logger,
        ):
            await manager.log_soft_conflict_safely(
                action="create_task",
                ma_result=sample_ma_result_with_conflicts,
                room_id="room-1",
                account_id="user-1",
                organization_id="org-1",
                message_excerpt="test",
            )

        call_kwargs = mock_ma_logger.log_soft_conflict_async.call_args[1]
        details = call_kwargs["conflict_details"]
        assert len(details) == 2
        assert details[0]["memory_type"] == "policy"
        assert details[0]["excerpt"] == "タスクは朝に作成する方針"
        assert details[0]["why_conflict"] == "夜にタスク作成を試みている"
        assert details[0]["severity"] == "soft"

    @pytest.mark.asyncio
    async def test_log_soft_conflict_safely_no_conflicts(
        self, manager, sample_ma_result_no_conflicts
    ):
        """矛盾なしの場合：空のdetected_memory_referenceとconflict_reason"""
        mock_ma_logger = MagicMock()
        mock_ma_logger.log_soft_conflict_async = AsyncMock(return_value="sc_456")

        with patch(
            "lib.brain.memory_manager.get_memory_authority_logger",
            return_value=mock_ma_logger,
        ):
            await manager.log_soft_conflict_safely(
                action="create_task",
                ma_result=sample_ma_result_no_conflicts,
                room_id="room-1",
                account_id="user-1",
                organization_id="org-1",
                message_excerpt="test",
            )

        call_kwargs = mock_ma_logger.log_soft_conflict_async.call_args[1]
        assert call_kwargs["detected_memory_reference"] == ""
        assert call_kwargs["conflict_reason"] == ""
        assert call_kwargs["conflict_details"] == []

    @pytest.mark.asyncio
    async def test_log_soft_conflict_safely_exception_suppressed(
        self, manager, sample_ma_result_with_conflicts
    ):
        """行188-189: 例外が発生してもsuppressされる"""
        with patch(
            "lib.brain.memory_manager.get_memory_authority_logger",
            side_effect=Exception("Logger init failed"),
        ):
            # 例外が投げられないことを確認
            await manager.log_soft_conflict_safely(
                action="create_task",
                ma_result=sample_ma_result_with_conflicts,
                room_id="room-1",
                account_id="user-1",
                organization_id="org-1",
                message_excerpt="test",
            )

    @pytest.mark.asyncio
    async def test_log_soft_conflict_safely_exception_logged(
        self, manager, sample_ma_result_with_conflicts
    ):
        """行189: 例外メッセージがlogger.warningに記録される"""
        with patch(
            "lib.brain.memory_manager.get_memory_authority_logger",
            side_effect=RuntimeError("broken logger"),
        ):
            with patch("lib.brain.memory_manager.logger") as mock_logger:
                await manager.log_soft_conflict_safely(
                    action="create_task",
                    ma_result=sample_ma_result_with_conflicts,
                    room_id="room-1",
                    account_id="user-1",
                    organization_id="org-1",
                    message_excerpt="test",
                )
                mock_logger.warning.assert_called_once()
                assert "Error logging soft conflict" in mock_logger.warning.call_args[0][0]

    @pytest.mark.asyncio
    async def test_log_soft_conflict_safely_excerpt_truncation(self, manager):
        """3つ以上の矛盾がある場合、最初の3つだけが使われる"""
        ma_result = MemoryAuthorityResult(
            decision=MemoryDecision.REQUIRE_CONFIRMATION,
            original_action="test",
            reasons=["reason1", "reason2", "reason3", "reason4"],
            conflicts=[
                {"memory_type": "a", "excerpt": "excerpt1", "why_conflict": "w1", "severity": "soft"},
                {"memory_type": "b", "excerpt": "excerpt2", "why_conflict": "w2", "severity": "soft"},
                {"memory_type": "c", "excerpt": "excerpt3", "why_conflict": "w3", "severity": "soft"},
                {"memory_type": "d", "excerpt": "excerpt4", "why_conflict": "w4", "severity": "soft"},
            ],
            confidence=0.6,
        )

        mock_ma_logger = MagicMock()
        mock_ma_logger.log_soft_conflict_async = AsyncMock(return_value="sc_789")

        with patch(
            "lib.brain.memory_manager.get_memory_authority_logger",
            return_value=mock_ma_logger,
        ):
            await manager.log_soft_conflict_safely(
                action="test",
                ma_result=ma_result,
                room_id="room-1",
                account_id="user-1",
                organization_id="org-1",
                message_excerpt="test",
            )

        call_kwargs = mock_ma_logger.log_soft_conflict_async.call_args[1]
        # excerpts[:3] -> 3つのみ
        ref = call_kwargs["detected_memory_reference"]
        assert "excerpt1" in ref
        assert "excerpt2" in ref
        assert "excerpt3" in ref
        # excerpt4は含まれない
        assert "excerpt4" not in ref

        # reasons[:3] -> 3つのみ
        reason = call_kwargs["conflict_reason"]
        assert "reason1" in reason
        assert "reason2" in reason
        assert "reason3" in reason
        assert "reason4" not in reason


# =============================================================================
# is_ceo_user テスト
# =============================================================================


class TestIsCeoUser:
    """is_ceo_user のテスト"""

    def test_is_ceo_user_true(self, manager):
        """CEOアカウントIDの場合True"""
        assert manager.is_ceo_user("1728974") is True

    def test_is_ceo_user_false(self, manager):
        """非CEOアカウントIDの場合False"""
        assert manager.is_ceo_user("9999999") is False

    def test_is_ceo_user_empty(self, manager):
        """空文字列の場合False"""
        assert manager.is_ceo_user("") is False


# =============================================================================
# process_ceo_message_safely テスト (lines 207-244)
# =============================================================================


class TestProcessCeoMessageSafely:
    """process_ceo_message_safely のテスト"""

    @pytest.mark.asyncio
    async def test_process_ceo_message_safely_success_with_teachings(
        self, manager, mock_ceo_learning
    ):
        """正常系: 教えが抽出・保存される"""
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.teachings_saved = 2
        mock_result.teachings_extracted = 2
        mock_ceo_learning.process_ceo_message.return_value = mock_result

        await manager.process_ceo_message_safely(
            message="お客様を大切にしなさい",
            room_id="room-1",
            account_id="1728974",
            sender_name="菊地雅克",
        )

        mock_ceo_learning.process_ceo_message.assert_awaited_once_with(
            message="お客様を大切にしなさい",
            room_id="room-1",
            account_id="1728974",
        )

    @pytest.mark.asyncio
    async def test_process_ceo_message_safely_no_teachings_detected(
        self, manager, mock_ceo_learning
    ):
        """教えが検出されなかった場合"""
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.teachings_saved = 0
        mock_result.teachings_extracted = 0
        mock_ceo_learning.process_ceo_message.return_value = mock_result

        await manager.process_ceo_message_safely(
            message="おはようございます",
            room_id="room-1",
            account_id="1728974",
            sender_name="菊地雅克",
        )

        mock_ceo_learning.process_ceo_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_process_ceo_message_safely_success_false(
        self, manager, mock_ceo_learning
    ):
        """success=False かつ teachings_extracted > 0 の場合"""
        mock_result = MagicMock()
        mock_result.success = False
        mock_result.teachings_saved = 0
        mock_result.teachings_extracted = 1
        mock_ceo_learning.process_ceo_message.return_value = mock_result

        await manager.process_ceo_message_safely(
            message="品質を重視して",
            room_id="room-1",
            account_id="1728974",
            sender_name="菊地雅克",
        )

        # 例外は出ない
        mock_ceo_learning.process_ceo_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_process_ceo_message_safely_exception_suppressed(
        self, manager, mock_ceo_learning
    ):
        """行243-244: 例外が発生してもsuppressされる"""
        mock_ceo_learning.process_ceo_message.side_effect = Exception("LLM API error")

        await manager.process_ceo_message_safely(
            message="test",
            room_id="room-1",
            account_id="1728974",
            sender_name="菊地雅克",
        )

        mock_ceo_learning.process_ceo_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_process_ceo_message_safely_exception_logged(
        self, manager, mock_ceo_learning
    ):
        """行244: 例外メッセージがlogger.warningに記録される"""
        mock_ceo_learning.process_ceo_message.side_effect = RuntimeError("timeout")

        with patch("lib.brain.memory_manager.logger") as mock_logger:
            await manager.process_ceo_message_safely(
                message="test",
                room_id="room-1",
                account_id="1728974",
                sender_name="Name",
            )
            mock_logger.warning.assert_called_once()
            assert "Error processing CEO message" in mock_logger.warning.call_args[0][0]

    @pytest.mark.asyncio
    async def test_process_ceo_message_safely_logs_info(
        self, manager, mock_ceo_learning
    ):
        """行227: logger.info が呼ばれる"""
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.teachings_saved = 1
        mock_result.teachings_extracted = 1
        mock_ceo_learning.process_ceo_message.return_value = mock_result

        with patch("lib.brain.memory_manager.logger") as mock_logger:
            await manager.process_ceo_message_safely(
                message="test",
                room_id="room-1",
                account_id="1728974",
                sender_name="菊地雅克",
            )
            # info が少なくとも1回呼ばれる（Processing CEO message + Saved teachings）
            assert mock_logger.info.call_count >= 1


# =============================================================================
# get_ceo_teachings_context テスト (lines 246-281)
# =============================================================================


class TestGetCeoTeachingsContext:
    """get_ceo_teachings_context のテスト"""

    @pytest.mark.asyncio
    async def test_get_ceo_teachings_context_with_teachings(
        self, manager, mock_ceo_learning
    ):
        """正常系: 関連する教えがある場合CEOTeachingContextを返す"""
        teaching = CEOTeaching(
            statement="お客様を大切にする",
            reasoning="信頼関係が重要",
        )
        context = CEOTeachingContext(
            relevant_teachings=[teaching],
        )
        mock_ceo_learning.get_ceo_teaching_context.return_value = context

        result = await manager.get_ceo_teachings_context(
            message="お客様対応について",
            account_id="user-1",
        )

        assert result is not None
        assert len(result.relevant_teachings) == 1
        assert result.relevant_teachings[0].statement == "お客様を大切にする"

    @pytest.mark.asyncio
    async def test_get_ceo_teachings_context_no_teachings(
        self, manager, mock_ceo_learning
    ):
        """関連する教えがない場合Noneを返す"""
        context = CEOTeachingContext(
            relevant_teachings=[],
        )
        mock_ceo_learning.get_ceo_teaching_context.return_value = context

        result = await manager.get_ceo_teachings_context(
            message="天気はどうですか",
            account_id="user-1",
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_get_ceo_teachings_context_ceo_user(
        self, manager, mock_ceo_learning
    ):
        """CEOユーザーの場合 is_ceo=True が渡される"""
        context = CEOTeachingContext(relevant_teachings=[])
        mock_ceo_learning.get_ceo_teaching_context.return_value = context

        await manager.get_ceo_teachings_context(
            message="test",
            account_id="1728974",  # CEO account ID
        )

        mock_ceo_learning.get_ceo_teaching_context.assert_called_once_with(
            query="test",
            is_ceo=True,
        )

    @pytest.mark.asyncio
    async def test_get_ceo_teachings_context_non_ceo_user(
        self, manager, mock_ceo_learning
    ):
        """非CEOユーザーの場合 is_ceo=False が渡される"""
        context = CEOTeachingContext(relevant_teachings=[])
        mock_ceo_learning.get_ceo_teaching_context.return_value = context

        await manager.get_ceo_teachings_context(
            message="test",
            account_id="9999999",
        )

        mock_ceo_learning.get_ceo_teaching_context.assert_called_once_with(
            query="test",
            is_ceo=False,
        )

    @pytest.mark.asyncio
    async def test_get_ceo_teachings_context_no_account_id(
        self, manager, mock_ceo_learning
    ):
        """account_id=None の場合 is_ceo=False"""
        context = CEOTeachingContext(relevant_teachings=[])
        mock_ceo_learning.get_ceo_teaching_context.return_value = context

        await manager.get_ceo_teachings_context(
            message="test",
            account_id=None,
        )

        mock_ceo_learning.get_ceo_teaching_context.assert_called_once_with(
            query="test",
            is_ceo=False,
        )

    @pytest.mark.asyncio
    async def test_get_ceo_teachings_context_exception_returns_none(
        self, manager, mock_ceo_learning
    ):
        """行279-281: 例外が発生した場合Noneを返す"""
        mock_ceo_learning.get_ceo_teaching_context.side_effect = Exception("Search failed")

        result = await manager.get_ceo_teachings_context(
            message="test",
            account_id="user-1",
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_get_ceo_teachings_context_exception_logged(
        self, manager, mock_ceo_learning
    ):
        """行280: 例外メッセージがlogger.warningに記録される"""
        mock_ceo_learning.get_ceo_teaching_context.side_effect = RuntimeError("DB error")

        with patch("lib.brain.memory_manager.logger") as mock_logger:
            result = await manager.get_ceo_teachings_context(
                message="test",
                account_id="user-1",
            )
            assert result is None
            mock_logger.warning.assert_called_once()
            assert "Error getting CEO teachings context" in mock_logger.warning.call_args[0][0]

    @pytest.mark.asyncio
    async def test_get_ceo_teachings_context_default_account_id(
        self, manager, mock_ceo_learning
    ):
        """account_id のデフォルト値（None）"""
        context = CEOTeachingContext(relevant_teachings=[])
        mock_ceo_learning.get_ceo_teaching_context.return_value = context

        await manager.get_ceo_teachings_context(message="test")

        mock_ceo_learning.get_ceo_teaching_context.assert_called_once_with(
            query="test",
            is_ceo=False,
        )
