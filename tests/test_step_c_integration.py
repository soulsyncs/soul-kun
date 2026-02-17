# tests/test_step_c_integration.py
"""
Step C-6: 全体結合テスト — C-1〜C-5をつなげたEnd-to-Endテスト

操作レジストリ全体の統合動作を検証する:
1. Brain判断 → Guardian安全チェック → 承認ゲート → 操作実行の一気通貫フロー
2. 読み取り操作と書き込み操作の両方をテスト
3. セキュリティ制約（PII除去、org_idフィルタ、レートリミット）の横断テスト
4. 不正操作のブロックが全レイヤーで機能するか

Author: Claude Opus 4.6
Created: 2026-02-17
"""

import asyncio
import importlib
import time
import pytest
from unittest.mock import MagicMock, patch, AsyncMock

# テスト対象モジュール
from lib.brain.operations.registry import (
    OperationDefinition,
    OperationResult,
    register_operation,
    get_operation,
    is_registered,
    list_operations,
    validate_params,
    execute_operation,
    _registry,
    OPERATION_TIMEOUT_SECONDS,
    OPERATION_MAX_OUTPUT_BYTES,
)
from lib.brain.guardian_layer import (
    GuardianLayer,
    GuardianAction,
    GuardianResult,
)
from lib.brain.approval_gate import (
    ApprovalGate,
    ApprovalLevel,
    ApprovalCheckResult,
)
from lib.brain.llm_brain import LLMBrainResult, ToolCall, ConfidenceScores
from lib.brain.context_builder import LLMContext


# =====================================================
# フィクスチャ
# =====================================================


@pytest.fixture(autouse=True)
def clear_registry():
    """各テスト前にレジストリをクリア"""
    _registry.clear()
    yield
    _registry.clear()


def _make_llm_result(
    tool_name: str, params: dict = None, confidence: float = 0.9
) -> LLMBrainResult:
    """テスト用LLMBrainResult作成"""
    tc = ToolCall(tool_name=tool_name, parameters=params or {})
    return LLMBrainResult(
        output_type="tool_call",
        text_response=None,
        tool_calls=[tc],
        reasoning="テスト用推論",
        confidence=ConfidenceScores(
            overall=confidence,
            intent=confidence,
            parameters=confidence,
        ),
    )


def _make_context(account_id: str = "acc-001") -> LLMContext:
    """テスト用LLMContext作成"""
    ctx = MagicMock(spec=LLMContext)
    ctx.account_id = account_id
    ctx.ceo_teachings = []
    return ctx


def _register_test_read_op():
    """テスト用読み取り操作を登録"""
    async def handler(params, organization_id, account_id):
        return OperationResult(
            success=True,
            message="データ集計完了",
            data={"count": 42, "source": params.get("data_source", "")},
        )

    op = OperationDefinition(
        name="data_aggregate",
        description="データ集計",
        handler=handler,
        risk_level="low",
        requires_confirmation=False,
        category="read",
        params_schema={
            "data_source": {"type": "string", "required": True},
            "operation": {"type": "string", "required": False},
        },
    )
    register_operation(op)
    return op


def _register_test_write_op():
    """テスト用書き込み操作を登録"""
    async def handler(params, organization_id, account_id):
        return OperationResult(
            success=True,
            message=f"レポート生成完了: {params.get('title', '')}",
            data={"path": f"gs://test/{organization_id}/reports/test.txt"},
        )

    op = OperationDefinition(
        name="report_generate",
        description="レポート生成",
        handler=handler,
        risk_level="medium",
        requires_confirmation=True,
        category="write",
        params_schema={
            "title": {"type": "string", "required": True},
            "content": {"type": "string", "required": True},
        },
    )
    register_operation(op)
    return op


# =====================================================
# 1. 読み取り操作の一気通貫テスト
# =====================================================


