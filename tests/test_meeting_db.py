# tests/test_meeting_db.py
"""
MeetingDB のテスト

CRUD、org_idフィルタ、カスケード削除、楽観ロックをテスト。
"""

import pytest
from unittest.mock import MagicMock, call
from datetime import datetime, timezone

from lib.meetings.meeting_db import MeetingDB


@pytest.fixture
def mock_pool():
    pool = MagicMock()
    conn = MagicMock()
    pool.connect.return_value.__enter__ = MagicMock(return_value=conn)
    pool.connect.return_value.__exit__ = MagicMock(return_value=None)
    return pool


@pytest.fixture
def db(mock_pool):
    return MeetingDB(mock_pool, "org_test")


class TestInit:
    def test_valid_org_id(self, mock_pool):
        db = MeetingDB(mock_pool, "org_test")
        assert db.organization_id == "org_test"

    def test_empty_org_id_raises(self, mock_pool):
        with pytest.raises(ValueError, match="organization_id is required"):
            MeetingDB(mock_pool, "")

    def test_none_org_id_raises(self, mock_pool):
        with pytest.raises(ValueError):
            MeetingDB(mock_pool, None)


class TestCreateMeeting:
    def test_creates_with_org_id(self, db, mock_pool):
        result = db.create_meeting(title="Weekly Standup", meeting_type="regular")

        assert "id" in result
        assert result["status"] == "pending"

        # SQL実行を確認
        conn = mock_pool.connect.return_value.__enter__.return_value
        call_args = conn.execute.call_args
        params = call_args[0][1]
        assert params["org_id"] == "org_test"
        assert params["title"] == "Weekly Standup"
        assert params["meeting_type"] == "regular"
        conn.commit.assert_called_once()

    def test_creates_with_all_fields(self, db, mock_pool):
        db.create_meeting(
            title="Client Review",
            meeting_type="client",
            created_by="12345",
            room_id="room_1",
            source="zoom",
            source_meeting_id="zoom_abc",
        )

        conn = mock_pool.connect.return_value.__enter__.return_value
        params = conn.execute.call_args[0][1]
        assert params["created_by"] == "12345"
        assert params["room_id"] == "room_1"
        assert params["source"] == "zoom"


