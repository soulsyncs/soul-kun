# lib/meetings/vtt_parser.py
"""
Zoom WebVTT トランスクリプトパーサー

Zoom built-in transcription が生成する VTT ファイルをパースし、
タイムスタンプ付き発言セグメントに変換する。

VTTフォーマット例:
    WEBVTT

    00:00:01.000 --> 00:00:05.000
    Speaker Name: こんにちは、本日の会議を始めます

Author: Claude Opus 4.6
Created: 2026-02-10
"""

import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)

TIMESTAMP_PATTERN = re.compile(
    r"(\d{2}:\d{2}:\d{2}\.\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}\.\d{3})"
)

SPEAKER_PATTERN = re.compile(r"^(.+?):\s+(.+)$")


@dataclass
class VTTSegment:
    """A single VTT caption segment."""

    start_time: str
    end_time: str
    speaker: Optional[str]
    text: str


@dataclass
class VTTTranscript:
    """Parsed VTT transcript."""

    segments: List[VTTSegment] = field(default_factory=list)

    @property
    def speakers(self) -> List[str]:
        """Unique speakers in order of appearance."""
        seen: set = set()
        result: List[str] = []
        for seg in self.segments:
            if seg.speaker and seg.speaker not in seen:
                seen.add(seg.speaker)
                result.append(seg.speaker)
        return result

    @property
    def full_text(self) -> str:
        """Concatenated full transcript text."""
        return "\n".join(
            f"{seg.speaker}: {seg.text}" if seg.speaker else seg.text
            for seg in self.segments
        )

    @property
    def duration_seconds(self) -> float:
        """Estimated duration from last segment end time."""
        if not self.segments:
            return 0.0
        return _parse_timestamp(self.segments[-1].end_time)

    def to_segments_json(self) -> List[dict]:
        """Convert to JSON-serializable list for DB storage."""
        return [
            {
                "start": seg.start_time,
                "end": seg.end_time,
                "speaker": seg.speaker,
                "text": seg.text,
            }
            for seg in self.segments
        ]

    def to_speakers_json(self) -> List[dict]:
        """Convert speaker info to JSON for DB storage."""
        speaker_counts: dict = {}
        for seg in self.segments:
            if seg.speaker:
                speaker_counts[seg.speaker] = (
                    speaker_counts.get(seg.speaker, 0) + 1
                )
        return [
            {"name": name, "segment_count": count}
            for name, count in speaker_counts.items()
        ]


def parse_vtt(vtt_content: str) -> VTTTranscript:
    """
    Parse a WebVTT file into structured segments.

    Handles:
    - Standard WEBVTT header
    - Timestamp lines with --> separator
    - Speaker identification ("Name: text")
    - Multi-line captions
    - Empty lines between cues
    - Numeric cue identifiers

    Args:
        vtt_content: Raw VTT file content

    Returns:
        VTTTranscript with parsed segments
    """
    if not vtt_content or not vtt_content.strip():
        return VTTTranscript()

    lines = vtt_content.strip().split("\n")
    transcript = VTTTranscript()

    i = 0
    # Skip WEBVTT header and any metadata
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("WEBVTT") or line == "" or line.startswith("NOTE"):
            i += 1
            continue
        break

    # Parse cues
    while i < len(lines):
        line = lines[i].strip()

        # Skip empty lines and cue identifiers (numeric)
        if not line or line.isdigit():
            i += 1
            continue

        # Look for timestamp line
        ts_match = TIMESTAMP_PATTERN.match(line)
        if ts_match:
            start_time = ts_match.group(1)
            end_time = ts_match.group(2)

            # Collect text lines until next empty line or timestamp
            i += 1
            text_parts = []
            while i < len(lines):
                text_line = lines[i].strip()
                if not text_line:
                    i += 1
                    break
                if TIMESTAMP_PATTERN.match(text_line):
                    break
                if text_line.isdigit():
                    i += 1
                    break
                text_parts.append(text_line)
                i += 1

            full_text = " ".join(text_parts)

            # Try to extract speaker
            speaker = None
            speaker_match = SPEAKER_PATTERN.match(full_text)
            if speaker_match:
                speaker = speaker_match.group(1).strip()
                full_text = speaker_match.group(2).strip()

            if full_text:
                transcript.segments.append(
                    VTTSegment(
                        start_time=start_time,
                        end_time=end_time,
                        speaker=speaker,
                        text=full_text,
                    )
                )
        else:
            i += 1

    logger.info(
        "VTT parsed: segments=%d, speakers=%d, duration=%.0fs",
        len(transcript.segments),
        len(transcript.speakers),
        transcript.duration_seconds,
    )
    return transcript


def _parse_timestamp(ts: str) -> float:
    """Convert VTT timestamp to seconds: '01:23:45.678' -> 5025.678"""
    try:
        parts = ts.split(":")
        hours = int(parts[0])
        minutes = int(parts[1])
        sec_parts = parts[2].split(".")
        seconds = int(sec_parts[0])
        millis = int(sec_parts[1]) if len(sec_parts) > 1 else 0
        return hours * 3600 + minutes * 60 + seconds + millis / 1000
    except (ValueError, IndexError):
        return 0.0
