# lib/meetings/google_calendar_client.py
"""
Google Calendar連携クライアント（Vision 12.2.2準拠）

Zoom録画とGoogleカレンダー予定を時間帯で照合し、
会議タイトル・説明欄・参加者情報を取得する。

用途:
  - Zoom Webhook受信時にカレンダー情報を照合
  - カレンダー説明欄の CW:ルームID タグ抽出（room_routerと連携）
  - 参加者リストの取得（Phase 5 タスク自動割り当てに必要）

CLAUDE.md準拠:
  - §3-2 #8: PIIをログに含めない（参加者メールはマスク）
  - §3-2 #11: リソースリーク防止（with文不要、googleapiclient管理）
  - §3-2 #16: ハードコード検出（Calendar IDは環境変数 or 引数）

Author: Claude Opus 4.6
Created: 2026-02-13
"""

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import List, Optional

logger = logging.getLogger(__name__)

# CW:ルームID抽出パターン（5〜12桁の数字）
_CW_TAG_PATTERN = re.compile(r"CW:(\d{5,12})")

# デフォルトの検索ウィンドウ（分）
DEFAULT_TIME_WINDOW_MINUTES = 30

# 環境変数
CALENDAR_ID_ENV = "GOOGLE_CALENDAR_ID"
DEFAULT_CALENDAR_ID = "primary"


@dataclass
class CalendarEvent:
    """Googleカレンダーイベント情報"""

    event_id: str
    title: str
    description: Optional[str]
    start_time: Optional[datetime]
    end_time: Optional[datetime]
    attendees: List[str] = field(default_factory=list)
    organizer_email: Optional[str] = None
    html_link: Optional[str] = None

    @property
    def has_cw_tag(self) -> bool:
        """説明欄にCW:ルームIDタグ（CW:数字5〜12桁）が含まれるか"""
        if not self.description:
            return False
        return bool(_CW_TAG_PATTERN.search(self.description))

    @property
    def cw_room_id(self) -> Optional[str]:
        """説明欄からCW:ルームIDを抽出（なければNone）"""
        if not self.description:
            return None
        match = _CW_TAG_PATTERN.search(self.description)
        return match.group(1) if match else None


class GoogleCalendarClient:
    """
    Google Calendar API クライアント。

    Zoom録画情報との時間帯照合を行い、
    会議のカレンダー情報（説明欄、参加者等）を取得する。

    認証: サービスアカウント or Application Default Credentials
    （GoogleDriveClientと同パターン）
    """

    def __init__(
        self,
        service_account_file: Optional[str] = None,
        service_account_info: Optional[dict] = None,
        calendar_id: Optional[str] = None,
    ):
        """
        Args:
            service_account_file: サービスアカウントJSONファイルのパス
            service_account_info: サービスアカウント情報の辞書
            calendar_id: GoogleカレンダーID（デフォルト: 環境変数 or "primary"）
        """
        self.calendar_id = (
            calendar_id
            or os.environ.get(CALENDAR_ID_ENV)
            or DEFAULT_CALENDAR_ID
        )
        self._service = None
        self._sa_file = service_account_file
        self._sa_info = service_account_info

    def _get_service(self):
        """Lazy-init Calendar API service."""
        if self._service is not None:
            return self._service

        from google.oauth2 import service_account as sa_module
        from googleapiclient.discovery import build

        scopes = ["https://www.googleapis.com/auth/calendar.readonly"]

        if self._sa_info:
            credentials = sa_module.Credentials.from_service_account_info(
                self._sa_info, scopes=scopes
            )
        elif self._sa_file:
            credentials = sa_module.Credentials.from_service_account_file(
                self._sa_file, scopes=scopes
            )
        else:
            sa_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
            if sa_path:
                credentials = sa_module.Credentials.from_service_account_file(
                    sa_path, scopes=scopes
                )
            else:
                from google.auth import default

                credentials, _ = default(scopes=scopes)

        self._service = build("calendar", "v3", credentials=credentials)
        return self._service

    def find_matching_event(
        self,
        zoom_start_time: datetime,
        zoom_topic: Optional[str] = None,
        time_window_minutes: int = DEFAULT_TIME_WINDOW_MINUTES,
    ) -> Optional[CalendarEvent]:
        """
        Zoom録画の開始時刻に一致するカレンダーイベントを検索する。

        Args:
            zoom_start_time: Zoom録画の開始時刻（UTC）
            zoom_topic: Zoom会議のトピック（タイトル照合に使用）
            time_window_minutes: 検索ウィンドウ（±分）

        Returns:
            最も一致度の高いCalendarEvent、なければNone
        """
        try:
            service = self._get_service()
        except Exception as e:
            logger.warning(
                "Google Calendar API initialization failed: %s",
                type(e).__name__,
            )
            return None

        # 検索ウィンドウ
        window = timedelta(minutes=time_window_minutes)
        time_min = (zoom_start_time - window).isoformat()
        time_max = (zoom_start_time + window).isoformat()

        try:
            result = (
                service.events()
                .list(
                    calendarId=self.calendar_id,
                    timeMin=time_min,
                    timeMax=time_max,
                    singleEvents=True,
                    orderBy="startTime",
                    maxResults=10,
                )
                .execute()
            )
        except Exception as e:
            logger.warning(
                "Google Calendar API events.list failed: %s",
                type(e).__name__,
            )
            return None

        events = result.get("items", [])
        if not events:
            logger.info("No calendar events found in time window")
            return None

        # 候補イベントをCalendarEventに変換
        candidates = []
        for ev in events:
            cal_event = _parse_calendar_event(ev)
            if cal_event:
                candidates.append(cal_event)

        if not candidates:
            return None

        # ベストマッチを選択
        best = _select_best_match(candidates, zoom_start_time, zoom_topic)

        if best:
            logger.info(
                "Calendar event matched: event_id=%s, has_cw_tag=%s",
                best.event_id,
                best.has_cw_tag,
            )

        return best

    def get_event_by_id(self, event_id: str) -> Optional[CalendarEvent]:
        """
        イベントIDで直接取得する。

        Args:
            event_id: GoogleカレンダーイベントID

        Returns:
            CalendarEvent or None
        """
        try:
            service = self._get_service()
            ev = (
                service.events()
                .get(calendarId=self.calendar_id, eventId=event_id)
                .execute()
            )
            return _parse_calendar_event(ev)
        except Exception as e:
            logger.warning(
                "Google Calendar get_event_by_id failed: %s",
                type(e).__name__,
            )
            return None


