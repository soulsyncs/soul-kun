# tests/test_brain_decision.py
"""
BrainDecision（判断層）のユニットテスト

Phase E: Decision Layer Enhancement
設計書: docs/13_brain_architecture.md

テストカバレッジ:
- 初期化テスト
- 機能スコアリングテスト
- 複数アクション検出テスト
- 確認要否判断テスト
- MVV整合性チェックテスト
- アクティブセッション処理テスト
- エラーハンドリングテスト
"""

import pytest
from datetime import datetime, timedelta
from typing import Dict, Any, List
from unittest.mock import MagicMock, patch, AsyncMock

from lib.brain.decision import (
    BrainDecision,
    MVVCheckResult,
    CAPABILITY_KEYWORDS,
    DECISION_PROMPT,
    create_decision,
    _load_mvv_context,
)
from lib.brain.models import (
    BrainContext,
    UnderstandingResult,
    DecisionResult,
    ActionCandidate,
    ConversationState,
    StateType,
)
from lib.brain.constants import (
    CONFIRMATION_THRESHOLD,
    DANGEROUS_ACTIONS,
    RISK_LEVELS,
    SPLIT_PATTERNS,
    CAPABILITY_MIN_SCORE_THRESHOLD,
)


# =============================================================================
# フィクスチャ
# =============================================================================


@pytest.fixture
def sample_capabilities() -> Dict[str, Dict]:
    """テスト用のSYSTEM_CAPABILITIES"""
    return {
        "chatwork_task_create": {
            "name": "ChatWorkタスク作成",
            "description": "タスクを作成する",
            "category": "task",
            "enabled": True,
            "trigger_examples": ["タスク追加して", "タスク作って"],
            "params_schema": {
                "assigned_to": {"type": "string", "required": True},
                "task_body": {"type": "string", "required": True},
            },
            "requires_confirmation": False,
        },
        "chatwork_task_search": {
            "name": "タスク検索",
            "description": "タスクを検索する",
            "category": "task",
            "enabled": True,
            "trigger_examples": ["タスク教えて", "タスク一覧"],
            "params_schema": {
                "person_name": {"type": "string", "required": False},
            },
            "requires_confirmation": False,
        },
        "chatwork_task_complete": {
            "name": "タスク完了",
            "description": "タスクを完了にする",
            "category": "task",
            "enabled": True,
            "trigger_examples": ["完了にして", "終わった"],
            "params_schema": {},
            "requires_confirmation": False,
        },
        "delete_memory": {
            "name": "記憶削除",
            "description": "記憶を削除する",
            "category": "memory",
            "enabled": True,
            "trigger_examples": ["忘れて", "削除して"],
            "params_schema": {},
            "requires_confirmation": True,
        },
        "disabled_feature": {
            "name": "無効機能",
            "description": "無効な機能",
            "category": "test",
            "enabled": False,
            "trigger_examples": [],
            "params_schema": {},
            "requires_confirmation": False,
        },
    }


@pytest.fixture
def brain_decision(sample_capabilities) -> BrainDecision:
    """テスト用のBrainDecisionインスタンス"""
    return BrainDecision(
        capabilities=sample_capabilities,
        get_ai_response_func=None,
        org_id="org_test",
        use_llm=False,
    )


@pytest.fixture
def empty_context() -> BrainContext:
    """空のコンテキスト"""
    return BrainContext(
        room_id="room_123",
        sender_account_id="user_456",
        sender_name="テストユーザー",
        organization_id="org_test",
    )


@pytest.fixture
def active_goal_setting_context() -> BrainContext:
    """目標設定セッション中のコンテキスト"""
    state = ConversationState(
        state_id="state_123",
        organization_id="org_test",
        room_id="room_123",
        user_id="user_456",
        state_type=StateType.GOAL_SETTING,
        state_step="why",
        expires_at=datetime.now() + timedelta(hours=1),
    )
    return BrainContext(
        room_id="room_123",
        sender_account_id="user_456",
        sender_name="テストユーザー",
        organization_id="org_test",
        current_state=state,
    )


