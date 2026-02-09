# tests/test_zoom_brain_interface.py
"""
ZoomBrainInterfaceの統合テスト

Author: Claude Opus 4.6
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lib.brain.models import HandlerResult
from lib.meetings.zoom_brain_interface import (
    ZoomBrainInterface,
    _parse_zoom_datetime,
)


@pytest.fixture
def mock_pool():
    pool = MagicMock()
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)

    # dedup check (find_meeting_by_source_id) — returns None (no duplicate)
    dedup_result = MagicMock()
    dedup_result.mappings.return_value.fetchone.return_value = None

    # create_meeting
    create_result = MagicMock()
    create_result.mappings.return_value.fetchone.return_value = {
        "id": "meeting-uuid-123",
        "status": "pending",
    }

    # save_transcript
    save_result = MagicMock()
    save_result.mappings.return_value.fetchone.return_value = {
        "id": "transcript-uuid-456",
    }

    # update_meeting_status
    update_result = MagicMock()
    update_result.rowcount = 1

    conn.execute = MagicMock(
        side_effect=[dedup_result, create_result, save_result, update_result]
    )
    conn.commit = MagicMock()
    pool.connect.return_value = conn
    return pool


@pytest.fixture
def mock_zoom_client():
    client = MagicMock()
    client.list_recordings.return_value = [
        {
            "id": "zoom-meeting-001",
            "topic": "Weekly Standup",
            "start_time": "2026-02-09T10:00:00Z",
            "recording_files": [
                {"file_type": "MP4", "download_url": "https://zoom.us/mp4"},
                {
                    "file_type": "TRANSCRIPT",
                    "download_url": "https://zoom.us/vtt",
                },
            ],
        }
    ]
    client.download_transcript.return_value = """WEBVTT

00:00:01.000 --> 00:00:05.000
田中: 今日の議題は3つあります

