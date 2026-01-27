# lib/capabilities/multimodal/models.py
"""
Phase M1: Multimodal入力能力 - データモデル

このモジュールは、Multimodal入力処理で使用するデータモデルを定義します。

設計書: docs/20_next_generation_capabilities.md セクション5
Author: Claude Opus 4.5
Created: 2026-01-27
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import UUID

from .constants import (
    InputType,
    ProcessingStatus,
    ImageType,
    PDFType,
    URLType,
    AudioType,
    TranscriptionStatus,
    SpeakerLabel,
    ContentConfidenceLevel,
)


# =============================================================================
# 共通モデル
# =============================================================================


@dataclass
class ProcessingMetadata:
    """
    処理メタデータ

    全ての処理結果に共通するメタ情報。
    """

    # 識別情報
    processing_id: Optional[str] = None
    organization_id: str = ""

    # タイミング
    started_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    processing_time_ms: int = 0

    # 処理情報
    input_type: InputType = InputType.IMAGE
    status: ProcessingStatus = ProcessingStatus.PENDING
    model_used: Optional[str] = None
    model_provider: Optional[str] = None

    # コスト情報
    api_calls_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_jpy: float = 0.0

    # エラー情報
    error_message: Optional[str] = None
    error_code: Optional[str] = None

    @property
    def is_successful(self) -> bool:
        """処理が成功したか"""
        return self.status == ProcessingStatus.COMPLETED

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式で返す"""
        return {
            "processing_id": self.processing_id,
            "organization_id": self.organization_id,
            "input_type": self.input_type.value,
            "status": self.status.value,
            "processing_time_ms": self.processing_time_ms,
            "model_used": self.model_used,
            "api_calls_count": self.api_calls_count,
            "estimated_cost_jpy": self.estimated_cost_jpy,
            "error_message": self.error_message,
        }


@dataclass
class ExtractedEntity:
    """
    抽出されたエンティティ

    画像やテキストから抽出された固有表現。
    """

    entity_type: str           # person, organization, date, amount, location, etc.
    value: str                 # 抽出された値
    confidence: float = 1.0    # 確信度（0.0-1.0）
    start_position: Optional[int] = None  # テキスト内の開始位置
    end_position: Optional[int] = None    # テキスト内の終了位置
    context: Optional[str] = None         # 周辺コンテキスト

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式で返す"""
        result = {
            "entity_type": self.entity_type,
            "value": self.value,
            "confidence": self.confidence,
        }
        if self.context:
            result["context"] = self.context
        return result


# =============================================================================
# 画像処理モデル
# =============================================================================


@dataclass
class ImageMetadata:
    """
    画像メタデータ

    画像ファイルの基本情報。
    """

    width: int = 0
    height: int = 0
    format: str = ""           # jpg, png, etc.
    file_size_bytes: int = 0
    color_mode: str = ""       # RGB, RGBA, L, etc.
    has_transparency: bool = False
    dpi: Optional[tuple] = None
    exif_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ImageAnalysisResult:
    """
    画像解析結果

    Vision APIによる画像解析の結果。
    """

    # 成功/失敗
    success: bool = True

    # 基本情報
    image_type: ImageType = ImageType.UNKNOWN
    description: str = ""      # 画像の説明

    # 抽出テキスト（OCR）
    extracted_text: Optional[str] = None
    text_confidence: float = 0.0

    # 抽出エンティティ
    entities: List[ExtractedEntity] = field(default_factory=list)

    # 構造化データ（領収書、名刺等の場合）
    structured_data: Dict[str, Any] = field(default_factory=dict)

    # 画像メタデータ
    image_metadata: Optional[ImageMetadata] = None

    # 確信度
    overall_confidence: float = 0.0
    confidence_level: ContentConfidenceLevel = ContentConfidenceLevel.MEDIUM

    # 処理メタデータ
    metadata: ProcessingMetadata = field(default_factory=ProcessingMetadata)

    # ソウルくん向けサマリー
    summary_for_user: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式で返す"""
        return {
            "success": self.success,
            "image_type": self.image_type.value,
            "description": self.description,
            "extracted_text": self.extracted_text,
            "text_confidence": self.text_confidence,
            "entities": [e.to_dict() for e in self.entities],
            "structured_data": self.structured_data,
            "overall_confidence": self.overall_confidence,
            "confidence_level": self.confidence_level.value,
            "summary_for_user": self.summary_for_user,
            "metadata": self.metadata.to_dict(),
        }

    def to_brain_context(self) -> str:
        """
        脳のコンテキスト用文字列を生成

        BrainContextに渡す形式。
        """
        parts = [f"【画像解析結果】（{self.image_type.value}）"]

        if self.description:
            parts.append(f"内容: {self.description}")

        if self.extracted_text:
            text_preview = self.extracted_text[:200]
            if len(self.extracted_text) > 200:
                text_preview += "..."
            parts.append(f"テキスト: {text_preview}")

        if self.entities:
            entity_strs = [f"{e.entity_type}: {e.value}" for e in self.entities[:5]]
            parts.append(f"検出項目: {', '.join(entity_strs)}")

        if self.structured_data:
            # 構造化データの主要項目
            for key, value in list(self.structured_data.items())[:5]:
                parts.append(f"  {key}: {value}")

        return "\n".join(parts)


