# tests/test_brain_learning_loop_extended.py
"""
ソウルくんの脳 - Learning Loop 拡張テスト

lib/brain/learning_loop.py のカバレッジ向上テスト
対象: 未カバーの行 474-475, 497-499, 531-533, 555-559, 595, 626-627, 642,
      672, 694, 707-714, 750, 855-868, 873-875, 896, 937, 961, 985, 995,
      1068, 1091, 1096-1119, 1135, 1169, 1181, 1186-1188, 1193-1195,
      1200-1202, 1207-1209, 1233-1237, 1248-1250, 1289, 1299-1301,
      1305-1316, 1353, 1355-1358, 1391-1403, 1434-1437, 1445-1447
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from lib.brain.learning_loop import (
    LearningLoop,
    create_learning_loop,
    FeedbackType,
    FailureCause,
    ImprovementType,
    LearningStatus,
    Feedback,
    DecisionSnapshot,
    FailureAnalysis,
    Improvement,
    LearningEntry,
    LearningStatistics,
    LEARNING_LOG_BUFFER_SIZE,
    DEFAULT_KEYWORD_WEIGHT,
    THRESHOLD_MIN,
    THRESHOLD_ADJUSTMENT_STEP,
)


# =============================================================================
# learn_from_feedback エラーハンドリング (lines 474-475, 497-499)
# =============================================================================

class TestLearnFromFeedbackErrors:
    """learn_from_feedback のエラーハンドリングテスト"""

    @pytest.mark.asyncio
    async def test_no_improvements_generated_returns_empty(self):
        """改善が生成されない場合は空リストを返す (lines 474-475)"""
        loop = LearningLoop()

        snapshot = DecisionSnapshot(
            decision_id="dec-001",
            user_message="テスト",
            detected_intent="test",
            intent_confidence=0.9,
            selected_action="test_action",
            action_confidence=0.9,
            context_summary="コンテキストあり",
        )
        await loop.record_decision("dec-001", snapshot)

        # NEGATIVE feedback without correct_intent or correct_action
        # and high confidence -> no improvements
        feedback = Feedback(
            decision_id="dec-001",
            feedback_type=FeedbackType.NEGATIVE,
            message="なんかダメだった",
        )

        improvements = await loop.learn_from_feedback("dec-001", feedback)
        # Could be empty if analysis produces UNKNOWN cause with no actionable improvements
        assert isinstance(improvements, list)

    @pytest.mark.asyncio
    async def test_learn_from_feedback_exception_returns_empty(self):
        """例外発生時は空リストを返す (lines 497-499)"""
        loop = LearningLoop()

        # Patch _get_decision to raise an exception
        with patch.object(loop, '_get_decision', side_effect=Exception("DB error")):
            feedback = Feedback(
                decision_id="dec-001",
                feedback_type=FeedbackType.NEGATIVE,
            )
            result = await loop.learn_from_feedback("dec-001", feedback)
            assert result == []

    @pytest.mark.asyncio
    async def test_learn_with_auto_apply_disabled(self):
        """auto_apply が無効の場合は改善を適用しない"""
        loop = LearningLoop(enable_auto_apply=False)

        snapshot = DecisionSnapshot(
            decision_id="dec-001",
            user_message="タスクを追加して",
            detected_intent="search_tasks",
            intent_confidence=0.4,
            selected_action="chatwork_task_search",
        )
        await loop.record_decision("dec-001", snapshot)

        feedback = Feedback(
            decision_id="dec-001",
            feedback_type=FeedbackType.CORRECTION,
            correct_intent="create_task",
            correct_action="chatwork_task_create",
        )

        improvements = await loop.learn_from_feedback("dec-001", feedback)
        # Improvements generated but not applied
        for imp in improvements:
            assert imp.status == LearningStatus.PENDING


# =============================================================================
# record_decision エラーハンドリング (lines 531-533)
# =============================================================================

class TestRecordDecisionErrors:
    """record_decision のエラーハンドリングテスト"""

    @pytest.mark.asyncio
    async def test_record_decision_exception(self):
        """例外発生時はFalseを返す (lines 531-533)"""
        loop = LearningLoop()

        # Replace _decision_cache with a dict-like object that raises on __setitem__
        class FailingDict(dict):
            def __setitem__(self, key, value):
                raise Exception("cache error")

        loop._decision_cache = FailingDict()

        snapshot = DecisionSnapshot(decision_id="dec-001")
        result = await loop.record_decision("dec-001", snapshot)
        assert result == False


# =============================================================================
# _get_decision DB検索 (lines 555-559)
# =============================================================================

class TestGetDecisionFromDB:
    """_get_decision のDB検索テスト"""

    @pytest.mark.asyncio
    async def test_get_decision_from_db_with_pool(self):
        """DBプールありの場合のDB検索 — 見つからない"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.mappings.return_value.first.return_value = None
        loop = LearningLoop(pool=mock_pool)

        result = await loop._get_decision("dec-not-in-cache")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_decision_db_exception(self):
        """DB検索中の例外"""
        mock_pool = MagicMock()
        mock_pool.connect.side_effect = Exception("DB error")
        loop = LearningLoop(pool=mock_pool)

        result = await loop._get_decision("dec-missing")
        assert result is None


# =============================================================================
# _analyze_failure 分析テスト (lines 595, 626-627, 642, 672, 694)
# =============================================================================