@pytest.fixture
def understanding_task_create() -> UnderstandingResult:
    """タスク作成の理解結果"""
    return UnderstandingResult(
        raw_message="菊地さんにタスク作成して",
        intent="chatwork_task_create",
        intent_confidence=0.85,
        entities={
            "person": "菊地",
            "task": "タスク",
        },
    )


@pytest.fixture
def understanding_task_search() -> UnderstandingResult:
    """タスク検索の理解結果"""
    return UnderstandingResult(
        raw_message="自分のタスク教えて",
        intent="chatwork_task_search",
        intent_confidence=0.9,
        entities={
            "person": "sender",
        },
    )


@pytest.fixture
def understanding_low_confidence() -> UnderstandingResult:
    """低確信度の理解結果"""
    return UnderstandingResult(
        raw_message="あれやっといて",
        intent="unknown",
        intent_confidence=0.4,
        entities={},
    )


@pytest.fixture
def understanding_multiple_actions() -> UnderstandingResult:
    """複数アクションの理解結果"""
    return UnderstandingResult(
        raw_message="タスク作成して、あと自分のタスク教えて",
        intent="chatwork_task_create",
        intent_confidence=0.85,
        entities={},
    )


# =============================================================================
# 初期化テスト
# =============================================================================


class TestBrainDecisionInit:
    """BrainDecision初期化のテスト"""

    def test_init_with_capabilities(self, sample_capabilities):
        """機能カタログ付きの初期化"""
        decision = BrainDecision(
            capabilities=sample_capabilities,
            org_id="org_test",
        )
        assert decision.org_id == "org_test"
        assert len(decision.capabilities) == 5
        assert len(decision.enabled_capabilities) == 4  # disabled_feature除外

    def test_init_without_capabilities(self):
        """機能カタログなしの初期化"""
        decision = BrainDecision(org_id="org_test")
        assert decision.capabilities == {}
        assert decision.enabled_capabilities == {}

    def test_init_with_llm(self):
        """LLM使用フラグ付きの初期化"""
        decision = BrainDecision(
            org_id="org_test",
            use_llm=True,
        )
        assert decision.use_llm is True

    def test_init_filters_disabled_capabilities(self, sample_capabilities):
        """無効な機能がフィルタされる"""
        decision = BrainDecision(capabilities=sample_capabilities)
        assert "disabled_feature" not in decision.enabled_capabilities
        assert "chatwork_task_create" in decision.enabled_capabilities

    def test_create_decision_factory(self, sample_capabilities):
        """ファクトリー関数のテスト"""
        decision = create_decision(
            capabilities=sample_capabilities,
            org_id="org_factory_test",
            use_llm=False,
        )
        assert isinstance(decision, BrainDecision)
        assert decision.org_id == "org_factory_test"


# =============================================================================
# 機能スコアリングテスト
# =============================================================================