00:00:05.000 --> 00:00:10.000
山田: 了解しました
"""
    client.find_transcript_url.return_value = "https://zoom.us/vtt"
    return client


class TestZoomBrainInterfaceInit:
    def test_valid_init(self, mock_pool):
        interface = ZoomBrainInterface(mock_pool, "org_test")
        assert interface.organization_id == "org_test"

    def test_empty_org_id_raises(self, mock_pool):
        with pytest.raises(ValueError, match="organization_id"):
            ZoomBrainInterface(mock_pool, "")

    def test_whitespace_org_id_raises(self, mock_pool):
        with pytest.raises(ValueError, match="organization_id"):
            ZoomBrainInterface(mock_pool, "   ")


class TestProcessZoomMinutes:
    @pytest.mark.asyncio
    async def test_success_flow(self, mock_pool, mock_zoom_client):
        interface = ZoomBrainInterface(
            mock_pool, "org_test", zoom_client=mock_zoom_client
        )
        result = await interface.process_zoom_minutes(
            room_id="room_123",
            account_id="user_456",
        )
        assert result.success is True
        assert "meeting_id" in result.data
        assert result.data["speakers_detected"] == 2
        assert result.data["zoom_meeting_id"] == "zoom-meeting-001"

    @pytest.mark.asyncio
    async def test_no_recordings_found(self, mock_pool):
        client = MagicMock()
        client.list_recordings.return_value = []

        interface = ZoomBrainInterface(
            mock_pool, "org_test", zoom_client=client
        )
        result = await interface.process_zoom_minutes(
            room_id="room_123",
            account_id="user_456",
        )
        assert result.success is False
        assert "見つからなかった" in result.message

    @pytest.mark.asyncio
    async def test_transcript_not_ready(self, mock_pool):
        client = MagicMock()
        client.list_recordings.return_value = [
            {
                "id": "m1",
                "topic": "Test",
                "start_time": "2026-02-09T10:00:00Z",
                "recording_files": [
                    {"file_type": "MP4", "download_url": "https://zoom.us/mp4"},
                ],
            }
        ]
        client.find_transcript_url.return_value = None

        interface = ZoomBrainInterface(
            mock_pool, "org_test", zoom_client=client
        )
        result = await interface.process_zoom_minutes(
            room_id="room_123",
            account_id="user_456",
        )
        assert result.success is False
        assert "準備中" in result.message

    @pytest.mark.asyncio
    async def test_empty_transcript(self, mock_pool):
        client = MagicMock()
        client.list_recordings.return_value = [
            {
                "id": "m1",
                "topic": "Test",
                "start_time": "2026-02-09T10:00:00Z",
                "recording_files": [
                    {"file_type": "TRANSCRIPT", "download_url": "https://zoom.us/vtt"},
                ],
            }
        ]
        client.find_transcript_url.return_value = "https://zoom.us/vtt"
        client.download_transcript.return_value = "WEBVTT\n\n"

        interface = ZoomBrainInterface(
            mock_pool, "org_test", zoom_client=client
        )
        result = await interface.process_zoom_minutes(
            room_id="room_123",
            account_id="user_456",
        )
        assert result.success is False
        assert "空" in result.message

    @pytest.mark.asyncio
    async def test_specific_meeting_id(self, mock_pool, mock_zoom_client):
        mock_zoom_client.get_meeting_recordings.return_value = {
            "id": "specific-meeting",
            "topic": "Specific Meeting",
            "start_time": "2026-02-09T10:00:00Z",
            "recording_files": [
                {
                    "file_type": "TRANSCRIPT",
                    "download_url": "https://zoom.us/specific_vtt",
                },
            ],
        }
        mock_zoom_client.find_transcript_url.return_value = (
            "https://zoom.us/specific_vtt"
        )

        interface = ZoomBrainInterface(
            mock_pool, "org_test", zoom_client=mock_zoom_client
        )
        result = await interface.process_zoom_minutes(
            room_id="room_123",
            account_id="user_456",
            zoom_meeting_id="specific-meeting",
        )
        assert result.success is True
        mock_zoom_client.get_meeting_recordings.assert_called_once_with(
            "specific-meeting"
        )

    @pytest.mark.asyncio
    async def test_api_error_returns_handler_result(self, mock_pool):
        client = MagicMock()
        # list_recordings returns empty (simulating catch in _find_recording)
        client.list_recordings.side_effect = Exception("API Error")

        interface = ZoomBrainInterface(
            mock_pool, "org_test", zoom_client=client
        )
        result = await interface.process_zoom_minutes(
            room_id="room_123",
            account_id="user_456",
        )
        assert result.success is False
        # _find_recording catches the exception and returns None,
        # so we get "not found" message rather than error data
        assert "見つからなかった" in result.message

    @pytest.mark.asyncio
    async def test_custom_title(self, mock_pool, mock_zoom_client):
        interface = ZoomBrainInterface(
            mock_pool, "org_test", zoom_client=mock_zoom_client
        )
        result = await interface.process_zoom_minutes(
            room_id="room_123",
            account_id="user_456",
            meeting_title="カスタムタイトル",
        )
        assert result.success is True
        assert result.data["title"] == "カスタムタイトル"

    @pytest.mark.asyncio
    async def test_llm_minutes_generated(self, mock_pool, mock_zoom_client):
        def mock_ai_response(messages, system_prompt):
            return json.dumps({
                "summary": "LLM生成の要約",
                "topics": ["議題1"],
                "decisions": ["決定1"],
                "action_items": [],
                "next_meeting": "",
                "corrections": [],
            })

        interface = ZoomBrainInterface(
            mock_pool, "org_test", zoom_client=mock_zoom_client
        )
        result = await interface.process_zoom_minutes(
            room_id="room_123",
            account_id="user_456",
            get_ai_response_func=mock_ai_response,
        )
        assert result.success is True
        assert "minutes" in result.data
        assert result.data["minutes"]["summary"] == "LLM生成の要約"

    @pytest.mark.asyncio
    async def test_llm_failure_falls_back(self, mock_pool, mock_zoom_client):
        def failing_ai(messages, system_prompt):
            raise Exception("LLM Error")

        interface = ZoomBrainInterface(
            mock_pool, "org_test", zoom_client=mock_zoom_client
        )
        result = await interface.process_zoom_minutes(
            room_id="room_123",
            account_id="user_456",
            get_ai_response_func=failing_ai,
        )
        # Should still succeed with transcript-only message
        assert result.success is True
        assert "minutes" not in result.data

    @pytest.mark.asyncio
    async def test_speakers_extracted(self, mock_pool, mock_zoom_client):
        interface = ZoomBrainInterface(
            mock_pool, "org_test", zoom_client=mock_zoom_client
        )
        result = await interface.process_zoom_minutes(
            room_id="room_123",
            account_id="user_456",
        )
        assert result.success is True
        assert "田中" in result.data["speakers"]
        assert "山田" in result.data["speakers"]

    @pytest.mark.asyncio
    async def test_duplicate_meeting_returns_existing(self, mock_pool, mock_zoom_client):
        """Idempotency: same Zoom meeting ID should not create duplicate records."""
        # Setup: find_meeting_by_source_id returns a match
        conn = MagicMock()
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=False)

        # find_meeting_by_source_id returns existing record
        source_result = MagicMock()
        source_result.mappings.return_value.fetchone.return_value = {
            "id": "existing-meeting-id",
            "title": "Already Processed",
            "source": "zoom",
            "source_meeting_id": "zoom-meeting-001",
            "status": "transcribed",
            "created_at": None,
        }
        conn.execute = MagicMock(return_value=source_result)
        conn.commit = MagicMock()
        mock_pool.connect.return_value = conn

        interface = ZoomBrainInterface(
            mock_pool, "org_test", zoom_client=mock_zoom_client
        )
        result = await interface.process_zoom_minutes(
            room_id="room_123",
            account_id="user_456",
        )
        assert result.success is True
        assert result.data.get("already_processed") is True
        assert result.data["meeting_id"] == "existing-meeting-id"

    @pytest.mark.asyncio
    async def test_async_ai_response_func(self, mock_pool, mock_zoom_client):
        """Async get_ai_response_func should be awaited directly."""
        async def async_ai(messages, system_prompt):
            return json.dumps({
                "summary": "Async生成の要約",
                "topics": [],
                "decisions": [],
                "action_items": [],
                "next_meeting": "",
                "corrections": [],
            })

        interface = ZoomBrainInterface(
            mock_pool, "org_test", zoom_client=mock_zoom_client
        )
        result = await interface.process_zoom_minutes(
            room_id="room_123",
            account_id="user_456",
            get_ai_response_func=async_ai,
        )
        assert result.success is True
        assert "minutes" in result.data
        assert result.data["minutes"]["summary"] == "Async生成の要約"


    @pytest.mark.asyncio
    async def test_recording_id_none_safe(self):
        """recording_data with id=None should not produce 'None' string."""
        # Custom mock_pool: no dedup call (source_mid=""), so skip dedup result
        pool = MagicMock()
        conn = MagicMock()
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=False)

        create_result = MagicMock()
        create_result.mappings.return_value.fetchone.return_value = {
            "id": "new-meeting-id",
            "status": "pending",
        }
        save_result = MagicMock()
        save_result.mappings.return_value.fetchone.return_value = {"id": "t1"}
        update_result = MagicMock()
        update_result.rowcount = 1

        conn.execute = MagicMock(
            side_effect=[create_result, save_result, update_result]
        )
        conn.commit = MagicMock()
        pool.connect.return_value = conn

        client = MagicMock()
        client.list_recordings.return_value = [
            {
                "id": None,
                "topic": "No ID Meeting",
                "start_time": "2026-02-09T10:00:00Z",
                "recording_files": [
                    {"file_type": "TRANSCRIPT", "download_url": "https://zoom.us/vtt"},
                ],
            }
        ]
        client.find_transcript_url.return_value = "https://zoom.us/vtt"
        client.download_transcript.return_value = """WEBVTT

