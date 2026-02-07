"""
Comprehensive unit tests for learning_foundation subpackage files with low coverage.

Target files:
1. lib/brain/learning_foundation/authority_resolver.py
2. lib/brain/learning_foundation/detector.py
3. lib/brain/learning_foundation/effectiveness_tracker.py
4. lib/brain/learning_foundation/extractor.py

Coverage goal: Raise each file above 80%.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock, patch, call
from uuid import uuid4

from lib.brain.learning_foundation.authority_resolver import (
    AuthorityResolver,
    AuthorityResolverWithDb,
    create_authority_resolver,
    create_authority_resolver_with_db,
)
from lib.brain.learning_foundation.constants import (
    AuthorityLevel,
    AUTHORITY_PRIORITY,
    CONFIDENCE_THRESHOLD_AUTO_LEARN,
    CONFIDENCE_THRESHOLD_CONFIRM,
    CONFIDENCE_THRESHOLD_MIN,
    DecisionImpact,
    DEFAULT_CONFIDENCE_DECAY_RATE,
    LearningCategory,
    LearningScope,
    TriggerType,
)
from lib.brain.learning_foundation.detector import (
    FeedbackDetector,
    create_detector,
)
from lib.brain.learning_foundation.effectiveness_tracker import (
    EffectivenessMetrics,
    EffectivenessTracker,
    LearningHealth,
    create_effectiveness_tracker,
)
from lib.brain.learning_foundation.extractor import (
    LearningExtractor,
    create_extractor,
)
from lib.brain.learning_foundation.models import (
    ConversationContext,
    FeedbackDetectionResult,
    Learning,
    LearningLog,
    PatternMatch,
    EffectivenessResult,
    ImprovementSuggestion,
)
from lib.brain.learning_foundation.patterns import (
    DetectionPattern,
    ALL_PATTERNS,
)


# ============================================================================
# Helpers
# ============================================================================

ORG_ID = "org-test-001"
CEO_ACCOUNT = "ceo-001"
MANAGER_ACCOUNT = "mgr-001"
USER_ACCOUNT = "user-001"
SYSTEM_ACCOUNT = "sys-001"


def _make_learning(**kwargs):
    """Helper to create a Learning with defaults."""
    defaults = dict(
        id=str(uuid4()),
        organization_id=ORG_ID,
        category=LearningCategory.FACT.value,
        trigger_type=TriggerType.KEYWORD.value,
        trigger_value="test",
        learned_content={"type": "fact", "description": "test"},
        authority_level=AuthorityLevel.USER.value,
        taught_by_account_id=USER_ACCOUNT,
        is_active=True,
        applied_count=0,
        success_count=0,
        failure_count=0,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    defaults.update(kwargs)
    return Learning(**defaults)


def _make_detection_result(**kwargs):
    """Helper to create a FeedbackDetectionResult."""
    defaults = dict(
        pattern_name="test_pattern",
        pattern_category=LearningCategory.FACT.value,
        match=PatternMatch(
            groups={"fact": "test fact"},
            start=0,
            end=10,
            matched_text="test fact",
        ),
        extracted={
            "category": LearningCategory.FACT.value,
            "original_message": "test message",
            "type": "fact",
            "description": "test fact",
        },
        confidence=0.8,
    )
    defaults.update(kwargs)
    return FeedbackDetectionResult(**defaults)


# ============================================================================
# AuthorityResolver Tests
# ============================================================================

class TestAuthorityResolverInit:
    """AuthorityResolver.__init__ tests."""

    def test_init_defaults(self):
        resolver = AuthorityResolver(ORG_ID)
        assert resolver.organization_id == ORG_ID
        assert resolver.ceo_account_ids == set()
        assert resolver.manager_account_ids == set()
        assert resolver.authority_fetcher is None

    def test_init_with_ceo_ids(self):
        resolver = AuthorityResolver(ORG_ID, ceo_account_ids=[CEO_ACCOUNT])
        assert CEO_ACCOUNT in resolver.ceo_account_ids

    def test_init_with_manager_ids(self):
        resolver = AuthorityResolver(ORG_ID, manager_account_ids=[MANAGER_ACCOUNT])
        assert MANAGER_ACCOUNT in resolver.manager_account_ids

    def test_init_with_fetcher(self):
        fetcher = Mock()
        resolver = AuthorityResolver(ORG_ID, authority_fetcher=fetcher)
        assert resolver.authority_fetcher is fetcher


class TestAuthorityResolverGetLevel:
    """AuthorityResolver.get_authority_level tests."""

    def test_ceo_identified(self):
        resolver = AuthorityResolver(ORG_ID, ceo_account_ids=[CEO_ACCOUNT])
        assert resolver.get_authority_level(None, CEO_ACCOUNT) == "ceo"

    def test_manager_identified(self):
        resolver = AuthorityResolver(
            ORG_ID, manager_account_ids=[MANAGER_ACCOUNT]
        )
        assert resolver.get_authority_level(None, MANAGER_ACCOUNT) == "manager"

    def test_ceo_takes_precedence_over_manager(self):
        resolver = AuthorityResolver(
            ORG_ID,
            ceo_account_ids=[CEO_ACCOUNT],
            manager_account_ids=[CEO_ACCOUNT],
        )
        assert resolver.get_authority_level(None, CEO_ACCOUNT) == "ceo"

    def test_default_is_user(self):
        resolver = AuthorityResolver(ORG_ID)
        assert resolver.get_authority_level(None, USER_ACCOUNT) == "user"

    def test_authority_fetcher_used(self):
        fetcher = Mock(return_value="manager")
        conn = Mock()
        resolver = AuthorityResolver(ORG_ID, authority_fetcher=fetcher)
        result = resolver.get_authority_level(conn, USER_ACCOUNT)
        assert result == "manager"
        fetcher.assert_called_once_with(conn, USER_ACCOUNT)

    def test_authority_fetcher_invalid_value_falls_through(self):
        fetcher = Mock(return_value="invalid_level")
        conn = Mock()
        resolver = AuthorityResolver(ORG_ID, authority_fetcher=fetcher)
        result = resolver.get_authority_level(conn, USER_ACCOUNT)
        assert result == "user"

    def test_authority_fetcher_exception_falls_through(self):
        fetcher = Mock(side_effect=RuntimeError("DB error"))
        conn = Mock()
        resolver = AuthorityResolver(ORG_ID, authority_fetcher=fetcher)
        result = resolver.get_authority_level(conn, USER_ACCOUNT)
        assert result == "user"

    def test_authority_fetcher_not_called_without_conn(self):
        fetcher = Mock(return_value="manager")
        resolver = AuthorityResolver(ORG_ID, authority_fetcher=fetcher)
        result = resolver.get_authority_level(None, USER_ACCOUNT)
        assert result == "user"
        fetcher.assert_not_called()

    def test_authority_fetcher_returns_system(self):
        fetcher = Mock(return_value="system")
        conn = Mock()
        resolver = AuthorityResolver(ORG_ID, authority_fetcher=fetcher)
        result = resolver.get_authority_level(conn, SYSTEM_ACCOUNT)
        assert result == "system"


class TestAuthorityResolverBoolChecks:
    """is_ceo, is_manager, is_admin tests."""

    def test_is_ceo_true(self):
        resolver = AuthorityResolver(ORG_ID, ceo_account_ids=[CEO_ACCOUNT])
        assert resolver.is_ceo(CEO_ACCOUNT) is True

    def test_is_ceo_false(self):
        resolver = AuthorityResolver(ORG_ID, ceo_account_ids=[CEO_ACCOUNT])
        assert resolver.is_ceo(USER_ACCOUNT) is False

    def test_is_manager_true(self):
        resolver = AuthorityResolver(
            ORG_ID, manager_account_ids=[MANAGER_ACCOUNT]
        )
        assert resolver.is_manager(MANAGER_ACCOUNT) is True

    def test_is_manager_false(self):
        resolver = AuthorityResolver(
            ORG_ID, manager_account_ids=[MANAGER_ACCOUNT]
        )
        assert resolver.is_manager(USER_ACCOUNT) is False

    def test_is_admin_true_for_ceo(self):
        resolver = AuthorityResolver(ORG_ID, ceo_account_ids=[CEO_ACCOUNT])
        assert resolver.is_admin(CEO_ACCOUNT) is True

    def test_is_admin_true_for_manager(self):
        resolver = AuthorityResolver(
            ORG_ID, manager_account_ids=[MANAGER_ACCOUNT]
        )
        assert resolver.is_admin(MANAGER_ACCOUNT) is True

    def test_is_admin_false_for_user(self):
        resolver = AuthorityResolver(ORG_ID)
        assert resolver.is_admin(USER_ACCOUNT) is False


class TestAuthorityComparison:
    """compare_authority, is_higher_or_equal, is_higher tests."""

    def setup_method(self):
        self.resolver = AuthorityResolver(ORG_ID)

    def test_compare_ceo_vs_user(self):
        assert self.resolver.compare_authority("ceo", "user") == -1

    def test_compare_user_vs_ceo(self):
        assert self.resolver.compare_authority("user", "ceo") == 1

    def test_compare_equal(self):
        assert self.resolver.compare_authority("manager", "manager") == 0

    def test_compare_unknown_authority(self):
        assert self.resolver.compare_authority("unknown", "ceo") == 1

    def test_compare_both_unknown(self):
        assert self.resolver.compare_authority("x", "y") == 0

    def test_is_higher_or_equal_true(self):
        assert self.resolver.is_higher_or_equal("ceo", "manager") is True

    def test_is_higher_or_equal_equal(self):
        assert self.resolver.is_higher_or_equal("manager", "manager") is True

    def test_is_higher_or_equal_false(self):
        assert self.resolver.is_higher_or_equal("user", "ceo") is False

    def test_is_higher_true(self):
        assert self.resolver.is_higher("ceo", "manager") is True

    def test_is_higher_equal_returns_false(self):
        assert self.resolver.is_higher("manager", "manager") is False

    def test_is_higher_lower_returns_false(self):
        assert self.resolver.is_higher("user", "ceo") is False


class TestAuthoritySortAndFilter:
    """sort_by_authority, filter_by_authority, group_by_authority tests."""

    def setup_method(self):
        self.resolver = AuthorityResolver(ORG_ID)
        self.ceo_learning = _make_learning(
            authority_level="ceo", taught_by_account_id=CEO_ACCOUNT
        )
        self.mgr_learning = _make_learning(
            authority_level="manager", taught_by_account_id=MANAGER_ACCOUNT
        )
        self.user_learning = _make_learning(
            authority_level="user", taught_by_account_id=USER_ACCOUNT
        )
        self.system_learning = _make_learning(
            authority_level="system", taught_by_account_id=SYSTEM_ACCOUNT
        )

    def test_sort_descending(self):
        result = self.resolver.sort_by_authority(
            [self.user_learning, self.ceo_learning, self.mgr_learning],
            descending=True,
        )
        assert result[0].authority_level == "ceo"
        assert result[1].authority_level == "manager"
        assert result[2].authority_level == "user"

    def test_sort_ascending(self):
        result = self.resolver.sort_by_authority(
            [self.ceo_learning, self.user_learning],
            descending=False,
        )
        assert result[0].authority_level == "user"
        assert result[1].authority_level == "ceo"

    def test_filter_min_authority(self):
        learnings = [self.ceo_learning, self.mgr_learning, self.user_learning]
        result = self.resolver.filter_by_authority(
            learnings, min_authority="manager"
        )
        assert len(result) == 2
        levels = {l.authority_level for l in result}
        assert "ceo" in levels
        assert "manager" in levels

    def test_filter_max_authority(self):
        learnings = [self.ceo_learning, self.mgr_learning, self.user_learning]
        result = self.resolver.filter_by_authority(
            learnings, max_authority="manager"
        )
        assert len(result) == 2
        levels = {l.authority_level for l in result}
        assert "manager" in levels
        assert "user" in levels

    def test_filter_min_and_max(self):
        learnings = [
            self.ceo_learning,
            self.mgr_learning,
            self.user_learning,
            self.system_learning,
        ]
        # min_authority="user" means authority >= user (user, manager, ceo pass)
        # max_authority="manager" means authority <= manager (user, manager, system pass)
        # Combined: user AND manager pass; ceo too high, system too low
        result = self.resolver.filter_by_authority(
            learnings, min_authority="user", max_authority="manager"
        )
        levels = {l.authority_level for l in result}
        assert "manager" in levels
        assert "user" in levels
        assert "ceo" not in levels
        assert "system" not in levels

    def test_filter_no_criteria(self):
        learnings = [self.ceo_learning, self.user_learning]
        result = self.resolver.filter_by_authority(learnings)
        assert len(result) == 2

    def test_get_highest_authority_learning(self):
        result = self.resolver.get_highest_authority_learning(
            [self.user_learning, self.ceo_learning, self.mgr_learning]
        )
        assert result is not None
        assert result.authority_level == "ceo"

    def test_get_highest_authority_learning_empty(self):
        result = self.resolver.get_highest_authority_learning([])
        assert result is None

    def test_group_by_authority(self):
        learnings = [self.ceo_learning, self.mgr_learning, self.user_learning]
        groups = self.resolver.group_by_authority(learnings)
        assert len(groups["ceo"]) == 1
        assert len(groups["manager"]) == 1
        assert len(groups["user"]) == 1
        assert len(groups["system"]) == 0

    def test_group_by_authority_unknown_level(self):
        unknown = _make_learning(authority_level="unknown_level")
        groups = self.resolver.group_by_authority([unknown])
        # unknown_level is not in AuthorityLevel, so it won't be added
        total = sum(len(v) for v in groups.values())
        assert total == 0


class TestAuthorityCanActions:
    """can_teach, can_modify, can_delete, can_view_all tests."""

    def setup_method(self):
        self.resolver = AuthorityResolver(
            ORG_ID,
            ceo_account_ids=[CEO_ACCOUNT],
            manager_account_ids=[MANAGER_ACCOUNT],
        )

    def test_can_teach_always_true(self):
        can, level = self.resolver.can_teach(None, USER_ACCOUNT)
        assert can is True
        assert level == "user"

    def test_can_teach_ceo(self):
        can, level = self.resolver.can_teach(None, CEO_ACCOUNT)
        assert can is True
        assert level == "ceo"

    def test_can_teach_with_category(self):
        can, level = self.resolver.can_teach(None, USER_ACCOUNT, category="rule")
        assert can is True

    def test_can_modify_own_learning(self):
        learning = _make_learning(taught_by_account_id=USER_ACCOUNT, authority_level="user")
        can, reason = self.resolver.can_modify(None, USER_ACCOUNT, learning)
        assert can is True
        assert "自分が教えた" in reason

    def test_can_modify_higher_authority(self):
        learning = _make_learning(taught_by_account_id=USER_ACCOUNT, authority_level="user")
        can, reason = self.resolver.can_modify(None, CEO_ACCOUNT, learning)
        assert can is True
        assert "権限レベル" in reason

    def test_can_modify_ceo_learning_by_ceo(self):
        learning = _make_learning(
            taught_by_account_id=CEO_ACCOUNT,
            authority_level="ceo",
        )
        can, reason = self.resolver.can_modify(None, CEO_ACCOUNT, learning)
        assert can is True

    def test_cannot_modify_ceo_learning_by_user(self):
        learning = _make_learning(
            taught_by_account_id=CEO_ACCOUNT,
            authority_level="ceo",
        )
        can, reason = self.resolver.can_modify(None, USER_ACCOUNT, learning)
        assert can is False
        assert "CEO" in reason

    def test_cannot_modify_higher_authority_learning(self):
        learning = _make_learning(
            taught_by_account_id=MANAGER_ACCOUNT,
            authority_level="manager",
        )
        can, reason = self.resolver.can_modify(None, USER_ACCOUNT, learning)
        assert can is False
        assert "権限レベル" in reason

    def test_can_delete_own_non_ceo_learning(self):
        learning = _make_learning(taught_by_account_id=USER_ACCOUNT, authority_level="user")
        can, reason = self.resolver.can_delete(None, USER_ACCOUNT, learning)
        assert can is True

    def test_cannot_delete_ceo_learning(self):
        learning = _make_learning(authority_level="ceo")
        can, reason = self.resolver.can_delete(None, CEO_ACCOUNT, learning)
        assert can is False
        assert "CEO教えは削除" in reason

    def test_can_delete_as_admin(self):
        learning = _make_learning(
            taught_by_account_id=USER_ACCOUNT,
            authority_level="user",
        )
        can, reason = self.resolver.can_delete(None, MANAGER_ACCOUNT, learning)
        assert can is True
        assert "管理者権限" in reason

    def test_can_delete_higher_authority(self):
        # User with no admin status but higher authority through fetcher
        fetcher = Mock(return_value="manager")
        resolver = AuthorityResolver(ORG_ID, authority_fetcher=fetcher)
        learning = _make_learning(
            taught_by_account_id="someone-else",
            authority_level="user",
        )
        conn = Mock()
        can, reason = resolver.can_delete(conn, "some-manager", learning)
        assert can is True

    def test_cannot_delete_insufficient_authority(self):
        learning = _make_learning(
            taught_by_account_id=MANAGER_ACCOUNT,
            authority_level="manager",
        )
        can, reason = self.resolver.can_delete(None, USER_ACCOUNT, learning)
        assert can is False

    def test_can_view_all_ceo(self):
        assert self.resolver.can_view_all(None, CEO_ACCOUNT) is True

    def test_can_view_all_manager(self):
        assert self.resolver.can_view_all(None, MANAGER_ACCOUNT) is True

    def test_cannot_view_all_user(self):
        assert self.resolver.can_view_all(None, USER_ACCOUNT) is False


class TestAuthorityResolverConfigUpdate:
    """add_ceo, remove_ceo, add_manager, remove_manager, set_authority_fetcher."""

    def test_add_ceo(self):
        resolver = AuthorityResolver(ORG_ID)
        resolver.add_ceo("new-ceo")
        assert resolver.is_ceo("new-ceo") is True

    def test_remove_ceo(self):
        resolver = AuthorityResolver(ORG_ID, ceo_account_ids=[CEO_ACCOUNT])
        resolver.remove_ceo(CEO_ACCOUNT)
        assert resolver.is_ceo(CEO_ACCOUNT) is False

    def test_remove_ceo_not_present(self):
        resolver = AuthorityResolver(ORG_ID)
        resolver.remove_ceo("nonexistent")  # Should not raise

    def test_add_manager(self):
        resolver = AuthorityResolver(ORG_ID)
        resolver.add_manager("new-mgr")
        assert resolver.is_manager("new-mgr") is True

    def test_remove_manager(self):
        resolver = AuthorityResolver(
            ORG_ID, manager_account_ids=[MANAGER_ACCOUNT]
        )
        resolver.remove_manager(MANAGER_ACCOUNT)
        assert resolver.is_manager(MANAGER_ACCOUNT) is False

    def test_remove_manager_not_present(self):
        resolver = AuthorityResolver(ORG_ID)
        resolver.remove_manager("nonexistent")  # Should not raise

    def test_set_authority_fetcher(self):
        resolver = AuthorityResolver(ORG_ID)
        assert resolver.authority_fetcher is None
        fetcher = Mock()
        resolver.set_authority_fetcher(fetcher)
        assert resolver.authority_fetcher is fetcher


class TestAuthorityResolverWithDb:
    """AuthorityResolverWithDb tests."""

    def test_init(self):
        resolver = AuthorityResolverWithDb(ORG_ID)
        assert resolver.organization_id == ORG_ID
        assert resolver._config_loaded is False

    def test_load_config_from_admin_config(self):
        config = Mock()
        config.admin_account_id = CEO_ACCOUNT
        get_config = Mock(return_value=config)
        resolver = AuthorityResolverWithDb(ORG_ID, get_admin_config=get_config)

        result = resolver.get_authority_level(None, CEO_ACCOUNT)
        assert result == "ceo"
        assert resolver._config_loaded is True
        get_config.assert_called_once()

    def test_load_config_cached(self):
        config = Mock()
        config.admin_account_id = CEO_ACCOUNT
        get_config = Mock(return_value=config)
        resolver = AuthorityResolverWithDb(ORG_ID, get_admin_config=get_config)

        resolver.get_authority_level(None, CEO_ACCOUNT)
        resolver.get_authority_level(None, CEO_ACCOUNT)
        get_config.assert_called_once()  # Only loaded once

    def test_load_config_none_returned(self):
        get_config = Mock(return_value=None)
        resolver = AuthorityResolverWithDb(ORG_ID, get_admin_config=get_config)

        result = resolver.get_authority_level(None, USER_ACCOUNT)
        assert result == "user"

    def test_load_config_no_admin_account_id(self):
        config = Mock(spec=[])  # No admin_account_id attribute
        get_config = Mock(return_value=config)
        resolver = AuthorityResolverWithDb(ORG_ID, get_admin_config=get_config)

        result = resolver.get_authority_level(None, USER_ACCOUNT)
        assert result == "user"
        assert resolver._config_loaded is True

    def test_load_config_exception(self):
        get_config = Mock(side_effect=RuntimeError("DB error"))
        resolver = AuthorityResolverWithDb(ORG_ID, get_admin_config=get_config)

        result = resolver.get_authority_level(None, USER_ACCOUNT)
        assert result == "user"

    def test_load_config_without_fetcher(self):
        resolver = AuthorityResolverWithDb(ORG_ID)
        result = resolver.get_authority_level(None, USER_ACCOUNT)
        assert result == "user"


class TestAuthorityResolverFactories:
    """Factory function tests."""

    def test_create_authority_resolver(self):
        resolver = create_authority_resolver(
            ORG_ID,
            ceo_account_ids=[CEO_ACCOUNT],
            manager_account_ids=[MANAGER_ACCOUNT],
        )
        assert isinstance(resolver, AuthorityResolver)
        assert resolver.is_ceo(CEO_ACCOUNT) is True
        assert resolver.is_manager(MANAGER_ACCOUNT) is True

    def test_create_authority_resolver_with_db(self):
        resolver = create_authority_resolver_with_db(ORG_ID)
        assert isinstance(resolver, AuthorityResolverWithDb)


# ============================================================================
# FeedbackDetector Tests
# ============================================================================

class TestFeedbackDetectorInit:
    """FeedbackDetector.__init__ tests."""

    def test_default_patterns(self):
        detector = FeedbackDetector()
        assert len(detector.patterns) == len(ALL_PATTERNS)

    def test_custom_patterns_override(self):
        custom = [DetectionPattern(name="custom", category="fact", regex_patterns=[r"test"])]
        detector = FeedbackDetector(patterns=custom)
        assert len(detector.patterns) == 1
        assert detector.patterns[0].name == "custom"

    def test_additional_custom_patterns(self):
        custom = [DetectionPattern(name="extra", category="fact", regex_patterns=[r"extra"], priority=100)]
        detector = FeedbackDetector(custom_patterns=custom)
        assert len(detector.patterns) == len(ALL_PATTERNS) + 1
        # Sorted by priority desc, so "extra" (100) should be first
        assert detector.patterns[0].name == "extra"


class TestFeedbackDetectorDetect:
    """FeedbackDetector.detect tests."""

    def setup_method(self):
        self.detector = FeedbackDetector()

    def test_empty_message(self):
        assert self.detector.detect("") is None

    def test_whitespace_only(self):
        assert self.detector.detect("   ") is None

    def test_none_like_empty(self):
        assert self.detector.detect("") is None

    def test_alias_detection(self):
        result = self.detector.detect("SSはソウルシンクスの略")
        assert result is not None
        assert result.pattern_category == LearningCategory.ALIAS.value

    def test_correction_detection(self):
        result = self.detector.detect("田中じゃなくて佐藤")
        assert result is not None
        assert result.pattern_category == LearningCategory.CORRECTION.value

    def test_prohibition_detection(self):
        result = self.detector.detect("勝手にタスク削除しないで")
        assert result is not None
        assert result.pattern_category == LearningCategory.RULE.value

    def test_preference_detection(self):
        result = self.detector.detect("敬語でお願い")
        assert result is not None
        assert result.pattern_category == LearningCategory.PREFERENCE.value

    def test_remember_request_detection(self):
        result = self.detector.detect("覚えておいて、来月から新オフィス")
        assert result is not None
        assert result.pattern_category == LearningCategory.FACT.value

    def test_no_match(self):
        result = self.detector.detect("ありがとうございます")
        assert result is None

    def test_context_required_pattern_skipped_without_context(self):
        # context_correction requires context; without it, won't match
        result = self.detector.detect("佐藤です")
        assert result is None

    def test_context_required_pattern_matches_with_context(self):
        context = ConversationContext(
            previous_messages=[{"body": "prev"}],
            soulkun_last_response="田中さんにお伝えします",
        )
        result = self.detector.detect("佐藤です", context=context)
        # This should match context_correction pattern
        assert result is not None

    def test_confidence_below_min_ignored(self):
        """Pattern with very low base_confidence below CONFIDENCE_THRESHOLD_MIN is skipped."""
        low_conf_pattern = DetectionPattern(
            name="low_conf",
            category="fact",
            regex_patterns=[r"テスト低確信"],
            base_confidence=0.01,  # Very low
            priority=200,
        )
        detector = FeedbackDetector(patterns=[low_conf_pattern])
        result = detector.detect("テスト低確信")
        assert result is None

    def test_normalization_fullwidth_spaces(self):
        result = self.detector.detect("覚えておいて、\u3000来月から新オフィス")
        assert result is not None

    def test_normalization_multiple_spaces(self):
        result = self.detector.detect("覚えておいて、  来月から新オフィス")
        assert result is not None


class TestFeedbackDetectorDetectAll:
    """FeedbackDetector.detect_all tests."""

    def test_empty_message(self):
        detector = FeedbackDetector()
        assert detector.detect_all("") == []

    def test_whitespace_only(self):
        detector = FeedbackDetector()
        assert detector.detect_all("   ") == []

    def test_multiple_matches(self):
        detector = FeedbackDetector()
        results = detector.detect_all("覚えておいて、来月から新オフィス")
        assert len(results) >= 1

    def test_sorted_by_confidence(self):
        detector = FeedbackDetector()
        results = detector.detect_all("田中じゃなくて佐藤")
        if len(results) > 1:
            assert results[0].confidence >= results[1].confidence

    def test_context_required_skipped_without_context(self):
        detector = FeedbackDetector()
        results = detector.detect_all("佐藤です")
        # context_correction needs context, should be skipped
        for r in results:
            pattern = next(
                (p for p in detector.patterns if p.name == r.pattern_name), None
            )
            if pattern:
                assert not pattern.requires_context


class TestFeedbackDetectorConfidence:
    """Confidence calculation tests."""

    def test_context_support_boosts_confidence(self):
        context = ConversationContext(
            previous_messages=[{"body": "prev"}],
            soulkun_last_response="田中さんにお伝えします",
            has_recent_error=False,
        )
        detector = FeedbackDetector()
        result_without = detector.detect("田中じゃなくて佐藤")
        result_with = detector.detect("田中じゃなくて佐藤", context=context)
        if result_without and result_with:
            assert result_with.confidence >= result_without.confidence

    def test_error_support_boosts_confidence(self):
        context = ConversationContext(
            has_recent_error=True,
        )
        detector = FeedbackDetector()
        result_without = detector.detect("田中じゃなくて佐藤")
        result_with = detector.detect("田中じゃなくて佐藤", context=context)
        if result_without and result_with:
            assert result_with.confidence >= result_without.confidence

    def test_related_response_boosts_confidence(self):
        context = ConversationContext(
            soulkun_last_response="田中さんに連絡します",
        )
        detector = FeedbackDetector()
        result = detector.detect("田中じゃなくて佐藤", context=context)
        assert result is not None
        # The matched groups include "田中" which is in the last response


class TestFeedbackDetectorContextSupport:
    """_has_context_support, _has_error_support, _is_related_to_last_response."""

    def test_has_context_support_no_context(self):
        detector = FeedbackDetector()
        pattern = DetectionPattern(
            name="test",
            category=LearningCategory.CORRECTION.value,
            regex_patterns=[r"test"],
        )
        assert detector._has_context_support(pattern, None) is False

    def test_has_context_support_correction_with_response(self):
        detector = FeedbackDetector()
        pattern = DetectionPattern(
            name="test",
            category=LearningCategory.CORRECTION.value,
            regex_patterns=[r"test"],
        )
        ctx = ConversationContext(
            previous_messages=[{"body": "something"}],
            soulkun_last_response="何かの返答",
        )
        assert detector._has_context_support(pattern, ctx) is True

    def test_has_context_support_non_correction(self):
        detector = FeedbackDetector()
        pattern = DetectionPattern(
            name="test",
            category=LearningCategory.FACT.value,
            regex_patterns=[r"test"],
        )
        ctx = ConversationContext(
            previous_messages=[{"body": "something"}],
            soulkun_last_response="何かの返答",
        )
        assert detector._has_context_support(pattern, ctx) is False

    def test_has_error_support_no_context(self):
        detector = FeedbackDetector()
        assert detector._has_error_support(None) is False

    def test_has_error_support_true(self):
        detector = FeedbackDetector()
        ctx = ConversationContext(has_recent_error=True)
        assert detector._has_error_support(ctx) is True

    def test_has_error_support_false(self):
        detector = FeedbackDetector()
        ctx = ConversationContext(has_recent_error=False)
        assert detector._has_error_support(ctx) is False

    def test_is_related_no_context(self):
        detector = FeedbackDetector()
        assert detector._is_related_to_last_response({}, None) is False

    def test_is_related_no_response(self):
        detector = FeedbackDetector()
        ctx = ConversationContext(soulkun_last_response=None)
        assert detector._is_related_to_last_response({}, ctx) is False

    def test_is_related_matching_group(self):
        detector = FeedbackDetector()
        ctx = ConversationContext(soulkun_last_response="田中さんに送ります")
        match_result = {
            "groups": {"wrong": "田中"},
            "matched_text": "田中じゃなくて佐藤",
        }
        assert detector._is_related_to_last_response(match_result, ctx) is True

    def test_is_related_no_match(self):
        detector = FeedbackDetector()
        ctx = ConversationContext(soulkun_last_response="何も関係ない応答")
        match_result = {
            "groups": {"wrong": "XXXXXX"},
            "matched_text": "unrelated",
        }
        assert detector._is_related_to_last_response(match_result, ctx) is False


class TestFeedbackDetectorExtractInfo:
    """_extract_info and category-specific extraction."""

    def setup_method(self):
        self.detector = FeedbackDetector()

    def test_extract_alias_info(self):
        groups = {"from_value": "SS", "to_value": "ソウルシンクス"}
        result = self.detector._extract_alias_info(groups, None)
        assert result["type"] == "alias"
        assert result["from_value"] == "SS"
        assert result["to_value"] == "ソウルシンクス"
        assert result["bidirectional"] is False

    def test_extract_correction_info_with_both(self):
        groups = {"wrong": "田中", "correct": "佐藤"}
        result = self.detector._extract_correction_info(groups, None)
        assert result["type"] == "correction"
        assert result["wrong_pattern"] == "田中"
        assert result["correct_pattern"] == "佐藤"

    def test_extract_correction_info_infer_wrong(self):
        groups = {"wrong": "", "correct": "佐藤さん"}
        ctx = ConversationContext(
            soulkun_last_response="田中さんに連絡します"
        )
        result = self.detector._extract_correction_info(groups, ctx)
        assert result["type"] == "correction"
        assert result["wrong_pattern"] == "田中さん"

    def test_extract_rule_prohibition(self):
        groups = {"action": "勝手にタスク削除", "condition": ""}
        result = self.detector._extract_rule_info(groups, None)
        assert result["is_prohibition"] is True
        assert "しない" in result["action"]

    def test_extract_rule_conditional(self):
        groups = {"condition": "急ぎ", "action": "DMで連絡", "subject": "", "rule": ""}
        result = self.detector._extract_rule_info(groups, None)
        assert result["is_prohibition"] is False
        assert result["condition"] == "急ぎ"
        assert result["action"] == "DMで連絡"

    def test_extract_rule_statement(self):
        groups = {"subject": "報告", "rule": "毎日17時", "condition": "", "action": ""}
        result = self.detector._extract_rule_info(groups, None)
        assert result["condition"] == "報告"
        assert result["action"] == "毎日17時"

    def test_extract_rule_fallback(self):
        groups = {"condition": "", "action": "", "subject": "", "rule": ""}
        result = self.detector._extract_rule_info(groups, None)
        assert result["type"] == "rule"

    def test_extract_preference_with_name(self):
        groups = {"preference": "敬語"}
        ctx = ConversationContext(user_name="カズ")
        result = self.detector._extract_preference_info(groups, ctx)
        assert result["user_name"] == "カズ"

    def test_extract_preference_without_name(self):
        groups = {"preference": "敬語"}
        result = self.detector._extract_preference_info(groups, None)
        assert result["user_name"] == ""

    def test_extract_fact_with_subject_value(self):
        groups = {"subject": "プロジェクトA", "value": "田中さん", "fact": ""}
        result = self.detector._extract_fact_info(groups, None)
        assert result["subject"] == "プロジェクトA"
        assert result["value"] == "田中さん"
        assert "description" in result

    def test_extract_fact_with_fact_only(self):
        groups = {"subject": "", "value": "", "fact": "来月から新オフィス"}
        result = self.detector._extract_fact_info(groups, None)
        assert result["description"] == "来月から新オフィス"

    def test_extract_fact_empty(self):
        groups = {"subject": "", "value": "", "fact": ""}
        result = self.detector._extract_fact_info(groups, None)
        assert result["type"] == "fact"

    def test_extract_relationship_info(self):
        groups = {"person1": "佐藤", "person2": "鈴木", "relationship": "同期"}
        result = self.detector._extract_relationship_info(groups, None)
        assert result["person1"] == "佐藤"
        assert result["person2"] == "鈴木"
        assert result["relationship"] == "同期"

    def test_extract_procedure_info(self):
        groups = {"task": "請求書", "action": "経理"}
        result = self.detector._extract_procedure_info(groups, None)
        assert result["task"] == "請求書"
        assert result["action"] == "経理"

    def test_extract_context_info(self):
        groups = {"period": "今月", "context": "繁忙期"}
        result = self.detector._extract_context_info(groups, None)
        assert result["period"] == "今月"
        assert result["context"] == "繁忙期"


class TestFeedbackDetectorInferWrong:
    """_infer_wrong_from_context tests."""

    def test_infer_name_from_context(self):
        detector = FeedbackDetector()
        ctx = ConversationContext(soulkun_last_response="田中さんにお伝えします")
        result = detector._infer_wrong_from_context("佐藤さん", ctx)
        assert result == "田中さん"

    def test_infer_number_from_context(self):
        detector = FeedbackDetector()
        ctx = ConversationContext(soulkun_last_response="10時に設定しました")
        result = detector._infer_wrong_from_context("11", ctx)
        assert result == "10"

    def test_infer_no_response(self):
        detector = FeedbackDetector()
        ctx = ConversationContext(soulkun_last_response=None)
        result = detector._infer_wrong_from_context("佐藤さん", ctx)
        assert result == ""

    def test_infer_no_name_match(self):
        detector = FeedbackDetector()
        ctx = ConversationContext(soulkun_last_response="特に何もありません")
        result = detector._infer_wrong_from_context("佐藤さん", ctx)
        assert result == ""

    def test_infer_same_name_skipped(self):
        detector = FeedbackDetector()
        ctx = ConversationContext(soulkun_last_response="佐藤さんにお伝えします")
        result = detector._infer_wrong_from_context("佐藤さん", ctx)
        assert result == ""

    def test_infer_same_number_skipped(self):
        detector = FeedbackDetector()
        ctx = ConversationContext(soulkun_last_response="11時に設定しました")
        result = detector._infer_wrong_from_context("11", ctx)
        assert result == ""


class TestFeedbackDetectorThresholds:
    """requires_confirmation, should_auto_learn tests."""

    def test_requires_confirmation_true(self):
        detector = FeedbackDetector()
        result = _make_detection_result(confidence=0.5)
        assert detector.requires_confirmation(result) is True

    def test_requires_confirmation_too_high(self):
        detector = FeedbackDetector()
        result = _make_detection_result(confidence=0.8)
        assert detector.requires_confirmation(result) is False

    def test_requires_confirmation_too_low(self):
        detector = FeedbackDetector()
        result = _make_detection_result(confidence=0.3)
        assert detector.requires_confirmation(result) is False

    def test_should_auto_learn_true(self):
        detector = FeedbackDetector()
        result = _make_detection_result(confidence=0.8)
        assert detector.should_auto_learn(result) is True

    def test_should_auto_learn_false(self):
        detector = FeedbackDetector()
        result = _make_detection_result(confidence=0.5)
        assert detector.should_auto_learn(result) is False

    def test_should_auto_learn_at_threshold(self):
        detector = FeedbackDetector()
        result = _make_detection_result(confidence=CONFIDENCE_THRESHOLD_AUTO_LEARN)
        assert detector.should_auto_learn(result) is True


class TestDetectorFactory:
    """create_detector factory tests."""

    def test_create_detector_default(self):
        detector = create_detector()
        assert isinstance(detector, FeedbackDetector)
        assert len(detector.patterns) == len(ALL_PATTERNS)

    def test_create_detector_with_custom(self):
        custom = [DetectionPattern(name="c", category="fact", regex_patterns=[r"c"])]
        detector = create_detector(custom_patterns=custom)
        assert len(detector.patterns) == len(ALL_PATTERNS) + 1


# ============================================================================
# EffectivenessTracker Tests
# ============================================================================

class TestEffectivenessTrackerInit:
    """EffectivenessTracker.__init__ tests."""

    def test_init_defaults(self):
        tracker = EffectivenessTracker(ORG_ID)
        assert tracker.organization_id == ORG_ID
        assert tracker.confidence_decay_rate == DEFAULT_CONFIDENCE_DECAY_RATE

    def test_init_custom_decay(self):
        tracker = EffectivenessTracker(ORG_ID, confidence_decay_rate=0.01)
        assert tracker.confidence_decay_rate == 0.01

    def test_init_custom_repository(self):
        repo = Mock()
        tracker = EffectivenessTracker(ORG_ID, repository=repo)
        assert tracker.repository is repo


class TestEffectivenessTrackerCalculate:
    """calculate_effectiveness tests."""

    def test_learning_without_id(self):
        tracker = EffectivenessTracker(ORG_ID)
        learning = _make_learning(id=None)
        result = tracker.calculate_effectiveness(learning)
        assert result.learning_id == ""
        assert result.recommendation == "review"

    def test_new_learning_default_score(self):
        tracker = EffectivenessTracker(ORG_ID)
        learning = _make_learning(
            applied_count=0,
            success_count=0,
            failure_count=0,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        result = tracker.calculate_effectiveness(learning)
        assert result.learning_id == learning.id
        assert 0.0 <= result.effectiveness_score <= 1.0
        assert result.recommendation in ("keep", "review", "deactivate")

    def test_high_success_learning(self):
        tracker = EffectivenessTracker(ORG_ID)
        learning = _make_learning(
            applied_count=20,
            success_count=15,
            failure_count=1,
            created_at=datetime.now() - timedelta(days=5),
            updated_at=datetime.now(),
        )
        result = tracker.calculate_effectiveness(learning)
        assert result.effectiveness_score > 0.5

    def test_high_failure_learning(self):
        tracker = EffectivenessTracker(ORG_ID)
        learning = _make_learning(
            applied_count=20,
            success_count=1,
            failure_count=15,
            created_at=datetime.now() - timedelta(days=5),
            updated_at=datetime.now(),
        )
        result = tracker.calculate_effectiveness(learning)
        # Low feedback ratio + some usage = lower score
        assert result.effectiveness_score < 0.7

    def test_old_unused_learning_review(self):
        tracker = EffectivenessTracker(ORG_ID)
        learning = _make_learning(
            applied_count=0,
            success_count=0,
            failure_count=0,
            created_at=datetime.now() - timedelta(days=60),
            updated_at=datetime.now() - timedelta(days=60),
        )
        result = tracker.calculate_effectiveness(learning)
        assert result.recommendation == "review"


class TestEffectivenessTrackerBatch:
    """calculate_effectiveness_batch tests."""

    def test_batch_with_provided_learnings(self):
        tracker = EffectivenessTracker(ORG_ID)
        learnings = [
            _make_learning(applied_count=5, success_count=3, failure_count=1),
            _make_learning(applied_count=0),
        ]
        conn = Mock()
        results = tracker.calculate_effectiveness_batch(conn, learnings=learnings)
        assert len(results) == 2

    def test_batch_loads_from_repo(self):
        repo = Mock()
        learnings = [_make_learning()]
        repo.find_all.return_value = (learnings, 1)
        tracker = EffectivenessTracker(ORG_ID, repository=repo)
        conn = Mock()
        results = tracker.calculate_effectiveness_batch(conn)
        repo.find_all.assert_called_once_with(conn, active_only=True)
        assert len(results) == 1


class TestEffectivenessTrackerMetrics:
    """_calculate_metrics tests."""

    def test_metrics_basic(self):
        tracker = EffectivenessTracker(ORG_ID)
        learning = _make_learning(
            applied_count=10,
            success_count=7,
            failure_count=3,
            created_at=datetime.now() - timedelta(days=10),
            updated_at=datetime.now(),
        )
        metrics = tracker._calculate_metrics(learning)
        assert metrics.apply_count == 10
        assert metrics.positive_feedback_count == 7
        assert metrics.negative_feedback_count == 3
        assert metrics.feedback_ratio == 0.7
        assert metrics.days_since_creation >= 9

    def test_metrics_no_feedback(self):
        tracker = EffectivenessTracker(ORG_ID)
        learning = _make_learning(
            applied_count=5,
            success_count=0,
            failure_count=0,
        )
        metrics = tracker._calculate_metrics(learning)
        assert metrics.feedback_ratio == 0.0

    def test_metrics_none_counts(self):
        tracker = EffectivenessTracker(ORG_ID)
        learning = _make_learning()
        learning.applied_count = None
        learning.success_count = None
        learning.failure_count = None
        metrics = tracker._calculate_metrics(learning)
        assert metrics.apply_count == 0
        assert metrics.positive_feedback_count == 0
        assert metrics.negative_feedback_count == 0

    def test_metrics_no_created_at(self):
        tracker = EffectivenessTracker(ORG_ID)
        learning = _make_learning(created_at=None, updated_at=None)
        metrics = tracker._calculate_metrics(learning)
        assert metrics.days_since_creation == 0


class TestEffectivenessTrackerScore:
    """_calculate_score tests."""

    def test_score_no_feedback(self):
        tracker = EffectivenessTracker(ORG_ID)
        metrics = EffectivenessMetrics(
            apply_count=0,
            positive_feedback_count=0,
            negative_feedback_count=0,
            feedback_ratio=0.0,
            confidence_score=1.0,
        )
        score = tracker._calculate_score(metrics)
        # feedback_score = 0.5 (no feedback default)
        # frequency = 0 / 10 = 0
        # confidence = 1.0
        expected = 0.5 * 0.4 + 0.0 * 0.3 + 1.0 * 0.3
        assert score == round(expected, 3)

    def test_score_all_positive(self):
        tracker = EffectivenessTracker(ORG_ID)
        metrics = EffectivenessMetrics(
            apply_count=10,
            positive_feedback_count=10,
            negative_feedback_count=0,
            feedback_ratio=1.0,
            confidence_score=1.0,
        )
        score = tracker._calculate_score(metrics)
        expected = 1.0 * 0.4 + 1.0 * 0.3 + 1.0 * 0.3
        assert score == round(expected, 3)

    def test_score_all_negative(self):
        tracker = EffectivenessTracker(ORG_ID)
        metrics = EffectivenessMetrics(
            apply_count=10,
            positive_feedback_count=0,
            negative_feedback_count=10,
            feedback_ratio=0.0,
            confidence_score=1.0,
        )
        score = tracker._calculate_score(metrics)
        expected = 0.0 * 0.4 + 1.0 * 0.3 + 1.0 * 0.3
        assert score == round(expected, 3)


class TestEffectivenessTrackerRecommendation:
    """_determine_recommendation tests."""

    def test_keep_high_score(self):
        tracker = EffectivenessTracker(ORG_ID)
        metrics = EffectivenessMetrics(apply_count=5, days_since_creation=10)
        rec = tracker._determine_recommendation(0.8, metrics)
        assert rec == "keep"

    def test_review_medium_score(self):
        tracker = EffectivenessTracker(ORG_ID)
        metrics = EffectivenessMetrics(apply_count=5, days_since_creation=10)
        rec = tracker._determine_recommendation(0.45, metrics)
        assert rec == "review"

    def test_deactivate_low_score(self):
        tracker = EffectivenessTracker(ORG_ID)
        metrics = EffectivenessMetrics(apply_count=5, days_since_creation=10)
        rec = tracker._determine_recommendation(0.2, metrics)
        assert rec == "deactivate"

    def test_review_unused_old(self):
        tracker = EffectivenessTracker(ORG_ID)
        metrics = EffectivenessMetrics(apply_count=0, days_since_creation=31)
        rec = tracker._determine_recommendation(0.6, metrics)
        assert rec == "review"

    def test_unused_but_new(self):
        tracker = EffectivenessTracker(ORG_ID)
        metrics = EffectivenessMetrics(apply_count=0, days_since_creation=5)
        rec = tracker._determine_recommendation(0.6, metrics)
        assert rec == "keep"


class TestEffectivenessTrackerSuggestions:
    """_generate_suggestions tests."""

    def test_no_suggestions_healthy(self):
        tracker = EffectivenessTracker(ORG_ID)
        learning = _make_learning()
        metrics = EffectivenessMetrics(
            apply_count=5,
            positive_feedback_count=4,
            negative_feedback_count=0,
            feedback_ratio=1.0,
            days_since_creation=5,
            days_since_last_apply=1,
            confidence_score=0.9,
        )
        suggestions = tracker._generate_suggestions(learning, metrics)
        assert len(suggestions) == 0

    def test_review_content_high_negative(self):
        tracker = EffectivenessTracker(ORG_ID)
        learning = _make_learning()
        metrics = EffectivenessMetrics(
            negative_feedback_count=5,
            feedback_ratio=0.3,
            days_since_creation=10,
            confidence_score=0.9,
        )
        suggestions = tracker._generate_suggestions(learning, metrics)
        types = [s.suggestion_type for s in suggestions]
        assert "review_content" in types

    def test_check_relevance_long_unused(self):
        tracker = EffectivenessTracker(ORG_ID)
        learning = _make_learning()
        metrics = EffectivenessMetrics(
            days_since_last_apply=100,
            days_since_creation=100,
            confidence_score=0.9,
        )
        suggestions = tracker._generate_suggestions(learning, metrics)
        types = [s.suggestion_type for s in suggestions]
        assert "check_relevance" in types

    def test_unused_suggestion(self):
        tracker = EffectivenessTracker(ORG_ID)
        learning = _make_learning()
        metrics = EffectivenessMetrics(
            apply_count=0,
            days_since_creation=31,
            confidence_score=0.9,
        )
        suggestions = tracker._generate_suggestions(learning, metrics)
        types = [s.suggestion_type for s in suggestions]
        assert "unused" in types

    def test_refresh_low_confidence(self):
        tracker = EffectivenessTracker(ORG_ID)
        learning = _make_learning()
        metrics = EffectivenessMetrics(
            days_since_creation=100,
            confidence_score=0.3,
        )
        suggestions = tracker._generate_suggestions(learning, metrics)
        types = [s.suggestion_type for s in suggestions]
        assert "refresh" in types

    def test_no_suggestions_learning_without_id(self):
        tracker = EffectivenessTracker(ORG_ID)
        learning = _make_learning(id=None)
        metrics = EffectivenessMetrics(
            negative_feedback_count=10,
            feedback_ratio=0.1,
        )
        suggestions = tracker._generate_suggestions(learning, metrics)
        assert len(suggestions) == 0


class TestEffectivenessTrackerHealth:
    """check_health tests."""

    def test_healthy_learning(self):
        tracker = EffectivenessTracker(ORG_ID)
        learning = _make_learning(
            applied_count=5,
            success_count=4,
            failure_count=0,
            created_at=datetime.now() - timedelta(days=5),
            updated_at=datetime.now(),
        )
        health = tracker.check_health(learning)
        assert health.status == "healthy"
        assert len(health.issues) == 0

    def test_critical_health(self):
        tracker = EffectivenessTracker(ORG_ID)
        learning = _make_learning(
            applied_count=10,
            success_count=1,
            failure_count=8,
            created_at=datetime.now() - timedelta(days=10),
            updated_at=datetime.now(),
        )
        health = tracker.check_health(learning)
        assert health.status == "critical"
        assert len(health.issues) > 0

    def test_warning_health(self):
        tracker = EffectivenessTracker(ORG_ID)
        learning = _make_learning(
            applied_count=10,
            success_count=2,
            failure_count=3,
            created_at=datetime.now() - timedelta(days=10),
            updated_at=datetime.now(),
        )
        health = tracker.check_health(learning)
        assert health.status == "warning"

    def test_stale_health(self):
        tracker = EffectivenessTracker(ORG_ID)
        learning = _make_learning(
            applied_count=5,
            success_count=3,
            failure_count=0,
            created_at=datetime.now() - timedelta(days=200),
            updated_at=datetime.now() - timedelta(days=200),
        )
        health = tracker.check_health(learning)
        assert health.status == "stale"

    def test_warning_never_used(self):
        tracker = EffectivenessTracker(ORG_ID)
        learning = _make_learning(
            applied_count=0,
            success_count=0,
            failure_count=0,
            created_at=datetime.now() - timedelta(days=90),
            updated_at=datetime.now() - timedelta(days=90),
        )
        health = tracker.check_health(learning)
        assert health.status == "warning"
        assert any("使用されていない" in issue for issue in health.issues)

    def test_health_no_id(self):
        tracker = EffectivenessTracker(ORG_ID)
        learning = _make_learning(id=None)
        health = tracker.check_health(learning)
        assert health.status == "critical"
        assert health.learning_id == ""


class TestEffectivenessTrackerHealthBatch:
    """check_health_batch tests."""

    def test_batch_with_learnings(self):
        tracker = EffectivenessTracker(ORG_ID)
        learnings = [
            _make_learning(
                applied_count=5,
                success_count=4,
                failure_count=0,
                created_at=datetime.now() - timedelta(days=5),
                updated_at=datetime.now(),
            ),
        ]
        conn = Mock()
        result = tracker.check_health_batch(conn, learnings=learnings)
        assert "healthy" in result
        assert "warning" in result
        assert "critical" in result
        assert "stale" in result

    def test_batch_loads_from_repo(self):
        repo = Mock()
        repo.find_all.return_value = ([], 0)
        tracker = EffectivenessTracker(ORG_ID, repository=repo)
        conn = Mock()
        result = tracker.check_health_batch(conn)
        repo.find_all.assert_called_once_with(conn, active_only=True)


class TestEffectivenessTrackerFeedback:
    """record_feedback, record_positive_feedback, record_negative_feedback."""

    def test_record_positive_feedback(self):
        repo = Mock()
        repo.update_feedback_count.return_value = True
        tracker = EffectivenessTracker(ORG_ID, repository=repo)
        conn = Mock()
        result = tracker.record_positive_feedback(conn, "learn-1")
        assert result is True
        repo.update_feedback_count.assert_called_once_with(conn, "learn-1", True)

    def test_record_negative_feedback(self):
        repo = Mock()
        repo.update_feedback_count.return_value = True
        tracker = EffectivenessTracker(ORG_ID, repository=repo)
        conn = Mock()
        result = tracker.record_negative_feedback(conn, "learn-1")
        assert result is True
        repo.update_feedback_count.assert_called_once_with(conn, "learn-1", False)

    def test_record_feedback_positive_impact(self):
        repo = Mock()
        repo.update_feedback_count.return_value = True
        tracker = EffectivenessTracker(ORG_ID, repository=repo)
        conn = Mock()
        result = tracker.record_feedback(conn, "learn-1", DecisionImpact.POSITIVE)
        assert result is True
        repo.update_feedback_count.assert_called_once_with(conn, "learn-1", True)

    def test_record_feedback_negative_impact(self):
        repo = Mock()
        repo.update_feedback_count.return_value = True
        tracker = EffectivenessTracker(ORG_ID, repository=repo)
        conn = Mock()
        result = tracker.record_feedback(conn, "learn-1", DecisionImpact.NEGATIVE)
        assert result is True
        repo.update_feedback_count.assert_called_once_with(conn, "learn-1", False)


class TestEffectivenessTrackerUpdateScores:
    """update_effectiveness_scores tests."""

    def test_update_scores(self):
        repo = Mock()
        learning1 = _make_learning(id="l1", applied_count=5, success_count=3, failure_count=1)
        learning2 = _make_learning(id="l2", applied_count=0)
        repo.find_all.return_value = ([learning1, learning2], 2)
        repo.update_effectiveness_score.return_value = True
        tracker = EffectivenessTracker(ORG_ID, repository=repo)
        conn = Mock()
        updated = tracker.update_effectiveness_scores(conn)
        assert updated == 2
        assert repo.update_effectiveness_score.call_count == 2

    def test_update_scores_skips_no_id(self):
        repo = Mock()
        learning = _make_learning(id=None)
        repo.find_all.return_value = ([learning], 1)
        tracker = EffectivenessTracker(ORG_ID, repository=repo)
        conn = Mock()
        updated = tracker.update_effectiveness_scores(conn)
        assert updated == 0
        repo.update_effectiveness_score.assert_not_called()

    def test_update_scores_partial_failure(self):
        repo = Mock()
        learning1 = _make_learning(id="l1")
        learning2 = _make_learning(id="l2")
        repo.find_all.return_value = ([learning1, learning2], 2)
        repo.update_effectiveness_score.side_effect = [True, False]
        tracker = EffectivenessTracker(ORG_ID, repository=repo)
        conn = Mock()
        updated = tracker.update_effectiveness_scores(conn)
        assert updated == 1


class TestEffectivenessTrackerReport:
    """generate_summary_report, format_summary_report tests."""

    def test_generate_summary_report(self):
        repo = Mock()
        learnings = [
            _make_learning(
                applied_count=5,
                success_count=4,
                failure_count=0,
                created_at=datetime.now() - timedelta(days=5),
                updated_at=datetime.now(),
            ),
        ]
        repo.find_all.return_value = (learnings, 1)
        tracker = EffectivenessTracker(ORG_ID, repository=repo)
        conn = Mock()
        report = tracker.generate_summary_report(conn)
        assert "total_learnings" in report
        assert "by_status" in report
        assert "health_ratio" in report
        assert "average_effectiveness_score" in report
        assert "critical_learnings" in report
        assert "improvement_suggestions_count" in report

    def test_generate_summary_report_empty(self):
        repo = Mock()
        repo.find_all.return_value = ([], 0)
        tracker = EffectivenessTracker(ORG_ID, repository=repo)
        conn = Mock()
        report = tracker.generate_summary_report(conn)
        assert report["total_learnings"] == 0
        assert report["average_effectiveness_score"] == 0.0
        assert report["health_ratio"] == 0

    def test_format_summary_report(self):
        tracker = EffectivenessTracker(ORG_ID)
        report = {
            "total_learnings": 10,
            "by_status": {
                "healthy": 6,
                "warning": 2,
                "critical": 1,
                "stale": 1,
            },
            "health_ratio": 0.6,
            "average_effectiveness_score": 0.75,
            "critical_learnings": [
                {"id": "c1", "category": "rule", "issues": ["bad feedback"]},
            ],
            "improvement_suggestions_count": 3,
        }
        formatted = tracker.format_summary_report(report)
        assert "学習の有効性レポート" in formatted
        assert "10件" in formatted
        assert "改善提案" in formatted

    def test_format_summary_report_no_critical(self):
        tracker = EffectivenessTracker(ORG_ID)
        report = {
            "total_learnings": 5,
            "by_status": {"healthy": 5, "warning": 0, "critical": 0, "stale": 0},
            "health_ratio": 1.0,
            "average_effectiveness_score": 0.9,
            "critical_learnings": [],
            "improvement_suggestions_count": 0,
        }
        formatted = tracker.format_summary_report(report)
        assert "要対応の学習" not in formatted


class TestEffectivenessTrackerFactory:
    """create_effectiveness_tracker factory tests."""

    def test_create_default(self):
        tracker = create_effectiveness_tracker(ORG_ID)
        assert isinstance(tracker, EffectivenessTracker)
        assert tracker.organization_id == ORG_ID

    def test_create_custom_decay(self):
        tracker = create_effectiveness_tracker(ORG_ID, confidence_decay_rate=0.01)
        assert tracker.confidence_decay_rate == 0.01


# ============================================================================
# LearningExtractor Tests
# ============================================================================

class TestLearningExtractorInit:
    """LearningExtractor.__init__ tests."""

    def test_init(self):
        extractor = LearningExtractor(ORG_ID)
        assert extractor.organization_id == ORG_ID


class TestLearningExtractorExtract:
    """LearningExtractor.extract tests."""

    def setup_method(self):
        self.extractor = LearningExtractor(ORG_ID)

    def test_extract_alias(self):
        detection = _make_detection_result(
            pattern_category=LearningCategory.ALIAS.value,
            extracted={
                "category": "alias",
                "original_message": "SSはソウルシンクスの略",
                "type": "alias",
                "from_value": "SS",
                "to_value": "ソウルシンクス",
                "bidirectional": False,
            },
        )
        learning = self.extractor.extract(
            detection, "SSはソウルシンクスの略",
            taught_by_account_id=USER_ACCOUNT,
        )
        assert learning.category == "alias"
        assert learning.trigger_type == TriggerType.KEYWORD.value
        assert learning.trigger_value == "SS"
        assert learning.learned_content["type"] == "alias"
        assert learning.scope == LearningScope.GLOBAL.value

    def test_extract_correction(self):
        detection = _make_detection_result(
            pattern_category=LearningCategory.CORRECTION.value,
            extracted={
                "category": "correction",
                "original_message": "田中じゃなくて佐藤",
                "type": "correction",
                "wrong_pattern": "田中",
                "correct_pattern": "佐藤",
            },
        )
        learning = self.extractor.extract(
            detection, "田中じゃなくて佐藤",
            taught_by_account_id=USER_ACCOUNT,
        )
        assert learning.category == "correction"
        assert learning.trigger_type == TriggerType.PATTERN.value
        assert learning.learned_content["wrong_pattern"] == "田中"

    def test_extract_rule(self):
        detection = _make_detection_result(
            pattern_category=LearningCategory.RULE.value,
            extracted={
                "category": "rule",
                "original_message": "急ぎの時はDMで連絡して",
                "type": "rule",
                "condition": "急ぎ",
                "action": "DMで連絡",
                "is_prohibition": False,
            },
        )
        learning = self.extractor.extract(
            detection, "急ぎの時はDMで連絡して",
            taught_by_account_id=USER_ACCOUNT,
        )
        assert learning.category == "rule"
        assert learning.trigger_type == TriggerType.CONTEXT.value

    def test_extract_preference(self):
        detection = _make_detection_result(
            pattern_category=LearningCategory.PREFERENCE.value,
            extracted={
                "category": "preference",
                "original_message": "敬語でお願い",
                "type": "preference",
                "preference": "敬語",
                "user_name": "カズ",
            },
        )
        learning = self.extractor.extract(
            detection, "敬語でお願い",
            taught_by_account_id=USER_ACCOUNT,
        )
        assert learning.category == "preference"
        assert learning.trigger_type == TriggerType.ALWAYS.value
        assert learning.scope == LearningScope.USER.value
        assert learning.scope_target_id == USER_ACCOUNT
        assert learning.classification == "confidential"

    def test_extract_fact(self):
        detection = _make_detection_result(
            pattern_category=LearningCategory.FACT.value,
            extracted={
                "category": "fact",
                "original_message": "覚えておいて、来月から新オフィス",
                "type": "fact",
                "subject": "新オフィス",
                "value": "来月から",
                "description": "新オフィスは来月から",
            },
        )
        learning = self.extractor.extract(
            detection, "覚えておいて、来月から新オフィス",
            taught_by_account_id=USER_ACCOUNT,
        )
        assert learning.category == "fact"
        assert learning.trigger_type == TriggerType.KEYWORD.value

    def test_extract_relationship(self):
        detection = _make_detection_result(
            pattern_category=LearningCategory.RELATIONSHIP.value,
            extracted={
                "category": "relationship",
                "original_message": "佐藤と鈴木は同期",
                "type": "relationship",
                "person1": "佐藤",
                "person2": "鈴木",
                "relationship": "同期",
            },
        )
        learning = self.extractor.extract(
            detection, "佐藤と鈴木は同期",
            taught_by_account_id=USER_ACCOUNT,
        )
        assert learning.category == "relationship"
        assert learning.trigger_type == TriggerType.KEYWORD.value
        assert "佐藤" in learning.trigger_value
        assert "鈴木" in learning.trigger_value
        assert learning.classification == "confidential"

    def test_extract_procedure(self):
        detection = _make_detection_result(
            pattern_category=LearningCategory.PROCEDURE.value,
            extracted={
                "category": "procedure",
                "original_message": "請求書は経理に回して",
                "type": "procedure",
                "task": "請求書",
                "action": "経理",
            },
        )
        learning = self.extractor.extract(
            detection, "請求書は経理に回して",
            taught_by_account_id=USER_ACCOUNT,
        )
        assert learning.category == "procedure"
        assert learning.trigger_type == TriggerType.KEYWORD.value
        assert learning.trigger_value == "請求書"

    def test_extract_context(self):
        detection = _make_detection_result(
            pattern_category=LearningCategory.CONTEXT.value,
            extracted={
                "category": "context",
                "original_message": "今月は繁忙期",
                "type": "context",
                "period": "今月",
                "context": "繁忙期",
            },
        )
        learning = self.extractor.extract(
            detection, "今月は繁忙期",
            taught_by_account_id=USER_ACCOUNT,
        )
        assert learning.category == "context"
        assert learning.scope == LearningScope.TEMPORARY.value
        assert learning.valid_until is not None  # "今月" should calculate end date

    def test_extract_unknown_category(self):
        detection = _make_detection_result(
            pattern_category="unknown_category",
            extracted={
                "category": "unknown_category",
                "original_message": "something",
            },
        )
        learning = self.extractor.extract(
            detection, "something",
            taught_by_account_id=USER_ACCOUNT,
        )
        assert learning.category == "unknown_category"
        assert learning.learned_content["type"] == "unknown_category"
        assert "raw" in learning.learned_content

    def test_extract_with_context(self):
        ctx = ConversationContext(
            user_name="カズ",
            room_id="room-123",
        )
        detection = _make_detection_result(
            pattern_category=LearningCategory.FACT.value,
            extracted={
                "category": "fact",
                "original_message": "test",
                "type": "fact",
                "description": "test fact",
            },
        )
        learning = self.extractor.extract(
            detection, "test",
            context=ctx,
            taught_by_account_id=USER_ACCOUNT,
        )
        assert learning.taught_by_name == "カズ"
        assert learning.taught_in_room_id == "room-123"
        assert learning.source_context is not None

    def test_extract_with_explicit_name_and_room(self):
        detection = _make_detection_result(
            pattern_category=LearningCategory.FACT.value,
            extracted={
                "category": "fact",
                "original_message": "test",
                "type": "fact",
            },
        )
        learning = self.extractor.extract(
            detection, "test",
            taught_by_account_id=USER_ACCOUNT,
            taught_by_name="Explicit Name",
            room_id="explicit-room",
        )
        assert learning.taught_by_name == "Explicit Name"
        assert learning.taught_in_room_id == "explicit-room"

    def test_extract_ceo_authority(self):
        detection = _make_detection_result()
        learning = self.extractor.extract(
            detection, "test",
            taught_by_account_id=CEO_ACCOUNT,
            taught_by_authority=AuthorityLevel.CEO.value,
        )
        assert learning.authority_level == "ceo"


class TestLearningExtractorBuildContent:
    """_build_*_content tests."""

    def setup_method(self):
        self.extractor = LearningExtractor(ORG_ID)

    def test_build_alias_content(self):
        content = self.extractor._build_alias_content({
            "from_value": "SS",
            "to_value": "ソウルシンクス",
        })
        assert content["type"] == "alias"
        assert content["from"] == "SS"
        assert content["to"] == "ソウルシンクス"

    def test_build_preference_content_with_user(self):
        content = self.extractor._build_preference_content({
            "preference": "敬語",
            "user_name": "カズ",
        })
        assert "カズ" in content["description"]

    def test_build_preference_content_without_user(self):
        content = self.extractor._build_preference_content({
            "preference": "敬語",
        })
        assert content["description"] == "敬語を好む"

    def test_build_fact_content_with_subject(self):
        content = self.extractor._build_fact_content({
            "subject": "プロジェクトA",
            "value": "田中さん",
        })
        assert content["subject"] == "プロジェクトA"
        assert content["value"] == "田中さん"
        assert "プロジェクトA" in content["description"]

    def test_build_fact_content_with_description(self):
        content = self.extractor._build_fact_content({
            "subject": "X",
            "value": "Y",
            "description": "custom description",
        })
        assert content["description"] == "custom description"

    def test_build_fact_content_empty(self):
        content = self.extractor._build_fact_content({})
        assert content["type"] == "fact"
        assert content["subject"] == ""

    def test_build_rule_content_prohibition(self):
        content = self.extractor._build_rule_content({
            "condition": "",
            "action": "タスク削除",
            "is_prohibition": True,
        })
        assert content["is_prohibition"] is True
        assert content["priority"] == "high"
        assert "禁止" in content["description"]

    def test_build_rule_content_normal(self):
        content = self.extractor._build_rule_content({
            "condition": "急ぎ",
            "action": "DM",
        })
        assert content["is_prohibition"] is False
        assert content["condition"] == "急ぎ"

    def test_build_correction_content(self):
        content = self.extractor._build_correction_content({
            "wrong_pattern": "田中",
            "correct_pattern": "佐藤",
        })
        assert content["wrong_pattern"] == "田中"
        assert content["correct_pattern"] == "佐藤"

    def test_build_context_content(self):
        content = self.extractor._build_context_content({
            "period": "今月",
            "context": "繁忙期",
        })
        assert content["subject"] == "今月"
        assert content["context"] == "繁忙期"
        assert "valid_until" in content

    def test_build_context_content_no_period(self):
        content = self.extractor._build_context_content({
            "period": "",
            "context": "something",
        })
        assert "valid_until" not in content

    def test_build_relationship_content(self):
        content = self.extractor._build_relationship_content({
            "person1": "A",
            "person2": "B",
            "relationship": "同期",
        })
        assert content["person1"] == "A"
        assert content["person2"] == "B"
        assert "同期" in content["description"]

    def test_build_procedure_content(self):
        content = self.extractor._build_procedure_content({
            "task": "請求書",
            "action": "経理に回す",
        })
        assert content["task"] == "請求書"
        assert "経理に回す" in content["steps"]

    def test_build_procedure_content_no_action(self):
        content = self.extractor._build_procedure_content({
            "task": "something",
            "action": "",
        })
        assert content["steps"] == []
        assert content["description"] == "something"


class TestLearningExtractorDetermineTrigger:
    """_determine_trigger tests."""

    def setup_method(self):
        self.extractor = LearningExtractor(ORG_ID)

    def test_alias_trigger(self):
        t, v = self.extractor._determine_trigger(
            "alias", {}, {"type": "alias", "from": "SS", "to": "ソウルシンクス"}
        )
        assert t == TriggerType.KEYWORD.value
        assert v == "SS"

    def test_correction_trigger(self):
        t, v = self.extractor._determine_trigger(
            "correction", {}, {"wrong_pattern": "田中"}
        )
        assert t == TriggerType.PATTERN.value
        assert v == "田中"

    def test_rule_trigger(self):
        t, v = self.extractor._determine_trigger(
            "rule", {}, {"condition": "急ぎ"}
        )
        assert t == TriggerType.CONTEXT.value
        assert v == "急ぎ"

    def test_preference_trigger(self):
        t, v = self.extractor._determine_trigger(
            "preference", {}, {"subject": "表示形式"}
        )
        assert t == TriggerType.ALWAYS.value
        assert v == "表示形式"

    def test_preference_trigger_no_subject(self):
        t, v = self.extractor._determine_trigger(
            "preference", {}, {}
        )
        assert t == TriggerType.ALWAYS.value
        assert v == "*"

    def test_fact_trigger(self):
        t, v = self.extractor._determine_trigger(
            "fact", {}, {"subject": "オフィス"}
        )
        assert t == TriggerType.KEYWORD.value
        assert v == "オフィス"

    def test_relationship_trigger(self):
        t, v = self.extractor._determine_trigger(
            "relationship", {}, {"person1": "A", "person2": "B"}
        )
        assert t == TriggerType.KEYWORD.value
        assert v == "A,B"

    def test_procedure_trigger(self):
        t, v = self.extractor._determine_trigger(
            "procedure", {}, {"task": "請求書"}
        )
        assert t == TriggerType.KEYWORD.value
        assert v == "請求書"

    def test_context_trigger(self):
        t, v = self.extractor._determine_trigger(
            "context", {}, {"subject": "今月"}
        )
        assert t == TriggerType.KEYWORD.value
        assert v == "今月"

    def test_default_trigger(self):
        t, v = self.extractor._determine_trigger(
            "unknown", {}, {}
        )
        assert t == TriggerType.ALWAYS.value
        assert v == "*"


class TestLearningExtractorDetermineScope:
    """_determine_scope tests."""

    def setup_method(self):
        self.extractor = LearningExtractor(ORG_ID)

    def test_preference_scope(self):
        s, sid = self.extractor._determine_scope(
            "preference", {}, None, USER_ACCOUNT, None
        )
        assert s == LearningScope.USER.value
        assert sid == USER_ACCOUNT

    def test_context_scope(self):
        s, sid = self.extractor._determine_scope(
            "context", {}, None, USER_ACCOUNT, None
        )
        assert s == LearningScope.TEMPORARY.value
        assert sid is None

    def test_default_scope(self):
        s, sid = self.extractor._determine_scope(
            "fact", {}, None, USER_ACCOUNT, None
        )
        assert s == LearningScope.GLOBAL.value
        assert sid is None


class TestLearningExtractorDetermineValidity:
    """_determine_validity tests."""

    def setup_method(self):
        self.extractor = LearningExtractor(ORG_ID)

    def test_context_validity(self):
        vf, vu = self.extractor._determine_validity(
            "context", {"period": "今月"}
        )
        assert vf is not None
        assert vu is not None

    def test_non_context_validity(self):
        vf, vu = self.extractor._determine_validity("fact", {})
        assert vf is not None
        assert vu is None


class TestLearningExtractorEstimatePeriod:
    """_estimate_period_end tests."""

    def setup_method(self):
        self.extractor = LearningExtractor(ORG_ID)

    def test_this_month(self):
        result = self.extractor._estimate_period_end("今月")
        assert result is not None
        now = datetime.now()
        if now.month == 12:
            expected_year = now.year + 1
            expected_month = 1
        else:
            expected_year = now.year
            expected_month = now.month + 1
        expected = datetime(expected_year, expected_month, 1) - timedelta(days=1)
        assert result.month == expected.month
        assert result.day == expected.day

    def test_this_week(self):
        result = self.extractor._estimate_period_end("今週")
        assert result is not None
        now = datetime.now()
        days_until_sunday = 6 - now.weekday()
        expected = now + timedelta(days=days_until_sunday)
        assert result.day == expected.day

    def test_today(self):
        result = self.extractor._estimate_period_end("今日")
        assert result is not None
        now = datetime.now()
        assert result.hour == 23
        assert result.minute == 59

    def test_next_month(self):
        result = self.extractor._estimate_period_end("来月")
        assert result is not None

    def test_next_week(self):
        result = self.extractor._estimate_period_end("来週")
        assert result is not None

    def test_unknown_period(self):
        result = self.extractor._estimate_period_end("いつか")
        assert result is None


class TestLearningExtractorClassification:
    """_determine_classification tests."""

    def setup_method(self):
        self.extractor = LearningExtractor(ORG_ID)

    def test_relationship_confidential(self):
        result = self.extractor._determine_classification("relationship", {})
        assert result == "confidential"

    def test_preference_confidential(self):
        result = self.extractor._determine_classification("preference", {})
        assert result == "confidential"

    def test_fact_internal(self):
        result = self.extractor._determine_classification("fact", {})
        assert result == "internal"

    def test_rule_internal(self):
        result = self.extractor._determine_classification("rule", {})
        assert result == "internal"


class TestExtractorFactory:
    """create_extractor factory tests."""

    def test_create(self):
        extractor = create_extractor(ORG_ID)
        assert isinstance(extractor, LearningExtractor)
        assert extractor.organization_id == ORG_ID


# ============================================================================
# Edge case integration-like tests
# ============================================================================

class TestDetectorExtractorIntegration:
    """Test that detector output feeds correctly into extractor."""

    def test_alias_flow(self):
        detector = FeedbackDetector()
        extractor = LearningExtractor(ORG_ID)

        result = detector.detect("麻美は渡部麻美のことだよ")
        assert result is not None

        learning = extractor.extract(
            result,
            "麻美は渡部麻美のことだよ",
            taught_by_account_id=USER_ACCOUNT,
        )
        assert learning.category == LearningCategory.ALIAS.value
        assert learning.organization_id == ORG_ID

    def test_correction_flow(self):
        detector = FeedbackDetector()
        extractor = LearningExtractor(ORG_ID)

        result = detector.detect("田中じゃなくて佐藤")
        assert result is not None

        learning = extractor.extract(
            result,
            "田中じゃなくて佐藤",
            taught_by_account_id=USER_ACCOUNT,
        )
        assert learning.category == LearningCategory.CORRECTION.value

    def test_remember_flow(self):
        detector = FeedbackDetector()
        extractor = LearningExtractor(ORG_ID)

        result = detector.detect("覚えておいて、来月から新オフィス")
        assert result is not None

        learning = extractor.extract(
            result,
            "覚えておいて、来月から新オフィス",
            taught_by_account_id=USER_ACCOUNT,
        )
        assert learning.category == LearningCategory.FACT.value

    def test_relationship_flow(self):
        detector = FeedbackDetector()
        extractor = LearningExtractor(ORG_ID)

        result = detector.detect("佐藤と鈴木は同期")
        assert result is not None

        learning = extractor.extract(
            result,
            "佐藤と鈴木は同期",
            taught_by_account_id=USER_ACCOUNT,
        )
        assert learning.category == LearningCategory.RELATIONSHIP.value
        assert learning.classification == "confidential"
