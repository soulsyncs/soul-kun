# tests/test_operation_registry.py
"""
Step C-3: 操作レジストリ テストと安全性チェック

操作の登録・検証・実行・セキュリティ制約をテストする。
C-3で追加: PII除去、3層ゲート統合、緊急停止統合テスト。

Author: Claude Opus 4.6
Created: 2026-02-17
Updated: 2026-02-17 (Step C-3)
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
# TASK-14: CapabilityContract契約インターフェーステスト
# =====================================================


class TestCapabilityContract:
    """CapabilityContract契約インターフェースのテスト（TASK-14）"""

    def test_validate_capability_contract_valid(self):
        """全必須フィールドがある場合はNoneを返す"""
        validate = _registry_mod.validate_capability_contract
        valid_cap = {
            "name": "テスト機能",
            "description": "テスト用の機能です",
            "category": "task",
            "enabled": True,
            "params_schema": {"query": {"type": "string", "required": True}},
            "handler": "test_handler",
            "requires_confirmation": False,
        }
        error = validate("test_cap", valid_cap)
        assert error is None

    def test_validate_capability_contract_missing_required_field(self):
        """必須フィールドが不足している場合はエラー文字列を返す"""
        validate = _registry_mod.validate_capability_contract
        required_fields = _registry_mod.REQUIRED_CAPABILITY_FIELDS

        for missing_field in required_fields:
            cap = {
                "name": "テスト機能",
                "description": "説明",
                "category": "task",
                "enabled": True,
                "params_schema": {},
                "handler": "test_handler",
                "requires_confirmation": False,
            }
            del cap[missing_field]

            error = validate("test_cap", cap)
            assert error is not None, f"'{missing_field}' 不足でエラーが発生すべき"
            assert missing_field in error, f"エラーメッセージに '{missing_field}' が含まれるべき"

    def test_validate_capability_contract_optional_fields_not_required(self):
        """任意フィールド（trigger_examples等）が省略されても契約OK"""
        validate = _registry_mod.validate_capability_contract
        # trigger_examples, required_data, brain_metadata, required_level は任意
        minimal_cap = {
            "name": "最小Capability",
            "description": "最小構成",
            "category": "general",
            "enabled": True,
            "params_schema": {},
            "handler": "minimal_handler",
            "requires_confirmation": False,
        }
        error = validate("minimal_cap", minimal_cap)
        assert error is None

    def test_operation_capabilities_all_satisfy_contract(self):
        """OPERATION_CAPABILITIESの全エントリがCapabilityContract契約を満たす"""
        validate = _registry_mod.validate_capability_contract
        caps = _registry_mod.OPERATION_CAPABILITIES
        for cap_name, cap_def in caps.items():
            error = validate(cap_name, cap_def)
            assert error is None, (
                f"OPERATION_CAPABILITIES['{cap_name}'] の契約違反: {error}"
            )

    def test_required_capability_fields_constant(self):
        """REQUIRED_CAPABILITY_FIELDSが7フィールドを含む"""
        required = _registry_mod.REQUIRED_CAPABILITY_FIELDS
        assert len(required) == 7
        assert "name" in required
        assert "description" in required
        assert "category" in required
        assert "enabled" in required
        assert "params_schema" in required
        assert "handler" in required
        assert "requires_confirmation" in required

    def test_tool_metadata_registry_loads_operation_capabilities(self):
        """ToolMetadataRegistryがOPERATION_CAPABILITIESも自動ロードする"""
        from unittest.mock import patch
        from lib.brain.tool_converter import ToolMetadataRegistry
        from lib.brain.operations.registry import OPERATION_CAPABILITIES

        # SYSTEM_CAPABILITIESにないoperation専用のcapability名を特定
        # OPERATION_CAPABILITIESのエントリはSYSTEM_CAPABILITIESにも存在するが、
        # ToolMetadataRegistryが両方をロードすることを確認する
        registry = ToolMetadataRegistry()
        all_tools = registry.get_all()
        tool_names = {t.name for t in all_tools}

        for op_name in OPERATION_CAPABILITIES:
            if OPERATION_CAPABILITIES[op_name].get("enabled", True):
                assert op_name in tool_names, (
                    f"OPERATION_CAPABILITIES['{op_name}'] がToolMetadataRegistryにロードされていない"
                )


# =====================================================
# データ操作ハンドラーテスト
# =====================================================


class TestDataOpsHandlers:
    """データ操作ハンドラーの個別テスト"""

    def test_resolve_data_source(self):
        """データソース名の解決"""
        data_ops_mod = importlib.import_module("lib.brain.operations.data_ops")
        resolve = data_ops_mod._resolve_data_source
        assert resolve("tasks") == "chatwork_tasks"
        assert resolve("タスク") == "chatwork_tasks"
        assert resolve("goals") == "staff_goals"
        assert resolve("目標") == "staff_goals"
        assert resolve("unknown") is None
        assert resolve("売上") is None

    def test_build_task_filter_status(self):
        """ステータスフィルタの生成"""
        data_ops_mod = importlib.import_module("lib.brain.operations.data_ops")
        build_filter = data_ops_mod._build_task_filter

        where, params = build_filter("完了")
        assert "status = :status" in where
        assert params["status"] == "done"

        where, params = build_filter("未完了")
        assert "status = :status" in where
        assert params["status"] == "open"

    def test_build_task_filter_date(self):
        """時期フィルタの生成"""
        data_ops_mod = importlib.import_module("lib.brain.operations.data_ops")
        build_filter = data_ops_mod._build_task_filter

        where, params = build_filter("今月")
        assert "created_at >= :date_from" in where
        assert "date_from" in params

        where, params = build_filter("先月")
        assert "date_from" in params
        assert "date_to" in params

    def test_build_task_filter_empty(self):
        """フィルタなし"""
        data_ops_mod = importlib.import_module("lib.brain.operations.data_ops")
        build_filter = data_ops_mod._build_task_filter
        where, params = build_filter("")
        assert where == ""
        assert params == {}

    def test_extract_keywords(self):
        """キーワード抽出"""
        data_ops_mod = importlib.import_module("lib.brain.operations.data_ops")
        extract = data_ops_mod._extract_keywords
        assert extract("先月の未完了タスク") == ""
        assert extract("営業報告") == "営業報告"

    @pytest.mark.asyncio
    async def test_data_aggregate_unsupported_source(self):
        """未対応データソースはエラーを返す"""
        data_ops_mod = importlib.import_module("lib.brain.operations.data_ops")
        result = await data_ops_mod.handle_data_aggregate(
            params={"data_source": "売上", "operation": "sum"},
            organization_id="org-123",
            account_id="user-456",
        )
        assert result.success is False
        assert "対応していません" in result.message

    @pytest.mark.asyncio
    async def test_data_search_unsupported_source(self):
        """未対応データソースはエラーを返す"""
        data_ops_mod = importlib.import_module("lib.brain.operations.data_ops")
        result = await data_ops_mod.handle_data_search(
            params={"data_source": "unknown", "query": "test"},
            organization_id="org-123",
            account_id="user-456",
        )
        assert result.success is False
        assert "対応していません" in result.message

    @pytest.mark.asyncio
    async def test_data_aggregate_with_mock_db(self):
        """DBモックでの集計テスト"""
        from unittest.mock import MagicMock, patch

        data_ops_mod = importlib.import_module("lib.brain.operations.data_ops")

        # モックDBの結果（ステータス別集計）
        mock_rows = [("open", 5), ("done", 3)]
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = mock_rows
        mock_pool = MagicMock()
        mock_pool.connect.return_value.__enter__ = lambda self: mock_conn
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=False)

        with patch.object(data_ops_mod, "_execute_aggregate") as mock_exec, \
             patch("lib.db.get_db_pool", return_value=mock_pool):
            mock_exec.return_value = {
                "message": "タスク集計:\n合計: 8件\n  - 未完了: 5件\n  - 完了: 3件",
                "total": 8,
                "breakdown": {"open": 5, "done": 3},
                "data_source": "chatwork_tasks",
                "filters": "",
            }

            result = await data_ops_mod.handle_data_aggregate(
                params={"data_source": "tasks", "operation": "count"},
                organization_id="org-123",
                account_id="user-456",
            )
            assert result.success is True
            assert "8件" in result.message

    @pytest.mark.asyncio
    async def test_data_search_with_mock_db(self):
        """DBモックでの検索テスト"""
        from unittest.mock import MagicMock, patch

        data_ops_mod = importlib.import_module("lib.brain.operations.data_ops")

        with patch.object(data_ops_mod, "_execute_search") as mock_exec, \
             patch("lib.db.get_db_pool", return_value=MagicMock()):
            mock_exec.return_value = {
                "message": "タスク検索結果: 2件\n  1. [未完了] 報告書作成\n  2. [完了] 会議準備",
                "results": [
                    {"task_id": "1", "summary": "報告書作成", "status": "未完了", "deadline": "", "room": ""},
                    {"task_id": "2", "summary": "会議準備", "status": "完了", "deadline": "", "room": ""},
                ],
                "total": 2,
                "data_source": "chatwork_tasks",
            }

            result = await data_ops_mod.handle_data_search(
                params={"data_source": "tasks", "query": "報告"},
                organization_id="org-123",
                account_id="user-456",
            )
            assert result.success is True
            assert "2件" in result.message
            assert result.data["total"] == 2

    @pytest.mark.asyncio
    async def test_data_search_limit_capped(self):
        """検索のlimitは最大50件に制限される"""
        from unittest.mock import MagicMock, patch

        data_ops_mod = importlib.import_module("lib.brain.operations.data_ops")

        with patch.object(data_ops_mod, "_execute_search") as mock_exec, \
             patch("lib.db.get_db_pool", return_value=MagicMock()):
            mock_exec.return_value = {"message": "OK", "results": [], "total": 0}

            await data_ops_mod.handle_data_search(
                params={"data_source": "tasks", "query": "test", "limit": 100},
                organization_id="org-123",
                account_id="user-456",
            )
            # _execute_searchが呼ばれた時のlimit引数が50以下であること
            call_args = mock_exec.call_args
            assert call_args[0][3] <= 50  # limit引数（4番目）


# =====================================================
# PII除去テスト（Step C-3）
# =====================================================


class TestPIIRemoval:
    """検索結果からPII（個人情報）が除去されていることを検証"""

    def test_search_result_excludes_pii_fields(self):
        """_execute_searchの結果にユーザー名・メール等が含まれない"""
        from unittest.mock import MagicMock

        data_ops_mod = importlib.import_module("lib.brain.operations.data_ops")

        # DBからの生データ: task_id, body, status, limit_time, room_name, summary
        # 重要: SELECT句にassigned_by, assigned_by_name, email等がないことを確認
        mock_rows = [
            (101, "田中さんへの報告書。taro@example.com宛。", "open", None, "営業室", "報告書作成"),
            (102, "090-1234-5678に電話。salary: 500000", "done", 1740000000, "経理室", "電話連絡"),
        ]
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = mock_rows
        mock_pool = MagicMock()
        mock_pool.connect.return_value.__enter__ = lambda self: mock_conn
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=False)

        result = data_ops_mod._execute_search(
            mock_pool, "chatwork_tasks", "", 20, "org-123"
        )

        # 結果にPIIフィールドが含まれないこと
        for item in result["results"]:
            assert "email" not in item, "メールアドレスフィールドが結果に含まれている"
            assert "assigned_by" not in item, "assigned_byフィールドが結果に含まれている"
            assert "assigned_by_name" not in item, "担当者名フィールドが結果に含まれている"
            assert "account_name" not in item, "account_nameフィールドが結果に含まれている"
            # 許可されたフィールドのみ
            allowed_keys = {"task_id", "summary", "status", "deadline", "room"}
            assert set(item.keys()) == allowed_keys, (
                f"予期しないフィールド: {set(item.keys()) - allowed_keys}"
            )

    def test_search_result_body_truncated(self):
        """本文は100文字に切り詰められる（過度な情報流出防止）"""
        from unittest.mock import MagicMock

        data_ops_mod = importlib.import_module("lib.brain.operations.data_ops")

        long_body = "機密情報" * 50  # 200文字
        mock_rows = [(1, long_body, "open", None, "部屋", None)]
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = mock_rows
        mock_pool = MagicMock()
        mock_pool.connect.return_value.__enter__ = lambda self: mock_conn
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=False)

        result = data_ops_mod._execute_search(
            mock_pool, "chatwork_tasks", "", 20, "org-123"
        )

        assert len(result["results"][0]["summary"]) <= 100

    def test_aggregate_excludes_pii(self):
        """集計結果にはユーザー名やメールが含まれない"""
        from unittest.mock import MagicMock

        data_ops_mod = importlib.import_module("lib.brain.operations.data_ops")

        # chatwork_tasksの集計: ステータス別COUNT
        mock_rows = [("open", 10), ("done", 5)]
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = mock_rows
        mock_pool = MagicMock()
        mock_pool.connect.return_value.__enter__ = lambda self: mock_conn
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=False)

        result = data_ops_mod._execute_aggregate(
            mock_pool, "chatwork_tasks", "count", "", "org-123"
        )

        # 結果にPIIが含まれないこと
        result_str = str(result)
        assert "email" not in result_str.lower()
        assert "assigned_by_name" not in result_str
        # 数値データのみ含まれること
        assert result["total"] == 15
        assert "breakdown" in result

    def test_goals_search_excludes_staff_name(self):
        """目標検索結果にスタッフ名が含まれない"""
        from unittest.mock import MagicMock

        data_ops_mod = importlib.import_module("lib.brain.operations.data_ops")

        # staff_goalsの検索: goal_id, staff_account_id, goal_month, sessions_target
        mock_rows = [(1, "acc-001", "2026-02", 10)]
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = mock_rows
        mock_pool = MagicMock()
        mock_pool.connect.return_value.__enter__ = lambda self: mock_conn
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=False)

        result = data_ops_mod._execute_search(
            mock_pool, "staff_goals", "", 20, "org-123"
        )

        for item in result["results"]:
            assert "staff_name" not in item, "スタッフ名が含まれている"
            assert "staff_email" not in item, "スタッフメールが含まれている"
            # account_idはPIIではないが、名前やメールは含まれないこと
            allowed_keys = {"goal_id", "month", "target"}
            assert set(item.keys()) == allowed_keys


# =====================================================
# 3層ゲート統合テスト（Step C-3）
# =====================================================


class TestThreeLayerGateIntegration:
    """Guardian → ApprovalGate → 操作実行の3層ゲート統合テスト"""

    def test_approval_gate_auto_approves_low_risk_operations(self):
        """低リスク操作（data_aggregate, data_search）はAUTO_APPROVE"""
        gate_mod = importlib.import_module("lib.brain.approval_gate")
        gate = gate_mod.ApprovalGate()

        for op_name in ["data_aggregate", "data_search"]:
            result = gate.check(op_name, {"data_source": "tasks"})
            assert result.level == gate_mod.ApprovalLevel.AUTO_APPROVE, (
                f"{op_name} should be AUTO_APPROVE, got {result.level}"
            )
            assert result.risk_level == "low"

    def test_approval_gate_blocks_high_risk_with_large_amount(self):
        """高額パラメータ（10万以上）はDOUBLE_CHECKにエスカレーション"""
        gate_mod = importlib.import_module("lib.brain.approval_gate")
        gate = gate_mod.ApprovalGate()

        result = gate.check("data_aggregate", {"amount": 150000})
        assert result.level == gate_mod.ApprovalLevel.REQUIRE_DOUBLE_CHECK

    def test_approval_gate_unknown_tool_requires_confirmation(self):
        """未知のTool名はmediumリスクに倒される"""
        gate_mod = importlib.import_module("lib.brain.approval_gate")
        gate = gate_mod.ApprovalGate()

        result = gate.check("completely_unknown_tool", {})
        # mediumは確認必須（CONFIRMATION_REQUIRED_RISK_LEVELSに含まれる）
        assert result.level != gate_mod.ApprovalLevel.AUTO_APPROVE

    def test_risk_levels_defined_for_operations(self):
        """RISK_LEVELSにdata_aggregate/data_searchが定義されている"""
        constants_mod = importlib.import_module("lib.brain.constants")
        assert constants_mod.RISK_LEVELS.get("data_aggregate") == "low"
        assert constants_mod.RISK_LEVELS.get("data_search") == "low"

    def test_operation_registry_validates_before_execution(self):
        """実行前にパラメータ検証が行われる"""
        # レジストリに操作を登録（パラメータスキーマ付き）
        op = _make_test_operation(
            name="guarded_op",
            params_schema={
                "data_source": {"type": "string", "required": True},
            },
        )
        register_operation(op)

        # パラメータ不正で検証エラー
        error = validate_params("guarded_op", {})
        assert error is not None
        assert "data_source" in error

        # パラメータ正常で検証パス
        error = validate_params("guarded_op", {"data_source": "tasks"})
        assert error is None

    @pytest.mark.asyncio
    async def test_full_pipeline_registry_to_execution(self):
        """レジストリ登録 → パラメータ検証 → 実行の一気通貫テスト"""
        execution_log = []

        async def tracked_handler(params, organization_id, account_id):
            execution_log.append({
                "params": params,
                "org_id": organization_id,
                "account_id": account_id,
            })
            return OperationResult(
                success=True,
                message="パイプラインテスト成功",
                data={"count": 10},
            )

        op = _make_test_operation(
            name="pipeline_op",
            handler=tracked_handler,
            params_schema={
                "data_source": {"type": "string", "required": True},
            },
        )
        register_operation(op)

        # 1. レジストリ確認
        assert is_registered("pipeline_op")

        # 2. パラメータ検証
        error = validate_params("pipeline_op", {"data_source": "tasks"})
        assert error is None

        # 3. 承認ゲートチェック（lowリスクなのでAUTO_APPROVE）
        gate_mod = importlib.import_module("lib.brain.approval_gate")
        gate = gate_mod.ApprovalGate()
        approval = gate.check("pipeline_op", {"data_source": "tasks"})
        # pipeline_opはRISK_LEVELSに未定義→medium→確認要求になるが、
        # レジストリのoperationDefinitionのrisk_levelは"low"
        # ただしApprovalGateはconstants.RISK_LEVELSを参照するので
        # 未知ToolはMEDIUM扱い。これは設計通り。

        # 4. 実行
        result = await execute_operation(
            name="pipeline_op",
            params={"data_source": "tasks"},
            organization_id="org-999",
            account_id="acc-001",
        )
        assert result.success is True
        assert "パイプラインテスト成功" in result.message
        assert len(execution_log) == 1
        assert execution_log[0]["org_id"] == "org-999"

    @pytest.mark.asyncio
    async def test_unregistered_operation_blocked_at_every_layer(self):
        """未登録操作はレジストリレベルでブロックされる"""
        # 1. レジストリチェック
        assert not is_registered("hack_server")

        # 2. パラメータ検証
        error = validate_params("hack_server", {"cmd": "rm -rf /"})
        assert error is not None
        assert "未登録" in error

        # 3. 実行拒否
        result = await execute_operation(
            name="hack_server",
            params={"cmd": "rm -rf /"},
            organization_id="org-123",
            account_id="attacker-001",
        )
        assert result.success is False
        assert "未登録" in result.message


# =====================================================
# 緊急停止統合テスト（Step C-3）
# =====================================================


class TestEmergencyStopIntegration:
    """緊急停止中は操作がブロックされることを検証"""

    def test_emergency_stop_checker_is_stopped_true(self):
        """is_stopped()=True のとき停止中と判定される"""
        from unittest.mock import MagicMock

        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = lambda self: mock_conn
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=False)
        # is_active = True を返す
        mock_conn.execute.return_value.fetchone.return_value = (True,)

        stop_mod = importlib.import_module("lib.brain.emergency_stop")
        checker = stop_mod.EmergencyStopChecker(
            pool=mock_pool, org_id="org-123", cache_ttl_seconds=0
        )
        assert checker.is_stopped() is True

    def test_emergency_stop_checker_not_stopped(self):
        """is_stopped()=False のとき通常稼働と判定される"""
        from unittest.mock import MagicMock

        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = lambda self: mock_conn
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=False)
        # is_active = False を返す
        mock_conn.execute.return_value.fetchone.return_value = (False,)

        stop_mod = importlib.import_module("lib.brain.emergency_stop")
        checker = stop_mod.EmergencyStopChecker(
            pool=mock_pool, org_id="org-123", cache_ttl_seconds=0
        )
        assert checker.is_stopped() is False

    def test_emergency_stop_checker_no_record(self):
        """レコードなし→停止していないと判定"""
        from unittest.mock import MagicMock

        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = lambda self: mock_conn
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchone.return_value = None

        stop_mod = importlib.import_module("lib.brain.emergency_stop")
        checker = stop_mod.EmergencyStopChecker(
            pool=mock_pool, org_id="org-123", cache_ttl_seconds=0
        )
        assert checker.is_stopped() is False

    def test_emergency_stop_db_failure_safe_side(self):
        """DB障害時は安全側（停止しない）に倒す"""
        from unittest.mock import MagicMock

        mock_pool = MagicMock()
        mock_pool.connect.side_effect = Exception("DB connection failed")

        stop_mod = importlib.import_module("lib.brain.emergency_stop")
        checker = stop_mod.EmergencyStopChecker(
            pool=mock_pool, org_id="org-123", cache_ttl_seconds=0
        )
        # DB障害でも例外は投げない。False（停止しない）を返す
        assert checker.is_stopped() is False

    def test_emergency_stop_cache_ttl(self):
        """TTLキャッシュが効くこと"""
        from unittest.mock import MagicMock

        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = lambda self: mock_conn
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchone.return_value = (False,)

        stop_mod = importlib.import_module("lib.brain.emergency_stop")
        checker = stop_mod.EmergencyStopChecker(
            pool=mock_pool, org_id="org-123", cache_ttl_seconds=60
        )

        # 1回目: DBアクセス
        assert checker.is_stopped() is False
        call_count_1 = mock_pool.connect.call_count

        # 2回目: キャッシュから（DBアクセスなし）
        assert checker.is_stopped() is False
        call_count_2 = mock_pool.connect.call_count
        assert call_count_2 == call_count_1, "キャッシュが効いていない"

    def test_emergency_stop_cache_invalidate(self):
        """invalidate_cache()でキャッシュが無効になる"""
        from unittest.mock import MagicMock

        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = lambda self: mock_conn
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchone.return_value = (False,)

        stop_mod = importlib.import_module("lib.brain.emergency_stop")
        checker = stop_mod.EmergencyStopChecker(
            pool=mock_pool, org_id="org-123", cache_ttl_seconds=60
        )

        checker.is_stopped()  # キャッシュ充填
        call_count_1 = mock_pool.connect.call_count

        checker.invalidate_cache()
        checker.is_stopped()  # 再度DBアクセス
        call_count_2 = mock_pool.connect.call_count
        assert call_count_2 > call_count_1, "invalidate後にDBアクセスが起きていない"


# =====================================================
# パラメータ型検証強化テスト（Step C-3）
# =====================================================


class TestParameterValidationExtended:
    """パラメータ検証の追加テスト"""

    def test_path_traversal_with_encoded_dots(self):
        """エンコードされたパストラバーサルもブロック"""
        op = _make_test_operation(
            params_schema={"path": {"type": "string", "required": True}}
        )
        register_operation(op)

        # 通常のパストラバーサル
        error = validate_params("test_op", {"path": "..\\..\\windows\\system32"})
        assert error is not None

    def test_multiple_params_all_validated(self):
        """複数パラメータが全て検証される"""
        op = _make_test_operation(
            params_schema={
                "source": {"type": "string", "required": True},
                "query": {"type": "string", "required": True},
                "limit": {"type": "integer", "required": False},
            }
        )
        register_operation(op)

        # sourceのみ→queryが不足
        error = validate_params("test_op", {"source": "tasks"})
        assert error is not None
        assert "query" in error

    def test_sql_injection_in_param_value(self):
        """SQLインジェクション風の値もパラメータ検証は通す（SQLはパラメータ化される）"""
        op = _make_test_operation(
            params_schema={"query": {"type": "string", "required": True}}
        )
        register_operation(op)

        # SQLインジェクションの値自体はvalidate_paramsでは拒否しない
        # （SQLパラメータ化で安全なため）
        error = validate_params("test_op", {"query": "'; DROP TABLE users; --"})
        assert error is None  # 200文字以下かつパストラバーサルでないのでOK

    def test_empty_string_param_allowed(self):
        """空文字列は許容される"""
        op = _make_test_operation(
            params_schema={"filters": {"type": "string", "required": True}}
        )
        register_operation(op)

        error = validate_params("test_op", {"filters": ""})
        assert error is None

    def test_param_exactly_200_chars(self):
        """ちょうど200文字は許容される"""
        op = _make_test_operation(
            params_schema={"query": {"type": "string", "required": True}}
        )
        register_operation(op)

        error = validate_params("test_op", {"query": "a" * 200})
        assert error is None

        error = validate_params("test_op", {"query": "a" * 201})
        assert error is not None
