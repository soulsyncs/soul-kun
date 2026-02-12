# tests/test_google_calendar_client.py
"""
Google Calendar連携クライアントのテスト

Author: Claude Opus 4.6
Created: 2026-02-13
"""

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from lib.meetings.google_calendar_client import (
    CalendarEvent,
    GoogleCalendarClient,
    _parse_calendar_event,
    _parse_gcal_datetime,
    _select_best_match,
    create_calendar_client_from_env,
)


# ============================================================
# CalendarEvent dataclass tests
# ============================================================


class TestCalendarEvent:
    def test_has_cw_tag_true(self):
        ev = CalendarEvent(
            event_id="1", title="MTG", description="送信先 CW:12345678",
            start_time=None, end_time=None,
        )
        assert ev.has_cw_tag is True

    def test_has_cw_tag_false(self):
        ev = CalendarEvent(
            event_id="1", title="MTG", description="普通の説明文",
            start_time=None, end_time=None,
        )
        assert ev.has_cw_tag is False

    def test_has_cw_tag_false_no_digits(self):
        """CW:の後に数字がなければ偽"""
        ev = CalendarEvent(
            event_id="1", title="MTG", description="See CW: notes",
            start_time=None, end_time=None,
        )
        assert ev.has_cw_tag is False

    def test_has_cw_tag_false_short_digits(self):
        """4桁以下は無効"""
        ev = CalendarEvent(
            event_id="1", title="MTG", description="CW:1234",
            start_time=None, end_time=None,
        )
        assert ev.has_cw_tag is False

    def test_has_cw_tag_none_description(self):
        ev = CalendarEvent(
            event_id="1", title="MTG", description=None,
            start_time=None, end_time=None,
        )
        assert ev.has_cw_tag is False

    def test_cw_room_id_extraction(self):
        ev = CalendarEvent(
            event_id="1", title="MTG", description="送信先 CW:12345678",
            start_time=None, end_time=None,
        )
        assert ev.cw_room_id == "12345678"

    def test_cw_room_id_none_when_missing(self):
        ev = CalendarEvent(
            event_id="1", title="MTG", description="普通の説明文",
            start_time=None, end_time=None,
        )
        assert ev.cw_room_id is None

    def test_attendees_default_empty(self):
        ev = CalendarEvent(
            event_id="1", title="MTG", description=None,
            start_time=None, end_time=None,
        )
        assert ev.attendees == []


# ============================================================
# _parse_gcal_datetime tests
# ============================================================


class TestParseGcalDatetime:
    def test_iso_with_timezone(self):
        dt = _parse_gcal_datetime("2026-02-13T10:00:00+09:00")
        assert dt is not None
        assert dt.hour == 10
        assert dt.tzinfo is not None

    def test_iso_utc(self):
        dt = _parse_gcal_datetime("2026-02-13T01:00:00+00:00")
        assert dt is not None

    def test_date_only(self):
        dt = _parse_gcal_datetime("2026-02-13")
        assert dt is not None
        assert dt.year == 2026

    def test_none_input(self):
        assert _parse_gcal_datetime(None) is None

    def test_invalid_string(self):
        assert _parse_gcal_datetime("not-a-date") is None


# ============================================================
# _parse_calendar_event tests
# ============================================================


