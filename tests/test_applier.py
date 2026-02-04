"""
Comprehensive unit tests for applier.py

Target: /Users/kikubookair/soul-kun/lib/brain/learning_foundation/applier.py
Coverage goal: 80%+

Tests cover:
- LearningApplier class
  - __init__
  - find_applicable
  - apply
  - apply_all
  - build_context_additions
  - build_prompt_instructions
  - record_feedback
  - _select_best_learnings
  - _generate_modification
  - _generate_mention_text

- LearningApplierWithCeoCheck class
  - __init__
  - find_applicable_with_ceo_check
  - _filter_conflicting_with_ceo
  - _is_conflicting

- Factory functions
  - create_applier
  - create_applier_with_ceo_check
"""

import pytest
from datetime import datetime
from unittest.mock import Mock, MagicMock, patch, call
from uuid import uuid4

from lib.brain.learning_foundation.applier import (
    LearningApplier,
    LearningApplierWithCeoCheck,
    create_applier,
    create_applier_with_ceo_check,
)
from lib.brain.learning_foundation.constants import (
    AuthorityLevel,
    AUTHORITY_PRIORITY,
    LearningCategory,
    LearningScope,
    TriggerType,
    MENTION_TEMPLATES,
)
from lib.brain.learning_foundation.models import (
    AppliedLearning,
    ConversationContext,
    Learning,
    LearningLog,
)
from lib.brain.learning_foundation.repository import LearningRepository


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def mock_conn():
    """Mock DB connection"""
    conn = MagicMock()
    conn.execute = MagicMock(return_value=MagicMock(fetchone=MagicMock(return_value=None)))
    return conn


@pytest.fixture
def mock_repository():
    """Mock LearningRepository"""
    repo = MagicMock(spec=LearningRepository)
    repo.find_applicable = MagicMock(return_value=[])
    repo.increment_apply_count = MagicMock(return_value=True)
    repo.save_log = MagicMock(return_value="log-id")
    repo.update_feedback_count = MagicMock(return_value=True)
    repo.update_log_feedback = MagicMock(return_value=True)
    return repo


@pytest.fixture
def sample_alias_learning():
    """Sample alias learning"""
    return Learning(
        id=str(uuid4()),
        organization_id="org_test",
        category=LearningCategory.ALIAS.value,
        trigger_type=TriggerType.KEYWORD.value,
        trigger_value="mtg",
        learned_content={
            "type": "alias",
            "from": "mtg",
            "to": "ミーティング",
            "bidirectional": False,
            "description": "mtgはミーティングの略称",
        },
        scope=LearningScope.GLOBAL.value,
        authority_level=AuthorityLevel.USER.value,
        taught_by_account_id="12345",
        taught_by_name="田中さん",
        is_active=True,
        applied_count=0,
        created_at=datetime.now(),
    )


@pytest.fixture
def sample_ceo_rule_learning():
    """Sample CEO rule learning"""
    return Learning(
        id=str(uuid4()),
        organization_id="org_test",
        category=LearningCategory.RULE.value,
        trigger_type=TriggerType.ALWAYS.value,
        trigger_value="*",
        learned_content={
            "type": "rule",
            "condition": "常に",
            "action": "人の可能性を信じる",
            "priority": "high",
            "is_prohibition": False,
            "description": "人の可能性を信じる",
        },
        scope=LearningScope.GLOBAL.value,
        authority_level=AuthorityLevel.CEO.value,
        taught_by_account_id="1728974",
        taught_by_name="菊地さん",
        is_active=True,
        applied_count=5,
        created_at=datetime.now(),
    )


@pytest.fixture
def sample_correction_learning():
    """Sample correction learning"""
    return Learning(
        id=str(uuid4()),
        organization_id="org_test",
        category=LearningCategory.CORRECTION.value,
        trigger_type=TriggerType.KEYWORD.value,
        trigger_value="田中",
        learned_content={
            "type": "correction",
            "wrong_pattern": "田中",
            "correct_pattern": "佐藤",
            "reason": "担当者変更",
            "description": "田中→佐藤に修正",
        },
        scope=LearningScope.GLOBAL.value,
        authority_level=AuthorityLevel.USER.value,
        taught_by_account_id="67890",
        taught_by_name="山田さん",
        is_active=True,
        applied_count=2,
        created_at=datetime.now(),
    )


@pytest.fixture
def sample_preference_learning():
    """Sample preference learning"""
    return Learning(
        id=str(uuid4()),
        organization_id="org_test",
        category=LearningCategory.PREFERENCE.value,
        trigger_type=TriggerType.ALWAYS.value,
        trigger_value="*",
        learned_content={
            "type": "preference",
            "subject": "報告形式",
            "preference": "箇条書き",
            "priority": "high",
            "description": "箇条書きで報告してほしい",
        },
        scope=LearningScope.USER.value,
        scope_target_id="user123",
        authority_level=AuthorityLevel.USER.value,
        taught_by_account_id="user123",
        taught_by_name="鈴木さん",
        is_active=True,
        applied_count=10,
        created_at=datetime.now(),
    )


@pytest.fixture
def sample_fact_learning():
    """Sample fact learning"""
    return Learning(
        id=str(uuid4()),
        organization_id="org_test",
        category=LearningCategory.FACT.value,
        trigger_type=TriggerType.KEYWORD.value,
        trigger_value="会議室",
        learned_content={
            "type": "fact",
            "subject": "会議室",
            "value": "3階のA会議室",
            "description": "定例会議は3階のA会議室で行う",
            "source": "総務部",
        },
        scope=LearningScope.GLOBAL.value,
        authority_level=AuthorityLevel.MANAGER.value,
        taught_by_account_id="mgr001",
        taught_by_name="部長",
        is_active=True,
        applied_count=3,
        created_at=datetime.now(),
    )


@pytest.fixture
def sample_context_learning():
    """Sample context learning"""
    return Learning(
        id=str(uuid4()),
        organization_id="org_test",
        category=LearningCategory.CONTEXT.value,
        trigger_type=TriggerType.CONTEXT.value,
        trigger_value="決算",
        learned_content={
            "type": "context",
            "subject": "決算期",
            "context": "今月は決算期",
            "implications": ["忙しい", "残業増加"],
            "description": "今月は決算期なので忙しい",
        },
        scope=LearningScope.GLOBAL.value,
        authority_level=AuthorityLevel.USER.value,
        taught_by_account_id="acct123",
        taught_by_name="経理担当",
        is_active=True,
        applied_count=1,
        created_at=datetime.now(),
    )


@pytest.fixture
def sample_relationship_learning():
    """Sample relationship learning"""
    return Learning(
        id=str(uuid4()),
        organization_id="org_test",
        category=LearningCategory.RELATIONSHIP.value,
        trigger_type=TriggerType.KEYWORD.value,
        trigger_value="田中,佐藤",
        learned_content={
            "type": "relationship",
            "person1": "田中",
            "person2": "佐藤",
            "relationship": "同期",
            "description": "田中と佐藤は同期入社",
        },
        scope=LearningScope.GLOBAL.value,
        authority_level=AuthorityLevel.USER.value,
        taught_by_account_id="hr001",
        taught_by_name="人事担当",
        is_active=True,
        applied_count=0,
        created_at=datetime.now(),
    )


