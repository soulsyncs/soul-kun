"""
v10.14.0 タスク要約機能のテスト（スタンドアロン版）

テスト項目:
1. remove_greetings() - 挨拶除去
2. extract_task_subject() - 件名抽出
3. is_greeting_only() - 挨拶のみ判定
4. validate_summary() - 要約バリデーション
"""

import re

# =====================================================
# 挨拶パターン（main.pyからコピー）
# =====================================================
GREETING_PATTERNS = [
    # 開始の挨拶
    r'^お疲れ様です[。！!]?\s*',
    r'^お疲れさまです[。！!]?\s*',
    r'^おつかれさまです[。！!]?\s*',
    r'^お疲れ様でした[。！!]?\s*',
    r'^いつもお世話になっております[。！!]?\s*',
    r'^いつもお世話になります[。！!]?\s*',
    r'^お世話になっております[。！!]?\s*',
    r'^お世話になります[。！!]?\s*',
    r'^こんにちは[。！!]?\s*',
    r'^おはようございます[。！!]?\s*',
    r'^こんばんは[。！!]?\s*',
    # お詫び・断り
    r'^夜分に申し訳ございません[。！!]?\s*',
    r'^夜分遅くに失礼いたします[。！!]?\s*',
    r'^夜分遅くに失礼します[。！!]?\s*',
    r'^お忙しいところ恐れ入りますが[、,]?\s*',
    r'^お忙しいところ申し訳ございませんが[、,]?\s*',
    r'^お忙しいところ恐縮ですが[、,]?\s*',
    r'^突然のご連絡失礼いたします[。！!]?\s*',
    r'^突然のご連絡失礼します[。！!]?\s*',
    r'^ご連絡が遅くなり申し訳ございません[。！!]?\s*',
    r'^ご連絡遅くなりまして申し訳ございません[。！!]?\s*',
    r'^大変遅くなってしまい申し訳[ございませんありません。！!]*\s*',
    # メール形式
    r'^[Rr][Ee]:\s*',
    r'^[Ff][Ww][Dd]?:\s*',
    r'^[Cc][Cc]:\s*',
]

CLOSING_PATTERNS = [
    r'よろしくお願い(いた)?します[。！!]?\s*$',
    r'よろしくお願い(いた)?致します[。！!]?\s*$',
    r'お願い(いた)?します[。！!]?\s*$',
    r'ご確認(の程)?よろしくお願い(いた)?します[。！!]?\s*$',
    r'ご対応(の程)?よろしくお願い(いた)?します[。！!]?\s*$',
    r'ご検討(の程)?よろしくお願い(いた)?します[。！!]?\s*$',
    r'何卒よろしくお願い(いた)?します[。！!]?\s*$',
    r'以上、?よろしくお願い(いた)?します[。！!]?\s*$',
    r'以上です[。！!]?\s*$',
    r'以上となります[。！!]?\s*$',
    r'引き続きよろしくお願い(いた)?します[。！!]?\s*$',
]


def remove_greetings(text: str) -> str:
    """テキストから日本語の挨拶・定型文を除去する"""
    if not text:
        return ""

    result = text

    # 開始の挨拶を除去（複数回試行 - ネストした挨拶対応）
    for _ in range(3):
        original = result
        for pattern in GREETING_PATTERNS:
            result = re.sub(pattern, '', result, flags=re.MULTILINE | re.IGNORECASE)
        if result == original:
            break

    # 終了の挨拶を除去
    for pattern in CLOSING_PATTERNS:
        result = re.sub(pattern, '', result, flags=re.MULTILINE | re.IGNORECASE)

    # 行頭の空白・改行を整理
    result = result.strip()

    return result


