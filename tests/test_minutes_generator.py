# tests/test_minutes_generator.py
"""
議事録生成器のユニットテスト

Author: Claude Opus 4.6
"""

import json

import pytest

from lib.meetings.minutes_generator import (
    MeetingMinutes,
    build_minutes_prompt,
    parse_minutes_response,
    _extract_json,
    MAX_TRANSCRIPT_CHARS,
)


class TestBuildMinutesPrompt:
    def test_basic_prompt(self):
        prompt = build_minutes_prompt("トランスクリプト内容")
        assert "トランスクリプト内容" in prompt
        assert "議事録を作成してください" in prompt

    def test_prompt_with_title(self):
        prompt = build_minutes_prompt("内容", meeting_title="定例会議")
        assert "定例会議" in prompt
        assert "内容" in prompt

    def test_prompt_without_title(self):
        prompt = build_minutes_prompt("内容")
        assert "会議タイトル" not in prompt

    def test_truncation(self):
        long_text = "あ" * (MAX_TRANSCRIPT_CHARS + 1000)
        prompt = build_minutes_prompt(long_text)
        assert "省略" in prompt
        assert len(prompt) < len(long_text) + 500


class TestParseMinutesResponse:
    def test_parse_json_response(self):
        response = json.dumps({
            "summary": "プロジェクトの進捗確認会議",
            "topics": ["進捗報告", "課題共有"],
            "decisions": ["来週リリース"],
            "action_items": [
                {"task": "テスト実施", "assignee": "田中", "deadline": "2/15"}
            ],
            "next_meeting": "来週月曜",
            "corrections": ["「しんちょく」→「進捗」"],
        })

        minutes = parse_minutes_response(response)
        assert minutes.summary == "プロジェクトの進捗確認会議"
        assert len(minutes.topics) == 2
        assert len(minutes.decisions) == 1
        assert len(minutes.action_items) == 1
        assert minutes.action_items[0]["assignee"] == "田中"
        assert minutes.next_meeting == "来週月曜"

    def test_parse_json_in_code_block(self):
        response = """以下が議事録です:

```json
{
  "summary": "テスト会議",
  "topics": ["議題A"],
  "decisions": [],
  "action_items": [],
  "next_meeting": "",
  "corrections": []
}
```
"""
        minutes = parse_minutes_response(response)
        assert minutes.summary == "テスト会議"
        assert minutes.topics == ["議題A"]

    def test_parse_fallback_freeform(self):
        response = "これは構造化されていない議事録テキストです。"
        minutes = parse_minutes_response(response)
        assert "構造化されていない" in minutes.summary
        assert minutes.topics == []

    def test_parse_invalid_json(self):
        response = "{invalid json content"
        minutes = parse_minutes_response(response)
        assert minutes.summary != ""  # Falls back to raw text

    def test_raw_response_preserved(self):
        response = '{"summary": "test"}'
        minutes = parse_minutes_response(response)
        assert minutes.raw_response == response


class TestMeetingMinutes:
    def test_to_chatwork_message(self):
        minutes = MeetingMinutes(
            summary="プロジェクト進捗確認",
            topics=["進捗報告", "課題"],
            decisions=["来週リリース"],
            action_items=[
                {"task": "テスト", "assignee": "田中", "deadline": "2/15"}
            ],
            next_meeting="来週月曜",
        )
        msg = minutes.to_chatwork_message("定例会議")
        assert "[info]" in msg
        assert "定例会議 - 議事録" in msg
        assert "プロジェクト進捗確認" in msg
        assert "進捗報告" in msg
        assert "来週リリース" in msg
        assert "[田中]" in msg
        assert "期限: 2/15" in msg
        assert "来週月曜" in msg

    def test_to_chatwork_message_empty_fields(self):
        minutes = MeetingMinutes(summary="概要のみ")
        msg = minutes.to_chatwork_message()
        assert "[info]" in msg
        assert "概要のみ" in msg
        assert "アクションアイテム" not in msg

    def test_to_chatwork_message_default_title(self):
        minutes = MeetingMinutes(summary="test")
        msg = minutes.to_chatwork_message()
        assert "会議 - 議事録" in msg

    def test_to_dict(self):
        minutes = MeetingMinutes(
            summary="s",
            topics=["t"],
            decisions=["d"],
            action_items=[{"task": "a"}],
            next_meeting="n",
            corrections=["c"],
        )
        d = minutes.to_dict()
        assert d["summary"] == "s"
        assert d["topics"] == ["t"]
        assert d["action_items"] == [{"task": "a"}]


class TestExtractJson:
    def test_code_block(self):
        text = '```json\n{"key": "value"}\n```'
        result = _extract_json(text)
        assert result == '{"key": "value"}'

    def test_raw_json(self):
        text = 'Some text {"key": "value"} more text'
        result = _extract_json(text)
        assert result == '{"key": "value"}'

    def test_nested_json(self):
        text = '{"outer": {"inner": "value"}}'
        result = _extract_json(text)
        assert '"inner"' in result

    def test_no_json(self):
        result = _extract_json("plain text without json")
        assert result is None

    def test_code_block_without_json_label(self):
        text = '```\n{"key": "val"}\n```'
        result = _extract_json(text)
        assert result == '{"key": "val"}'
