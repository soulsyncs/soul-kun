"""
Drive Permission Snapshot テスト

Phase D: Google Drive 自動権限管理機能
"""

import pytest
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime

from lib.drive_permission_snapshot import (
    SnapshotManager,
    PermissionSnapshot,
    FolderPermissionState,
    RollbackResult,
    DEFAULT_MAX_SNAPSHOTS,
    MAX_FOLDERS_PER_SNAPSHOT,
    SNAPSHOT_PREFIX,
)
from lib.drive_permission_manager import PermissionRole, PermissionType, DrivePermission, PermissionSyncResult


# ================================================================
# FolderPermissionState Tests
# ================================================================

class TestFolderPermissionState:
    """FolderPermissionStateデータクラスのテスト"""

    def test_permission_count(self):
        """権限数のカウント"""
        state = FolderPermissionState(
            folder_id="folder1",
            folder_name="Test Folder",
            permissions=[
                {"email_address": "user1@test.com", "role": "reader"},
                {"email_address": "user2@test.com", "role": "writer"},
            ],
            captured_at="2026-01-26T12:00:00"
        )
        assert state.permission_count == 2

    def test_to_dict(self):
        """辞書への変換"""
        state = FolderPermissionState(
            folder_id="folder1",
            folder_name="Test Folder",
            permissions=[{"email": "test@test.com"}],
            captured_at="2026-01-26T12:00:00"
        )
        d = state.to_dict()
        assert d['folder_id'] == "folder1"
        assert d['folder_name'] == "Test Folder"
        assert len(d['permissions']) == 1

    def test_from_dict(self):
        """辞書からの復元"""
        data = {
            'folder_id': 'folder1',
            'folder_name': 'Test Folder',
            'permissions': [{'email': 'test@test.com'}],
            'captured_at': '2026-01-26T12:00:00'
        }
        state = FolderPermissionState.from_dict(data)
        assert state.folder_id == 'folder1'
        assert state.folder_name == 'Test Folder'


# ================================================================
# PermissionSnapshot Tests
# ================================================================

class TestPermissionSnapshot:
    """PermissionSnapshotデータクラスのテスト"""

    def test_folder_count(self):
        """フォルダ数のカウント"""
        snapshot = PermissionSnapshot(
            id="snap_123",
            description="Test",
            created_at="2026-01-26T12:00:00",
            created_by="test",
            folder_states=[
                FolderPermissionState(
                    folder_id="f1", folder_name="F1",
                    permissions=[], captured_at="2026-01-26"
                ),
                FolderPermissionState(
                    folder_id="f2", folder_name="F2",
                    permissions=[], captured_at="2026-01-26"
                ),
            ]
        )
        assert snapshot.folder_count == 2

    def test_total_permissions(self):
        """総権限数のカウント"""
        snapshot = PermissionSnapshot(
            id="snap_123",
            description="Test",
            created_at="2026-01-26T12:00:00",
            created_by="test",
            folder_states=[
                FolderPermissionState(
                    folder_id="f1", folder_name="F1",
                    permissions=[{}, {}], captured_at="2026-01-26"
                ),
                FolderPermissionState(
                    folder_id="f2", folder_name="F2",
                    permissions=[{}, {}, {}], captured_at="2026-01-26"
                ),
            ]
        )
        assert snapshot.total_permissions == 5

    def test_get_folder_state(self):
        """フォルダ状態の取得"""
        state1 = FolderPermissionState(
            folder_id="f1", folder_name="F1",
            permissions=[], captured_at="2026-01-26"
        )
        state2 = FolderPermissionState(
            folder_id="f2", folder_name="F2",
            permissions=[], captured_at="2026-01-26"
        )
        snapshot = PermissionSnapshot(
            id="snap_123",
            description="Test",
            created_at="2026-01-26T12:00:00",
            created_by="test",
            folder_states=[state1, state2]
        )

        assert snapshot.get_folder_state("f1") == state1
        assert snapshot.get_folder_state("f2") == state2
        assert snapshot.get_folder_state("f3") is None

    def test_to_dict_and_from_dict(self):
        """シリアライズ/デシリアライズ"""
        original = PermissionSnapshot(
            id="snap_123",
            description="Test Snapshot",
            created_at="2026-01-26T12:00:00",
            created_by="tester",
            folder_states=[
                FolderPermissionState(
                    folder_id="f1", folder_name="F1",
                    permissions=[{"email": "test@test.com", "role": "reader"}],
                    captured_at="2026-01-26T12:00:00"
                )
            ],
            metadata={"key": "value"}
        )

        d = original.to_dict()
        restored = PermissionSnapshot.from_dict(d)

        assert restored.id == original.id
        assert restored.description == original.description
        assert restored.created_by == original.created_by
        assert restored.folder_count == original.folder_count
        assert restored.metadata == original.metadata


# ================================================================
# RollbackResult Tests
# ================================================================

