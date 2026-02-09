# tests/test_brain_learning_loop_phase2e.py
"""
Phase 2E: LearningLoop フィードバック→判断改善 テスト

テスト対象:
- 2E-1: 改善の永続化（save/load）
- 2E-2: _apply_weight_adjustment
- 2E-3: _apply_rule_addition
- 2E-4: _apply_exception_addition
- 2E-5: _apply_confirmation_rule
- 2E-6: 効果測定 + 自動リバート
- Decision / Guardian 連携
"""

import json
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from lib.brain.learning_loop import (
    LearningLoop,
    Improvement,
    ImprovementType,
    LearningStatus,
    THRESHOLD_MAX,
    THRESHOLD_MIN,
    THRESHOLD_ADJUSTMENT_STEP,
    MIN_SAMPLES_FOR_IMPROVEMENT,
    create_learning_loop,
)
from lib.brain.decision import BrainDecision
from lib.brain.guardian_layer import GuardianLayer, GuardianAction


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def loop():
    """LearningLoop without DB pool"""
    return LearningLoop(
        pool=None,
        organization_id="test-org",
        enable_auto_apply=True,
        enable_effectiveness_tracking=True,
    )


@pytest.fixture
def loop_with_pool():
    """LearningLoop with mock DB pool"""
    mock_pool = MagicMock()
    return LearningLoop(
        pool=mock_pool,
        organization_id="test-org",
        enable_auto_apply=True,
        enable_effectiveness_tracking=True,
    )


@pytest.fixture
def weight_improvement():
    return Improvement(
        id="imp-weight-1",
        improvement_type=ImprovementType.WEIGHT_ADJUSTMENT,
        target_action="task_management",
        weight_changes={"keyword_match": 0.1, "context_match": -0.05},
        description="タスク管理のキーワードマッチ重みを増加",
    )


@pytest.fixture
def rule_improvement():
    return Improvement(
        id="imp-rule-1",
        improvement_type=ImprovementType.RULE_ADDITION,
        target_action="send_message",
        rule_condition="send_message",
        rule_action="confirm",
        description="メッセージ送信時は確認を取る",
    )


@pytest.fixture
def exception_improvement():
    return Improvement(
        id="imp-exc-1",
        improvement_type=ImprovementType.EXCEPTION_ADDITION,
        target_action="general_conversation",
        rule_condition="挨拶",
        rule_action="greeting",
        description="挨拶パターンは一般会話ではなく挨拶アクション",
    )


@pytest.fixture
def confirmation_improvement():
    return Improvement(
        id="imp-conf-1",
        improvement_type=ImprovementType.CONFIRMATION_RULE,
        target_action="delete_task",
        description="タスク削除は確認を要求",
    )


# =============================================================================
# 2E-2: Weight Adjustment Tests
# =============================================================================


class TestApplyWeightAdjustment:

    @pytest.mark.asyncio
    async def test_apply_success(self, loop, weight_improvement):
        result = await loop._apply_weight_adjustment(weight_improvement)

        assert result is True
        assert weight_improvement.status == LearningStatus.APPLIED
        assert weight_improvement.applied_at is not None

        adjustments = loop.get_weight_adjustments("task_management")
        assert adjustments["keyword_match"] == pytest.approx(0.1)
        assert adjustments["context_match"] == pytest.approx(-0.05)

    @pytest.mark.asyncio
    async def test_missing_target(self, loop):
        imp = Improvement(
            improvement_type=ImprovementType.WEIGHT_ADJUSTMENT,
            weight_changes={"keyword_match": 0.1},
        )
        assert await loop._apply_weight_adjustment(imp) is False

    @pytest.mark.asyncio
    async def test_empty_changes(self, loop):
        imp = Improvement(
            improvement_type=ImprovementType.WEIGHT_ADJUSTMENT,
            target_action="task_management",
            weight_changes={},
        )
        assert await loop._apply_weight_adjustment(imp) is False

    @pytest.mark.asyncio
    async def test_clamped_to_bounds(self, loop):
        """重み調整は-0.5〜+0.5にクランプ"""
        imp = Improvement(
            improvement_type=ImprovementType.WEIGHT_ADJUSTMENT,
            target_action="test_action",
            weight_changes={"score": 0.9},
        )
        await loop._apply_weight_adjustment(imp)
        assert loop.get_weight_adjustments("test_action")["score"] == pytest.approx(0.5)

    @pytest.mark.asyncio
    async def test_cumulative(self, loop):
        """複数の重み調整が累積される"""
        for i, delta in enumerate([0.1, 0.15]):
            imp = Improvement(
                id=f"w{i}",
                improvement_type=ImprovementType.WEIGHT_ADJUSTMENT,
                target_action="action_a",
                weight_changes={"score": delta},
            )
            await loop._apply_weight_adjustment(imp)

        assert loop.get_weight_adjustments("action_a")["score"] == pytest.approx(0.25)


