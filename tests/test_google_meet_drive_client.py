# tests/test_google_meet_drive_client.py
"""
Google Meet Drive クライアントのユニットテスト

Author: Claude Sonnet 4.6
Created: 2026-02-19
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, call

import pytest

from lib.meetings.google_meet_drive_client import (
    GoogleMeetDriveClient,
    MeetRecordingFile,
    MEET_RECORDING_MIME_TYPE,
    MEET_RECORDINGS_FOLDER_NAME,
    MAX_DOWNLOAD_BYTES,
    create_meet_drive_client_from_db,
)
from lib.meetings.google_meet_brain_interface import GoogleMeetBrainInterface


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def drive_client():
    """OAuth トークンを使ったクライアント（サービス初期化はモック）"""
    return GoogleMeetDriveClient(
        oauth_access_token="test_access_token",
        oauth_refresh_token="test_refresh_token",
        oauth_client_id="test_client_id",
        oauth_client_secret="test_client_secret",
    )


@pytest.fixture
def mock_drive_service():
    """Drive API サービスのモック"""
    return MagicMock()


# ---------------------------------------------------------------------------
# MeetRecordingFile
# ---------------------------------------------------------------------------


class TestMeetRecordingFile:
    def test_is_video_true(self):
        f = MeetRecordingFile(
            file_id="abc",
            name="weekly.mp4",
            mime_type=MEET_RECORDING_MIME_TYPE,
            size_bytes=10 * 1024 * 1024,
            created_time=None,
        )
        assert f.is_video is True

    def test_is_video_false(self):
        f = MeetRecordingFile(
            file_id="abc",
            name="doc.docx",
            mime_type="application/vnd.google-apps.document",
            size_bytes=None,
            created_time=None,
        )
        assert f.is_video is False

    def test_estimated_duration_none_when_no_size(self):
        f = MeetRecordingFile(
            file_id="abc",
            name="rec.mp4",
            mime_type=MEET_RECORDING_MIME_TYPE,
            size_bytes=None,
            created_time=None,
        )
        assert f.estimated_duration_minutes is None

    def test_estimated_duration_10mb_is_2min(self):
        f = MeetRecordingFile(
            file_id="abc",
            name="rec.mp4",
            mime_type=MEET_RECORDING_MIME_TYPE,
            size_bytes=10 * 1024 * 1024,
            created_time=None,
        )
        assert f.estimated_duration_minutes == 2.0


# ---------------------------------------------------------------------------
# GoogleMeetDriveClient — init
# ---------------------------------------------------------------------------


class TestGoogleMeetDriveClientInit:
    def test_oauth_token_stored(self):
        client = GoogleMeetDriveClient(
            oauth_access_token="token",
            oauth_refresh_token="refresh",
        )
        assert client._oauth_access_token == "token"
        assert client._oauth_refresh_token == "refresh"

    def test_sa_file_stored(self):
        client = GoogleMeetDriveClient(service_account_file="/path/to/sa.json")
        assert client._sa_file == "/path/to/sa.json"

    def test_service_is_initially_none(self):
        client = GoogleMeetDriveClient()
        assert client._service is None


# ---------------------------------------------------------------------------
# _find_meet_recordings_folder_id
# ---------------------------------------------------------------------------


class TestFindMeetRecordingsFolderId:
    def test_returns_folder_id_when_found(self, drive_client, mock_drive_service):
        drive_client._service = mock_drive_service

        mock_drive_service.files.return_value.list.return_value.execute.return_value = {
            "files": [{"id": "folder123", "name": MEET_RECORDINGS_FOLDER_NAME}]
        }

        folder_id = drive_client._find_meet_recordings_folder_id()
        assert folder_id == "folder123"

    def test_returns_none_when_folder_not_found(self, drive_client, mock_drive_service):
        drive_client._service = mock_drive_service

        mock_drive_service.files.return_value.list.return_value.execute.return_value = {
            "files": []
        }

        folder_id = drive_client._find_meet_recordings_folder_id()
        assert folder_id is None


# ---------------------------------------------------------------------------
# find_recent_recordings
# ---------------------------------------------------------------------------


class TestFindRecentRecordings:
    def test_returns_recording_list(self, drive_client, mock_drive_service):
        drive_client._service = mock_drive_service

        # フォルダ検索をモック
        folder_search = MagicMock()
        folder_search.execute.return_value = {
            "files": [{"id": "folder123", "name": MEET_RECORDINGS_FOLDER_NAME}]
        }

        # 録画ファイル一覧をモック
        recording_search = MagicMock()
        recording_search.execute.return_value = {
            "files": [
                {
                    "id": "file1",
                    "name": "週次定例 (2026-02-19 at 10:00 GMT).mp4",
                    "mimeType": MEET_RECORDING_MIME_TYPE,
                    "size": "52428800",  # 50MB
                    "createdTime": "2026-02-19T01:00:00Z",
                    "webViewLink": "https://drive.google.com/file/file1/view",
                    "parents": ["folder123"],
                }
            ]
        }

        # 2回目の list() 呼び出し（録画検索）でrecording_searchを返す
        mock_drive_service.files.return_value.list.side_effect = [
            folder_search,
            recording_search,
        ]

        results = drive_client.find_recent_recordings(days_back=1)

        assert len(results) == 1
        rec = results[0]
        assert rec.file_id == "file1"
        assert rec.mime_type == MEET_RECORDING_MIME_TYPE
        assert rec.size_bytes == 52428800
        assert rec.created_time is not None
        assert rec.created_time.tzinfo is not None

    def test_returns_empty_list_when_no_recordings(self, drive_client, mock_drive_service):
        drive_client._service = mock_drive_service

        mock_drive_service.files.return_value.list.return_value.execute.return_value = {
            "files": []
        }

        results = drive_client.find_recent_recordings(days_back=1)
        assert results == []

    def test_uses_provided_folder_id(self, drive_client, mock_drive_service):
        """folder_id を直接指定した場合、フォルダ検索をスキップする"""
        drive_client._service = mock_drive_service

        mock_drive_service.files.return_value.list.return_value.execute.return_value = {
            "files": []
        }

        drive_client.find_recent_recordings(days_back=1, folder_id="direct_folder")

        # list() は1回だけ呼ばれる（フォルダ検索なし）
        assert mock_drive_service.files.return_value.list.call_count == 1


# ---------------------------------------------------------------------------
# _extract_title (static method)
# ---------------------------------------------------------------------------


class TestExtractTitle:
    def test_extracts_title_from_standard_name(self):
        name = "週次定例 (2026-02-19 at 10:00 GMT).mp4"
        title = GoogleMeetBrainInterface._extract_title(name)
        assert title == "週次定例"

    def test_extracts_title_with_number_in_title(self):
        name = "Q1 キックオフ (2026-02-19 at 09:30 JST).mp4"
        title = GoogleMeetBrainInterface._extract_title(name)
        assert title == "Q1 キックオフ"

    def test_returns_original_when_no_pattern(self):
        name = "untitled_recording.mp4"
        title = GoogleMeetBrainInterface._extract_title(name)
        assert title == "untitled_recording.mp4"


# ---------------------------------------------------------------------------
# create_meet_drive_client_from_db
# ---------------------------------------------------------------------------


class TestCreateMeetDriveClientFromDb:
    def test_returns_none_when_no_token_and_no_sa(self):
        mock_pool = MagicMock()

        # DB接続は成功するがトークンなし
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = None
        mock_pool.connect.return_value.__enter__ = lambda s: mock_conn
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=False)

        with patch("os.getenv", return_value=""):  # SA file なし
            client = create_meet_drive_client_from_db(mock_pool, "org-123")

        assert client is None

    def test_returns_client_with_oauth_token(self):
        mock_pool = MagicMock()

        mock_conn = MagicMock()
        # (access_token, refresh_token)
        mock_conn.execute.return_value.fetchone.return_value = (
            "access_tok",
            "refresh_tok",
        )
        mock_pool.connect.return_value.__enter__ = lambda s: mock_conn
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=False)

        with patch("os.getenv", side_effect=lambda k, default="": default):
            client = create_meet_drive_client_from_db(mock_pool, "org-123")

        assert client is not None
        assert client._oauth_access_token == "access_tok"
        assert client._oauth_refresh_token == "refresh_tok"
