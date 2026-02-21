# tests/test_past_meeting_interface.py
"""
過去会議検索インターフェースのテスト

テスト対象:
  - parse_time_range_from_query(): 自然言語 → 日付範囲変換
  - format_meeting_list_message(): 検索結果 → ChatWorkメッセージ変換
  - search_past_meetings(): DB検索（モック使用）

設計:
  - DB接続は一切使用しない（全てモック）
  - PII含まず（会議タイトルのみ）
  - 後方互換性: 既存テストに影響なし
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from lib.meetings.past_meeting_interface import (
    MAX_MEETING_SEARCH_RESULTS,
    PastMeetingResult,
    PastMeetingSearchResult,
    format_duration,
    format_meeting_list_message,
    parse_time_range_from_query,
    search_past_meetings,
)


# ===========================================================================
# テスト用ヘルパー
# ===========================================================================

def make_meeting(
    title: str = "週次朝会",
    occurred_at: datetime = None,
    document_url: str = "https://docs.google.com/document/d/abc",
    duration_seconds: int = 3600,
    task_count: int = 3,
) -> PastMeetingResult:
    if occurred_at is None:
        occurred_at = datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
    return PastMeetingResult(
        meeting_id="meeting-001",
        title=title,
        occurred_at=occurred_at,
        document_url=document_url,
        duration_seconds=duration_seconds,
        task_count=task_count,
        summary=f"Zoom会議「{title}」の議事録を作成",
    )


# ===========================================================================
# parse_time_range_from_query() のテスト
# ===========================================================================

class TestParseTimeRangeFromQuery:
    """自然言語クエリ → 日付範囲変換のテスト"""

    def test_today_month_includes_today(self):
        """今月クエリ: 今月1日〜今月末が返る"""
        now = datetime.now(timezone.utc)
        start, end, desc = parse_time_range_from_query("今月の会議は？")
        assert start is not None
        assert end is not None
        assert start.day == 1
        assert start.month == now.month
        assert end.month == now.month
        assert "今月" in desc

    def test_last_month(self):
        """先月クエリ: 先月の日付範囲が返る"""
        now = datetime.now(timezone.utc)
        start, end, desc = parse_time_range_from_query("先月の採用会議")
        assert start is not None
        assert end is not None
        assert "先月" in desc
        # 先月の月は今月から1引いたもの（または12月）
        expected_month = now.month - 1 if now.month > 1 else 12
        assert start.month == expected_month

    def test_last_week(self):
        """先週クエリ: 先週の日付範囲が返る"""
        start, end, desc = parse_time_range_from_query("先週の会議")
        assert start is not None
        assert end is not None
        assert "先週" in desc
        # 先週は少なくとも7日以上前
        now = datetime.now(timezone.utc)
        assert start < now - timedelta(days=6)

    def test_this_week(self):
        """今週クエリ: 今週の日付範囲が返る"""
        start, end, desc = parse_time_range_from_query("今週の会議")
        assert start is not None
        assert "今週" in desc

    def test_specific_month_pattern(self):
        """N月の: 対応する月が返る"""
        now = datetime.now(timezone.utc)
        # 過去の月を指定（1月）
        # 1月が未来の場合は昨年を返すので、yearの検証は省略してmonthだけ確認
        start, end, desc = parse_time_range_from_query("1月の会議")
        assert start is not None
        assert start.month == 1
        assert "1月" in desc

    def test_recent_keywords(self):
        """直近/最近: 過去30日の範囲が返る"""
        start, end, desc = parse_time_range_from_query("最近の会議")
        assert start is not None
        assert end is not None
        now = datetime.now(timezone.utc)
        # 30日前後の範囲
        assert (now - start).days <= 31

    def test_fallback_no_time_expression(self):
        """時間表現なし: fallback (None, None) またはデフォルト30日前が返る"""
        start, end, desc = parse_time_range_from_query("採用会議の議事録")
        # fallbackはNone (呼び出し側でデフォルト処理)
        # または "最近の" がdescに入る
        assert desc == "最近の"

    def test_this_year(self):
        """今年クエリ"""
        now = datetime.now(timezone.utc)
        start, end, desc = parse_time_range_from_query("今年の会議")
        assert start.year == now.year
        assert start.month == 1
        assert "今年" in desc

    def test_last_year(self):
        """昨年/去年クエリ"""
        now = datetime.now(timezone.utc)
        start, end, desc = parse_time_range_from_query("昨年の会議を教えて")
        assert start is not None
        assert start.year == now.year - 1
        assert start.month == 1
        assert "昨年" in desc

    def test_start_before_end(self):
        """start < end の不変条件を確認"""
        queries = ["先月の", "今月の", "先週の", "今週の", "最近の"]
        for q in queries:
            start, end, _ = parse_time_range_from_query(q)
            if start and end:
                assert start < end, f"start >= end for query: {q}"


# ===========================================================================
# format_duration() のテスト
# ===========================================================================

class TestFormatDuration:
    """秒 → 時間表示変換のテスト"""

    def test_minutes_only(self):
        assert format_duration(30 * 60) == "30分"

    def test_hours_and_minutes(self):
        assert format_duration(90 * 60) == "1時間30分"

    def test_hours_only(self):
        assert format_duration(2 * 3600) == "2時間"

    def test_zero_returns_unknown(self):
        assert format_duration(0) == "不明"

    def test_negative_returns_unknown(self):
        assert format_duration(-1) == "不明"


# ===========================================================================
# format_meeting_list_message() のテスト
# ===========================================================================

class TestFormatMeetingListMessage:
    """検索結果 → ChatWorkメッセージ変換のテスト"""

    def test_no_results(self):
        """結果なし: 「見つかりませんでした」メッセージ"""
        result = PastMeetingSearchResult(
            meetings=[],
            total_found=0,
            query_description="先月の",
        )
        msg = format_meeting_list_message(result)
        assert "先月の" in msg
        assert "見つかりませんでした" in msg

    def test_single_result_with_url(self):
        """1件: タイトル・日付・URLが含まれる"""
        meeting = make_meeting(
            title="採用会議",
            occurred_at=datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
            document_url="https://docs.google.com/document/d/abc",
        )
        result = PastMeetingSearchResult(
            meetings=[meeting],
            total_found=1,
            query_description="先月の",
        )
        msg = format_meeting_list_message(result)
        assert "採用会議" in msg
        assert "1月15日" in msg
        assert "https://docs.google.com/document/d/abc" in msg

    def test_single_result_with_duration_and_tasks(self):
        """1件: 時間とタスク数が含まれる"""
        meeting = make_meeting(duration_seconds=3600, task_count=5)
        result = PastMeetingSearchResult(
            meetings=[meeting],
            total_found=1,
            query_description="今月の",
        )
        msg = format_meeting_list_message(result)
        assert "1時間" in msg
        assert "タスク5件" in msg

    def test_multiple_results(self):
        """複数件: 全タイトルと件数が含まれる"""
        meetings = [
            make_meeting(title=f"会議{i}") for i in range(3)
        ]
        result = PastMeetingSearchResult(
            meetings=meetings,
            total_found=3,
            query_description="今月の",
        )
        msg = format_meeting_list_message(result)
        assert "3件" in msg
        assert "会議0" in msg
        assert "会議1" in msg
        assert "会議2" in msg

    def test_no_document_url(self):
        """URLなし: URLリンクが含まれない"""
        meeting = make_meeting(document_url="")
        result = PastMeetingSearchResult(
            meetings=[meeting],
            total_found=1,
            query_description="先月の",
        )
        msg = format_meeting_list_message(result)
        assert "docs.google.com" not in msg

    def test_no_occurred_at(self):
        """日付なし: タイトルだけが出力される（クラッシュしない）"""
        meeting = make_meeting(occurred_at=None)
        result = PastMeetingSearchResult(
            meetings=[meeting],
            total_found=1,
            query_description="先月の",
        )
        msg = format_meeting_list_message(result)
        assert "週次朝会" in msg  # title is included


# ===========================================================================
# search_past_meetings() のテスト（モック使用）
# ===========================================================================

class TestSearchPastMeetings:
    """DB検索のテスト（モック使用）"""

    def _make_episode(self, title: str, source: str = "zoom"):
        """モック Episode を作成"""
        ep = MagicMock()
        ep.id = "ep-001"
        ep.summary = f"Zoom会議「{title}」の議事録を作成"
        ep.occurred_at = datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        ep.details = {
            "meeting_id": "zoom-001",
            "title": title,
            "room_id": "123",
            "document_url": "https://docs.google.com/document/d/test",
            "duration_seconds": 3600,
            "task_count": 2,
            "source": source,
        }
        return ep

    def test_returns_zoom_meetings_only(self):
        """zoom sourceのエピソードだけが返る"""
        episodes = [
            self._make_episode("採用会議", source="zoom"),
            self._make_episode("一般会話", source="chatwork"),  # 除外対象
        ]

        mock_memory = MagicMock()
        mock_memory.find_episodes_by_time_range.return_value = episodes
        mock_conn = MagicMock()

        result = search_past_meetings(
            memory_enhancement=mock_memory,
            conn=mock_conn,
            organization_id="org-001",
            query="先月の会議",
        )

        assert result.total_found == 1
        assert result.meetings[0].title == "採用会議"

    def test_returns_google_meet_meetings(self):
        """google_meet sourceも含まれ、drive_urlがdocument_urlとして正しく返る（C-1対応）"""
        ep = MagicMock()
        ep.id = "ep-gm"
        ep.summary = "Google Meet会議の議事録"
        ep.occurred_at = datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        ep.details = {
            "meeting_id": "gm-001",
            "title": "Google Meet会議",
            "room_id": "456",
            "drive_url": "https://docs.google.com/document/d/gm_doc",  # drive_urlキー
            "duration_seconds": 1800,
            "task_count": 1,
            "source": "google_meet",
        }
        mock_memory = MagicMock()
        mock_memory.find_episodes_by_time_range.return_value = [ep]
        mock_conn = MagicMock()

        result = search_past_meetings(
            memory_enhancement=mock_memory,
            conn=mock_conn,
            organization_id="org-001",
            query="今月の会議",
        )
        assert result.total_found == 1
        # C-1 修正確認: drive_url が document_url に正しくマッピングされること
        assert result.meetings[0].document_url == "https://docs.google.com/document/d/gm_doc"

    def test_empty_episodes_returns_empty_result(self):
        """エピソードなし: 空の結果が返る"""
        mock_memory = MagicMock()
        mock_memory.find_episodes_by_time_range.return_value = []
        mock_conn = MagicMock()

        result = search_past_meetings(
            memory_enhancement=mock_memory,
            conn=mock_conn,
            organization_id="org-001",
            query="先月の会議",
        )
        assert result.total_found == 0
        assert result.meetings == []

    def test_query_description_passed_through(self):
        """クエリの説明文が結果に含まれる"""
        mock_memory = MagicMock()
        mock_memory.find_episodes_by_time_range.return_value = []
        mock_conn = MagicMock()

        result = search_past_meetings(
            memory_enhancement=mock_memory,
            conn=mock_conn,
            organization_id="org-001",
            query="今月の会議",
        )
        assert "今月" in result.query_description

    def test_episode_type_interaction_filter_applied(self):
        """EpisodeType.INTERACTIONでフィルタされる"""
        from lib.brain.memory_enhancement import EpisodeType

        mock_memory = MagicMock()
        mock_memory.find_episodes_by_time_range.return_value = []
        mock_conn = MagicMock()

        search_past_meetings(
            memory_enhancement=mock_memory,
            conn=mock_conn,
            organization_id="org-001",
            query="先月の会議",
        )

        call_kwargs = mock_memory.find_episodes_by_time_range.call_args
        assert call_kwargs.kwargs.get("episode_type") == EpisodeType.INTERACTION