@pytest.fixture
def sample_procedure_learning():
    """Sample procedure learning"""
    return Learning(
        id=str(uuid4()),
        organization_id="org_test",
        category=LearningCategory.PROCEDURE.value,
        trigger_type=TriggerType.KEYWORD.value,
        trigger_value="経費精算",
        learned_content={
            "type": "procedure",
            "task": "経費精算",
            "steps": ["申請書作成", "上長承認", "経理提出"],
            "description": "経費精算は申請書を作成し上長承認後に経理に提出",
        },
        scope=LearningScope.GLOBAL.value,
        authority_level=AuthorityLevel.USER.value,
        taught_by_account_id="acct456",
        taught_by_name="総務担当",
        is_active=True,
        applied_count=5,
        created_at=datetime.now(),
    )


@pytest.fixture
def sample_conversation_context():
    """Sample conversation context

    Note: applier.py uses context.user_account_id but ConversationContext
    model only has user_id. We add user_account_id as an attribute for testing.
    """
    context = ConversationContext(
        previous_messages=[
            {"role": "user", "content": "タスクを教えて"},
            {"role": "assistant", "content": "タスク一覧を表示するウル！"},
        ],
        soulkun_last_action="task_search",
        soulkun_last_response="タスク一覧を表示するウル！",
        has_recent_error=False,
        room_id="room123",
        room_name="テストルーム",
        user_id="user456",
        user_name="田中さん",
    )
    # Add user_account_id for applier.py compatibility (applier uses user_account_id)
    context.user_account_id = "account456"
    return context


# =============================================================================
# LearningApplier Tests - Initialization
# =============================================================================

class TestLearningApplierInit:
    """Tests for LearningApplier initialization"""

    def test_init_with_organization_id(self):
        """Initialize with organization ID only"""
        applier = LearningApplier("org_test")
        assert applier.organization_id == "org_test"
        assert applier.repository is not None
        assert isinstance(applier.repository, LearningRepository)

    def test_init_with_custom_repository(self, mock_repository):
        """Initialize with custom repository"""
        applier = LearningApplier("org_test", repository=mock_repository)
        assert applier.organization_id == "org_test"
        assert applier.repository is mock_repository

    def test_init_with_empty_organization_id(self):
        """Initialize with empty organization ID"""
        applier = LearningApplier("")
        assert applier.organization_id == ""
        assert applier.repository is not None


# =============================================================================
# LearningApplier Tests - find_applicable
# =============================================================================

class TestLearningApplierFindApplicable:
    """Tests for find_applicable method"""

    def test_find_applicable_returns_empty_list_when_no_learnings(
        self, mock_conn, mock_repository
    ):
        """Returns empty list when no learnings found"""
        mock_repository.find_applicable.return_value = []
        applier = LearningApplier("org_test", repository=mock_repository)

        result = applier.find_applicable(mock_conn, "test message")

        assert result == []
        mock_repository.find_applicable.assert_called_once()

    def test_find_applicable_returns_learnings(
        self, mock_conn, mock_repository, sample_alias_learning
    ):
        """Returns learnings when found"""
        mock_repository.find_applicable.return_value = [sample_alias_learning]
        applier = LearningApplier("org_test", repository=mock_repository)

        result = applier.find_applicable(mock_conn, "mtgの予定")

        assert len(result) == 1
        assert result[0] == sample_alias_learning

    def test_find_applicable_with_context(
        self, mock_conn, mock_repository, sample_alias_learning, sample_conversation_context
    ):
        """Uses context for user_id and room_id"""
        mock_repository.find_applicable.return_value = [sample_alias_learning]
        applier = LearningApplier("org_test", repository=mock_repository)

        result = applier.find_applicable(
            mock_conn,
            "test message",
            context=sample_conversation_context,
        )

        # Check that repository was called with context values
        call_kwargs = mock_repository.find_applicable.call_args[1]
        assert call_kwargs.get("user_id") == sample_conversation_context.user_account_id
        assert call_kwargs.get("room_id") == sample_conversation_context.room_id

    def test_find_applicable_with_explicit_user_and_room_id(
        self, mock_conn, mock_repository, sample_alias_learning
    ):
        """Uses explicit user_id and room_id over context"""
        mock_repository.find_applicable.return_value = [sample_alias_learning]
        applier = LearningApplier("org_test", repository=mock_repository)

        result = applier.find_applicable(
            mock_conn,
            "test message",
            user_id="explicit_user",
            room_id="explicit_room",
        )

        call_kwargs = mock_repository.find_applicable.call_args[1]
        assert call_kwargs.get("user_id") == "explicit_user"
        assert call_kwargs.get("room_id") == "explicit_room"

    def test_find_applicable_context_overrides_none_values(
        self, mock_conn, mock_repository, sample_alias_learning, sample_conversation_context
    ):
        """Context fills in None user_id and room_id"""
        mock_repository.find_applicable.return_value = [sample_alias_learning]
        applier = LearningApplier("org_test", repository=mock_repository)

        result = applier.find_applicable(
            mock_conn,
            "test message",
            context=sample_conversation_context,
            user_id=None,
            room_id=None,
        )

        call_kwargs = mock_repository.find_applicable.call_args[1]
        assert call_kwargs.get("user_id") == sample_conversation_context.user_account_id
        assert call_kwargs.get("room_id") == sample_conversation_context.room_id


# =============================================================================
# LearningApplier Tests - _select_best_learnings
# =============================================================================

