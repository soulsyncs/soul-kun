# lib/meetings/retention_manager.py
"""
Phase C MVP0: データ保持管理

録音ファイル・原文テキストのTTLベース自動削除。
- 録音ファイル: GCS + DB から90日後に物理削除
- 原文テキスト: 90日後にraw_transcriptをNULL化（sanitized版は永続）

設計根拠:
- docs/07_phase_c_meetings.md: Data Retention Policy
- PDPA: 保存期間の最小化

Author: Claude Opus 4.6
Created: 2026-02-10
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class RetentionManager:
    """データ保持期限の管理と期限切れデータの削除"""

    def __init__(self, meeting_db, gcs_client=None):
        """
        Args:
            meeting_db: MeetingDBインスタンス
            gcs_client: google.cloud.storage.Client（オプション）
        """
        self.db = meeting_db
        self.gcs_client = gcs_client

    def cleanup_expired_recordings(self) -> Dict[str, Any]:
        """
        保持期限切れの録音を削除する。

        1. DBから期限切れレコードを取得
        2. GCSから物理ファイルを削除
        3. DBレコードを削除済みにマーク

        Returns:
            {"deleted_count": int, "errors": list}
        """
        expired = self.db.get_expired_recordings()
        if not expired:
            return {"deleted_count": 0, "errors": []}

        errors = []
        deleted_ids = []

        for recording in expired:
            gcs_path = recording["gcs_path"]
            recording_id = recording["id"]

            if self.gcs_client:
                try:
                    self._delete_gcs_file(gcs_path)
                except Exception as e:
                    logger.error(
                        "GCS delete failed: path=%s, error=%s",
                        gcs_path, e,
                    )
                    errors.append({
                        "recording_id": recording_id,
                        "gcs_path": gcs_path,
                        "error": str(e),
                    })
                    continue

            deleted_ids.append(recording_id)

        marked = 0
        if deleted_ids:
            marked = self.db.mark_recordings_deleted(deleted_ids)

        logger.info(
            "Retention cleanup: expired=%d, deleted=%d, errors=%d",
            len(expired), marked, len(errors),
        )

        return {"deleted_count": marked, "errors": errors}

    def cleanup_expired_transcripts(self) -> int:
        """
        保持期限切れのraw_transcriptをNULL化する。
        sanitized_transcriptは永続保持（PII除去済みのため）。

        Returns:
            NULL化されたレコード数
        """
        count = self.db.nullify_expired_raw_transcripts()
        if count > 0:
            logger.info("Raw transcripts nullified: count=%d", count)
        return count

    def get_retention_stats(self) -> Dict[str, Any]:
        """保持状況の統計を返す"""
        expired_recordings = self.db.get_expired_recordings()
        return {
            "expired_recordings_count": len(expired_recordings),
            "organization_id": self.db.organization_id,
        }

    def _delete_gcs_file(self, gcs_path: str) -> None:
        """GCSからファイルを物理削除する"""
        if not self.gcs_client:
            logger.warning("GCS client not configured, skipping delete: %s", gcs_path)
            return

        # gcs_path format: gs://bucket-name/path/to/file
        if gcs_path.startswith("gs://"):
            path = gcs_path[5:]
            bucket_name, _, blob_name = path.partition("/")
        else:
            raise ValueError(f"Invalid GCS path: {gcs_path}")

        bucket = self.gcs_client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        blob.delete()

        logger.info("GCS file deleted: %s", gcs_path)