# =============================================================================
# 2E-3: Rule Addition Tests
# =============================================================================


class TestApplyRuleAddition:

    @pytest.mark.asyncio
    async def test_apply_success(self, loop, rule_improvement):
        result = await loop._apply_rule_addition(rule_improvement)

        assert result is True
        assert rule_improvement.status == LearningStatus.APPLIED

        rules = loop.get_learned_rules()
        assert len(rules) == 1
        assert rules[0]["condition"] == "send_message"
        assert rules[0]["action"] == "confirm"
        assert rules[0]["improvement_id"] == "imp-rule-1"

    @pytest.mark.asyncio
    async def test_missing_condition(self, loop):
        imp = Improvement(
            improvement_type=ImprovementType.RULE_ADDITION,
            rule_action="block",
        )
        assert await loop._apply_rule_addition(imp) is False

    @pytest.mark.asyncio
    async def test_missing_action(self, loop):
        imp = Improvement(
            improvement_type=ImprovementType.RULE_ADDITION,
            rule_condition="some_condition",
        )
        assert await loop._apply_rule_addition(imp) is False


# =============================================================================
# 2E-4: Exception Addition Tests
# =============================================================================


class TestApplyExceptionAddition:

    @pytest.mark.asyncio
    async def test_apply_success(self, loop, exception_improvement):
        result = await loop._apply_exception_addition(exception_improvement)

        assert result is True
        assert exception_improvement.status == LearningStatus.APPLIED

        exceptions = loop.get_learned_exceptions()
        assert len(exceptions) == 1
        assert exceptions[0]["target_action"] == "general_conversation"
        assert exceptions[0]["condition"] == "挨拶"
        assert exceptions[0]["override_action"] == "greeting"

    @pytest.mark.asyncio
    async def test_missing_target(self, loop):
        imp = Improvement(
            improvement_type=ImprovementType.EXCEPTION_ADDITION,
            rule_condition="test",
        )
        assert await loop._apply_exception_addition(imp) is False

    @pytest.mark.asyncio
    async def test_missing_condition(self, loop):
        imp = Improvement(
            improvement_type=ImprovementType.EXCEPTION_ADDITION,
            target_action="test_action",
        )
        assert await loop._apply_exception_addition(imp) is False


# =============================================================================
# 2E-5: Confirmation Rule Tests
# =============================================================================


class TestApplyConfirmationRule:

    @pytest.mark.asyncio
    async def test_apply_success(self, loop, confirmation_improvement):
        result = await loop._apply_confirmation_rule(confirmation_improvement)

        assert result is True
        assert confirmation_improvement.status == LearningStatus.APPLIED
        assert confirmation_improvement.old_threshold == THRESHOLD_MAX
        expected = THRESHOLD_MAX - THRESHOLD_ADJUSTMENT_STEP
        assert confirmation_improvement.new_threshold == pytest.approx(expected)
        assert loop.get_adjusted_threshold("delete_task") == pytest.approx(expected)

    @pytest.mark.asyncio
    async def test_missing_target(self, loop):
        imp = Improvement(improvement_type=ImprovementType.CONFIRMATION_RULE)
        assert await loop._apply_confirmation_rule(imp) is False

    @pytest.mark.asyncio
    async def test_cumulative_lower(self, loop):
        """繰り返し適用で閾値が下がる"""
        for i in range(3):
            imp = Improvement(
                id=f"conf-{i}",
                improvement_type=ImprovementType.CONFIRMATION_RULE,
                target_action="risky_action",
            )
            await loop._apply_confirmation_rule(imp)

        expected = THRESHOLD_MAX - (THRESHOLD_ADJUSTMENT_STEP * 3)
        assert loop.get_adjusted_threshold("risky_action") == pytest.approx(expected)

    @pytest.mark.asyncio
    async def test_min_clamp(self, loop):
        """閾値はTHRESHOLD_MINを下回らない"""
        for i in range(20):
            imp = Improvement(
                id=f"conf-{i}",
                improvement_type=ImprovementType.CONFIRMATION_RULE,
                target_action="very_risky",
            )
            await loop._apply_confirmation_rule(imp)

        assert loop.get_adjusted_threshold("very_risky") >= THRESHOLD_MIN