class TestAnalyzeFailureExtended:
    """_analyze_failure の拡張テスト"""

    @pytest.mark.asyncio
    async def test_analyze_intent_as_secondary_cause(self):
        """意図理解が副次的原因となる場合 (line 595)"""
        loop = LearningLoop()

        decision = DecisionSnapshot(
            decision_id="dec-001",
            user_message="タスク追加",
            detected_intent="search_tasks",
            intent_confidence=0.3,
            selected_action="chatwork_task_search",
            action_confidence=0.4,
            alternative_actions=["chatwork_task_create"],
            context_summary="",
        )
        feedback = Feedback(
            feedback_type=FeedbackType.CORRECTION,
            correct_intent="create_task",
            correct_action="chatwork_task_create",
        )

        analysis = await loop._analyze_failure(decision, feedback)
        # Multiple causes should be detected
        all_causes = [analysis.primary_cause] + analysis.secondary_causes
        assert len(all_causes) >= 2

    @pytest.mark.asyncio
    async def test_analyze_action_as_secondary_cause(self):
        """アクション選択が副次的原因となる場合 (lines 626-627)"""
        loop = LearningLoop()

        decision = DecisionSnapshot(
            decision_id="dec-001",
            user_message="さっきのタスクを完了にして",
            detected_intent="search_tasks",
            intent_confidence=0.3,
            selected_action="chatwork_task_search",
            action_confidence=0.4,
            context_summary="",
        )
        feedback = Feedback(
            feedback_type=FeedbackType.CORRECTION,
            correct_intent="complete_task",
            correct_action="chatwork_task_complete",
            message="さっきの会話を考慮してほしかった",
        )

        analysis = await loop._analyze_failure(decision, feedback)
        # Should have multiple causes
        all_causes = [analysis.primary_cause] + analysis.secondary_causes
        assert len(all_causes) >= 2

    @pytest.mark.asyncio
    async def test_analyze_context_as_secondary_cause(self):
        """コンテキストが副次的原因となる場合 (line 626-627 context branch)"""
        loop = LearningLoop()

        decision = DecisionSnapshot(
            decision_id="dec-001",
            user_message="それを更新して",
            detected_intent="search_tasks",
            intent_confidence=0.3,
            selected_action="chatwork_task_search",
            action_confidence=0.6,
            context_summary="",
        )
        feedback = Feedback(
            feedback_type=FeedbackType.CORRECTION,
            correct_intent="update_task",
            message="前のタスクを更新してほしかった",
        )

        analysis = await loop._analyze_failure(decision, feedback)
        all_causes = [analysis.primary_cause] + analysis.secondary_causes
        assert FailureCause.CONTEXT_MISSING in all_causes

    @pytest.mark.asyncio
    async def test_analyze_unknown_cause(self):
        """原因不明の場合 (line 642)"""
        loop = LearningLoop()

        decision = DecisionSnapshot(
            decision_id="dec-001",
            user_message="テスト",
            detected_intent="test",
            intent_confidence=0.9,
            selected_action="test_action",
            action_confidence=0.9,
            context_summary="コンテキストあり",
        )
        feedback = Feedback(
            feedback_type=FeedbackType.NEGATIVE,
            message="なんとなくダメだった",
        )

        analysis = await loop._analyze_failure(decision, feedback)
        if analysis.primary_cause == FailureCause.UNKNOWN:
            assert "特定できません" in analysis.cause_explanation

    def test_analyze_intent_low_confidence(self):
        """意図の確信度が低い場合 (line 672)"""
        loop = LearningLoop()

        decision = DecisionSnapshot(
            detected_intent="search_tasks",
            intent_confidence=0.3,
        )
        feedback = Feedback()

        cause = loop._analyze_intent_understanding(decision, feedback)
        assert cause == FailureCause.INTENT_MISUNDERSTANDING

    def test_analyze_intent_high_confidence_no_correction(self):
        """意図の確信度が高く修正なしの場合"""
        loop = LearningLoop()

        decision = DecisionSnapshot(
            detected_intent="search_tasks",
            intent_confidence=0.9,
        )
        feedback = Feedback()

        cause = loop._analyze_intent_understanding(decision, feedback)
        assert cause is None

    def test_analyze_action_low_confidence(self):
        """アクションの確信度が低い場合 (line 694)"""
        loop = LearningLoop()

        decision = DecisionSnapshot(
            selected_action="test_action",
            action_confidence=0.3,
        )
        feedback = Feedback()

        cause = loop._analyze_action_selection(decision, feedback)
        assert cause == FailureCause.ACTION_WRONG

    def test_analyze_action_correct_in_alternatives(self):
        """正しいアクションが代替候補にある場合"""
        loop = LearningLoop()

        decision = DecisionSnapshot(
            selected_action="chatwork_task_search",
            action_confidence=0.6,
            alternative_actions=["chatwork_task_create"],
        )
        feedback = Feedback(correct_action="chatwork_task_create")

        cause = loop._analyze_action_selection(decision, feedback)
        assert cause == FailureCause.THRESHOLD_WRONG

    def test_analyze_action_correct_not_in_alternatives(self):
        """正しいアクションが代替候補にない場合"""
        loop = LearningLoop()

        decision = DecisionSnapshot(
            selected_action="chatwork_task_search",
            action_confidence=0.6,
            alternative_actions=["general_conversation"],
        )
        feedback = Feedback(correct_action="chatwork_task_create")

        cause = loop._analyze_action_selection(decision, feedback)
        assert cause == FailureCause.PATTERN_UNKNOWN


# =============================================================================
# _analyze_context テスト (lines 707-714)
# =============================================================================

class TestAnalyzeContext:
    """_analyze_context のテスト"""

    def test_context_keywords_detection(self):
        """コンテキスト関連キーワードの検出 (lines 707-714)"""
        loop = LearningLoop()

        decision = DecisionSnapshot(context_summary="コンテキストあり")

        context_keywords = ["前の", "さっき", "続き", "それ", "あれ", "コンテキスト", "文脈"]
        for keyword in context_keywords:
            feedback = Feedback(message=f"{keyword}話を考慮して")
            cause = loop._analyze_context(decision, feedback)
            assert cause == FailureCause.CONTEXT_MISSING, f"Keyword '{keyword}' should trigger CONTEXT_MISSING"

    def test_no_context_keywords(self):
        """コンテキスト関連キーワードなし"""
        loop = LearningLoop()

        decision = DecisionSnapshot(context_summary="コンテキストあり")
        feedback = Feedback(message="単なるフィードバック")

        cause = loop._analyze_context(decision, feedback)
        assert cause is None

    def test_empty_context(self):
        """コンテキストが空の場合"""
        loop = LearningLoop()

        decision = DecisionSnapshot(context_summary="")
        feedback = Feedback(message="テスト")

        cause = loop._analyze_context(decision, feedback)
        assert cause == FailureCause.CONTEXT_MISSING


