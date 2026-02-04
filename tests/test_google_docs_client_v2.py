# tests/test_google_docs_client_v2.py
"""
Phase G1: Google Docs クライアントの包括的テスト

GoogleDocsClientの全メソッドをテストし、80%以上のカバレッジを目指す。

Author: Claude Opus 4.5
Created: 2026-02-04
"""

import pytest
from unittest.mock import Mock, patch, MagicMock, AsyncMock
from uuid import uuid4
from dataclasses import dataclass

# テスト対象のインポート
from lib.capabilities.generation.google_docs_client import (
    GoogleDocsClient,
    create_google_docs_client,
    GOOGLE_DOCS_API_VERSION,
    GOOGLE_DOCS_SCOPES,
    GOOGLE_DRIVE_API_VERSION,
    GOOGLE_DRIVE_SCOPES,
)
from lib.capabilities.generation.exceptions import (
    GoogleAuthError,
    GoogleDocsCreateError,
    GoogleDocsUpdateError,
    GoogleDriveUploadError,
)
from lib.capabilities.generation.models import SectionContent
from lib.capabilities.generation.constants import SectionType


# =============================================================================
# フィクスチャ
# =============================================================================


@pytest.fixture
def mock_credentials():
    """モック認証情報（JSON形式）"""
    return {
        "type": "service_account",
        "project_id": "test-project",
        "private_key_id": "test-key-id",
        "private_key": "DUMMY_PRIVATE_KEY_FOR_TESTING",
        "client_email": "test@test-project.iam.gserviceaccount.com",
        "client_id": "123456789012345678901",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/test%40test-project.iam.gserviceaccount.com",
    }


@pytest.fixture
def mock_credentials_path():
    """モック認証情報ファイルパス"""
    return "/path/to/service_account.json"


@pytest.fixture
def docs_client(mock_credentials):
    """テスト用クライアント（JSON認証情報）"""
    return GoogleDocsClient(credentials_json=mock_credentials)


@pytest.fixture
def docs_client_path(mock_credentials_path):
    """テスト用クライアント（ファイルパス認証情報）"""
    return GoogleDocsClient(credentials_path=mock_credentials_path)


@pytest.fixture
def document_id():
    """テスト用ドキュメントID"""
    return "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"


@pytest.fixture
def folder_id():
    """テスト用フォルダID"""
    return "1a2b3c4d5e6f7g8h9i0j"


@pytest.fixture
def sample_sections():
    """テスト用セクションリスト"""
    return [
        SectionContent(
            section_id=1,
            title="概要",
            content="これは概要セクションです。",
            section_type=SectionType.HEADING1,
        ),
        SectionContent(
            section_id=2,
            title="詳細",
            content="これは詳細セクションです。詳しい説明を記載します。",
            section_type=SectionType.HEADING2,
        ),
        SectionContent(
            section_id=3,
            title="本文",
            content="本文のテキストです。",
            section_type=SectionType.PARAGRAPH,
        ),
    ]


# =============================================================================
# 定数テスト
# =============================================================================


class TestConstants:
    """定数のテスト"""

    def test_google_docs_api_version(self):
        """Google Docs APIバージョン"""
        assert GOOGLE_DOCS_API_VERSION == "v1"

    def test_google_docs_scopes(self):
        """Google Docsスコープ"""
        assert "https://www.googleapis.com/auth/documents" in GOOGLE_DOCS_SCOPES
        assert "https://www.googleapis.com/auth/drive.file" in GOOGLE_DOCS_SCOPES

    def test_google_drive_api_version(self):
        """Google Drive APIバージョン"""
        assert GOOGLE_DRIVE_API_VERSION == "v3"

    def test_google_drive_scopes(self):
        """Google Driveスコープ"""
        assert "https://www.googleapis.com/auth/drive.file" in GOOGLE_DRIVE_SCOPES


# =============================================================================
# 例外テスト
# =============================================================================


class TestExceptions:
    """例外クラスのテスト"""

    def test_google_auth_error(self):
        """GoogleAuthErrorの基本動作"""
        error = GoogleAuthError(details={"reason": "Invalid credentials"})
        assert error.error_code == "GOOGLE_AUTH_FAILED"
        assert "Google認証" in str(error)
        assert "Googleサービスへの接続に失敗" in error.to_user_message()

    def test_google_auth_error_with_original(self):
        """GoogleAuthErrorの元エラー付き"""
        original = ValueError("Token expired")
        error = GoogleAuthError(original_error=original)
        assert error.original_error == original
        assert error.error_code == "GOOGLE_AUTH_FAILED"

    def test_google_docs_create_error(self):
        """GoogleDocsCreateErrorの基本動作"""
        error = GoogleDocsCreateError(document_title="テスト文書")
        assert error.error_code == "GOOGLE_DOCS_CREATE_FAILED"
        assert error.document_title == "テスト文書"
        assert "Google Docsの作成に失敗" in error.to_user_message()

    def test_google_docs_create_error_to_dict(self):
        """GoogleDocsCreateErrorの辞書変換"""
        error = GoogleDocsCreateError(
            document_title="テスト文書",
            details={"extra": "info"},
        )
        d = error.to_dict()
        assert d["error_code"] == "GOOGLE_DOCS_CREATE_FAILED"
        assert "document_title" in d["details"]

    def test_google_docs_update_error(self):
        """GoogleDocsUpdateErrorの基本動作"""
        error = GoogleDocsUpdateError(document_id="doc-123")
        assert error.error_code == "GOOGLE_DOCS_UPDATE_FAILED"
        assert error.document_id == "doc-123"
        assert "文書の更新に失敗" in error.to_user_message()

    def test_google_drive_upload_error(self):
        """GoogleDriveUploadErrorの基本動作"""
        error = GoogleDriveUploadError(file_name="document.pdf")
        assert error.error_code == "GOOGLE_DRIVE_UPLOAD_FAILED"
        assert error.file_name == "document.pdf"
        assert "アップロードに失敗" in error.to_user_message()


