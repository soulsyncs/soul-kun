"""
ナレッジ検索 API スキーマ

Phase 3: ナレッジ検索機能
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


# ================================================================
# 検索リクエスト/レスポンス
# ================================================================

class KnowledgeSearchRequest(BaseModel):
    """ナレッジ検索リクエスト"""
    query: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="検索クエリ",
        examples=["経費精算の手順を教えてください"]
    )
    categories: Optional[list[str]] = Field(
        default=None,
        description="カテゴリフィルタ（A, B, C, D, E, F）",
        examples=[["A", "B"]]
    )
    top_k: Optional[int] = Field(
        default=5,
        ge=1,
        le=20,
        description="取得する検索結果の最大数"
    )
    include_content: Optional[bool] = Field(
        default=True,
        description="チャンク内容を含めるかどうか"
    )
    generate_answer: Optional[bool] = Field(
        default=False,
        description="AIによる回答生成を行うかどうか"
    )
    source: Optional[str] = Field(
        default="api",
        description="検索元（chatwork, web, api, admin）"
    )
    source_room_id: Optional[str] = Field(
        default=None,
        description="検索元のルームID（Chatwork連携時）"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "query": "経費精算の手順を教えてください",
                "categories": ["B"],
                "top_k": 5,
                "include_content": True,
                "generate_answer": False
            }
        }


class DocumentMetadata(BaseModel):
    """検索結果のドキュメントメタデータ"""
    document_id: str
    title: str
    file_name: str
    category: str
    classification: str
    department_id: Optional[str] = None
    google_drive_web_view_link: Optional[str] = None


class ChunkResult(BaseModel):
    """検索結果のチャンク情報"""
    chunk_id: str
    pinecone_id: str
    score: float = Field(description="類似度スコア（0-1）")
    content: Optional[str] = Field(default=None, description="チャンク内容")
    page_number: Optional[int] = None
    section_title: Optional[str] = None
    document: DocumentMetadata


class KnowledgeSearchResponse(BaseModel):
    """ナレッジ検索レスポンス"""
    query: str
    results: list[ChunkResult]
    total_results: int
    search_log_id: str = Field(description="検索ログID（フィードバック用）")

    # 検索品質情報
    top_score: Optional[float] = None
    average_score: Optional[float] = None

    # 回答生成（オプション）
    answer: Optional[str] = None
    answer_refused: bool = False
    refused_reason: Optional[str] = None

    # パフォーマンス
    search_time_ms: int
    total_time_ms: int

    class Config:
        json_schema_extra = {
            "example": {
                "query": "経費精算の手順を教えてください",
                "results": [
                    {
                        "chunk_id": "550e8400-e29b-41d4-a716-446655440000",
                        "pinecone_id": "org_soulsyncs_doc123_v1_chunk0",
                        "score": 0.92,
                        "content": "経費精算の手順は以下の通りです...",
                        "page_number": 1,
                        "section_title": "1. 経費精算の基本",
                        "document": {
                            "document_id": "doc123",
                            "title": "経費精算マニュアル",
                            "file_name": "経費精算マニュアル.pdf",
                            "category": "B",
                            "classification": "internal",
                            "google_drive_web_view_link": "https://drive.google.com/..."
                        }
                    }
                ],
                "total_results": 1,
                "search_log_id": "log_abc123",
                "top_score": 0.92,
                "average_score": 0.92,
                "search_time_ms": 150,
                "total_time_ms": 200
            }
        }


# ================================================================
# フィードバックリクエスト/レスポンス
# ================================================================

class KnowledgeFeedbackRequest(BaseModel):
    """ナレッジ検索フィードバックリクエスト"""
    search_log_id: str = Field(
        ...,
        description="フィードバック対象の検索ログID"
    )
    feedback_type: str = Field(
        ...,
        description="フィードバックタイプ",
        pattern="^(helpful|not_helpful|wrong|incomplete|outdated)$"
    )
    rating: Optional[int] = Field(
        default=None,
        ge=1,
        le=5,
        description="評価スコア（1-5）"
    )
    comment: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="自由記述コメント"
    )
    target_chunk_ids: Optional[list[str]] = Field(
        default=None,
        description="フィードバック対象のチャンクID（特定チャンクへのフィードバック時）"
    )
    suggested_answer: Optional[str] = Field(
        default=None,
        max_length=5000,
        description="ユーザーが提案する正しい回答"
    )
    suggested_source: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="ユーザーが提案する正しい情報源"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "search_log_id": "log_abc123",
                "feedback_type": "helpful",
                "rating": 5,
                "comment": "とても分かりやすかったです"
            }
        }


class KnowledgeFeedbackResponse(BaseModel):
    """ナレッジ検索フィードバックレスポンス"""
    feedback_id: str
    status: str = "received"
    message: str = "フィードバックを受け付けました"

    class Config:
        json_schema_extra = {
            "example": {
                "feedback_id": "fb_xyz789",
                "status": "received",
                "message": "フィードバックを受け付けました"
            }
        }


# ================================================================
# ドキュメント情報
# ================================================================

class DocumentInfo(BaseModel):
    """ドキュメント詳細情報"""
    id: str
    organization_id: str
    title: str
    description: Optional[str] = None
    file_name: str
    file_type: str
    category: str
    classification: str
    department_id: Optional[str] = None
    current_version: int
    total_chunks: int
    total_pages: int
    processing_status: str
    is_active: bool
    is_searchable: bool
    google_drive_file_id: Optional[str] = None
    google_drive_web_view_link: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class DocumentListResponse(BaseModel):
    """ドキュメント一覧レスポンス"""
    documents: list[DocumentInfo]
    total: int
    page: int
    page_size: int
    has_next: bool


# ================================================================
# 検索統計
# ================================================================

class SearchStatsResponse(BaseModel):
    """検索統計レスポンス"""
    total_searches: int
    total_documents: int
    total_chunks: int
    average_score: Optional[float] = None
    feedback_positive_rate: Optional[float] = None
    top_categories: list[dict]
    recent_queries: list[str]
