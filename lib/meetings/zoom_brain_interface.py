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
from typing import Any, Callable, Dict, Optional

from lib.brain.models import HandlerResult
from lib.meetings.meeting_db import MeetingDB
from lib.meetings.transcript_sanitizer import TranscriptSanitizer
from lib.meetings.zoom_api_client import ZoomAPIClient, create_zoom_client_from_secrets
from lib.meetings.vtt_parser import parse_vtt, VTTTranscript
from lib.meetings.minutes_generator import (
    build_chatwork_minutes_prompt,
    format_chatwork_minutes,
    CHATWORK_MINUTES_SYSTEM_PROMPT,
)
from lib.meetings.docs_brain_integration import (
    create_meeting_docs_publisher,
)
from lib.meetings.task_extractor import (
    extract_and_create_tasks,
    TaskExtractionResult,
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
        chatwork_client=None,
        recording_data_override: Optional[Dict[str, Any]] = None,
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

            assert recording_data is not None  # Noneは上でreturn済み
            api_files = recording_data.get("recording_files", [])
            logger.debug("recording_files types: %s, meeting_id=%s",
                         [f.get("file_type") for f in api_files], recording_data.get("id"))

            # Extract source meeting ID (null-safe: id=None → None, not "")
            raw_id = recording_data.get("id")
            source_mid = str(raw_id) if raw_id else None

            # Step 2: Find VTT transcript URL
            # recording.transcript_completed イベントではVTTが既に生成済み。
            # recording.completed イベントでもVTTが存在すれば即座に処理する。
            # リトライなし: VTTが存在しない場合は transcript_completed イベントを待つ。
            transcript_url = await asyncio.to_thread(
                zoom_client.find_transcript_url,
                recording_data,
            )

            if transcript_url is None:
                logger.debug("find_transcript_url returned None (VTT not yet ready)")
                return HandlerResult(
                    success=False,
                    message=ZOOM_TRANSCRIPT_NOT_READY_MESSAGE,
                    data={
                        "zoom_meeting_id": source_mid or "",
                        "retry": False,
                    },
                )

            vtt_content = await asyncio.to_thread(
                zoom_client.download_transcript,
                transcript_url,
            )
            if not vtt_content or not vtt_content.strip():
                return HandlerResult(
                    success=False,
                    message=ZOOM_TRANSCRIPT_NOT_READY_MESSAGE,
                    data={"zoom_meeting_id": source_mid or ""},
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
            # source_midがNoneの場合もdedup_hash（topic+start_timeのSHA256）でフォールバック。
            # topicはSHA256でハッシュ化されるためPII文字列はDBに保存されない（§3-2 #8準拠）。
            dedup_hash: Optional[str] = MeetingDB.build_dedup_hash(
                "zoom",
                recording_data.get("topic", ""),
                recording_data.get("start_time", ""),
            )
            existing = await asyncio.to_thread(
                self.db.find_meeting_by_source_id,
                source="zoom",
                source_meeting_id=source_mid,
                dedup_hash=dedup_hash,
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
                dedup_hash=dedup_hash,
            )
            meeting_id = meeting["id"]

            # CLAUDE.md §3-2 #8 準拠: PIIをDB保存に含めない。
            # raw_transcript=None: Zoom VTTには話者名（PII）が含まれるため保存しない。
            # segments_json=None, speakers_json=None: 話者名がPIIに該当。
            # sanitized_transcriptのみ保存（PII除去済み）。
            await asyncio.to_thread(
                self.db.save_transcript,
                meeting_id=meeting_id,
                raw_transcript=None,
                sanitized_transcript=sanitized_text,
                segments_json=None,
                speakers_json=None,
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

            # Step 8: 録画URL取得
            assert recording_data is not None  # Step 1で早期リターン済み
            recording_play_url = await asyncio.to_thread(
                zoom_client.find_recording_play_url,
                recording_data,
            )

            # Step 9: Googleドキュメント保存（有効時のみ）
            document_url = ""
            if minutes:
                try:
                    docs_publisher = create_meeting_docs_publisher(
                        pool=self.pool,
                        organization_id=self.organization_id,
                    )
                    if docs_publisher:
                        docs_result = await docs_publisher.publish_to_google_docs(
                            meeting_id=meeting_id,
                            minutes_text=minutes,
                            title=resolved_title,
                            expected_version=2,
                        )
                        document_url = docs_result.get("document_url", "")
                        if document_url:
                            logger.info("Minutes saved to Google Docs: %s", document_url)
                except Exception as e:
                    logger.warning("Google Docs publish failed: %s", type(e).__name__)

            # Step 10: タスク自動抽出＆ChatWork作成
            task_result: Optional[TaskExtractionResult] = None
            if minutes and get_ai_response_func:
                try:
                    task_result = await extract_and_create_tasks(
                        minutes_text=minutes,
                        meeting_title=resolved_title,
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

            # Step 11: Build result（3点セットメッセージ）
            # CLAUDE.md §3-2 #8: speakersリスト（話者名=PII）はresult_dataに含めない。
            result_data: Dict[str, Any] = {
                "meeting_id": meeting_id,
                "status": "transcribed",
                "title": resolved_title,
                "zoom_meeting_id": source_mid or "",
                "speakers_detected": len(vtt_transcript.speakers),
                "duration_seconds": vtt_transcript.duration_seconds,
                "pii_removed_count": pii_count,
                "segment_count": len(vtt_transcript.segments),
                "recording_url": recording_play_url or "",
                "document_url": document_url,
            }

            if minutes:
                result_data["minutes_text"] = minutes
                message = self._build_delivery_message(
                    title=resolved_title,
                    minutes_text=minutes,
                    recording_url=recording_play_url,
                    document_url=document_url,
                    task_result=task_result,
                )
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

            # Step 12: 議事録をソウルくんの記憶に保存（非クリティカル）
            # 目的: 「あの会議で何を決めたか」をソウルくんに後で聞けるようにする。
            # CLAUDE.md §9-2準拠: 議事録本文（PII可能性あり）は保存しない。
            #   タイトル・メタ情報のみをエピソード記憶として保存する。
            # 失敗しても議事録送信はブロックしない（try/except で保護）。
            if minutes:
                try:
                    await self._save_minutes_to_memory(
                        meeting_id=meeting_id,
                        title=resolved_title,
                        room_id=room_id,
                        document_url=document_url,
                        duration_seconds=vtt_transcript.duration_seconds,
                        task_count=task_result.total_created if task_result else 0,
                    )
                except Exception as mem_err:
                    logger.warning(
                        "Memory save skipped (non-critical): %s", type(mem_err).__name__
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

        # Search recent recordings (last 2 days)
        # 7日→2日に短縮: 直近の録画のみ対象にすることで誤爆を防ぐ。
        # 2日にする理由: 深夜23時開始→翌日1時終了の会議でZoomが翌日2時に
        # 録画処理するケースで、days=1だとfrom_dateが翌日になり録画が
        # 見つからなくなるため2日を保持。
        user_id = zoom_user_email or "me"
        from_date = (
            datetime.now(timezone.utc) - timedelta(days=2)
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

    async def _save_minutes_to_memory(
        self,
        meeting_id: str,
        title: str,
        room_id: str,
        document_url: str,
        duration_seconds: float,
        task_count: int,
    ) -> None:
        """議事録の要約をエピソード記憶（brain_episodes）に保存する（Step 12）

        CLAUDE.md §9-2準拠:
        - 議事録本文（PII可能性あり）は保存しない
        - タイトル・メタ情報のみを保存
        - これにより「先月の会議で何を決めたか」をソウルくんに聞ける

        Raises:
            Exception: DB接続失敗など（呼び出し元でtry/exceptすること）
        """
        from lib.brain.memory_enhancement import (
            BrainMemoryEnhancement,
            EpisodeType,
            EntityType,
            EntityRelationship,
            RelatedEntity,
        )

        # キーワード: 会議タイトルの単語（2文字以上）＋固定キーワード
        title_words = [
            w for w in title.replace("\u3000", " ").split()
            if len(w) >= 2
        ]
        keywords = list(
            dict.fromkeys(["会議", "議事録", "Zoom"] + title_words[:5])
        )

        # Summary（200文字上限）
        # CLAUDE.md §9-2 設計判断: 会議タイトルは「業務に必要な事実」として保存する。
        # 例: "週次朝会"・"受注確認MTG" はビジネス文脈の事実であり記憶すべき情報。
        # 議事録本文（PII可能性あり）は保存しない（上流でこのメソッドに渡さない）。
        task_info = f"・タスク{task_count}件" if task_count > 0 else ""
        summary = f"Zoom会議「{title}」の議事録を作成{task_info}"
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
                        "document_url": document_url,
                        "duration_seconds": int(duration_seconds),
                        "task_count": task_count,
                        "source": "zoom",
                    },
                    keywords=keywords,
                    entities=entities,
                    importance=0.7,
                )
                conn.commit()

        await asyncio.to_thread(_save_sync)
        logger.info("Meeting episode saved to memory: meeting_id=%s", meeting_id)

    async def _generate_minutes(
        self,
        sanitized_text: str,
        title: str,
        get_ai_response_func: Callable,
    ) -> Optional[str]:
        """Generate lecture-style minutes using LLM (Vision 12.2.4 format).

        Returns plain text with ■主題（00:00〜）sections,
        not JSON-structured MeetingMinutes.
        """
        try:
            prompt = build_chatwork_minutes_prompt(sanitized_text, title)

            if asyncio.iscoroutinefunction(get_ai_response_func):
                response = await get_ai_response_func(
                    prompt,
                    system_prompt=CHATWORK_MINUTES_SYSTEM_PROMPT,
                )
            else:
                response = await asyncio.to_thread(
                    get_ai_response_func,
                    prompt,
                    system_prompt=CHATWORK_MINUTES_SYSTEM_PROMPT,
                )

            if response:
                return response
        except Exception as e:
            logger.warning("Minutes generation failed: %s", type(e).__name__)

        return None

    def _build_name_resolver(self):
        """
        名前→ChatWork account_id 解決関数を返す。

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
        recording_url: Optional[str] = None,
        document_url: Optional[str] = None,
        task_result: Optional[TaskExtractionResult] = None,
    ) -> str:
        """
        3点セット（録画URL + GoogleドキュメントURL + 議事録テキスト）の
        ChatWorkメッセージを組み立てる。
        """
        parts = [f"[info][title]\U0001f4cb {title} - 議事録[/title]"]

        # (a) 録画動画URL
        if recording_url:
            parts.append(f"\U0001f3ac 録画: {recording_url}")
        # (b) GoogleドキュメントURL
        if document_url:
            parts.append(f"\U0001f4c4 Google Docs: {document_url}")
        # 区切り
        if recording_url or document_url:
            parts.append("")

        # (c) 議事録テキスト
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

    @staticmethod
    def _build_transcript_only_message(
        title: str,
        sanitized: str,
        pii_count: int,
        vtt: VTTTranscript,
    ) -> str:
        """Fallback message when LLM minutes generation is unavailable."""
        preview = sanitized[:500] + "..." if len(sanitized) > 500 else sanitized
        speakers_count = len(vtt.speakers)
        duration_min = int(vtt.duration_seconds // 60)
        parts = [
            f"[info][title]{title} - \u6587\u5b57\u8d77\u3053\u3057[/title]",
        ]
        if speakers_count > 0:
            parts.append(f"\u53c2\u52a0\u8005: {speakers_count}\u540d")
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
