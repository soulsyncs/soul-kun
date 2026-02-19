# lib/meetings/google_meet_brain_interface.py
"""
Google Meet議事録機能のBrain連携インターフェース

Brain（lib/brain/）との唯一の接続点（zoom_brain_interface.pyと同パターン）。

フロー:
1. ユーザー「今日のGoogle Meetの議事録まとめて」→ Brain Tool呼び出し
2. Drive API → 直近のMeet録画を検索
3. 自動文字起こし（Google Docs）があれば取得。なければ録画をWhisper APIで文字起こし
4. PII除去 → DB保存（brain_approved=FALSE）
5. LLM議事録生成（Brain経由）
6. HandlerResult返却 → Brainが投稿判断

Author: Claude Sonnet 4.6
Created: 2026-02-19
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

from lib.brain.models import HandlerResult
from lib.meetings.meeting_db import MeetingDB
from lib.meetings.transcript_sanitizer import TranscriptSanitizer
from lib.meetings.google_meet_drive_client import (
    GoogleMeetDriveClient,
    MeetRecordingFile,
    create_meet_drive_client_from_db,
    MAX_DOWNLOAD_BYTES,
)
from lib.meetings.minutes_generator import (
    build_chatwork_minutes_prompt,
    format_chatwork_minutes,
    CHATWORK_MINUTES_SYSTEM_PROMPT,
)

logger = logging.getLogger(__name__)

GOOGLE_MEET_TRANSCRIPT_NOT_READY_MESSAGE = (
    "Google Meetの録画がまだ見つからないウル。"
    "会議終了後、Googleドライブに録画が保存されるまで"
    "数分かかることがあるウル。少し待ってからまた聞いてほしいウル\U0001f43a"
)

GOOGLE_MEET_NO_OAUTH_MESSAGE = (
    "Google カレンダー連携が設定されていないウル。"
    "管理画面の「連携設定」からGoogleアカウントを接続してほしいウル\U0001f43a"
)

# 録画ファイルのWhisper文字起こしに使う音声フォーマット
_WHISPER_FILENAME = "meet_recording.mp4"


class GoogleMeetBrainInterface:
    """
    Google Meet議事録機能とBrainの連携インターフェース。

    責務:
    - Drive APIから録画を検索・ダウンロード
    - 自動文字起こし（Google Docs）の取得、なければWhisper APIで文字起こし
    - PII除去 → DB保存（source='google_meet'）
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
        drive_client: Optional[GoogleMeetDriveClient] = None,
    ):
        if not organization_id or not organization_id.strip():
            raise ValueError("organization_id is required")
        self.pool = pool
        self.organization_id = organization_id
        self.db = MeetingDB(pool, organization_id)
        self.sanitizer = TranscriptSanitizer()
        self._drive_client = drive_client

    def _get_drive_client(self) -> Optional[GoogleMeetDriveClient]:
        """Lazy-init Drive client from DB OAuth tokens."""
        if self._drive_client is None:
            self._drive_client = create_meet_drive_client_from_db(
                self.pool, self.organization_id
            )
        return self._drive_client

    async def process_google_meet_minutes(
        self,
        room_id: str,
        account_id: str,
        days_back: int = 1,
        meeting_title_filter: Optional[str] = None,
        get_ai_response_func: Optional[Callable] = None,
    ) -> HandlerResult:
        """
        Google Meet議事録を生成する。

        Args:
            room_id: ChatWorkルームID
            account_id: ユーザーアカウントID
            days_back: 何日前まで検索するか（デフォルト: 1日）
            meeting_title_filter: 会議名フィルタ（部分一致）
            get_ai_response_func: LLM呼び出し関数（Brain側から注入）

        Returns:
            HandlerResult with minutes data
        """
        try:
            # Step 1: Drive クライアント取得
            drive_client = await asyncio.to_thread(self._get_drive_client)
            if drive_client is None:
                return HandlerResult(
                    success=False,
                    message=GOOGLE_MEET_NO_OAUTH_MESSAGE,
                    data={},
                )

            # Step 2: 録画ファイルを検索
            recordings = await asyncio.to_thread(
                drive_client.find_recent_recordings,
                days_back,
            )

            if not recordings:
                return HandlerResult(
                    success=False,
                    message=GOOGLE_MEET_TRANSCRIPT_NOT_READY_MESSAGE,
                    data={},
                )

            # タイトルフィルタ
            if meeting_title_filter:
                filtered = [
                    r for r in recordings
                    if meeting_title_filter.lower() in r.name.lower()
                ]
                if filtered:
                    recordings = filtered

            # 最新の録画を使用
            recording = recordings[0]
            logger.info(
                "Using Meet recording: name_prefix=%s..., size=%s bytes",
                recording.name[:20],
                recording.size_bytes,
            )

            # Step 3: 文字起こし取得（自動文字起こし → Whisper の順）
            transcript_text = await self._get_transcript(drive_client, recording)
            if not transcript_text:
                return HandlerResult(
                    success=False,
                    message=(
                        "録画の文字起こしが取得できなかったウル。"
                        "録画時間が長い場合は処理に時間がかかることがあるウル\U0001f43a"
                    ),
                    data={},
                )

            # Step 4: PII除去
            sanitized_text = self.sanitizer.sanitize(transcript_text)

            # Step 5: DB保存
            source_recording_id = recording.file_id
            meeting_date = recording.created_time or datetime.now(timezone.utc)
            meeting_title = self._extract_title(recording.name)

            transcript_id = await self.db.save_transcript(
                source="google_meet",
                source_meeting_id=source_recording_id,
                transcript_text=sanitized_text,
                meeting_date=meeting_date,
                meeting_title=meeting_title,
                room_id=room_id,
                account_id=account_id,
            )

            # Step 6: 議事録生成（LLMが注入されている場合）
            if get_ai_response_func is not None:
                return await self._generate_minutes(
                    sanitized_text,
                    meeting_title,
                    meeting_date,
                    transcript_id,
                    get_ai_response_func,
                    recording,
                )

            # LLM未注入の場合: 文字起こし結果のみ返す
            return HandlerResult(
                success=True,
                message=(
                    f"「{meeting_title}」の文字起こしを取得したウル\U0001f43a\n"
                    f"議事録生成機能が有効でないため、文字起こし結果のみウル。\n"
                    f"（{len(sanitized_text)}文字）"
                ),
                data={
                    "transcript_id": str(transcript_id),
                    "meeting_title": meeting_title,
                    "transcript_length": len(sanitized_text),
                },
            )

        except Exception as e:
            logger.error(
                "GoogleMeetBrainInterface error: %s", type(e).__name__, exc_info=True
            )
            return HandlerResult(
                success=False,
                message=(
                    "Google Meetの議事録取得中にエラーが発生したウル\U0001f43a"
                    "しばらく待ってからもう一度試してほしいウル。"
                ),
                data={"error_type": type(e).__name__},
            )

    async def _get_transcript(
        self,
        drive_client: GoogleMeetDriveClient,
        recording: MeetRecordingFile,
    ) -> Optional[str]:
        """
        文字起こしを取得する。
        優先順位: Google自動文字起こし(Docs) > Whisper API

        Args:
            drive_client: Drive APIクライアント
            recording: 録画ファイル情報

        Returns:
            文字起こしテキスト、またはNone
        """
        # 優先1: Google自動文字起こし（Workspace有料プランで利用可）
        auto_transcript = await asyncio.to_thread(
            drive_client.get_auto_transcript,
            recording.file_id,
        )
        if auto_transcript and len(auto_transcript.strip()) > 50:
            logger.info(
                "Using Google auto-transcript (%d chars)", len(auto_transcript)
            )
            return auto_transcript

        # 優先2: 録画をダウンロードしてWhisper APIで文字起こし
        logger.info("Auto-transcript not available, falling back to Whisper API")

        # サイズチェック（巨大ファイルはスキップ）
        if recording.size_bytes and recording.size_bytes > MAX_DOWNLOAD_BYTES * 2:
            logger.warning(
                "Recording too large for Whisper (%d bytes), skipping",
                recording.size_bytes,
            )
            return None

        try:
            audio_bytes = await asyncio.to_thread(
                drive_client.download_recording_bytes,
                recording.file_id,
                MAX_DOWNLOAD_BYTES,
            )
        except Exception as e:
            logger.error(
                "Failed to download recording: %s", type(e).__name__
            )
            return None

        return await self._transcribe_with_whisper(audio_bytes)

    async def _transcribe_with_whisper(self, audio_bytes: bytes) -> Optional[str]:
        """
        Whisper APIで音声を文字起こしする。

        既存のWhisperAPIClient（lib/capabilities/multimodal/audio_processor.py）を再利用。

        Args:
            audio_bytes: 音声データ

        Returns:
            文字起こしテキスト、またはNone
        """
        try:
            from lib.capabilities.multimodal.audio_processor import WhisperAPIClient
            import os
            import io

            openai_api_key = os.getenv("OPENAI_API_KEY", "")
            if not openai_api_key:
                from lib.secrets import get_secret_cached
                openai_api_key = get_secret_cached("openai-api-key") or ""

            if not openai_api_key:
                logger.error("OpenAI API key not configured for Whisper")
                return None

            whisper = WhisperAPIClient(api_key=openai_api_key)
            audio_file = io.BytesIO(audio_bytes)
            audio_file.name = _WHISPER_FILENAME

            transcript = await asyncio.to_thread(
                whisper.transcribe,
                audio_file,
            )
            logger.info("Whisper transcription: %d chars", len(transcript))
            return transcript

        except Exception as e:
            logger.error(
                "Whisper transcription failed: %s", type(e).__name__, exc_info=True
            )
            return None

    async def _generate_minutes(
        self,
        transcript_text: str,
        meeting_title: str,
        meeting_date: datetime,
        transcript_id,
        get_ai_response_func: Callable,
        recording: MeetRecordingFile,
    ) -> HandlerResult:
        """LLMで議事録を生成してHandlerResultを返す。"""
        try:
            prompt = build_chatwork_minutes_prompt(
                transcript_text=transcript_text,
                meeting_title=meeting_title,
                meeting_date=meeting_date.strftime("%Y-%m-%d"),
            )

            history: list = []
            raw_minutes = await asyncio.to_thread(
                get_ai_response_func,
                prompt,
                history,
                "meeting_minutes_bot",
            )

            formatted = format_chatwork_minutes(raw_minutes, meeting_title, meeting_date)

            # DB更新: brain_approved=TRUE
            await self.db.approve_transcript(transcript_id)

            return HandlerResult(
                success=True,
                message=formatted,
                data={
                    "transcript_id": str(transcript_id),
                    "meeting_title": meeting_title,
                    "recording_name": recording.name,
                    "source": "google_meet",
                },
            )

        except Exception as e:
            logger.error(
                "Minutes generation failed: %s", type(e).__name__, exc_info=True
            )
            return HandlerResult(
                success=False,
                message=(
                    "議事録の生成中にエラーが発生したウル\U0001f43a"
                    "文字起こしは保存済みなので、もう一度試してほしいウル。"
                ),
                data={"transcript_id": str(transcript_id)},
            )

    @staticmethod
    def _extract_title(recording_name: str) -> str:
        """
        録画ファイル名から会議タイトルを抽出する。

        例: "週次定例 (2026-02-19 at 10:00 GMT).mp4" → "週次定例"
        """
        # "(YYYY-MM-DD at HH:MM GMT).mp4" を除去
        import re
        cleaned = re.sub(r"\s*\(\d{4}-\d{2}-\d{2} at \d+:\d+ [A-Z]+\)\.mp4$", "", recording_name)
        return cleaned.strip() or recording_name