class TestLearningApplierSelectBestLearnings:
    """Tests for _select_best_learnings method"""

    def test_select_best_learnings_empty_list(self, mock_repository):
        """Returns empty list for empty input"""
        applier = LearningApplier("org_test", repository=mock_repository)
        result = applier._select_best_learnings([], "test")
        assert result == []

    def test_select_best_learnings_single_learning(
        self, mock_repository, sample_alias_learning
    ):
        """Returns single learning unchanged"""
        applier = LearningApplier("org_test", repository=mock_repository)
        result = applier._select_best_learnings([sample_alias_learning], "test")
        assert len(result) == 1
        assert result[0] == sample_alias_learning

    def test_select_best_learnings_prioritizes_ceo_over_user(
        self, mock_repository, sample_alias_learning
    ):
        """CEO authority takes priority over user"""
        applier = LearningApplier("org_test", repository=mock_repository)

        # Create two learnings with same category and trigger but different authority
        user_learning = Learning(
            id="user-learning",
            category=LearningCategory.ALIAS.value,
            trigger_value="mtg",
            authority_level=AuthorityLevel.USER.value,
            learned_content={"from": "mtg", "to": "ミーティング"},
        )
        ceo_learning = Learning(
            id="ceo-learning",
            category=LearningCategory.ALIAS.value,
            trigger_value="mtg",
            authority_level=AuthorityLevel.CEO.value,
            learned_content={"from": "mtg", "to": "会議"},
        )

        result = applier._select_best_learnings([user_learning, ceo_learning], "mtg")

        assert len(result) == 1
        assert result[0].id == "ceo-learning"

    def test_select_best_learnings_prioritizes_manager_over_user(
        self, mock_repository
    ):
        """Manager authority takes priority over user"""
        applier = LearningApplier("org_test", repository=mock_repository)

        user_learning = Learning(
            id="user-learning",
            category=LearningCategory.RULE.value,
            trigger_value="monday",
            authority_level=AuthorityLevel.USER.value,
            learned_content={"condition": "monday", "action": "user action"},
        )
        manager_learning = Learning(
            id="manager-learning",
            category=LearningCategory.RULE.value,
            trigger_value="monday",
            authority_level=AuthorityLevel.MANAGER.value,
            learned_content={"condition": "monday", "action": "manager action"},
        )

        result = applier._select_best_learnings([user_learning, manager_learning], "monday")

        assert len(result) == 1
        assert result[0].id == "manager-learning"

    def test_select_best_learnings_different_categories_all_returned(
        self, mock_repository
    ):
        """Different categories are all returned"""
        applier = LearningApplier("org_test", repository=mock_repository)

        alias_learning = Learning(
            id="alias",
            category=LearningCategory.ALIAS.value,
            trigger_value="mtg",
            authority_level=AuthorityLevel.USER.value,
            learned_content={"from": "mtg", "to": "ミーティング"},
        )
        rule_learning = Learning(
            id="rule",
            category=LearningCategory.RULE.value,
            trigger_value="mtg",
            authority_level=AuthorityLevel.USER.value,
            learned_content={"condition": "mtg", "action": "notify"},
        )

        result = applier._select_best_learnings([alias_learning, rule_learning], "mtg")

        assert len(result) == 2

    def test_select_best_learnings_different_triggers_all_returned(
        self, mock_repository
    ):
        """Different triggers within same category are all returned"""
        applier = LearningApplier("org_test", repository=mock_repository)

        learning1 = Learning(
            id="learning1",
            category=LearningCategory.ALIAS.value,
            trigger_value="mtg",
            authority_level=AuthorityLevel.USER.value,
            learned_content={"from": "mtg", "to": "ミーティング"},
        )
        learning2 = Learning(
            id="learning2",
            category=LearningCategory.ALIAS.value,
            trigger_value="pl",
            authority_level=AuthorityLevel.USER.value,
            learned_content={"from": "pl", "to": "プロジェクトリーダー"},
        )

        result = applier._select_best_learnings([learning1, learning2], "mtg pl")

        assert len(result) == 2

    def test_select_best_learnings_system_has_lowest_priority(
        self, mock_repository
    ):
        """System authority has lowest priority"""
        applier = LearningApplier("org_test", repository=mock_repository)

        system_learning = Learning(
            id="system",
            category=LearningCategory.FACT.value,
            trigger_value="test",
            authority_level=AuthorityLevel.SYSTEM.value,
            learned_content={"subject": "test", "value": "system"},
        )
        user_learning = Learning(
            id="user",
            category=LearningCategory.FACT.value,
            trigger_value="test",
            authority_level=AuthorityLevel.USER.value,
            learned_content={"subject": "test", "value": "user"},
        )

        result = applier._select_best_learnings([system_learning, user_learning], "test")

        assert len(result) == 1
        assert result[0].id == "user"


# =============================================================================
# LearningApplier Tests - apply
# =============================================================================

class TestLearningApplierApply:
    """Tests for apply method"""

    def test_apply_increments_count(
        self, mock_conn, mock_repository, sample_alias_learning
    ):
        """Apply increments the apply count"""
        sample_alias_learning.applied_count = 0

        applier = LearningApplier("org_test", repository=mock_repository)

        applier.apply(mock_conn, sample_alias_learning, "test message")

        mock_repository.increment_apply_count.assert_called_once_with(
            mock_conn, sample_alias_learning.id
        )

    def test_apply_saves_log(
        self, mock_conn, mock_repository, sample_alias_learning
    ):
        """Apply saves a learning log with correct fields"""
        sample_alias_learning.applied_count = 0

        applier = LearningApplier("org_test", repository=mock_repository)

        applier.apply(
            mock_conn,
            sample_alias_learning,
            "test message",
            room_id="room123",
            account_id="account456",
        )

        # Verify save_log was called
        mock_repository.save_log.assert_called_once()
        # Get the actual LearningLog object passed to save_log
        saved_log = mock_repository.save_log.call_args[0][1]
        assert saved_log.organization_id == "org_test"
        assert saved_log.learning_id == sample_alias_learning.id
        assert saved_log.applied_in_room_id == "room123"
        assert saved_log.applied_for_account_id == "account456"
        assert saved_log.trigger_message == "test message"
        assert saved_log.was_successful is True
        assert saved_log.result_description == "applied"

    def test_apply_returns_applied_learning(
        self, mock_conn, mock_repository, sample_alias_learning
    ):
        """Apply returns AppliedLearning object with correct fields"""
        sample_alias_learning.applied_count = 0
        sample_alias_learning.category = "alias"

        applier = LearningApplier("org_test", repository=mock_repository)

        result = applier.apply(mock_conn, sample_alias_learning, "mtgの予定")

        assert result.learning == sample_alias_learning
        assert result.application_type == "alias"
        assert result.before_value == "mtgの予定"
        assert result.after_value is not None  # modification was generated

    def test_apply_with_context(
        self, mock_conn, mock_repository, sample_alias_learning, sample_conversation_context
    ):
        """Apply uses context for room_id and account_id"""
        sample_alias_learning.applied_count = 0

        applier = LearningApplier("org_test", repository=mock_repository)

        applier.apply(
            mock_conn,
            sample_alias_learning,
            "test",
            context=sample_conversation_context,
        )

        # Verify LearningLog was saved with context values
        saved_log = mock_repository.save_log.call_args[0][1]
        assert saved_log.applied_in_room_id == sample_conversation_context.room_id
        assert saved_log.applied_for_account_id == sample_conversation_context.user_account_id


# =============================================================================
# LearningApplier Tests - apply_all
# =============================================================================

class TestLearningApplierApplyAll:
    """Tests for apply_all method"""

    def test_apply_all_empty_list(self, mock_conn, mock_repository):
        """Apply all with empty list returns empty list"""
        applier = LearningApplier("org_test", repository=mock_repository)

        result = applier.apply_all(mock_conn, [], "test message")

        assert result == []
        mock_repository.increment_apply_count.assert_not_called()

    def test_apply_all_single_learning(
        self, mock_conn, mock_repository, sample_alias_learning
    ):
        """Apply all with single learning"""
        sample_alias_learning.applied_count = 0

        applier = LearningApplier("org_test", repository=mock_repository)

        result = applier.apply_all(
            mock_conn, [sample_alias_learning], "test message"
        )

        assert len(result) == 1
        mock_repository.increment_apply_count.assert_called_once()

    def test_apply_all_multiple_learnings(
        self, mock_conn, mock_repository, sample_alias_learning, sample_ceo_rule_learning
    ):
        """Apply all with multiple learnings"""
        sample_alias_learning.applied_count = 0
        sample_ceo_rule_learning.applied_count = 0

        applier = LearningApplier("org_test", repository=mock_repository)

        result = applier.apply_all(
            mock_conn,
            [sample_alias_learning, sample_ceo_rule_learning],
            "test message",
        )

        assert len(result) == 2
        assert mock_repository.increment_apply_count.call_count == 2
        assert mock_repository.save_log.call_count == 2


