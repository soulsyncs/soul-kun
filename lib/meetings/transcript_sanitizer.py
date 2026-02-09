# lib/meetings/transcript_sanitizer.py
"""
会議文字起こし用PIIサニタイザー

既存の memory_sanitizer.py のパターンを再利用しつつ、
会議固有のPIIパターン（住所、カード番号、社員番号）を追加。
長文対応のためチャンク分割処理を実装（Codex Fix #2）。

設計根拠:
- CLAUDE.md §9-2: PIIは保存しない
- docs/07_phase_c_meetings.md: PII Sanitization Patterns
- memory_sanitizer.py: 既存パターンの再利用

Author: Claude Opus 4.6
Created: 2026-02-10
"""

import re
import logging
from typing import List, Tuple

logger = logging.getLogger(__name__)

# memory_sanitizer.py から再利用するパターン
from lib.brain.memory_sanitizer import MASK_PATTERNS

# =============================================================================
# 会議固有のPIIパターン（docs/07_phase_c_meetings.md 準拠）
# =============================================================================

MEETING_EXTRA_PATTERNS: List[Tuple[re.Pattern, str]] = [
    # クレジットカード番号（phoneパターンより先に適用すること）
    (re.compile(r'(?<![0-9])\d{4}[- ]\d{4}[- ]\d{4}[- ]\d{4}(?![0-9])'), "[CARD]"),
    # 日本の住所（都道府県から始まるパターン）
    (re.compile(
        r'(?:北海道|青森県|岩手県|宮城県|秋田県|山形県|福島県|茨城県|栃木県|群馬県|'
        r'埼玉県|千葉県|東京都|神奈川県|新潟県|富山県|石川県|福井県|山梨県|長野県|'
        r'岐阜県|静岡県|愛知県|三重県|滋賀県|京都府|大阪府|兵庫県|奈良県|和歌山県|'
        r'鳥取県|島根県|岡山県|広島県|山口県|徳島県|香川県|愛媛県|高知県|福岡県|'
        r'佐賀県|長崎県|熊本県|大分県|宮崎県|鹿児島県|沖縄県).{3,30}?'
        r'(?:\d+[-ー]\d+[-ー]?\d*|\d+番地?\d*号?)'
    ), "[ADDRESS]"),
    # 社員番号（英字2-3文字 + ハイフン + 数字4-6桁）
    # \bは日本語文字とASCII間で機能しないため、負の先読み/後読みを使用
    (re.compile(r'(?<![A-Za-z0-9])[A-Z]{2,3}-?\d{4,6}(?![0-9])'), "[EMPLOYEE_ID]"),
    # マイナンバー（12桁: 4桁×3グループ、スペース区切り）
    (re.compile(r'(?<![0-9])\d{4} \d{4} \d{4}(?![0-9])'), "[MY_NUMBER]"),
]

# 全パターン統合（EXTRA を先に適用 → カード番号が電話番号パターンに誤マッチするのを防止）
MEETING_PII_PATTERNS: List[Tuple[re.Pattern, str]] = [
    *MEETING_EXTRA_PATTERNS,
    *MASK_PATTERNS,
]

# =============================================================================
# チャンク分割サニタイザー
# =============================================================================

DEFAULT_CHUNK_SIZE = 1000
DEFAULT_OVERLAP = 50


class TranscriptSanitizer:
    """会議文字起こしテキストのPIIサニタイザー"""

    def __init__(
        self,
        patterns: List[Tuple[re.Pattern, str]] = None,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        overlap: int = DEFAULT_OVERLAP,
    ):
        self.patterns = patterns or MEETING_PII_PATTERNS
        self.chunk_size = chunk_size
        self.overlap = overlap

    def sanitize(self, text: str) -> Tuple[str, int]:
        """
        テキスト全体をサニタイズする。

        短いテキストは直接処理、長いテキストはチャンク分割処理。

        Returns:
            (sanitized_text, pii_count): サニタイズ済みテキストとPII検出数
        """
        if not text:
            return ("", 0)

        if len(text) <= self.chunk_size:
            return self._apply_patterns(text)

        return self._sanitize_chunked(text)

    def _apply_patterns(self, text: str) -> Tuple[str, int]:
        """全パターンを順次適用する"""
        pii_count = 0
        result = text
        for pattern, replacement in self.patterns:
            matches = pattern.findall(result)
            if matches:
                pii_count += len(matches)
                result = pattern.sub(replacement, result)
        return (result, pii_count)

    def _sanitize_chunked(self, text: str) -> Tuple[str, int]:
        """
        チャンク分割サニタイズ。

        テキストをchunk_size単位に分割し、各チャンクにパターンを適用。
        オーバーラップ領域での重複置換を防ぐため、
        非オーバーラップ部分のみを結果に採用する。
        """
        total_pii = 0
        result_parts = []
        pos = 0
        text_len = len(text)

        while pos < text_len:
            # チャンク範囲を決定
            chunk_end = min(pos + self.chunk_size + self.overlap, text_len)
            chunk = text[pos:chunk_end]

            sanitized_chunk, chunk_pii = self._apply_patterns(chunk)
            total_pii += chunk_pii

            if pos + self.chunk_size >= text_len:
                # 最後のチャンク: 全体を採用
                result_parts.append(sanitized_chunk)
            else:
                # 非オーバーラップ部分のみ採用
                # サニタイズで文字数が変わるため、比率で切り出す
                ratio = self.chunk_size / len(chunk)
                cut_pos = int(len(sanitized_chunk) * ratio)
                result_parts.append(sanitized_chunk[:cut_pos])

            pos += self.chunk_size

        return ("".join(result_parts), total_pii)


def sanitize_transcript(text: str, chunk_size: int = DEFAULT_CHUNK_SIZE) -> Tuple[str, int]:
    """
    モジュールレベルのヘルパー関数。

    Args:
        text: サニタイズ対象のテキスト
        chunk_size: チャンクサイズ（デフォルト1000文字）

    Returns:
        (sanitized_text, pii_count)
    """
    sanitizer = TranscriptSanitizer(chunk_size=chunk_size)
    return sanitizer.sanitize(text)
