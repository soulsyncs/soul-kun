"""
Value Authority Layer テスト

v10.42.0 P3: 実行直前の価値観最終チェック機能のテスト
"""

import pytest
from lib.brain.value_authority import (
    ValueAuthority,
    ValueAuthorityResult,
    ValueDecision,
    create_value_authority,
    LIFE_AXIS_VIOLATION_PATTERNS,
    GOAL_CONTRADICTION_PATTERNS,
)


class TestValueDecision:
    """ValueDecision Enum のテスト"""

    def test_enum_values(self):
        """Enumの値が正しいこと"""
        assert ValueDecision.APPROVE.value == "approve"
        assert ValueDecision.BLOCK_AND_SUGGEST.value == "block_and_suggest"
        assert ValueDecision.FORCE_MODE_SWITCH.value == "force_mode_switch"

    def test_all_members_exist(self):
        """すべてのメンバーが存在すること"""
        members = list(ValueDecision)
        assert len(members) == 3


class TestValueAuthorityResult:
    """ValueAuthorityResult のテスト"""

    def test_approve_result(self):
        """APPROVE結果のプロパティ"""
        result = ValueAuthorityResult(
            decision=ValueDecision.APPROVE,
            original_action="test_action",
        )
        assert result.is_approved is True
        assert result.should_block is False
        assert result.should_force_mode_switch is False

    def test_block_and_suggest_result(self):
        """BLOCK_AND_SUGGEST結果のプロパティ"""
        result = ValueAuthorityResult(
            decision=ValueDecision.BLOCK_AND_SUGGEST,
            original_action="test_action",
            reason="人生軸との矛盾",
            violation_type="life_axis_family_priority",
            alternative_message="代替メッセージ",
        )
        assert result.is_approved is False
        assert result.should_block is True
        assert result.should_force_mode_switch is False
        assert result.reason == "人生軸との矛盾"

    def test_force_mode_switch_result(self):
        """FORCE_MODE_SWITCH結果のプロパティ"""
        result = ValueAuthorityResult(
            decision=ValueDecision.FORCE_MODE_SWITCH,
            original_action="test_action",
            reason="CRITICAL: ng_mental_health",
            forced_mode="listening",
        )
        assert result.is_approved is False
        assert result.should_block is True
        assert result.should_force_mode_switch is True
        assert result.forced_mode == "listening"


class TestValueAuthorityNoLifeAxis:
    """人生軸データがない場合のテスト"""

    @pytest.fixture
    def authority_no_axis(self):
        """人生軸なしのAuthority"""
        return create_value_authority(
            user_life_axis=None,
            user_name="テスト太郎",
        )

    def test_no_life_axis_always_approves(self, authority_no_axis):
        """人生軸がない場合は常にAPPROVE"""
        result = authority_no_axis.evaluate_action(
            action="chatwork_task_create",
            action_params={"task_body": "徹夜で資料作成"},
            user_message="徹夜で資料作成のタスク追加して",
        )
        assert result.decision == ValueDecision.APPROVE

    def test_empty_life_axis_always_approves(self):
        """空の人生軸でも常にAPPROVE"""
        authority = create_value_authority(
            user_life_axis=[],
            user_name="テスト太郎",
        )
        result = authority.evaluate_action(
            action="test_action",
            user_message="テスト",
        )
        assert result.decision == ValueDecision.APPROVE


class TestLifeAxisViolation:
    """人生軸違反検出のテスト"""

    @pytest.fixture
    def authority_family_priority(self):
        """家族優先の人生軸を持つAuthority"""
        return create_value_authority(
            user_life_axis=[
                {
                    "memory_type": "values",
                    "content": "家族を最優先にする。子供との時間を大切にしたい。",
                },
            ],
            user_name="テスト太郎",
        )

    @pytest.fixture
    def authority_health_priority(self):
        """健康重視の人生軸を持つAuthority"""
        return create_value_authority(
            user_life_axis=[
                {
                    "memory_type": "life_why",
                    "content": "健康でいることが全ての基盤。睡眠を大切にする。",
                },
            ],
            user_name="テスト太郎",
        )

    def test_family_priority_blocks_late_night_work(self, authority_family_priority):
        """家族優先の人生軸で深夜作業をブロック"""
        result = authority_family_priority.evaluate_action(
            action="chatwork_task_create",
            action_params={"task_body": "深夜まで作業する"},
            user_message="深夜まで作業するタスクを追加して",
        )
        assert result.decision == ValueDecision.BLOCK_AND_SUGGEST
        assert "life_axis" in result.violation_type
        assert result.alternative_message is not None

    def test_health_priority_blocks_all_nighter(self, authority_health_priority):
        """健康重視の人生軸で徹夜をブロック"""
        result = authority_health_priority.evaluate_action(
            action="chatwork_task_create",
            action_params={"task_body": "徹夜で仕上げる"},
            user_message="徹夜で資料仕上げて",
        )
        assert result.decision == ValueDecision.BLOCK_AND_SUGGEST
        assert "health_priority" in result.violation_type

    def test_non_violating_action_approves(self, authority_family_priority):
        """違反しないアクションはAPPROVE"""
        result = authority_family_priority.evaluate_action(
            action="chatwork_task_create",
            action_params={"task_body": "明日の朝までに資料作成"},
            user_message="明日の朝までに資料作成して",
        )
        assert result.decision == ValueDecision.APPROVE


