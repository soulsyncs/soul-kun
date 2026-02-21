"""
Admin Dashboard - Google Drive Management Endpoints

管理ダッシュボード用 Google Drive ファイル管理API。
- ファイル一覧・詳細（DBから取得、Drive API不使用）
- 同期状態（最終同期日時・件数）
- ファイルダウンロード（Drive API経由）
- ファイルアップロード（Drive API経由、Level 6以上）

セキュリティ:
    - 全エンドポイントにJWT認証必須
    - 一覧・ダウンロード: Level 5以上（require_admin）
    - アップロード: Level 6以上（require_editor）
    - 全クエリにorganization_idフィルタ（鉄則#1）
    - PII（個人情報）はログに含めない
"""

import asyncio
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from sqlalchemy import text

from lib.db import get_db_pool
from lib.logging import log_audit_event

from .deps import (
    logger,
    get_current_user,
    require_admin,
    require_editor,
    _escape_like,
)
from app.schemas.admin import (
    DriveFilesResponse,
    DriveFileItem,
    DriveSyncStatusResponse,
    DriveUploadResponse,
    PineconeSyncResponse,
)

router = APIRouter()

# =============================================================================
# 設定
# =============================================================================

# アップロード先フォルダ（環境変数で設定）
_UPLOAD_FOLDER_ID = os.getenv("GOOGLE_DRIVE_UPLOAD_FOLDER_ID", "")

# アップロード上限（20MB）
_MAX_UPLOAD_BYTES = 20 * 1024 * 1024

# 許可するファイル拡張子ホワイトリスト
_ALLOWED_EXTENSIONS = {
    "pdf", "docx", "doc", "xlsx", "xls", "pptx", "ppt",
    "txt", "md", "csv",
}

# 許可するMIMEタイプホワイトリスト
_ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.ms-powerpoint",
    "text/plain",
    "text/markdown",
    "text/csv",
}

# Google Drive APIに接続するためのサービスアカウント設定
_SA_KEY_SECRET = os.getenv("GOOGLE_SA_KEY_SECRET", "google-docs-sa-key")
_GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "soulkun-production")


def _get_drive_client(writable: bool = False):
    """
    サービスアカウントでGoogle Drive APIクライアントを取得する。
    Secret Manager呼び出しは同期I/Oのため、呼び出し元でasyncio.to_thread()を使うこと。

    Args:
        writable: Trueにすると書き込みスコープ（drive.file）でクライアントを初期化する。
                  アップロード機能を使う場合はTrueを指定すること。
    """
    import json
    from google.cloud import secretmanager

    try:
        sm_client = secretmanager.SecretManagerServiceClient()
        secret_name = f"projects/{_GCP_PROJECT_ID}/secrets/{_SA_KEY_SECRET}/versions/latest"
        response = sm_client.access_secret_version(request={"name": secret_name})
        sa_key_str = response.payload.data.decode("utf-8")
        sa_info = json.loads(sa_key_str)
    except Exception as e:
        logger.error("SA key fetch from Secret Manager failed: %s", type(e).__name__)
        raise HTTPException(status_code=503, detail="Drive認証情報の取得に失敗しました")

    from lib.google_drive import GoogleDriveClient
    try:
        return GoogleDriveClient(service_account_info=sa_info, writable=writable)
    except Exception as e:
        logger.error("Drive client init failed: %s", type(e).__name__)
        raise HTTPException(status_code=503, detail="Drive認証の初期化に失敗しました")


# =============================================================================
# 同期DBヘルパー（asyncio.to_thread()用）
# RLS set_config とクエリは必ず同一コネクション内で実行する（Codex指摘）
# pool_size との整合: 同時リクエスト数が pool_size を超えないよう注意
# =============================================================================

def _sync_list_drive_files(
    pool, org_id: str, q, classification, department_id, page: int, per_page: int,
):
    """get_drive_filesのDB処理（同期版）→ asyncio.to_thread()で呼ぶ"""
    with pool.connect() as conn:
        conn.execute(
            text("SELECT set_config('app.current_organization_id', :org_id, true)"),
            {"org_id": org_id},
        )
        where_clauses = [
            "organization_id = :org_id",
            "google_drive_file_id IS NOT NULL",
            "is_active = TRUE",
        ]
        params: dict = {"org_id": org_id}

        if q:
            where_clauses.append("(title ILIKE :q OR file_name ILIKE :q)")
            params["q"] = f"%{_escape_like(q)}%"
        if classification:
            where_clauses.append("classification = :classification")
            params["classification"] = classification
        if department_id:
            where_clauses.append("department_id = CAST(:dept_id AS UUID)")
            params["dept_id"] = department_id

        # where_clausesの全要素は固定文字列のみ。ユーザー入力は全てバインドパラメータ経由（SQLインジェクション安全）
        where_sql = " AND ".join(where_clauses)

        count_row = conn.execute(
            text(f"SELECT COUNT(*) FROM soulkun.documents WHERE {where_sql}"),
            params,
        ).fetchone()
        total = count_row[0] if count_row else 0

        offset = (page - 1) * per_page
        params["limit"] = per_page
        params["offset"] = offset

        rows = conn.execute(
            text(f"""
                SELECT
                    id::text,
                    title,
                    file_name,
                    file_type,
                    file_size_bytes,
                    classification,
                    category,
                    google_drive_file_id,
                    google_drive_web_view_link,
                    google_drive_last_modified::text,
                    processing_status,
                    updated_at::text
                FROM soulkun.documents
                WHERE {where_sql}
                ORDER BY google_drive_last_modified DESC NULLS LAST
                LIMIT :limit OFFSET :offset
            """),
            params,
        ).fetchall()

    return rows, total


