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
        """正常フロー: 会議作成→GCSアップロード→文字起こし→PII除去→DB保存"""
        interface.db.create_meeting = MagicMock(return_value={"id": "m1"})
        interface.db.update_meeting_status = MagicMock(return_value=True)
        interface.db.save_transcript = MagicMock()
        interface.db.save_recording = MagicMock()

        with patch.object(interface, "_transcribe_audio", new_callable=AsyncMock) as mock_transcribe, \
             patch.object(interface, "_upload_audio_to_gcs", new_callable=AsyncMock) as mock_gcs:
            mock_transcribe.return_value = (
                "田中さんが電話090-1234-5678で連絡しました",
                {"segments": None, "speakers": None, "speakers_count": 2,
                 "language": "ja", "duration": 3600, "confidence": 0.95},
            )
            mock_gcs.return_value = None  # GCSバケット未設定

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
        interface.db.save_recording.assert_not_called()

    @pytest.mark.asyncio
    async def test_success_flow_with_gcs(self, interface):
        """正常フロー（GCS有効）: 音声GCSアップロード + DB録音レコード保存"""
        interface.db.create_meeting = MagicMock(return_value={"id": "m1"})
        interface.db.update_meeting_status = MagicMock(return_value=True)
        interface.db.save_transcript = MagicMock()
        interface.db.save_recording = MagicMock()

        with patch.object(interface, "_transcribe_audio", new_callable=AsyncMock) as mock_transcribe, \
             patch.object(interface, "_upload_audio_to_gcs", new_callable=AsyncMock) as mock_gcs:
            mock_transcribe.return_value = (
                "テスト文字起こし",
                {"language": "ja", "duration": 600, "confidence": 0.9},
            )
            mock_gcs.return_value = "gs://soulkun-meeting-recordings/org_test/m1/audio.mp3"

            result = await interface.process_meeting_upload(
                audio_data=b"fake_audio",
                room_id="room1",
                account_id="user1",
                title="朝会",
            )

        assert result.success is True
        interface.db.save_recording.assert_called_once()
        call_kwargs = interface.db.save_recording.call_args[1]
        assert call_kwargs["meeting_id"] == "m1"
        assert "gs://soulkun-meeting-recordings" in call_kwargs["gcs_path"]

    @pytest.mark.asyncio
    async def test_brain_approved_is_false(self, interface):
        """brain_approved=FALSEのまま返却されることを確認（Brain bypass防止）"""
        interface.db.create_meeting = MagicMock(return_value={"id": "m1"})
        interface.db.update_meeting_status = MagicMock(return_value=True)
        interface.db.save_transcript = MagicMock()

        with patch.object(interface, "_transcribe_audio", new_callable=AsyncMock) as mock_transcribe, \
             patch.object(interface, "_upload_audio_to_gcs", new_callable=AsyncMock) as mock_gcs:
            mock_transcribe.return_value = ("テスト", {"language": "ja", "duration": 0, "confidence": 0})
            mock_gcs.return_value = None

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

        with patch.object(interface, "_transcribe_audio", new_callable=AsyncMock) as mock_transcribe, \
             patch.object(interface, "_upload_audio_to_gcs", new_callable=AsyncMock) as mock_gcs:
            mock_transcribe.side_effect = Exception("Speech-to-Text API error")
            mock_gcs.return_value = None

            result = await interface.process_meeting_upload(
                audio_data=b"bad_audio", room_id="r1", account_id="u1",
            )

        assert result.success is False
        assert "失敗" in result.message


