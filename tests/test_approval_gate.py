"""
承認ゲート（ApprovalGate）テスト — Step 0-1

ApprovalGateの3段階リスク判定をテストする:
- AUTO_APPROVE: 低リスク → そのまま実行
- REQUIRE_CONFIRMATION: 中リスク → 確認が必要
- REQUIRE_DOUBLE_CHECK: 高リスク → ダブルチェックが必要
"""

import pytest
from unittest.mock import patch

from lib.brain.approval_gate import (
    ApprovalGate,
    ApprovalLevel,
    ApprovalCheckResult,
    get_approval_gate,
)


class TestApprovalGateBasic:
    """基本的なリスク判定のテスト"""

    def setup_method(self):
        self.gate = ApprovalGate()

    def test_low_risk_auto_approve(self):
        """低リスク操作（タスク作成など）は自動承認"""
        result = self.gate.check("chatwork_task_create")
        assert result.level == ApprovalLevel.AUTO_APPROVE
        assert result.risk_level == "low"
        assert result.confirmation_message is None

    def test_medium_risk_requires_confirmation(self):
        """中リスク操作（目標削除など）は確認が必要"""
        result = self.gate.check("goal_delete")
        assert result.level == ApprovalLevel.REQUIRE_CONFIRMATION
        assert result.risk_level == "medium"
        assert result.confirmation_message is not None

    def test_high_risk_requires_double_check(self):
        """高リスク操作（削除など）はダブルチェックが必要"""
        result = self.gate.check("delete")
        assert result.level == ApprovalLevel.REQUIRE_DOUBLE_CHECK
        assert result.risk_level == "high"
        assert result.confirmation_message is not None
        assert "⚠️" in result.confirmation_message

    def test_memory_delete_requires_confirmation(self):
        """記憶削除は確認が必要"""
        result = self.gate.check("delete_memory")
        assert result.level == ApprovalLevel.REQUIRE_CONFIRMATION
        assert result.risk_level == "medium"

    def test_knowledge_forget_requires_confirmation(self):
        """ナレッジ削除は確認が必要"""
        result = self.gate.check("forget_knowledge")
        assert result.level == ApprovalLevel.REQUIRE_CONFIRMATION
        assert result.risk_level == "medium"

    def test_send_announcement_requires_confirmation(self):
        """一斉通知は確認が必要"""
        result = self.gate.check("send_announcement")
        assert result.level == ApprovalLevel.REQUIRE_CONFIRMATION
        assert result.risk_level == "medium"

    def test_query_operations_auto_approve(self):
        """参照系操作は自動承認"""
        for tool_name in ("query_memory", "query_knowledge", "query_org_chart"):
            result = self.gate.check(tool_name)
            assert result.level == ApprovalLevel.AUTO_APPROVE, (
                f"{tool_name} should be AUTO_APPROVE"
            )


class TestApprovalGateParameterEscalation:
    """パラメータに基づくリスクエスカレーションのテスト"""

    def setup_method(self):
        self.gate = ApprovalGate()

    def test_high_amount_escalates(self):
        """10万円以上の金額でリスクがエスカレーション"""
        result = self.gate.check("chatwork_task_create", {"amount": 100000})
        assert result.level == ApprovalLevel.REQUIRE_DOUBLE_CHECK
        assert result.risk_level == "high"

    def test_normal_amount_no_escalation(self):
        """10万円未満は通常のリスクレベル"""
        result = self.gate.check("chatwork_task_create", {"amount": 50000})
        assert result.level == ApprovalLevel.AUTO_APPROVE

    def test_many_recipients_escalates(self):
        """10人以上への送信でリスクがエスカレーション"""
        recipients = [f"user_{i}" for i in range(10)]
        result = self.gate.check("chatwork_task_create", {"recipients": recipients})
        assert result.level == ApprovalLevel.REQUIRE_DOUBLE_CHECK

    def test_few_recipients_no_escalation(self):
        """少人数への送信はエスカレーションなし"""
        result = self.gate.check(
            "chatwork_task_create", {"recipients": ["user_1", "user_2"]}
        )
        assert result.level == ApprovalLevel.AUTO_APPROVE


class TestApprovalGateUnknownTool:
    """未知のTool（MCP追加分など）のテスト"""

    def setup_method(self):
        self.gate = ApprovalGate()

    def test_unknown_tool_defaults_to_medium(self):
        """未知のToolは安全側（medium）に倒す"""
        with patch(
            "lib.brain.approval_gate.ApprovalGate._check_requires_confirmation",
            return_value=True,
        ):
            result = self.gate.check("some_new_mcp_tool")
            # mediumかつrequires_confirmation=True → REQUIRE_CONFIRMATION
            assert result.level in (
                ApprovalLevel.REQUIRE_CONFIRMATION,
                ApprovalLevel.REQUIRE_DOUBLE_CHECK,
            )


class TestApprovalCheckResult:
    """ApprovalCheckResultデータクラスのテスト"""

    def test_result_has_all_fields(self):
        """結果に必要なフィールドが全てある"""
        result = ApprovalCheckResult(
            level=ApprovalLevel.AUTO_APPROVE,
            risk_level="low",
            tool_name="test_tool",
            reason="test reason",
        )
        assert result.level == ApprovalLevel.AUTO_APPROVE
        assert result.risk_level == "low"
        assert result.tool_name == "test_tool"
        assert result.reason == "test reason"
        assert result.confirmation_message is None

    def test_result_with_confirmation_message(self):
        """確認メッセージ付きの結果"""
        result = ApprovalCheckResult(
            level=ApprovalLevel.REQUIRE_CONFIRMATION,
            risk_level="medium",
            tool_name="goal_delete",
            reason="test",
            confirmation_message="確認: 目標を削除します",
        )
        assert result.confirmation_message is not None


class TestGetApprovalGateSingleton:
    """シングルトンアクセスのテスト"""

    def test_singleton_returns_same_instance(self):
        """get_approval_gate()は常に同じインスタンスを返す"""
        gate1 = get_approval_gate()
        gate2 = get_approval_gate()
        assert gate1 is gate2

    def test_singleton_is_approval_gate_instance(self):
        """シングルトンはApprovalGateのインスタンス"""
        gate = get_approval_gate()
        assert isinstance(gate, ApprovalGate)