def extract_task_subject(text: str) -> str:
    """テキストからタスクの件名/タイトルを抽出する"""
    if not text:
        return ""

    # 1. 【...】 形式の件名を抽出
    subject_match = re.search(r'【([^】]+)】', text)
    if subject_match:
        subject = subject_match.group(1).strip()
        if len(subject) >= 3:
            return f"【{subject}】"

    # 2. ■/●/◆/▼/★ で始まる見出しを抽出
    headline_match = re.search(r'^[■●◆▼★☆□○◇]\s*(.+?)(?:\n|$)', text, re.MULTILINE)
    if headline_match:
        headline = headline_match.group(1).strip()
        if 3 <= len(headline) <= 50:
            return headline

    # 3. 1行目が短い場合は件名として扱う
    first_line = text.split('\n')[0].strip()
    if (first_line and
        len(first_line) <= 40 and
        not re.match(r'^(お疲れ|いつも|こんにち|おはよう|こんばん)', first_line) and
        not first_line.endswith(('。', '？', '?'))):
        return first_line

    return ""


def is_greeting_only(text: str) -> bool:
    """テキストが挨拶のみかどうかを判定する"""
    if not text:
        return True

    cleaned = remove_greetings(text)
    return len(cleaned.strip()) <= 5


def validate_summary(summary: str, original_body: str) -> bool:
    """要約の品質を検証する"""
    if not summary:
        return False

    # 1. 挨拶だけの場合はNG
    if is_greeting_only(summary):
        return False

    # 2. 非常に短い場合はNG（ただし元の本文も短い場合はOK）
    if len(summary) < 8 and len(original_body) > 50:
        return False

    # 3. 明らかに途切れている場合はNG
    truncation_indicators = ['…', '...', '。。', '、、']
    if any(summary.endswith(ind) for ind in truncation_indicators):
        return False

    # 4. 挨拶で始まる場合はNG
    greeting_starts = ['お疲れ', 'いつも', 'お世話', '夜分', 'お忙し']
    if any(summary.startswith(g) for g in greeting_starts):
        return False

    return True


def test_remove_greetings():
    """挨拶除去のテスト"""
    print("\n=== test_remove_greetings ===")

    test_cases = [
        ("お疲れ様です！\n夜分に申し訳ございません。\n経費精算書を提出してください。", "経費精算書を提出してください"),
        ("お疲れ様です。\nETCカードの利用報告をお願いします。", "ETCカードの利用報告"),
        ("いつもお世話になっております。\n請求書の確認をお願いいたします。", "請求書の確認"),
        ("こんにちは！タスクの進捗を教えてください。", "タスクの進捗を教えてください"),
        ("Re: 会議資料の件", "会議資料の件"),
        ("CC: 週次報告について", "週次報告について"),
        ("シンプルなタスク内容", "シンプルなタスク内容"),
    ]

    passed = 0
    failed = 0

    for input_text, expected_part in test_cases:
        result = remove_greetings(input_text)
        if expected_part in result:
            print(f"✅ PASS: '{input_text[:30]}...' -> '{result}'")
            passed += 1
        else:
            print(f"❌ FAIL: '{input_text[:30]}...' -> '{result}' (expected to contain '{expected_part}')")
            failed += 1

    print(f"\n結果: {passed}/{passed + failed} passed")
    return failed == 0


def test_extract_task_subject():
    """件名抽出のテスト"""
    print("\n=== test_extract_task_subject ===")

    test_cases = [
        ("【1月ETCカード利用管理依頼】\nお疲れ様です！\n...", "【1月ETCカード利用管理依頼】"),
        ("【経費精算書提出のお願い】について", "【経費精算書提出のお願い】"),
        ("■ 週次報告\nお疲れ様です。今週の報告です。", "週次報告"),
        ("● 緊急対応のお願い\n本日中に対応ください。", "緊急対応のお願い"),
        ("お疲れ様です。\n経費精算をお願いします。", ""),
    ]

    passed = 0
    failed = 0

    for input_text, expected in test_cases:
        result = extract_task_subject(input_text)
        if result == expected:
            print(f"✅ PASS: '{input_text[:30]}...' -> '{result}'")
            passed += 1
        else:
            print(f"❌ FAIL: '{input_text[:30]}...' -> '{result}' (expected '{expected}')")
            failed += 1

    print(f"\n結果: {passed}/{passed + failed} passed")
    return failed == 0


