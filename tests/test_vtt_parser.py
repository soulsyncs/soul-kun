# tests/test_vtt_parser.py
"""
VTTパーサーのユニットテスト

Author: Claude Opus 4.6
"""

import pytest

from lib.meetings.vtt_parser import (
    VTTSegment,
    VTTTranscript,
    parse_vtt,
    _parse_timestamp,
)


class TestParseVtt:
    def test_basic_vtt_with_speakers(self):
        vtt = """WEBVTT

00:00:01.000 --> 00:00:05.000
田中太郎: こんにちは、本日の会議を始めます

00:00:05.000 --> 00:00:10.000
山田花子: はい、よろしくお願いします
"""
        result = parse_vtt(vtt)
        assert len(result.segments) == 2
        assert result.segments[0].speaker == "田中太郎"
        assert result.segments[0].text == "こんにちは、本日の会議を始めます"
        assert result.segments[1].speaker == "山田花子"

    def test_vtt_without_speakers(self):
        vtt = """WEBVTT

00:00:01.000 --> 00:00:05.000
Hello world

00:00:05.000 --> 00:00:10.000
Testing one two three
"""
        result = parse_vtt(vtt)
        assert len(result.segments) == 2
        assert result.segments[0].speaker is None
        assert result.segments[0].text == "Hello world"

    def test_vtt_with_cue_identifiers(self):
        vtt = """WEBVTT

1
00:00:01.000 --> 00:00:05.000
First segment

2
00:00:05.000 --> 00:00:10.000
Second segment
"""
        result = parse_vtt(vtt)
        assert len(result.segments) == 2
        assert result.segments[0].text == "First segment"
        assert result.segments[1].text == "Second segment"

    def test_empty_vtt(self):
        result = parse_vtt("")
        assert len(result.segments) == 0

    def test_none_vtt(self):
        result = parse_vtt(None)
        assert len(result.segments) == 0

    def test_whitespace_only(self):
        result = parse_vtt("   \n\n  ")
        assert len(result.segments) == 0

    def test_multiline_captions(self):
        vtt = """WEBVTT

00:00:01.000 --> 00:00:05.000
This is line one
and this is line two
"""
        result = parse_vtt(vtt)
        assert len(result.segments) == 1
        assert "line one" in result.segments[0].text
        assert "line two" in result.segments[0].text

    def test_japanese_content(self):
        vtt = """WEBVTT

00:00:00.000 --> 00:01:30.500
菊池: 今日のアジェンダは3つあります

00:01:30.500 --> 00:03:00.000
橋本: 了解しました
"""
        result = parse_vtt(vtt)
        assert len(result.segments) == 2
        assert result.segments[0].speaker == "菊池"
        assert "アジェンダ" in result.segments[0].text

    def test_header_with_metadata(self):
        vtt = """WEBVTT
Kind: captions
Language: ja

NOTE This is a comment

00:00:01.000 --> 00:00:05.000
テスト発言
"""
        result = parse_vtt(vtt)
        assert len(result.segments) == 1
        assert result.segments[0].text == "テスト発言"


class TestVTTTranscriptProperties:
    def test_speakers_unique_ordered(self):
        t = VTTTranscript(
            segments=[
                VTTSegment("00:00:01.000", "00:00:02.000", "Alice", "Hi"),
                VTTSegment("00:00:02.000", "00:00:03.000", "Bob", "Hello"),
                VTTSegment("00:00:03.000", "00:00:04.000", "Alice", "Bye"),
            ]
        )
        assert t.speakers == ["Alice", "Bob"]

    def test_speakers_empty(self):
        t = VTTTranscript(
            segments=[
                VTTSegment("00:00:01.000", "00:00:02.000", None, "text"),
            ]
        )
        assert t.speakers == []

    def test_full_text_with_speakers(self):
        t = VTTTranscript(
            segments=[
                VTTSegment("00:00:01.000", "00:00:02.000", "A", "hello"),
                VTTSegment("00:00:02.000", "00:00:03.000", None, "world"),
            ]
        )
        assert t.full_text == "A: hello\nworld"

    def test_duration_seconds(self):
        t = VTTTranscript(
            segments=[
                VTTSegment("00:00:01.000", "01:30:45.500", "A", "long meeting"),
            ]
        )
        assert t.duration_seconds == pytest.approx(5445.5)

    def test_duration_seconds_empty(self):
        t = VTTTranscript()
        assert t.duration_seconds == 0.0

    def test_to_segments_json(self):
        t = VTTTranscript(
            segments=[
                VTTSegment("00:00:01.000", "00:00:05.000", "Bob", "text"),
            ]
        )
        result = t.to_segments_json()
        assert len(result) == 1
        assert result[0]["speaker"] == "Bob"
        assert result[0]["start"] == "00:00:01.000"

    def test_to_speakers_json(self):
        t = VTTTranscript(
            segments=[
                VTTSegment("", "", "Alice", "1"),
                VTTSegment("", "", "Bob", "2"),
                VTTSegment("", "", "Alice", "3"),
            ]
        )
        result = t.to_speakers_json()
        alice = next(s for s in result if s["name"] == "Alice")
        bob = next(s for s in result if s["name"] == "Bob")
        assert alice["segment_count"] == 2
        assert bob["segment_count"] == 1


class TestParseTimestamp:
    def test_standard_timestamp(self):
        assert _parse_timestamp("01:23:45.678") == pytest.approx(5025.678)

    def test_zero_timestamp(self):
        assert _parse_timestamp("00:00:00.000") == 0.0

    def test_hours_only(self):
        assert _parse_timestamp("02:00:00.000") == pytest.approx(7200.0)

    def test_invalid_timestamp(self):
        assert _parse_timestamp("invalid") == 0.0

    def test_empty_timestamp(self):
        assert _parse_timestamp("") == 0.0