def _sync_get_drive_sync_status(pool, org_id: str):
    """get_drive_sync_statusのDB処理（同期版）→ asyncio.to_thread()で呼ぶ"""
    with pool.connect() as conn:
        conn.execute(
            text("SELECT set_config('app.current_organization_id', :org_id, true)"),
            {"org_id": org_id},
        )
        row = conn.execute(
            text("""
                SELECT
                    COUNT(*) AS total_files,
                    MAX(updated_at)::text AS last_synced_at,
                    COUNT(*) FILTER (WHERE processing_status = 'failed') AS failed_count
                FROM soulkun.documents
                WHERE organization_id = :org_id
                  AND google_drive_file_id IS NOT NULL
                  AND is_active = TRUE
            """),
            {"org_id": org_id},
        ).fetchone()
    return row


def _sync_get_drive_file_info(pool, org_id: str, document_id: str):
    """download_drive_fileのDB処理（同期版）→ asyncio.to_thread()で呼ぶ"""
    with pool.connect() as conn:
        conn.execute(
            text("SELECT set_config('app.current_organization_id', :org_id, true)"),
            {"org_id": org_id},
        )
        row = conn.execute(
            text("""
                SELECT google_drive_file_id, file_name, file_type
                FROM soulkun.documents
                WHERE id = CAST(:doc_id AS UUID)
                  AND organization_id = :org_id
                  AND is_active = TRUE
                LIMIT 1
            """),
            {"doc_id": document_id, "org_id": org_id},
        ).fetchone()
    return row


def _sync_record_drive_upload(
    pool, org_id: str, original_name: str, ext: str, content_size: int,
    classification: str, drive_file_id: str, web_view_link, user_id: str,
):
    """upload_drive_fileのDB処理（同期版）→ asyncio.to_thread()で呼ぶ"""
    with pool.connect() as conn:
        conn.execute(
            text("SELECT set_config('app.current_organization_id', :org_id, true)"),
            {"org_id": org_id},
        )
        row = conn.execute(
            text("""
                INSERT INTO soulkun.documents (
                    organization_id, title, file_name, file_type,
                    file_size_bytes, classification, google_drive_file_id,
                    google_drive_web_view_link, processing_status, is_active,
                    created_by, updated_by
                ) VALUES (
                    CAST(:org_id AS UUID), :title, :file_name, :file_type,
                    :file_size, :classification, :drive_file_id,
                    :web_view_link, 'sync_pending', TRUE,
                    CAST(:user_id AS UUID), CAST(:user_id AS UUID)
                )
                RETURNING id::text
            """),
            {
                "org_id": org_id,
                "title": original_name.rsplit(".", 1)[0] if "." in original_name else original_name,
                "file_name": original_name,
                "file_type": ext,
                "file_size": content_size,
                "classification": classification,
                "drive_file_id": drive_file_id,
                "web_view_link": web_view_link,
                "user_id": user_id,
            },
        ).fetchone()
        conn.commit()
    return row[0] if row else None


# =============================================================================
# ファイル一覧
# =============================================================================


