# tests/test_transcript_sanitizer.py
"""
TranscriptSanitizer のテスト

PIIパターン検出、チャンク分割処理、オーバーラップ、パフォーマンスをテスト。
"""

import time
import pytest

from lib.meetings.transcript_sanitizer import (
    TranscriptSanitizer,
    sanitize_transcript,
    MEETING_PII_PATTERNS,
    MEETING_EXTRA_PATTERNS,
)


class TestBasicPatterns:
    """基本PIIパターンのテスト（memory_sanitizer.pyから継承）"""

    def setup_method(self):
        self.sanitizer = TranscriptSanitizer()

    def test_phone_hyphenated(self):
        text = "田中さんの電話番号は090-1234-5678です"
        result, count = self.sanitizer.sanitize(text)
        assert "[PHONE]" in result
        assert "090-1234-5678" not in result
        assert count >= 1

    def test_phone_no_hyphen(self):
        text = "連絡先は09012345678まで"
        result, count = self.sanitizer.sanitize(text)
        assert "[PHONE]" in result
        assert "09012345678" not in result

    def test_email(self):
        text = "メールはtanaka@example.com宛てに送ってください"
        result, count = self.sanitizer.sanitize(text)
        assert "[EMAIL]" in result
        assert "tanaka@example.com" not in result

    def test_password(self):
        text = "パスワード: mySecret123"
        result, count = self.sanitizer.sanitize(text)
        assert "[PASSWORD]" in result
        assert "mySecret123" not in result

    def test_salary(self):
        text = "月額850000円の契約です"
        result, count = self.sanitizer.sanitize(text)
        assert "[SALARY]" in result

    def test_api_key(self):
        text = "APIキー: sk-abc123xyz"
        result, count = self.sanitizer.sanitize(text)
        assert "[API_KEY]" in result


class TestMeetingExtraPatterns:
    """会議固有PIIパターンのテスト"""

    def setup_method(self):
        self.sanitizer = TranscriptSanitizer()

    def test_credit_card_with_spaces(self):
        text = "カード番号は4111 1111 1111 1111です"
        result, count = self.sanitizer.sanitize(text)
        assert "[CARD]" in result
        assert "4111" not in result

    def test_credit_card_with_hyphens(self):
        text = "支払い: 5500-0000-0000-0004"
        result, count = self.sanitizer.sanitize(text)
        assert "[CARD]" in result

    def test_address(self):
        text = "住所は東京都渋谷区神宮前1-2-3です"
        result, count = self.sanitizer.sanitize(text)
        assert "[ADDRESS]" in result
        assert "渋谷区" not in result

    def test_employee_id(self):
        text = "社員番号はEMP-12345です"
        result, count = self.sanitizer.sanitize(text)
        assert "[EMPLOYEE_ID]" in result
        assert "EMP-12345" not in result

    def test_my_number(self):
        text = "マイナンバーは1234 5678 9012です"
        result, count = self.sanitizer.sanitize(text)
        assert "[MY_NUMBER]" in result


class TestChunkProcessing:
    """チャンク分割処理のテスト"""

    def test_short_text_no_chunking(self):
        """短いテキストはチャンク分割しない"""
        sanitizer = TranscriptSanitizer(chunk_size=1000)
        text = "これは短いテキストです。電話は090-1111-2222です。"
        result, count = sanitizer.sanitize(text)
        assert "[PHONE]" in result
        assert count >= 1

    def test_long_text_chunked(self):
        """長いテキストはチャンク分割で処理"""
        sanitizer = TranscriptSanitizer(chunk_size=100, overlap=20)
        # 200文字以上のテキストにPIIを埋め込む
        filler = "会議の議題について話し合いました。" * 10
        text = f"{filler}電話番号は090-9999-8888です。{filler}"
        result, count = sanitizer.sanitize(text)
        assert "[PHONE]" in result
        assert "090-9999-8888" not in result

    def test_pii_at_chunk_boundary(self):
        """チャンク境界付近のPIIも検出する"""
        sanitizer = TranscriptSanitizer(chunk_size=100, overlap=30)
        # PIIをチャンクの中間に配置し、オーバーラップ内で検出
        text = "A" * 30 + " 090-1234-5678 " + "B" * 100
        result, count = sanitizer.sanitize(text)
        assert "[PHONE]" in result

    def test_multiple_pii_across_chunks(self):
        """複数チャンクにまたがるPIIを全て検出"""
        sanitizer = TranscriptSanitizer(chunk_size=100, overlap=20)
        text = (
            "最初の電話は03-1234-5678で、"
            + "A" * 100
            + "次のメールはtest@example.comです。"
            + "B" * 100
            + "給与は月額500000円です。"
        )
        result, count = sanitizer.sanitize(text)
        assert "[PHONE]" in result
        assert "[EMAIL]" in result
        assert "[SALARY]" in result


class TestEdgeCases:
    """エッジケース"""

    def test_empty_text(self):
        result, count = sanitize_transcript("")
        assert result == ""
        assert count == 0

    def test_none_like_empty(self):
        sanitizer = TranscriptSanitizer()
        result, count = sanitizer.sanitize("")
        assert result == ""
        assert count == 0

    def test_no_pii(self):
        text = "今日の会議では新製品の戦略について話し合いました。"
        result, count = sanitize_transcript(text)
        assert result == text
        assert count == 0

    def test_mixed_japanese_english(self):
        text = "John's email is john@corp.co.jp and 電話は03-1111-2222"
        result, count = sanitize_transcript(text)
        assert "[EMAIL]" in result
        assert "[PHONE]" in result
        assert count >= 2


class TestPerformance:
    """パフォーマンステスト"""

    def test_large_transcript_under_1_second(self):
        """50KBのテキストを1秒以内に処理"""
        # 約50KB（日本語3文字 = ~9バイト × 5500回 ≈ 50KB）
        text = "今日の会議では重要な話をしました。" * 3000
        # PIIを散在させる
        text = text[:5000] + " 090-1111-2222 " + text[5000:10000] + " test@a.com " + text[10000:]

        start = time.time()
        result, count = sanitize_transcript(text)
        elapsed = time.time() - start

        assert elapsed < 1.0, f"Took {elapsed:.2f}s, expected < 1s"
        assert "[PHONE]" in result
        assert "[EMAIL]" in result


class TestModuleLevelFunction:
    """sanitize_transcript() ヘルパー関数のテスト"""

    def test_default_call(self):
        text = "電話: 090-0000-0000、メール: a@b.com"
        result, count = sanitize_transcript(text)
        assert "[PHONE]" in result
        assert "[EMAIL]" in result
        assert count >= 2

    def test_custom_chunk_size(self):
        text = "A" * 200 + " 090-1234-5678 " + "B" * 200
        result, count = sanitize_transcript(text, chunk_size=100)
        assert "[PHONE]" in result
