"""
ナレッジ検索 API エンドポイント

Phase 3: ナレッジ検索機能

エンドポイント:
    POST /api/v1/knowledge/search - ナレッジ検索
    POST /api/v1/knowledge/feedback - フィードバック登録
    GET /api/v1/knowledge/documents - ドキュメント一覧
    GET /api/v1/knowledge/documents/{document_id} - ドキュメント詳細

設計ドキュメント:
    docs/05_phase3_knowledge_detailed_design.md
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Header

from lib.config import get_settings
from lib.logging import get_logger
from lib.db import get_async_db_pool
from app.schemas.knowledge import (
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
    KnowledgeFeedbackRequest,
    KnowledgeFeedbackResponse,
    DocumentInfo,
    DocumentListResponse,
)
from app.services.knowledge_search import (
    KnowledgeSearchService,
    UserContext,
)

from sqlalchemy import text


logger = get_logger(__name__)
settings = get_settings()

router = APIRouter(prefix="/knowledge", tags=["Knowledge"])


# ================================================================
# 依存性注入
# ================================================================

async def get_db_connection():
    """DB接続を取得"""
    pool = await get_async_db_pool()
    async with pool.connect() as conn:
        yield conn
        await conn.commit()


async def get_current_user(
    x_user_id: str = Header(..., description="ユーザーID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID", description="テナントID"),
    x_department_id: Optional[str] = Header(None, alias="X-Department-ID", description="部署ID"),
) -> UserContext:
    """
    現在のユーザーコンテキストを取得

    Note:
        本番環境では認証ミドルウェアでJWTトークン等から取得する。
        ここでは簡易的にヘッダーから取得している。
    """
    # ユーザーのアクセス可能な機密区分を取得
    # 本来はDBからユーザーの権限を確認する
    accessible_classifications = ["public", "internal"]

    # ユーザーの役職によって confidential/restricted へのアクセスを許可
    # Phase 3.5 で組織階層から動的に計算

    return UserContext(
        user_id=x_user_id,
        organization_id=x_tenant_id,
        department_id=x_department_id,
        accessible_classifications=accessible_classifications,
        accessible_department_ids=[x_department_id] if x_department_id else [],
    )


# ================================================================
# エンドポイント
# ================================================================

@router.post(
    "/search",
    response_model=KnowledgeSearchResponse,
    summary="ナレッジ検索",
    description="""
    ナレッジDBから関連ドキュメントを検索します。

    ## 処理フロー
    1. クエリのエンベディング生成
    2. Pineconeベクトル検索
    3. アクセス制御フィルタ
    4. 検索ログ記録

    ## アクセス制御
    - 機密区分（classification）によるフィルタ
    - Phase 3.5 以降: 部署（department_id）によるフィルタ

    ## 検索結果
    - スコアが閾値以下の場合は回答拒否（answer_refused=True）
    - 検索ログIDをフィードバック用に返却
    """,
)
async def search_knowledge(
    request: KnowledgeSearchRequest,
    user: UserContext = Depends(get_current_user),
    db_conn=Depends(get_db_connection),
):
    """ナレッジ検索を実行"""
    try:
        service = KnowledgeSearchService(db_conn)
        response = await service.search(user, request)
        return response
    except Exception as e:
        logger.error(f"Knowledge search error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "status": "error",
                "error_code": "SEARCH_FAILED",
                "error_message": "検索処理中にエラーが発生しました",
            }
        )


@router.post(
    "/feedback",
    response_model=KnowledgeFeedbackResponse,
    summary="フィードバック登録",
    description="""
    検索結果に対するフィードバックを登録します。

    ## フィードバックタイプ
    - `helpful`: 役に立った
    - `not_helpful`: 役に立たなかった
    - `wrong`: 間違っている
    - `incomplete`: 情報が不完全
    - `outdated`: 情報が古い

    ## 使用例
    検索結果が役に立った場合:
    ```json
    {
        "search_log_id": "log_abc123",
        "feedback_type": "helpful",
        "rating": 5,
        "comment": "とても分かりやすかったです"
    }
    ```
    """,
)
async def submit_feedback(
    request: KnowledgeFeedbackRequest,
    user: UserContext = Depends(get_current_user),
    db_conn=Depends(get_db_connection),
):
    """フィードバックを登録"""
    try:
        service = KnowledgeSearchService(db_conn)
        response = await service.submit_feedback(user, request)
        return response
    except Exception as e:
        logger.error(f"Feedback submission error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "status": "error",
                "error_code": "FEEDBACK_FAILED",
                "error_message": "フィードバックの登録に失敗しました",
            }
        )


@router.get(
    "/documents",
    response_model=DocumentListResponse,
    summary="ドキュメント一覧",
    description="""
    登録されているドキュメントの一覧を取得します。

    ## フィルタ
    - カテゴリ（category）
    - 機密区分（classification）
    - 処理状態（status）

    ## ページネーション
    - page: ページ番号（1始まり）
    - page_size: 1ページあたりの件数（デフォルト: 20, 最大: 100）
    """,
)
async def list_documents(
    category: Optional[str] = Query(None, description="カテゴリフィルタ（A, B, C, D, E, F）"),
    classification: Optional[str] = Query(None, description="機密区分フィルタ"),
    status: Optional[str] = Query(None, description="処理状態フィルタ"),
    search: Optional[str] = Query(None, description="タイトル検索"),
    page: int = Query(1, ge=1, description="ページ番号"),
    page_size: int = Query(20, ge=1, le=100, description="1ページあたりの件数"),
    user: UserContext = Depends(get_current_user),
    db_conn=Depends(get_db_connection),
):
    """ドキュメント一覧を取得"""
    try:
        offset = (page - 1) * page_size

        # クエリ構築
        conditions = ["organization_id = :org_id", "deleted_at IS NULL"]
        params = {"org_id": user.organization_id, "limit": page_size, "offset": offset}

        # 機密区分フィルタ（ユーザーがアクセス可能なもののみ）
        classifications_pg = "{" + ",".join(user.accessible_classifications) + "}"
        conditions.append("classification = ANY(CAST(:classifications AS TEXT[]))")
        params["classifications"] = classifications_pg

        if category:
            conditions.append("category = :category")
            params["category"] = category

        if classification:
            conditions.append("classification = :classification_filter")
            params["classification_filter"] = classification

        if status:
            conditions.append("processing_status = :status")
            params["status"] = status

        if search:
            conditions.append("(title ILIKE :search OR file_name ILIKE :search)")
            params["search"] = f"%{search}%"

        where_clause = " AND ".join(conditions)

        # カウントクエリ
        count_result = await db_conn.execute(
            text(f"SELECT COUNT(*) FROM documents WHERE {where_clause}"),
            params
        )
        total = count_result.scalar()

        # データクエリ
        query = f"""
            SELECT
                id, organization_id, title, description, file_name, file_type,
                category, classification, department_id, current_version,
                total_chunks, total_pages, processing_status,
                is_active, is_searchable,
                google_drive_file_id, google_drive_web_view_link,
                created_at, updated_at
            FROM documents
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
        """

        result = await db_conn.execute(text(query), params)
        rows = result.fetchall()

        documents = [
            DocumentInfo(
                id=str(row[0]),
                organization_id=str(row[1]),
                title=row[2],
                description=row[3],
                file_name=row[4],
                file_type=row[5],
                category=row[6],
                classification=row[7],
                department_id=str(row[8]) if row[8] else None,
                current_version=row[9],
                total_chunks=row[10] or 0,
                total_pages=row[11] or 0,
                processing_status=row[12],
                is_active=row[13],
                is_searchable=row[14],
                google_drive_file_id=row[15],
                google_drive_web_view_link=row[16],
                created_at=row[17],
                updated_at=row[18],
            )
            for row in rows
        ]

        has_next = (offset + page_size) < total

        return DocumentListResponse(
            documents=documents,
            total=total,
            page=page,
            page_size=page_size,
            has_next=has_next,
        )

    except Exception as e:
        logger.error(f"Document list error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "status": "error",
                "error_code": "LIST_FAILED",
                "error_message": "ドキュメント一覧の取得に失敗しました",
            }
        )


@router.get(
    "/documents/{document_id}",
    response_model=DocumentInfo,
    summary="ドキュメント詳細",
    description="指定されたドキュメントの詳細情報を取得します。",
)
async def get_document(
    document_id: str,
    user: UserContext = Depends(get_current_user),
    db_conn=Depends(get_db_connection),
):
    """ドキュメント詳細を取得"""
    try:
        # 機密区分フィルタ
        classifications_pg = "{" + ",".join(user.accessible_classifications) + "}"

        query = """
            SELECT
                id, organization_id, title, description, file_name, file_type,
                category, classification, department_id, current_version,
                total_chunks, total_pages, processing_status,
                is_active, is_searchable,
                google_drive_file_id, google_drive_web_view_link,
                created_at, updated_at
            FROM documents
            WHERE id = :doc_id
              AND organization_id = :org_id
              AND classification = ANY(CAST(:classifications AS TEXT[]))
              AND deleted_at IS NULL
        """

        result = await db_conn.execute(
            text(query),
            {
                "doc_id": document_id,
                "org_id": user.organization_id,
                "classifications": classifications_pg,
            }
        )
        row = result.fetchone()

        if not row:
            raise HTTPException(
                status_code=404,
                detail={
                    "status": "error",
                    "error_code": "NOT_FOUND",
                    "error_message": "ドキュメントが見つかりません",
                }
            )

        return DocumentInfo(
            id=str(row[0]),
            organization_id=str(row[1]),
            title=row[2],
            description=row[3],
            file_name=row[4],
            file_type=row[5],
            category=row[6],
            classification=row[7],
            department_id=str(row[8]) if row[8] else None,
            current_version=row[9],
            total_chunks=row[10] or 0,
            total_pages=row[11] or 0,
            processing_status=row[12],
            is_active=row[13],
            is_searchable=row[14],
            google_drive_file_id=row[15],
            google_drive_web_view_link=row[16],
            created_at=row[17],
            updated_at=row[18],
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Document detail error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "status": "error",
                "error_code": "DETAIL_FAILED",
                "error_message": "ドキュメント詳細の取得に失敗しました",
            }
        )