@router.get(
    "/drive/files",
    response_model=DriveFilesResponse,
)
async def get_drive_files(
    q: Optional[str] = Query(None, description="キーワード検索（ファイル名・タイトル）"),
    classification: Optional[str] = Query(None, description="機密区分: public/internal/restricted/confidential"),
    department_id: Optional[str] = Query(None, description="部署UUID"),
    page: int = Query(1, ge=1, description="ページ番号"),
    per_page: int = Query(20, ge=1, le=100, description="1ページあたりの件数"),
    user=Depends(require_admin),
):
    """Driveファイル一覧を取得（DBから高速取得）"""
    organization_id = user.organization_id
    pool = get_db_pool()

    # 機密区分バリデーション
    valid_classifications = {"public", "internal", "restricted", "confidential"}
    if classification and classification not in valid_classifications:
        raise HTTPException(status_code=400, detail="classificationの値が不正です")

    try:
        rows, total = await asyncio.to_thread(
            _sync_list_drive_files,
            pool, organization_id, q, classification, department_id, page, per_page,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Drive files list error")
        raise HTTPException(status_code=500, detail="ファイル一覧の取得に失敗しました")

    files = [
        DriveFileItem(
            id=row[0],
            title=row[1],
            file_name=row[2],
            file_type=row[3],
            file_size_bytes=row[4],
            classification=row[5],
            category=row[6],
            google_drive_file_id=row[7],
            google_drive_web_view_link=row[8],
            google_drive_last_modified=row[9],
            processing_status=row[10],
            updated_at=row[11],
        )
        for row in rows
    ]

    log_audit_event(
        logger=logger,
        action="drive_files_listed",
        resource_type="drive",
        resource_id="files",
        user_id=user.user_id,
        details={"org_id": organization_id, "total": total},
    )

    return DriveFilesResponse(
        files=files,
        total=total,
        page=page,
        per_page=per_page,
    )


# =============================================================================
# 同期状態
# =============================================================================


@router.get(
    "/drive/sync-status",
    response_model=DriveSyncStatusResponse,
)
async def get_drive_sync_status(
    user=Depends(require_admin),
):
    """Drive同期状態（最終同期日時・総件数・エラー件数）を取得"""
    organization_id = user.organization_id
    pool = get_db_pool()

    try:
        row = await asyncio.to_thread(_sync_get_drive_sync_status, pool, organization_id)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Drive sync status error")
        raise HTTPException(status_code=500, detail="同期状態の取得に失敗しました")

    if not row:
        return DriveSyncStatusResponse()

    return DriveSyncStatusResponse(
        total_files=row[0] or 0,
        last_synced_at=row[1],
        failed_count=row[2] or 0,
    )


# =============================================================================
# ファイルダウンロード
# =============================================================================


@router.get("/drive/files/{document_id}/download")
async def download_drive_file(
    document_id: str,
    user=Depends(require_admin),
):
    """指定ドキュメントをDriveからダウンロード（StreamingResponse）"""
    organization_id = user.organization_id
    pool = get_db_pool()

    # DBからgoogle_drive_file_idを取得（mime_typeカラムは存在しないためfile_typeから推定）
    _EXT_TO_MIME = {
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "doc": "application/msword",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "xls": "application/vnd.ms-excel",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "ppt": "application/vnd.ms-powerpoint",
        "txt": "text/plain",
        "md": "text/markdown",
        "csv": "text/csv",
    }

    try:
        row = await asyncio.to_thread(_sync_get_drive_file_info, pool, organization_id, document_id)
    except Exception:
        logger.exception("Drive download DB lookup error")
        raise HTTPException(status_code=500, detail="ファイル情報の取得に失敗しました")

    if not row or not row[0]:
        raise HTTPException(status_code=404, detail="ファイルが見つかりません")

    drive_file_id, file_name, file_type = row[0], row[1], row[2]
    mime_type = _EXT_TO_MIME.get((file_type or "").lower(), "application/octet-stream")

    # Drive APIでダウンロード（_get_drive_clientは同期I/Oのためto_thread経由）
    try:
        drive_client = await asyncio.to_thread(_get_drive_client)
        content: bytes = await drive_client.download_file(drive_file_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Drive download failed: %s", type(e).__name__)
        raise HTTPException(status_code=502, detail="ファイルのダウンロードに失敗しました")

    # レスポンス用ファイル名を安全にサニタイズ（RFC 5987: 日本語対応）
    import urllib.parse
    raw_name = file_name or f"file.{file_type or 'bin'}"
    safe_name = raw_name.replace('"', "").replace("\n", "").replace("\r", "")
    encoded_name = urllib.parse.quote(safe_name, safe="")
    content_type = mime_type

    log_audit_event(
        logger=logger,
        action="drive_file_downloaded",
        resource_type="drive",
        resource_id=document_id,
        user_id=user.user_id,
        details={"org_id": organization_id},
    )

    return StreamingResponse(
        iter([content]),
        media_type=content_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}",
        },
    )


# =============================================================================
# ファイルアップロード（Level 6以上のみ）
# =============================================================================


