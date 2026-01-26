# tests/test_brain_execution.py
"""
BrainExecution（実行層）のユニットテスト

テスト対象:
- 初期化
- ハンドラー取得
- パラメータ検証
- 実行フロー
- エラーハンドリング
- リトライ
- タイムアウト
- 先読み提案
- 結果統合
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Dict, Any

from lib.brain.execution import (
    BrainExecution,
    ExecutionResult,
    create_execution,
    HANDLER_TIMEOUT_SECONDS,
    RETRY_DELAY_SECONDS,
    ERROR_MESSAGES,
    SUGGESTION_TEMPLATES,
    REQUIRED_PARAMETERS,
    PARAMETER_TYPES,
)
from lib.brain.models import (
    BrainContext,
    DecisionResult,
    HandlerResult,
)
from lib.brain.exceptions import (
    HandlerTimeoutError,
    ParameterValidationError,
)


# =============================================================================
# フィクスチャ
# =============================================================================

@pytest.fixture
def sample_context() -> BrainContext:
    """テスト用のBrainContext"""
    return BrainContext(
        sender_name="テストユーザー",
        sender_account_id="7890",
        recent_conversation=[],
        recent_tasks=[],
        active_goals=[],
        person_info=[],
        relevant_knowledge=[],
    )


@pytest.fixture
def sample_decision() -> DecisionResult:
    """テスト用のDecisionResult"""
    return DecisionResult(
        action="chatwork_task_create",
        params={"body": "テストタスク"},
        confidence=0.9,
        needs_confirmation=False,
    )


@pytest.fixture
def sample_handlers() -> Dict[str, Any]:
    """テスト用のハンドラー"""
    async def mock_task_create(params, room_id, account_id, sender_name, context):
        return HandlerResult(
            success=True,
            message="タスクを作成したウル！",
            data={"task_id": "12345"},
        )

    async def mock_task_search(params, room_id, account_id, sender_name, context):
        return HandlerResult(
            success=True,
            message="タスクを見つけたウル！",
            data={"tasks": [], "overdue_count": 0},
        )

    async def mock_failing_handler(params, room_id, account_id, sender_name, context):
        raise ConnectionError("接続エラー")

    async def mock_slow_handler(params, room_id, account_id, sender_name, context):
        await asyncio.sleep(60)  # タイムアウトするまで待機
        return HandlerResult(success=True, message="完了")

    def sync_handler(params, room_id, account_id, sender_name, context):
        return {"success": True, "message": "同期ハンドラー完了"}

    return {
        "chatwork_task_create": mock_task_create,
        "chatwork_task_search": mock_task_search,
        "failing_handler": mock_failing_handler,
        "slow_handler": mock_slow_handler,
        "sync_handler": sync_handler,
    }


@pytest.fixture
def execution(sample_handlers) -> BrainExecution:
    """テスト用のBrainExecution"""
    return BrainExecution(
        handlers=sample_handlers,
        get_ai_response_func=lambda conv, ctx: "AI応答ウル！",
        org_id="org_test",
        enable_suggestions=True,
        enable_retry=True,
    )


@pytest.fixture
def execution_no_retry(sample_handlers) -> BrainExecution:
    """リトライ無効のBrainExecution"""
    return BrainExecution(
        handlers=sample_handlers,
        org_id="org_test",
        enable_retry=False,
    )


# =============================================================================
# 初期化テスト
# =============================================================================

class TestBrainExecutionInit:
    """初期化テスト"""

    def test_init_default(self):
        """デフォルト初期化"""
        execution = BrainExecution()
        assert execution.handlers == {}
        assert execution.get_ai_response is None
        assert execution.org_id == ""
        assert execution.enable_suggestions is True
        assert execution.enable_retry is True

    def test_init_with_handlers(self, sample_handlers):
        """ハンドラー付き初期化"""
        execution = BrainExecution(handlers=sample_handlers)
        assert len(execution.handlers) == len(sample_handlers)
        assert "chatwork_task_create" in execution.handlers

    def test_init_with_options(self, sample_handlers):
        """オプション付き初期化"""
        execution = BrainExecution(
            handlers=sample_handlers,
            org_id="org_custom",
            enable_suggestions=False,
            enable_retry=False,
        )
        assert execution.org_id == "org_custom"
        assert execution.enable_suggestions is False
        assert execution.enable_retry is False

    def test_create_execution_factory(self):
        """ファクトリ関数のテスト"""
        execution = create_execution(
            handlers={"test": lambda: None},
            org_id="org_factory",
        )
        assert isinstance(execution, BrainExecution)
        assert execution.org_id == "org_factory"


# =============================================================================
# 定数テスト
# =============================================================================

class TestExecutionConstants:
    """定数のテスト"""

    def test_handler_timeout_positive(self):
        """ハンドラータイムアウトが正の値"""
        assert HANDLER_TIMEOUT_SECONDS > 0

    def test_retry_delay_positive(self):
        """リトライ間隔が正の値"""
        assert RETRY_DELAY_SECONDS > 0

    def test_error_messages_defined(self):
        """エラーメッセージが定義されている"""
        required_keys = [
            "parameter_missing",
            "handler_not_found",
            "handler_timeout",
            "handler_error",
            "permission_denied",
        ]
        for key in required_keys:
            assert key in ERROR_MESSAGES

    def test_suggestion_templates_defined(self):
        """先読み提案テンプレートが定義されている"""
        assert "chatwork_task_create" in SUGGESTION_TEMPLATES
        assert "chatwork_task_search" in SUGGESTION_TEMPLATES

    def test_required_parameters_defined(self):
        """必須パラメータが定義されている"""
        assert "chatwork_task_create" in REQUIRED_PARAMETERS
        assert "body" in REQUIRED_PARAMETERS["chatwork_task_create"]


# =============================================================================
# ハンドラー取得テスト
# =============================================================================

class TestHandlerRetrieval:
    """ハンドラー取得テスト"""

    def test_get_existing_handler(self, execution):
        """存在するハンドラーの取得"""
        handler = execution._get_handler("chatwork_task_create")
        assert handler is not None

    def test_get_nonexistent_handler(self, execution):
        """存在しないハンドラーの取得"""
        handler = execution._get_handler("nonexistent_action")
        assert handler is None

    def test_find_similar_handler_exact(self, execution):
        """大文字小文字を無視した類似ハンドラー検索"""
        similar = execution._find_similar_handler("CHATWORK_TASK_CREATE")
        assert similar == "chatwork_task_create"

    def test_find_similar_handler_partial(self, execution):
        """部分一致の類似ハンドラー検索"""
        similar = execution._find_similar_handler("task_create")
        assert similar == "chatwork_task_create"

    def test_find_similar_handler_no_match(self, execution):
        """一致なしの類似ハンドラー検索"""
        similar = execution._find_similar_handler("completely_different")
        assert similar is None


# =============================================================================
# パラメータ検証テスト
# =============================================================================

class TestParameterValidation:
    """パラメータ検証テスト"""

    def test_validate_valid_params(self, execution):
        """有効なパラメータの検証"""
        error = execution._validate_parameters(
            "chatwork_task_create",
            {"body": "テストタスク"}
        )
        assert error is None

    def test_validate_missing_required_param(self, execution):
        """必須パラメータ欠落の検証"""
        error = execution._validate_parameters(
            "chatwork_task_create",
            {}
        )
        assert error is not None
        assert "タスクの内容" in error

    def test_validate_empty_string_param(self, execution):
        """空文字列パラメータの検証"""
        error = execution._validate_parameters(
            "chatwork_task_create",
            {"body": "   "}
        )
        assert error is not None

    def test_validate_none_param(self, execution):
        """Noneパラメータの検証"""
        error = execution._validate_parameters(
            "chatwork_task_create",
            {"body": None}
        )
        assert error is not None

    def test_validate_optional_params_only(self, execution):
        """オプションパラメータのみのアクション"""
        error = execution._validate_parameters(
            "chatwork_task_search",
            {}
        )
        assert error is None

    def test_get_param_display_name(self, execution):
        """パラメータ表示名の取得"""
        assert execution._get_param_display_name("body") == "タスクの内容"
        assert execution._get_param_display_name("task_id") == "タスクID"
        assert execution._get_param_display_name("unknown") == "unknown"


# =============================================================================
# 実行フローテスト
# =============================================================================

class TestExecutionFlow:
    """実行フローテスト"""

    @pytest.mark.asyncio
    async def test_execute_success(self, execution, sample_decision, sample_context):
        """正常な実行フロー"""
        result = await execution.execute(
            decision=sample_decision,
            context=sample_context,
            room_id="123456",
            account_id="7890",
            sender_name="テスト",
        )

        assert result.success is True
        assert "タスクを作成した" in result.message
        assert result.action == "chatwork_task_create"
        assert result.execution_time_ms >= 0

    @pytest.mark.asyncio
    async def test_execute_with_suggestions(self, execution, sample_decision, sample_context):
        """先読み提案付き実行"""
        result = await execution.execute(
            decision=sample_decision,
            context=sample_context,
            room_id="123456",
            account_id="7890",
            sender_name="テスト",
        )

        assert result.success is True
        # 提案が生成されている
        assert len(result.suggestions) > 0

    @pytest.mark.asyncio
    async def test_execute_no_handler(self, execution, sample_context):
        """ハンドラーがない場合の実行"""
        decision = DecisionResult(
            action="unknown_action",
            params={},
            confidence=0.9,
            needs_confirmation=False,
        )

        result = await execution.execute(
            decision=decision,
            context=sample_context,
            room_id="123456",
            account_id="7890",
            sender_name="テスト",
        )

        # AI応答またはデフォルト応答
        assert result.success is True
        assert result.handler_name in ["ai_response", "default"]

    @pytest.mark.asyncio
    async def test_execute_parameter_error(self, execution, sample_context):
        """パラメータエラー時の実行"""
        decision = DecisionResult(
            action="chatwork_task_create",
            params={},  # 必須パラメータなし
            confidence=0.9,
            needs_confirmation=False,
        )

        result = await execution.execute(
            decision=decision,
            context=sample_context,
            room_id="123456",
            account_id="7890",
            sender_name="テスト",
        )

        assert result.success is False
        assert result.error_code == "PARAMETER_ERROR"

    @pytest.mark.asyncio
    async def test_execute_sync_handler(self, execution, sample_context):
        """同期ハンドラーの実行"""
        decision = DecisionResult(
            action="sync_handler",
            params={},
            confidence=0.9,
            needs_confirmation=False,
        )

        result = await execution.execute(
            decision=decision,
            context=sample_context,
            room_id="123456",
            account_id="7890",
            sender_name="テスト",
        )

        assert result.success is True
        assert "同期ハンドラー" in result.message


# =============================================================================
# エラーハンドリングテスト
# =============================================================================

class TestErrorHandling:
    """エラーハンドリングテスト"""

    @pytest.mark.asyncio
    async def test_handle_connection_error_with_retry(self, execution, sample_context):
        """接続エラー時のリトライ"""
        decision = DecisionResult(
            action="failing_handler",
            params={},
            confidence=0.9,
            needs_confirmation=False,
        )

        # リトライが有効なので、最大リトライ回数後にエラー
        result = await execution.execute(
            decision=decision,
            context=sample_context,
            room_id="123456",
            account_id="7890",
            sender_name="テスト",
        )

        assert result.success is False
        # 最大リトライ超過のメッセージ
        assert "何回やっても" in result.message or "エラー" in result.message

    @pytest.mark.asyncio
    async def test_handle_error_no_retry(self, execution_no_retry, sample_context):
        """リトライ無効時のエラー"""
        decision = DecisionResult(
            action="failing_handler",
            params={},
            confidence=0.9,
            needs_confirmation=False,
        )

        result = await execution_no_retry.execute(
            decision=decision,
            context=sample_context,
            room_id="123456",
            account_id="7890",
            sender_name="テスト",
        )

        assert result.success is False

    @pytest.mark.asyncio
    async def test_normalize_string_result(self, execution):
        """文字列結果の正規化"""
        result = execution._normalize_result("テストメッセージ")
        assert isinstance(result, HandlerResult)
        assert result.success is True
        assert result.message == "テストメッセージ"

    @pytest.mark.asyncio
    async def test_normalize_dict_result(self, execution):
        """辞書結果の正規化"""
        result = execution._normalize_result({
            "success": True,
            "message": "辞書メッセージ",
            "data": {"key": "value"},
        })
        assert isinstance(result, HandlerResult)
        assert result.success is True
        assert result.message == "辞書メッセージ"

    @pytest.mark.asyncio
    async def test_normalize_none_result(self, execution):
        """None結果の正規化"""
        result = execution._normalize_result(None)
        assert isinstance(result, HandlerResult)
        assert result.success is True
        assert "完了" in result.message


# =============================================================================
# タイムアウトテスト
# =============================================================================

class TestTimeout:
    """タイムアウトテスト"""

    @pytest.mark.asyncio
    async def test_handler_timeout(self, sample_handlers, sample_context):
        """ハンドラーのタイムアウト"""
        # タイムアウトを短くしたexecution
        execution = BrainExecution(
            handlers=sample_handlers,
            enable_retry=False,  # リトライなし
        )

        decision = DecisionResult(
            action="slow_handler",
            params={},
            confidence=0.9,
            needs_confirmation=False,
        )

        # タイムアウトを1秒に設定してテスト
        with patch("lib.brain.execution.HANDLER_TIMEOUT_SECONDS", 0.1):
            result = await execution.execute(
                decision=decision,
                context=sample_context,
                room_id="123456",
                account_id="7890",
                sender_name="テスト",
            )

        assert result.success is False
        assert result.error_code == "TIMEOUT"


# =============================================================================
# 先読み提案テスト
# =============================================================================

class TestSuggestions:
    """先読み提案テスト"""

    def test_generate_suggestions_task_create(self, execution, sample_context):
        """タスク作成後の提案生成"""
        result = ExecutionResult(
            success=True,
            message="タスク作成完了",
            action="chatwork_task_create",
            data={"task_id": "12345"},
        )

        suggestions = execution._generate_suggestions(
            "chatwork_task_create",
            result,
            sample_context,
        )

        assert len(suggestions) > 0
        assert len(suggestions) <= 3

    def test_generate_suggestions_task_search_with_overdue(self, execution, sample_context):
        """期限超過タスクがある場合の提案"""
        result = ExecutionResult(
            success=True,
            message="タスク検索完了",
            action="chatwork_task_search",
            data={"tasks": [], "overdue_count": 5},
        )

        suggestions = execution._generate_suggestions(
            "chatwork_task_search",
            result,
            sample_context,
        )

        # 期限超過の提案が含まれる
        assert any("期限超過" in s for s in suggestions)

    def test_generate_suggestions_disabled(self, sample_handlers, sample_context):
        """提案無効時"""
        execution = BrainExecution(
            handlers=sample_handlers,
            enable_suggestions=False,
        )

        # enable_suggestions=Falseでもメソッドは動作する
        result = ExecutionResult(
            success=True,
            message="完了",
            action="chatwork_task_create",
        )

        suggestions = execution._generate_suggestions(
            "chatwork_task_create",
            result,
            sample_context,
        )

        # 結果は返るが、execute内で使われない
        assert isinstance(suggestions, list)

    def test_generate_context_suggestions_many_tasks(self, execution):
        """タスクが多い場合のコンテキスト提案"""
        context = BrainContext(
            sender_name="テスト",
            sender_account_id="7890",
            recent_tasks=[{"id": str(i)} for i in range(5)],
        )
        result = ExecutionResult(
            success=True,
            message="完了",
            action="chatwork_task_create",
        )

        suggestions = execution._generate_context_suggestions(
            "chatwork_task_create",
            result,
            context,
        )

        # タスクが多い場合の提案
        assert any("優先順位" in s for s in suggestions)


# =============================================================================
# 結果統合テスト
# =============================================================================

class TestResultIntegration:
    """結果統合テスト"""

    def test_integrate_success_result(self, execution):
        """成功結果の統合"""
        handler_result = HandlerResult(
            success=True,
            message="完了ウル！",
            data={"id": "12345"},
        )

        result = execution._integrate_result(
            result=handler_result,
            action="chatwork_task_create",
            start_time=0,
        )

        assert result.success is True
        assert result.message == "完了ウル！"
        assert result.action == "chatwork_task_create"
        assert result.audit_action == "chatwork_task_create"
        assert result.audit_resource_type == "task"
        assert result.audit_resource_id == "12345"

    def test_integrate_failure_result(self, execution):
        """失敗結果の統合"""
        handler_result = HandlerResult(
            success=False,
            message="エラー",
            error_code="TEST_ERROR",
            error_details="テストエラー",
        )

        result = execution._integrate_result(
            result=handler_result,
            action="chatwork_task_create",
            start_time=0,
        )

        assert result.success is False
        assert result.error_code == "TEST_ERROR"

    def test_get_resource_type(self, execution):
        """リソースタイプ取得"""
        assert execution._get_resource_type("chatwork_task_create") == "task"
        assert execution._get_resource_type("learn_knowledge") == "knowledge"
        assert execution._get_resource_type("save_memory") == "memory"
        assert execution._get_resource_type("unknown") == "unknown"


# =============================================================================
# ExecutionResult テスト
# =============================================================================

class TestExecutionResult:
    """ExecutionResultのテスト"""

    def test_to_handler_result(self):
        """HandlerResultへの変換"""
        exec_result = ExecutionResult(
            success=True,
            message="テスト",
            data={"key": "value"},
            next_action="next",
            suggestions=["提案1", "提案2"],
        )

        handler_result = exec_result.to_handler_result()

        assert isinstance(handler_result, HandlerResult)
        assert handler_result.success is True
        assert handler_result.message == "テスト"
        assert handler_result.data == {"key": "value"}
        assert handler_result.next_action == "next"
        assert handler_result.suggestions == ["提案1", "提案2"]

    def test_execution_result_defaults(self):
        """デフォルト値のテスト"""
        result = ExecutionResult(
            success=True,
            message="テスト",
        )

        assert result.data is None
        assert result.error_code is None
        assert result.action == ""
        assert result.retry_count == 0
        assert result.suggestions == []


# =============================================================================
# ハンドラー管理テスト
# =============================================================================

class TestHandlerManagement:
    """ハンドラー管理テスト"""

    def test_add_handler(self, execution):
        """ハンドラーの追加"""
        execution.add_handler("new_action", lambda: "new")
        assert "new_action" in execution.handlers

    def test_remove_handler(self, execution):
        """ハンドラーの削除"""
        result = execution.remove_handler("chatwork_task_create")
        assert result is True
        assert "chatwork_task_create" not in execution.handlers

    def test_remove_nonexistent_handler(self, execution):
        """存在しないハンドラーの削除"""
        result = execution.remove_handler("nonexistent")
        assert result is False

    def test_get_available_actions(self, execution, sample_handlers):
        """利用可能なアクションの取得"""
        actions = execution.get_available_actions()
        assert len(actions) == len(sample_handlers)
        assert "chatwork_task_create" in actions


# =============================================================================
# ユーティリティテスト
# =============================================================================

class TestUtilities:
    """ユーティリティテスト"""

    def test_elapsed_ms(self, execution):
        """経過時間計算"""
        import time
        start = time.time() - 0.1  # 100ms前
        elapsed = execution._elapsed_ms(start)
        assert elapsed >= 100

    def test_create_parameter_error_result(self, execution):
        """パラメータエラー結果の作成"""
        import time
        result = execution._create_parameter_error_result(
            action="test_action",
            error_message="テストエラー",
            start_time=time.time(),
        )

        assert result.success is False
        assert result.message == "テストエラー"
        assert result.error_code == "PARAMETER_ERROR"
        assert result.update_state is not None
        assert result.update_state["state_type"] == "confirmation"


# =============================================================================
# リトライテスト
# =============================================================================

class TestRetry:
    """リトライテスト"""

    @pytest.mark.asyncio
    async def test_retry_count(self, sample_context):
        """リトライ回数のテスト"""
        call_count = 0

        async def counting_handler(params, room_id, account_id, sender_name, context):
            nonlocal call_count
            call_count += 1
            raise ConnectionError("テストエラー")

        execution = BrainExecution(
            handlers={"counting": counting_handler},
            enable_retry=True,
        )

        decision = DecisionResult(
            action="counting",
            params={},
            confidence=0.9,
            needs_confirmation=False,
        )

        # リトライ間隔を短くしてテスト
        with patch("lib.brain.execution.RETRY_DELAY_SECONDS", 0.01):
            await execution.execute(
                decision=decision,
                context=sample_context,
                room_id="123456",
                account_id="7890",
                sender_name="テスト",
            )

        # MAX_RETRY_COUNT回呼ばれる
        from lib.brain.constants import MAX_RETRY_COUNT
        assert call_count == MAX_RETRY_COUNT

    @pytest.mark.asyncio
    async def test_retry_success_on_second_attempt(self, sample_context):
        """2回目で成功するリトライ"""
        call_count = 0

        async def sometimes_failing_handler(params, room_id, account_id, sender_name, context):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ConnectionError("一時的エラー")
            return HandlerResult(success=True, message="成功！")

        execution = BrainExecution(
            handlers={"sometimes_failing": sometimes_failing_handler},
            enable_retry=True,
        )

        decision = DecisionResult(
            action="sometimes_failing",
            params={},
            confidence=0.9,
            needs_confirmation=False,
        )

        with patch("lib.brain.execution.RETRY_DELAY_SECONDS", 0.01):
            result = await execution.execute(
                decision=decision,
                context=sample_context,
                room_id="123456",
                account_id="7890",
                sender_name="テスト",
            )

        assert result.success is True
        assert call_count == 2


# =============================================================================
# 統合テスト
# =============================================================================

class TestIntegration:
    """統合テスト"""

    @pytest.mark.asyncio
    async def test_full_execution_flow(self, sample_handlers, sample_context):
        """完全な実行フロー"""
        execution = BrainExecution(
            handlers=sample_handlers,
            get_ai_response_func=lambda conv, ctx: "AI応答",
            org_id="org_integration",
            enable_suggestions=True,
            enable_retry=True,
        )

        decision = DecisionResult(
            action="chatwork_task_create",
            params={"body": "統合テストタスク"},
            confidence=0.95,
            needs_confirmation=False,
        )

        result = await execution.execute(
            decision=decision,
            context=sample_context,
            room_id="123456",
            account_id="7890",
            sender_name="統合テスト",
        )

        # 成功
        assert result.success is True
        # メッセージあり
        assert result.message
        # アクション記録
        assert result.action == "chatwork_task_create"
        # 実行時間記録
        assert result.execution_time_ms >= 0
        # 提案生成
        assert isinstance(result.suggestions, list)

    @pytest.mark.asyncio
    async def test_execution_with_core_integration(self, sample_handlers, sample_context):
        """core.pyとの統合テスト"""
        execution = BrainExecution(
            handlers=sample_handlers,
            org_id="org_core_test",
        )

        decision = DecisionResult(
            action="chatwork_task_search",
            params={},
            confidence=0.9,
            needs_confirmation=False,
        )

        result = await execution.execute(
            decision=decision,
            context=sample_context,
            room_id="123456",
            account_id="7890",
            sender_name="コアテスト",
        )

        # HandlerResultに変換可能
        handler_result = result.to_handler_result()
        assert isinstance(handler_result, HandlerResult)
        assert handler_result.success == result.success