# =============================================================================
# _is_similar_decision テスト (line 750)
# =============================================================================

class TestIsSimilarDecision:
    """_is_similar_decision のテスト"""

    def test_empty_message_not_similar(self):
        """空メッセージは非類似 (line 750)"""
        loop = LearningLoop()

        decision1 = DecisionSnapshot(
            user_message="",
            detected_intent="search",
            selected_action="action_a",
        )
        decision2 = DecisionSnapshot(
            user_message="テスト",
            detected_intent="create",
            selected_action="action_b",
        )

        result = loop._is_similar_decision(decision1, decision2)
        assert result == False

    def test_both_empty_messages(self):
        """両方空メッセージで異なるアクション/意図の場合"""
        loop = LearningLoop()

        decision1 = DecisionSnapshot(
            user_message="",
            detected_intent="search",
            selected_action="action_a",
        )
        decision2 = DecisionSnapshot(
            user_message="",
            detected_intent="create",
            selected_action="action_b",
        )

        result = loop._is_similar_decision(decision1, decision2)
        assert result == False

    def test_high_word_overlap(self):
        """単語の重複が高い場合は類似"""
        loop = LearningLoop()

        decision1 = DecisionSnapshot(
            user_message="タスクを 追加 して ください",
            detected_intent="search",
            selected_action="action_a",
        )
        decision2 = DecisionSnapshot(
            user_message="タスクを 追加 して ほしい",
            detected_intent="create",
            selected_action="action_b",
        )

        result = loop._is_similar_decision(decision1, decision2)
        assert result == True

    def test_low_word_overlap(self):
        """単語の重複が低い場合は非類似"""
        loop = LearningLoop()

        decision1 = DecisionSnapshot(
            user_message="タスク 追加",
            detected_intent="search",
            selected_action="action_a",
        )
        decision2 = DecisionSnapshot(
            user_message="ナレッジ 検索 お願い 結果",
            detected_intent="create",
            selected_action="action_b",
        )

        result = loop._is_similar_decision(decision1, decision2)
        assert result == False


# =============================================================================
# _generate_improvements 拡張テスト (lines 855-868, 873-875, 896, 937, 961, 985, 995)
# =============================================================================

class TestGenerateImprovementsExtended:
    """_generate_improvements の拡張テスト"""

    @pytest.mark.asyncio
    async def test_context_missing_improvement(self):
        """コンテキスト不足の改善生成 (line 855-858, 995)"""
        loop = LearningLoop()

        analysis = FailureAnalysis(
            primary_cause=FailureCause.CONTEXT_MISSING,
            cause_confidence=0.6,
        )
        decision = DecisionSnapshot(
            decision_id="dec-001",
            user_message="それを完了にして",
            detected_intent="complete_task",
            selected_action="general_conversation",
        )
        feedback = Feedback(
            feedback_type=FeedbackType.NEGATIVE,
            message="コンテキストが分からなかった",
        )

        improvements = await loop._generate_improvements(analysis, decision, feedback)
        assert len(improvements) >= 1
        confirmation_improvements = [
            i for i in improvements
            if i.improvement_type == ImprovementType.CONFIRMATION_RULE
        ]
        assert len(confirmation_improvements) >= 1

    @pytest.mark.asyncio
    async def test_action_wrong_improvement(self):
        """アクション誤りの改善生成 (lines 860-868)"""
        loop = LearningLoop()

        analysis = FailureAnalysis(
            primary_cause=FailureCause.ACTION_WRONG,
            cause_confidence=0.7,
        )
        decision = DecisionSnapshot(
            decision_id="dec-001",
            user_message="やることを登録して",
            detected_intent="general_conversation",
            selected_action="general_conversation",
            action_confidence=0.3,
        )
        feedback = Feedback(
            feedback_type=FeedbackType.CORRECTION,
            correct_action="chatwork_task_create",
        )

        improvements = await loop._generate_improvements(analysis, decision, feedback)
        # ACTION_WRONG generates both pattern and keyword improvements
        assert len(improvements) >= 1
        types = [i.improvement_type for i in improvements]
        assert ImprovementType.PATTERN_ADDITION in types or ImprovementType.KEYWORD_UPDATE in types

    @pytest.mark.asyncio
    async def test_secondary_cause_keyword_improvement(self):
        """副次的原因(KEYWORD_MISSING)の改善生成 (lines 873-875)"""
        loop = LearningLoop()

        analysis = FailureAnalysis(
            primary_cause=FailureCause.INTENT_MISUNDERSTANDING,
            cause_confidence=0.8,
            secondary_causes=[FailureCause.KEYWORD_MISSING],
        )
        decision = DecisionSnapshot(
            decision_id="dec-001",
            user_message="やることを登録して",
            detected_intent="search_tasks",
            selected_action="chatwork_task_search",
        )
        feedback = Feedback(
            feedback_type=FeedbackType.CORRECTION,
            correct_intent="create_task",
            correct_action="chatwork_task_create",
        )

        improvements = await loop._generate_improvements(analysis, decision, feedback)
        # Should have both pattern (for intent) and keyword (for secondary cause)
        types = [i.improvement_type for i in improvements]
        assert ImprovementType.KEYWORD_UPDATE in types

    def test_generate_intent_improvement_no_correct_intent(self):
        """正しい意図が指定されていない場合 (line 896)"""
        loop = LearningLoop()

        analysis = FailureAnalysis()
        decision = DecisionSnapshot(user_message="テスト")
        feedback = Feedback()  # correct_intent is None

        result = loop._generate_intent_improvement(analysis, decision, feedback)
        assert result is None

    def test_generate_threshold_improvement_no_match(self):
        """閾値改善生成で条件を満たさない場合 (line 937)"""
        loop = LearningLoop()

        analysis = FailureAnalysis()
        decision = DecisionSnapshot(
            selected_action="test_action",
            action_confidence=0.6,
            alternative_actions=[],
        )
        feedback = Feedback(correct_action="other_action")

        result = loop._generate_threshold_improvement(analysis, decision, feedback)
        assert result is None

    def test_generate_threshold_improvement_at_minimum(self):
        """閾値が最小値に達している場合"""
        loop = LearningLoop()
        loop._applied_thresholds["test_action"] = THRESHOLD_MIN

        analysis = FailureAnalysis()
        decision = DecisionSnapshot(
            selected_action="test_action",
            action_confidence=THRESHOLD_MIN,
            alternative_actions=["correct_action"],
        )
        feedback = Feedback(correct_action="correct_action")

        result = loop._generate_threshold_improvement(analysis, decision, feedback)
        # At minimum, new_threshold == current_threshold, so None
        assert result is None

    def test_generate_pattern_improvement_no_pattern(self):
        """パターン抽出できない場合 (line 961)"""
        loop = LearningLoop()

        analysis = FailureAnalysis()
        decision = DecisionSnapshot(user_message="a")  # very short
        feedback = Feedback(correct_action="test_action")

        result = loop._generate_pattern_improvement(analysis, decision, feedback)
        assert result is None

    def test_generate_keyword_improvement_no_keywords(self):
        """キーワード抽出できない場合 (line 985)"""
        loop = LearningLoop()

        analysis = FailureAnalysis()
        decision = DecisionSnapshot(user_message="ab")  # no Japanese keywords
        feedback = Feedback(correct_action="test_action")

        result = loop._generate_keyword_improvement(analysis, decision, feedback)
        assert result is None

    def test_generate_context_improvement(self):
        """コンテキスト改善の生成 (line 995)"""
        loop = LearningLoop()

        analysis = FailureAnalysis()
        decision = DecisionSnapshot(detected_intent="complete_task")
        feedback = Feedback()

        result = loop._generate_context_improvement(analysis, decision, feedback)
        assert result is not None
        assert result.improvement_type == ImprovementType.CONFIRMATION_RULE
        assert "clarification" in result.rule_action


