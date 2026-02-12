# tests/test_room_router.py
"""
ChatWorkルーム自動振り分けのテスト

Author: Claude Opus 4.6
Created: 2026-02-13
"""

from unittest.mock import MagicMock

import pytest

from lib.meetings.room_router import (
    ADMIN_ROOM_ID,
    MeetingRoomRouter,
    RoomRoutingResult,
)


@pytest.fixture
def mock_pool_with_keywords():
    """キーワードマッピングが存在するモックプール"""
    pool = MagicMock()
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)

    rows = [
        {"keyword": "営業定例", "chatwork_room_id": "111111", "room_name": "営業部"},
        {"keyword": "開発MTG", "chatwork_room_id": "222222", "room_name": "開発チーム"},
        {"keyword": "1on1", "chatwork_room_id": "333333", "room_name": "1on1ルーム"},
        {"keyword": "面談", "chatwork_room_id": "333333", "room_name": "1on1ルーム"},
        {"keyword": "全社", "chatwork_room_id": "444444", "room_name": "全社ルーム"},
        {"keyword": "全体", "chatwork_room_id": "444444", "room_name": "全社ルーム"},
    ]

    result = MagicMock()
    result.mappings.return_value.fetchall.return_value = rows
    conn.execute.return_value = result
    pool.connect.return_value = conn
    return pool


@pytest.fixture
def mock_pool_empty():
    """キーワードマッピングが空のモックプール"""
    pool = MagicMock()
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)

    result = MagicMock()
    result.mappings.return_value.fetchall.return_value = []
    conn.execute.return_value = result
    pool.connect.return_value = conn
    return pool


@pytest.fixture
def mock_pool_db_error():
    """DB接続エラーのモックプール"""
    pool = MagicMock()
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    conn.execute.side_effect = Exception("DB connection lost")
    pool.connect.return_value = conn
    return pool


class TestMeetingRoomRouterInit:
    def test_valid_init(self, mock_pool_empty):
        router = MeetingRoomRouter(mock_pool_empty, "org_test")
        assert router.organization_id == "org_test"

    def test_empty_org_id_raises(self, mock_pool_empty):
        with pytest.raises(ValueError, match="organization_id"):
            MeetingRoomRouter(mock_pool_empty, "")

    def test_whitespace_org_id_raises(self, mock_pool_empty):
        with pytest.raises(ValueError, match="organization_id"):
            MeetingRoomRouter(mock_pool_empty, "   ")


class TestKeywordMatching:
    def test_exact_keyword_match(self, mock_pool_with_keywords):
        router = MeetingRoomRouter(mock_pool_with_keywords, "org_test")
        result = router.resolve_room("営業定例会議")
        assert result.room_id == "111111"
        assert result.routing_method == "keyword_match"
        assert result.matched_keyword == "営業定例"
        assert result.confidence == 0.9

    def test_case_insensitive_match(self, mock_pool_with_keywords):
        router = MeetingRoomRouter(mock_pool_with_keywords, "org_test")
        result = router.resolve_room("開発mtg 2月分")
        assert result.room_id == "222222"
        assert result.routing_method == "keyword_match"

    def test_partial_match_in_title(self, mock_pool_with_keywords):
        router = MeetingRoomRouter(mock_pool_with_keywords, "org_test")
        result = router.resolve_room("2月の全社ミーティング")
        assert result.room_id == "444444"
        assert result.matched_keyword == "全社"

    def test_1on1_match(self, mock_pool_with_keywords):
        router = MeetingRoomRouter(mock_pool_with_keywords, "org_test")
        result = router.resolve_room("田中さんとの1on1")
        assert result.room_id == "333333"

    def test_mendan_match(self, mock_pool_with_keywords):
        router = MeetingRoomRouter(mock_pool_with_keywords, "org_test")
        result = router.resolve_room("新入社員面談")
        assert result.room_id == "333333"

    def test_no_keyword_match_falls_through(self, mock_pool_with_keywords):
        router = MeetingRoomRouter(mock_pool_with_keywords, "org_test")
        result = router.resolve_room("Unknown Meeting")
        assert result.routing_method == "admin_fallback"

    def test_empty_title_falls_through(self, mock_pool_with_keywords):
        router = MeetingRoomRouter(mock_pool_with_keywords, "org_test")
        result = router.resolve_room("")
        assert result.routing_method == "admin_fallback"


