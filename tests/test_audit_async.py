"""
lib/audit.py 非同期版のテスト

v10.28.0: Google Drive権限管理用の監査ログ関数テスト
"""

import pytest
from unittest.mock import patch, MagicMock
import json

from lib.audit import (
    AuditAction,
    AuditResourceType,
    log_audit_async,
    log_drive_permission_change,
    log_drive_sync_summary,
)


class TestAuditResourceType:
    """AuditResourceTypeのテスト"""

    def test_drive_permission_type_exists(self):
        """DRIVE_PERMISSIONタイプが存在"""
        assert AuditResourceType.DRIVE_PERMISSION == "drive_permission"

    def test_drive_folder_type_exists(self):
        """DRIVE_FOLDERタイプが存在"""
        assert AuditResourceType.DRIVE_FOLDER == "drive_folder"


class TestLogAuditAsync:
    """log_audit_asyncのテスト"""

    @pytest.mark.asyncio
    async def test_log_audit_async_success(self):
        """正常にログ出力される"""
        result = await log_audit_async(
            organization_id="org_soulsyncs",
            action="create",
            resource_type="drive_permission",
            resource_id="folder_123",
            resource_name="営業部",
            details={"email": "user@example.com", "role": "reader"}
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_log_audit_async_minimal(self):
        """最小限のパラメータでも動作"""
        result = await log_audit_async(
            organization_id="org_soulsyncs",
            action="delete",
            resource_type="drive_permission",
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_log_audit_async_with_classification(self):
        """機密区分を指定して動作"""
        result = await log_audit_async(
            organization_id="org_soulsyncs",
            action="update",
            resource_type="drive_folder",
            classification="restricted",
        )
        assert result is True


class TestLogDrivePermissionChange:
    """log_drive_permission_changeのテスト"""

    @pytest.mark.asyncio
    async def test_log_add_permission(self):
        """権限追加のログ"""
        result = await log_drive_permission_change(
            organization_id="org_soulsyncs",
            folder_id="folder_123",
            folder_name="営業部",
            action="add",
            email="user@example.com",
            role="reader",
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_log_remove_permission(self):
        """権限削除のログ"""
        result = await log_drive_permission_change(
            organization_id="org_soulsyncs",
            folder_id="folder_123",
            folder_name="営業部",
            action="remove",
            email="user@example.com",
            old_role="writer",
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_log_update_permission(self):
        """権限更新のログ"""
        result = await log_drive_permission_change(
            organization_id="org_soulsyncs",
            folder_id="folder_123",
            folder_name="営業部",
            action="update",
            email="user@example.com",
            role="writer",
            old_role="reader",
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_log_dry_run(self):
        """dry_runモードのログ"""
        result = await log_drive_permission_change(
            organization_id="org_soulsyncs",
            folder_id="folder_123",
            folder_name="営業部",
            action="add",
            email="user@example.com",
            role="reader",
            dry_run=True,
        )
        assert result is True


class TestLogDriveSyncSummary:
    """log_drive_sync_summaryのテスト"""

    @pytest.mark.asyncio
    async def test_log_sync_summary(self):
        """同期サマリーのログ"""
        result = await log_drive_sync_summary(
            organization_id="org_soulsyncs",
            folders_processed=10,
            permissions_added=5,
            permissions_removed=2,
            permissions_updated=3,
            errors=0,
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_log_sync_summary_with_errors(self):
        """エラーありの同期サマリー"""
        result = await log_drive_sync_summary(
            organization_id="org_soulsyncs",
            folders_processed=10,
            permissions_added=3,
            permissions_removed=1,
            permissions_updated=2,
            errors=2,
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_log_sync_summary_dry_run(self):
        """dry_runモードの同期サマリー"""
        result = await log_drive_sync_summary(
            organization_id="org_soulsyncs",
            folders_processed=10,
            permissions_added=5,
            permissions_removed=2,
            permissions_updated=3,
            errors=0,
            dry_run=True,
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_log_sync_summary_with_snapshot(self):
        """スナップショット付きの同期サマリー"""
        result = await log_drive_sync_summary(
            organization_id="org_soulsyncs",
            folders_processed=10,
            permissions_added=5,
            permissions_removed=2,
            permissions_updated=3,
            errors=0,
            snapshot_id="snap_20260126_123456_abc123",
        )
        assert result is True


class TestOrganizationIdRequired:
    """organization_id必須のテスト（10の鉄則 #1）"""

    @pytest.mark.asyncio
    async def test_organization_id_is_included(self):
        """organization_idがログに含まれる"""
        with patch('lib.audit.logger') as mock_logger:
            await log_audit_async(
                organization_id="org_test123",
                action="create",
                resource_type="drive_permission",
            )

            # logger.infoが呼ばれたことを確認
            mock_logger.info.assert_called_once()
            log_message = mock_logger.info.call_args[0][0]

            # organization_idがログに含まれている
            assert "org_test123" in log_message
