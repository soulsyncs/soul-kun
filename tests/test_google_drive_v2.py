"""
lib/google_drive.py のテスト（v2）

GoogleDriveClient クラスおよび関連データクラスの包括的なユニットテスト。
Google API クライアントはモックを使用し、実際のAPIは呼び出さない。

テスト対象:
- DriveFile データクラス
- DriveChange データクラス
- SyncResult データクラス
- GoogleDriveClient クラス
- FolderMapper クラス
- FolderMappingConfig データクラス

カバレッジ目標: 80%以上
"""

import pytest
import io
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime, timezone
from dataclasses import FrozenInstanceError

from lib.google_drive import (
    DriveFile,
    DriveChange,
    SyncResult,
    GoogleDriveClient,
    FolderMapper,
    FolderMappingConfig,
    SUPPORTED_MIME_TYPES,
    MAX_FILE_SIZE,
    EXCLUDE_PATTERNS,
)


# ================================================================
# DriveFile データクラスのテスト
# ================================================================

class TestDriveFile:
    """DriveFile データクラスのテスト"""

    def test_basic_creation(self):
        """基本的なインスタンス生成"""
        file = DriveFile(
            id="file123",
            name="test.pdf",
            mime_type="application/pdf",
            size=1024,
            modified_time=datetime.now(timezone.utc),
            created_time=datetime.now(timezone.utc),
            parents=["folder123"],
            web_view_link="https://drive.google.com/file/d/file123/view",
        )

        assert file.id == "file123"
        assert file.name == "test.pdf"
        assert file.mime_type == "application/pdf"
        assert file.size == 1024
        assert file.parents == ["folder123"]
        assert file.trashed is False  # デフォルト値

    def test_creation_with_trashed(self):
        """trashed=True でのインスタンス生成"""
        file = DriveFile(
            id="file123",
            name="deleted.pdf",
            mime_type="application/pdf",
            size=1024,
            modified_time=None,
            created_time=None,
            parents=[],
            web_view_link=None,
            trashed=True,
        )

        assert file.trashed is True

    def test_creation_with_folder_path(self):
        """folder_path付きのインスタンス生成"""
        file = DriveFile(
            id="file123",
            name="manual.docx",
            mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            size=2048,
            modified_time=None,
            created_time=None,
            parents=["folder1"],
            web_view_link=None,
            folder_path=["Root", "Documents", "Manuals"],
        )

        assert file.folder_path == ["Root", "Documents", "Manuals"]

    def test_file_extension_pdf(self):
        """file_extension プロパティ: PDFファイル"""
        file = DriveFile(
            id="1", name="report.pdf", mime_type="application/pdf",
            size=100, modified_time=None, created_time=None,
            parents=[], web_view_link=None
        )

        assert file.file_extension == "pdf"

    def test_file_extension_docx(self):
        """file_extension プロパティ: Wordファイル"""
        file = DriveFile(
            id="1", name="document.DOCX", mime_type="application/msword",
            size=100, modified_time=None, created_time=None,
            parents=[], web_view_link=None
        )

        # 大文字は小文字に変換される
        assert file.file_extension == "docx"

    def test_file_extension_multiple_dots(self):
        """file_extension プロパティ: 複数のドットを含むファイル名"""
        file = DriveFile(
            id="1", name="report.2024.01.pdf", mime_type="application/pdf",
            size=100, modified_time=None, created_time=None,
            parents=[], web_view_link=None
        )

        assert file.file_extension == "pdf"

    def test_file_extension_no_extension(self):
        """file_extension プロパティ: 拡張子なし"""
        file = DriveFile(
            id="1", name="README", mime_type="text/plain",
            size=100, modified_time=None, created_time=None,
            parents=[], web_view_link=None
        )

        assert file.file_extension == ""

    def test_file_extension_dot_only(self):
        """file_extension プロパティ: ドットで終わるファイル名"""
        file = DriveFile(
            id="1", name="file.", mime_type="text/plain",
            size=100, modified_time=None, created_time=None,
            parents=[], web_view_link=None
        )

        assert file.file_extension == ""

    def test_is_supported_type_pdf(self):
        """is_supported_type プロパティ: PDF（サポート対象）"""
        file = DriveFile(
            id="1", name="document.pdf", mime_type="application/pdf",
            size=100, modified_time=None, created_time=None,
            parents=[], web_view_link=None
        )

        assert file.is_supported_type is True

    def test_is_supported_type_docx(self):
        """is_supported_type プロパティ: DOCX（サポート対象）"""
        file = DriveFile(
            id="1", name="document.docx", mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            size=100, modified_time=None, created_time=None,
            parents=[], web_view_link=None
        )

        assert file.is_supported_type is True

    def test_is_supported_type_doc(self):
        """is_supported_type プロパティ: DOC（サポート対象）"""
        file = DriveFile(
            id="1", name="old_document.doc", mime_type="application/msword",
            size=100, modified_time=None, created_time=None,
            parents=[], web_view_link=None
        )

        assert file.is_supported_type is True

    def test_is_supported_type_txt(self):
        """is_supported_type プロパティ: TXT（サポート対象）"""
        file = DriveFile(
            id="1", name="readme.txt", mime_type="text/plain",
            size=100, modified_time=None, created_time=None,
            parents=[], web_view_link=None
        )

        assert file.is_supported_type is True

    def test_is_supported_type_md(self):
        """is_supported_type プロパティ: MD（サポート対象）"""
        file = DriveFile(
            id="1", name="documentation.md", mime_type="text/markdown",
            size=100, modified_time=None, created_time=None,
            parents=[], web_view_link=None
        )

        assert file.is_supported_type is True

    def test_is_supported_type_html(self):
        """is_supported_type プロパティ: HTML（サポート対象）"""
        file = DriveFile(
            id="1", name="page.html", mime_type="text/html",
            size=100, modified_time=None, created_time=None,
            parents=[], web_view_link=None
        )

        assert file.is_supported_type is True

    def test_is_supported_type_htm(self):
        """is_supported_type プロパティ: HTM（サポート対象）"""
        file = DriveFile(
            id="1", name="page.htm", mime_type="text/html",
            size=100, modified_time=None, created_time=None,
            parents=[], web_view_link=None
        )

        assert file.is_supported_type is True

    def test_is_supported_type_xlsx(self):
        """is_supported_type プロパティ: XLSX（サポート対象）"""
        file = DriveFile(
            id="1", name="spreadsheet.xlsx", mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            size=100, modified_time=None, created_time=None,
            parents=[], web_view_link=None
        )

        assert file.is_supported_type is True

    def test_is_supported_type_xls(self):
        """is_supported_type プロパティ: XLS（サポート対象）"""
        file = DriveFile(
            id="1", name="old_spreadsheet.xls", mime_type="application/vnd.ms-excel",
            size=100, modified_time=None, created_time=None,
            parents=[], web_view_link=None
        )

        assert file.is_supported_type is True

    def test_is_supported_type_pptx(self):
        """is_supported_type プロパティ: PPTX（サポート対象）"""
        file = DriveFile(
            id="1", name="presentation.pptx", mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            size=100, modified_time=None, created_time=None,
            parents=[], web_view_link=None
        )

        assert file.is_supported_type is True

    def test_is_supported_type_ppt(self):
        """is_supported_type プロパティ: PPT（サポート対象）"""
        file = DriveFile(
            id="1", name="old_presentation.ppt", mime_type="application/vnd.ms-powerpoint",
            size=100, modified_time=None, created_time=None,
            parents=[], web_view_link=None
        )

        assert file.is_supported_type is True

    def test_is_supported_type_unsupported_image(self):
        """is_supported_type プロパティ: 画像（非サポート）"""
        file = DriveFile(
            id="1", name="photo.jpg", mime_type="image/jpeg",
            size=100, modified_time=None, created_time=None,
            parents=[], web_view_link=None
        )

        assert file.is_supported_type is False

    def test_is_supported_type_unsupported_video(self):
        """is_supported_type プロパティ: 動画（非サポート）"""
        file = DriveFile(
            id="1", name="video.mp4", mime_type="video/mp4",
            size=100, modified_time=None, created_time=None,
            parents=[], web_view_link=None
        )

        assert file.is_supported_type is False

    def test_is_supported_type_no_extension_but_plain_text(self):
        """is_supported_type プロパティ: 拡張子なしでも text/plain は対応"""
        file = DriveFile(
            id="1", name="README", mime_type="text/plain",
            size=100, modified_time=None, created_time=None,
            parents=[], web_view_link=None
        )
        # MIMEタイプで判定するため text/plain は対応済み
        assert file.is_supported_type is True

    def test_is_supported_type_unknown_mime(self):
        """is_supported_type プロパティ: 未対応のMIMEタイプは False"""
        file = DriveFile(
            id="1", name="binary.bin", mime_type="application/octet-stream",
            size=100, modified_time=None, created_time=None,
            parents=[], web_view_link=None
        )
        assert file.is_supported_type is False