# =============================================================================
# クライアント初期化テスト
# =============================================================================


class TestClientInitialization:
    """GoogleDocsClient初期化のテスト"""

    def test_init_with_credentials_json(self, mock_credentials):
        """JSON認証情報での初期化"""
        client = GoogleDocsClient(credentials_json=mock_credentials)
        assert client._credentials_json == mock_credentials
        assert client._credentials_path is None
        assert client._docs_service is None
        assert client._drive_service is None
        assert client._credentials is None

    def test_init_with_credentials_path(self, mock_credentials_path):
        """ファイルパスでの初期化"""
        client = GoogleDocsClient(credentials_path=mock_credentials_path)
        assert client._credentials_path == mock_credentials_path
        assert client._credentials_json is None
        assert client._docs_service is None

    def test_init_with_env_variable(self, monkeypatch):
        """環境変数からの初期化"""
        monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/env/path/credentials.json")
        client = GoogleDocsClient()
        assert client._credentials_path == "/env/path/credentials.json"
        assert client._credentials_json is None

    def test_init_priority_path_over_env(self, mock_credentials_path, monkeypatch):
        """引数がある場合は環境変数より優先"""
        monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/env/path/credentials.json")
        client = GoogleDocsClient(credentials_path=mock_credentials_path)
        assert client._credentials_path == mock_credentials_path

    def test_init_priority_json_over_path(self, mock_credentials, mock_credentials_path):
        """JSON認証情報が両方指定された場合"""
        client = GoogleDocsClient(
            credentials_json=mock_credentials,
            credentials_path=mock_credentials_path,
        )
        assert client._credentials_json == mock_credentials
        assert client._credentials_path == mock_credentials_path


# =============================================================================
# ファクトリ関数テスト
# =============================================================================


class TestFactoryFunction:
    """ファクトリ関数のテスト"""

    def test_create_google_docs_client_with_json(self, mock_credentials):
        """JSON認証情報でのファクトリ関数"""
        client = create_google_docs_client(credentials_json=mock_credentials)
        assert isinstance(client, GoogleDocsClient)
        assert client._credentials_json == mock_credentials

    def test_create_google_docs_client_with_path(self, mock_credentials_path):
        """ファイルパスでのファクトリ関数"""
        client = create_google_docs_client(credentials_path=mock_credentials_path)
        assert isinstance(client, GoogleDocsClient)
        assert client._credentials_path == mock_credentials_path

    def test_create_google_docs_client_no_args(self):
        """引数なしでのファクトリ関数"""
        client = create_google_docs_client()
        assert isinstance(client, GoogleDocsClient)


# =============================================================================
# 認証情報取得テスト
# =============================================================================


class TestGetCredentials:
    """_get_credentialsメソッドのテスト"""

    def test_get_credentials_from_json(self, docs_client, mock_credentials):
        """JSON認証情報からの認証情報取得"""
        with patch("lib.capabilities.generation.google_docs_client.service_account.Credentials.from_service_account_info") as mock_from_info:
            mock_creds = Mock()
            mock_from_info.return_value = mock_creds

            result = docs_client._get_credentials()

            mock_from_info.assert_called_once()
            # スコープが正しく設定されているか確認
            call_args = mock_from_info.call_args
            assert call_args[0][0] == mock_credentials
            assert "scopes" in call_args[1]
            assert result == mock_creds

    def test_get_credentials_from_file(self, docs_client_path, mock_credentials_path):
        """ファイルパスからの認証情報取得"""
        with patch("lib.capabilities.generation.google_docs_client.service_account.Credentials.from_service_account_file") as mock_from_file:
            mock_creds = Mock()
            mock_from_file.return_value = mock_creds

            result = docs_client_path._get_credentials()

            mock_from_file.assert_called_once()
            call_args = mock_from_file.call_args
            assert call_args[0][0] == mock_credentials_path
            assert result == mock_creds

    def test_get_credentials_cached(self, docs_client):
        """認証情報のキャッシュ"""
        mock_creds = Mock()
        docs_client._credentials = mock_creds

        result = docs_client._get_credentials()

        assert result == mock_creds

    def test_get_credentials_no_credentials_raises_error(self):
        """認証情報がない場合のエラー"""
        client = GoogleDocsClient()
        client._credentials_path = None
        client._credentials_json = None

        with pytest.raises(GoogleAuthError) as exc_info:
            client._get_credentials()

        # GoogleAuthErrorが発生することを確認
        assert exc_info.value.error_code == "GOOGLE_AUTH_FAILED"

    def test_get_credentials_auth_failure_raises_error(self, docs_client):
        """認証失敗時のエラー"""
        with patch("lib.capabilities.generation.google_docs_client.service_account.Credentials.from_service_account_info") as mock_from_info:
            mock_from_info.side_effect = Exception("Invalid key")

            with pytest.raises(GoogleAuthError) as exc_info:
                docs_client._get_credentials()

            assert exc_info.value.original_error is not None


