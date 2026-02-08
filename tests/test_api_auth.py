"""
tests/test_api_auth.py - JWT認証テスト

Task 1-2: API認証ミドルウェアの単体テスト。
- JWT生成・検証
- 無効トークンで401
- 期限切れトークンで401
- 必須claims不足で401
- 正常トークンでUserContext取得
- ロール別アクセス制御
"""

import datetime
import os
import sys
from unittest.mock import patch, MagicMock

import pytest
from jose import jwt

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

# テスト用JWT秘密鍵
TEST_JWT_SECRET = "test-secret-key-for-unit-tests-only"


@pytest.fixture(autouse=True)
def set_jwt_secret(monkeypatch):
    """テスト用のJWT秘密鍵を設定（環境変数＋モジュール変数＋キャッシュリセット）"""
    monkeypatch.setenv("SOULKUN_JWT_SECRET", TEST_JWT_SECRET)
    import app.deps.auth as auth_module
    monkeypatch.setattr(auth_module, "JWT_SECRET_KEY", TEST_JWT_SECRET)
    monkeypatch.setattr(auth_module, "_cached_secret", None)


def _make_token(
    user_id="user-001",
    org_id="org-001",
    role="member",
    dept_id=None,
    expires_minutes=60,
    secret=TEST_JWT_SECRET,
    extra_claims=None,
):
    """テスト用JWTトークンを生成"""
    now = datetime.datetime.now(datetime.timezone.utc)
    payload = {
        "sub": user_id,
        "org_id": org_id,
        "role": role,
        "iat": now,
        "exp": now + datetime.timedelta(minutes=expires_minutes),
    }
    if dept_id:
        payload["dept_id"] = dept_id
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, secret, algorithm="HS256")


def _make_expired_token(**kwargs):
    """期限切れトークンを生成"""
    return _make_token(expires_minutes=-10, **kwargs)


# ================================================================
# decode_jwt テスト
# ================================================================


class TestDecodeJwt:
    """decode_jwt関数のテスト"""

    def test_valid_token(self):
        """正常なトークンをデコードできる"""
        from app.deps.auth import decode_jwt

        token = _make_token(user_id="u-123", org_id="o-456", role="admin")
        payload = decode_jwt(token)

        assert payload["sub"] == "u-123"
        assert payload["org_id"] == "o-456"
        assert payload["role"] == "admin"

    def test_invalid_token_raises_401(self):
        """不正なトークンで401"""
        from app.deps.auth import decode_jwt
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            decode_jwt("invalid-token-string")
        assert exc_info.value.status_code == 401
        assert "Invalid or expired token" in exc_info.value.detail

    def test_expired_token_raises_401(self):
        """期限切れトークンで401"""
        from app.deps.auth import decode_jwt
        from fastapi import HTTPException

        token = _make_expired_token()
        with pytest.raises(HTTPException) as exc_info:
            decode_jwt(token)
        assert exc_info.value.status_code == 401

    def test_wrong_secret_raises_401(self):
        """異なる秘密鍵で署名されたトークンで401"""
        from app.deps.auth import decode_jwt
        from fastapi import HTTPException

        token = _make_token(secret="wrong-secret-key")
        with pytest.raises(HTTPException) as exc_info:
            decode_jwt(token)
        assert exc_info.value.status_code == 401

    def test_missing_sub_raises_401(self):
        """subクレームがないトークンで401"""
        from app.deps.auth import decode_jwt
        from fastapi import HTTPException

        now = datetime.datetime.now(datetime.timezone.utc)
        payload = {
            "org_id": "org-001",
            "iat": now,
            "exp": now + datetime.timedelta(hours=1),
        }
        token = jwt.encode(payload, TEST_JWT_SECRET, algorithm="HS256")

        with pytest.raises(HTTPException) as exc_info:
            decode_jwt(token)
        assert exc_info.value.status_code == 401
        assert "sub" in exc_info.value.detail

    def test_missing_org_id_raises_401(self):
        """org_idクレームがないトークンで401"""
        from app.deps.auth import decode_jwt
        from fastapi import HTTPException

        now = datetime.datetime.now(datetime.timezone.utc)
        payload = {
            "sub": "user-001",
            "iat": now,
            "exp": now + datetime.timedelta(hours=1),
        }
        token = jwt.encode(payload, TEST_JWT_SECRET, algorithm="HS256")

        with pytest.raises(HTTPException) as exc_info:
            decode_jwt(token)
        assert exc_info.value.status_code == 401
        assert "org_id" in exc_info.value.detail


# ================================================================
# get_current_user テスト
# ================================================================


