# tests/test_retention_manager.py
"""
RetentionManager のテスト

期限切れ検出、GCS削除、DB更新、raw_transcript NULL化をテスト。
"""

import pytest
from unittest.mock import MagicMock, patch

from lib.meetings.retention_manager import RetentionManager


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.organization_id = "org_test"
    return db


@pytest.fixture
def mock_gcs():
    return MagicMock()


@pytest.fixture
def manager(mock_db):
    return RetentionManager(mock_db)


@pytest.fixture
def manager_with_gcs(mock_db, mock_gcs):
    return RetentionManager(mock_db, gcs_client=mock_gcs)


class TestCleanupExpiredRecordings:
    def test_no_expired(self, manager, mock_db):
        mock_db.get_expired_recordings.return_value = []

        result = manager.cleanup_expired_recordings()
        assert result["deleted_count"] == 0
        assert result["errors"] == []

    def test_deletes_gcs_and_marks_db(self, manager_with_gcs, mock_db):
        mock_db.get_expired_recordings.return_value = [
            {"id": "r1", "meeting_id": "m1", "gcs_path": "gs://bucket/file1.mp3"},
            {"id": "r2", "meeting_id": "m2", "gcs_path": "gs://bucket/file2.mp3"},
        ]
        mock_db.mark_recordings_deleted.return_value = 2

        result = manager_with_gcs.cleanup_expired_recordings()
        assert result["deleted_count"] == 2
        assert result["errors"] == []
        mock_db.mark_recordings_deleted.assert_called_once_with(["r1", "r2"])

    def test_gcs_error_skips_recording(self, manager_with_gcs, mock_db, mock_gcs):
        mock_db.get_expired_recordings.return_value = [
            {"id": "r1", "meeting_id": "m1", "gcs_path": "gs://bucket/file1.mp3"},
            {"id": "r2", "meeting_id": "m2", "gcs_path": "gs://bucket/file2.mp3"},
        ]
        # r1のGCS削除が失敗、r2は成功
        mock_gcs.bucket.return_value.blob.return_value.delete.side_effect = [
            Exception("GCS error"), None,
        ]
        mock_db.mark_recordings_deleted.return_value = 1

        result = manager_with_gcs.cleanup_expired_recordings()
        assert result["deleted_count"] == 1
        assert len(result["errors"]) == 1
        assert result["errors"][0]["recording_id"] == "r1"
        mock_db.mark_recordings_deleted.assert_called_once_with(["r2"])

    def test_without_gcs_client_skips_gcs_delete(self, manager, mock_db):
        mock_db.get_expired_recordings.return_value = [
            {"id": "r1", "meeting_id": "m1", "gcs_path": "gs://bucket/file1.mp3"},
        ]
        mock_db.mark_recordings_deleted.return_value = 1

        result = manager.cleanup_expired_recordings()
        assert result["deleted_count"] == 1
        assert result["errors"] == []


class TestCleanupExpiredTranscripts:
    def test_nullifies_expired(self, manager, mock_db):
        mock_db.nullify_expired_raw_transcripts.return_value = 3

        count = manager.cleanup_expired_transcripts()
        assert count == 3
        mock_db.nullify_expired_raw_transcripts.assert_called_once()

    def test_returns_zero_when_none_expired(self, manager, mock_db):
        mock_db.nullify_expired_raw_transcripts.return_value = 0

        count = manager.cleanup_expired_transcripts()
        assert count == 0


class TestGetRetentionStats:
    def test_returns_stats(self, manager, mock_db):
        mock_db.get_expired_recordings.return_value = [
            {"id": "r1"}, {"id": "r2"},
        ]

        stats = manager.get_retention_stats()
        assert stats["expired_recordings_count"] == 2
        assert stats["organization_id"] == "org_test"


class TestDeleteGcsFile:
    def test_parses_gs_path(self, manager_with_gcs, mock_gcs):
        manager_with_gcs._delete_gcs_file("gs://my-bucket/path/to/file.mp3")

        mock_gcs.bucket.assert_called_once_with("my-bucket")
        mock_gcs.bucket.return_value.blob.assert_called_once_with("path/to/file.mp3")
        mock_gcs.bucket.return_value.blob.return_value.delete.assert_called_once()

    def test_invalid_path_raises(self, manager_with_gcs):
        with pytest.raises(ValueError, match="Invalid GCS path"):
            manager_with_gcs._delete_gcs_file("/local/path/file.mp3")

    def test_no_gcs_client_skips(self, manager):
        # gcs_client=None の場合、警告のみでエラーにならない
        manager._delete_gcs_file("gs://bucket/file.mp3")