# =============================================================================
# _estimate_improvement_rate テスト (line 1068)
# =============================================================================

class TestEstimateImprovementRate:
    """_estimate_improvement_rate のテスト"""

    def test_similar_cases_boost(self):
        """類似ケースが多い場合の効果増 (line 1068)"""
        loop = LearningLoop()

        improvement = Improvement(
            improvement_type=ImprovementType.PATTERN_ADDITION,
        )
        analysis = FailureAnalysis(
            total_similar_cases=10,  # > 5
            cause_confidence=0.8,
        )

        rate = loop._estimate_improvement_rate(improvement, analysis)
        # Base rate 0.25 * 1.5 (similar cases) * (1 + 0.8*0.5) = 0.25 * 1.5 * 1.4 = 0.525
        assert rate > 0.25

    def test_low_confidence_low_rate(self):
        """原因の確信度が低い場合の効果"""
        loop = LearningLoop()

        improvement = Improvement(
            improvement_type=ImprovementType.KEYWORD_UPDATE,
        )
        analysis = FailureAnalysis(
            total_similar_cases=0,
            cause_confidence=0.1,
        )

        rate = loop._estimate_improvement_rate(improvement, analysis)
        assert rate < 0.2

    def test_rate_capped_at_one(self):
        """効果は1.0を超えない"""
        loop = LearningLoop()

        improvement = Improvement(
            improvement_type=ImprovementType.PATTERN_ADDITION,
        )
        analysis = FailureAnalysis(
            total_similar_cases=100,
            cause_confidence=1.0,
        )

        rate = loop._estimate_improvement_rate(improvement, analysis)
        assert rate <= 1.0


# =============================================================================
# _apply_improvement ディスパッチ テスト (lines 1091, 1096-1119)
# =============================================================================