# ================================================================
# DriveChange データクラスのテスト
# ================================================================

class TestDriveChange:
    """DriveChange データクラスのテスト"""

    def test_basic_creation_added(self):
        """追加タイプの変更"""
        file = DriveFile(
            id="file123", name="new_file.pdf", mime_type="application/pdf",
            size=1024, modified_time=datetime.now(timezone.utc),
            created_time=datetime.now(timezone.utc),
            parents=["folder123"], web_view_link=None
        )

        change = DriveChange(
            file_id="file123",
            removed=False,
            file=file,
            change_type="added",
            time=datetime.now(timezone.utc),
        )

        assert change.file_id == "file123"
        assert change.removed is False
        assert change.file is not None
        assert change.change_type == "added"

    def test_basic_creation_modified(self):
        """更新タイプの変更"""
        file = DriveFile(
            id="file456", name="updated_file.docx",
            mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            size=2048, modified_time=datetime.now(timezone.utc),
            created_time=datetime.now(timezone.utc),
            parents=["folder456"], web_view_link=None
        )

        change = DriveChange(
            file_id="file456",
            removed=False,
            file=file,
            change_type="modified",
            time=datetime.now(timezone.utc),
        )

        assert change.change_type == "modified"
        assert change.file.name == "updated_file.docx"

    def test_basic_creation_removed(self):
        """削除タイプの変更"""
        change = DriveChange(
            file_id="file789",
            removed=True,
            file=None,
            change_type="removed",
            time=datetime.now(timezone.utc),
        )

        assert change.removed is True
        assert change.file is None
        assert change.change_type == "removed"

    def test_change_with_trashed_file(self):
        """ゴミ箱に移動されたファイルの変更"""
        file = DriveFile(
            id="file_trashed", name="deleted.pdf", mime_type="application/pdf",
            size=512, modified_time=datetime.now(timezone.utc),
            created_time=datetime.now(timezone.utc),
            parents=[], web_view_link=None, trashed=True
        )

        change = DriveChange(
            file_id="file_trashed",
            removed=False,
            file=file,
            change_type="removed",
            time=datetime.now(timezone.utc),
        )

        assert change.file.trashed is True
        assert change.change_type == "removed"


# ================================================================
# SyncResult データクラスのテスト
# ================================================================

class TestSyncResult:
    """SyncResult データクラスのテスト"""

    def test_default_values(self):
        """デフォルト値でのインスタンス生成"""
        result = SyncResult()

        assert result.files_checked == 0
        assert result.files_added == 0
        assert result.files_updated == 0
        assert result.files_deleted == 0
        assert result.files_skipped == 0
        assert result.files_failed == 0
        assert result.new_page_token is None
        assert result.failed_files == []

    def test_custom_values(self):
        """カスタム値でのインスタンス生成"""
        result = SyncResult(
            files_checked=100,
            files_added=10,
            files_updated=20,
            files_deleted=5,
            files_skipped=60,
            files_failed=5,
            new_page_token="new_token_abc",
            failed_files=["file1", "file2", "file3", "file4", "file5"],
        )

        assert result.files_checked == 100
        assert result.files_added == 10
        assert result.files_updated == 20
        assert result.files_deleted == 5
        assert result.files_skipped == 60
        assert result.files_failed == 5
        assert result.new_page_token == "new_token_abc"
        assert len(result.failed_files) == 5

    def test_partial_values(self):
        """一部の値のみ指定"""
        result = SyncResult(
            files_checked=50,
            files_added=5,
            new_page_token="partial_token",
        )

        assert result.files_checked == 50
        assert result.files_added == 5
        assert result.files_updated == 0  # デフォルト
        assert result.new_page_token == "partial_token"


# ================================================================
# GoogleDriveClient のテスト
# ================================================================

