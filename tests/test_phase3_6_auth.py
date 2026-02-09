# tests/test_phase3_6_auth.py
"""Phase 3.6 認証ミドルウェアのテスト"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from api.app.middleware.auth import (
    AuthenticatedUser,
    TenantRole,
    get_current_user,
    require_role,
    verify_firebase_token,
)
from fastapi import HTTPException


class TestTenantRole:
    """TenantRoleのテスト"""

    def test_role_values(self):
        """役割の値が正しい"""
        assert TenantRole.OWNER == "owner"
        assert TenantRole.ADMIN == "admin"
        assert TenantRole.EDITOR == "editor"
        assert TenantRole.VIEWER == "viewer"

    def test_role_from_string(self):
        """文字列からの変換"""
        assert TenantRole("owner") == TenantRole.OWNER
        assert TenantRole("viewer") == TenantRole.VIEWER


class TestAuthenticatedUser:
    """AuthenticatedUserのテスト"""

    def test_default_values(self):
        """デフォルト値が正しい"""
        user = AuthenticatedUser(
            firebase_uid="uid123",
            email="test@example.com",
        )
        assert user.firebase_uid == "uid123"
        assert user.email == "test@example.com"
        assert user.display_name is None
        assert user.tenant_id is None
        assert user.organization_id is None
        assert user.role == TenantRole.VIEWER

    def test_with_all_fields(self):
        """全フィールド指定"""
        user = AuthenticatedUser(
            firebase_uid="uid123",
            email="test@example.com",
            display_name="Test User",
            tenant_id="tenant_1",
            organization_id="org_1",
            role=TenantRole.ADMIN,
        )
        assert user.display_name == "Test User"
        assert user.role == TenantRole.ADMIN


class TestVerifyFirebaseToken:
    """verify_firebase_tokenのテスト"""

    @pytest.mark.asyncio
    async def test_not_implemented(self):
        """未実装時は501を返す"""
        with pytest.raises(HTTPException) as exc_info:
            await verify_firebase_token("fake_token")
        assert exc_info.value.status_code == 501


class TestGetCurrentUser:
    """get_current_userのテスト"""

    @pytest.mark.asyncio
    async def test_no_credentials_returns_401(self):
        """認証情報なしは401"""
        request = MagicMock()
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(request, credentials=None)
        assert exc_info.value.status_code == 401


class TestRequireRole:
    """require_roleのテスト"""

    @pytest.mark.asyncio
    async def test_owner_can_access_all(self):
        """オーナーは全てにアクセス可能"""
        user = AuthenticatedUser(
            firebase_uid="uid1",
            email="owner@test.com",
            role=TenantRole.OWNER,
        )
        # 全ての役割に対してアクセス可能（例外なし）
        await require_role(user, TenantRole.VIEWER)
        await require_role(user, TenantRole.EDITOR)
        await require_role(user, TenantRole.ADMIN)
        await require_role(user, TenantRole.OWNER)

    @pytest.mark.asyncio
    async def test_viewer_cannot_access_admin(self):
        """閲覧者はAdmin操作にアクセス不可"""
        user = AuthenticatedUser(
            firebase_uid="uid2",
            email="viewer@test.com",
            role=TenantRole.VIEWER,
        )
        with pytest.raises(HTTPException) as exc_info:
            await require_role(user, TenantRole.ADMIN)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_editor_can_access_viewer(self):
        """編集者はViewer操作にアクセス可能"""
        user = AuthenticatedUser(
            firebase_uid="uid3",
            email="editor@test.com",
            role=TenantRole.EDITOR,
        )
        await require_role(user, TenantRole.VIEWER)

    @pytest.mark.asyncio
    async def test_admin_cannot_access_owner(self):
        """管理者はOwner操作にアクセス不可"""
        user = AuthenticatedUser(
            firebase_uid="uid4",
            email="admin@test.com",
            role=TenantRole.ADMIN,
        )
        with pytest.raises(HTTPException) as exc_info:
            await require_role(user, TenantRole.OWNER)
        assert exc_info.value.status_code == 403
