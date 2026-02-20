# tests/test_zoom_brain_interface.py
"""
ZoomBrainInterfaceの統合テスト

Author: Claude Opus 4.6
"""

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
    async def test_specific_meeting_id_api_error(self, mock_pool):
        """zoom_meeting_id指定時にAPI例外→None返却→「見つからなかった」"""
        client = MagicMock()
        client.get_meeting_recordings.side_effect = Exception("Zoom 404")

        interface = ZoomBrainInterface(
            mock_pool, "org_test", zoom_client=client
        )
        result = await interface.process_zoom_minutes(
            room_id="room_123",
            account_id="user_456",
            zoom_meeting_id="nonexistent-meeting",
        )
        assert result.success is False
        assert "見つからなかった" in result.message

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
        """Vision 12.2.4: LLMが講義スタイルのプレーンテキスト議事録を生成"""
        def mock_ai_response(messages, system_prompt):
            return (
                "■ 今日の議題について（00:00〜）\n"
                "今日は3つの議題について議論しました。\n\n"
                "■ タスク一覧\n"
                "- [ ] 田中: 見積もり作成"
            )

        interface = ZoomBrainInterface(
            mock_pool, "org_test", zoom_client=mock_zoom_client
        )
        result = await interface.process_zoom_minutes(
            room_id="room_123",
            account_id="user_456",
            get_ai_response_func=mock_ai_response,
        )
        assert result.success is True
        assert "minutes_text" in result.data
        assert "■" in result.data["minutes_text"]
        assert "議題" in result.data["minutes_text"]

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
    async def test_speakers_count_returned_without_names(self, mock_pool, mock_zoom_client):
        """PII保護: 話者名はresult_dataに含めず、人数のみ返す"""
        interface = ZoomBrainInterface(
            mock_pool, "org_test", zoom_client=mock_zoom_client
        )
        result = await interface.process_zoom_minutes(
            room_id="room_123",
            account_id="user_456",
        )
        assert result.success is True
        assert result.data["speakers_detected"] == 2
        assert "speakers" not in result.data  # 話者名リストはPIIのため返さない

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
            return (
                "■ Async議題（00:00〜）\n"
                "非同期AIで生成された議事録です。\n\n"
                "■ タスク一覧\n"
                "- [ ] なし"
            )

        interface = ZoomBrainInterface(
            mock_pool, "org_test", zoom_client=mock_zoom_client
        )
        result = await interface.process_zoom_minutes(
            room_id="room_123",
            account_id="user_456",
            get_ai_response_func=async_ai,
        )
        assert result.success is True
        assert "minutes_text" in result.data
        assert "■" in result.data["minutes_text"]


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


class TestOuterExceptionHandler:
    """process_zoom_minutes の最外 except ブランチ"""

    @pytest.mark.asyncio
    async def test_outer_except_returns_error_result(self, mock_pool, mock_zoom_client):
        """DB create_meeting が例外を投げた場合、catch-all で安全に返る"""
        # dedup check succeeds (no existing)
        conn = MagicMock()
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=False)

        dedup_result = MagicMock()
        dedup_result.mappings.return_value.fetchone.return_value = None

        # create_meeting raises
        conn.execute = MagicMock(
            side_effect=[dedup_result, RuntimeError("DB connection lost")]
        )
        conn.commit = MagicMock()
        mock_pool.connect.return_value = conn

        interface = ZoomBrainInterface(
            mock_pool, "org_test", zoom_client=mock_zoom_client
        )
        result = await interface.process_zoom_minutes(
            room_id="room_123",
            account_id="user_456",
        )
        assert result.success is False
        assert "エラー" in result.message
        assert result.data.get("error") == "RuntimeError"


class TestPiiProtection:
    """raw_transcript は PII 保護のため None で保存する"""

    @pytest.mark.asyncio
    async def test_raw_transcript_not_saved(self, mock_pool, mock_zoom_client):
        """CLAUDE.md §3-2 #8: raw_transcript=None でDB保存される"""
        interface = ZoomBrainInterface(
            mock_pool, "org_test", zoom_client=mock_zoom_client
        )
        result = await interface.process_zoom_minutes(
            room_id="room_123",
            account_id="user_456",
        )
        assert result.success is True

        # save_transcript is the 3rd DB call (dedup, create, save_transcript)
        conn = mock_pool.connect.return_value
        calls = conn.execute.call_args_list
        # save_transcript call params should have raw=None
        save_call_params = calls[2][0][1]  # positional arg [1] = params dict
        assert save_call_params["raw"] is None