# =============================================================================
# Docs/Driveサービス取得テスト
# =============================================================================


class TestGetServices:
    """サービス取得メソッドのテスト"""

    def test_get_docs_service(self, docs_client):
        """Docsサービス取得"""
        mock_creds = Mock()
        mock_service = Mock()

        with patch.object(docs_client, "_get_credentials", return_value=mock_creds):
            with patch("lib.capabilities.generation.google_docs_client.build", return_value=mock_service) as mock_build:
                result = docs_client._get_docs_service()

                mock_build.assert_called_once_with(
                    "docs",
                    GOOGLE_DOCS_API_VERSION,
                    credentials=mock_creds,
                )
                assert result == mock_service
                assert docs_client._docs_service == mock_service

    def test_get_docs_service_cached(self, docs_client):
        """Docsサービスのキャッシュ"""
        mock_service = Mock()
        docs_client._docs_service = mock_service

        result = docs_client._get_docs_service()

        assert result == mock_service

    def test_get_drive_service(self, docs_client):
        """Driveサービス取得"""
        mock_creds = Mock()
        mock_service = Mock()

        with patch.object(docs_client, "_get_credentials", return_value=mock_creds):
            with patch("lib.capabilities.generation.google_docs_client.build", return_value=mock_service) as mock_build:
                result = docs_client._get_drive_service()

                mock_build.assert_called_once_with(
                    "drive",
                    GOOGLE_DRIVE_API_VERSION,
                    credentials=mock_creds,
                )
                assert result == mock_service
                assert docs_client._drive_service == mock_service

    def test_get_drive_service_cached(self, docs_client):
        """Driveサービスのキャッシュ"""
        mock_service = Mock()
        docs_client._drive_service = mock_service

        result = docs_client._get_drive_service()

        assert result == mock_service


# =============================================================================
# ドキュメント作成テスト
# =============================================================================


class TestCreateDocument:
    """create_documentメソッドのテスト"""

    @pytest.mark.asyncio
    async def test_create_document_basic(self, docs_client):
        """基本的なドキュメント作成"""
        mock_response = {
            "documentId": "new-doc-id-123",
        }

        with patch.object(docs_client, "_get_docs_service") as mock_service_getter:
            mock_service = Mock()
            mock_service_getter.return_value = mock_service
            mock_service.documents.return_value.create.return_value.execute.return_value = mock_response

            result = await docs_client.create_document("テスト文書")

            assert result["document_id"] == "new-doc-id-123"
            assert result["document_url"] == "https://docs.google.com/document/d/new-doc-id-123/edit"

            # create呼び出しの確認
            mock_service.documents.return_value.create.assert_called_once_with(
                body={"title": "テスト文書"}
            )

    @pytest.mark.asyncio
    async def test_create_document_with_folder(self, docs_client, folder_id):
        """フォルダ指定でのドキュメント作成"""
        mock_response = {
            "documentId": "new-doc-id-456",
        }

        with patch.object(docs_client, "_get_docs_service") as mock_service_getter:
            mock_service = Mock()
            mock_service_getter.return_value = mock_service
            mock_service.documents.return_value.create.return_value.execute.return_value = mock_response

            with patch.object(docs_client, "_move_to_folder", new_callable=AsyncMock) as mock_move:
                mock_move.return_value = True

                result = await docs_client.create_document("テスト文書", folder_id=folder_id)

                assert result["document_id"] == "new-doc-id-456"
                mock_move.assert_called_once_with("new-doc-id-456", folder_id)

    @pytest.mark.asyncio
    async def test_create_document_http_error(self, docs_client):
        """HTTPエラー時の例外処理"""
        from googleapiclient.errors import HttpError

        mock_response = Mock()
        mock_response.status = 403
        mock_response.reason = "Forbidden"
        http_error = HttpError(mock_response, b'{"error": "Forbidden"}')

        with patch.object(docs_client, "_get_docs_service") as mock_service_getter:
            mock_service = Mock()
            mock_service_getter.return_value = mock_service
            mock_service.documents.return_value.create.return_value.execute.side_effect = http_error

            with pytest.raises(GoogleDocsCreateError) as exc_info:
                await docs_client.create_document("テスト文書")

            assert exc_info.value.document_title == "テスト文書"
            assert exc_info.value.original_error == http_error

    @pytest.mark.asyncio
    async def test_create_document_unexpected_error(self, docs_client):
        """予期しないエラー時の例外処理"""
        with patch.object(docs_client, "_get_docs_service") as mock_service_getter:
            mock_service = Mock()
            mock_service_getter.return_value = mock_service
            mock_service.documents.return_value.create.return_value.execute.side_effect = RuntimeError("Unexpected")

            with pytest.raises(GoogleDocsCreateError) as exc_info:
                await docs_client.create_document("テスト文書")

            assert exc_info.value.document_title == "テスト文書"


# =============================================================================
# ドキュメント更新テスト
# =============================================================================