# =============================================================================
# 2E-1: Persistence Tests
# =============================================================================


class TestPersistence:

    @pytest.mark.asyncio
    async def test_save_to_db(self, loop_with_pool, weight_improvement):
        """改善がDBに永続化される"""
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        loop_with_pool.pool.connect.return_value = mock_conn

        result = await loop_with_pool._save_improvement_to_db(weight_improvement)

        assert result is True
        mock_conn.execute.assert_called_once()
        mock_conn.commit.assert_called_once()

        call_args = mock_conn.execute.call_args[0]
        params = call_args[1]
        assert params["org_id"] == "test-org"
        assert params["type"] == "weight_adjustment"

    @pytest.mark.asyncio
    async def test_save_no_pool(self, loop, weight_improvement):
        assert await loop._save_improvement_to_db(weight_improvement) is False

    @pytest.mark.asyncio
    async def test_load_persisted(self, loop_with_pool):
        """DBから改善を復元"""
        details = json.dumps({
            "improvement_id": "loaded-1",
            "target_action": "task_management",
            "weight_changes": {"keyword_match": 0.2},
            "description": "テスト改善",
            "priority": 5,
            "status": "applied",
        })

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = [
            {
                "improvement_type": "weight_adjustment",
                "category": "applied",
                "trigger_event": details,
            }
        ]
        mock_conn.execute.return_value = mock_result
        loop_with_pool.pool.connect.return_value = mock_conn

        count = await loop_with_pool.load_persisted_improvements()

        assert count == 1
        assert "loaded-1" in loop_with_pool._improvement_cache
        assert loop_with_pool.get_weight_adjustments("task_management")["keyword_match"] == pytest.approx(0.2)

    @pytest.mark.asyncio
    async def test_load_no_pool(self, loop):
        assert await loop.load_persisted_improvements() == 0

    @pytest.mark.asyncio
    async def test_load_skips_invalid(self, loop_with_pool):
        """不正な行はスキップ"""
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = [
            {"improvement_type": "invalid_xxx", "category": "applied", "trigger_event": "{}"},
            {"improvement_type": "weight_adjustment", "category": "applied", "trigger_event": "bad-json{{{"},
        ]
        mock_conn.execute.return_value = mock_result
        loop_with_pool.pool.connect.return_value = mock_conn

        assert await loop_with_pool.load_persisted_improvements() == 0


# =============================================================================
# Restore Tests
# =============================================================================


class TestRestoreImprovement:

    @pytest.mark.asyncio
    async def test_restore_rule(self, loop):
        imp = Improvement(
            id="r1", improvement_type=ImprovementType.RULE_ADDITION,
            rule_condition="dangerous_op", rule_action="block", description="危険操作",
        )
        assert await loop._restore_improvement(imp) is True
        assert len(loop.get_learned_rules()) == 1

    @pytest.mark.asyncio
    async def test_restore_exception(self, loop):
        imp = Improvement(
            id="e1", improvement_type=ImprovementType.EXCEPTION_ADDITION,
            target_action="search", rule_condition="help", rule_action="help",
        )
        assert await loop._restore_improvement(imp) is True
        assert len(loop.get_learned_exceptions()) == 1

    @pytest.mark.asyncio
    async def test_restore_confirmation(self, loop):
        imp = Improvement(
            id="c1", improvement_type=ImprovementType.CONFIRMATION_RULE,
            target_action="send_all", new_threshold=0.6,
        )
        assert await loop._restore_improvement(imp) is True
        assert loop.get_adjusted_threshold("send_all") == pytest.approx(0.6)


# =============================================================================
# 2E-6: Revert Tests (extended)
# =============================================================================


class TestRevertImprovement:

    @pytest.mark.asyncio
    async def test_revert_weight(self, loop, weight_improvement):
        await loop._apply_weight_adjustment(weight_improvement)
        assert await loop.revert_improvement("imp-weight-1") is True
        assert weight_improvement.status == LearningStatus.REVERTED
        adj = loop.get_weight_adjustments("task_management")
        assert adj["keyword_match"] == pytest.approx(0.0)
        assert adj["context_match"] == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_revert_rule(self, loop, rule_improvement):
        await loop._apply_rule_addition(rule_improvement)
        assert len(loop.get_learned_rules()) == 1
        assert await loop.revert_improvement("imp-rule-1") is True
        assert len(loop.get_learned_rules()) == 0

    @pytest.mark.asyncio
    async def test_revert_exception(self, loop, exception_improvement):
        await loop._apply_exception_addition(exception_improvement)
        assert len(loop.get_learned_exceptions()) == 1
        assert await loop.revert_improvement("imp-exc-1") is True
        assert len(loop.get_learned_exceptions()) == 0

    @pytest.mark.asyncio
    async def test_revert_confirmation(self, loop, confirmation_improvement):
        await loop._apply_confirmation_rule(confirmation_improvement)
        old = confirmation_improvement.old_threshold
        assert await loop.revert_improvement("imp-conf-1") is True
        assert loop.get_adjusted_threshold("delete_task") == pytest.approx(old)

    @pytest.mark.asyncio
    async def test_revert_nonexistent(self, loop):
        assert await loop.revert_improvement("nonexistent") is False