def test_is_greeting_only():
    """挨拶のみ判定のテスト"""
    print("\n=== test_is_greeting_only ===")

    test_cases = [
        ("お疲れ様です！", True),
        ("お疲れ様です！夜分に申し訳ございません。", True),
        ("いつもお世話になっております。", True),
        ("お疲れ様です！経費精算書を提出してください。", False),
        ("ETCカードの利用報告", False),
        ("【重要】会議資料の提出", False),
    ]

    passed = 0
    failed = 0

    for input_text, expected in test_cases:
        result = is_greeting_only(input_text)
        if result == expected:
            print(f"✅ PASS: '{input_text[:30]}' -> {result}")
            passed += 1
        else:
            print(f"❌ FAIL: '{input_text[:30]}' -> {result} (expected {expected})")
            failed += 1

    print(f"\n結果: {passed}/{passed + failed} passed")
    return failed == 0


def test_validate_summary():
    """要約バリデーションのテスト"""
    print("\n=== test_validate_summary ===")

    test_cases = [
        ("経費精算書の提出依頼", "お疲れ様です。経費精算書を提出してください。", True),
        ("ETCカード利用報告", "ETCカードの利用報告をお願いします。", True),
        ("お疲れ様です！夜分に申し訳ございません。", "長い本文..." * 20, False),
        ("いつもお世話になっております", "長い本文..." * 20, False),
        ("経費精算書を確認し…", "長い本文..." * 20, False),
        ("短", "とても長い本文がここに入ります" * 10, False),
    ]

    passed = 0
    failed = 0

    for summary, original, expected in test_cases:
        result = validate_summary(summary, original)
        if result == expected:
            print(f"✅ PASS: '{summary[:30]}' -> {result}")
            passed += 1
        else:
            print(f"❌ FAIL: '{summary[:30]}' -> {result} (expected {expected})")
            failed += 1

    print(f"\n結果: {passed}/{passed + failed} passed")
    return failed == 0


def test_real_world_examples():
    """実際のタスク例でのテスト"""
    print("\n=== test_real_world_examples ===")

    # DBで見つかった実際の低品質要約
    test_cases = [
        # (元の要約, 元の本文, 期待: validate_summary=False)
        (
            "お疲れ様です！\n夜分に申し訳ございません。",
            "[qt][qtmeta aid=2930506 time=1768998166][To:1728974]菊地 雅克(キクチ マサカズ)さん\n[To:10191707]高野　義浩 (タカノ ヨシヒロ)さん\nお疲れ様です！\n夜分に申し訳ございません。\n経理申請フォームの確認をお願いします。[/qt]",
            False
        ),
        (
            "【1月ETCカード利用管理依頼】\nお疲れ様です！\nETCカードに関わる業務の",
            "【1月ETCカード利用管理依頼】\nお疲れ様です！\nETCカードに関わる業務のご依頼です！\nこちら来月の月初（10日ごろまで）にご対応いただければと思います。",
            True  # 件名があるから有効
        ),
    ]

    passed = 0
    failed = 0

    for summary, original, expected in test_cases:
        result = validate_summary(summary, original)
        if result == expected:
            print(f"✅ PASS: '{summary[:30]}...' -> validate={result}")
            passed += 1
        else:
            print(f"❌ FAIL: '{summary[:30]}...' -> validate={result} (expected {expected})")
            failed += 1

    print(f"\n結果: {passed}/{passed + failed} passed")
    return failed == 0


def run_all_tests():
    """全テストを実行"""
    print("=" * 60)
    print("v10.14.0 タスク要約機能テスト")
    print("=" * 60)

    results = []
    results.append(("remove_greetings", test_remove_greetings()))
    results.append(("extract_task_subject", test_extract_task_subject()))
    results.append(("is_greeting_only", test_is_greeting_only()))
    results.append(("validate_summary", test_validate_summary()))
    results.append(("real_world_examples", test_real_world_examples()))

    print("\n" + "=" * 60)
    print("テスト結果サマリー")
    print("=" * 60)

    all_passed = True
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {name}")
        if not passed:
            all_passed = False

    print("\n" + "=" * 60)
    if all_passed:
        print("✅ 全テスト成功!")
    else:
        print("❌ 一部テスト失敗")
    print("=" * 60)

    return all_passed


if __name__ == "__main__":
    import sys
    success = run_all_tests()
    sys.exit(0 if success else 1)