class TestCapabilityScoring:
    """機能スコアリングのテスト"""

    def test_score_capability_exact_intent_match(
        self, brain_decision, understanding_task_create
    ):
        """意図が完全一致する場合"""
        score = brain_decision._score_capability(
            "chatwork_task_create",
            brain_decision.capabilities["chatwork_task_create"],
            understanding_task_create,
        )
        # 意図マッチ(1.0 * 0.3) + コンテキスト(0.5 * 0.3) = 0.45以上
        assert score >= 0.4

    def test_score_capability_keyword_match(self, brain_decision):
        """キーワードマッチのテスト"""
        understanding = UnderstandingResult(
            raw_message="タスク作成をお願い",
            intent="unknown",
            intent_confidence=0.5,
            entities={},
        )
        score = brain_decision._score_capability(
            "chatwork_task_create",
            brain_decision.capabilities["chatwork_task_create"],
            understanding,
        )
        # キーワードマッチで正のスコア
        assert score > 0

    def test_score_capability_negative_keyword(self, brain_decision):
        """ネガティブキーワードがある場合"""
        understanding = UnderstandingResult(
            raw_message="タスク検索して完了一覧",
            intent="unknown",
            intent_confidence=0.5,
            entities={},
        )
        # "完了"はchatwork_task_searchのネガティブキーワード
        score = brain_decision._score_capability(
            "chatwork_task_search",
            brain_decision.capabilities["chatwork_task_search"],
            understanding,
        )
        # ネガティブキーワードでスコア0
        assert score == 0.0

    def test_score_capabilities_returns_sorted_list(
        self, brain_decision, understanding_task_create
    ):
        """スコア順にソートされた候補リストを返す"""
        candidates = brain_decision._score_capabilities(understanding_task_create)
        scores = [c.score for c in candidates]
        assert scores == sorted(scores, reverse=True)

    def test_score_capabilities_filters_low_scores(self, brain_decision):
        """低スコアの候補がフィルタされる"""
        understanding = UnderstandingResult(
            raw_message="こんにちは",
            intent="greeting",
            intent_confidence=0.9,
            entities={},
        )
        candidates = brain_decision._score_capabilities(understanding)
        # 全てのスコアが最低閾値を超えている
        for candidate in candidates:
            assert candidate.score > CAPABILITY_MIN_SCORE_THRESHOLD

    def test_calculate_keyword_score_primary_match(self, brain_decision):
        """プライマリキーワードマッチ"""
        score = brain_decision._calculate_keyword_score(
            "chatwork_task_create",
            "タスク作成をお願いします",
        )
        assert score > 0.3

    def test_calculate_keyword_score_secondary_match(self, brain_decision):
        """セカンダリキーワードマッチ"""
        score = brain_decision._calculate_keyword_score(
            "chatwork_task_create",
            "仕事を依頼したい",
        )
        # セカンダリマッチは低いスコア
        assert 0 <= score <= 0.7

    def test_calculate_keyword_score_no_match(self, brain_decision):
        """キーワードマッチなし"""
        score = brain_decision._calculate_keyword_score(
            "chatwork_task_create",
            "天気が良いですね",
        )
        assert score == 0.0

    def test_calculate_intent_score_exact_match(self, brain_decision):
        """意図が完全一致"""
        score = brain_decision._calculate_intent_score(
            "chatwork_task_create",
            "chatwork_task_create",
            brain_decision.capabilities["chatwork_task_create"],
        )
        assert score == 1.0

    def test_calculate_intent_score_category_match(self, brain_decision):
        """カテゴリマッチ"""
        score = brain_decision._calculate_intent_score(
            "chatwork_task_create",
            "task_something",
            brain_decision.capabilities["chatwork_task_create"],
        )
        assert score == 0.6

    def test_calculate_intent_score_no_match(self, brain_decision):
        """意図マッチなし"""
        score = brain_decision._calculate_intent_score(
            "chatwork_task_create",
            "completely_different",
            brain_decision.capabilities["chatwork_task_create"],
        )
        assert score == 0.0

    def test_calculate_context_score_task_with_person(self, brain_decision):
        """タスク関連でpersonエンティティあり"""
        understanding = UnderstandingResult(
            raw_message="タスク",
            intent="unknown",
            intent_confidence=0.5,
            entities={"person": "菊地"},
        )
        score = brain_decision._calculate_context_score(
            "chatwork_task_create",
            understanding,
        )
        assert score == 0.5

    def test_calculate_context_score_no_relevant_entities(self, brain_decision):
        """関連エンティティなし"""
        understanding = UnderstandingResult(
            raw_message="タスク",
            intent="unknown",
            intent_confidence=0.5,
            entities={},
        )
        score = brain_decision._calculate_context_score(
            "chatwork_task_create",
            understanding,
        )
        assert score == 0.0


# =============================================================================
# 複数アクション検出テスト
# =============================================================================