# =============================================================================
# PDF処理モデル
# =============================================================================


@dataclass
class PDFPageContent:
    """
    PDFページコンテンツ

    PDFの各ページから抽出された内容。
    """

    page_number: int
    text: str = ""
    has_images: bool = False
    image_count: int = 0
    ocr_used: bool = False
    ocr_confidence: float = 0.0

    # 構造情報
    headings: List[str] = field(default_factory=list)
    tables: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式で返す"""
        return {
            "page_number": self.page_number,
            "text_length": len(self.text),
            "has_images": self.has_images,
            "image_count": self.image_count,
            "ocr_used": self.ocr_used,
            "headings": self.headings,
        }


@dataclass
class PDFMetadata:
    """
    PDFメタデータ

    PDFファイルの基本情報。
    """

    title: Optional[str] = None
    author: Optional[str] = None
    subject: Optional[str] = None
    creator: Optional[str] = None
    producer: Optional[str] = None
    creation_date: Optional[datetime] = None
    modification_date: Optional[datetime] = None
    page_count: int = 0
    file_size_bytes: int = 0
    is_encrypted: bool = False
    pdf_version: Optional[str] = None


@dataclass
class PDFAnalysisResult:
    """
    PDF解析結果

    PDFの解析結果。
    """

    # 成功/失敗
    success: bool = True

    # 基本情報
    pdf_type: PDFType = PDFType.TEXT_BASED
    pdf_metadata: PDFMetadata = field(default_factory=PDFMetadata)

    # 抽出テキスト
    full_text: str = ""
    pages: List[PDFPageContent] = field(default_factory=list)

    # 構造情報
    table_of_contents: List[Dict[str, Any]] = field(default_factory=list)
    all_headings: List[str] = field(default_factory=list)
    all_tables: List[Dict[str, Any]] = field(default_factory=list)

    # 抽出エンティティ
    entities: List[ExtractedEntity] = field(default_factory=list)

    # 要約
    summary: str = ""
    key_points: List[str] = field(default_factory=list)

    # 確信度
    overall_confidence: float = 0.0
    confidence_level: ContentConfidenceLevel = ContentConfidenceLevel.MEDIUM

    # 処理メタデータ
    metadata: ProcessingMetadata = field(default_factory=ProcessingMetadata)

    # ナレッジDBへの保存
    saved_to_knowledge: bool = False
    knowledge_document_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式で返す"""
        return {
            "success": self.success,
            "pdf_type": self.pdf_type.value,
            "page_count": self.pdf_metadata.page_count,
            "title": self.pdf_metadata.title,
            "full_text_length": len(self.full_text),
            "summary": self.summary,
            "key_points": self.key_points,
            "entities": [e.to_dict() for e in self.entities],
            "overall_confidence": self.overall_confidence,
            "confidence_level": self.confidence_level.value,
            "saved_to_knowledge": self.saved_to_knowledge,
            "metadata": self.metadata.to_dict(),
        }

    def to_brain_context(self) -> str:
        """脳のコンテキスト用文字列を生成"""
        parts = [f"【PDF解析結果】{self.pdf_metadata.page_count}ページ"]

        if self.pdf_metadata.title:
            parts.append(f"タイトル: {self.pdf_metadata.title}")

        if self.summary:
            parts.append(f"要約: {self.summary}")

        if self.key_points:
            parts.append("重要ポイント:")
            for point in self.key_points[:5]:
                parts.append(f"  - {point}")

        if self.entities:
            entity_strs = [f"{e.entity_type}: {e.value}" for e in self.entities[:5]]
            parts.append(f"検出項目: {', '.join(entity_strs)}")

        return "\n".join(parts)


# =============================================================================
# URL処理モデル
# =============================================================================