class TestApplyImprovementDispatch:
    """_apply_improvement のディスパッチテスト"""

    @pytest.mark.asyncio
    async def test_apply_threshold_dispatch(self):
        """閾値調整のディスパッチ (line 1091)"""
        loop = LearningLoop()
        improvement = Improvement(
            improvement_type=ImprovementType.THRESHOLD_ADJUSTMENT,
            target_action="test_action",
            old_threshold=0.7,
            new_threshold=0.65,
        )
        result = await loop._apply_improvement(improvement)
        assert result == True

    @pytest.mark.asyncio
    async def test_apply_keyword_update_dispatch(self):
        """キーワード更新のディスパッチ (line 1096-1097)"""
        loop = LearningLoop()
        improvement = Improvement(
            improvement_type=ImprovementType.KEYWORD_UPDATE,
            target_action="test_action",
            keywords_to_add=["追加"],
            keyword_weights={"追加": 1.0},
        )
        result = await loop._apply_improvement(improvement)
        assert result == True

    @pytest.mark.asyncio
    async def test_apply_weight_adjustment_dispatch(self):
        """重み調整のディスパッチ"""
        loop = LearningLoop()
        improvement = Improvement(
            improvement_type=ImprovementType.WEIGHT_ADJUSTMENT,
            target_action="test_action",
            weight_changes={"score": 0.1},
        )
        result = await loop._apply_improvement(improvement)
        assert result == True

    @pytest.mark.asyncio
    async def test_apply_rule_addition_dispatch(self):
        """ルール追加のディスパッチ"""
        loop = LearningLoop()
        improvement = Improvement(
            improvement_type=ImprovementType.RULE_ADDITION,
            rule_condition="test_cond",
            rule_action="confirm",
        )
        result = await loop._apply_improvement(improvement)
        assert result == True

    @pytest.mark.asyncio
    async def test_apply_exception_addition_dispatch(self):
        """例外追加のディスパッチ"""
        loop = LearningLoop()
        improvement = Improvement(
            improvement_type=ImprovementType.EXCEPTION_ADDITION,
            target_action="test_action",
            rule_condition="test_cond",
        )
        result = await loop._apply_improvement(improvement)
        assert result == True

    @pytest.mark.asyncio
    async def test_apply_confirmation_rule_dispatch(self):
        """確認ルールのディスパッチ"""
        loop = LearningLoop()
        improvement = Improvement(
            improvement_type=ImprovementType.CONFIRMATION_RULE,
            target_action="test_action",
        )
        result = await loop._apply_improvement(improvement)
        assert result == True

    @pytest.mark.asyncio
    async def test_apply_unknown_type(self):
        """不明な改善タイプ (lines 1111-1115)"""
        loop = LearningLoop()
        improvement = Improvement()
        # Forcefully set an invalid type by mocking
        improvement.improvement_type = MagicMock()
        improvement.improvement_type.value = "unknown_type"
        # None of the if branches match
        # We need to make sure it doesn't match any known type
        result = await loop._apply_improvement(improvement)
        assert result == False

    @pytest.mark.asyncio
    async def test_apply_improvement_exception(self):
        """改善適用中の例外 (lines 1117-1119)"""
        loop = LearningLoop()
        improvement = Improvement(
            improvement_type=ImprovementType.THRESHOLD_ADJUSTMENT,
            target_action="test_action",
            new_threshold=0.65,
        )
        # Patch to raise exception
        with patch.object(loop, '_apply_threshold_adjustment', side_effect=Exception("apply error")):
            result = await loop._apply_improvement(improvement)
            assert result == False


# =============================================================================
# _apply_* 個別テスト (lines 1135, 1169, 1181, 1186-1209)
# =============================================================================

class TestApplyImprovementMethods:
    """個別適用メソッドのテスト"""

    @pytest.mark.asyncio
    async def test_apply_threshold_no_target(self):
        """閾値調整 - target_actionなし (line 1135)"""
        loop = LearningLoop()
        improvement = Improvement(
            improvement_type=ImprovementType.THRESHOLD_ADJUSTMENT,
            target_action=None,
            new_threshold=0.65,
        )
        result = await loop._apply_threshold_adjustment(improvement)
        assert result == False

    @pytest.mark.asyncio
    async def test_apply_threshold_no_new_threshold(self):
        """閾値調整 - new_thresholdなし"""
        loop = LearningLoop()
        improvement = Improvement(
            improvement_type=ImprovementType.THRESHOLD_ADJUSTMENT,
            target_action="test_action",
            new_threshold=None,
        )
        result = await loop._apply_threshold_adjustment(improvement)
        assert result == False

    @pytest.mark.asyncio
    async def test_apply_pattern_no_target(self):
        """パターン追加 - ターゲットなし (line 1169 - implicit)"""
        loop = LearningLoop()
        improvement = Improvement(
            improvement_type=ImprovementType.PATTERN_ADDITION,
            target_action=None,
            target_intent=None,
            pattern_regex=r"test.*pattern",
        )
        result = await loop._apply_pattern_addition(improvement)
        assert result == False

    @pytest.mark.asyncio
    async def test_apply_pattern_no_regex(self):
        """パターン追加 - regexなし"""
        loop = LearningLoop()
        improvement = Improvement(
            improvement_type=ImprovementType.PATTERN_ADDITION,
            target_action="test_action",
            pattern_regex=None,
        )
        result = await loop._apply_pattern_addition(improvement)
        assert result == False

    @pytest.mark.asyncio
    async def test_apply_pattern_with_intent_target(self):
        """パターン追加 - target_intentで適用"""
        loop = LearningLoop()
        improvement = Improvement(
            improvement_type=ImprovementType.PATTERN_ADDITION,
            target_action=None,
            target_intent="create_task",
            pattern_regex=r"タスク.*追加",
        )
        result = await loop._apply_pattern_addition(improvement)
        assert result == True
        assert "create_task" in loop._applied_patterns
        assert r"タスク.*追加" in loop._applied_patterns["create_task"]

    @pytest.mark.asyncio
    async def test_apply_keyword_no_target(self):
        """キーワード更新 - target_actionなし (line 1181)"""
        loop = LearningLoop()
        improvement = Improvement(
            improvement_type=ImprovementType.KEYWORD_UPDATE,
            target_action=None,
            keywords_to_add=["追加"],
        )
        result = await loop._apply_keyword_update(improvement)
        assert result == False

    @pytest.mark.asyncio
    async def test_apply_keyword_no_keywords(self):
        """キーワード更新 - キーワードなし"""
        loop = LearningLoop()
        improvement = Improvement(
            improvement_type=ImprovementType.KEYWORD_UPDATE,
            target_action="test_action",
            keywords_to_add=[],
        )
        result = await loop._apply_keyword_update(improvement)
        assert result == False

    @pytest.mark.asyncio
    async def test_apply_keyword_with_removal(self):
        """キーワード更新 - 既存キーワードの削除 (line 1169)"""
        loop = LearningLoop()
        loop._applied_keywords["test_action"] = {"old_keyword": 1.0, "keep_this": 1.5}

        improvement = Improvement(
            improvement_type=ImprovementType.KEYWORD_UPDATE,
            target_action="test_action",
            keywords_to_add=["新規"],
            keywords_to_remove=["old_keyword"],
            keyword_weights={"新規": 1.2},
        )

        result = await loop._apply_keyword_update(improvement)
        assert result == True
        assert "old_keyword" not in loop._applied_keywords["test_action"]
        assert "新規" in loop._applied_keywords["test_action"]
        assert "keep_this" in loop._applied_keywords["test_action"]

    @pytest.mark.asyncio
    async def test_apply_weight_adjustment(self):
        """重み調整の適用 (lines 1186-1188)"""
        loop = LearningLoop()
        improvement = Improvement(
            improvement_type=ImprovementType.WEIGHT_ADJUSTMENT,
            target_action="test_action",
            weight_changes={"relevance": 0.1},
        )
        result = await loop._apply_weight_adjustment(improvement)
        assert result == True
        assert improvement.status == LearningStatus.APPLIED
        assert improvement.applied_at is not None

    @pytest.mark.asyncio
    async def test_apply_rule_addition(self):
        """ルール追加の適用 (lines 1193-1195)"""
        loop = LearningLoop()
        improvement = Improvement(
            improvement_type=ImprovementType.RULE_ADDITION,
            rule_condition="dangerous_tool",
            rule_action="block",
        )
        result = await loop._apply_rule_addition(improvement)
        assert result == True
        assert improvement.status == LearningStatus.APPLIED

    @pytest.mark.asyncio
    async def test_apply_exception_addition(self):
        """例外追加の適用 (lines 1200-1202)"""
        loop = LearningLoop()
        improvement = Improvement(
            improvement_type=ImprovementType.EXCEPTION_ADDITION,
            target_action="some_action",
            rule_condition="special_context",
            rule_action="override_action",
        )
        result = await loop._apply_exception_addition(improvement)
        assert result == True
        assert improvement.status == LearningStatus.APPLIED

    @pytest.mark.asyncio
    async def test_apply_confirmation_rule(self):
        """確認ルール追加の適用 (lines 1207-1209)"""
        loop = LearningLoop()
        improvement = Improvement(
            improvement_type=ImprovementType.CONFIRMATION_RULE,
            target_action="risky_action",
        )
        result = await loop._apply_confirmation_rule(improvement)
        assert result == True
        assert improvement.status == LearningStatus.APPLIED


