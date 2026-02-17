"""
Googleカレンダー読み取りツール テスト — Step A-3

calendar_tool の予定取得・フォーマット機能をテスト:
- 正常な予定一覧のフォーマット
- 空の予定リスト
- 日付パースエラー
- カレンダー未接続時のエラー
- PII保護（参加者メールアドレスが含まれないこと）
"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta

from lib.brain.calendar_tool import (
    list_calendar_events,
    format_calendar_events,
    _format_time,
    DEFAULT_DAYS_AHEAD,
    MAX_EVENTS,
)


class TestListCalendarEvents:
    """list_calendar_events のテスト"""

    def test_invalid_date_format_returns_error(self):
        """不正な日付形式はエラーを返す"""
        pool = MagicMock()
        result = list_calendar_events(
            pool=pool,
            organization_id="org-123",
            date_from="invalid-date",
        )
        assert result["success"] is False
        assert "日付の形式" in result["error"]

    @patch("lib.meetings.google_calendar_client.create_calendar_client_from_db")
    def test_no_client_returns_error(self, mock_create):
        """カレンダー未接続時はエラーを返す"""
        mock_create.return_value = None
        pool = MagicMock()

        result = list_calendar_events(
            pool=pool,
            organization_id="org-123",
            date_from="2026-02-17",
        )
        assert result["success"] is False
        assert "接続されていません" in result["error"]

    @patch("lib.meetings.google_calendar_client.create_calendar_client_from_db")
    def test_successful_event_list(self, mock_create):
        """正常に予定一覧を取得"""
        mock_client = MagicMock()
        mock_client.calendar_id = "primary"
        mock_service = MagicMock()
        mock_client._get_service.return_value = mock_service

        # Google Calendar API レスポンスをモック
        mock_service.events.return_value.list.return_value.execute.return_value = {
            "items": [
                {
                    "summary": "チームミーティング",
                    "start": {"dateTime": "2026-02-17T10:00:00+09:00"},
                    "end": {"dateTime": "2026-02-17T11:00:00+09:00"},
                    "location": "会議室A",
                    "description": "週次のチームミーティング",
                    "attendees": [
                        {"email": "tanaka@example.com"},
                        {"email": "yamada@example.com"},
                        {"email": "room-a@resource.calendar.google.com"},  # リソース
                    ],
                    "htmlLink": "https://calendar.google.com/event?eid=xxx",
                },
                {
                    "summary": "ランチ",
                    "start": {"dateTime": "2026-02-17T12:00:00+09:00"},
                    "end": {"dateTime": "2026-02-17T13:00:00+09:00"},
                },
            ]
        }
        mock_create.return_value = mock_client

        pool = MagicMock()
        result = list_calendar_events(
            pool=pool,
            organization_id="org-123",
            date_from="2026-02-17",
        )

        assert result["success"] is True
        assert result["event_count"] == 2
        assert result["events"][0]["title"] == "チームミーティング"
        assert result["events"][0]["location"] == "会議室A"
        assert result["events"][0]["attendee_count"] == 2  # リソースを除外
        assert result["events"][1]["title"] == "ランチ"

    @patch("lib.meetings.google_calendar_client.create_calendar_client_from_db")
    def test_no_events_returns_empty(self, mock_create):
        """予定なしの場合"""
        mock_client = MagicMock()
        mock_client.calendar_id = "primary"
        mock_service = MagicMock()
        mock_client._get_service.return_value = mock_service
        mock_service.events.return_value.list.return_value.execute.return_value = {
            "items": []
        }
        mock_create.return_value = mock_client

        pool = MagicMock()
        result = list_calendar_events(
            pool=pool,
            organization_id="org-123",
            date_from="2026-02-17",
        )

        assert result["success"] is True
        assert result["event_count"] == 0
        assert result["events"] == []

    @patch("lib.meetings.google_calendar_client.create_calendar_client_from_db")
    def test_api_error_returns_failure(self, mock_create):
        """API呼び出し失敗時"""
        mock_client = MagicMock()
        mock_client.calendar_id = "primary"
        mock_service = MagicMock()
        mock_client._get_service.return_value = mock_service
        mock_service.events.return_value.list.return_value.execute.side_effect = Exception("API Error")
        mock_create.return_value = mock_client

        pool = MagicMock()
        result = list_calendar_events(
            pool=pool,
            organization_id="org-123",
            date_from="2026-02-17",
        )

        assert result["success"] is False
        assert "失敗" in result["error"]

    @patch("lib.meetings.google_calendar_client.create_calendar_client_from_db")
    def test_pii_protection_no_email_in_result(self, mock_create):
        """結果に参加者のメールアドレスが含まれないこと（PII保護）"""
        mock_client = MagicMock()
        mock_client.calendar_id = "primary"
        mock_service = MagicMock()
        mock_client._get_service.return_value = mock_service
        mock_service.events.return_value.list.return_value.execute.return_value = {
            "items": [
                {
                    "summary": "会議",
                    "start": {"dateTime": "2026-02-17T10:00:00+09:00"},
                    "end": {"dateTime": "2026-02-17T11:00:00+09:00"},
                    "attendees": [
                        {"email": "secret@example.com"},
                    ],
                },
            ]
        }
        mock_create.return_value = mock_client

        pool = MagicMock()
        result = list_calendar_events(
            pool=pool,
            organization_id="org-123",
            date_from="2026-02-17",
        )

        # メールアドレスが結果に含まれないことを確認
        import json
        result_str = json.dumps(result, ensure_ascii=False)
        assert "secret@example.com" not in result_str
        # 代わりに件数だけ返す
        assert result["events"][0]["attendee_count"] == 1

    @patch("lib.meetings.google_calendar_client.create_calendar_client_from_db")
    def test_long_description_truncated(self, mock_create):
        """長い説明文が切り詰められること"""
        mock_client = MagicMock()
        mock_client.calendar_id = "primary"
        mock_service = MagicMock()
        mock_client._get_service.return_value = mock_service
        long_desc = "あ" * 200
        mock_service.events.return_value.list.return_value.execute.return_value = {
            "items": [
                {
                    "summary": "会議",
                    "start": {"dateTime": "2026-02-17T10:00:00+09:00"},
                    "end": {"dateTime": "2026-02-17T11:00:00+09:00"},
                    "description": long_desc,
                },
            ]
        }
        mock_create.return_value = mock_client

        pool = MagicMock()
        result = list_calendar_events(
            pool=pool,
            organization_id="org-123",
            date_from="2026-02-17",
        )

        desc = result["events"][0]["description_summary"]
        assert desc.endswith("...")
        assert len(desc) <= 104  # 100 + "..."


class TestFormatCalendarEvents:
    """format_calendar_events のテスト"""

    def test_format_with_events(self):
        """予定ありのフォーマット"""
        result = {
            "success": True,
            "events": [
                {
                    "title": "朝会",
                    "start_time": "2026-02-17T09:00:00+09:00",
                    "end_time": "2026-02-17T09:30:00+09:00",
                    "location": None,
                    "description_summary": None,
                    "attendee_count": 5,
                    "html_link": None,
                },
            ],
            "date_range": "2026年02月17日",
            "event_count": 1,
        }
        formatted = format_calendar_events(result)
        assert "2026年02月17日" in formatted
        assert "1件" in formatted
        assert "朝会" in formatted
        assert "09:00" in formatted
        assert "5名" in formatted

    def test_format_no_events(self):
        """予定なしのフォーマット"""
        result = {
            "success": True,
            "events": [],
            "date_range": "2026年02月17日",
            "event_count": 0,
        }
        formatted = format_calendar_events(result)
        assert "予定はありません" in formatted

    def test_format_error(self):
        """エラーのフォーマット"""
        result = {
            "success": False,
            "error": "カレンダー未接続",
        }
        formatted = format_calendar_events(result)
        assert "カレンダーエラー" in formatted
        assert "カレンダー未接続" in formatted

    def test_format_with_location(self):
        """場所ありのフォーマット"""
        result = {
            "success": True,
            "events": [
                {
                    "title": "客先訪問",
                    "start_time": "2026-02-17T14:00:00+09:00",
                    "end_time": "2026-02-17T16:00:00+09:00",
                    "location": "渋谷オフィス",
                    "description_summary": None,
                    "attendee_count": 0,
                    "html_link": None,
                },
            ],
            "date_range": "2026年02月17日",
            "event_count": 1,
        }
        formatted = format_calendar_events(result)
        assert "渋谷オフィス" in formatted


class TestFormatTime:
    """_format_time のテスト"""

    def test_iso_datetime(self):
        """ISO形式の日時"""
        assert _format_time("2026-02-17T09:00:00+09:00") == "09:00"

    def test_empty_string(self):
        """空文字列"""
        assert _format_time("") == ""

    def test_date_only(self):
        """日付のみ（終日イベント）→ 00:00として扱われる"""
        result = _format_time("2026-02-17")
        assert result == "00:00"

    def test_invalid_format(self):
        """不正なフォーマット"""
        result = _format_time("not-a-date")
        assert result  # エラーにならずに何か返す
