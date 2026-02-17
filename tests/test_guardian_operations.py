# tests/test_guardian_operations.py
"""
Step C-4: Guardian Layer 操作系チェックのテスト

操作系（category="operations"）に対する5つのGuardianルールをテストする:
1. レジストリ登録チェック
2. パラメータ長チェック
3. パス安全性チェック
4. 連続実行チェック（レートリミット）
5. 日次クォータチェック

Author: Claude Opus 4.6
Created: 2026-02-17
"""

import importlib
import time
import pytest
from unittest.mock import MagicMock, patch

# 直接インポートでテスト（重い依存を避ける）
from lib.brain.guardian_layer import (
    GuardianLayer,
    GuardianAction,
    GuardianResult,
)
from lib.brain.llm_brain import LLMBrainResult, ToolCall, ConfidenceScores
from lib.brain.context_builder import LLMContext


# =====================================================
# フィクスチャ
# =====================================================


def _make_llm_result_with_tool(
    tool_name: str, params: dict = None, confidence: float = 0.9
) -> LLMBrainResult:
    """Tool呼び出し付きのLLMBrainResultを作成"""
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
    """テスト用LLMContextを作成（最小構成）"""
    ctx = MagicMock(spec=LLMContext)
    ctx.account_id = account_id
    ctx.ceo_teachings = []
    return ctx


@pytest.fixture
def guardian():
    """テスト用GuardianLayerインスタンス"""
    g = GuardianLayer()
    return g


# =====================================================
# 8-1: レジストリ登録チェック
# =====================================================


class TestOperationRegistryCheck:
    """未登録の操作系ツールはブロックされる"""

    @pytest.mark.asyncio
    async def test_registered_operation_allowed(self, guardian):
        """レジストリに登録済みの操作は通過する"""
        llm_result = _make_llm_result_with_tool(
            "data_aggregate", {"data_source": "tasks", "operation": "count"}
        )
        ctx = _make_context()

        # data_aggregateはSYSTEM_CAPABILITIES(category=operations)に登録済み
        # かつ操作レジストリにも登録されている前提でテスト
        with patch(
            "lib.brain.guardian_layer.GuardianLayer._is_operation_tool",
            return_value=True,
        ), patch(
            "lib.brain.operations.registry.is_registered",
            return_value=True,
        ):
            result = await guardian.check(llm_result, ctx)
            assert result.action == GuardianAction.ALLOW

    @pytest.mark.asyncio
    async def test_unregistered_operation_blocked(self, guardian):
        """レジストリ未登録の操作系ツールはブロックされる"""
        llm_result = _make_llm_result_with_tool("evil_command", {"cmd": "rm -rf /"})
        ctx = _make_context()

        with patch(
            "lib.brain.guardian_layer.GuardianLayer._is_operation_tool",
            return_value=True,
        ), patch(
            "lib.brain.operations.registry.is_registered",
            return_value=False,
        ):
            result = await guardian.check(llm_result, ctx)
            assert result.action == GuardianAction.BLOCK
            assert "レジストリ" in result.blocked_reason

    @pytest.mark.asyncio
    async def test_non_operation_tool_skips_registry_check(self, guardian):
        """操作系でないツールはレジストリチェックをスキップ"""
        llm_result = _make_llm_result_with_tool(
            "chatwork_task_create", {"title": "テストタスク"}
        )
        ctx = _make_context()

        # _is_operation_tool=Falseなので操作チェックはスキップされる
        result = await guardian.check(llm_result, ctx)
        assert result.action == GuardianAction.ALLOW


# =====================================================
# 8-2: パラメータ長チェック
# =====================================================


