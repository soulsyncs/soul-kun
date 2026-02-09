# tests/test_llm_brain_context_builder.py
"""
LLM Brain - Context Builder のテスト

LLM Brainに渡すコンテキストを構築する機能をテストします。

設計書: docs/25_llm_native_brain_architecture.md セクション5.1
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, timedelta

from lib.brain.context_builder import (
    LLMContext,
    ContextBuilder,
    Message,
    UserPreferences,
    PersonInfo,
    TaskInfo,
    GoalInfo,
    CEOTeaching,
    SessionState,
    KnowledgeChunk,
)


# =============================================================================
# フィクスチャ
# =============================================================================


@pytest.fixture
def sample_message():
    """テスト用のMessage"""
    return Message(
        role="user",
        content="タスク追加して",
        timestamp=datetime.now(),
    )


@pytest.fixture
def sample_user_preferences():
    """テスト用のUserPreferences"""
    return UserPreferences(
        preferred_name="カズさん",
        report_format="簡潔",
        notification_time="09:00",
        other_preferences={"language": "ja"},
    )


@pytest.fixture
def sample_person_info():
    """テスト用のPersonInfo"""
    return PersonInfo(
        name="田中太郎",
        department="営業部",
        role="manager",
        attributes={"email": "tanaka@example.com"},
    )


@pytest.fixture
def sample_task_info():
    """テスト用のTaskInfo（統一版: lib/brain/models.py）"""
    return TaskInfo(
        task_id="task_001",
        title="資料作成",
        due_date=datetime.now() + timedelta(days=1),
        status="open",
        assignee_name="user_001",  # assigned_to -> assignee_name
        is_overdue=False,
    )


@pytest.fixture
def sample_goal_info():
    """テスト用のGoalInfo"""
    return GoalInfo(
        goal_id="goal_001",
        title="売上目標達成",
        progress=50.0,
        status="active",
        deadline=datetime.now() + timedelta(days=30),
    )


@pytest.fixture
def sample_ceo_teaching():
    """テスト用のCEOTeaching"""
    return CEOTeaching(
        content="お客様第一",
        category="行動指針",
        priority=1,
        created_at=datetime.now(),
    )


@pytest.fixture
def sample_session_state():
    """テスト用のSessionState"""
    return SessionState(
        mode="normal",
        pending_action=None,
    )


@pytest.fixture
def sample_llm_context(
    sample_message,
    sample_user_preferences,
    sample_person_info,
    sample_task_info,
    sample_goal_info,
    sample_ceo_teaching,
):
    """テスト用のLLMContext"""
    return LLMContext(
        user_id="user_001",
        user_name="テストユーザー",
        user_role="member",
        organization_id="org_test",
        room_id="room_123",
        current_datetime=datetime.now(),
        session_state=None,
        recent_messages=[sample_message],
        user_preferences=sample_user_preferences,
        known_persons=[sample_person_info],
        recent_tasks=[sample_task_info],
        active_goals=[sample_goal_info],
        ceo_teachings=[sample_ceo_teaching],
    )


# =============================================================================
# Message データクラステスト
# =============================================================================


class TestMessage:
    """Messageデータクラスのテスト"""

    def test_init(self):
        """初期化できること"""
        msg = Message(
            role="user",
            content="テストメッセージ",
            timestamp=datetime.now(),
        )
        assert msg.role == "user"
        assert msg.content == "テストメッセージ"
        assert msg.timestamp is not None

    def test_init_with_defaults(self):
        """デフォルト値で初期化できること"""
        msg = Message(role="assistant", content="応答")
        assert msg.role == "assistant"
        assert msg.content == "応答"
        assert msg.timestamp is None

    def test_message_content(self):
        """contentが正しく保持されること"""
        msg = Message(role="user", content="テスト")
        assert msg.content == "テスト"
        assert msg.role == "user"

    def test_message_assistant_role(self):
        """assistantロールが正しく保持されること"""
        msg = Message(role="assistant", content="応答")
        assert msg.role == "assistant"
        assert msg.content == "応答"


# =============================================================================
# UserPreferences データクラステスト
# =============================================================================


class TestUserPreferences:
    """UserPreferencesデータクラスのテスト"""

    def test_init(self):
        """初期化できること"""
        prefs = UserPreferences(
            preferred_name="カズさん",
            report_format="詳細",
        )
        assert prefs.preferred_name == "カズさん"
        assert prefs.report_format == "詳細"

    def test_to_string_with_all_fields(self):
        """全フィールドがto_stringに含まれること"""
        prefs = UserPreferences(
            preferred_name="カズさん",
            report_format="簡潔",
            notification_time="09:00",
        )
        result = prefs.to_string()
        assert "カズさん" in result
        assert "簡潔" in result
        assert "09:00" in result

    def test_to_string_empty(self):
        """フィールドがない場合も動作すること"""
        prefs = UserPreferences()
        result = prefs.to_string()
        # 空またはデフォルト値が返る
        assert result is not None


# =============================================================================
# PersonInfo データクラステスト
# =============================================================================


class TestPersonInfo:
    """PersonInfoデータクラスのテスト"""

    def test_init(self):
        """初期化できること"""
        person = PersonInfo(
            name="田中太郎",
            department="営業部",
            role="manager",
        )
        assert person.name == "田中太郎"
        assert person.department == "営業部"
        assert person.role == "manager"

    def test_to_string(self):
        """to_stringが正しい形式を返すこと"""
        person = PersonInfo(
            name="田中太郎",
            department="営業部",
            role="manager",
        )
        result = person.to_string()
        assert "田中太郎" in result
        assert "営業部" in result
        assert "manager" in result


# =============================================================================
# TaskInfo データクラステスト
# =============================================================================


class TestTaskInfo:
    """TaskInfoデータクラスのテスト"""

    def test_init(self):
        """初期化できること"""
        task = TaskInfo(
            task_id="task_001",
            title="資料作成",
            status="open",
        )
        assert task.task_id == "task_001"
        assert task.title == "資料作成"
        assert task.status == "open"

    def test_to_string_with_due_date(self):
        """期限付きタスクのto_string"""
        due = datetime(2026, 2, 1)
        task = TaskInfo(
            task_id="task_001",
            title="資料作成",
            due_date=due,
        )
        result = task.to_string()
        assert "資料作成" in result
        assert "2026-02-01" in result

    def test_to_string_overdue(self):
        """期限切れタスクのto_string"""
        task = TaskInfo(
            task_id="task_001",
            title="資料作成",
            is_overdue=True,
        )
        result = task.to_string()
        assert "期限切れ" in result


# =============================================================================
# GoalInfo データクラステスト
# =============================================================================


class TestGoalInfo:
    """GoalInfoデータクラスのテスト"""

    def test_init(self):
        """初期化できること"""
        goal = GoalInfo(
            goal_id="goal_001",
            title="売上目標",
            progress=50.0,
        )
        assert goal.goal_id == "goal_001"
        assert goal.title == "売上目標"
        assert goal.progress == 50.0

    def test_to_string(self):
        """to_stringが正しい形式を返すこと"""
        goal = GoalInfo(
            goal_id="goal_001",
            title="売上目標",
            progress=75.5,
        )
        result = goal.to_string()
        assert "売上目標" in result
        assert "76%" in result or "75%" in result  # 四捨五入の違いを許容


# =============================================================================
# CEOTeaching データクラステスト
# =============================================================================


class TestCEOTeaching:
    """CEOTeachingデータクラスのテスト"""

    def test_init(self):
        """初期化できること"""
        teaching = CEOTeaching(
            content="お客様第一",
            category="行動指針",
            priority=1,
        )
        assert teaching.content == "お客様第一"
        assert teaching.category == "行動指針"
        assert teaching.priority == 1

    def test_to_string_with_category(self):
        """カテゴリ付きのto_string"""
        teaching = CEOTeaching(
            content="お客様第一",
            category="行動指針",
        )
        result = teaching.to_string()
        assert "[行動指針]" in result
        assert "お客様第一" in result

    def test_to_string_without_category(self):
        """カテゴリなしのto_string"""
        teaching = CEOTeaching(content="お客様第一")
        result = teaching.to_string()
        assert result == "お客様第一"


# =============================================================================
# SessionState データクラステスト
# =============================================================================


class TestSessionState:
    """SessionStateデータクラスのテスト"""

    def test_init(self):
        """初期化できること"""
        state = SessionState(mode="normal")
        assert state.mode == "normal"
        assert state.pending_action is None

    def test_to_string_normal(self):
        """normalモードのto_string"""
        state = SessionState(mode="normal")
        result = state.to_string()
        assert "normal" in result or "通常" in result

    def test_to_string_confirmation_pending(self):
        """confirmation_pendingモードのto_string"""
        state = SessionState(
            mode="confirmation_pending",
            pending_action={"tool": "test"},
        )
        result = state.to_string()
        assert "確認待ち" in result


# =============================================================================
# LLMContext データクラステスト
# =============================================================================


class TestLLMContext:
    """LLMContextデータクラスのテスト"""

    def test_init_minimal(self):
        """最小限の引数で初期化できること"""
        ctx = LLMContext(
            user_id="user_001",
            user_name="テストユーザー",
            user_role="member",
            organization_id="org_test",
            room_id="room_123",
            current_datetime=datetime.now(),
        )
        assert ctx.user_id == "user_001"
        assert ctx.user_name == "テストユーザー"
        assert ctx.recent_messages == []

    def test_to_prompt_string_basic(self, sample_llm_context):
        """to_prompt_stringが正しい形式を返すこと"""
        result = sample_llm_context.to_prompt_string()

        # 必須セクションの存在確認
        assert "【ユーザー情報】" in result
        assert "【直近の会話】" in result
        assert "【CEO教え（最優先で従う）】" in result
        assert "【現在日時】" in result

    def test_to_prompt_string_includes_user_info(self, sample_llm_context):
        """ユーザー情報が含まれること"""
        result = sample_llm_context.to_prompt_string()
        assert "テストユーザー" in result
        assert "member" in result

    def test_to_prompt_string_includes_messages(self, sample_llm_context):
        """会話履歴が含まれること"""
        result = sample_llm_context.to_prompt_string()
        assert "タスク追加して" in result

    def test_to_prompt_string_includes_ceo_teachings(self, sample_llm_context):
        """CEO教えが含まれること"""
        result = sample_llm_context.to_prompt_string()
        assert "お客様第一" in result

    def test_to_prompt_string_includes_tasks(self, sample_llm_context):
        """タスク情報が含まれること"""
        result = sample_llm_context.to_prompt_string()
        assert "資料作成" in result

    def test_to_prompt_string_includes_goals(self, sample_llm_context):
        """目標情報が含まれること"""
        result = sample_llm_context.to_prompt_string()
        assert "売上目標達成" in result

    def test_to_prompt_string_empty_lists(self):
        """空のリストでも動作すること"""
        ctx = LLMContext(
            user_id="user_001",
            user_name="テストユーザー",
            user_role="member",
            organization_id="org_test",
            room_id="room_123",
            current_datetime=datetime.now(),
        )
        result = ctx.to_prompt_string()
        assert "【ユーザー情報】" in result


# =============================================================================
# ContextBuilder テスト
# =============================================================================


class TestContextBuilder:
    """ContextBuilderのテスト"""

    @pytest.fixture
    def mock_memory_access(self):
        """モックのMemoryAccess"""
        mock = MagicMock()
        mock.get_conversation_history = AsyncMock(return_value=[])
        mock.get_user_preferences = AsyncMock(return_value=None)
        mock.get_person_info = AsyncMock(return_value=[])
        mock.get_recent_tasks = AsyncMock(return_value=[])
        mock.get_active_goals = AsyncMock(return_value=[])
        return mock

    @pytest.fixture
    def mock_state_manager(self):
        """モックのStateManager"""
        mock = MagicMock()
        mock.get_current_state = AsyncMock(return_value=None)
        return mock

    @pytest.fixture
    def mock_pool(self):
        """モックのDBプール"""
        return MagicMock()

    def test_init(self, mock_pool, mock_memory_access, mock_state_manager):
        """初期化できること"""
        builder = ContextBuilder(
            pool=mock_pool,
            memory_access=mock_memory_access,
            state_manager=mock_state_manager,
        )
        assert builder.pool is mock_pool
        assert builder.memory_access is mock_memory_access

    @pytest.mark.asyncio
    async def test_build_returns_llm_context(
        self,
        mock_pool,
        mock_memory_access,
        mock_state_manager,
    ):
        """buildがLLMContextを返すこと"""
        builder = ContextBuilder(
            pool=mock_pool,
            memory_access=mock_memory_access,
            state_manager=mock_state_manager,
        )

        # _get_user_infoをモック（辞書を返すように）
        with patch.object(builder, '_get_user_info', new_callable=AsyncMock) as mock_get_user:
            mock_get_user.return_value = {"name": "テストユーザー", "role": "member"}

            context = await builder.build(
                user_id="user_001",
                room_id="room_123",
                organization_id="org_test",
                message="テスト",
            )

            assert isinstance(context, LLMContext)
            assert context.user_id == "user_001"
            assert context.room_id == "room_123"
            assert context.organization_id == "org_test"

    @pytest.mark.asyncio
    async def test_build_with_sender_name(
        self,
        mock_pool,
        mock_memory_access,
        mock_state_manager,
    ):
        """sender_nameが指定された場合、それが使用されること"""
        builder = ContextBuilder(
            pool=mock_pool,
            memory_access=mock_memory_access,
            state_manager=mock_state_manager,
        )

        context = await builder.build(
            user_id="user_001",
            room_id="room_123",
            organization_id="org_test",
            message="テスト",
            sender_name="指定された名前",
        )

        assert context.user_name == "指定された名前"


# =============================================================================
# Phase 2E: 学習統合テスト
# =============================================================================


class TestPhase2ELearningIntegration:
    """Phase 2E学習のContextBuilder/LLMContext統合テスト"""

    def test_llm_context_has_phase2e_field(self):
        """LLMContextにphase2e_learningsフィールドがあること"""
        ctx = LLMContext(
            user_id="user_001",
            user_name="テスト",
            user_role="member",
            organization_id="org_test",
            room_id="room_123",
            current_datetime=datetime.now(),
        )
        assert ctx.phase2e_learnings == ""

    def test_to_prompt_string_includes_learnings(self):
        """phase2e_learningsがプロンプトに含まれること"""
        ctx = LLMContext(
            user_id="user_001",
            user_name="テスト",
            user_role="member",
            organization_id="org_test",
            room_id="room_123",
            current_datetime=datetime.now(),
            phase2e_learnings="【覚えている別名】\n- 「麻美」は「渡部麻美」のこと",
        )
        result = ctx.to_prompt_string()
        assert "【覚えている別名】" in result
        assert "渡部麻美" in result

    def test_to_prompt_string_excludes_empty_learnings(self):
        """空のphase2e_learningsはプロンプトに含まれないこと"""
        ctx = LLMContext(
            user_id="user_001",
            user_name="テスト",
            user_role="member",
            organization_id="org_test",
            room_id="room_123",
            current_datetime=datetime.now(),
            phase2e_learnings="",
        )
        result = ctx.to_prompt_string()
        assert "覚えている別名" not in result

    def test_context_builder_init_with_phase2e(self):
        """ContextBuilderがphase2e_learningパラメータを受け取ること"""
        mock_pool = MagicMock()
        mock_learning = MagicMock()
        builder = ContextBuilder(
            pool=mock_pool,
            phase2e_learning=mock_learning,
        )
        assert builder.phase2e_learning is mock_learning

    @pytest.mark.asyncio
    async def test_build_includes_phase2e_learnings(self):
        """buildがPhase 2E学習を含むLLMContextを返すこと"""
        mock_pool = MagicMock()
        mock_learning = MagicMock()
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=False)

        # find_applicable → build_context_additions → build_prompt_instructions
        mock_applied = [MagicMock()]
        mock_learning.find_applicable.return_value = mock_applied
        mock_learning.build_context_additions.return_value = {"aliases": [{"from": "麻美", "to": "渡部麻美"}]}
        mock_learning.build_prompt_instructions.return_value = "【覚えている別名】\n- 「麻美」は「渡部麻美」のこと"

        builder = ContextBuilder(
            pool=mock_pool,
            phase2e_learning=mock_learning,
        )

        with patch.object(builder, '_get_user_info', new_callable=AsyncMock) as mock_ui:
            mock_ui.return_value = {"name": "テスト", "role": ""}
            context = await builder.build(
                user_id="user_001",
                room_id="room_123",
                organization_id="org_test",
                message="麻美さんに連絡して",
            )

        assert context.phase2e_learnings == "【覚えている別名】\n- 「麻美」は「渡部麻美」のこと"
        mock_learning.find_applicable.assert_called_once_with(
            mock_conn, "麻美さんに連絡して", None, "user_001", "room_123"
        )

    @pytest.mark.asyncio
    async def test_build_phase2e_no_applicable(self):
        """適用可能な学習がない場合、空文字が返ること"""
        mock_pool = MagicMock()
        mock_learning = MagicMock()
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_learning.find_applicable.return_value = []

        builder = ContextBuilder(
            pool=mock_pool,
            phase2e_learning=mock_learning,
        )

        with patch.object(builder, '_get_user_info', new_callable=AsyncMock) as mock_ui:
            mock_ui.return_value = {"name": "テスト", "role": ""}
            context = await builder.build(
                user_id="user_001",
                room_id="room_123",
                organization_id="org_test",
                message="こんにちは",
            )

        assert context.phase2e_learnings == ""
        mock_learning.build_context_additions.assert_not_called()

    @pytest.mark.asyncio
    async def test_build_phase2e_error_graceful(self):
        """Phase 2E取得エラー時もLLMContextが正常に返ること"""
        mock_pool = MagicMock()
        mock_learning = MagicMock()
        mock_pool.connect.side_effect = Exception("DB connection error")

        builder = ContextBuilder(
            pool=mock_pool,
            phase2e_learning=mock_learning,
        )

        with patch.object(builder, '_get_user_info', new_callable=AsyncMock) as mock_ui:
            mock_ui.return_value = {"name": "テスト", "role": ""}
            context = await builder.build(
                user_id="user_001",
                room_id="room_123",
                organization_id="org_test",
                message="テスト",
            )

        assert isinstance(context, LLMContext)
        assert context.phase2e_learnings == ""

    @pytest.mark.asyncio
    async def test_build_without_phase2e(self):
        """phase2e_learning未設定時も正常に動作すること"""
        mock_pool = MagicMock()
        builder = ContextBuilder(pool=mock_pool)

        with patch.object(builder, '_get_user_info', new_callable=AsyncMock) as mock_ui:
            mock_ui.return_value = {"name": "テスト", "role": ""}
            context = await builder.build(
                user_id="user_001",
                room_id="room_123",
                organization_id="org_test",
                message="テスト",
            )

        assert context.phase2e_learnings == ""


# =============================================================================
# Phase 2F: Outcome Learning Context Integration
# =============================================================================


class TestOutcomePatternsContext:
    """Phase 2F: 行動パターンのコンテキスト統合テスト"""

    def test_to_prompt_string_includes_outcome_patterns(self):
        """outcome_patternsがプロンプトに含まれること"""
        ctx = LLMContext(
            user_id="user_001",
            user_name="テスト",
            user_role="member",
            organization_id="org_test",
            room_id="room_123",
            current_datetime=datetime.now(),
            outcome_patterns="【行動パターン（Phase 2F）】\n- 午前中のリマインドが効果的 (信頼度: 85%)",
        )
        result = ctx.to_prompt_string()
        assert "行動パターン（Phase 2F）" in result
        assert "午前中のリマインド" in result

    def test_to_prompt_string_excludes_empty_outcome_patterns(self):
        """空のoutcome_patternsはプロンプトに含まれないこと"""
        ctx = LLMContext(
            user_id="user_001",
            user_name="テスト",
            user_role="member",
            organization_id="org_test",
            room_id="room_123",
            current_datetime=datetime.now(),
            outcome_patterns="",
        )
        result = ctx.to_prompt_string()
        assert "行動パターン" not in result

    def test_context_builder_init_with_outcome_learning(self):
        """ContextBuilderがoutcome_learningパラメータを受け取ること"""
        mock_pool = MagicMock()
        mock_outcome = MagicMock()
        builder = ContextBuilder(
            pool=mock_pool,
            outcome_learning=mock_outcome,
        )
        assert builder.outcome_learning is mock_outcome

    def test_context_builder_init_without_outcome_learning(self):
        """outcome_learning未設定時はNoneであること"""
        mock_pool = MagicMock()
        builder = ContextBuilder(pool=mock_pool)
        assert builder.outcome_learning is None

    @pytest.mark.asyncio
    async def test_get_outcome_patterns_with_patterns(self):
        """パターンがある場合、フォーマットされた文字列が返ること"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=False)

        mock_pattern = MagicMock()
        mock_pattern.pattern_content = {"description": "午前中のリマインドが効果的"}
        mock_pattern.pattern_type = "timing"
        mock_pattern.confidence_score = 0.85

        mock_outcome = MagicMock()
        mock_outcome.find_applicable_patterns.return_value = [mock_pattern]

        builder = ContextBuilder(pool=mock_pool, outcome_learning=mock_outcome)
        result = await builder._get_outcome_patterns("user_001")

        assert "行動パターン（Phase 2F）" in result
        assert "午前中のリマインド" in result
        assert "85%" in result

    @pytest.mark.asyncio
    async def test_get_outcome_patterns_no_patterns(self):
        """パターンがない場合、空文字が返ること"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=False)

        mock_outcome = MagicMock()
        mock_outcome.find_applicable_patterns.return_value = []

        builder = ContextBuilder(pool=mock_pool, outcome_learning=mock_outcome)
        result = await builder._get_outcome_patterns("user_001")

        assert result == ""

    @pytest.mark.asyncio
    async def test_get_outcome_patterns_none_learning(self):
        """outcome_learning未設定時は空文字が返ること"""
        mock_pool = MagicMock()
        builder = ContextBuilder(pool=mock_pool)
        result = await builder._get_outcome_patterns("user_001")
        assert result == ""

    @pytest.mark.asyncio
    async def test_get_outcome_patterns_max_3(self):
        """最大3件に制限されること"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=False)

        patterns = []
        for i in range(5):
            p = MagicMock()
            p.pattern_content = {"description": f"パターン{i}"}
            p.pattern_type = "timing"
            p.confidence_score = 0.8
            patterns.append(p)

        mock_outcome = MagicMock()
        mock_outcome.find_applicable_patterns.return_value = patterns

        builder = ContextBuilder(pool=mock_pool, outcome_learning=mock_outcome)
        result = await builder._get_outcome_patterns("user_001")

        assert "パターン0" in result
        assert "パターン1" in result
        assert "パターン2" in result
        assert "パターン3" not in result
        assert "パターン4" not in result

    @pytest.mark.asyncio
    async def test_get_outcome_patterns_error_graceful(self):
        """エラー時も空文字が返ること"""
        mock_pool = MagicMock()
        mock_pool.connect.side_effect = Exception("DB error")
        mock_outcome = MagicMock()

        builder = ContextBuilder(pool=mock_pool, outcome_learning=mock_outcome)
        result = await builder._get_outcome_patterns("user_001")
        assert result == ""

    @pytest.mark.asyncio
    async def test_build_includes_outcome_patterns(self):
        """buildがoutcome_patternsを含むLLMContextを返すこと"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=False)

        mock_pattern = MagicMock()
        mock_pattern.pattern_content = {"description": "朝のリマインドが効果的"}
        mock_pattern.pattern_type = "timing"
        mock_pattern.confidence_score = 0.9

        mock_outcome = MagicMock()
        mock_outcome.find_applicable_patterns.return_value = [mock_pattern]

        builder = ContextBuilder(pool=mock_pool, outcome_learning=mock_outcome)

        with patch.object(builder, '_get_user_info', new_callable=AsyncMock) as mock_ui:
            mock_ui.return_value = {"name": "テスト", "role": ""}
            context = await builder.build(
                user_id="user_001",
                room_id="room_123",
                organization_id="org_test",
                message="テスト",
            )

        assert "行動パターン" in context.outcome_patterns
        assert "朝のリマインド" in context.outcome_patterns