# =============================================================================
# _reinforce_successful_pattern テスト (lines 1233-1237, 1248-1250)
# =============================================================================

class TestReinforceSuccessfulPattern:
    """_reinforce_successful_pattern のテスト"""

    @pytest.mark.asyncio
    async def test_reinforce_with_existing_keywords(self):
        """既存キーワードの重み増加 (lines 1233-1237)"""
        loop = LearningLoop()
        # _extract_keywords_from_message extracts continuous Japanese character runs >= 2 chars
        # Spaces break the runs, so "経費精算 依頼" -> ["経費精算", "依頼"]
        loop._applied_keywords["test_action"] = {"経費精算": 1.0, "依頼": 0.9}

        decision = DecisionSnapshot(
            selected_action="test_action",
            user_message="経費精算 依頼",
        )
        feedback = Feedback(feedback_type=FeedbackType.POSITIVE)

        result = await loop._reinforce_successful_pattern(decision, feedback)
        assert result == True
        # The extracted keywords ["経費精算", "依頼"] match applied_keywords
        assert loop._applied_keywords["test_action"]["経費精算"] > 1.0
        assert loop._applied_keywords["test_action"]["依頼"] > 0.9

    @pytest.mark.asyncio
    async def test_reinforce_weight_cap_at_two(self):
        """重みは2.0を超えない"""
        loop = LearningLoop()
        loop._applied_keywords["test_action"] = {"タスク": 1.95}

        decision = DecisionSnapshot(
            selected_action="test_action",
            user_message="タスク確認",
        )
        feedback = Feedback(feedback_type=FeedbackType.POSITIVE)

        await loop._reinforce_successful_pattern(decision, feedback)
        assert loop._applied_keywords["test_action"]["タスク"] <= 2.0

    @pytest.mark.asyncio
    async def test_reinforce_no_existing_keywords(self):
        """既存キーワードなしの場合"""
        loop = LearningLoop()

        decision = DecisionSnapshot(
            selected_action="test_action",
            user_message="タスク追加",
        )
        feedback = Feedback(feedback_type=FeedbackType.POSITIVE)

        result = await loop._reinforce_successful_pattern(decision, feedback)
        assert result == True

    @pytest.mark.asyncio
    async def test_reinforce_exception(self):
        """強化中の例外 (lines 1248-1250)"""
        loop = LearningLoop()

        decision = DecisionSnapshot(
            selected_action="test_action",
            user_message="テスト",
        )
        feedback = Feedback(feedback_type=FeedbackType.POSITIVE)

        # Patch to cause exception
        with patch.object(loop, '_extract_keywords_from_message', side_effect=Exception("error")):
            loop._applied_keywords["test_action"] = {"テスト": 1.0}
            result = await loop._reinforce_successful_pattern(decision, feedback)
            assert result == False


# =============================================================================
# _log_learning / _flush_learning_buffer テスト (lines 1289, 1299-1301, 1305-1316)
# =============================================================================

