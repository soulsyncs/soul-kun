"""
lib/brain/outcome_learning/implicit_detector.py のテスト
"""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from lib.brain.outcome_learning.implicit_detector import ImplicitFeedbackDetector
from lib.brain.outcome_learning.models import OutcomeEvent
from lib.brain.outcome_learning.constants import (
    EventType,
    FeedbackSignal,
    OutcomeType,
    ADOPTED_THRESHOLD_HOURS,
    DELAYED_THRESHOLD_HOURS,
    IGNORED_THRESHOLD_HOURS,
)


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


def _event(event_type, **kwargs):
    base = dict(
        id="event-1",
        event_type=event_type,
        target_account_id="u",
        target_room_id="room",
        event_timestamp=datetime.now() - timedelta(hours=1),
        related_resource_id=None,
    )
    base.update(kwargs)
    return OutcomeEvent(**base)


def test_detect_skips_if_outcome_already_detected():
    detector = ImplicitFeedbackDetector("org")
    event = _event(EventType.GOAL_REMINDER.value, outcome_detected=True)
    assert detector.detect(_make_conn(), event) is None


def test_detect_routes_goal_reminder():
    detector = ImplicitFeedbackDetector("org")
    event = _event(EventType.GOAL_REMINDER.value)
    # force fallback by missing goal_id
    result = detector.detect(_make_conn(fetchone=None), event)
    assert result is None


def test_detect_from_goal_progress_no_rows_ignored():
    detector = ImplicitFeedbackDetector("org")
    event = _event(EventType.GOAL_REMINDER.value, related_resource_id="goal-1")
    conn = _make_conn(fetchall=[])
    # force elapsed time beyond ignored threshold
    event.event_timestamp = datetime.now() - timedelta(hours=IGNORED_THRESHOLD_HOURS + 1)
    fb = detector._detect_from_goal_progress(conn, event)
    assert fb.outcome_type == OutcomeType.IGNORED.value
    assert fb.feedback_signal == FeedbackSignal.GOAL_STALLED.value


def test_detect_from_goal_progress_with_daily_note():
    detector = ImplicitFeedbackDetector("org")
    event = _event(EventType.GOAL_REMINDER.value, related_resource_id="goal-1")
    row = (datetime.now().date(), "note", None, datetime.now())
    conn = _make_conn(fetchall=[row])
    fb = detector._detect_from_goal_progress(conn, event)
    assert fb.outcome_type == OutcomeType.ADOPTED.value
    assert fb.feedback_signal == FeedbackSignal.GOAL_PROGRESS_MADE.value


def test_detect_from_goal_progress_partial_when_no_note():
    detector = ImplicitFeedbackDetector("org")
    event = _event(EventType.GOAL_REMINDER.value, related_resource_id="goal-1")
    row = (datetime.now().date(), None, None, datetime.now())
    conn = _make_conn(fetchall=[row])
    fb = detector._detect_from_goal_progress(conn, event)
    assert fb.outcome_type == OutcomeType.PARTIAL.value
    assert fb.feedback_signal == FeedbackSignal.READ_BUT_NO_ACTION.value


def test_detect_from_task_status_done():
    detector = ImplicitFeedbackDetector("org")
    event = _event(EventType.TASK_REMINDER.value, related_resource_id="task-1")
    row = ("done", datetime.now(), None)
    conn = _make_conn(fetchone=row)
    fb = detector._detect_from_task_status(conn, event)
    assert fb.outcome_type == OutcomeType.ADOPTED.value
    assert fb.feedback_signal == FeedbackSignal.TASK_COMPLETED.value


def test_detect_from_task_status_overdue():
    detector = ImplicitFeedbackDetector("org")
    event = _event(EventType.TASK_REMINDER.value, related_resource_id="task-1")
    overdue = datetime.now() - timedelta(days=1)
    row = ("open", datetime.now(), overdue)
    conn = _make_conn(fetchone=row)
    fb = detector._detect_from_task_status(conn, event)
    assert fb.outcome_type == OutcomeType.IGNORED.value
    assert fb.feedback_signal == FeedbackSignal.TASK_OVERDUE.value


def test_detect_from_daily_response_success_falls_back_to_time():
    detector = ImplicitFeedbackDetector("org")
    event = _event(EventType.DAILY_CHECK.value)
    row = ("success", datetime.now(), {})
    conn = _make_conn(fetchone=row)
    # when no response yet and elapsed < ignored threshold, returns None
    event.event_timestamp = datetime.now() - timedelta(hours=1)
    detector._check_user_response = MagicMock(return_value=False)
    fb = detector._detect_from_daily_response(conn, event)
    assert fb is None


def test_detect_from_time_elapsed_adopted_on_response():
    detector = ImplicitFeedbackDetector("org")
    event = _event(EventType.NOTIFICATION_SENT.value)
    conn = _make_conn(fetchone=(True,))
    detector._check_user_response = MagicMock(return_value=True)
    event.event_timestamp = datetime.now() - timedelta(hours=ADOPTED_THRESHOLD_HOURS - 0.5)
    fb = detector._detect_from_time_elapsed(conn, event)
    assert fb.outcome_type == OutcomeType.ADOPTED.value


def test_detect_from_time_elapsed_delayed_on_response():
    detector = ImplicitFeedbackDetector("org")
    event = _event(EventType.NOTIFICATION_SENT.value)
    detector._check_user_response = MagicMock(return_value=True)
    event.event_timestamp = datetime.now() - timedelta(hours=DELAYED_THRESHOLD_HOURS - 0.5)
    fb = detector._detect_from_time_elapsed(_make_conn(), event)
    assert fb.outcome_type == OutcomeType.DELAYED.value


def test_detect_from_time_elapsed_ignored_no_response():
    detector = ImplicitFeedbackDetector("org")
    event = _event(EventType.NOTIFICATION_SENT.value)
    detector._check_user_response = MagicMock(return_value=False)
    event.event_timestamp = datetime.now() - timedelta(hours=IGNORED_THRESHOLD_HOURS + 1)
    fb = detector._detect_from_time_elapsed(_make_conn(), event)
    assert fb.outcome_type == OutcomeType.IGNORED.value


def test_check_user_response_handles_db_error():
    detector = ImplicitFeedbackDetector("org")
    event = _event(EventType.NOTIFICATION_SENT.value)
    conn = _make_conn()
    conn.execute.side_effect = Exception("db")
    assert detector._check_user_response(conn, event) is False


def test_detect_batch_collects_feedback():
    detector = ImplicitFeedbackDetector("org")
    event = _event(EventType.NOTIFICATION_SENT.value)
    detector.detect = MagicMock(return_value="fb")
    result = detector.detect_batch(_make_conn(), [event])
    assert result == ["fb"]
