# lib/meetings/meeting_db.py
"""
Phase C MVP0: 会議データベースアクセス層

全クエリにorganization_idフィルタを適用（CLAUDE.md 鉄則#1）。
パラメータ化SQLのみ使用（鉄則#9）。
楽観ロック（version）で並行更新を安全に処理。

Author: Claude Opus 4.6
Created: 2026-02-10
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from sqlalchemy import text

logger = logging.getLogger(__name__)

# デフォルト保持期間（日）
DEFAULT_RETENTION_DAYS = 90


class MeetingDB:
    """会議関連テーブルのDBアクセス"""

    def __init__(self, pool, organization_id: str):
        if not organization_id or not organization_id.strip():
            raise ValueError("organization_id is required")
        self.pool = pool
        self.organization_id = organization_id

    # =========================================================================
    # meetings CRUD
    # =========================================================================

    def create_meeting(
        self,
        title: Optional[str],
        meeting_type: str = "unknown",
        created_by: Optional[str] = None,
        room_id: Optional[str] = None,
        source: str = "manual_upload",
        source_meeting_id: Optional[str] = None,
        meeting_date: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """会議レコードを作成する"""
        meeting_id = str(uuid4())
        now = datetime.now(timezone.utc)

        with self.pool.connect() as conn:
            conn.execute(
                text("""
                    INSERT INTO meetings (
                        id, organization_id, title, meeting_type,
                        meeting_date, status, source, source_meeting_id,
                        room_id, created_by, created_at, updated_at
                    ) VALUES (
                        :id, :org_id, :title, :meeting_type,
                        :meeting_date, 'pending', :source, :source_meeting_id,
                        :room_id, :created_by, :now, :now
                    )
                """),
                {
                    "id": meeting_id,
                    "org_id": self.organization_id,
                    "title": title,
                    "meeting_type": meeting_type,
                    "meeting_date": meeting_date or now,
                    "source": source,
                    "source_meeting_id": source_meeting_id,
                    "room_id": room_id,
                    "created_by": created_by,
                    "now": now,
                },
            )
            conn.commit()

        logger.info(
            "Meeting created: id=%s, org=%s, type=%s",
            meeting_id, self.organization_id, meeting_type,
        )
        return {"id": meeting_id, "status": "pending"}

    def get_meeting(self, meeting_id: str) -> Optional[Dict[str, Any]]:
        """会議レコードを取得する"""
        with self.pool.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT id, organization_id, title, meeting_type,
                           meeting_date, duration_seconds, status, source,
                           room_id, created_by, brain_approved,
                           transcript_sanitized, attendees_count,
                           speakers_detected, document_url,
                           total_tokens_used, estimated_cost_jpy,
                           error_message, error_code, version,
                           created_at, updated_at
                    FROM meetings
                    WHERE id = :id
                      AND organization_id = :org_id
                      AND deleted_at IS NULL
                """),
                {"id": meeting_id, "org_id": self.organization_id},
            )
            row = result.mappings().fetchone()
            return dict(row) if row else None

    def update_meeting_status(
        self,
        meeting_id: str,
        status: str,
        expected_version: int,
        **kwargs,
    ) -> bool:
        """
        会議ステータスを更新する（楽観ロック付き）。

        Returns:
            True: 更新成功, False: バージョン競合
        """
        set_clauses = ["status = :status", "updated_at = :now", "version = version + 1"]
        params: Dict[str, Any] = {
            "id": meeting_id,
            "org_id": self.organization_id,
            "status": status,
            "now": datetime.now(timezone.utc),
            "expected_version": expected_version,
        }

        allowed_fields = {
            "brain_approved", "transcript_sanitized", "duration_seconds",
            "attendees_count", "speakers_detected", "document_url",
            "document_id", "total_tokens_used", "estimated_cost_jpy",
            "error_message", "error_code", "title", "meeting_type",
        }
        for key, value in kwargs.items():
            if key in allowed_fields:
                set_clauses.append(f"{key} = :{key}")
                params[key] = value

        query = f"""
            UPDATE meetings
            SET {', '.join(set_clauses)}
            WHERE id = :id
              AND organization_id = :org_id
              AND version = :expected_version
              AND deleted_at IS NULL
        """

        with self.pool.connect() as conn:
            result = conn.execute(text(query), params)
            conn.commit()
            updated = result.rowcount > 0

        if not updated:
            logger.warning(
                "Meeting update failed (version conflict): id=%s, expected_version=%d",
                meeting_id, expected_version,
            )
        return updated

    def get_meetings_by_status(
        self, status: str, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """ステータスで会議一覧を取得する"""
        limit = min(limit, 100)
        with self.pool.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT id, title, meeting_type, meeting_date,
                           status, brain_approved, created_by, room_id,
                           created_at
                    FROM meetings
                    WHERE organization_id = :org_id
                      AND status = :status
                      AND deleted_at IS NULL
                    ORDER BY created_at DESC
                    LIMIT :limit
                """),
                {
                    "org_id": self.organization_id,
                    "status": status,
                    "limit": limit,
                },
            )
            return [dict(row) for row in result.mappings().fetchall()]

    # =========================================================================
    # meeting_recordings
    # =========================================================================

    def save_recording(
        self,
        meeting_id: str,
        gcs_path: str,
        file_size_bytes: int = 0,
        duration_seconds: float = 0,
        format: Optional[str] = None,
        sample_rate: Optional[int] = None,
        channels: int = 1,
    ) -> Dict[str, Any]:
        """録音レコードを保存する"""
        recording_id = str(uuid4())
        now = datetime.now(timezone.utc)
        retention_expires = now + timedelta(days=DEFAULT_RETENTION_DAYS)

        with self.pool.connect() as conn:
            conn.execute(
                text("""
                    INSERT INTO meeting_recordings (
                        id, organization_id, meeting_id, gcs_path,
                        file_size_bytes, duration_seconds, format,
                        sample_rate, channels, retention_expires_at,
                        created_at
                    ) VALUES (
                        :id, :org_id, :meeting_id, :gcs_path,
                        :file_size, :duration, :format,
                        :sample_rate, :channels, :retention_expires,
                        :now
                    )
                """),
                {
                    "id": recording_id,
                    "org_id": self.organization_id,
                    "meeting_id": meeting_id,
                    "gcs_path": gcs_path,
                    "file_size": file_size_bytes,
                    "duration": duration_seconds,
                    "format": format,
                    "sample_rate": sample_rate,
                    "channels": channels,
                    "retention_expires": retention_expires,
                    "now": now,
                },
            )
            conn.commit()

        return {"id": recording_id, "retention_expires_at": retention_expires.isoformat()}

    # =========================================================================
    # meeting_transcripts
    # =========================================================================

    def save_transcript(
        self,
        meeting_id: str,
        raw_transcript: Optional[str],
        sanitized_transcript: str,
        segments_json: Optional[Any] = None,
        speakers_json: Optional[Any] = None,
        detected_language: str = "ja",
        word_count: int = 0,
        confidence: float = 0,
    ) -> Dict[str, Any]:
        """文字起こし結果を保存する"""
        transcript_id = str(uuid4())
        now = datetime.now(timezone.utc)
        retention_expires = now + timedelta(days=DEFAULT_RETENTION_DAYS)

        with self.pool.connect() as conn:
            conn.execute(
                text("""
                    INSERT INTO meeting_transcripts (
                        id, organization_id, meeting_id,
                        raw_transcript, sanitized_transcript,
                        segments_json, speakers_json,
                        detected_language, word_count, confidence,
                        retention_expires_at, created_at
                    ) VALUES (
                        :id, :org_id, :meeting_id,
                        :raw, :sanitized,
                        CAST(:segments AS jsonb), CAST(:speakers AS jsonb),
                        :lang, :words, :confidence,
                        :retention_expires, :now
                    )
                """),
                {
                    "id": transcript_id,
                    "org_id": self.organization_id,
                    "meeting_id": meeting_id,
                    "raw": raw_transcript,
                    "sanitized": sanitized_transcript,
                    "segments": _json_str(segments_json),
                    "speakers": _json_str(speakers_json),
                    "lang": detected_language,
                    "words": word_count,
                    "confidence": confidence,
                    "retention_expires": retention_expires,
                    "now": now,
                },
            )
            conn.commit()

        return {"id": transcript_id}

    # =========================================================================
    # カスケード削除（Codex Fix #3: 同意撤回時の即時削除）
    # =========================================================================

    def delete_meeting_cascade(self, meeting_id: str) -> bool:
        """
        会議と関連データを即時削除する。

        FK ON DELETE CASCADEにより、recordings/transcripts/consent_logsも連鎖削除。
        同意撤回時に呼び出される。
        """
        with self.pool.connect() as conn:
            result = conn.execute(
                text("""
                    DELETE FROM meetings
                    WHERE id = :id
                      AND organization_id = :org_id
                """),
                {"id": meeting_id, "org_id": self.organization_id},
            )
            conn.commit()
            deleted = result.rowcount > 0

        if deleted:
            logger.info(
                "Meeting cascade deleted: id=%s, org=%s",
                meeting_id, self.organization_id,
            )
        return deleted

    def get_recordings_for_meeting(self, meeting_id: str) -> List[Dict[str, Any]]:
        """会議に紐づく録音レコードを取得する（同意撤回時のGCS削除用）"""
        with self.pool.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT id, gcs_path
                    FROM meeting_recordings
                    WHERE organization_id = :org_id
                      AND meeting_id = :meeting_id
                      AND is_deleted = FALSE
                """),
                {"org_id": self.organization_id, "meeting_id": meeting_id},
            )
            return [dict(row) for row in result.mappings().fetchall()]

    # =========================================================================
    # リテンション管理用クエリ
    # =========================================================================

    def get_expired_recordings(self, expire_before: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """保持期限切れの録音を取得する"""
        if expire_before is None:
            expire_before = datetime.now(timezone.utc)

        with self.pool.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT r.id, r.meeting_id, r.gcs_path
                    FROM meeting_recordings r
                    WHERE r.organization_id = :org_id
                      AND r.retention_expires_at < :expire_before
                      AND r.is_deleted = FALSE
                """),
                {"org_id": self.organization_id, "expire_before": expire_before},
            )
            return [dict(row) for row in result.mappings().fetchall()]

    def mark_recordings_deleted(self, recording_ids: List[str]) -> int:
        """録音レコードを削除済みにマークする"""
        if not recording_ids:
            return 0

        now = datetime.now(timezone.utc)
        with self.pool.connect() as conn:
            result = conn.execute(
                text("""
                    UPDATE meeting_recordings
                    SET is_deleted = TRUE, deleted_at = :now
                    WHERE organization_id = :org_id
                      AND id = ANY(:ids)
                      AND is_deleted = FALSE
                """),
                {"org_id": self.organization_id, "ids": recording_ids, "now": now},
            )
            conn.commit()
            return result.rowcount

    def nullify_expired_raw_transcripts(self, expire_before: Optional[datetime] = None) -> int:
        """保持期限切れの原文を削除（サニタイズ版は保持）"""
        if expire_before is None:
            expire_before = datetime.now(timezone.utc)

        with self.pool.connect() as conn:
            result = conn.execute(
                text("""
                    UPDATE meeting_transcripts
                    SET raw_transcript = NULL,
                        segments_json = NULL,
                        speakers_json = NULL,
                        deleted_at = :now
                    WHERE organization_id = :org_id
                      AND retention_expires_at < :expire_before
                      AND raw_transcript IS NOT NULL
                      AND is_deleted = FALSE
                """),
                {
                    "org_id": self.organization_id,
                    "expire_before": expire_before,
                    "now": datetime.now(timezone.utc),
                },
            )
            conn.commit()
            return result.rowcount


    def find_meeting_by_source_id(
        self,
        source: str,
        source_meeting_id: str,
    ) -> Optional[Dict[str, Any]]:
        """source_meeting_idで既存会議を検索する（重複チェック用）"""
        if not source_meeting_id:
            return None
        with self.pool.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT id, title, status, source, source_meeting_id,
                           created_at
                    FROM meetings
                    WHERE organization_id = :org_id
                      AND source = :source
                      AND source_meeting_id = :source_mid
                      AND deleted_at IS NULL
                    LIMIT 1
                """),
                {
                    "org_id": self.organization_id,
                    "source": source,
                    "source_mid": source_meeting_id,
                },
            )
            row = result.mappings().fetchone()
            return dict(row) if row else None

    def get_recent_meetings_by_source(
        self,
        source: str,
        limit: int = 5,
        days: int = 30,
    ) -> List[Dict[str, Any]]:
        """指定ソースの直近の会議を取得する"""
        limit = min(limit, 100)
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        with self.pool.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT id, title, meeting_type, meeting_date,
                           status, source, source_meeting_id,
                           brain_approved, created_by, room_id, created_at
                    FROM meetings
                    WHERE organization_id = :org_id
                      AND source = :source
                      AND created_at >= :cutoff
                      AND deleted_at IS NULL
                    ORDER BY created_at DESC
                    LIMIT :limit
                """),
                {
                    "org_id": self.organization_id,
                    "source": source,
                    "cutoff": cutoff,
                    "limit": limit,
                },
            )
            return [dict(row) for row in result.mappings().fetchall()]

    def get_transcript_for_meeting(
        self, meeting_id: str
    ) -> Optional[Dict[str, Any]]:
        """会議のトランスクリプトを取得する"""
        with self.pool.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT id, meeting_id, sanitized_transcript,
                           segments_json, speakers_json,
                           detected_language, word_count, confidence,
                           created_at
                    FROM meeting_transcripts
                    WHERE organization_id = :org_id
                      AND meeting_id = :meeting_id
                      AND is_deleted = FALSE
                    ORDER BY created_at DESC
                    LIMIT 1
                """),
                {"org_id": self.organization_id, "meeting_id": meeting_id},
            )
            row = result.mappings().fetchone()
            return dict(row) if row else None


def _json_str(obj: Any) -> Optional[str]:
    """JSONBカラム用にオブジェクトを文字列化する"""
    if obj is None:
        return None
    import json
    return json.dumps(obj, ensure_ascii=False) if not isinstance(obj, str) else obj
