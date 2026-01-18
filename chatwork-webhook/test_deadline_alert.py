#!/usr/bin/env python3
"""
期限ガードレール機能のテスト（v10.3.2 メンション対応版）

テストケース:
1. 当日期限 → アラート必要
2. 明日期限 → アラート必要
3. 明後日期限 → アラート不要
4. 1週間後期限 → アラート不要
5. 過去日付 → アラート不要
6. 期限なし → アラート不要
7. メッセージ内容確認（カズさんの意図反映）
8. メンション機能確認（v10.3.2）
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


def generate_deadline_alert_message(
    task_name: str,
    limit_date,
    days_until: int,
    requester_account_id: str = None,
    requester_name: str = None
) -> str:
    """
    期限が近いタスクのアラートメッセージを生成する（v10.3.2 メンション対応版）
    """
    day_label = DEADLINE_ALERT_DAYS.get(days_until, f"{days_until}日後")
    formatted_date = limit_date.strftime("%m/%d")

    # メンション部分を生成
    mention_line = ""
    if requester_account_id:
        if requester_name:
            mention_line = f"[To:{requester_account_id}] {requester_name}さん\n\n"
        else:
            mention_line = f"[To:{requester_account_id}]\n\n"

    message = f"""{mention_line}⚠️ 期限が近いタスクだウル！

「{task_name}」の期限が【{formatted_date}（{day_label}）】だウル。

期限が当日・明日だと、依頼された側も大変かもしれないウル。
もし余裕があるなら、期限を少し先に編集してあげてね。

※ 明後日以降ならこのアラートは出ないウル
※ このままでOKなら、何もしなくて大丈夫だウル！"""

    return message


def generate_deadline_alert_message_for_manual_task(
    task_name: str,
    limit_date,
    days_until: int,
    assigned_to_name: str,
    requester_account_id: str = None,
    requester_name: str = None
) -> str:
    """
    手動追加タスク用のアラートメッセージを生成する（v10.3.2 メンション対応版）
    """
    day_label = DEADLINE_ALERT_DAYS.get(days_until, f"{days_until}日後")
    formatted_date = limit_date.strftime("%m/%d")

    if len(task_name) > 30:
        task_name = task_name[:30] + "..."

    # メンション部分を生成
    mention_line = ""
    if requester_account_id:
        if requester_name:
            mention_line = f"[To:{requester_account_id}] {requester_name}さん\n\n"
        else:
            mention_line = f"[To:{requester_account_id}]\n\n"

    message = f"""{mention_line}⚠️ 期限が近いタスクを追加したウル！

{assigned_to_name}さんへの「{task_name}」の期限が【{formatted_date}（{day_label}）】だウル。

期限が当日・明日だと、依頼された側も大変かもしれないウル。
もし余裕があるなら、ChatWorkでタスクの期限を少し先に編集してあげてね。

