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
from unittest.mock import AsyncMock, MagicMock, patch

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

    def test_chat_without_auth_rejected(self):
        from fastapi.testclient import TestClient
        client = TestClient(mobile_main.app)
        response = client.post("/api/v1/chat", json={"message": "test"})
        # HTTPBearer: 403 (fastapi<0.110) or 401 (fastapi>=0.110)
        assert response.status_code in (401, 403)

    def test_tasks_without_auth_rejected(self):
        from fastapi.testclient import TestClient
        client = TestClient(mobile_main.app)
        response = client.get("/api/v1/tasks")
        assert response.status_code in (401, 403)

    def test_goals_without_auth_rejected(self):
        from fastapi.testclient import TestClient
        client = TestClient(mobile_main.app)
        response = client.get("/api/v1/goals")
        assert response.status_code in (401, 403)

    def test_persons_without_auth_rejected(self):
        from fastapi.testclient import TestClient
        client = TestClient(mobile_main.app)
        response = client.get("/api/v1/persons")
        assert response.status_code in (401, 403)

    def test_invalid_bearer_token_rejected(self):
        from fastapi.testclient import TestClient
        client = TestClient(mobile_main.app)
        response = client.post(
            "/api/v1/chat",
            json={"message": "test"},
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert response.status_code in (401, 403)

    def test_refresh_without_auth_rejected(self):
        from fastapi.testclient import TestClient
        client = TestClient(mobile_main.app)
        response = client.post("/api/v1/auth/refresh")
        assert response.status_code in (401, 403)

    def test_notification_register_without_auth_rejected(self):
        from fastapi.testclient import TestClient
        client = TestClient(mobile_main.app)
        response = client.post(
            "/api/v1/notifications/register",
            json={"device_token": "abc", "platform": "ios"},
        )
        assert response.status_code in (401, 403)


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


# =============================================================================
# ログイン ハッピーパステスト
# =============================================================================


class TestLoginHappyPath:
    """ログイン成功パスのテスト（DBモック使用）"""

    def _setup_jwt(self):
        mobile_main.JWT_SECRET = "test-secret-key-for-testing-only"

    def test_login_success(self):
        self._setup_jwt()
        from fastapi.testclient import TestClient

        with patch.object(
            mobile_main, "_login_db", return_value={
                "id": "user-1",
                "display_name": "Test User",
                "organization_id": "org-1",
            }
        ):
            client = TestClient(mobile_main.app)
            response = client.post(
                "/api/v1/auth/login",
                json={"email": "test@example.com", "password": "secret123"},
            )
            assert response.status_code == 200
            data = response.json()
            assert "access_token" in data
            assert data["user"]["id"] == "user-1"
            assert data["user"]["display_name"] == "Test User"
            # PII確認: emailがレスポンスに含まれないこと（鉄則#8）
            assert "email" not in data["user"]
            assert "@" not in json.dumps(data["user"])

    def test_login_wrong_password(self):
        self._setup_jwt()
        from fastapi.testclient import TestClient

        with patch.object(mobile_main, "_login_db", return_value={}):
            client = TestClient(mobile_main.app)
            response = client.post(
                "/api/v1/auth/login",
                json={"email": "test@example.com", "password": "wrong"},
            )
            assert response.status_code == 401


# =============================================================================
# 認証済みエンドポイント ハッピーパステスト
# =============================================================================


class TestAuthenticatedEndpoints:
    """JWT認証済みでのデータ取得テスト（DBモック使用）"""

    def _get_auth_header(self):
        mobile_main.JWT_SECRET = "test-secret-key-for-testing-only"
        token = mobile_main._create_token("user1", "org_test", "Test User")
        return {"Authorization": f"Bearer {token}"}

    def test_get_tasks_returns_list(self):
        from fastapi.testclient import TestClient
        headers = self._get_auth_header()
        mock_rows = [
            {"id": 1, "title": "タスクA", "status": "open", "assigned_to": "user1", "due_date": "2026-03-01"},
            {"id": 2, "title": "タスクB", "status": "in_progress", "assigned_to": None, "due_date": None},
        ]
        with patch.object(mobile_main, "_run_db_query", return_value=mock_rows):
            client = TestClient(mobile_main.app)
            response = client.get("/api/v1/tasks", headers=headers)
            assert response.status_code == 200
            data = response.json()
            assert len(data) == 2
            assert data[0]["title"] == "タスクA"

    def test_get_tasks_org_id_passed_correctly(self):
        """org_idがJWTから正しく抽出されDBクエリに渡されること（鉄則#1）"""
        from fastapi.testclient import TestClient
        headers = self._get_auth_header()

        with patch.object(mobile_main, "_run_db_query", return_value=[]) as mock_query:
            client = TestClient(mobile_main.app)
            client.get("/api/v1/tasks", headers=headers)
            # _run_db_queryの第1引数がorg_id
            mock_query.assert_called_once()
            call_args = mock_query.call_args
            assert call_args[0][0] == "org_test"  # JWTに含まれるorg_id

    def test_get_goals_returns_list(self):
        from fastapi.testclient import TestClient
        headers = self._get_auth_header()
        mock_rows = [
            {"id": 1, "title": "売上目標", "description": "Q1", "status": "active", "progress_percentage": 0.7},
        ]
        with patch.object(mobile_main, "_run_db_query", return_value=mock_rows):
            client = TestClient(mobile_main.app)
            response = client.get("/api/v1/goals", headers=headers)
            assert response.status_code == 200
            data = response.json()
            assert len(data) == 1
            assert data[0]["progress_percentage"] == 0.7

    def test_get_persons_returns_list_without_pii(self):
        """メンバー一覧にPII（email/phone）が含まれないこと（鉄則#8）"""
        from fastapi.testclient import TestClient
        headers = self._get_auth_header()
        mock_rows = [
            {"id": 1, "display_name": "田中太郎", "department": "営業部", "position": "リーダー"},
        ]
        with patch.object(mobile_main, "_run_db_query", return_value=mock_rows) as mock_query:
            client = TestClient(mobile_main.app)
            response = client.get("/api/v1/persons", headers=headers)
            assert response.status_code == 200
            data = response.json()
            assert len(data) == 1
            assert data[0]["display_name"] == "田中太郎"
            # PII検証: SQLのSELECT句にemail/phoneが含まれないこと（鉄則#8）
            mock_query.assert_called_once()
            sql_arg = mock_query.call_args[0][1]  # 2nd arg = query (1st is org_id)
            select_clause = sql_arg.upper().split("FROM")[0]
            assert "EMAIL" not in select_clause
            assert "PHONE" not in select_clause
            # レスポンスにもPIIマーカーがないこと
            response_text = response.text
            assert "@" not in response_text
            assert "phone" not in response_text.lower()

    def test_get_tasks_limit_capped_at_100(self):
        """limitパラメータが100以上でも100に制限されること（鉄則#5）"""
        from fastapi.testclient import TestClient
        headers = self._get_auth_header()

        with patch.object(mobile_main, "_run_db_query", return_value=[]) as mock_query:
            client = TestClient(mobile_main.app)
            client.get("/api/v1/tasks?limit=9999", headers=headers)
            # SQLのLIMITパラメータが100以下であること
            call_args = mock_query.call_args
            query_params = call_args[0][2]  # 3rd arg = params list
            # 最後のparamがlimit値
            assert query_params[-1] <= 100


# =============================================================================
# チャット ハッピーパステスト
# =============================================================================


class TestChatHappyPath:
    """チャットエンドポイントのハッピーパステスト（Brain経由）"""

    def _get_auth_header(self):
        mobile_main.JWT_SECRET = "test-secret-key-for-testing-only"
        token = mobile_main._create_token("user1", "org_test", "Test User")
        return {"Authorization": f"Bearer {token}"}

    def test_chat_via_brain(self):
        import sys
        from fastapi.testclient import TestClient
        headers = self._get_auth_header()

        mock_result = MagicMock()
        mock_result.to_chatwork_message.return_value = "こんにちは！元気ですか？"
        mock_result.action = None
        mock_result.metadata = None

        # lib.brain.llm はカスタム __getattr__ のため直接patchできない
        mock_llm_module = MagicMock()
        mock_integration_module = MagicMock()
        MockBrain = MagicMock()
        instance = AsyncMock()
        instance.process_message.return_value = mock_result
        MockBrain.return_value = instance
        mock_integration_module.BrainIntegration = MockBrain

        with patch.dict(sys.modules, {
            "lib.brain.llm": mock_llm_module,
            "lib.brain.integration": mock_integration_module,
        }), \
             patch.object(mobile_main, "_get_pool", return_value=MagicMock()), \
             patch.object(mobile_main, "_get_handlers", return_value={}), \
             patch.object(mobile_main, "_get_capabilities", return_value={}):

            client = TestClient(mobile_main.app)
            response = client.post(
                "/api/v1/chat",
                json={"message": "こんにちは"},
                headers=headers,
            )
            assert response.status_code == 200
            data = response.json()
            assert "こんにちは" in data["response"]
            # BrainIntegrationが使われたことを確認（bypass禁止）
            MockBrain.assert_called_once()

    def test_chat_brain_error_returns_500(self):
        from fastapi.testclient import TestClient
        headers = self._get_auth_header()

        with patch.object(mobile_main, "_get_pool", side_effect=Exception("DB down")):
            client = TestClient(mobile_main.app)
            response = client.post(
                "/api/v1/chat",
                json={"message": "テスト"},
                headers=headers,
            )
            assert response.status_code == 500
            # エラー詳細が漏れないこと（鉄則#8）
            assert "DB down" not in response.text


# =============================================================================
# WebSocket 認証テスト
# =============================================================================


class TestWebSocketAuth:
    """WebSocket認証フローのテスト"""

    def test_websocket_connect_with_valid_token(self):
        from fastapi.testclient import TestClient
        mobile_main.JWT_SECRET = "test-secret-key-for-testing-only"
        token = mobile_main._create_token("user1", "org_test", "Test User")

        client = TestClient(mobile_main.app)
        with client.websocket_connect("/api/v1/ws") as ws:
            ws.send_json({"token": token})
            data = ws.receive_json()
            assert data["type"] == "connected"
            assert data["user_id"] == "user1"

    def test_websocket_connect_with_invalid_token(self):
        from fastapi.testclient import TestClient
        mobile_main.JWT_SECRET = "test-secret-key-for-testing-only"

        client = TestClient(mobile_main.app)
        with client.websocket_connect("/api/v1/ws") as ws:
            ws.send_json({"token": "invalid-token"})
            data = ws.receive_json()
            assert data.get("error") == "Authentication failed"
