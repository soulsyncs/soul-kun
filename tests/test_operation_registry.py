# tests/test_operation_registry.py
"""
Step C-1: 操作レジストリのテスト

操作の登録・検証・実行・セキュリティ制約をテストする。

Author: Claude Opus 4.6
Created: 2026-02-17
"""

import asyncio
import sys
import os
import pytest
from unittest.mock import AsyncMock

# lib/brain/__init__.pyの重い連鎖インポートを避け、直接モジュールをインポート
import importlib
_registry_mod = importlib.import_module("lib.brain.operations.registry")

OperationDefinition = _registry_mod.OperationDefinition
OperationResult = _registry_mod.OperationResult
register_operation = _registry_mod.register_operation
get_operation = _registry_mod.get_operation
is_registered = _registry_mod.is_registered
list_operations = _registry_mod.list_operations
validate_params = _registry_mod.validate_params
execute_operation = _registry_mod.execute_operation
_registry = _registry_mod._registry
OPERATION_TIMEOUT_SECONDS = _registry_mod.OPERATION_TIMEOUT_SECONDS
OPERATION_MAX_OUTPUT_BYTES = _registry_mod.OPERATION_MAX_OUTPUT_BYTES


# =====================================================
# フィクスチャ
# =====================================================


@pytest.fixture(autouse=True)
def clear_registry():
    """各テスト前にレジストリをクリア"""
    _registry.clear()
    yield
    _registry.clear()


def _make_test_operation(
    name: str = "test_op",
    handler=None,
    risk_level: str = "low",
    requires_confirmation: bool = False,
    category: str = "read",
    params_schema=None,
) -> OperationDefinition:
    """テスト用の操作定義を生成"""
    if handler is None:
        async def _default_handler(params, organization_id, account_id):
            return OperationResult(success=True, message="OK", data={"result": "test"})
        handler = _default_handler

    return OperationDefinition(
        name=name,
        description=f"テスト操作: {name}",
        handler=handler,
        risk_level=risk_level,
        requires_confirmation=requires_confirmation,
        category=category,
        params_schema=params_schema or {},
    )


# =====================================================
# 登録・取得テスト
# =====================================================


class TestOperationRegistration:
    """操作の登録・取得"""

    def test_register_and_get(self):
        """操作を登録して取得できる"""
        op = _make_test_operation("my_op")
        register_operation(op)
        result = get_operation("my_op")
        assert result is not None
        assert result.name == "my_op"

    def test_get_unregistered_returns_none(self):
        """未登録の操作はNoneを返す"""
        assert get_operation("nonexistent") is None

    def test_is_registered(self):
        """登録済みチェック"""
        op = _make_test_operation("my_op")
        assert is_registered("my_op") is False
        register_operation(op)
        assert is_registered("my_op") is True

    def test_list_operations(self):
        """登録済み操作の一覧"""
        register_operation(_make_test_operation("op_a", category="read"))
        register_operation(_make_test_operation("op_b", category="write"))
        register_operation(_make_test_operation("op_c", category="read"))

        all_ops = list_operations()
        assert len(all_ops) == 3

        read_ops = list_operations(category="read")
        assert len(read_ops) == 2
        assert "op_a" in read_ops
        assert "op_c" in read_ops

        write_ops = list_operations(category="write")
        assert len(write_ops) == 1
        assert "op_b" in write_ops

    def test_overwrite_existing(self):
        """同名操作の上書き"""
        op1 = _make_test_operation("my_op", risk_level="low")
        op2 = _make_test_operation("my_op", risk_level="high")
        register_operation(op1)
        register_operation(op2)
        result = get_operation("my_op")
        assert result.risk_level == "high"


# =====================================================
# パラメータ検証テスト
# =====================================================