# =============================================================================
# LearningApplier Tests - build_context_additions
# =============================================================================

class TestLearningApplierBuildContextAdditions:
    """Tests for build_context_additions method"""

    def test_build_context_additions_empty_list(self, mock_repository):
        """Build context additions with empty list"""
        applier = LearningApplier("org_test", repository=mock_repository)

        result = applier.build_context_additions([])

        assert result == {
            "aliases": [],
            "preferences": [],
            "facts": [],
            "rules": [],
            "corrections": [],
            "contexts": [],
            "relationships": [],
            "procedures": [],
        }

    def test_build_context_additions_alias(
        self, mock_repository, sample_alias_learning
    ):
        """Build context additions for alias"""
        applier = LearningApplier("org_test", repository=mock_repository)
        applied = AppliedLearning(learning=sample_alias_learning)

        result = applier.build_context_additions([applied])

        assert len(result["aliases"]) == 1
        assert result["aliases"][0]["from"] == "mtg"
        assert result["aliases"][0]["to"] == "ミーティング"
        assert result["aliases"][0]["taught_by"] == "田中さん"

    def test_build_context_additions_preference(
        self, mock_repository, sample_preference_learning
    ):
        """Build context additions for preference"""
        applier = LearningApplier("org_test", repository=mock_repository)
        applied = AppliedLearning(learning=sample_preference_learning)

        result = applier.build_context_additions([applied])

        assert len(result["preferences"]) == 1
        assert result["preferences"][0]["subject"] == "報告形式"
        assert result["preferences"][0]["preference"] == "箇条書き"

    def test_build_context_additions_fact(
        self, mock_repository, sample_fact_learning
    ):
        """Build context additions for fact"""
        applier = LearningApplier("org_test", repository=mock_repository)
        applied = AppliedLearning(learning=sample_fact_learning)

        result = applier.build_context_additions([applied])

        assert len(result["facts"]) == 1
        assert result["facts"][0]["subject"] == "会議室"
        assert result["facts"][0]["value"] == "3階のA会議室"

    def test_build_context_additions_rule(
        self, mock_repository, sample_ceo_rule_learning
    ):
        """Build context additions for rule"""
        applier = LearningApplier("org_test", repository=mock_repository)
        applied = AppliedLearning(learning=sample_ceo_rule_learning)

        result = applier.build_context_additions([applied])

        assert len(result["rules"]) == 1
        assert result["rules"][0]["condition"] == "常に"
        assert result["rules"][0]["action"] == "人の可能性を信じる"
        assert result["rules"][0]["authority"] == AuthorityLevel.CEO.value

    def test_build_context_additions_correction(
        self, mock_repository, sample_correction_learning
    ):
        """Build context additions for correction"""
        applier = LearningApplier("org_test", repository=mock_repository)
        applied = AppliedLearning(learning=sample_correction_learning)

        result = applier.build_context_additions([applied])

        assert len(result["corrections"]) == 1
        assert result["corrections"][0]["wrong_pattern"] == "田中"
        assert result["corrections"][0]["correct_pattern"] == "佐藤"

    def test_build_context_additions_context(
        self, mock_repository, sample_context_learning
    ):
        """Build context additions for context"""
        applier = LearningApplier("org_test", repository=mock_repository)
        applied = AppliedLearning(learning=sample_context_learning)

        result = applier.build_context_additions([applied])

        assert len(result["contexts"]) == 1
        assert result["contexts"][0]["subject"] == "決算期"
        assert result["contexts"][0]["context"] == "今月は決算期"

    def test_build_context_additions_relationship(
        self, mock_repository, sample_relationship_learning
    ):
        """Build context additions for relationship"""
        applier = LearningApplier("org_test", repository=mock_repository)
        applied = AppliedLearning(learning=sample_relationship_learning)

        result = applier.build_context_additions([applied])

        assert len(result["relationships"]) == 1
        assert result["relationships"][0]["person1"] == "田中"
        assert result["relationships"][0]["person2"] == "佐藤"
        assert result["relationships"][0]["relationship"] == "同期"

    def test_build_context_additions_procedure(
        self, mock_repository, sample_procedure_learning
    ):
        """Build context additions for procedure"""
        applier = LearningApplier("org_test", repository=mock_repository)
        applied = AppliedLearning(learning=sample_procedure_learning)

        result = applier.build_context_additions([applied])

        assert len(result["procedures"]) == 1
        assert result["procedures"][0]["task"] == "経費精算"
        assert result["procedures"][0]["steps"] == ["申請書作成", "上長承認", "経理提出"]

    def test_build_context_additions_multiple_categories(
        self, mock_repository, sample_alias_learning, sample_ceo_rule_learning
    ):
        """Build context additions for multiple categories"""
        applier = LearningApplier("org_test", repository=mock_repository)
        applied1 = AppliedLearning(learning=sample_alias_learning)
        applied2 = AppliedLearning(learning=sample_ceo_rule_learning)

        result = applier.build_context_additions([applied1, applied2])

        assert len(result["aliases"]) == 1
        assert len(result["rules"]) == 1


# =============================================================================
# LearningApplier Tests - build_prompt_instructions
# =============================================================================

