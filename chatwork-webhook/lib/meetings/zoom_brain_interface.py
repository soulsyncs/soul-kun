# lib/meetings/zoom_brain_interface.py
"""
Zoom議事録機能のBrain連携インターフェース

Brain（lib/brain/）との唯一の接続点（meeting_brain_interface.pyと同パターン）。

フロー:
1. ユーザー「Zoomの議事録まとめて」→ Brain Tool呼び出し
2. Zoom API → 直近のミーティングRecording取得
3. VTTダウンロード → パース → PII除去
4. DB保存（brain_approved=FALSE）
5. LLM議事録生成（Brain経由）
6. HandlerResult返却 → Brainが投稿判断

Author: Claude Opus 4.6
Created: 2026-02-10
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from lib.brain.models import HandlerResult
from lib.meetings.meeting_db import MeetingDB
from lib.meetings.transcript_sanitizer import TranscriptSanitizer
from lib.meetings.zoom_api_client import ZoomAPIClient, create_zoom_client_from_secrets
from lib.meetings.vtt_parser import parse_vtt, VTTTranscript
from lib.meetings.minutes_generator import (
    build_minutes_prompt,
    parse_minutes_response,
    MeetingMinutes,
    MINUTES_SYSTEM_PROMPT,
)

logger = logging.getLogger(__name__)

ZOOM_TRANSCRIPT_NOT_READY_MESSAGE = (
    "Zoomの文字起こしがまだ準備中のようウル。"
    "会議終了後、会議時間の約2倍の時間が必要ウル。"
    "もう少し待ってからまた聞いてほしいウル\U0001f43a"
)


class ZoomBrainInterface:
    """
    Zoom議事録機能とBrainの連携インターフェース。

    責務:
    - Zoom APIからトランスクリプト取得
    - VTTパース + PII除去
    - DB保存（source='zoom'）
    - LLM議事録生成のプロンプト構築と結果パース
    - HandlerResultをBrainに返却

    非責務（Brain側が担当）:
    - ChatWork投稿判断
    - LLM呼び出し自体（get_ai_response_funcで注入）
    - Guardian Layer検証
    """

    def __init__(
        self,
        pool,
        organization_id: str,
        zoom_client: Optional[ZoomAPIClient] = None,
    ):
        if not organization_id or not organization_id.strip():
            raise ValueError("organization_id is required")
        self.pool = pool
        self.organization_id = organization_id
        self.db = MeetingDB(pool, organization_id)
        self.sanitizer = TranscriptSanitizer()
        self._zoom_client = zoom_client

    def _get_zoom_client(self) -> ZoomAPIClient:
        """Lazy-init Zoom client from secrets."""
        if self._zoom_client is None:
            self._zoom_client = create_zoom_client_from_secrets()
        return self._zoom_client

    async def process_zoom_minutes(
        self,
        room_id: str,
        account_id: str,
        meeting_title: Optional[str] = None,
        zoom_meeting_id: Optional[str] = None,
        zoom_user_email: Optional[str] = None,
        get_ai_response_func: Optional[Callable] = None,
    ) -> HandlerResult:
        """
        Zoom議事録を生成する。

        Args:
            room_id: ChatWorkルームID
            account_id: ユーザーアカウントID
            meeting_title: 会議タイトル（指定があれば）
            zoom_meeting_id: 特定のZoomミーティングID（指定があれば）
            zoom_user_email: ZoomユーザーEmail（指定があれば）
            get_ai_response_func: LLM呼び出し関数（Brain側から注入）

        Returns:
            HandlerResult with minutes data
        """
        try:
            zoom_client = await asyncio.to_thread(self._get_zoom_client)

            # Step 1: Find the relevant Zoom recording
            recording_data = await self._find_recording(
                zoom_client,
                zoom_meeting_id,
                zoom_user_email,
            )
            if recording_data is None:
                return HandlerResult(
                    success=False,
                    message=(
                        "直近のZoomミーティングの録画が見つからなかったウル。"
                        "録画付きで会議を行ったか確認してほしいウル\U0001f43a"
                    ),
                    data={},
                )

            # Extract source meeting ID (null-safe: id=None → "")
            raw_id = recording_data.get("id")
            source_mid = str(raw_id) if raw_id else ""

            # Step 2: Find and download VTT transcript
            transcript_url = await asyncio.to_thread(
                zoom_client.find_transcript_url,
                recording_data,
            )
            if transcript_url is None:
                return HandlerResult(
                    success=False,
                    message=ZOOM_TRANSCRIPT_NOT_READY_MESSAGE,
                    data={"zoom_meeting_id": source_mid},
                )

            vtt_content = await asyncio.to_thread(
                zoom_client.download_transcript,
                transcript_url,
            )
            if not vtt_content or not vtt_content.strip():
                return HandlerResult(
                    success=False,
                    message=ZOOM_TRANSCRIPT_NOT_READY_MESSAGE,
                    data={"zoom_meeting_id": source_mid},
                )

            # Step 3: Parse VTT
            vtt_transcript = parse_vtt(vtt_content)
            if not vtt_transcript.segments:
                return HandlerResult(
                    success=False,
                    message=(
                        "Zoomの文字起こしが空だったウル。"
                        "会議中に発言があったか確認してほしいウル\U0001f43a"
                    ),
                    data={},
                )

            # Step 4: PII sanitization
            raw_text = vtt_transcript.full_text
            sanitized_text, pii_count = self.sanitizer.sanitize(raw_text)

            # Step 5: Resolve meeting title
            resolved_title = meeting_title or recording_data.get(
                "topic", "Zoom\u30df\u30fc\u30c6\u30a3\u30f3\u30b0"
            )

            # Step 6: Dedup check + DB save
            if source_mid:
                existing = await asyncio.to_thread(
                    self.db.find_meeting_by_source_id,
                    source="zoom",
                    source_meeting_id=source_mid,
                )
                if existing:
                    logger.info(
                        "Zoom meeting already processed: %s",
                        existing.get("id"),
                    )
                    return HandlerResult(
                        success=True,
                        message=(
                            "このZoomミーティングの議事録は既に作成済みウル\U0001f43a"
                        ),
                        data={
                            "meeting_id": existing["id"],
                            "status": existing.get("status", ""),
                            "already_processed": True,
                        },
                    )

            meeting = await asyncio.to_thread(
                self.db.create_meeting,
                title=resolved_title,
                meeting_type="zoom",
                created_by=account_id,
                room_id=room_id,
                source="zoom",
                source_meeting_id=source_mid,
                meeting_date=_parse_zoom_datetime(
                    recording_data.get("start_time")
                ),
            )
            meeting_id = meeting["id"]

            # raw_transcript: retention_managerが90日後にNULL化（PII保護）。
            # sanitized_transcriptがLLM・表示用。meeting_brain_interface.pyと同設計。
            await asyncio.to_thread(
                self.db.save_transcript,
                meeting_id=meeting_id,
                raw_transcript=raw_text,
                sanitized_transcript=sanitized_text,
                segments_json=vtt_transcript.to_segments_json(),
                speakers_json=vtt_transcript.to_speakers_json(),
                detected_language="ja",
                word_count=len(sanitized_text),
                confidence=1.0,
            )

            await asyncio.to_thread(
                self.db.update_meeting_status,
                meeting_id,
                "transcribed",
                expected_version=1,
                transcript_sanitized=True,
                duration_seconds=vtt_transcript.duration_seconds,
                speakers_detected=len(vtt_transcript.speakers),
            )

            # Step 7: LLM minutes generation
            minutes = None
            if get_ai_response_func:
                minutes = await self._generate_minutes(
                    sanitized_text,
                    resolved_title,
                    get_ai_response_func,
                )

            # Step 8: Build result
            result_data: Dict[str, Any] = {
                "meeting_id": meeting_id,
                "status": "transcribed",
                "title": resolved_title,
                "zoom_meeting_id": source_mid,
                "speakers": vtt_transcript.speakers,
                "speakers_detected": len(vtt_transcript.speakers),
                "duration_seconds": vtt_transcript.duration_seconds,
                "pii_removed_count": pii_count,
                "segment_count": len(vtt_transcript.segments),
            }

            if minutes:
                result_data["minutes"] = minutes.to_dict()
                message = minutes.to_chatwork_message(resolved_title)
            else:
                message = self._build_transcript_only_message(
                    resolved_title,
                    sanitized_text,
                    pii_count,
                    vtt_transcript,
                )

            logger.info(
                "Zoom minutes generated: meeting_id=%s, segments=%d, speakers=%d",
                meeting_id,
                len(vtt_transcript.segments),
                len(vtt_transcript.speakers),
            )

            return HandlerResult(
                success=True,
                message=message,
                data=result_data,
            )

        except Exception as e:
            logger.error("Zoom minutes failed: %s", type(e).__name__)
            return HandlerResult(
                success=False,
                message=(
                    "Zoom\u306e\u8b70\u4e8b\u9332\u751f\u6210\u4e2d\u306b"
                    "\u30a8\u30e9\u30fc\u304c\u767a\u751f\u3057\u305f\u30a6\u30eb\u3002"
                    "\u3082\u3046\u4e00\u5ea6\u8a66\u3057\u3066\u307b\u3057\u3044\u30a6\u30eb\U0001f43a"
                ),
                data={"error": type(e).__name__},
            )

    async def _find_recording(
        self,
        zoom_client: ZoomAPIClient,
        zoom_meeting_id: Optional[str],
        zoom_user_email: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        """Find the relevant Zoom recording."""
        if zoom_meeting_id:
            try:
                return await asyncio.to_thread(
                    zoom_client.get_meeting_recordings,
                    zoom_meeting_id,
                )
            except Exception as e:
                logger.warning(
                    "Failed to get specific recording: %s", type(e).__name__
                )
                return None

        # Search recent recordings (last 7 days)
        user_id = zoom_user_email or "me"
        from_date = (
            datetime.now(timezone.utc) - timedelta(days=7)
        ).strftime("%Y-%m-%d")

        try:
            meetings = await asyncio.to_thread(
                zoom_client.list_recordings,
                user_id=user_id,
                from_date=from_date,
            )
        except Exception as e:
            logger.warning("Failed to list recordings: %s", type(e).__name__)
            return None

        if not meetings:
            return None

        # Return the most recent meeting with a transcript
        for meeting in sorted(
            meetings,
            key=lambda m: m.get("start_time", ""),
            reverse=True,
        ):
            recording_files = meeting.get("recording_files", [])
            has_transcript = any(
                f.get("file_type") == "TRANSCRIPT" for f in recording_files
            )
            if has_transcript:
                return meeting

        # Fallback: return most recent (transcript may still be processing)
        return meetings[0] if meetings else None

    async def _generate_minutes(
        self,
        sanitized_text: str,
        title: str,
        get_ai_response_func: Callable,
    ) -> Optional[MeetingMinutes]:
        """Generate structured minutes using LLM."""
        try:
            prompt = build_minutes_prompt(sanitized_text, title)

            if asyncio.iscoroutinefunction(get_ai_response_func):
                response = await get_ai_response_func(
                    [{"role": "user", "content": prompt}],
                    MINUTES_SYSTEM_PROMPT,
                )
            else:
                response = await asyncio.to_thread(
                    get_ai_response_func,
                    [{"role": "user", "content": prompt}],
                    MINUTES_SYSTEM_PROMPT,
                )

            if response:
                return parse_minutes_response(response)
        except Exception as e:
            logger.warning("Minutes generation failed: %s", type(e).__name__)

        return None

    @staticmethod
    def _build_transcript_only_message(
        title: str,
        sanitized: str,
        pii_count: int,
        vtt: VTTTranscript,
    ) -> str:
        """Fallback message when LLM minutes generation is unavailable."""
        preview = sanitized[:500] + "..." if len(sanitized) > 500 else sanitized
        speakers_list = ", ".join(vtt.speakers[:10])
        duration_min = int(vtt.duration_seconds // 60)
        parts = [
            f"[info][title]{title} - \u6587\u5b57\u8d77\u3053\u3057[/title]",
        ]
        if speakers_list:
            parts.append(f"\u53c2\u52a0\u8005: {speakers_list}")
        parts.append(
            f"\u767a\u8a00\u6570: {len(vtt.segments)}, "
            f"\u6240\u8981\u6642\u9593: {duration_min}\u5206"
        )
        if pii_count > 0:
            parts.append(
                f"\u500b\u4eba\u60c5\u5831 {pii_count}\u4ef6 "
                f"\u3092\u81ea\u52d5\u30de\u30b9\u30ad\u30f3\u30b0\u3057\u307e\u3057\u305f\u3002"
            )
        parts.append(f"\n--- \u30d7\u30ec\u30d3\u30e5\u30fc ---\n{preview}")
        parts.append("[/info]")
        return "\n".join(parts)


def _parse_zoom_datetime(dt_str: Optional[str]) -> Optional[datetime]:
    """Parse Zoom datetime format: '2026-02-09T10:00:00Z'"""
    if not dt_str:
        return None
    try:
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