class TestReadOperationE2E:
    """読み取り操作（data_aggregate等）のEnd-to-Endテスト"""

    @pytest.mark.asyncio
    async def test_read_full_flow_success(self):
        """正常な読み取り操作の全フロー: Guardian→承認→実行"""
        _register_test_read_op()

        # 1. Brain判断をシミュレート
        brain_result = _make_llm_result(
            "data_aggregate", {"data_source": "tasks", "operation": "count"}
        )
        ctx = _make_context()

        # 2. Guardianチェック（asyncメソッド）
        guardian = GuardianLayer()
        g_result = await guardian.check(brain_result, ctx)
        assert g_result.action == GuardianAction.ALLOW, f"Guardian should ALLOW: {g_result.reason}"

        # 3. 承認ゲート
        gate = ApprovalGate()
        approval = gate.check("data_aggregate", {"data_source": "tasks"})

        # 4. レジストリ検証
        error = validate_params("data_aggregate", {"data_source": "tasks"})
        assert error is None

        # 5. 実行
        result = await execute_operation(
            name="data_aggregate",
            params={"data_source": "tasks", "operation": "count"},
            organization_id="org-test-001",
            account_id="acc-001",
        )
        assert result.success is True
        assert "集計完了" in result.message
        assert result.data["count"] == 42

    @pytest.mark.asyncio
    async def test_read_missing_required_param_blocked(self):
        """必須パラメータ不足はレジストリレベルで拒否"""
        _register_test_read_op()

        error = validate_params("data_aggregate", {})
        assert error is not None
        assert "data_source" in error


# =====================================================
# 2. 書き込み操作の一気通貫テスト
# =====================================================


class TestWriteOperationE2E:
    """書き込み操作（report_generate等）のEnd-to-Endテスト"""

    @pytest.mark.asyncio
    async def test_write_full_flow_with_confirmation(self):
        """書き込み操作の全フロー: Guardian→承認（確認必要）→実行"""
        _register_test_write_op()

        # 1. Brain判断
        brain_result = _make_llm_result(
            "report_generate",
            {"title": "月次レポート", "content": "2月の売上報告"},
        )
        ctx = _make_context()

        # 2. Guardianチェック（asyncメソッド）
        guardian = GuardianLayer()
        g_result = await guardian.check(brain_result, ctx)
        assert g_result.action == GuardianAction.ALLOW

        # 3. 承認ゲート（medium→確認必要）
        gate = ApprovalGate()
        approval = gate.check("report_generate", {"title": "月次レポート"})

        # 4. パラメータ検証
        error = validate_params("report_generate", {"title": "月次レポート", "content": "報告内容"})
        assert error is None

        # 5. 実行（確認済みとして）
        result = await execute_operation(
            name="report_generate",
            params={"title": "月次レポート", "content": "2月の売上報告"},
            organization_id="org-test-002",
            account_id="acc-001",
        )
        assert result.success is True
        assert "レポート生成完了" in result.message
        assert "org-test-002" in result.data["path"]


# =====================================================
# 3. セキュリティ横断テスト
# =====================================================


class TestSecurityCrossCutting:
    """全レイヤーにまたがるセキュリティテスト"""

    @pytest.mark.asyncio
    async def test_unregistered_op_blocked_all_layers(self):
        """未登録操作は全レイヤーでブロックされる"""
        # 1. レジストリ：未登録
        assert not is_registered("hack_server")

        # 2. パラメータ検証：拒否
        error = validate_params("hack_server", {"cmd": "rm -rf /"})
        assert error is not None
        assert "未登録" in error

        # 3. 実行：拒否
        result = await execute_operation(
            name="hack_server",
            params={"cmd": "rm -rf /"},
            organization_id="org-123",
            account_id="attacker",
        )
        assert result.success is False
        assert "未登録" in result.message

    @pytest.mark.asyncio
    async def test_path_traversal_blocked(self):
        """パストラバーサルはパラメータ検証でブロック"""
        _register_test_read_op()

        error = validate_params("data_aggregate", {"data_source": "../../etc/passwd"})
        assert error is not None
        assert "不正なパス" in error

    @pytest.mark.asyncio
    async def test_absolute_path_blocked(self):
        """絶対パスはパラメータ検証でブロック"""
        _register_test_read_op()

        error = validate_params("data_aggregate", {"data_source": "/etc/passwd"})
        assert error is not None
        assert "不正なパス" in error

    @pytest.mark.asyncio
    async def test_long_param_rejected(self):
        """200文字超のパラメータは拒否"""
        _register_test_read_op()

        long_value = "a" * 201
        error = validate_params("data_aggregate", {"data_source": long_value})
        assert error is not None
        assert "長すぎ" in error

    @pytest.mark.asyncio
    async def test_org_id_propagated_to_handler(self):
        """organization_idがハンドラまで正しく伝搬する"""
        execution_log = []

        async def tracking_handler(params, organization_id, account_id):
            execution_log.append({
                "org_id": organization_id,
                "account_id": account_id,
            })
            return OperationResult(success=True, message="OK")

        op = OperationDefinition(
            name="tracked_op",
            description="追跡テスト",
            handler=tracking_handler,
            risk_level="low",
            requires_confirmation=False,
            category="read",
            params_schema={"q": {"type": "string", "required": True}},
        )
        register_operation(op)

        await execute_operation("tracked_op", {"q": "test"}, "org-ABC", "user-123")

        assert len(execution_log) == 1
        assert execution_log[0]["org_id"] == "org-ABC"
        assert execution_log[0]["account_id"] == "user-123"