class TestOperationParamLength:
    """200文字を超えるパラメータは確認を要求"""

    @pytest.mark.asyncio
    async def test_long_param_requires_confirmation(self, guardian):
        """200文字超のパラメータでCONFIRM"""
        long_query = "a" * 250
        llm_result = _make_llm_result_with_tool(
            "data_search", {"data_source": "tasks", "query": long_query}
        )
        ctx = _make_context()

        with patch(
            "lib.brain.guardian_layer.GuardianLayer._is_operation_tool",
            return_value=True,
        ), patch(
            "lib.brain.operations.registry.is_registered",
            return_value=True,
        ):
            result = await guardian.check(llm_result, ctx)
            assert result.action == GuardianAction.CONFIRM
            assert "250文字" in result.confirmation_question

    @pytest.mark.asyncio
    async def test_normal_param_allowed(self, guardian):
        """200文字以下のパラメータは通過"""
        llm_result = _make_llm_result_with_tool(
            "data_search", {"data_source": "tasks", "query": "営業報告"}
        )
        ctx = _make_context()

        with patch(
            "lib.brain.guardian_layer.GuardianLayer._is_operation_tool",
            return_value=True,
        ), patch(
            "lib.brain.operations.registry.is_registered",
            return_value=True,
        ):
            result = await guardian.check(llm_result, ctx)
            assert result.action == GuardianAction.ALLOW


# =====================================================
# 8-3: パス安全性チェック
# =====================================================


class TestOperationPathSafety:
    """パストラバーサルや絶対パスはブロック"""

    @pytest.mark.asyncio
    async def test_path_traversal_blocked(self, guardian):
        """..を含むパスはブロック"""
        llm_result = _make_llm_result_with_tool(
            "data_search", {"data_source": "tasks", "path": "../../etc/passwd"}
        )
        ctx = _make_context()

        with patch(
            "lib.brain.guardian_layer.GuardianLayer._is_operation_tool",
            return_value=True,
        ), patch(
            "lib.brain.operations.registry.is_registered",
            return_value=True,
        ):
            result = await guardian.check(llm_result, ctx)
            assert result.action == GuardianAction.BLOCK
            assert "不正なパス" in result.blocked_reason

    @pytest.mark.asyncio
    async def test_absolute_path_blocked(self, guardian):
        """絶対パスはブロック"""
        llm_result = _make_llm_result_with_tool(
            "data_search", {"data_source": "tasks", "file_path": "/etc/shadow"}
        )
        ctx = _make_context()

        with patch(
            "lib.brain.guardian_layer.GuardianLayer._is_operation_tool",
            return_value=True,
        ), patch(
            "lib.brain.operations.registry.is_registered",
            return_value=True,
        ):
            result = await guardian.check(llm_result, ctx)
            assert result.action == GuardianAction.BLOCK
            assert "絶対パス" in result.blocked_reason

    @pytest.mark.asyncio
    async def test_safe_data_source_allowed(self, guardian):
        """安全なdata_sourceは通過"""
        llm_result = _make_llm_result_with_tool(
            "data_aggregate", {"data_source": "tasks", "operation": "count"}
        )
        ctx = _make_context()

        with patch(
            "lib.brain.guardian_layer.GuardianLayer._is_operation_tool",
            return_value=True,
        ), patch(
            "lib.brain.operations.registry.is_registered",
            return_value=True,
        ):
            result = await guardian.check(llm_result, ctx)
            assert result.action == GuardianAction.ALLOW


# =====================================================
# 8-4: 連続実行チェック（レートリミット）
# =====================================================


class TestOperationRateLimit:
    """連続実行はブロック"""

    @pytest.mark.asyncio
    async def test_burst_limit_blocks(self, guardian):
        """10秒以内に3回以上でブロック"""
        ctx = _make_context("burst-user")

        # 3回の履歴を偽装
        now = time.time()
        guardian._op_call_timestamps["burst-user"].extend([now - 2, now - 1, now])

        llm_result = _make_llm_result_with_tool(
            "data_aggregate", {"data_source": "tasks", "operation": "count"}
        )

        with patch(
            "lib.brain.guardian_layer.GuardianLayer._is_operation_tool",
            return_value=True,
        ), patch(
            "lib.brain.operations.registry.is_registered",
            return_value=True,
        ):
            result = await guardian.check(llm_result, ctx)
            assert result.action == GuardianAction.BLOCK
            assert "連続実行" in result.blocked_reason

    @pytest.mark.asyncio
    async def test_rate_limit_per_minute_blocks(self, guardian):
        """1分以内に5回以上でブロック"""
        ctx = _make_context("rate-user")

        # 5回の履歴を偽装（10秒超間隔＝バーストにはならない）
        now = time.time()
        guardian._op_call_timestamps["rate-user"].extend(
            [now - 55, now - 45, now - 35, now - 25, now - 15]
        )

        llm_result = _make_llm_result_with_tool(
            "data_search", {"data_source": "tasks", "query": "test"}
        )

        with patch(
            "lib.brain.guardian_layer.GuardianLayer._is_operation_tool",
            return_value=True,
        ), patch(
            "lib.brain.operations.registry.is_registered",
            return_value=True,
        ):
            result = await guardian.check(llm_result, ctx)
            assert result.action == GuardianAction.BLOCK
            assert "回数制限" in result.blocked_reason

    @pytest.mark.asyncio
    async def test_normal_rate_allowed(self, guardian):
        """通常頻度の実行は通過"""
        ctx = _make_context("normal-user")

        llm_result = _make_llm_result_with_tool(
            "data_aggregate", {"data_source": "tasks", "operation": "count"}
        )

        with patch(
            "lib.brain.guardian_layer.GuardianLayer._is_operation_tool",
            return_value=True,
        ), patch(
            "lib.brain.operations.registry.is_registered",
            return_value=True,
        ):
            result = await guardian.check(llm_result, ctx)
            assert result.action == GuardianAction.ALLOW


