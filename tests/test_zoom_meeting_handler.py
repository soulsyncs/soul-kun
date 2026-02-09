# tests/test_zoom_meeting_handler.py
"""
Zoom議事録ハンドラーのユニットテスト

Author: Claude Opus 4.6
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lib.brain.models import HandlerResult


class TestHandleZoomMeetingMinutes:
    @pytest.mark.asyncio
    async def test_missing_pool_returns_error(self):
        from handlers.zoom_meeting_handler import handle_zoom_meeting_minutes

        result = await handle_zoom_meeting_minutes(
            room_id="room_1",
            account_id="acc_1",
            sender_name="Test User",
            params={},
            pool=None,
            organization_id="org_test",
        )
        assert result.success is False
        assert "システム設定エラー" in result.message

    @pytest.mark.asyncio
    async def test_missing_org_id_returns_error(self):
        from handlers.zoom_meeting_handler import handle_zoom_meeting_minutes

        result = await handle_zoom_meeting_minutes(
            room_id="room_1",
            account_id="acc_1",
            sender_name="Test User",
            params={},
            pool=MagicMock(),
            organization_id="",
        )
        assert result.success is False
        assert "システム設定エラー" in result.message

    @pytest.mark.asyncio
    async def test_delegates_to_zoom_brain_interface(self):
        from handlers.zoom_meeting_handler import handle_zoom_meeting_minutes

        mock_result = HandlerResult(
            success=True,
            message="議事録完了",
            data={"meeting_id": "m1"},
        )

        with patch(
            "lib.meetings.zoom_brain_interface.ZoomBrainInterface"
        ) as MockInterface:
            mock_instance = MagicMock()
            mock_instance.process_zoom_minutes = AsyncMock(
                return_value=mock_result
            )
            MockInterface.return_value = mock_instance

            result = await handle_zoom_meeting_minutes(
                room_id="room_1",
                account_id="acc_1",
                sender_name="Test User",
                params={"meeting_title": "テスト会議"},
                pool=MagicMock(),
                organization_id="org_test",
            )

            assert result.success is True
            assert result.message == "議事録完了"

    @pytest.mark.asyncio
    async def test_params_forwarded_correctly(self):
        from handlers.zoom_meeting_handler import handle_zoom_meeting_minutes

        mock_result = HandlerResult(
            success=True, message="ok", data={}
        )

        with patch(
            "lib.meetings.zoom_brain_interface.ZoomBrainInterface"
        ) as MockInterface:
            mock_instance = MagicMock()
            mock_instance.process_zoom_minutes = AsyncMock(
                return_value=mock_result
            )
            MockInterface.return_value = mock_instance

            await handle_zoom_meeting_minutes(
                room_id="room_1",
                account_id="acc_1",
                sender_name="Test User",
                params={
                    "meeting_title": "定例",
                    "zoom_meeting_id": "zm123",
                    "zoom_user_email": "user@example.com",
                },
                pool=MagicMock(),
                organization_id="org_test",
            )

            call_kwargs = mock_instance.process_zoom_minutes.call_args[1]
            assert call_kwargs["meeting_title"] == "定例"
            assert call_kwargs["zoom_meeting_id"] == "zm123"
            assert call_kwargs["zoom_user_email"] == "user@example.com"

    @pytest.mark.asyncio
    async def test_get_ai_response_func_passed(self):
        from handlers.zoom_meeting_handler import handle_zoom_meeting_minutes

        mock_result = HandlerResult(
            success=True, message="ok", data={}
        )
        mock_ai_func = MagicMock()

        with patch(
            "lib.meetings.zoom_brain_interface.ZoomBrainInterface"
        ) as MockInterface:
            mock_instance = MagicMock()
            mock_instance.process_zoom_minutes = AsyncMock(
                return_value=mock_result
            )
            MockInterface.return_value = mock_instance

            await handle_zoom_meeting_minutes(
                room_id="room_1",
                account_id="acc_1",
                sender_name="Test User",
                params={},
                pool=MagicMock(),
                organization_id="org_test",
                get_ai_response_func=mock_ai_func,
            )

            call_kwargs = mock_instance.process_zoom_minutes.call_args[1]
            assert call_kwargs["get_ai_response_func"] is mock_ai_func
