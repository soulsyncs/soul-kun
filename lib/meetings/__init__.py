# lib/meetings/__init__.py
"""
Phase C MVP0: 会議文字起こしモジュール

会議録音の文字起こし・議事録自動生成のコア機能を提供。
Brain（lib/brain/）の内部には依存せず、Tool登録パターンで連携する。
"""

from lib.meetings.transcript_sanitizer import (
    TranscriptSanitizer,
    sanitize_transcript,
    MEETING_PII_PATTERNS,
)
from lib.meetings.meeting_db import MeetingDB
from lib.meetings.consent_manager import ConsentManager
from lib.meetings.retention_manager import RetentionManager
from lib.meetings.meeting_brain_interface import MeetingBrainInterface
from lib.meetings.zoom_api_client import ZoomAPIClient, create_zoom_client_from_secrets
from lib.meetings.vtt_parser import parse_vtt, VTTTranscript, VTTSegment
from lib.meetings.minutes_generator import (
    MeetingMinutes,
    build_minutes_prompt,
    parse_minutes_response,
)
from lib.meetings.zoom_brain_interface import ZoomBrainInterface

__all__ = [
    "TranscriptSanitizer",
    "sanitize_transcript",
    "MEETING_PII_PATTERNS",
    "MeetingDB",
    "ConsentManager",
    "RetentionManager",
    "MeetingBrainInterface",
    "ZoomAPIClient",
    "create_zoom_client_from_secrets",
    "parse_vtt",
    "VTTTranscript",
    "VTTSegment",
    "MeetingMinutes",
    "build_minutes_prompt",
    "parse_minutes_response",
    "ZoomBrainInterface",
]