@dataclass
class URLMetadata:
    """
    URLメタデータ

    URLページの基本情報。
    """

    url: str = ""
    final_url: str = ""        # リダイレクト後のURL
    domain: str = ""
    title: Optional[str] = None
    description: Optional[str] = None
    author: Optional[str] = None
    published_time: Optional[datetime] = None
    language: Optional[str] = None
    content_type: Optional[str] = None
    content_length: Optional[int] = None
    status_code: int = 200
    redirected: bool = False
    redirect_count: int = 0


@dataclass
class URLAnalysisResult:
    """
    URL解析結果

    URLの解析結果。
    """

    # 成功/失敗
    success: bool = True

    # 基本情報
    url_type: URLType = URLType.WEBPAGE
    url_metadata: URLMetadata = field(default_factory=URLMetadata)

    # 抽出コンテンツ
    main_content: str = ""     # 本文
    raw_html: Optional[str] = None  # 生HTML（オプション）

    # 構造情報
    headings: List[str] = field(default_factory=list)
    links: List[Dict[str, str]] = field(default_factory=list)  # [{"text": "...", "href": "..."}]
    images: List[Dict[str, str]] = field(default_factory=list)  # [{"alt": "...", "src": "..."}]

    # 抽出エンティティ
    entities: List[ExtractedEntity] = field(default_factory=list)

    # 要約
    summary: str = ""
    key_points: List[str] = field(default_factory=list)

    # 会社との関連性
    relevance_to_company: Optional[str] = None
    relevance_score: float = 0.0

    # 確信度
    overall_confidence: float = 0.0
    confidence_level: ContentConfidenceLevel = ContentConfidenceLevel.MEDIUM

    # 処理メタデータ
    metadata: ProcessingMetadata = field(default_factory=ProcessingMetadata)

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式で返す"""
        return {
            "success": self.success,
            "url_type": self.url_type.value,
            "url": self.url_metadata.url,
            "domain": self.url_metadata.domain,
            "title": self.url_metadata.title,
            "content_length": len(self.main_content),
            "summary": self.summary,
            "key_points": self.key_points,
            "entities": [e.to_dict() for e in self.entities],
            "relevance_to_company": self.relevance_to_company,
            "relevance_score": self.relevance_score,
            "overall_confidence": self.overall_confidence,
            "confidence_level": self.confidence_level.value,
            "metadata": self.metadata.to_dict(),
        }

    def to_brain_context(self) -> str:
        """脳のコンテキスト用文字列を生成"""
        parts = [f"【URL解析結果】{self.url_metadata.domain}"]

        if self.url_metadata.title:
            parts.append(f"タイトル: {self.url_metadata.title}")

        if self.summary:
            parts.append(f"要約: {self.summary}")

        if self.key_points:
            parts.append("重要ポイント:")
            for point in self.key_points[:5]:
                parts.append(f"  - {point}")

        if self.relevance_to_company:
            parts.append(f"会社との関連: {self.relevance_to_company}")

        return "\n".join(parts)


# =============================================================================
# Phase M2: 音声処理モデル
# =============================================================================


@dataclass
class Speaker:
    """
    話者情報

    音声中で検出された話者。
    """

    speaker_id: str                         # 話者ID（例: "speaker_1"）
    label: SpeakerLabel = SpeakerLabel.UNKNOWN  # 話者ラベル
    name: Optional[str] = None              # 話者名（判明している場合）
    speaking_time_seconds: float = 0.0      # 発話時間（秒）
    segment_count: int = 0                  # 発話セグメント数
    confidence: float = 0.0                 # 検出確信度

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式で返す"""
        return {
            "speaker_id": self.speaker_id,
            "label": self.label.value,
            "name": self.name,
            "speaking_time_seconds": self.speaking_time_seconds,
            "segment_count": self.segment_count,
            "confidence": self.confidence,
        }


