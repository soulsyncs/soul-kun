"""
Google Drive 権限管理モジュール

組織図と連携してGoogle Driveフォルダの共有権限を自動管理する。

使用例:
    from lib.drive_permission_manager import DrivePermissionManager

    manager = DrivePermissionManager()

    # 権限を追加
    await manager.add_permission(
        file_id="1abc...",
        email="user@company.com",
        role="reader"
    )

    # 権限を削除
    await manager.remove_permission(
        file_id="1abc...",
        email="user@company.com"
    )

    # 現在の権限を取得
    permissions = await manager.list_permissions(file_id="1abc...")

Phase B: Google Drive 自動権限管理機能
Created: 2026-01-26
"""

import os
import asyncio
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import logging

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from lib.config import get_settings
from lib.logging import mask_email


logger = logging.getLogger(__name__)


# ================================================================
# 定数
# ================================================================

class PermissionRole(str, Enum):
    """Google Drive 権限ロール"""
    READER = "reader"        # 閲覧のみ
    COMMENTER = "commenter"  # コメント可能
    WRITER = "writer"        # 編集可能
    ORGANIZER = "organizer"  # 管理者（共有ドライブのみ）
    OWNER = "owner"          # オーナー（変更不可）


class PermissionType(str, Enum):
    """Google Drive 権限タイプ"""
    USER = "user"            # 特定ユーザー
    GROUP = "group"          # グループ
    DOMAIN = "domain"        # ドメイン全体
    ANYONE = "anyone"        # 誰でも


# 組織階層レベル → 推奨権限ロールのマッピング
# 役職レベルが高いほど、より多くのフォルダにアクセス可能
ROLE_LEVEL_TO_PERMISSION: Dict[int, PermissionRole] = {
    1: PermissionRole.READER,      # 一般スタッフ
    2: PermissionRole.READER,      # シニアスタッフ
    3: PermissionRole.COMMENTER,   # リーダー
    4: PermissionRole.WRITER,      # マネージャー
    5: PermissionRole.WRITER,      # 部長
    6: PermissionRole.WRITER,      # 役員
}


# ================================================================
# データクラス
# ================================================================

@dataclass
class DrivePermission:
    """Google Drive 権限情報"""
    id: str
    type: PermissionType
    role: PermissionRole
    email_address: Optional[str] = None
    display_name: Optional[str] = None
    domain: Optional[str] = None
    expiration_time: Optional[datetime] = None
    deleted: bool = False

    @property
    def is_user_permission(self) -> bool:
        """ユーザー権限かどうか"""
        return self.type == PermissionType.USER

    @property
    def is_editable(self) -> bool:
        """編集可能な権限かどうか（owner以外は変更可能）"""
        return self.role != PermissionRole.OWNER


@dataclass
class PermissionChange:
    """権限変更の記録"""
    file_id: str
    file_name: Optional[str]
    action: str  # "add", "remove", "update"
    email: str
    old_role: Optional[PermissionRole] = None
    new_role: Optional[PermissionRole] = None
    success: bool = True
    error_message: Optional[str] = None
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()


@dataclass
class PermissionSyncResult:
    """権限同期の結果"""
    folder_id: str
    folder_name: Optional[str] = None
    permissions_added: int = 0
    permissions_removed: int = 0
    permissions_updated: int = 0
    permissions_unchanged: int = 0
    errors: int = 0
    changes: List[PermissionChange] = None
    dry_run: bool = False

    def __post_init__(self):
        if self.changes is None:
            self.changes = []

    @property
    def total_changes(self) -> int:
        return self.permissions_added + self.permissions_removed + self.permissions_updated


# ================================================================
# Drive Permission Manager
# ================================================================

