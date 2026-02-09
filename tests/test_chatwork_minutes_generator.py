# tests/test_chatwork_minutes_generator.py
"""
ChatWork議事録生成のユニットテスト（Phase C MVP1）

ChatWork専用プロンプト、プレーンテキスト出力、[info]タグフォーマットをテスト。
Zoom用（test_minutes_generator.py）とは分離。

Author: Claude Opus 4.6
"""

import pytest

from lib.meetings.minutes_generator import (
    CHATWORK_MINUTES_SYSTEM_PROMPT,
    build_chatwork_minutes_prompt,
    format_chatwork_minutes,
    MAX_TRANSCRIPT_CHARS,
)


class TestChatworkMinutesSystemPrompt:
    """ChatWork用システムプロンプトの構造検証"""

    def test_contains_lecture_style_rule(self):
        assert "講義" in CHATWORK_MINUTES_SYSTEM_PROMPT

    def test_contains_section_format(self):
        assert "■主題" in CHATWORK_MINUTES_SYSTEM_PROMPT

    def test_contains_task_list_section(self):
        assert "タスク一覧" in CHATWORK_MINUTES_SYSTEM_PROMPT

    def test_contains_pii_rule(self):
        assert "個人情報" in CHATWORK_MINUTES_SYSTEM_PROMPT

    def test_contains_plain_text_rule(self):
        assert "プレーンテキスト" in CHATWORK_MINUTES_SYSTEM_PROMPT

    def test_contains_timestamp_format(self):
        assert "00:00" in CHATWORK_MINUTES_SYSTEM_PROMPT

    def test_contains_background_rule(self):
        assert "背景" in CHATWORK_MINUTES_SYSTEM_PROMPT

    def test_no_markdown_rule(self):
        assert "Markdown" in CHATWORK_MINUTES_SYSTEM_PROMPT


class TestBuildChatworkMinutesPrompt:
    def test_basic_prompt(self):
        prompt = build_chatwork_minutes_prompt("テスト書き起こし")
        assert "テスト書き起こし" in prompt
        assert "議事録にしてください" in prompt

    def test_prompt_with_title(self):
        prompt = build_chatwork_minutes_prompt("内容", meeting_title="朝会")
        assert "朝会" in prompt
        assert "内容" in prompt

    def test_prompt_without_title(self):
        prompt = build_chatwork_minutes_prompt("内容")
        assert "会議タイトル" not in prompt

    def test_truncation(self):
        long_text = "あ" * (MAX_TRANSCRIPT_CHARS + 1000)
        prompt = build_chatwork_minutes_prompt(long_text)
        assert "省略" in prompt

    def test_does_not_truncate_short_text(self):
        short_text = "短いテキスト"
        prompt = build_chatwork_minutes_prompt(short_text)
        assert "省略" not in prompt


class TestFormatChatworkMinutes:
    def test_wraps_in_info_tags(self):
        result = format_chatwork_minutes("議事録内容", title="定例会議")
        assert result.startswith("[info][title]定例会議 - 議事録[/title]")
        assert result.endswith("[/info]")

    def test_default_title(self):
        result = format_chatwork_minutes("内容")
        assert "会議 - 議事録" in result

    def test_preserves_content(self):
        content = "■ 主題1（00:00〜）\nここでは重要な議論がありました。"
        result = format_chatwork_minutes(content, title="テスト")
        assert "■ 主題1（00:00〜）" in result
        assert "重要な議論" in result

    def test_strips_whitespace(self):
        result = format_chatwork_minutes("  内容  \n\n", title="会議")
        assert "  内容  " not in result
        assert "内容" in result

    def test_multiline_content(self):
        content = "■ 主題1（序盤〜）\n詳細内容\n\n■ タスク一覧\n- [ ] 担当者: タスク"
        result = format_chatwork_minutes(content)
        assert "■ 主題1（序盤〜）" in result
        assert "■ タスク一覧" in result
        assert "- [ ] 担当者: タスク" in result