class TestMultipleActionDetection:
    """複数アクション検出のテスト"""

    def test_detect_single_action(self, brain_decision):
        """単一アクションの検出"""
        # 「して」がSPLIT_PATTERNSにマッチするため「タスク作成」になる
        actions = brain_decision._detect_multiple_actions("タスク作成をお願い")
        assert len(actions) == 1
        assert actions[0] == "タスク作成をお願い"

    def test_detect_multiple_actions_with_あと(self, brain_decision):
        """「あと」で区切られた複数アクション"""
        actions = brain_decision._detect_multiple_actions(
            "タスク作成して、あと自分のタスク教えて"
        )
        assert len(actions) >= 2

    def test_detect_multiple_actions_with_それと(self, brain_decision):
        """「それと」で区切られた複数アクション"""
        actions = brain_decision._detect_multiple_actions(
            "タスク作成して。それとタスク一覧見せて"
        )
        assert len(actions) >= 2

    def test_detect_multiple_actions_with_ついでに(self, brain_decision):
        """「ついでに」で区切られた複数アクション"""
        actions = brain_decision._detect_multiple_actions(
            "タスク完了にして、ついでに新しいタスク作って"
        )
        assert len(actions) >= 2

    def test_detect_multiple_actions_filters_short_segments(self, brain_decision):
        """短いセグメントがフィルタされる"""
        actions = brain_decision._detect_multiple_actions("あと。")
        assert len(actions) == 1

    def test_detect_multiple_actions_empty_message(self, brain_decision):
        """空メッセージの場合"""
        actions = brain_decision._detect_multiple_actions("")
        assert len(actions) == 1
        assert actions[0] == ""


# =============================================================================
# 確認要否判断テスト
# =============================================================================


class TestConfirmationDetermination:
    """確認要否判断のテスト"""

    def test_confirmation_required_low_confidence(
        self, brain_decision, understanding_low_confidence, empty_context
    ):
        """低確信度の場合は確認が必要"""
        candidate = ActionCandidate(
            action="chatwork_task_create",
            score=0.5,  # < CONFIRMATION_THRESHOLD (0.7)
            params={},
        )
        needs, question, options = brain_decision._determine_confirmation(
            candidate,
            understanding_low_confidence,
            empty_context,
        )
        assert needs is True
        assert question is not None
        assert "いいウル" in question

    def test_confirmation_required_dangerous_action(
        self, brain_decision, understanding_task_create, empty_context
    ):
        """危険な操作の場合は確認が必要"""
        candidate = ActionCandidate(
            action="delete",  # DANGEROUS_ACTIONS
            score=0.9,
            params={},
        )
        needs, question, options = brain_decision._determine_confirmation(
            candidate,
            understanding_task_create,
            empty_context,
        )
        assert needs is True
        assert "本当に" in question

    def test_confirmation_required_high_risk_level(
        self, brain_decision, understanding_task_create, empty_context
    ):
        """高リスクレベルの場合は確認が必要"""
        candidate = ActionCandidate(
            action="delete",  # RISK_LEVELS["delete"] = "high"
            score=0.9,
            params={},
        )
        needs, question, options = brain_decision._determine_confirmation(
            candidate,
            understanding_task_create,
            empty_context,
        )
        assert needs is True

    def test_confirmation_not_required_high_confidence(
        self, brain_decision, understanding_task_search, empty_context
    ):
        """高確信度で安全な操作は確認不要"""
        candidate = ActionCandidate(
            action="chatwork_task_search",  # 安全な操作
            score=0.9,  # > CONFIRMATION_THRESHOLD
            params={},
        )
        needs, question, options = brain_decision._determine_confirmation(
            candidate,
            understanding_task_search,
            empty_context,
        )
        assert needs is False
        assert question is None

    def test_confirmation_options_default(
        self, brain_decision, understanding_low_confidence, empty_context
    ):
        """デフォルトの選択肢"""
        candidate = ActionCandidate(
            action="chatwork_task_create",
            score=0.5,
            params={},
        )
        needs, question, options = brain_decision._determine_confirmation(
            candidate,
            understanding_low_confidence,
            empty_context,
        )
        assert options == ["はい", "いいえ"]


# =============================================================================
# MVV整合性チェックテスト
# =============================================================================