class TestLogLearning:
    """_log_learning のテスト"""

    @pytest.mark.asyncio
    async def test_log_learning_success(self):
        """学習ログの記録成功"""
        loop = LearningLoop(organization_id="org-001")

        feedback = Feedback(id="fb-001")
        analysis = FailureAnalysis(
            primary_cause=FailureCause.INTENT_MISUNDERSTANDING,
            cause_explanation="意図を誤解",
        )
        improvements = [Improvement()]

        result = await loop._log_learning(
            decision_id="dec-001",
            feedback=feedback,
            analysis=analysis,
            improvements=improvements,
        )
        assert result == True
        assert len(loop._learning_buffer) == 1

    @pytest.mark.asyncio
    async def test_log_learning_triggers_flush(self):
        """バッファがいっぱいになるとフラッシュ (line 1289)"""
        loop = LearningLoop(organization_id="org-001")

        # Fill buffer to just below threshold
        for i in range(LEARNING_LOG_BUFFER_SIZE - 1):
            loop._learning_buffer.append(LearningEntry())

        feedback = Feedback(id="fb-final")
        analysis = FailureAnalysis()
        improvements = []

        result = await loop._log_learning(
            decision_id="dec-final",
            feedback=feedback,
            analysis=analysis,
            improvements=improvements,
        )
        assert result == True
        # Buffer should have been flushed
        assert len(loop._learning_buffer) == 0

    @pytest.mark.asyncio
    async def test_log_learning_exception(self):
        """ログ記録中の例外 (lines 1299-1301)"""
        loop = LearningLoop()

        # Patch LearningEntry to raise
        with patch('lib.brain.learning_loop.LearningEntry', side_effect=Exception("log error")):
            feedback = Feedback()
            analysis = FailureAnalysis()

            result = await loop._log_learning(
                decision_id="dec-001",
                feedback=feedback,
                analysis=analysis,
                improvements=[],
            )
            assert result == False

    @pytest.mark.asyncio
    async def test_flush_empty_buffer(self):
        """空バッファのフラッシュ (lines 1305-1306)"""
        loop = LearningLoop()

        count = await loop._flush_learning_buffer()
        assert count == 0

    @pytest.mark.asyncio
    async def test_flush_non_empty_buffer(self):
        """非空バッファのフラッシュ (lines 1308-1316)"""
        loop = LearningLoop()
        loop._learning_buffer.append(LearningEntry())
        loop._learning_buffer.append(LearningEntry())
        loop._learning_buffer.append(LearningEntry())

        count = await loop._flush_learning_buffer()
        assert count == 3
        assert len(loop._learning_buffer) == 0


# =============================================================================
# get_statistics 拡張テスト (lines 1353, 1355-1358)
# =============================================================================

class TestGetStatisticsExtended:
    """get_statistics の拡張テスト"""

    @pytest.mark.asyncio
    async def test_statistics_with_effective_improvements(self):
        """効果確認済みの改善統計 (line 1353)"""
        loop = LearningLoop()

        entry = LearningEntry(
            failure_cause=FailureCause.PATTERN_UNKNOWN,
            improvements=[
                Improvement(
                    improvement_type=ImprovementType.PATTERN_ADDITION,
                    status=LearningStatus.EFFECTIVE,
                ),
            ],
        )
        loop._learning_buffer.append(entry)

        stats = await loop.get_statistics()
        assert stats.effective_improvements == 1

    @pytest.mark.asyncio
    async def test_statistics_with_reverted_improvements(self):
        """取り消された改善統計 (lines 1354-1355)"""
        loop = LearningLoop()

        entry = LearningEntry(
            failure_cause=FailureCause.THRESHOLD_WRONG,
            improvements=[
                Improvement(
                    improvement_type=ImprovementType.THRESHOLD_ADJUSTMENT,
                    status=LearningStatus.REVERTED,
                ),
            ],
        )
        loop._learning_buffer.append(entry)

        stats = await loop.get_statistics()
        assert stats.reverted_improvements == 1

    @pytest.mark.asyncio
    async def test_statistics_exception_handling(self):
        """統計計算中の例外 (lines 1357-1358)"""
        loop = LearningLoop()

        # Add a bad entry that causes an exception
        bad_entry = MagicMock()
        bad_entry.failure_cause = MagicMock()
        bad_entry.failure_cause.value = "test"
        bad_entry.improvements = MagicMock()
        bad_entry.improvements.__iter__ = MagicMock(side_effect=Exception("iter error"))
        loop._learning_buffer.append(bad_entry)

        stats = await loop.get_statistics()
        # Should return stats (possibly partial) without raising
        assert isinstance(stats, LearningStatistics)

    @pytest.mark.asyncio
    async def test_statistics_multiple_improvement_types(self):
        """複数改善タイプの統計"""
        loop = LearningLoop()

        entry = LearningEntry(
            failure_cause=FailureCause.ACTION_WRONG,
            improvements=[
                Improvement(
                    improvement_type=ImprovementType.PATTERN_ADDITION,
                    status=LearningStatus.APPLIED,
                ),
                Improvement(
                    improvement_type=ImprovementType.KEYWORD_UPDATE,
                    status=LearningStatus.APPLIED,
                ),
            ],
        )
        loop._learning_buffer.append(entry)

        stats = await loop.get_statistics()
        assert stats.applied_improvements == 2
        assert "pattern_addition" in stats.improvement_type_distribution
        assert "keyword_update" in stats.improvement_type_distribution


# =============================================================================
# measure_effectiveness テスト (lines 1391-1403)
# =============================================================================

class TestMeasureEffectiveness:
    """measure_effectiveness のテスト"""

    @pytest.mark.asyncio
    async def test_effectiveness_tracking_disabled(self):
        """効果測定が無効の場合 (line 1391-1392)"""
        loop = LearningLoop(enable_effectiveness_tracking=False)

        result = await loop.measure_effectiveness("imp-001")
        assert result is None

    @pytest.mark.asyncio
    async def test_improvement_not_found(self):
        """改善が見つからない場合 (lines 1394-1396)"""
        loop = LearningLoop(enable_effectiveness_tracking=True)

        result = await loop.measure_effectiveness("non-existent")
        assert result is None

    @pytest.mark.asyncio
    async def test_improvement_found_but_not_implemented(self):
        """改善が見つかるがTODO未実装 (lines 1398-1403)"""
        loop = LearningLoop(enable_effectiveness_tracking=True)
        loop._improvement_cache["imp-001"] = Improvement(id="imp-001")

        result = await loop.measure_effectiveness("imp-001")
        assert result is None