class TestLearningApplierBuildPromptInstructions:
    """Tests for build_prompt_instructions method"""

    def test_build_prompt_instructions_empty(self, mock_repository):
        """Build prompt instructions with empty additions"""
        applier = LearningApplier("org_test", repository=mock_repository)

        result = applier.build_prompt_instructions({})

        assert result == ""

    def test_build_prompt_instructions_with_aliases(self, mock_repository):
        """Build prompt instructions with aliases"""
        applier = LearningApplier("org_test", repository=mock_repository)
        additions = {
            "aliases": [
                {"from": "mtg", "to": "ミーティング", "description": "", "taught_by": "田中さん"}
            ],
            "preferences": [],
            "facts": [],
            "rules": [],
            "corrections": [],
            "contexts": [],
            "relationships": [],
            "procedures": [],
        }

        result = applier.build_prompt_instructions(additions)

        assert "覚えている別名" in result
        assert "mtg" in result
        assert "ミーティング" in result
        assert "田中さん" in result

    def test_build_prompt_instructions_with_preferences(self, mock_repository):
        """Build prompt instructions with preferences"""
        applier = LearningApplier("org_test", repository=mock_repository)
        additions = {
            "aliases": [],
            "preferences": [{"description": "箇条書きで報告してほしい"}],
            "facts": [],
            "rules": [],
            "corrections": [],
            "contexts": [],
            "relationships": [],
            "procedures": [],
        }

        result = applier.build_prompt_instructions(additions)

        assert "ユーザーの好み" in result
        assert "箇条書き" in result

    def test_build_prompt_instructions_with_facts(self, mock_repository):
        """Build prompt instructions with facts"""
        applier = LearningApplier("org_test", repository=mock_repository)
        additions = {
            "aliases": [],
            "preferences": [],
            "facts": [{"description": "定例会議は3階のA会議室で行う"}],
            "rules": [],
            "corrections": [],
            "contexts": [],
            "relationships": [],
            "procedures": [],
        }

        result = applier.build_prompt_instructions(additions)

        assert "覚えている事実" in result
        assert "会議室" in result

    def test_build_prompt_instructions_with_rules(self, mock_repository):
        """Build prompt instructions with rules"""
        applier = LearningApplier("org_test", repository=mock_repository)
        additions = {
            "aliases": [],
            "preferences": [],
            "facts": [],
            "rules": [
                {
                    "description": "人の可能性を信じる",
                    "priority": "high",
                    "authority": "ceo",
                }
            ],
            "corrections": [],
            "contexts": [],
            "relationships": [],
            "procedures": [],
        }

        result = applier.build_prompt_instructions(additions)

        assert "守るべきルール" in result
        assert "人の可能性を信じる" in result
        assert "重要" in result
        assert "CEO教え" in result

    def test_build_prompt_instructions_with_corrections(self, mock_repository):
        """Build prompt instructions with corrections"""
        applier = LearningApplier("org_test", repository=mock_repository)
        additions = {
            "aliases": [],
            "preferences": [],
            "facts": [],
            "rules": [],
            "corrections": [{"description": "田中→佐藤に修正"}],
            "contexts": [],
            "relationships": [],
            "procedures": [],
        }

        result = applier.build_prompt_instructions(additions)

        assert "修正すべきパターン" in result
        assert "田中" in result

    def test_build_prompt_instructions_with_contexts(self, mock_repository):
        """Build prompt instructions with contexts"""
        applier = LearningApplier("org_test", repository=mock_repository)
        additions = {
            "aliases": [],
            "preferences": [],
            "facts": [],
            "rules": [],
            "corrections": [],
            "contexts": [{"description": "今月は決算期なので忙しい"}],
            "relationships": [],
            "procedures": [],
        }

        result = applier.build_prompt_instructions(additions)

        assert "現在の文脈" in result
        assert "決算期" in result

    def test_build_prompt_instructions_with_relationships(self, mock_repository):
        """Build prompt instructions with relationships"""
        applier = LearningApplier("org_test", repository=mock_repository)
        additions = {
            "aliases": [],
            "preferences": [],
            "facts": [],
            "rules": [],
            "corrections": [],
            "contexts": [],
            "relationships": [{"description": "田中と佐藤は同期入社"}],
            "procedures": [],
        }

        result = applier.build_prompt_instructions(additions)

        assert "人間関係" in result
        assert "同期" in result

    def test_build_prompt_instructions_with_procedures(self, mock_repository):
        """Build prompt instructions with procedures"""
        applier = LearningApplier("org_test", repository=mock_repository)
        additions = {
            "aliases": [],
            "preferences": [],
            "facts": [],
            "rules": [],
            "corrections": [],
            "contexts": [],
            "relationships": [],
            "procedures": [{"description": "経費精算は申請書を作成し上長承認後に経理に提出"}],
        }

        result = applier.build_prompt_instructions(additions)

        assert "覚えている手順" in result
        assert "経費精算" in result

    def test_build_prompt_instructions_multiple_sections(self, mock_repository):
        """Build prompt instructions with multiple sections"""
        applier = LearningApplier("org_test", repository=mock_repository)
        additions = {
            "aliases": [{"from": "mtg", "to": "ミーティング", "description": "", "taught_by": None}],
            "preferences": [{"description": "箇条書きで報告"}],
            "facts": [],
            "rules": [{"description": "ルール", "priority": "medium", "authority": "user"}],
            "corrections": [],
            "contexts": [],
            "relationships": [],
            "procedures": [],
        }

        result = applier.build_prompt_instructions(additions)

        assert "覚えている別名" in result
        assert "ユーザーの好み" in result
        assert "守るべきルール" in result
        # Sections should be separated by double newlines
        assert "\n\n" in result


# =============================================================================
# LearningApplier Tests - record_feedback
# =============================================================================

class TestLearningApplierRecordFeedback:
    """Tests for record_feedback method"""

    def test_record_feedback_positive(self, mock_conn, mock_repository):
        """Record positive feedback"""
        applier = LearningApplier("org_test", repository=mock_repository)

        result = applier.record_feedback(mock_conn, "learning-id", is_positive=True)

        assert result is True
        mock_repository.update_feedback_count.assert_called_once_with(
            mock_conn, "learning-id", True
        )

    def test_record_feedback_negative(self, mock_conn, mock_repository):
        """Record negative feedback"""
        applier = LearningApplier("org_test", repository=mock_repository)

        result = applier.record_feedback(mock_conn, "learning-id", is_positive=False)

        assert result is True
        mock_repository.update_feedback_count.assert_called_once_with(
            mock_conn, "learning-id", False
        )

    def test_record_feedback_with_log_id(self, mock_conn, mock_repository):
        """Record feedback with log ID"""
        applier = LearningApplier("org_test", repository=mock_repository)

        result = applier.record_feedback(
            mock_conn, "learning-id", is_positive=True, log_id="log-id"
        )

        assert result is True
        mock_repository.update_log_feedback.assert_called_once_with(
            mock_conn, "log-id", "positive"
        )

    def test_record_feedback_negative_with_log_id(self, mock_conn, mock_repository):
        """Record negative feedback with log ID"""
        applier = LearningApplier("org_test", repository=mock_repository)

        result = applier.record_feedback(
            mock_conn, "learning-id", is_positive=False, log_id="log-id"
        )

        mock_repository.update_log_feedback.assert_called_once_with(
            mock_conn, "log-id", "negative"
        )

    def test_record_feedback_without_log_id(self, mock_conn, mock_repository):
        """Record feedback without log ID does not call update_log_feedback"""
        applier = LearningApplier("org_test", repository=mock_repository)

        applier.record_feedback(mock_conn, "learning-id", is_positive=True)

        mock_repository.update_log_feedback.assert_not_called()

    def test_record_feedback_returns_false_on_failure(self, mock_conn, mock_repository):
        """Record feedback returns False when repository fails"""
        mock_repository.update_feedback_count.return_value = False
        applier = LearningApplier("org_test", repository=mock_repository)

        result = applier.record_feedback(mock_conn, "learning-id", is_positive=True)

        assert result is False


# =============================================================================
# LearningApplier Tests - _generate_modification
# =============================================================================

