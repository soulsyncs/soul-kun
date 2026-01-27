# lib/capabilities/multimodal/constants.py
"""
Phase M1: Multimodal入力能力 - 定数定義

このモジュールは、Multimodal入力処理で使用する全ての定数を定義します。

設計書: docs/20_next_generation_capabilities.md セクション5
Author: Claude Opus 4.5
Created: 2026-01-27
"""

from enum import Enum
from typing import Set, Dict, List, FrozenSet


# =============================================================================
# 列挙型（Enum）
# =============================================================================


class InputType(str, Enum):
    """入力タイプ"""

    IMAGE = "image"       # 画像
    PDF = "pdf"           # PDF
    URL = "url"           # URL
    AUDIO = "audio"       # 音声（Phase M2）
    VIDEO = "video"       # 動画（Phase M3）


class ProcessingStatus(str, Enum):
    """処理ステータス"""

    PENDING = "pending"           # 処理待ち
    PROCESSING = "processing"     # 処理中
    COMPLETED = "completed"       # 完了
    FAILED = "failed"             # 失敗
    PARTIAL = "partial"           # 部分的に成功


class ImageType(str, Enum):
    """画像タイプ"""

    PHOTO = "photo"               # 写真
    SCREENSHOT = "screenshot"     # スクリーンショット
    DOCUMENT = "document"         # 文書画像（領収書、名刺等）
    DIAGRAM = "diagram"           # 図解
    CHART = "chart"               # グラフ・チャート
    UNKNOWN = "unknown"           # 不明


class PDFType(str, Enum):
    """PDFタイプ"""

    TEXT_BASED = "text_based"     # テキストベース（コピー可能）
    SCANNED = "scanned"           # スキャン画像（OCR必要）
    MIXED = "mixed"               # テキストと画像の混合
    ENCRYPTED = "encrypted"       # 暗号化されている


class URLType(str, Enum):
    """URLタイプ"""

    WEBPAGE = "webpage"           # 一般的なWebページ
    NEWS = "news"                 # ニュース記事
    BLOG = "blog"                 # ブログ記事
    DOCUMENT = "document"         # ドキュメント（Notion, Confluence等）
    VIDEO = "video"               # 動画ページ（YouTube等）
    SOCIAL = "social"             # SNS（Twitter, LinkedIn等）
    API = "api"                   # API/JSON
    UNKNOWN = "unknown"           # 不明


class ContentConfidenceLevel(str, Enum):
    """コンテンツ抽出の確信度レベル"""

    VERY_HIGH = "very_high"       # 0.9以上: ほぼ確実
    HIGH = "high"                 # 0.7-0.9: 高い
    MEDIUM = "medium"             # 0.5-0.7: 中程度
    LOW = "low"                   # 0.3-0.5: 低い
    VERY_LOW = "very_low"         # 0.3未満: 非常に低い

    @classmethod
    def from_score(cls, score: float) -> "ContentConfidenceLevel":
        """スコアから確信度レベルを判定"""
        if score >= 0.9:
            return cls.VERY_HIGH
        elif score >= 0.7:
            return cls.HIGH
        elif score >= 0.5:
            return cls.MEDIUM
        elif score >= 0.3:
            return cls.LOW
        else:
            return cls.VERY_LOW


# =============================================================================
# サポートするファイルフォーマット
# =============================================================================


# 画像フォーマット
SUPPORTED_IMAGE_FORMATS: FrozenSet[str] = frozenset([
    "jpg",
    "jpeg",
    "png",
    "gif",
    "webp",
    "bmp",
    "tiff",
    "tif",
])

# PDFフォーマット
SUPPORTED_PDF_FORMATS: FrozenSet[str] = frozenset([
    "pdf",
])

# URLプロトコル
SUPPORTED_URL_PROTOCOLS: FrozenSet[str] = frozenset([
    "http",
    "https",
])


# =============================================================================
# ファイルサイズ制限
# =============================================================================


# 画像の最大ファイルサイズ（バイト）
MAX_IMAGE_SIZE_BYTES: int = 20 * 1024 * 1024  # 20MB

# PDFの最大ファイルサイズ（バイト）
MAX_PDF_SIZE_BYTES: int = 50 * 1024 * 1024  # 50MB

# PDFの最大ページ数
MAX_PDF_PAGES: int = 100

# URLコンテンツの最大サイズ（バイト）
MAX_URL_CONTENT_SIZE_BYTES: int = 10 * 1024 * 1024  # 10MB


# =============================================================================
# タイムアウト設定
# =============================================================================


# Vision API呼び出しのタイムアウト（秒）
VISION_API_TIMEOUT_SECONDS: int = 60

# PDF処理のタイムアウト（秒）
PDF_PROCESSING_TIMEOUT_SECONDS: int = 120

# URL取得のタイムアウト（秒）
URL_FETCH_TIMEOUT_SECONDS: int = 30

# OCR処理のタイムアウト（秒）
OCR_TIMEOUT_SECONDS: int = 90


# =============================================================================
# Vision API モデル設定
# =============================================================================