00:00:01.000 --> 00:00:05.000
Speaker: test
"""

        interface = ZoomBrainInterface(
            pool, "org_test", zoom_client=client
        )
        result = await interface.process_zoom_minutes(
            room_id="room_123",
            account_id="user_456",
        )
        assert result.success is True
        # source_mid should be "" not "None"
        assert result.data.get("zoom_meeting_id") == ""

    @pytest.mark.asyncio
    async def test_find_recording_fallback_no_transcript(self, mock_pool):
        """_find_recording returns latest meeting even without transcript file."""
        client = MagicMock()
        client.list_recordings.return_value = [
            {
                "id": "m1",
                "topic": "No Transcript",
                "start_time": "2026-02-09T10:00:00Z",
                "recording_files": [
                    {"file_type": "MP4", "download_url": "https://zoom.us/mp4"},
                ],
            }
        ]
        client.find_transcript_url.return_value = None

        interface = ZoomBrainInterface(
            mock_pool, "org_test", zoom_client=client
        )
        result = await interface.process_zoom_minutes(
            room_id="room_123",
            account_id="user_456",
        )
        # Falls back to latest meeting, but transcript_url is None → "not ready"
        assert result.success is False
        assert "準備中" in result.message


class TestParseZoomDatetime:
    def test_valid_iso_with_z(self):
        dt = _parse_zoom_datetime("2026-02-09T10:00:00Z")
        assert dt is not None
        assert dt.year == 2026
        assert dt.month == 2
        assert dt.hour == 10

    def test_none_input(self):
        assert _parse_zoom_datetime(None) is None

    def test_empty_string(self):
        assert _parse_zoom_datetime("") is None

    def test_invalid_format(self):
        assert _parse_zoom_datetime("not-a-date") is None
