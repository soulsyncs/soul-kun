# lib/capabilities/generation/constants.py
"""
Phase G1: 文書生成能力 - 定数定義

このモジュールは、文書生成に関する定数を定義します。

設計書: docs/20_next_generation_capabilities.md セクション6
Author: Claude Opus 4.5
Created: 2026-01-27
"""

from enum import Enum
from typing import FrozenSet, Dict, Optional


# =============================================================================
# 列挙型
# =============================================================================


class GenerationType(str, Enum):
    """生成タイプ"""
    DOCUMENT = "document"         # 文書（報告書、提案書）
    IMAGE = "image"               # 画像
    RESEARCH = "research"         # リサーチレポート
    VIDEO = "video"               # 動画
    AUDIO = "audio"               # 音声（TTS）
    SPREADSHEET = "spreadsheet"   # スプレッドシート
    PRESENTATION = "presentation" # プレゼン資料


class DocumentType(str, Enum):
    """文書タイプ"""
    # ビジネス文書
    PROPOSAL = "proposal"             # 提案書
    REPORT = "report"                 # 報告書
    MINUTES = "minutes"               # 議事録
    SUMMARY = "summary"               # サマリー・要約
    MANUAL = "manual"                 # マニュアル
    PROCEDURE = "procedure"           # 手順書
    SPECIFICATION = "specification"   # 仕様書
    CONTRACT = "contract"             # 契約書
    QUOTATION = "quotation"           # 見積書
    INVOICE = "invoice"               # 請求書
    LETTER = "letter"                 # ビジネスレター

    # 社内文書
    MEMO = "memo"                     # メモ・連絡事項
    ANNOUNCEMENT = "announcement"     # お知らせ
    GUIDELINE = "guideline"           # ガイドライン
    FAQ = "faq"                       # FAQ

    # その他
    CUSTOM = "custom"                 # カスタム
    UNKNOWN = "unknown"               # 不明


class GenerationStatus(str, Enum):
    """生成ステータス"""
    PENDING = "pending"               # 保留中（確認待ち）
    GATHERING_INFO = "gathering_info" # 情報収集中
    GENERATING = "generating"         # 生成中
    REVIEWING = "reviewing"           # レビュー中
    COMPLETED = "completed"           # 完了
    FAILED = "failed"                 # 失敗
    CANCELLED = "cancelled"           # キャンセル


class OutputFormat(str, Enum):
    """出力フォーマット"""
    GOOGLE_DOCS = "google_docs"       # Google Docs
    GOOGLE_SHEETS = "google_sheets"   # Google Sheets
    GOOGLE_SLIDES = "google_slides"   # Google Slides
    PDF = "pdf"                       # PDF
    MARKDOWN = "markdown"             # Markdown
    HTML = "html"                     # HTML
    PLAIN_TEXT = "plain_text"         # プレーンテキスト
    JSON = "json"                     # JSON


class SectionType(str, Enum):
    """文書セクションタイプ"""
    TITLE = "title"                   # タイトル
    SUBTITLE = "subtitle"             # サブタイトル
    HEADING1 = "heading1"             # 見出し1
    HEADING2 = "heading2"             # 見出し2
    HEADING3 = "heading3"             # 見出し3
    PARAGRAPH = "paragraph"           # 段落
    BULLET_LIST = "bullet_list"       # 箇条書き
    NUMBERED_LIST = "numbered_list"   # 番号付きリスト
    TABLE = "table"                   # 表
    IMAGE = "image"                   # 画像
    QUOTE = "quote"                   # 引用
    CODE = "code"                     # コードブロック
    DIVIDER = "divider"               # 区切り線
    PAGE_BREAK = "page_break"         # ページ区切り


class ConfirmationLevel(str, Enum):
    """確認レベル"""
    NONE = "none"                     # 確認なし
    OUTLINE_ONLY = "outline_only"     # アウトラインのみ確認
    FULL_DRAFT = "full_draft"         # 全文ドラフト確認
    SECTION_BY_SECTION = "section_by_section"  # セクションごと確認