class TestGoogleDriveClientInitialization:
    """GoogleDriveClient 初期化のテスト"""

    @patch('lib.google_drive.build')
    @patch('lib.google_drive.service_account.Credentials.from_service_account_info')
    @patch('lib.google_drive.get_settings')
    def test_init_with_service_account_info(self, mock_settings, mock_creds, mock_build):
        """サービスアカウント情報（辞書）での初期化"""
        mock_settings.return_value = MagicMock()
        mock_creds.return_value = MagicMock()
        mock_build.return_value = MagicMock()

        service_account_info = {
            "type": "service_account",
            "project_id": "test-project",
            "private_key_id": "key123",
            "private_key": "DUMMY_PRIVATE_KEY_FOR_TESTING",
            "client_email": "test@test-project.iam.gserviceaccount.com",
        }

        client = GoogleDriveClient(service_account_info=service_account_info)

        mock_creds.assert_called_once()
        mock_build.assert_called_once_with('drive', 'v3', credentials=mock_creds.return_value)

    @patch('lib.google_drive.build')
    @patch('lib.google_drive.service_account.Credentials.from_service_account_file')
    @patch('lib.google_drive.get_settings')
    def test_init_with_service_account_file(self, mock_settings, mock_creds, mock_build):
        """サービスアカウントファイルでの初期化"""
        mock_settings.return_value = MagicMock()
        mock_creds.return_value = MagicMock()
        mock_build.return_value = MagicMock()

        client = GoogleDriveClient(service_account_file="/path/to/service_account.json")

        mock_creds.assert_called_once_with(
            "/path/to/service_account.json",
            scopes=['https://www.googleapis.com/auth/drive.readonly']
        )
        mock_build.assert_called_once()

    @patch.dict('os.environ', {'GOOGLE_SERVICE_ACCOUNT_FILE': '/env/path/sa.json'})
    @patch('lib.google_drive.build')
    @patch('lib.google_drive.service_account.Credentials.from_service_account_file')
    @patch('lib.google_drive.get_settings')
    def test_init_with_env_variable(self, mock_settings, mock_creds, mock_build):
        """環境変数からのサービスアカウントファイルパスでの初期化"""
        mock_settings.return_value = MagicMock()
        mock_creds.return_value = MagicMock()
        mock_build.return_value = MagicMock()

        client = GoogleDriveClient()

        mock_creds.assert_called_once_with(
            '/env/path/sa.json',
            scopes=['https://www.googleapis.com/auth/drive.readonly']
        )

    @patch.dict('os.environ', {}, clear=True)
    @patch('lib.google_drive.build')
    @patch('lib.google_drive.get_settings')
    @patch('google.auth.default')
    def test_init_with_default_credentials(self, mock_default, mock_settings, mock_build):
        """Application Default Credentialsでの初期化"""
        mock_settings.return_value = MagicMock()
        mock_default.return_value = (MagicMock(), "project-id")
        mock_build.return_value = MagicMock()

        # 環境変数を削除
        import os
        if 'GOOGLE_SERVICE_ACCOUNT_FILE' in os.environ:
            del os.environ['GOOGLE_SERVICE_ACCOUNT_FILE']

        client = GoogleDriveClient()

        mock_default.assert_called_once_with(
            scopes=['https://www.googleapis.com/auth/drive.readonly']
        )


class TestGoogleDriveClientGetStartPageToken:
    """GoogleDriveClient.get_start_page_token のテスト"""

    @pytest.fixture
    def mock_client(self):
        """モックされたGoogleDriveClient"""
        with patch('lib.google_drive.build') as mock_build, \
             patch('lib.google_drive.service_account.Credentials.from_service_account_info') as mock_creds, \
             patch('lib.google_drive.get_settings') as mock_settings:
            mock_settings.return_value = MagicMock()
            mock_creds.return_value = MagicMock()

            service = MagicMock()
            mock_build.return_value = service

            client = GoogleDriveClient(service_account_info={"type": "service_account"})
            client.service = service

            return client, service

    @pytest.mark.asyncio
    async def test_get_start_page_token_success(self, mock_client):
        """ページトークン取得成功"""
        client, service = mock_client

        # モックの設定
        start_token_mock = MagicMock()
        start_token_mock.execute.return_value = {'startPageToken': 'initial_token_123'}
        service.changes.return_value.getStartPageToken.return_value = start_token_mock

        token = await client.get_start_page_token()

        assert token == 'initial_token_123'
        service.changes.return_value.getStartPageToken.assert_called_once()


class TestGoogleDriveClientGetChanges:
    """GoogleDriveClient.get_changes のテスト"""

    @pytest.fixture
    def mock_client(self):
        """モックされたGoogleDriveClient"""
        with patch('lib.google_drive.build') as mock_build, \
             patch('lib.google_drive.service_account.Credentials.from_service_account_info') as mock_creds, \
             patch('lib.google_drive.get_settings') as mock_settings:
            mock_settings.return_value = MagicMock()
            mock_creds.return_value = MagicMock()

            service = MagicMock()
            mock_build.return_value = service

            client = GoogleDriveClient(service_account_info={"type": "service_account"})
            client.service = service

            return client, service

    @pytest.mark.asyncio
    async def test_get_changes_empty(self, mock_client):
        """変更なしの場合"""
        client, service = mock_client

        changes_mock = MagicMock()
        changes_mock.execute.return_value = {
            'changes': [],
            'newStartPageToken': 'new_token_abc'
        }
        service.changes.return_value.list.return_value = changes_mock

        changes, new_token = await client.get_changes('old_token')

        assert changes == []
        assert new_token == 'new_token_abc'

    @pytest.mark.asyncio
    async def test_get_changes_with_file_added(self, mock_client):
        """ファイル追加の変更"""
        client, service = mock_client

        changes_mock = MagicMock()
        changes_mock.execute.return_value = {
            'changes': [
                {
                    'fileId': 'file123',
                    'removed': False,
                    'file': {
                        'id': 'file123',
                        'name': 'new_document.pdf',
                        'mimeType': 'application/pdf',
                        'size': '1024',
                        'modifiedTime': '2026-01-15T10:00:00.000Z',
                        'createdTime': '2026-01-15T09:00:00.000Z',
                        'parents': ['folder123'],
                        'webViewLink': 'https://drive.google.com/file/d/file123/view',
                        'trashed': False,
                    }
                }
            ],
            'newStartPageToken': 'new_token_def'
        }
        service.changes.return_value.list.return_value = changes_mock

        changes, new_token = await client.get_changes('old_token')

        assert len(changes) == 1
        assert changes[0].file_id == 'file123'
        assert changes[0].file.name == 'new_document.pdf'
        assert changes[0].change_type == 'modified'  # 新規か更新かはDB側で判定するため、常にmodified

    @pytest.mark.asyncio
    async def test_get_changes_with_file_removed(self, mock_client):
        """ファイル削除の変更"""
        client, service = mock_client

        changes_mock = MagicMock()
        changes_mock.execute.return_value = {
            'changes': [
                {
                    'fileId': 'file_deleted',
                    'removed': True,
                    'file': None,
                }
            ],
            'newStartPageToken': 'new_token_ghi'
        }
        service.changes.return_value.list.return_value = changes_mock

        changes, new_token = await client.get_changes('old_token')

        assert len(changes) == 1
        assert changes[0].file_id == 'file_deleted'
        assert changes[0].removed is True
        assert changes[0].change_type == 'removed'

    @pytest.mark.asyncio
    async def test_get_changes_with_trashed_file(self, mock_client):
        """ゴミ箱に移動されたファイルの変更"""
        client, service = mock_client

        changes_mock = MagicMock()
        changes_mock.execute.return_value = {
            'changes': [
                {
                    'fileId': 'file_trashed',
                    'removed': False,
                    'file': {
                        'id': 'file_trashed',
                        'name': 'to_be_deleted.pdf',
                        'mimeType': 'application/pdf',
                        'size': '512',
                        'modifiedTime': '2026-01-15T11:00:00.000Z',
                        'createdTime': '2026-01-10T09:00:00.000Z',
                        'parents': [],
                        'webViewLink': None,
                        'trashed': True,
                    }
                }
            ],
            'newStartPageToken': 'new_token_jkl'
        }
        service.changes.return_value.list.return_value = changes_mock

        changes, new_token = await client.get_changes('old_token')

        assert len(changes) == 1
        assert changes[0].file.trashed is True
        assert changes[0].change_type == 'removed'

    @pytest.mark.asyncio
    async def test_get_changes_pagination(self, mock_client):
        """複数ページにまたがる変更の取得"""
        client, service = mock_client

        # 1ページ目
        page1_mock = MagicMock()
        page1_mock.execute.return_value = {
            'changes': [
                {
                    'fileId': 'file1',
                    'removed': False,
                    'file': {
                        'id': 'file1',
                        'name': 'file1.pdf',
                        'mimeType': 'application/pdf',
                        'parents': [],
                    }
                }
            ],
            'nextPageToken': 'page2_token'
        }

        # 2ページ目
        page2_mock = MagicMock()
        page2_mock.execute.return_value = {
            'changes': [
                {
                    'fileId': 'file2',
                    'removed': False,
                    'file': {
                        'id': 'file2',
                        'name': 'file2.docx',
                        'mimeType': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                        'parents': [],
                    }
                }
            ],
            'newStartPageToken': 'final_token'
        }

        service.changes.return_value.list.return_value.execute.side_effect = [
            page1_mock.execute.return_value,
            page2_mock.execute.return_value
        ]

        changes, new_token = await client.get_changes('initial_token')

        assert len(changes) == 2
        assert changes[0].file_id == 'file1'
        assert changes[1].file_id == 'file2'
        assert new_token == 'final_token'


