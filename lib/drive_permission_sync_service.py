"""
Google Drive 権限同期サービス

フォルダ階層（機密区分）と組織図を紐付けて、
期待する権限を計算し同期するサービス。

使用例:
    from lib.drive_permission_sync_service import DrivePermissionSyncService

    service = DrivePermissionSyncService(
        supabase_url="https://xxx.supabase.co",
        supabase_key="xxx",
        service_account_info={...}
    )

    # dry-runで差分確認
    results = await service.sync_all_folders(dry_run=True)

    # 実際に同期
    results = await service.sync_all_folders(dry_run=False)

フォルダ構造と権限マッピング:
    ソウルくん用フォルダ/
    ├── 全社共有/       → 全社員: reader
    ├── 社員限定/       → 全社員: reader
    ├── 役員限定/       → 役職レベル6: reader
    └── 部署別/
        ├── 営業部/     → 営業部社員: reader/writer
        ├── 開発部/     → 開発部社員: reader/writer
        └── ...

Phase C: Google Drive 自動権限管理機能
Created: 2026-01-26
"""

import os
import asyncio
from typing import Optional, List, Dict, Any, Set
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import logging

from lib.drive_permission_manager import (
    DrivePermissionManager,
    PermissionRole,
    PermissionSyncResult,
    PermissionChange,
    ROLE_LEVEL_TO_PERMISSION,
)
from lib.org_chart_service import (
    OrgChartService,
    Employee,
    Department,
)
from lib.google_drive import GoogleDriveClient
from lib.drive_permission_change_detector import (
    ChangeDetector,
    ChangeDetectionConfig,
    ChangeAlert,
    AlertLevel,
    create_detector_from_env,
)


logger = logging.getLogger(__name__)


# ================================================================
# 定数
# ================================================================

class FolderType(str, Enum):
    """フォルダ種類（機密区分）"""
    PUBLIC = "public"           # 全社共有
    INTERNAL = "internal"       # 社員限定
    RESTRICTED = "restricted"   # 役員限定
    DEPARTMENT = "department"   # 部署別
    UNKNOWN = "unknown"         # 不明


# フォルダ名 → 機密区分のマッピング
FOLDER_TYPE_MAP: Dict[str, FolderType] = {
    "全社共有": FolderType.PUBLIC,
    "社員限定": FolderType.INTERNAL,
    "役員限定": FolderType.RESTRICTED,
    "部署別": FolderType.DEPARTMENT,
}

# 機密区分 → 必要な最小役職レベル
FOLDER_MIN_ROLE_LEVEL: Dict[FolderType, int] = {
    FolderType.PUBLIC: 1,      # 全員
    FolderType.INTERNAL: 1,    # 全員
    FolderType.RESTRICTED: 6,  # 役員のみ
    FolderType.DEPARTMENT: 1,  # 部署メンバー（別途フィルタ）
}

# 機密区分 → デフォルト権限ロール
FOLDER_DEFAULT_ROLE: Dict[FolderType, PermissionRole] = {
    FolderType.PUBLIC: PermissionRole.READER,
    FolderType.INTERNAL: PermissionRole.READER,
    FolderType.RESTRICTED: PermissionRole.READER,
    FolderType.DEPARTMENT: PermissionRole.READER,
}

# サービスアカウントなど削除から保護するメール
DEFAULT_PROTECTED_EMAILS: List[str] = [
    # サービスアカウント等を追加
]


# ================================================================
# データクラス
# ================================================================

@dataclass
class FolderPermissionSpec:
    """フォルダの期待する権限仕様"""
    folder_id: str
    folder_name: str
    folder_type: FolderType
    folder_path: List[str]
    department_id: Optional[str] = None
    department_name: Optional[str] = None
    expected_permissions: Dict[str, PermissionRole] = field(default_factory=dict)
    # email -> role

    @property
    def is_department_folder(self) -> bool:
        return self.folder_type == FolderType.DEPARTMENT and self.department_name is not None


@dataclass
class SyncPlan:
    """同期計画"""
    folder_specs: List[FolderPermissionSpec] = field(default_factory=list)
    total_folders: int = 0
    total_expected_permissions: int = 0
    created_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()