def _parse_calendar_event(ev: dict) -> Optional[CalendarEvent]:
    """Google Calendar APIレスポンスをCalendarEventに変換"""
    event_id = ev.get("id")
    if not event_id:
        return None

    title = ev.get("summary", "")
    description = ev.get("description")

    # 開始・終了時刻
    start_raw = ev.get("start", {})
    end_raw = ev.get("end", {})
    start_time = _parse_gcal_datetime(
        start_raw.get("dateTime") or start_raw.get("date")
    )
    end_time = _parse_gcal_datetime(
        end_raw.get("dateTime") or end_raw.get("date")
    )

    # 参加者リスト（メールアドレス）
    attendees = []
    for att in ev.get("attendees", []):
        email = att.get("email", "")
        if email and not email.endswith("resource.calendar.google.com"):
            attendees.append(email)

    organizer = ev.get("organizer", {}).get("email")

    return CalendarEvent(
        event_id=event_id,
        title=title,
        description=description,
        start_time=start_time,
        end_time=end_time,
        attendees=attendees,
        organizer_email=organizer,
        html_link=ev.get("htmlLink"),
    )


def _parse_gcal_datetime(dt_str: Optional[str]) -> Optional[datetime]:
    """Google Calendar datetime文字列をパース"""
    if not dt_str:
        return None
    try:
        return datetime.fromisoformat(dt_str)
    except (ValueError, AttributeError):
        return None


def _select_best_match(
    candidates: List[CalendarEvent],
    zoom_start: datetime,
    zoom_topic: Optional[str],
) -> Optional[CalendarEvent]:
    """
    候補イベントからベストマッチを選択する。

    スコアリング:
      - CW:タグあり → +10点（最優先）
      - タイトル部分一致 → +5点
      - 時刻の近さ → 0〜3点（30分以内で線形）
    """
    if not candidates:
        return None

    best_event = None
    best_score = -1.0

    zoom_topic_lower = (zoom_topic or "").lower()

    for event in candidates:
        score = 0.0

        # CW:タグがあれば最優先
        if event.has_cw_tag:
            score += 10.0

        # タイトル類似度
        if zoom_topic_lower and event.title:
            event_title_lower = event.title.lower()
            if zoom_topic_lower in event_title_lower or event_title_lower in zoom_topic_lower:
                score += 5.0

        # 時刻の近さ（±30分で0〜3点）
        if event.start_time and zoom_start:
            # timezone-aware比較
            event_start = event.start_time
            zoom_start_aware = zoom_start
            if event_start.tzinfo is None:
                event_start = event_start.replace(tzinfo=timezone.utc)
            if zoom_start_aware.tzinfo is None:
                zoom_start_aware = zoom_start_aware.replace(tzinfo=timezone.utc)

            diff_minutes = abs(
                (event_start - zoom_start_aware).total_seconds()
            ) / 60.0
            if diff_minutes <= DEFAULT_TIME_WINDOW_MINUTES:
                time_score = 3.0 * (
                    1.0 - diff_minutes / DEFAULT_TIME_WINDOW_MINUTES
                )
                score += time_score

        if score > best_score:
            best_score = score
            best_event = event

    return best_event


def create_calendar_client_from_env() -> Optional[GoogleCalendarClient]:
    """
    環境変数からGoogleCalendarClientを生成する。

    Returns:
        GoogleCalendarClient or None（Calendar連携が無効な場合）
    """
    enabled = os.environ.get("ENABLE_GOOGLE_CALENDAR", "").lower()
    if enabled not in ("true", "1"):
        logger.debug("Google Calendar integration disabled")
        return None

    return GoogleCalendarClient()