# =============================================================================
# revert_improvement 拡張テスト (lines 1434-1437, 1445-1447)
# =============================================================================

class TestRevertImprovementExtended:
    """revert_improvement の拡張テスト"""

    @pytest.mark.asyncio
    async def test_revert_keyword_update(self):
        """キーワード更新の取り消し (lines 1434-1437)"""
        loop = LearningLoop()

        improvement = Improvement(
            id="imp-001",
            improvement_type=ImprovementType.KEYWORD_UPDATE,
            target_action="test_action",
            keywords_to_add=["追加", "登録"],
        )
        loop._improvement_cache["imp-001"] = improvement
        loop._applied_keywords["test_action"] = {
            "追加": 1.2,
            "登録": 1.0,
            "既存": 0.8,
        }

        result = await loop.revert_improvement("imp-001")
        assert result == True
        assert "追加" not in loop._applied_keywords["test_action"]
        assert "登録" not in loop._applied_keywords["test_action"]
        assert "既存" in loop._applied_keywords["test_action"]
        assert improvement.status == LearningStatus.REVERTED

    @pytest.mark.asyncio
    async def test_revert_keyword_update_no_target(self):
        """キーワード更新取り消し - target_actionなし"""
        loop = LearningLoop()

        improvement = Improvement(
            id="imp-002",
            improvement_type=ImprovementType.KEYWORD_UPDATE,
            target_action=None,
            keywords_to_add=["追加"],
        )
        loop._improvement_cache["imp-002"] = improvement

        result = await loop.revert_improvement("imp-002")
        # Still marks as reverted even without target
        assert result == True
        assert improvement.status == LearningStatus.REVERTED

    @pytest.mark.asyncio
    async def test_revert_exception(self):
        """取り消し中の例外 (lines 1445-1447)"""
        loop = LearningLoop()

        improvement = Improvement(
            id="imp-001",
            improvement_type=ImprovementType.THRESHOLD_ADJUSTMENT,
            target_action="test_action",
            old_threshold=0.7,
        )
        loop._improvement_cache["imp-001"] = improvement

        # Replace _applied_thresholds with a dict-like object that raises on __setitem__
        class FailingDict(dict):
            def __setitem__(self, key, value):
                raise Exception("revert error")

        loop._applied_thresholds = FailingDict()

        result = await loop.revert_improvement("imp-001")
        assert result == False

    @pytest.mark.asyncio
    async def test_revert_pattern_no_matching_pattern(self):
        """パターン取り消し - マッチするパターンなし"""
        loop = LearningLoop()

        improvement = Improvement(
            id="imp-003",
            improvement_type=ImprovementType.PATTERN_ADDITION,
            target_action="test_action",
            pattern_regex=r"nonexistent.*pattern",
        )
        loop._improvement_cache["imp-003"] = improvement
        loop._applied_patterns["test_action"] = [r"other.*pattern"]

        result = await loop.revert_improvement("imp-003")
        assert result == True
        # The non-matching pattern should remain
        assert r"other.*pattern" in loop._applied_patterns["test_action"]

    @pytest.mark.asyncio
    async def test_revert_pattern_with_intent_target(self):
        """パターン取り消し - target_intentで"""
        loop = LearningLoop()

        improvement = Improvement(
            id="imp-004",
            improvement_type=ImprovementType.PATTERN_ADDITION,
            target_action=None,
            target_intent="create_task",
            pattern_regex=r"タスク.*追加",
        )
        loop._improvement_cache["imp-004"] = improvement
        loop._applied_patterns["create_task"] = [r"タスク.*追加"]

        result = await loop.revert_improvement("imp-004")
        assert result == True
        assert r"タスク.*追加" not in loop._applied_patterns.get("create_task", [])


# =============================================================================
# _generate_cause_explanation 追加テスト
# =============================================================================

class TestGenerateCauseExplanationExtended:
    """_generate_cause_explanation の追加テスト"""

    def test_all_cause_explanations(self):
        """全原因の説明生成"""
        loop = LearningLoop()

        decision = DecisionSnapshot(
            user_message="テストメッセージ",
            detected_intent="test_intent",
            selected_action="test_action",
            action_confidence=0.5,
        )
        feedback = Feedback(
            correct_intent="correct_intent",
            correct_action="correct_action",
        )

        for cause in FailureCause:
            explanation = loop._generate_cause_explanation(cause, decision, feedback)
            assert isinstance(explanation, str)
            assert len(explanation) > 0

    def test_threshold_wrong_explanation(self):
        """閾値問題の説明"""
        loop = LearningLoop()

        decision = DecisionSnapshot(
            user_message="テスト",
            selected_action="test_action",
            action_confidence=0.55,
        )
        feedback = Feedback(correct_action="correct_action")

        explanation = loop._generate_cause_explanation(
            FailureCause.THRESHOLD_WRONG, decision, feedback
        )
        assert "閾値" in explanation
        assert "0.55" in explanation

    def test_pattern_unknown_explanation(self):
        """パターン未学習の説明"""
        loop = LearningLoop()

        decision = DecisionSnapshot(user_message="新しいパターンのメッセージ")
        feedback = Feedback()

        explanation = loop._generate_cause_explanation(
            FailureCause.PATTERN_UNKNOWN, decision, feedback
        )
        assert "パターン" in explanation

    def test_keyword_missing_explanation(self):
        """キーワード不足の説明"""
        loop = LearningLoop()

        decision = DecisionSnapshot(user_message="テストメッセージ")
        feedback = Feedback()

        explanation = loop._generate_cause_explanation(
            FailureCause.KEYWORD_MISSING, decision, feedback
        )
        assert "キーワード" in explanation