class TestGoogleDriveClientDownloadFile:
    """GoogleDriveClient.download_file のテスト"""

    @pytest.fixture
    def mock_client(self):
        """モックされたGoogleDriveClient"""
        with patch('lib.google_drive.build') as mock_build, \
             patch('lib.google_drive.service_account.Credentials.from_service_account_info') as mock_creds, \
             patch('lib.google_drive.get_settings') as mock_settings:
            mock_settings.return_value = MagicMock()
            mock_creds.return_value = MagicMock()

            service = MagicMock()
            mock_build.return_value = service

            client = GoogleDriveClient(service_account_info={"type": "service_account"})
            client.service = service

            return client, service

    @pytest.mark.asyncio
    async def test_download_file_success(self, mock_client):
        """ファイルダウンロード成功"""
        client, service = mock_client

        # get_file のモック
        file_get_mock = MagicMock()
        file_get_mock.execute.return_value = {
            'id': 'file123',
            'name': 'test.pdf',
            'mimeType': 'application/pdf',
            'size': '1024',
            'parents': [],
        }
        service.files.return_value.get.return_value = file_get_mock

        # get_media のモック
        media_mock = MagicMock()
        service.files.return_value.get_media.return_value = media_mock

        # MediaIoBaseDownload のモック
        with patch('lib.google_drive.MediaIoBaseDownload') as mock_downloader_class:
            mock_downloader = MagicMock()
            mock_downloader.next_chunk.side_effect = [
                (MagicMock(progress=lambda: 0.5), False),
                (MagicMock(progress=lambda: 1.0), True),
            ]
            mock_downloader_class.return_value = mock_downloader

            # バッファに書き込まれるデータをモック
            def write_to_buffer(buffer, request):
                buffer.write(b'PDF content here')
                return mock_downloader

            mock_downloader_class.side_effect = lambda buffer, request: write_to_buffer(buffer, request) or mock_downloader

            content = await client.download_file('file123')

            # ダウンローダーが呼ばれたことを確認
            assert mock_downloader.next_chunk.call_count == 2

    @pytest.mark.asyncio
    async def test_download_file_size_exceeded(self, mock_client):
        """ファイルサイズ超過エラー"""
        client, service = mock_client

        # 大きすぎるファイルサイズを設定
        file_get_mock = MagicMock()
        file_get_mock.execute.return_value = {
            'id': 'large_file',
            'name': 'large.pdf',
            'mimeType': 'application/pdf',
            'size': str(MAX_FILE_SIZE + 1),  # 最大サイズを超過
            'parents': [],
        }
        service.files.return_value.get.return_value = file_get_mock

        with pytest.raises(ValueError) as exc_info:
            await client.download_file('large_file')

        assert "ファイルサイズが大きすぎます" in str(exc_info.value)


class TestGoogleDriveClientGetFile:
    """GoogleDriveClient.get_file のテスト"""

    @pytest.fixture
    def mock_client(self):
        """モックされたGoogleDriveClient"""
        with patch('lib.google_drive.build') as mock_build, \
             patch('lib.google_drive.service_account.Credentials.from_service_account_info') as mock_creds, \
             patch('lib.google_drive.get_settings') as mock_settings:
            mock_settings.return_value = MagicMock()
            mock_creds.return_value = MagicMock()

            service = MagicMock()
            mock_build.return_value = service

            client = GoogleDriveClient(service_account_info={"type": "service_account"})
            client.service = service

            return client, service

    @pytest.mark.asyncio
    async def test_get_file_success(self, mock_client):
        """ファイル情報取得成功"""
        client, service = mock_client

        file_get_mock = MagicMock()
        file_get_mock.execute.return_value = {
            'id': 'file123',
            'name': 'document.pdf',
            'mimeType': 'application/pdf',
            'size': '2048',
            'modifiedTime': '2026-01-20T15:30:00.000Z',
            'createdTime': '2026-01-15T10:00:00.000Z',
            'parents': ['folder456'],
            'webViewLink': 'https://drive.google.com/file/d/file123/view',
            'trashed': False,
        }
        service.files.return_value.get.return_value = file_get_mock

        file = await client.get_file('file123')

        assert file is not None
        assert file.id == 'file123'
        assert file.name == 'document.pdf'
        assert file.mime_type == 'application/pdf'
        assert file.size == 2048
        assert file.modified_time is not None
        assert file.created_time is not None
        assert 'folder456' in file.parents

    @pytest.mark.asyncio
    async def test_get_file_not_found(self, mock_client):
        """ファイルが存在しない場合"""
        client, service = mock_client

        from googleapiclient.errors import HttpError

        # 404エラーをモック
        resp = MagicMock()
        resp.status = 404
        error = HttpError(resp, b'File not found')

        service.files.return_value.get.return_value.execute.side_effect = error

        file = await client.get_file('nonexistent_file')

        assert file is None

    @pytest.mark.asyncio
    async def test_get_file_other_error(self, mock_client):
        """404以外のHTTPエラー"""
        client, service = mock_client

        from googleapiclient.errors import HttpError

        # 500エラーをモック
        resp = MagicMock()
        resp.status = 500
        error = HttpError(resp, b'Internal server error')

        service.files.return_value.get.return_value.execute.side_effect = error

        with pytest.raises(HttpError):
            await client.get_file('file_with_error')