class TestMVVAlignmentCheck:
    """MVV整合性チェックのテスト"""

    def test_mvv_check_no_ng_pattern(self, brain_decision):
        """NGパターンなしの場合"""
        result = brain_decision._check_mvv_alignment(
            "タスクを作成してください",
            "chatwork_task_create",
        )
        assert result.is_aligned is True
        assert result.ng_pattern_detected is False

    def test_mvv_check_returns_mvv_check_result(self, brain_decision):
        """戻り値の型がMVVCheckResult"""
        result = brain_decision._check_mvv_alignment(
            "タスクを作成して",
            "chatwork_task_create",
        )
        assert isinstance(result, MVVCheckResult)

    @patch("lib.brain.decision._detect_ng_pattern")
    def test_mvv_check_with_ng_pattern(self, mock_detect, brain_decision):
        """NGパターン検出時"""
        # モックでNGパターンを検出
        mock_result = MagicMock()
        mock_result.detected = True
        mock_result.pattern_type = "ng_mental_health"
        mock_result.response_hint = "心に寄り添う対応"
        mock_result.risk_level = MagicMock(value="high")
        mock_detect.return_value = mock_result

        # モジュールをロード済みに設定
        import lib.brain.decision as decision_module
        decision_module._mvv_context_loaded = True
        decision_module._detect_ng_pattern = mock_detect

        result = brain_decision._check_mvv_alignment(
            "辞めたい",
            "unknown",
        )
        assert result.ng_pattern_detected is True
        assert result.ng_pattern_type == "ng_mental_health"
        assert "NGパターン検出" in result.warnings[0]


# =============================================================================
# アクティブセッション処理テスト
# =============================================================================


class TestActiveSessionHandling:
    """アクティブセッション処理のテスト"""

    @pytest.mark.asyncio
    async def test_handle_goal_setting_session(
        self, brain_decision, active_goal_setting_context
    ):
        """目標設定セッション中の処理"""
        understanding = UnderstandingResult(
            raw_message="やりがいを感じたい",
            intent="unknown",
            intent_confidence=0.5,
            entities={},
        )
        result = await brain_decision.decide(
            understanding,
            active_goal_setting_context,
        )
        assert result.action == "continue_goal_setting"
        assert result.params.get("step") == "why"
        assert result.confidence == 1.0

    @pytest.mark.asyncio
    async def test_handle_cancel_during_session(
        self, brain_decision, active_goal_setting_context
    ):
        """セッション中のキャンセル"""
        understanding = UnderstandingResult(
            raw_message="やめる",
            intent="cancel",
            intent_confidence=0.9,
            entities={},
        )
        result = await brain_decision.decide(
            understanding,
            active_goal_setting_context,
        )
        assert result.action == "cancel_session"
        assert result.confidence == 1.0

    @pytest.mark.asyncio
    async def test_handle_announcement_session(self, brain_decision):
        """アナウンスセッション中の処理"""
        state = ConversationState(
            state_id="state_123",
            organization_id="org_test",
            room_id="room_123",
            user_id="user_456",
            state_type=StateType.ANNOUNCEMENT,
            expires_at=datetime.now() + timedelta(minutes=30),
        )
        context = BrainContext(
            room_id="room_123",
            sender_account_id="user_456",
            sender_name="テスト",
            organization_id="org_test",
            current_state=state,
        )
        understanding = UnderstandingResult(
            raw_message="OK",
            intent="confirmation",
            intent_confidence=0.9,
            entities={},
        )
        result = await brain_decision.decide(understanding, context)
        assert result.action == "continue_announcement"

    @pytest.mark.asyncio
    async def test_handle_confirmation_session(self, brain_decision):
        """確認待ちセッション中の処理"""
        state = ConversationState(
            state_id="state_123",
            organization_id="org_test",
            room_id="room_123",
            user_id="user_456",
            state_type=StateType.CONFIRMATION,
            state_data={"pending_action": "chatwork_task_create"},
            expires_at=datetime.now() + timedelta(minutes=5),
        )
        context = BrainContext(
            room_id="room_123",
            sender_account_id="user_456",
            sender_name="テスト",
            organization_id="org_test",
            current_state=state,
        )
        understanding = UnderstandingResult(
            raw_message="はい",
            intent="confirmation",
            intent_confidence=0.9,
            entities={},
        )
        result = await brain_decision.decide(understanding, context)
        assert result.action == "handle_confirmation_response"
        assert result.params.get("pending_action") == "chatwork_task_create"