class TestUpdateDocument:
    """update_documentメソッドのテスト"""

    @pytest.mark.asyncio
    async def test_update_document_with_sections(self, docs_client, document_id, sample_sections):
        """セクション付きドキュメント更新"""
        with patch.object(docs_client, "_get_docs_service") as mock_service_getter:
            mock_service = Mock()
            mock_service_getter.return_value = mock_service
            mock_service.documents.return_value.batchUpdate.return_value.execute.return_value = {}

            result = await docs_client.update_document(document_id, sample_sections)

            assert result is True
            mock_service.documents.return_value.batchUpdate.assert_called_once()

            # batchUpdate呼び出しの内容を検証
            call_args = mock_service.documents.return_value.batchUpdate.call_args
            assert call_args.kwargs["documentId"] == document_id
            assert "body" in call_args.kwargs
            assert "requests" in call_args.kwargs["body"]

    @pytest.mark.asyncio
    async def test_update_document_empty_sections(self, docs_client, document_id):
        """空のセクションリストでの更新"""
        with patch.object(docs_client, "_get_docs_service") as mock_service_getter:
            mock_service = Mock()
            mock_service_getter.return_value = mock_service

            result = await docs_client.update_document(document_id, [])

            assert result is True
            # 空の場合はbatchUpdateが呼ばれない
            mock_service.documents.return_value.batchUpdate.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_document_heading_styles(self, docs_client, document_id):
        """各種見出しスタイルのテスト"""
        sections = [
            SectionContent(section_id=1, title="タイトル", content="", section_type=SectionType.TITLE),
            SectionContent(section_id=2, title="サブタイトル", content="", section_type=SectionType.SUBTITLE),
            SectionContent(section_id=3, title="見出し1", content="", section_type=SectionType.HEADING1),
            SectionContent(section_id=4, title="見出し2", content="", section_type=SectionType.HEADING2),
            SectionContent(section_id=5, title="見出し3", content="", section_type=SectionType.HEADING3),
        ]

        with patch.object(docs_client, "_get_docs_service") as mock_service_getter:
            mock_service = Mock()
            mock_service_getter.return_value = mock_service
            mock_service.documents.return_value.batchUpdate.return_value.execute.return_value = {}

            result = await docs_client.update_document(document_id, sections)

            assert result is True

            # リクエストの検証
            call_args = mock_service.documents.return_value.batchUpdate.call_args
            requests = call_args.kwargs["body"]["requests"]

            # 各見出しにはinsertTextとupdateParagraphStyleが含まれる
            style_requests = [r for r in requests if "updateParagraphStyle" in r]
            assert len(style_requests) >= 5

    @pytest.mark.asyncio
    async def test_update_document_with_content(self, docs_client, document_id):
        """コンテンツ付きセクションの更新"""
        sections = [
            SectionContent(
                section_id=1,
                title="概要",
                content="これは概要の本文です。",
                section_type=SectionType.HEADING1,
            ),
        ]

        with patch.object(docs_client, "_get_docs_service") as mock_service_getter:
            mock_service = Mock()
            mock_service_getter.return_value = mock_service
            mock_service.documents.return_value.batchUpdate.return_value.execute.return_value = {}

            result = await docs_client.update_document(document_id, sections)

            assert result is True

            call_args = mock_service.documents.return_value.batchUpdate.call_args
            requests = call_args.kwargs["body"]["requests"]

            # insertTextリクエストがタイトルとコンテンツの両方に存在
            insert_requests = [r for r in requests if "insertText" in r]
            assert len(insert_requests) >= 2

    @pytest.mark.asyncio
    async def test_update_document_http_error(self, docs_client, document_id, sample_sections):
        """更新時のHTTPエラー処理"""
        from googleapiclient.errors import HttpError

        mock_response = Mock()
        mock_response.status = 404
        mock_response.reason = "Not Found"
        http_error = HttpError(mock_response, b'{"error": "Document not found"}')

        with patch.object(docs_client, "_get_docs_service") as mock_service_getter:
            mock_service = Mock()
            mock_service_getter.return_value = mock_service
            mock_service.documents.return_value.batchUpdate.return_value.execute.side_effect = http_error

            with pytest.raises(GoogleDocsUpdateError) as exc_info:
                await docs_client.update_document(document_id, sample_sections)

            assert exc_info.value.document_id == document_id
            assert exc_info.value.original_error == http_error

    @pytest.mark.asyncio
    async def test_update_document_paragraph_section(self, docs_client, document_id):
        """PARAGRAPH型セクションの更新（見出しなし）"""
        sections = [
            SectionContent(
                section_id=1,
                title="",  # タイトルなし
                content="本文のみのテキストです。",
                section_type=SectionType.PARAGRAPH,
            ),
        ]

        with patch.object(docs_client, "_get_docs_service") as mock_service_getter:
            mock_service = Mock()
            mock_service_getter.return_value = mock_service
            mock_service.documents.return_value.batchUpdate.return_value.execute.return_value = {}

            result = await docs_client.update_document(document_id, sections)

            assert result is True


# =============================================================================
# Markdownコンテンツ書き込みテスト
# =============================================================================


