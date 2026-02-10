"""
Google Drive 権限スナップショット管理

権限同期前にスナップショットを取得し、
問題発生時にロールバックできる機能を提供する。

使用例:
    from lib.drive_permission_snapshot import SnapshotManager

    manager = SnapshotManager(
        storage_path="/path/to/snapshots",
        service_account_info={...}
    )

    # スナップショット作成
    snapshot = await manager.create_snapshot(
        folder_ids=["folder1", "folder2"],
        description="Before quarterly sync"
    )

    # スナップショット一覧
    snapshots = manager.list_snapshots()

    # ロールバック
    result = await manager.rollback(
        snapshot_id="snap_20260126_123456",
        dry_run=True
    )

Phase D: Google Drive 自動権限管理機能
Created: 2026-01-26
"""

import os
import json
import asyncio
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
import logging
import hashlib

from lib.drive_permission_manager import (
    DrivePermissionManager,
    DrivePermission,
    PermissionRole,
    PermissionChange,
    PermissionSyncResult,
)


logger = logging.getLogger(__name__)


# ================================================================
# 定数
# ================================================================

# スナップショットファイル名のプレフィックス
SNAPSHOT_PREFIX = "snap_"
SNAPSHOT_EXTENSION = ".json"

# 最大保持スナップショット数（デフォルト）
DEFAULT_MAX_SNAPSHOTS = 10

# スナップショットの最大サイズ（フォルダ数）
MAX_FOLDERS_PER_SNAPSHOT = 100


# ================================================================
# データクラス
# ================================================================

@dataclass
class FolderPermissionState:
    """フォルダの権限状態"""
    folder_id: str
    folder_name: str
    permissions: List[Dict[str, Any]]  # [{email, role, type, ...}]
    captured_at: str  # ISO format

    @property
    def permission_count(self) -> int:
        return len(self.permissions)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> 'FolderPermissionState':
        return cls(**data)


@dataclass
class PermissionSnapshot:
    """権限スナップショット"""
    id: str
    description: str
    created_at: str  # ISO format
    created_by: str
    folder_states: List[FolderPermissionState]
    organization_id: str = "org_soulsyncs"  # テナント分離（v10.28.0追加）
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def folder_count(self) -> int:
        return len(self.folder_states)

    @property
    def total_permissions(self) -> int:
        return sum(fs.permission_count for fs in self.folder_states)

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'description': self.description,
            'created_at': self.created_at,
            'created_by': self.created_by,
            'organization_id': self.organization_id,
            'folder_states': [fs.to_dict() for fs in self.folder_states],
            'metadata': self.metadata
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'PermissionSnapshot':
        folder_states = [
            FolderPermissionState.from_dict(fs)
            for fs in data.get('folder_states', [])
        ]
        return cls(
            id=data['id'],
            description=data['description'],
            created_at=data['created_at'],
            created_by=data.get('created_by', 'unknown'),
            folder_states=folder_states,
            organization_id=data.get('organization_id', 'org_soulsyncs'),
            metadata=data.get('metadata', {})
        )

    def get_folder_state(self, folder_id: str) -> Optional[FolderPermissionState]:
        """フォルダIDで状態を取得"""
        for fs in self.folder_states:
            if fs.folder_id == folder_id:
                return fs
        return None


@dataclass
class RollbackResult:
    """ロールバック結果"""
    snapshot_id: str
    dry_run: bool
    started_at: datetime
    completed_at: Optional[datetime] = None
    folders_processed: int = 0
    permissions_added: int = 0
    permissions_removed: int = 0
    permissions_updated: int = 0
    errors: int = 0
    folder_results: List[PermissionSyncResult] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def total_changes(self) -> int:
        return self.permissions_added + self.permissions_removed + self.permissions_updated

    @property
    def success(self) -> bool:
        return self.errors == 0

    def to_summary(self) -> str:
        mode = "[DRY RUN]" if self.dry_run else "[EXECUTED]"
        status = "SUCCESS" if self.success else f"FAILED ({self.errors} errors)"
        return (
            f"{mode} ロールバック結果: {status}\n"
            f"スナップショット: {self.snapshot_id}\n"
            f"処理フォルダ数: {self.folders_processed}\n"
            f"追加: {self.permissions_added}, 削除: {self.permissions_removed}, "
            f"更新: {self.permissions_updated}"
        )