# =====================================================
# 8-5: 日次クォータチェック
# =====================================================


class TestOperationDailyQuota:
    """日次クォータ超過はブロック"""

    @pytest.mark.asyncio
    async def test_read_quota_exceeded_blocks(self, guardian):
        """読み取り操作50回超でブロック"""
        from datetime import date as date_mod

        ctx = _make_context("quota-user")
        today_str = date_mod.today().isoformat()
        guardian._op_daily_counts[("quota-user", today_str)]["read"] = 50

        llm_result = _make_llm_result_with_tool(
            "data_aggregate", {"data_source": "tasks", "operation": "count"}
        )

        with patch(
            "lib.brain.guardian_layer.GuardianLayer._is_operation_tool",
            return_value=True,
        ), patch(
            "lib.brain.operations.registry.is_registered",
            return_value=True,
        ):
            result = await guardian.check(llm_result, ctx)
            assert result.action == GuardianAction.BLOCK
            assert "上限" in result.blocked_reason

    @pytest.mark.asyncio
    async def test_write_quota_exceeded_blocks(self, guardian):
        """書き込み操作20回超でブロック"""
        from datetime import date as date_mod

        ctx = _make_context("quota-writer")
        today_str = date_mod.today().isoformat()
        guardian._op_daily_counts[("quota-writer", today_str)]["write"] = 20

        llm_result = _make_llm_result_with_tool(
            "report_generate", {"format": "pdf"}
        )

        with patch(
            "lib.brain.guardian_layer.GuardianLayer._is_operation_tool",
            return_value=True,
        ), patch(
            "lib.brain.operations.registry.is_registered",
            return_value=True,
        ):
            result = await guardian.check(llm_result, ctx)
            assert result.action == GuardianAction.BLOCK
            assert "上限" in result.blocked_reason

    @pytest.mark.asyncio
    async def test_under_quota_allowed(self, guardian):
        """クォータ内は通過"""
        ctx = _make_context("under-quota")

        llm_result = _make_llm_result_with_tool(
            "data_search", {"data_source": "tasks", "query": "test"}
        )

        with patch(
            "lib.brain.guardian_layer.GuardianLayer._is_operation_tool",
            return_value=True,
        ), patch(
            "lib.brain.operations.registry.is_registered",
            return_value=True,
        ):
            result = await guardian.check(llm_result, ctx)
            assert result.action == GuardianAction.ALLOW


# =====================================================
# _is_operation_tool判定テスト
# =====================================================


class TestIsOperationTool:
    """操作系ツール判定"""

    def test_operation_tool_detected(self, guardian):
        """SYSTEM_CAPABILITIESでcategory=operationsのツールを検出"""
        # 実際のSYSTEM_CAPABILITIESを使って確認
        assert guardian._is_operation_tool("data_aggregate") is True
        assert guardian._is_operation_tool("data_search") is True

    def test_non_operation_tool(self, guardian):
        """操作系でないツールはFalse"""
        assert guardian._is_operation_tool("chatwork_task_create") is False
        assert guardian._is_operation_tool("save_memory") is False

    def test_unknown_tool(self, guardian):
        """未知のツールはFalse"""
        assert guardian._is_operation_tool("completely_unknown") is False