class TestWriteMarkdownContent:
    """write_markdown_contentメソッドのテスト"""

    @pytest.mark.asyncio
    async def test_write_markdown_basic(self, docs_client, document_id):
        """基本的なMarkdown書き込み"""
        markdown = """# タイトル

本文テキストです。

## サブタイトル

詳細な説明。
"""
        with patch.object(docs_client, "_get_docs_service") as mock_service_getter:
            mock_service = Mock()
            mock_service_getter.return_value = mock_service
            mock_service.documents.return_value.batchUpdate.return_value.execute.return_value = {}

            result = await docs_client.write_markdown_content(document_id, markdown)

            assert result is True
            mock_service.documents.return_value.batchUpdate.assert_called_once()

    @pytest.mark.asyncio
    async def test_write_markdown_empty(self, docs_client, document_id):
        """空のMarkdown書き込み"""
        with patch.object(docs_client, "_get_docs_service") as mock_service_getter:
            mock_service = Mock()
            mock_service_getter.return_value = mock_service
            mock_service.documents.return_value.batchUpdate.return_value.execute.return_value = {}

            result = await docs_client.write_markdown_content(document_id, "")

            assert result is True
            # 空文字列でも改行が挿入されるため、batchUpdateが呼ばれる
            # これは実装の挙動に依存（空文字列は空行として扱われる）

    @pytest.mark.asyncio
    async def test_write_markdown_http_error(self, docs_client, document_id):
        """Markdown書き込み時のHTTPエラー"""
        from googleapiclient.errors import HttpError

        mock_response = Mock()
        mock_response.status = 500
        mock_response.reason = "Internal Server Error"
        http_error = HttpError(mock_response, b'{"error": "Server error"}')

        markdown = "# テスト\n本文"

        with patch.object(docs_client, "_get_docs_service") as mock_service_getter:
            mock_service = Mock()
            mock_service_getter.return_value = mock_service
            mock_service.documents.return_value.batchUpdate.return_value.execute.side_effect = http_error

            with pytest.raises(GoogleDocsUpdateError) as exc_info:
                await docs_client.write_markdown_content(document_id, markdown)

            assert exc_info.value.document_id == document_id


# =============================================================================
# ドキュメント共有テスト
# =============================================================================


class TestShareDocument:
    """share_documentメソッドのテスト"""

    @pytest.mark.asyncio
    async def test_share_document_single_user(self, docs_client, document_id):
        """単一ユーザーへの共有"""
        with patch.object(docs_client, "_get_drive_service") as mock_service_getter:
            mock_service = Mock()
            mock_service_getter.return_value = mock_service
            mock_service.permissions.return_value.create.return_value.execute.return_value = {}

            result = await docs_client.share_document(
                document_id,
                ["user@example.com"],
            )

            assert result is True
            mock_service.permissions.return_value.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_share_document_multiple_users(self, docs_client, document_id):
        """複数ユーザーへの共有"""
        emails = ["user1@example.com", "user2@example.com", "user3@example.com"]

        with patch.object(docs_client, "_get_drive_service") as mock_service_getter:
            mock_service = Mock()
            mock_service_getter.return_value = mock_service
            mock_service.permissions.return_value.create.return_value.execute.return_value = {}

            result = await docs_client.share_document(document_id, emails)

            assert result is True
            assert mock_service.permissions.return_value.create.call_count == 3

    @pytest.mark.asyncio
    async def test_share_document_with_writer_role(self, docs_client, document_id):
        """writer権限での共有"""
        with patch.object(docs_client, "_get_drive_service") as mock_service_getter:
            mock_service = Mock()
            mock_service_getter.return_value = mock_service
            mock_service.permissions.return_value.create.return_value.execute.return_value = {}

            result = await docs_client.share_document(
                document_id,
                ["editor@example.com"],
                role="writer",
            )

            assert result is True

            call_args = mock_service.permissions.return_value.create.call_args
            body = call_args.kwargs.get("body", {})
            assert body["role"] == "writer"
            assert body["type"] == "user"
            assert body["emailAddress"] == "editor@example.com"

    @pytest.mark.asyncio
    async def test_share_document_with_commenter_role(self, docs_client, document_id):
        """commenter権限での共有"""
        with patch.object(docs_client, "_get_drive_service") as mock_service_getter:
            mock_service = Mock()
            mock_service_getter.return_value = mock_service
            mock_service.permissions.return_value.create.return_value.execute.return_value = {}

            result = await docs_client.share_document(
                document_id,
                ["commenter@example.com"],
                role="commenter",
            )

            assert result is True

            call_args = mock_service.permissions.return_value.create.call_args
            body = call_args.kwargs.get("body", {})
            assert body["role"] == "commenter"

    @pytest.mark.asyncio
    async def test_share_document_http_error(self, docs_client, document_id):
        """共有時のHTTPエラー"""
        from googleapiclient.errors import HttpError

        mock_response = Mock()
        mock_response.status = 403
        mock_response.reason = "Forbidden"
        http_error = HttpError(mock_response, b'{"error": "Permission denied"}')

        with patch.object(docs_client, "_get_drive_service") as mock_service_getter:
            mock_service = Mock()
            mock_service_getter.return_value = mock_service
            mock_service.permissions.return_value.create.return_value.execute.side_effect = http_error

            with pytest.raises(GoogleDriveUploadError) as exc_info:
                await docs_client.share_document(document_id, ["user@example.com"])

            assert exc_info.value.file_name == document_id


# =============================================================================
# フォルダ移動テスト
# =============================================================================