# ================================================================
# Snapshot Manager
# ================================================================

class SnapshotManager:
    """
    権限スナップショット管理

    スナップショットの作成、保存、ロールバックを管理する。
    """

    def __init__(
        self,
        storage_path: Optional[str] = None,
        service_account_info: Optional[dict] = None,
        service_account_file: Optional[str] = None,
        max_snapshots: int = DEFAULT_MAX_SNAPSHOTS,
        organization_id: str = "org_soulsyncs",
    ):
        """
        Args:
            storage_path: スナップショット保存先ディレクトリ
            service_account_info: Google サービスアカウント情報
            service_account_file: Google サービスアカウントファイルパス
            max_snapshots: 最大保持スナップショット数
            organization_id: テナントID（Phase 4マルチテナント対応）
        """
        self.organization_id = organization_id
        self.storage_path = Path(
            storage_path or os.getenv('SNAPSHOT_STORAGE_PATH', '/tmp/drive_snapshots')
        )
        self.max_snapshots = max_snapshots

        # ディレクトリ作成
        self.storage_path.mkdir(parents=True, exist_ok=True)

        # DrivePermissionManager
        self.permission_manager = DrivePermissionManager(
            service_account_info=service_account_info,
            service_account_file=service_account_file
        )

    # ================================================================
    # スナップショット作成
    # ================================================================

    async def create_snapshot(
        self,
        folder_ids: List[str],
        description: str = "",
        created_by: str = "system",
        metadata: Optional[Dict[str, Any]] = None
    ) -> PermissionSnapshot:
        """
        権限スナップショットを作成

        Args:
            folder_ids: スナップショット対象のフォルダIDリスト
            description: スナップショットの説明
            created_by: 作成者
            metadata: 追加メタデータ

        Returns:
            作成されたスナップショット
        """
        if len(folder_ids) > MAX_FOLDERS_PER_SNAPSHOT:
            raise ValueError(
                f"Too many folders: {len(folder_ids)} "
                f"(max: {MAX_FOLDERS_PER_SNAPSHOT})"
            )

        # スナップショットID生成
        snapshot_id = self._generate_snapshot_id()
        created_at = datetime.now().isoformat()

        logger.info(f"Creating snapshot {snapshot_id} for {len(folder_ids)} folders")

        # 各フォルダの権限を取得
        folder_states = []
        for folder_id in folder_ids:
            try:
                state = await self._capture_folder_state(folder_id)
                folder_states.append(state)
            except Exception as e:
                logger.error(f"Failed to capture folder {folder_id}: {e}")
                raise

        # スナップショット作成
        snapshot = PermissionSnapshot(
            id=snapshot_id,
            description=description,
            created_at=created_at,
            created_by=created_by,
            folder_states=folder_states,
            organization_id=self.organization_id,
            metadata=metadata or {}
        )

        # 保存
        self._save_snapshot(snapshot)

        # 古いスナップショットを削除
        self._cleanup_old_snapshots()

        logger.info(
            f"Snapshot {snapshot_id} created: "
            f"{snapshot.folder_count} folders, {snapshot.total_permissions} permissions"
        )

        return snapshot

    async def _capture_folder_state(self, folder_id: str) -> FolderPermissionState:
        """フォルダの権限状態をキャプチャ"""
        permissions = await self.permission_manager.list_permissions(folder_id)

        # ファイル名を取得
        folder_name = await self.permission_manager._get_file_name(folder_id) or folder_id

        # 権限をシリアライズ可能な形式に変換
        perm_list = []
        for perm in permissions:
            perm_dict = {
                'id': perm.id,
                'type': perm.type.value,
                'role': perm.role.value,
                'email_address': perm.email_address,
                'display_name': perm.display_name,
                'domain': perm.domain,
            }
            perm_list.append(perm_dict)

        return FolderPermissionState(
            folder_id=folder_id,
            folder_name=folder_name,
            permissions=perm_list,
            captured_at=datetime.now().isoformat()
        )

    # ================================================================
    # スナップショット管理
    # ================================================================

    def list_snapshots(self, include_all_orgs: bool = False) -> List[Dict[str, Any]]:
        """
        スナップショット一覧を取得

        Args:
            include_all_orgs: Trueの場合、全組織のスナップショットを返す（管理者用）

        Returns:
            スナップショットのサマリーリスト（新しい順）
        """
        snapshots = []
        for file_path in self.storage_path.glob(f"{SNAPSHOT_PREFIX}*{SNAPSHOT_EXTENSION}"):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                    # テナント分離: organization_idでフィルタ（Phase 4対応）
                    snapshot_org_id = data.get('organization_id', 'org_soulsyncs')
                    if not include_all_orgs and snapshot_org_id != self.organization_id:
                        continue

                    snapshots.append({
                        'id': data['id'],
                        'description': data['description'],
                        'created_at': data['created_at'],
                        'created_by': data.get('created_by', 'unknown'),
                        'organization_id': snapshot_org_id,
                        'folder_count': len(data.get('folder_states', [])),
                        'file_path': str(file_path)
                    })
            except Exception as e:
                logger.warning(f"Failed to read snapshot {file_path}: {e}")

        # 新しい順にソート
        snapshots.sort(key=lambda x: x['created_at'], reverse=True)
        return snapshots

    def get_snapshot(self, snapshot_id: str) -> Optional[PermissionSnapshot]:
        """スナップショットを取得"""
        file_path = self._get_snapshot_path(snapshot_id)
        if not file_path.exists():
            return None

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return PermissionSnapshot.from_dict(data)
        except Exception as e:
            logger.error(f"Failed to load snapshot {snapshot_id}: {e}")
            return None

    def delete_snapshot(self, snapshot_id: str) -> bool:
        """スナップショットを削除"""
        file_path = self._get_snapshot_path(snapshot_id)
        if file_path.exists():
            file_path.unlink()
            logger.info(f"Deleted snapshot: {snapshot_id}")
            return True
        return False

    # ================================================================
    # ロールバック
    # ================================================================

    async def rollback(
        self,
        snapshot_id: str,
        dry_run: bool = True,
        folder_ids: Optional[List[str]] = None
    ) -> RollbackResult:
        """
        スナップショットから権限をロールバック

        Args:
            snapshot_id: ロールバック対象のスナップショットID
            dry_run: Trueの場合、実際には変更しない
            folder_ids: 特定フォルダのみロールバック（省略時は全フォルダ）

        Returns:
            ロールバック結果
        """
        result = RollbackResult(
            snapshot_id=snapshot_id,
            dry_run=dry_run,
            started_at=datetime.now()
        )

        # スナップショット読み込み
        snapshot = self.get_snapshot(snapshot_id)
        if not snapshot:
            result.errors = 1
            result.warnings.append(f"Snapshot not found: {snapshot_id}")
            result.completed_at = datetime.now()
            return result

        logger.info(
            f"{'[DRY RUN] ' if dry_run else ''}"
            f"Rolling back to snapshot {snapshot_id}"
        )

        # 対象フォルダを決定
        target_states = snapshot.folder_states
        if folder_ids:
            target_states = [
                fs for fs in snapshot.folder_states
                if fs.folder_id in folder_ids
            ]

        result.folders_processed = len(target_states)

        # 各フォルダをロールバック
        for folder_state in target_states:
            try:
                folder_result = await self._rollback_folder(
                    folder_state=folder_state,
                    dry_run=dry_run
                )
                result.folder_results.append(folder_result)
                result.permissions_added += folder_result.permissions_added
                result.permissions_removed += folder_result.permissions_removed
                result.permissions_updated += folder_result.permissions_updated
                result.errors += folder_result.errors

            except Exception as e:
                logger.error(f"Failed to rollback folder {folder_state.folder_id}: {e}")
                result.errors += 1
                result.warnings.append(
                    f"Failed to rollback {folder_state.folder_name}: {str(e)}"
                )

        result.completed_at = datetime.now()
        logger.info(result.to_summary())

        return result

    async def _rollback_folder(
        self,
        folder_state: FolderPermissionState,
        dry_run: bool
    ) -> PermissionSyncResult:
        """単一フォルダをロールバック"""
        logger.info(
            f"{'[DRY RUN] ' if dry_run else ''}"
            f"Rolling back folder: {folder_state.folder_name}"
        )

        # スナップショット時の権限を期待値として設定
        expected_permissions = {}
        for perm in folder_state.permissions:
            if perm.get('email_address') and perm.get('type') == 'user':
                email = perm['email_address'].lower()
                role = PermissionRole(perm['role'])
                expected_permissions[email] = role

        # sync_folder_permissionsでロールバック
        # remove_unlisted=True で、スナップショットにない権限は削除
        result = await self.permission_manager.sync_folder_permissions(
            folder_id=folder_state.folder_id,
            expected_permissions=expected_permissions,
            remove_unlisted=True,
            dry_run=dry_run
        )

        result.folder_name = folder_state.folder_name
        return result

    # ================================================================
    # 比較・差分
    # ================================================================

    async def compare_with_current(
        self,
        snapshot_id: str,
        folder_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        スナップショットと現在の状態を比較

        Args:
            snapshot_id: 比較対象のスナップショットID
            folder_id: 特定フォルダのみ比較（省略時は全フォルダ）

        Returns:
            差分情報
        """
        snapshot = self.get_snapshot(snapshot_id)
        if not snapshot:
            return {'error': f'Snapshot not found: {snapshot_id}'}

        target_states = snapshot.folder_states
        if folder_id:
            target_states = [
                fs for fs in snapshot.folder_states
                if fs.folder_id == folder_id
            ]

        differences = []
        for folder_state in target_states:
            diff = await self._compare_folder_state(folder_state)
            if diff['has_changes']:
                differences.append(diff)

        return {
            'snapshot_id': snapshot_id,
            'snapshot_created_at': snapshot.created_at,
            'folders_compared': len(target_states),
            'folders_with_changes': len(differences),
            'differences': differences
        }

    async def _compare_folder_state(
        self,
        snapshot_state: FolderPermissionState
    ) -> Dict[str, Any]:
        """フォルダの状態を比較"""
        # 現在の権限を取得
        current_perms = await self.permission_manager.list_permissions(
            snapshot_state.folder_id
        )
        current_by_email = {
            p.email_address.lower(): p.role.value
            for p in current_perms
            if p.email_address and p.type.value == 'user'
        }

        # スナップショット時の権限
        snapshot_by_email = {
            p['email_address'].lower(): p['role']
            for p in snapshot_state.permissions
            if p.get('email_address') and p.get('type') == 'user'
        }

        # 差分計算
        added = []  # 現在にあってスナップショットにない
        removed = []  # スナップショットにあって現在にない
        changed = []  # 両方にあるが権限が異なる

        for email, role in current_by_email.items():
            if email not in snapshot_by_email:
                added.append({'email': email, 'role': role})
            elif snapshot_by_email[email] != role:
                changed.append({
                    'email': email,
                    'snapshot_role': snapshot_by_email[email],
                    'current_role': role
                })

        for email, role in snapshot_by_email.items():
            if email not in current_by_email:
                removed.append({'email': email, 'role': role})

        return {
            'folder_id': snapshot_state.folder_id,
            'folder_name': snapshot_state.folder_name,
            'has_changes': bool(added or removed or changed),
            'added': added,
            'removed': removed,
            'changed': changed
        }

    # ================================================================
    # ユーティリティ
    # ================================================================

    def _generate_snapshot_id(self) -> str:
        """ユニークなスナップショットIDを生成"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        random_suffix = hashlib.md5(
            str(datetime.now().timestamp()).encode()
        ).hexdigest()[:6]
        return f"{SNAPSHOT_PREFIX}{timestamp}_{random_suffix}"

    def _get_snapshot_path(self, snapshot_id: str) -> Path:
        """スナップショットのファイルパスを取得"""
        return self.storage_path / f"{snapshot_id}{SNAPSHOT_EXTENSION}"

    def _save_snapshot(self, snapshot: PermissionSnapshot):
        """スナップショットを保存"""
        file_path = self._get_snapshot_path(snapshot.id)
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(snapshot.to_dict(), f, ensure_ascii=False, indent=2)
        logger.debug(f"Saved snapshot to {file_path}")

    def _cleanup_old_snapshots(self):
        """古いスナップショットを削除"""
        snapshots = self.list_snapshots()
        if len(snapshots) > self.max_snapshots:
            # 古いものから削除
            for snapshot in snapshots[self.max_snapshots:]:
                self.delete_snapshot(snapshot['id'])
                logger.info(f"Cleaned up old snapshot: {snapshot['id']}")


# ================================================================
# エクスポート
# ================================================================

__all__ = [
    'SnapshotManager',
    'PermissionSnapshot',
    'FolderPermissionState',
    'RollbackResult',
    'DEFAULT_MAX_SNAPSHOTS',
    'MAX_FOLDERS_PER_SNAPSHOT',
]
