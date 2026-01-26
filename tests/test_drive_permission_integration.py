"""
Drive Permission 統合テスト

Phase F: Google Drive 自動権限管理機能 - 統合テスト

全モジュールの連携をテストする。
"""

import pytest
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime

# Phase B
from lib.drive_permission_manager import (
    DrivePermissionManager,
    PermissionRole,
    PermissionType,
    DrivePermission,
    PermissionSyncResult,
    ROLE_LEVEL_TO_PERMISSION,
)

# Phase B
from lib.org_chart_service import (
    OrgChartService,
    Employee,
    Department,
)

# Phase C
from lib.drive_permission_sync_service import (
    DrivePermissionSyncService,
    FolderPermissionSpec,
    SyncPlan,
    SyncReport,
    FolderType,
    FOLDER_TYPE_MAP,
)

# Phase D
from lib.drive_permission_snapshot import (
    SnapshotManager,
    PermissionSnapshot,
    FolderPermissionState,
    RollbackResult,
)

# Phase E
from lib.drive_permission_change_detector import (
    ChangeDetector,
    ChangeDetectionConfig,
    ChangeAlert,
    AlertLevel,
)


# ================================================================
# Fixtures
# ================================================================

@pytest.fixture
def mock_google_drive():
    """モックGoogle Driveクライアント"""
    mock = MagicMock()
    mock.service.files.return_value.list.return_value.execute.return_value = {
        'files': [
            {'id': 'folder_public', 'name': '全社共有'},
            {'id': 'folder_internal', 'name': '社員限定'},
            {'id': 'folder_restricted', 'name': '役員限定'},
            {'id': 'folder_dept', 'name': '部署別'},
        ]
    }
    return mock


@pytest.fixture
def mock_org_chart():
    """モック組織図サービス"""
    mock = AsyncMock()
    mock.get_all_employees.return_value = [
        Employee(
            id='emp1', name='田中太郎',
            google_account_email='tanaka@test.com',
            role_level=1, department_id='dept_sales'
        ),
        Employee(
            id='emp2', name='鈴木花子',
            google_account_email='suzuki@test.com',
            role_level=4, department_id='dept_sales'
        ),
        Employee(
            id='emp3', name='佐藤次郎',
            google_account_email='sato@test.com',
            role_level=6, department_id='dept_exec'
        ),
        Employee(
            id='emp4', name='高橋三郎',
            google_account_email='takahashi@test.com',
            role_level=2, department_id='dept_dev'
        ),
    ]
    mock.get_all_departments.return_value = [
        Department(id='dept_sales', name='営業部', parent_id=None),
        Department(id='dept_dev', name='開発部', parent_id=None),
        Department(id='dept_exec', name='経営企画', parent_id=None),
    ]
    mock.close = AsyncMock()
    return mock


@pytest.fixture
def mock_permission_manager():
    """モック権限マネージャー"""
    mock = AsyncMock()
    mock.list_permissions.return_value = [
        DrivePermission(
            id='perm1', type=PermissionType.USER, role=PermissionRole.READER,
            email_address='existing@test.com'
        ),
    ]
    mock.sync_folder_permissions.return_value = PermissionSyncResult(
        folder_id='folder1',
        permissions_added=2,
        permissions_removed=1,
        permissions_updated=0,
        permissions_unchanged=1,
    )
    mock.clear_cache = Mock()
    return mock


@pytest.fixture
def mock_chatwork():
    """モックChatworkクライアント"""
    mock = Mock()
    mock.send_message.return_value = {'message_id': '12345'}
    return mock