class TestGetMeeting:
    def test_returns_meeting_with_org_filter(self, db, mock_pool):
        conn = mock_pool.connect.return_value.__enter__.return_value
        mock_row = {
            "id": "meeting-1", "organization_id": "org_test",
            "title": "Test", "meeting_type": "regular",
            "meeting_date": None, "duration_seconds": 0,
            "status": "pending", "source": "manual_upload",
            "room_id": "r1", "created_by": "u1",
            "brain_approved": False, "transcript_sanitized": False,
            "attendees_count": 0, "speakers_detected": 0,
            "document_url": None, "total_tokens_used": 0,
            "estimated_cost_jpy": 0, "error_message": None,
            "error_code": None, "version": 1,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
        conn.execute.return_value.mappings.return_value.fetchone.return_value = mock_row

        result = db.get_meeting("meeting-1")
        assert result["id"] == "meeting-1"

        # org_idフィルタが含まれることを確認
        params = conn.execute.call_args[0][1]
        assert params["org_id"] == "org_test"
        assert params["id"] == "meeting-1"

    def test_returns_none_for_missing(self, db, mock_pool):
        conn = mock_pool.connect.return_value.__enter__.return_value
        conn.execute.return_value.mappings.return_value.fetchone.return_value = None

        result = db.get_meeting("nonexistent")
        assert result is None


class TestUpdateMeetingStatus:
    def test_updates_with_optimistic_lock(self, db, mock_pool):
        conn = mock_pool.connect.return_value.__enter__.return_value
        conn.execute.return_value.rowcount = 1

        result = db.update_meeting_status("m1", "transcribed", expected_version=1)
        assert result is True

        params = conn.execute.call_args[0][1]
        assert params["expected_version"] == 1
        assert params["status"] == "transcribed"
        assert params["org_id"] == "org_test"

    def test_fails_on_version_mismatch(self, db, mock_pool):
        conn = mock_pool.connect.return_value.__enter__.return_value
        conn.execute.return_value.rowcount = 0

        result = db.update_meeting_status("m1", "transcribed", expected_version=99)
        assert result is False

    def test_updates_extra_fields(self, db, mock_pool):
        conn = mock_pool.connect.return_value.__enter__.return_value
        conn.execute.return_value.rowcount = 1

        db.update_meeting_status(
            "m1", "completed", expected_version=2,
            brain_approved=True, duration_seconds=3600,
        )

        sql_str = str(conn.execute.call_args[0][0])
        assert "brain_approved" in sql_str
        assert "duration_seconds" in sql_str

    def test_ignores_disallowed_fields(self, db, mock_pool):
        conn = mock_pool.connect.return_value.__enter__.return_value
        conn.execute.return_value.rowcount = 1

        db.update_meeting_status(
            "m1", "completed", expected_version=1,
            id="hacked", organization_id="other_org",
        )

        sql_str = str(conn.execute.call_args[0][0])
        # idとorganization_idはallowed_fieldsに含まれないので無視される
        assert "hacked" not in str(conn.execute.call_args[0][1].values())


class TestDeleteMeetingCascade:
    def test_deletes_with_org_filter(self, db, mock_pool):
        conn = mock_pool.connect.return_value.__enter__.return_value
        conn.execute.return_value.rowcount = 1

        result = db.delete_meeting_cascade("m1")
        assert result is True

        params = conn.execute.call_args[0][1]
        assert params["org_id"] == "org_test"
        assert params["id"] == "m1"

    def test_returns_false_for_missing(self, db, mock_pool):
        conn = mock_pool.connect.return_value.__enter__.return_value
        conn.execute.return_value.rowcount = 0

        result = db.delete_meeting_cascade("nonexistent")
        assert result is False


class TestRecordingOperations:
    def test_save_recording_with_retention(self, db, mock_pool):
        result = db.save_recording(
            meeting_id="m1",
            gcs_path="gs://bucket/audio.mp3",
            file_size_bytes=1024000,
            duration_seconds=3600,
            format="mp3",
        )

        assert "id" in result
        assert "retention_expires_at" in result

        conn = mock_pool.connect.return_value.__enter__.return_value
        params = conn.execute.call_args[0][1]
        assert params["org_id"] == "org_test"
        assert params["gcs_path"] == "gs://bucket/audio.mp3"

    def test_get_expired_recordings(self, db, mock_pool):
        conn = mock_pool.connect.return_value.__enter__.return_value
        conn.execute.return_value.mappings.return_value.fetchall.return_value = [
            {"id": "r1", "meeting_id": "m1", "gcs_path": "gs://b/f1"},
        ]

        result = db.get_expired_recordings()
        assert len(result) == 1
        assert result[0]["gcs_path"] == "gs://b/f1"

    def test_mark_recordings_deleted(self, db, mock_pool):
        conn = mock_pool.connect.return_value.__enter__.return_value
        conn.execute.return_value.rowcount = 2

        count = db.mark_recordings_deleted(["r1", "r2"])
        assert count == 2

    def test_mark_empty_list_returns_zero(self, db, mock_pool):
        count = db.mark_recordings_deleted([])
        assert count == 0


class TestTranscriptOperations:
    def test_save_transcript(self, db, mock_pool):
        result = db.save_transcript(
            meeting_id="m1",
            raw_transcript="田中さんが発言しました",
            sanitized_transcript="[PERSON]が発言しました",
            detected_language="ja",
            word_count=10,
            confidence=0.95,
        )

        assert "id" in result

        conn = mock_pool.connect.return_value.__enter__.return_value
        params = conn.execute.call_args[0][1]
        assert params["org_id"] == "org_test"
        assert params["raw"] == "田中さんが発言しました"
        assert params["sanitized"] == "[PERSON]が発言しました"

    def test_find_meeting_by_source_id(self, db, mock_pool):
        conn = mock_pool.connect.return_value.__enter__.return_value
        mock_row = {
            "id": "m1", "title": "Zoom Meeting", "status": "transcribed",
            "source": "zoom", "source_meeting_id": "zm123",
            "created_at": datetime.now(timezone.utc),
        }
        conn.execute.return_value.mappings.return_value.fetchone.return_value = mock_row

        result = db.find_meeting_by_source_id("zoom", "zm123")
        assert result is not None
        assert result["source_meeting_id"] == "zm123"

        params = conn.execute.call_args[0][1]
        assert params["org_id"] == "org_test"
        assert params["source"] == "zoom"
        assert params["source_mid"] == "zm123"

    def test_find_meeting_by_source_id_not_found(self, db, mock_pool):
        conn = mock_pool.connect.return_value.__enter__.return_value
        conn.execute.return_value.mappings.return_value.fetchone.return_value = None

        result = db.find_meeting_by_source_id("zoom", "nonexistent")
        assert result is None

    def test_find_meeting_by_source_id_empty_id(self, db, mock_pool):
        result = db.find_meeting_by_source_id("zoom", "")
        assert result is None

    def test_get_recent_meetings_by_source(self, db, mock_pool):
        conn = mock_pool.connect.return_value.__enter__.return_value
        mock_rows = [
            {"id": "m1", "title": "Meeting 1", "source": "zoom",
             "source_meeting_id": "zm1", "meeting_type": "zoom",
             "meeting_date": None, "status": "transcribed",
             "brain_approved": False, "created_by": "u1",
             "room_id": "r1", "created_at": datetime.now(timezone.utc)},
        ]
        conn.execute.return_value.mappings.return_value.fetchall.return_value = mock_rows

        result = db.get_recent_meetings_by_source("zoom")
        assert len(result) == 1
        assert result[0]["source"] == "zoom"

        params = conn.execute.call_args[0][1]
        assert params["org_id"] == "org_test"
        assert params["source"] == "zoom"

    def test_get_recent_meetings_by_source_empty(self, db, mock_pool):
        conn = mock_pool.connect.return_value.__enter__.return_value
        conn.execute.return_value.mappings.return_value.fetchall.return_value = []

        result = db.get_recent_meetings_by_source("zoom")
        assert result == []

    def test_get_recent_meetings_by_source_limit_cap(self, db, mock_pool):
        conn = mock_pool.connect.return_value.__enter__.return_value
        conn.execute.return_value.mappings.return_value.fetchall.return_value = []

        db.get_recent_meetings_by_source("zoom", limit=999)

        params = conn.execute.call_args[0][1]
        assert params["limit"] == 100  # capped at 100

    def test_get_transcript_for_meeting(self, db, mock_pool):
        conn = mock_pool.connect.return_value.__enter__.return_value
        mock_row = {
            "id": "t1",
            "meeting_id": "m1",
            "sanitized_transcript": "sanitized text",
            "segments_json": "[]",
            "speakers_json": "[]",
            "detected_language": "ja",
            "word_count": 10,
            "confidence": 0.95,
            "created_at": datetime.now(timezone.utc),
        }
        conn.execute.return_value.mappings.return_value.fetchone.return_value = mock_row

        result = db.get_transcript_for_meeting("m1")
        assert result is not None
        assert result["meeting_id"] == "m1"
        assert result["sanitized_transcript"] == "sanitized text"

        params = conn.execute.call_args[0][1]
        assert params["org_id"] == "org_test"
        assert params["meeting_id"] == "m1"

    def test_get_transcript_for_meeting_not_found(self, db, mock_pool):
        conn = mock_pool.connect.return_value.__enter__.return_value
        conn.execute.return_value.mappings.return_value.fetchone.return_value = None

        result = db.get_transcript_for_meeting("nonexistent")
        assert result is None

    def test_nullify_expired_raw_transcripts(self, db, mock_pool):
        conn = mock_pool.connect.return_value.__enter__.return_value
        conn.execute.return_value.rowcount = 3

        count = db.nullify_expired_raw_transcripts()
        assert count == 3

        params = conn.execute.call_args[0][1]
        assert params["org_id"] == "org_test"
