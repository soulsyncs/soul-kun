"""
Admin Drive Routes テスト

drive_routes.py のバリデーション・権限・エラー処理ロジックをテストする。
importlib.util.spec_from_file_location で __init__.py チェーンを回避して直接ロード。

テスト対象:
- フィルタなし一覧取得
- classification フィルタ / 不正値 → 400
- キーワードフィルタ
- ページング
- 同期状態集計値
- ダウンロード 404（ファイル不在 / drive_file_id=NULL）
- アップロード 拡張子不正 → 400 / サイズ超過 → 413 / 不正 classification → 400
- _escape_like ユニットテスト
"""

import sys
import os
import uuid
import importlib.util
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

# ──────────────────────────────────────────────────────────────
# プロジェクトルートをパスに追加（conftest.py と同じ）
# ──────────────────────────────────────────────────────────────
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_API_DIR = os.path.join(_ROOT, "api")
for _p in [_ROOT, _API_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ──────────────────────────────────────────────────────────────
# 共通 sys.modules スタブ（importlib.util ロード前に注入）
# ──────────────────────────────────────────────────────────────

def _install_stubs():
    """重量依存モジュールを MagicMock で差し替える。"""
    _logging_mock = MagicMock()
    _logging_mock.get_logger.return_value = MagicMock()
    _logging_mock.log_audit_event = MagicMock()

    stubs = {
        # HTTP / DB
        "httpx": MagicMock(),
        "httpcore": MagicMock(),
        "pg8000": MagicMock(),
        "pg8000.native": MagicMock(),
        "sqlalchemy": MagicMock(),
        "sqlalchemy.orm": MagicMock(),
        "sqlalchemy.pool": MagicMock(),
        "sqlalchemy.engine": MagicMock(),
        # Google
        "google": MagicMock(),
        "google.auth": MagicMock(),
        "google.auth.transport": MagicMock(),
        "google.auth.transport.requests": MagicMock(),
        "google.cloud": MagicMock(),
        "google.cloud.secretmanager": MagicMock(),
        "google.oauth2": MagicMock(),
        "google.oauth2.service_account": MagicMock(),
        "googleapiclient": MagicMock(),
        "googleapiclient.discovery": MagicMock(),
        "googleapiclient.http": MagicMock(),
        # Others
        "pinecone": MagicMock(),
        "openai": MagicMock(),
        "slowapi": MagicMock(),
        "slowapi.util": MagicMock(),
        "slowapi.errors": MagicMock(),
        # Internal libs (heavy)
        "lib.chatwork": MagicMock(),
        "lib.brain": MagicMock(),
        "lib.brain.constants": MagicMock(),
        "lib.brain.models": MagicMock(),
        "lib.text_utils": MagicMock(),
        # Internal app mocks
        "app.limiter": MagicMock(),
        "app.deps.auth": MagicMock(),
        "app.services.access_control": MagicMock(),
        "app.services.knowledge_search": MagicMock(),
        # lib.logging
        "lib.logging": _logging_mock,
    }
    for name, mock in stubs.items():
        sys.modules.setdefault(name, mock)

    return _logging_mock


_LOGGING_MOCK = _install_stubs()


# lib.db モックに get_db_pool を設定
_db_mock = MagicMock()
sys.modules.setdefault("lib.db", _db_mock)

# ──────────────────────────────────────────────────────────────
# 相対インポートのために api.app.api.v1.admin パッケージ階層を構築
# ──────────────────────────────────────────────────────────────

def _build_package_hierarchy():
    """
    drive_routes.py の `from .deps import ...` を解決するために、
    親パッケージ階層を sys.modules に登録する。
    """
    import types

    # 各パッケージ段階をダミーパッケージとして登録
    for pkg_name in [
        "api", "api.app", "api.app.api", "api.app.api.v1", "api.app.api.v1.admin",
        "app", "app.schemas",
    ]:
        if pkg_name not in sys.modules:
            pkg = types.ModuleType(pkg_name)
            pkg.__path__ = [os.path.join(_API_DIR, *pkg_name.replace("api.", "").split("."))]
            pkg.__package__ = pkg_name
            sys.modules[pkg_name] = pkg

    # deps.py を api.app.api.v1.admin.deps として登録
    deps_path = os.path.join(_ROOT, "api/app/api/v1/admin/deps.py")
    deps_spec = importlib.util.spec_from_file_location(
        "api.app.api.v1.admin.deps", deps_path,
        submodule_search_locations=[],
    )
    deps_mod = importlib.util.module_from_spec(deps_spec)
    deps_mod.__package__ = "api.app.api.v1.admin"
    sys.modules["api.app.api.v1.admin.deps"] = deps_mod
    deps_spec.loader.exec_module(deps_mod)

    # schemas/admin.py を app.schemas.admin として登録
    schemas_path = os.path.join(_ROOT, "api/app/schemas/admin.py")
    schemas_spec = importlib.util.spec_from_file_location(
        "app.schemas.admin", schemas_path,
        submodule_search_locations=[],
    )
    schemas_mod = importlib.util.module_from_spec(schemas_spec)
    schemas_mod.__package__ = "app.schemas"
    sys.modules["app.schemas.admin"] = schemas_mod
    schemas_spec.loader.exec_module(schemas_mod)

    # drive_routes.py を api.app.api.v1.admin.drive_routes として登録
    dr_path = os.path.join(_ROOT, "api/app/api/v1/admin/drive_routes.py")
    dr_spec = importlib.util.spec_from_file_location(
        "api.app.api.v1.admin.drive_routes", dr_path,
        submodule_search_locations=[],
    )
    dr_mod = importlib.util.module_from_spec(dr_spec)
    dr_mod.__package__ = "api.app.api.v1.admin"
    sys.modules["api.app.api.v1.admin.drive_routes"] = dr_mod
    dr_spec.loader.exec_module(dr_mod)

    return deps_mod, dr_mod


_deps, _drive_mod = _build_package_hierarchy()


# ──────────────────────────────────────────────────────────────
# 補助型・ファクトリ
# ──────────────────────────────────────────────────────────────

class MockUser:
    def __init__(self, role_level: int = 6):
        self.user_id = str(uuid.uuid4())
        self.organization_id = "5f98365f-e7c5-4f48-9918-7fe9aabae5df"
        self.role_level = role_level


def _make_pool(fetchall_rows=None, count_val=0):
    pool = MagicMock()
    conn = MagicMock()
    pool.connect.return_value.__enter__ = MagicMock(return_value=conn)
    pool.connect.return_value.__exit__ = MagicMock(return_value=None)

    count_row = MagicMock()
    count_row.__getitem__ = lambda self, i: count_val
    conn.execute.return_value.fetchone.return_value = count_row
    conn.execute.return_value.fetchall.return_value = fetchall_rows or []
    return pool, conn


def _drive_row(**kwargs):
    defaults = dict(
        doc_id=None, title="テスト資料", file_name="test.pdf",
        file_type="pdf", file_size_bytes=1024, classification="internal",
        category=None, drive_file_id="drive-file-001",
        web_view_link="https://docs.google.com/file/001",
        last_modified=None, processing_status="completed", updated_at=None,
    )
    defaults.update(kwargs)
    return (
        defaults["doc_id"] or str(uuid.uuid4()),
        defaults["title"], defaults["file_name"], defaults["file_type"],
        defaults["file_size_bytes"], defaults["classification"], defaults["category"],
        defaults["drive_file_id"], defaults["web_view_link"],
        str(defaults["last_modified"] or datetime(2026, 2, 21, tzinfo=timezone.utc)),
        defaults["processing_status"],
        str(defaults["updated_at"] or datetime(2026, 2, 21, tzinfo=timezone.utc)),
    )


# ──────────────────────────────────────────────────────────────
# ファイル一覧テスト
# ──────────────────────────────────────────────────────────────

class TestGetDriveFiles:
    """GET /admin/drive/files"""

    def _run(self, pool, **kwargs):
        import asyncio
        # FastAPI Query()デフォルトを直接呼び出し時に正しく渡すため、
        # 未指定パラメータはNone/デフォルト値を明示する
        defaults = dict(q=None, classification=None, department_id=None, page=1, per_page=20)
        defaults.update(kwargs)
        user = defaults.pop("user", MockUser())
        with patch.object(_drive_mod, "get_db_pool", return_value=pool):
            return asyncio.run(
                _drive_mod.get_drive_files(user=user, **defaults)
            )

    def test_no_filter_returns_files(self):
        """フィルタなしでファイル一覧が返る"""
        pool, _ = _make_pool(fetchall_rows=[_drive_row()], count_val=1)
        result = self._run(pool)
        assert result.status == "success"
        assert result.total == 1
        assert len(result.files) == 1
        assert result.files[0].file_name == "test.pdf"

    def test_invalid_classification_raises_400(self):
        """不正な classification は 400"""
        from fastapi import HTTPException
        pool, _ = _make_pool()
        with pytest.raises(HTTPException) as exc:
            self._run(pool, classification="invalid_value")
        assert exc.value.status_code == 400

    def test_classification_filter_passes_param(self):
        """classification フィルタが SQL パラメータに渡される"""
        row = _drive_row(classification="confidential")
        pool, conn = _make_pool(fetchall_rows=[row], count_val=1)
        result = self._run(pool, classification="confidential")
        assert result.status == "success"
        call_args = [str(c) for c in conn.execute.call_args_list]
        assert any("confidential" in c for c in call_args)

    def test_keyword_filter(self):
        """キーワード検索"""
        pool, _ = _make_pool(fetchall_rows=[_drive_row(title="営業マニュアル")], count_val=1)
        result = self._run(pool, q="営業")
        assert result.status == "success"
        assert len(result.files) == 1

    def test_pagination(self):
        """ページング: page=2, per_page=5"""
        rows = [_drive_row(title=f"ファイル{i}") for i in range(5)]
        pool, _ = _make_pool(fetchall_rows=rows, count_val=25)
        result = self._run(pool, page=2, per_page=5)
        assert result.page == 2
        assert result.per_page == 5
        assert result.total == 25

    def test_empty_result(self):
        """ファイルなしは空リスト"""
        pool, _ = _make_pool(fetchall_rows=[], count_val=0)
        result = self._run(pool)
        assert result.status == "success"
        assert result.total == 0
        assert result.files == []


# ──────────────────────────────────────────────────────────────
# 同期状態テスト
# ──────────────────────────────────────────────────────────────

class TestGetDriveSyncStatus:
    """GET /admin/drive/sync-status"""

    def _run(self, conn_setup):
        import asyncio
        pool = MagicMock()
        conn = MagicMock()
        pool.connect.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connect.return_value.__exit__ = MagicMock(return_value=None)
        conn_setup(conn)
        with patch.object(_drive_mod, "get_db_pool", return_value=pool):
            return asyncio.run(
                _drive_mod.get_drive_sync_status(user=MockUser())
            )

    def test_returns_aggregates(self):
        """集計値が正しく返る"""
        def setup(conn):
            row = MagicMock()
            row.__getitem__ = lambda self, i: {0: 42, 1: "2026-02-21T00:00:00+00:00", 2: 3}[i]
            conn.execute.return_value.fetchone.return_value = row

        result = self._run(setup)
        assert result.status == "success"
        assert result.total_files == 42
        assert result.failed_count == 3
        assert result.last_synced_at is not None

    def test_no_rows_returns_defaults(self):
        """DB 0件の場合はデフォルト値"""
        def setup(conn):
            conn.execute.return_value.fetchone.return_value = None

        result = self._run(setup)
        assert result.status == "success"
        assert result.total_files == 0
        assert result.failed_count == 0
        assert result.last_synced_at is None


# ──────────────────────────────────────────────────────────────
# ダウンロードテスト
# ──────────────────────────────────────────────────────────────

class TestDownloadDriveFile:
    """GET /admin/drive/files/{document_id}/download"""

    def _run(self, conn_setup, doc_id=None):
        import asyncio
        pool = MagicMock()
        conn = MagicMock()
        pool.connect.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connect.return_value.__exit__ = MagicMock(return_value=None)
        conn_setup(conn)
        with patch.object(_drive_mod, "get_db_pool", return_value=pool):
            return asyncio.run(
                _drive_mod.download_drive_file(
                    document_id=doc_id or str(uuid.uuid4()),
                    user=MockUser(),
                )
            )

    def test_not_found_raises_404(self):
        """DBに存在しないドキュメントは 404"""
        from fastapi import HTTPException

        def setup(conn):
            conn.execute.return_value.fetchone.return_value = None

        with pytest.raises(HTTPException) as exc:
            self._run(setup)
        assert exc.value.status_code == 404

    def test_no_drive_file_id_raises_404(self):
        """google_drive_file_id が NULL なら 404"""
        from fastapi import HTTPException

        def setup(conn):
            row = MagicMock()
            row.__getitem__ = lambda self, i: {0: None, 1: "test.pdf", 2: "pdf"}[i]
            conn.execute.return_value.fetchone.return_value = row

        with pytest.raises(HTTPException) as exc:
            self._run(setup)
        assert exc.value.status_code == 404


# ──────────────────────────────────────────────────────────────
# アップロードバリデーションテスト
# ──────────────────────────────────────────────────────────────

class TestUploadDriveFileValidation:
    """POST /admin/drive/upload — Drive API不要のバリデーション部分"""

    def _run(self, file_name, content_type, content, classification, role_level=6):
        import asyncio
        from fastapi import UploadFile

        mock_file = MagicMock(spec=UploadFile)
        mock_file.filename = file_name
        mock_file.content_type = content_type
        mock_file.read = AsyncMock(return_value=content)

        return asyncio.run(
            _drive_mod.upload_drive_file(
                file=mock_file,
                classification=classification,
                user=MockUser(role_level=role_level),
            )
        )

    def test_invalid_extension_raises_400(self):
        """許可されていない拡張子は 400"""
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            self._run("malware.exe", "application/octet-stream", b"x" * 100, "internal")
        assert exc.value.status_code == 400

    def test_too_large_raises_413(self):
        """21MB 超は 413"""
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            self._run("big.pdf", "application/pdf", b"x" * (21 * 1024 * 1024), "internal")
        assert exc.value.status_code == 413

    def test_invalid_classification_raises_400(self):
        """不正な classification は 400"""
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            self._run("doc.pdf", "application/pdf", b"data", "bad_value")
        assert exc.value.status_code == 400

    def test_no_extension_raises_400(self):
        """拡張子なしのファイル名は 400"""
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            self._run("nodot", "application/pdf", b"data", "internal")
        assert exc.value.status_code == 400


# ──────────────────────────────────────────────────────────────
# _escape_like ユニットテスト
# ──────────────────────────────────────────────────────────────

class TestEscapeLike:
    """deps._escape_like の純粋関数テスト"""

    @pytest.fixture(autouse=True)
    def _setup(self):
        self.fn = _deps._escape_like

    def test_escapes_percent(self):
        assert self.fn("100%") == r"100\%"

    def test_escapes_underscore(self):
        assert self.fn("file_name") == r"file\_name"

    def test_escapes_backslash(self):
        assert self.fn(r"path\dir") == r"path\\dir"

    def test_no_special_chars(self):
        assert self.fn("normal") == "normal"

    def test_empty_string(self):
        assert self.fn("") == ""