class TestLearningApplierGenerateModification:
    """Tests for _generate_modification method"""

    def test_generate_modification_alias(self, mock_repository, sample_alias_learning):
        """Generate modification for alias learning"""
        applier = LearningApplier("org_test", repository=mock_repository)

        result = applier._generate_modification(
            sample_alias_learning, "今日のmtgは何時から？"
        )

        assert result == "今日のミーティングは何時から？"

    def test_generate_modification_alias_case_insensitive(self, mock_repository):
        """Generate modification for alias is case insensitive"""
        applier = LearningApplier("org_test", repository=mock_repository)
        learning = Learning(
            category=LearningCategory.ALIAS.value,
            learned_content={"from": "MTG", "to": "ミーティング"},
        )

        result = applier._generate_modification(learning, "今日のmtgは何時？")

        assert result == "今日のミーティングは何時？"

    def test_generate_modification_alias_no_match(self, mock_repository):
        """Generate modification for alias with no match returns None"""
        applier = LearningApplier("org_test", repository=mock_repository)
        learning = Learning(
            category=LearningCategory.ALIAS.value,
            learned_content={"from": "mtg", "to": "ミーティング"},
        )

        result = applier._generate_modification(learning, "今日の会議は何時？")

        assert result is None

    def test_generate_modification_correction(
        self, mock_repository, sample_correction_learning
    ):
        """Generate modification for correction learning"""
        applier = LearningApplier("org_test", repository=mock_repository)

        result = applier._generate_modification(
            sample_correction_learning, "田中さんに連絡してください"
        )

        assert result == "佐藤さんに連絡してください"

    def test_generate_modification_correction_case_insensitive(self, mock_repository):
        """Generate modification for correction is case insensitive"""
        applier = LearningApplier("org_test", repository=mock_repository)
        learning = Learning(
            category=LearningCategory.CORRECTION.value,
            learned_content={"wrong_pattern": "ABC", "correct_pattern": "XYZ"},
        )

        result = applier._generate_modification(learning, "abc is correct")

        assert result == "XYZ is correct"

    def test_generate_modification_correction_no_match(self, mock_repository):
        """Generate modification for correction with no match returns None"""
        applier = LearningApplier("org_test", repository=mock_repository)
        learning = Learning(
            category=LearningCategory.CORRECTION.value,
            learned_content={"wrong_pattern": "田中", "correct_pattern": "佐藤"},
        )

        result = applier._generate_modification(learning, "山田さんに連絡")

        assert result is None

    def test_generate_modification_other_category_returns_none(
        self, mock_repository, sample_ceo_rule_learning
    ):
        """Generate modification for other categories returns None"""
        applier = LearningApplier("org_test", repository=mock_repository)

        result = applier._generate_modification(
            sample_ceo_rule_learning, "test message"
        )

        assert result is None

    def test_generate_modification_empty_from_value(self, mock_repository):
        """Generate modification with empty from value returns None"""
        applier = LearningApplier("org_test", repository=mock_repository)
        learning = Learning(
            category=LearningCategory.ALIAS.value,
            learned_content={"from": "", "to": "something"},
        )

        result = applier._generate_modification(learning, "test message")

        assert result is None


# =============================================================================
# LearningApplier Tests - _generate_mention_text
# =============================================================================

class TestLearningApplierGenerateMentionText:
    """Tests for _generate_mention_text method

    Note: applier.py uses learning.applied_count but the Learning model
    has applied_count. We add applied_count as an attribute for testing.
    """

    def test_generate_mention_text_alias_first_use(self, mock_repository):
        """Generate mention text for alias first use"""
        applier = LearningApplier("org_test", repository=mock_repository)
        learning = Learning(
            category=LearningCategory.ALIAS.value,
            learned_content={"from": "mtg", "to": "ミーティング"},
            taught_by_name="田中さん",
        )
        learning.applied_count = 0  # First use (applier uses applied_count, not applied_count)

        result = applier._generate_mention_text(learning)

        assert result is not None
        assert "ミーティング" in result
        assert "田中さん" in result
        assert "mtg" in result

    def test_generate_mention_text_alias_not_first_use(self, mock_repository):
        """Generate mention text for alias not first use returns None"""
        applier = LearningApplier("org_test", repository=mock_repository)
        learning = Learning(
            category=LearningCategory.ALIAS.value,
            learned_content={"from": "mtg", "to": "ミーティング"},
            taught_by_name="田中さん",
        )
        learning.applied_count = 5  # Not first use

        result = applier._generate_mention_text(learning)

        assert result is None

    def test_generate_mention_text_alias_first_use_applied_count_one(self, mock_repository):
        """Generate mention text for alias when applied_count is 1"""
        applier = LearningApplier("org_test", repository=mock_repository)
        learning = Learning(
            category=LearningCategory.ALIAS.value,
            learned_content={"from": "mtg", "to": "ミーティング"},
            taught_by_name="田中さん",
        )
        learning.applied_count = 1  # First use (applied_count <= 1)

        result = applier._generate_mention_text(learning)

        assert result is not None

    def test_generate_mention_text_alias_no_teacher_name(self, mock_repository):
        """Generate mention text for alias without teacher name"""
        applier = LearningApplier("org_test", repository=mock_repository)
        learning = Learning(
            category=LearningCategory.ALIAS.value,
            learned_content={"from": "mtg", "to": "ミーティング"},
            taught_by_name=None,
        )
        learning.applied_count = 0

        result = applier._generate_mention_text(learning)

        assert result is not None
        assert "誰か" in result  # Default teacher name

    def test_generate_mention_text_rule(self, mock_repository):
        """Generate mention text for rule learning"""
        applier = LearningApplier("org_test", repository=mock_repository)
        learning = Learning(
            category=LearningCategory.RULE.value,
            learned_content={
                "description": "人の可能性を信じる",
                "action": "ポジティブに対応する",
            },
        )
        learning.applied_count = 0

        result = applier._generate_mention_text(learning)

        # Should generate rule applied text
        assert result is not None
        assert "ルール" in result or "人の可能性" in result

    def test_generate_mention_text_other_category(
        self, mock_repository, sample_fact_learning
    ):
        """Generate mention text for other categories returns None"""
        applier = LearningApplier("org_test", repository=mock_repository)

        result = applier._generate_mention_text(sample_fact_learning)

        assert result is None


# =============================================================================
# LearningApplierWithCeoCheck Tests
# =============================================================================

class TestLearningApplierWithCeoCheckInit:
    """Tests for LearningApplierWithCeoCheck initialization"""

    def test_init_with_organization_id(self):
        """Initialize with organization ID"""
        applier = LearningApplierWithCeoCheck("org_test")
        assert applier.organization_id == "org_test"
        assert applier.ceo_teachings_fetcher is None

    def test_init_with_ceo_teachings_fetcher(self, mock_repository):
        """Initialize with CEO teachings fetcher"""
        fetcher = Mock(return_value=[])
        applier = LearningApplierWithCeoCheck(
            "org_test",
            repository=mock_repository,
            ceo_teachings_fetcher=fetcher,
        )
        assert applier.ceo_teachings_fetcher is fetcher