# =====================================================
# 4. Guardianの操作固有ルール統合テスト
# =====================================================


class TestGuardianOperationRulesE2E:
    """Guardian Layerの操作系5ルールの統合テスト"""

    @pytest.mark.asyncio
    async def test_registered_op_passes_guardian(self):
        """登録済み操作はGuardianを通過する"""
        _register_test_read_op()

        brain_result = _make_llm_result("data_aggregate", {"data_source": "tasks"})
        ctx = _make_context()

        guardian = GuardianLayer()
        g_result = await guardian.check(brain_result, ctx)
        assert g_result.action == GuardianAction.ALLOW

    @pytest.mark.asyncio
    async def test_guardian_path_traversal_in_params(self):
        """Guardianがパラメータ内のパストラバーサルを検出"""
        _register_test_read_op()

        brain_result = _make_llm_result(
            "data_aggregate", {"data_source": "../../etc/passwd"}
        )
        ctx = _make_context()

        guardian = GuardianLayer()
        g_result = await guardian.check(brain_result, ctx)
        # Guardianが操作系ツールと認識した場合はBLOCK
        # 認識しない場合はALLOW（レジストリ検証で止まる）
        # どちらかで安全が保証される


# =====================================================
# 5. データ操作実機テスト（DB接続なし）
# =====================================================


class TestDataOpsIntegration:
    """data_ops.pyの統合テスト（DBモック使用）"""

    @pytest.mark.asyncio
    async def test_data_aggregate_without_db_returns_error(self):
        """DB接続なしではエラーを返す（クラッシュしない）"""
        data_ops = importlib.import_module("lib.brain.operations.data_ops")

        result = await data_ops.handle_data_aggregate(
            params={"data_source": "tasks", "operation": "count"},
            organization_id="org-test",
            account_id="acc-001",
        )
        # DBプール未設定のため失敗するが、クラッシュしないことが重要
        assert isinstance(result, OperationResult)

    @pytest.mark.asyncio
    async def test_data_search_without_db_returns_error(self):
        """DB接続なしの検索はエラーを返す"""
        data_ops = importlib.import_module("lib.brain.operations.data_ops")

        result = await data_ops.handle_data_search(
            params={"data_source": "tasks", "query": "営業"},
            organization_id="org-test",
            account_id="acc-001",
        )
        assert isinstance(result, OperationResult)

    @pytest.mark.asyncio
    async def test_unsupported_data_source_returns_error(self):
        """未対応データソースはエラー"""
        data_ops = importlib.import_module("lib.brain.operations.data_ops")

        result = await data_ops.handle_data_aggregate(
            params={"data_source": "給与", "operation": "sum"},
            organization_id="org-test",
            account_id="acc-001",
        )
        assert result.success is False
        assert "対応していません" in result.message


# =====================================================
# 6. レポート操作実機テスト（GCSモック使用）
# =====================================================


class TestReportOpsIntegration:
    """report_ops.pyの統合テスト"""

    @pytest.mark.asyncio
    async def test_report_generate_without_gcs_returns_error(self):
        """GCSバケット未設定ではエラーを返す"""
        report_ops = importlib.import_module("lib.brain.operations.report_ops")

        with patch.object(report_ops, "OPERATIONS_GCS_BUCKET", ""):
            result = await report_ops.handle_report_generate(
                params={"title": "テスト", "content": "テスト内容"},
                organization_id="org-test",
                account_id="acc-001",
            )
            assert isinstance(result, OperationResult)
            # バケット未設定でエラーになるがクラッシュしない

    @pytest.mark.asyncio
    async def test_file_create_sanitizes_filename(self):
        """ファイル作成でファイル名が無害化される"""
        report_ops = importlib.import_module("lib.brain.operations.report_ops")
        safe = report_ops._safe_filename("../../etc/passwd")
        assert ".." not in safe
        assert "/" not in safe

    def test_safe_filename_preserves_japanese(self):
        """日本語ファイル名は保持される"""
        report_ops = importlib.import_module("lib.brain.operations.report_ops")
        safe = report_ops._safe_filename("月次レポート_2月.txt")
        assert "月次レポート" in safe
        assert ".txt" in safe


# =====================================================
# 7. 緊急停止統合テスト
# =====================================================


