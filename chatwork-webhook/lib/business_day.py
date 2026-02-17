"""
営業日判定ユーティリティ

日本の祝日・土日を判定し、営業日かどうかを返す。
タスクリマインドや遅延タスク報告の送信判定に使用。

使用方法:
    from lib.business_day import is_business_day

    if not is_business_day():
        print("本日は営業日ではありません。リマインドをスキップします。")
        return
"""

import logging
from datetime import date, datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# JST タイムゾーン
JST = timezone(timedelta(hours=9))

# jpholidayライブラリを使用（日本の祝日判定）
try:
    import jpholiday
    _JPHOLIDAY_AVAILABLE = True
except ImportError:
    _JPHOLIDAY_AVAILABLE = False
    logger.warning("jpholidayライブラリが見つかりません。祝日判定はスキップされます。")


def is_weekend(target_date: Optional[date] = None) -> bool:
    """
    土日かどうかを判定

    Args:
        target_date: 判定対象の日付（省略時は今日）

    Returns:
        土曜日(5)または日曜日(6)ならTrue
    """
    if target_date is None:
        target_date = datetime.now(JST).date()

    # weekday(): 月曜=0, 火曜=1, ..., 土曜=5, 日曜=6
    return target_date.weekday() >= 5


def is_holiday(target_date: Optional[date] = None) -> bool:
    """
    日本の祝日かどうかを判定

    Args:
        target_date: 判定対象の日付（省略時は今日）

    Returns:
        祝日ならTrue
    """
    if target_date is None:
        target_date = datetime.now(JST).date()

    if not _JPHOLIDAY_AVAILABLE:
        return False

    return jpholiday.is_holiday(target_date)


def get_holiday_name(target_date: Optional[date] = None) -> Optional[str]:
    """
    祝日名を取得

    Args:
        target_date: 判定対象の日付（省略時は今日）

    Returns:
        祝日名（祝日でなければNone）
    """
    if target_date is None:
        target_date = datetime.now(JST).date()

    if not _JPHOLIDAY_AVAILABLE:
        return None

    return jpholiday.is_holiday_name(target_date)


def is_business_day(target_date: Optional[date] = None) -> bool:
    """
    営業日かどうかを判定

    土日または祝日ならFalse、それ以外（平日かつ祝日でない）ならTrue

    Args:
        target_date: 判定対象の日付（省略時は今日）

    Returns:
        営業日ならTrue、土日祝日ならFalse
    """
    if target_date is None:
        target_date = datetime.now(JST).date()

    # 土日チェック
    if is_weekend(target_date):
        return False

    # 祝日チェック
    if is_holiday(target_date):
        return False

    return True


def get_non_business_day_reason(target_date: Optional[date] = None) -> Optional[str]:
    """
    営業日でない理由を取得

    Args:
        target_date: 判定対象の日付（省略時は今日）

    Returns:
        営業日でない理由（営業日ならNone）
        例: "土曜日", "日曜日", "元日", "成人の日"
    """
    if target_date is None:
        target_date = datetime.now(JST).date()

    weekday = target_date.weekday()

    # 土日チェック
    if weekday == 5:
        return "土曜日"
    if weekday == 6:
        return "日曜日"

    # 祝日チェック
    holiday_name = get_holiday_name(target_date)
    if holiday_name:
        return holiday_name

    return None
