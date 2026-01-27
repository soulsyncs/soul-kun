# tests/test_brain_learning_loop.py
"""
ソウルくんの脳 - Learning Loop テスト

Ultimate Brain Phase 3: 真の学習ループのユニットテスト
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from lib.brain.learning_loop import (
    # クラス
    LearningLoop,
    create_learning_loop,
    # 列挙型
    FeedbackType,
    FailureCause,
    ImprovementType,
    LearningStatus,
    # データクラス
    Feedback,
    DecisionSnapshot,
    FailureAnalysis,
    Improvement,
    LearningEntry,
    LearningStatistics,
    # 定数
    LEARNING_HISTORY_RETENTION_DAYS,
    MIN_SAMPLES_FOR_IMPROVEMENT,
    THRESHOLD_MIN,
    THRESHOLD_MAX,
    THRESHOLD_ADJUSTMENT_STEP,
    PATTERN_MIN_CONFIDENCE,
    DEFAULT_KEYWORD_WEIGHT,
    LEARNING_LOG_BUFFER_SIZE,
    ANALYSIS_DECISION_LOOKBACK,
    EFFECTIVENESS_MEASUREMENT_DAYS,
)


# =============================================================================
# 定数テスト
# =============================================================================

class TestConstants:
    """定数のテスト"""

    def test_learning_history_retention_days(self):
        """学習履歴保持期間"""
        assert LEARNING_HISTORY_RETENTION_DAYS == 180

    def test_min_samples_for_improvement(self):
        """改善適用の最小サンプル数"""
        assert MIN_SAMPLES_FOR_IMPROVEMENT == 3

    def test_threshold_min(self):
        """閾値の最小値"""
        assert THRESHOLD_MIN == 0.3

    def test_threshold_max(self):
        """閾値の最大値"""
        assert THRESHOLD_MAX == 0.95

    def test_threshold_adjustment_step(self):
        """閾値調整の単位"""
        assert THRESHOLD_ADJUSTMENT_STEP == 0.05

    def test_pattern_min_confidence(self):
        """パターン追加の最小確信度"""
        assert PATTERN_MIN_CONFIDENCE == 0.6

    def test_default_keyword_weight(self):
        """キーワード重みの初期値"""
        assert DEFAULT_KEYWORD_WEIGHT == 1.0

    def test_learning_log_buffer_size(self):
        """学習ログバッファサイズ"""
        assert LEARNING_LOG_BUFFER_SIZE == 20


# =============================================================================
# 列挙型テスト
# =============================================================================

class TestFeedbackType:
    """FeedbackType のテスト"""

    def test_all_values(self):
        """全値の確認"""
        assert FeedbackType.POSITIVE.value == "positive"
        assert FeedbackType.NEGATIVE.value == "negative"
        assert FeedbackType.CORRECTION.value == "correction"
        assert FeedbackType.CLARIFICATION.value == "clarification"
        assert FeedbackType.PREFERENCE.value == "preference"
        assert FeedbackType.SUGGESTION.value == "suggestion"

    def test_count(self):
        """値の数"""
        assert len(FeedbackType) == 6


class TestFailureCause:
    """FailureCause のテスト"""

    def test_intent_misunderstanding(self):
        """意図の誤解"""
        assert FailureCause.INTENT_MISUNDERSTANDING.value == "intent_misunderstanding"

    def test_context_missing(self):
        """コンテキスト不足"""
        assert FailureCause.CONTEXT_MISSING.value == "context_missing"

    def test_threshold_wrong(self):
        """閾値の問題"""
        assert FailureCause.THRESHOLD_WRONG.value == "threshold_wrong"

    def test_pattern_unknown(self):
        """パターン未学習"""
        assert FailureCause.PATTERN_UNKNOWN.value == "pattern_unknown"

    def test_keyword_missing(self):
        """キーワード不足"""
        assert FailureCause.KEYWORD_MISSING.value == "keyword_missing"

    def test_count(self):
        """値の数"""
        assert len(FailureCause) == 11


class TestImprovementType:
    """ImprovementType のテスト"""

    def test_threshold_adjustment(self):
        """閾値調整"""
        assert ImprovementType.THRESHOLD_ADJUSTMENT.value == "threshold_adjustment"

    def test_pattern_addition(self):
        """パターン追加"""
        assert ImprovementType.PATTERN_ADDITION.value == "pattern_addition"

    def test_keyword_update(self):
        """キーワード更新"""
        assert ImprovementType.KEYWORD_UPDATE.value == "keyword_update"

    def test_count(self):
        """値の数"""
        assert len(ImprovementType) == 7


class TestLearningStatus:
    """LearningStatus のテスト"""

    def test_all_values(self):
        """全値の確認"""
        assert LearningStatus.PENDING.value == "pending"
        assert LearningStatus.APPLIED.value == "applied"
        assert LearningStatus.EFFECTIVE.value == "effective"
        assert LearningStatus.INEFFECTIVE.value == "ineffective"
        assert LearningStatus.REVERTED.value == "reverted"


# =============================================================================
# Feedback データクラステスト
# =============================================================================

class TestFeedback:
    """Feedback のテスト"""

    def test_creation_defaults(self):
        """デフォルト値での作成"""
        feedback = Feedback()

        assert feedback.id is not None
        assert feedback.decision_id == ""
        assert feedback.feedback_type == FeedbackType.NEGATIVE
        assert feedback.message == ""
        assert feedback.correct_action is None
        assert feedback.correct_params is None
        assert feedback.correct_intent is None
        assert feedback.room_id == ""
        assert feedback.user_id == ""
        assert feedback.original_message == ""
        assert feedback.confidence == 1.0
        assert feedback.source == "user"
        assert feedback.created_at is not None

    def test_creation_with_values(self):
        """値を指定して作成"""
        feedback = Feedback(
            id="fb-001",
            decision_id="dec-001",
            feedback_type=FeedbackType.CORRECTION,
            message="タスク検索ではなく、タスク作成でした",
            correct_action="chatwork_task_create",
            correct_intent="create_task",
            room_id="room-123",
            user_id="user-456",
            original_message="タスクを追加して",
        )

        assert feedback.id == "fb-001"
        assert feedback.decision_id == "dec-001"
        assert feedback.feedback_type == FeedbackType.CORRECTION
        assert feedback.correct_action == "chatwork_task_create"

    def test_positive_feedback(self):
        """ポジティブフィードバック"""
        feedback = Feedback(
            feedback_type=FeedbackType.POSITIVE,
            message="ありがとう、合ってました",
        )

        assert feedback.feedback_type == FeedbackType.POSITIVE


# =============================================================================
# DecisionSnapshot データクラステスト
# =============================================================================

class TestDecisionSnapshot:
    """DecisionSnapshot のテスト"""

    def test_creation_defaults(self):
        """デフォルト値での作成"""
        snapshot = DecisionSnapshot()

        assert snapshot.decision_id == ""
        assert snapshot.user_message == ""
        assert snapshot.detected_intent == ""
        assert snapshot.intent_confidence == 0.0
        assert snapshot.detected_entities == {}
        assert snapshot.selected_action == ""
        assert snapshot.action_confidence == 0.0
        assert snapshot.action_params == {}
        assert snapshot.alternative_actions == []
        assert snapshot.execution_success == False
        assert snapshot.state_type == "normal"

    def test_creation_with_values(self):
        """値を指定して作成"""
        snapshot = DecisionSnapshot(
            decision_id="dec-001",
            user_message="自分のタスクを教えて",
            room_id="room-123",
            user_id="user-456",
            detected_intent="search_tasks",
            intent_confidence=0.85,
            detected_entities={"scope": "self"},
            selected_action="chatwork_task_search",
            action_confidence=0.90,
            action_params={"search_all_rooms": True},
            alternative_actions=["general_conversation"],
            execution_success=True,
        )

        assert snapshot.decision_id == "dec-001"
        assert snapshot.detected_intent == "search_tasks"
        assert snapshot.intent_confidence == 0.85
        assert snapshot.selected_action == "chatwork_task_search"
        assert snapshot.alternative_actions == ["general_conversation"]


# =============================================================================
# FailureAnalysis データクラステスト
# =============================================================================

class TestFailureAnalysis:
    """FailureAnalysis のテスト"""

    def test_creation_defaults(self):
        """デフォルト値での作成"""
        analysis = FailureAnalysis()

        assert analysis.primary_cause == FailureCause.UNKNOWN
        assert analysis.cause_confidence == 0.0
        assert analysis.cause_explanation == ""
        assert analysis.secondary_causes == []
        assert analysis.issues == []
        assert analysis.similar_failures == []
        assert analysis.failure_rate_for_pattern == 0.0

    def test_creation_with_values(self):
        """値を指定して作成"""
        analysis = FailureAnalysis(
            primary_cause=FailureCause.INTENT_MISUNDERSTANDING,
            cause_confidence=0.8,
            cause_explanation="意図を誤解しました",
            secondary_causes=[FailureCause.KEYWORD_MISSING],
            issues=["意図を誤解: search_tasks → create_task"],
            intent_analysis="検出された意図: search_tasks (確信度: 0.70)",
        )

        assert analysis.primary_cause == FailureCause.INTENT_MISUNDERSTANDING
        assert analysis.cause_confidence == 0.8
        assert len(analysis.secondary_causes) == 1


# =============================================================================
# Improvement データクラステスト
# =============================================================================

class TestImprovement:
    """Improvement のテスト"""

    def test_creation_defaults(self):
        """デフォルト値での作成"""
        improvement = Improvement()

        assert improvement.id is not None
        assert improvement.improvement_type == ImprovementType.PATTERN_ADDITION
        assert improvement.description == ""
        assert improvement.target_action is None
        assert improvement.priority == 5
        assert improvement.status == LearningStatus.PENDING
        assert improvement.expected_improvement == 0.0

    def test_creation_threshold_adjustment(self):
        """閾値調整の改善"""
        improvement = Improvement(
            improvement_type=ImprovementType.THRESHOLD_ADJUSTMENT,
            description="chatwork_task_searchの閾値を0.70から0.65に調整",
            target_action="chatwork_task_search",
            old_threshold=0.70,
            new_threshold=0.65,
            priority=6,
        )

        assert improvement.improvement_type == ImprovementType.THRESHOLD_ADJUSTMENT
        assert improvement.old_threshold == 0.70
        assert improvement.new_threshold == 0.65

    def test_creation_pattern_addition(self):
        """パターン追加の改善"""
        improvement = Improvement(
            improvement_type=ImprovementType.PATTERN_ADDITION,
            description="タスク作成パターンを追加",
            target_action="chatwork_task_create",
            pattern_regex=r"タスク.*追加",
            pattern_examples=["タスクを追加して", "タスク追加"],
        )

        assert improvement.improvement_type == ImprovementType.PATTERN_ADDITION
        assert improvement.pattern_regex == r"タスク.*追加"
        assert len(improvement.pattern_examples) == 2

    def test_creation_keyword_update(self):
        """キーワード更新の改善"""
        improvement = Improvement(
            improvement_type=ImprovementType.KEYWORD_UPDATE,
            description="キーワードを追加",
            target_action="chatwork_task_create",
            keywords_to_add=["追加", "作成", "登録"],
            keyword_weights={"追加": 1.2, "作成": 1.0, "登録": 0.8},
        )

        assert improvement.improvement_type == ImprovementType.KEYWORD_UPDATE
        assert "追加" in improvement.keywords_to_add
        assert improvement.keyword_weights["追加"] == 1.2

    def test_to_dict(self):
        """辞書変換"""
        improvement = Improvement(
            id="imp-001",
            improvement_type=ImprovementType.THRESHOLD_ADJUSTMENT,
            description="テスト",
            target_action="test_action",
            old_threshold=0.7,
            new_threshold=0.65,
            priority=6,
        )

        d = improvement.to_dict()

        assert d["id"] == "imp-001"
        assert d["improvement_type"] == "threshold_adjustment"
        assert d["target_action"] == "test_action"
        assert d["old_threshold"] == 0.7
        assert d["new_threshold"] == 0.65


# =============================================================================
# LearningEntry データクラステスト
# =============================================================================

class TestLearningEntry:
    """LearningEntry のテスト"""

    def test_creation_defaults(self):
        """デフォルト値での作成"""
        entry = LearningEntry()

        assert entry.id is not None
        assert entry.organization_id == ""
        assert entry.decision_id == ""
        assert entry.feedback_id == ""
        assert entry.failure_cause == FailureCause.UNKNOWN
        assert entry.improvements == []
        assert entry.baseline_success_rate == 0.0
        assert entry.improvement_verified == False

    def test_creation_with_values(self):
        """値を指定して作成"""
        improvement = Improvement(
            improvement_type=ImprovementType.PATTERN_ADDITION,
            description="パターン追加",
        )

        entry = LearningEntry(
            organization_id="org-001",
            decision_id="dec-001",
            feedback_id="fb-001",
            failure_cause=FailureCause.PATTERN_UNKNOWN,
            cause_explanation="パターン未学習",
            improvements=[improvement],
            baseline_success_rate=0.75,
        )

        assert entry.organization_id == "org-001"
        assert entry.failure_cause == FailureCause.PATTERN_UNKNOWN
        assert len(entry.improvements) == 1


# =============================================================================
# LearningLoop 初期化テスト
# =============================================================================

class TestLearningLoopInit:
    """LearningLoop 初期化のテスト"""

    def test_default_initialization(self):
        """デフォルト初期化"""
        loop = LearningLoop()

        assert loop.pool is None
        assert loop.organization_id == ""
        assert loop.enable_auto_apply == True
        assert loop.enable_effectiveness_tracking == True
        assert loop._decision_cache == {}
        assert loop._improvement_cache == {}
        assert loop._learning_buffer == []
        assert loop._applied_thresholds == {}
        assert loop._applied_patterns == {}
        assert loop._applied_keywords == {}

    def test_initialization_with_values(self):
        """値を指定して初期化"""
        mock_pool = MagicMock()

        loop = LearningLoop(
            pool=mock_pool,
            organization_id="org-001",
            enable_auto_apply=False,
            enable_effectiveness_tracking=False,
        )

        assert loop.pool == mock_pool
        assert loop.organization_id == "org-001"
        assert loop.enable_auto_apply == False
        assert loop.enable_effectiveness_tracking == False


# =============================================================================
# LearningLoop 判断記録テスト
# =============================================================================

class TestLearningLoopRecordDecision:
    """判断記録のテスト"""

    @pytest.mark.asyncio
    async def test_record_decision_success(self):
        """判断記録成功"""
        loop = LearningLoop()
        snapshot = DecisionSnapshot(
            decision_id="dec-001",
            user_message="テストメッセージ",
            selected_action="test_action",
        )

        result = await loop.record_decision("dec-001", snapshot)

        assert result == True
        assert "dec-001" in loop._decision_cache
        assert loop._decision_cache["dec-001"] == snapshot

    @pytest.mark.asyncio
    async def test_record_decision_cache_limit(self):
        """キャッシュサイズ制限"""
        loop = LearningLoop()

        # 1001件の判断を記録
        for i in range(1001):
            snapshot = DecisionSnapshot(
                decision_id=f"dec-{i:04d}",
                user_message=f"メッセージ{i}",
            )
            await loop.record_decision(f"dec-{i:04d}", snapshot)

        # キャッシュサイズは1000以下になる
        assert len(loop._decision_cache) <= 1000


# =============================================================================
# LearningLoop 判断取得テスト
# =============================================================================

class TestLearningLoopGetDecision:
    """判断取得のテスト"""

    @pytest.mark.asyncio
    async def test_get_decision_from_cache(self):
        """キャッシュからの取得"""
        loop = LearningLoop()
        snapshot = DecisionSnapshot(
            decision_id="dec-001",
            user_message="テストメッセージ",
        )
        loop._decision_cache["dec-001"] = snapshot

        result = await loop._get_decision("dec-001")

        assert result == snapshot

    @pytest.mark.asyncio
    async def test_get_decision_not_found(self):
        """見つからない場合"""
        loop = LearningLoop()

        result = await loop._get_decision("non-existent")

        assert result is None


# =============================================================================
# LearningLoop 失敗分析テスト
# =============================================================================

class TestLearningLoopAnalyzeFailure:
    """失敗分析のテスト"""

    @pytest.mark.asyncio
    async def test_analyze_intent_misunderstanding(self):
        """意図誤解の分析"""
        loop = LearningLoop()
        decision = DecisionSnapshot(
            decision_id="dec-001",
            user_message="タスクを追加して",
            detected_intent="search_tasks",
            intent_confidence=0.6,
            selected_action="chatwork_task_search",
        )
        feedback = Feedback(
            feedback_type=FeedbackType.CORRECTION,
            correct_intent="create_task",
            correct_action="chatwork_task_create",
        )

        analysis = await loop._analyze_failure(decision, feedback)

        assert analysis.primary_cause == FailureCause.INTENT_MISUNDERSTANDING
        assert "意図を誤解" in str(analysis.issues)

    @pytest.mark.asyncio
    async def test_analyze_threshold_wrong(self):
        """閾値問題の分析"""
        loop = LearningLoop()
        decision = DecisionSnapshot(
            decision_id="dec-001",
            user_message="タスク追加",
            detected_intent="create_task",
            intent_confidence=0.8,
            selected_action="chatwork_task_search",
            action_confidence=0.55,
            alternative_actions=["chatwork_task_create"],  # 正解が代替候補にある
        )
        feedback = Feedback(
            feedback_type=FeedbackType.CORRECTION,
            correct_action="chatwork_task_create",
        )

        analysis = await loop._analyze_failure(decision, feedback)

        # 正しいアクションが代替候補にある場合は閾値の問題
        assert analysis.primary_cause in [
            FailureCause.THRESHOLD_WRONG,
            FailureCause.INTENT_MISUNDERSTANDING,
        ]

    @pytest.mark.asyncio
    async def test_analyze_context_missing(self):
        """コンテキスト不足の分析"""
        loop = LearningLoop()
        decision = DecisionSnapshot(
            decision_id="dec-001",
            user_message="それを完了にして",
            detected_intent="complete_task",
            intent_confidence=0.7,
            context_summary="",  # コンテキストが空
        )
        feedback = Feedback(
            feedback_type=FeedbackType.NEGATIVE,
            message="前の会話を考慮してほしかった",
        )

        analysis = await loop._analyze_failure(decision, feedback)

        assert FailureCause.CONTEXT_MISSING in [
            analysis.primary_cause,
            *analysis.secondary_causes
        ]


# =============================================================================
# LearningLoop 改善生成テスト
# =============================================================================

class TestLearningLoopGenerateImprovements:
    """改善生成のテスト"""

    @pytest.mark.asyncio
    async def test_generate_improvements_for_intent_misunderstanding(self):
        """意図誤解に対する改善生成"""
        loop = LearningLoop()
        analysis = FailureAnalysis(
            primary_cause=FailureCause.INTENT_MISUNDERSTANDING,
            cause_confidence=0.8,
        )
        decision = DecisionSnapshot(
            decision_id="dec-001",
            user_message="タスクを追加して",
            detected_intent="search_tasks",
            selected_action="chatwork_task_search",
        )
        feedback = Feedback(
            feedback_type=FeedbackType.CORRECTION,
            correct_intent="create_task",
            correct_action="chatwork_task_create",
        )

        improvements = await loop._generate_improvements(analysis, decision, feedback)

        assert len(improvements) >= 1
        # パターン追加が含まれるはず
        pattern_improvements = [
            i for i in improvements
            if i.improvement_type == ImprovementType.PATTERN_ADDITION
        ]
        assert len(pattern_improvements) >= 1

    @pytest.mark.asyncio
    async def test_generate_improvements_for_threshold(self):
        """閾値問題に対する改善生成"""
        loop = LearningLoop()
        analysis = FailureAnalysis(
            primary_cause=FailureCause.THRESHOLD_WRONG,
            cause_confidence=0.7,
        )
        decision = DecisionSnapshot(
            decision_id="dec-001",
            user_message="タスク追加",
            selected_action="chatwork_task_search",
            action_confidence=0.6,
            alternative_actions=["chatwork_task_create"],
        )
        feedback = Feedback(
            feedback_type=FeedbackType.CORRECTION,
            correct_action="chatwork_task_create",
        )

        improvements = await loop._generate_improvements(analysis, decision, feedback)

        # 閾値調整が含まれるはず
        threshold_improvements = [
            i for i in improvements
            if i.improvement_type == ImprovementType.THRESHOLD_ADJUSTMENT
        ]
        assert len(threshold_improvements) >= 1

    @pytest.mark.asyncio
    async def test_generate_improvements_for_keyword_missing(self):
        """キーワード不足に対する改善生成"""
        loop = LearningLoop()
        analysis = FailureAnalysis(
            primary_cause=FailureCause.KEYWORD_MISSING,
            cause_confidence=0.6,
        )
        decision = DecisionSnapshot(
            decision_id="dec-001",
            user_message="やることを登録して",
            selected_action="general_conversation",
        )
        feedback = Feedback(
            feedback_type=FeedbackType.CORRECTION,
            correct_action="chatwork_task_create",
        )

        improvements = await loop._generate_improvements(analysis, decision, feedback)

        # キーワード更新が含まれるはず
        keyword_improvements = [
            i for i in improvements
            if i.improvement_type == ImprovementType.KEYWORD_UPDATE
        ]
        assert len(keyword_improvements) >= 1


# =============================================================================
# LearningLoop 改善適用テスト
# =============================================================================

class TestLearningLoopApplyImprovement:
    """改善適用のテスト"""

    @pytest.mark.asyncio
    async def test_apply_threshold_adjustment(self):
        """閾値調整の適用"""
        loop = LearningLoop()
        improvement = Improvement(
            improvement_type=ImprovementType.THRESHOLD_ADJUSTMENT,
            target_action="chatwork_task_search",
            old_threshold=0.7,
            new_threshold=0.65,
        )

        result = await loop._apply_threshold_adjustment(improvement)

        assert result == True
        assert loop._applied_thresholds["chatwork_task_search"] == 0.65
        assert improvement.status == LearningStatus.APPLIED

    @pytest.mark.asyncio
    async def test_apply_pattern_addition(self):
        """パターン追加の適用"""
        loop = LearningLoop()
        improvement = Improvement(
            improvement_type=ImprovementType.PATTERN_ADDITION,
            target_action="chatwork_task_create",
            pattern_regex=r"タスク.*追加",
        )

        result = await loop._apply_pattern_addition(improvement)

        assert result == True
        assert "chatwork_task_create" in loop._applied_patterns
        assert r"タスク.*追加" in loop._applied_patterns["chatwork_task_create"]
        assert improvement.status == LearningStatus.APPLIED

    @pytest.mark.asyncio
    async def test_apply_keyword_update(self):
        """キーワード更新の適用"""
        loop = LearningLoop()
        improvement = Improvement(
            improvement_type=ImprovementType.KEYWORD_UPDATE,
            target_action="chatwork_task_create",
            keywords_to_add=["追加", "登録"],
            keyword_weights={"追加": 1.2, "登録": 1.0},
        )

        result = await loop._apply_keyword_update(improvement)

        assert result == True
        assert "chatwork_task_create" in loop._applied_keywords
        assert loop._applied_keywords["chatwork_task_create"]["追加"] == 1.2
        assert improvement.status == LearningStatus.APPLIED


# =============================================================================
# LearningLoop 学習フローテスト
# =============================================================================

class TestLearningLoopLearnFromFeedback:
    """学習フローのテスト"""

    @pytest.mark.asyncio
    async def test_learn_from_positive_feedback(self):
        """ポジティブフィードバックからの学習"""
        loop = LearningLoop()

        # 判断を記録
        snapshot = DecisionSnapshot(
            decision_id="dec-001",
            user_message="自分のタスク教えて",
            selected_action="chatwork_task_search",
            action_confidence=0.9,
        )
        await loop.record_decision("dec-001", snapshot)

        # ポジティブフィードバック
        feedback = Feedback(
            decision_id="dec-001",
            feedback_type=FeedbackType.POSITIVE,
            message="ありがとう",
        )

        improvements = await loop.learn_from_feedback("dec-001", feedback)

        # ポジティブフィードバックでは改善は生成されない
        assert improvements == []

    @pytest.mark.asyncio
    async def test_learn_from_negative_feedback(self):
        """ネガティブフィードバックからの学習"""
        loop = LearningLoop()

        # 判断を記録
        snapshot = DecisionSnapshot(
            decision_id="dec-001",
            user_message="タスクを追加して",
            detected_intent="search_tasks",
            intent_confidence=0.6,
            selected_action="chatwork_task_search",
        )
        await loop.record_decision("dec-001", snapshot)

        # 修正フィードバック
        feedback = Feedback(
            decision_id="dec-001",
            feedback_type=FeedbackType.CORRECTION,
            correct_intent="create_task",
            correct_action="chatwork_task_create",
        )

        improvements = await loop.learn_from_feedback("dec-001", feedback)

        # 改善が生成される
        assert len(improvements) >= 1

    @pytest.mark.asyncio
    async def test_learn_from_feedback_decision_not_found(self):
        """判断が見つからない場合"""
        loop = LearningLoop()
        feedback = Feedback(
            decision_id="non-existent",
            feedback_type=FeedbackType.NEGATIVE,
        )

        improvements = await loop.learn_from_feedback("non-existent", feedback)

        assert improvements == []


# =============================================================================
# LearningLoop ゲッターテスト
# =============================================================================

class TestLearningLoopGetters:
    """ゲッターメソッドのテスト"""

    def test_get_applied_patterns_empty(self):
        """適用パターン取得（空）"""
        loop = LearningLoop()

        patterns = loop.get_applied_patterns("test_action")

        assert patterns == []

    def test_get_applied_patterns_with_data(self):
        """適用パターン取得（データあり）"""
        loop = LearningLoop()
        loop._applied_patterns["test_action"] = [r"パターン1", r"パターン2"]

        patterns = loop.get_applied_patterns("test_action")

        assert patterns == [r"パターン1", r"パターン2"]

    def test_get_applied_keywords_empty(self):
        """適用キーワード取得（空）"""
        loop = LearningLoop()

        keywords = loop.get_applied_keywords("test_action")

        assert keywords == {}

    def test_get_applied_keywords_with_data(self):
        """適用キーワード取得（データあり）"""
        loop = LearningLoop()
        loop._applied_keywords["test_action"] = {"追加": 1.2, "作成": 1.0}

        keywords = loop.get_applied_keywords("test_action")

        assert keywords["追加"] == 1.2

    def test_get_adjusted_threshold_default(self):
        """調整閾値取得（デフォルト）"""
        loop = LearningLoop()

        threshold = loop.get_adjusted_threshold("test_action", default=0.7)

        assert threshold == 0.7

    def test_get_adjusted_threshold_with_data(self):
        """調整閾値取得（データあり）"""
        loop = LearningLoop()
        loop._applied_thresholds["test_action"] = 0.65

        threshold = loop.get_adjusted_threshold("test_action")

        assert threshold == 0.65


# =============================================================================
# LearningLoop 統計テスト
# =============================================================================

class TestLearningLoopStatistics:
    """統計のテスト"""

    @pytest.mark.asyncio
    async def test_get_statistics_empty(self):
        """空の統計取得"""
        loop = LearningLoop()

        stats = await loop.get_statistics(days=7)

        assert stats.period_days == 7
        assert stats.total_learnings == 0
        assert stats.cause_distribution == {}

    @pytest.mark.asyncio
    async def test_get_statistics_with_data(self):
        """データありの統計取得"""
        loop = LearningLoop()

        # 学習エントリを追加
        entry = LearningEntry(
            failure_cause=FailureCause.INTENT_MISUNDERSTANDING,
            improvements=[
                Improvement(
                    improvement_type=ImprovementType.PATTERN_ADDITION,
                    status=LearningStatus.APPLIED,
                ),
            ],
        )
        loop._learning_buffer.append(entry)

        stats = await loop.get_statistics()

        assert stats.total_learnings == 1
        assert "intent_misunderstanding" in stats.cause_distribution


# =============================================================================
# LearningLoop 改善取り消しテスト
# =============================================================================

class TestLearningLoopRevertImprovement:
    """改善取り消しのテスト"""

    @pytest.mark.asyncio
    async def test_revert_threshold_adjustment(self):
        """閾値調整の取り消し"""
        loop = LearningLoop()

        # 改善を適用
        improvement = Improvement(
            id="imp-001",
            improvement_type=ImprovementType.THRESHOLD_ADJUSTMENT,
            target_action="test_action",
            old_threshold=0.7,
            new_threshold=0.65,
        )
        loop._improvement_cache["imp-001"] = improvement
        loop._applied_thresholds["test_action"] = 0.65

        # 取り消し
        result = await loop.revert_improvement("imp-001")

        assert result == True
        assert loop._applied_thresholds["test_action"] == 0.7
        assert improvement.status == LearningStatus.REVERTED

    @pytest.mark.asyncio
    async def test_revert_pattern_addition(self):
        """パターン追加の取り消し"""
        loop = LearningLoop()

        # 改善を適用
        improvement = Improvement(
            id="imp-001",
            improvement_type=ImprovementType.PATTERN_ADDITION,
            target_action="test_action",
            pattern_regex=r"テスト.*パターン",
        )
        loop._improvement_cache["imp-001"] = improvement
        loop._applied_patterns["test_action"] = [r"テスト.*パターン"]

        # 取り消し
        result = await loop.revert_improvement("imp-001")

        assert result == True
        assert r"テスト.*パターン" not in loop._applied_patterns.get("test_action", [])

    @pytest.mark.asyncio
    async def test_revert_nonexistent_improvement(self):
        """存在しない改善の取り消し"""
        loop = LearningLoop()

        result = await loop.revert_improvement("non-existent")

        assert result == False


# =============================================================================
# LearningLoop パターン抽出テスト
# =============================================================================

class TestLearningLoopPatternExtraction:
    """パターン抽出のテスト"""

    def test_extract_pattern_from_message(self):
        """メッセージからのパターン抽出"""
        loop = LearningLoop()

        pattern = loop._extract_pattern_from_message("タスクを追加して")

        assert pattern is not None
        assert len(pattern) > 0

    def test_extract_pattern_from_short_message(self):
        """短いメッセージからのパターン抽出"""
        loop = LearningLoop()

        pattern = loop._extract_pattern_from_message("あ")

        # 短すぎる場合はNone
        assert pattern is None


# =============================================================================
# LearningLoop キーワード抽出テスト
# =============================================================================

class TestLearningLoopKeywordExtraction:
    """キーワード抽出のテスト"""

    def test_extract_keywords_from_message(self):
        """メッセージからのキーワード抽出"""
        loop = LearningLoop()

        keywords = loop._extract_keywords_from_message("タスクを追加して経費精算")

        assert isinstance(keywords, list)
        # ストップワードが除外されていることを確認
        assert "を" not in keywords
        assert "して" not in keywords

    def test_extract_keywords_limit(self):
        """キーワード抽出の上限"""
        loop = LearningLoop()

        keywords = loop._extract_keywords_from_message(
            "タスク追加経費精算営業報告週次レポート月次集計年度計画"
        )

        assert len(keywords) <= 5


# =============================================================================
# ファクトリ関数テスト
# =============================================================================

class TestCreateLearningLoop:
    """ファクトリ関数のテスト"""

    def test_create_learning_loop_defaults(self):
        """デフォルト値での作成"""
        loop = create_learning_loop()

        assert isinstance(loop, LearningLoop)
        assert loop.pool is None
        assert loop.organization_id == ""
        assert loop.enable_auto_apply == True

    def test_create_learning_loop_with_values(self):
        """値を指定して作成"""
        mock_pool = MagicMock()

        loop = create_learning_loop(
            pool=mock_pool,
            organization_id="org-001",
            enable_auto_apply=False,
            enable_effectiveness_tracking=False,
        )

        assert loop.pool == mock_pool
        assert loop.organization_id == "org-001"
        assert loop.enable_auto_apply == False
        assert loop.enable_effectiveness_tracking == False


# =============================================================================
# 類似判断検索テスト
# =============================================================================

class TestLearningLoopSimilarDecisions:
    """類似判断検索のテスト"""

    def test_is_similar_decision_same_action_intent(self):
        """同じアクション・意図の判断は類似"""
        loop = LearningLoop()

        decision1 = DecisionSnapshot(
            decision_id="dec-001",
            user_message="タスクを教えて",
            detected_intent="search_tasks",
            selected_action="chatwork_task_search",
        )
        decision2 = DecisionSnapshot(
            decision_id="dec-002",
            user_message="タスク一覧を見せて",
            detected_intent="search_tasks",
            selected_action="chatwork_task_search",
        )

        result = loop._is_similar_decision(decision1, decision2)

        assert result == True

    def test_is_similar_decision_different(self):
        """異なる判断は非類似"""
        loop = LearningLoop()

        decision1 = DecisionSnapshot(
            decision_id="dec-001",
            user_message="タスクを教えて",
            detected_intent="search_tasks",
            selected_action="chatwork_task_search",
        )
        decision2 = DecisionSnapshot(
            decision_id="dec-002",
            user_message="ナレッジを検索",
            detected_intent="query_knowledge",
            selected_action="query_knowledge",
        )

        result = loop._is_similar_decision(decision1, decision2)

        # アクションも意図も異なるので非類似
        assert result == False

    @pytest.mark.asyncio
    async def test_find_similar_failures(self):
        """類似失敗の検索"""
        loop = LearningLoop()

        # 複数の判断をキャッシュに追加
        for i in range(5):
            snapshot = DecisionSnapshot(
                decision_id=f"dec-{i:03d}",
                user_message="タスクを検索",
                detected_intent="search_tasks",
                selected_action="chatwork_task_search",
            )
            loop._decision_cache[f"dec-{i:03d}"] = snapshot

        target = DecisionSnapshot(
            decision_id="dec-target",
            user_message="タスク一覧",
            detected_intent="search_tasks",
            selected_action="chatwork_task_search",
        )

        similar = await loop._find_similar_failures(target)

        assert len(similar) >= 1


# =============================================================================
# 原因説明生成テスト
# =============================================================================

class TestLearningLoopCauseExplanation:
    """原因説明生成のテスト"""

    def test_generate_cause_explanation_intent_misunderstanding(self):
        """意図誤解の説明"""
        loop = LearningLoop()

        decision = DecisionSnapshot(
            user_message="タスクを追加して",
            detected_intent="search_tasks",
        )
        feedback = Feedback(correct_intent="create_task")

        explanation = loop._generate_cause_explanation(
            FailureCause.INTENT_MISUNDERSTANDING, decision, feedback
        )

        assert "誤解" in explanation
        assert "search_tasks" in explanation

    def test_generate_cause_explanation_context_missing(self):
        """コンテキスト不足の説明"""
        loop = LearningLoop()

        decision = DecisionSnapshot()
        feedback = Feedback()

        explanation = loop._generate_cause_explanation(
            FailureCause.CONTEXT_MISSING, decision, feedback
        )

        assert "コンテキスト" in explanation

    def test_generate_cause_explanation_unknown(self):
        """原因不明の説明"""
        loop = LearningLoop()

        decision = DecisionSnapshot()
        feedback = Feedback()

        explanation = loop._generate_cause_explanation(
            FailureCause.UNKNOWN, decision, feedback
        )

        assert "特定できません" in explanation


# =============================================================================
# 統合テスト
# =============================================================================

class TestLearningLoopIntegration:
    """統合テスト"""

    @pytest.mark.asyncio
    async def test_full_learning_cycle(self):
        """完全な学習サイクル"""
        loop = LearningLoop(organization_id="org-001")

        # 1. 判断を記録
        snapshot = DecisionSnapshot(
            decision_id="dec-001",
            user_message="やることを登録して",
            room_id="room-123",
            user_id="user-456",
            detected_intent="general_conversation",
            intent_confidence=0.5,
            selected_action="general_conversation",
            action_confidence=0.6,
            execution_success=False,
        )
        await loop.record_decision("dec-001", snapshot)

        # 2. フィードバックを受ける
        feedback = Feedback(
            decision_id="dec-001",
            feedback_type=FeedbackType.CORRECTION,
            message="タスク作成をお願いしたかった",
            correct_action="chatwork_task_create",
            correct_intent="create_task",
            original_message="やることを登録して",
        )

        # 3. 学習
        improvements = await loop.learn_from_feedback("dec-001", feedback)

        # 4. 改善が適用されたか確認
        assert len(improvements) >= 1

        # 5. 統計を確認
        stats = await loop.get_statistics()
        assert stats.total_learnings >= 1

    @pytest.mark.asyncio
    async def test_multiple_feedbacks_same_pattern(self):
        """同じパターンへの複数フィードバック"""
        loop = LearningLoop(organization_id="org-001")

        # 複数の類似した判断と修正フィードバック
        for i in range(3):
            snapshot = DecisionSnapshot(
                decision_id=f"dec-{i:03d}",
                user_message=f"タスク追加{i}",
                detected_intent="search_tasks",
                intent_confidence=0.6,
                selected_action="chatwork_task_search",
            )
            await loop.record_decision(f"dec-{i:03d}", snapshot)

            feedback = Feedback(
                decision_id=f"dec-{i:03d}",
                feedback_type=FeedbackType.CORRECTION,
                correct_action="chatwork_task_create",
            )

            await loop.learn_from_feedback(f"dec-{i:03d}", feedback)

        # 学習エントリが複数あることを確認
        assert len(loop._learning_buffer) >= 3
