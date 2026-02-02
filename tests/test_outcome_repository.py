"""
lib/brain/outcome_learning/repository.py のテスト
"""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from lib.brain.outcome_learning.repository import OutcomeRepository
from lib.brain.outcome_learning.models import OutcomeEvent, OutcomePattern
from lib.brain.outcome_learning.constants import PatternScope


def _row(mapping):
    return SimpleNamespace(_mapping=mapping)


def _make_conn(fetchone=None, fetchall=None, iterable=None):
    conn = MagicMock()
    result = MagicMock()
    result.fetchone.return_value = fetchone
    result.fetchall.return_value = fetchall or []
    if iterable is not None:
        result.__iter__.return_value = iter(iterable)
    conn.execute.return_value = result
    return conn


def test_save_event_returns_id():
    repo = OutcomeRepository("11111111-1111-1111-1111-111111111111")
    event = OutcomeEvent(target_account_id="user", event_type="notification_sent")
    conn = _make_conn(fetchone=("event-id",))

    event_id = repo.save_event(conn, event)
    assert event_id == "event-id"


def test_update_outcome_returns_true():
    repo = OutcomeRepository("org")
    conn = _make_conn(fetchone=("event-id",))
    assert repo.update_outcome(conn, "event-id", "adopted") is True


def test_mark_learning_extracted_returns_false_when_missing():
    repo = OutcomeRepository("org")
    conn = _make_conn(fetchone=None)
    assert repo.mark_learning_extracted(conn, "event-id") is False


def test_find_pending_events_maps_rows():
    repo = OutcomeRepository("org")
    row = {
        "id": "event-1",
        "organization_id": "org",
        "event_type": "notification_sent",
        "event_subtype": None,
        "event_timestamp": datetime.utcnow(),
        "target_account_id": "user",
        "target_room_id": None,
        "event_details": {},
        "related_resource_type": None,
        "related_resource_id": None,
        "outcome_detected": False,
        "context_snapshot": None,
        "created_at": datetime.utcnow(),
    }
    conn = _make_conn(iterable=[_row(row)])
    results = repo.find_pending_events(conn, max_age_hours=24, limit=10)
    assert len(results) == 1
    assert results[0].id == "event-1"


def test_find_events_by_target_filters_event_type():
    repo = OutcomeRepository("org")
    row = {
        "id": "event-2",
        "organization_id": "org",
        "event_type": "notification_sent",
        "event_subtype": None,
        "event_timestamp": datetime.utcnow(),
        "target_account_id": "user",
        "target_room_id": None,
        "event_details": {},
        "related_resource_type": None,
        "related_resource_id": None,
        "outcome_detected": False,
        "context_snapshot": None,
        "created_at": datetime.utcnow(),
    }
    conn = _make_conn(iterable=[_row(row)])
    results = repo.find_events_by_target(conn, target_account_id="user", event_type="notification_sent")
    assert results[0].event_type == "notification_sent"


def test_find_event_by_id_none():
    repo = OutcomeRepository("org")
    conn = _make_conn(fetchone=None)
    assert repo.find_event_by_id(conn, "event-id") is None


def test_save_pattern_returns_id():
    repo = OutcomeRepository("org")
    pattern = OutcomePattern(pattern_type="timing")
    conn = _make_conn(fetchone=("pattern-id",))
    assert repo.save_pattern(conn, pattern) == "pattern-id"


def test_update_pattern_stats_returns_true():
    repo = OutcomeRepository("org")
    conn = _make_conn(fetchone=("pattern-id",))
    ok = repo.update_pattern_stats(conn, "pattern-id", 10, 7, 3, 0.7, 0.8)
    assert ok is True


def test_mark_pattern_promoted_returns_true():
    repo = OutcomeRepository("org")
    conn = _make_conn(fetchone=("pattern-id",))
    assert repo.mark_pattern_promoted(conn, "pattern-id", "learning-id") is True


def test_find_patterns_active_only():
    repo = OutcomeRepository("org")
    row = {
        "id": "pattern-1",
        "organization_id": "org",
        "pattern_type": "timing",
        "pattern_category": None,
        "scope": PatternScope.USER.value,
        "scope_target_id": None,
        "pattern_content": {},
        "sample_count": 1,
        "success_count": 1,
        "failure_count": 0,
        "success_rate": 1.0,
        "confidence_score": 0.9,
        "is_active": True,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    conn = _make_conn(iterable=[_row(row)])
    results = repo.find_patterns(conn, active_only=True)
    assert results[0].is_active is True


def test_find_applicable_patterns_returns_list():
    repo = OutcomeRepository("org")
    row = {
        "id": "pattern-2",
        "organization_id": "org",
        "pattern_type": "timing",
        "pattern_category": None,
        "scope": PatternScope.GLOBAL.value,
        "scope_target_id": None,
        "pattern_content": {},
        "sample_count": 2,
        "success_count": 1,
        "failure_count": 1,
        "success_rate": 0.5,
        "confidence_score": 0.6,
        "is_active": True,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    conn = _make_conn(iterable=[_row(row)])
    results = repo.find_applicable_patterns(conn, target_account_id="user")
    assert len(results) == 1


def test_find_promotable_patterns():
    repo = OutcomeRepository("org")
    row = {
        "id": "pattern-3",
        "organization_id": "org",
        "pattern_type": "timing",
        "pattern_category": None,
        "scope": PatternScope.USER.value,
        "scope_target_id": None,
        "pattern_content": {},
        "sample_count": 5,
        "success_count": 4,
        "failure_count": 1,
        "success_rate": 0.8,
        "confidence_score": 0.9,
        "is_active": True,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    conn = _make_conn(iterable=[_row(row)])
    results = repo.find_promotable_patterns(conn, min_confidence=0.7, min_sample_count=3)
    assert results[0].confidence_score == 0.9


def test_get_statistics_computes_rates():
    repo = OutcomeRepository("org")
    mapping = {
        "total_events": 10,
        "adopted_count": 6,
        "ignored_count": 2,
        "delayed_count": 1,
        "rejected_count": 1,
        "pending_count": 0,
    }
    conn = _make_conn(fetchone=_row(mapping))
    stats = repo.get_statistics(conn, target_account_id=None, days=7)
    assert stats.total_events == 10
    assert stats.adoption_rate == 0.6
    assert stats.ignore_rate == 0.2


def test_get_hourly_statistics_maps_rows():
    repo = OutcomeRepository("org")
    rows = [
        _row({"hour": 9, "total": 5, "adopted": 3, "ignored": 2}),
        _row({"hour": 10, "total": 2, "adopted": 2, "ignored": 0}),
    ]
    conn = _make_conn(iterable=rows)
    stats = repo.get_hourly_statistics(conn, days=7)
    assert stats[9]["total"] == 5


def test_get_day_of_week_statistics_converts_dow():
    repo = OutcomeRepository("org")
    rows = [
        _row({"dow": 0, "total": 3, "adopted": 1, "ignored": 2}),
    ]
    conn = _make_conn(iterable=rows)
    stats = repo.get_day_of_week_statistics(conn, days=7)
    # PostgreSQL 0=Sunday -> Python 6
    assert 6 in stats
    assert stats[6]["total"] == 3