class TestGoalContradiction:
    """長期目標矛盾検出のテスト"""

    @pytest.fixture
    def authority_independence_goal(self):
        """独立目標を持つAuthority"""
        return create_value_authority(
            user_life_axis=[
                {
                    "memory_type": "long_term_goal",
                    "content": "5年以内に独立して自分の会社を持つ",
                },
            ],
            user_name="テスト太郎",
        )

    @pytest.fixture
    def authority_growth_goal(self):
        """成長目標を持つAuthority"""
        return create_value_authority(
            user_life_axis=[
                {
                    "memory_type": "long_term_goal",
                    "content": "常にスキルアップし続けて成長する",
                },
            ],
            user_name="テスト太郎",
        )

    def test_independence_goal_blocks_status_quo(self, authority_independence_goal):
        """独立目標で現状維持志向をブロック"""
        result = authority_independence_goal.evaluate_action(
            action="goal_registration",
            action_params={},
            user_message="リスクを避けて安定を重視したい",
        )
        assert result.decision == ValueDecision.BLOCK_AND_SUGGEST
        assert "goal" in result.violation_type
        assert "independence" in result.violation_type

    def test_growth_goal_blocks_stagnation(self, authority_growth_goal):
        """成長目標で停滞志向をブロック"""
        result = authority_growth_goal.evaluate_action(
            action="general_conversation",
            action_params={},
            user_message="楽したいから挑戦しないことにする",
        )
        assert result.decision == ValueDecision.BLOCK_AND_SUGGEST
        assert "growth" in result.violation_type

    def test_non_contradicting_action_approves(self, authority_independence_goal):
        """矛盾しないアクションはAPPROVE"""
        result = authority_independence_goal.evaluate_action(
            action="goal_registration",
            action_params={},
            user_message="起業に向けて新しいスキルを身につけたい",
        )
        assert result.decision == ValueDecision.APPROVE


class TestNGPatternIntegration:
    """NGパターン連携のテスト"""

    @pytest.fixture
    def authority(self):
        """標準Authority"""
        return create_value_authority(
            user_life_axis=[
                {"memory_type": "values", "content": "ポジティブに生きる"},
            ],
            user_name="テスト太郎",
        )

    def test_critical_ng_pattern_forces_mode_switch(self, authority):
        """CRITICAL NGパターンで強制モード遷移"""
        result = authority.evaluate_action(
            action="general_conversation",
            user_message="もう死にたい",
            ng_pattern_result={
                "risk_level": "CRITICAL",
                "pattern_type": "ng_mental_health",
                "original_action": "general_conversation",
            },
        )
        assert result.decision == ValueDecision.FORCE_MODE_SWITCH
        assert result.forced_mode == "listening"
        assert "ng_pattern" in result.violation_type

    def test_high_ng_pattern_forces_mode_switch(self, authority):
        """HIGH NGパターンで強制モード遷移"""
        result = authority.evaluate_action(
            action="general_conversation",
            user_message="辞めたい",
            ng_pattern_result={
                "risk_level": "HIGH",
                "pattern_type": "ng_retention_critical",
                "original_action": "general_conversation",
            },
        )
        assert result.decision == ValueDecision.FORCE_MODE_SWITCH
        assert result.forced_mode == "listening"

    def test_medium_ng_pattern_does_not_force_switch(self, authority):
        """MEDIUM NGパターンは強制遷移しない（人生軸違反がなければ）"""
        result = authority.evaluate_action(
            action="general_conversation",
            user_message="会社がおかしい",
            ng_pattern_result={
                "risk_level": "MEDIUM",
                "pattern_type": "ng_company_criticism",
                "original_action": "general_conversation",
            },
        )
        # MEDIUMはValueAuthorityではスルー（P1で処理済み）
        assert result.decision == ValueDecision.APPROVE


class TestCreateValueAuthority:
    """create_value_authority ファクトリー関数のテスト"""

    def test_create_with_all_params(self):
        """全パラメータ指定で作成"""
        authority = create_value_authority(
            user_life_axis=[{"memory_type": "values", "content": "test"}],
            user_name="テスト太郎",
            organization_id="org_test",
        )
        assert authority.user_name == "テスト太郎"
        assert authority.organization_id == "org_test"
        assert len(authority.user_life_axis) == 1

    def test_create_with_defaults(self):
        """デフォルト値で作成"""
        authority = create_value_authority()
        assert authority.user_name == "あなた"
        assert authority.organization_id == ""
        assert authority.user_life_axis == []


class TestPatternDefinitions:
    """パターン定義のテスト"""

    def test_life_axis_violation_patterns_exist(self):
        """人生軸違反パターンが定義されている"""
        assert len(LIFE_AXIS_VIOLATION_PATTERNS) >= 3
        assert "family_priority" in LIFE_AXIS_VIOLATION_PATTERNS
        assert "health_priority" in LIFE_AXIS_VIOLATION_PATTERNS
        assert "work_life_balance" in LIFE_AXIS_VIOLATION_PATTERNS

    def test_goal_contradiction_patterns_exist(self):
        """目標矛盾パターンが定義されている"""
        assert len(GOAL_CONTRADICTION_PATTERNS) >= 3
        assert "independence_goal" in GOAL_CONTRADICTION_PATTERNS
        assert "growth_goal" in GOAL_CONTRADICTION_PATTERNS
        assert "leadership_goal" in GOAL_CONTRADICTION_PATTERNS

    def test_patterns_have_required_fields(self):
        """パターンに必須フィールドがある"""
        for key, pattern in LIFE_AXIS_VIOLATION_PATTERNS.items():
            assert "axis_keywords" in pattern, f"{key} missing axis_keywords"
            assert "violation_patterns" in pattern, f"{key} missing violation_patterns"
            assert "alternative_message" in pattern, f"{key} missing alternative_message"

        for key, pattern in GOAL_CONTRADICTION_PATTERNS.items():
            assert "goal_keywords" in pattern, f"{key} missing goal_keywords"
            assert "contradiction_patterns" in pattern, f"{key} missing contradiction_patterns"
            assert "alternative_message" in pattern, f"{key} missing alternative_message"
