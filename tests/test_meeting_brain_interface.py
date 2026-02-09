# tests/test_meeting_brain_interface.py
"""
MeetingBrainInterface のテスト

ワークフロー、brain_approved=False確認、承認、同意撤回、エラー処理をテスト。
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from lib.brain.models import HandlerResult
from lib.meetings.meeting_brain_interface import MeetingBrainInterface


@pytest.fixture
def mock_pool():
    pool = MagicMock()
    conn = MagicMock()
    pool.connect.return_value.__enter__ = MagicMock(return_value=conn)
    pool.connect.return_value.__exit__ = MagicMock(return_value=None)
    return pool


@pytest.fixture
def interface(mock_pool):
    return MeetingBrainInterface(mock_pool, "org_test")


class TestProcessMeetingUpload:
    @pytest.mark.asyncio
    async def test_success_flow(self, interface):
        """正常フロー: 会議作成→文字起こし→PII除去→DB保存"""
        interface.db.create_meeting = MagicMock(return_value={"id": "m1"})
        interface.db.update_meeting_status = MagicMock(return_value=True)
        interface.db.save_transcript = MagicMock()

        mock_result = MagicMock()
        mock_result.transcript = "田中さんが電話090-1234-5678で連絡しました"
        mock_result.segments = None
        mock_result.speakers = None
        mock_result.speakers_detected = 2
        mock_result.detected_language = "ja"
        mock_result.audio_duration_seconds = 3600
        mock_result.confidence = 0.95

        with patch.object(interface, "_transcribe_audio", new_callable=AsyncMock) as mock_transcribe:
            mock_transcribe.return_value = (
                "田中さんが電話090-1234-5678で連絡しました",
                {"segments": None, "speakers": None, "speakers_count": 2,
                 "language": "ja", "duration": 3600, "confidence": 0.95},
            )

            result = await interface.process_meeting_upload(
                audio_data=b"fake_audio",
                room_id="room1",
                account_id="user1",
                title="テスト会議",
            )

        assert result.success is True
        assert result.data["meeting_id"] == "m1"
        assert result.data["status"] == "transcribed"
        assert result.data["pii_removed_count"] >= 0

    @pytest.mark.asyncio
    async def test_brain_approved_is_false(self, interface):
        """brain_approved=FALSEのまま返却されることを確認（Brain bypass防止）"""
        interface.db.create_meeting = MagicMock(return_value={"id": "m1"})
        interface.db.update_meeting_status = MagicMock(return_value=True)
        interface.db.save_transcript = MagicMock()

        with patch.object(interface, "_transcribe_audio", new_callable=AsyncMock) as mock_transcribe:
            mock_transcribe.return_value = ("テスト", {"language": "ja", "duration": 0, "confidence": 0})

            result = await interface.process_meeting_upload(
                audio_data=b"fake", room_id="r1", account_id="u1",
            )

        # brain_approvedはresult.dataに含まれない（FALSEのまま）
        assert result.success is True
        assert "brain_approved" not in result.data or result.data.get("brain_approved") is not True

    @pytest.mark.asyncio
    async def test_error_sets_failed_status(self, interface):
        """エラー時にステータスをfailedに更新"""
        interface.db.create_meeting = MagicMock(return_value={"id": "m1"})
        interface.db.update_meeting_status = MagicMock(return_value=True)

        with patch.object(interface, "_transcribe_audio", new_callable=AsyncMock) as mock_transcribe:
            mock_transcribe.side_effect = Exception("Whisper API error")

            result = await interface.process_meeting_upload(
                audio_data=b"bad_audio", room_id="r1", account_id="u1",
            )

        assert result.success is False
        assert "失敗" in result.message


class TestApproveAndNotify:
    @pytest.mark.asyncio
    async def test_approve_success(self, interface):
        """Brain承認成功: brain_approved=TRUE"""
        interface.db.get_meeting = MagicMock(return_value={
            "id": "m1", "version": 3, "title": "テスト",
        })
        interface.db.update_meeting_status = MagicMock(return_value=True)

        result = await interface.approve_and_notify("m1")

        assert result.success is True
        assert result.data["brain_approved"] is True

        # update呼び出しを確認
        call_kwargs = interface.db.update_meeting_status.call_args
        assert call_kwargs[1]["brain_approved"] is True

    @pytest.mark.asyncio
    async def test_approve_meeting_not_found(self, interface):
        interface.db.get_meeting = MagicMock(return_value=None)

        result = await interface.approve_and_notify("nonexistent")
        assert result.success is False
        assert "見つかりません" in result.message

    @pytest.mark.asyncio
    async def test_approve_version_conflict(self, interface):
        interface.db.get_meeting = MagicMock(return_value={
            "id": "m1", "version": 3,
        })
        interface.db.update_meeting_status = MagicMock(return_value=False)

        result = await interface.approve_and_notify("m1")
        assert result.success is False
        assert "バージョン競合" in result.message


class TestHandleConsentWithdrawal:
    @pytest.mark.asyncio
    async def test_withdrawal_deletes_meeting(self, interface):
        """同意撤回→カスケード削除"""
        interface.consent.record_consent = MagicMock(return_value=True)
        interface.db.get_recordings_for_meeting = MagicMock(return_value=[])
        interface.db.delete_meeting_cascade = MagicMock(return_value=True)

        result = await interface.handle_consent_withdrawal("m1", "user1")

        assert result.success is True
        assert result.data["deleted"] is True
        interface.consent.record_consent.assert_called_once_with("m1", "user1", "withdrawn")
        interface.db.delete_meeting_cascade.assert_called_once_with("m1")

    @pytest.mark.asyncio
    async def test_withdrawal_deletes_gcs_files(self, interface):
        """同意撤回→GCSファイルも物理削除"""
        interface.consent.record_consent = MagicMock(return_value=True)
        interface.db.get_recordings_for_meeting = MagicMock(return_value=[
            {"id": "r1", "gcs_path": "gs://bucket/file.mp3"},
        ])
        interface.db.delete_meeting_cascade = MagicMock(return_value=True)
        mock_gcs = MagicMock()

        result = await interface.handle_consent_withdrawal("m1", "user1", gcs_client=mock_gcs)

        assert result.success is True
        mock_gcs.bucket.assert_called_once()

    @pytest.mark.asyncio
    async def test_withdrawal_delete_fails(self, interface):
        interface.consent.record_consent = MagicMock(return_value=True)
        interface.db.get_recordings_for_meeting = MagicMock(return_value=[])
        interface.db.delete_meeting_cascade = MagicMock(return_value=False)

        result = await interface.handle_consent_withdrawal("m1", "user1")
        assert result.success is False

    @pytest.mark.asyncio
    async def test_withdrawal_error_returns_handler_result(self, interface):
        """エラー時もHandlerResultを返す（例外がpropagateしない）"""
        interface.consent.record_consent = MagicMock(side_effect=Exception("DB error"))

        result = await interface.handle_consent_withdrawal("m1", "user1")
        assert result.success is False
        assert "error" in result.data


class TestGetMeetingSummary:
    @pytest.mark.asyncio
    async def test_returns_summary(self, interface):
        interface.db.get_meeting = MagicMock(return_value={
            "id": "m1", "title": "週次定例", "status": "completed",
            "meeting_type": "regular", "brain_approved": True,
            "duration_seconds": 3600, "speakers_detected": 3,
        })

        result = await interface.get_meeting_summary("m1")
        assert result.success is True
        assert result.data["title"] == "週次定例"
        assert result.data["brain_approved"] is True

    @pytest.mark.asyncio
    async def test_meeting_not_found(self, interface):
        interface.db.get_meeting = MagicMock(return_value=None)

        result = await interface.get_meeting_summary("nonexistent")
        assert result.success is False


class TestBuildSummaryMessage:
    def test_with_pii(self):
        msg = MeetingBrainInterface._build_summary_message(
            "朝会", "テストテキスト" * 10, 3,
        )
        assert "朝会" in msg
        assert "3件" in msg

    def test_without_pii(self):
        msg = MeetingBrainInterface._build_summary_message(
            "ミーティング", "短いテキスト", 0,
        )
        assert "ミーティング" in msg
        assert "個人情報" not in msg

    def test_long_text_truncated_in_preview(self):
        long_text = "A" * 500
        msg = MeetingBrainInterface._build_summary_message("会議", long_text, 0)
        assert "..." in msg