@router.post(
    "/drive/upload",
    response_model=DriveUploadResponse,
)
async def upload_drive_file(
    file: UploadFile = File(..., description="アップロードするファイル"),
    classification: str = Form(..., description="機密区分: public/internal/restricted/confidential"),
    folder_id: Optional[str] = Form(None, description="アップロード先フォルダID（省略時はデフォルト）"),
    user=Depends(require_editor),
):
    """ファイルをGoogle Driveにアップロードし、documentsテーブルに記録する（Level 6以上）"""
    organization_id = user.organization_id

    # 機密区分バリデーション
    valid_classifications = {"public", "internal", "restricted", "confidential"}
    if classification not in valid_classifications:
        raise HTTPException(status_code=400, detail="classificationの値が不正です")

    # ファイル名・拡張子バリデーション
    original_name = file.filename or "unknown"
    ext = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"許可されていないファイル形式です。対応形式: {', '.join(sorted(_ALLOWED_EXTENSIONS))}",
        )

    # MIMEタイプバリデーション（Content-Type未指定も拒否）
    content_type = file.content_type or ""
    if not content_type or content_type not in _ALLOWED_MIME_TYPES:
        raise HTTPException(status_code=400, detail="許可されていないファイル種別です")

    # ファイルサイズバリデーション（20MB上限）
    content = await file.read()
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"ファイルサイズが上限（20MB）を超えています（{len(content) // 1024 // 1024}MB）",
        )
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="空のファイルはアップロードできません")

    # アップロード先フォルダID決定
    target_folder = folder_id or _UPLOAD_FOLDER_ID or None

    # Drive APIでアップロード（_get_drive_clientは同期I/Oのためto_thread経由）
    try:
        drive_client = await asyncio.to_thread(_get_drive_client, True)
        drive_file = await drive_client.upload_file(
            file_name=original_name,
            mime_type=content_type or "application/octet-stream",
            content=content,
            folder_id=target_folder,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Drive upload failed: %s", type(e).__name__)
        raise HTTPException(status_code=502, detail="Google Driveへのアップロードに失敗しました")

    # documentsテーブルに記録
    pool = get_db_pool()
    try:
        document_id = await asyncio.to_thread(
            _sync_record_drive_upload,
            pool, organization_id, original_name, ext, len(content),
            classification, drive_file.id, drive_file.web_view_link, user.user_id,
        )
    except Exception:
        logger.exception("Drive upload DB record error")
        # Drive側にアップロード済みなのでエラーは警告のみ（後でウォッチャーが拾う）
        logger.warning("Drive upload succeeded but DB record failed for file_id=%s", drive_file.id)
        # DB記録失敗は区別できる監査ログを残す
        log_audit_event(
            logger=logger,
            action="drive_file_uploaded_db_failed",
            resource_type="drive",
            resource_id=drive_file.id,
            user_id=user.user_id,
            details={"org_id": organization_id, "classification": classification},
        )
        return DriveUploadResponse(
            document_id=None,
            google_drive_file_id=drive_file.id,
            google_drive_web_view_link=drive_file.web_view_link,
        )

    log_audit_event(
        logger=logger,
        action="drive_file_uploaded",
        resource_type="drive",
        resource_id=drive_file.id,
        user_id=user.user_id,
        details={"org_id": organization_id, "classification": classification},
    )

    return DriveUploadResponse(
        document_id=document_id,
        google_drive_file_id=drive_file.id,
        google_drive_web_view_link=drive_file.web_view_link,
    )


# =============================================================================
# Pinecone メタデータ同期
# =============================================================================


@router.post(
    "/sync-pinecone-metadata",
    response_model=PineconeSyncResponse,
    summary="Pineconeメタデータ同期",
    description="DBのdocument_chunksとPineconeのメタデータ（機密区分・部署ID）を同期する。Level 5以上のみ実行可能。",
)
async def sync_pinecone_metadata(
    user=Depends(require_admin),
):
    """
    DBとPineconeのメタデータ（classification, department_id）を全件同期する。

    用途:
    - Google Driveでファイルが別フォルダに移動した後の手動同期
    - 定期的なデータ整合性確認
    - Cloud Schedulerからの自動実行

    セキュリティ: require_admin (Level 5以上のみ)
    """
    organization_id = user.organization_id

    try:
        from lib.pinecone_client import PineconeClient
        from lib.pinecone_metadata_sync import sync_all_pinecone_metadata

        pool = get_db_pool()
        pinecone_client = PineconeClient()

        result = await sync_all_pinecone_metadata(pool, organization_id, pinecone_client)

        log_audit_event(
            logger=logger,
            action="pinecone_metadata_sync",
            resource_type="pinecone",
            resource_id="all",
            user_id=user.user_id,
            details={
                "org_id": organization_id,
                "total_checked": result.total_chunks_checked,
                "updated": result.updated_count,
                "errors": result.error_count,
            },
        )

        return PineconeSyncResponse(
            status="success" if result.success else "partial_failure",
            message=f"{result.updated_count}/{result.total_chunks_checked} チャンクを同期しました",
            org_id=organization_id,
            total_chunks_checked=result.total_chunks_checked,
            updated_count=result.updated_count,
            error_count=result.error_count,
        )

    except Exception as e:
        logger.error("Pinecone sync endpoint error (org=%s): %s", organization_id, type(e).__name__)
        raise HTTPException(status_code=500, detail="Pineconeメタデータ同期に失敗しました")