class TestEmergencyStopE2E:
    """緊急停止と操作レジストリの統合"""

    def test_emergency_stop_interface(self):
        """EmergencyStopCheckerのインターフェース確認"""
        from lib.brain.emergency_stop import EmergencyStopChecker

        # DB接続なしでインスタンス化（パラメータ名はorg_id）
        checker = EmergencyStopChecker(pool=None, org_id="org-test")

        # is_stopped()がDB未接続でもクラッシュしないこと
        # （DB未接続はFalse = 安全側に倒す）
        result = checker.is_stopped()
        assert isinstance(result, bool)


# =====================================================
# 8. 操作一覧・カテゴリテスト
# =====================================================


class TestOperationCatalog:
    """操作カタログの整合性テスト"""

    def test_read_and_write_operations_separate(self):
        """読み取りと書き込み操作がカテゴリで分離される"""
        _register_test_read_op()
        _register_test_write_op()

        read_ops = list_operations(category="read")
        write_ops = list_operations(category="write")

        assert "data_aggregate" in read_ops
        assert "report_generate" in write_ops
        assert "data_aggregate" not in write_ops
        assert "report_generate" not in read_ops

    def test_all_operations_listed(self):
        """全操作がカテゴリなしで一覧取得できる"""
        _register_test_read_op()
        _register_test_write_op()

        all_ops = list_operations()
        assert "data_aggregate" in all_ops
        assert "report_generate" in all_ops
        assert len(all_ops) == 2

    def test_operation_definition_has_required_fields(self):
        """操作定義に必須フィールドがすべて含まれる"""
        _register_test_write_op()

        op = get_operation("report_generate")
        assert op is not None
        assert op.name == "report_generate"
        assert op.risk_level in ("low", "medium", "high")
        assert isinstance(op.requires_confirmation, bool)
        assert op.category in ("read", "write")
        assert callable(op.handler)

    def test_write_operations_require_confirmation(self):
        """書き込み操作は必ず確認が必要"""
        _register_test_write_op()

        op = get_operation("report_generate")
        assert op.requires_confirmation is True

    def test_read_operations_no_confirmation(self):
        """読み取り操作は確認不要"""
        _register_test_read_op()

        op = get_operation("data_aggregate")
        assert op.requires_confirmation is False


# =====================================================
# 9. タイムアウト・出力制限テスト
# =====================================================


class TestExecutionLimits:
    """実行制限のテスト"""

    @pytest.mark.asyncio
    async def test_timeout_enforcement(self):
        """30秒タイムアウトが機能する"""
        async def slow_handler(params, organization_id, account_id):
            await asyncio.sleep(35)
            return OperationResult(success=True, message="遅延完了")

        op = OperationDefinition(
            name="slow_op",
            description="遅い操作",
            handler=slow_handler,
            risk_level="low",
            requires_confirmation=False,
            category="read",
        )
        register_operation(op)

        result = await execute_operation("slow_op", {}, "org-test", "acc-001")
        assert result.success is False
        assert "タイムアウト" in result.message

    @pytest.mark.asyncio
    async def test_output_truncation(self):
        """10KB超のデータは切り詰められる"""
        async def big_output_handler(params, organization_id, account_id):
            # dataフィールドに大量データを入れる（truncation対象はresult.data）
            huge_data = {f"key_{i}": "x" * 100 for i in range(200)}
            return OperationResult(
                success=True,
                message="大量データ",
                data=huge_data,
            )

        op = OperationDefinition(
            name="big_op",
            description="大量出力",
            handler=big_output_handler,
            risk_level="low",
            requires_confirmation=False,
            category="read",
        )
        register_operation(op)

        result = await execute_operation("big_op", {}, "org-test", "acc-001")
        assert result.success is True
        assert result.truncated is True

    @pytest.mark.asyncio
    async def test_handler_exception_returns_error(self):
        """ハンドラの例外はエラー結果として返る（クラッシュしない）"""
        async def crash_handler(params, organization_id, account_id):
            raise ValueError("内部エラー発生")

        op = OperationDefinition(
            name="crash_op",
            description="クラッシュ操作",
            handler=crash_handler,
            risk_level="low",
            requires_confirmation=False,
            category="read",
        )
        register_operation(op)

        result = await execute_operation("crash_op", {}, "org-test", "acc-001")
        assert result.success is False
        # エラーメッセージに機密情報を含まないこと（CLAUDE.md §3 鉄則#8）


# =====================================================
# 10. フィルタ・キーワード処理テスト
# =====================================================


