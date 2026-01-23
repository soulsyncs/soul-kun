"""
lib/text_utils.py のユニットテスト

v10.17.0: prepare_task_display_text() 追加対応

テスト対象:
1. prepare_task_display_text() - 新規追加関数
2. clean_chatwork_tags() - 既存関数
3. remove_greetings() - 既存関数
4. validate_summary() - 既存関数

実行方法:
    pytest tests/test_text_utils_lib.py -v
"""

import pytest
import sys
import os

# libをインポートパスに追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.text_utils import (
    prepare_task_display_text,
    clean_chatwork_tags,
    remove_greetings,
    validate_summary,
    is_greeting_only,
)


class TestPrepareTaskDisplayText:
    """prepare_task_display_text() のテスト"""

    def test_empty_input_returns_default(self):
        """空入力の場合はデフォルトメッセージを返す"""
        assert prepare_task_display_text("") == "（タスク内容なし）"
        assert prepare_task_display_text(None) == "（タスク内容なし）"

    def test_short_text_unchanged(self):
        """短いテキストはそのまま返す"""
        text = "経費精算書の提出"
        result = prepare_task_display_text(text, max_length=40)
        assert result == text

    def test_truncation_at_period(self):
        """句点で切れる"""
        text = "経費精算書を提出してください。追加の資料も必要です。確認お願いします。"
        result = prepare_task_display_text(text, max_length=25)
        assert result.endswith("。")
        assert len(result) <= 25

    def test_truncation_at_comma(self):
        """読点で切れる"""
        text = "経費精算書を提出し、追加の資料も送付してください"
        result = prepare_task_display_text(text, max_length=15)
        assert len(result) <= 15

    def test_truncation_at_particle(self):
        """助詞で切れる"""
        text = "経費精算書を確認して提出する必要があります"
        result = prepare_task_display_text(text, max_length=20)
        assert len(result) <= 20
        # 助詞（を、に、で、と、が、は、の、へ、も）で終わるか確認
        particles = ['を', 'に', 'で', 'と', 'が', 'は', 'の', 'へ', 'も', '対応']
        assert any(result.endswith(p) for p in particles) or result.endswith("。") or result.endswith("、")

    def test_no_ellipsis(self):
        """途切れインジケータ（...）が出ない"""
        text = "とても長いタスクの説明文がここに入ります。"
        result = prepare_task_display_text(text, max_length=15)
        assert "..." not in result
        assert "…" not in result

    def test_greeting_removal(self):
        """挨拶が除去される"""
        text = "お疲れ様です！経費精算書を提出してください。"
        result = prepare_task_display_text(text)
        assert "お疲れ" not in result
        assert "経費精算" in result

    def test_newline_handling(self):
        """改行がスペースに置換される"""
        text = "経費精算書を\n提出してください"
        result = prepare_task_display_text(text)
        assert "\n" not in result

    def test_real_world_case_1(self):
        """実例1: メンション後の本文"""
        text = "どなたに伺うのが最適なのかわからなかったため、複数のメンションで失礼します。"
        result = prepare_task_display_text(text, max_length=40)
        assert len(result) <= 40
        # 意味のある位置で切れている
        assert not result.endswith("わか")  # 単語の途中で切れない

    def test_real_world_case_2(self):
        """実例2: 有料職業紹介の例"""
        text = "有料職業紹介の申請を行っていたのですが、本日無事に受付されました！（決算書の"
        result = prepare_task_display_text(text, max_length=40)
        assert len(result) <= 40
        assert not result.endswith("（")  # 括弧の途中で切れない

    def test_fallback_with_action_word(self):
        """最終手段: 動作語で終わる"""
        text = "あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほ"  # 句読点なし
        result = prepare_task_display_text(text, max_length=20)
        assert len(result) <= 20


class TestCleanChatworkTags:
    """clean_chatwork_tags() のテスト"""

    def test_remove_to_tag(self):
        """[To:xxx]タグが除去される"""
        text = "[To:12345]菊地さん お疲れ様です"
        result = clean_chatwork_tags(text)
        assert "[To:" not in result

    def test_remove_qt_tag(self):
        """[qt]...[/qt]タグが除去される"""
        text = "[qt][qtmeta aid=123 time=1234567890]引用内容[/qt]本文"
        result = clean_chatwork_tags(text)
        assert "[qt]" not in result
        assert "[/qt]" not in result

    def test_preserve_content(self):
        """[info]タグは除去するが内容は残す"""
        text = "[info]重要なお知らせ[/info]"
        result = clean_chatwork_tags(text)
        assert "[info]" not in result
        assert "重要なお知らせ" in result


class TestRemoveGreetings:
    """remove_greetings() のテスト"""

    def test_remove_otsukare(self):
        """「お疲れ様です」が除去される"""
        text = "お疲れ様です！経費精算書を提出してください。"
        result = remove_greetings(text)
        assert "お疲れ" not in result
        assert "経費精算" in result

    def test_remove_osewa(self):
        """「いつもお世話になっております」が除去される"""
        text = "いつもお世話になっております。資料を送付します。"
        result = remove_greetings(text)
        assert "お世話" not in result
        assert "資料" in result

    def test_remove_yoroshiku(self):
        """「よろしくお願いします」が除去される"""
        text = "資料を確認してください。よろしくお願いします。"
        result = remove_greetings(text)
        assert "よろしく" not in result
        assert "資料を確認" in result


class TestValidateSummary:
    """validate_summary() のテスト"""

    def test_valid_summary(self):
        """有効な要約"""
        assert validate_summary("経費精算書の提出依頼", "長い本文...") is True

    def test_invalid_greeting_only(self):
        """挨拶のみは無効"""
        assert validate_summary("お疲れ様です！", "長い本文...") is False

    def test_invalid_too_short(self):
        """短すぎるのは無効（元本文が長い場合）"""
        assert validate_summary("資料", "とても長い本文がここに入ります" * 10) is False

    def test_invalid_truncated(self):
        """途中で途切れているのは無効"""
        assert validate_summary("経費精算書を...", "長い本文...") is False


class TestIsGreetingOnly:
    """is_greeting_only() のテスト"""

    def test_greeting_only_true(self):
        """挨拶のみの場合はTrue"""
        assert is_greeting_only("お疲れ様です！") is True
        assert is_greeting_only("いつもお世話になっております。") is True

    def test_greeting_only_false(self):
        """内容がある場合はFalse"""
        assert is_greeting_only("お疲れ様です！経費精算書を提出してください。") is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