class QualityLevel(str, Enum):
    """品質レベル"""
    DRAFT = "draft"                   # ドラフト（速度重視）
    STANDARD = "standard"             # 標準
    HIGH_QUALITY = "high_quality"     # 高品質（品質重視）
    PREMIUM = "premium"               # プレミアム（最高品質）


class ToneStyle(str, Enum):
    """文体・トーン"""
    FORMAL = "formal"                 # フォーマル
    SEMI_FORMAL = "semi_formal"       # セミフォーマル
    CASUAL = "casual"                 # カジュアル
    FRIENDLY = "friendly"             # フレンドリー
    PROFESSIONAL = "professional"     # プロフェッショナル
    ACADEMIC = "academic"             # アカデミック
    TECHNICAL = "technical"           # テクニカル


# =============================================================================
# サポートフォーマット
# =============================================================================


SUPPORTED_DOCUMENT_TYPES: FrozenSet[str] = frozenset([
    doc_type.value for doc_type in DocumentType
])

SUPPORTED_OUTPUT_FORMATS: FrozenSet[str] = frozenset([
    output_format.value for output_format in OutputFormat
])


# =============================================================================
# サイズ制限
# =============================================================================


# 文書サイズ制限
MAX_DOCUMENT_SECTIONS: int = 50              # 最大セクション数
MAX_SECTION_LENGTH: int = 10000              # セクションあたりの最大文字数
MAX_DOCUMENT_LENGTH: int = 200000            # 文書全体の最大文字数
MAX_TITLE_LENGTH: int = 200                  # タイトルの最大文字数
MAX_OUTLINE_ITEMS: int = 20                  # アウトラインの最大項目数

# 入力制限
MAX_REQUEST_CONTEXT_LENGTH: int = 50000      # リクエストコンテキストの最大文字数
MAX_REFERENCE_DOCUMENTS: int = 10            # 参照文書の最大数
MAX_TEMPLATE_SIZE_BYTES: int = 5 * 1024 * 1024  # テンプレートの最大サイズ（5MB）


# =============================================================================
# タイムアウト
# =============================================================================


# 各処理のタイムアウト（秒）
OUTLINE_GENERATION_TIMEOUT: int = 60         # アウトライン生成
SECTION_GENERATION_TIMEOUT: int = 120        # セクション生成
FULL_DOCUMENT_GENERATION_TIMEOUT: int = 600  # 全文生成（10分）
GOOGLE_DOCS_API_TIMEOUT: int = 60            # Google Docs API
INFO_GATHERING_TIMEOUT: int = 120            # 情報収集


# =============================================================================
# LLM設定
# =============================================================================


# デフォルトモデル
DEFAULT_GENERATION_MODEL: str = "claude-sonnet-4-20250514"
HIGH_QUALITY_MODEL: str = "claude-opus-4-5-20251101"
FAST_MODEL: str = "claude-3-5-haiku-20241022"

# 温度設定（タスクタイプ別）
TEMPERATURE_SETTINGS: Dict[str, float] = {
    "outline": 0.5,      # アウトライン生成（やや創造的）
    "content": 0.3,      # コンテンツ生成（やや保守的）
    "summary": 0.2,      # 要約（正確性重視）
    "creative": 0.7,     # クリエイティブ（創造的）
}


# =============================================================================
# Google API設定
# =============================================================================


# Google Docs API
GOOGLE_DOCS_API_VERSION: str = "v1"
GOOGLE_DOCS_SCOPES: FrozenSet[str] = frozenset([
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive.file",
])

# Google Drive API
GOOGLE_DRIVE_API_VERSION: str = "v3"
GOOGLE_DRIVE_SCOPES: FrozenSet[str] = frozenset([
    "https://www.googleapis.com/auth/drive.file",
])


# =============================================================================
# Feature Flag
# =============================================================================


FEATURE_FLAG_NAME: str = "USE_GENERATION"
FEATURE_FLAG_DOCUMENT: str = "USE_GENERATION_DOCUMENT"
FEATURE_FLAG_IMAGE: str = "USE_GENERATION_IMAGE"
FEATURE_FLAG_RESEARCH: str = "USE_GENERATION_RESEARCH"