class TestGoogleDriveClientShouldSkipFile:
    """GoogleDriveClient.should_skip_file のテスト"""

    @pytest.fixture
    def client(self):
        """モックされたGoogleDriveClient"""
        with patch('lib.google_drive.build') as mock_build, \
             patch('lib.google_drive.service_account.Credentials.from_service_account_info') as mock_creds, \
             patch('lib.google_drive.get_settings') as mock_settings:
            mock_settings.return_value = MagicMock()
            mock_creds.return_value = MagicMock()
            mock_build.return_value = MagicMock()

            return GoogleDriveClient(service_account_info={"type": "service_account"})

    def test_should_skip_hidden_file(self, client):
        """隠しファイルはスキップ"""
        file = DriveFile(
            id="1", name=".hidden_file.txt", mime_type="text/plain",
            size=100, modified_time=None, created_time=None,
            parents=[], web_view_link=None
        )

        should_skip, reason = client.should_skip_file(file)

        assert should_skip is True
        assert "除外パターン" in reason

    def test_should_skip_office_temp_file(self, client):
        """Office一時ファイルはスキップ"""
        file = DriveFile(
            id="1", name="~$document.docx", mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            size=100, modified_time=None, created_time=None,
            parents=[], web_view_link=None
        )

        should_skip, reason = client.should_skip_file(file)

        assert should_skip is True
        assert "除外パターン" in reason

    def test_should_skip_tmp_file(self, client):
        """一時ファイルはスキップ"""
        file = DriveFile(
            id="1", name="temp_file.tmp", mime_type="application/octet-stream",
            size=100, modified_time=None, created_time=None,
            parents=[], web_view_link=None
        )

        should_skip, reason = client.should_skip_file(file)

        assert should_skip is True
        assert "除外パターン" in reason

    def test_should_skip_bak_file(self, client):
        """バックアップファイルはスキップ"""
        file = DriveFile(
            id="1", name="document.bak", mime_type="application/octet-stream",
            size=100, modified_time=None, created_time=None,
            parents=[], web_view_link=None
        )

        should_skip, reason = client.should_skip_file(file)

        assert should_skip is True
        assert "除外パターン" in reason

    def test_should_skip_unsupported_mime_type(self, client):
        """サポートされていないMIMEタイプはスキップ"""
        file = DriveFile(
            id="1", name="image.png", mime_type="image/png",
            size=100, modified_time=None, created_time=None,
            parents=[], web_view_link=None
        )

        should_skip, reason = client.should_skip_file(file)

        assert should_skip is True
        assert "サポートされていないファイル形式" in reason

    def test_should_not_skip_google_docs_format(self, client):
        """Google Docs形式はエクスポートAPIで対応済み — スキップしない"""
        file = DriveFile(
            id="1", name="社内規則", mime_type="application/vnd.google-apps.document",
            size=None, modified_time=None, created_time=None,
            parents=[], web_view_link=None
        )

        should_skip, reason = client.should_skip_file(file)

        assert should_skip is False

    def test_should_not_skip_google_sheets_format(self, client):
        """Google Sheets形式はエクスポートAPIで対応済み — スキップしない"""
        file = DriveFile(
            id="1", name="業務データ", mime_type="application/vnd.google-apps.spreadsheet",
            size=None, modified_time=None, created_time=None,
            parents=[], web_view_link=None
        )

        should_skip, reason = client.should_skip_file(file)

        assert should_skip is False

    def test_should_not_skip_google_slides_format(self, client):
        """Google Slides形式はエクスポートAPIで対応済み — スキップしない"""
        file = DriveFile(
            id="1", name="プレゼン", mime_type="application/vnd.google-apps.presentation",
            size=None, modified_time=None, created_time=None,
            parents=[], web_view_link=None
        )

        should_skip, reason = client.should_skip_file(file)

        assert should_skip is False

    def test_should_skip_large_file(self, client):
        """大きすぎるファイルはスキップ"""
        file = DriveFile(
            id="1", name="huge_file.pdf", mime_type="application/pdf",
            size=MAX_FILE_SIZE + 1, modified_time=None, created_time=None,
            parents=[], web_view_link=None
        )

        should_skip, reason = client.should_skip_file(file)

        assert should_skip is True
        assert "ファイルサイズ超過" in reason

    def test_should_not_skip_valid_pdf(self, client):
        """有効なPDFファイルはスキップしない"""
        file = DriveFile(
            id="1", name="valid_document.pdf", mime_type="application/pdf",
            size=1024, modified_time=None, created_time=None,
            parents=[], web_view_link=None
        )

        should_skip, reason = client.should_skip_file(file)

        assert should_skip is False
        assert reason is None

    def test_should_not_skip_valid_docx(self, client):
        """有効なDOCXファイルはスキップしない"""
        file = DriveFile(
            id="1", name="report.docx",
            mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            size=2048, modified_time=None, created_time=None,
            parents=[], web_view_link=None
        )

        should_skip, reason = client.should_skip_file(file)

        assert should_skip is False
        assert reason is None


class TestGoogleDriveClientClearCache:
    """GoogleDriveClient.clear_cache のテスト"""

    def test_clear_cache(self):
        """キャッシュクリア"""
        with patch('lib.google_drive.build') as mock_build, \
             patch('lib.google_drive.service_account.Credentials.from_service_account_info') as mock_creds, \
             patch('lib.google_drive.get_settings') as mock_settings:
            mock_settings.return_value = MagicMock()
            mock_creds.return_value = MagicMock()
            mock_build.return_value = MagicMock()

            client = GoogleDriveClient(service_account_info={"type": "service_account"})

            # キャッシュにデータを追加
            client._folder_cache['folder1'] = {'id': 'folder1', 'name': 'Folder 1'}
            client._folder_cache['folder2'] = {'id': 'folder2', 'name': 'Folder 2'}

            assert len(client._folder_cache) == 2

            # キャッシュをクリア
            client.clear_cache()

            assert len(client._folder_cache) == 0


# ================================================================
# FolderMappingConfig のテスト
# ================================================================