class TestLearningApplierWithCeoCheckFindApplicable:
    """Tests for find_applicable_with_ceo_check method"""

    def test_find_applicable_with_ceo_check_no_ceo_learnings(
        self, mock_conn, mock_repository, sample_alias_learning
    ):
        """Find applicable with CEO check when no CEO learnings"""
        mock_repository.find_applicable.return_value = [sample_alias_learning]
        applier = LearningApplierWithCeoCheck("org_test", repository=mock_repository)

        learnings, ceo_learnings = applier.find_applicable_with_ceo_check(
            mock_conn, "test message"
        )

        assert len(learnings) == 1
        assert len(ceo_learnings) == 0

    def test_find_applicable_with_ceo_check_has_ceo_learnings(
        self, mock_conn, mock_repository, sample_alias_learning, sample_ceo_rule_learning
    ):
        """Find applicable with CEO check when CEO learnings present"""
        mock_repository.find_applicable.return_value = [
            sample_alias_learning,
            sample_ceo_rule_learning,
        ]
        applier = LearningApplierWithCeoCheck("org_test", repository=mock_repository)

        learnings, ceo_learnings = applier.find_applicable_with_ceo_check(
            mock_conn, "test message"
        )

        assert len(ceo_learnings) == 1
        assert ceo_learnings[0] == sample_ceo_rule_learning
        # Non-CEO learnings plus CEO learnings
        assert sample_ceo_rule_learning in learnings

    def test_find_applicable_with_ceo_check_filters_conflicting(
        self, mock_conn, mock_repository
    ):
        """Find applicable with CEO check filters conflicting learnings"""
        # CEO learning
        ceo_learning = Learning(
            id="ceo-learning",
            category=LearningCategory.RULE.value,
            trigger_value="test",
            authority_level=AuthorityLevel.CEO.value,
            learned_content={"condition": "test", "action": "ceo action"},
        )
        # User learning that conflicts with CEO
        user_learning = Learning(
            id="user-learning",
            category=LearningCategory.RULE.value,
            trigger_value="test",
            authority_level=AuthorityLevel.USER.value,
            learned_content={"condition": "test", "action": "user action"},
        )
        # Non-conflicting learning
        non_conflicting = Learning(
            id="non-conflicting",
            category=LearningCategory.ALIAS.value,
            trigger_value="mtg",
            authority_level=AuthorityLevel.USER.value,
            learned_content={"from": "mtg", "to": "meeting"},
        )

        mock_repository.find_applicable.return_value = [
            ceo_learning,
            user_learning,
            non_conflicting,
        ]
        applier = LearningApplierWithCeoCheck("org_test", repository=mock_repository)

        learnings, ceo_learnings = applier.find_applicable_with_ceo_check(
            mock_conn, "test message"
        )

        # user_learning should be filtered out (conflicts with CEO)
        assert user_learning not in learnings
        # non_conflicting should remain
        assert non_conflicting in learnings
        # CEO learning should be present
        assert ceo_learning in learnings


class TestLearningApplierWithCeoCheckFilterConflicting:
    """Tests for _filter_conflicting_with_ceo method"""

    def test_filter_conflicting_with_ceo_no_conflicts(self, mock_repository):
        """Filter conflicting with CEO when no conflicts"""
        applier = LearningApplierWithCeoCheck("org_test", repository=mock_repository)

        ceo_learning = Learning(
            category=LearningCategory.RULE.value,
            trigger_value="test",
            learned_content={"condition": "a", "action": "x"},
        )
        user_learning = Learning(
            category=LearningCategory.ALIAS.value,
            trigger_value="other",
            learned_content={"from": "a", "to": "b"},
        )

        result = applier._filter_conflicting_with_ceo(
            [ceo_learning], [user_learning]
        )

        assert len(result) == 1
        assert result[0] == user_learning

    def test_filter_conflicting_with_ceo_with_conflicts(self, mock_repository):
        """Filter conflicting with CEO when conflicts exist"""
        applier = LearningApplierWithCeoCheck("org_test", repository=mock_repository)

        ceo_learning = Learning(
            category=LearningCategory.ALIAS.value,
            trigger_value="mtg",
            learned_content={"from": "mtg", "to": "会議"},
        )
        conflicting = Learning(
            category=LearningCategory.ALIAS.value,
            trigger_value="mtg",
            learned_content={"from": "mtg", "to": "ミーティング"},
        )
        non_conflicting = Learning(
            category=LearningCategory.ALIAS.value,
            trigger_value="pl",
            learned_content={"from": "pl", "to": "プロジェクトリーダー"},
        )

        result = applier._filter_conflicting_with_ceo(
            [ceo_learning], [conflicting, non_conflicting]
        )

        assert len(result) == 1
        assert non_conflicting in result
        assert conflicting not in result

    def test_filter_conflicting_with_ceo_empty_lists(self, mock_repository):
        """Filter conflicting with CEO with empty lists"""
        applier = LearningApplierWithCeoCheck("org_test", repository=mock_repository)

        result = applier._filter_conflicting_with_ceo([], [])
        assert result == []


