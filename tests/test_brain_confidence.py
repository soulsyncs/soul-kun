# tests/test_brain_confidence.py
"""
Ultimate Brain Phase 2: 確信度キャリブレーション（Confidence Calibration）のテスト
"""

import pytest
from lib.brain.confidence import (
    ConfidenceCalibrator,
    create_confidence_calibrator,
    RiskLevel,
    ConfidenceAction,
    ConfidenceAdjustment,
    CalibratedDecision,
    CONFIDENCE_THRESHOLDS,
    AMBIGUOUS_PATTERNS,
    CONFIRMATION_TEMPLATES,
)
from lib.brain.chain_of_thought import (
    ChainOfThought,
    create_chain_of_thought,
    InputType,
)


# ============================================================
# 定数テスト
# ============================================================

class TestConstants:
    """定数のテスト"""

    def test_confidence_thresholds_values(self):
        """確信度閾値が正しく定義されている"""
        assert CONFIDENCE_THRESHOLDS[RiskLevel.HIGH] == 0.85
        assert CONFIDENCE_THRESHOLDS[RiskLevel.NORMAL] == 0.70
        assert CONFIDENCE_THRESHOLDS[RiskLevel.LOW] == 0.50

    def test_confidence_thresholds_order(self):
        """リスクレベルが高いほど閾値が高い"""
        assert CONFIDENCE_THRESHOLDS[RiskLevel.HIGH] > CONFIDENCE_THRESHOLDS[RiskLevel.NORMAL]
        assert CONFIDENCE_THRESHOLDS[RiskLevel.NORMAL] > CONFIDENCE_THRESHOLDS[RiskLevel.LOW]

    def test_ambiguous_patterns_exist(self):
        """曖昧表現パターンが定義されている"""
        assert len(AMBIGUOUS_PATTERNS) > 0

    def test_confirmation_templates_exist(self):
        """確認メッセージテンプレートが定義されている"""
        assert len(CONFIRMATION_TEMPLATES) > 0


# ============================================================
# Enumテスト
# ============================================================

class TestRiskLevel:
    """RiskLevel Enumのテスト"""

    def test_values(self):
        """値が正しく定義されている"""
        assert RiskLevel.HIGH.value == "high"
        assert RiskLevel.NORMAL.value == "normal"
        assert RiskLevel.LOW.value == "low"

    def test_all_values(self):
        """全ての値が存在する"""
        assert len(RiskLevel) == 3


class TestConfidenceAction:
    """ConfidenceAction Enumのテスト"""

    def test_values(self):
        """値が正しく定義されている"""
        assert ConfidenceAction.EXECUTE.value == "execute"
        assert ConfidenceAction.CONFIRM.value == "confirm"
        assert ConfidenceAction.CLARIFY.value == "clarify"
        assert ConfidenceAction.DECLINE.value == "decline"

    def test_all_values(self):
        """全ての値が存在する"""
        assert len(ConfidenceAction) == 4


# ============================================================
# データクラステスト
# ============================================================

class TestConfidenceAdjustment:
    """ConfidenceAdjustmentデータクラスのテスト"""

    def test_creation(self):
        """正しく作成できる"""
        adj = ConfidenceAdjustment(
            factor="曖昧な表現",
            delta=-0.1,
            reasoning="「あれ」という代名詞が含まれている",
        )
        assert adj.factor == "曖昧な表現"
        assert adj.delta == -0.1
        assert "あれ" in adj.reasoning


class TestCalibratedDecision:
    """CalibratedDecisionデータクラスのテスト"""

    def test_creation_execute(self):
        """EXECUTE判定で正しく作成できる"""
        decision = CalibratedDecision(
            action=ConfidenceAction.EXECUTE,
            original_action="task_create",
            confidence=0.90,
            base_confidence=0.85,
            adjustments=[],
        )
        assert decision.action == ConfidenceAction.EXECUTE
        assert decision.confidence == 0.90

    def test_creation_confirm(self):
        """CONFIRM判定で正しく作成できる"""
        decision = CalibratedDecision(
            action=ConfidenceAction.CONFIRM,
            original_action="task_complete",
            confidence=0.60,
            base_confidence=0.65,
            adjustments=[],
            confirmation_message="タスクを完了にしますか？",
        )
        assert decision.action == ConfidenceAction.CONFIRM
        assert decision.confirmation_message is not None


# ============================================================
# ConfidenceCalibratorテスト
# ============================================================

class TestConfidenceCalibratorInit:
    """ConfidenceCalibrator初期化のテスト"""

    def test_create_default(self):
        """デフォルト設定で作成できる"""
        calibrator = create_confidence_calibrator()
        assert calibrator is not None

    def test_create_with_custom_thresholds(self):
        """カスタム閾値で作成できる"""
        custom = {
            RiskLevel.HIGH: 0.90,
            RiskLevel.NORMAL: 0.75,
            RiskLevel.LOW: 0.55,
        }
        calibrator = create_confidence_calibrator(custom_thresholds=custom)
        assert calibrator is not None


class TestConfidenceCalibratorCalibrate:
    """ConfidenceCalibrator.calibrate()のテスト"""

    def test_calibrate_with_thought_chain(self):
        """思考連鎖を使ってキャリブレーションできる"""
        calibrator = create_confidence_calibrator()
        cot = create_chain_of_thought()

        # 思考連鎖を実行
        chain = cot.analyze("タスクを作成して")

        # キャリブレーション
        result = calibrator.calibrate(
            thought_chain=chain,
            action="task_create",
        )

        assert result is not None
        assert isinstance(result.action, ConfidenceAction)
        assert 0.0 <= result.confidence <= 1.0

    def test_high_confidence_executes(self):
        """高確信度ならEXECUTEの可能性が高い"""
        calibrator = create_confidence_calibrator()
        cot = create_chain_of_thought()

        # 明確なコマンド
        chain = cot.analyze("新しいタスクを作成してください")
        result = calibrator.calibrate(
            thought_chain=chain,
            action="task_create",
        )

        # 明確な依頼は確信度が高いはず
        assert result.confidence >= 0.5


class TestConfidenceCalibratorRiskLevel:
    """リスクレベル判定のテスト"""

    def test_get_risk_level(self):
        """リスクレベルを取得できる"""
        calibrator = create_confidence_calibrator()

        # 高リスク
        assert calibrator._get_risk_level("task_complete") == RiskLevel.HIGH
        assert calibrator._get_risk_level("forget_knowledge") == RiskLevel.HIGH

        # 低リスク
        assert calibrator._get_risk_level("query_knowledge") == RiskLevel.LOW
        assert calibrator._get_risk_level("general_conversation") == RiskLevel.LOW


# ============================================================
# ファクトリ関数テスト
# ============================================================

class TestFactory:
    """ファクトリ関数のテスト"""

    def test_create_confidence_calibrator(self):
        """create_confidence_calibratorが正しく動作する"""
        calibrator = create_confidence_calibrator()
        assert isinstance(calibrator, ConfidenceCalibrator)

    def test_factory_returns_instance(self):
        """ファクトリがConfidenceCalibratorインスタンスを返す"""
        result = create_confidence_calibrator()
        assert isinstance(result, ConfidenceCalibrator)