class TestFolderMappingConfig:
    """FolderMappingConfig データクラスのテスト"""

    def test_default_classification_map(self):
        """デフォルトの機密区分マッピング"""
        config = FolderMappingConfig()

        assert config.CLASSIFICATION_MAP["全社共有"] == "public"
        assert config.CLASSIFICATION_MAP["社員限定"] == "internal"
        assert config.CLASSIFICATION_MAP["役員限定"] == "restricted"
        assert config.CLASSIFICATION_MAP["部署別"] == "confidential"

    def test_default_category_map(self):
        """デフォルトのカテゴリマッピング"""
        config = FolderMappingConfig()

        assert config.CATEGORY_MAP["mvv"] == "A"
        assert config.CATEGORY_MAP["マニュアル"] == "B"
        assert config.CATEGORY_MAP["就業規則"] == "C"
        assert config.CATEGORY_MAP["テンプレート"] == "D"
        assert config.CATEGORY_MAP["顧客"] == "E"
        assert config.CATEGORY_MAP["サービス"] == "F"

    def test_default_department_map(self):
        """デフォルトの部署マッピング"""
        config = FolderMappingConfig()

        assert config.DEPARTMENT_MAP["営業部"] == "dept_sales"
        assert config.DEPARTMENT_MAP["総務部"] == "dept_admin"
        assert config.DEPARTMENT_MAP["開発部"] == "dept_dev"

    def test_custom_config(self):
        """カスタム設定"""
        config = FolderMappingConfig(
            CLASSIFICATION_MAP={"カスタム公開": "public"},
            CATEGORY_MAP={"カスタムカテゴリ": "X"},
            DEPARTMENT_MAP={"カスタム部署": "dept_custom"},
        )

        assert config.CLASSIFICATION_MAP == {"カスタム公開": "public"}
        assert config.CATEGORY_MAP == {"カスタムカテゴリ": "X"}
        assert config.DEPARTMENT_MAP == {"カスタム部署": "dept_custom"}


# ================================================================
# FolderMapper のテスト
# ================================================================

class TestFolderMapper:
    """FolderMapper クラスのテスト"""

    def test_init_without_db(self):
        """DB接続なしでの初期化"""
        mapper = FolderMapper("org_test")

        assert mapper.organization_id == "org_test"
        assert mapper.config is not None
        assert mapper._dept_service is None

    def test_determine_classification_public(self):
        """機密区分: public"""
        mapper = FolderMapper("org_test")

        classification = mapper.determine_classification(["Root", "全社共有", "Documents"])

        assert classification == "public"

    def test_determine_classification_internal(self):
        """機密区分: internal"""
        mapper = FolderMapper("org_test")

        classification = mapper.determine_classification(["Root", "社員限定", "Manuals"])

        assert classification == "internal"

    def test_determine_classification_restricted(self):
        """機密区分: restricted"""
        mapper = FolderMapper("org_test")

        classification = mapper.determine_classification(["Root", "役員限定", "Confidential"])

        assert classification == "restricted"

    def test_determine_classification_confidential(self):
        """機密区分: confidential"""
        mapper = FolderMapper("org_test")

        classification = mapper.determine_classification(["Root", "部署別", "営業部"])

        assert classification == "confidential"

    def test_determine_classification_default(self):
        """機密区分: デフォルト（internal）"""
        mapper = FolderMapper("org_test")

        classification = mapper.determine_classification(["Root", "Unknown", "Documents"])

        assert classification == "internal"

    def test_determine_classification_case_insensitive(self):
        """機密区分: 大文字小文字を区別しない（英語）"""
        mapper = FolderMapper("org_test")

        classification = mapper.determine_classification(["Root", "PUBLIC", "Files"])

        assert classification == "public"

    def test_determine_category_a(self):
        """カテゴリA: 理念・哲学"""
        mapper = FolderMapper("org_test")

        category = mapper.determine_category(["Root", "MVV", "Mission"])

        assert category == "A"

    def test_determine_category_b(self):
        """カテゴリB: 業務マニュアル"""
        mapper = FolderMapper("org_test")

        category = mapper.determine_category(["Root", "業務マニュアル", "経理"])

        assert category == "B"

    def test_determine_category_c(self):
        """カテゴリC: 就業規則"""
        mapper = FolderMapper("org_test")

        category = mapper.determine_category(["Root", "就業規則", "休暇"])

        assert category == "C"

    def test_determine_category_d(self):
        """カテゴリD: テンプレート"""
        mapper = FolderMapper("org_test")

        category = mapper.determine_category(["Root", "テンプレート", "申請書"])

        assert category == "D"

    def test_determine_category_e(self):
        """カテゴリE: 顧客情報"""
        mapper = FolderMapper("org_test")

        category = mapper.determine_category(["Root", "顧客情報", "A社"])

        assert category == "E"

    def test_determine_category_f(self):
        """カテゴリF: サービス情報"""
        mapper = FolderMapper("org_test")

        category = mapper.determine_category(["Root", "サービス情報", "料金表"])

        assert category == "F"

    def test_determine_category_default(self):
        """カテゴリ: デフォルト（B）"""
        mapper = FolderMapper("org_test")

        category = mapper.determine_category(["Root", "Unknown", "Documents"])

        assert category == "B"

    def test_determine_category_partial_match(self):
        """カテゴリ: 部分一致"""
        mapper = FolderMapper("org_test")

        # 「経費精算手順書」に「手順書」が含まれる → カテゴリB
        category = mapper.determine_category(["Root", "経費精算手順書", "2026年版"])

        assert category == "B"

    def test_determine_department_id_not_confidential(self):
        """部署ID: confidential以外はNone"""
        mapper = FolderMapper("org_test")

        # 社員限定（internal）の場合、部署IDはNone
        dept_id = mapper.determine_department_id(["Root", "社員限定", "営業部"])

        assert dept_id is None

    def test_determine_department_id_confidential(self):
        """部署ID: confidentialの場合は部署IDを返す"""
        mapper = FolderMapper("org_test")

        # 部署別（confidential）の場合、部署IDを返す
        dept_id = mapper.determine_department_id(["Root", "部署別", "営業部"])

        assert dept_id == "dept_sales"

    def test_determine_department_id_unknown_department(self):
        """部署ID: 未知の部署はNone"""
        mapper = FolderMapper("org_test")

        dept_id = mapper.determine_department_id(["Root", "部署別", "未知部署"])

        assert dept_id is None

    def test_map_folder_to_permissions(self):
        """map_folder_to_permissions: 全権限情報の取得"""
        mapper = FolderMapper("org_test")

        permissions = mapper.map_folder_to_permissions(["Root", "部署別", "営業部", "マニュアル"])

        assert permissions["classification"] == "confidential"
        assert permissions["category"] == "B"
        assert permissions["department_id"] == "dept_sales"

    def test_map_folder_to_permissions_public(self):
        """map_folder_to_permissions: 全社共有の権限"""
        mapper = FolderMapper("org_test")

        permissions = mapper.map_folder_to_permissions(["Root", "全社共有", "会社紹介"])

        assert permissions["classification"] == "public"
        assert permissions["category"] == "A"
        assert permissions["department_id"] is None

    def test_is_dynamic_mapping_enabled_false(self):
        """動的マッピング無効の確認"""
        mapper = FolderMapper("org_test")

        assert mapper.is_dynamic_mapping_enabled() is False

    def test_get_all_departments_static(self):
        """静的マッピングでの全部署取得"""
        mapper = FolderMapper("org_test")

        departments = mapper.get_all_departments()

        assert "営業部" in departments
        assert "総務部" in departments
        assert "開発部" in departments