class DrivePermissionManager:
    """
    Google Drive 権限管理クライアント

    注意:
    - このクライアントはフル権限（drive スコープ）を使用します
    - 本番環境では慎重に使用してください
    - dry_run モードでテストすることを推奨します
    """

    # フル権限スコープ（権限操作に必要）
    SCOPES = ['https://www.googleapis.com/auth/drive']

    def __init__(
        self,
        service_account_file: Optional[str] = None,
        service_account_info: Optional[dict] = None,
    ):
        """
        Args:
            service_account_file: サービスアカウントJSONファイルのパス
            service_account_info: サービスアカウント情報の辞書
        """
        self.settings = get_settings()

        # 認証情報の取得
        if service_account_info:
            credentials = service_account.Credentials.from_service_account_info(
                service_account_info,
                scopes=self.SCOPES
            )
        elif service_account_file:
            credentials = service_account.Credentials.from_service_account_file(
                service_account_file,
                scopes=self.SCOPES
            )
        else:
            # 環境変数からパスを取得
            sa_path = os.getenv('GOOGLE_SERVICE_ACCOUNT_FILE')
            if sa_path:
                credentials = service_account.Credentials.from_service_account_file(
                    sa_path,
                    scopes=self.SCOPES
                )
            else:
                # Application Default Credentials を使用
                from google.auth import default
                credentials, _ = default(scopes=self.SCOPES)

        self.service = build('drive', 'v3', credentials=credentials)
        self._file_cache: Dict[str, dict] = {}

    # ================================================================
    # 権限の取得
    # ================================================================

    async def list_permissions(
        self,
        file_id: str,
        include_inherited: bool = True
    ) -> List[DrivePermission]:
        """
        ファイル/フォルダの権限一覧を取得

        Args:
            file_id: GoogleドライブのファイルID
            include_inherited: 継承された権限も含めるか

        Returns:
            権限のリスト
        """
        loop = asyncio.get_event_loop()
        permissions = []
        page_token = None

        while True:
            try:
                response = await loop.run_in_executor(
                    None,
                    lambda token=page_token: self.service.permissions().list(
                        fileId=file_id,
                        pageToken=token,
                        fields='nextPageToken,permissions(id,type,role,emailAddress,displayName,domain,expirationTime,deleted)',
                        supportsAllDrives=True
                    ).execute()
                )

                for perm_data in response.get('permissions', []):
                    permission = self._parse_permission(perm_data)
                    permissions.append(permission)

                page_token = response.get('nextPageToken')
                if not page_token:
                    break

            except HttpError as e:
                logger.error(f"Failed to list permissions for {file_id}: {e}")
                raise

        return permissions

    async def get_permission_by_email(
        self,
        file_id: str,
        email: str
    ) -> Optional[DrivePermission]:
        """
        メールアドレスで権限を検索

        Args:
            file_id: ファイルID
            email: メールアドレス

        Returns:
            見つかった権限、なければNone
        """
        permissions = await self.list_permissions(file_id)
        email_lower = email.lower()

        for perm in permissions:
            if perm.email_address and perm.email_address.lower() == email_lower:
                return perm

        return None

    # ================================================================
    # 権限の追加
    # ================================================================

    async def add_permission(
        self,
        file_id: str,
        email: str,
        role: PermissionRole = PermissionRole.READER,
        send_notification: bool = False,
        email_message: Optional[str] = None,
        dry_run: bool = False
    ) -> PermissionChange:
        """
        権限を追加

        Args:
            file_id: ファイルID
            email: 付与するユーザーのメールアドレス
            role: 権限ロール
            send_notification: 通知メールを送信するか
            email_message: 通知メールに含めるメッセージ
            dry_run: Trueの場合、実際には変更しない

        Returns:
            権限変更の記録
        """
        file_name = await self._get_file_name(file_id)

        # 既存の権限をチェック
        existing = await self.get_permission_by_email(file_id, email)
        if existing:
            if existing.role == role:
                logger.info(f"Permission already exists: {mask_email(email)} has {role.value} on {file_id}")
                return PermissionChange(
                    file_id=file_id,
                    file_name=file_name,
                    action="unchanged",
                    email=email,
                    old_role=existing.role,
                    new_role=role,
                    success=True
                )
            else:
                # ロールが異なる場合は更新
                return await self.update_permission(
                    file_id=file_id,
                    email=email,
                    new_role=role,
                    dry_run=dry_run
                )

        if dry_run:
            logger.info(f"[DRY RUN] Would add permission: {mask_email(email)} as {role.value} on {file_id}")
            return PermissionChange(
                file_id=file_id,
                file_name=file_name,
                action="add",
                email=email,
                new_role=role,
                success=True
            )

        try:
            loop = asyncio.get_event_loop()
            permission_body = {
                'type': 'user',
                'role': role.value,
                'emailAddress': email
            }

            await loop.run_in_executor(
                None,
                lambda: self.service.permissions().create(
                    fileId=file_id,
                    body=permission_body,
                    sendNotificationEmail=send_notification,
                    emailMessage=email_message,
                    supportsAllDrives=True
                ).execute()
            )

            logger.info(f"Added permission: {mask_email(email)} as {role.value} on {file_id}")
            return PermissionChange(
                file_id=file_id,
                file_name=file_name,
                action="add",
                email=email,
                new_role=role,
                success=True
            )

        except HttpError as e:
            error_msg = str(e)
            logger.error(f"Failed to add permission: {error_msg}")
            return PermissionChange(
                file_id=file_id,
                file_name=file_name,
                action="add",
                email=email,
                new_role=role,
                success=False,
                error_message=error_msg
            )

    # ================================================================
    # 権限の削除
    # ================================================================

    async def remove_permission(
        self,
        file_id: str,
        email: str,
        dry_run: bool = False
    ) -> PermissionChange:
        """
        権限を削除

        Args:
            file_id: ファイルID
            email: 削除するユーザーのメールアドレス
            dry_run: Trueの場合、実際には変更しない

        Returns:
            権限変更の記録
        """
        file_name = await self._get_file_name(file_id)

        # 権限を検索
        permission = await self.get_permission_by_email(file_id, email)
        if not permission:
            logger.info(f"Permission not found: {mask_email(email)} on {file_id}")
            return PermissionChange(
                file_id=file_id,
                file_name=file_name,
                action="remove",
                email=email,
                success=True,
                error_message="Permission not found (already removed)"
            )

        if not permission.is_editable:
            error_msg = f"Cannot remove {permission.role.value} permission"
            logger.warning(f"{error_msg}: {mask_email(email)} on {file_id}")
            return PermissionChange(
                file_id=file_id,
                file_name=file_name,
                action="remove",
                email=email,
                old_role=permission.role,
                success=False,
                error_message=error_msg
            )

        if dry_run:
            logger.info(f"[DRY RUN] Would remove permission: {mask_email(email)} ({permission.role.value}) from {file_id}")
            return PermissionChange(
                file_id=file_id,
                file_name=file_name,
                action="remove",
                email=email,
                old_role=permission.role,
                success=True
            )

        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self.service.permissions().delete(
                    fileId=file_id,
                    permissionId=permission.id,
                    supportsAllDrives=True
                ).execute()
            )

            logger.info(f"Removed permission: {mask_email(email)} from {file_id}")
            return PermissionChange(
                file_id=file_id,
                file_name=file_name,
                action="remove",
                email=email,
                old_role=permission.role,
                success=True
            )

        except HttpError as e:
            error_msg = str(e)
            logger.error(f"Failed to remove permission: {error_msg}")
            return PermissionChange(
                file_id=file_id,
                file_name=file_name,
                action="remove",
                email=email,
                old_role=permission.role,
                success=False,
                error_message=error_msg
            )

    # ================================================================
    # 権限の更新
    # ================================================================

    async def update_permission(
        self,
        file_id: str,
        email: str,
        new_role: PermissionRole,
        dry_run: bool = False
    ) -> PermissionChange:
        """
        権限を更新

        Args:
            file_id: ファイルID
            email: ユーザーのメールアドレス
            new_role: 新しい権限ロール
            dry_run: Trueの場合、実際には変更しない

        Returns:
            権限変更の記録
        """
        file_name = await self._get_file_name(file_id)

        # 既存の権限を検索
        permission = await self.get_permission_by_email(file_id, email)
        if not permission:
            # 権限がない場合は追加
            return await self.add_permission(
                file_id=file_id,
                email=email,
                role=new_role,
                dry_run=dry_run
            )

        if permission.role == new_role:
            logger.info(f"Permission unchanged: {mask_email(email)} already has {new_role.value} on {file_id}")
            return PermissionChange(
                file_id=file_id,
                file_name=file_name,
                action="unchanged",
                email=email,
                old_role=permission.role,
                new_role=new_role,
                success=True
            )

        if not permission.is_editable:
            error_msg = f"Cannot update {permission.role.value} permission"
            logger.warning(f"{error_msg}: {mask_email(email)} on {file_id}")
            return PermissionChange(
                file_id=file_id,
                file_name=file_name,
                action="update",
                email=email,
                old_role=permission.role,
                new_role=new_role,
                success=False,
                error_message=error_msg
            )

        if dry_run:
            logger.info(
                f"[DRY RUN] Would update permission: {mask_email(email)} "
                f"{permission.role.value} -> {new_role.value} on {file_id}"
            )
            return PermissionChange(
                file_id=file_id,
                file_name=file_name,
                action="update",
                email=email,
                old_role=permission.role,
                new_role=new_role,
                success=True
            )

        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self.service.permissions().update(
                    fileId=file_id,
                    permissionId=permission.id,
                    body={'role': new_role.value},
                    supportsAllDrives=True
                ).execute()
            )

            logger.info(
                f"Updated permission: {mask_email(email)} "
                f"{permission.role.value} -> {new_role.value} on {file_id}"
            )
            return PermissionChange(
                file_id=file_id,
                file_name=file_name,
                action="update",
                email=email,
                old_role=permission.role,
                new_role=new_role,
                success=True
            )

        except HttpError as e:
            error_msg = str(e)
            logger.error(f"Failed to update permission: {error_msg}")
            return PermissionChange(
                file_id=file_id,
                file_name=file_name,
                action="update",
                email=email,
                old_role=permission.role,
                new_role=new_role,
                success=False,
                error_message=error_msg
            )

    # ================================================================
    # バッチ操作
    # ================================================================

    async def sync_folder_permissions(
        self,
        folder_id: str,
        expected_permissions: Dict[str, PermissionRole],
        remove_unlisted: bool = False,
        dry_run: bool = False,
        protected_emails: Optional[List[str]] = None
    ) -> PermissionSyncResult:
        """
        フォルダの権限を期待する状態に同期

        Args:
            folder_id: フォルダID
            expected_permissions: 期待する権限 {email: role}
            remove_unlisted: リストにないユーザーの権限を削除するか
            dry_run: Trueの場合、実際には変更しない
            protected_emails: 削除から保護するメールアドレスのリスト

        Returns:
            同期結果
        """
        folder_name = await self._get_file_name(folder_id)
        result = PermissionSyncResult(
            folder_id=folder_id,
            folder_name=folder_name,
            dry_run=dry_run
        )

        protected = set(e.lower() for e in (protected_emails or []))

        # 現在の権限を取得
        current_permissions = await self.list_permissions(folder_id)
        current_by_email = {
            p.email_address.lower(): p
            for p in current_permissions
            if p.email_address and p.is_user_permission
        }

        expected_lower = {k.lower(): v for k, v in expected_permissions.items()}

        # 追加または更新
        for email, role in expected_permissions.items():
            email_lower = email.lower()

            if email_lower in current_by_email:
                current = current_by_email[email_lower]
                if current.role != role:
                    change = await self.update_permission(
                        folder_id, email, role, dry_run=dry_run
                    )
                    result.changes.append(change)
                    if change.success:
                        result.permissions_updated += 1
                    else:
                        result.errors += 1
                else:
                    result.permissions_unchanged += 1
            else:
                change = await self.add_permission(
                    folder_id, email, role, dry_run=dry_run
                )
                result.changes.append(change)
                if change.success:
                    result.permissions_added += 1
                else:
                    result.errors += 1

        # 削除（オプション）
        if remove_unlisted:
            for email_lower, perm in current_by_email.items():
                if email_lower not in expected_lower:
                    if email_lower in protected:
                        logger.info(f"Skipping protected email: {mask_email(email_lower)}")
                        continue
                    if not perm.is_editable:
                        continue

                    change = await self.remove_permission(
                        folder_id, perm.email_address, dry_run=dry_run
                    )
                    result.changes.append(change)
                    if change.success:
                        result.permissions_removed += 1
                    else:
                        result.errors += 1

        return result

    # ================================================================
    # ユーティリティ
    # ================================================================

    async def _get_file_name(self, file_id: str) -> Optional[str]:
        """ファイル名を取得（キャッシュ付き）"""
        if file_id in self._file_cache:
            return self._file_cache[file_id].get('name')

        try:
            loop = asyncio.get_event_loop()
            file_data = await loop.run_in_executor(
                None,
                lambda: self.service.files().get(
                    fileId=file_id,
                    fields='id,name',
                    supportsAllDrives=True
                ).execute()
            )
            self._file_cache[file_id] = file_data
            return file_data.get('name')
        except HttpError:
            return None

    def _parse_permission(self, perm_data: dict) -> DrivePermission:
        """APIレスポンスをDrivePermissionに変換"""
        expiration_time = None
        if perm_data.get('expirationTime'):
            expiration_time = datetime.fromisoformat(
                perm_data['expirationTime'].replace('Z', '+00:00')
            )

        return DrivePermission(
            id=perm_data['id'],
            type=PermissionType(perm_data.get('type', 'user')),
            role=PermissionRole(perm_data.get('role', 'reader')),
            email_address=perm_data.get('emailAddress'),
            display_name=perm_data.get('displayName'),
            domain=perm_data.get('domain'),
            expiration_time=expiration_time,
            deleted=perm_data.get('deleted', False)
        )

    def clear_cache(self):
        """キャッシュをクリア"""
        self._file_cache.clear()


# ================================================================
# エクスポート
# ================================================================

__all__ = [
    'DrivePermissionManager',
    'DrivePermission',
    'PermissionChange',
    'PermissionSyncResult',
    'PermissionRole',
    'PermissionType',
    'ROLE_LEVEL_TO_PERMISSION',
]