class TestParameterValidation:
    """パラメータ検証"""

    def test_validate_unregistered_operation(self):
        """未登録操作のパラメータ検証はエラー"""
        error = validate_params("nonexistent", {})
        assert error is not None
        assert "未登録" in error

    def test_validate_missing_required_param(self):
        """必須パラメータの不足"""
        op = _make_test_operation(
            params_schema={
                "query": {"type": "string", "required": True},
            }
        )
        register_operation(op)
        error = validate_params("test_op", {})
        assert error is not None
        assert "query" in error

    def test_validate_optional_param_ok(self):
        """オプションパラメータは省略OK"""
        op = _make_test_operation(
            params_schema={
                "query": {"type": "string", "required": True},
                "limit": {"type": "integer", "required": False},
            }
        )
        register_operation(op)
        error = validate_params("test_op", {"query": "test"})
        assert error is None

    def test_validate_path_traversal_blocked(self):
        """パストラバーサルの防止"""
        op = _make_test_operation(
            params_schema={
                "path": {"type": "string", "required": True},
            }
        )
        register_operation(op)

        # ".." は拒否
        error = validate_params("test_op", {"path": "../../etc/passwd"})
        assert error is not None
        assert "不正なパス" in error

        # 絶対パスは拒否
        error = validate_params("test_op", {"path": "/etc/passwd"})
        assert error is not None
        assert "不正なパス" in error

    def test_validate_param_too_long(self):
        """パラメータ長制限（200文字）"""
        op = _make_test_operation(
            params_schema={
                "query": {"type": "string", "required": True},
            }
        )
        register_operation(op)
        long_query = "a" * 201
        error = validate_params("test_op", {"query": long_query})
        assert error is not None
        assert "長すぎ" in error

    def test_validate_normal_params_pass(self):
        """正常なパラメータはパス"""
        op = _make_test_operation(
            params_schema={
                "query": {"type": "string", "required": True},
                "limit": {"type": "integer", "required": False},
            }
        )
        register_operation(op)
        error = validate_params("test_op", {"query": "売上データ", "limit": 10})
        assert error is None


# =====================================================
# 実行テスト
# =====================================================


class TestOperationExecution:
    """操作の実行"""

    @pytest.mark.asyncio
    async def test_execute_registered_operation(self):
        """登録済み操作の実行"""
        async def my_handler(params, organization_id, account_id):
            return OperationResult(
                success=True,
                message=f"集計完了: {params['query']}",
                data={"count": 42},
            )

        op = _make_test_operation(handler=my_handler, params_schema={
            "query": {"type": "string", "required": True},
        })
        register_operation(op)

        result = await execute_operation(
            name="test_op",
            params={"query": "売上"},
            organization_id="org-123",
            account_id="user-456",
        )
        assert result.success is True
        assert "集計完了" in result.message
        assert result.data["count"] == 42
        assert result.execution_time_ms >= 0

    @pytest.mark.asyncio
    async def test_execute_unregistered_operation_blocked(self):
        """未登録操作の実行はブロック"""
        result = await execute_operation(
            name="dangerous_command",
            params={},
            organization_id="org-123",
            account_id="user-456",
        )
        assert result.success is False
        assert "未登録" in result.message

    @pytest.mark.asyncio
    async def test_execute_with_invalid_params(self):
        """不正パラメータでの実行はエラー"""
        op = _make_test_operation(params_schema={
            "query": {"type": "string", "required": True},
        })
        register_operation(op)

        result = await execute_operation(
            name="test_op",
            params={},  # queryが不足
            organization_id="org-123",
            account_id="user-456",
        )
        assert result.success is False
        assert "パラメータエラー" in result.message

    @pytest.mark.asyncio
    async def test_execute_timeout(self):
        """タイムアウト（30秒制限）"""
        async def slow_handler(params, organization_id, account_id):
            await asyncio.sleep(60)  # 30秒を超える
            return OperationResult(success=True, message="完了")

        op = _make_test_operation(handler=slow_handler)
        register_operation(op)

        # タイムアウトを短くしてテスト
        original_timeout = _registry_mod.OPERATION_TIMEOUT_SECONDS
        _registry_mod.OPERATION_TIMEOUT_SECONDS = 0.1  # 0.1秒でタイムアウト

        try:
            result = await execute_operation(
                name="test_op",
                params={},
                organization_id="org-123",
                account_id="user-456",
            )
            assert result.success is False
            assert "タイムアウト" in result.message
        finally:
            _registry_mod.OPERATION_TIMEOUT_SECONDS = original_timeout

    @pytest.mark.asyncio
    async def test_execute_output_truncation(self):
        """出力サイズ制限（10KB）"""
        async def large_output_handler(params, organization_id, account_id):
            big_data = {"content": "x" * 20000}  # 10KBを超える
            return OperationResult(success=True, message="OK", data=big_data)

        op = _make_test_operation(handler=large_output_handler)
        register_operation(op)

        result = await execute_operation(
            name="test_op",
            params={},
            organization_id="org-123",
            account_id="user-456",
        )
        assert result.success is True
        assert result.truncated is True

    @pytest.mark.asyncio
    async def test_execute_handler_exception(self):
        """ハンドラーの例外は安全にキャッチ"""
        async def broken_handler(params, organization_id, account_id):
            raise RuntimeError("Something went wrong")

        op = _make_test_operation(handler=broken_handler)
        register_operation(op)

        result = await execute_operation(
            name="test_op",
            params={},
            organization_id="org-123",
            account_id="user-456",
        )
        assert result.success is False
        assert "エラー" in result.message

    @pytest.mark.asyncio
    async def test_execute_dict_result_normalized(self):
        """dict戻り値がOperationResultに正規化される"""
        async def dict_handler(params, organization_id, account_id):
            return {"success": True, "message": "OK", "data": {"x": 1}}

        op = _make_test_operation(handler=dict_handler)
        register_operation(op)

        result = await execute_operation(
            name="test_op",
            params={},
            organization_id="org-123",
            account_id="user-456",
        )
        assert result.success is True
        assert result.message == "OK"

    @pytest.mark.asyncio
    async def test_execute_string_result_normalized(self):
        """str戻り値がOperationResultに正規化される"""
        async def str_handler(params, organization_id, account_id):
            return "処理完了しました"

        op = _make_test_operation(handler=str_handler)
        register_operation(op)

        result = await execute_operation(
            name="test_op",
            params={},
            organization_id="org-123",
            account_id="user-456",
        )
        assert result.success is True
        assert result.message == "処理完了しました"