# =============================================================================
# メイン判断メソッドテスト
# =============================================================================


class TestDecideMethod:
    """decide()メソッドのテスト"""

    @pytest.mark.asyncio
    async def test_decide_with_matching_capability(
        self, brain_decision, understanding_task_create, empty_context
    ):
        """機能にマッチする場合"""
        result = await brain_decision.decide(
            understanding_task_create,
            empty_context,
        )
        assert isinstance(result, DecisionResult)
        assert result.action == "chatwork_task_create"
        assert result.confidence > 0

    @pytest.mark.asyncio
    async def test_decide_with_no_matching_capability(
        self, brain_decision, empty_context
    ):
        """機能にマッチしない場合"""
        understanding = UnderstandingResult(
            raw_message="天気を教えて",
            intent="weather",
            intent_confidence=0.9,
            entities={},
        )
        result = await brain_decision.decide(understanding, empty_context)
        # v10.29.7: general_response → general_conversation（ハンドラー名と統一）
        assert result.action == "general_conversation"
        assert result.confidence == 0.3

    @pytest.mark.asyncio
    async def test_decide_includes_other_candidates(
        self, brain_decision, understanding_task_create, empty_context
    ):
        """他の候補が含まれる"""
        result = await brain_decision.decide(
            understanding_task_create,
            empty_context,
        )
        # other_candidatesは最大5件
        assert len(result.other_candidates) <= 5

    @pytest.mark.asyncio
    async def test_decide_merges_params(
        self, brain_decision, understanding_task_create, empty_context
    ):
        """パラメータがマージされる"""
        result = await brain_decision.decide(
            understanding_task_create,
            empty_context,
        )
        # 理解層のエンティティがパラメータに含まれる
        assert "person" in result.params

    @pytest.mark.asyncio
    async def test_decide_returns_processing_time(
        self, brain_decision, understanding_task_create, empty_context
    ):
        """処理時間が返される"""
        result = await brain_decision.decide(
            understanding_task_create,
            empty_context,
        )
        assert result.processing_time_ms >= 0

    @pytest.mark.asyncio
    async def test_decide_handles_error(self, brain_decision, empty_context):
        """エラー時の処理"""
        # 壊れた理解結果
        understanding = MagicMock()
        understanding.raw_message = "テスト"
        understanding.intent = "test"
        understanding.intent_confidence = 0.5
        understanding.entities = None  # これでエラーを起こす

        result = await brain_decision.decide(understanding, empty_context)
        # エラーでもDecisionResultを返す
        assert isinstance(result, DecisionResult)


# =============================================================================
# キャンセル検出テスト
# =============================================================================


class TestCancelDetection:
    """キャンセル検出のテスト"""

    def test_is_cancel_request_direct(self, brain_decision):
        """直接的なキャンセル"""
        assert brain_decision._is_cancel_request("やめる") is True
        assert brain_decision._is_cancel_request("キャンセル") is True
        assert brain_decision._is_cancel_request("中止") is True

    def test_is_cancel_request_indirect(self, brain_decision):
        """間接的なキャンセル"""
        assert brain_decision._is_cancel_request("やっぱりいい") is True
        assert brain_decision._is_cancel_request("もういいや") is True

    def test_is_cancel_request_not_cancel(self, brain_decision):
        """キャンセルでない場合"""
        assert brain_decision._is_cancel_request("タスク作成して") is False
        assert brain_decision._is_cancel_request("教えて") is False

    def test_is_cancel_request_case_insensitive(self, brain_decision):
        """大文字小文字を無視"""
        assert brain_decision._is_cancel_request("CANCEL") is True
        assert brain_decision._is_cancel_request("Cancel") is True


# =============================================================================
# パラメータ抽出テスト
# =============================================================================


