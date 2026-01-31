# tests/test_llm_observability.py
"""
LLM Observability テスト

設計書: docs/25_llm_native_brain_architecture.md セクション15

【テスト対象】
- LLMBrainLog データクラス
- LLMBrainObservability クラス
- コスト計算
- ログ永続化

Author: Claude Opus 4.5
Created: 2026-01-31
"""

import pytest
from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock, AsyncMock, patch

from lib.brain.llm_observability import (
    LLMBrainLog,
    LLMBrainObservability,
    UserFeedback,
    ConfirmationStatus,
    LLMLogType,
    create_llm_observability,
    get_llm_observability,
    save_user_feedback,
    COST_PER_1M_INPUT_TOKENS_USD,
    COST_PER_1M_OUTPUT_TOKENS_USD,
    USD_TO_JPY,
)


class TestLLMBrainLog:
    """LLMBrainLog のテスト"""

    def test_create_basic_log(self):
        """基本的なログ作成"""
        log = LLMBrainLog(
            organization_id="org_test",
            user_id="user_123",
            room_id="room_456",
        )

        assert log.organization_id == "org_test"
        assert log.user_id == "user_123"
        assert log.room_id == "room_456"
        assert log.output_type == "text_response"
        assert log.tool_count == 0

    def test_calculate_cost_input_only(self):
        """入力トークンのみのコスト計算"""
        log = LLMBrainLog(
            organization_id="org_test",
            user_id="user_123",
            input_tokens=1_000_000,  # 1Mトークン
            output_tokens=0,
        )

        cost = log.calculate_cost()

        # $1.75 * 154 = 269.5円
        expected = Decimal(str(COST_PER_1M_INPUT_TOKENS_USD * USD_TO_JPY))
        assert abs(cost - expected) < Decimal("0.01")

    def test_calculate_cost_output_only(self):
        """出力トークンのみのコスト計算"""
        log = LLMBrainLog(
            organization_id="org_test",
            user_id="user_123",
            input_tokens=0,
            output_tokens=1_000_000,  # 1Mトークン
        )

        cost = log.calculate_cost()

        # $14 * 154 = 2156円
        expected = Decimal(str(COST_PER_1M_OUTPUT_TOKENS_USD * USD_TO_JPY))
        assert abs(cost - expected) < Decimal("0.01")

    def test_calculate_cost_typical_request(self):
        """典型的なリクエストのコスト計算"""
        log = LLMBrainLog(
            organization_id="org_test",
            user_id="user_123",
            input_tokens=20500,   # 約20Kトークン
            output_tokens=250,    # 約250トークン
        )

        cost = log.calculate_cost()

        # 入力: 20500/1M * $1.75 * 154 = 5.53円
        # 出力: 250/1M * $14 * 154 = 0.54円
        # 合計: 約6.07円
        assert cost > Decimal("5.0")
        assert cost < Decimal("7.0")

    def test_to_dict(self):
        """辞書変換"""
        log = LLMBrainLog(
            organization_id="org_test",
            user_id="user_123",
            tool_name="chatwork_task_create",
            input_tokens=1000,
            output_tokens=100,
        )

        data = log.to_dict()

        assert data["organization_id"] == "org_test"
        assert data["user_id"] == "user_123"
        assert data["tool_name"] == "chatwork_task_create"
        assert data["input_tokens"] == 1000
        assert data["output_tokens"] == 100
        assert data["estimated_cost_yen"] is not None

    def test_to_log_string(self):
        """ログ文字列生成"""
        log = LLMBrainLog(
            organization_id="org_test",
            user_id="user_123",
            output_type="tool_call",
            tool_name="chatwork_task_create",
            confidence_overall=0.85,
            guardian_action="allow",
            execution_success=True,
            total_response_time_ms=1500,
            input_tokens=1000,
            output_tokens=100,
        )
        log.estimated_cost_yen = log.calculate_cost()

        log_str = log.to_log_string()

        assert "LLM Brain Log" in log_str
        assert "user_123" in log_str
        assert "tool_call" in log_str
        assert "chatwork_task_create" in log_str
        assert "0.85" in log_str
        assert "allow" in log_str
        assert "1500ms" in log_str

    def test_message_preview_truncation(self):
        """メッセージプレビューの切り捨て"""
        long_message = "a" * 300

        log = LLMBrainLog(
            organization_id="org_test",
            user_id="user_123",
            message_preview=long_message[:200],
        )

        assert len(log.message_preview) == 200


