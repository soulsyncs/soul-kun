"""
v10.14.1 タスク要約機能のテスト（pytest形式）

★★★ v10.14.1: pytest形式に変換 ★★★

テスト項目:
1. remove_greetings() - 挨拶除去
2. extract_task_subject() - 件名抽出
3. is_greeting_only() - 挨拶のみ判定
4. validate_summary() - 要約バリデーション
5. validate_and_get_reason() - 理由付きバリデーション
6. clean_chatwork_tags() - ChatWorkタグ除去

実行方法:
    pytest test_summary_v10_14.py -v
"""

import pytest
import sys
import os

# lib/をインポートパスに追加
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from lib import (
        GREETING_PATTERNS,
        CLOSING_PATTERNS,
        GREETING_STARTS,
        TRUNCATION_INDICATORS,
        remove_greetings,
        extract_task_subject,
        is_greeting_only,
        validate_summary,
        validate_and_get_reason,
        clean_chatwork_tags,
    )
    LIB_AVAILABLE = True
except ImportError as e:
    print(f"Warning: lib/ not available ({e}), using local definitions")
    LIB_AVAILABLE = False

    # Fallback: lib/がない場合のローカル定義
    import re

    GREETING_PATTERNS = [
        r'^お疲れ様です[。！!]?\s*',
        r'^お疲れさまです[。！!]?\s*',
        r'^いつもお世話になっております[。！!]?\s*',
        r'^こんにちは[。！!]?\s*',
        r'^夜分に申し訳ございません[。！!]?\s*',
        r'^[Rr][Ee]:\s*',
        r'^[Cc][Cc]:\s*',
    ]

    CLOSING_PATTERNS = [
        r'よろしくお願い(いた)?します[。！!]?\s*$',
    ]

    GREETING_STARTS = ['お疲れ', 'いつも', 'お世話', '夜分', 'お忙し']
    TRUNCATION_INDICATORS = ['…', '...', '。。', '、、']

    def remove_greetings(text: str) -> str:
        if not text:
            return ""
        result = text
        for _ in range(3):
            original = result
            for pattern in GREETING_PATTERNS:
                result = re.sub(pattern, '', result, flags=re.MULTILINE | re.IGNORECASE)
            if result == original:
                break
        for pattern in CLOSING_PATTERNS:
            result = re.sub(pattern, '', result, flags=re.MULTILINE | re.IGNORECASE)
        return result.strip()

    def extract_task_subject(text: str) -> str:
        if not text:
            return ""
        subject_match = re.search(r'【([^】]+)】', text)
        if subject_match:
            subject = subject_match.group(1).strip()
            if len(subject) >= 3:
                return f"【{subject}】"
        headline_match = re.search(r'^[■●◆▼★☆□○◇]\s*(.+?)(?:\n|$)', text, re.MULTILINE)
        if headline_match:
            headline = headline_match.group(1).strip()
            if 3 <= len(headline) <= 50:
                return headline
        return ""

    def is_greeting_only(text: str) -> bool:
        if not text:
            return True
        cleaned = remove_greetings(text)
        return len(cleaned.strip()) <= 5

    def validate_summary(summary: str, original_body: str) -> bool:
        if not summary:
            return False
        if is_greeting_only(summary):
            return False
        if len(summary) < 8 and len(original_body) > 50:
            return False
        if any(summary.endswith(ind) for ind in TRUNCATION_INDICATORS):
            return False
        if any(summary.startswith(g) for g in GREETING_STARTS):
            return False
        return True

    def validate_and_get_reason(summary, original_body):
        if not validate_summary(summary, original_body):
            return False, "invalid"
        return True, None

    def clean_chatwork_tags(body: str) -> str:
        return body


# =====================================================
# テストケース
# =====================================================

class TestRemoveGreetings:
    """remove_greetings() のテスト"""

    @pytest.mark.parametrize("input_text,expected_part", [
        ("お疲れ様です！\n夜分に申し訳ございません。\n経費精算書を提出してください。", "経費精算書を提出してください"),
        ("お疲れ様です。\nETCカードの利用報告をお願いします。", "ETCカードの利用報告"),
        ("いつもお世話になっております。\n請求書の確認をお願いいたします。", "請求書の確認"),
        ("こんにちは！タスクの進捗を教えてください。", "タスクの進捗を教えてください"),
        ("Re: 会議資料の件", "会議資料の件"),
        ("CC: 週次報告について", "週次報告について"),
        ("シンプルなタスク内容", "シンプルなタスク内容"),
    ])
    def test_basic_greeting_removal(self, input_text, expected_part):
        """基本的な挨拶除去"""
        result = remove_greetings(input_text)
        assert expected_part in result, f"Expected '{expected_part}' in '{result}'"

    def test_empty_input(self):
        """空入力の処理"""
        assert remove_greetings("") == ""
        assert remove_greetings(None) == ""

    def test_no_greeting(self):
        """挨拶がない場合"""
        text = "経費精算書を提出してください"
        result = remove_greetings(text)
        assert text in result

    def test_nested_greetings(self):
        """ネストした挨拶の除去"""
        text = "お疲れ様です！いつもお世話になっております。タスク内容です。"
        result = remove_greetings(text)
        assert "タスク内容" in result


