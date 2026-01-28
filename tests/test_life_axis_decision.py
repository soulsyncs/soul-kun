"""
Life Axis Decision Integration テスト

v10.42.0 P2: 人生軸・価値観・長期目標とDecision Layerの統合テスト
"""

import pytest
from unittest.mock import MagicMock, patch
from lib.brain.decision import (
    BrainDecision,
    create_decision,
)
from lib.brain.models import (
    UnderstandingResult,
    BrainContext,
)


class TestLifeAxisAlignment:
    """_calculate_life_axis_alignment のテスト"""

    @pytest.fixture
    def decision(self):
        """テスト用Decisionインスタンス"""
        return create_decision(
            capabilities={
                "goal_registration": {
                    "name": "目標設定",
                    "enabled": True,
                    "brain_metadata": {
                        "decision_keywords": {
                            "primary": ["目標設定", "目標を立てたい"],
                            "secondary": ["目標"],
                            "negative": [],
                        }
                    },
                },
                "general_conversation": {
                    "name": "一般会話",
                    "enabled": True,
                    "brain_metadata": {
                        "decision_keywords": {
                            "primary": [],
                            "secondary": ["こんにちは"],
                            "negative": [],
                        }
                    },
                },
            },
            org_id="test-org",
        )

    def test_no_life_axis_returns_neutral(self, decision):
        """人生軸データがない場合はニュートラル(0.5)を返す"""
        # context=Noneの場合
        score = decision._calculate_life_axis_alignment(
            "goal_registration",
            "目標を立てたい",
            None,
        )
        assert score == 0.5

        # context.user_life_axis=Noneの場合
        context = BrainContext()
        context.user_life_axis = None
        score = decision._calculate_life_axis_alignment(
            "goal_registration",
            "目標を立てたい",
            context,
        )
        assert score == 0.5

        # 空リストの場合
        context.user_life_axis = []
        score = decision._calculate_life_axis_alignment(
            "goal_registration",
            "目標を立てたい",
            context,
        )
        assert score == 0.5

    def test_goal_alignment_increases_score(self, decision):
        """長期目標との整合性でスコアが上がる"""
        context = BrainContext()
        context.user_life_axis = [
            {
                "memory_type": "long_term_goal",
                "content": "5年以内に起業する",
            },
        ]

        # 起業に関連するメッセージ
        score = decision._calculate_life_axis_alignment(
            "goal_registration",
            "起業に向けて目標を立てたい",
            context,
        )
        # ベース0.5 + 目標整合0.3 = 0.8
        assert score >= 0.7

    def test_life_why_alignment_increases_score(self, decision):
        """人生WHYとの整合性でスコアが上がる"""
        context = BrainContext()
        context.user_life_axis = [
            {
                "memory_type": "life_why",
                "content": "人の成長を支援することで世界を良くしたい",
            },
        ]

        # 成長支援に関連するメッセージ
        score = decision._calculate_life_axis_alignment(
            "general_conversation",
            "人の成長を支援する方法を教えて",
            context,
        )
        # ベース0.5 + WHY整合0.2 = 0.7
        assert score >= 0.65

    def test_values_alignment_increases_score(self, decision):
        """価値観との整合性でスコアが上がる"""
        context = BrainContext()
        context.user_life_axis = [
            {
                "memory_type": "values",
                "content": "誠実さと正直さを大切にする",
            },
        ]

        # 価値観に関連するメッセージ
        score = decision._calculate_life_axis_alignment(
            "general_conversation",
            "誠実に対応することが大切だと思う",
            context,
        )
        # ベース0.5 + 価値観整合0.15 = 0.65
        assert score >= 0.6

    def test_anti_value_pattern_decreases_score(self, decision):
        """反価値観パターンでスコアが下がる"""
        context = BrainContext()
        context.user_life_axis = [
            {
                "memory_type": "values",
                "content": "丁寧な仕事を心がける",
            },
        ]

        # 反価値観パターンを含むメッセージ
        score = decision._calculate_life_axis_alignment(
            "general_conversation",
            "適当でいいからとりあえずやって",
            context,
        )
        # ベース0.5 - 反価値観0.2 = 0.3
        assert score <= 0.4

    def test_multiple_alignments_stack(self, decision):
        """複数の整合性が積み上がる"""
        context = BrainContext()
        context.user_life_axis = [
            {
                "memory_type": "life_why",
                "content": "技術で世界を変える",
            },
            {
                "memory_type": "long_term_goal",
                "content": "技術スタートアップを立ち上げる",
            },
            {
                "memory_type": "values",
                "content": "技術への情熱を持ち続ける",
            },
        ]

        # 複数の軸に関連するメッセージ
        score = decision._calculate_life_axis_alignment(
            "goal_registration",
            "技術スタートアップの目標を設定したい",
            context,
        )
        # ベース0.5 + 目標0.3 + WHY0.2 + 価値観0.15 = 1.15 → 1.0にクランプ
        assert score >= 0.9


