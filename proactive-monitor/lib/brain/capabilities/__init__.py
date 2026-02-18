"""
lib.brain.capabilities — CapabilityBridgeのハンドラー群

各モジュールがカテゴリ別のハンドラー関数を提供する。
capability_bridge.py はこれらに委譲することで責務を分散する。

モジュール構成:
    generation.py       — 文書・画像・動画・ディープリサーチ
    google_workspace.py — Google Sheets / Google Slides
    feedback.py         — CEOフィードバック
    meeting.py          — 会議文字起こし / Zoom議事録
    connection.py       — DM可能な相手一覧（Connection Query）
"""

from lib.brain.capabilities.connection import handle_connection_query
from lib.brain.capabilities.feedback import handle_feedback_generation
from lib.brain.capabilities.generation import (
    handle_deep_research,
    handle_document_generation,
    handle_image_generation,
    handle_video_generation,
)
from lib.brain.capabilities.google_workspace import (
    handle_create_presentation,
    handle_create_spreadsheet,
    handle_read_presentation,
    handle_read_spreadsheet,
    handle_write_spreadsheet,
)
from lib.brain.capabilities.meeting import (
    handle_meeting_transcription,
    handle_zoom_meeting_minutes,
)

__all__ = [
    # generation
    "handle_document_generation",
    "handle_image_generation",
    "handle_video_generation",
    "handle_deep_research",
    # google_workspace
    "handle_read_spreadsheet",
    "handle_write_spreadsheet",
    "handle_create_spreadsheet",
    "handle_read_presentation",
    "handle_create_presentation",
    # feedback
    "handle_feedback_generation",
    # meeting
    "handle_meeting_transcription",
    "handle_zoom_meeting_minutes",
    # connection
    "handle_connection_query",
]
