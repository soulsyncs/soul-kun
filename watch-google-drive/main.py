"""
Googleドライブ監視ジョブ Cloud Function

Googleドライブのファイル変更を監視し、ソウルくんのナレッジDBに反映します。
Cloud Schedulerから5分ごとに呼び出されます。

デプロイ:
    gcloud functions deploy watch_google_drive \
        --runtime python311 \
        --trigger-http \
        --allow-unauthenticated=false \
        --timeout=540 \
        --memory=512MB \
        --region=asia-northeast1 \
        --env-vars-file=env-vars.yaml

設計ドキュメント:
    docs/06_phase3_google_drive_integration.md
"""

import os
import sys
import json
import uuid
import asyncio
from datetime import datetime
from typing import Optional
import hashlib
import logging

import functions_framework
from flask import Request

# PostgreSQL配列リテラル変換ユーティリティ
def to_pg_array(python_list: list) -> str:
    """
    Python リストを PostgreSQL 配列リテラル形式に変換

    Args:
        python_list: Python リスト

    Returns:
        PostgreSQL 配列リテラル文字列 (例: '{"item1", "item2"}')

    Note:
        SQLAlchemy + pg8000 では Python リストを直接 TEXT[] に渡せないため、
        配列リテラル形式の文字列に変換する必要がある。
    """
    if not python_list:
        return '{}'
    # 各要素をエスケープしてダブルクォートで囲む
    escaped = []
    for item in python_list:
        if item is None:
            escaped.append('NULL')
        else:
            # ダブルクォートとバックスラッシュをエスケープ
            str_item = str(item).replace('\\', '\\\\').replace('"', '\\"')
            escaped.append(f'"{str_item}"')
    return '{' + ','.join(escaped) + '}'

# Cloud Functions デプロイ時はlibが同じディレクトリにある
# ローカル開発時はプロジェクトルートから参照
current_dir = os.path.dirname(os.path.abspath(__file__))
if os.path.exists(os.path.join(current_dir, 'lib')):
    sys.path.insert(0, current_dir)
else:
    sys.path.insert(0, os.path.dirname(current_dir))

from lib.google_drive import (
    GoogleDriveClient,
    DriveFile,
    DriveChange,
    FolderMapper,
)
from lib.document_processor import (
    DocumentProcessor,
    ExtractedDocument,
    Chunk,
)
from lib.embedding import EmbeddingClient
from lib.pinecone_client import PineconeClient
from lib.db import get_db_pool
from lib.secrets import get_secret

from sqlalchemy import text


# ================================================================
# 設定
# ================================================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 環境変数
ORGANIZATION_ID = os.getenv('ORGANIZATION_ID', 'org_soulsyncs')
ROOT_FOLDER_ID = os.getenv('ROOT_FOLDER_ID')
CHUNK_SIZE = int(os.getenv('CHUNK_SIZE', '1000'))
CHUNK_OVERLAP = int(os.getenv('CHUNK_OVERLAP', '200'))


# ================================================================
# データベース操作
# ================================================================