@dataclass
class TranscriptSegment:
    """
    文字起こしセグメント

    音声の一区間の文字起こし結果。
    """

    segment_id: int                         # セグメントID
    text: str = ""                          # 文字起こしテキスト
    start_time: float = 0.0                 # 開始時間（秒）
    end_time: float = 0.0                   # 終了時間（秒）
    speaker: Optional[Speaker] = None       # 話者
    confidence: float = 0.0                 # 文字起こし確信度
    language: Optional[str] = None          # 言語コード

    @property
    def duration(self) -> float:
        """セグメントの長さ（秒）"""
        return self.end_time - self.start_time

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式で返す"""
        result = {
            "segment_id": self.segment_id,
            "text": self.text,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration": self.duration,
            "confidence": self.confidence,
            "language": self.language,
        }
        if self.speaker:
            result["speaker"] = self.speaker.to_dict()
        return result

    def format_timestamp(self) -> str:
        """タイムスタンプを [mm:ss - mm:ss] 形式で出力"""
        return f"[{self._format_time(self.start_time)} - {self._format_time(self.end_time)}]"

    def to_transcript_line(self) -> str:
        """文字起こし行として出力"""
        time_str = self.format_timestamp()
        speaker_str = f"{self.speaker.name or self.speaker.label.value}: " if self.speaker else ""
        return f"{time_str} {speaker_str}{self.text}"

    @staticmethod
    def _format_time(seconds: float) -> str:
        """秒を mm:ss 形式に変換"""
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{mins:02d}:{secs:02d}"


@dataclass
class AudioMetadata:
    """
    音声メタデータ

    音声ファイルの基本情報。
    """

    duration_seconds: float = 0.0           # 音声の長さ（秒）
    sample_rate: Optional[int] = None       # サンプルレート
    channels: int = 1                       # チャンネル数
    bitrate: Optional[int] = None           # ビットレート
    format: str = ""                        # フォーマット（mp3, wav等）
    file_size_bytes: int = 0                # ファイルサイズ

    @property
    def duration_minutes(self) -> float:
        """音声の長さ（分）"""
        return self.duration_seconds / 60

    @property
    def duration_formatted(self) -> str:
        """音声の長さをフォーマット済み文字列で返す"""
        total_seconds = int(self.duration_seconds)
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60

        if hours > 0:
            return f"{hours}時間{minutes}分{seconds}秒"
        elif minutes > 0:
            return f"{minutes}分{seconds}秒"
        else:
            return f"{seconds}秒"

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式で返す"""
        return {
            "duration_seconds": self.duration_seconds,
            "duration_minutes": self.duration_minutes,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "bitrate": self.bitrate,
            "format": self.format,
            "file_size_bytes": self.file_size_bytes,
        }


