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
6. タスク自動抽出＆ChatWork作成（GM①）
7. ソウルくん記憶保存（GM②）
8. HandlerResult返却 → Brainが投稿判断
9. 送信失敗時→管理者DM通知（GM③ / routes/google_meet.py 側で実施）

Author: Claude Sonnet 4.6
Created: 2026-02-19
Updated: 2026-02-20 — GM①②③: タスク抽出・記憶保存・管理者通知
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

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
from lib.meetings.task_extractor import (
    extract_and_create_tasks,
    TaskExtractionResult,
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
        chatwork_client=None,
    ) -> HandlerResult:
        """
        Google Meet議事録を生成する。

        Args:
            room_id: ChatWorkルームID
            account_id: ユーザーアカウントID
            days_back: 何日前まで検索するか（デフォルト: 1日）
            meeting_title_filter: 会議名フィルタ（部分一致）
            get_ai_response_func: LLM呼び出し関数（Brain側から注入）
            chatwork_client: ChatWork APIクライアント（タスク作成に使用。任意）

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

            # Step 5: DB保存（MeetingDB の正しいAPI順序）
            source_recording_id = recording.file_id
            meeting_date = recording.created_time or datetime.now(timezone.utc)
            meeting_title = self._extract_title(recording.name)

            # 5a: meetings テーブルにレコードを作成
            meeting = await asyncio.to_thread(
                self.db.create_meeting,
                title=meeting_title,
                meeting_type="google_meet",
                created_by=account_id,
                room_id=room_id,
                source="google_meet",
                source_meeting_id=source_recording_id,
                meeting_date=meeting_date,
            )
            meeting_id = meeting["id"]

            # 5b: PII除去済みの文字起こしを保存（raw_transcript=None: PII保護）
            transcript_result = await asyncio.to_thread(
                self.db.save_transcript,
                meeting_id=meeting_id,
                raw_transcript=None,
                sanitized_transcript=sanitized_text,
                detected_language="ja",
                word_count=len(sanitized_text),
            )
            transcript_id = transcript_result["id"]

            # 5c: ステータスを "transcribed" に更新
            await asyncio.to_thread(
                self.db.update_meeting_status,
                meeting_id,
                "transcribed",
                expected_version=1,
                transcript_sanitized=True,
            )

            # Step 6: 議事録生成（LLMが注入されている場合）
            minutes: Optional[str] = None
            if get_ai_response_func is not None:
                minutes = await self._generate_minutes_text(
                    sanitized_text,
                    meeting_title,
                    meeting_date,
                    meeting_id,
                    get_ai_response_func,
                )

            # Step 7: タスク自動抽出＆ChatWork作成（GM①）
            task_result: Optional[TaskExtractionResult] = None
            if minutes and get_ai_response_func:
                try:
                    task_result = await extract_and_create_tasks(
                        minutes_text=minutes,
                        meeting_title=meeting_title,
                        room_id=room_id,
                        organization_id=self.organization_id,
                        get_ai_response_func=get_ai_response_func,
                        chatwork_client=chatwork_client,
                        name_resolver=self._build_name_resolver(),
                    )
                    if task_result and task_result.total_extracted > 0:
                        logger.info(
                            "Tasks extracted: %d, created: %d",
                            task_result.total_extracted,
                            task_result.total_created,
                        )
                except Exception as e:
                    logger.warning("Task extraction failed: %s", type(e).__name__)

            # Step 8: 3点セットメッセージ組み立て
            drive_url = recording.web_view_link  # Google Drive の録画URL
            if minutes:
                message = self._build_delivery_message(
                    title=meeting_title,
                    minutes_text=minutes,
                    drive_url=drive_url,
                    task_result=task_result,
                )
            else:
                message = (
                    f"「{meeting_title}」の文字起こしを取得したウル\U0001f43a\n"
                    f"議事録生成機能が有効でないため、文字起こし結果のみウル。\n"
                    f"（{len(sanitized_text)}文字）"
                )

            # Step 9: 議事録をソウルくんの記憶に保存（GM②・非クリティカル）
            # CLAUDE.md §9-2準拠: 議事録本文（PII可能性あり）は保存しない。
            # タイトル・メタ情報のみをエピソード記憶として保存する。
            if minutes:
                try:
                    await self._save_minutes_to_memory(
                        meeting_id=meeting_id,
                        title=meeting_title,
                        room_id=room_id,
                        drive_url=drive_url or "",
                        task_count=task_result.total_created if task_result else 0,
                    )
                except Exception as mem_err:
                    logger.warning(
                        "Memory save skipped (non-critical): %s", type(mem_err).__name__
                    )

            logger.info(
                "Google Meet minutes generated: meeting_id=%s, title_prefix=%s...",
                meeting_id,
                meeting_title[:20],
            )

            return HandlerResult(
                success=True,
                message=message,
                data={
                    "meeting_id": meeting_id,
                    "transcript_id": transcript_id,
                    "meeting_title": meeting_title,
                    "source": "google_meet",
                    "drive_url": drive_url or "",
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

    async def _generate_minutes_text(
        self,
        transcript_text: str,
        meeting_title: str,
        meeting_date: datetime,
        meeting_id: str,
        get_ai_response_func: Callable,
    ) -> Optional[str]:
        """
        LLMで議事録テキストを生成して返す（zoom_brain_interface.pyと同パターン）。

        Returns:
            フォーマット済み議事録テキスト。失敗時はNone。
        """
        try:
            # C-1修正: meeting_dateはbuild_chatwork_minutes_promptの引数に存在しない
            prompt = build_chatwork_minutes_prompt(transcript_text, meeting_title)

            # C-2修正: async/sync callable を判別して適切に呼ぶ（Zoomと同パターン）
            if asyncio.iscoroutinefunction(get_ai_response_func):
                raw_minutes = await get_ai_response_func(
                    prompt,
                    system_prompt=CHATWORK_MINUTES_SYSTEM_PROMPT,
                )
            else:
                raw_minutes = await asyncio.to_thread(
                    get_ai_response_func,
                    prompt,
                    system_prompt=CHATWORK_MINUTES_SYSTEM_PROMPT,
                )

            if not raw_minutes:
                return None

            formatted = format_chatwork_minutes(raw_minutes, meeting_title, meeting_date)

            # DB更新: status="completed", brain_approved=True
            await asyncio.to_thread(
                self.db.update_meeting_status,
                meeting_id,
                "completed",
                expected_version=2,
                brain_approved=True,
            )

            return formatted

        except Exception as e:
            logger.warning(
                "Minutes generation failed: %s", type(e).__name__
            )
            return None

    def _build_name_resolver(self):
        """
        名前→ChatWork account_id 解決関数を返す（zoom_brain_interface.pyと同パターン）。

        chatwork_usersテーブルとusersテーブルからLIKE検索で名前を解決。
        """
        from sqlalchemy import text as sa_text

        pool = self.pool
        org_id = self.organization_id

        def resolver(name: str) -> Optional[str]:
            if not name:
                return None
            # 「さん」「くん」等の敬称を除去
            clean_name = name.rstrip("さんくんちゃん様氏")
            if not clean_name:
                return None

            with pool.connect() as conn:
                # chatwork_usersテーブルから検索
                row = conn.execute(
                    sa_text("""
                        SELECT cu.account_id
                        FROM chatwork_users cu
                        WHERE cu.organization_id = :org_id
                          AND cu.name LIKE :pattern
                        LIMIT 1
                    """),
                    {"org_id": org_id, "pattern": f"%{clean_name}%"},
                ).fetchone()
                if row:
                    return str(row[0])

                # usersテーブルからもフォールバック検索
                row = conn.execute(
                    sa_text("""
                        SELECT u.chatwork_account_id
                        FROM users u
                        WHERE u.organization_id = :org_id
                          AND u.name LIKE :pattern
                          AND u.chatwork_account_id IS NOT NULL
                        LIMIT 1
                    """),
                    {"org_id": org_id, "pattern": f"%{clean_name}%"},
                ).fetchone()
                if row:
                    return str(row[0])

            return None

        return resolver

    @staticmethod
    def _build_delivery_message(
        title: str,
        minutes_text: str,
        drive_url: Optional[str] = None,
        task_result: Optional[TaskExtractionResult] = None,
    ) -> str:
        """
        3点セット（Drive録画URL + 議事録テキスト + タスク結果）の
        ChatWorkメッセージを組み立てる。
        """
        parts = [f"[info][title]\U0001f4cb {title} - 議事録[/title]"]

        # Google Drive の録画URL
        if drive_url:
            parts.append(f"\U0001f4f9 録画 (Google Drive): {drive_url}")
            parts.append("")

        # 議事録テキスト
        parts.append(minutes_text)

        # タスク抽出結果
        if task_result and task_result.total_extracted > 0:
            parts.append("")
            parts.append(f"\u2705 タスク: {task_result.total_created}件作成")
            if task_result.total_unassigned > 0:
                parts.append(
                    f"\u26a0 担当者不明: {task_result.total_unassigned}件"
                    "（手動で担当者を設定してください）"
                )

        parts.append("[/info]")
        return "\n".join(parts)

    async def _save_minutes_to_memory(
        self,
        meeting_id: str,
        title: str,
        room_id: str,
        drive_url: str,
        task_count: int,
    ) -> None:
        """
        会議メタ情報をソウルくんのエピソード記憶に保存する（GM②）。

        CLAUDE.md §9-2準拠:
        - 議事録本文は保存しない（PII可能性あり）
        - タイトル・meeting_id・room_id・task_count のみ保存
        - タイトルは「業務に必要な事実」として保存可（§9-2 カテゴリ1）
        """
        from lib.brain.memory_enhancement import (
            BrainMemoryEnhancement,
            EpisodeType,
            EntityType,
            EntityRelationship,
            RelatedEntity,
        )

        title_words = [w for w in title.replace("\u3000", " ").split() if len(w) >= 2]
        keywords = list(dict.fromkeys(["会議", "議事録", "Google Meet"] + title_words[:5]))

        task_info = f"・タスク{task_count}件" if task_count > 0 else ""
        summary = f"Google Meet「{title}」の議事録を作成{task_info}"
        if len(summary) > 200:
            summary = summary[:197] + "..."

        entities = [
            RelatedEntity(
                entity_type=EntityType.MEETING,
                entity_id=meeting_id,
                entity_name=title,
                relationship=EntityRelationship.INVOLVED,
            ),
            RelatedEntity(
                entity_type=EntityType.ROOM,
                entity_id=room_id,
                entity_name=f"ChatWorkルーム#{room_id}",
                relationship=EntityRelationship.INVOLVED,
            ),
        ]

        memory = BrainMemoryEnhancement(self.organization_id)

        def _save_sync() -> None:
            with self.pool.connect() as conn:
                memory.record_episode(
                    conn=conn,
                    episode_type=EpisodeType.INTERACTION,
                    summary=summary,
                    details={
                        "meeting_id": meeting_id,
                        "title": title,
                        "room_id": room_id,
                        "drive_url": drive_url,
                        "task_count": task_count,
                        "source": "google_meet",
                    },
                    keywords=keywords,
                    entities=entities,
                    importance=0.7,
                )
                conn.commit()

        await asyncio.to_thread(_save_sync)
        logger.info("Meeting episode saved to memory: meeting_id=%s", meeting_id)

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