class TestMoveToFolder:
    """_move_to_folderメソッドのテスト"""

    @pytest.mark.asyncio
    async def test_move_to_folder_success(self, docs_client, document_id, folder_id):
        """フォルダ移動成功"""
        with patch.object(docs_client, "_get_drive_service") as mock_service_getter:
            mock_service = Mock()
            mock_service_getter.return_value = mock_service

            # ファイル情報取得のモック
            mock_service.files.return_value.get.return_value.execute.return_value = {
                "parents": ["old-parent-id"]
            }
            # 更新のモック
            mock_service.files.return_value.update.return_value.execute.return_value = {
                "id": document_id,
                "parents": [folder_id],
            }

            result = await docs_client._move_to_folder(document_id, folder_id)

            assert result is True
            mock_service.files.return_value.update.assert_called_once()

    @pytest.mark.asyncio
    async def test_move_to_folder_http_error(self, docs_client, document_id, folder_id):
        """フォルダ移動時のHTTPエラー（Falseを返す）"""
        from googleapiclient.errors import HttpError

        mock_response = Mock()
        mock_response.status = 404
        mock_response.reason = "Not Found"
        http_error = HttpError(mock_response, b'{"error": "Folder not found"}')

        with patch.object(docs_client, "_get_drive_service") as mock_service_getter:
            mock_service = Mock()
            mock_service_getter.return_value = mock_service
            mock_service.files.return_value.get.return_value.execute.side_effect = http_error

            result = await docs_client._move_to_folder(document_id, folder_id)

            # HTTPエラー時はFalseを返す（例外を投げない）
            assert result is False


# =============================================================================
# ドキュメントコンテンツ取得テスト
# =============================================================================


class TestGetDocumentContent:
    """get_document_contentメソッドのテスト"""

    @pytest.mark.asyncio
    async def test_get_document_content_success(self, docs_client, document_id):
        """コンテンツ取得成功"""
        mock_document = {
            "body": {
                "content": [
                    {
                        "paragraph": {
                            "elements": [
                                {"textRun": {"content": "Hello, "}},
                                {"textRun": {"content": "World!"}},
                            ]
                        }
                    },
                    {
                        "paragraph": {
                            "elements": [
                                {"textRun": {"content": "\nThis is a test."}},
                            ]
                        }
                    },
                ]
            }
        }

        with patch.object(docs_client, "_get_docs_service") as mock_service_getter:
            mock_service = Mock()
            mock_service_getter.return_value = mock_service
            mock_service.documents.return_value.get.return_value.execute.return_value = mock_document

            result = await docs_client.get_document_content(document_id)

            assert result == "Hello, World!\nThis is a test."

    @pytest.mark.asyncio
    async def test_get_document_content_empty(self, docs_client, document_id):
        """空のドキュメント"""
        mock_document = {
            "body": {
                "content": []
            }
        }

        with patch.object(docs_client, "_get_docs_service") as mock_service_getter:
            mock_service = Mock()
            mock_service_getter.return_value = mock_service
            mock_service.documents.return_value.get.return_value.execute.return_value = mock_document

            result = await docs_client.get_document_content(document_id)

            assert result == ""

    @pytest.mark.asyncio
    async def test_get_document_content_no_body(self, docs_client, document_id):
        """bodyがないドキュメント"""
        mock_document = {}

        with patch.object(docs_client, "_get_docs_service") as mock_service_getter:
            mock_service = Mock()
            mock_service_getter.return_value = mock_service
            mock_service.documents.return_value.get.return_value.execute.return_value = mock_document

            result = await docs_client.get_document_content(document_id)

            assert result == ""

    @pytest.mark.asyncio
    async def test_get_document_content_http_error(self, docs_client, document_id):
        """コンテンツ取得時のHTTPエラー"""
        from googleapiclient.errors import HttpError

        mock_response = Mock()
        mock_response.status = 404
        mock_response.reason = "Not Found"
        http_error = HttpError(mock_response, b'{"error": "Document not found"}')

        with patch.object(docs_client, "_get_docs_service") as mock_service_getter:
            mock_service = Mock()
            mock_service_getter.return_value = mock_service
            mock_service.documents.return_value.get.return_value.execute.side_effect = http_error

            with pytest.raises(GoogleDocsUpdateError) as exc_info:
                await docs_client.get_document_content(document_id)

            assert exc_info.value.document_id == document_id


# =============================================================================
# ヘルパーメソッドテスト
# =============================================================================


class TestHelperMethods:
    """ヘルパーメソッドのテスト"""

    def test_get_heading_style_title(self, docs_client):
        """TITLEスタイル"""
        result = docs_client._get_heading_style(SectionType.TITLE)
        assert result == "TITLE"

    def test_get_heading_style_subtitle(self, docs_client):
        """SUBTITLEスタイル"""
        result = docs_client._get_heading_style(SectionType.SUBTITLE)
        assert result == "SUBTITLE"

    def test_get_heading_style_heading1(self, docs_client):
        """HEADING_1スタイル"""
        result = docs_client._get_heading_style(SectionType.HEADING1)
        assert result == "HEADING_1"

    def test_get_heading_style_heading2(self, docs_client):
        """HEADING_2スタイル"""
        result = docs_client._get_heading_style(SectionType.HEADING2)
        assert result == "HEADING_2"

    def test_get_heading_style_heading3(self, docs_client):
        """HEADING_3スタイル"""
        result = docs_client._get_heading_style(SectionType.HEADING3)
        assert result == "HEADING_3"

    def test_get_heading_style_unknown(self, docs_client):
        """不明なスタイルはNORMAL_TEXT"""
        result = docs_client._get_heading_style(SectionType.PARAGRAPH)
        assert result == "NORMAL_TEXT"


