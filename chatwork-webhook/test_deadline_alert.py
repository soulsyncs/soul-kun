#!/usr/bin/env python3
"""
期限ガードレール機能のテスト

テストケース:
1. 当日期限 → アラート必要
2. 明日期限 → アラート必要
3. 明後日期限 → アラート不要
4. 1週間後期限 → アラート不要
5. 過去日付 → アラート不要
6. 期限なし → アラート不要
"""

import sys
import os

# 親ディレクトリをパスに追加
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime, timedelta, timezone

# JST タイムゾーン（main.pyと同じ定義）
JST = timezone(timedelta(hours=9))

# 期限ガードレール設定（main.pyと同じ定義）
DEADLINE_ALERT_DAYS = {
    0: "今日",    # 当日
    1: "明日",    # 翌日
}


def check_deadline_proximity(limit_date_str: str) -> tuple:
    """
    期限が近すぎるかチェックする（main.pyからコピー）
    """
    if not limit_date_str:
        return False, -1, None

    try:
        now = datetime.now(JST)
        today = now.date()
        limit_date = datetime.strptime(limit_date_str, "%Y-%m-%d").date()
        days_until = (limit_date - today).days

        if days_until < 0:
            return False, days_until, limit_date

        if days_until in DEADLINE_ALERT_DAYS:
            return True, days_until, limit_date

        return False, days_until, limit_date
    except Exception as e:
        print(f"エラー: {e}")
        return False, -1, None


def generate_deadline_alert_message(task_name: str, limit_date, days_until: int) -> str:
    """
    期限が近いタスクのアラートメッセージを生成する（main.pyからコピー）
    """
    day_label = DEADLINE_ALERT_DAYS.get(days_until, f"{days_until}日後")
    formatted_date = limit_date.strftime("%m/%d")

    message = f"""⚠️ 期限が近いタスクだウル！

「{task_name}」の期限が【{formatted_date}（{day_label}）】になってるウル。

期限が近すぎると、リマインドが届く前にタスクが期限切れになっちゃうウル...

📌 確認してほしいウル：
・このまま追加して大丈夫？
・間違えてたらChatWorkでタスクの期限を編集してね
・期限を編集したら、それに連動して僕がリマインドしていくウル！

このままでOKなら、何もしなくて大丈夫だウル！"""

    return message


def test_deadline_alert():
    """期限ガードレールのテスト"""
    print("=" * 60)
    print("期限ガードレール機能テスト")
    print("=" * 60)

    now = datetime.now(JST)
    today = now.date()
    print(f"現在日時（JST）: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # テストケース
    test_cases = [
        ("当日期限", today.strftime("%Y-%m-%d"), True, 0),
        ("明日期限", (today + timedelta(days=1)).strftime("%Y-%m-%d"), True, 1),
        ("明後日期限", (today + timedelta(days=2)).strftime("%Y-%m-%d"), False, 2),
        ("1週間後期限", (today + timedelta(days=7)).strftime("%Y-%m-%d"), False, 7),
        ("過去日付（昨日）", (today - timedelta(days=1)).strftime("%Y-%m-%d"), False, -1),
        ("期限なし", None, False, -1),
    ]

    passed = 0
    failed = 0

    for name, date_str, expected_alert, expected_days in test_cases:
        print(f"テスト: {name}")
        print(f"  入力: {date_str}")

        needs_alert, days_until, limit_date = check_deadline_proximity(date_str)

        alert_ok = needs_alert == expected_alert
        days_ok = days_until == expected_days

        print(f"  結果: needs_alert={needs_alert} (期待値: {expected_alert}) {'✅' if alert_ok else '❌'}")
        print(f"        days_until={days_until} (期待値: {expected_days}) {'✅' if days_ok else '❌'}")

        if alert_ok and days_ok:
            passed += 1
            print("  → PASSED")
        else:
            failed += 1
            print("  → FAILED")

        # アラートが必要な場合はメッセージも確認
        if needs_alert:
            message = generate_deadline_alert_message("テストタスク", limit_date, days_until)
            print(f"  生成されるアラートメッセージ:")
            print("-" * 40)
            print(message)
            print("-" * 40)

        print()

    print("=" * 60)
    print(f"テスト結果: {passed} passed, {failed} failed")
    print("=" * 60)

    if failed == 0:
        print("✅ All tests passed!")
        return True
    else:
        print("❌ Some tests failed!")
        return False


if __name__ == "__main__":
    success = test_deadline_alert()
    sys.exit(0 if success else 1)
