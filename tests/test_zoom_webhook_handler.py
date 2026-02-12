# tests/test_zoom_webhook_handler.py
"""
Zoom Webhookハンドラーのテスト

Author: Claude Opus 4.6
Created: 2026-02-13
"""

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'chatwork-webhook'))

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from handlers.zoom_webhook_handler import (
    handle_zoom_webhook_event,
    SOULKUN_ACCOUNT_ID,
)
from lib.admin_config import DEFAULT_ADMIN_ROOM_ID


@pytest.fixture
def mock_pool():
    pool = MagicMock()
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)

    dedup_result = MagicMock()
    dedup_result.mappings.return_value.fetchone.return_value = None

    create_result = MagicMock()
    create_result.mappings.return_value.fetchone.return_value = {
        "id": "meeting-uuid-webhook",
        "status": "pending",
    }

    save_result = MagicMock()
    save_result.mappings.return_value.fetchone.return_value = {"id": "t1"}

    update_result = MagicMock()
    update_result.rowcount = 1

    conn.execute = MagicMock(
        side_effect=[dedup_result, create_result, save_result, update_result]
    )
    conn.commit = MagicMock()
    pool.connect.return_value = conn
    return pool


@pytest.fixture
def sample_recording_completed_payload():
    return {
        "object": {
            "id": 12345678,
            "uuid": "abc-def-ghi",
            "topic": "Weekly Standup",
            "start_time": "2026-02-13T10:00:00Z",
            "duration": 60,
            "host_id": "host-user-id",
            "host_email": "host@example.com",
            "recording_files": [
                {
                    "file_type": "MP4",
                    "download_url": "https://zoom.us/rec/download/mp4",
                },
                {
                    "file_type": "TRANSCRIPT",
                    "download_url": "https://zoom.us/rec/download/vtt",
                },
            ],
            "participant_count": 5,
        }
    }