class TestGetCurrentUser:
    """get_current_user依存関数のテスト"""

    @pytest.mark.asyncio
    async def test_no_credentials_raises_401(self):
        """認証情報なしで401"""
        from app.deps.auth import get_current_user
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(credentials=None)
        assert exc_info.value.status_code == 401
        assert "Authentication required" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_valid_member_token(self):
        """memberロールの正常トークンでUserContext取得"""
        from app.deps.auth import get_current_user
        from fastapi.security import HTTPAuthorizationCredentials

        token = _make_token(
            user_id="u-member",
            org_id="o-test",
            role="member",
            dept_id="d-sales",
        )
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        user = await get_current_user(credentials=creds)

        assert user.user_id == "u-member"
        assert user.organization_id == "o-test"
        assert user.department_id == "d-sales"
        assert user.accessible_classifications == ["public", "internal"]
        assert user.accessible_department_ids == ["d-sales"]

    @pytest.mark.asyncio
    async def test_admin_role_access(self):
        """adminロールはrestricted含む4区分アクセス可能"""
        from app.deps.auth import get_current_user
        from fastapi.security import HTTPAuthorizationCredentials

        token = _make_token(user_id="u-admin", org_id="o-test", role="admin")
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        user = await get_current_user(credentials=creds)

        assert "restricted" in user.accessible_classifications
        assert "confidential" in user.accessible_classifications
        assert len(user.accessible_classifications) == 4

    @pytest.mark.asyncio
    async def test_executive_role_access(self):
        """executiveロールはrestricted含む4区分アクセス可能"""
        from app.deps.auth import get_current_user
        from fastapi.security import HTTPAuthorizationCredentials

        token = _make_token(user_id="u-exec", org_id="o-test", role="executive")
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        user = await get_current_user(credentials=creds)

        assert "restricted" in user.accessible_classifications
        assert len(user.accessible_classifications) == 4

    @pytest.mark.asyncio
    async def test_manager_role_access(self):
        """managerロールはconfidentialまでアクセス可能"""
        from app.deps.auth import get_current_user
        from fastapi.security import HTTPAuthorizationCredentials

        token = _make_token(user_id="u-mgr", org_id="o-test", role="manager")
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        user = await get_current_user(credentials=creds)

        assert "confidential" in user.accessible_classifications
        assert "restricted" not in user.accessible_classifications
        assert len(user.accessible_classifications) == 3

    @pytest.mark.asyncio
    async def test_leader_role_access(self):
        """leaderロールはconfidentialまでアクセス可能"""
        from app.deps.auth import get_current_user
        from fastapi.security import HTTPAuthorizationCredentials

        token = _make_token(user_id="u-ldr", org_id="o-test", role="leader")
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        user = await get_current_user(credentials=creds)

        assert "confidential" in user.accessible_classifications
        assert len(user.accessible_classifications) == 3

    @pytest.mark.asyncio
    async def test_no_dept_id(self):
        """dept_idなしトークンのUserContext"""
        from app.deps.auth import get_current_user
        from fastapi.security import HTTPAuthorizationCredentials

        token = _make_token(user_id="u-test", org_id="o-test")
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        user = await get_current_user(credentials=creds)

        assert user.department_id is None
        assert user.accessible_department_ids == []

    @pytest.mark.asyncio
    async def test_default_role_is_member(self):
        """roleクレームなしのトークンはmember扱い"""
        from app.deps.auth import get_current_user
        from fastapi.security import HTTPAuthorizationCredentials

        now = datetime.datetime.now(datetime.timezone.utc)
        payload = {
            "sub": "u-norole",
            "org_id": "o-test",
            "iat": now,
            "exp": now + datetime.timedelta(hours=1),
        }
        token = jwt.encode(payload, TEST_JWT_SECRET, algorithm="HS256")
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        user = await get_current_user(credentials=creds)

        # roleなし → member → public, internal のみ
        assert user.accessible_classifications == ["public", "internal"]


# ================================================================
# create_access_token テスト
# ================================================================


class TestCreateAccessToken:
    """create_access_token関数のテスト"""

    def test_create_and_decode_roundtrip(self):
        """生成したトークンを正しくデコードできる"""
        from app.deps.auth import create_access_token, decode_jwt

        token = create_access_token(
            user_id="u-rt",
            organization_id="o-rt",
            department_id="d-rt",
            role="manager",
        )

        payload = decode_jwt(token)
        assert payload["sub"] == "u-rt"
        assert payload["org_id"] == "o-rt"
        assert payload["dept_id"] == "d-rt"
        assert payload["role"] == "manager"

    def test_create_without_department(self):
        """dept_idなしでトークン生成"""
        from app.deps.auth import create_access_token, decode_jwt

        token = create_access_token(
            user_id="u-nd",
            organization_id="o-nd",
        )

        payload = decode_jwt(token)
        assert payload["sub"] == "u-nd"
        assert "dept_id" not in payload

    def test_custom_expiry(self):
        """有効期限をカスタム設定"""
        from app.deps.auth import create_access_token, decode_jwt

        token = create_access_token(
            user_id="u-exp",
            organization_id="o-exp",
            expires_minutes=5,
        )

        payload = decode_jwt(token)
        # 5分後に期限切れ（±1分の誤差許容）
        exp = datetime.datetime.fromtimestamp(payload["exp"], tz=datetime.timezone.utc)
        now = datetime.datetime.now(datetime.timezone.utc)
        diff = (exp - now).total_seconds()
        assert 180 < diff < 360  # 3-6分の範囲


# ================================================================
# _get_jwt_secret テスト
# ================================================================


class TestGetJwtSecret:
    """_get_jwt_secret関数のテスト"""

    def test_env_var_priority(self):
        """環境変数が設定されていれば環境変数を使用"""
        from app.deps.auth import _get_jwt_secret

        secret = _get_jwt_secret()
        assert secret == TEST_JWT_SECRET

    def test_no_secret_raises_500(self, monkeypatch):
        """JWT秘密鍵が未設定で500"""
        from fastapi import HTTPException

        import app.deps.auth as auth_module
        monkeypatch.setenv("SOULKUN_JWT_SECRET", "")
        monkeypatch.setattr(auth_module, "JWT_SECRET_KEY", "")
        monkeypatch.setattr(auth_module, "_cached_secret", None)

        # Secret Managerも失敗させる
        with patch.dict(os.environ, {"GCP_PROJECT_ID": ""}, clear=False):
            with pytest.raises(HTTPException) as exc_info:
                auth_module._get_jwt_secret()
            assert exc_info.value.status_code == 500