class TestSaveMinutesToMemory:
    """Step 12: 議事録をエピソード記憶に保存するテスト"""

    @pytest.mark.asyncio
    async def test_save_called_when_minutes_generated(self, mock_pool, mock_zoom_client):
        """議事録生成後に_save_minutes_to_memoryが呼ばれる"""
        def mock_ai(messages, system_prompt):
            return "■ 議題（00:00〜）\n内容\n\n■ タスク一覧\nなし"

        with patch.object(
            ZoomBrainInterface, "_save_minutes_to_memory", new_callable=AsyncMock
        ) as mock_save:
            interface = ZoomBrainInterface(
                mock_pool, "org_test", zoom_client=mock_zoom_client
            )
            result = await interface.process_zoom_minutes(
                room_id="room_123",
                account_id="user_456",
                get_ai_response_func=mock_ai,
            )
        assert result.success is True
        mock_save.assert_called_once()

    @pytest.mark.asyncio
    async def test_memory_failure_does_not_block_result(
        self, mock_pool, mock_zoom_client
    ):
        """記憶保存失敗でも議事録送信はブロックされない（非クリティカル）"""
        def mock_ai(messages, system_prompt):
            return "■ 議題（00:00〜）\n内容\n\n■ タスク一覧\nなし"

        with patch.object(
            ZoomBrainInterface,
            "_save_minutes_to_memory",
            side_effect=RuntimeError("DB Error"),
        ):
            interface = ZoomBrainInterface(
                mock_pool, "org_test", zoom_client=mock_zoom_client
            )
            result = await interface.process_zoom_minutes(
                room_id="room_123",
                account_id="user_456",
                get_ai_response_func=mock_ai,
            )
        assert result.success is True
        assert "minutes_text" in result.data  # 議事録はちゃんと入っている

    @pytest.mark.asyncio
    async def test_memory_not_called_without_minutes(self, mock_pool, mock_zoom_client):
        """議事録なし（LLM未使用）の場合はメモリ保存しない"""
        with patch.object(
            ZoomBrainInterface, "_save_minutes_to_memory", new_callable=AsyncMock
        ) as mock_save:
            interface = ZoomBrainInterface(
                mock_pool, "org_test", zoom_client=mock_zoom_client
            )
            result = await interface.process_zoom_minutes(
                room_id="room_123",
                account_id="user_456",
                # get_ai_response_func なし → minutes = None
            )
        assert result.success is True
        mock_save.assert_not_called()  # 議事録なしなので呼ばれない

    @pytest.mark.asyncio
    async def test_save_minutes_summary_contains_title(self, mock_pool):
        """サマリーに会議タイトルとタスク数が含まれる"""
        with patch(
            "lib.brain.memory_enhancement.BrainMemoryEnhancement"
        ) as mock_mem_cls:
            mock_mem = MagicMock()
            mock_mem.record_episode = MagicMock()
            mock_mem_cls.return_value = mock_mem

            conn = MagicMock()
            conn.__enter__ = MagicMock(return_value=conn)
            conn.__exit__ = MagicMock(return_value=False)
            conn.commit = MagicMock()
            mock_pool.connect.return_value = conn

            interface = ZoomBrainInterface(
                mock_pool, "00000000-0000-0000-0000-000000000001"
            )
            await interface._save_minutes_to_memory(
                meeting_id="m1",
                title="週次営業MTG",
                room_id="room_1",
                document_url="https://docs.google.com/example",
                duration_seconds=3600.0,
                task_count=3,
            )

        mock_mem.record_episode.assert_called_once()
        kw = mock_mem.record_episode.call_args.kwargs
        assert "週次営業MTG" in kw["summary"]
        assert "タスク3件" in kw["summary"]
        assert "会議" in kw["keywords"]
        assert "議事録" in kw["keywords"]
        # PII保護: details に minutes_text は含まない
        assert "minutes_text" not in kw["details"]

    @pytest.mark.asyncio
    async def test_save_minutes_summary_truncation(self, mock_pool):
        """200文字超のサマリーは切り詰める"""
        with patch(
            "lib.brain.memory_enhancement.BrainMemoryEnhancement"
        ) as mock_mem_cls:
            mock_mem = MagicMock()
            mock_mem.record_episode = MagicMock()
            mock_mem_cls.return_value = mock_mem

            conn = MagicMock()
            conn.__enter__ = MagicMock(return_value=conn)
            conn.__exit__ = MagicMock(return_value=False)
            conn.commit = MagicMock()
            mock_pool.connect.return_value = conn

            long_title = "あ" * 180  # 200文字超になるタイトル
            interface = ZoomBrainInterface(
                mock_pool, "00000000-0000-0000-0000-000000000001"
            )
            await interface._save_minutes_to_memory(
                meeting_id="m1",
                title=long_title,
                room_id="room_1",
                document_url="",
                duration_seconds=1800.0,
                task_count=0,
            )

        kw = mock_mem.record_episode.call_args.kwargs
        assert len(kw["summary"]) <= 200

    @pytest.mark.asyncio
    async def test_save_minutes_entities_include_meeting_and_room(self, mock_pool):
        """関連エンティティにMEETINGとROOMが含まれる"""
        with patch(
            "lib.brain.memory_enhancement.BrainMemoryEnhancement"
        ) as mock_mem_cls:
            mock_mem = MagicMock()
            mock_mem.record_episode = MagicMock()
            mock_mem_cls.return_value = mock_mem

            conn = MagicMock()
            conn.__enter__ = MagicMock(return_value=conn)
            conn.__exit__ = MagicMock(return_value=False)
            conn.commit = MagicMock()
            mock_pool.connect.return_value = conn

            interface = ZoomBrainInterface(
                mock_pool, "00000000-0000-0000-0000-000000000001"
            )
            await interface._save_minutes_to_memory(
                meeting_id="meeting-abc",
                title="朝会",
                room_id="room_999",
                document_url="",
                duration_seconds=600.0,
                task_count=0,
            )

        kw = mock_mem.record_episode.call_args.kwargs
        entities = kw["entities"]
        entity_types = [e.entity_type.value for e in entities]
        assert "meeting" in entity_types
        assert "room" in entity_types
        entity_ids = [e.entity_id for e in entities]
        assert "meeting-abc" in entity_ids
        assert "room_999" in entity_ids


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