class DatabaseOperations:
    """データベース操作クラス"""

    def __init__(self, pool):
        self.pool = pool

    def get_sync_state(
        self,
        organization_id: str,
        root_folder_id: str
    ) -> Optional[dict]:
        """同期状態を取得"""
        with self.pool.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT page_token, last_sync_at
                    FROM google_drive_sync_state
                    WHERE organization_id = :org_id
                      AND root_folder_id = :folder_id
                """),
                {"org_id": organization_id, "folder_id": root_folder_id}
            )
            row = result.fetchone()
            if row:
                return {
                    "page_token": row[0],
                    "last_sync_at": row[1]
                }
            return None

    def update_sync_state(
        self,
        organization_id: str,
        root_folder_id: str,
        page_token: str,
        sync_log_id: str
    ):
        """同期状態を更新"""
        with self.pool.connect() as conn:
            conn.execute(
                text("""
                    INSERT INTO google_drive_sync_state
                        (organization_id, root_folder_id, page_token, last_sync_at, last_sync_id)
                    VALUES
                        (:org_id, :folder_id, :token, NOW(), :sync_id)
                    ON CONFLICT (organization_id, root_folder_id)
                    DO UPDATE SET
                        page_token = EXCLUDED.page_token,
                        last_sync_at = EXCLUDED.last_sync_at,
                        last_sync_id = EXCLUDED.last_sync_id,
                        updated_at = NOW()
                """),
                {
                    "org_id": organization_id,
                    "folder_id": root_folder_id,
                    "token": page_token,
                    "sync_id": sync_log_id
                }
            )
            conn.commit()

    def create_sync_log(
        self,
        organization_id: str,
        sync_id: str,
        sync_type: str,
        root_folder_id: str,
        start_page_token: Optional[str]
    ) -> str:
        """同期ログを作成"""
        log_id = str(uuid.uuid4())
        with self.pool.connect() as conn:
            conn.execute(
                text("""
                    INSERT INTO google_drive_sync_logs
                        (id, organization_id, sync_id, sync_type,
                         root_folder_id, start_page_token, status)
                    VALUES
                        (:id, :org_id, :sync_id, :sync_type,
                         :folder_id, :token, 'in_progress')
                """),
                {
                    "id": log_id,
                    "org_id": organization_id,
                    "sync_id": sync_id,
                    "sync_type": sync_type,
                    "folder_id": root_folder_id,
                    "token": start_page_token
                }
            )
            conn.commit()
        return log_id

    def update_sync_log(
        self,
        log_id: str,
        status: str,
        files_checked: int = 0,
        files_added: int = 0,
        files_updated: int = 0,
        files_deleted: int = 0,
        files_skipped: int = 0,
        files_failed: int = 0,
        new_page_token: Optional[str] = None,
        error_message: Optional[str] = None,
        failed_files: Optional[list] = None
    ):
        """同期ログを更新"""
        with self.pool.connect() as conn:
            conn.execute(
                text("""
                    UPDATE google_drive_sync_logs
                    SET status = :status,
                        files_checked = :checked,
                        files_added = :added,
                        files_updated = :updated,
                        files_deleted = :deleted,
                        files_skipped = :skipped,
                        files_failed = :failed,
                        new_page_token = :new_token,
                        error_message = :error_msg,
                        failed_files = :failed_files::jsonb,
                        completed_at = NOW(),
                        duration_ms = EXTRACT(EPOCH FROM (NOW() - started_at)) * 1000
                    WHERE id = :id
                """),
                {
                    "id": log_id,
                    "status": status,
                    "checked": files_checked,
                    "added": files_added,
                    "updated": files_updated,
                    "deleted": files_deleted,
                    "skipped": files_skipped,
                    "failed": files_failed,
                    "new_token": new_page_token,
                    "error_msg": error_message,
                    "failed_files": json.dumps(failed_files) if failed_files else None
                }
            )
            conn.commit()

    def get_document_by_drive_id(
        self,
        organization_id: str,
        google_drive_file_id: str
    ) -> Optional[dict]:
        """Googleドライブファイルに対応するドキュメントを取得"""
        with self.pool.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT id, current_version, file_hash, google_drive_last_modified
                    FROM documents
                    WHERE organization_id = :org_id
                      AND google_drive_file_id = :file_id
                      AND deleted_at IS NULL
                """),
                {"org_id": organization_id, "file_id": google_drive_file_id}
            )
            row = result.fetchone()
            if row:
                return {
                    "id": str(row[0]),
                    "current_version": row[1],
                    "file_hash": row[2],
                    "google_drive_last_modified": row[3]
                }
            return None

    def create_document(
        self,
        organization_id: str,
        title: str,
        file_name: str,
        file_type: str,
        file_size_bytes: int,
        file_hash: str,
        category: str,
        classification: str,
        department_id: Optional[str],
        google_drive_file_id: str,
        google_drive_folder_path: list[str],
        google_drive_web_view_link: Optional[str],
        google_drive_last_modified: Optional[datetime]
    ) -> str:
        """ドキュメントを作成"""
        doc_id = str(uuid.uuid4())
        with self.pool.connect() as conn:
            # PostgreSQL配列リテラル形式に変換
            folder_path_pg = to_pg_array(google_drive_folder_path)

            conn.execute(
                text("""
                    INSERT INTO documents
                        (id, organization_id, title, file_name, file_type,
                         file_size_bytes, file_hash, category, classification,
                         department_id, google_drive_file_id, google_drive_folder_path,
                         google_drive_web_view_link, google_drive_last_modified,
                         processing_status)
                    VALUES
                        (:id, :org_id, :title, :file_name, :file_type,
                         :file_size, :file_hash, :category, :classification,
                         :dept_id, :drive_id, :folder_path::TEXT[],
                         :web_link, :last_modified,
                         'processing')
                """),
                {
                    "id": doc_id,
                    "org_id": organization_id,
                    "title": title,
                    "file_name": file_name,
                    "file_type": file_type,
                    "file_size": file_size_bytes,
                    "file_hash": file_hash,
                    "category": category,
                    "classification": classification,
                    "dept_id": department_id,
                    "drive_id": google_drive_file_id,
                    "folder_path": folder_path_pg,
                    "web_link": google_drive_web_view_link,
                    "last_modified": google_drive_last_modified
                }
            )
            conn.commit()
        return doc_id

    def create_document_version(
        self,
        organization_id: str,
        document_id: str,
        version_number: int,
        file_name: str,
        file_hash: str,
        file_size_bytes: int,
        pinecone_namespace: str
    ) -> str:
        """ドキュメントバージョンを作成"""
        version_id = str(uuid.uuid4())
        with self.pool.connect() as conn:
            conn.execute(
                text("""
                    INSERT INTO document_versions
                        (id, organization_id, document_id, version_number,
                         file_name, file_hash, file_size_bytes,
                         pinecone_namespace, is_latest, processing_status)
                    VALUES
                        (:id, :org_id, :doc_id, :version,
                         :file_name, :file_hash, :file_size,
                         :namespace, TRUE, 'processing')
                """),
                {
                    "id": version_id,
                    "org_id": organization_id,
                    "doc_id": document_id,
                    "version": version_number,
                    "file_name": file_name,
                    "file_hash": file_hash,
                    "file_size": file_size_bytes,
                    "namespace": pinecone_namespace
                }
            )
            conn.commit()
        return version_id

    def create_document_chunk(
        self,
        organization_id: str,
        document_id: str,
        document_version_id: str,
        chunk_index: int,
        pinecone_id: str,
        pinecone_namespace: str,
        content: str,
        content_hash: str,
        char_count: int,
        page_number: Optional[int],
        section_title: Optional[str],
        section_hierarchy: list[str],
        start_position: int,
        end_position: int,
        embedding_model: str
    ) -> str:
        """ドキュメントチャンクを作成"""
        chunk_id = str(uuid.uuid4())
        with self.pool.connect() as conn:
            # PostgreSQL配列リテラル形式に変換
            section_hierarchy_pg = to_pg_array(section_hierarchy)

            # is_indexed=FALSE で登録（Pinecone upsert成功後に TRUE に更新）
            conn.execute(
                text("""
                    INSERT INTO document_chunks
                        (id, organization_id, document_id, document_version_id,
                         chunk_index, pinecone_id, pinecone_namespace,
                         content, content_hash, char_count,
                         page_number, section_title, section_hierarchy,
                         start_position, end_position, embedding_model,
                         is_indexed)
                    VALUES
                        (:id, :org_id, :doc_id, :version_id,
                         :chunk_index, :pinecone_id, :namespace,
                         :content, :content_hash, :char_count,
                         :page_number, :section_title, :section_hierarchy::TEXT[],
                         :start_pos, :end_pos, :embedding_model,
                         FALSE)
                """),
                {
                    "id": chunk_id,
                    "org_id": organization_id,
                    "doc_id": document_id,
                    "version_id": document_version_id,
                    "chunk_index": chunk_index,
                    "pinecone_id": pinecone_id,
                    "namespace": pinecone_namespace,
                    "content": content,
                    "content_hash": content_hash,
                    "char_count": char_count,
                    "page_number": page_number,
                    "section_title": section_title,
                    "section_hierarchy": section_hierarchy_pg,
                    "start_pos": start_position,
                    "end_pos": end_position,
                    "embedding_model": embedding_model
                }
            )
            conn.commit()
        return chunk_id

    def update_document_status(
        self,
        document_id: str,
        status: str,
        total_chunks: int = 0,
        total_pages: int = 0,
        error: Optional[str] = None
    ):
        """ドキュメントのステータスを更新"""
        with self.pool.connect() as conn:
            conn.execute(
                text("""
                    UPDATE documents
                    SET processing_status = :status,
                        total_chunks = :chunks,
                        total_pages = :pages,
                        processing_error = :error,
                        processed_at = CASE WHEN :status = 'completed' THEN NOW() ELSE processed_at END,
                        updated_at = NOW()
                    WHERE id = :id
                """),
                {
                    "id": document_id,
                    "status": status,
                    "chunks": total_chunks,
                    "pages": total_pages,
                    "error": error
                }
            )
            conn.commit()

    def soft_delete_document(self, document_id: str):
        """ドキュメントを論理削除"""
        with self.pool.connect() as conn:
            conn.execute(
                text("""
                    UPDATE documents
                    SET deleted_at = NOW(),
                        is_active = FALSE,
                        is_searchable = FALSE,
                        updated_at = NOW()
                    WHERE id = :id
                """),
                {"id": document_id}
            )
            conn.commit()

    def mark_chunks_indexed(self, document_id: str, version_number: int):
        """
        チャンクの is_indexed フラグを TRUE に設定

        Pinecone upsert 成功後に呼び出す
        """
        with self.pool.connect() as conn:
            conn.execute(
                text("""
                    UPDATE document_chunks dc
                    SET is_indexed = TRUE,
                        indexed_at = NOW(),
                        updated_at = NOW()
                    FROM document_versions dv
                    WHERE dc.document_version_id = dv.id
                      AND dv.document_id = :doc_id
                      AND dv.version_number = :version
                """),
                {"doc_id": document_id, "version": version_number}
            )
            conn.commit()

    def mark_chunks_not_indexed(self, document_id: str, version_number: int):
        """
        チャンクの is_indexed フラグを FALSE に設定

        Pinecone upsert 失敗時に呼び出す
        """
        with self.pool.connect() as conn:
            conn.execute(
                text("""
                    UPDATE document_chunks dc
                    SET is_indexed = FALSE,
                        index_error = 'Pinecone upsert failed',
                        updated_at = NOW()
                    FROM document_versions dv
                    WHERE dc.document_version_id = dv.id
                      AND dv.document_id = :doc_id
                      AND dv.version_number = :version
                """),
                {"doc_id": document_id, "version": version_number}
            )
            conn.commit()