# =============================================================================
# 2E-6: Effectiveness Measurement Tests
# =============================================================================


class TestEffectiveness:

    @pytest.mark.asyncio
    async def test_no_target_action(self, loop):
        imp = Improvement(id="no-target", status=LearningStatus.APPLIED)
        imp.applied_at = datetime.now() - timedelta(days=15)
        loop._improvement_cache["no-target"] = imp
        assert await loop.measure_effectiveness("no-target") is None

    @pytest.mark.asyncio
    async def test_not_applied(self, loop):
        assert await loop.measure_effectiveness("nonexistent") is None

    @pytest.mark.asyncio
    async def test_tracking_disabled(self):
        loop = LearningLoop(enable_effectiveness_tracking=False)
        assert await loop.measure_effectiveness("any") is None

    @pytest.mark.asyncio
    async def test_measure_effective(self, loop_with_pool):
        """成功率が上がった→EFFECTIVE"""
        imp = Improvement(
            id="m1", improvement_type=ImprovementType.WEIGHT_ADJUSTMENT,
            target_action="task_management", status=LearningStatus.APPLIED,
        )
        imp.applied_at = datetime.now() - timedelta(days=15)
        loop_with_pool._improvement_cache["m1"] = imp

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        before_result = MagicMock()
        before_result.mappings.return_value.first.return_value = {"successes": 6, "total": 10}
        after_result = MagicMock()
        after_result.mappings.return_value.first.return_value = {"successes": 8, "total": 10}

        mock_conn.execute.side_effect = [before_result, after_result]
        loop_with_pool.pool.connect.return_value = mock_conn

        rate = await loop_with_pool.measure_effectiveness("m1")
        assert rate == pytest.approx(0.2)
        assert imp.status == LearningStatus.EFFECTIVE

    @pytest.mark.asyncio
    async def test_measure_ineffective(self, loop_with_pool):
        """成功率が下がった→INEFFECTIVE"""
        imp = Improvement(
            id="m-bad", improvement_type=ImprovementType.WEIGHT_ADJUSTMENT,
            target_action="search", status=LearningStatus.APPLIED,
        )
        imp.applied_at = datetime.now() - timedelta(days=15)
        loop_with_pool._improvement_cache["m-bad"] = imp

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        before_result = MagicMock()
        before_result.mappings.return_value.first.return_value = {"successes": 8, "total": 10}
        after_result = MagicMock()
        after_result.mappings.return_value.first.return_value = {"successes": 5, "total": 10}

        mock_conn.execute.side_effect = [before_result, after_result]
        loop_with_pool.pool.connect.return_value = mock_conn

        rate = await loop_with_pool.measure_effectiveness("m-bad")
        assert rate == pytest.approx(-0.3)
        assert imp.status == LearningStatus.INEFFECTIVE


# =============================================================================
# 2E-6: Auto Revert Tests
# =============================================================================