# =============================================================================
# テンプレート設定
# =============================================================================


# デフォルトテンプレートID（None = テンプレート未使用）
DEFAULT_TEMPLATE_ID: Optional[str] = None

# 文書タイプ別デフォルトセクション構成
DOCUMENT_TYPE_DEFAULT_SECTIONS: Dict[str, list] = {
    DocumentType.PROPOSAL.value: [
        "エグゼクティブサマリー",
        "背景・課題",
        "提案内容",
        "実施スケジュール",
        "費用",
        "期待効果",
        "会社概要",
    ],
    DocumentType.REPORT.value: [
        "概要",
        "目的",
        "実施内容",
        "結果",
        "考察",
        "今後の展望",
    ],
    DocumentType.MINUTES.value: [
        "会議概要",
        "出席者",
        "議題",
        "議論内容",
        "決定事項",
        "アクションアイテム",
        "次回予定",
    ],
    DocumentType.MANUAL.value: [
        "はじめに",
        "目的と対象読者",
        "前提条件",
        "手順",
        "注意事項",
        "トラブルシューティング",
        "参考資料",
    ],
    DocumentType.SPECIFICATION.value: [
        "概要",
        "目的",
        "スコープ",
        "機能要件",
        "非機能要件",
        "制約条件",
        "用語定義",
    ],
}


# =============================================================================
# プロンプトテンプレート
# =============================================================================


OUTLINE_GENERATION_PROMPT: str = """
あなたは優秀な文書作成アシスタントです。
以下の要件に基づいて、文書のアウトライン（構成案）を作成してください。

【文書タイプ】
{document_type}

【タイトル】
{title}

【作成目的】
{purpose}

【参考情報】
{context}

【指示】
{instruction}

【出力形式】
以下のJSON形式で出力してください：
{{
    "sections": [
        {{
            "title": "セクションタイトル",
            "description": "このセクションで書く内容の概要",
            "estimated_length": "想定文字数（例: 500文字）"
        }}
    ],
    "estimated_total_length": "想定総文字数",
    "notes": "作成上の注意点"
}}
"""

SECTION_GENERATION_PROMPT: str = """
あなたは優秀な文書作成アシスタントです。
以下のセクションの内容を作成してください。

【文書タイトル】
{document_title}

【文書タイプ】
{document_type}

【セクションタイトル】
{section_title}

【セクションの目的】
{section_description}

【前後のセクション】
前: {previous_section}
後: {next_section}

【参考情報】
{context}

【トーン・文体】
{tone}

【出力形式】
- Markdown形式で出力してください
- 見出しは「## 」で始めてください（セクションタイトルは含めない）
- 必要に応じて箇条書き、表、引用を使ってください
"""


# =============================================================================
# エラーメッセージ
# =============================================================================


ERROR_MESSAGES: Dict[str, str] = {
    # 検証エラー
    "EMPTY_TITLE": "タイトルが指定されていません。",
    "TITLE_TOO_LONG": "タイトルが長すぎます（最大{max}文字）。",
    "INVALID_DOCUMENT_TYPE": "サポートされていない文書タイプです: {type}",
    "INVALID_OUTPUT_FORMAT": "サポートされていない出力フォーマットです: {format}",
    "TOO_MANY_SECTIONS": "セクション数が多すぎます（最大{max}件）。",

    # 生成エラー
    "OUTLINE_GENERATION_FAILED": "アウトラインの生成に失敗しました。",
    "SECTION_GENERATION_FAILED": "セクション「{section}」の生成に失敗しました。",
    "DOCUMENT_GENERATION_FAILED": "文書の生成に失敗しました。",

    # Google API エラー
    "GOOGLE_AUTH_FAILED": "Google認証に失敗しました。",
    "GOOGLE_DOCS_CREATE_FAILED": "Google Docsの作成に失敗しました。",
    "GOOGLE_DOCS_UPDATE_FAILED": "Google Docsの更新に失敗しました。",
    "GOOGLE_DRIVE_UPLOAD_FAILED": "Google Driveへのアップロードに失敗しました。",

    # タイムアウト
    "OUTLINE_TIMEOUT": "アウトライン生成がタイムアウトしました。",
    "SECTION_TIMEOUT": "セクション生成がタイムアウトしました。",
    "FULL_DOCUMENT_TIMEOUT": "文書生成がタイムアウトしました。",

    # その他
    "FEATURE_DISABLED": "文書生成機能は現在無効です。",
    "TEMPLATE_NOT_FOUND": "テンプレートが見つかりません: {template_id}",
    "INSUFFICIENT_CONTEXT": "文書を生成するための情報が不足しています。",
}


