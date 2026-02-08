"""
tests/test_org_isolation.py - 組織分離テスト

CLAUDE.md 鉄則#1「全テーブルにorganization_idを追加」の検証テスト。

テスト対象:
- PersonService: 全SQLクエリにorganization_idフィルターが含まれる
- TaskHandler: 全SQLクエリにorganization_idフィルターが含まれる
- API endpoints: JWT org_idとパスorg_idの不一致で403
- org_id validation: 空文字列のorg_idを拒否

テナント間データ漏洩を防止するための回帰テスト。
"""

import datetime
import os
import sys
from unittest.mock import MagicMock, AsyncMock, patch

import pytest
from jose import jwt

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

# TaskHandlerはimportlibで直接ファイルパス指定（lib/handlersの名前衝突を回避）
import importlib.util

_task_handler_path = os.path.join(
    os.path.dirname(__file__), "..", "chatwork-webhook", "handlers", "task_handler.py"
)
_spec = importlib.util.spec_from_file_location("task_handler", _task_handler_path)
_task_handler_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_task_handler_mod)
TaskHandler = _task_handler_mod.TaskHandler

# テスト用JWT秘密鍵
TEST_JWT_SECRET = "test-secret-key-for-org-isolation-tests"


@pytest.fixture(autouse=True)
def set_jwt_secret(monkeypatch):
    """テスト用のJWT秘密鍵を設定"""
    monkeypatch.setenv("SOULKUN_JWT_SECRET", TEST_JWT_SECRET)
    import app.deps.auth as auth_module
    monkeypatch.setattr(auth_module, "JWT_SECRET_KEY", TEST_JWT_SECRET)
    monkeypatch.setattr(auth_module, "_cached_secret", None)


def _make_token(user_id="user-001", org_id="org-001", role="member", expires_minutes=60):
    """テスト用JWTトークンを生成"""
    now = datetime.datetime.now(datetime.timezone.utc)
    payload = {
        "sub": user_id,
        "org_id": org_id,
        "role": role,
        "iat": now,
        "exp": now + datetime.timedelta(minutes=expires_minutes),
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm="HS256")


def _make_mock_pool():
    """mock_poolを生成するヘルパー（context manager pattern）"""
    mock_pool = MagicMock()
    mock_conn = MagicMock()
    mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
    mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)
    mock_pool.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
    mock_pool.begin.return_value.__exit__ = MagicMock(return_value=None)
    return mock_pool, mock_conn


# ================================================================
# TestPersonServiceOrgIsolation
# ================================================================