@dataclass
class SyncReport:
    """同期レポート"""
    dry_run: bool = True
    started_at: datetime = None
    completed_at: datetime = None
    folders_processed: int = 0
    permissions_added: int = 0
    permissions_removed: int = 0
    permissions_updated: int = 0
    permissions_unchanged: int = 0
    errors: int = 0
    folder_results: List[PermissionSyncResult] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def __post_init__(self):
        if self.started_at is None:
            self.started_at = datetime.now()

    @property
    def total_changes(self) -> int:
        return self.permissions_added + self.permissions_removed + self.permissions_updated

    @property
    def duration_seconds(self) -> float:
        if self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return 0

    def to_summary(self) -> str:
        """サマリー文字列を生成"""
        mode = "[DRY RUN]" if self.dry_run else "[EXECUTED]"
        return (
            f"{mode} 同期レポート\n"
            f"処理フォルダ数: {self.folders_processed}\n"
            f"追加: {self.permissions_added}, 削除: {self.permissions_removed}, "
            f"更新: {self.permissions_updated}, 変更なし: {self.permissions_unchanged}\n"
            f"エラー: {self.errors}\n"
            f"処理時間: {self.duration_seconds:.1f}秒"
        )


# ================================================================
# Drive Permission Sync Service
# ================================================================

