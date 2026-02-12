# lib/meetings/room_router.py
"""
ChatWorkルーム自動振り分けモジュール（Vision 12.2.3準拠）

会議タイトルやカレンダー情報から、議事録の投稿先ChatWorkルームを自動判定する。

振り分け優先順位:
  1. キーワード→ルームマッピングテーブル（meeting_room_keywords）
  2. Googleカレンダー説明欄の CW:ルームID タグ
  3. 管理部ルームへのフォールバック（人間に確認を促す）

CLAUDE.md準拠:
  - 鉄則#1: organization_idフィルタ必須
  - 鉄則#9: パラメータ化SQL
  - §3-2 #8: PIIをログに含めない

Author: Claude Opus 4.6
Created: 2026-02-13
"""

import logging
import re
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import text

from lib.admin_config import DEFAULT_ADMIN_ROOM_ID

logger = logging.getLogger(__name__)

# 管理部ルーム（フォールバック先）— admin_configから取得
ADMIN_ROOM_ID = DEFAULT_ADMIN_ROOM_ID

# CW:ID抽出パターン（カレンダー説明欄）
CW_ROOM_ID_PATTERN = re.compile(r"CW:(\d+)")


@dataclass
class RoomRoutingResult:
    """ルーム振り分け結果"""

    room_id: str
    routing_method: str  # "keyword_match" | "calendar_cw_id" | "admin_fallback"
    confidence: float  # 0.0〜1.0
    matched_keyword: Optional[str] = None


class MeetingRoomRouter:
    """
    議事録投稿先ChatWorkルームを自動判定する。

    Vision 12.2.3の3段階優先順位:
    1. キーワードマッピングテーブル検索
    2. カレンダー説明欄のCW:IDタグ
    3. 管理部フォールバック
    """

    def __init__(self, pool, organization_id: str):
        if not organization_id or not organization_id.strip():
            raise ValueError("organization_id is required")
        self.pool = pool
        self.organization_id = organization_id

    def resolve_room(
        self,
        meeting_title: str,
        calendar_description: Optional[str] = None,
        admin_room_id: str = ADMIN_ROOM_ID,
    ) -> RoomRoutingResult:
        """
        議事録の投稿先ルームを判定する。

        Args:
            meeting_title: 会議タイトル
            calendar_description: Googleカレンダーの説明欄（あれば）
            admin_room_id: フォールバック先の管理部ルームID

        Returns:
            RoomRoutingResult with resolved room_id and method
        """
        # 優先度1: キーワードマッピングテーブル
        keyword_result = self._match_keyword(meeting_title)
        if keyword_result:
            return keyword_result

        # 優先度2: カレンダー説明欄の CW:ID タグ
        if calendar_description:
            cw_result = self._extract_cw_id(calendar_description)
            if cw_result:
                return cw_result

        # 優先度3: 管理部フォールバック
        logger.info(
            "Room routing: no match found for meeting, falling back to admin room"
        )
        return RoomRoutingResult(
            room_id=admin_room_id,
            routing_method="admin_fallback",
            confidence=0.0,
        )

    def _match_keyword(self, meeting_title: str) -> Optional[RoomRoutingResult]:
        """キーワードマッピングテーブルから一致を検索"""
        if not meeting_title:
            return None

        try:
            with self.pool.connect() as conn:
                conn.rollback()
                conn.execute(
                    text("SELECT set_config('statement_timeout', '5000', true)")
                )
                result = conn.execute(
                    text("""
                        SELECT keyword, chatwork_room_id, room_name
                        FROM meeting_room_keywords
                        WHERE organization_id = :org_id
                        ORDER BY priority DESC, LENGTH(keyword) DESC
                    """),
                    {"org_id": self.organization_id},
                )
                rows = result.mappings().fetchall()

            title_lower = meeting_title.lower()
            for row in rows:
                keyword = row["keyword"]
                if keyword.lower() in title_lower:
                    logger.info(
                        "Room routing: keyword '%s' matched -> room %s",
                        keyword,
                        row["chatwork_room_id"],
                    )
                    return RoomRoutingResult(
                        room_id=row["chatwork_room_id"],
                        routing_method="keyword_match",
                        confidence=0.9,
                        matched_keyword=keyword,
                    )
        except Exception as e:
            logger.warning(
                "Room routing keyword lookup failed: %s", type(e).__name__
            )

        return None

    @staticmethod
    def _extract_cw_id(description: str) -> Optional[RoomRoutingResult]:
        """カレンダー説明欄からCW:ルームIDを抽出"""
        match = CW_ROOM_ID_PATTERN.search(description)
        if match:
            room_id = match.group(1)
            logger.info("Room routing: CW:%s found in calendar description", room_id)
            return RoomRoutingResult(
                room_id=room_id,
                routing_method="calendar_cw_id",
                confidence=0.95,
            )
        return None

    def build_admin_fallback_message(
        self, meeting_title: str, meeting_id: Optional[str] = None
    ) -> str:
        """管理部フォールバック時の確認メッセージを生成"""
        msg = (
            f"[info][title]議事録の送信先が不明ウル[/title]\n"
            f"「{meeting_title}」の議事録を作成したウル。\n"
            f"どのルームに送ればいいウル？\n"
            f"ルームIDを教えてほしいウル🐺\n"
        )
        if meeting_id:
            msg += f"\n（会議ID: {meeting_id}）\n"
        msg += "[/info]"
        return msg
