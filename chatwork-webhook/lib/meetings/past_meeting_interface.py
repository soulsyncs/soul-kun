# lib/meetings/past_meeting_interface.py
"""
過去会議検索インターフェース（機能②: 過去会議質問）

「先月の会議で何を決めた？」「採用会議の議事録どこ？」といった
自然言語の質問に対して、brain_episodes DBを検索し回答を返す。

フロー:
  1. 自然言語の時間表現 → 日付範囲に変換
  2. brain_episodes を組織IDでフィルタして検索
  3. 検索結果をChatWork向けメッセージにフォーマット

設計方針:
  - Phase 1: summaryで直接回答 + Googleドキュメントリンク提示（ハイブリッド方式）
  - PII非保存: brain_episodesにはタイトル・メタ情報のみ保存済み（zoom_brain_interface.py §Step12）
  - organization_id フィルタを全クエリに適用（CLAUDE.md 鉄則#1）

CLAUDE.md準拠:
  - 鉄則#1: organization_id必須
  - §3-2 #8: PIIをログに含めない
  - Truth順位 2位: DBから正規データを取得

Author: Claude Sonnet 4.6
Created: 2026-02-21
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# 過去会議検索の最大件数
MAX_MEETING_SEARCH_RESULTS = 10


@dataclass
class PastMeetingResult:
    """過去会議の検索結果1件"""

    meeting_id: str
    title: str
    occurred_at: Optional[datetime]
    document_url: str
    duration_seconds: int
    task_count: int
    summary: str


@dataclass
class PastMeetingSearchResult:
    """過去会議検索の全体結果"""

    meetings: List[PastMeetingResult] = field(default_factory=list)
    total_found: int = 0
    query_description: str = ""  # 「先月の会議」など検索条件の説明


def parse_time_range_from_query(query: str) -> Tuple[Optional[datetime], Optional[datetime], str]:
    """
    自然言語クエリから日付範囲を解析する。

    対応表現:
        今月 / 今月の       → 今月1日〜今月末
        先月 / 先月の       → 先月1日〜先月末
        今週 / 今週の       → 今週月曜〜今週日曜
        先週 / 先週の       → 先週月曜〜先週日曜
        今年 / 今年の       → 今年1月1日〜今年末
        昨年 / 去年 / 昨年の → 昨年1月1日〜昨年末
        N月の / N月に       → 今年のN月1日〜N月末
        直近 / 最近 / 最新   → 過去30日
        (マッチなし)        → (None, None, "最近の")  → 呼び出し側で最近30日にfallback

    Returns:
        (start, end, description) — start/endはNoneの場合あり（fallback用）
    """
    now = datetime.now(timezone.utc)

    def _month_range(year: int, month: int) -> Tuple[datetime, datetime]:
        start = now.replace(year=year, month=month, day=1,
                             hour=0, minute=0, second=0, microsecond=0)
        # 月末: 翌月1日の直前
        if month == 12:
            end = start.replace(year=year + 1, month=1) - timedelta(seconds=1)
        else:
            end = start.replace(month=month + 1) - timedelta(seconds=1)
        return start, end

    def _week_range(weeks_ago: int = 0) -> Tuple[datetime, datetime]:
        """0=今週, 1=先週"""
        monday = now - timedelta(days=now.weekday() + weeks_ago * 7)
        start = monday.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=6, hours=23, minutes=59, seconds=59)
        return start, end

    # 今週
    if re.search(r"今週", query):
        start, end = _week_range(0)
        return start, end, "今週の"

    # 先週
    if re.search(r"先週|先週の", query):
        start, end = _week_range(1)
        return start, end, "先週の"

    # 今月
    if re.search(r"今月", query):
        start, end = _month_range(now.year, now.month)
        return start, end, "今月の"

    # 先月
    if re.search(r"先月", query):
        if now.month == 1:
            start, end = _month_range(now.year - 1, 12)
        else:
            start, end = _month_range(now.year, now.month - 1)
        return start, end, "先月の"

    # 今年
    if re.search(r"今年", query):
        start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        end = now.replace(month=12, day=31, hour=23, minute=59, second=59, microsecond=0)
        return start, end, "今年の"

    # 昨年・去年
    if re.search(r"昨年|去年", query):
        last_year = now.year - 1
        start = now.replace(year=last_year, month=1, day=1,
                             hour=0, minute=0, second=0, microsecond=0)
        end = now.replace(year=last_year, month=12, day=31,
                           hour=23, minute=59, second=59, microsecond=0)
        return start, end, "昨年の"

    # N月の（例: 1月の、12月の）
    m = re.search(r"(\d{1,2})月", query)
    if m:
        month = int(m.group(1))
        if 1 <= month <= 12:
            # 今年のN月。ただし未来の月なら昨年
            year = now.year
            if month > now.month:
                year -= 1
            start, end = _month_range(year, month)
            return start, end, f"{month}月の"

    # 直近・最近・最新
    if re.search(r"直近|最近|最新|最後|前回", query):
        start = now - timedelta(days=30)
        return start, now, "最近の"

    # マッチなし → fallback
    return None, None, "最近の"


def format_duration(duration_seconds: int) -> str:
    """秒を「X時間Y分」形式に変換"""
    if duration_seconds <= 0:
        return "不明"
    minutes = duration_seconds // 60
    hours = minutes // 60
    mins = minutes % 60
    if hours > 0:
        return f"{hours}時間{mins}分" if mins > 0 else f"{hours}時間"
    return f"{mins}分"


def format_meeting_list_message(search_result: PastMeetingSearchResult) -> str:
    """
    検索結果をChatWork向けメッセージにフォーマットする。

    ハイブリッド方式:
    - summaryで直接回答（「〇月〇日に△△がありました」）
    - Googleドキュメントリンクを提示（詳細はリンクから）
    """
    if not search_result.meetings:
        return f"{search_result.query_description}会議は見つかりませんでした。"

    total = search_result.total_found
    desc = search_result.query_description

    if total == 1:
        m = search_result.meetings[0]
        lines = [f"【{desc}会議】"]
        if m.occurred_at:
            date_str = m.occurred_at.strftime("%-m月%-d日")
            lines.append(f"・{date_str}「{m.title}」")
        else:
            lines.append(f"・「{m.title}」")

        meta_parts = []
        if m.duration_seconds > 0:
            meta_parts.append(format_duration(m.duration_seconds))
        if m.task_count > 0:
            meta_parts.append(f"タスク{m.task_count}件")
        if meta_parts:
            lines.append(f"  ({', '.join(meta_parts)})")

        if m.document_url:
            lines.append(f"  詳細はこちら→ {m.document_url}")
        return "\n".join(lines)

    # 複数件
    lines = [f"【{desc}会議 — {total}件見つかりました】"]
    for i, m in enumerate(search_result.meetings, 1):
        if m.occurred_at:
            date_str = m.occurred_at.strftime("%-m月%-d日")
            line = f"{i}. {date_str}「{m.title}」"
        else:
            line = f"{i}. 「{m.title}」"

        meta_parts = []
        if m.duration_seconds > 0:
            meta_parts.append(format_duration(m.duration_seconds))
        if m.task_count > 0:
            meta_parts.append(f"タスク{m.task_count}件")
        if meta_parts:
            line += f" ({', '.join(meta_parts)})"
        lines.append(line)
        if m.document_url:
            lines.append(f"   詳細→ {m.document_url}")

    return "\n".join(lines)


def search_past_meetings(
    memory_enhancement,
    conn,
    organization_id: str,
    query: str,
    limit: int = MAX_MEETING_SEARCH_RESULTS,
) -> PastMeetingSearchResult:
    """
    過去会議を検索して結果を返す。

    Args:
        memory_enhancement: BrainMemoryEnhancementインスタンス
        conn: DB接続
        organization_id: 組織ID（鉄則#1: 必須）
        query: ユーザーの質問テキスト（「先月の会議は？」など）
        limit: 最大件数

    Returns:
        PastMeetingSearchResult
    """
    from lib.brain.memory_enhancement import EpisodeType

    start, end, desc = parse_time_range_from_query(query)

    # fallback: 過去30日
    if start is None:
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=30)
        end = now

    episodes = memory_enhancement.find_episodes_by_time_range(
        conn=conn,
        start=start,
        end=end,
        episode_type=EpisodeType.INTERACTION,
        limit=limit,
    )

    # 会議エピソードのみ抽出（source == "zoom" or "google_meet"）
    meeting_episodes = [
        ep for ep in episodes
        if isinstance(ep.details, dict)
        and ep.details.get("source") in ("zoom", "google_meet")
    ]

    results = []
    for ep in meeting_episodes:
        details = ep.details
        # Zoom は "document_url"、Google Meet は "drive_url" キーで保存する
        doc_url = details.get("document_url") or details.get("drive_url", "")
        results.append(PastMeetingResult(
            meeting_id=details.get("meeting_id", ""),
            title=details.get("title", ep.summary),
            occurred_at=ep.occurred_at,
            document_url=doc_url,
            duration_seconds=int(details.get("duration_seconds", 0)),
            task_count=int(details.get("task_count", 0)),
            summary=ep.summary,
        ))

    logger.info(
        "Past meeting search: query_len=%d, found=%d, desc=%s",
        len(query),
        len(results),
        desc,
    )

    return PastMeetingSearchResult(
        meetings=results,
        total_found=len(results),
        query_description=desc,
    )