class TestParameterExtraction:
    """パラメータ抽出のテスト"""

    def test_extract_params_from_entities(self, brain_decision, understanding_task_create):
        """エンティティからパラメータを抽出"""
        params = brain_decision._extract_params_for_capability(
            "chatwork_task_create",
            brain_decision.capabilities["chatwork_task_create"],
            understanding_task_create,
        )
        assert "assigned_to" in params
        assert params["assigned_to"] == "菊地"

    def test_extract_params_alias_person_to_assigned_to(self, brain_decision):
        """personエンティティをassigned_toに変換"""
        understanding = UnderstandingResult(
            raw_message="菊地さんにタスク",
            intent="chatwork_task_create",
            intent_confidence=0.9,
            entities={"person": "菊地"},
        )
        params = brain_decision._extract_params_for_capability(
            "chatwork_task_create",
            brain_decision.capabilities["chatwork_task_create"],
            understanding,
        )
        assert params.get("assigned_to") == "菊地"

    def test_extract_params_alias_task_to_task_body(self, brain_decision):
        """taskエンティティをtask_bodyに変換"""
        understanding = UnderstandingResult(
            raw_message="資料作成のタスク",
            intent="chatwork_task_create",
            intent_confidence=0.9,
            entities={"task": "資料作成"},
        )
        params = brain_decision._extract_params_for_capability(
            "chatwork_task_create",
            brain_decision.capabilities["chatwork_task_create"],
            understanding,
        )
        assert params.get("task_body") == "資料作成"

    def test_extract_params_empty_entities(self, brain_decision):
        """エンティティが空の場合"""
        understanding = UnderstandingResult(
            raw_message="タスク",
            intent="chatwork_task_create",
            intent_confidence=0.5,
            entities={},
        )
        params = brain_decision._extract_params_for_capability(
            "chatwork_task_create",
            brain_decision.capabilities["chatwork_task_create"],
            understanding,
        )
        assert params == {}


# =============================================================================
# 機能名取得テスト
# =============================================================================


class TestGetCapabilityName:
    """機能名取得のテスト"""

    def test_get_capability_name_exists(self, brain_decision):
        """機能が存在する場合"""
        name = brain_decision._get_capability_name("chatwork_task_create")
        assert name == "ChatWorkタスク作成"

    def test_get_capability_name_not_exists(self, brain_decision):
        """機能が存在しない場合"""
        name = brain_decision._get_capability_name("unknown_action")
        assert name == "unknown_action"


# =============================================================================
# 判断理由構築テスト
# =============================================================================


class TestBuildReasoning:
    """判断理由構築のテスト"""

    def test_build_reasoning_basic(self, brain_decision, understanding_task_create):
        """基本的な理由構築"""
        candidate = ActionCandidate(
            action="chatwork_task_create",
            score=0.85,
            params={},
        )
        mvv_result = MVVCheckResult()
        reasoning = brain_decision._build_reasoning(
            candidate,
            understanding_task_create,
            mvv_result,
        )
        assert "chatwork_task_create" in reasoning
        assert "0.85" in reasoning

    def test_build_reasoning_with_ng_pattern(self, brain_decision, understanding_task_create):
        """NGパターンありの理由構築"""
        candidate = ActionCandidate(
            action="chatwork_task_create",
            score=0.85,
            params={},
        )
        mvv_result = MVVCheckResult(
            ng_pattern_detected=True,
            ng_pattern_type="ng_mental_health",
        )
        reasoning = brain_decision._build_reasoning(
            candidate,
            understanding_task_create,
            mvv_result,
        )
        assert "ng_mental_health" in reasoning
        assert "Warning" in reasoning


# =============================================================================
# 定数テスト
# =============================================================================