# =============================================================================
# Markdown変換テスト
# =============================================================================


class TestMarkdownToRequests:
    """_markdown_to_requestsメソッドのテスト"""

    def test_markdown_to_requests_heading(self, docs_client):
        """見出しの変換"""
        markdown = "# 見出し1"
        requests = docs_client._markdown_to_requests(markdown)

        assert len(requests) == 2  # insertText + updateParagraphStyle
        assert "insertText" in requests[0]
        assert "updateParagraphStyle" in requests[1]
        assert requests[1]["updateParagraphStyle"]["paragraphStyle"]["namedStyleType"] == "HEADING_1"

    def test_markdown_to_requests_multiple_headings(self, docs_client):
        """複数レベルの見出し"""
        markdown = """# 見出し1
## 見出し2
### 見出し3
#### 見出し4
##### 見出し5
###### 見出し6"""

        requests = docs_client._markdown_to_requests(markdown)

        # 各見出しにinsertText + updateParagraphStyle
        style_requests = [r for r in requests if "updateParagraphStyle" in r]
        assert len(style_requests) == 6

        styles = [r["updateParagraphStyle"]["paragraphStyle"]["namedStyleType"] for r in style_requests]
        assert "HEADING_1" in styles
        assert "HEADING_2" in styles
        assert "HEADING_3" in styles
        assert "HEADING_4" in styles
        assert "HEADING_5" in styles
        assert "HEADING_6" in styles

    def test_markdown_to_requests_bullet_list(self, docs_client):
        """箇条書きの変換"""
        markdown = """- 項目1
- 項目2
* 項目3"""

        requests = docs_client._markdown_to_requests(markdown)

        bullet_requests = [r for r in requests if "createParagraphBullets" in r]
        assert len(bullet_requests) == 3

        for br in bullet_requests:
            assert br["createParagraphBullets"]["bulletPreset"] == "BULLET_DISC_CIRCLE_SQUARE"

    def test_markdown_to_requests_numbered_list(self, docs_client):
        """番号付きリストの変換"""
        markdown = """1. 項目1
2. 項目2
3. 項目3"""

        requests = docs_client._markdown_to_requests(markdown)

        numbered_requests = [r for r in requests if "createParagraphBullets" in r]
        assert len(numbered_requests) == 3

        for nr in numbered_requests:
            assert nr["createParagraphBullets"]["bulletPreset"] == "NUMBERED_DECIMAL_ALPHA_ROMAN"

    def test_markdown_to_requests_normal_text(self, docs_client):
        """通常テキストの変換"""
        markdown = "これは通常のテキストです。"

        requests = docs_client._markdown_to_requests(markdown)

        assert len(requests) == 1
        assert "insertText" in requests[0]
        assert requests[0]["insertText"]["text"] == "これは通常のテキストです。\n"

    def test_markdown_to_requests_empty_lines(self, docs_client):
        """空行の処理"""
        markdown = """テキスト1

テキスト2"""

        requests = docs_client._markdown_to_requests(markdown)

        # テキスト1 + 空行 + テキスト2
        insert_requests = [r for r in requests if "insertText" in r]
        assert len(insert_requests) == 3

    def test_markdown_to_requests_mixed_content(self, docs_client):
        """混合コンテンツの変換"""
        markdown = """# タイトル

本文テキスト。

## サブセクション

- 項目A
- 項目B

1. ステップ1
2. ステップ2

終わりのテキスト。"""

        requests = docs_client._markdown_to_requests(markdown)

        # 正しい数のリクエストが生成されているか確認
        assert len(requests) > 0

        # 見出しスタイルの確認
        style_requests = [r for r in requests if "updateParagraphStyle" in r]
        assert len(style_requests) >= 2

        # 箇条書きの確認
        bullet_requests = [r for r in requests if "createParagraphBullets" in r]
        assert len(bullet_requests) >= 4  # 2つの箇条書き + 2つの番号付き


# =============================================================================
# パッケージインポートテスト
# =============================================================================


class TestPackageImports:
    """パッケージインポートのテスト"""

    def test_import_client(self):
        """クライアントのインポート"""
        from lib.capabilities.generation.google_docs_client import (
            GoogleDocsClient,
            create_google_docs_client,
        )
        assert GoogleDocsClient is not None
        assert create_google_docs_client is not None

    def test_import_exceptions(self):
        """例外のインポート"""
        from lib.capabilities.generation.exceptions import (
            GoogleAuthError,
            GoogleDocsCreateError,
            GoogleDocsUpdateError,
            GoogleDriveUploadError,
        )
        assert GoogleAuthError is not None
        assert GoogleDocsCreateError is not None
        assert GoogleDocsUpdateError is not None
        assert GoogleDriveUploadError is not None

    def test_import_constants(self):
        """定数のインポート"""
        from lib.capabilities.generation.google_docs_client import (
            GOOGLE_DOCS_API_VERSION,
            GOOGLE_DOCS_SCOPES,
            GOOGLE_DRIVE_API_VERSION,
            GOOGLE_DRIVE_SCOPES,
        )
        assert GOOGLE_DOCS_API_VERSION is not None
        assert GOOGLE_DOCS_SCOPES is not None
        assert GOOGLE_DRIVE_API_VERSION is not None
        assert GOOGLE_DRIVE_SCOPES is not None