class TestCalendarCwIdExtraction:
    def test_cw_id_in_description(self, mock_pool_empty):
        router = MeetingRoomRouter(mock_pool_empty, "org_test")
        result = router.resolve_room(
            "Unknown Meeting",
            calendar_description="会議の詳細 CW:99887766 参加者: ...",
        )
        assert result.room_id == "99887766"
        assert result.routing_method == "calendar_cw_id"
        assert result.confidence == 0.95

    def test_cw_id_at_start(self, mock_pool_empty):
        router = MeetingRoomRouter(mock_pool_empty, "org_test")
        result = router.resolve_room(
            "Meeting", calendar_description="CW:12345678"
        )
        assert result.room_id == "12345678"

    def test_cw_id_at_end(self, mock_pool_empty):
        router = MeetingRoomRouter(mock_pool_empty, "org_test")
        result = router.resolve_room(
            "Meeting", calendar_description="議事録送信先 CW:55555555"
        )
        assert result.room_id == "55555555"

    def test_no_cw_id_falls_through(self, mock_pool_empty):
        router = MeetingRoomRouter(mock_pool_empty, "org_test")
        result = router.resolve_room(
            "Meeting", calendar_description="普通の説明文です"
        )
        assert result.routing_method == "admin_fallback"

    def test_none_description_falls_through(self, mock_pool_empty):
        router = MeetingRoomRouter(mock_pool_empty, "org_test")
        result = router.resolve_room("Meeting", calendar_description=None)
        assert result.routing_method == "admin_fallback"


class TestKeywordPriorityOverCalendar:
    def test_keyword_wins_over_cw_id(self, mock_pool_with_keywords):
        """優先度1（キーワード）が優先度2（CW:ID）より先に評価される"""
        router = MeetingRoomRouter(mock_pool_with_keywords, "org_test")
        result = router.resolve_room(
            "営業定例会議",
            calendar_description="CW:99999999",
        )
        assert result.room_id == "111111"
        assert result.routing_method == "keyword_match"


class TestAdminFallback:
    def test_default_admin_room(self, mock_pool_empty):
        router = MeetingRoomRouter(mock_pool_empty, "org_test")
        result = router.resolve_room("Unknown Meeting")
        assert result.room_id == ADMIN_ROOM_ID
        assert result.routing_method == "admin_fallback"
        assert result.confidence == 0.0

    def test_custom_admin_room(self, mock_pool_empty):
        router = MeetingRoomRouter(mock_pool_empty, "org_test")
        result = router.resolve_room(
            "Unknown", admin_room_id="custom_room_123"
        )
        assert result.room_id == "custom_room_123"

    def test_fallback_message_format(self, mock_pool_empty):
        router = MeetingRoomRouter(mock_pool_empty, "org_test")
        msg = router.build_admin_fallback_message("テスト会議", "meeting-123")
        assert "テスト会議" in msg
        assert "meeting-123" in msg
        assert "[info]" in msg
        assert "ルームID" in msg

    def test_fallback_message_without_meeting_id(self, mock_pool_empty):
        router = MeetingRoomRouter(mock_pool_empty, "org_test")
        msg = router.build_admin_fallback_message("テスト会議")
        assert "テスト会議" in msg
        assert "会議ID" not in msg


class TestDbError:
    def test_db_error_falls_through_to_fallback(self, mock_pool_db_error):
        """DBエラー時はキーワード検索をスキップしてフォールバック"""
        router = MeetingRoomRouter(mock_pool_db_error, "org_test")
        result = router.resolve_room("営業定例会議")
        assert result.routing_method == "admin_fallback"


class TestRoomRoutingResultDataclass:
    def test_default_values(self):
        result = RoomRoutingResult(
            room_id="123", routing_method="test", confidence=0.5
        )
        assert result.matched_keyword is None

    def test_with_keyword(self):
        result = RoomRoutingResult(
            room_id="123",
            routing_method="keyword_match",
            confidence=0.9,
            matched_keyword="営業",
        )
        assert result.matched_keyword == "営業"