class TestRollbackResult:
    """RollbackResultデータクラスのテスト"""

    def test_total_changes(self):
        """総変更数のカウント"""
        result = RollbackResult(
            snapshot_id="snap_123",
            dry_run=True,
            started_at=datetime.now(),
            permissions_added=5,
            permissions_removed=3,
            permissions_updated=2
        )
        assert result.total_changes == 10

    def test_success_true(self):
        """成功判定（エラーなし）"""
        result = RollbackResult(
            snapshot_id="snap_123",
            dry_run=True,
            started_at=datetime.now(),
            errors=0
        )
        assert result.success is True

    def test_success_false(self):
        """成功判定（エラーあり）"""
        result = RollbackResult(
            snapshot_id="snap_123",
            dry_run=True,
            started_at=datetime.now(),
            errors=1
        )
        assert result.success is False

    def test_to_summary_dry_run(self):
        """サマリー出力（dry run）"""
        result = RollbackResult(
            snapshot_id="snap_123",
            dry_run=True,
            started_at=datetime.now(),
            folders_processed=5,
            permissions_added=10,
            permissions_removed=2,
            permissions_updated=3
        )
        summary = result.to_summary()
        assert "[DRY RUN]" in summary
        assert "snap_123" in summary
        assert "SUCCESS" in summary

    def test_to_summary_failed(self):
        """サマリー出力（失敗）"""
        result = RollbackResult(
            snapshot_id="snap_123",
            dry_run=False,
            started_at=datetime.now(),
            errors=2
        )
        summary = result.to_summary()
        assert "[EXECUTED]" in summary
        assert "FAILED" in summary
        assert "2 errors" in summary


# ================================================================
# SnapshotManager Tests
# ================================================================