class TestParseCalendarEvent:
    def test_full_event(self):
        raw = {
            "id": "evt_123",
            "summary": "営業定例",
            "description": "CW:11111111",
            "start": {"dateTime": "2026-02-13T10:00:00+09:00"},
            "end": {"dateTime": "2026-02-13T11:00:00+09:00"},
            "attendees": [
                {"email": "user1@example.com"},
                {"email": "user2@example.com"},
                {"email": "room@resource.calendar.google.com"},
            ],
            "organizer": {"email": "boss@example.com"},
            "htmlLink": "https://calendar.google.com/event?id=evt_123",
        }
        ev = _parse_calendar_event(raw)
        assert ev is not None
        assert ev.event_id == "evt_123"
        assert ev.title == "営業定例"
        assert ev.description == "CW:11111111"
        assert ev.has_cw_tag is True
        assert len(ev.attendees) == 2  # resource excluded
        assert ev.organizer_email == "boss@example.com"
        assert ev.html_link is not None

    def test_minimal_event(self):
        raw = {"id": "evt_min"}
        ev = _parse_calendar_event(raw)
        assert ev is not None
        assert ev.title == ""
        assert ev.description is None
        assert ev.attendees == []

    def test_no_id_returns_none(self):
        raw = {"summary": "No ID event"}
        assert _parse_calendar_event(raw) is None

    def test_resource_rooms_excluded(self):
        raw = {
            "id": "evt_rooms",
            "attendees": [
                {"email": "user@example.com"},
                {"email": "conf-room@resource.calendar.google.com"},
            ],
        }
        ev = _parse_calendar_event(raw)
        assert len(ev.attendees) == 1
        assert "resource.calendar.google.com" not in ev.attendees[0]


# ============================================================
# _select_best_match tests
# ============================================================


class TestSelectBestMatch:
    @pytest.fixture
    def base_time(self):
        return datetime(2026, 2, 13, 10, 0, 0, tzinfo=timezone.utc)

    def _make_event(self, event_id, title="MTG", description=None, start_offset_min=0, base_time=None):
        base = base_time or datetime(2026, 2, 13, 10, 0, 0, tzinfo=timezone.utc)
        return CalendarEvent(
            event_id=event_id,
            title=title,
            description=description,
            start_time=base + timedelta(minutes=start_offset_min),
            end_time=base + timedelta(minutes=start_offset_min + 60),
        )

    def test_cw_tag_highest_priority(self, base_time):
        # CW:タグありが他の全条件より優先
        ev_cw = self._make_event("1", title="Other", description="CW:99999999", start_offset_min=25)
        ev_title = self._make_event("2", title="営業定例", start_offset_min=0)
        best = _select_best_match([ev_cw, ev_title], base_time, "営業定例")
        assert best.event_id == "1"

    def test_title_match_over_time(self, base_time):
        # タイトル一致が時刻近さより優先
        ev_far_title = self._make_event("1", title="営業定例", start_offset_min=20)
        ev_close = self._make_event("2", title="Other", start_offset_min=1)
        best = _select_best_match([ev_far_title, ev_close], base_time, "営業定例")
        assert best.event_id == "1"

    def test_closer_time_wins_same_title(self, base_time):
        ev1 = self._make_event("1", title="MTG", start_offset_min=5)
        ev2 = self._make_event("2", title="MTG", start_offset_min=20)
        best = _select_best_match([ev1, ev2], base_time, None)
        assert best.event_id == "1"

    def test_empty_candidates(self, base_time):
        assert _select_best_match([], base_time, "test") is None

    def test_single_candidate(self, base_time):
        ev = self._make_event("1", start_offset_min=0)
        best = _select_best_match([ev], base_time, None)
        assert best.event_id == "1"

    def test_partial_title_match(self, base_time):
        ev = self._make_event("1", title="2月の営業定例会議", start_offset_min=0)
        best = _select_best_match([ev], base_time, "営業定例")
        assert best is not None
        assert best.event_id == "1"


# ============================================================
# GoogleCalendarClient tests
# ============================================================