class TestLearningApplierWithCeoCheckIsConflicting:
    """Tests for _is_conflicting method"""

    def test_is_conflicting_same_alias_different_to(self, mock_repository):
        """Same alias with different to values conflicts"""
        applier = LearningApplierWithCeoCheck("org_test", repository=mock_repository)

        learning1 = Learning(
            category=LearningCategory.ALIAS.value,
            trigger_value="mtg",
            learned_content={"from": "mtg", "to": "ミーティング"},
        )
        learning2 = Learning(
            category=LearningCategory.ALIAS.value,
            trigger_value="mtg",
            learned_content={"from": "mtg", "to": "会議"},
        )

        assert applier._is_conflicting(learning1, learning2) is True

    def test_is_conflicting_same_alias_same_to(self, mock_repository):
        """Same alias with same to values does not conflict"""
        applier = LearningApplierWithCeoCheck("org_test", repository=mock_repository)

        learning1 = Learning(
            category=LearningCategory.ALIAS.value,
            trigger_value="mtg",
            learned_content={"from": "mtg", "to": "ミーティング"},
        )
        learning2 = Learning(
            category=LearningCategory.ALIAS.value,
            trigger_value="mtg",
            learned_content={"from": "mtg", "to": "ミーティング"},
        )

        assert applier._is_conflicting(learning1, learning2) is False

    def test_is_conflicting_different_triggers(self, mock_repository):
        """Different triggers do not conflict"""
        applier = LearningApplierWithCeoCheck("org_test", repository=mock_repository)

        learning1 = Learning(
            category=LearningCategory.ALIAS.value,
            trigger_value="mtg",
            learned_content={"from": "mtg", "to": "ミーティング"},
        )
        learning2 = Learning(
            category=LearningCategory.ALIAS.value,
            trigger_value="pl",
            learned_content={"from": "pl", "to": "プロジェクトリーダー"},
        )

        assert applier._is_conflicting(learning1, learning2) is False

    def test_is_conflicting_different_categories(self, mock_repository):
        """Different categories do not conflict"""
        applier = LearningApplierWithCeoCheck("org_test", repository=mock_repository)

        learning1 = Learning(
            category=LearningCategory.ALIAS.value,
            trigger_value="mtg",
            learned_content={"from": "mtg", "to": "ミーティング"},
        )
        learning2 = Learning(
            category=LearningCategory.RULE.value,
            trigger_value="mtg",
            learned_content={"condition": "mtg", "action": "notify"},
        )

        assert applier._is_conflicting(learning1, learning2) is False

    def test_is_conflicting_rule_same_condition_different_action(self, mock_repository):
        """Rule with same condition but different action conflicts"""
        applier = LearningApplierWithCeoCheck("org_test", repository=mock_repository)

        learning1 = Learning(
            category=LearningCategory.RULE.value,
            trigger_value="monday",
            learned_content={"condition": "monday", "action": "action1"},
        )
        learning2 = Learning(
            category=LearningCategory.RULE.value,
            trigger_value="monday",
            learned_content={"condition": "monday", "action": "action2"},
        )

        assert applier._is_conflicting(learning1, learning2) is True

    def test_is_conflicting_rule_same_condition_same_action(self, mock_repository):
        """Rule with same condition and action does not conflict"""
        applier = LearningApplierWithCeoCheck("org_test", repository=mock_repository)

        learning1 = Learning(
            category=LearningCategory.RULE.value,
            trigger_value="monday",
            learned_content={"condition": "monday", "action": "action1"},
        )
        learning2 = Learning(
            category=LearningCategory.RULE.value,
            trigger_value="monday",
            learned_content={"condition": "monday", "action": "action1"},
        )

        assert applier._is_conflicting(learning1, learning2) is False

    def test_is_conflicting_fact_same_subject_different_value(self, mock_repository):
        """Fact with same subject but different value conflicts"""
        applier = LearningApplierWithCeoCheck("org_test", repository=mock_repository)

        learning1 = Learning(
            category=LearningCategory.FACT.value,
            trigger_value="meeting_room",
            learned_content={"subject": "meeting_room", "value": "room A"},
        )
        learning2 = Learning(
            category=LearningCategory.FACT.value,
            trigger_value="meeting_room",
            learned_content={"subject": "meeting_room", "value": "room B"},
        )

        assert applier._is_conflicting(learning1, learning2) is True

    def test_is_conflicting_fact_same_subject_same_value(self, mock_repository):
        """Fact with same subject and value does not conflict"""
        applier = LearningApplierWithCeoCheck("org_test", repository=mock_repository)

        learning1 = Learning(
            category=LearningCategory.FACT.value,
            trigger_value="meeting_room",
            learned_content={"subject": "meeting_room", "value": "room A"},
        )
        learning2 = Learning(
            category=LearningCategory.FACT.value,
            trigger_value="meeting_room",
            learned_content={"subject": "meeting_room", "value": "room A"},
        )

        assert applier._is_conflicting(learning1, learning2) is False


# =============================================================================
# Factory Function Tests
# =============================================================================

class TestFactoryFunctions:
    """Tests for factory functions"""

    def test_create_applier(self):
        """Create applier with factory function"""
        applier = create_applier("org_test")

        assert isinstance(applier, LearningApplier)
        assert applier.organization_id == "org_test"

    def test_create_applier_with_repository(self, mock_repository):
        """Create applier with custom repository"""
        applier = create_applier("org_test", repository=mock_repository)

        assert applier.repository is mock_repository

    def test_create_applier_with_ceo_check(self):
        """Create applier with CEO check"""
        applier = create_applier_with_ceo_check("org_test")

        assert isinstance(applier, LearningApplierWithCeoCheck)
        assert applier.organization_id == "org_test"

    def test_create_applier_with_ceo_check_with_fetcher(self, mock_repository):
        """Create applier with CEO check and fetcher"""
        fetcher = Mock(return_value=[])
        applier = create_applier_with_ceo_check(
            "org_test",
            repository=mock_repository,
            ceo_teachings_fetcher=fetcher,
        )

        assert applier.ceo_teachings_fetcher is fetcher


# =============================================================================
# Edge Case Tests
# =============================================================================

class TestEdgeCases:
    """Tests for edge cases"""

    def test_find_applicable_with_none_values(self, mock_conn, mock_repository):
        """Find applicable with None values"""
        mock_repository.find_applicable.return_value = []
        applier = LearningApplier("org_test", repository=mock_repository)

        result = applier.find_applicable(
            mock_conn,
            "test",
            context=None,
            user_id=None,
            room_id=None,
        )

        assert result == []

    def test_build_context_additions_missing_content_keys(self, mock_repository):
        """Build context additions handles missing content keys"""
        applier = LearningApplier("org_test", repository=mock_repository)
        learning = Learning(
            category=LearningCategory.ALIAS.value,
            learned_content={},  # Empty content
        )
        applied = AppliedLearning(learning=learning)

        result = applier.build_context_additions([applied])

        # Should not raise, and should have empty values
        assert len(result["aliases"]) == 1
        assert result["aliases"][0]["from"] == ""
        assert result["aliases"][0]["to"] == ""

    def test_generate_modification_special_regex_characters(self, mock_repository):
        """Generate modification handles special regex characters"""
        applier = LearningApplier("org_test", repository=mock_repository)
        learning = Learning(
            category=LearningCategory.ALIAS.value,
            learned_content={"from": "C++", "to": "シープラスプラス"},
        )

        result = applier._generate_modification(learning, "C++のコード")

        assert result == "シープラスプラスのコード"

    def test_generate_modification_parentheses(self, mock_repository):
        """Generate modification handles parentheses"""
        applier = LearningApplier("org_test", repository=mock_repository)
        learning = Learning(
            category=LearningCategory.ALIAS.value,
            learned_content={"from": "(株)", "to": "株式会社"},
        )

        result = applier._generate_modification(learning, "ABC(株)です")

        assert result == "ABC株式会社です"

    def test_apply_all_preserves_order(
        self, mock_conn, mock_repository, sample_alias_learning, sample_ceo_rule_learning
    ):
        """Apply all preserves order of learnings"""
        sample_alias_learning.applied_count = 0
        sample_ceo_rule_learning.applied_count = 0

        applier = LearningApplier("org_test", repository=mock_repository)

        result = applier.apply_all(
            mock_conn,
            [sample_alias_learning, sample_ceo_rule_learning],
            "test",
        )

        assert result[0].learning == sample_alias_learning
        assert result[1].learning == sample_ceo_rule_learning

    def test_select_best_learnings_unknown_authority_level(self, mock_repository):
        """Select best learnings handles unknown authority level"""
        applier = LearningApplier("org_test", repository=mock_repository)

        learning = Learning(
            id="unknown",
            category=LearningCategory.ALIAS.value,
            trigger_value="test",
            authority_level="unknown_level",  # Not in AUTHORITY_PRIORITY
            learned_content={"from": "test", "to": "テスト"},
        )

        result = applier._select_best_learnings([learning], "test")

        assert len(result) == 1
        assert result[0] == learning