# Vision API対応モデル（優先度順）
VISION_MODELS: List[Dict[str, str]] = [
    {
        "model_id": "google/gemini-2.0-flash-001",
        "provider": "google",
        "display_name": "Gemini 2.0 Flash",
        "tier": "1",
    },
    {
        "model_id": "openai/gpt-4o",
        "provider": "openai",
        "display_name": "GPT-4o",
        "tier": "2",
    },
    {
        "model_id": "anthropic/claude-3.5-sonnet",
        "provider": "anthropic",
        "display_name": "Claude 3.5 Sonnet",
        "tier": "2",
    },
]

# デフォルトのVisionモデル
DEFAULT_VISION_MODEL: str = "google/gemini-2.0-flash-001"


# =============================================================================
# セキュリティ設定
# =============================================================================


# URLアクセスを禁止するドメイン（セキュリティ）
BLOCKED_DOMAINS: FrozenSet[str] = frozenset([
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "::1",
    "internal",
    "local",
    "intranet",
    "corp",
    "private",
])

# URLアクセスを禁止するIPレンジ（プライベートIP）
BLOCKED_IP_PREFIXES: List[str] = [
    "10.",
    "172.16.", "172.17.", "172.18.", "172.19.",
    "172.20.", "172.21.", "172.22.", "172.23.",
    "172.24.", "172.25.", "172.26.", "172.27.",
    "172.28.", "172.29.", "172.30.", "172.31.",
    "192.168.",
    "169.254.",  # Link-local
]

# 許可するUser-Agent
USER_AGENT: str = "Soulkun/1.0 (Multimodal Processor; +https://soulkun.soulsyncs.co.jp)"


# =============================================================================
# 処理設定
# =============================================================================


# 画像の最大解像度（ピクセル）
MAX_IMAGE_DIMENSION: int = 4096

# PDFのOCR時の解像度（DPI）
PDF_OCR_DPI: int = 300

# URLコンテンツの本文抽出で除外するタグ
HTML_EXCLUDE_TAGS: FrozenSet[str] = frozenset([
    "script",
    "style",
    "noscript",
    "header",
    "footer",
    "nav",
    "aside",
    "advertisement",
    "iframe",
])

# メタデータとして抽出するHTML要素
HTML_METADATA_TAGS: Dict[str, str] = {
    "title": "title",
    "og:title": "meta[property='og:title']",
    "og:description": "meta[property='og:description']",
    "description": "meta[name='description']",
    "author": "meta[name='author']",
    "keywords": "meta[name='keywords']",
    "published_time": "meta[property='article:published_time']",
}


# =============================================================================
# テキスト処理設定
# =============================================================================


# 抽出テキストの最大文字数
MAX_EXTRACTED_TEXT_LENGTH: int = 100000

# 要約の最大文字数
MAX_SUMMARY_LENGTH: int = 2000

# チャンクサイズ（文字数）
CHUNK_SIZE: int = 1000

# チャンクのオーバーラップ（文字数）
CHUNK_OVERLAP: int = 100


# =============================================================================
# エラーメッセージ
# =============================================================================


ERROR_MESSAGES: Dict[str, str] = {
    "invalid_format": "サポートされていないファイル形式ウル",
    "file_too_large": "ファイルが大きすぎるウル（{max_size}MB以下にしてほしいウル）",
    "pdf_too_many_pages": "ページ数が多すぎるウル（{max_pages}ページ以下にしてほしいウル）",
    "url_blocked": "セキュリティ上の理由でアクセスできないURLウル",
    "url_timeout": "URLへのアクセスがタイムアウトしたウル",
    "url_not_found": "URLが見つからないウル（404）",
    "url_forbidden": "URLへのアクセスが禁止されてるウル（403）",
    "processing_failed": "処理中にエラーが発生したウル",
    "vision_api_error": "画像解析APIでエラーが発生したウル",
    "pdf_encrypted": "PDFが暗号化されていて読めないウル",
    "no_content": "コンテンツを抽出できなかったウル",
}


# =============================================================================
# Feature Flag
# =============================================================================


# Multimodal機能のFeature Flag名
FEATURE_FLAG_NAME: str = "USE_MULTIMODAL_INPUT"

# 各サブ機能のFeature Flag
FEATURE_FLAG_IMAGE: str = "USE_MULTIMODAL_IMAGE"
FEATURE_FLAG_PDF: str = "USE_MULTIMODAL_PDF"
FEATURE_FLAG_URL: str = "USE_MULTIMODAL_URL"


# =============================================================================
# ログ設定
# =============================================================================


# 処理ログを保存するか
SAVE_PROCESSING_LOGS: bool = True

# 処理ログの保持期間（日）
PROCESSING_LOG_RETENTION_DAYS: int = 90


# =============================================================================
# Phase M2: 音声入力 - 列挙型
# =============================================================================


class AudioType(str, Enum):
    """音声タイプ"""

    MEETING = "meeting"           # 会議
    INTERVIEW = "interview"       # インタビュー
    LECTURE = "lecture"           # 講義・セミナー
    PHONE_CALL = "phone_call"     # 電話
    VOICE_MEMO = "voice_memo"     # ボイスメモ
    PODCAST = "podcast"           # ポッドキャスト
    DICTATION = "dictation"       # ディクテーション
    UNKNOWN = "unknown"           # 不明