class TestGoogleCalendarClient:
    def test_init_default_calendar_id(self):
        with patch.dict("os.environ", {}, clear=False):
            client = GoogleCalendarClient()
            assert client.calendar_id == "primary"

    def test_init_env_calendar_id(self):
        with patch.dict("os.environ", {"GOOGLE_CALENDAR_ID": "test@group.calendar.google.com"}):
            client = GoogleCalendarClient()
            assert client.calendar_id == "test@group.calendar.google.com"

    def test_init_explicit_calendar_id(self):
        client = GoogleCalendarClient(calendar_id="custom@calendar")
        assert client.calendar_id == "custom@calendar"

    def test_find_matching_event_api_error(self):
        """API初期化失敗時はNoneを返す"""
        client = GoogleCalendarClient()
        # _get_service が例外を投げるようにモック
        client._get_service = MagicMock(side_effect=Exception("auth failed"))
        result = client.find_matching_event(
            datetime(2026, 2, 13, 10, 0, 0, tzinfo=timezone.utc)
        )
        assert result is None

    def test_find_matching_event_no_results(self):
        """イベントなしの場合はNoneを返す"""
        mock_service = MagicMock()
        mock_service.events.return_value.list.return_value.execute.return_value = {
            "items": []
        }
        client = GoogleCalendarClient()
        client._service = mock_service
        result = client.find_matching_event(
            datetime(2026, 2, 13, 10, 0, 0, tzinfo=timezone.utc)
        )
        assert result is None

    def test_find_matching_event_returns_best(self):
        """マッチするイベントを正しく返す"""
        mock_service = MagicMock()
        mock_service.events.return_value.list.return_value.execute.return_value = {
            "items": [
                {
                    "id": "evt_1",
                    "summary": "営業定例",
                    "description": "CW:12345678",
                    "start": {"dateTime": "2026-02-13T10:00:00+00:00"},
                    "end": {"dateTime": "2026-02-13T11:00:00+00:00"},
                },
                {
                    "id": "evt_2",
                    "summary": "ランチ",
                    "start": {"dateTime": "2026-02-13T10:05:00+00:00"},
                    "end": {"dateTime": "2026-02-13T10:30:00+00:00"},
                },
            ]
        }
        client = GoogleCalendarClient()
        client._service = mock_service
        result = client.find_matching_event(
            datetime(2026, 2, 13, 10, 0, 0, tzinfo=timezone.utc),
            zoom_topic="営業定例",
        )
        assert result is not None
        assert result.event_id == "evt_1"
        assert result.description == "CW:12345678"

    def test_find_matching_event_list_error(self):
        """API呼び出しエラー時はNoneを返す"""
        mock_service = MagicMock()
        mock_service.events.return_value.list.return_value.execute.side_effect = (
            Exception("API error")
        )
        client = GoogleCalendarClient()
        client._service = mock_service
        result = client.find_matching_event(
            datetime(2026, 2, 13, 10, 0, 0, tzinfo=timezone.utc)
        )
        assert result is None

    def test_get_event_by_id_success(self):
        mock_service = MagicMock()
        mock_service.events.return_value.get.return_value.execute.return_value = {
            "id": "evt_direct",
            "summary": "直接取得",
            "description": "test",
            "start": {"dateTime": "2026-02-13T10:00:00+00:00"},
            "end": {"dateTime": "2026-02-13T11:00:00+00:00"},
        }
        client = GoogleCalendarClient()
        client._service = mock_service
        result = client.get_event_by_id("evt_direct")
        assert result is not None
        assert result.title == "直接取得"

    def test_get_event_by_id_error(self):
        mock_service = MagicMock()
        mock_service.events.return_value.get.return_value.execute.side_effect = (
            Exception("not found")
        )
        client = GoogleCalendarClient()
        client._service = mock_service
        result = client.get_event_by_id("nonexistent")
        assert result is None


# ============================================================
# create_calendar_client_from_env tests
# ============================================================


class TestCreateCalendarClientFromEnv:
    def test_disabled_by_default(self):
        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop("ENABLE_GOOGLE_CALENDAR", None)
            result = create_calendar_client_from_env()
            assert result is None

    def test_enabled_true(self):
        with patch.dict("os.environ", {"ENABLE_GOOGLE_CALENDAR": "true"}):
            result = create_calendar_client_from_env()
            assert result is not None
            assert isinstance(result, GoogleCalendarClient)

    def test_enabled_1(self):
        with patch.dict("os.environ", {"ENABLE_GOOGLE_CALENDAR": "1"}):
            result = create_calendar_client_from_env()
            assert result is not None

    def test_disabled_false(self):
        with patch.dict("os.environ", {"ENABLE_GOOGLE_CALENDAR": "false"}):
            result = create_calendar_client_from_env()
            assert result is None