# =============================================================================
# 文書タイプキーワード（自動判定用）
# =============================================================================


DOCUMENT_TYPE_KEYWORDS: Dict[str, list] = {
    DocumentType.PROPOSAL.value: [
        "提案", "プロポーザル", "企画", "ご提案", "提案書",
    ],
    DocumentType.REPORT.value: [
        "報告", "レポート", "報告書", "結果報告", "活動報告",
    ],
    DocumentType.MINUTES.value: [
        "議事録", "会議録", "ミーティング記録", "打ち合わせメモ",
    ],
    DocumentType.SUMMARY.value: [
        "要約", "サマリー", "概要", "まとめ",
    ],
    DocumentType.MANUAL.value: [
        "マニュアル", "手引き", "ハンドブック", "使い方",
    ],
    DocumentType.PROCEDURE.value: [
        "手順書", "操作手順", "作業手順", "フロー",
    ],
    DocumentType.SPECIFICATION.value: [
        "仕様書", "要件定義", "スペック", "機能仕様",
    ],
    DocumentType.CONTRACT.value: [
        "契約書", "契約", "覚書", "同意書",
    ],
    DocumentType.QUOTATION.value: [
        "見積", "見積書", "お見積り", "概算",
    ],
    DocumentType.MEMO.value: [
        "メモ", "連絡", "通知", "お知らせ",
    ],
    DocumentType.GUIDELINE.value: [
        "ガイドライン", "指針", "ルール", "規約",
    ],
    DocumentType.FAQ.value: [
        "FAQ", "よくある質問", "Q&A", "質問集",
    ],
}


# =============================================================================
# コスト設定（参考値）
# =============================================================================


# 1000トークンあたりのコスト（円）
COST_PER_1K_TOKENS: Dict[str, float] = {
    "claude-opus-4-5-20251101": 15.0,       # 入力
    "claude-sonnet-4-20250514": 3.0,        # 入力
    "claude-3-5-haiku-20241022": 0.25,      # 入力
}

# 出力は入力の5倍
OUTPUT_COST_MULTIPLIER: float = 5.0


# =============================================================================
# Phase G2: 画像生成定数
# =============================================================================


class ImageProvider(str, Enum):
    """画像生成プロバイダー"""
    DALLE3 = "dalle3"               # OpenAI DALL-E 3
    DALLE2 = "dalle2"               # OpenAI DALL-E 2
    STABILITY = "stability"         # Stability AI
    MIDJOURNEY = "midjourney"       # Midjourney（将来対応）


class ImageSize(str, Enum):
    """画像サイズ"""
    # DALL-E 3対応サイズ
    SQUARE_1024 = "1024x1024"       # 正方形（標準）
    LANDSCAPE_1792 = "1792x1024"    # 横長
    PORTRAIT_1024 = "1024x1792"     # 縦長

    # DALL-E 2対応サイズ
    SQUARE_256 = "256x256"          # 小
    SQUARE_512 = "512x512"          # 中
    SQUARE_1024_V2 = "1024x1024"    # 大（DALL-E 2）


class ImageQuality(str, Enum):
    """画像品質"""
    STANDARD = "standard"           # 標準品質
    HD = "hd"                       # 高品質（DALL-E 3のみ）


