# lib/meetings/minutes_generator.py
"""
LLM議事録生成器

VTTから抽出したトランスクリプトを、LLMで構造化議事録に変換する。
Brain経由でLLMを使用（Brain bypass禁止: CLAUDE.md S1）。

このクラスはLLMへのプロンプト構築と結果パースのみ行い、
実際のLLM呼び出しはBrainInterface側から注入される。

生成する議事録フォーマット:
- 概要（1-2行）
- 議題一覧
- 決定事項
- アクションアイテム（担当者・期限付き）
- 次回予定

Author: Claude Opus 4.6
Created: 2026-02-10
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

MINUTES_SYSTEM_PROMPT = """あなたは議事録作成の専門家です。
以下の会議トランスクリプトから、構造化された議事録を作成してください。

必ず以下のJSON形式で出力してください:
{
  "summary": "会議の概要（1-2文）",
  "topics": ["議題1", "議題2"],
  "decisions": ["決定事項1", "決定事項2"],
  "action_items": [
    {"task": "内容", "assignee": "担当者名", "deadline": "期限（あれば）"}
  ],
  "next_meeting": "次回予定（あれば）",
  "corrections": ["音声認識の修正箇所（主要なもの3-5件）"]
}

注意:
- 日本語の音声認識エラーは文脈から推測して修正してください
- 専門用語は正しい表記に修正してください
- 個人情報（電話番号、メール等）は含めないでください
- 発言者名はそのまま使用してください"""

MAX_TRANSCRIPT_CHARS = 12000


@dataclass
class MeetingMinutes:
    """構造化された議事録。"""

    summary: str = ""
    topics: List[str] = field(default_factory=list)
    decisions: List[str] = field(default_factory=list)
    action_items: List[Dict[str, str]] = field(default_factory=list)
    next_meeting: str = ""
    corrections: List[str] = field(default_factory=list)
    raw_response: str = ""

    def to_chatwork_message(self, title: Optional[str] = None) -> str:
        """ChatWork投稿用にフォーマット。"""
        meeting_name = title or "会議"
        parts = [f"[info][title]{meeting_name} - 議事録[/title]"]

        if self.summary:
            parts.append(f"\n{self.summary}\n")

        if self.topics:
            parts.append("--- 議題 ---")
            for i, topic in enumerate(self.topics, 1):
                parts.append(f"  {i}. {topic}")
            parts.append("")

        if self.decisions:
            parts.append("--- 決定事項 ---")
            for i, decision in enumerate(self.decisions, 1):
                parts.append(f"  {i}. {decision}")
            parts.append("")

        if self.action_items:
            parts.append("--- アクションアイテム ---")
            for item in self.action_items:
                assignee = item.get("assignee", "未定")
                deadline = item.get("deadline", "")
                deadline_str = f"（期限: {deadline}）" if deadline else ""
                parts.append(
                    f"  - [{assignee}] {item.get('task', '')}{deadline_str}"
                )
            parts.append("")

        if self.next_meeting:
            parts.append(f"--- 次回予定 ---\n  {self.next_meeting}\n")

        parts.append("[/info]")
        return "\n".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        """JSON-serializable dict."""
        return {
            "summary": self.summary,
            "topics": self.topics,
            "decisions": self.decisions,
            "action_items": self.action_items,
            "next_meeting": self.next_meeting,
            "corrections": self.corrections,
        }


def build_minutes_prompt(
    transcript_text: str, meeting_title: Optional[str] = None
) -> str:
    """
    議事録生成用のプロンプトを構築する。

    LLM呼び出し自体はBrainInterface経由で行う（Brain bypass防止）。

    Args:
        transcript_text: サニタイズ済みトランスクリプト
        meeting_title: 会議タイトル（あれば）

    Returns:
        LLMに渡すユーザーメッセージ
    """
    if len(transcript_text) > MAX_TRANSCRIPT_CHARS:
        transcript_text = (
            transcript_text[:MAX_TRANSCRIPT_CHARS] + "\n\n[... 省略 ...]"
        )
        logger.info(
            "Transcript truncated to %d chars for LLM", MAX_TRANSCRIPT_CHARS
        )

    title_line = (
        f"会議タイトル: {meeting_title}\n\n" if meeting_title else ""
    )
    return (
        f"{title_line}"
        f"以下のトランスクリプトから議事録を作成してください:\n\n"
        f"{transcript_text}"
    )


def parse_minutes_response(response_text: str) -> MeetingMinutes:
    """
    LLMの応答をMeetingMinutesにパースする。

    JSONパースを試み、失敗した場合はfreeform textとしてsummaryに格納。

    Args:
        response_text: LLMからの応答テキスト

    Returns:
        MeetingMinutes
    """
    minutes = MeetingMinutes(raw_response=response_text)

    json_str = _extract_json(response_text)
    if json_str:
        try:
            data = json.loads(json_str)
            minutes.summary = data.get("summary", "")
            minutes.topics = data.get("topics", [])
            minutes.decisions = data.get("decisions", [])
            minutes.action_items = data.get("action_items", [])
            minutes.next_meeting = data.get("next_meeting", "")
            minutes.corrections = data.get("corrections", [])
            return minutes
        except json.JSONDecodeError:
            logger.warning("Failed to parse LLM response as JSON")

    # Fallback: use entire response as summary
    minutes.summary = response_text[:2000]
    return minutes


def _extract_json(text: str) -> Optional[str]:
    """Extract JSON object from text that may contain markdown code blocks."""
    # Try: ```json ... ``` pattern
    json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if json_match:
        return json_match.group(1)

    # Try: raw { ... } pattern (balanced braces)
    brace_start = text.find("{")
    if brace_start >= 0:
        brace_count = 0
        for i in range(brace_start, len(text)):
            if text[i] == "{":
                brace_count += 1
            elif text[i] == "}":
                brace_count -= 1
                if brace_count == 0:
                    return text[brace_start : i + 1]

    return None