class TestSnapshotManager:
    """SnapshotManagerのテスト"""

    @pytest.fixture
    def temp_storage(self):
        """一時ストレージディレクトリ"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def mock_permission_manager(self):
        """モックPermissionManager"""
        with patch('lib.drive_permission_snapshot.DrivePermissionManager') as mock:
            mock_instance = AsyncMock()
            mock.return_value = mock_instance
            yield mock_instance

    @pytest.fixture
    def snapshot_manager(self, temp_storage, mock_permission_manager):
        """テスト用SnapshotManager"""
        return SnapshotManager(
            storage_path=temp_storage,
            service_account_info={'type': 'service_account'}
        )

    def test_init_creates_directory(self, temp_storage, mock_permission_manager):
        """初期化時にディレクトリが作成される"""
        new_path = Path(temp_storage) / "new_dir"
        manager = SnapshotManager(
            storage_path=str(new_path),
            service_account_info={'type': 'service_account'}
        )
        assert new_path.exists()

    def test_generate_snapshot_id(self, snapshot_manager):
        """スナップショットID生成"""
        id1 = snapshot_manager._generate_snapshot_id()
        id2 = snapshot_manager._generate_snapshot_id()

        assert id1.startswith(SNAPSHOT_PREFIX)
        assert id1 != id2  # ユニーク

    @pytest.mark.asyncio
    async def test_create_snapshot(self, snapshot_manager, mock_permission_manager):
        """スナップショット作成"""
        mock_permission_manager.list_permissions.return_value = [
            DrivePermission(
                id="perm1", type=PermissionType.USER,
                role=PermissionRole.READER, email_address="user1@test.com"
            )
        ]
        mock_permission_manager._get_file_name.return_value = "Test Folder"

        snapshot = await snapshot_manager.create_snapshot(
            folder_ids=["folder1"],
            description="Test Snapshot",
            created_by="tester"
        )

        assert snapshot.id.startswith(SNAPSHOT_PREFIX)
        assert snapshot.description == "Test Snapshot"
        assert snapshot.created_by == "tester"
        assert snapshot.folder_count == 1

    @pytest.mark.asyncio
    async def test_create_snapshot_too_many_folders(self, snapshot_manager):
        """フォルダ数制限のテスト"""
        folder_ids = [f"folder{i}" for i in range(MAX_FOLDERS_PER_SNAPSHOT + 1)]

        with pytest.raises(ValueError) as exc:
            await snapshot_manager.create_snapshot(folder_ids=folder_ids)

        assert "Too many folders" in str(exc.value)

    def test_list_snapshots_empty(self, snapshot_manager):
        """空のスナップショット一覧"""
        snapshots = snapshot_manager.list_snapshots()
        assert snapshots == []

    def test_list_snapshots_with_data(self, snapshot_manager, temp_storage):
        """スナップショット一覧"""
        # テストデータ作成
        for i in range(3):
            snapshot_data = {
                'id': f'snap_2026010{i}_123456',
                'description': f'Snapshot {i}',
                'created_at': f'2026-01-0{i}T12:00:00',
                'created_by': 'test',
                'folder_states': []
            }
            file_path = Path(temp_storage) / f"snap_2026010{i}_123456.json"
            with open(file_path, 'w') as f:
                json.dump(snapshot_data, f)

        snapshots = snapshot_manager.list_snapshots()
        assert len(snapshots) == 3
        # 新しい順
        assert snapshots[0]['id'] == 'snap_20260102_123456'

    def test_get_snapshot_not_found(self, snapshot_manager):
        """存在しないスナップショットの取得"""
        result = snapshot_manager.get_snapshot("nonexistent")
        assert result is None

    def test_get_snapshot_success(self, snapshot_manager, temp_storage):
        """スナップショットの取得"""
        snapshot_data = {
            'id': 'snap_test',
            'description': 'Test',
            'created_at': '2026-01-26T12:00:00',
            'created_by': 'test',
            'folder_states': []
        }
        file_path = Path(temp_storage) / "snap_test.json"
        with open(file_path, 'w') as f:
            json.dump(snapshot_data, f)

        snapshot = snapshot_manager.get_snapshot("snap_test")
        assert snapshot is not None
        assert snapshot.id == "snap_test"

    def test_delete_snapshot(self, snapshot_manager, temp_storage):
        """スナップショットの削除"""
        # ファイル作成
        file_path = Path(temp_storage) / "snap_delete.json"
        file_path.write_text("{}")

        assert file_path.exists()
        result = snapshot_manager.delete_snapshot("snap_delete")
        assert result is True
        assert not file_path.exists()

    def test_delete_snapshot_not_found(self, snapshot_manager):
        """存在しないスナップショットの削除"""
        result = snapshot_manager.delete_snapshot("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_rollback_snapshot_not_found(self, snapshot_manager):
        """存在しないスナップショットへのロールバック"""
        result = await snapshot_manager.rollback("nonexistent", dry_run=True)
        assert result.errors == 1
        assert "not found" in result.warnings[0].lower()

    @pytest.mark.asyncio
    async def test_rollback_dry_run(self, snapshot_manager, mock_permission_manager, temp_storage):
        """ロールバック（dry run）"""
        # スナップショット作成
        snapshot_data = {
            'id': 'snap_rollback',
            'description': 'Rollback Test',
            'created_at': '2026-01-26T12:00:00',
            'created_by': 'test',
            'folder_states': [{
                'folder_id': 'folder1',
                'folder_name': 'Test Folder',
                'permissions': [
                    {'id': 'p1', 'type': 'user', 'role': 'reader', 'email_address': 'user@test.com'}
                ],
                'captured_at': '2026-01-26T12:00:00'
            }]
        }
        file_path = Path(temp_storage) / "snap_rollback.json"
        with open(file_path, 'w') as f:
            json.dump(snapshot_data, f)

        # モック設定
        mock_permission_manager.sync_folder_permissions.return_value = PermissionSyncResult(
            folder_id="folder1",
            permissions_added=1,
            permissions_removed=0,
            permissions_updated=0
        )

        result = await snapshot_manager.rollback("snap_rollback", dry_run=True)

        assert result.dry_run is True
        assert result.folders_processed == 1
        assert result.success is True

    def test_cleanup_old_snapshots(self, snapshot_manager, temp_storage):
        """古いスナップショットの自動削除"""
        snapshot_manager.max_snapshots = 3

        # 5個のスナップショット作成
        for i in range(5):
            snapshot_data = {
                'id': f'snap_20260{i:02d}01_123456',
                'description': f'Snapshot {i}',
                'created_at': f'2026-0{i+1}-01T12:00:00',
                'created_by': 'test',
                'folder_states': []
            }
            file_path = Path(temp_storage) / f"snap_20260{i:02d}01_123456.json"
            with open(file_path, 'w') as f:
                json.dump(snapshot_data, f)

        # クリーンアップ実行
        snapshot_manager._cleanup_old_snapshots()

        # 3個だけ残る
        remaining = snapshot_manager.list_snapshots()
        assert len(remaining) == 3

    @pytest.mark.asyncio
    async def test_compare_with_current(self, snapshot_manager, mock_permission_manager, temp_storage):
        """スナップショットと現在の比較"""
        # スナップショット作成
        snapshot_data = {
            'id': 'snap_compare',
            'description': 'Compare Test',
            'created_at': '2026-01-26T12:00:00',
            'created_by': 'test',
            'folder_states': [{
                'folder_id': 'folder1',
                'folder_name': 'Test Folder',
                'permissions': [
                    {'id': 'p1', 'type': 'user', 'role': 'reader', 'email_address': 'old@test.com'}
                ],
                'captured_at': '2026-01-26T12:00:00'
            }]
        }
        file_path = Path(temp_storage) / "snap_compare.json"
        with open(file_path, 'w') as f:
            json.dump(snapshot_data, f)

        # 現在の権限（異なる）
        mock_permission_manager.list_permissions.return_value = [
            DrivePermission(
                id="p2", type=PermissionType.USER,
                role=PermissionRole.WRITER, email_address="new@test.com"
            )
        ]

        result = await snapshot_manager.compare_with_current("snap_compare")

        assert result['snapshot_id'] == 'snap_compare'
        assert result['folders_compared'] == 1
        assert result['folders_with_changes'] == 1
        assert len(result['differences']) == 1

        diff = result['differences'][0]
        assert diff['has_changes'] is True
        assert len(diff['added']) == 1  # new@test.com
        assert len(diff['removed']) == 1  # old@test.com
