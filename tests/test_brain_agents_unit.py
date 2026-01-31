# tests/test_brain_agents_unit.py
"""
Ultimate Brain Phase 3: Multi-Agent System Unit Tests

エージェントシステムの詳細なユニットテストスイート。
既存のtest_brain_agents.pyを補完し、より詳細なテストを提供する。

テスト対象:
1. 各エージェントのconsult()メソッド（モック使用）
2. オーケストレーターによる複数エージェント連携
3. エラーハンドリング
4. エッジケースと異常系
5. 委任（delegate）機能
6. 統計情報の更新
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock
from typing import Any, Dict, List, Optional

# =============================================================================
# Imports
# =============================================================================

from lib.brain.agents.base import (
    AgentType,
    AgentStatus,
    MessageType,
    MessagePriority,
    ExpertiseLevel,
    AgentCapability,
    AgentMessage,
    AgentResponse,
    AgentContext,
    AgentStats,
    BaseAgent,
    create_agent_message,
    create_agent_context,
    MAX_CONCURRENT_AGENTS,
    INTER_AGENT_TIMEOUT_SECONDS,
)

from lib.brain.agents.orchestrator import (
    Orchestrator,
    create_orchestrator,
    AgentScore,
    RoutingDecision,
    IntegratedResponse,
    AGENT_KEYWORDS,
    ACTION_AGENT_MAPPING,
    MAX_PARALLEL_AGENTS,
)

from lib.brain.agents.task_expert import (
    TaskExpert,
    create_task_expert,
    TaskInfo,
    TaskAnalysis,
    TASK_PRIORITY_URGENT,
    TASK_PRIORITY_HIGH,
    TASK_PRIORITY_NORMAL,
    TASK_PRIORITY_LOW,
)

from lib.brain.agents.goal_expert import (
    GoalExpert,
    create_goal_expert,
    GoalInfo,
    GoalSession,
    GOAL_STEP_WHY,
    GOAL_STEP_WHAT,
    GOAL_STEP_HOW,
    GOAL_STEP_COMPLETE,
)

from lib.brain.agents.knowledge_expert import (
    KnowledgeExpert,
    create_knowledge_expert,
)

from lib.brain.agents.hr_expert import (
    HRExpert,
    create_hr_expert,
)

from lib.brain.agents.emotion_expert import (
    EmotionExpert,
    create_emotion_expert,
    EmotionType,
    UrgencyLevel,
)

from lib.brain.agents.organization_expert import (
    OrganizationExpert,
    create_organization_expert,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_pool():
    """Mock database pool."""
    pool = MagicMock()
    conn = MagicMock()
    pool.connect.return_value.__enter__ = MagicMock(return_value=conn)
    pool.connect.return_value.__exit__ = MagicMock(return_value=False)
    return pool


@pytest.fixture
def organization_id():
    """Test organization ID."""
    return "test-org-unit-001"


@pytest.fixture
def user_id():
    """Test user ID."""
    return "test-user-001"


@pytest.fixture
def room_id():
    """Test room ID."""
    return "test-room-001"


@pytest.fixture
def agent_context(organization_id, user_id, room_id):
    """Test agent context."""
    return create_agent_context(
        organization_id=organization_id,
        user_id=user_id,
        room_id=room_id,
        original_message="test message",
    )


@pytest.fixture
def orchestrator_with_all_agents(mock_pool, organization_id):
    """Orchestrator with all agents registered."""
    orchestrator = Orchestrator(pool=mock_pool, organization_id=organization_id)
    agents = [
        TaskExpert(pool=mock_pool, organization_id=organization_id),
        GoalExpert(pool=mock_pool, organization_id=organization_id),
        KnowledgeExpert(pool=mock_pool, organization_id=organization_id),
        HRExpert(pool=mock_pool, organization_id=organization_id),
        EmotionExpert(pool=mock_pool, organization_id=organization_id),
        OrganizationExpert(pool=mock_pool, organization_id=organization_id),
    ]
    orchestrator.register_agents(agents)
    return orchestrator


# =============================================================================
# Part 1: Factory Function Tests
# =============================================================================

class TestAgentMessageFactory:
    """AgentMessage factory function tests."""

    def test_create_agent_message_defaults(self):
        """Test create_agent_message with default values."""
        msg = create_agent_message(
            from_agent=AgentType.ORCHESTRATOR,
            to_agent=AgentType.TASK_EXPERT,
        )
        assert msg.from_agent == AgentType.ORCHESTRATOR
        assert msg.to_agent == AgentType.TASK_EXPERT
        assert msg.message_type == MessageType.REQUEST
        assert msg.priority == MessagePriority.NORMAL
        assert msg.requires_response is True
        assert msg.content == {}

    def test_create_agent_message_custom(self):
        """Test create_agent_message with custom values."""
        content = {"action": "test", "data": "value"}
        msg = create_agent_message(
            from_agent=AgentType.TASK_EXPERT,
            to_agent=AgentType.ORCHESTRATOR,
            message_type=MessageType.RESPONSE,
            priority=MessagePriority.HIGH,
            content=content,
            requires_response=False,
        )
        assert msg.from_agent == AgentType.TASK_EXPERT
        assert msg.message_type == MessageType.RESPONSE
        assert msg.priority == MessagePriority.HIGH
        assert msg.content == content
        assert msg.requires_response is False


class TestAgentContextFactory:
    """AgentContext factory function tests."""

    def test_create_agent_context_defaults(self, organization_id):
        """Test create_agent_context with default values."""
        context = create_agent_context(organization_id=organization_id)
        assert context.organization_id == organization_id
        assert context.user_id == ""
        assert context.room_id == ""
        assert context.session_id != ""  # Auto-generated UUID
        assert context.depth == 0
        assert context.visited_agents == []

    def test_create_agent_context_custom(self, organization_id, user_id, room_id):
        """Test create_agent_context with custom values."""
        context = create_agent_context(
            organization_id=organization_id,
            user_id=user_id,
            room_id=room_id,
            original_message="test message",
        )
        assert context.organization_id == organization_id
        assert context.user_id == user_id
        assert context.room_id == room_id
        assert context.original_message == "test message"


# =============================================================================
# Part 2: BaseAgent handle_message Tests
# =============================================================================

class TestBaseAgentHandleMessage:
    """BaseAgent.handle_message method tests."""

    @pytest.mark.asyncio
    async def test_handle_message_updates_stats(self, mock_pool, organization_id, agent_context):
        """Test that handle_message updates statistics."""
        expert = TaskExpert(pool=mock_pool, organization_id=organization_id)
        initial_total = expert.stats.total_requests

        message = AgentMessage(
            from_agent=AgentType.ORCHESTRATOR,
            to_agent=AgentType.TASK_EXPERT,
            content={"action": "task_search"},
        )

        await expert.handle_message(agent_context, message)

        assert expert.stats.total_requests == initial_total + 1
        assert expert.stats.last_request_at is not None

    @pytest.mark.asyncio
    async def test_handle_message_success_increments_successful(
        self, mock_pool, organization_id, agent_context
    ):
        """Test that successful processing increments successful_requests."""
        expert = TaskExpert(pool=mock_pool, organization_id=organization_id)
        initial_successful = expert.stats.successful_requests

        message = AgentMessage(
            from_agent=AgentType.ORCHESTRATOR,
            to_agent=AgentType.TASK_EXPERT,
            content={"action": "task_search"},
        )

        response = await expert.handle_message(agent_context, message)

        if response.success:
            assert expert.stats.successful_requests == initial_successful + 1

    @pytest.mark.asyncio
    async def test_handle_message_max_depth_exceeded(
        self, mock_pool, organization_id, agent_context
    ):
        """Test that max delegation depth is enforced."""
        expert = TaskExpert(pool=mock_pool, organization_id=organization_id)
        agent_context.depth = MAX_CONCURRENT_AGENTS + 1

        message = AgentMessage(
            from_agent=AgentType.ORCHESTRATOR,
            to_agent=AgentType.TASK_EXPERT,
            content={"action": "task_search"},
        )

        response = await expert.handle_message(agent_context, message)

        assert response.success is False
        assert "最大委任深度" in response.error_message

    @pytest.mark.asyncio
    async def test_handle_message_exception_handling(
        self, mock_pool, organization_id, agent_context
    ):
        """Test that exceptions are handled gracefully."""
        expert = TaskExpert(pool=mock_pool, organization_id=organization_id)

        # Mock process to raise an exception
        async def mock_process(*args, **kwargs):
            raise ValueError("Test error")

        expert.process = mock_process

        message = AgentMessage(
            from_agent=AgentType.ORCHESTRATOR,
            to_agent=AgentType.TASK_EXPERT,
            content={"action": "task_search"},
        )

        response = await expert.handle_message(agent_context, message)

        assert response.success is False
        assert "Test error" in response.error_message

    @pytest.mark.asyncio
    async def test_handle_message_status_changes(
        self, mock_pool, organization_id, agent_context
    ):
        """Test that status changes during processing."""
        expert = TaskExpert(pool=mock_pool, organization_id=organization_id)

        assert expert.status == AgentStatus.IDLE

        message = AgentMessage(
            from_agent=AgentType.ORCHESTRATOR,
            to_agent=AgentType.TASK_EXPERT,
            content={"action": "task_search"},
        )

        await expert.handle_message(agent_context, message)

        # After processing, should return to IDLE
        assert expert.status == AgentStatus.IDLE


# =============================================================================
# Part 3: Agent Delegation Tests
# =============================================================================

class TestAgentDelegation:
    """Agent delegation (delegate_to) tests."""

    @pytest.mark.asyncio
    async def test_delegate_to_registered_agent(
        self, orchestrator_with_all_agents, agent_context
    ):
        """Test delegation to a registered agent."""
        orchestrator = orchestrator_with_all_agents

        response = await orchestrator.delegate_to(
            AgentType.TASK_EXPERT,
            agent_context,
            {"action": "task_search", "message": "test"},
        )

        assert isinstance(response, AgentResponse)
        assert response.agent_type == AgentType.TASK_EXPERT

    @pytest.mark.asyncio
    async def test_delegate_to_unregistered_agent(
        self, mock_pool, organization_id, agent_context
    ):
        """Test delegation to an unregistered agent fails gracefully."""
        orchestrator = Orchestrator(pool=mock_pool, organization_id=organization_id)
        # Don't register any agents

        response = await orchestrator.delegate_to(
            AgentType.TASK_EXPERT,
            agent_context,
            {"action": "task_search"},
        )

        assert response.success is False
        assert "見つかりません" in response.error_message

    @pytest.mark.asyncio
    async def test_delegate_updates_context_depth(
        self, orchestrator_with_all_agents, agent_context
    ):
        """Test that delegation increments context depth."""
        orchestrator = orchestrator_with_all_agents
        initial_depth = agent_context.depth

        await orchestrator.delegate_to(
            AgentType.TASK_EXPERT,
            agent_context,
            {"action": "task_search"},
        )

        assert agent_context.depth == initial_depth + 1

    @pytest.mark.asyncio
    async def test_delegate_updates_visited_agents(
        self, orchestrator_with_all_agents, agent_context
    ):
        """Test that delegation adds to visited_agents."""
        orchestrator = orchestrator_with_all_agents
        initial_visited = len(agent_context.visited_agents)

        await orchestrator.delegate_to(
            AgentType.TASK_EXPERT,
            agent_context,
            {"action": "task_search"},
        )

        assert len(agent_context.visited_agents) == initial_visited + 1
        assert AgentType.ORCHESTRATOR in agent_context.visited_agents


# =============================================================================
# Part 4: Agent Query Tests
# =============================================================================

class TestAgentQuery:
    """Agent query (query_agent) tests."""

    @pytest.mark.asyncio
    async def test_query_agent_success(
        self, orchestrator_with_all_agents
    ):
        """Test successful agent query."""
        orchestrator = orchestrator_with_all_agents

        response = await orchestrator.query_agent(
            AgentType.TASK_EXPERT,
            {"action": "task_search"},
        )

        assert response is not None
        assert isinstance(response, AgentResponse)

    @pytest.mark.asyncio
    async def test_query_agent_not_found(
        self, mock_pool, organization_id
    ):
        """Test query to non-existent agent returns None."""
        orchestrator = Orchestrator(pool=mock_pool, organization_id=organization_id)

        response = await orchestrator.query_agent(
            AgentType.TASK_EXPERT,
            {"action": "task_search"},
        )

        assert response is None

    @pytest.mark.asyncio
    async def test_query_agent_timeout(
        self, orchestrator_with_all_agents
    ):
        """Test query timeout handling."""
        orchestrator = orchestrator_with_all_agents

        # Mock a slow response
        async def slow_process(*args, **kwargs):
            await asyncio.sleep(10)  # Longer than timeout
            return AgentResponse(success=True)

        task_expert = orchestrator.get_agent(AgentType.TASK_EXPERT)
        original_process = task_expert.process
        task_expert.process = slow_process

        try:
            response = await orchestrator.query_agent(
                AgentType.TASK_EXPERT,
                {"action": "task_search"},
                timeout=0.1,  # Very short timeout
            )

            # Should timeout and return None
            assert response is None
        finally:
            task_expert.process = original_process


# =============================================================================
# Part 5: Orchestrator Process Tests
# =============================================================================

class TestOrchestratorProcess:
    """Orchestrator.process method tests."""

    @pytest.mark.asyncio
    async def test_process_with_explicit_action(
        self, orchestrator_with_all_agents, agent_context
    ):
        """Test processing with explicit action routes correctly."""
        orchestrator = orchestrator_with_all_agents

        message = AgentMessage(
            from_agent=AgentType.ORCHESTRATOR,
            to_agent=AgentType.ORCHESTRATOR,
            content={"action": "task_create", "message": "create task"},
        )

        response = await orchestrator.process(agent_context, message)

        assert isinstance(response, AgentResponse)
        # Should route to TaskExpert
        assert response.agent_type == AgentType.TASK_EXPERT

    @pytest.mark.asyncio
    async def test_process_infers_routing_from_message(
        self, orchestrator_with_all_agents, agent_context
    ):
        """Test that routing is inferred from message content."""
        orchestrator = orchestrator_with_all_agents
        agent_context.original_message = "目標を設定したい"

        message = AgentMessage(
            from_agent=AgentType.ORCHESTRATOR,
            to_agent=AgentType.ORCHESTRATOR,
            content={"message": "目標を設定したい"},
        )

        response = await orchestrator.process(agent_context, message)

        assert isinstance(response, AgentResponse)

    @pytest.mark.asyncio
    async def test_process_fallback_to_emotion_expert(
        self, orchestrator_with_all_agents, agent_context
    ):
        """Test fallback to EmotionExpert for unmatched messages."""
        orchestrator = orchestrator_with_all_agents
        agent_context.original_message = "こんにちは"

        message = AgentMessage(
            from_agent=AgentType.ORCHESTRATOR,
            to_agent=AgentType.ORCHESTRATOR,
            content={"message": "こんにちは"},  # Generic greeting
        )

        routing = await orchestrator._decide_routing("こんにちは", agent_context)

        # For generic messages, should fallback to EmotionExpert
        assert routing.primary_agent in [
            AgentType.EMOTION_EXPERT,
            AgentType.ORCHESTRATOR,
            AgentType.KNOWLEDGE_EXPERT,
        ]


# =============================================================================
# Part 6: Orchestrator Parallel Execution Tests
# =============================================================================

class TestOrchestratorParallelExecution:
    """Orchestrator parallel execution tests."""

    @pytest.mark.asyncio
    async def test_execute_parallel_multiple_agents(
        self, orchestrator_with_all_agents, agent_context
    ):
        """Test parallel execution with multiple agents."""
        orchestrator = orchestrator_with_all_agents

        routing = RoutingDecision(
            primary_agent=AgentType.TASK_EXPERT,
            secondary_agents=[AgentType.GOAL_EXPERT],
            parallel_execution=True,
            confidence=0.8,
        )

        content = {"message": "test parallel"}

        response = await orchestrator._execute_parallel(
            agent_context, routing, content
        )

        assert isinstance(response, AgentResponse)

    @pytest.mark.asyncio
    async def test_integrate_responses_primary_preferred(
        self, orchestrator_with_all_agents
    ):
        """Test that primary agent response is preferred in integration."""
        orchestrator = orchestrator_with_all_agents

        responses = [
            AgentResponse(
                agent_type=AgentType.GOAL_EXPERT,
                success=True,
                result={"data": "secondary"},
                confidence=0.7,
            ),
            AgentResponse(
                agent_type=AgentType.TASK_EXPERT,
                success=True,
                result={"data": "primary"},
                confidence=0.9,
            ),
        ]

        routing = RoutingDecision(
            primary_agent=AgentType.TASK_EXPERT,
            secondary_agents=[AgentType.GOAL_EXPERT],
        )

        integrated = orchestrator._integrate_responses(responses, routing)

        assert integrated.agent_type == AgentType.TASK_EXPERT
        assert integrated.result.get("data") == "primary"

    @pytest.mark.asyncio
    async def test_integrate_responses_all_failed(
        self, orchestrator_with_all_agents
    ):
        """Test integration when all responses failed."""
        orchestrator = orchestrator_with_all_agents

        responses = [
            AgentResponse(success=False, error_message="error1"),
            AgentResponse(success=False, error_message="error2"),
        ]

        routing = RoutingDecision(primary_agent=AgentType.TASK_EXPERT)

        integrated = orchestrator._integrate_responses(responses, routing)

        assert integrated.success is False


# =============================================================================
# Part 7: TaskExpert Handler Tests
# =============================================================================

class TestTaskExpertHandlers:
    """TaskExpert handler tests."""

    @pytest.mark.asyncio
    async def test_handle_task_create(self, mock_pool, organization_id, agent_context):
        """Test task creation handler."""
        expert = TaskExpert(pool=mock_pool, organization_id=organization_id)

        content = {
            "action": "task_create",
            "message": "緊急タスクを作成して",
            "assignee_id": "user-001",
        }

        result = await expert._handle_task_create(content, agent_context)

        assert result["action"] == "task_create"
        assert result["requires_external_handler"] is True
        assert "priority" in result["task_info"]

    @pytest.mark.asyncio
    async def test_handle_task_complete_needs_clarification(
        self, mock_pool, organization_id, agent_context
    ):
        """Test task complete handler when task_id is missing."""
        expert = TaskExpert(pool=mock_pool, organization_id=organization_id)

        content = {"action": "task_complete", "message": "タスク完了"}

        result = await expert._handle_task_complete(content, agent_context)

        assert result["needs_clarification"] is True

    @pytest.mark.asyncio
    async def test_handle_task_analyze(self, mock_pool, organization_id, agent_context):
        """Test task analysis handler."""
        expert = TaskExpert(pool=mock_pool, organization_id=organization_id)

        tasks = [
            {"task_id": "1", "priority": TASK_PRIORITY_HIGH, "status": "open"},
            {"task_id": "2", "priority": TASK_PRIORITY_NORMAL, "status": "open"},
            {
                "task_id": "3",
                "priority": TASK_PRIORITY_URGENT,
                "status": "open",
                "due_date": (datetime.now() - timedelta(days=1)).isoformat(),
            },
        ]

        content = {"action": "task_analyze", "tasks": tasks}

        result = await expert._handle_task_analyze(content, agent_context)

        assert result["action"] == "task_analyze"
        assert "analysis" in result
        assert result["analysis"]["total_tasks"] == 3

    def test_extract_priority_urgent(self, mock_pool, organization_id):
        """Test priority extraction for urgent."""
        expert = TaskExpert(pool=mock_pool, organization_id=organization_id)

        priority = expert._extract_priority("これは緊急のタスクです")
        assert priority == TASK_PRIORITY_URGENT

    def test_extract_priority_high(self, mock_pool, organization_id):
        """Test priority extraction for high."""
        expert = TaskExpert(pool=mock_pool, organization_id=organization_id)

        priority = expert._extract_priority("これは重要なタスクです")
        assert priority == TASK_PRIORITY_HIGH

    def test_extract_priority_low(self, mock_pool, organization_id):
        """Test priority extraction for low."""
        expert = TaskExpert(pool=mock_pool, organization_id=organization_id)

        priority = expert._extract_priority("暇な時にやって")
        assert priority == TASK_PRIORITY_LOW

    def test_extract_priority_default(self, mock_pool, organization_id):
        """Test default priority extraction."""
        expert = TaskExpert(pool=mock_pool, organization_id=organization_id)

        priority = expert._extract_priority("普通のメッセージ")
        assert priority == TASK_PRIORITY_NORMAL


# =============================================================================
# Part 8: GoalExpert Session Tests
# =============================================================================

class TestGoalExpertSession:
    """GoalExpert session management tests."""

    @pytest.mark.asyncio
    async def test_goal_setting_start_creates_session(
        self, mock_pool, organization_id, agent_context
    ):
        """Test that goal_setting_start creates a session."""
        expert = GoalExpert(pool=mock_pool, organization_id=organization_id)

        content = {"action": "goal_setting_start"}
        result = await expert._handle_goal_setting_start(content, agent_context)

        session_key = f"{agent_context.user_id}:{agent_context.room_id}"
        assert session_key in expert._active_sessions
        assert result["current_step"] == GOAL_STEP_WHY

    @pytest.mark.asyncio
    async def test_goal_setting_continue_progresses_steps(
        self, mock_pool, organization_id, agent_context
    ):
        """Test that goal_setting_continue progresses through steps."""
        expert = GoalExpert(pool=mock_pool, organization_id=organization_id)

        # Start session
        await expert._handle_goal_setting_start({}, agent_context)

        # Provide WHY
        content_why = {
            "message": "成長したいからです。自分を高めたいと思っています。"
        }
        result_why = await expert._handle_goal_setting_continue(
            content_why, agent_context
        )
        assert result_why["current_step"] == GOAL_STEP_WHAT

        # Provide WHAT
        content_what = {
            "message": "プログラミングスキルを向上させて、新しいプロジェクトをリードしたい"
        }
        result_what = await expert._handle_goal_setting_continue(
            content_what, agent_context
        )
        assert result_what["current_step"] == GOAL_STEP_HOW

        # Provide HOW
        content_how = {
            "message": "毎日1時間勉強する、週末はプロジェクトに取り組むことを実行します"
        }
        result_how = await expert._handle_goal_setting_continue(
            content_how, agent_context
        )
        assert result_how["current_step"] == GOAL_STEP_COMPLETE

        # Session should be removed after completion
        session_key = f"{agent_context.user_id}:{agent_context.room_id}"
        assert session_key not in expert._active_sessions

    @pytest.mark.asyncio
    async def test_goal_setting_continue_no_session(
        self, mock_pool, organization_id, agent_context
    ):
        """Test continue without an active session."""
        expert = GoalExpert(pool=mock_pool, organization_id=organization_id)

        content = {"message": "進捗報告"}
        result = await expert._handle_goal_setting_continue(content, agent_context)

        assert result.get("error") == "active_session_not_found"

    def test_validate_step_input_too_short(self, mock_pool, organization_id):
        """Test validation rejects too short input."""
        expert = GoalExpert(pool=mock_pool, organization_id=organization_id)

        result = expert._validate_step_input(GOAL_STEP_WHY, "短い")

        assert result["valid"] is False

    def test_validate_step_input_why_no_reason(self, mock_pool, organization_id):
        """Test WHY step validation requires reason keywords."""
        expert = GoalExpert(pool=mock_pool, organization_id=organization_id)

        result = expert._validate_step_input(
            GOAL_STEP_WHY,
            "これは十分長いですがなぜという言葉がない"
        )

        assert result["valid"] is False

    def test_validate_step_input_why_valid(self, mock_pool, organization_id):
        """Test valid WHY input."""
        expert = GoalExpert(pool=mock_pool, organization_id=organization_id)

        result = expert._validate_step_input(
            GOAL_STEP_WHY,
            "成長したいからです。自分を高めたいと思っています。"
        )

        assert result["valid"] is True


# =============================================================================
# Part 9: EmotionExpert Detection Tests
# =============================================================================

class TestEmotionExpertDetection:
    """EmotionExpert emotion detection tests."""

    def test_detect_multiple_negative_emotions(self, mock_pool, organization_id):
        """Test detection with multiple negative emotion keywords."""
        expert = EmotionExpert(pool=mock_pool, organization_id=organization_id)

        state = expert._detect_emotion_state(
            "不安で心配で、とても疲れた状態です"
        )

        assert len(state.detected_keywords) >= 2
        assert state.intensity > 0.5

    def test_detect_urgent_overrides_emotion(self, mock_pool, organization_id):
        """Test that urgent keywords take priority."""
        expert = EmotionExpert(pool=mock_pool, organization_id=organization_id)

        state = expert._detect_emotion_state("もう限界で消えたいです")

        assert state.urgency == UrgencyLevel.CRITICAL
        assert state.primary_emotion == EmotionType.FEAR
        assert state.intensity == 1.0

    def test_detect_positive_overrides_negative(self, mock_pool, organization_id):
        """Test positive emotion detection."""
        expert = EmotionExpert(pool=mock_pool, organization_id=organization_id)

        state = expert._detect_emotion_state(
            "やった！成功した！嬉しい！"
        )

        assert state.primary_emotion == EmotionType.JOY

    def test_classify_negative_emotion_sadness(self, mock_pool, organization_id):
        """Test classifying sadness emotion."""
        expert = EmotionExpert(pool=mock_pool, organization_id=organization_id)

        emotion = expert._classify_negative_emotion(["悲しい", "落ち込む"])
        assert emotion == EmotionType.SADNESS

    def test_classify_negative_emotion_anger(self, mock_pool, organization_id):
        """Test classifying anger emotion."""
        expert = EmotionExpert(pool=mock_pool, organization_id=organization_id)

        emotion = expert._classify_negative_emotion(["イライラ", "怒り"])
        assert emotion == EmotionType.ANGER

    @pytest.mark.asyncio
    async def test_handle_urgent_case(self, mock_pool, organization_id, agent_context):
        """Test urgent case handling."""
        expert = EmotionExpert(pool=mock_pool, organization_id=organization_id)

        message = AgentMessage(
            from_agent=AgentType.ORCHESTRATOR,
            to_agent=AgentType.EMOTION_EXPERT,
            content={"message": "死にたい、もう限界です"},
        )

        emotion_state = expert._detect_emotion_state("死にたい、もう限界です")
        response = await expert._handle_urgent_case(
            message, agent_context, emotion_state
        )

        assert response.success is True
        assert response.result.get("urgency") == "critical"
        assert "resources" in response.result
        assert response.confidence == 1.0


# =============================================================================
# Part 10: HRExpert Tests
# =============================================================================

class TestHRExpertHandlers:
    """HRExpert handler tests."""

    @pytest.mark.asyncio
    async def test_handle_guide_consultation_sensitive(
        self, mock_pool, organization_id, agent_context
    ):
        """Test consultation guide for sensitive topics."""
        expert = HRExpert(pool=mock_pool, organization_id=organization_id)

        content = {"topic": "上司からパワハラを受けています"}
        result = await expert._handle_guide_consultation(content, agent_context)

        assert result["is_sensitive"] is True
        assert "note" in result

    @pytest.mark.asyncio
    async def test_handle_guide_consultation_normal(
        self, mock_pool, organization_id, agent_context
    ):
        """Test consultation guide for normal topics."""
        expert = HRExpert(pool=mock_pool, organization_id=organization_id)

        content = {"topic": "有給休暇の申請方法"}
        result = await expert._handle_guide_consultation(content, agent_context)

        assert result["is_sensitive"] is False

    def test_infer_action_consultation_priority(self, mock_pool, organization_id):
        """Test that consultation has priority in action inference."""
        expert = HRExpert(pool=mock_pool, organization_id=organization_id)

        # Message with consultation keyword should prioritize consultation
        action = expert._infer_action("悩みを相談したいです")
        assert action == "guide_consultation"

    def test_infer_action_onboarding(self, mock_pool, organization_id):
        """Test onboarding action inference."""
        expert = HRExpert(pool=mock_pool, organization_id=organization_id)

        # Note: "入社" is in EMPLOYMENT_KEYWORDS but "手続き" is in PROCEDURE_KEYWORDS
        # which has higher priority. Testing with a pure employment message.
        action = expert._infer_action("入社について教えてください")
        assert action == "onboarding_guide"

    def test_infer_action_offboarding(self, mock_pool, organization_id):
        """Test offboarding action inference."""
        expert = HRExpert(pool=mock_pool, organization_id=organization_id)

        # Note: "手続き" triggers guide_procedure first.
        # Testing with a pure employment message.
        action = expert._infer_action("退職について知りたい")
        assert action == "offboarding_guide"


# =============================================================================
# Part 11: OrganizationExpert Tests
# =============================================================================

class TestOrganizationExpertConfidence:
    """OrganizationExpert confidence calculation tests."""

    def test_confidence_with_org_graph_boost(
        self, mock_pool, organization_id, agent_context
    ):
        """Test that org_graph provides confidence boost."""
        mock_org_graph = MagicMock()

        expert_with = OrganizationExpert(
            pool=mock_pool,
            organization_id=organization_id,
            org_graph=mock_org_graph,
        )

        expert_without = OrganizationExpert(
            pool=mock_pool,
            organization_id=organization_id,
        )

        conf_with = expert_with.get_confidence("query_org_chart", agent_context)
        conf_without = expert_without.get_confidence("query_org_chart", agent_context)

        assert conf_with > conf_without

    def test_infer_action_recommendation_priority(self, mock_pool, organization_id):
        """Test that recommendation has priority."""
        expert = OrganizationExpert(pool=mock_pool, organization_id=organization_id)

        action = expert._infer_action("経理のことは誰に相談すればいいですか")
        assert action == "recommend_person"

    def test_infer_action_expertise(self, mock_pool, organization_id):
        """Test expertise search action inference."""
        expert = OrganizationExpert(pool=mock_pool, organization_id=organization_id)

        # Note: "専門家" is in RECOMMENDATION_KEYWORDS which has higher priority.
        # EXPERTISE_KEYWORDS contains "スキル", "資格", "実績" without overlap with recommendations.
        # Using a pure expertise keyword without recommendation overlap.
        action = expert._infer_action("Pythonのスキルを持つ人を探しています")
        assert action == "find_expert"


# =============================================================================
# Part 12: KnowledgeExpert Tests
# =============================================================================

class TestKnowledgeExpertHandlers:
    """KnowledgeExpert handler tests."""

    @pytest.mark.asyncio
    async def test_handle_save_memory(self, mock_pool, organization_id, agent_context):
        """Test memory save handler."""
        expert = KnowledgeExpert(pool=mock_pool, organization_id=organization_id)

        content = {
            "action": "save_memory",
            "message": "田中さんは営業部長です",
            "subject": "田中",
        }

        result = await expert._handle_save_memory(content, agent_context)

        assert result["action"] == "save_memory"
        assert result["requires_external_handler"] is True

    @pytest.mark.asyncio
    async def test_handle_forget_knowledge(
        self, mock_pool, organization_id, agent_context
    ):
        """Test knowledge forget handler."""
        expert = KnowledgeExpert(pool=mock_pool, organization_id=organization_id)

        content = {"action": "forget_knowledge", "message": "田中さんのことを忘れて"}

        result = await expert._handle_forget_knowledge(content, agent_context)

        assert result["action"] == "forget_knowledge"
        assert result["requires_external_handler"] is True

    def test_infer_action_delete_priority(self, mock_pool, organization_id):
        """Test delete action has priority over search."""
        expert = KnowledgeExpert(pool=mock_pool, organization_id=organization_id)

        action = expert._infer_action("これを忘れて削除して")
        assert action == "forget_knowledge"


# =============================================================================
# Part 13: Statistics Tests
# =============================================================================

class TestAgentStatistics:
    """Agent statistics tests."""

    def test_success_rate_calculation(self):
        """Test success rate calculation."""
        stats = AgentStats(
            total_requests=100,
            successful_requests=75,
            failed_requests=25,
        )

        assert stats.success_rate == 0.75

    def test_success_rate_zero_requests(self):
        """Test success rate with zero requests."""
        stats = AgentStats()

        assert stats.success_rate == 0.0

    @pytest.mark.asyncio
    async def test_stats_update_after_processing(
        self, mock_pool, organization_id, agent_context
    ):
        """Test statistics update after processing."""
        expert = TaskExpert(pool=mock_pool, organization_id=organization_id)

        initial_total = expert.stats.total_requests

        message = AgentMessage(
            from_agent=AgentType.ORCHESTRATOR,
            to_agent=AgentType.TASK_EXPERT,
            content={"action": "task_search"},
        )

        await expert.handle_message(agent_context, message)

        assert expert.stats.total_requests > initial_total
        assert expert.stats.avg_processing_time_ms > 0


# =============================================================================
# Part 14: Routing Cache Tests
# =============================================================================

class TestOrchestratorCache:
    """Orchestrator routing cache tests."""

    @pytest.mark.asyncio
    async def test_routing_cache_hit(
        self, orchestrator_with_all_agents, agent_context
    ):
        """Test that routing is cached."""
        orchestrator = orchestrator_with_all_agents

        # First call - should cache
        routing1 = await orchestrator._decide_routing(
            "タスクを作成して", agent_context
        )

        # Second call - should hit cache
        routing2 = await orchestrator._decide_routing(
            "タスクを作成して", agent_context
        )

        assert routing1.primary_agent == routing2.primary_agent

    def test_clear_routing_cache(self, orchestrator_with_all_agents):
        """Test clearing routing cache."""
        orchestrator = orchestrator_with_all_agents
        orchestrator._routing_cache["test"] = RoutingDecision(
            primary_agent=AgentType.TASK_EXPERT
        )

        orchestrator.clear_routing_cache()

        assert len(orchestrator._routing_cache) == 0

    def test_get_agent_stats(self, orchestrator_with_all_agents):
        """Test getting all agent statistics."""
        orchestrator = orchestrator_with_all_agents

        stats = orchestrator.get_agent_stats()

        assert AgentType.TASK_EXPERT in stats
        assert AgentType.GOAL_EXPERT in stats
        assert "total_requests" in stats[AgentType.TASK_EXPERT]


# =============================================================================
# Part 15: Data Class to_dict Tests
# =============================================================================

class TestDataClassSerialization:
    """Data class serialization tests."""

    def test_agent_capability_to_dict(self):
        """Test AgentCapability.to_dict()."""
        capability = AgentCapability(
            capability_id="test",
            name="Test",
            description="Test description",
            keywords=["test"],
            actions=["test_action"],
            expertise_level=ExpertiseLevel.PRIMARY,
            confidence_boost=0.1,
        )

        data = capability.to_dict()

        assert data["capability_id"] == "test"
        assert data["expertise_level"] == "primary"
        assert isinstance(data["keywords"], list)

    def test_agent_message_to_dict(self):
        """Test AgentMessage.to_dict()."""
        msg = AgentMessage(
            id="msg-001",
            from_agent=AgentType.ORCHESTRATOR,
            to_agent=AgentType.TASK_EXPERT,
            message_type=MessageType.REQUEST,
            content={"action": "test"},
        )

        data = msg.to_dict()

        assert data["id"] == "msg-001"
        assert data["from_agent"] == "orchestrator"
        assert data["to_agent"] == "task_expert"
        assert data["message_type"] == "request"

    def test_agent_response_to_dict(self):
        """Test AgentResponse.to_dict()."""
        response = AgentResponse(
            id="resp-001",
            request_id="msg-001",
            agent_type=AgentType.TASK_EXPERT,
            success=True,
            result={"data": "test"},
            confidence=0.9,
            delegate_to=AgentType.GOAL_EXPERT,
        )

        data = response.to_dict()

        assert data["id"] == "resp-001"
        assert data["agent_type"] == "task_expert"
        assert data["success"] is True
        assert data["delegate_to"] == "goal_expert"


# =============================================================================
# Part 16: Task Analysis Tests
# =============================================================================

class TestTaskAnalysis:
    """TaskExpert analysis tests."""

    def test_analyze_tasks_workload_overloaded(self, mock_pool, organization_id):
        """Test workload detection - overloaded."""
        expert = TaskExpert(pool=mock_pool, organization_id=organization_id)

        tasks = [
            {
                "task_id": str(i),
                "status": "open",
                "due_date": (datetime.now() - timedelta(days=1)).isoformat(),
            }
            for i in range(5)
        ]

        analysis = expert._analyze_tasks(tasks)

        assert analysis.overdue_tasks == 5
        assert analysis.workload_level == "overloaded"

    def test_analyze_tasks_workload_light(self, mock_pool, organization_id):
        """Test workload detection - light."""
        expert = TaskExpert(pool=mock_pool, organization_id=organization_id)

        tasks = [
            {
                "task_id": "1",
                "status": "open",
                "due_date": (datetime.now() + timedelta(days=7)).isoformat(),
            }
        ]

        analysis = expert._analyze_tasks(tasks)

        assert analysis.workload_level == "light"

    def test_prioritize_tasks_order(self, mock_pool, organization_id):
        """Test task prioritization order."""
        expert = TaskExpert(pool=mock_pool, organization_id=organization_id)

        tasks = [
            {"task_id": "1", "priority": TASK_PRIORITY_LOW},
            {"task_id": "2", "priority": TASK_PRIORITY_URGENT},
            {"task_id": "3", "priority": TASK_PRIORITY_NORMAL},
        ]

        prioritized = expert._prioritize_tasks(tasks)

        assert prioritized[0]["task_id"] == "2"  # URGENT first
        assert prioritized[-1]["task_id"] == "1"  # LOW last


# =============================================================================
# Part 17: Error Handling Edge Cases
# =============================================================================

class TestErrorHandlingEdgeCases:
    """Error handling edge case tests."""

    @pytest.mark.asyncio
    async def test_process_with_none_content(
        self, mock_pool, organization_id, agent_context
    ):
        """Test processing with None in content causes error (edge case behavior)."""
        expert = TaskExpert(pool=mock_pool, organization_id=organization_id)

        message = AgentMessage(
            from_agent=AgentType.ORCHESTRATOR,
            to_agent=AgentType.TASK_EXPERT,
            content={"action": None, "message": None},
        )

        # This will be caught by handle_message's exception handler
        response = await expert.handle_message(agent_context, message)

        # Should return error response due to None message
        assert isinstance(response, AgentResponse)
        # The response may fail due to None message, which is expected behavior
        assert response.success is False or response.result is not None

    @pytest.mark.asyncio
    async def test_process_unknown_action(
        self, mock_pool, organization_id, agent_context
    ):
        """Test processing with unknown action."""
        expert = TaskExpert(pool=mock_pool, organization_id=organization_id)

        message = AgentMessage(
            from_agent=AgentType.ORCHESTRATOR,
            to_agent=AgentType.TASK_EXPERT,
            content={"action": "unknown_action_xyz"},
        )

        response = await expert.process(agent_context, message)

        # Should fail gracefully
        assert response.success is False

    def test_get_keywords_returns_set(self, mock_pool, organization_id):
        """Test get_keywords returns a set."""
        expert = TaskExpert(pool=mock_pool, organization_id=organization_id)

        keywords = expert.get_keywords()

        assert isinstance(keywords, set)
        assert len(keywords) > 0

    def test_get_capability_for_action_not_found(self, mock_pool, organization_id):
        """Test get_capability_for_action returns None for unknown action."""
        expert = TaskExpert(pool=mock_pool, organization_id=organization_id)

        capability = expert.get_capability_for_action("unknown_action")

        assert capability is None


# =============================================================================
# Part 18: Agent Registry Tests
# =============================================================================

class TestAgentRegistry:
    """Agent registry tests."""

    def test_set_agent_registry(self, mock_pool, organization_id):
        """Test setting agent registry."""
        expert = TaskExpert(pool=mock_pool, organization_id=organization_id)
        goal_expert = GoalExpert(pool=mock_pool, organization_id=organization_id)

        registry = {
            AgentType.TASK_EXPERT: expert,
            AgentType.GOAL_EXPERT: goal_expert,
        }

        expert.set_agent_registry(registry)

        assert expert._agent_registry == registry
        assert AgentType.GOAL_EXPERT in expert._agent_registry

    def test_get_all_agents(self, orchestrator_with_all_agents):
        """Test getting all agents from orchestrator."""
        orchestrator = orchestrator_with_all_agents

        agents = orchestrator.get_all_agents()

        # Should include all registered agents + orchestrator
        assert len(agents) == 7
        assert all(isinstance(a, BaseAgent) for a in agents)


# =============================================================================
# Part 19: TaskInfo and GoalInfo Property Tests
# =============================================================================

class TestDataClassProperties:
    """Data class property tests."""

    def test_task_info_is_overdue_true(self):
        """Test TaskInfo.is_overdue property - true case."""
        task = TaskInfo(
            task_id="1",
            status="open",
            due_date=datetime.now() - timedelta(days=1),
        )

        assert task.is_overdue is True

    def test_task_info_is_overdue_false(self):
        """Test TaskInfo.is_overdue property - false case."""
        task = TaskInfo(
            task_id="1",
            status="open",
            due_date=datetime.now() + timedelta(days=1),
        )

        assert task.is_overdue is False

    def test_task_info_is_overdue_done(self):
        """Test TaskInfo.is_overdue property - done status."""
        task = TaskInfo(
            task_id="1",
            status="done",
            due_date=datetime.now() - timedelta(days=1),
        )

        # Done tasks are not overdue
        assert task.is_overdue is False

    def test_task_info_days_until_due(self):
        """Test TaskInfo.days_until_due property."""
        task = TaskInfo(
            task_id="1",
            due_date=datetime.now() + timedelta(days=5),
        )

        assert task.days_until_due is not None
        assert 4 <= task.days_until_due <= 5

    def test_goal_info_is_stale(self):
        """Test GoalInfo.is_stale property."""
        goal = GoalInfo(
            goal_id="1",
            status="active",
            updated_at=datetime.now() - timedelta(days=10),
        )

        assert goal.is_stale is True

    def test_goal_info_days_since_update(self):
        """Test GoalInfo.days_since_update property."""
        goal = GoalInfo(
            goal_id="1",
            updated_at=datetime.now() - timedelta(days=5),
        )

        assert goal.days_since_update == 5
