"""
日付処理ユーティリティ

main.pyから分割された日付関連の関数を提供する。
これらは他の機能に依存しない純粋な関数。

分割元: chatwork-webhook/main.py
分割日: 2026-01-25
バージョン: v10.24.0
"""

import re
from datetime import datetime, timedelta, timezone

# JST タイムゾーン
JST = timezone(timedelta(hours=9))

# 期限ガードレール設定
# タスク追加時に期限が近すぎる場合にアラートを表示
# 当日(0)と明日(1)の場合にアラートを送信
DEADLINE_ALERT_DAYS = {
    0: "今日",    # 当日
    1: "明日",    # 翌日
}


def parse_date_from_text(text):
    """
    自然言語の日付表現をYYYY-MM-DD形式に変換
    例: "明日", "明後日", "12/27", "来週金曜日"

    Args:
        text: 日付を含むテキスト

    Returns:
        YYYY-MM-DD形式の文字列、またはNone
    """
    now = datetime.now(JST)
    today = now.date()

    text = text.strip().lower()

    # 「明日」
    if "明日" in text or "あした" in text:
        return (today + timedelta(days=1)).strftime("%Y-%m-%d")

    # 「明後日」
    if "明後日" in text or "あさって" in text:
        return (today + timedelta(days=2)).strftime("%Y-%m-%d")

    # 「今日」
    if "今日" in text or "きょう" in text:
        return today.strftime("%Y-%m-%d")

    # 「来週」
    if "来週" in text:
        # 来週の月曜日を基準に
        days_until_monday = (7 - today.weekday()) % 7
        if days_until_monday == 0:
            days_until_monday = 7
        next_monday = today + timedelta(days=days_until_monday)

        # 曜日指定があるか確認
        weekdays = {
            "月": 0, "火": 1, "水": 2, "木": 3, "金": 4, "土": 5, "日": 6,
            "月曜": 0, "火曜": 1, "水曜": 2, "木曜": 3, "金曜": 4, "土曜": 5, "日曜": 6,
        }
        for day_name, day_num in weekdays.items():
            if day_name in text:
                target = next_monday + timedelta(days=day_num)
                return target.strftime("%Y-%m-%d")

        # 曜日指定がなければ来週の月曜日
        return next_monday.strftime("%Y-%m-%d")

    # 「○日後」
    match = re.search(r'(\d+)日後', text)
    if match:
        days = int(match.group(1))
        return (today + timedelta(days=days)).strftime("%Y-%m-%d")

    # 「MM/DD」形式
    match = re.search(r'(\d{1,2})[/\-](\d{1,2})', text)
    if match:
        month = int(match.group(1))
        day = int(match.group(2))
        year = today.year
        # 過去の日付なら来年に
        target = datetime(year, month, day).date()
        if target < today:
            target = datetime(year + 1, month, day).date()
        return target.strftime("%Y-%m-%d")

    # 「MM月DD日」形式
    match = re.search(r'(\d{1,2})月(\d{1,2})日', text)
    if match:
        month = int(match.group(1))
        day = int(match.group(2))
        year = today.year
        target = datetime(year, month, day).date()
        if target < today:
            target = datetime(year + 1, month, day).date()
        return target.strftime("%Y-%m-%d")

    return None


def check_deadline_proximity(limit_date_str: str) -> tuple:
    """
    期限が近すぎるかチェックする

    Args:
        limit_date_str: タスクの期限日（YYYY-MM-DD形式）

    Returns:
        (needs_alert: bool, days_until: int, limit_date: date or None)
        - needs_alert: アラートが必要か
        - days_until: 期限までの日数（0=今日, 1=明日, 負=過去）
        - limit_date: 期限日（date型）
    """
    if not limit_date_str:
        return False, -1, None

    try:
        # JSTで現在日付を取得
        now = datetime.now(JST)
        today = now.date()

        # 期限日をパース
        limit_date = datetime.strptime(limit_date_str, "%Y-%m-%d").date()

        # 期限までの日数を計算
        days_until = (limit_date - today).days

        # 過去の日付は別のバリデーションで処理（ここではアラート対象外）
        if days_until < 0:
            return False, days_until, limit_date

        # 当日(0) または 明日(1) ならアラート
        if days_until in DEADLINE_ALERT_DAYS:
            return True, days_until, limit_date

        return False, days_until, limit_date
    except Exception as e:
        print(f"⚠️ check_deadline_proximity エラー: {e}")
        return False, -1, None


def get_overdue_days(limit_time):
    """
    期限超過日数を計算

    Args:
        limit_time: 期限時刻（Unix timestamp, int/float または datetime）

    Returns:
        期限超過日数（0以上の整数）
    """
    if not limit_time:
        return 0

    now = datetime.now(JST)
    today = now.date()

    # v6.8.6: int/float両対応
    try:
        if isinstance(limit_time, (int, float)):
            limit_date = datetime.fromtimestamp(int(limit_time), tz=JST).date()
        elif hasattr(limit_time, 'date'):
            limit_date = limit_time.date()
        else:
            print(f"⚠️ get_overdue_days: 不明なlimit_time型: {type(limit_time)}")
            return 0
    except Exception as e:
        print(f"⚠️ get_overdue_days: 変換エラー: {limit_time}, error={e}")
        return 0

    delta = (today - limit_date).days
    return max(0, delta)