class TestConstants:
    """定数のテスト"""

    def test_capability_keywords_structure(self):
        """CAPABILITY_KEYWORDSの構造"""
        for cap_key, keywords in CAPABILITY_KEYWORDS.items():
            assert "primary" in keywords
            assert "secondary" in keywords
            assert "negative" in keywords
            assert isinstance(keywords["primary"], list)
            assert isinstance(keywords["secondary"], list)
            assert isinstance(keywords["negative"], list)

    def test_decision_prompt_format(self):
        """DECISION_PROMPTのフォーマット"""
        assert "{capabilities_json}" in DECISION_PROMPT
        assert "{intent}" in DECISION_PROMPT
        assert "{confidence}" in DECISION_PROMPT
        assert "{entities}" in DECISION_PROMPT
        assert "{raw_message}" in DECISION_PROMPT
        assert "{context}" in DECISION_PROMPT

    def test_split_patterns_valid_regex(self):
        """SPLIT_PATTERNSが有効な正規表現"""
        import re
        for pattern in SPLIT_PATTERNS:
            try:
                re.compile(pattern)
            except re.error as e:
                pytest.fail(f"Invalid regex pattern: {pattern}, error: {e}")


# =============================================================================
# ユーティリティテスト
# =============================================================================


class TestUtilities:
    """ユーティリティメソッドのテスト"""

    def test_elapsed_ms(self, brain_decision):
        """経過時間計算"""
        import time
        start = time.time() - 0.1  # 100ms前
        elapsed = brain_decision._elapsed_ms(start)
        assert elapsed >= 100
        assert elapsed < 200  # 合理的な範囲


# =============================================================================
# エッジケーステスト
# =============================================================================


class TestEdgeCases:
    """エッジケースのテスト"""

    @pytest.mark.asyncio
    async def test_decide_with_empty_message(self, brain_decision, empty_context):
        """空メッセージの場合"""
        understanding = UnderstandingResult(
            raw_message="",
            intent="unknown",
            intent_confidence=0.0,
            entities={},
        )
        result = await brain_decision.decide(understanding, empty_context)
        assert isinstance(result, DecisionResult)

    @pytest.mark.asyncio
    async def test_decide_with_very_long_message(self, brain_decision, empty_context):
        """非常に長いメッセージの場合"""
        understanding = UnderstandingResult(
            raw_message="タスク" * 1000,  # 非常に長い
            intent="chatwork_task_create",
            intent_confidence=0.7,
            entities={},
        )
        result = await brain_decision.decide(understanding, empty_context)
        assert isinstance(result, DecisionResult)

    @pytest.mark.asyncio
    async def test_decide_with_special_characters(self, brain_decision, empty_context):
        """特殊文字を含むメッセージ"""
        understanding = UnderstandingResult(
            raw_message="タスク作成！？🐺✨",
            intent="chatwork_task_create",
            intent_confidence=0.7,
            entities={},
        )
        result = await brain_decision.decide(understanding, empty_context)
        assert isinstance(result, DecisionResult)

    def test_score_capability_with_empty_capability(self, brain_decision):
        """空の機能定義の場合"""
        empty_cap = {"enabled": True}
        understanding = UnderstandingResult(
            raw_message="テスト",
            intent="test",
            intent_confidence=0.5,
            entities={},
        )
        score = brain_decision._score_capability("empty", empty_cap, understanding)
        assert score >= 0

    def test_detect_multiple_actions_with_only_conjunctions(self, brain_decision):
        """接続詞のみのメッセージ"""
        actions = brain_decision._detect_multiple_actions("あと、それと")
        # 短いセグメントはフィルタされる
        assert len(actions) >= 1

    @pytest.mark.asyncio
    async def test_decide_with_expired_session(self, brain_decision):
        """期限切れセッションの場合"""
        state = ConversationState(
            state_id="state_123",
            organization_id="org_test",
            room_id="room_123",
            user_id="user_456",
            state_type=StateType.GOAL_SETTING,
            expires_at=datetime.now() - timedelta(hours=1),  # 期限切れ
        )
        context = BrainContext(
            room_id="room_123",
            sender_account_id="user_456",
            sender_name="テスト",
            organization_id="org_test",
            current_state=state,
        )
        understanding = UnderstandingResult(
            raw_message="タスク作成して",
            intent="chatwork_task_create",
            intent_confidence=0.9,
            entities={},
        )
        # 期限切れセッションはアクティブでないので通常処理
        result = await brain_decision.decide(understanding, context)
        # セッション継続ではなく、通常の判断が行われる
        assert result.action != "continue_goal_setting"
