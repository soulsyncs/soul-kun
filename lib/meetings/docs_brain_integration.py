# lib/meetings/docs_brain_integration.py
"""
Phase 6: Google Docs出力 + Brain記憶統合

議事録をGoogle Docsに保存し、会議情報をBrainのエピソード記憶として永続化する。

設計書: docs/12_2_zoom_auto_minutes_vision.md セクション12.2.6

フロー:
1. GoogleDocsClient で議事録ドキュメント作成
2. MeetingDB に document_url/document_id を保存
3. conversation_summaries に会議サマリーを保存（Brainのエピソード記憶）
4. HandlerResult を返却

Feature flag: ENABLE_MEETING_DOCS（デフォルト無効）

Author: Claude Opus 4.6
Created: 2026-02-13
"""

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional
from uuid import UUID

from sqlalchemy import text

from lib.brain.models import HandlerResult
from lib.meetings.meeting_db import MeetingDB

logger = logging.getLogger(__name__)

# Feature flag
ENABLE_MEETING_DOCS = os.getenv("ENABLE_MEETING_DOCS", "false").lower() == "true"

# Google Docs フォルダID（議事録保存先）
MEETING_DOCS_FOLDER_ID = os.getenv("MEETING_DOCS_FOLDER_ID", "")

# Brain記憶の分類
MEETING_MEMORY_CLASSIFICATION = "meeting_minutes"

# 議事録テキストの最大長（Google Docs書き込み用）
MAX_MINUTES_LENGTH = 100000

# 会議サマリーの最大長（conversation_summaries保存用）
MAX_SUMMARY_LENGTH = 2000