class TestProcessMeetingUploadWithMinutes:
    """get_ai_response_func付きの議事録自動生成テスト（Phase C MVP1）"""

    @pytest.mark.asyncio
    async def test_minutes_generated_when_func_provided(self, interface):
        """get_ai_response_funcがあれば議事録を生成"""
        interface.db.create_meeting = MagicMock(return_value={"id": "m1"})
        interface.db.update_meeting_status = MagicMock(return_value=True)
        interface.db.save_transcript = MagicMock()

        mock_llm = AsyncMock(return_value="■ 主題1（序盤〜）\nテスト議事録内容\n\n■ タスク一覧\n- [ ] 担当: タスク")

        with patch.object(interface, "_transcribe_audio", new_callable=AsyncMock) as mock_transcribe, \
             patch.object(interface, "_upload_audio_to_gcs", new_callable=AsyncMock) as mock_gcs:
            mock_transcribe.return_value = (
                "テスト文字起こし",
                {"language": "ja", "duration": 600, "confidence": 0.9},
            )
            mock_gcs.return_value = None

            result = await interface.process_meeting_upload(
                audio_data=b"fake_audio",
                room_id="room1",
                account_id="user1",
                title="朝会",
                get_ai_response_func=mock_llm,
                enable_minutes=True,
            )

        assert result.success is True
        assert "minutes_text" in result.data
        assert "[info]" in result.data["minutes_text"]
        assert "朝会 - 議事録" in result.data["minutes_text"]
        # message にも議事録が入る
        assert "[info]" in result.message
        mock_llm.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_minutes_without_func(self, interface):
        """get_ai_response_funcがなければ従来通り文字起こしのみ"""
        interface.db.create_meeting = MagicMock(return_value={"id": "m1"})
        interface.db.update_meeting_status = MagicMock(return_value=True)
        interface.db.save_transcript = MagicMock()

        with patch.object(interface, "_transcribe_audio", new_callable=AsyncMock) as mock_transcribe, \
             patch.object(interface, "_upload_audio_to_gcs", new_callable=AsyncMock) as mock_gcs:
            mock_transcribe.return_value = (
                "テスト文字起こし",
                {"language": "ja", "duration": 600, "confidence": 0.9},
            )
            mock_gcs.return_value = None

            result = await interface.process_meeting_upload(
                audio_data=b"fake_audio",
                room_id="room1",
                account_id="user1",
                title="朝会",
            )

        assert result.success is True
        assert "minutes_text" not in result.data
        assert "文字起こしが完了しました" in result.message

    @pytest.mark.asyncio
    async def test_minutes_failure_falls_back_to_transcript(self, interface):
        """LLM失敗時は文字起こし結果にフォールバック"""
        interface.db.create_meeting = MagicMock(return_value={"id": "m1"})
        interface.db.update_meeting_status = MagicMock(return_value=True)
        interface.db.save_transcript = MagicMock()

        mock_llm = AsyncMock(side_effect=Exception("LLM API error"))

        with patch.object(interface, "_transcribe_audio", new_callable=AsyncMock) as mock_transcribe, \
             patch.object(interface, "_upload_audio_to_gcs", new_callable=AsyncMock) as mock_gcs:
            mock_transcribe.return_value = (
                "テスト文字起こし",
                {"language": "ja", "duration": 600, "confidence": 0.9},
            )
            mock_gcs.return_value = None

            result = await interface.process_meeting_upload(
                audio_data=b"fake_audio",
                room_id="room1",
                account_id="user1",
                title="朝会",
                get_ai_response_func=mock_llm,
                enable_minutes=True,
            )

        assert result.success is True
        assert "minutes_text" not in result.data
        assert "文字起こしが完了しました" in result.message

    @pytest.mark.asyncio
    async def test_minutes_empty_response_falls_back(self, interface):
        """LLMが空レスポンスを返した場合もフォールバック"""
        interface.db.create_meeting = MagicMock(return_value={"id": "m1"})
        interface.db.update_meeting_status = MagicMock(return_value=True)
        interface.db.save_transcript = MagicMock()

        mock_llm = AsyncMock(return_value="")

        with patch.object(interface, "_transcribe_audio", new_callable=AsyncMock) as mock_transcribe, \
             patch.object(interface, "_upload_audio_to_gcs", new_callable=AsyncMock) as mock_gcs:
            mock_transcribe.return_value = (
                "テスト文字起こし",
                {"language": "ja", "duration": 600, "confidence": 0.9},
            )
            mock_gcs.return_value = None

            result = await interface.process_meeting_upload(
                audio_data=b"fake_audio",
                room_id="room1",
                account_id="user1",
                title="朝会",
                get_ai_response_func=mock_llm,
                enable_minutes=True,
            )

        assert result.success is True
        assert "minutes_text" not in result.data

    @pytest.mark.asyncio
    async def test_no_minutes_when_enable_minutes_false(self, interface):
        """enable_minutes=Falseならget_ai_response_funcがあっても議事録生成しない"""
        interface.db.create_meeting = MagicMock(return_value={"id": "m1"})
        interface.db.update_meeting_status = MagicMock(return_value=True)
        interface.db.save_transcript = MagicMock()

        mock_llm = AsyncMock(return_value="議事録テキスト")

        with patch.object(interface, "_transcribe_audio", new_callable=AsyncMock) as mock_transcribe, \
             patch.object(interface, "_upload_audio_to_gcs", new_callable=AsyncMock) as mock_gcs:
            mock_transcribe.return_value = (
                "テスト文字起こし",
                {"language": "ja", "duration": 600, "confidence": 0.9},
            )
            mock_gcs.return_value = None

            result = await interface.process_meeting_upload(
                audio_data=b"fake_audio",
                room_id="room1",
                account_id="user1",
                title="朝会",
                get_ai_response_func=mock_llm,
                enable_minutes=False,
            )

        assert result.success is True
        assert "minutes_text" not in result.data
        assert "文字起こしが完了しました" in result.message
        mock_llm.assert_not_called()


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