class TestHandleZoomWebhookEvent:
    @pytest.mark.asyncio
    async def test_ignores_non_recording_events(self, mock_pool):
        result = await handle_zoom_webhook_event(
            event_type="meeting.started",
            payload={},
            pool=mock_pool,
            organization_id="org_test",
        )
        assert result.success is True
        assert result.data["action"] == "ignored"

    @pytest.mark.asyncio
    async def test_ignores_unknown_event_type(self, mock_pool):
        result = await handle_zoom_webhook_event(
            event_type="unknown.event",
            payload={},
            pool=mock_pool,
            organization_id="org_test",
        )
        assert result.success is True
        assert "ignored" in result.data.get("action", "")

    @pytest.mark.asyncio
    async def test_missing_pool_returns_error(self):
        result = await handle_zoom_webhook_event(
            event_type="recording.completed",
            payload={"object": {"id": 1, "topic": "Test"}},
            pool=None,
            organization_id="org_test",
        )
        assert result.success is False
        assert "設定エラー" in result.message

    @pytest.mark.asyncio
    async def test_missing_org_id_returns_error(self, mock_pool):
        result = await handle_zoom_webhook_event(
            event_type="recording.completed",
            payload={"object": {"id": 1, "topic": "Test"}},
            pool=mock_pool,
            organization_id="",
        )
        assert result.success is False
        assert "設定エラー" in result.message

    @pytest.mark.asyncio
    async def test_recording_completed_calls_zoom_brain_interface(
        self, mock_pool, sample_recording_completed_payload
    ):
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.message = "議事録生成完了"
        mock_result.data = {"meeting_id": "m1"}

        with patch(
            "lib.meetings.zoom_brain_interface.ZoomBrainInterface"
        ) as MockInterface, patch(
            "handlers.zoom_webhook_handler._lookup_calendar_event",
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            "handlers.zoom_webhook_handler._resolve_room_id",
            return_value=DEFAULT_ADMIN_ROOM_ID,
        ):
            instance = MockInterface.return_value
            instance.process_zoom_minutes = AsyncMock(return_value=mock_result)

            result = await handle_zoom_webhook_event(
                event_type="recording.completed",
                payload=sample_recording_completed_payload,
                pool=mock_pool,
                organization_id="org_test",
            )

            assert result.success is True
            instance.process_zoom_minutes.assert_called_once()
            call_kwargs = instance.process_zoom_minutes.call_args[1]
            assert call_kwargs["room_id"] == DEFAULT_ADMIN_ROOM_ID
            assert call_kwargs["account_id"] == SOULKUN_ACCOUNT_ID
            assert call_kwargs["meeting_title"] == "Weekly Standup"
            assert call_kwargs["zoom_meeting_id"] == "12345678"
            assert call_kwargs["zoom_user_email"] == "host@example.com"

    @pytest.mark.asyncio
    async def test_webhook_trigger_recorded_in_data(
        self, mock_pool, sample_recording_completed_payload
    ):
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.message = "OK"
        mock_result.data = {"meeting_id": "m1"}

        with patch(
            "lib.meetings.zoom_brain_interface.ZoomBrainInterface"
        ) as MockInterface, patch(
            "handlers.zoom_webhook_handler._lookup_calendar_event",
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            "handlers.zoom_webhook_handler._resolve_room_id",
            return_value=DEFAULT_ADMIN_ROOM_ID,
        ):
            instance = MockInterface.return_value
            instance.process_zoom_minutes = AsyncMock(return_value=mock_result)

            result = await handle_zoom_webhook_event(
                event_type="recording.completed",
                payload=sample_recording_completed_payload,
                pool=mock_pool,
                organization_id="org_test",
            )

            assert result.data.get("trigger") == "webhook"
            assert result.data.get("webhook_event") == "recording.completed"

    @pytest.mark.asyncio
    async def test_ai_response_func_passed_through(
        self, mock_pool, sample_recording_completed_payload
    ):
        mock_ai = MagicMock()
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.message = "OK"
        mock_result.data = {}

        with patch(
            "lib.meetings.zoom_brain_interface.ZoomBrainInterface"
        ) as MockInterface, patch(
            "handlers.zoom_webhook_handler._lookup_calendar_event",
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            "handlers.zoom_webhook_handler._resolve_room_id",
            return_value=DEFAULT_ADMIN_ROOM_ID,
        ):
            instance = MockInterface.return_value
            instance.process_zoom_minutes = AsyncMock(return_value=mock_result)

            await handle_zoom_webhook_event(
                event_type="recording.completed",
                payload=sample_recording_completed_payload,
                pool=mock_pool,
                organization_id="org_test",
                get_ai_response_func=mock_ai,
            )

            call_kwargs = instance.process_zoom_minutes.call_args[1]
            assert call_kwargs["get_ai_response_func"] is mock_ai

    @pytest.mark.asyncio
    async def test_calendar_event_used_for_routing(
        self, mock_pool, sample_recording_completed_payload
    ):
        """Calendar連携でCW:タグがある場合、room_routerに渡される"""
        from lib.meetings.google_calendar_client import CalendarEvent

        cal_event = CalendarEvent(
            event_id="cal_1",
            title="営業定例会議",
            description="議事録送信先 CW:99887766",
            start_time=None,
            end_time=None,
            attendees=["user1@example.com", "user2@example.com"],
        )

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.message = "OK"
        mock_result.data = {"meeting_id": "m1"}

        with patch(
            "lib.meetings.zoom_brain_interface.ZoomBrainInterface"
        ) as MockInterface, patch(
            "handlers.zoom_webhook_handler._lookup_calendar_event",
            new_callable=AsyncMock,
            return_value=cal_event,
        ), patch(
            "handlers.zoom_webhook_handler._resolve_room_id",
            return_value="99887766",
        ) as mock_resolve:
            instance = MockInterface.return_value
            instance.process_zoom_minutes = AsyncMock(return_value=mock_result)

            result = await handle_zoom_webhook_event(
                event_type="recording.completed",
                payload=sample_recording_completed_payload,
                pool=mock_pool,
                organization_id="org_test",
            )

            assert result.success is True
            # Calendar descriptionがroom resolverに渡されたか
            mock_resolve.assert_called_once_with(
                mock_pool, "org_test", "Weekly Standup", "議事録送信先 CW:99887766"
            )
            # room_idが正しく設定されたか
            call_kwargs = instance.process_zoom_minutes.call_args[1]
            assert call_kwargs["room_id"] == "99887766"
            # カレンダーのタイトルが使われたか
            assert call_kwargs["meeting_title"] == "営業定例会議"
            # attendee_countが記録されたか
            assert result.data.get("attendee_count") == 2
            assert result.data.get("room_resolved_by") == "calendar+router"
