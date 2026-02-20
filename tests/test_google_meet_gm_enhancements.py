# tests/test_google_meet_gm_enhancements.py
"""
Google Meet GM①②③強化テスト

GM①: タスク自動抽出 + 3点セットメッセージ
GM②: ソウルくん記憶保存
GM③: 送信失敗→管理者通知（将来対応）

NOTE: langfuse/Python 3.14非互換のため、ローカルでは --collect-only が失敗する。
      CI（Python 3.11）で実行されることを前提としている。

Author: Claude Sonnet 4.6
Created: 2026-02-20
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lib.brain.models import HandlerResult
from lib.meetings.google_meet_brain_interface import GoogleMeetBrainInterface
from lib.meetings.google_meet_drive_client import MeetRecordingFile
from lib.meetings.task_extractor import TaskExtractionResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def org_id():
    return "org-uuid-abc-123"


@pytest.fixture
def mock_pool(org_id):
    pool = MagicMock()
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)

    # create_meeting returns
    create_result = MagicMock()
    create_result.mappings.return_value.fetchone.return_value = {
        "id": "meet-id-001",
        "status": "pending",
    }
    # save_transcript returns
    save_result = MagicMock()
    save_result.mappings.return_value.fetchone.return_value = {
        "id": "transcript-id-001",
    }
    # update_meeting_status
    update_result = MagicMock()
    update_result.rowcount = 1

    conn.execute = MagicMock(side_effect=[create_result, save_result, update_result])
    conn.commit = MagicMock()
    pool.connect.return_value.__enter__ = MagicMock(return_value=conn)
    pool.connect.return_value.__exit__ = MagicMock(return_value=False)
    pool.connect.return_value = conn
    return pool


@pytest.fixture
def mock_recording():
    return MeetRecordingFile(
        file_id="drive-file-001",
        name="週次定例 (2026-02-20 at 10:00 GMT).mp4",
        created_time=None,
        size_bytes=1024 * 1024,
        web_view_link="https://drive.google.com/file/d/drive-file-001/view",
    )


@pytest.fixture
def interface(mock_pool, org_id):
    return GoogleMeetBrainInterface(pool=mock_pool, organization_id=org_id)


# ---------------------------------------------------------------------------
# GM①: _build_delivery_message()
# ---------------------------------------------------------------------------

class TestBuildDeliveryMessage:
    """3点セットメッセージの組み立てテスト"""

    def test_message_contains_title(self):
        msg = GoogleMeetBrainInterface._build_delivery_message(
            title="週次定例",
            minutes_text="議事録本文です",
        )
        assert "週次定例" in msg

    def test_message_contains_drive_url(self):
        drive_url = "https://drive.google.com/file/d/abc/view"
        msg = GoogleMeetBrainInterface._build_delivery_message(
            title="テスト会議",
            minutes_text="本文",
            drive_url=drive_url,
        )
        assert drive_url in msg
        assert "録画" in msg

    def test_message_without_drive_url(self):
        msg = GoogleMeetBrainInterface._build_delivery_message(
            title="テスト",
            minutes_text="本文",
            drive_url=None,
        )
        # URLなしでも録画行が出ないこと
        assert "drive.google.com" not in msg

    def test_message_with_task_result(self):
        task_result = TaskExtractionResult()
        task_result.total_extracted = 3
        task_result.total_created = 3
        task_result.total_unassigned = 0

        msg = GoogleMeetBrainInterface._build_delivery_message(
            title="会議A",
            minutes_text="本文",
            task_result=task_result,
        )
        assert "タスク: 3件作成" in msg

    def test_message_with_unassigned_tasks(self):
        task_result = TaskExtractionResult()
        task_result.total_extracted = 5
        task_result.total_created = 3
        task_result.total_unassigned = 2

        msg = GoogleMeetBrainInterface._build_delivery_message(
            title="会議B",
            minutes_text="本文",
            task_result=task_result,
        )
        assert "担当者不明: 2件" in msg

    def test_message_no_task_section_when_no_tasks(self):
        task_result = TaskExtractionResult()
        task_result.total_extracted = 0

        msg = GoogleMeetBrainInterface._build_delivery_message(
            title="会議C",
            minutes_text="本文",
            task_result=task_result,
        )
        assert "タスク" not in msg

    def test_message_chatwork_format(self):
        msg = GoogleMeetBrainInterface._build_delivery_message(
            title="会議",
            minutes_text="内容",
        )
        assert "[info]" in msg
        assert "[/info]" in msg
        assert "[title]" in msg
        assert "[/title]" in msg


# ---------------------------------------------------------------------------
# GM①: タスク自動抽出が呼ばれるか
# ---------------------------------------------------------------------------

class TestTaskExtractionInProcessMinutes:
    """process_google_meet_minutes()でタスク抽出が呼ばれることを確認"""

    @pytest.mark.asyncio
    async def test_task_extraction_called_when_minutes_generated(
        self, interface, mock_pool, mock_recording
    ):
        """議事録生成成功時にextract_and_create_tasksが呼ばれること"""
        minutes_text = "会議の議事録です。田中さんが○○を担当します。"

        with patch.object(
            interface,
            "_get_drive_client",
            return_value=MagicMock(
                find_recent_recordings=MagicMock(return_value=[mock_recording]),
            ),
        ), patch.object(
            interface,
            "_get_transcript",
            new=AsyncMock(return_value="文字起こし本文"),
        ), patch.object(
            interface,
            "_generate_minutes_text",
            new=AsyncMock(return_value=minutes_text),
        ), patch(
            "lib.meetings.google_meet_brain_interface.extract_and_create_tasks",
            new=AsyncMock(return_value=TaskExtractionResult()),
        ) as mock_extract, patch.object(
            interface,
            "_save_minutes_to_memory",
            new=AsyncMock(),
        ):
            result = await interface.process_google_meet_minutes(
                room_id="12345",
                account_id="acc-001",
                get_ai_response_func=MagicMock(),
            )

        assert result.success is True
        mock_extract.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_task_extraction_skipped_without_minutes(
        self, interface, mock_pool, mock_recording
    ):
        """議事録生成が失敗した場合タスク抽出はスキップされること"""
        with patch.object(
            interface,
            "_get_drive_client",
            return_value=MagicMock(
                find_recent_recordings=MagicMock(return_value=[mock_recording]),
            ),
        ), patch.object(
            interface,
            "_get_transcript",
            new=AsyncMock(return_value="文字起こし"),
        ), patch.object(
            interface,
            "_generate_minutes_text",
            new=AsyncMock(return_value=None),  # 議事録生成失敗
        ), patch(
            "lib.meetings.google_meet_brain_interface.extract_and_create_tasks",
            new=AsyncMock(return_value=TaskExtractionResult()),
        ) as mock_extract, patch.object(
            interface,
            "_save_minutes_to_memory",
            new=AsyncMock(),
        ):
            result = await interface.process_google_meet_minutes(
                room_id="12345",
                account_id="acc-001",
                get_ai_response_func=MagicMock(),
            )

        # タスク抽出は呼ばれないこと
        mock_extract.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_task_extraction_failure_does_not_block_result(
        self, interface, mock_pool, mock_recording
    ):
        """タスク抽出が失敗しても議事録結果を返すこと"""
        with patch.object(
            interface,
            "_get_drive_client",
            return_value=MagicMock(
                find_recent_recordings=MagicMock(return_value=[mock_recording]),
            ),
        ), patch.object(
            interface,
            "_get_transcript",
            new=AsyncMock(return_value="文字起こし"),
        ), patch.object(
            interface,
            "_generate_minutes_text",
            new=AsyncMock(return_value="議事録テキスト"),
        ), patch(
            "lib.meetings.google_meet_brain_interface.extract_and_create_tasks",
            new=AsyncMock(side_effect=RuntimeError("DB Error")),
        ), patch.object(
            interface,
            "_save_minutes_to_memory",
            new=AsyncMock(),
        ):
            result = await interface.process_google_meet_minutes(
                room_id="12345",
                account_id="acc-001",
                get_ai_response_func=MagicMock(),
            )

        # エラーが出ても成功として返ること
        assert result.success is True


# ---------------------------------------------------------------------------
# GM②: ソウルくん記憶保存
# ---------------------------------------------------------------------------

class TestSaveMinutesToMemoryGoogleMeet:
    """_save_minutes_to_memory()のテスト（GM②）"""

    @pytest.mark.asyncio
    async def test_memory_save_called_when_minutes_generated(
        self, interface, mock_pool, mock_recording
    ):
        """議事録生成成功時に記憶保存が呼ばれること"""
        with patch.object(
            interface,
            "_get_drive_client",
            return_value=MagicMock(
                find_recent_recordings=MagicMock(return_value=[mock_recording]),
            ),
        ), patch.object(
            interface,
            "_get_transcript",
            new=AsyncMock(return_value="文字起こし"),
        ), patch.object(
            interface,
            "_generate_minutes_text",
            new=AsyncMock(return_value="議事録テキスト"),
        ), patch(
            "lib.meetings.google_meet_brain_interface.extract_and_create_tasks",
            new=AsyncMock(return_value=TaskExtractionResult()),
        ), patch.object(
            interface,
            "_save_minutes_to_memory",
            new=AsyncMock(),
        ) as mock_memory:
            await interface.process_google_meet_minutes(
                room_id="12345",
                account_id="acc-001",
                get_ai_response_func=MagicMock(),
            )

        mock_memory.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_memory_save_failure_does_not_block_result(
        self, interface, mock_pool, mock_recording
    ):
        """記憶保存が失敗しても議事録結果を返すこと"""
        with patch.object(
            interface,
            "_get_drive_client",
            return_value=MagicMock(
                find_recent_recordings=MagicMock(return_value=[mock_recording]),
            ),
        ), patch.object(
            interface,
            "_get_transcript",
            new=AsyncMock(return_value="文字起こし"),
        ), patch.object(
            interface,
            "_generate_minutes_text",
            new=AsyncMock(return_value="議事録テキスト"),
        ), patch(
            "lib.meetings.google_meet_brain_interface.extract_and_create_tasks",
            new=AsyncMock(return_value=TaskExtractionResult()),
        ), patch.object(
            interface,
            "_save_minutes_to_memory",
            new=AsyncMock(side_effect=RuntimeError("Memory DB Error")),
        ):
            result = await interface.process_google_meet_minutes(
                room_id="12345",
                account_id="acc-001",
                get_ai_response_func=MagicMock(),
            )

        # 記憶保存失敗でも成功として返ること
        assert result.success is True

    @pytest.mark.asyncio
    async def test_memory_not_called_without_minutes(
        self, interface, mock_pool, mock_recording
    ):
        """議事録生成失敗時は記憶保存が呼ばれないこと"""
        with patch.object(
            interface,
            "_get_drive_client",
            return_value=MagicMock(
                find_recent_recordings=MagicMock(return_value=[mock_recording]),
            ),
        ), patch.object(
            interface,
            "_get_transcript",
            new=AsyncMock(return_value="文字起こし"),
        ), patch.object(
            interface,
            "_generate_minutes_text",
            new=AsyncMock(return_value=None),
        ), patch.object(
            interface,
            "_save_minutes_to_memory",
            new=AsyncMock(),
        ) as mock_memory:
            await interface.process_google_meet_minutes(
                room_id="12345",
                account_id="acc-001",
                get_ai_response_func=MagicMock(),
            )

        mock_memory.assert_not_awaited()

    def test_memory_summary_contains_google_meet(self, interface, mock_pool, org_id):
        """_save_minutes_to_memory のサマリーに Google Meet が含まれること"""
        # 静的解析: _save_minutes_to_memoryのsummaryパターン確認
        # (BrainMemoryEnhancementをモックして実行)
        import asyncio

        with patch(
            "lib.brain.memory_enhancement.BrainMemoryEnhancement"
        ) as MockMem:
            mock_mem_inst = MagicMock()
            MockMem.return_value = mock_mem_inst
            conn_mock = MagicMock()
            mock_pool.connect.return_value.__enter__ = MagicMock(return_value=conn_mock)
            mock_pool.connect.return_value.__exit__ = MagicMock(return_value=False)

            asyncio.get_event_loop().run_until_complete(
                interface._save_minutes_to_memory(
                    meeting_id="m001",
                    title="週次定例",
                    room_id="12345",
                    drive_url="https://drive.google.com/test",
                    task_count=2,
                )
            )

        # record_episodeが呼ばれていること
        mock_mem_inst.record_episode.assert_called_once()
        call_kwargs = mock_mem_inst.record_episode.call_args[1]
        # summaryに Google Meet が含まれること
        assert "Google Meet" in call_kwargs["summary"]
        # detailsに source=google_meet が含まれること
        assert call_kwargs["details"]["source"] == "google_meet"
        # タスク数が反映されていること
        assert call_kwargs["details"]["task_count"] == 2