class TestLLMBrainObservability:
    """LLMBrainObservability のテスト"""

    def test_create_log(self):
        """ログ作成"""
        obs = LLMBrainObservability(
            org_id="org_test",
            enable_persistence=False,
        )

        log = obs.create_log(
            user_id="user_123",
            room_id="room_456",
            message="タスク追加して",
        )

        assert log.organization_id == "org_test"
        assert log.user_id == "user_123"
        assert log.room_id == "room_456"
        assert log.message_preview == "タスク追加して"
        assert log.message_hash is not None
        assert len(log.message_hash) == 64  # SHA256

    def test_create_log_without_message(self):
        """メッセージなしのログ作成"""
        obs = LLMBrainObservability(org_id="org_test")

        log = obs.create_log(user_id="user_123")

        assert log.message_preview is None
        assert log.message_hash is None

    def test_log_llm_process(self):
        """LLM処理結果のログ"""
        obs = LLMBrainObservability(
            org_id="org_test",
            enable_cloud_logging=False,
            enable_persistence=False,
        )

        # モックのLLMBrainResult
        mock_result = MagicMock()
        mock_result.output_type = "tool_call"
        mock_result.reasoning = "タスク追加の意図を検出"
        mock_result.model_used = "openai/gpt-5.2"
        mock_result.api_provider = "openrouter"
        mock_result.input_tokens = 1000
        mock_result.output_tokens = 100
        mock_result.confidence = MagicMock()
        mock_result.confidence.overall = 0.85
        mock_result.confidence.intent = 0.9
        mock_result.confidence.parameters = 0.8
        mock_result.tool_calls = [MagicMock(tool_name="chatwork_task_create", parameters={})]
        mock_result.needs_confirmation = False
        mock_result.confirmation_question = None

        log = obs.log_llm_process(
            user_id="user_123",
            message="タスク追加して",
            result=mock_result,
            response_time_ms=1500,
        )

        assert log.output_type == "tool_call"
        assert log.reasoning == "タスク追加の意図を検出"
        assert log.model_used == "openai/gpt-5.2"
        assert log.confidence_overall == 0.85
        assert log.tool_name == "chatwork_task_create"
        assert log.llm_response_time_ms == 1500
        assert log.estimated_cost_yen is not None

    def test_log_guardian_check(self):
        """Guardian判定のログ"""
        obs = LLMBrainObservability(
            org_id="org_test",
            enable_persistence=False,
        )

        log = obs.create_log(user_id="user_123")
        log.llm_response_time_ms = 1000

        # モックのGuardianResult
        mock_guardian = MagicMock()
        mock_guardian.action = MagicMock()
        mock_guardian.action.value = "allow"
        mock_guardian.reason = "安全な操作"

        log = obs.log_guardian_check(
            log_entry=log,
            guardian_result=mock_guardian,
            check_time_ms=50,
        )

        assert log.guardian_action == "allow"
        assert log.guardian_reason == "安全な操作"
        assert log.guardian_check_time_ms == 50
        assert log.total_response_time_ms == 1050

    def test_log_execution_result_success(self):
        """実行結果のログ（成功）"""
        obs = LLMBrainObservability(org_id="org_test")

        log = obs.create_log(user_id="user_123")
        log.total_response_time_ms = 1000

        log = obs.log_execution_result(
            log_entry=log,
            success=True,
            result_summary="タスクを作成しました",
            execution_time_ms=200,
        )

        assert log.execution_success is True
        assert log.execution_result_summary == "タスクを作成しました"
        assert log.total_response_time_ms == 1200

    def test_log_execution_result_failure(self):
        """実行結果のログ（失敗）"""
        obs = LLMBrainObservability(org_id="org_test")

        log = obs.create_log(user_id="user_123")

        log = obs.log_execution_result(
            log_entry=log,
            success=False,
            error_code="API_ERROR",
            error_message="ChatWork APIに接続できません",
        )

        assert log.execution_success is False
        assert log.execution_error_code == "API_ERROR"
        assert log.execution_error_message == "ChatWork APIに接続できません"

    def test_log_confirmation_response(self):
        """確認応答のログ"""
        obs = LLMBrainObservability(org_id="org_test")

        log = obs.create_log(user_id="user_123")
        log.needs_confirmation = True
        log.confirmation_status = ConfirmationStatus.PENDING.value

        log = obs.log_confirmation_response(
            log_entry=log,
            status=ConfirmationStatus.APPROVED,
        )

        assert log.confirmation_status == "approved"

    @pytest.mark.asyncio
    async def test_save_to_db(self):
        """DB保存"""
        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
        mock_conn.fetchrow.return_value = {"id": "test-uuid"}

        obs = LLMBrainObservability(
            pool=mock_pool,
            org_id="org_test",
            enable_persistence=True,
        )

        log = obs.create_log(user_id="user_123")
        log.output_type = "tool_call"
        log.input_tokens = 1000
        log.output_tokens = 100

        log_id = await obs.save(log)

        assert log_id == "test-uuid"
        mock_conn.fetchrow.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_disabled(self):
        """永続化無効時のDB保存"""
        obs = LLMBrainObservability(
            org_id="org_test",
            enable_persistence=False,
        )

        log = obs.create_log(user_id="user_123")
        log_id = await obs.save(log)

        assert log_id is None

    def test_add_to_buffer(self):
        """バッファへの追加"""
        obs = LLMBrainObservability(org_id="org_test")

        log1 = obs.create_log(user_id="user_1")
        log2 = obs.create_log(user_id="user_2")

        obs.add_to_buffer(log1)
        obs.add_to_buffer(log2)

        assert len(obs._buffer) == 2