class TestPersonServiceOrgIsolation:
    """PersonServiceが全クエリでorganization_idフィルターを適用することを検証"""

    def _make_service(self, mock_pool, org_id="org-alpha"):
        """PersonServiceを生成するヘルパー"""
        from lib.person_service import PersonService

        return PersonService(
            get_pool=lambda: mock_pool,
            organization_id=org_id,
        )

    def test_search_person_includes_org_id(self):
        """search_person_by_partial_nameがorganization_idをSQLパラメータに含む"""
        mock_pool, mock_conn = _make_mock_pool()

        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result

        service = self._make_service(mock_pool, org_id="org-alpha")
        service.search_person_by_partial_name("田中")

        call_args = mock_conn.execute.call_args
        params = call_args[0][1]
        assert params["org_id"] == "org-alpha"

    def test_search_person_different_orgs_different_params(self):
        """異なるorg_idを持つPersonServiceが異なるSQLパラメータを生成する"""
        # org-alpha
        mock_pool_a, mock_conn_a = _make_mock_pool()
        mock_result_a = MagicMock()
        mock_result_a.fetchall.return_value = [("田中太郎",)]
        mock_conn_a.execute.return_value = mock_result_a

        service_a = self._make_service(mock_pool_a, org_id="org-alpha")
        service_a.search_person_by_partial_name("田中")

        params_a = mock_conn_a.execute.call_args[0][1]

        # org-beta
        mock_pool_b, mock_conn_b = _make_mock_pool()
        mock_result_b = MagicMock()
        mock_result_b.fetchall.return_value = [("田中花子",)]
        mock_conn_b.execute.return_value = mock_result_b

        service_b = self._make_service(mock_pool_b, org_id="org-beta")
        service_b.search_person_by_partial_name("田中")

        params_b = mock_conn_b.execute.call_args[0][1]

        # org_idが異なることを検証
        assert params_a["org_id"] == "org-alpha"
        assert params_b["org_id"] == "org-beta"
        assert params_a["org_id"] != params_b["org_id"]

    def test_get_or_create_person_includes_org_id(self):
        """get_or_create_personがorganization_idをSQLパラメータに含む"""
        mock_pool, mock_conn = _make_mock_pool()

        # 人物が見つかるケース
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (42,)
        mock_conn.execute.return_value = mock_result

        service = self._make_service(mock_pool, org_id="org-gamma")
        service.get_or_create_person("鈴木一郎")

        call_args = mock_conn.execute.call_args
        params = call_args[0][1]
        assert params["org_id"] == "org-gamma"

    def test_get_person_info_includes_org_id(self):
        """get_person_infoがorganization_idをSQLパラメータに含む"""
        mock_pool, mock_conn = _make_mock_pool()

        # 人物が見つかるケース
        mock_result_person = MagicMock()
        mock_result_person.fetchone.return_value = (1,)

        mock_result_attrs = MagicMock()
        mock_result_attrs.fetchall.return_value = [("role", "manager")]

        mock_conn.execute.side_effect = [mock_result_person, mock_result_attrs]

        service = self._make_service(mock_pool, org_id="org-delta")
        service.get_person_info("高橋健太")

        # 両方のクエリでorg_idが渡されていることを検証
        assert mock_conn.execute.call_count == 2
        for call in mock_conn.execute.call_args_list:
            params = call[0][1]
            assert params["org_id"] == "org-delta"

    def test_delete_person_includes_org_id_in_all_queries(self):
        """delete_personが全てのSQLクエリでorganization_idを含む"""
        mock_pool, mock_conn = _make_mock_pool()

        # person検索
        mock_result_find = MagicMock()
        mock_result_find.fetchone.return_value = (99,)

        # DELETE結果（属性、イベント、人物）
        mock_delete_result = MagicMock()

        # begin() + transaction mock
        mock_trans = MagicMock()
        mock_conn.begin.return_value = mock_trans

        mock_conn.execute.side_effect = [
            mock_result_find,
            mock_delete_result,
            mock_delete_result,
            mock_delete_result,
        ]

        service = self._make_service(mock_pool, org_id="org-epsilon")
        service.delete_person("佐藤次郎")

        # 全クエリ（SELECT + 3つのDELETE）でorg_idが渡されている
        assert mock_conn.execute.call_count == 4
        for call in mock_conn.execute.call_args_list:
            params = call[0][1]
            assert params["org_id"] == "org-epsilon"

    def test_get_all_persons_summary_includes_org_id(self):
        """get_all_persons_summaryがorganization_idをSQLパラメータに含む"""
        mock_pool, mock_conn = _make_mock_pool()

        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result

        service = self._make_service(mock_pool, org_id="org-zeta")
        service.get_all_persons_summary()

        call_args = mock_conn.execute.call_args
        params = call_args[0][1]
        assert params["org_id"] == "org-zeta"

    def test_save_person_attribute_includes_org_id(self):
        """save_person_attributeがorganization_idをSQLパラメータに含む"""
        mock_pool, mock_conn = _make_mock_pool()

        # get_or_create_person用（beginコンテキスト内）
        mock_result_find = MagicMock()
        mock_result_find.fetchone.return_value = (10,)
        mock_conn.execute.return_value = mock_result_find

        service = self._make_service(mock_pool, org_id="org-eta")
        service.save_person_attribute("山田太郎", "role", "engineer")

        # 全executeコールでorg_idが渡されている
        for call in mock_conn.execute.call_args_list:
            params = call[0][1]
            assert params["org_id"] == "org-eta"


# ================================================================
# TestTaskHandlerOrgIsolation
# ================================================================