class DrivePermissionSyncService:
    """
    Google Drive 権限同期サービス

    組織図とGoogle Driveフォルダ構造を紐付けて、
    権限を自動的に同期する。
    """

    def __init__(
        self,
        supabase_url: str,
        supabase_key: str,
        service_account_info: Optional[dict] = None,
        service_account_file: Optional[str] = None,
        organization_id: str = "org_soulsyncs",
        root_folder_id: Optional[str] = None,
        protected_emails: Optional[List[str]] = None,
    ):
        """
        Args:
            supabase_url: Supabase URL
            supabase_key: Supabase API Key
            service_account_info: Google サービスアカウント情報
            service_account_file: Google サービスアカウントファイルパス
            organization_id: 組織ID
            root_folder_id: ルートフォルダID（省略時は環境変数から）
            protected_emails: 削除から保護するメールアドレス
        """
        self.organization_id = organization_id
        self.root_folder_id = root_folder_id or os.getenv('SOULKUN_DRIVE_ROOT_FOLDER_ID')
        self.protected_emails = set(
            e.lower() for e in (protected_emails or DEFAULT_PROTECTED_EMAILS)
        )

        # サービス初期化
        self.org_chart = OrgChartService(
            supabase_url=supabase_url,
            supabase_key=supabase_key,
            organization_id=organization_id
        )

        self.permission_manager = DrivePermissionManager(
            service_account_info=service_account_info,
            service_account_file=service_account_file
        )

        self.drive_client = GoogleDriveClient(
            service_account_info=service_account_info,
            service_account_file=service_account_file
        )

        # キャッシュ
        self._employees_cache: Optional[List[Employee]] = None
        self._departments_cache: Optional[List[Department]] = None
        self._dept_name_to_id: Dict[str, str] = {}

    # ================================================================
    # メイン同期メソッド
    # ================================================================

    async def sync_all_folders(
        self,
        dry_run: bool = True,
        remove_unlisted: bool = False,
        max_changes_per_folder: int = 50,
        change_detector: Optional['ChangeDetector'] = None,
        send_alerts: bool = True,
    ) -> SyncReport:
        """
        全フォルダの権限を同期

        Args:
            dry_run: Trueの場合、実際には変更しない
            remove_unlisted: リストにないユーザーの権限を削除するか
            max_changes_per_folder: フォルダあたりの最大変更数（超えたら警告）
            change_detector: 変更検知器（省略時は自動生成）
            send_alerts: アラートをChatworkに送信するか

        Returns:
            同期レポート
        """
        report = SyncReport(dry_run=dry_run)

        # 変更検知器を初期化
        if change_detector is None:
            change_detector = create_detector_from_env()
        change_detector.config.max_changes_per_folder = max_changes_per_folder

        # 緊急停止チェック
        if change_detector.check_emergency_stop():
            report.warnings.append("緊急停止フラグが有効なため、同期を中止しました")
            if send_alerts:
                change_detector.send_all_critical_alerts()
            report.completed_at = datetime.now()
            return report

        try:
            # 1. 同期計画を作成
            plan = await self.create_sync_plan()
            report.folders_processed = plan.total_folders

            # 2. 各フォルダを同期
            for spec in plan.folder_specs:
                # 停止チェック
                if change_detector.should_stop():
                    report.warnings.append(
                        f"大量変更検知により同期を中止しました（{change_detector._result.folders_processed}フォルダ処理済み）"
                    )
                    break

                try:
                    result = await self._sync_folder(
                        spec=spec,
                        dry_run=dry_run,
                        remove_unlisted=remove_unlisted,
                        max_changes=max_changes_per_folder
                    )

                    report.folder_results.append(result)
                    report.permissions_added += result.permissions_added
                    report.permissions_removed += result.permissions_removed
                    report.permissions_updated += result.permissions_updated
                    report.permissions_unchanged += result.permissions_unchanged
                    report.errors += result.errors

                    # 変更検知
                    alert = change_detector.check_folder_changes(
                        folder_id=spec.folder_id,
                        folder_name=spec.folder_name,
                        additions=result.permissions_added,
                        removals=result.permissions_removed,
                        updates=result.permissions_updated,
                    )

                    # アラートが発生した場合
                    if alert:
                        report.warnings.append(alert.message)
                        if alert.level in (AlertLevel.CRITICAL, AlertLevel.EMERGENCY):
                            logger.warning(f"Critical alert: {alert.message}")

                except Exception as e:
                    logger.error(f"Error syncing folder {spec.folder_name}: {e}")
                    report.errors += 1
                    report.warnings.append(f"フォルダ '{spec.folder_name}' でエラー: {str(e)}")

            # 全体の変更数チェック
            change_detector.check_total_changes()

        except Exception as e:
            logger.error(f"Error during sync: {e}")
            report.warnings.append(f"同期中にエラー: {str(e)}")

        finally:
            report.completed_at = datetime.now()
            await self.org_chart.close()

            # アラート送信
            if send_alerts:
                # CRITICALアラートを送信
                if change_detector.get_critical_alerts():
                    change_detector.send_all_critical_alerts()

                # サマリーを送信（アラートがある場合のみ）
                if change_detector._result.alerts:
                    change_detector.send_summary_alert(
                        dry_run=dry_run,
                        additional_message=f"処理フォルダ: {report.folders_processed}件"
                    )

        return report

    async def sync_single_folder(
        self,
        folder_id: str,
        dry_run: bool = True,
        remove_unlisted: bool = False,
    ) -> PermissionSyncResult:
        """
        単一フォルダの権限を同期

        Args:
            folder_id: フォルダID
            dry_run: Trueの場合、実際には変更しない
            remove_unlisted: リストにないユーザーの権限を削除するか

        Returns:
            同期結果
        """
        try:
            # フォルダ情報を取得
            file_info = await self.drive_client.get_file(folder_id)
            if not file_info:
                raise ValueError(f"Folder not found: {folder_id}")

            folder_path = await self.drive_client.get_folder_path(file_info)

            # フォルダ仕様を計算
            spec = await self._calculate_folder_spec(
                folder_id=folder_id,
                folder_name=file_info.name,
                folder_path=folder_path
            )

            # 同期実行
            return await self._sync_folder(
                spec=spec,
                dry_run=dry_run,
                remove_unlisted=remove_unlisted
            )

        finally:
            await self.org_chart.close()

    # ================================================================
    # 同期計画
    # ================================================================

    async def create_sync_plan(self) -> SyncPlan:
        """
        同期計画を作成

        ルートフォルダ配下の全フォルダを走査し、
        各フォルダの期待する権限を計算する。
        """
        plan = SyncPlan()

        if not self.root_folder_id:
            raise ValueError("Root folder ID is not set")

        # キャッシュをロード
        await self._load_caches()

        # ルートフォルダの子フォルダを取得
        root_children = await self._list_subfolders(self.root_folder_id)

        for child in root_children:
            folder_type = self._determine_folder_type(child['name'])
            folder_path = [child['name']]

            if folder_type == FolderType.DEPARTMENT:
                # 部署別フォルダの場合、各部署フォルダを処理
                dept_folders = await self._list_subfolders(child['id'])
                for dept_folder in dept_folders:
                    spec = await self._calculate_folder_spec(
                        folder_id=dept_folder['id'],
                        folder_name=dept_folder['name'],
                        folder_path=[child['name'], dept_folder['name']]
                    )
                    plan.folder_specs.append(spec)
                    plan.total_expected_permissions += len(spec.expected_permissions)
            else:
                # 通常フォルダ
                spec = await self._calculate_folder_spec(
                    folder_id=child['id'],
                    folder_name=child['name'],
                    folder_path=folder_path
                )
                plan.folder_specs.append(spec)
                plan.total_expected_permissions += len(spec.expected_permissions)

        plan.total_folders = len(plan.folder_specs)
        logger.info(
            f"Sync plan created: {plan.total_folders} folders, "
            f"{plan.total_expected_permissions} expected permissions"
        )

        return plan

    # ================================================================
    # 内部メソッド
    # ================================================================

    async def _load_caches(self):
        """キャッシュをロード"""
        if self._employees_cache is None:
            self._employees_cache = await self.org_chart.get_all_employees(
                with_google_account_only=True
            )
            logger.info(f"Loaded {len(self._employees_cache)} employees with Google accounts")

        if self._departments_cache is None:
            self._departments_cache = await self.org_chart.get_all_departments()
            self._dept_name_to_id = {
                dept.name: dept.id for dept in self._departments_cache
            }
            logger.info(f"Loaded {len(self._departments_cache)} departments")

    async def _list_subfolders(self, folder_id: str) -> List[dict]:
        """サブフォルダ一覧を取得"""
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: self.drive_client.service.files().list(
                q=f"'{folder_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false",
                fields='files(id,name)',
                pageSize=100
            ).execute()
        )
        return response.get('files', [])

    def _determine_folder_type(self, folder_name: str) -> FolderType:
        """フォルダ名から種類を判定"""
        return FOLDER_TYPE_MAP.get(folder_name, FolderType.UNKNOWN)

    async def _calculate_folder_spec(
        self,
        folder_id: str,
        folder_name: str,
        folder_path: List[str]
    ) -> FolderPermissionSpec:
        """
        フォルダの期待する権限仕様を計算
        """
        await self._load_caches()

        # フォルダ種類を判定
        if len(folder_path) >= 2 and folder_path[0] == "部署別":
            folder_type = FolderType.DEPARTMENT
            department_name = folder_path[1]
            department_id = self._dept_name_to_id.get(department_name)
        else:
            folder_type = self._determine_folder_type(folder_name)
            department_name = None
            department_id = None

        spec = FolderPermissionSpec(
            folder_id=folder_id,
            folder_name=folder_name,
            folder_type=folder_type,
            folder_path=folder_path,
            department_id=department_id,
            department_name=department_name
        )

        # 期待する権限を計算
        spec.expected_permissions = self._calculate_expected_permissions(spec)

        return spec

    def _calculate_expected_permissions(
        self,
        spec: FolderPermissionSpec
    ) -> Dict[str, PermissionRole]:
        """
        フォルダ仕様から期待する権限を計算

        Returns:
            {email: PermissionRole}
        """
        permissions: Dict[str, PermissionRole] = {}

        if spec.folder_type == FolderType.UNKNOWN:
            logger.warning(f"Unknown folder type for {spec.folder_name}, skipping")
            return permissions

        min_level = FOLDER_MIN_ROLE_LEVEL.get(spec.folder_type, 1)
        default_role = FOLDER_DEFAULT_ROLE.get(spec.folder_type, PermissionRole.READER)

        for emp in self._employees_cache:
            if not emp.google_account_email:
                continue

            email = emp.google_account_email.lower()

            # 部署別フォルダの場合
            if spec.folder_type == FolderType.DEPARTMENT:
                if spec.department_id and spec.department_id in emp.all_department_ids:
                    # 役職レベルに応じた権限
                    role = ROLE_LEVEL_TO_PERMISSION.get(emp.role_level, default_role)
                    permissions[email] = role
                # 部署に所属していない人は権限なし
                continue

            # その他のフォルダ（役職レベルでフィルタ）
            if emp.role_level >= min_level:
                role = ROLE_LEVEL_TO_PERMISSION.get(emp.role_level, default_role)
                permissions[email] = role

        return permissions

    async def _sync_folder(
        self,
        spec: FolderPermissionSpec,
        dry_run: bool,
        remove_unlisted: bool,
        max_changes: int = 50
    ) -> PermissionSyncResult:
        """
        単一フォルダを同期
        """
        logger.info(
            f"{'[DRY RUN] ' if dry_run else ''}Syncing folder: {spec.folder_name} "
            f"({spec.folder_type.value}, {len(spec.expected_permissions)} expected permissions)"
        )

        result = await self.permission_manager.sync_folder_permissions(
            folder_id=spec.folder_id,
            expected_permissions=spec.expected_permissions,
            remove_unlisted=remove_unlisted,
            dry_run=dry_run,
            protected_emails=list(self.protected_emails)
        )

        # フォルダ情報を追加
        result.folder_name = spec.folder_name

        return result

    # ================================================================
    # ユーティリティ
    # ================================================================

    async def get_folder_permission_diff(
        self,
        folder_id: str
    ) -> Dict[str, Any]:
        """
        フォルダの現在の権限と期待する権限の差分を取得

        Returns:
            {
                "folder_name": str,
                "folder_type": str,
                "current": {email: role},
                "expected": {email: role},
                "to_add": {email: role},
                "to_remove": [email],
                "to_update": {email: {"old": role, "new": role}}
            }
        """
        try:
            await self._load_caches()

            # フォルダ情報を取得
            file_info = await self.drive_client.get_file(folder_id)
            if not file_info:
                raise ValueError(f"Folder not found: {folder_id}")

            folder_path = await self.drive_client.get_folder_path(file_info)

            # 期待する権限を計算
            spec = await self._calculate_folder_spec(
                folder_id=folder_id,
                folder_name=file_info.name,
                folder_path=folder_path
            )

            # 現在の権限を取得
            current_perms = await self.permission_manager.list_permissions(folder_id)
            current = {
                p.email_address.lower(): p.role
                for p in current_perms
                if p.email_address and p.is_user_permission
            }

            expected = spec.expected_permissions

            # 差分計算
            to_add = {}
            to_remove = []
            to_update = {}

            for email, role in expected.items():
                if email not in current:
                    to_add[email] = role.value
                elif current[email] != role:
                    to_update[email] = {
                        "old": current[email].value,
                        "new": role.value
                    }

            for email in current:
                if email not in expected and email not in self.protected_emails:
                    to_remove.append(email)

            return {
                "folder_name": file_info.name,
                "folder_type": spec.folder_type.value,
                "current": {e: r.value for e, r in current.items()},
                "expected": {e: r.value for e, r in expected.items()},
                "to_add": to_add,
                "to_remove": to_remove,
                "to_update": to_update,
            }

        finally:
            await self.org_chart.close()

    def clear_caches(self):
        """キャッシュをクリア"""
        self._employees_cache = None
        self._departments_cache = None
        self._dept_name_to_id = {}
        self.drive_client.clear_cache()
        self.permission_manager.clear_cache()


# ================================================================
# エクスポート
# ================================================================

__all__ = [
    'DrivePermissionSyncService',
    'FolderPermissionSpec',
    'SyncPlan',
    'SyncReport',
    'FolderType',
    'FOLDER_TYPE_MAP',
    'FOLDER_MIN_ROLE_LEVEL',
    'FOLDER_DEFAULT_ROLE',
    # Phase E: 変更検知
    'ChangeDetector',
    'ChangeDetectionConfig',
    'ChangeAlert',
    'AlertLevel',
    'create_detector_from_env',
]