class ImageStyle(str, Enum):
    """画像スタイル"""
    VIVID = "vivid"                 # 鮮やか・ドラマチック
    NATURAL = "natural"             # 自然・リアル
    # カスタムスタイル（プロンプトで調整）
    ANIME = "anime"                 # アニメ風
    PHOTOREALISTIC = "photorealistic"  # 写実的
    ILLUSTRATION = "illustration"   # イラスト風
    MINIMALIST = "minimalist"       # ミニマリスト
    CORPORATE = "corporate"         # ビジネス・企業向け


# -----------------------------------------------------------------------------
# DALL-E API設定
# -----------------------------------------------------------------------------

DALLE_API_URL: str = "https://api.openai.com/v1/images/generations"
DALLE_API_TIMEOUT_SECONDS: int = 120
DALLE_MAX_RETRIES: int = 3
DALLE_RETRY_DELAY_SECONDS: float = 2.0

# デフォルト設定
DEFAULT_IMAGE_PROVIDER: ImageProvider = ImageProvider.DALLE3
DEFAULT_IMAGE_SIZE: ImageSize = ImageSize.SQUARE_1024
DEFAULT_IMAGE_QUALITY: ImageQuality = ImageQuality.STANDARD
DEFAULT_IMAGE_STYLE: ImageStyle = ImageStyle.VIVID
DEFAULT_IMAGE_MODEL: str = "dall-e-3"

# DALL-E 2のモデル名
DALLE2_MODEL: str = "dall-e-2"

# プロバイダー別サポートサイズ
SUPPORTED_SIZES_BY_PROVIDER: Dict[str, FrozenSet[str]] = {
    ImageProvider.DALLE3.value: frozenset([
        ImageSize.SQUARE_1024.value,
        ImageSize.LANDSCAPE_1792.value,
        ImageSize.PORTRAIT_1024.value,
    ]),
    ImageProvider.DALLE2.value: frozenset([
        ImageSize.SQUARE_256.value,
        ImageSize.SQUARE_512.value,
        ImageSize.SQUARE_1024.value,
    ]),
}

# プロバイダー別サポート品質
SUPPORTED_QUALITY_BY_PROVIDER: Dict[str, FrozenSet[str]] = {
    ImageProvider.DALLE3.value: frozenset([
        ImageQuality.STANDARD.value,
        ImageQuality.HD.value,
    ]),
    ImageProvider.DALLE2.value: frozenset([
        ImageQuality.STANDARD.value,
    ]),
}


# -----------------------------------------------------------------------------
# 画像生成制限
# -----------------------------------------------------------------------------

MAX_PROMPT_LENGTH: int = 4000           # プロンプト最大文字数
MAX_IMAGES_PER_REQUEST: int = 1         # 1リクエストあたりの最大生成数（DALL-E 3は1固定）
MAX_IMAGES_PER_DAY_PER_USER: int = 50   # ユーザーあたり日次上限
MAX_IMAGE_FILE_SIZE_BYTES: int = 20 * 1024 * 1024  # 20MB（編集用アップロード時）


# -----------------------------------------------------------------------------
# 画像生成コスト（円、参考値）
# -----------------------------------------------------------------------------

IMAGE_COST_JPY: Dict[str, Dict[str, float]] = {
    # DALL-E 3
    f"{ImageProvider.DALLE3.value}_{ImageQuality.STANDARD.value}_{ImageSize.SQUARE_1024.value}": 6.0,
    f"{ImageProvider.DALLE3.value}_{ImageQuality.STANDARD.value}_{ImageSize.LANDSCAPE_1792.value}": 12.0,
    f"{ImageProvider.DALLE3.value}_{ImageQuality.STANDARD.value}_{ImageSize.PORTRAIT_1024.value}": 12.0,
    f"{ImageProvider.DALLE3.value}_{ImageQuality.HD.value}_{ImageSize.SQUARE_1024.value}": 12.0,
    f"{ImageProvider.DALLE3.value}_{ImageQuality.HD.value}_{ImageSize.LANDSCAPE_1792.value}": 18.0,
    f"{ImageProvider.DALLE3.value}_{ImageQuality.HD.value}_{ImageSize.PORTRAIT_1024.value}": 18.0,

    # DALL-E 2
    f"{ImageProvider.DALLE2.value}_{ImageQuality.STANDARD.value}_{ImageSize.SQUARE_256.value}": 2.4,
    f"{ImageProvider.DALLE2.value}_{ImageQuality.STANDARD.value}_{ImageSize.SQUARE_512.value}": 2.7,
    f"{ImageProvider.DALLE2.value}_{ImageQuality.STANDARD.value}_{ImageSize.SQUARE_1024.value}": 3.0,
}


