"""
日付処理ユーティリティのテスト

chatwork-webhook/utils/date_utils.py のテスト
"""

import pytest
from datetime import datetime, timedelta, timezone
import sys
import os

# chatwork-webhookのパスを追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'chatwork-webhook'))

from utils.date_utils import (
    parse_date_from_text,
    check_deadline_proximity,
    get_overdue_days,
    JST,
    DEADLINE_ALERT_DAYS,
)


class TestParseDateFromText:
    """parse_date_from_text関数のテスト"""

    def test_ashita(self):
        """「明日」のテスト"""
        result = parse_date_from_text("明日")
        today = datetime.now(JST).date()
        expected = (today + timedelta(days=1)).strftime("%Y-%m-%d")
        assert result == expected

    def test_asatte(self):
        """「明後日」のテスト"""
        result = parse_date_from_text("明後日")
        today = datetime.now(JST).date()
        expected = (today + timedelta(days=2)).strftime("%Y-%m-%d")
        assert result == expected

    def test_kyou(self):
        """「今日」のテスト"""
        result = parse_date_from_text("今日")
        today = datetime.now(JST).date()
        expected = today.strftime("%Y-%m-%d")
        assert result == expected

    def test_days_later(self):
        """「○日後」のテスト"""
        result = parse_date_from_text("3日後")
        today = datetime.now(JST).date()
        expected = (today + timedelta(days=3)).strftime("%Y-%m-%d")
        assert result == expected

    def test_mm_dd_format(self):
        """「MM/DD」形式のテスト"""
        result = parse_date_from_text("12/31")
        assert result is not None
        assert result.endswith("-12-31")

    def test_mm_gatsu_dd_nichi_format(self):
        """「MM月DD日」形式のテスト"""
        result = parse_date_from_text("12月31日")
        assert result is not None
        assert result.endswith("-12-31")

    def test_invalid_text(self):
        """無効なテキストのテスト"""
        result = parse_date_from_text("無関係なテキスト")
        assert result is None

    def test_raishuu(self):
        """「来週」のテスト"""
        result = parse_date_from_text("来週")
        assert result is not None
        # 来週の月曜日の日付が返される
        parsed_date = datetime.strptime(result, "%Y-%m-%d").date()
        # 月曜日であることを確認
        assert parsed_date.weekday() == 0

    def test_raishuu_kinyoubi(self):
        """「来週金曜日」のテスト"""
        result = parse_date_from_text("来週金曜日")
        assert result is not None
        parsed_date = datetime.strptime(result, "%Y-%m-%d").date()
        # 金曜日であることを確認
        assert parsed_date.weekday() == 4


class TestCheckDeadlineProximity:
    """check_deadline_proximity関数のテスト"""

    def test_today_needs_alert(self):
        """今日の期限はアラートが必要"""
        today = datetime.now(JST).date().strftime("%Y-%m-%d")
        needs_alert, days_until, limit_date = check_deadline_proximity(today)
        assert needs_alert is True
        assert days_until == 0

    def test_tomorrow_needs_alert(self):
        """明日の期限はアラートが必要"""
        tomorrow = (datetime.now(JST).date() + timedelta(days=1)).strftime("%Y-%m-%d")
        needs_alert, days_until, limit_date = check_deadline_proximity(tomorrow)
        assert needs_alert is True
        assert days_until == 1

    def test_far_future_no_alert(self):
        """遠い未来の期限はアラート不要"""
        far_future = (datetime.now(JST).date() + timedelta(days=30)).strftime("%Y-%m-%d")
        needs_alert, days_until, limit_date = check_deadline_proximity(far_future)
        assert needs_alert is False
        assert days_until == 30

    def test_past_date_no_alert(self):
        """過去の日付はアラート不要"""
        past = (datetime.now(JST).date() - timedelta(days=1)).strftime("%Y-%m-%d")
        needs_alert, days_until, limit_date = check_deadline_proximity(past)
        assert needs_alert is False
        assert days_until < 0

    def test_empty_string(self):
        """空文字列"""
        needs_alert, days_until, limit_date = check_deadline_proximity("")
        assert needs_alert is False
        assert days_until == -1
        assert limit_date is None

    def test_none_value(self):
        """None値"""
        needs_alert, days_until, limit_date = check_deadline_proximity(None)
        assert needs_alert is False
        assert days_until == -1
        assert limit_date is None


class TestGetOverdueDays:
    """get_overdue_days関数のテスト"""

    def test_no_overdue(self):
        """期限超過していない場合"""
        future_timestamp = int((datetime.now(JST) + timedelta(days=1)).timestamp())
        result = get_overdue_days(future_timestamp)
        assert result == 0

    def test_overdue_1_day(self):
        """1日超過"""
        yesterday_timestamp = int((datetime.now(JST) - timedelta(days=1)).timestamp())
        result = get_overdue_days(yesterday_timestamp)
        assert result == 1

    def test_overdue_5_days(self):
        """5日超過"""
        past_timestamp = int((datetime.now(JST) - timedelta(days=5)).timestamp())
        result = get_overdue_days(past_timestamp)
        assert result == 5

    def test_datetime_input(self):
        """datetime型の入力"""
        yesterday = datetime.now(JST) - timedelta(days=1)
        result = get_overdue_days(yesterday)
        assert result == 1

    def test_none_value(self):
        """None値"""
        result = get_overdue_days(None)
        assert result == 0

    def test_float_input(self):
        """float型の入力"""
        yesterday_timestamp = float((datetime.now(JST) - timedelta(days=1)).timestamp())
        result = get_overdue_days(yesterday_timestamp)
        assert result == 1


class TestConstants:
    """定数のテスト"""

    def test_jst_offset(self):
        """JSTのオフセットが+9時間であること"""
        assert JST.utcoffset(None) == timedelta(hours=9)

    def test_deadline_alert_days(self):
        """DEADLINE_ALERT_DAYSの設定"""
        assert 0 in DEADLINE_ALERT_DAYS  # 今日
        assert 1 in DEADLINE_ALERT_DAYS  # 明日
        assert 2 not in DEADLINE_ALERT_DAYS  # 明後日はアラート対象外