※ 明後日以降ならこのアラートは出ないウル
※ このままでOKなら、何もしなくて大丈夫だウル！"""

    return message


def test_deadline_alert():
    """期限ガードレールのテスト"""
    print("=" * 60)
    print("期限ガードレール機能テスト（v10.3.2 メンション対応版）")
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

    print("-" * 60)
    print("【テスト1】期限チェック機能")
    print("-" * 60)

    for name, date_str, expected_alert, expected_days in test_cases:
        print(f"\nテスト: {name}")
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

    print()
    print("-" * 60)
    print("【テスト2】メッセージ内容確認（カズさんの意図反映）")
    print("-" * 60)

    # ソウルくん経由のメッセージ（メンションなし - 後方互換性確認）
    print("\n■ ソウルくん経由タスク作成時のメッセージ（メンションなし）:")
    _, _, limit_date = check_deadline_proximity(today.strftime("%Y-%m-%d"))
    msg = generate_deadline_alert_message("資料作成", limit_date, 0)
    print("-" * 40)
    print(msg)
    print("-" * 40)

    # 必須フレーズのチェック
    required_phrases = [
        "依頼された側も大変かもしれないウル",
        "期限を少し先に編集してあげてね",
        "明後日以降ならこのアラートは出ないウル",
    ]

    all_phrases_found = True
    for phrase in required_phrases:
        if phrase in msg:
            print(f"  ✅ 必須フレーズ含まれる: 「{phrase[:20]}...」")
        else:
            print(f"  ❌ 必須フレーズ不足: 「{phrase[:20]}...」")
            all_phrases_found = False

    if all_phrases_found:
        passed += 1
        print("  → ソウルくん経由メッセージ PASSED")
    else:
        failed += 1
        print("  → ソウルくん経由メッセージ FAILED")

    # 手動追加時のメッセージ（メンションなし - 後方互換性確認）
    print("\n■ 手動タスク追加時のメッセージ（メンションなし）:")
    msg_manual = generate_deadline_alert_message_for_manual_task(
        "レポート提出", limit_date, 0, "田中"
    )
    print("-" * 40)
    print(msg_manual)
    print("-" * 40)

    # 手動追加用の必須フレーズのチェック
    required_phrases_manual = [
        "田中さんへの「レポート提出」",
        "依頼された側も大変かもしれないウル",
        "ChatWorkでタスクの期限を少し先に編集してあげてね",
    ]

    all_phrases_found_manual = True
    for phrase in required_phrases_manual:
        if phrase in msg_manual:
            print(f"  ✅ 必須フレーズ含まれる: 「{phrase[:25]}...」")
        else:
            print(f"  ❌ 必須フレーズ不足: 「{phrase[:25]}...」")
            all_phrases_found_manual = False

    if all_phrases_found_manual:
        passed += 1
        print("  → 手動追加メッセージ PASSED")
    else:
        failed += 1
        print("  → 手動追加メッセージ FAILED")

    print()
    print("-" * 60)
    print("【テスト3】メンション機能確認（v10.3.2）")
    print("-" * 60)

    # ソウルくん経由（メンションあり）
    print("\n■ ソウルくん経由タスク作成時のメッセージ（メンションあり）:")
    msg_with_mention = generate_deadline_alert_message(
        task_name="資料作成",
        limit_date=limit_date,
        days_until=0,
        requester_account_id="1728974",
        requester_name="菊地"
    )
    print("-" * 40)
    print(msg_with_mention)
    print("-" * 40)

    # メンションのチェック
    mention_ok = "[To:1728974] 菊地さん" in msg_with_mention
    if mention_ok:
        print(f"  ✅ メンション含まれる: [To:1728974] 菊地さん")
        passed += 1
        print("  → ソウルくん経由メンション PASSED")
    else:
        print(f"  ❌ メンション不足")
        failed += 1
        print("  → ソウルくん経由メンション FAILED")

    # 手動追加（メンションあり）
    print("\n■ 手動タスク追加時のメッセージ（メンションあり）:")
    msg_manual_with_mention = generate_deadline_alert_message_for_manual_task(
        task_name="レポート提出",
        limit_date=limit_date,
        days_until=0,
        assigned_to_name="田中",
        requester_account_id="1728974",
        requester_name="菊地"
    )
    print("-" * 40)
    print(msg_manual_with_mention)
    print("-" * 40)

    # メンションのチェック
    mention_manual_ok = "[To:1728974] 菊地さん" in msg_manual_with_mention
    if mention_manual_ok:
        print(f"  ✅ メンション含まれる: [To:1728974] 菊地さん")
        passed += 1
        print("  → 手動追加メンション PASSED")
    else:
        print(f"  ❌ メンション不足")
        failed += 1
        print("  → 手動追加メンション FAILED")

    # アカウントIDのみ（名前なし）のケース
    print("\n■ メンション（名前なし）のケース:")
    msg_no_name = generate_deadline_alert_message(
        task_name="資料作成",
        limit_date=limit_date,
        days_until=0,
        requester_account_id="1728974",
        requester_name=None
    )

    mention_no_name_ok = "[To:1728974]\n\n" in msg_no_name
    if mention_no_name_ok:
        print(f"  ✅ 名前なしメンション正常: [To:1728974]")
        passed += 1
        print("  → 名前なしメンション PASSED")
    else:
        print(f"  ❌ 名前なしメンション不正")
        failed += 1
        print("  → 名前なしメンション FAILED")

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