# ================================================================
# 定数のテスト
# ================================================================

class TestConstants:
    """定数のテスト"""

    def test_supported_mime_types(self):
        """サポートされているMIMEタイプ"""
        assert 'application/pdf' in SUPPORTED_MIME_TYPES
        assert 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' in SUPPORTED_MIME_TYPES
        assert 'text/plain' in SUPPORTED_MIME_TYPES
        assert 'text/html' in SUPPORTED_MIME_TYPES

    def test_max_file_size(self):
        """最大ファイルサイズ"""
        assert MAX_FILE_SIZE == 50 * 1024 * 1024  # 50MB

    def test_exclude_patterns_hidden_file(self):
        """除外パターン: 隠しファイル"""
        hidden_pattern = EXCLUDE_PATTERNS[0]

        assert hidden_pattern(".hidden") is True
        assert hidden_pattern(".gitignore") is True
        assert hidden_pattern("normal_file") is False

    def test_exclude_patterns_office_temp(self):
        """除外パターン: Office一時ファイル"""
        temp_pattern = EXCLUDE_PATTERNS[1]

        assert temp_pattern("~$document.docx") is True
        assert temp_pattern("~$spreadsheet.xlsx") is True
        assert temp_pattern("document.docx") is False

    def test_exclude_patterns_tmp(self):
        """除外パターン: .tmp ファイル"""
        tmp_pattern = EXCLUDE_PATTERNS[2]

        assert tmp_pattern("file.tmp") is True
        assert tmp_pattern("file.txt") is False

    def test_exclude_patterns_bak(self):
        """除外パターン: .bak ファイル"""
        bak_pattern = EXCLUDE_PATTERNS[3]

        assert bak_pattern("file.bak") is True
        assert bak_pattern("file.pdf") is False


# ================================================================
# HttpError 処理のテスト
# ================================================================

class TestHttpErrorHandling:
    """HttpError 処理のテスト"""

    @pytest.fixture
    def mock_client(self):
        """モックされたGoogleDriveClient"""
        with patch('lib.google_drive.build') as mock_build, \
             patch('lib.google_drive.service_account.Credentials.from_service_account_info') as mock_creds, \
             patch('lib.google_drive.get_settings') as mock_settings:
            mock_settings.return_value = MagicMock()
            mock_creds.return_value = MagicMock()

            service = MagicMock()
            mock_build.return_value = service

            client = GoogleDriveClient(service_account_info={"type": "service_account"})
            client.service = service

            return client, service

    @pytest.mark.asyncio
    async def test_get_folder_info_404_returns_none(self, mock_client):
        """_get_folder_info: 404エラーでNoneを返す"""
        client, service = mock_client

        from googleapiclient.errors import HttpError

        resp = MagicMock()
        resp.status = 404
        error = HttpError(resp, b'Folder not found')

        service.files.return_value.get.return_value.execute.side_effect = error

        result = await client._get_folder_info('nonexistent_folder')

        assert result is None

    @pytest.mark.asyncio
    async def test_get_folder_info_500_raises(self, mock_client):
        """_get_folder_info: 500エラーは例外を発生"""
        client, service = mock_client

        from googleapiclient.errors import HttpError

        resp = MagicMock()
        resp.status = 500
        error = HttpError(resp, b'Internal server error')

        service.files.return_value.get.return_value.execute.side_effect = error

        with pytest.raises(HttpError):
            await client._get_folder_info('error_folder')

    @pytest.mark.asyncio
    async def test_get_folder_info_uses_cache(self, mock_client):
        """_get_folder_info: キャッシュを使用"""
        client, service = mock_client

        # キャッシュにデータを追加
        client._folder_cache['cached_folder'] = {
            'id': 'cached_folder',
            'name': 'Cached Folder',
            'parents': ['parent_folder']
        }

        result = await client._get_folder_info('cached_folder')

        # APIは呼ばれない
        service.files.return_value.get.assert_not_called()

        assert result['id'] == 'cached_folder'
        assert result['name'] == 'Cached Folder'


# ================================================================
# _parse_file メソッドのテスト
# ================================================================

class TestParseFile:
    """_parse_file メソッドのテスト"""

    @pytest.fixture
    def client(self):
        """モックされたGoogleDriveClient"""
        with patch('lib.google_drive.build') as mock_build, \
             patch('lib.google_drive.service_account.Credentials.from_service_account_info') as mock_creds, \
             patch('lib.google_drive.get_settings') as mock_settings:
            mock_settings.return_value = MagicMock()
            mock_creds.return_value = MagicMock()
            mock_build.return_value = MagicMock()

            return GoogleDriveClient(service_account_info={"type": "service_account"})

    def test_parse_file_full_data(self, client):
        """全データが揃っている場合"""
        file_data = {
            'id': 'file123',
            'name': 'document.pdf',
            'mimeType': 'application/pdf',
            'size': '2048',
            'modifiedTime': '2026-01-20T15:30:00Z',
            'createdTime': '2026-01-15T10:00:00Z',
            'parents': ['folder123', 'folder456'],
            'webViewLink': 'https://drive.google.com/file/d/file123/view',
            'trashed': False,
        }

        drive_file = client._parse_file(file_data)

        assert drive_file.id == 'file123'
        assert drive_file.name == 'document.pdf'
        assert drive_file.mime_type == 'application/pdf'
        assert drive_file.size == 2048
        assert drive_file.modified_time is not None
        assert drive_file.created_time is not None
        assert len(drive_file.parents) == 2
        assert drive_file.web_view_link is not None
        assert drive_file.trashed is False

    def test_parse_file_minimal_data(self, client):
        """最小限のデータの場合"""
        file_data = {
            'id': 'file_min',
            'name': 'minimal.txt',
        }

        drive_file = client._parse_file(file_data)

        assert drive_file.id == 'file_min'
        assert drive_file.name == 'minimal.txt'
        assert drive_file.mime_type == ''
        assert drive_file.size is None
        assert drive_file.modified_time is None
        assert drive_file.created_time is None
        assert drive_file.parents == []
        assert drive_file.web_view_link is None
        assert drive_file.trashed is False

    def test_parse_file_trashed(self, client):
        """ゴミ箱に入っているファイル"""
        file_data = {
            'id': 'file_trashed',
            'name': 'deleted.pdf',
            'mimeType': 'application/pdf',
            'trashed': True,
        }

        drive_file = client._parse_file(file_data)

        assert drive_file.trashed is True


