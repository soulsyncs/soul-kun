"""
lib/business_day.py のユニットテスト
"""

import pytest
from datetime import date
from lib.business_day import (
    is_weekend,
    is_holiday,
    get_holiday_name,
    is_business_day,
    get_non_business_day_reason,
)


class TestIsWeekend:
    """is_weekend()のテスト"""

    def test_saturday_is_weekend(self):
        """土曜日は週末"""
        saturday = date(2026, 1, 24)  # 土曜日
        assert is_weekend(saturday) is True

    def test_sunday_is_weekend(self):
        """日曜日は週末"""
        sunday = date(2026, 1, 25)  # 日曜日
        assert is_weekend(sunday) is True

    def test_monday_is_not_weekend(self):
        """月曜日は週末ではない"""
        monday = date(2026, 1, 26)  # 月曜日
        assert is_weekend(monday) is False

    def test_friday_is_not_weekend(self):
        """金曜日は週末ではない"""
        friday = date(2026, 1, 30)  # 金曜日
        assert is_weekend(friday) is False


class TestIsHoliday:
    """is_holiday()のテスト"""

    def test_new_years_day_is_holiday(self):
        """元日は祝日"""
        new_years = date(2026, 1, 1)
        assert is_holiday(new_years) is True

    def test_coming_of_age_day_2026(self):
        """2026年の成人の日（1月12日）は祝日"""
        coming_of_age = date(2026, 1, 12)
        assert is_holiday(coming_of_age) is True

    def test_regular_weekday_is_not_holiday(self):
        """通常の平日は祝日ではない"""
        regular_day = date(2026, 1, 20)  # 火曜日
        assert is_holiday(regular_day) is False

    def test_mountain_day(self):
        """山の日（8月11日）は祝日"""
        mountain_day = date(2026, 8, 11)
        assert is_holiday(mountain_day) is True


class TestGetHolidayName:
    """get_holiday_name()のテスト"""

    def test_new_years_day_name(self):
        """元日の名前を取得"""
        new_years = date(2026, 1, 1)
        assert get_holiday_name(new_years) == "元日"

    def test_coming_of_age_day_name(self):
        """成人の日の名前を取得"""
        coming_of_age = date(2026, 1, 12)
        assert get_holiday_name(coming_of_age) == "成人の日"

    def test_non_holiday_returns_none(self):
        """祝日でない日はNoneを返す"""
        regular_day = date(2026, 1, 20)
        assert get_holiday_name(regular_day) is None


class TestIsBusinessDay:
    """is_business_day()のテスト"""

    def test_regular_weekday_is_business_day(self):
        """通常の平日は営業日"""
        monday = date(2026, 1, 26)  # 月曜日、祝日でない
        assert is_business_day(monday) is True

    def test_saturday_is_not_business_day(self):
        """土曜日は営業日ではない"""
        saturday = date(2026, 1, 24)
        assert is_business_day(saturday) is False

    def test_sunday_is_not_business_day(self):
        """日曜日は営業日ではない"""
        sunday = date(2026, 1, 25)
        assert is_business_day(sunday) is False

    def test_holiday_is_not_business_day(self):
        """祝日は営業日ではない"""
        new_years = date(2026, 1, 1)  # 元日（木曜日）
        assert is_business_day(new_years) is False

    def test_holiday_on_weekday_is_not_business_day(self):
        """平日の祝日は営業日ではない"""
        coming_of_age = date(2026, 1, 12)  # 成人の日（月曜日）
        assert is_business_day(coming_of_age) is False


class TestGetNonBusinessDayReason:
    """get_non_business_day_reason()のテスト"""

    def test_saturday_reason(self):
        """土曜日の理由を取得"""
        saturday = date(2026, 1, 24)
        assert get_non_business_day_reason(saturday) == "土曜日"

    def test_sunday_reason(self):
        """日曜日の理由を取得"""
        sunday = date(2026, 1, 25)
        assert get_non_business_day_reason(sunday) == "日曜日"

    def test_holiday_reason(self):
        """祝日の理由を取得"""
        new_years = date(2026, 1, 1)
        assert get_non_business_day_reason(new_years) == "元日"

    def test_business_day_returns_none(self):
        """営業日はNoneを返す"""
        monday = date(2026, 1, 26)  # 通常の月曜日
        assert get_non_business_day_reason(monday) is None
