# lib/brain/calendar_tool.py
"""
Googleカレンダー読み取りツール — Step A-3: 秘書に手帳を見せる

ソウルくんがGoogleカレンダーの予定を参照できるようにする機能。
既存の GoogleCalendarClient（lib/meetings/google_calendar_client.py）を活用し、
予定一覧の取得・フォーマットを行う。

【設計原則】
- 読み取り専用（calendar.readonly スコープ）→ リスクレベルは"low"
- OAuth接続は管理画面から事前に実施済み（google_oauth_tokens テーブル）
- PIIマスキング: 参加者メールアドレスはログに出さない（CLAUDE.md §3-2 #8）
- sync I/Oは asyncio.to_thread() で包む（CLAUDE.md §3-2 #6）

Author: Claude Opus 4.6
Created: 2026-02-17
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# デフォルト設定
DEFAULT_DAYS_AHEAD = 1  # 今日〜明日
MAX_EVENTS = 20


def list_calendar_events(
    pool: Any,
    organization_id: str,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    max_results: int = MAX_EVENTS,
) -> Dict[str, Any]:
    """
    Googleカレンダーの予定一覧を取得する。

    Args:
        pool: SQLAlchemy connection pool
        organization_id: 組織ID
        date_from: 開始日（YYYY-MM-DD形式、省略時は今日）
        date_to: 終了日（YYYY-MM-DD形式、省略時はdate_from+1日）
        max_results: 最大取得件数

    Returns:
        dict: {
            "success": bool,
            "events": [{
                "title": str,
                "start_time": str,
                "end_time": str,
                "location": str | None,
                "description_summary": str | None,
                "attendee_count": int,
                "html_link": str | None,
            }],
            "date_range": str,
            "event_count": int,
        }
    """
    # 日付範囲を決定
    try:
        jst = timezone(timedelta(hours=9))
        now_jst = datetime.now(jst)

        if date_from:
            start_dt = datetime.strptime(date_from, "%Y-%m-%d").replace(tzinfo=jst)
        else:
            start_dt = now_jst.replace(hour=0, minute=0, second=0, microsecond=0)

        if date_to:
            end_dt = datetime.strptime(date_to, "%Y-%m-%d").replace(tzinfo=jst)
            end_dt = end_dt.replace(hour=23, minute=59, second=59)
        else:
            end_dt = start_dt + timedelta(days=DEFAULT_DAYS_AHEAD)
    except ValueError:
        return {
            "success": False,
            "error": "日付の形式が正しくありません（YYYY-MM-DD）",
            "events": [],
            "event_count": 0,
        }

    # max_resultsを制限
    max_results = min(max(1, max_results), MAX_EVENTS)

    # カレンダークライアントを取得
    try:
        from lib.meetings.google_calendar_client import create_calendar_client_from_db
        client = create_calendar_client_from_db(pool, organization_id)
    except Exception as e:
        logger.error("Calendar client creation failed: %s", e)
        client = None

    if client is None:
        return {
            "success": False,
            "error": "Googleカレンダーが接続されていません。管理画面から接続してください。",
            "events": [],
            "event_count": 0,
        }

    # Google Calendar APIを呼び出し
    try:
        service = client._get_service()
        result = (
            service.events()
            .list(
                calendarId=client.calendar_id,
                timeMin=start_dt.isoformat(),
                timeMax=end_dt.isoformat(),
                singleEvents=True,
                orderBy="startTime",
                maxResults=max_results,
            )
            .execute()
        )
    except Exception as e:
        logger.error("Calendar API call failed: %s", type(e).__name__)
        return {
            "success": False,
            "error": f"Googleカレンダーの取得に失敗しました: {type(e).__name__}",
            "events": [],
            "event_count": 0,
        }

    # 結果をフォーマット
    events = []
    for ev in result.get("items", []):
        start_raw = ev.get("start", {})
        end_raw = ev.get("end", {})
        start_str = start_raw.get("dateTime") or start_raw.get("date", "")
        end_str = end_raw.get("dateTime") or end_raw.get("date", "")

        # 参加者数（メールアドレスはPII、件数のみ返す）
        attendees = ev.get("attendees", [])
        attendee_count = len([
            a for a in attendees
            if not a.get("email", "").endswith("resource.calendar.google.com")
        ])

        # 説明文は先頭100文字のみ（PII漏洩防止）
        desc = ev.get("description", "")
        desc_summary = desc[:100] + "..." if len(desc) > 100 else desc if desc else None

        events.append({
            "title": ev.get("summary", "（タイトルなし）"),
            "start_time": start_str,
            "end_time": end_str,
            "location": ev.get("location"),
            "description_summary": desc_summary,
            "attendee_count": attendee_count,
            "html_link": ev.get("htmlLink"),
        })

    # 日付範囲の表示テキスト
    date_range = start_dt.strftime("%Y年%m月%d日")
    if date_to and date_to != date_from:
        date_range += f" 〜 {end_dt.strftime('%Y年%m月%d日')}"

    return {
        "success": True,
        "events": events,
        "date_range": date_range,
        "event_count": len(events),
    }


def format_calendar_events(result: Dict[str, Any]) -> str:
    """
    カレンダー予定一覧をBrainが合成回答に使える形式にフォーマットする。

    Args:
        result: list_calendar_events() の結果

    Returns:
        str: フォーマットされた予定テキスト
    """
    if not result.get("success"):
        return f"カレンダーエラー: {result.get('error', '不明なエラー')}"

    events = result.get("events", [])
    date_range = result.get("date_range", "")

    if not events:
        return f"【{date_range}の予定】\n予定はありません。"

    parts = [f"【{date_range}の予定: {len(events)}件】"]

    for i, ev in enumerate(events, 1):
        title = ev.get("title", "（タイトルなし）")
        start = _format_time(ev.get("start_time", ""))
        end = _format_time(ev.get("end_time", ""))

        time_str = f"{start}" if start else "時間未定"
        if end:
            time_str += f" 〜 {end}"

        line = f"{i}. {time_str}  {title}"

        location = ev.get("location")
        if location:
            line += f"\n   場所: {location}"

        attendee_count = ev.get("attendee_count", 0)
        if attendee_count > 0:
            line += f"\n   参加者: {attendee_count}名"

        parts.append(line)

    return "\n".join(parts)


def _format_time(dt_str: str) -> str:
    """ISO形式の日時文字列を「HH:MM」に変換"""
    if not dt_str:
        return ""
    try:
        dt = datetime.fromisoformat(dt_str)
        return dt.strftime("%H:%M")
    except (ValueError, AttributeError):
        return dt_str[:10] if len(dt_str) >= 10 else dt_str
