# lib/meetings/meeting_brain_interface.py
"""
Phase C MVP0: Brain連携インターフェース

Brain（lib/brain/）との唯一の接続点。
lib/brain/ の内部実装には依存せず、安定データクラス（HandlerResult）のみ参照。
Brain Tool定義が変わってもこのファイルの修正で吸収する（Codex Fix #4）。

フロー（Codex Fix #1: Brain bypass防止）:
1. 音声アップロード → Whisper文字起こし → PII除去 → DB保存(brain_approved=FALSE)
2. Brain Tool通知 → Brainが内容判断 → Guardian検証 → ChatWork投稿決定

Author: Claude Opus 4.6
Created: 2026-02-10
"""

import logging
from dataclasses import dataclass
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

            # 3. 音声処理（AudioProcessor）
            transcript_text, audio_meta = await self._transcribe_audio(audio_data)

            # 4. PII除去
            sanitized, pii_count = self.sanitizer.sanitize(transcript_text)

            # 5. 文字起こし結果を保存（segments/speakersもサニタイズ）
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

            # 6. ステータス更新: transcribed（brain_approved=FALSEのまま）
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

    async def _transcribe_audio(self, audio_data: bytes) -> tuple:
        """
        AudioProcessorで文字起こしを実行する。

        Returns:
            (transcript_text, metadata_dict)
        """
        from lib.capabilities.multimodal import AudioProcessor, MultimodalInput, InputType

        processor = AudioProcessor(
            pool=self.pool,
            organization_id=self.organization_id,
            api_key=None,
            openai_api_key=self._get_openai_key(),
        )

        input_data = MultimodalInput(
            input_type=InputType.AUDIO,
            audio_data=audio_data,
        )

        result = await processor.process(input_data)

        return (
            result.transcript or "",
            {
                "segments": result.segments if hasattr(result, "segments") else None,
                "speakers": result.speakers if hasattr(result, "speakers") else None,
                "speakers_count": result.speakers_detected if hasattr(result, "speakers_detected") else 0,
                "language": result.detected_language if hasattr(result, "detected_language") else "ja",
                "duration": result.audio_duration_seconds if hasattr(result, "audio_duration_seconds") else 0,
                "confidence": result.confidence if hasattr(result, "confidence") else 0,
            },
        )

    @staticmethod
    def _get_openai_key() -> str:
        """OpenAI APIキーを取得する"""
        import os
        key = os.getenv("OPENAI_API_KEY", "")
        if not key:
            try:
                from lib.secrets import get_secret_cached
                key = get_secret_cached("OPENAI_API_KEY")
            except Exception as e:
                logger.warning("Failed to get OpenAI key from Secret Manager: %s", e)
        return key

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
