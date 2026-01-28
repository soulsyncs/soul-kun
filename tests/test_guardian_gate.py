"""
Guardian Gate テスト

v10.42.0 P0: アクション実行前の価値観評価機能のテスト
"""

import pytest
from lib.brain.guardian import (
    GuardianService,
    GuardianActionResult,
    GuardianActionType,
)


class TestGuardianActionResult:
    """GuardianActionResult のテスト"""

    def test_approve_result(self):
        """APPROVE結果のテスト"""
        result = GuardianActionResult(
            action_type=GuardianActionType.APPROVE,
            original_action="general_conversation",
        )
        assert result.action_type == GuardianActionType.APPROVE
        assert result.should_block is False
        assert result.should_force_mode_switch is False

    def test_block_and_suggest_result(self):
        """BLOCK_AND_SUGGEST結果のテスト"""
        result = GuardianActionResult(
            action_type=GuardianActionType.BLOCK_AND_SUGGEST,
            original_action="task_registration",
            blocked_reason="MEDIUM: ng_company_criticism",
            alternative_message="モヤモヤがあるウルね。何があったか教えてウル",
        )
        assert result.action_type == GuardianActionType.BLOCK_AND_SUGGEST
        assert result.should_block is True
        assert result.should_force_mode_switch is False
        assert result.alternative_message is not None

    def test_force_mode_switch_result(self):
        """FORCE_MODE_SWITCH結果のテスト"""
        result = GuardianActionResult(
            action_type=GuardianActionType.FORCE_MODE_SWITCH,
            original_action="goal_registration",
            blocked_reason="CRITICAL: ng_mental_health",
            force_mode="listening",
            alternative_message="つらい状況ウルね。話してくれてありがとうウル。",
        )
        assert result.action_type == GuardianActionType.FORCE_MODE_SWITCH
        assert result.should_block is True
        assert result.should_force_mode_switch is True
        assert result.force_mode == "listening"


class TestGuardianEvaluateAction:
    """GuardianService.evaluate_action() のテスト"""

    @pytest.fixture
    def guardian(self):
        """テスト用Guardianインスタンス"""
        # DB不要のモック用（evaluate_actionはDBを使わない）
        class MockPool:
            pass
        return GuardianService(
            pool=MockPool(),
            organization_id="test-org",
        )

    def test_approve_normal_message(self, guardian):
        """通常メッセージはAPPROVE"""
        result = guardian.evaluate_action(
            user_message="今日のタスクを教えて",
            action="task_list",
        )
        assert result.action_type == GuardianActionType.APPROVE
        assert result.should_block is False

    def test_block_retention_risk(self, guardian):
        """離職リスクメッセージはFORCE_MODE_SWITCH"""
        result = guardian.evaluate_action(
            user_message="転職を考えてるんだよね",
            action="general_conversation",
        )
        # ng_retention_critical は HIGH リスク → FORCE_MODE_SWITCH
        assert result.action_type == GuardianActionType.FORCE_MODE_SWITCH
        assert result.should_block is True
        assert result.force_mode == "listening"
        assert "ng_retention" in (result.ng_pattern_type or "")

    def test_block_mental_health_critical(self, guardian):
        """メンタルヘルスリスクはFORCE_MODE_SWITCH（CRITICAL）"""
        result = guardian.evaluate_action(
            user_message="もう生きてる意味がないかも",
            action="general_conversation",
        )
        # ng_mental_health は CRITICAL → FORCE_MODE_SWITCH
        assert result.action_type == GuardianActionType.FORCE_MODE_SWITCH
        assert result.should_block is True
        assert "mental_health" in (result.ng_pattern_type or "")

    def test_block_company_criticism_medium(self, guardian):
        """会社批判はBLOCK_AND_SUGGEST（MEDIUM）"""
        result = guardian.evaluate_action(
            user_message="この会社はおかしいよ",
            action="general_conversation",
        )
        # ng_company_criticism は MEDIUM → BLOCK_AND_SUGGEST
        assert result.action_type == GuardianActionType.BLOCK_AND_SUGGEST
        assert result.should_block is True
        assert result.alternative_message is not None

    def test_approve_hr_low_risk(self, guardian):
        """人事関連（LOW）はAPPROVE"""
        result = guardian.evaluate_action(
            user_message="給料の査定ってどうなってるの？",
            action="general_conversation",
        )
        # ng_hr_authority は LOW → APPROVE
        assert result.action_type == GuardianActionType.APPROVE
        assert result.should_block is False


class TestGuardianGateIntegration:
    """Guardian GateとNG Patternの統合テスト"""

    @pytest.fixture
    def guardian(self):
        """テスト用Guardianインスタンス"""
        class MockPool:
            pass
        return GuardianService(
            pool=MockPool(),
            organization_id="test-org",
        )

    @pytest.mark.parametrize("message,expected_type", [
        # CRITICAL (ng_mental_health)
        ("死にたい", GuardianActionType.FORCE_MODE_SWITCH),
        ("消えたい", GuardianActionType.FORCE_MODE_SWITCH),
        ("生きてる意味がない", GuardianActionType.FORCE_MODE_SWITCH),
        # HIGH (ng_retention_critical)
        ("辞めたい", GuardianActionType.FORCE_MODE_SWITCH),
        ("転職考えてる", GuardianActionType.FORCE_MODE_SWITCH),
        ("他の会社に行こうかな", GuardianActionType.FORCE_MODE_SWITCH),
        # MEDIUM (ng_company_criticism)
        ("この会社はダメだ", GuardianActionType.BLOCK_AND_SUGGEST),
        ("経営陣がおかしい", GuardianActionType.BLOCK_AND_SUGGEST),
        # MEDIUM (ng_low_psychological_safety)
        ("本音が言えない", GuardianActionType.BLOCK_AND_SUGGEST),
        ("失敗できない雰囲気", GuardianActionType.BLOCK_AND_SUGGEST),
        # LOW (ng_hr_authority) - approve
        ("給料上げて", GuardianActionType.APPROVE),
        ("昇進したい", GuardianActionType.APPROVE),
        # Normal - approve
        ("今日のタスクは？", GuardianActionType.APPROVE),
        ("ミーティングの予定", GuardianActionType.APPROVE),
    ])
    def test_ng_pattern_to_action_type(self, guardian, message, expected_type):
        """NGパターンに応じた正しいアクションタイプが返されること"""
        result = guardian.evaluate_action(
            user_message=message,
            action="test_action",
        )
        assert result.action_type == expected_type, f"Message: {message}"