class TestTaskHandlerOrgIsolation:
    """TaskHandlerが全クエリでorganization_idフィルターを適用することを検証"""

    def _make_handler(self, mock_pool, org_id="org-task-alpha"):
        """TaskHandlerを生成するヘルパー"""
        return TaskHandler(
            get_pool=lambda: mock_pool,
            get_secret=lambda key: "dummy-secret",
            call_chatwork_api_with_retry=MagicMock(),
            organization_id=org_id,
        )

    def test_search_tasks_includes_org_id(self):
        """search_tasks_from_dbがorganization_idをSQLパラメータに含む"""
        mock_pool, mock_conn = _make_mock_pool()

        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result

        handler = self._make_handler(mock_pool, org_id="org-task-alpha")
        handler.search_tasks_from_db(room_id="room-123")

        call_args = mock_conn.execute.call_args
        params = call_args[0][1]
        assert params["org_id"] == "org-task-alpha"

    def test_search_tasks_different_orgs_different_params(self):
        """異なるorg_idを持つTaskHandlerが異なるSQLパラメータを生成する"""
        # org-task-alpha
        mock_pool_a, mock_conn_a = _make_mock_pool()
        mock_result_a = MagicMock()
        mock_result_a.fetchall.return_value = []
        mock_conn_a.execute.return_value = mock_result_a

        handler_a = self._make_handler(mock_pool_a, org_id="org-task-alpha")
        handler_a.search_tasks_from_db(room_id="room-123")

        params_a = mock_conn_a.execute.call_args[0][1]

        # org-task-beta
        mock_pool_b, mock_conn_b = _make_mock_pool()
        mock_result_b = MagicMock()
        mock_result_b.fetchall.return_value = []
        mock_conn_b.execute.return_value = mock_result_b

        handler_b = self._make_handler(mock_pool_b, org_id="org-task-beta")
        handler_b.search_tasks_from_db(room_id="room-123")

        params_b = mock_conn_b.execute.call_args[0][1]

        assert params_a["org_id"] == "org-task-alpha"
        assert params_b["org_id"] == "org-task-beta"
        assert params_a["org_id"] != params_b["org_id"]

    def test_update_task_status_includes_org_id(self):
        """update_task_status_in_dbがorganization_idをSQLパラメータに含む"""
        mock_pool, mock_conn = _make_mock_pool()
        mock_conn.execute.return_value = MagicMock()

        handler = self._make_handler(mock_pool, org_id="org-task-gamma")
        handler.update_task_status_in_db(task_id="task-001", status="done")

        call_args = mock_conn.execute.call_args
        params = call_args[0][1]
        assert params["org_id"] == "org-task-gamma"

    def test_save_task_to_db_includes_org_id(self):
        """save_chatwork_task_to_dbがorganization_idをSQLパラメータに含む"""
        mock_pool, mock_conn = _make_mock_pool()
        mock_conn.execute.return_value = MagicMock()

        handler = self._make_handler(mock_pool, org_id="org-task-delta")
        handler.save_chatwork_task_to_db(
            task_id="task-002",
            room_id="room-456",
            assigned_by_account_id="acc-001",
            assigned_to_account_id="acc-002",
            body="テストタスク",
        )

        call_args = mock_conn.execute.call_args
        params = call_args[0][1]
        assert params["org_id"] == "org-task-delta"

    def test_get_task_by_id_includes_org_id(self):
        """get_task_by_idがorganization_idをSQLパラメータに含む"""
        mock_pool, mock_conn = _make_mock_pool()

        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_conn.execute.return_value = mock_result

        handler = self._make_handler(mock_pool, org_id="org-task-epsilon")
        handler.get_task_by_id(task_id="task-999")

        call_args = mock_conn.execute.call_args
        params = call_args[0][1]
        assert params["org_id"] == "org-task-epsilon"

    def test_search_tasks_all_rooms_still_includes_org_id(self):
        """search_all_rooms=Trueでもorganization_idフィルターが含まれる"""
        mock_pool, mock_conn = _make_mock_pool()

        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result

        handler = self._make_handler(mock_pool, org_id="org-task-zeta")
        handler.search_tasks_from_db(room_id="room-123", search_all_rooms=True)

        call_args = mock_conn.execute.call_args
        params = call_args[0][1]

        # org_idフィルターは必ず存在する
        assert params["org_id"] == "org-task-zeta"
        # search_all_rooms=Trueなのでroom_idフィルターはない
        assert "room_id" not in params


# ================================================================
# TestApiOrgMismatch
# ================================================================


