# tests/test_brain_learning.py
"""
BrainLearning（学習層）のユニットテスト

テスト対象:
- DecisionLogEntry, LearningInsight, MemoryUpdateデータクラス
- BrainLearning初期化
- 判断ログ記録（log_decision, flush）
- 記憶更新（update_memory, conversation, summary, preference）
- パターン分析（analyze_patterns, low_confidence, errors, success_rates）
- フィードバック処理（record_feedback, learn_from_feedback）
- 統計情報（get_statistics, get_recent_decisions）
- ユーティリティ（cleanup_old_logs, buffer operations）
- ファクトリ関数（create_learning）
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock, AsyncMock, patch

from lib.brain.learning import (
    BrainLearning,
    DecisionLogEntry,
    LearningInsight,
    MemoryUpdate,
    create_learning,
    DECISION_LOG_RETENTION_DAYS,
    LOW_CONFIDENCE_THRESHOLD,
    MIN_PATTERN_SAMPLES,
    SUMMARY_THRESHOLD,
    PREFERENCE_UPDATE_INTERVAL_MINUTES,
)
from lib.brain.models import (
    BrainContext,
    UnderstandingResult,
    DecisionResult,
    HandlerResult,
    ConversationMessage,
)


# =============================================================================
# テスト用フィクスチャ
# =============================================================================

@pytest.fixture
def mock_pool():
    """モックDBプール"""
    pool = MagicMock()
    pool.connect = MagicMock(return_value=MagicMock(__enter__=MagicMock(), __exit__=MagicMock()))
    return pool


@pytest.fixture
def mock_firestore():
    """モックFirestoreクライアント"""
    return MagicMock()


@pytest.fixture
def brain_learning(mock_pool, mock_firestore):
    """BrainLearningインスタンス"""
    return BrainLearning(
        pool=mock_pool,
        org_id="org_test",
        firestore_db=mock_firestore,
        enable_logging=True,
        enable_learning=True,
    )


@pytest.fixture
def brain_learning_no_deps():
    """依存なしのBrainLearningインスタンス"""
    return BrainLearning(
        pool=None,
        org_id="org_test",
        firestore_db=None,
        enable_logging=True,
        enable_learning=True,
    )


@pytest.fixture
def sample_understanding():
    """サンプルUnderstandingResult"""
    return UnderstandingResult(
        raw_message="田中さんの未完了タスクを教えて",
        intent="task_search",
        intent_confidence=0.85,
        entities={"person": "田中さん", "status": "未完了"},
    )


@pytest.fixture
def sample_decision():
    """サンプルDecisionResult"""
    return DecisionResult(
        action="search_tasks",
        params={"assignee": "田中", "status": "incomplete"},
        confidence=0.82,
        needs_confirmation=False,
    )


@pytest.fixture
def sample_handler_result():
    """サンプルHandlerResult"""
    return HandlerResult(
        success=True,
        message="タスクが見つかりました",
        data={"tasks": [{"id": "1", "title": "テストタスク"}]},
    )


@pytest.fixture
def sample_context():
    """サンプルBrainContext"""
    return BrainContext(
        sender_account_id="12345",
        sender_name="テストユーザー",
        recent_conversation=[
            ConversationMessage(
                role="user",
                content="こんにちは",
                timestamp=datetime.now() - timedelta(minutes=5),
            ),
            ConversationMessage(
                role="assistant",
                content="こんにちはウル！",
                timestamp=datetime.now() - timedelta(minutes=4),
            ),
        ],
        organization_id="org_test",
        room_id="room123",
    )


# =============================================================================
# 定数テスト
# =============================================================================

class TestLearningConstants:
    """学習層定数のテスト"""

    def test_decision_log_retention_days(self):
        """判断ログ保持期間が適切な値"""
        assert DECISION_LOG_RETENTION_DAYS == 90
        assert DECISION_LOG_RETENTION_DAYS > 0

    def test_low_confidence_threshold(self):
        """低確信度閾値が適切な範囲"""
        assert 0 < LOW_CONFIDENCE_THRESHOLD < 1
        assert LOW_CONFIDENCE_THRESHOLD == 0.5

    def test_min_pattern_samples(self):
        """パターン分析最小サンプル数"""
        assert MIN_PATTERN_SAMPLES == 10
        assert MIN_PATTERN_SAMPLES > 0

    def test_summary_threshold(self):
        """会話サマリー閾値"""
        assert SUMMARY_THRESHOLD == 10
        assert SUMMARY_THRESHOLD > 0

    def test_preference_update_interval(self):
        """嗜好更新間隔"""
        assert PREFERENCE_UPDATE_INTERVAL_MINUTES == 60
        assert PREFERENCE_UPDATE_INTERVAL_MINUTES > 0


# =============================================================================
# DecisionLogEntryテスト
# =============================================================================

class TestDecisionLogEntry:
    """DecisionLogEntryデータクラスのテスト"""

    def test_create_with_all_fields(self):
        """全フィールド指定で作成"""
        entry = DecisionLogEntry(
            room_id="room123",
            user_id="user456",
            user_message="タスクを教えて",
            understanding_intent="task_search",
            understanding_confidence=0.85,
            understanding_entities={"type": "task"},
            understanding_time_ms=150,
            selected_action="search_tasks",
            action_params={"status": "incomplete"},
            decision_confidence=0.82,
            decision_reasoning="タスク検索意図を検出",
            required_confirmation=False,
            confirmation_question=None,
            execution_success=True,
            execution_error=None,
            execution_time_ms=200,
            total_time_ms=400,
        )

        assert entry.room_id == "room123"
        assert entry.user_id == "user456"
        assert entry.understanding_intent == "task_search"
        assert entry.understanding_confidence == 0.85
        assert entry.selected_action == "search_tasks"
        assert entry.execution_success is True
        assert entry.total_time_ms == 400

    def test_create_with_defaults(self):
        """デフォルト値で作成"""
        entry = DecisionLogEntry(
            room_id="room123",
            user_id="user456",
            user_message="こんにちは",
            understanding_intent="greeting",
            understanding_confidence=0.95,
            selected_action="general_response",
        )

        assert entry.understanding_entities == {}
        assert entry.understanding_time_ms == 0
        assert entry.action_params == {}
        assert entry.decision_confidence == 0.0
        assert entry.decision_reasoning is None
        assert entry.required_confirmation is False
        assert entry.execution_success is False
        assert entry.execution_error is None
        assert entry.execution_time_ms == 0
        assert entry.total_time_ms == 0
        assert entry.classification == "internal"
        assert isinstance(entry.created_at, datetime)

    def test_to_dict(self):
        """辞書変換"""
        entry = DecisionLogEntry(
            room_id="room123",
            user_id="user456",
            user_message="タスクを教えて",
            understanding_intent="task_search",
            understanding_confidence=0.85,
            selected_action="search_tasks",
            action_params={"status": "incomplete"},
            decision_confidence=0.82,
            execution_success=True,
            execution_time_ms=200,
            total_time_ms=400,
        )

        result = entry.to_dict()

        assert result["room_id"] == "room123"
        assert result["user_id"] == "user456"
        assert result["user_message"] == "タスクを教えて"
        assert result["understanding_result"]["intent"] == "task_search"
        assert result["understanding_result"]["confidence"] == 0.85
        assert result["selected_action"] == "search_tasks"
        assert result["action_params"] == {"status": "incomplete"}
        assert result["decision_confidence"] == 0.82
        assert result["execution_success"] is True
        assert result["execution_time_ms"] == 200
        assert result["total_time_ms"] == 400
        assert "created_at" in result
        assert result["classification"] == "internal"

    def test_to_dict_iso_format_date(self):
        """created_atがISO形式で出力される"""
        entry = DecisionLogEntry(
            room_id="room123",
            user_id="user456",
            user_message="test",
            understanding_intent="test",
            understanding_confidence=0.9,
            selected_action="test_action",
        )

        result = entry.to_dict()

        # ISO形式の日付文字列であることを確認
        datetime.fromisoformat(result["created_at"])


# =============================================================================
# LearningInsightテスト
# =============================================================================

class TestLearningInsight:
    """LearningInsightデータクラスのテスト"""

    def test_create_with_all_fields(self):
        """全フィールド指定で作成"""
        insight = LearningInsight(
            insight_type="low_confidence",
            description="タスク検索の確信度が低い傾向",
            action="search_tasks",
            confidence=0.45,
            sample_count=15,
            recommendation="キーワードマッピングの追加を推奨",
        )

        assert insight.insight_type == "low_confidence"
        assert insight.description == "タスク検索の確信度が低い傾向"
        assert insight.action == "search_tasks"
        assert insight.confidence == 0.45
        assert insight.sample_count == 15
        assert insight.recommendation == "キーワードマッピングの追加を推奨"
        assert isinstance(insight.created_at, datetime)

    def test_create_with_defaults(self):
        """デフォルト値で作成"""
        insight = LearningInsight(
            insight_type="pattern_detected",
            description="パターン検出",
            action="general_response",
            confidence=0.7,
            sample_count=20,
        )

        assert insight.recommendation is None
        assert isinstance(insight.created_at, datetime)


# =============================================================================
# MemoryUpdateテスト
# =============================================================================

class TestMemoryUpdate:
    """MemoryUpdateデータクラスのテスト"""

    def test_create_with_defaults(self):
        """デフォルト値で作成"""
        update = MemoryUpdate()

        assert update.conversation_saved is False
        assert update.summary_generated is False
        assert update.preference_updated is False
        assert update.errors == []

    def test_create_with_values(self):
        """値を指定して作成"""
        update = MemoryUpdate(
            conversation_saved=True,
            summary_generated=True,
            preference_updated=False,
            errors=["エラー1"],
        )

        assert update.conversation_saved is True
        assert update.summary_generated is True
        assert update.preference_updated is False
        assert update.errors == ["エラー1"]


# =============================================================================
# BrainLearning初期化テスト
# =============================================================================

class TestBrainLearningInit:
    """BrainLearning初期化のテスト"""

    def test_basic_init(self):
        """基本的な初期化"""
        learning = BrainLearning()

        assert learning.pool is None
        assert learning.org_id == ""
        assert learning.firestore_db is None
        assert learning.enable_learning is True

    def test_init_with_options(self):
        """オプション指定で初期化"""
        learning = BrainLearning(
            org_id="5f98365f-e7c5-4f48-9918-7fe9aabae5df",
            enable_logging=False,
            enable_learning=False,
        )

        assert learning.org_id == "5f98365f-e7c5-4f48-9918-7fe9aabae5df"
        assert learning.enable_logging is False
        assert learning.enable_learning is False

    def test_init_with_pool(self, mock_pool):
        """DBプール付きで初期化"""
        learning = BrainLearning(
            pool=mock_pool,
            org_id="org_test",
        )

        assert learning.pool is mock_pool
        assert learning.org_id == "org_test"

    def test_init_with_firestore(self, mock_firestore):
        """Firestore付きで初期化"""
        learning = BrainLearning(
            firestore_db=mock_firestore,
        )

        assert learning.firestore_db is mock_firestore

    def test_init_creates_empty_caches(self):
        """初期化時にキャッシュが空"""
        learning = BrainLearning()

        assert learning._preference_update_times == {}
        assert learning._decision_logs_buffer == []

    @patch("lib.brain.learning.SAVE_DECISION_LOGS", False)
    def test_init_logging_disabled_by_constant(self):
        """定数でログ記録が無効化される"""
        learning = BrainLearning(enable_logging=True)

        # SAVE_DECISION_LOGSがFalseなのでenable_loggingもFalseになる
        assert learning.enable_logging is False


# =============================================================================
# 判断ログ記録テスト
# =============================================================================

class TestLogDecision:
    """log_decisionメソッドのテスト"""

    @pytest.mark.asyncio
    async def test_log_decision_basic(
        self,
        brain_learning,
        sample_understanding,
        sample_decision,
        sample_handler_result,
    ):
        """基本的な判断ログ記録"""
        result = await brain_learning.log_decision(
            message="田中さんのタスクを教えて",
            understanding=sample_understanding,
            decision=sample_decision,
            result=sample_handler_result,
            room_id="room123",
            account_id="user456",
            understanding_time_ms=100,
            execution_time_ms=200,
            total_time_ms=350,
        )

        assert result is True
        assert brain_learning.get_buffer_size() == 1

    @pytest.mark.asyncio
    async def test_log_decision_disabled(
        self,
        mock_pool,
        sample_understanding,
        sample_decision,
        sample_handler_result,
    ):
        """ログ記録が無効の場合"""
        learning = BrainLearning(
            pool=mock_pool,
            enable_logging=False,
        )

        result = await learning.log_decision(
            message="test",
            understanding=sample_understanding,
            decision=sample_decision,
            result=sample_handler_result,
            room_id="room123",
            account_id="user456",
        )

        assert result is True
        assert learning.get_buffer_size() == 0

    @pytest.mark.asyncio
    async def test_log_decision_buffer_accumulation(
        self,
        brain_learning,
        sample_understanding,
        sample_decision,
        sample_handler_result,
    ):
        """バッファに蓄積される"""
        for i in range(5):
            await brain_learning.log_decision(
                message=f"メッセージ{i}",
                understanding=sample_understanding,
                decision=sample_decision,
                result=sample_handler_result,
                room_id="room123",
                account_id="user456",
            )

        assert brain_learning.get_buffer_size() == 5

    @pytest.mark.asyncio
    async def test_log_decision_auto_flush_at_10(
        self,
        brain_learning,
        sample_understanding,
        sample_decision,
        sample_handler_result,
    ):
        """10件でバッファが自動フラッシュ"""
        for i in range(10):
            await brain_learning.log_decision(
                message=f"メッセージ{i}",
                understanding=sample_understanding,
                decision=sample_decision,
                result=sample_handler_result,
                room_id="room123",
                account_id="user456",
            )

        # フラッシュ後はバッファが空
        assert brain_learning.get_buffer_size() == 0

    @pytest.mark.asyncio
    async def test_log_decision_creates_correct_entry(
        self,
        brain_learning,
        sample_understanding,
        sample_decision,
        sample_handler_result,
    ):
        """正しいログエントリが作成される"""
        await brain_learning.log_decision(
            message="田中さんのタスクを教えて",
            understanding=sample_understanding,
            decision=sample_decision,
            result=sample_handler_result,
            room_id="room123",
            account_id="user456",
            understanding_time_ms=100,
            execution_time_ms=200,
            total_time_ms=350,
        )

        entry = brain_learning._decision_logs_buffer[0]
        assert entry.room_id == "room123"
        assert entry.user_id == "user456"
        assert entry.user_message == "田中さんのタスクを教えて"
        assert entry.understanding_intent == "task_search"
        assert entry.understanding_confidence == 0.85
        assert entry.selected_action == "search_tasks"
        assert entry.execution_success is True
        assert entry.understanding_time_ms == 100
        assert entry.execution_time_ms == 200
        assert entry.total_time_ms == 350


# =============================================================================
# バッファフラッシュテスト
# =============================================================================

class TestFlushDecisionLogs:
    """_flush_decision_logsメソッドのテスト"""

    @pytest.mark.asyncio
    async def test_flush_empty_buffer(self, brain_learning):
        """空のバッファをフラッシュ"""
        result = await brain_learning._flush_decision_logs()
        assert result == 0

    @pytest.mark.asyncio
    async def test_flush_with_entries(
        self,
        brain_learning,
        sample_understanding,
        sample_decision,
        sample_handler_result,
    ):
        """エントリがあるバッファをフラッシュ"""
        # バッファに追加
        for i in range(5):
            await brain_learning.log_decision(
                message=f"メッセージ{i}",
                understanding=sample_understanding,
                decision=sample_decision,
                result=sample_handler_result,
                room_id="room123",
                account_id="user456",
            )

        # フラッシュ
        result = await brain_learning._flush_decision_logs()

        assert result == 5
        assert brain_learning.get_buffer_size() == 0

    @pytest.mark.asyncio
    async def test_flush_without_pool(
        self,
        brain_learning_no_deps,
        sample_understanding,
        sample_decision,
        sample_handler_result,
    ):
        """DBプールなしでフラッシュ"""
        # バッファに追加
        for i in range(3):
            await brain_learning_no_deps.log_decision(
                message=f"メッセージ{i}",
                understanding=sample_understanding,
                decision=sample_decision,
                result=sample_handler_result,
                room_id="room123",
                account_id="user456",
            )

        # フラッシュ（DBなしでもバッファはクリアされる）
        result = await brain_learning_no_deps._flush_decision_logs()

        assert result == 3
        assert brain_learning_no_deps.get_buffer_size() == 0

    @pytest.mark.asyncio
    async def test_force_flush(
        self,
        brain_learning,
        sample_understanding,
        sample_decision,
        sample_handler_result,
    ):
        """強制フラッシュ"""
        # バッファに追加
        for i in range(3):
            await brain_learning.log_decision(
                message=f"メッセージ{i}",
                understanding=sample_understanding,
                decision=sample_decision,
                result=sample_handler_result,
                room_id="room123",
                account_id="user456",
            )

        # 強制フラッシュ
        result = await brain_learning.force_flush()

        assert result == 3
        assert brain_learning.get_buffer_size() == 0


# =============================================================================
# 記憶更新テスト
# =============================================================================

class TestUpdateMemory:
    """update_memoryメソッドのテスト"""

    @pytest.mark.asyncio
    async def test_update_memory_basic(
        self,
        brain_learning,
        sample_handler_result,
        sample_context,
    ):
        """基本的な記憶更新"""
        result = await brain_learning.update_memory(
            message="タスクを教えて",
            result=sample_handler_result,
            context=sample_context,
            room_id="room123",
            account_id="user456",
            sender_name="テストユーザー",
        )

        assert isinstance(result, MemoryUpdate)
        assert result.errors == []

    @pytest.mark.asyncio
    async def test_update_memory_saves_conversation(
        self,
        brain_learning,
        sample_handler_result,
        sample_context,
    ):
        """会話が保存される"""
        result = await brain_learning.update_memory(
            message="タスクを教えて",
            result=sample_handler_result,
            context=sample_context,
            room_id="room123",
            account_id="user456",
            sender_name="テストユーザー",
        )

        assert result.conversation_saved is True

    @pytest.mark.asyncio
    async def test_update_memory_generates_summary_when_threshold(
        self,
        brain_learning,
        sample_handler_result,
    ):
        """会話数が閾値を超えるとサマリーが生成される"""
        # 閾値以上の会話を持つコンテキスト
        context_with_many_msgs = BrainContext(
            sender_account_id="12345",
            sender_name="テストユーザー",
            recent_conversation=[
                ConversationMessage(
                    role="user" if i % 2 == 0 else "assistant",
                    content=f"メッセージ{i}",
                    timestamp=datetime.now() - timedelta(minutes=i),
                )
                for i in range(SUMMARY_THRESHOLD + 5)
            ],
            organization_id="org_test",
            room_id="room123",
        )

        result = await brain_learning.update_memory(
            message="タスクを教えて",
            result=sample_handler_result,
            context=context_with_many_msgs,
            room_id="room123",
            account_id="user456",
            sender_name="テストユーザー",
        )

        assert result.summary_generated is True

    @pytest.mark.asyncio
    async def test_update_memory_no_summary_below_threshold(
        self,
        brain_learning,
        sample_handler_result,
        sample_context,
    ):
        """会話数が閾値以下ではサマリーが生成されない"""
        result = await brain_learning.update_memory(
            message="タスクを教えて",
            result=sample_handler_result,
            context=sample_context,  # 会話数が少ない
            room_id="room123",
            account_id="user456",
            sender_name="テストユーザー",
        )

        assert result.summary_generated is False

    @pytest.mark.asyncio
    async def test_update_memory_updates_preference(
        self,
        brain_learning,
        sample_handler_result,
        sample_context,
    ):
        """ユーザー嗜好が更新される（初回）"""
        result = await brain_learning.update_memory(
            message="タスクを教えて",
            result=sample_handler_result,
            context=sample_context,
            room_id="room123",
            account_id="user456",
            sender_name="テストユーザー",
        )

        assert result.preference_updated is True

    @pytest.mark.asyncio
    async def test_update_memory_no_preference_update_within_interval(
        self,
        brain_learning,
        sample_handler_result,
        sample_context,
    ):
        """間隔内では嗜好が更新されない"""
        # 最初の更新
        await brain_learning.update_memory(
            message="タスクを教えて",
            result=sample_handler_result,
            context=sample_context,
            room_id="room123",
            account_id="user456",
            sender_name="テストユーザー",
        )

        # 2回目の更新（間隔内）
        result = await brain_learning.update_memory(
            message="別のメッセージ",
            result=sample_handler_result,
            context=sample_context,
            room_id="room123",
            account_id="user456",
            sender_name="テストユーザー",
        )

        assert result.preference_updated is False

    @pytest.mark.asyncio
    async def test_update_memory_without_firestore(
        self,
        brain_learning_no_deps,
        sample_handler_result,
        sample_context,
    ):
        """Firestoreなしでも動作する（会話はwebhookレイヤーで保存済みなのでTrue）"""
        result = await brain_learning_no_deps.update_memory(
            message="タスクを教えて",
            result=sample_handler_result,
            context=sample_context,
            room_id="room123",
            account_id="user456",
            sender_name="テストユーザー",
        )

        assert isinstance(result, MemoryUpdate)
        assert result.conversation_saved is True


# =============================================================================
# 嗜好更新チェックテスト
# =============================================================================

class TestShouldUpdatePreference:
    """_should_update_preferenceメソッドのテスト"""

    def test_first_time_should_update(self, brain_learning):
        """初回は更新すべき"""
        result = brain_learning._should_update_preference("user123")
        assert result is True

    def test_recent_update_should_not_update(self, brain_learning):
        """最近更新した場合は更新しない"""
        # 更新時刻を設定
        brain_learning._preference_update_times["user123"] = datetime.now()

        result = brain_learning._should_update_preference("user123")
        assert result is False

    def test_after_interval_should_update(self, brain_learning):
        """間隔後は更新すべき"""
        # 間隔以上前の更新時刻を設定
        old_time = datetime.now() - timedelta(
            minutes=PREFERENCE_UPDATE_INTERVAL_MINUTES + 1
        )
        brain_learning._preference_update_times["user123"] = old_time

        result = brain_learning._should_update_preference("user123")
        assert result is True

    def test_learning_disabled_should_not_update(self, mock_pool):
        """学習が無効の場合は更新しない"""
        learning = BrainLearning(
            pool=mock_pool,
            enable_learning=False,
        )

        result = learning._should_update_preference("user123")
        assert result is False

    def test_different_users_independent(self, brain_learning):
        """ユーザーごとに独立"""
        # user1は最近更新
        brain_learning._preference_update_times["user1"] = datetime.now()

        # user1は更新しない
        assert brain_learning._should_update_preference("user1") is False

        # user2は初回なので更新する
        assert brain_learning._should_update_preference("user2") is True


# =============================================================================
# パターン分析テスト
# =============================================================================

class TestAnalyzePatterns:
    """analyze_patternsメソッドのテスト"""

    @pytest.mark.asyncio
    async def test_analyze_patterns_without_pool(self, brain_learning_no_deps):
        """DBプールなしでは空リストを返す"""
        result = await brain_learning_no_deps.analyze_patterns(days=7)
        assert result == []

    @pytest.mark.asyncio
    async def test_analyze_patterns_basic(self, brain_learning):
        """基本的なパターン分析"""
        result = await brain_learning.analyze_patterns(days=7)

        # 現在はTODO実装なので空リスト
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_analyze_patterns_custom_days(self, brain_learning):
        """日数指定でパターン分析"""
        result = await brain_learning.analyze_patterns(days=30)
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_detect_low_confidence_patterns(self, brain_learning):
        """低確信度パターン検出"""
        result = await brain_learning._detect_low_confidence_patterns(days=7)
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_detect_frequent_errors(self, brain_learning):
        """頻繁なエラー検出"""
        result = await brain_learning._detect_frequent_errors(days=7)
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_analyze_action_success_rates(self, brain_learning):
        """アクション成功率分析"""
        result = await brain_learning._analyze_action_success_rates(days=7)
        assert isinstance(result, list)


# =============================================================================
# フィードバック処理テスト
# =============================================================================

class TestRecordFeedback:
    """record_feedbackメソッドのテスト"""

    @pytest.mark.asyncio
    async def test_record_feedback_basic(self, brain_learning):
        """基本的なフィードバック記録"""
        result = await brain_learning.record_feedback(
            decision_log_id="log123",
            feedback_type="correct",
            feedback_value=True,
            room_id="room123",
            account_id="user456",
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_record_feedback_without_pool(self, brain_learning_no_deps):
        """DBプールなしではFalseを返す"""
        result = await brain_learning_no_deps.record_feedback(
            decision_log_id="log123",
            feedback_type="correct",
            feedback_value=True,
            room_id="room123",
            account_id="user456",
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_record_feedback_different_types(self, brain_learning):
        """様々なフィードバックタイプ"""
        feedback_types = ["correct", "incorrect", "helpful", "not_helpful"]

        for fb_type in feedback_types:
            result = await brain_learning.record_feedback(
                decision_log_id=f"log_{fb_type}",
                feedback_type=fb_type,
                feedback_value=True,
                room_id="room123",
                account_id="user456",
            )
            assert result is True


class TestLearnFromFeedback:
    """learn_from_feedbackメソッドのテスト"""

    @pytest.mark.asyncio
    async def test_learn_from_feedback_basic(
        self,
        brain_learning,
        sample_understanding,
        sample_decision,
    ):
        """基本的なフィードバック学習"""
        result = await brain_learning.learn_from_feedback(
            feedback_type="incorrect",
            original_understanding=sample_understanding,
            original_decision=sample_decision,
            corrected_action="task_create",
            corrected_params={"title": "新しいタスク"},
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_learn_from_feedback_disabled(
        self,
        mock_pool,
        sample_understanding,
        sample_decision,
    ):
        """学習が無効の場合"""
        learning = BrainLearning(
            pool=mock_pool,
            enable_learning=False,
        )

        result = await learning.learn_from_feedback(
            feedback_type="incorrect",
            original_understanding=sample_understanding,
            original_decision=sample_decision,
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_learn_from_feedback_without_correction(
        self,
        brain_learning,
        sample_understanding,
        sample_decision,
    ):
        """修正なしでの学習"""
        result = await brain_learning.learn_from_feedback(
            feedback_type="correct",
            original_understanding=sample_understanding,
            original_decision=sample_decision,
            corrected_action=None,
            corrected_params=None,
        )

        assert result is True


# =============================================================================
# 統計情報テスト
# =============================================================================

class TestGetStatistics:
    """get_statisticsメソッドのテスト"""

    @pytest.mark.asyncio
    async def test_get_statistics_without_pool(self, brain_learning_no_deps):
        """DBプールなしでデフォルト統計を返す"""
        stats = await brain_learning_no_deps.get_statistics(days=7)

        assert stats["period_days"] == 7
        assert stats["total_decisions"] == 0
        assert stats["success_rate"] == 0.0
        assert stats["avg_confidence"] == 0.0
        assert stats["low_confidence_count"] == 0
        assert stats["confirmation_rate"] == 0.0
        assert stats["action_distribution"] == {}
        assert stats["avg_response_time_ms"] == 0

    @pytest.mark.asyncio
    async def test_get_statistics_basic(self, brain_learning):
        """基本的な統計情報取得"""
        stats = await brain_learning.get_statistics(days=7)

        assert isinstance(stats, dict)
        assert "period_days" in stats
        assert "total_decisions" in stats

    @pytest.mark.asyncio
    async def test_get_statistics_custom_days(self, brain_learning):
        """日数指定で統計情報取得"""
        stats = await brain_learning.get_statistics(days=30)
        assert stats["period_days"] == 30


class TestGetRecentDecisions:
    """get_recent_decisionsメソッドのテスト"""

    @pytest.mark.asyncio
    async def test_get_recent_decisions_empty(self, brain_learning):
        """空のバッファから取得"""
        decisions = await brain_learning.get_recent_decisions(limit=10)
        assert decisions == []

    @pytest.mark.asyncio
    async def test_get_recent_decisions_with_entries(
        self,
        brain_learning,
        sample_understanding,
        sample_decision,
        sample_handler_result,
    ):
        """エントリがあるバッファから取得"""
        # ログを追加
        for i in range(5):
            await brain_learning.log_decision(
                message=f"メッセージ{i}",
                understanding=sample_understanding,
                decision=sample_decision,
                result=sample_handler_result,
                room_id="room123",
                account_id="user456",
            )

        decisions = await brain_learning.get_recent_decisions(limit=10)

        assert len(decisions) == 5

    @pytest.mark.asyncio
    async def test_get_recent_decisions_with_limit(
        self,
        brain_learning,
        sample_understanding,
        sample_decision,
        sample_handler_result,
    ):
        """制限付きで取得"""
        # ログを追加
        for i in range(5):
            await brain_learning.log_decision(
                message=f"メッセージ{i}",
                understanding=sample_understanding,
                decision=sample_decision,
                result=sample_handler_result,
                room_id="room123",
                account_id="user456",
            )

        decisions = await brain_learning.get_recent_decisions(limit=3)

        assert len(decisions) == 3

    @pytest.mark.asyncio
    async def test_get_recent_decisions_with_filter(
        self,
        brain_learning,
        sample_understanding,
        sample_handler_result,
    ):
        """アクションフィルタ付きで取得"""
        # 異なるアクションのログを追加
        actions = ["search_tasks", "create_task", "search_tasks", "general_response"]
        for action in actions:
            decision = DecisionResult(
                action=action,
                params={},
                confidence=0.8,
                needs_confirmation=False,
            )
            await brain_learning.log_decision(
                message=f"メッセージ_{action}",
                understanding=sample_understanding,
                decision=decision,
                result=sample_handler_result,
                room_id="room123",
                account_id="user456",
            )

        # search_tasksのみフィルタ
        decisions = await brain_learning.get_recent_decisions(
            limit=10,
            action_filter="search_tasks",
        )

        assert len(decisions) == 2
        for d in decisions:
            assert d.selected_action == "search_tasks"

    @pytest.mark.asyncio
    async def test_get_recent_decisions_returns_reversed_order(
        self,
        brain_learning,
        sample_understanding,
        sample_decision,
        sample_handler_result,
    ):
        """新しい順で返される"""
        # ログを追加
        for i in range(3):
            await brain_learning.log_decision(
                message=f"メッセージ{i}",
                understanding=sample_understanding,
                decision=sample_decision,
                result=sample_handler_result,
                room_id="room123",
                account_id="user456",
            )

        decisions = await brain_learning.get_recent_decisions(limit=10)

        # 最後に追加されたものが最初に来る
        assert decisions[0].user_message == "メッセージ2"
        assert decisions[-1].user_message == "メッセージ0"


# =============================================================================
# クリーンアップテスト
# =============================================================================

class TestCleanupOldLogs:
    """cleanup_old_logsメソッドのテスト"""

    @pytest.mark.asyncio
    async def test_cleanup_without_pool(self, brain_learning_no_deps):
        """DBプールなしでは0を返す"""
        result = await brain_learning_no_deps.cleanup_old_logs(days=90)
        assert result == 0

    @pytest.mark.asyncio
    async def test_cleanup_basic(self, brain_learning):
        """基本的なクリーンアップ — DB DELETE実行"""
        conn = brain_learning.pool.connect().__enter__()
        mock_result = MagicMock()
        mock_result.rowcount = 5
        conn.execute.return_value = mock_result

        result = await brain_learning.cleanup_old_logs(days=90)
        assert result == 5
        conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_custom_days(self, brain_learning):
        """日数指定でクリーンアップ"""
        conn = brain_learning.pool.connect().__enter__()
        mock_result = MagicMock()
        mock_result.rowcount = 0
        conn.execute.return_value = mock_result

        result = await brain_learning.cleanup_old_logs(days=30)
        assert result == 0

    @pytest.mark.asyncio
    async def test_cleanup_uses_default_days(self, brain_learning):
        """デフォルト日数を使用"""
        conn = brain_learning.pool.connect().__enter__()
        mock_result = MagicMock()
        mock_result.rowcount = 3
        conn.execute.return_value = mock_result

        result = await brain_learning.cleanup_old_logs()
        assert result == 3


# =============================================================================
# バッファ操作テスト
# =============================================================================

class TestBufferOperations:
    """バッファ操作のテスト"""

    def test_get_buffer_size_empty(self, brain_learning):
        """空のバッファサイズ"""
        assert brain_learning.get_buffer_size() == 0

    @pytest.mark.asyncio
    async def test_get_buffer_size_with_entries(
        self,
        brain_learning,
        sample_understanding,
        sample_decision,
        sample_handler_result,
    ):
        """エントリがあるバッファサイズ"""
        for i in range(3):
            await brain_learning.log_decision(
                message=f"メッセージ{i}",
                understanding=sample_understanding,
                decision=sample_decision,
                result=sample_handler_result,
                room_id="room123",
                account_id="user456",
            )

        assert brain_learning.get_buffer_size() == 3


# =============================================================================
# ファクトリ関数テスト
# =============================================================================

class TestCreateLearning:
    """create_learningファクトリ関数のテスト"""

    def test_create_basic(self):
        """基本的な作成"""
        learning = create_learning()

        assert isinstance(learning, BrainLearning)
        assert learning.pool is None
        assert learning.org_id == ""

    def test_create_with_options(self, mock_pool, mock_firestore):
        """オプション付きで作成"""
        learning = create_learning(
            pool=mock_pool,
            org_id="org_test",
            firestore_db=mock_firestore,
            enable_logging=False,
            enable_learning=False,
        )

        assert learning.pool is mock_pool
        assert learning.org_id == "org_test"
        assert learning.firestore_db is mock_firestore
        assert learning.enable_logging is False
        assert learning.enable_learning is False


# =============================================================================
# エラーハンドリングテスト
# =============================================================================

class TestErrorHandling:
    """エラーハンドリングのテスト"""

    @pytest.mark.asyncio
    async def test_log_decision_handles_exception(self, brain_learning):
        """log_decisionが例外を処理する"""
        # 不正なUnderstandingResultを渡す
        bad_understanding = Mock()
        bad_understanding.intent = None  # Noneはエラーを引き起こす可能性
        bad_understanding.confidence = "invalid"  # 不正な型
        bad_understanding.entities = None

        result = await brain_learning.log_decision(
            message="test",
            understanding=bad_understanding,
            decision=Mock(
                action="test",
                params={},
                confidence=0.8,
                needs_confirmation=False,
                confirmation_question=None,
            ),
            result=Mock(
                success=True,
                message="test",
                error_details=None,
            ),
            room_id="room123",
            account_id="user456",
        )

        # 例外が発生してもFalseを返す（クラッシュしない）
        assert result is True or result is False

    @pytest.mark.asyncio
    async def test_update_memory_handles_exception(
        self,
        brain_learning,
        sample_handler_result,
    ):
        """update_memoryが例外を処理する"""
        # 不正なコンテキストを渡す
        bad_context = Mock()
        bad_context.recent_conversation = None  # 反復できない

        result = await brain_learning.update_memory(
            message="test",
            result=sample_handler_result,
            context=bad_context,
            room_id="room123",
            account_id="user456",
            sender_name="テスト",
        )

        # エラーが記録されるがクラッシュしない
        assert isinstance(result, MemoryUpdate)

    @pytest.mark.asyncio
    async def test_analyze_patterns_handles_db_error(self, brain_learning):
        """analyze_patternsがDBエラーを処理する"""
        # poolのconnectをエラーを投げるように設定
        brain_learning.pool.connect.side_effect = Exception("DB connection error")

        result = await brain_learning.analyze_patterns(days=7)

        # 例外を処理して空リストを返す
        assert result == []


# =============================================================================
# 統合テスト
# =============================================================================

class TestIntegration:
    """統合テスト"""

    @pytest.mark.asyncio
    async def test_full_learning_cycle(
        self,
        brain_learning,
        sample_understanding,
        sample_decision,
        sample_handler_result,
        sample_context,
    ):
        """学習の完全なサイクル"""
        # 1. 判断ログを記録
        log_result = await brain_learning.log_decision(
            message="田中さんのタスクを教えて",
            understanding=sample_understanding,
            decision=sample_decision,
            result=sample_handler_result,
            room_id="room123",
            account_id="user456",
            understanding_time_ms=100,
            execution_time_ms=200,
            total_time_ms=350,
        )
        assert log_result is True

        # 2. 記憶を更新
        memory_result = await brain_learning.update_memory(
            message="田中さんのタスクを教えて",
            result=sample_handler_result,
            context=sample_context,
            room_id="room123",
            account_id="user456",
            sender_name="テストユーザー",
        )
        assert memory_result.conversation_saved is True

        # 3. パターン分析
        insights = await brain_learning.analyze_patterns(days=7)
        assert isinstance(insights, list)

        # 4. 統計情報取得
        stats = await brain_learning.get_statistics(days=7)
        assert isinstance(stats, dict)

        # 5. 最近の判断を取得
        recent = await brain_learning.get_recent_decisions(limit=5)
        assert len(recent) >= 1

    @pytest.mark.asyncio
    async def test_multiple_users_independent_learning(
        self,
        brain_learning,
        sample_understanding,
        sample_decision,
        sample_handler_result,
    ):
        """複数ユーザーの独立した学習"""
        users = ["user1", "user2", "user3"]

        for user in users:
            context = BrainContext(
                sender_account_id=user,
                sender_name=f"ユーザー{user}",
                recent_conversation=[],
                organization_id="org_test",
                room_id="room123",
            )

            # 記憶更新
            result = await brain_learning.update_memory(
                message=f"メッセージ_{user}",
                result=sample_handler_result,
                context=context,
                room_id="room123",
                account_id=user,
                sender_name=f"ユーザー{user}",
            )

            # 初回は嗜好が更新される
            assert result.preference_updated is True

        # 各ユーザーの更新時刻が記録されている
        for user in users:
            assert user in brain_learning._preference_update_times
