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
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
# api/app のインポート用にapiディレクトリも追加
sys.path.insert(0, os.path.join(project_root, "api"))


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
# 管理者設定モック（v10.30.1: Phase A）
# ================================================================

@pytest.fixture
def mock_admin_config():
    """lib/admin_config.pyのモック"""
    from lib.admin_config import AdminConfig

    mock_config = AdminConfig(
        organization_id="5f98365f-e7c5-4f48-9918-7fe9aabae5df",
        admin_account_id="1728974",
        admin_name="菊地雅克",
        admin_room_id="405315911",
        admin_room_name="管理部",
        admin_dm_room_id="217825794",
        authorized_room_ids=frozenset([405315911]),
        bot_account_id="10909425",
        is_active=True
    )

    with patch('lib.admin_config.get_admin_config', return_value=mock_config):
        with patch('lib.admin_config._fetch_from_db', return_value=mock_config):
            yield mock_config


@pytest.fixture(autouse=True)
def clear_admin_config_cache_fixture():
    """各テスト後に管理者設定キャッシュをクリア"""
    yield
    try:
        from lib.admin_config import clear_admin_config_cache
        clear_admin_config_cache()
    except ImportError:
        pass


# ================================================================
# Gemini Embedding モック（v10.12.0: OpenAI → Gemini に変更）
# ★★★ v10.25.0: google-genai SDKに対応 ★★★
# ================================================================

@pytest.fixture
def mock_openai_embedding(monkeypatch):
    """Gemini Embedding APIのモック（後方互換のため名前は維持）

    v10.54.5: GOOGLE_AI_API_KEY 環境変数もモック（CI環境対応）
    """
    # 環境変数をモック（APIキーチェックをパス）
    monkeypatch.setenv('GOOGLE_AI_API_KEY', 'mock-api-key-for-testing')

    with patch('lib.embedding.genai') as mock_genai:
        # 新SDK（google-genai）のモック構造
        mock_client = MagicMock()
        mock_genai.Client.return_value = mock_client

        def mock_embed_content(model, contents, config=None):
            """動的にembeddingsを生成するモック関数"""
            mock_response = MagicMock()

            # contentsが文字列（単一）かリスト（バッチ）かで分岐
            if isinstance(contents, str):
                # 単一テキストの場合
                mock_embedding = MagicMock()
                mock_embedding.values = [0.1] * 768
                mock_response.embeddings = [mock_embedding]
            else:
                # バッチ処理の場合
                mock_embeddings = []
                for _ in contents:
                    mock_embedding = MagicMock()
                    mock_embedding.values = [0.1] * 768
                    mock_embeddings.append(mock_embedding)
                mock_response.embeddings = mock_embeddings

            return mock_response

        mock_client.models.embed_content.side_effect = mock_embed_content

        yield {
            'genai': mock_genai,
            'client': mock_client,
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
    try:
        from api.app.services.knowledge_search import UserContext
        return UserContext(
            user_id="user_test_001",
            organization_id="org_test",
            department_id=None,
            accessible_classifications=["public", "internal"],
            accessible_department_ids=[],
        )
    except ImportError:
        # CI環境やAPIモジュールがない場合はスキップ
        pytest.skip("api.app.services.knowledge_search not available")


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


# ================================================================
# Phase 2.5: 目標管理関連フィクスチャ
# ================================================================

@pytest.fixture
def sample_goal():
    """サンプル目標データ"""
    from datetime import date
    return {
        "id": "goal_test_001",
        "organization_id": "org_test",
        "user_id": "user_test_001",
        "department_id": "dept_test_001",
        "parent_goal_id": None,
        "goal_level": "individual",
        "title": "粗利300万円",
        "description": "今月の粗利目標",
        "goal_type": "numeric",
        "target_value": 3000000,
        "current_value": 1500000,
        "unit": "円",
        "deadline": None,
        "period_type": "monthly",
        "period_start": date(2026, 1, 1),
        "period_end": date(2026, 1, 31),
        "status": "active",
        "classification": "internal",
        "created_at": datetime.now(),
        "updated_at": datetime.now(),
    }


@pytest.fixture
def sample_goal_progress():
    """サンプル進捗データ"""
    from datetime import date
    return {
        "id": "progress_test_001",
        "goal_id": "goal_test_001",
        "organization_id": "org_test",
        "progress_date": date.today(),
        "value": 150000,
        "cumulative_value": 1650000,
        "daily_note": "新規案件の契約が取れました",
        "daily_choice": "積極的に提案活動を行いました",
        "ai_feedback": None,
        "ai_feedback_sent_at": None,
        "classification": "internal",
        "created_at": datetime.now(),
        "updated_at": datetime.now(),
    }


@pytest.fixture
def sample_user():
    """サンプルユーザーデータ"""
    return {
        "id": "user_test_001",
        "organization_id": "org_test",
        "display_name": "山田太郎",
        "email": "yamada@example.com",
        "chatwork_account_id": "12345678",
        "chatwork_room_id": "987654321",
    }


@pytest.fixture
def sample_department():
    """サンプル部署データ"""
    return {
        "id": "dept_test_001",
        "organization_id": "org_test",
        "name": "営業部",
        "path": "営業部",
    }


@pytest.fixture
def sample_team_members():
    """サンプルチームメンバーデータ"""
    return [
        {
            "user_id": "user_test_001",
            "user_name": "山田太郎",
            "goals": [
                {
                    "id": "goal_001",
                    "title": "粗利目標",
                    "goal_type": "numeric",
                    "target_value": 3000000,
                    "current_value": 1950000,
                    "unit": "円",
                }
            ]
        },
        {
            "user_id": "user_test_002",
            "user_name": "鈴木花子",
            "goals": [
                {
                    "id": "goal_002",
                    "title": "粗利目標",
                    "goal_type": "numeric",
                    "target_value": 3000000,
                    "current_value": 1500000,
                    "unit": "円",
                }
            ]
        },
        {
            "user_id": "user_test_003",
            "user_name": "田中一郎",
            "goals": [
                {
                    "id": "goal_003",
                    "title": "粗利目標",
                    "goal_type": "numeric",
                    "target_value": 3000000,
                    "current_value": 2200000,
                    "unit": "円",
                }
            ]
        },
    ]


@pytest.fixture
def mock_goal_db_conn():
    """目標管理用DBコネクションのモック"""
    conn = MagicMock()

    # execute のモックを設定
    result = MagicMock()
    result.fetchone.return_value = None
    result.fetchall.return_value = []
    result.rowcount = 1
    conn.execute.return_value = result

    # コンテキストマネージャー対応
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=None)

    return conn


@pytest.fixture
def mock_chatwork_send():
    """ChatWorkメッセージ送信のモック"""
    def mock_send(room_id, message):
        return True
    return mock_send