# ================================================================
# ファイル処理
# ================================================================

async def process_file(
    file: DriveFile,
    folder_path: list[str],
    db_ops: DatabaseOperations,
    drive_client: GoogleDriveClient,
    doc_processor: DocumentProcessor,
    embedding_client: EmbeddingClient,
    pinecone_client: PineconeClient,
    folder_mapper: FolderMapper,
    organization_id: str
) -> dict:
    """
    ファイルを処理してナレッジDBに登録

    処理フロー:
    1. スキップチェック
    2. ファイルダウンロード・ハッシュ比較
    3. テキスト抽出・チャンク分割
    4. エンベディング生成
    5. DB登録（ドキュメント、バージョン、チャンク）
    6. Pinecone upsert
    7. ステータス更新

    エラーハンドリング:
    - Pinecone upsert 失敗時はドキュメントのステータスを 'failed' に更新
    - チャンクの is_indexed フラグを FALSE に設定
    - 次回の同期で再処理されるように整合性を維持

    Returns:
        {"status": "added" | "updated" | "skipped" | "failed", "reason": str}
    """
    document_id = None  # エラーハンドリング用に先に定義
    new_version = None
    status = None

    try:
        # スキップチェック
        should_skip, skip_reason = drive_client.should_skip_file(file)
        if should_skip:
            logger.info(f"スキップ: {file.name} - {skip_reason}")
            return {"status": "skipped", "reason": skip_reason}

        # 権限情報を取得
        permissions = folder_mapper.map_folder_to_permissions(folder_path)

        # 既存ドキュメントを確認
        existing_doc = db_ops.get_document_by_drive_id(
            organization_id,
            file.id
        )

        # ファイルをダウンロード
        file_content = await drive_client.download_file(file.id)
        file_hash = hashlib.sha256(file_content).hexdigest()

        # 既存ドキュメントがあり、ハッシュが同じなら更新不要
        if existing_doc and existing_doc.get("file_hash") == file_hash:
            logger.info(f"変更なし: {file.name}")
            return {"status": "skipped", "reason": "ファイル内容に変更なし"}

        # テキスト抽出とチャンク分割
        extracted_doc, chunks = doc_processor.process(
            file_content,
            file.file_extension
        )

        # エンベディング生成（この段階でエラーが発生してもDB変更なし）
        chunk_texts = [chunk.content for chunk in chunks]
        batch_result = embedding_client.embed_texts_sync(chunk_texts)

        # Pinecone namespace
        namespace = pinecone_client.get_namespace(organization_id)

        # 新規登録 or 更新
        if existing_doc:
            # 更新: 新バージョンを作成
            document_id = existing_doc["id"]
            new_version = existing_doc["current_version"] + 1

            # 旧バージョンのベクターを削除（失敗してもDB側は維持）
            try:
                await pinecone_client.delete_document_vectors(
                    organization_id,
                    document_id,
                    existing_doc["current_version"]
                )
            except Exception as e:
                logger.warning(f"旧ベクター削除エラー（続行）: {document_id} v{existing_doc['current_version']} - {str(e)}")

            status = "updated"
        else:
            # 新規登録
            document_id = db_ops.create_document(
                organization_id=organization_id,
                title=file.name.rsplit('.', 1)[0],
                file_name=file.name,
                file_type=file.file_extension,
                file_size_bytes=file.size or len(file_content),
                file_hash=file_hash,
                category=permissions["category"],
                classification=permissions["classification"],
                department_id=permissions["department_id"],
                google_drive_file_id=file.id,
                google_drive_folder_path=folder_path,
                google_drive_web_view_link=file.web_view_link,
                google_drive_last_modified=file.modified_time
            )
            new_version = 1
            status = "added"

        # バージョンを作成
        version_id = db_ops.create_document_version(
            organization_id=organization_id,
            document_id=document_id,
            version_number=new_version,
            file_name=file.name,
            file_hash=file_hash,
            file_size_bytes=file.size or len(file_content),
            pinecone_namespace=namespace
        )

        # チャンクをDBに登録（Pinecone upsert前）
        # is_indexed=FALSE で登録し、Pinecone成功後に TRUE に更新
        pinecone_vectors = []
        chunk_pinecone_ids = []  # ロールバック用に保存

        for i, (chunk, embedding_result) in enumerate(zip(chunks, batch_result.results)):
            pinecone_id = pinecone_client.generate_pinecone_id(
                organization_id,
                document_id,
                new_version,
                i
            )
            chunk_pinecone_ids.append(pinecone_id)

            # DBにチャンクを登録
            db_ops.create_document_chunk(
                organization_id=organization_id,
                document_id=document_id,
                document_version_id=version_id,
                chunk_index=i,
                pinecone_id=pinecone_id,
                pinecone_namespace=namespace,
                content=chunk.content,
                content_hash=chunk.content_hash,
                char_count=chunk.char_count,
                page_number=chunk.page_number,
                section_title=chunk.section_title,
                section_hierarchy=chunk.section_hierarchy,
                start_position=chunk.start_position,
                end_position=chunk.end_position,
                embedding_model=embedding_client.model
            )

            # Pineconeベクターを準備
            pinecone_vectors.append({
                "id": pinecone_id,
                "values": embedding_result.vector,
                "metadata": {
                    "document_id": document_id,
                    "version": new_version,
                    "chunk_index": i,
                    "title": file.name.rsplit('.', 1)[0],
                    "category": permissions["category"],
                    "classification": permissions["classification"],
                    "department_id": permissions["department_id"] or "",
                    "page_number": chunk.page_number or 0,
                    "section_title": chunk.section_title or "",
                }
            })

        # Pineconeにupsert（失敗時はロールバック処理）
        try:
            await pinecone_client.upsert_vectors(
                organization_id,
                pinecone_vectors
            )
        except Exception as pinecone_error:
            # Pinecone失敗時: ドキュメントのステータスを 'failed' に更新
            logger.error(f"Pinecone upsertエラー: {file.name} - {str(pinecone_error)}")

            # チャンクの is_indexed を FALSE に更新（すでにFALSEで登録されているので不要だが念のため）
            db_ops.mark_chunks_not_indexed(document_id, new_version)

            # ドキュメントのステータスを 'failed' に更新
            db_ops.update_document_status(
                document_id,
                "failed",
                total_chunks=len(chunks),
                total_pages=extracted_doc.total_pages or 0,
                error=f"Pinecone upsert failed: {str(pinecone_error)}"
            )

            # 失敗として返す（次回の同期で再処理）
            return {
                "status": "failed",
                "reason": f"Pinecone upsert failed: {str(pinecone_error)}"
            }

        # Pinecone成功: チャンクの is_indexed を TRUE に更新
        db_ops.mark_chunks_indexed(document_id, new_version)

        # ドキュメントのステータスを更新
        db_ops.update_document_status(
            document_id,
            "completed",
            total_chunks=len(chunks),
            total_pages=extracted_doc.total_pages or 0
        )

        logger.info(f"{status}: {file.name} ({len(chunks)} chunks)")
        return {"status": status}

    except Exception as e:
        logger.error(f"処理エラー: {file.name} - {str(e)}")

        # ドキュメントが作成された後のエラーの場合、ステータスを更新
        if document_id:
            try:
                db_ops.update_document_status(
                    document_id,
                    "failed",
                    error=str(e)
                )
            except Exception as db_error:
                logger.error(f"ステータス更新エラー: {document_id} - {str(db_error)}")

        return {"status": "failed", "reason": str(e)}


