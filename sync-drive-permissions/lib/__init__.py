"""
Soul-kun 共通ライブラリ（sync-drive-permissions用）

このモジュールは sync-drive-permissions Cloud Function で必要な
最小限の機能のみをエクスポートします。

Phase F: Google Drive 自動権限管理機能
"""

__version__ = "1.0.0"  # sync-drive-permissions専用バージョン

# 設定
from lib.config import (
    Settings,
    get_settings,
)

# シークレット管理
from lib.secrets import (
    get_secret,
    get_secret_cached,
)

# Chatwork（アラート通知用）
from lib.chatwork import (
    ChatworkClient,
)

# Google Drive
from lib.google_drive import (
    GoogleDriveClient,
    DriveFile,
)

# Drive Permission Manager
from lib.drive_permission_manager import (
    DrivePermissionManager,
    DrivePermission,
    PermissionRole,
)

# Drive Permission Sync Service
from lib.drive_permission_sync_service import (
    DrivePermissionSyncService,
    SyncReport,
)

# Drive Permission Snapshot
from lib.drive_permission_snapshot import (
    SnapshotManager,
    PermissionSnapshot,
)

# Drive Permission Change Detector
from lib.drive_permission_change_detector import (
    ChangeDetector,
    ChangeDetectionConfig,
    create_detector_from_env,
)

# Org Chart Service
from lib.org_chart_service import (
    OrgChartService,
    Employee,
    Department,
)

# Audit（v10.28.0追加）
from lib.audit import (
    AuditAction,
    AuditResourceType,
    log_audit_async,
    log_drive_permission_change,
    log_drive_sync_summary,
)

__all__ = [
    # config
    "Settings",
    "get_settings",
    # secrets
    "get_secret",
    "get_secret_cached",
    # chatwork
    "ChatworkClient",
    # google_drive
    "GoogleDriveClient",
    "DriveFile",
    # drive_permission_manager
    "DrivePermissionManager",
    "DrivePermission",
    "PermissionRole",
    # drive_permission_sync_service
    "DrivePermissionSyncService",
    "SyncReport",
    # drive_permission_snapshot
    "SnapshotManager",
    "PermissionSnapshot",
    # drive_permission_change_detector
    "ChangeDetector",
    "ChangeDetectionConfig",
    "create_detector_from_env",
    # org_chart_service
    "OrgChartService",
    "Employee",
    "Department",
    # audit
    "AuditAction",
    "AuditResourceType",
    "log_audit_async",
    "log_drive_permission_change",
    "log_drive_sync_summary",
]