class TranscriptionStatus(str, Enum):
    """文字起こしステータス"""

    PENDING = "pending"           # 待機中
    TRANSCRIBING = "transcribing" # 文字起こし中
    PROCESSING = "processing"     # 処理中
    COMPLETED = "completed"       # 完了
    FAILED = "failed"             # 失敗
    PARTIAL = "partial"           # 部分完了


class SpeakerLabel(str, Enum):
    """話者ラベル"""

    SPEAKER_1 = "speaker_1"
    SPEAKER_2 = "speaker_2"
    SPEAKER_3 = "speaker_3"
    SPEAKER_4 = "speaker_4"
    SPEAKER_5 = "speaker_5"
    SPEAKER_6 = "speaker_6"
    SPEAKER_7 = "speaker_7"
    SPEAKER_8 = "speaker_8"
    SPEAKER_9 = "speaker_9"
    SPEAKER_10 = "speaker_10"
    UNKNOWN = "unknown"

    @classmethod
    def from_index(cls, index: int) -> "SpeakerLabel":
        """インデックスからラベルを取得"""
        if 1 <= index <= 8:
            return cls(f"speaker_{index}")
        return cls.UNKNOWN


# =============================================================================
# Phase M2: 音声入力 - サポートフォーマット
# =============================================================================


# サポートする音声フォーマット
SUPPORTED_AUDIO_FORMATS: FrozenSet[str] = frozenset([
    "mp3",
    "mp4",
    "mpeg",
    "mpga",
    "m4a",
    "wav",
    "webm",
    "ogg",
    "flac",
])

# 音声MIMEタイプ
AUDIO_MIME_TYPES: Dict[str, str] = {
    "mp3": "audio/mpeg",
    "mp4": "audio/mp4",
    "mpeg": "audio/mpeg",
    "mpga": "audio/mpeg",
    "m4a": "audio/mp4",
    "wav": "audio/wav",
    "webm": "audio/webm",
    "ogg": "audio/ogg",
    "flac": "audio/flac",
}


# =============================================================================
# Phase M2: 音声入力 - サイズ・時間制限
# =============================================================================


# 音声の最大ファイルサイズ（バイト）
MAX_AUDIO_SIZE_BYTES: int = 25 * 1024 * 1024  # 25MB

# 音声の最大長さ（秒）
MAX_AUDIO_DURATION_SECONDS: int = 3600 * 2  # 2時間

# 音声の最大長さ（分）
MAX_AUDIO_DURATION_MINUTES: int = 120  # 2時間

# 音声チャンクの長さ（秒）
AUDIO_CHUNK_DURATION_SECONDS: int = 600  # 10分


# =============================================================================
# Phase M2: 音声入力 - タイムアウト
# =============================================================================


# Whisper API呼び出しのタイムアウト（秒）
WHISPER_API_TIMEOUT_SECONDS: int = 300  # 5分

# 音声処理全体のタイムアウト（秒）
AUDIO_PROCESSING_TIMEOUT_SECONDS: int = 600  # 10分


# =============================================================================
# Phase M2: 音声入力 - Whisper API設定
# =============================================================================


# デフォルトのWhisperモデル
DEFAULT_WHISPER_MODEL: str = "whisper-1"

# デフォルトの言語（None = 自動検出）
DEFAULT_WHISPER_LANGUAGE: str = "ja"

# デフォルトのレスポンス形式
DEFAULT_WHISPER_RESPONSE_FORMAT: str = "verbose_json"


# =============================================================================
# Phase M2: 音声入力 - 処理設定
# =============================================================================


# 最大話者数
MAX_SPEAKERS: int = 10

# 要約の最大文字数
MAX_AUDIO_SUMMARY_LENGTH: int = 2000

# 文字起こしの最大文字数
MAX_TRANSCRIPT_LENGTH: int = 100000


# =============================================================================
# Phase M2: 音声入力 - 音声タイプ検出キーワード
# =============================================================================


AUDIO_TYPE_KEYWORDS: Dict[str, List[str]] = {
    AudioType.MEETING.value: [
        "会議", "ミーティング", "定例", "打ち合わせ", "mtg",
    ],
    AudioType.INTERVIEW.value: [
        "インタビュー", "面接", "面談", "取材",
    ],
    AudioType.LECTURE.value: [
        "講義", "セミナー", "研修", "勉強会", "講演",
    ],
    AudioType.PHONE_CALL.value: [
        "電話", "通話", "コール",
    ],
    AudioType.VOICE_MEMO.value: [
        "メモ", "ボイスメモ", "録音",
    ],
    AudioType.PODCAST.value: [
        "ポッドキャスト", "podcast", "ラジオ",
    ],
    AudioType.DICTATION.value: [
        "ディクテーション", "口述", "文字起こし",
    ],
}


# =============================================================================
# Phase M2: 音声入力 - Feature Flag
# =============================================================================


FEATURE_FLAG_AUDIO: str = "USE_MULTIMODAL_AUDIO"