@dataclass
class AudioAnalysisResult:
    """
    音声解析結果

    音声の文字起こし・分析結果。
    """

    # 成功/失敗
    success: bool = True

    # 基本情報
    audio_type: AudioType = AudioType.UNKNOWN
    audio_metadata: AudioMetadata = field(default_factory=AudioMetadata)

    # 文字起こし結果
    full_transcript: str = ""               # 全体の文字起こしテキスト
    segments: List[TranscriptSegment] = field(default_factory=list)
    transcription_status: TranscriptionStatus = TranscriptionStatus.COMPLETED

    # 話者情報
    speakers: List[Speaker] = field(default_factory=list)
    speaker_count: int = 0
    speakers_detected: bool = False

    # 言語情報
    detected_language: Optional[str] = None
    language_confidence: float = 0.0

    # 要約・分析
    summary: str = ""
    key_points: List[str] = field(default_factory=list)
    action_items: List[str] = field(default_factory=list)
    topics: List[str] = field(default_factory=list)

    # 抽出エンティティ
    entities: List[ExtractedEntity] = field(default_factory=list)

    # 確信度
    overall_confidence: float = 0.0
    confidence_level: ContentConfidenceLevel = ContentConfidenceLevel.MEDIUM

    # 処理メタデータ
    metadata: ProcessingMetadata = field(default_factory=ProcessingMetadata)

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式で返す"""
        return {
            "success": self.success,
            "audio_type": self.audio_type.value,
            "duration_seconds": self.audio_metadata.duration_seconds,
            "transcription_status": self.transcription_status.value,
            "transcript_length": len(self.full_transcript),
            "segment_count": len(self.segments),
            "speaker_count": self.speaker_count,
            "speakers_detected": self.speakers_detected,
            "detected_language": self.detected_language,
            "summary": self.summary,
            "key_points": self.key_points,
            "action_items": self.action_items,
            "topics": self.topics,
            "entities": [e.to_dict() for e in self.entities],
            "overall_confidence": self.overall_confidence,
            "confidence_level": self.confidence_level.value,
            "metadata": self.metadata.to_dict(),
        }

    # 言語コードから表示名へのマッピング
    LANGUAGE_NAMES = {
        "ja": "日本語",
        "en": "英語",
        "zh": "中国語",
        "ko": "韓国語",
        "es": "スペイン語",
        "fr": "フランス語",
        "de": "ドイツ語",
        "it": "イタリア語",
        "pt": "ポルトガル語",
        "ru": "ロシア語",
    }

    def to_brain_context(self) -> str:
        """脳のコンテキスト用文字列を生成"""
        duration_min = int(self.audio_metadata.duration_seconds // 60)
        parts = [f"【音声解析結果】{duration_min}分"]

        if self.detected_language:
            lang_name = self.LANGUAGE_NAMES.get(self.detected_language, self.detected_language)
            parts.append(f"言語: {lang_name}")

        if self.speaker_count > 0:
            parts.append(f"話者数: {self.speaker_count}名")

        if self.summary:
            parts.append(f"要約: {self.summary}")

        if self.key_points:
            parts.append("重要ポイント:")
            for point in self.key_points[:5]:
                parts.append(f"  - {point}")

        if self.action_items:
            parts.append("アクションアイテム:")
            for item in self.action_items[:5]:
                parts.append(f"  - {item}")

        if self.topics:
            parts.append(f"トピック: {', '.join(self.topics[:5])}")

        return "\n".join(parts)

    def get_transcript_with_speakers(self) -> str:
        """話者付きの文字起こしテキストを取得"""
        if not self.segments:
            return self.full_transcript

        lines = []
        for segment in self.segments:
            lines.append(segment.to_transcript_line())
        return "\n".join(lines)


# =============================================================================
# 統合リクエスト/レスポンス
# =============================================================================


@dataclass
class MultimodalInput:
    """
    Multimodal入力

    各種入力の統一インターフェース。
    """

    # 入力タイプ
    input_type: InputType

    # 組織情報
    organization_id: str
    room_id: Optional[str] = None
    user_id: Optional[str] = None

    # 入力データ（いずれか1つ）
    image_data: Optional[bytes] = None        # 画像のバイナリ
    pdf_data: Optional[bytes] = None          # PDFのバイナリ
    url: Optional[str] = None                 # URL文字列
    audio_data: Optional[bytes] = None        # 音声のバイナリ（Phase M2）
    file_path: Optional[str] = None           # ファイルパス（ローカル）

    # 追加オプション
    instruction: Optional[str] = None         # 追加の指示
    save_to_knowledge: bool = False           # ナレッジDBに保存するか
    deep_analysis: bool = False               # 詳細分析を行うか

    # Phase M2: 音声処理オプション
    language: Optional[str] = None            # 言語コード（音声用）
    detect_speakers: bool = True              # 話者検出を行うか
    generate_summary: bool = True             # 要約を生成するか

    # コンテキスト
    brain_context: Optional[Any] = None       # BrainContext（型循環を避けるためAny）

    def validate(self) -> bool:
        """入力の検証"""
        if not self.organization_id:
            return False

        if self.input_type == InputType.IMAGE:
            return self.image_data is not None or self.file_path is not None
        elif self.input_type == InputType.PDF:
            return self.pdf_data is not None or self.file_path is not None
        elif self.input_type == InputType.URL:
            return self.url is not None
        elif self.input_type == InputType.AUDIO:
            return self.audio_data is not None or self.file_path is not None

        return False


@dataclass
class MultimodalOutput:
    """
    Multimodal出力

    各種解析結果の統一インターフェース。
    """

    # 成功/失敗
    success: bool = True

    # 入力タイプ
    input_type: InputType = InputType.IMAGE

    # 各種解析結果（いずれか1つ）
    image_result: Optional[ImageAnalysisResult] = None
    pdf_result: Optional[PDFAnalysisResult] = None
    url_result: Optional[URLAnalysisResult] = None
    audio_result: Optional[AudioAnalysisResult] = None  # Phase M2

    # 共通項目
    summary: str = ""
    extracted_text: str = ""
    entities: List[ExtractedEntity] = field(default_factory=list)

    # 処理メタデータ
    metadata: ProcessingMetadata = field(default_factory=ProcessingMetadata)

    # エラー情報
    error_message: Optional[str] = None
    error_code: Optional[str] = None

    def get_result(self):
        """適切な結果オブジェクトを取得"""
        if self.input_type == InputType.IMAGE:
            return self.image_result
        elif self.input_type == InputType.PDF:
            return self.pdf_result
        elif self.input_type == InputType.URL:
            return self.url_result
        elif self.input_type == InputType.AUDIO:
            return self.audio_result
        return None

    def to_brain_context(self) -> str:
        """脳のコンテキスト用文字列を生成"""
        result = self.get_result()
        if result and hasattr(result, 'to_brain_context'):
            return result.to_brain_context()
        return f"【{self.input_type.value}解析結果】{self.summary or '解析完了'}"

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式で返す"""
        result_dict = None
        result = self.get_result()
        if result:
            result_dict = result.to_dict()

        return {
            "success": self.success,
            "input_type": self.input_type.value,
            "summary": self.summary,
            "extracted_text_length": len(self.extracted_text),
            "entities": [e.to_dict() for e in self.entities],
            "result": result_dict,
            "metadata": self.metadata.to_dict(),
            "error_message": self.error_message,
        }