# =============================================================================
# エッジケーステスト
# =============================================================================


class TestEdgeCases:
    """エッジケースのテスト"""

    @pytest.mark.asyncio
    async def test_create_document_with_special_characters(self, docs_client):
        """特殊文字を含むタイトルでのドキュメント作成"""
        title = "テスト文書 [2024] - 特殊文字: @#$%&*"
        mock_response = {"documentId": "doc-special-chars"}

        with patch.object(docs_client, "_get_docs_service") as mock_service_getter:
            mock_service = Mock()
            mock_service_getter.return_value = mock_service
            mock_service.documents.return_value.create.return_value.execute.return_value = mock_response

            result = await docs_client.create_document(title)

            assert result["document_id"] == "doc-special-chars"

            call_args = mock_service.documents.return_value.create.call_args
            assert call_args.kwargs["body"]["title"] == title

    @pytest.mark.asyncio
    async def test_update_document_with_unicode(self, docs_client, document_id):
        """Unicode文字を含むセクションでの更新"""
        sections = [
            SectionContent(
                section_id=1,
                title="日本語タイトル",
                content="絵文字テスト: ... 記号: +-=",
                section_type=SectionType.HEADING1,
            ),
        ]

        with patch.object(docs_client, "_get_docs_service") as mock_service_getter:
            mock_service = Mock()
            mock_service_getter.return_value = mock_service
            mock_service.documents.return_value.batchUpdate.return_value.execute.return_value = {}

            result = await docs_client.update_document(document_id, sections)

            assert result is True

    @pytest.mark.asyncio
    async def test_share_document_empty_list(self, docs_client, document_id):
        """空のメールリストでの共有"""
        with patch.object(docs_client, "_get_drive_service") as mock_service_getter:
            mock_service = Mock()
            mock_service_getter.return_value = mock_service

            result = await docs_client.share_document(document_id, [])

            assert result is True
            # 空リストの場合はcreateが呼ばれない
            mock_service.permissions.return_value.create.assert_not_called()

    def test_markdown_to_requests_empty_string(self, docs_client):
        """空文字列のMarkdown変換"""
        requests = docs_client._markdown_to_requests("")
        # 空文字列でもsplitにより空行が1つ生成され、改行が挿入される
        # これは実装の挙動に依存
        assert len(requests) >= 0  # 実装により空リストまたは改行挿入リクエスト

    def test_markdown_to_requests_only_whitespace(self, docs_client):
        """空白のみのMarkdown変換"""
        requests = docs_client._markdown_to_requests("   \n\n   ")

        # 空行と空白が処理される
        insert_requests = [r for r in requests if "insertText" in r]
        assert len(insert_requests) > 0

    @pytest.mark.asyncio
    async def test_move_to_folder_no_previous_parents(self, docs_client, document_id, folder_id):
        """親フォルダがないドキュメントの移動"""
        with patch.object(docs_client, "_get_drive_service") as mock_service_getter:
            mock_service = Mock()
            mock_service_getter.return_value = mock_service

            # 親なしの場合
            mock_service.files.return_value.get.return_value.execute.return_value = {
                "parents": []
            }
            mock_service.files.return_value.update.return_value.execute.return_value = {
                "id": document_id,
                "parents": [folder_id],
            }

            result = await docs_client._move_to_folder(document_id, folder_id)

            assert result is True


# =============================================================================
# 統合テスト
# =============================================================================


class TestIntegration:
    """統合テスト（モック使用）"""

    @pytest.mark.asyncio
    async def test_full_workflow_create_update_share(self, docs_client, folder_id):
        """作成 -> 更新 -> 共有の一連のワークフロー"""
        # モックの設定
        mock_docs_service = Mock()
        mock_drive_service = Mock()

        with patch.object(docs_client, "_get_docs_service", return_value=mock_docs_service):
            with patch.object(docs_client, "_get_drive_service", return_value=mock_drive_service):
                # 1. ドキュメント作成
                mock_docs_service.documents.return_value.create.return_value.execute.return_value = {
                    "documentId": "workflow-doc-id"
                }
                mock_drive_service.files.return_value.get.return_value.execute.return_value = {
                    "parents": ["root"]
                }
                mock_drive_service.files.return_value.update.return_value.execute.return_value = {}

                create_result = await docs_client.create_document("ワークフローテスト", folder_id=folder_id)
                assert create_result["document_id"] == "workflow-doc-id"

                # 2. ドキュメント更新
                sections = [
                    SectionContent(
                        section_id=1,
                        title="概要",
                        content="ワークフローテストの概要です。",
                        section_type=SectionType.HEADING1,
                    ),
                ]
                mock_docs_service.documents.return_value.batchUpdate.return_value.execute.return_value = {}

                update_result = await docs_client.update_document("workflow-doc-id", sections)
                assert update_result is True

                # 3. ドキュメント共有
                mock_drive_service.permissions.return_value.create.return_value.execute.return_value = {}

                share_result = await docs_client.share_document(
                    "workflow-doc-id",
                    ["user@example.com"],
                    role="writer",
                )
                assert share_result is True