class TestUserFeedback:
    """UserFeedback のテスト"""

    def test_create_feedback(self):
        """フィードバック作成"""
        feedback = UserFeedback(
            organization_id="org_test",
            log_id="log_123",
            user_id="user_456",
            rating=5,
            is_helpful=True,
            feedback_type="helpful",
            comment="とても役に立ちました",
        )

        assert feedback.organization_id == "org_test"
        assert feedback.log_id == "log_123"
        assert feedback.rating == 5
        assert feedback.is_helpful is True
        assert feedback.feedback_type == "helpful"

    @pytest.mark.asyncio
    async def test_save_user_feedback(self):
        """フィードバック保存"""
        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
        mock_conn.fetchrow.return_value = {"id": "feedback-uuid"}

        feedback = UserFeedback(
            organization_id="org_test",
            log_id="log_123",
            user_id="user_456",
            rating=5,
        )

        feedback_id = await save_user_feedback(mock_pool, feedback)

        assert feedback_id == "feedback-uuid"
        mock_conn.fetchrow.assert_called_once()


class TestFactoryFunctions:
    """ファクトリ関数のテスト"""

    def test_create_llm_observability(self):
        """ファクトリ関数"""
        obs = create_llm_observability(
            org_id="org_test",
            enable_persistence=True,
        )

        assert obs.org_id == "org_test"
        assert obs.enable_persistence is True

    def test_get_llm_observability_singleton(self):
        """シングルトン取得"""
        import lib.brain.llm_observability as module

        # グローバルインスタンスをリセット
        module._default_llm_observability = None

        obs1 = get_llm_observability(org_id="org_test")
        obs2 = get_llm_observability()

        assert obs1 is obs2


class TestConfirmationStatus:
    """ConfirmationStatus のテスト"""

    def test_confirmation_status_values(self):
        """確認ステータスの値"""
        assert ConfirmationStatus.PENDING.value == "pending"
        assert ConfirmationStatus.APPROVED.value == "approved"
        assert ConfirmationStatus.DENIED.value == "denied"
        assert ConfirmationStatus.TIMEOUT.value == "timeout"


class TestLLMLogType:
    """LLMLogType のテスト"""

    def test_log_type_values(self):
        """ログタイプの値"""
        assert LLMLogType.LLM_PROCESS.value == "llm_process"
        assert LLMLogType.GUARDIAN_CHECK.value == "guardian_check"
        assert LLMLogType.TOOL_EXECUTION.value == "tool_execution"


class TestCostConstants:
    """コスト定数のテスト"""

    def test_cost_constants(self):
        """コスト定数が設定されている"""
        assert COST_PER_1M_INPUT_TOKENS_USD == 1.75
        assert COST_PER_1M_OUTPUT_TOKENS_USD == 14.0
        assert USD_TO_JPY == 154