class TestAutoRevert:

    @pytest.mark.asyncio
    async def test_revert_ineffective(self, loop):
        """効果なしは自動リバート"""
        imp = Improvement(
            id="ar1", improvement_type=ImprovementType.WEIGHT_ADJUSTMENT,
            target_action="test_action", weight_changes={"score": 0.1},
            status=LearningStatus.APPLIED,
        )
        imp.applied_at = datetime.now() - timedelta(days=15)
        loop._improvement_cache["ar1"] = imp
        # Apply sets status to APPLIED + caches; don't re-apply
        loop._applied_weight_adjustments["test_action"] = {"score": 0.1}

        with patch.object(loop, "measure_effectiveness", return_value=-0.1):
            reverted = await loop.check_and_auto_revert()

        assert reverted == 1
        assert imp.status == LearningStatus.REVERTED

    @pytest.mark.asyncio
    async def test_skip_recent(self, loop):
        """14日未満はスキップ"""
        imp = Improvement(
            id="recent", improvement_type=ImprovementType.WEIGHT_ADJUSTMENT,
            target_action="a", weight_changes={"s": 0.1}, status=LearningStatus.APPLIED,
        )
        imp.applied_at = datetime.now() - timedelta(days=5)
        loop._improvement_cache["recent"] = imp

        with patch.object(loop, "measure_effectiveness") as mock_m:
            assert await loop.check_and_auto_revert() == 0
            mock_m.assert_not_called()

    @pytest.mark.asyncio
    async def test_keep_effective(self, loop):
        """効果ありはリバートしない"""
        imp = Improvement(
            id="eff1", improvement_type=ImprovementType.WEIGHT_ADJUSTMENT,
            target_action="good", weight_changes={"s": 0.1}, status=LearningStatus.APPLIED,
        )
        imp.applied_at = datetime.now() - timedelta(days=15)
        loop._improvement_cache["eff1"] = imp

        with patch.object(loop, "measure_effectiveness", return_value=0.2):
            assert await loop.check_and_auto_revert() == 0


# =============================================================================
# Decision Integration Tests
# =============================================================================


class TestDecisionIntegration:

    def test_set_learned_adjustments(self):
        decision = BrainDecision(capabilities={}, org_id="test")
        adjustments = {"task_management": {"keyword_match": 0.1}}
        exceptions = [{"target_action": "search", "condition": "test"}]
        decision.set_learned_adjustments(adjustments, exceptions)
        assert decision._learned_score_adjustments == adjustments
        assert decision._learned_exceptions == exceptions

    def test_score_with_adjustment(self):
        """学習済み調整がスコアに反映"""
        decision = BrainDecision(
            capabilities={
                "test_action": {
                    "enabled": True,
                    "brain_metadata": {"decision_keywords": {"primary": ["test"]}},
                }
            },
            org_id="test",
        )
        from lib.brain.models import UnderstandingResult
        understanding = UnderstandingResult(raw_message="test keyword", intent="test_intent", intent_confidence=0.8)

        base_score = decision._score_capability(
            "test_action", decision.enabled_capabilities["test_action"], understanding,
        )
        decision._learned_score_adjustments = {"test_action": {"boost": 0.2}}
        adjusted = decision._score_capability(
            "test_action", decision.enabled_capabilities["test_action"], understanding,
        )
        assert adjusted >= base_score
        assert adjusted <= 1.0


# =============================================================================
# Guardian Integration Tests
# =============================================================================


class TestGuardianIntegration:

    def test_set_learned_rules(self):
        guardian = GuardianLayer()
        rules = [{"condition": "delete", "action": "confirm", "description": "削除確認"}]
        guardian.set_learned_rules(rules)
        assert guardian._learned_rules == rules

    @pytest.mark.asyncio
    async def test_rule_triggers_confirm(self):
        from lib.brain.llm_brain import ToolCall
        from lib.brain.context_builder import LLMContext

        guardian = GuardianLayer()
        guardian.set_learned_rules([
            {"condition": "delete", "action": "confirm", "description": "削除確認"},
        ])
        tool_call = ToolCall(tool_name="delete_task", parameters={"task_id": "123"})
        result = guardian._check_ceo_teachings(tool_call, LLMContext())
        assert result.action == GuardianAction.CONFIRM

    @pytest.mark.asyncio
    async def test_rule_triggers_block(self):
        from lib.brain.llm_brain import ToolCall
        from lib.brain.context_builder import LLMContext

        guardian = GuardianLayer()
        guardian.set_learned_rules([
            {"condition": "dangerous", "action": "block", "description": "危険操作ブロック"},
        ])
        tool_call = ToolCall(tool_name="dangerous_operation", parameters={})
        result = guardian._check_ceo_teachings(tool_call, LLMContext())
        assert result.action == GuardianAction.BLOCK

    @pytest.mark.asyncio
    async def test_no_rules_allows(self):
        from lib.brain.llm_brain import ToolCall
        from lib.brain.context_builder import LLMContext

        guardian = GuardianLayer()
        tool_call = ToolCall(tool_name="safe_action", parameters={})
        result = guardian._check_ceo_teachings(tool_call, LLMContext())
        assert result.action == GuardianAction.ALLOW


# =============================================================================
# Factory Function Test
# =============================================================================


class TestFactory:

    def test_create_learning_loop(self):
        loop = create_learning_loop(organization_id="test-org", enable_auto_apply=True)
        assert isinstance(loop, LearningLoop)
        assert loop.organization_id == "test-org"
        assert loop.enable_auto_apply is True
