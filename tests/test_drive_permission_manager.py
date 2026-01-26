"""
Drive Permission Manager テスト

Phase B: Google Drive 自動権限管理機能
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime

from lib.drive_permission_manager import (
    DrivePermissionManager,
    DrivePermission,
    PermissionChange,
    PermissionSyncResult,
    PermissionRole,
    PermissionType,
    ROLE_LEVEL_TO_PERMISSION,
)


# ================================================================
# Fixtures
# ================================================================

@pytest.fixture
def mock_credentials():
    """モック認証情報"""
    with patch('lib.drive_permission_manager.service_account') as mock_sa:
        mock_creds = Mock()
        mock_sa.Credentials.from_service_account_info.return_value = mock_creds
        mock_sa.Credentials.from_service_account_file.return_value = mock_creds
        yield mock_sa


@pytest.fixture
def mock_drive_service(mock_credentials):
    """モックDriveサービス"""
    with patch('lib.drive_permission_manager.build') as mock_build:
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        yield mock_service


@pytest.fixture
def permission_manager(mock_drive_service):
    """テスト用DrivePermissionManager"""
    return DrivePermissionManager(
        service_account_info={'type': 'service_account', 'project_id': 'test'}
    )


# ================================================================
# Constants Tests
# ================================================================

class TestConstants:
    """定数テスト"""

    def test_permission_role_values(self):
        """権限ロールの値が正しいか"""
        assert PermissionRole.READER.value == "reader"
        assert PermissionRole.COMMENTER.value == "commenter"
        assert PermissionRole.WRITER.value == "writer"
        assert PermissionRole.ORGANIZER.value == "organizer"
        assert PermissionRole.OWNER.value == "owner"

    def test_permission_type_values(self):
        """権限タイプの値が正しいか"""
        assert PermissionType.USER.value == "user"
        assert PermissionType.GROUP.value == "group"
        assert PermissionType.DOMAIN.value == "domain"
        assert PermissionType.ANYONE.value == "anyone"

    def test_role_level_to_permission_mapping(self):
        """役職レベル→権限マッピングが正しいか"""
        assert ROLE_LEVEL_TO_PERMISSION[1] == PermissionRole.READER
        assert ROLE_LEVEL_TO_PERMISSION[2] == PermissionRole.READER
        assert ROLE_LEVEL_TO_PERMISSION[3] == PermissionRole.COMMENTER
        assert ROLE_LEVEL_TO_PERMISSION[4] == PermissionRole.WRITER
        assert ROLE_LEVEL_TO_PERMISSION[5] == PermissionRole.WRITER
        assert ROLE_LEVEL_TO_PERMISSION[6] == PermissionRole.WRITER


# ================================================================
# DrivePermission Tests
# ================================================================

class TestDrivePermission:
    """DrivePermissionデータクラスのテスト"""

    def test_is_user_permission(self):
        """ユーザー権限の判定"""
        user_perm = DrivePermission(
            id="perm1",
            type=PermissionType.USER,
            role=PermissionRole.READER,
            email_address="test@example.com"
        )
        assert user_perm.is_user_permission is True

        group_perm = DrivePermission(
            id="perm2",
            type=PermissionType.GROUP,
            role=PermissionRole.READER
        )
        assert group_perm.is_user_permission is False

    def test_is_editable(self):
        """編集可能権限の判定"""
        reader = DrivePermission(
            id="perm1",
            type=PermissionType.USER,
            role=PermissionRole.READER
        )
        assert reader.is_editable is True

        owner = DrivePermission(
            id="perm2",
            type=PermissionType.USER,
            role=PermissionRole.OWNER
        )
        assert owner.is_editable is False


# ================================================================
# PermissionChange Tests
# ================================================================

class TestPermissionChange:
    """PermissionChangeデータクラスのテスト"""

    def test_timestamp_auto_set(self):
        """タイムスタンプが自動設定されるか"""
        change = PermissionChange(
            file_id="file1",
            file_name="test.txt",
            action="add",
            email="test@example.com"
        )
        assert change.timestamp is not None
        assert isinstance(change.timestamp, datetime)

    def test_explicit_timestamp(self):
        """明示的なタイムスタンプ"""
        ts = datetime(2026, 1, 1, 12, 0, 0)
        change = PermissionChange(
            file_id="file1",
            file_name="test.txt",
            action="add",
            email="test@example.com",
            timestamp=ts
        )
        assert change.timestamp == ts


# ================================================================
# PermissionSyncResult Tests
# ================================================================

class TestPermissionSyncResult:
    """PermissionSyncResultデータクラスのテスト"""

    def test_total_changes(self):
        """合計変更数の計算"""
        result = PermissionSyncResult(
            folder_id="folder1",
            permissions_added=3,
            permissions_removed=2,
            permissions_updated=1
        )
        assert result.total_changes == 6

    def test_changes_list_default(self):
        """changesリストのデフォルト値"""
        result = PermissionSyncResult(folder_id="folder1")
        assert result.changes == []
        assert isinstance(result.changes, list)


# ================================================================
# DrivePermissionManager Tests
# ================================================================

class TestDrivePermissionManager:
    """DrivePermissionManagerのテスト"""

    @pytest.mark.asyncio
    async def test_list_permissions(self, permission_manager, mock_drive_service):
        """権限一覧取得"""
        mock_permissions = Mock()
        mock_permissions.list.return_value.execute.return_value = {
            'permissions': [
                {
                    'id': 'perm1',
                    'type': 'user',
                    'role': 'reader',
                    'emailAddress': 'user1@example.com',
                    'displayName': 'User One'
                },
                {
                    'id': 'perm2',
                    'type': 'user',
                    'role': 'writer',
                    'emailAddress': 'user2@example.com'
                }
            ]
        }
        mock_drive_service.permissions.return_value = mock_permissions

        permissions = await permission_manager.list_permissions("file123")

        assert len(permissions) == 2
        assert permissions[0].email_address == 'user1@example.com'
        assert permissions[0].role == PermissionRole.READER
        assert permissions[1].role == PermissionRole.WRITER

    @pytest.mark.asyncio
    async def test_get_permission_by_email(self, permission_manager, mock_drive_service):
        """メールアドレスで権限検索"""
        mock_permissions = Mock()
        mock_permissions.list.return_value.execute.return_value = {
            'permissions': [
                {
                    'id': 'perm1',
                    'type': 'user',
                    'role': 'reader',
                    'emailAddress': 'user1@example.com'
                }
            ]
        }
        mock_drive_service.permissions.return_value = mock_permissions

        # 存在するメール
        perm = await permission_manager.get_permission_by_email(
            "file123", "user1@example.com"
        )
        assert perm is not None
        assert perm.email_address == 'user1@example.com'

        # 大文字小文字を無視
        perm2 = await permission_manager.get_permission_by_email(
            "file123", "USER1@EXAMPLE.COM"
        )
        assert perm2 is not None

    @pytest.mark.asyncio
    async def test_add_permission_dry_run(self, permission_manager, mock_drive_service):
        """権限追加（dry run）"""
        mock_permissions = Mock()
        mock_permissions.list.return_value.execute.return_value = {'permissions': []}
        mock_drive_service.permissions.return_value = mock_permissions

        mock_files = Mock()
        mock_files.get.return_value.execute.return_value = {
            'id': 'file123',
            'name': 'Test File'
        }
        mock_drive_service.files.return_value = mock_files

        change = await permission_manager.add_permission(
            file_id="file123",
            email="newuser@example.com",
            role=PermissionRole.READER,
            dry_run=True
        )

        assert change.success is True
        assert change.action == "add"
        assert change.email == "newuser@example.com"
        assert change.new_role == PermissionRole.READER
        # dry runなのでcreateは呼ばれない
        mock_permissions.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_add_permission_existing(self, permission_manager, mock_drive_service):
        """既存の権限がある場合"""
        mock_permissions = Mock()
        mock_permissions.list.return_value.execute.return_value = {
            'permissions': [
                {
                    'id': 'perm1',
                    'type': 'user',
                    'role': 'reader',
                    'emailAddress': 'existing@example.com'
                }
            ]
        }
        mock_drive_service.permissions.return_value = mock_permissions

        mock_files = Mock()
        mock_files.get.return_value.execute.return_value = {'id': 'file123', 'name': 'Test'}
        mock_drive_service.files.return_value = mock_files

        change = await permission_manager.add_permission(
            file_id="file123",
            email="existing@example.com",
            role=PermissionRole.READER
        )

        assert change.action == "unchanged"
        assert change.old_role == PermissionRole.READER

    @pytest.mark.asyncio
    async def test_remove_permission_dry_run(self, permission_manager, mock_drive_service):
        """権限削除（dry run）"""
        mock_permissions = Mock()
        mock_permissions.list.return_value.execute.return_value = {
            'permissions': [
                {
                    'id': 'perm1',
                    'type': 'user',
                    'role': 'reader',
                    'emailAddress': 'user@example.com'
                }
            ]
        }
        mock_drive_service.permissions.return_value = mock_permissions

        mock_files = Mock()
        mock_files.get.return_value.execute.return_value = {'id': 'file123', 'name': 'Test'}
        mock_drive_service.files.return_value = mock_files

        change = await permission_manager.remove_permission(
            file_id="file123",
            email="user@example.com",
            dry_run=True
        )

        assert change.success is True
        assert change.action == "remove"
        assert change.old_role == PermissionRole.READER
        # dry runなのでdeleteは呼ばれない
        mock_permissions.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_remove_permission_not_found(self, permission_manager, mock_drive_service):
        """存在しない権限の削除"""
        mock_permissions = Mock()
        mock_permissions.list.return_value.execute.return_value = {'permissions': []}
        mock_drive_service.permissions.return_value = mock_permissions

        mock_files = Mock()
        mock_files.get.return_value.execute.return_value = {'id': 'file123', 'name': 'Test'}
        mock_drive_service.files.return_value = mock_files

        change = await permission_manager.remove_permission(
            file_id="file123",
            email="notfound@example.com"
        )

        assert change.success is True
        assert "not found" in change.error_message.lower()

    @pytest.mark.asyncio
    async def test_update_permission_dry_run(self, permission_manager, mock_drive_service):
        """権限更新（dry run）"""
        mock_permissions = Mock()
        mock_permissions.list.return_value.execute.return_value = {
            'permissions': [
                {
                    'id': 'perm1',
                    'type': 'user',
                    'role': 'reader',
                    'emailAddress': 'user@example.com'
                }
            ]
        }
        mock_drive_service.permissions.return_value = mock_permissions

        mock_files = Mock()
        mock_files.get.return_value.execute.return_value = {'id': 'file123', 'name': 'Test'}
        mock_drive_service.files.return_value = mock_files

        change = await permission_manager.update_permission(
            file_id="file123",
            email="user@example.com",
            new_role=PermissionRole.WRITER,
            dry_run=True
        )

        assert change.success is True
        assert change.action == "update"
        assert change.old_role == PermissionRole.READER
        assert change.new_role == PermissionRole.WRITER
        mock_permissions.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_sync_folder_permissions_dry_run(self, permission_manager, mock_drive_service):
        """フォルダ権限同期（dry run）"""
        mock_permissions = Mock()
        mock_permissions.list.return_value.execute.return_value = {
            'permissions': [
                {
                    'id': 'perm1',
                    'type': 'user',
                    'role': 'reader',
                    'emailAddress': 'existing@example.com'
                }
            ]
        }
        mock_drive_service.permissions.return_value = mock_permissions

        mock_files = Mock()
        mock_files.get.return_value.execute.return_value = {'id': 'folder1', 'name': 'Test Folder'}
        mock_drive_service.files.return_value = mock_files

        expected = {
            'existing@example.com': PermissionRole.WRITER,  # 更新
            'new@example.com': PermissionRole.READER,       # 追加
        }

        result = await permission_manager.sync_folder_permissions(
            folder_id="folder1",
            expected_permissions=expected,
            dry_run=True
        )

        assert result.dry_run is True
        assert result.permissions_updated == 1
        assert result.permissions_added == 1
        assert result.total_changes == 2

    @pytest.mark.asyncio
    async def test_sync_folder_permissions_remove_unlisted(self, permission_manager, mock_drive_service):
        """リストにない権限を削除"""
        mock_permissions = Mock()
        mock_permissions.list.return_value.execute.return_value = {
            'permissions': [
                {
                    'id': 'perm1',
                    'type': 'user',
                    'role': 'reader',
                    'emailAddress': 'keep@example.com'
                },
                {
                    'id': 'perm2',
                    'type': 'user',
                    'role': 'reader',
                    'emailAddress': 'remove@example.com'
                }
            ]
        }
        mock_drive_service.permissions.return_value = mock_permissions

        mock_files = Mock()
        mock_files.get.return_value.execute.return_value = {'id': 'folder1', 'name': 'Test'}
        mock_drive_service.files.return_value = mock_files

        expected = {
            'keep@example.com': PermissionRole.READER,
        }

        result = await permission_manager.sync_folder_permissions(
            folder_id="folder1",
            expected_permissions=expected,
            remove_unlisted=True,
            dry_run=True
        )

        assert result.permissions_unchanged == 1
        assert result.permissions_removed == 1

    @pytest.mark.asyncio
    async def test_sync_folder_permissions_protected_emails(self, permission_manager, mock_drive_service):
        """保護されたメールアドレスは削除しない"""
        mock_permissions = Mock()
        mock_permissions.list.return_value.execute.return_value = {
            'permissions': [
                {
                    'id': 'perm1',
                    'type': 'user',
                    'role': 'reader',
                    'emailAddress': 'protected@example.com'
                }
            ]
        }
        mock_drive_service.permissions.return_value = mock_permissions

        mock_files = Mock()
        mock_files.get.return_value.execute.return_value = {'id': 'folder1', 'name': 'Test'}
        mock_drive_service.files.return_value = mock_files

        result = await permission_manager.sync_folder_permissions(
            folder_id="folder1",
            expected_permissions={},
            remove_unlisted=True,
            protected_emails=['protected@example.com'],
            dry_run=True
        )

        # 保護されているので削除されない
        assert result.permissions_removed == 0


# ================================================================
# Parse Permission Tests
# ================================================================

class TestParsePermission:
    """_parse_permission メソッドのテスト"""

    def test_parse_full_permission(self, permission_manager):
        """完全な権限データのパース"""
        perm_data = {
            'id': 'perm123',
            'type': 'user',
            'role': 'writer',
            'emailAddress': 'test@example.com',
            'displayName': 'Test User',
            'domain': 'example.com',
            'expirationTime': '2026-12-31T23:59:59Z',
            'deleted': False
        }

        perm = permission_manager._parse_permission(perm_data)

        assert perm.id == 'perm123'
        assert perm.type == PermissionType.USER
        assert perm.role == PermissionRole.WRITER
        assert perm.email_address == 'test@example.com'
        assert perm.display_name == 'Test User'
        assert perm.domain == 'example.com'
        assert perm.expiration_time is not None
        assert perm.deleted is False

    def test_parse_minimal_permission(self, permission_manager):
        """最小限の権限データのパース"""
        perm_data = {
            'id': 'perm456',
            'type': 'anyone',
            'role': 'reader'
        }

        perm = permission_manager._parse_permission(perm_data)

        assert perm.id == 'perm456'
        assert perm.type == PermissionType.ANYONE
        assert perm.role == PermissionRole.READER
        assert perm.email_address is None