class TestUploadAudioToGcs:
    @pytest.mark.asyncio
    async def test_skips_when_no_bucket_env(self, interface):
        """MEETING_GCS_BUCKET未設定時はNone返却"""
        with patch.dict("os.environ", {}, clear=False):
            # 明示的にMEETING_GCS_BUCKETを消す
            import os
            old = os.environ.pop("MEETING_GCS_BUCKET", None)
            try:
                result = await interface._upload_audio_to_gcs("m1", b"data")
                assert result is None
            finally:
                if old is not None:
                    os.environ["MEETING_GCS_BUCKET"] = old

    @pytest.mark.asyncio
    async def test_uploads_when_bucket_set(self, interface):
        """MEETING_GCS_BUCKET設定時はGCSアップロード実行"""
        with patch.dict("os.environ", {"MEETING_GCS_BUCKET": "test-bucket"}):
            with patch("asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
                mock_thread.return_value = None
                result = await interface._upload_audio_to_gcs("m1", b"fake_mp3")

        assert result is not None
        assert "gs://test-bucket/org_test/m1/" in result

    @pytest.mark.asyncio
    async def test_gcs_failure_returns_none(self, interface):
        """GCSアップロード失敗時はNone返却（文字起こしは継続）"""
        with patch.dict("os.environ", {"MEETING_GCS_BUCKET": "test-bucket"}):
            with patch("asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
                mock_thread.side_effect = Exception("GCS unavailable")
                result = await interface._upload_audio_to_gcs("m1", b"data")

        assert result is None


class TestDetectAudioFormat:
    def test_mp3_id3(self):
        assert MeetingBrainInterface._detect_audio_format(b"ID3\x04\x00") == "mp3"

    def test_mp3_sync(self):
        assert MeetingBrainInterface._detect_audio_format(b"\xff\xfb\x90\x00") == "mp3"

    def test_wav(self):
        assert MeetingBrainInterface._detect_audio_format(b"RIFF\x00\x00") == "wav"

    def test_flac(self):
        assert MeetingBrainInterface._detect_audio_format(b"fLaC\x00\x00") == "flac"

    def test_ogg(self):
        assert MeetingBrainInterface._detect_audio_format(b"OggS\x00\x00") == "ogg"

    def test_unknown_defaults_to_mp3(self):
        assert MeetingBrainInterface._detect_audio_format(b"\x00\x00\x00\x00") == "mp3"

    def test_empty_bytes_defaults_to_mp3(self):
        assert MeetingBrainInterface._detect_audio_format(b"") == "mp3"


class TestTranscribeAudioSpeechToText:
    """Google Cloud Speech-to-Text 統合テスト"""

    @pytest.mark.asyncio
    async def test_uses_gcs_uri_for_long_running(self, interface):
        """GCS URIがある場合はlong_running_recognizeを使用"""
        mock_response = MagicMock()
        mock_alt = MagicMock()
        mock_alt.transcript = "テスト文字起こし結果"
        mock_alt.confidence = 0.92
        mock_result = MagicMock()
        mock_result.alternatives = [mock_alt]
        mock_response.results = [mock_result]

        mock_client = MagicMock()
        mock_operation = MagicMock()
        mock_operation.result.return_value = mock_response
        mock_client.long_running_recognize.return_value = mock_operation

        with patch("asyncio.to_thread") as mock_thread:
            # asyncio.to_threadに渡された関数を同期実行する
            async def run_func(func, *args, **kwargs):
                return func(*args, **kwargs)
            mock_thread.side_effect = lambda fn: fn()

            with patch("google.cloud.speech.SpeechClient", return_value=mock_client):
                text, meta = await interface._transcribe_audio(
                    b"data", gcs_uri="gs://bucket/audio.mp3",
                )

        assert text == "テスト文字起こし結果"
        assert meta["confidence"] == pytest.approx(0.92)
        mock_client.long_running_recognize.assert_called_once()

    @pytest.mark.asyncio
    async def test_uses_inline_without_gcs_uri(self, interface):
        """GCS URIがない場合はrecognize（インライン）を使用"""
        mock_response = MagicMock()
        mock_alt = MagicMock()
        mock_alt.transcript = "短い音声"
        mock_alt.confidence = 0.88
        mock_result = MagicMock()
        mock_result.alternatives = [mock_alt]
        mock_response.results = [mock_result]

        mock_client = MagicMock()
        mock_client.recognize.return_value = mock_response

        with patch("asyncio.to_thread") as mock_thread:
            mock_thread.side_effect = lambda fn: fn()

            with patch("google.cloud.speech.SpeechClient", return_value=mock_client):
                text, meta = await interface._transcribe_audio(b"short_audio")

        assert text == "短い音声"
        mock_client.recognize.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_response_returns_empty_string(self, interface):
        """Speech APIが空結果を返した場合"""
        mock_response = MagicMock()
        mock_response.results = []

        mock_client = MagicMock()
        mock_client.recognize.return_value = mock_response

        with patch("asyncio.to_thread") as mock_thread:
            mock_thread.side_effect = lambda fn: fn()

            with patch("google.cloud.speech.SpeechClient", return_value=mock_client):
                text, meta = await interface._transcribe_audio(b"silence")

        assert text == ""
        assert meta["confidence"] == 0.0