class TestApiOrgMismatch:
    """API endpoints: JWT org_idとパスorg_idの不一致で403を返すことを検証"""

    @pytest.fixture
    def org_client(self):
        """organizationsルーターのテストクライアント"""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.api.v1.organizations import router

        app = FastAPI()
        app.include_router(router, prefix="/api/v1")
        return TestClient(app)

    @patch("app.api.v1.organizations.get_db_pool")
    def test_sync_org_chart_mismatch_returns_403(self, mock_get_pool, org_client):
        """JWT org_id="org-AAA" でパス org_id="org-BBB" にアクセスすると403"""
        token = _make_token(user_id="u-test", org_id="org-AAA", role="admin")
        response = org_client.post(
            "/api/v1/organizations/org-BBB/sync-org-chart",
            json={
                "organization_id": "org-BBB",
                "sync_type": "full",
                "departments": [],
                "employees": [],
                "roles": [],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403
        data = response.json()
        assert data["detail"]["error_code"] == "ACCESS_DENIED"

    @patch("app.api.v1.organizations.get_db_pool")
    def test_get_departments_mismatch_returns_403(self, mock_get_pool, org_client):
        """JWT org_id="org-AAA" で別組織の部署一覧にアクセスすると403"""
        token = _make_token(user_id="u-test", org_id="org-AAA", role="member")
        response = org_client.get(
            "/api/v1/organizations/org-BBB/departments",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403

    @patch("app.api.v1.organizations.get_db_pool")
    def test_get_department_detail_mismatch_returns_403(self, mock_get_pool, org_client):
        """JWT org_id="org-AAA" で別組織の部署詳細にアクセスすると403"""
        token = _make_token(user_id="u-test", org_id="org-AAA", role="admin")
        response = org_client.get(
            "/api/v1/organizations/org-BBB/departments/dept-001",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403

    @patch("app.api.v1.organizations.get_db_pool")
    def test_matching_org_id_does_not_return_403(self, mock_get_pool, org_client):
        """JWT org_idとパスorg_idが一致すれば403にならない"""
        # DB接続モック
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result
        mock_get_pool.return_value = mock_pool

        token = _make_token(user_id="u-test", org_id="org-MATCH", role="member")
        response = org_client.get(
            "/api/v1/organizations/org-MATCH/departments",
            headers={"Authorization": f"Bearer {token}"},
        )
        # 403ではない（200であるべき）
        assert response.status_code != 403

    def test_no_jwt_returns_401(self, org_client):
        """JWT未指定で401を返す"""
        response = org_client.get("/api/v1/organizations/org-001/departments")
        assert response.status_code == 401


# ================================================================
# TestOrgIdValidation
# ================================================================


class TestOrgIdValidation:
    """サービスが空のorg_id文字列を拒否することを検証"""

    def test_person_service_rejects_empty_org_id(self):
        """PersonServiceは空のorganization_idで初期化できない"""
        from lib.person_service import PersonService

        with pytest.raises(ValueError, match="organization_id is required"):
            PersonService(
                get_pool=lambda: MagicMock(),
                organization_id="",
            )

    def test_person_service_rejects_default_empty_org_id(self):
        """PersonServiceはデフォルトの空org_idで初期化できない"""
        from lib.person_service import PersonService

        with pytest.raises(ValueError, match="organization_id is required"):
            PersonService(
                get_pool=lambda: MagicMock(),
            )

    def test_task_handler_rejects_empty_org_id(self):
        """TaskHandlerは空のorganization_idで初期化できない"""
        with pytest.raises(ValueError, match="organization_id is required"):
            TaskHandler(
                get_pool=lambda: MagicMock(),
                get_secret=lambda key: "dummy",
                call_chatwork_api_with_retry=MagicMock(),
                organization_id="",
            )

    def test_task_handler_rejects_default_empty_org_id(self):
        """TaskHandlerはデフォルトの空org_idで初期化できない"""
        with pytest.raises(ValueError, match="organization_id is required"):
            TaskHandler(
                get_pool=lambda: MagicMock(),
                get_secret=lambda key: "dummy",
                call_chatwork_api_with_retry=MagicMock(),
            )

    def test_org_chart_service_rejects_empty_org_id(self):
        """OrgChartServiceは空のorganization_idで初期化できない"""
        from lib.person_service import OrgChartService

        with pytest.raises(ValueError, match="organization_id is required"):
            OrgChartService(
                get_pool=lambda: MagicMock(),
                organization_id="",
            )

    def test_person_service_accepts_valid_org_id(self):
        """PersonServiceは有効なorganization_idで正常に初期化できる"""
        from lib.person_service import PersonService

        service = PersonService(
            get_pool=lambda: MagicMock(),
            organization_id="org-valid-001",
        )
        assert service.organization_id == "org-valid-001"

    def test_task_handler_accepts_valid_org_id(self):
        """TaskHandlerは有効なorganization_idで正常に初期化できる"""
        handler = TaskHandler(
            get_pool=lambda: MagicMock(),
            get_secret=lambda key: "dummy",
            call_chatwork_api_with_retry=MagicMock(),
            organization_id="org-valid-002",
        )
        assert handler.organization_id == "org-valid-002"
