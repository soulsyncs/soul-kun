# tests/test_meeting_handler.py
"""
meeting_handler のテスト

ハンドラーディスパッチ、バリデーション、エラー処理をテスト。
"""

import importlib.util
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from lib.brain.models import HandlerResult

# handlers/ namespace collision回避（chatwork-webhook/handlers/と衝突するため）
_handler_path = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "handlers", "meeting_handler.py",
)
_spec = importlib.util.spec_from_file_location("meeting_handler", _handler_path)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
handle_meeting_upload = _mod.handle_meeting_upload
handle_meeting_status = _mod.handle_meeting_status


class TestHandleMeetingUpload:
    @pytest.mark.asyncio
    async def test_missing_pool_returns_error(self):
        result = await handle_meeting_upload(
            room_id="r1", account_id="u1", sender_name="テスト",
            params={"audio_data": b"data"},
            pool=None, organization_id="org1",
        )
        assert result.success is False
        assert "システム設定エラー" in result.message

    @pytest.mark.asyncio
    async def test_missing_org_id_returns_error(self):
        result = await handle_meeting_upload(
            room_id="r1", account_id="u1", sender_name="テスト",
            params={"audio_data": b"data"},
            pool=MagicMock(), organization_id="",
        )
        assert result.success is False

    @pytest.mark.asyncio
    async def test_missing_audio_data_returns_error(self):
        result = await handle_meeting_upload(
            room_id="r1", account_id="u1", sender_name="テスト",
            params={},
            pool=MagicMock(), organization_id="org1",
        )
        assert result.success is False
        assert "音声データ" in result.message

    @pytest.mark.asyncio
    async def test_delegates_to_brain_interface(self):
        mock_pool = MagicMock()
        expected_result = HandlerResult(
            success=True,
            message="完了",
            data={"meeting_id": "m1"},
        )

        with patch(
            "lib.meetings.meeting_brain_interface.MeetingBrainInterface"
        ) as MockInterface:
            instance = MockInterface.return_value
            instance.process_meeting_upload = AsyncMock(return_value=expected_result)

            result = await handle_meeting_upload(
                room_id="r1", account_id="u1", sender_name="テスト",
                params={"audio_data": b"data", "meeting_title": "朝会"},
                pool=mock_pool, organization_id="org1",
            )

        assert result.success is True
        assert result.data["meeting_id"] == "m1"
        MockInterface.assert_called_once_with(mock_pool, "org1")

    @pytest.mark.asyncio
    async def test_audio_file_param_fallback(self):
        """audio_dataがなくてもaudio_fileで受け付ける"""
        mock_pool = MagicMock()
        expected_result = HandlerResult(success=True, message="ok", data={})

        with patch(
            "lib.meetings.meeting_brain_interface.MeetingBrainInterface"
        ) as MockInterface:
            instance = MockInterface.return_value
            instance.process_meeting_upload = AsyncMock(return_value=expected_result)

            result = await handle_meeting_upload(
                room_id="r1", account_id="u1", sender_name="テスト",
                params={"audio_file": b"data"},
                pool=mock_pool, organization_id="org1",
            )

        assert result.success is True


class TestHandleMeetingStatus:
    @pytest.mark.asyncio
    async def test_missing_pool_returns_error(self):
        result = await handle_meeting_status(
            room_id="r1", account_id="u1", sender_name="テスト",
            params={"meeting_id": "m1"},
            pool=None, organization_id="org1",
        )
        assert result.success is False

    @pytest.mark.asyncio
    async def test_missing_meeting_id_returns_error(self):
        result = await handle_meeting_status(
            room_id="r1", account_id="u1", sender_name="テスト",
            params={},
            pool=MagicMock(), organization_id="org1",
        )
        assert result.success is False
        assert "会議ID" in result.message

    @pytest.mark.asyncio
    async def test_delegates_to_brain_interface(self):
        mock_pool = MagicMock()
        expected_result = HandlerResult(
            success=True,
            message="会議情報",
            data={"status": "completed"},
        )

        with patch(
            "lib.meetings.meeting_brain_interface.MeetingBrainInterface"
        ) as MockInterface:
            instance = MockInterface.return_value
            instance.get_meeting_summary = AsyncMock(return_value=expected_result)

            result = await handle_meeting_status(
                room_id="r1", account_id="u1", sender_name="テスト",
                params={"meeting_id": "m1"},
                pool=mock_pool, organization_id="org1",
            )

        assert result.success is True
        assert result.data["status"] == "completed"