# ================================================================
# list_files_in_folder のテスト
# ================================================================

class TestListFilesInFolder:
    """list_files_in_folder メソッドのテスト"""

    @pytest.fixture
    def mock_client(self):
        """モックされたGoogleDriveClient"""
        with patch('lib.google_drive.build') as mock_build, \
             patch('lib.google_drive.service_account.Credentials.from_service_account_info') as mock_creds, \
             patch('lib.google_drive.get_settings') as mock_settings:
            mock_settings.return_value = MagicMock()
            mock_creds.return_value = MagicMock()

            service = MagicMock()
            mock_build.return_value = service

            client = GoogleDriveClient(service_account_info={"type": "service_account"})
            client.service = service

            return client, service

    @pytest.mark.asyncio
    async def test_list_files_empty_folder(self, mock_client):
        """空フォルダの場合"""
        client, service = mock_client

        list_mock = MagicMock()
        list_mock.execute.return_value = {
            'files': [],
            'nextPageToken': None
        }
        service.files.return_value.list.return_value = list_mock

        files = []
        async for file in client.list_files_in_folder('empty_folder'):
            files.append(file)

        assert len(files) == 0

    @pytest.mark.asyncio
    async def test_list_files_with_files(self, mock_client):
        """ファイルが存在するフォルダ"""
        client, service = mock_client

        list_mock = MagicMock()
        list_mock.execute.return_value = {
            'files': [
                {
                    'id': 'file1',
                    'name': 'document1.pdf',
                    'mimeType': 'application/pdf',
                    'size': '1024',
                    'parents': ['folder123'],
                },
                {
                    'id': 'file2',
                    'name': 'document2.docx',
                    'mimeType': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                    'size': '2048',
                    'parents': ['folder123'],
                }
            ],
            'nextPageToken': None
        }
        service.files.return_value.list.return_value = list_mock

        files = []
        async for file in client.list_files_in_folder('folder123'):
            files.append(file)

        assert len(files) == 2
        assert files[0].name == 'document1.pdf'
        assert files[1].name == 'document2.docx'


# ================================================================
# get_folder_path のテスト
# ================================================================

class TestGetFolderPath:
    """get_folder_path メソッドのテスト"""

    @pytest.fixture
    def mock_client(self):
        """モックされたGoogleDriveClient"""
        with patch('lib.google_drive.build') as mock_build, \
             patch('lib.google_drive.service_account.Credentials.from_service_account_info') as mock_creds, \
             patch('lib.google_drive.get_settings') as mock_settings:
            mock_settings.return_value = MagicMock()
            mock_creds.return_value = MagicMock()

            service = MagicMock()
            mock_build.return_value = service

            client = GoogleDriveClient(service_account_info={"type": "service_account"})
            client.service = service

            return client, service

    @pytest.mark.asyncio
    async def test_get_folder_path_no_parents(self, mock_client):
        """親フォルダがない場合"""
        client, service = mock_client

        file = DriveFile(
            id="file_root", name="root_file.pdf", mime_type="application/pdf",
            size=100, modified_time=None, created_time=None,
            parents=[], web_view_link=None
        )

        path = await client.get_folder_path(file)

        assert path == []

    @pytest.mark.asyncio
    async def test_get_folder_path_single_level(self, mock_client):
        """1階層のパス"""
        client, service = mock_client

        file = DriveFile(
            id="file1", name="document.pdf", mime_type="application/pdf",
            size=100, modified_time=None, created_time=None,
            parents=["folder1"], web_view_link=None
        )

        # フォルダ情報のモック
        folder_get_mock = MagicMock()
        folder_get_mock.execute.return_value = {
            'id': 'folder1',
            'name': 'Documents',
            'parents': []
        }
        service.files.return_value.get.return_value = folder_get_mock

        path = await client.get_folder_path(file)

        assert path == ['Documents']

    @pytest.mark.asyncio
    async def test_get_folder_path_multiple_levels(self, mock_client):
        """複数階層のパス"""
        client, service = mock_client

        file = DriveFile(
            id="file1", name="document.pdf", mime_type="application/pdf",
            size=100, modified_time=None, created_time=None,
            parents=["folder3"], web_view_link=None
        )

        # フォルダ情報のモック（階層的に返す）
        folder_responses = [
            {'id': 'folder3', 'name': 'Manuals', 'parents': ['folder2']},
            {'id': 'folder2', 'name': 'Documents', 'parents': ['folder1']},
            {'id': 'folder1', 'name': 'Root', 'parents': []},
        ]

        service.files.return_value.get.return_value.execute.side_effect = folder_responses

        path = await client.get_folder_path(file)

        assert path == ['Root', 'Documents', 'Manuals']


# ================================================================
# _is_in_folder のテスト
# ================================================================

class TestIsInFolder:
    """_is_in_folder メソッドのテスト"""

    @pytest.fixture
    def mock_client(self):
        """モックされたGoogleDriveClient"""
        with patch('lib.google_drive.build') as mock_build, \
             patch('lib.google_drive.service_account.Credentials.from_service_account_info') as mock_creds, \
             patch('lib.google_drive.get_settings') as mock_settings:
            mock_settings.return_value = MagicMock()
            mock_creds.return_value = MagicMock()

            service = MagicMock()
            mock_build.return_value = service

            client = GoogleDriveClient(service_account_info={"type": "service_account"})
            client.service = service

            return client, service

    @pytest.mark.asyncio
    async def test_is_in_folder_no_parents(self, mock_client):
        """親フォルダがない場合はFalse"""
        client, service = mock_client

        file = DriveFile(
            id="file1", name="orphan.pdf", mime_type="application/pdf",
            size=100, modified_time=None, created_time=None,
            parents=[], web_view_link=None
        )

        result = await client._is_in_folder(file, "root_folder")

        assert result is False

    @pytest.mark.asyncio
    async def test_is_in_folder_direct_child(self, mock_client):
        """直接の子フォルダの場合はTrue"""
        client, service = mock_client

        file = DriveFile(
            id="file1", name="document.pdf", mime_type="application/pdf",
            size=100, modified_time=None, created_time=None,
            parents=["root_folder"], web_view_link=None
        )

        result = await client._is_in_folder(file, "root_folder")

        assert result is True
