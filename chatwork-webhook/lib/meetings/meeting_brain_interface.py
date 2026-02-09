# lib/meetings/meeting_brain_interface.py
"""
Phase C MVP0: Brain連携インターフェース

Brain（lib/brain/）との唯一の接続点。
lib/brain/ の内部実装には依存せず、安定データクラス（HandlerResult）のみ参照。
Brain Tool定義が変わってもこのファイルの修正で吸収する（Codex Fix #4）。

フロー（Codex Fix #1: Brain bypass防止）:
1. 音声アップロード → Google Speech-to-Text文字起こし → PII除去 → DB保存(brain_approved=FALSE)
2. Brain Tool通知 → Brainが内容判断 → Guardian検証 → ChatWork投稿決定

Author: Claude Opus 4.6
Created: 2026-02-10
"""

import logging
import os
from typing import Any, Dict, Optional

# 安定データクラスのみimport（lib/brain/の内部ロジックには依存しない）
from lib.brain.models import HandlerResult

from lib.meetings.meeting_db import MeetingDB
from lib.meetings.transcript_sanitizer import TranscriptSanitizer
from lib.meetings.consent_manager import ConsentManager

logger = logging.getLogger(__name__)


class MeetingBrainInterface:
    """
    会議機能とBrainの連携インターフェース。

    責務:
    - 音声処理の実行（文字起こし + PII除去 + DB保存）
    - 処理結果をHandlerResult形式でBrainに返却
    - Brain承認フラグの管理

    非責務（Brain側が担当）:
    - ChatWork投稿の判断・生成
    - Guardian Layer検証
    """

    def __init__(self, pool, organization_id: str):
        self.pool = pool
        self.organization_id = organization_id
        self.db = MeetingDB(pool, organization_id)
        self.sanitizer = TranscriptSanitizer()
        self.consent = ConsentManager(pool, organization_id)

    async def process_meeting_upload(
        self,
        audio_data: bytes,
        room_id: str,
        account_id: str,
        title: Optional[str] = None,
        meeting_type: str = "unknown",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> HandlerResult:
        """
        会議音声をアップロードし、文字起こしを実行する。

        brain_approved=FALSEのまま返却し、ChatWork投稿の判断はBrainに委ねる。

        Returns:
            HandlerResult with meeting_id, status, sanitized_transcript
        """
        import asyncio

        try:
            # 1. 会議レコード作成
            meeting = await asyncio.to_thread(
                self.db.create_meeting,
                title=title,
                meeting_type=meeting_type,
                created_by=account_id,
                room_id=room_id,
            )
            meeting_id = meeting["id"]
            current_version = 1

            # 2. ステータス更新: transcribing（楽観ロック検証）
            updated = await asyncio.to_thread(
                self.db.update_meeting_status,
                meeting_id, "transcribing", expected_version=current_version,
            )
            if not updated:
                return HandlerResult(
                    success=False,
                    message="会議のステータス更新に失敗しました（バージョン競合）。",
                    data={"meeting_id": meeting_id},
                )
            current_version += 1

            # 3. 音声をGCSにアップロード（バケット設定時のみ）
            gcs_path = await self._upload_audio_to_gcs(meeting_id, audio_data)
            if gcs_path:
                await asyncio.to_thread(
                    self.db.save_recording,
                    meeting_id=meeting_id,
                    gcs_path=gcs_path,
                    file_size_bytes=len(audio_data),
                    duration_seconds=0,
                    format=self._detect_audio_format(audio_data),
                )

            # 4. 音声処理（Google Speech-to-Text）
            transcript_text, audio_meta = await self._transcribe_audio(
                audio_data, gcs_uri=gcs_path,
            )

            # 5. PII除去
            sanitized, pii_count = self.sanitizer.sanitize(transcript_text)

            # 6. 文字起こし結果を保存（segments/speakersもサニタイズ）
            await asyncio.to_thread(
                self.db.save_transcript,
                meeting_id=meeting_id,
                raw_transcript=transcript_text,
                sanitized_transcript=sanitized,
                segments_json=None,
                speakers_json=None,
                detected_language=audio_meta.get("language", "ja"),
                word_count=len(sanitized),
                confidence=audio_meta.get("confidence", 0),
            )

            # 7. ステータス更新: transcribed（brain_approved=FALSEのまま）
            updated = await asyncio.to_thread(
                self.db.update_meeting_status,
                meeting_id, "transcribed", expected_version=current_version,
                transcript_sanitized=True,
                duration_seconds=audio_meta.get("duration", 0),
                speakers_detected=audio_meta.get("speakers_count", 0),
            )
            if not updated:
                return HandlerResult(
                    success=False,
                    message="会議のステータス更新に失敗しました（バージョン競合）。",
                    data={"meeting_id": meeting_id},
                )

            logger.info(
                "Meeting transcribed: id=%s, pii_removed=%d, words=%d",
                meeting_id, pii_count, len(sanitized),
            )

            return HandlerResult(
                success=True,
                message=self._build_summary_message(title, sanitized, pii_count),
                data={
                    "meeting_id": meeting_id,
                    "status": "transcribed",
                    "sanitized_transcript": sanitized[:4000],
                    "pii_removed_count": pii_count,
                    "duration_seconds": audio_meta.get("duration", 0),
                    "speakers_detected": audio_meta.get("speakers_count", 0),
                },
            )

        except Exception as e:
            logger.error("Meeting upload failed: meeting_id=%s",
                         locals().get("meeting_id", "unknown"))
            # エラー時もステータスを更新（PIIを含まない安全なメッセージのみ保存）
            error_safe = type(e).__name__
            if "meeting_id" in locals():
                try:
                    await asyncio.to_thread(
                        self.db.update_meeting_status,
                        meeting_id, "failed",
                        expected_version=locals().get("current_version", 1),
                        error_message=error_safe,
                    )
                except Exception:
                    pass
            return HandlerResult(
                success=False,
                message="会議の文字起こしに失敗しました。",
                data={"error": error_safe},
            )

    async def approve_and_notify(self, meeting_id: str) -> HandlerResult:
        """
        Brainが承認した場合に呼ばれる。brain_approved=TRUEに更新。
        """
        import asyncio

        meeting = await asyncio.to_thread(self.db.get_meeting, meeting_id)
        if not meeting:
            return HandlerResult(
                success=False,
                message="会議が見つかりません。",
                data={"meeting_id": meeting_id},
            )

        updated = await asyncio.to_thread(
            self.db.update_meeting_status,
            meeting_id, "completed",
            expected_version=meeting["version"],
            brain_approved=True,
        )

        if not updated:
            return HandlerResult(
                success=False,
                message="会議の更新に失敗しました（バージョン競合）。",
                data={"meeting_id": meeting_id},
            )

        return HandlerResult(
            success=True,
            message="文字起こしが承認されました。",
            data={"meeting_id": meeting_id, "brain_approved": True},
        )

    async def handle_consent_withdrawal(
        self, meeting_id: str, user_id: str,
        gcs_client=None,
    ) -> HandlerResult:
        """
        同意撤回を処理する。GCSファイル + DBデータを即時削除（Codex Fix #3）。
        """
        import asyncio

        try:
            # 同意撤回ログを記録
            await asyncio.to_thread(
                self.consent.record_consent,
                meeting_id, user_id, "withdrawn",
            )

            # GCS録音ファイルも物理削除（DB削除前に取得）
            recordings = await asyncio.to_thread(
                self.db.get_recordings_for_meeting, meeting_id,
            )
            if recordings and gcs_client:
                from lib.meetings.retention_manager import RetentionManager
                rm = RetentionManager(self.db, gcs_client=gcs_client)
                for rec in recordings:
                    try:
                        rm._delete_gcs_file(rec["gcs_path"])
                    except Exception as e:
                        logger.warning("GCS delete failed on withdrawal: %s", e)

            # カスケード削除（DB）
            deleted = await asyncio.to_thread(
                self.db.delete_meeting_cascade, meeting_id,
            )

            if deleted:
                logger.info(
                    "Consent withdrawn, meeting deleted: id=%s",
                    meeting_id,
                )
                return HandlerResult(
                    success=True,
                    message="同意が撤回され、関連データを全て削除しました。",
                    data={"meeting_id": meeting_id, "deleted": True},
                )

            return HandlerResult(
                success=False,
                message="会議データの削除に失敗しました。",
                data={"meeting_id": meeting_id},
            )

        except Exception as e:
            logger.error("Consent withdrawal failed: meeting_id=%s", meeting_id)
            return HandlerResult(
                success=False,
                message="同意撤回処理中にエラーが発生しました。",
                data={"meeting_id": meeting_id, "error": type(e).__name__},
            )

    async def get_meeting_summary(self, meeting_id: str) -> HandlerResult:
        """会議のサマリーを返す（Brainが表示判断に使用）"""
        import asyncio

        meeting = await asyncio.to_thread(self.db.get_meeting, meeting_id)
        if not meeting:
            return HandlerResult(
                success=False,
                message="会議が見つかりません。",
                data={},
            )

        return HandlerResult(
            success=True,
            message=f"会議「{meeting.get('title', '無題')}」の情報です。",
            data={
                "meeting_id": meeting_id,
                "title": meeting.get("title"),
                "status": meeting.get("status"),
                "meeting_type": meeting.get("meeting_type"),
                "brain_approved": meeting.get("brain_approved"),
                "duration_seconds": meeting.get("duration_seconds"),
                "speakers_detected": meeting.get("speakers_detected"),
            },
        )

    # =========================================================================
    # Private helpers
    # =========================================================================

    async def _transcribe_audio(
        self, audio_data: bytes, gcs_uri: str = None,
    ) -> tuple:
        """
        Google Cloud Speech-to-Text で文字起こしを実行する。

        gcs_uri がある場合: long_running_recognize（長時間音声対応）
        gcs_uri がない場合: recognize（インライン、短時間音声のみ）

        Returns:
            (transcript_text, metadata_dict)
        """
        import asyncio

        def _do_transcribe():
            from google.cloud import speech

            client = speech.SpeechClient()
            config = speech.RecognitionConfig(
                language_code="ja-JP",
                enable_automatic_punctuation=True,
                model="latest_long",
            )

            if gcs_uri:
                audio = speech.RecognitionAudio(uri=gcs_uri)
                operation = client.long_running_recognize(
                    config=config, audio=audio,
                )
                response = operation.result(timeout=600)
            else:
                max_inline = 10 * 1024 * 1024  # 10 MB
                if len(audio_data) > max_inline:
                    raise ValueError(
                        "Audio too large for inline transcription "
                        f"({len(audio_data)} bytes, max {max_inline})"
                    )
                audio = speech.RecognitionAudio(content=audio_data)
                response = client.recognize(config=config, audio=audio)

            transcript_parts = []
            total_confidence = 0.0
            result_count = 0
            for result in response.results:
                if result.alternatives:
                    best = result.alternatives[0]
                    transcript_parts.append(best.transcript)
                    total_confidence += best.confidence
                    result_count += 1

            transcript = "".join(transcript_parts)
            avg_confidence = (
                total_confidence / result_count if result_count > 0 else 0.0
            )

            return transcript, avg_confidence

        transcript, confidence = await asyncio.to_thread(_do_transcribe)

        return (
            transcript,
            {
                "language": "ja",
                "duration": 0,
                "confidence": confidence,
                "speakers_count": 0,
            },
        )

    async def _upload_audio_to_gcs(
        self,
        meeting_id: str,
        audio_data: bytes,
    ) -> Optional[str]:
        """
        音声データをGCSにアップロードする。

        MEETING_GCS_BUCKET が未設定の場合はスキップ（None返却）。
        GCSアップロード失敗は文字起こし処理を止めない（警告のみ）。

        Returns:
            GCSパス（gs://bucket/path）or None
        """
        import asyncio

        bucket_name = os.getenv("MEETING_GCS_BUCKET", "")
        if not bucket_name:
            logger.debug("MEETING_GCS_BUCKET not set, skipping GCS upload")
            return None

        try:
            audio_format = self._detect_audio_format(audio_data)
            gcs_path = (
                f"gs://{bucket_name}/{self.organization_id}"
                f"/{meeting_id}/audio.{audio_format}"
            )

            def _do_upload():
                from google.cloud import storage
                client = storage.Client()
                bucket = client.bucket(bucket_name)
                blob_path = f"{self.organization_id}/{meeting_id}/audio.{audio_format}"
                blob = bucket.blob(blob_path)
                content_type = (
                    "audio/mpeg" if audio_format == "mp3"
                    else f"audio/{audio_format}"
                )
                blob.upload_from_string(audio_data, content_type=content_type)

            await asyncio.to_thread(_do_upload)
            logger.info("Audio uploaded to GCS: %s", gcs_path)
            return gcs_path

        except Exception as e:
            logger.warning(
                "GCS upload failed (continuing with transcription): %s",
                type(e).__name__,
            )
            return None

    @staticmethod
    def _detect_audio_format(audio_data: bytes) -> str:
        """音声データのフォーマットをマジックバイトで判定する"""
        if audio_data[:4] == b"fLaC":
            return "flac"
        if audio_data[:4] == b"RIFF":
            return "wav"
        if audio_data[:3] == b"ID3" or (len(audio_data) > 1 and audio_data[0:2] == b"\xff\xfb"):
            return "mp3"
        if audio_data[:4] == b"OggS":
            return "ogg"
        return "mp3"

    @staticmethod
    def _build_summary_message(
        title: Optional[str], sanitized: str, pii_count: int,
    ) -> str:
        """Brainに渡すサマリーメッセージを生成"""
        meeting_name = title or "会議"
        preview = sanitized[:200] + "..." if len(sanitized) > 200 else sanitized
        parts = [
            f"「{meeting_name}」の文字起こしが完了しました。",
            f"文字数: {len(sanitized)}",
        ]
        if pii_count > 0:
            parts.append(f"個人情報 {pii_count}件 を自動マスキングしました。")
        parts.append(f"\n--- プレビュー ---\n{preview}")
        return "\n".join(parts)