@pytest.fixture
def temp_storage():
    """一時ストレージ"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


# ================================================================
# Integration Tests: Sync Flow
# ================================================================

class TestSyncFlowIntegration:
    """同期フロー全体の統合テスト"""

    @pytest.mark.asyncio
    async def test_full_sync_flow_dry_run(
        self, mock_google_drive, mock_org_chart, mock_permission_manager, mock_chatwork
    ):
        """
        フル同期フロー（dry_run）

        1. 組織図から社員情報を取得
        2. フォルダ構造を走査
        3. 期待する権限を計算
        4. 変更を検知
        5. dry_runで差分を報告
        """
        with patch('lib.drive_permission_sync_service.OrgChartService', return_value=mock_org_chart), \
             patch('lib.drive_permission_sync_service.DrivePermissionManager', return_value=mock_permission_manager), \
             patch('lib.drive_permission_sync_service.GoogleDriveClient', return_value=mock_google_drive):

            # 変更検知器を設定
            config = ChangeDetectionConfig(
                max_changes_per_folder=50,
                max_total_changes=200,
            )
            detector = ChangeDetector(config=config, chatwork_client=mock_chatwork)

            # 同期サービスを初期化
            service = DrivePermissionSyncService(
                supabase_url='https://test.supabase.co',
                supabase_key='test-key',
                service_account_info={'type': 'service_account'},
                root_folder_id='root123',
            )

            # dry_runで同期実行
            report = await service.sync_all_folders(
                dry_run=True,
                change_detector=detector,
                send_alerts=False,
            )

            # 検証
            assert report.dry_run is True
            assert report.completed_at is not None
            # 組織図が参照されたことを確認
            mock_org_chart.get_all_employees.assert_called()
            mock_org_chart.get_all_departments.assert_called()

    @pytest.mark.asyncio
    async def test_sync_with_threshold_exceeded(
        self, mock_google_drive, mock_org_chart, mock_chatwork
    ):
        """閾値超過時の自動停止テスト"""
        # 大量の変更を返すモック
        mock_permission_manager = AsyncMock()
        mock_permission_manager.sync_folder_permissions.return_value = PermissionSyncResult(
            folder_id='folder1',
            permissions_added=100,  # 閾値超過
            permissions_removed=0,
            permissions_updated=0,
            permissions_unchanged=0,
        )
        mock_permission_manager.list_permissions.return_value = []
        mock_permission_manager.clear_cache = Mock()

        with patch('lib.drive_permission_sync_service.OrgChartService', return_value=mock_org_chart), \
             patch('lib.drive_permission_sync_service.DrivePermissionManager', return_value=mock_permission_manager), \
             patch('lib.drive_permission_sync_service.GoogleDriveClient', return_value=mock_google_drive):

            config = ChangeDetectionConfig(
                max_changes_per_folder=50,
                stop_on_threshold=True,
            )
            detector = ChangeDetector(config=config, chatwork_client=mock_chatwork)

            service = DrivePermissionSyncService(
                supabase_url='https://test.supabase.co',
                supabase_key='test-key',
                service_account_info={'type': 'service_account'},
                root_folder_id='root123',
            )

            report = await service.sync_all_folders(
                dry_run=True,
                change_detector=detector,
                send_alerts=False,
            )

            # 警告が発生していることを確認
            assert len(report.warnings) > 0
            # 検知器が停止を要求
            assert detector.should_stop() is True


# ================================================================
# Integration Tests: Snapshot Flow
# ================================================================

class TestSnapshotFlowIntegration:
    """スナップショットフローの統合テスト"""

    @pytest.mark.asyncio
    async def test_create_and_rollback_snapshot(
        self, temp_storage, mock_permission_manager
    ):
        """
        スナップショット作成→ロールバックのフロー

        1. 現在の権限をスナップショットとして保存
        2. 変更を適用（シミュレート）
        3. スナップショットからロールバック
        """
        with patch('lib.drive_permission_snapshot.DrivePermissionManager', return_value=mock_permission_manager):
            # スナップショットマネージャーを初期化
            manager = SnapshotManager(
                storage_path=temp_storage,
                service_account_info={'type': 'service_account'},
            )

            # モックの設定
            mock_permission_manager.list_permissions.return_value = [
                DrivePermission(
                    id='perm1', type=PermissionType.USER, role=PermissionRole.READER,
                    email_address='user1@test.com'
                ),
                DrivePermission(
                    id='perm2', type=PermissionType.USER, role=PermissionRole.WRITER,
                    email_address='user2@test.com'
                ),
            ]
            mock_permission_manager._get_file_name = AsyncMock(return_value='Test Folder')

            # 1. スナップショット作成
            snapshot = await manager.create_snapshot(
                folder_ids=['folder1'],
                description='Integration Test Snapshot',
                created_by='test',
            )

            assert snapshot.id.startswith('snap_')
            assert snapshot.folder_count == 1
            assert snapshot.total_permissions == 2

            # 2. スナップショット一覧を確認
            snapshots = manager.list_snapshots()
            assert len(snapshots) == 1
            assert snapshots[0]['id'] == snapshot.id

            # 3. スナップショット取得
            retrieved = manager.get_snapshot(snapshot.id)
            assert retrieved is not None
            assert retrieved.description == 'Integration Test Snapshot'

            # 4. ロールバック（dry_run）
            mock_permission_manager.sync_folder_permissions.return_value = PermissionSyncResult(
                folder_id='folder1',
                permissions_added=0,
                permissions_removed=0,
                permissions_updated=0,
                permissions_unchanged=2,
            )

            result = await manager.rollback(snapshot.id, dry_run=True)

            assert result.dry_run is True
            assert result.success is True

            # 5. スナップショット削除
            deleted = manager.delete_snapshot(snapshot.id)
            assert deleted is True

            # 6. 削除確認
            assert manager.get_snapshot(snapshot.id) is None


# ================================================================
# Integration Tests: Alert Flow
# ================================================================

class TestAlertFlowIntegration:
    """アラートフローの統合テスト"""

    def test_alert_generation_and_send(self, mock_chatwork):
        """アラート生成→送信のフロー"""
        config = ChangeDetectionConfig(
            max_changes_per_folder=50,
            max_total_changes=200,
            alert_room_id='123456',
        )
        detector = ChangeDetector(config=config, chatwork_client=mock_chatwork)

        # 閾値を超える変更を登録
        alert = detector.check_folder_changes(
            folder_id='folder1',
            folder_name='全社共有',
            additions=100,
            removals=0,
            updates=0,
        )

        # アラートが生成されたことを確認
        assert alert is not None
        assert alert.level == AlertLevel.CRITICAL
        assert alert.should_stop is True

        # アラートを送信
        result = detector.send_alert(alert)
        assert result is True

        # Chatworkが呼び出されたことを確認
        mock_chatwork.send_message.assert_called_once()
        call_args = mock_chatwork.send_message.call_args
        assert call_args[1]['room_id'] == 123456
        assert '全社共有' in call_args[1]['message']
        assert '100件' in call_args[1]['message']

    def test_summary_alert_with_multiple_folders(self, mock_chatwork):
        """複数フォルダのサマリーアラート"""
        config = ChangeDetectionConfig(
            max_changes_per_folder=50,
            max_total_changes=200,
        )
        detector = ChangeDetector(config=config, chatwork_client=mock_chatwork)

        # 複数のフォルダを処理
        folders = [
            ('folder1', '全社共有', 30, 5, 0),
            ('folder2', '営業部', 40, 10, 0),
            ('folder3', '開発部', 20, 0, 0),
        ]

        for folder_id, name, adds, removes, updates in folders:
            detector.check_folder_changes(
                folder_id=folder_id,
                folder_name=name,
                additions=adds,
                removals=removes,
                updates=updates,
            )

        # 全体チェック
        detector.check_total_changes()

        # サマリーを送信
        result = detector.send_summary_alert(dry_run=True)

        # サマリーが送信されたことを確認
        assert result is True
        call_args = mock_chatwork.send_message.call_args
        message = call_args[1]['message']
        assert 'サマリー' in message
        assert 'DRY RUN' in message


# ================================================================
# Integration Tests: Full Workflow
# ================================================================

class TestFullWorkflowIntegration:
    """完全なワークフローの統合テスト"""

    @pytest.mark.asyncio
    async def test_complete_permission_sync_workflow(
        self, temp_storage, mock_google_drive, mock_org_chart,
        mock_permission_manager, mock_chatwork
    ):
        """
        完全な権限同期ワークフロー

        1. 事前スナップショット作成
        2. 同期実行（dry_run）
        3. 変更検知・アラート
        4. 問題なければ実行
        5. 事後スナップショット作成
        """
        with patch('lib.drive_permission_sync_service.OrgChartService', return_value=mock_org_chart), \
             patch('lib.drive_permission_sync_service.DrivePermissionManager', return_value=mock_permission_manager), \
             patch('lib.drive_permission_sync_service.GoogleDriveClient', return_value=mock_google_drive), \
             patch('lib.drive_permission_snapshot.DrivePermissionManager', return_value=mock_permission_manager):

            # モックの追加設定
            mock_permission_manager.list_permissions.return_value = [
                DrivePermission(
                    id='perm1', type=PermissionType.USER, role=PermissionRole.READER,
                    email_address='user1@test.com'
                ),
            ]
            mock_permission_manager._get_file_name = AsyncMock(return_value='Test Folder')

            # スナップショットマネージャー
            snapshot_manager = SnapshotManager(
                storage_path=temp_storage,
                service_account_info={'type': 'service_account'},
            )

            # 変更検知器
            config = ChangeDetectionConfig(
                max_changes_per_folder=50,
                max_total_changes=200,
            )
            detector = ChangeDetector(config=config, chatwork_client=mock_chatwork)

            # 同期サービス
            sync_service = DrivePermissionSyncService(
                supabase_url='https://test.supabase.co',
                supabase_key='test-key',
                service_account_info={'type': 'service_account'},
                root_folder_id='root123',
            )

            # === STEP 1: 事前スナップショット ===
            pre_snapshot = await snapshot_manager.create_snapshot(
                folder_ids=['folder1'],
                description='Pre-sync snapshot',
                created_by='integration_test',
            )
            assert pre_snapshot is not None

            # === STEP 2: dry_run同期 ===
            dry_run_report = await sync_service.sync_all_folders(
                dry_run=True,
                change_detector=detector,
                send_alerts=False,
            )
            assert dry_run_report.dry_run is True

            # === STEP 3: 変更検知確認 ===
            if not detector.should_stop():
                # === STEP 4: 実際の同期（dry_run=False） ===
                detector.reset()  # 検知器をリセット

                actual_report = await sync_service.sync_all_folders(
                    dry_run=False,
                    change_detector=detector,
                    send_alerts=False,
                )
                assert actual_report.dry_run is False

                # === STEP 5: 事後スナップショット ===
                post_snapshot = await snapshot_manager.create_snapshot(
                    folder_ids=['folder1'],
                    description='Post-sync snapshot',
                    created_by='integration_test',
                )
                assert post_snapshot is not None

                # スナップショットが2つあることを確認
                snapshots = snapshot_manager.list_snapshots()
                assert len(snapshots) == 2


# ================================================================
# Integration Tests: Error Handling
# ================================================================

class TestErrorHandlingIntegration:
    """エラーハンドリングの統合テスト"""

    @pytest.mark.asyncio
    async def test_partial_failure_handling(
        self, mock_google_drive, mock_org_chart, mock_chatwork
    ):
        """部分的な失敗のハンドリング"""
        # 一部のフォルダで失敗するモック
        mock_permission_manager = AsyncMock()
        call_count = [0]

        async def sync_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 2:
                raise Exception("API Error")
            return PermissionSyncResult(
                folder_id='folder1',
                permissions_added=1,
                permissions_removed=0,
                permissions_updated=0,
                permissions_unchanged=0,
            )

        mock_permission_manager.sync_folder_permissions.side_effect = sync_side_effect
        mock_permission_manager.list_permissions.return_value = []
        mock_permission_manager.clear_cache = Mock()

        with patch('lib.drive_permission_sync_service.OrgChartService', return_value=mock_org_chart), \
             patch('lib.drive_permission_sync_service.DrivePermissionManager', return_value=mock_permission_manager), \
             patch('lib.drive_permission_sync_service.GoogleDriveClient', return_value=mock_google_drive):

            detector = ChangeDetector(
                config=ChangeDetectionConfig(),
                chatwork_client=mock_chatwork,
            )

            service = DrivePermissionSyncService(
                supabase_url='https://test.supabase.co',
                supabase_key='test-key',
                service_account_info={'type': 'service_account'},
                root_folder_id='root123',
            )

            report = await service.sync_all_folders(
                dry_run=True,
                change_detector=detector,
                send_alerts=False,
            )

            # エラーが記録されていることを確認
            assert report.errors > 0
            # 警告メッセージが含まれていることを確認
            assert any('エラー' in w for w in report.warnings)

    @pytest.mark.asyncio
    async def test_org_chart_unavailable(self, mock_google_drive, mock_chatwork):
        """組織図サービスが利用不可の場合"""
        mock_org_chart = AsyncMock()
        mock_org_chart.get_all_employees.side_effect = Exception("Supabase unavailable")

        with patch('lib.drive_permission_sync_service.OrgChartService', return_value=mock_org_chart), \
             patch('lib.drive_permission_sync_service.DrivePermissionManager'), \
             patch('lib.drive_permission_sync_service.GoogleDriveClient', return_value=mock_google_drive):

            detector = ChangeDetector(
                config=ChangeDetectionConfig(),
                chatwork_client=mock_chatwork,
            )

            service = DrivePermissionSyncService(
                supabase_url='https://test.supabase.co',
                supabase_key='test-key',
                service_account_info={'type': 'service_account'},
                root_folder_id='root123',
            )

            report = await service.sync_all_folders(
                dry_run=True,
                change_detector=detector,
                send_alerts=False,
            )

            # エラーが記録されていることを確認
            assert any('エラー' in w for w in report.warnings)


# ================================================================
# Integration Tests: Role Level Permission Mapping
# ================================================================

class TestRoleLevelMappingIntegration:
    """役職レベル→権限マッピングの統合テスト"""

    def test_role_level_to_permission_mapping(self):
        """役職レベルが正しく権限に変換されることを確認"""
        # レベル1-2: reader
        assert ROLE_LEVEL_TO_PERMISSION[1] == PermissionRole.READER
        assert ROLE_LEVEL_TO_PERMISSION[2] == PermissionRole.READER

        # レベル3: commenter
        assert ROLE_LEVEL_TO_PERMISSION[3] == PermissionRole.COMMENTER

        # レベル4-6: writer
        assert ROLE_LEVEL_TO_PERMISSION[4] == PermissionRole.WRITER
        assert ROLE_LEVEL_TO_PERMISSION[5] == PermissionRole.WRITER
        assert ROLE_LEVEL_TO_PERMISSION[6] == PermissionRole.WRITER

    @pytest.mark.asyncio
    async def test_folder_type_permission_calculation(self, mock_org_chart):
        """フォルダタイプに応じた権限計算"""
        with patch('lib.drive_permission_sync_service.OrgChartService', return_value=mock_org_chart), \
             patch('lib.drive_permission_sync_service.DrivePermissionManager'), \
             patch('lib.drive_permission_sync_service.GoogleDriveClient'):

            service = DrivePermissionSyncService(
                supabase_url='https://test.supabase.co',
                supabase_key='test-key',
                service_account_info={'type': 'service_account'},
            )

            # キャッシュをロード
            service._employees_cache = await mock_org_chart.get_all_employees()
            service._departments_cache = await mock_org_chart.get_all_departments()
            service._dept_name_to_id = {
                d.name: d.id for d in service._departments_cache
            }

            # 全社共有フォルダ
            public_spec = FolderPermissionSpec(
                folder_id='folder1',
                folder_name='全社共有',
                folder_type=FolderType.PUBLIC,
                folder_path=['全社共有'],
            )
            public_perms = service._calculate_expected_permissions(public_spec)
            # 全社員がアクセス可能
            assert len(public_perms) == 4

            # 役員限定フォルダ
            restricted_spec = FolderPermissionSpec(
                folder_id='folder2',
                folder_name='役員限定',
                folder_type=FolderType.RESTRICTED,
                folder_path=['役員限定'],
            )
            restricted_perms = service._calculate_expected_permissions(restricted_spec)
            # 役員（レベル6）のみ
            assert len(restricted_perms) == 1
            assert 'sato@test.com' in restricted_perms

            # 部署別フォルダ（営業部）
            dept_spec = FolderPermissionSpec(
                folder_id='folder3',
                folder_name='営業部',
                folder_type=FolderType.DEPARTMENT,
                folder_path=['部署別', '営業部'],
                department_id='dept_sales',
                department_name='営業部',
            )
            dept_perms = service._calculate_expected_permissions(dept_spec)
            # 営業部メンバーのみ
            assert len(dept_perms) == 2
            assert 'tanaka@test.com' in dept_perms
            assert 'suzuki@test.com' in dept_perms
