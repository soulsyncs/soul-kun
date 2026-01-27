# lib/capabilities/generation/models.py
"""
Phase G1: 文書生成能力 - データモデル

このモジュールは、文書生成に関するデータモデルを定義します。

設計書: docs/20_next_generation_capabilities.md セクション6
Author: Claude Opus 4.5
Created: 2026-01-27
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any, List
from uuid import UUID, uuid4

from .constants import (
    GenerationType,
    DocumentType,
    GenerationStatus,
    OutputFormat,
    SectionType,
    ConfirmationLevel,
    QualityLevel,
    ToneStyle,
    # G2: 画像生成
    ImageProvider,
    ImageSize,
    ImageQuality,
    ImageStyle,
    DEFAULT_IMAGE_PROVIDER,
    DEFAULT_IMAGE_SIZE,
    DEFAULT_IMAGE_QUALITY,
    DEFAULT_IMAGE_STYLE,
    # G3: ディープリサーチ
    ResearchDepth,
    ResearchType,
    SourceType,
    ReportFormat,
)


# =============================================================================
# 共通モデル
# =============================================================================


@dataclass
class GenerationMetadata:
    """
    生成メタデータ

    生成処理の追跡情報を保持。
    """
    request_id: str = field(default_factory=lambda: str(uuid4()))
    organization_id: Optional[UUID] = None
    user_id: Optional[UUID] = None
    started_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    processing_time_ms: Optional[int] = None
    model_used: Optional[str] = None
    total_tokens_used: int = 0
    estimated_cost_jpy: float = 0.0
    error_message: Optional[str] = None
    error_code: Optional[str] = None

    def complete(
        self,
        success: bool = True,
        error_message: Optional[str] = None,
        error_code: Optional[str] = None,
    ) -> "GenerationMetadata":
        """処理完了時にメタデータを更新"""
        self.completed_at = datetime.utcnow()
        if self.started_at:
            delta = self.completed_at - self.started_at
            self.processing_time_ms = int(delta.total_seconds() * 1000)
        if not success:
            self.error_message = error_message
            self.error_code = error_code
        return self

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "request_id": self.request_id,
            "organization_id": str(self.organization_id) if self.organization_id else None,
            "user_id": str(self.user_id) if self.user_id else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "processing_time_ms": self.processing_time_ms,
            "model_used": self.model_used,
            "total_tokens_used": self.total_tokens_used,
            "estimated_cost_jpy": self.estimated_cost_jpy,
            "error_message": self.error_message,
            "error_code": self.error_code,
        }


@dataclass
class ReferenceDocument:
    """
    参照文書

    文書生成時に参照する既存文書の情報。
    """
    document_id: str
    title: str
    source_type: str = "google_docs"  # google_docs, knowledge_base, uploaded
    url: Optional[str] = None
    content: Optional[str] = None  # 抽出済みのコンテンツ
    relevance_score: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "document_id": self.document_id,
            "title": self.title,
            "source_type": self.source_type,
            "url": self.url,
            "has_content": self.content is not None,
            "relevance_score": self.relevance_score,
            "metadata": self.metadata,
        }


# =============================================================================
# セクション関連モデル
# =============================================================================


@dataclass
class SectionOutline:
    """
    セクションアウトライン

    文書の各セクションの構成情報。
    """
    section_id: int
    title: str
    description: str = ""
    section_type: SectionType = SectionType.HEADING1
    estimated_length: int = 500  # 想定文字数
    parent_section_id: Optional[int] = None
    order: int = 0
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "section_id": self.section_id,
            "title": self.title,
            "description": self.description,
            "section_type": self.section_type.value,
            "estimated_length": self.estimated_length,
            "parent_section_id": self.parent_section_id,
            "order": self.order,
            "notes": self.notes,
        }


@dataclass
class SectionContent:
    """
    セクションコンテンツ

    生成されたセクションの内容。
    """
    section_id: int
    title: str
    content: str
    section_type: SectionType = SectionType.PARAGRAPH
    word_count: int = 0
    tokens_used: int = 0
    generation_time_ms: int = 0
    model_used: Optional[str] = None

    def __post_init__(self):
        """初期化後処理"""
        if not self.word_count:
            self.word_count = len(self.content)

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "section_id": self.section_id,
            "title": self.title,
            "content": self.content,
            "section_type": self.section_type.value,
            "word_count": self.word_count,
            "tokens_used": self.tokens_used,
            "generation_time_ms": self.generation_time_ms,
            "model_used": self.model_used,
        }

    def to_markdown(self) -> str:
        """Markdown形式で出力"""
        # セクションタイプに応じた見出しレベル
        heading_prefix = {
            SectionType.TITLE: "# ",
            SectionType.SUBTITLE: "## ",
            SectionType.HEADING1: "## ",
            SectionType.HEADING2: "### ",
            SectionType.HEADING3: "#### ",
        }
        prefix = heading_prefix.get(self.section_type, "")

        if prefix:
            return f"{prefix}{self.title}\n\n{self.content}"
        return self.content


# =============================================================================
# アウトラインモデル
# =============================================================================


@dataclass
class DocumentOutline:
    """
    文書アウトライン

    文書全体の構成案。
    """
    title: str
    document_type: DocumentType
    sections: List[SectionOutline] = field(default_factory=list)
    estimated_total_length: int = 0
    notes: str = ""
    generated_at: datetime = field(default_factory=datetime.utcnow)
    model_used: Optional[str] = None
    tokens_used: int = 0

    def __post_init__(self):
        """初期化後処理"""
        if not self.estimated_total_length and self.sections:
            self.estimated_total_length = sum(s.estimated_length for s in self.sections)

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "title": self.title,
            "document_type": self.document_type.value,
            "sections": [s.to_dict() for s in self.sections],
            "estimated_total_length": self.estimated_total_length,
            "notes": self.notes,
            "generated_at": self.generated_at.isoformat(),
            "model_used": self.model_used,
            "tokens_used": self.tokens_used,
        }

    def to_user_display(self) -> str:
        """ユーザー表示用のフォーマット"""
        lines = [f"📝 「{self.title}」の構成案", ""]
        for i, section in enumerate(self.sections, 1):
            lines.append(f"{i}. {section.title}")
            if section.description:
                lines.append(f"   └ {section.description}")
        lines.append("")
        lines.append(f"📊 想定文字数: 約{self.estimated_total_length:,}文字")
        if self.notes:
            lines.append(f"📌 {self.notes}")
        return "\n".join(lines)


# =============================================================================
# リクエストモデル
# =============================================================================


@dataclass
class DocumentRequest:
    """
    文書生成リクエスト

    文書生成に必要な情報をすべて含む。
    """
    # 必須項目
    title: str
    organization_id: UUID

    # 文書設定
    document_type: DocumentType = DocumentType.REPORT
    output_format: OutputFormat = OutputFormat.GOOGLE_DOCS
    quality_level: QualityLevel = QualityLevel.STANDARD
    tone_style: ToneStyle = ToneStyle.PROFESSIONAL

    # コンテンツ設定
    purpose: str = ""              # 作成目的
    instruction: str = ""          # ユーザーからの指示
    context: str = ""              # 追加コンテキスト
    keywords: List[str] = field(default_factory=list)

    # 参照情報
    reference_documents: List[ReferenceDocument] = field(default_factory=list)
    template_id: Optional[str] = None

    # 確認設定
    confirmation_level: ConfirmationLevel = ConfirmationLevel.OUTLINE_ONLY
    require_confirmation: bool = True

    # 出力設定
    target_folder_id: Optional[str] = None  # Google Drive フォルダID
    share_with: List[str] = field(default_factory=list)  # 共有先メールアドレス

    # カスタムアウトライン（事前定義時）
    custom_outline: Optional[DocumentOutline] = None

    # メタデータ
    user_id: Optional[UUID] = None
    request_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "request_id": self.request_id,
            "title": self.title,
            "organization_id": str(self.organization_id),
            "document_type": self.document_type.value,
            "output_format": self.output_format.value,
            "quality_level": self.quality_level.value,
            "tone_style": self.tone_style.value,
            "purpose": self.purpose,
            "instruction": self.instruction,
            "context": self.context[:500] if self.context else "",  # 長すぎる場合は省略
            "keywords": self.keywords,
            "reference_count": len(self.reference_documents),
            "template_id": self.template_id,
            "confirmation_level": self.confirmation_level.value,
            "require_confirmation": self.require_confirmation,
            "target_folder_id": self.target_folder_id,
            "share_with_count": len(self.share_with),
            "has_custom_outline": self.custom_outline is not None,
            "user_id": str(self.user_id) if self.user_id else None,
            "created_at": self.created_at.isoformat(),
        }


# =============================================================================
# 結果モデル
# =============================================================================


@dataclass
class DocumentResult:
    """
    文書生成結果

    生成された文書の情報と処理結果。
    """
    # ステータス
    status: GenerationStatus = GenerationStatus.PENDING
    success: bool = False

    # 文書情報
    document_id: Optional[str] = None  # Google Docs ID
    document_url: Optional[str] = None
    document_title: str = ""

    # アウトライン（確認用）
    outline: Optional[DocumentOutline] = None

    # 生成されたコンテンツ
    sections: List[SectionContent] = field(default_factory=list)
    full_content: str = ""  # 全文（Markdown）

    # 統計情報
    total_word_count: int = 0
    total_sections: int = 0

    # メタデータ
    metadata: GenerationMetadata = field(default_factory=GenerationMetadata)

    # エラー情報
    error_message: Optional[str] = None
    error_code: Optional[str] = None

    def __post_init__(self):
        """初期化後処理"""
        if not self.total_word_count and self.sections:
            self.total_word_count = sum(s.word_count for s in self.sections)
        if not self.total_sections:
            self.total_sections = len(self.sections)

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "status": self.status.value,
            "success": self.success,
            "document_id": self.document_id,
            "document_url": self.document_url,
            "document_title": self.document_title,
            "has_outline": self.outline is not None,
            "section_count": len(self.sections),
            "total_word_count": self.total_word_count,
            "total_sections": self.total_sections,
            "metadata": self.metadata.to_dict(),
            "error_message": self.error_message,
            "error_code": self.error_code,
        }

    def to_user_message(self) -> str:
        """ユーザー向けメッセージを生成"""
        if self.status == GenerationStatus.PENDING:
            if self.outline:
                return self.outline.to_user_display() + "\n\nこの構成で進めていいウル？"
            return "文書を作成中ウル..."

        if self.status == GenerationStatus.COMPLETED:
            lines = [
                "━━━━━━━━━━━━━━━━━━━━━━",
                "✅ 完成したウル！",
                "",
                f"📄 {self.document_title}",
            ]
            if self.document_url:
                lines.append(self.document_url)
            lines.extend([
                "",
                f"📊 文字数: {self.total_word_count:,}文字",
                f"💰 コスト: ¥{self.metadata.estimated_cost_jpy:.0f}",
                "",
                "確認して、修正点があれば教えてほしいウル！",
                "━━━━━━━━━━━━━━━━━━━━━━",
            ])
            return "\n".join(lines)

        if self.status == GenerationStatus.FAILED:
            return f"文書の作成に失敗したウル... 😢\n{self.error_message or '原因不明'}"

        return f"文書を作成中ウル...（{self.status.value}）"

    def to_brain_context(self) -> str:
        """脳のコンテキスト用文字列を生成"""
        lines = [f"【文書生成結果: {self.document_title}】"]
        lines.append(f"ステータス: {self.status.value}")

        if self.status == GenerationStatus.COMPLETED:
            lines.append(f"URL: {self.document_url}")
            lines.append(f"文字数: {self.total_word_count:,}文字")
            if self.sections:
                lines.append("セクション:")
                for section in self.sections[:5]:  # 最初の5セクションのみ
                    lines.append(f"  - {section.title}")
                if len(self.sections) > 5:
                    lines.append(f"  ... 他{len(self.sections) - 5}セクション")

        elif self.status == GenerationStatus.PENDING and self.outline:
            lines.append("構成案:")
            for section in self.outline.sections[:10]:
                lines.append(f"  - {section.title}")

        return "\n".join(lines)


# =============================================================================
# 統合モデル
# =============================================================================


@dataclass
class GenerationInput:
    """
    生成入力（統合）

    複数の生成タイプに対応した統合入力モデル。
    """
    generation_type: GenerationType
    organization_id: UUID

    # 文書生成用
    document_request: Optional[DocumentRequest] = None

    # 画像生成用（G2）
    image_request: Optional["ImageRequest"] = None

    # 共通設定
    user_id: Optional[UUID] = None
    instruction: str = ""
    context: str = ""

    def get_request(self):
        """適切なリクエストオブジェクトを取得"""
        if self.generation_type == GenerationType.DOCUMENT:
            return self.document_request
        if self.generation_type == GenerationType.IMAGE:
            return self.image_request
        return None


@dataclass
class GenerationOutput:
    """
    生成出力（統合）

    複数の生成タイプに対応した統合出力モデル。
    """
    generation_type: GenerationType
    success: bool = False
    status: GenerationStatus = GenerationStatus.PENDING

    # 文書生成結果
    document_result: Optional[DocumentResult] = None

    # 画像生成結果（G2）
    image_result: Optional["ImageResult"] = None

    # 共通メタデータ
    metadata: GenerationMetadata = field(default_factory=GenerationMetadata)

    # エラー情報
    error_message: Optional[str] = None
    error_code: Optional[str] = None

    def get_result(self):
        """適切な結果オブジェクトを取得"""
        if self.generation_type == GenerationType.DOCUMENT:
            return self.document_result
        if self.generation_type == GenerationType.IMAGE:
            return self.image_result
        return None

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        result = {
            "generation_type": self.generation_type.value,
            "success": self.success,
            "status": self.status.value,
            "metadata": self.metadata.to_dict(),
            "error_message": self.error_message,
            "error_code": self.error_code,
        }
        if self.document_result:
            result["document_result"] = self.document_result.to_dict()
        if self.image_result:
            result["image_result"] = self.image_result.to_dict()
        return result

    def to_user_message(self) -> str:
        """ユーザー向けメッセージを生成"""
        if self.document_result:
            return self.document_result.to_user_message()
        if self.image_result:
            return self.image_result.to_user_message()
        if self.error_message:
            return f"生成に失敗しました: {self.error_message}"
        return "生成処理中..."

    def to_brain_context(self) -> str:
        """脳のコンテキスト用文字列を生成"""
        if self.document_result:
            return self.document_result.to_brain_context()
        if self.image_result:
            return self.image_result.to_brain_context()
        return f"【生成出力】タイプ: {self.generation_type.value}, ステータス: {self.status.value}"


# =============================================================================
# Phase G2: 画像生成モデル
# =============================================================================


@dataclass
class ImageRequest:
    """
    画像生成リクエスト

    DALL-E等の画像生成AIへのリクエストを表現。
    """
    organization_id: UUID
    prompt: str                                         # 生成したい画像の説明

    # オプション設定
    provider: ImageProvider = DEFAULT_IMAGE_PROVIDER
    size: ImageSize = DEFAULT_IMAGE_SIZE
    quality: ImageQuality = DEFAULT_IMAGE_QUALITY
    style: ImageStyle = DEFAULT_IMAGE_STYLE
    user_id: Optional[UUID] = None

    # 追加オプション
    instruction: str = ""                               # 追加の指示
    reference_image_url: Optional[str] = None           # 参考画像URL（将来用）
    negative_prompt: str = ""                           # 除外したい要素
    seed: Optional[int] = None                          # 再現性用シード（対応プロバイダのみ）

    # 出力先
    save_to_drive: bool = False                         # Google Driveに保存
    drive_folder_id: Optional[str] = None               # 保存先フォルダID
    send_to_chatwork: bool = False                      # ChatWorkに送信
    chatwork_room_id: Optional[str] = None              # 送信先ルームID

    # 確認
    require_confirmation: bool = False                  # 生成前に確認を求める

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "organization_id": str(self.organization_id),
            "prompt": self.prompt,
            "provider": self.provider.value,
            "size": self.size.value,
            "quality": self.quality.value,
            "style": self.style.value,
            "user_id": str(self.user_id) if self.user_id else None,
            "instruction": self.instruction,
            "negative_prompt": self.negative_prompt,
            "save_to_drive": self.save_to_drive,
            "send_to_chatwork": self.send_to_chatwork,
        }


@dataclass
class OptimizedPrompt:
    """
    最適化されたプロンプト

    LLMによって最適化されたDALL-E用プロンプト。
    """
    original_prompt: str                                # 元のプロンプト
    optimized_prompt: str                               # 最適化後のプロンプト（英語）
    japanese_summary: str = ""                          # 日本語での説明
    warnings: List[str] = field(default_factory=list)   # 注意点
    tokens_used: int = 0                                # 使用トークン数


@dataclass
class ImageResult:
    """
    画像生成結果

    生成された画像の情報と配信状況を保持。
    """
    # ステータス
    status: GenerationStatus = GenerationStatus.PENDING
    success: bool = False

    # 生成された画像
    image_url: Optional[str] = None                     # 画像URL（OpenAI一時URL）
    image_data: Optional[bytes] = None                  # 画像データ（バイナリ）
    image_format: str = "png"                           # 画像フォーマット

    # 保存先
    drive_url: Optional[str] = None                     # Google Drive URL
    drive_file_id: Optional[str] = None                 # Google Drive ファイルID

    # 生成情報
    prompt_used: Optional[str] = None                   # 実際に使用したプロンプト
    optimized_prompt: Optional[OptimizedPrompt] = None  # 最適化情報
    provider: ImageProvider = DEFAULT_IMAGE_PROVIDER
    size: ImageSize = DEFAULT_IMAGE_SIZE
    quality: ImageQuality = DEFAULT_IMAGE_QUALITY
    style: ImageStyle = DEFAULT_IMAGE_STYLE
    revised_prompt: Optional[str] = None                # DALL-E 3が返す修正済みプロンプト

    # コスト
    estimated_cost_jpy: float = 0.0

    # メタデータ
    metadata: GenerationMetadata = field(default_factory=GenerationMetadata)
    error_message: Optional[str] = None
    error_code: Optional[str] = None

    # ChatWork送信結果
    chatwork_sent: bool = False
    chatwork_message_id: Optional[str] = None

    def complete(
        self,
        success: bool = True,
        error_message: Optional[str] = None,
        error_code: Optional[str] = None,
    ) -> "ImageResult":
        """処理完了時に結果を更新"""
        self.success = success
        self.status = GenerationStatus.COMPLETED if success else GenerationStatus.FAILED
        if not success:
            self.error_message = error_message
            self.error_code = error_code
        self.metadata.complete(success, error_message, error_code)
        return self

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "status": self.status.value,
            "success": self.success,
            "image_url": self.image_url,
            "drive_url": self.drive_url,
            "prompt_used": self.prompt_used,
            "revised_prompt": self.revised_prompt,
            "provider": self.provider.value,
            "size": self.size.value,
            "quality": self.quality.value,
            "style": self.style.value,
            "estimated_cost_jpy": self.estimated_cost_jpy,
            "metadata": self.metadata.to_dict(),
            "error_message": self.error_message,
            "error_code": self.error_code,
            "chatwork_sent": self.chatwork_sent,
        }

    def to_user_message(self) -> str:
        """ユーザー向けメッセージを生成"""
        if self.status == GenerationStatus.GENERATING:
            return "画像を生成中ウル... 🎨"

        if self.status == GenerationStatus.COMPLETED:
            lines = [
                "━━━━━━━━━━━━━━━━━━━━━━",
                "✅ 完成したウル！",
                "",
            ]
            if self.image_url:
                lines.append(f"🖼 画像URL: {self.image_url}")
            if self.drive_url:
                lines.append(f"📁 Google Drive: {self.drive_url}")
            lines.extend([
                "",
                f"📐 サイズ: {self.size.value}",
                f"💰 コスト: ¥{self.estimated_cost_jpy:.0f}",
                "",
                "気に入らなかったら、修正指示を教えてほしいウル！",
                "・もっと明るく",
                "・色を変えて",
                "・構図を変えて",
                "など",
                "━━━━━━━━━━━━━━━━━━━━━━",
            ])
            return "\n".join(lines)

        if self.status == GenerationStatus.FAILED:
            return f"画像の生成に失敗したウル... 😢\n{self.error_message or '原因不明'}"

        return f"画像を準備中ウル...（{self.status.value}）"

    def to_brain_context(self) -> str:
        """脳のコンテキスト用文字列を生成"""
        lines = ["【画像生成結果】"]
        lines.append(f"ステータス: {self.status.value}")

        if self.status == GenerationStatus.COMPLETED:
            if self.drive_url:
                lines.append(f"Google Drive: {self.drive_url}")
            lines.append(f"サイズ: {self.size.value}")
            lines.append(f"品質: {self.quality.value}")
            if self.prompt_used:
                lines.append(f"プロンプト: {self.prompt_used[:100]}...")

        return "\n".join(lines)
