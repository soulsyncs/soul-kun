"""
lib/audit.py のテスト

監査ログモジュールのユニットテスト
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime, timezone
import json

from lib.audit import (
    AuditAction,
    AuditResourceType,
    log_audit,
    log_audit_batch,
    log_audit_async,
    log_drive_permission_change,
    log_drive_sync_summary,
)


class TestAuditAction:
    """AuditAction Enumのテスト"""

    def test_create_value(self):
        """CREATEの値"""
        assert AuditAction.CREATE.value == "create"

    def test_read_value(self):
        """READの値"""
        assert AuditAction.READ.value == "read"

    def test_update_value(self):
        """UPDATEの値"""
        assert AuditAction.UPDATE.value == "update"

    def test_delete_value(self):
        """DELETEの値"""
        assert AuditAction.DELETE.value == "delete"

    def test_export_value(self):
        """EXPORTの値"""
        assert AuditAction.EXPORT.value == "export"

    def test_regenerate_value(self):
        """REGENERATEの値"""
        assert AuditAction.REGENERATE.value == "regenerate"

    def test_sync_value(self):
        """SYNCの値"""
        assert AuditAction.SYNC.value == "sync"


class TestAuditResourceType:
    """AuditResourceType Enumのテスト"""

    def test_document_value(self):
        """DOCUMENTの値"""
        assert AuditResourceType.DOCUMENT.value == "document"

    def test_knowledge_value(self):
        """KNOWLEDGEの値"""
        assert AuditResourceType.KNOWLEDGE.value == "knowledge"

    def test_user_value(self):
        """USERの値"""
        assert AuditResourceType.USER.value == "user"

    def test_department_value(self):
        """DEPARTMENTの値"""
        assert AuditResourceType.DEPARTMENT.value == "department"

    def test_task_value(self):
        """TASKの値"""
        assert AuditResourceType.TASK.value == "task"

    def test_chatwork_task_value(self):
        """CHATWORK_TASKの値"""
        assert AuditResourceType.CHATWORK_TASK.value == "chatwork_task"

    def test_meeting_value(self):
        """MEETINGの値"""
        assert AuditResourceType.MEETING.value == "meeting"

    def test_organization_value(self):
        """ORGANIZATIONの値"""
        assert AuditResourceType.ORGANIZATION.value == "organization"

    def test_summary_value(self):
        """SUMMARYの値"""
        assert AuditResourceType.SUMMARY.value == "summary"

    def test_drive_permission_value(self):
        """DRIVE_PERMISSIONの値"""
        assert AuditResourceType.DRIVE_PERMISSION.value == "drive_permission"

    def test_drive_folder_value(self):
        """DRIVE_FOLDERの値"""
        assert AuditResourceType.DRIVE_FOLDER.value == "drive_folder"


@pytest.fixture
def mock_db_conn():
    """DB接続のモック"""
    conn = MagicMock()
    cursor = MagicMock()
    return conn, cursor


class TestLogAudit:
    """log_audit のテスト"""

    def test_log_audit_success_with_table(self, mock_db_conn):
        """テーブルが存在する場合の正常ログ"""
        conn, cursor = mock_db_conn
        # テーブル存在チェック: True
        cursor.fetchone.return_value = (True,)

        result = log_audit(
            conn=conn,
            cursor=cursor,
            organization_id="org_test",
            action="create",
            resource_type="document",
            resource_id="doc_123",
        )

        assert result is True
        assert cursor.execute.called
        assert conn.commit.called

    def test_log_audit_without_table(self, mock_db_conn, capsys):
        """テーブルが存在しない場合はprint出力のみ"""
        conn, cursor = mock_db_conn
        # テーブル存在チェック: False
        cursor.fetchone.return_value = (False,)

        result = log_audit(
            conn=conn,
            cursor=cursor,
            organization_id="org_test",
            action="update",
            resource_type="task",
            resource_id="task_456",
        )

        assert result is True
        # commitは呼ばれない
        assert not conn.commit.called
        # print出力を確認
        captured = capsys.readouterr()
        assert "Audit (no table)" in captured.out

    def test_log_audit_with_details(self, mock_db_conn):
        """詳細情報付きのログ"""
        conn, cursor = mock_db_conn
        cursor.fetchone.return_value = (True,)

        details = {"old_value": "before", "new_value": "after"}

        result = log_audit(
            conn=conn,
            cursor=cursor,
            organization_id="org_test",
            action="update",
            resource_type="chatwork_task",
            resource_id="task_789",
            details=details,
        )

        assert result is True
        # INSERTが呼ばれたことを確認
        call_args = cursor.execute.call_args_list[-1]
        assert "INSERT INTO audit_logs" in call_args[0][0]

    def test_log_audit_with_all_optional_params(self, mock_db_conn):
        """全オプションパラメータ付きのログ"""
        conn, cursor = mock_db_conn
        cursor.fetchone.return_value = (True,)

        result = log_audit(
            conn=conn,
            cursor=cursor,
            organization_id="org_test",
            action="delete",
            resource_type="user",
            resource_id="user_001",
            resource_name="田中太郎",
            user_id="admin_001",
            department_id="dept_001",
            classification="confidential",
            details={"reason": "退職"},
            ip_address="192.168.1.100",
            user_agent="Mozilla/5.0",
        )

        assert result is True

    def test_log_audit_handles_exception(self, mock_db_conn, capsys):
        """例外発生時のフォールバック"""
        conn, cursor = mock_db_conn
        cursor.execute.side_effect = Exception("DB connection failed")

        result = log_audit(
            conn=conn,
            cursor=cursor,
            organization_id="org_test",
            action="read",
            resource_type="document",
            resource_id="doc_001",
        )

        assert result is False
        # フォールバックのprint出力を確認
        captured = capsys.readouterr()
        assert "Audit log failed" in captured.out
        assert "Audit (fallback)" in captured.out

    def test_log_audit_exception_with_details(self, mock_db_conn, capsys):
        """例外発生時に詳細情報もprint出力"""
        conn, cursor = mock_db_conn
        cursor.execute.side_effect = Exception("Connection timeout")

        result = log_audit(
            conn=conn,
            cursor=cursor,
            organization_id="org_test",
            action="update",
            resource_type="task",
            resource_id="task_001",
            details={"field": "status", "value": "completed"},
        )

        assert result is False
        captured = capsys.readouterr()
        assert "Details:" in captured.out

    def test_log_audit_without_table_with_details(self, mock_db_conn, capsys):
        """テーブルなし+詳細情報の場合"""
        conn, cursor = mock_db_conn
        cursor.fetchone.return_value = (False,)

        result = log_audit(
            conn=conn,
            cursor=cursor,
            organization_id="org_test",
            action="export",
            resource_type="document",
            resource_id="doc_001",
            details={"format": "pdf"},
        )

        assert result is True
        captured = capsys.readouterr()
        assert "Details:" in captured.out


class TestLogAuditBatch:
    """log_audit_batch のテスト"""

    def test_batch_audit_success(self, mock_db_conn):
        """バッチ監査ログの正常記録"""
        conn, cursor = mock_db_conn
        cursor.fetchone.return_value = (True,)

        items = [
            {"id": "task_1", "old_summary": "旧1", "new_summary": "新1"},
            {"id": "task_2", "old_summary": "旧2", "new_summary": "新2"},
        ]

        result = log_audit_batch(
            conn=conn,
            cursor=cursor,
            organization_id="org_test",
            action="regenerate",
            resource_type="chatwork_task",
            items=items,
        )

        assert result is True

    def test_batch_audit_with_summary_details(self, mock_db_conn):
        """サマリー情報付きバッチ監査ログ"""
        conn, cursor = mock_db_conn
        cursor.fetchone.return_value = (True,)

        items = [{"id": f"item_{i}"} for i in range(5)]
        summary = {"total": 5, "success": 5, "failed": 0}

        result = log_audit_batch(
            conn=conn,
            cursor=cursor,
            organization_id="org_test",
            action="sync",
            resource_type="task",
            items=items,
            user_id="user_001",
            summary_details=summary,
        )

        assert result is True

    def test_batch_audit_truncates_items(self, mock_db_conn):
        """10件以上のアイテムは10件に切り詰め"""
        conn, cursor = mock_db_conn
        cursor.fetchone.return_value = (True,)

        items = [{"id": f"item_{i}"} for i in range(20)]

        result = log_audit_batch(
            conn=conn,
            cursor=cursor,
            organization_id="org_test",
            action="delete",
            resource_type="document",
            items=items,
        )

        assert result is True


class TestLogAuditAsync:
    """log_audit_async のテスト"""

    @pytest.mark.asyncio
    async def test_async_audit_success(self):
        """非同期監査ログの正常記録"""
        result = await log_audit_async(
            organization_id="org_test",
            action="create",
            resource_type="drive_permission",
            resource_id="folder_123",
            resource_name="営業部フォルダ",
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_async_audit_with_details(self):
        """詳細情報付き非同期監査ログ"""
        result = await log_audit_async(
            organization_id="org_test",
            action="update",
            resource_type="drive_folder",
            resource_id="folder_456",
            user_id="user_001",
            classification="restricted",
            details={"email": "user@example.com", "role": "writer"},
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_async_audit_handles_exception(self):
        """非同期監査ログの例外ハンドリング"""
        with patch('lib.audit.logger') as mock_logger:
            # jsonのシリアライズで例外を起こす
            class BadObject:
                def __repr__(self):
                    raise Exception("Cannot serialize")

            # 例外が発生してもFalseを返す
            with patch('json.dumps', side_effect=Exception("JSON error")):
                result = await log_audit_async(
                    organization_id="org_test",
                    action="read",
                    resource_type="document",
                )

                assert result is False


class TestLogDrivePermissionChange:
    """log_drive_permission_change のテスト"""

    @pytest.mark.asyncio
    async def test_permission_add(self):
        """権限追加のログ"""
        result = await log_drive_permission_change(
            organization_id="org_test",
            folder_id="folder_123",
            folder_name="営業部",
            action="add",
            email="newuser@example.com",
            role="reader",
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_permission_remove(self):
        """権限削除のログ"""
        result = await log_drive_permission_change(
            organization_id="org_test",
            folder_id="folder_123",
            folder_name="営業部",
            action="remove",
            email="olduser@example.com",
            old_role="writer",
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_permission_update(self):
        """権限更新のログ"""
        result = await log_drive_permission_change(
            organization_id="org_test",
            folder_id="folder_123",
            folder_name="営業部",
            action="update",
            email="user@example.com",
            role="writer",
            old_role="reader",
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_permission_dry_run(self):
        """dry_runモードのログ"""
        result = await log_drive_permission_change(
            organization_id="org_test",
            folder_id="folder_123",
            folder_name="テスト",
            action="add",
            email="test@example.com",
            role="reader",
            dry_run=True,
        )

        assert result is True


class TestLogDriveSyncSummary:
    """log_drive_sync_summary のテスト"""

    @pytest.mark.asyncio
    async def test_sync_summary_basic(self):
        """基本的な同期サマリーログ"""
        result = await log_drive_sync_summary(
            organization_id="org_test",
            folders_processed=10,
            permissions_added=5,
            permissions_removed=2,
            permissions_updated=1,
            errors=0,
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_sync_summary_with_errors(self):
        """エラーありの同期サマリーログ"""
        result = await log_drive_sync_summary(
            organization_id="org_test",
            folders_processed=10,
            permissions_added=3,
            permissions_removed=1,
            permissions_updated=0,
            errors=2,
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_sync_summary_dry_run(self):
        """dry_runモードの同期サマリーログ"""
        result = await log_drive_sync_summary(
            organization_id="org_test",
            folders_processed=5,
            permissions_added=10,
            permissions_removed=3,
            permissions_updated=2,
            errors=0,
            dry_run=True,
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_sync_summary_with_snapshot_id(self):
        """スナップショットID付き同期サマリーログ"""
        result = await log_drive_sync_summary(
            organization_id="org_test",
            folders_processed=20,
            permissions_added=15,
            permissions_removed=5,
            permissions_updated=3,
            errors=1,
            dry_run=False,
            snapshot_id="snapshot_20260203_120000",
        )

        assert result is True


class TestAuditIntegration:
    """監査ログの統合テスト"""

    def test_audit_action_enum_can_be_used_as_string(self, mock_db_conn):
        """AuditAction Enumが文字列として使用可能"""
        conn, cursor = mock_db_conn
        cursor.fetchone.return_value = (True,)

        result = log_audit(
            conn=conn,
            cursor=cursor,
            organization_id="org_test",
            action=AuditAction.CREATE.value,
            resource_type=AuditResourceType.DOCUMENT.value,
            resource_id="doc_001",
        )

        assert result is True

    def test_audit_resource_type_enum_can_be_used_as_string(self, mock_db_conn):
        """AuditResourceType Enumが文字列として使用可能"""
        conn, cursor = mock_db_conn
        cursor.fetchone.return_value = (True,)

        result = log_audit(
            conn=conn,
            cursor=cursor,
            organization_id="org_test",
            action=AuditAction.UPDATE.value,
            resource_type=AuditResourceType.CHATWORK_TASK.value,
            resource_id="task_001",
        )

        assert result is True