class MeetingDocsPublisher:
    """
    議事録のGoogle Docs出力とBrain記憶統合。

    責務:
    - Google Docsドキュメント作成・書き込み
    - meeting DBのdocument_url/document_id更新
    - conversation_summariesへのエピソード記憶保存

    非責務:
    - 議事録テキスト生成（Phase 1で生成済み）
    - ChatWork投稿判断（Brain側）
    """

    def __init__(
        self,
        pool,
        organization_id: str,
        google_docs_client=None,
    ):
        if not organization_id or not organization_id.strip():
            raise ValueError("organization_id is required")
        self.pool = pool
        self.organization_id = organization_id
        self.db = MeetingDB(pool, organization_id)
        self._docs_client = google_docs_client

    def _get_docs_client(self):
        """Lazy-init Google Docs client."""
        if self._docs_client is None:
            from lib.capabilities.generation.google_docs_client import (
                create_google_docs_client,
            )
            self._docs_client = create_google_docs_client()
        return self._docs_client

    async def publish_to_google_docs(
        self,
        meeting_id: str,
        minutes_text: str,
        title: str,
        expected_version: int,
    ) -> Dict[str, Any]:
        """
        議事録をGoogle Docsに保存し、meeting DBを更新する。

        Args:
            meeting_id: 会議ID
            minutes_text: 議事録テキスト（Markdown形式）
            title: ドキュメントタイトル
            expected_version: 楽観ロック用バージョン

        Returns:
            {"document_id": "...", "document_url": "..."} or empty dict on failure

        Raises:
            ValueError: meeting_idが空の場合
        """
        if not meeting_id or not meeting_id.strip():
            raise ValueError("meeting_id is required")

        if not minutes_text or not minutes_text.strip():
            logger.warning("Empty minutes_text, skipping Google Docs publish")
            return {}

        # テキスト長制限
        truncated_text = minutes_text[:MAX_MINUTES_LENGTH]

        try:
            docs_client = self._get_docs_client()

            # Google Docsドキュメント作成
            folder_id = MEETING_DOCS_FOLDER_ID or None
            doc_result = await docs_client.create_document(
                title=f"議事録: {title}",
                folder_id=folder_id,
            )
            document_id = doc_result["document_id"]
            document_url = doc_result["document_url"]

            # Markdown形式で書き込み
            await docs_client.write_markdown_content(
                document_id=document_id,
                markdown_content=truncated_text,
            )

            # meeting DBを更新（document_url + document_id）
            updated = await asyncio.to_thread(
                self.db.update_meeting_status,
                meeting_id,
                "published",
                expected_version=expected_version,
                document_url=document_url,
                document_id=document_id,
            )

            if not updated:
                logger.warning(
                    "Meeting status update failed (version conflict): "
                    "meeting_id=%s, expected_version=%d",
                    meeting_id, expected_version,
                )
                # ドキュメント自体は作成済みなので情報は返す
                return {
                    "document_id": document_id,
                    "document_url": document_url,
                    "db_updated": False,
                }

            logger.info(
                "Meeting published to Google Docs: meeting_id=%s, doc_id=%s",
                meeting_id, document_id,
            )

            return {
                "document_id": document_id,
                "document_url": document_url,
                "db_updated": True,
            }

        except Exception as e:
            logger.error(
                "Google Docs publish failed: meeting_id=%s, error=%s: %r",
                meeting_id, type(e).__name__, e,
            )
            return {}

    async def store_meeting_memory(
        self,
        meeting_id: str,
        summary_text: str,
        title: str,
        key_topics: Optional[List[str]] = None,
        mentioned_persons: Optional[List[str]] = None,
        room_id: Optional[str] = None,
        meeting_date: Optional[datetime] = None,
    ) -> bool:
        """
        会議サマリーをBrainのエピソード記憶（conversation_summaries）に保存。

        Brainが将来の会話で「先週の会議で何を話した？」等の質問に答えられるよう、
        会議のサマリーを長期記憶として永続化する。

        Args:
            meeting_id: 会議ID（mentioned_tasksとして参照）
            summary_text: 会議サマリーテキスト
            title: 会議タイトル
            key_topics: 主要トピック
            mentioned_persons: 言及された人物
            room_id: ChatWorkルームID
            meeting_date: 会議日時

        Returns:
            True: 保存成功, False: 保存失敗
        """
        if not summary_text or not summary_text.strip():
            logger.warning("Empty summary_text, skipping memory storage")
            return False

        # organization_idがUUID形式でない場合はスキップ
        # conversation_summaries.organization_id は UUID型
        try:
            UUID(self.organization_id)
        except (ValueError, AttributeError):
            logger.warning(
                "organization_id is not UUID format, skipping memory storage: %s...",
                self.organization_id[:8] if self.organization_id else "empty",
            )
            return False

        now = meeting_date or datetime.now(timezone.utc)
        truncated_summary = summary_text[:MAX_SUMMARY_LENGTH]
        safe_topics = (key_topics or [])[:10]
        safe_persons = (mentioned_persons or [])[:10]

        try:
            def _sync_store():
                with self.pool.connect() as conn:
                    conn.rollback()
                    conn.execute(
                        text("SELECT set_config('statement_timeout', '5000', true)")
                    )
                    conn.execute(
                        text("""
                            INSERT INTO conversation_summaries (
                                organization_id, user_id,
                                summary_text, key_topics,
                                mentioned_persons, mentioned_tasks,
                                conversation_start, conversation_end,
                                message_count, room_id,
                                generated_by, classification
                            )
                            SELECT
                                CAST(:org_id AS uuid),
                                u.id,
                                :summary_text,
                                :key_topics,
                                :mentioned_persons,
                                ARRAY[:meeting_ref]::text[],
                                :meeting_date,
                                :meeting_date,
                                0,
                                :room_id,
                                'meeting_minutes',
                                :classification
                            FROM users u
                            WHERE u.organization_id = :org_id
                              AND u.role = 'admin'
                              AND NOT EXISTS (
                                  SELECT 1 FROM conversation_summaries cs2
                                  WHERE cs2.organization_id = CAST(:org_id AS uuid)
                                    AND :meeting_ref = ANY(cs2.mentioned_tasks)
                              )
                            LIMIT 1
                        """),
                        {
                            "org_id": self.organization_id,
                            "summary_text": f"【会議議事録】{title}\n\n{truncated_summary}",
                            "key_topics": safe_topics,
                            "mentioned_persons": safe_persons,
                            "meeting_ref": f"meeting:{meeting_id}",
                            "meeting_date": now,
                            "room_id": room_id,
                            "classification": MEETING_MEMORY_CLASSIFICATION,
                        },
                    )
                    conn.commit()

            await asyncio.to_thread(_sync_store)

            logger.info(
                "Meeting memory stored: meeting_id=%s, topics=%d",
                meeting_id, len(safe_topics),
            )
            return True

        except Exception as e:
            logger.error(
                "Meeting memory storage failed: meeting_id=%s, error=%s: %r",
                meeting_id, type(e).__name__, e,
            )
            return False

    async def publish_and_remember(
        self,
        meeting_id: str,
        minutes_text: str,
        title: str,
        expected_version: int,
        key_topics: Optional[List[str]] = None,
        mentioned_persons: Optional[List[str]] = None,
        room_id: Optional[str] = None,
        meeting_date: Optional[datetime] = None,
        summary_text: Optional[str] = None,
    ) -> HandlerResult:
        """
        議事録のGoogle Docs出力 + Brain記憶統合のオーケストレータ。

        publish_to_google_docs → store_meeting_memory を順次実行。
        PR #471教訓: pool.connect()同時呼び出しを避けるため並列実行しない。
        いずれかの失敗は非致命的（部分成功を許容）。

        Args:
            meeting_id: 会議ID
            minutes_text: 議事録テキスト（Markdown）
            title: 会議タイトル
            expected_version: 楽観ロック用バージョン
            key_topics: 主要トピック（Brain記憶用）
            mentioned_persons: 言及された人物（Brain記憶用）
            room_id: ChatWorkルームID
            meeting_date: 会議日時
            summary_text: 会議サマリー（Noneの場合はminutes_textの先頭部分を使用）

        Returns:
            HandlerResult with document info and memory status
        """
        if not minutes_text or not minutes_text.strip():
            return HandlerResult(
                success=False,
                message="議事録テキストが空です。",
                data={"meeting_id": meeting_id},
            )

        # サマリーテキスト（明示指定がなければminutes_textの先頭を使用）
        memory_summary = summary_text or minutes_text[:MAX_SUMMARY_LENGTH]

        # PR #471教訓: pool.connect()を複数スレッドから同時に呼ぶとdb-f1-microでハング。
        # Google Docs出力（DB書き込み含む）→ Brain記憶保存を順次実行する。
        try:
            docs_result = await self.publish_to_google_docs(
                meeting_id=meeting_id,
                minutes_text=minutes_text,
                title=title,
                expected_version=expected_version,
            )
        except Exception as e:
            logger.error("Google Docs publish raised: %s: %r", type(e).__name__, e)
            docs_result = {}

        try:
            memory_stored = await self.store_meeting_memory(
                meeting_id=meeting_id,
                summary_text=memory_summary,
                title=title,
                key_topics=key_topics,
                mentioned_persons=mentioned_persons,
                room_id=room_id,
                meeting_date=meeting_date,
            )
        except Exception as e:
            logger.error("Memory storage raised: %s: %r", type(e).__name__, e)
            memory_stored = False

        result_data = {
            "meeting_id": meeting_id,
            "document_url": docs_result.get("document_url", ""),
            "document_id": docs_result.get("document_id", ""),
            "docs_published": bool(docs_result.get("document_id")),
            "memory_stored": memory_stored,
        }

        # 部分成功の場合でもsuccess=Trueを返す
        if docs_result.get("document_id"):
            message = (
                f"議事録をGoogle Docsに保存しました。\n"
                f"URL: {docs_result['document_url']}"
            )
        else:
            message = "Google Docsへの保存に失敗しましたが、議事録テキストは利用可能です。"

        if memory_stored:
            message += "\n会議内容をBrainの記憶に保存しました。"

        return HandlerResult(
            success=bool(docs_result.get("document_id")) or memory_stored,
            message=message,
            data=result_data,
        )


def create_meeting_docs_publisher(
    pool,
    organization_id: str,
    google_docs_client=None,
) -> Optional[MeetingDocsPublisher]:
    """
    MeetingDocsPublisherのファクトリ関数。

    ENABLE_MEETING_DOCS=true の場合のみインスタンスを返す。
    無効時はNoneを返す。

    Args:
        pool: SQLAlchemy接続プール
        organization_id: 組織ID
        google_docs_client: GoogleDocsClientインスタンス（テスト用DI）

    Returns:
        MeetingDocsPublisher or None（無効時）
    """
    if not ENABLE_MEETING_DOCS:
        logger.debug("ENABLE_MEETING_DOCS is disabled, skipping publisher creation")
        return None

    return MeetingDocsPublisher(
        pool=pool,
        organization_id=organization_id,
        google_docs_client=google_docs_client,
    )
