"""
pytest 共通フィクスチャ

テスト全体で共有するフィクスチャを定義します。
"""

import os
import sys
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ================================================================
# 環境変数のモック
# ================================================================

@pytest.fixture(autouse=True)
def mock_env_vars(monkeypatch):
    """テスト用の環境変数を設定"""
    monkeypatch.setenv("PROJECT_ID", "test-project")
    monkeypatch.setenv("DB_HOST", "localhost")
    monkeypatch.setenv("DB_NAME", "test_db")
    monkeypatch.setenv("DB_USER", "test_user")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("PINECONE_API_KEY", "test-pinecone-key")
    monkeypatch.setenv("PINECONE_INDEX_NAME", "test-index")
    monkeypatch.setenv("ORGANIZATION_ID", "org_test")
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("DEBUG", "true")


# ================================================================
# データベースモック
# ================================================================

@pytest.fixture
def mock_db_pool():
    """DBプールのモック"""
    pool = MagicMock()
    conn = MagicMock()
    pool.connect.return_value.__enter__ = MagicMock(return_value=conn)
    pool.connect.return_value.__exit__ = MagicMock(return_value=None)
    return pool


@pytest.fixture
def mock_async_db_conn():
    """非同期DBコネクションのモック"""
    conn = AsyncMock()
    conn.execute = AsyncMock()
    conn.commit = AsyncMock()
    return conn


# ================================================================
# Gemini Embedding モック（v10.12.0: OpenAI → Gemini に変更）
# ================================================================

@pytest.fixture
def mock_openai_embedding():
    """Gemini Embedding APIのモック（後方互換のため名前は維持）"""
    with patch('lib.embedding.genai') as mock_genai:
        # embed_contentのモック（768次元）
        mock_genai.embed_content.return_value = {
            'embedding': [0.1] * 768
        }

        yield {
            'genai': mock_genai,
            'response': {'embedding': [0.1] * 768},
        }


# ================================================================
# Pinecone モック
# ================================================================

@pytest.fixture
def mock_pinecone():
    """Pinecone APIのモック"""
    with patch('lib.pinecone_client.Pinecone') as mock_pc:
        pc_instance = MagicMock()
        index = MagicMock()

        # クエリ結果のモック
        query_response = MagicMock()
        query_response.matches = [
            MagicMock(
                id="org_test_doc1_v1_chunk0",
                score=0.95,
                metadata={
                    "document_id": "doc1",
                    "classification": "internal",
                    "category": "B",
                    "title": "テストドキュメント"
                }
            ),
            MagicMock(
                id="org_test_doc2_v1_chunk0",
                score=0.85,
                metadata={
                    "document_id": "doc2",
                    "classification": "internal",
                    "category": "A",
                    "title": "理念ドキュメント"
                }
            )
        ]
        index.query.return_value = query_response
        index.upsert.return_value = MagicMock(upserted_count=1)
        index.delete.return_value = None

        pc_instance.Index.return_value = index
        mock_pc.return_value = pc_instance

        yield {
            'client': mock_pc,
            'index': index,
            'query_response': query_response,
        }


# ================================================================
# Google Drive モック
# ================================================================

@pytest.fixture
def mock_google_drive():
    """Google Drive APIのモック"""
    with patch('lib.google_drive.build') as mock_build:
        service = MagicMock()

        # files().get()
        files_get = MagicMock()
        files_get.execute.return_value = {
            'id': 'file123',
            'name': 'テスト.pdf',
            'mimeType': 'application/pdf',
            'size': 1024,
            'modifiedTime': '2026-01-15T10:00:00.000Z',
            'webViewLink': 'https://drive.google.com/file/d/file123/view',
            'parents': ['folder123']
        }
        service.files.return_value.get.return_value = files_get

        # changes().list()
        changes_list = MagicMock()
        changes_list.execute.return_value = {
            'changes': [],
            'newStartPageToken': 'token_abc123'
        }
        service.changes.return_value.list.return_value = changes_list

        # changes().getStartPageToken()
        start_token = MagicMock()
        start_token.execute.return_value = {'startPageToken': 'token_start'}
        service.changes.return_value.getStartPageToken.return_value = start_token

        mock_build.return_value = service

        yield {
            'build': mock_build,
            'service': service,
        }


# ================================================================
# テストデータ
# ================================================================

@pytest.fixture
def sample_document():
    """サンプルドキュメントデータ"""
    return {
        "id": "doc_test_001",
        "organization_id": "org_test",
        "title": "経費精算マニュアル",
        "file_name": "経費精算マニュアル.pdf",
        "file_type": "pdf",
        "file_size_bytes": 102400,
        "file_hash": "abc123def456",
        "category": "B",
        "classification": "internal",
        "department_id": None,
        "current_version": 1,
        "total_chunks": 5,
        "total_pages": 10,
        "processing_status": "completed",
        "is_active": True,
        "is_searchable": True,
        "google_drive_file_id": "gdrive_file_123",
        "google_drive_folder_path": ["ソウルシンクス", "マニュアル"],
        "google_drive_web_view_link": "https://drive.google.com/file/d/gdrive_file_123/view",
        "created_at": datetime.now(),
        "updated_at": datetime.now(),
    }


@pytest.fixture
def sample_chunk():
    """サンプルチャンクデータ"""
    return {
        "id": "chunk_test_001",
        "organization_id": "org_test",
        "document_id": "doc_test_001",
        "document_version_id": "version_test_001",
        "chunk_index": 0,
        "pinecone_id": "org_test_doc_test_001_v1_chunk0",
        "pinecone_namespace": "org_org_test",
        "content": "経費精算の手順は以下の通りです。\n1. 申請書を作成\n2. 領収書を添付\n3. 上長の承認を得る",
        "content_hash": "hash123",
        "char_count": 50,
        "page_number": 1,
        "section_title": "1. 経費精算の基本",
        "section_hierarchy": ["第1章 経費精算", "1. 経費精算の基本"],
        "start_position": 0,
        "end_position": 50,
        "embedding_model": "text-embedding-3-small",
        "is_indexed": True,
    }


@pytest.fixture
def sample_search_request():
    """サンプル検索リクエスト"""
    return {
        "query": "経費精算の手順を教えてください",
        "categories": ["B"],
        "top_k": 5,
        "include_content": True,
        "generate_answer": False,
        "source": "api",
    }


@pytest.fixture
def sample_user_context():
    """サンプルユーザーコンテキスト"""
    from api.app.services.knowledge_search import UserContext
    return UserContext(
        user_id="user_test_001",
        organization_id="org_test",
        department_id=None,
        accessible_classifications=["public", "internal"],
        accessible_department_ids=[],
    )


# ================================================================
# ファイルコンテンツ
# ================================================================

@pytest.fixture
def sample_text_content():
    """サンプルテキストコンテンツ"""
    return """経費精算マニュアル

第1章 経費精算の基本

1.1 概要
本マニュアルでは、経費精算の手順について説明します。

1.2 対象者
全社員が対象です。

第2章 申請手順

2.1 申請書の作成
以下の手順で申請書を作成してください。
1. 経費精算システムにログイン
2. 「新規申請」ボタンをクリック
3. 必要事項を入力

2.2 領収書の添付
領収書は必ず原本を添付してください。
"""


@pytest.fixture
def sample_pdf_bytes():
    """サンプルPDFバイト（最小限のPDF構造）"""
    # 実際のテストでは適切なPDFファイルを使用
    return b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF"