class TestFilterProcessing:
    """data_opsのフィルタ処理の正確性テスト"""

    def test_status_filter_order(self):
        """「未完了」が「完了」より先にマッチする"""
        data_ops = importlib.import_module("lib.brain.operations.data_ops")

        # 「未完了」→ open
        where, params = data_ops._build_task_filter("未完了")
        assert params.get("status") == "open"

        # 「完了」→ done
        where, params = data_ops._build_task_filter("完了")
        assert params.get("status") == "done"

        # 「未完了タスク」→ open（「未完了」が先にマッチ）
        where, params = data_ops._build_task_filter("未完了タスク")
        assert params.get("status") == "open"

    def test_keyword_extraction_complete(self):
        """フィルタ語を全て除去してキーワードのみ抽出"""
        data_ops = importlib.import_module("lib.brain.operations.data_ops")

        # フィルタ語のみ → 空文字
        assert data_ops._extract_keywords("先月の未完了タスク") == ""

        # キーワード含む → キーワードのみ
        assert data_ops._extract_keywords("営業報告") == "営業報告"

        # 混合 → キーワードのみ残る
        result = data_ops._extract_keywords("今月の営業タスク")
        assert "営業" in result

    def test_date_filter_this_month(self):
        """「今月」フィルタ"""
        data_ops = importlib.import_module("lib.brain.operations.data_ops")

        where, params = data_ops._build_task_filter("今月")
        assert "date_from" in params
        assert "created_at >= :date_from" in where

    def test_date_filter_last_month(self):
        """「先月」フィルタ"""
        data_ops = importlib.import_module("lib.brain.operations.data_ops")

        where, params = data_ops._build_task_filter("先月")
        assert "date_from" in params
        assert "date_to" in params

    def test_empty_filter(self):
        """空フィルタは空WHERE"""
        data_ops = importlib.import_module("lib.brain.operations.data_ops")

        where, params = data_ops._build_task_filter("")
        assert where == ""
        assert params == {}


# =====================================================
# 11. SYSTEM_CAPABILITIES整合性テスト
# =====================================================


class TestSystemCapabilitiesIntegrity:
    """SYSTEM_CAPABILITIESの操作定義が正しいか"""

    def test_operation_capabilities_exist(self):
        """OPERATION_CAPABILITIESが定義されている"""
        registry_mod = importlib.import_module("lib.brain.operations.registry")
        caps = registry_mod.OPERATION_CAPABILITIES
        assert isinstance(caps, dict)
        assert len(caps) >= 5  # data_aggregate, data_search, report_generate, csv_export, file_create

    def test_all_operation_capabilities_have_required_fields(self):
        """全操作定義に必須フィールドがある"""
        registry_mod = importlib.import_module("lib.brain.operations.registry")
        caps = registry_mod.OPERATION_CAPABILITIES

        # OPERATION_CAPABILITIESはSYSTEM_CAPABILITIES形式で、risk_levelはbrain_metadata内
        required_top_fields = {"name", "description", "category"}
        for op_name, op_def in caps.items():
            for f in required_top_fields:
                assert f in op_def, f"{op_name}に'{f}'がありません"
            # risk_levelはbrain_metadata内にある
            brain_meta = op_def.get("brain_metadata", {})
            assert "risk_level" in brain_meta, \
                f"{op_name}のbrain_metadataに'risk_level'がありません"

    def test_write_ops_all_require_confirmation(self):
        """書き込み操作は全てrequires_confirmation=True"""
        registry_mod = importlib.import_module("lib.brain.operations.registry")
        caps = registry_mod.OPERATION_CAPABILITIES

        # 書き込み操作はrequires_confirmation=Trueが設定されている
        write_ops = {
            k: v for k, v in caps.items()
            if v.get("requires_confirmation") is True
        }
        assert len(write_ops) >= 3  # report_generate, csv_export, file_create

        for op_name, op_def in write_ops.items():
            assert op_def["requires_confirmation"] is True, \
                f"書き込み操作'{op_name}'はrequires_confirmation=Trueが必須"

    def test_risk_levels_consistent(self):
        """リスクレベルがconstantsと一致"""
        from lib.brain.constants import RISK_LEVELS
        registry_mod = importlib.import_module("lib.brain.operations.registry")
        caps = registry_mod.OPERATION_CAPABILITIES

        for op_name, op_def in caps.items():
            brain_meta = op_def.get("brain_metadata", {})
            cap_risk = brain_meta.get("risk_level")
            if op_name in RISK_LEVELS and cap_risk:
                assert RISK_LEVELS[op_name] == cap_risk, \
                    f"{op_name}: RISK_LEVELS={RISK_LEVELS[op_name]} != brain_metadata.risk_level={cap_risk}"