# =====================================================
# SYSTEM_CAPABILITIES統合テスト
# =====================================================


class TestSystemCapabilitiesIntegration:
    """SYSTEM_CAPABILITIESとの統合"""

    def test_operation_capabilities_defined(self):
        """OPERATION_CAPABILITIESが定義されている"""
        caps = _registry_mod.OPERATION_CAPABILITIES
        assert "data_aggregate" in caps
        assert "data_search" in caps

    def test_operation_in_system_capabilities(self):
        """操作がSYSTEM_CAPABILITIESに登録されている"""
        from handlers.registry import SYSTEM_CAPABILITIES
        assert "data_aggregate" in SYSTEM_CAPABILITIES
        assert "data_search" in SYSTEM_CAPABILITIES

    def test_operation_risk_levels_defined(self):
        """RISK_LEVELSに操作が定義されている"""
        constants_mod = importlib.import_module("lib.brain.constants")
        risk_levels = constants_mod.RISK_LEVELS
        assert "data_aggregate" in risk_levels
        assert risk_levels["data_aggregate"] == "low"
        assert "data_search" in risk_levels
        assert risk_levels["data_search"] == "low"

    def test_operation_capabilities_format(self):
        """SYSTEM_CAPABILITIESの操作が正しいフォーマット"""
        from handlers.registry import SYSTEM_CAPABILITIES
        for op_name in ["data_aggregate", "data_search"]:
            cap = SYSTEM_CAPABILITIES[op_name]
            assert "name" in cap
            assert "description" in cap
            assert "category" in cap
            assert cap["category"] == "operations"
            assert "params_schema" in cap
            assert "handler" in cap
            assert "brain_metadata" in cap
            assert "risk_level" in cap["brain_metadata"]
            assert cap["brain_metadata"]["risk_level"] == "low"


# =====================================================
# データ操作ハンドラーテスト
# =====================================================


class TestDataOpsHandlers:
    """データ操作ハンドラーの個別テスト"""

    @pytest.mark.asyncio
    async def test_data_aggregate_handler(self):
        """データ集計ハンドラーのスタブ応答"""
        data_ops_mod = importlib.import_module("lib.brain.operations.data_ops")
        handle_data_aggregate = data_ops_mod.handle_data_aggregate
        result = await handle_data_aggregate(
            params={"data_source": "sales", "operation": "sum", "filters": "先月"},
            organization_id="org-123",
            account_id="user-456",
        )
        assert result.success is True
        assert "sales" in result.message
        assert result.data["status"] == "stub"

    @pytest.mark.asyncio
    async def test_data_search_handler(self):
        """データ検索ハンドラーのスタブ応答"""
        data_ops_mod = importlib.import_module("lib.brain.operations.data_ops")
        handle_data_search = data_ops_mod.handle_data_search
        result = await handle_data_search(
            params={"data_source": "projects", "query": "未完了の案件"},
            organization_id="org-123",
            account_id="user-456",
        )
        assert result.success is True
        assert "projects" in result.message
        assert result.data["status"] == "stub"
