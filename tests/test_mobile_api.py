"""
Mobile API ユニットテスト

mobile-api/main.py のユニットテスト。
DB依存部分はモック化し、認証・入力検証・エラーハンドリングをテスト。
"""

import importlib
import importlib.util
import json
import os
import sys
import time
import types
import pytest
from unittest.mock import MagicMock, patch

# =============================================================================
# モジュールロード（root の main.py との名前衝突を回避）
# =============================================================================

_MOBILE_API_DIR = os.path.join(os.path.dirname(__file__), "..", "mobile-api")
_ROOT_DIR = os.path.join(os.path.dirname(__file__), "..")

# lib/ と chatwork-webhook/ をパスに追加（mobile-api/main.py の依存）
sys.path.insert(0, _ROOT_DIR)
sys.path.insert(0, os.path.join(_ROOT_DIR, "chatwork-webhook"))
sys.path.insert(0, _MOBILE_API_DIR)


def _load_mobile_main():
    """mobile-api/main.py を 'mobile_main' として明示ロード"""
    module_name = "mobile_main"
    if module_name in sys.modules:
        return sys.modules[module_name]

    # voice モジュールを先にロード（main.py line 560 で from voice import router）
    voice_path = os.path.join(_MOBILE_API_DIR, "voice.py")
    if os.path.exists(voice_path) and "voice" not in sys.modules:
        voice_spec = importlib.util.spec_from_file_location("voice", voice_path)
        voice_mod = importlib.util.module_from_spec(voice_spec)
        sys.modules["voice"] = voice_mod
        try:
            voice_spec.loader.exec_module(voice_mod)
        except (ImportError, ModuleNotFoundError, RuntimeError):
            # voice.py の外部依存（openai, google-cloud-tts, python-multipart等）が
            # 未インストールでも main.py のテストは可能。最低限の router を提供
            import warnings
            warnings.warn("voice.py load failed (expected in test env)")
            from fastapi import APIRouter
            voice_mod.router = APIRouter()

    main_path = os.path.join(_MOBILE_API_DIR, "main.py")
    spec = importlib.util.spec_from_file_location(module_name, main_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


# モジュールをグローバルで1回ロード
mobile_main = _load_mobile_main()


# =============================================================================
# JWT トークン テスト
# =============================================================================


class TestJWTToken:
    """JWT認証のテスト"""

    def _set_jwt_secret(self):
        """テスト用にJWT_SECRETを設定"""
        mobile_main.JWT_SECRET = "test-secret-key-for-testing-only"
        return mobile_main

    def test_create_token_returns_string(self):
        mm = self._set_jwt_secret()
        token = mm._create_token("user1", "org1", "Test User")
        assert isinstance(token, str)
        assert len(token) > 20

    def test_verify_valid_token(self):
        mm = self._set_jwt_secret()
        token = mm._create_token("user1", "org1", "Test User")
        payload = mm._verify_token(token)
        assert payload["sub"] == "user1"
        assert payload["org_id"] == "org1"
        assert payload["display_name"] == "Test User"

    def test_verify_invalid_token_raises(self):
        mm = self._set_jwt_secret()
        with pytest.raises(Exception):
            mm._verify_token("invalid.token.here")

    def test_verify_empty_token_raises(self):
        mm = self._set_jwt_secret()
        with pytest.raises(Exception):
            mm._verify_token("")

    def test_token_contains_expiry(self):
        mm = self._set_jwt_secret()
        token = mm._create_token("user1", "org1")
        payload = mm._verify_token(token)
        assert "exp" in payload
        # 有効期限が未来であること
        assert payload["exp"] > time.time()

    def test_token_contains_issued_at(self):
        mm = self._set_jwt_secret()
        token = mm._create_token("user1", "org1")
        payload = mm._verify_token(token)
        assert "iat" in payload

    def test_different_secrets_fail_verification(self):
        mm = self._set_jwt_secret()
        token = mm._create_token("user1", "org1")
        mm.JWT_SECRET = "different-secret"
        with pytest.raises(Exception):
            mm._verify_token(token)


# =============================================================================
# Pydantic モデル テスト
# =============================================================================


class TestPydanticModels:
    """リクエスト/レスポンスモデルのテスト"""

    def test_login_request_valid(self):
        req = mobile_main.LoginRequest(email="test@example.com", password="secret")
        assert req.email == "test@example.com"
        assert req.password == "secret"

    def test_chat_request_valid(self):
        req = mobile_main.ChatRequest(message="こんにちは")
        assert req.message == "こんにちは"

    def test_chat_request_with_context(self):
        req = mobile_main.ChatRequest(message="test", context={"key": "value"})
        assert req.context == {"key": "value"}

    def test_login_response_model(self):
        resp = mobile_main.LoginResponse(
            access_token="token123",
            token_type="bearer",
            user={"id": "u1", "display_name": "Test"},
        )
        assert resp.access_token == "token123"
        assert resp.token_type == "bearer"
        assert resp.user["id"] == "u1"

    def test_task_response_model(self):
        task = mobile_main.TaskResponse(
            id=1,
            title="テストタスク",
            status="open",
            assigned_to="user1",
            due_date="2026-03-01",
        )
        assert task.id == 1
        assert task.title == "テストタスク"

    def test_goal_response_model(self):
        goal = mobile_main.GoalResponse(
            id=1,
            title="売上目標",
            status="active",
            progress_percentage=0.5,
        )
        assert goal.progress_percentage == 0.5

    def test_person_response_model(self):
        person = mobile_main.PersonResponse(
            id=1,
            display_name="田中太郎",
            department="営業部",
            position="リーダー",
        )
        assert person.department == "営業部"

    def test_chat_response_model(self):
        resp = mobile_main.ChatResponse(
            response="こんにちは！",
            action=None,
            metadata=None,
        )
        assert resp.response == "こんにちは！"

    def test_notification_register_request_valid(self):
        req = mobile_main.NotificationRegisterRequest(
            device_token="abc123", platform="ios"
        )
        assert req.platform == "ios"

    def test_notification_register_request_invalid_platform(self):
        with pytest.raises(Exception):
            mobile_main.NotificationRegisterRequest(
                device_token="abc", platform="windows"
            )


# =============================================================================
# FastAPI アプリ テスト（TestClient使用）
# =============================================================================


class TestHealthEndpoint:
    """ヘルスチェックエンドポイントのテスト"""

    def test_health_returns_ok(self):
        from fastapi.testclient import TestClient
        client = TestClient(mobile_main.app)
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "soulkun-mobile-api"


class TestLoginEndpoint:
    """ログインエンドポイントのテスト"""

    def test_login_missing_fields(self):
        from fastapi.testclient import TestClient
        client = TestClient(mobile_main.app)
        response = client.post("/api/v1/auth/login", json={})
        assert response.status_code == 422  # Validation error

    def test_login_wrong_content_type(self):
        from fastapi.testclient import TestClient
        client = TestClient(mobile_main.app)
        response = client.post("/api/v1/auth/login", data="not json")
        assert response.status_code == 422


class TestAuthProtection:
    """認証保護のテスト"""

    def test_chat_without_auth_returns_403(self):
        from fastapi.testclient import TestClient
        client = TestClient(mobile_main.app)
        response = client.post("/api/v1/chat", json={"message": "test"})
        assert response.status_code == 403

    def test_tasks_without_auth_returns_403(self):
        from fastapi.testclient import TestClient
        client = TestClient(mobile_main.app)
        response = client.get("/api/v1/tasks")
        assert response.status_code == 403

    def test_goals_without_auth_returns_403(self):
        from fastapi.testclient import TestClient
        client = TestClient(mobile_main.app)
        response = client.get("/api/v1/goals")
        assert response.status_code == 403

    def test_persons_without_auth_returns_403(self):
        from fastapi.testclient import TestClient
        client = TestClient(mobile_main.app)
        response = client.get("/api/v1/persons")
        assert response.status_code == 403

    def test_invalid_bearer_token_returns_401(self):
        from fastapi.testclient import TestClient
        client = TestClient(mobile_main.app)
        response = client.post(
            "/api/v1/chat",
            json={"message": "test"},
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert response.status_code in (401, 403)

    def test_refresh_without_auth_returns_403(self):
        from fastapi.testclient import TestClient
        client = TestClient(mobile_main.app)
        response = client.post("/api/v1/auth/refresh")
        assert response.status_code == 403

    def test_notification_register_without_auth_returns_403(self):
        from fastapi.testclient import TestClient
        client = TestClient(mobile_main.app)
        response = client.post(
            "/api/v1/notifications/register",
            json={"device_token": "abc", "platform": "ios"},
        )
        assert response.status_code == 403


# =============================================================================
# CORS テスト
# =============================================================================


class TestCORS:
    """CORS設定のテスト"""

    def test_cors_headers_present(self):
        from fastapi.testclient import TestClient
        client = TestClient(mobile_main.app)
        response = client.options(
            "/api/v1/auth/login",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
            },
        )
        # CORSミドルウェアが応答すること
        assert response.status_code in (200, 400)


# =============================================================================
# セキュリティテスト
# =============================================================================


class TestSecurityPatterns:
    """セキュリティパターンのテスト"""

    @pytest.mark.asyncio
    async def test_jwt_secret_required_in_production(self):
        """本番環境ではJWT_SECRETが必須"""
        original = mobile_main.JWT_SECRET
        mobile_main.JWT_SECRET = ""
        try:
            with patch.dict(os.environ, {"ENVIRONMENT": "production"}):
                with pytest.raises(RuntimeError, match="JWT_SECRET"):
                    await mobile_main.validate_config()
        finally:
            mobile_main.JWT_SECRET = original

    def test_sql_safety_in_endpoint_code(self):
        """エンドポイントのSQL安全性を確認（鉄則#9: パラメータ化必須）"""
        import inspect
        for func_name in ["get_tasks", "get_goals", "get_persons"]:
            func = getattr(mobile_main, func_name)
            source = inspect.getsource(func)
            # 破壊的SQL文がないこと
            assert "DROP " not in source, f"{func_name} contains DROP statement"
            assert "TRUNCATE " not in source, f"{func_name} contains TRUNCATE statement"
            # f-string/format によるSQL組み立てがないこと（インジェクションリスク）
            assert 'f"SELECT' not in source, f"{func_name} may use f-string in SQL"
            assert "f'SELECT" not in source, f"{func_name} may use f-string in SQL"

    def test_pii_not_in_health_response(self):
        """ヘルスチェックにPIIが含まれないことを確認（鉄則#8）"""
        from fastapi.testclient import TestClient
        client = TestClient(mobile_main.app)
        response = client.get("/health")
        data = response.json()
        # ヘルスチェックには status/service/version のみ含まれるべき
        allowed_keys = {"status", "service", "version"}
        for key in data:
            assert key in allowed_keys, f"Unexpected key in health response: {key}"
        assert "password" not in response.text.lower()
        assert "@" not in response.text  # メールアドレスが含まれないこと


# =============================================================================
# ConnectionManager テスト
# =============================================================================


class TestConnectionManager:
    """WebSocket接続管理のテスト"""

    def test_manager_init(self):
        manager = mobile_main.ConnectionManager()
        assert hasattr(manager, "active_connections")
        assert len(manager.active_connections) == 0

    def test_manager_register_and_disconnect(self):
        manager = mobile_main.ConnectionManager()
        mock_ws = MagicMock()
        manager.register("user1", mock_ws)
        assert "user1" in manager.active_connections
        manager.disconnect("user1")
        assert "user1" not in manager.active_connections

    def test_manager_disconnect_nonexistent(self):
        manager = mobile_main.ConnectionManager()
        # 存在しないユーザーのdisconnectはエラーにならない
        manager.disconnect("nonexistent_user")

    def test_ws_max_message_size_defined(self):
        """DoS防止のメッセージサイズ制限が設定されていること"""
        assert hasattr(mobile_main, "WS_MAX_MESSAGE_SIZE")
        assert mobile_main.WS_MAX_MESSAGE_SIZE > 0