class TestHasSemanticOverlap:
    """_has_semantic_overlap のテスト"""

    @pytest.fixture
    def decision(self):
        return create_decision(capabilities={}, org_id="test-org")

    def test_exact_word_match(self, decision):
        """完全一致する単語がある場合"""
        result = decision._has_semantic_overlap(
            "起業したい",
            "起業に向けて準備する",
        )
        assert result is True

    def test_no_overlap(self, decision):
        """重複がない場合"""
        result = decision._has_semantic_overlap(
            "天気を教えて",
            "技術を学ぶ",
        )
        assert result is False

    def test_partial_match_japanese(self, decision):
        """日本語の部分一致"""
        result = decision._has_semantic_overlap(
            "成長支援をしたい",
            "人の成長を手伝う",
        )
        assert result is True


class TestDecisionWithLifeAxis:
    """decide() における人生軸の影響テスト"""

    @pytest.fixture
    def mock_capabilities(self):
        return {
            "goal_registration": {
                "name": "目標設定",
                "enabled": True,
                "brain_metadata": {
                    "decision_keywords": {
                        "primary": ["目標設定", "目標を立てたい"],
                        "secondary": ["目標", "ゴール"],
                        "negative": [],
                    }
                },
            },
            "chatwork_task_create": {
                "name": "タスク作成",
                "enabled": True,
                "brain_metadata": {
                    "decision_keywords": {
                        "primary": ["タスク作成", "タスク追加"],
                        "secondary": ["タスク", "やること"],
                        "negative": [],
                    }
                },
            },
            "general_conversation": {
                "name": "一般会話",
                "enabled": True,
                "brain_metadata": {
                    "decision_keywords": {
                        "primary": [],
                        "secondary": [],
                        "negative": [],
                    }
                },
            },
        }

    @pytest.fixture
    def decision(self, mock_capabilities):
        return create_decision(
            capabilities=mock_capabilities,
            org_id="test-org",
        )

    @pytest.fixture
    def mock_understanding(self):
        return UnderstandingResult(
            intent="goal_registration",
            intent_confidence=0.8,
            entities={},
            raw_message="起業の目標を設定したい",
        )

    @pytest.mark.asyncio
    async def test_score_higher_with_aligned_life_axis(
        self, decision, mock_understanding
    ):
        """人生軸と整合するアクションのスコアが上がる"""
        # 人生軸なしのコンテキスト
        context_without_axis = MagicMock(spec=BrainContext)
        context_without_axis.has_active_session.return_value = False
        context_without_axis.user_life_axis = None

        # 人生軸ありのコンテキスト
        context_with_axis = MagicMock(spec=BrainContext)
        context_with_axis.has_active_session.return_value = False
        context_with_axis.user_life_axis = [
            {
                "memory_type": "long_term_goal",
                "content": "5年以内に起業する",
            },
        ]

        # MVVチェックをモック
        with patch.object(decision, "_check_mvv_alignment") as mock_mvv:
            from lib.brain.decision import MVVCheckResult
            mock_mvv.return_value = MVVCheckResult()

            # 人生軸なしでdecide
            result_without = await decision.decide(
                mock_understanding, context_without_axis
            )

            # 人生軸ありでdecide
            result_with = await decision.decide(
                mock_understanding, context_with_axis
            )

        # 人生軸ありの方がconfidenceが高い
        assert result_with.confidence >= result_without.confidence

    @pytest.mark.asyncio
    async def test_action_changes_with_strong_life_axis(
        self, decision
    ):
        """人生軸が強く影響する場合、選択されるアクションが変わる可能性"""
        # 曖昧なメッセージ
        understanding = UnderstandingResult(
            intent="unknown",
            intent_confidence=0.3,
            entities={},
            raw_message="成長したい",  # 目標かタスクか曖昧
        )

        # 成長を重視する人生軸
        context = MagicMock(spec=BrainContext)
        context.has_active_session.return_value = False
        context.user_life_axis = [
            {
                "memory_type": "life_why",
                "content": "自己成長を通じて世界に貢献する",
            },
            {
                "memory_type": "long_term_goal",
                "content": "成長し続けるリーダーになる",
            },
        ]

        with patch.object(decision, "_check_mvv_alignment") as mock_mvv:
            from lib.brain.decision import MVVCheckResult
            mock_mvv.return_value = MVVCheckResult()

            result = await decision.decide(understanding, context)

        # 人生軸との整合性が考慮されたアクションが選ばれる
        # （具体的なアクションは他のスコアにも依存するためここでは検証しない）
        assert result.confidence > 0


class TestScoringWeightsIntegration:
    """スコアリング重みの統合テスト"""

    @pytest.fixture
    def decision(self):
        return create_decision(
            capabilities={
                "test_action": {
                    "name": "テストアクション",
                    "enabled": True,
                    "brain_metadata": {
                        "decision_keywords": {
                            "primary": ["テスト"],
                            "secondary": [],
                            "negative": [],
                        }
                    },
                },
            },
            org_id="test-org",
        )

    def test_weights_sum_to_one(self, decision):
        """スコアリング重みの合計が1.0"""
        from lib.brain.constants import CAPABILITY_SCORING_WEIGHTS

        total = sum(CAPABILITY_SCORING_WEIGHTS.values())
        assert abs(total - 1.0) < 0.01  # 浮動小数点の誤差を許容

    def test_life_axis_weight_is_015(self, decision):
        """人生軸の重みが0.15"""
        from lib.brain.constants import CAPABILITY_SCORING_WEIGHTS

        assert CAPABILITY_SCORING_WEIGHTS.get("life_axis_alignment") == 0.15