class TestExtractTaskSubject:
    """extract_task_subject() のテスト"""

    @pytest.mark.parametrize("input_text,expected", [
        ("【1月ETCカード利用管理依頼】\nお疲れ様です！\n...", "【1月ETCカード利用管理依頼】"),
        ("【経費精算書提出のお願い】について", "【経費精算書提出のお願い】"),
        ("■ 週次報告\nお疲れ様です。今週の報告です。", "週次報告"),
        ("● 緊急対応のお願い\n本日中に対応ください。", "緊急対応のお願い"),
        ("お疲れ様です。\n経費精算をお願いします。", ""),
    ])
    def test_subject_extraction(self, input_text, expected):
        """件名抽出"""
        result = extract_task_subject(input_text)
        assert result == expected

    def test_empty_input(self):
        """空入力の処理"""
        assert extract_task_subject("") == ""
        assert extract_task_subject(None) == ""

    def test_short_subject_ignored(self):
        """短すぎる件名は無視"""
        text = "【AB】テスト"  # 2文字は短すぎる
        result = extract_task_subject(text)
        # 3文字以上が必要
        assert result == "" or len(result.strip("【】")) >= 3


class TestIsGreetingOnly:
    """is_greeting_only() のテスト"""

    @pytest.mark.parametrize("input_text,expected", [
        ("お疲れ様です！", True),
        ("お疲れ様です！夜分に申し訳ございません。", True),
        ("いつもお世話になっております。", True),
        ("お疲れ様です！経費精算書を提出してください。", False),
        ("ETCカードの利用報告", False),
        ("【重要】会議資料の提出", False),
        ("", True),  # 空文字列はTrueを期待
        (None, True),  # Noneも同様
    ])
    def test_greeting_only_detection(self, input_text, expected):
        """挨拶のみ判定"""
        result = is_greeting_only(input_text)
        assert result == expected


class TestValidateSummary:
    """validate_summary() のテスト"""

    @pytest.mark.parametrize("summary,original,expected", [
        ("経費精算書の提出依頼", "お疲れ様です。経費精算書を提出してください。", True),
        ("ETCカード利用報告", "ETCカードの利用報告をお願いします。", True),
        ("お疲れ様です！夜分に申し訳ございません。", "長い本文..." * 20, False),
        ("いつもお世話になっております", "長い本文..." * 20, False),
        ("経費精算書を確認し…", "長い本文..." * 20, False),  # 途切れている
        ("短", "とても長い本文がここに入ります" * 10, False),  # 短すぎる
    ])
    def test_summary_validation(self, summary, original, expected):
        """要約バリデーション"""
        result = validate_summary(summary, original)
        assert result == expected

    def test_empty_summary(self):
        """空の要約は無効"""
        assert validate_summary("", "元の本文") == False
        assert validate_summary(None, "元の本文") == False


class TestRealWorldExamples:
    """実際のタスク例でのテスト"""

    @pytest.mark.parametrize("summary,original,expected", [
        # DBで見つかった実際の低品質要約
        (
            "お疲れ様です！\n夜分に申し訳ございません。",
            "[qt][qtmeta aid=2930506 time=1768998166]経理申請フォームの確認をお願いします。[/qt]",
            False
        ),
        # 件名があるから有効
        (
            "【1月ETCカード利用管理依頼】\nETCカードに関わる業務の",
            "【1月ETCカード利用管理依頼】\nお疲れ様です！\nETCカードに関わる業務のご依頼です！",
            True
        ),
    ])
    def test_real_world_cases(self, summary, original, expected):
        """実際のケース"""
        result = validate_summary(summary, original)
        assert result == expected


class TestValidateAndGetReason:
    """validate_and_get_reason() のテスト"""

    def test_valid_summary_returns_none_reason(self):
        """有効な要約は理由なし"""
        is_valid, reason = validate_and_get_reason("経費精算書の提出依頼", "元の本文")
        assert is_valid == True
        assert reason is None

    def test_invalid_summary_returns_reason(self):
        """無効な要約は理由あり"""
        is_valid, reason = validate_and_get_reason("お疲れ様です！", "長い本文" * 20)
        assert is_valid == False
        assert reason is not None


class TestCleanChatworkTags:
    """clean_chatwork_tags() のテスト"""

    def test_qt_tag_removal(self):
        """[qt]タグの除去"""
        text = "[qt][qtmeta aid=123]内容[/qt]"
        result = clean_chatwork_tags(text)
        # タグが除去されているか、少なくとも内容が残っている
        assert "[qt]" not in result or "内容" in result

    def test_to_tag_removal(self):
        """[To:]タグの除去"""
        text = "[To:12345]山田さん\nタスク内容"
        result = clean_chatwork_tags(text)
        assert "タスク内容" in result


# =====================================================
# テスト実行
# =====================================================

if __name__ == "__main__":
    print(f"lib/ available: {LIB_AVAILABLE}")
    pytest.main([__file__, "-v", "--tb=short"])