# ================================================================
# メインハンドラ
# ================================================================

@functions_framework.http
def watch_google_drive(request: Request):
    """
    Googleドライブ監視のHTTPハンドラ

    Cloud Schedulerから5分ごとに呼び出されます。

    リクエストボディ:
    {
        "organization_id": "org_soulsyncs",
        "root_folder_id": "FOLDER_ID",
        "full_sync": false  // オプション: 全ファイル再取り込み
    }
    """
    # リクエストパラメータを取得
    try:
        request_json = request.get_json(silent=True)
    except Exception:
        request_json = {}

    organization_id = (
        request_json.get('organization_id') if request_json else None
    ) or ORGANIZATION_ID

    root_folder_id = (
        request_json.get('root_folder_id') if request_json else None
    ) or ROOT_FOLDER_ID

    full_sync = (
        request_json.get('full_sync', False) if request_json else False
    )

    if not root_folder_id:
        return {
            "error": "root_folder_id is required"
        }, 400

    # 同期IDを生成
    sync_id = f"sync_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    sync_type = "initial" if full_sync else "scheduled"

    logger.info(f"同期開始: {sync_id} (org: {organization_id}, folder: {root_folder_id})")

    # クライアントを初期化
    try:
        db_pool = get_db_pool()
        db_ops = DatabaseOperations(db_pool)
        drive_client = GoogleDriveClient()
        doc_processor = DocumentProcessor(
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP
        )
        embedding_client = EmbeddingClient()
        pinecone_client = PineconeClient()
        folder_mapper = FolderMapper(organization_id)
    except Exception as e:
        logger.error(f"初期化エラー: {str(e)}")
        return {
            "error": f"Initialization failed: {str(e)}"
        }, 500

    # 同期状態を取得
    sync_state = db_ops.get_sync_state(organization_id, root_folder_id)
    start_page_token = sync_state.get("page_token") if sync_state and not full_sync else None

    # 同期ログを作成
    sync_log_id = db_ops.create_sync_log(
        organization_id,
        sync_id,
        sync_type,
        root_folder_id,
        start_page_token
    )

    # 統計
    stats = {
        "checked": 0,
        "added": 0,
        "updated": 0,
        "deleted": 0,
        "skipped": 0,
        "failed": 0
    }
    failed_files = []

    try:
        # asyncio イベントループを取得または作成
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        async def run_sync():
            nonlocal stats, failed_files

            # ページトークンを取得（初回の場合）
            if not start_page_token:
                token = await drive_client.get_start_page_token()
            else:
                token = start_page_token

            # 変更を取得
            if full_sync:
                # フルシンク: フォルダ内の全ファイルを処理
                async for file in drive_client.list_files_in_folder(
                    root_folder_id,
                    recursive=True
                ):
                    stats["checked"] += 1
                    folder_path = await drive_client.get_folder_path(file)

                    result = await process_file(
                        file,
                        folder_path,
                        db_ops,
                        drive_client,
                        doc_processor,
                        embedding_client,
                        pinecone_client,
                        folder_mapper,
                        organization_id
                    )

                    if result["status"] == "added":
                        stats["added"] += 1
                    elif result["status"] == "updated":
                        stats["updated"] += 1
                    elif result["status"] == "skipped":
                        stats["skipped"] += 1
                    elif result["status"] == "failed":
                        stats["failed"] += 1
                        failed_files.append({
                            "file_id": file.id,
                            "file_name": file.name,
                            "error": result.get("reason", "Unknown error")
                        })

                # 新しいページトークンを取得
                new_token = await drive_client.get_start_page_token()
            else:
                # 差分同期: 変更のみ処理
                changes, new_token = await drive_client.get_changes(
                    token,
                    root_folder_id
                )

                for change in changes:
                    stats["checked"] += 1

                    if change.removed or (change.file and change.file.trashed):
                        # 削除されたファイル
                        existing_doc = db_ops.get_document_by_drive_id(
                            organization_id,
                            change.file_id
                        )
                        if existing_doc:
                            db_ops.soft_delete_document(existing_doc["id"])
                            await pinecone_client.delete_document_vectors(
                                organization_id,
                                existing_doc["id"]
                            )
                            stats["deleted"] += 1
                            logger.info(f"削除: {change.file_id}")
                    elif change.file:
                        # 追加または更新されたファイル
                        folder_path = await drive_client.get_folder_path(change.file)

                        result = await process_file(
                            change.file,
                            folder_path,
                            db_ops,
                            drive_client,
                            doc_processor,
                            embedding_client,
                            pinecone_client,
                            folder_mapper,
                            organization_id
                        )

                        if result["status"] == "added":
                            stats["added"] += 1
                        elif result["status"] == "updated":
                            stats["updated"] += 1
                        elif result["status"] == "skipped":
                            stats["skipped"] += 1
                        elif result["status"] == "failed":
                            stats["failed"] += 1
                            failed_files.append({
                                "file_id": change.file_id,
                                "file_name": change.file.name if change.file else "Unknown",
                                "error": result.get("reason", "Unknown error")
                            })

            return new_token

        # 同期を実行
        new_page_token = loop.run_until_complete(run_sync())

        # 同期状態を更新
        db_ops.update_sync_state(
            organization_id,
            root_folder_id,
            new_page_token,
            sync_log_id
        )

        # 同期ログを更新
        status = "completed" if stats["failed"] == 0 else "completed_with_errors"
        db_ops.update_sync_log(
            sync_log_id,
            status=status,
            files_checked=stats["checked"],
            files_added=stats["added"],
            files_updated=stats["updated"],
            files_deleted=stats["deleted"],
            files_skipped=stats["skipped"],
            files_failed=stats["failed"],
            new_page_token=new_page_token,
            failed_files=failed_files if failed_files else None
        )

        logger.info(
            f"同期完了: {sync_id} - "
            f"checked={stats['checked']}, added={stats['added']}, "
            f"updated={stats['updated']}, deleted={stats['deleted']}, "
            f"skipped={stats['skipped']}, failed={stats['failed']}"
        )

        return {
            "sync_id": sync_id,
            "status": status,
            "stats": stats,
            "failed_files": failed_files if failed_files else None
        }, 200

    except Exception as e:
        logger.error(f"同期エラー: {str(e)}")

        # 同期ログを更新
        db_ops.update_sync_log(
            sync_log_id,
            status="failed",
            error_message=str(e)
        )

        return {
            "sync_id": sync_id,
            "status": "failed",
            "error": str(e)
        }, 500