# -----------------------------------------------------------------------------
# スタイル別プロンプト修飾子
# -----------------------------------------------------------------------------

STYLE_PROMPT_MODIFIERS: Dict[str, str] = {
    ImageStyle.ANIME.value: "anime style, Japanese animation aesthetic, vibrant colors",
    ImageStyle.PHOTOREALISTIC.value: "photorealistic, ultra-detailed, 8k resolution, professional photography",
    ImageStyle.ILLUSTRATION.value: "digital illustration, clean lines, artistic style",
    ImageStyle.MINIMALIST.value: "minimalist design, simple, clean, white space, modern",
    ImageStyle.CORPORATE.value: "professional corporate style, business appropriate, clean and modern",
}


# -----------------------------------------------------------------------------
# 画像生成エラーメッセージ
# -----------------------------------------------------------------------------

IMAGE_ERROR_MESSAGES: Dict[str, str] = {
    # 検証エラー
    "EMPTY_PROMPT": "画像の説明（プロンプト）が指定されていません。",
    "PROMPT_TOO_LONG": "プロンプトが長すぎます（最大{max}文字）。",
    "INVALID_SIZE": "サポートされていない画像サイズです: {size}",
    "INVALID_QUALITY": "サポートされていない画像品質です: {quality}",
    "INVALID_PROVIDER": "サポートされていないプロバイダーです: {provider}",
    "SIZE_NOT_SUPPORTED_BY_PROVIDER": "{provider}は{size}サイズをサポートしていません。",

    # 生成エラー
    "GENERATION_FAILED": "画像の生成に失敗しました。",
    "CONTENT_POLICY_VIOLATION": "コンテンツポリシーに違反するプロンプトです。内容を修正してください。",
    "SAFETY_FILTER_TRIGGERED": "安全フィルターが作動しました。プロンプトを修正してください。",

    # API エラー
    "DALLE_API_ERROR": "DALL-E APIエラー: {error}",
    "DALLE_RATE_LIMIT": "DALL-E APIのレート制限に達しました。しばらく待ってから再試行してください。",
    "DALLE_TIMEOUT": "画像生成がタイムアウトしました。",
    "DALLE_QUOTA_EXCEEDED": "APIクォータを超過しました。",

    # 保存エラー
    "SAVE_FAILED": "画像の保存に失敗しました。",
    "UPLOAD_FAILED": "画像のアップロードに失敗しました。",

    # その他
    "FEATURE_DISABLED": "画像生成機能は現在無効です。",
    "DAILY_LIMIT_EXCEEDED": "本日の画像生成上限（{limit}枚）に達しました。",
}


# -----------------------------------------------------------------------------
# プロンプト最適化用テンプレート
# -----------------------------------------------------------------------------

IMAGE_PROMPT_OPTIMIZATION_TEMPLATE: str = """
あなたは画像生成AIのプロンプトエンジニアです。
ユーザーの要望を、DALL-E 3で最適な結果が得られるプロンプトに変換してください。

【ユーザーの要望】
{user_prompt}

【スタイル指定】
{style}

【追加の指示】
{instruction}

【出力形式】
以下のJSON形式で出力してください：
{{
    "optimized_prompt": "最適化されたプロンプト（英語）",
    "japanese_summary": "生成される画像の日本語説明",
    "warnings": ["注意点があれば"]
}}

【ルール】
- プロンプトは英語で作成（DALL-E 3は英語の方が精度が高い）
- 具体的な描写を含める（構図、色、光、雰囲気）
- 著作権や商標を侵害する表現は避ける
- 人物の顔を特定できる表現は避ける
"""
