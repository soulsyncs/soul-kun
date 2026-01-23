#!/usr/bin/env python3
"""
オールメンション（toall）無視機能のテスト（v10.16.0）

テスト項目:
1. is_toall_mention関数の基本動作
2. 様々な入力パターンでの判定
3. エッジケース（None、空文字、型違い）
"""

import sys
import os

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def is_toall_mention(body):
    """オールメンション（[toall]）かどうかを判定

    オールメンションはアナウンス用途で使われるため、
    ソウルくんは反応しない。

    v10.16.0で追加

    Args:
        body: メッセージ本文

    Returns:
        bool: [toall]が含まれていればTrue
    """
    # Noneチェック
    if body is None:
        return False

    # 型チェック
    if not isinstance(body, str):
        try:
            body = str(body)
        except:
            return False

    # 空文字チェック
    if not body:
        return False

    try:
        # ChatWorkのオールメンションパターン: [toall]
        # 大文字小文字を区別しない（念のため）
        if "[toall]" in body.lower():
            return True

        return False
    except Exception as e:
        print(f"⚠️ is_toall_mention エラー: {e}")
        return False


def run_tests():
    """テスト実行"""
    print("=" * 60)
    print("オールメンション無視機能テスト（v10.16.0）")
    print("=" * 60)

    passed = 0
    failed = 0

    # ========================================
    # テスト1: 基本的なtoallパターン
    # ========================================
    print("\n【テスト1】基本的なtoallパターン")
    print("-" * 40)

    test_cases_basic = [
        # (入力, 期待結果, 説明)
        ("[toall]\nお知らせです", True, "標準的なtoallメッセージ"),
        ("[toall]明日は全員出社です", True, "toall直後にテキスト"),
        ("[To:1728974] 菊地さん、タスクお願いします", False, "個別メンション（toall無し）"),
        ("こんにちは、元気ですか？", False, "通常メッセージ（メンション無し）"),
        ("[rp aid=10909425 to=xxx]返信ありがとう", False, "返信ボタン（toall無し）"),
    ]

    for body, expected, description in test_cases_basic:
        result = is_toall_mention(body)
        status = "✅ PASS" if result == expected else "❌ FAIL"
        if result == expected:
            passed += 1
        else:
            failed += 1
        print(f"  {status}: {description}")
        print(f"         入力: {body[:50]}...")
        print(f"         期待: {expected}, 結果: {result}")

    # ========================================
    # テスト2: 大文字小文字の混在
    # ========================================
    print("\n【テスト2】大文字小文字の混在")
    print("-" * 40)

    test_cases_case = [
        ("[TOALL]\nアナウンスです", True, "全大文字"),
        ("[ToAll]\n重要なお知らせ", True, "キャメルケース"),
        ("[Toall]\nミーティングの連絡", True, "先頭大文字"),
        ("[toALL]\n締め切りの連絡", True, "ALLだけ大文字"),
    ]

    for body, expected, description in test_cases_case:
        result = is_toall_mention(body)
        status = "✅ PASS" if result == expected else "❌ FAIL"
        if result == expected:
            passed += 1
        else:
            failed += 1
        print(f"  {status}: {description}")
        print(f"         入力: {body[:30]}...")
        print(f"         期待: {expected}, 結果: {result}")

    # ========================================
    # テスト3: toallと個別メンションの複合
    # ========================================
    print("\n【テスト3】toallと個別メンションの複合")
    print("-" * 40)

    test_cases_combined = [
        ("[toall]\n[To:1728974] 菊地さん、特にお願いします", True, "toall + 個別メンション"),
        ("[To:1728974]\n[toall]\nみなさん、よろしくお願いします", True, "個別メンション + toall"),
        ("[toall][To:1234567]\n全員と菊地さんへ", True, "両方連続"),
    ]

    for body, expected, description in test_cases_combined:
        result = is_toall_mention(body)
        status = "✅ PASS" if result == expected else "❌ FAIL"
        if result == expected:
            passed += 1
        else:
            failed += 1
        print(f"  {status}: {description}")
        print(f"         入力: {body[:40]}...")
        print(f"         期待: {expected}, 結果: {result}")

    # ========================================
    # テスト4: エッジケース
    # ========================================
    print("\n【テスト4】エッジケース")
    print("-" * 40)

    test_cases_edge = [
        (None, False, "None入力"),
        ("", False, "空文字"),
        ("   ", False, "スペースのみ"),
        (123, False, "数値型"),
        (["toall"], False, "リスト型"),
        ("toall（括弧なし）", False, "括弧なしのtoall"),
        ("[toall", False, "閉じ括弧なし"),
        ("toall]", False, "開き括弧なし"),
        ("[to all]", False, "スペース入り（無効）"),
        ("[toall]", True, "toallのみ"),
    ]

    for body, expected, description in test_cases_edge:
        result = is_toall_mention(body)
        status = "✅ PASS" if result == expected else "❌ FAIL"
        if result == expected:
            passed += 1
        else:
            failed += 1
        body_str = str(body)[:30] if body is not None else "None"
        print(f"  {status}: {description}")
        print(f"         入力: {body_str}")
        print(f"         期待: {expected}, 結果: {result}")

    # ========================================
    # テスト5: 実際の業務メッセージ想定
    # ========================================
    print("\n【テスト5】実際の業務メッセージ想定")
    print("-" * 40)

    test_cases_real = [
        (
            "[toall]\n\n本日のスタンドアップミーティングは10時からです。\n各自準備をお願いします。",
            True,
            "スタンドアップ連絡"
        ),
        (
            "[toall]\n【重要】明日は全員出社日です\n・持ち物：PC、社員証\n・時間：9:00集合",
            True,
            "重要なお知らせ"
        ),
        (
            "[To:10909425] ソウルくん\n今日のタスクを教えて",
            False,
            "ソウルくんへの個別質問"
        ),
        (
            "[rp aid=10909425 to=xxx-yyy]\nありがとうございます！",
            False,
            "ソウルくんへの返信"
        ),
        (
            "お疲れ様です。明日の会議の件ですが...",
            False,
            "通常の業務連絡（メンション無し）"
        ),
    ]

    for body, expected, description in test_cases_real:
        result = is_toall_mention(body)
        status = "✅ PASS" if result == expected else "❌ FAIL"
        if result == expected:
            passed += 1
        else:
            failed += 1
        print(f"  {status}: {description}")
        print(f"         期待: {expected}, 結果: {result}")

    # ========================================
    # 結果サマリー
    # ========================================
    print("\n" + "=" * 60)
    print(f"テスト結果: {passed} passed, {failed} failed")
    print("=" * 60)

    if failed == 0:
        print("✅ すべてのテストがパスしました！")
        return 0
    else:
        print(f"❌ {failed}件のテストが失敗しました")
        return 1


if __name__ == "__main__":
    exit_code = run_tests()
    sys.exit(exit_code)
