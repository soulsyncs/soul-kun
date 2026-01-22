"""
テナントコンテキスト管理モジュール

マルチテナント環境でのテナント（organization）識別を管理。
Phase 4 の Row Level Security と連携。

使用例（Flask/Cloud Functions）:
    from lib.tenant import TenantContext, get_current_tenant

    # リクエストごとにテナントを設定
    with TenantContext("org_soulsyncs"):
        tenant_id = get_current_tenant()
        # このブロック内では org_soulsyncs がテナント

使用例（FastAPI）:
    from lib.tenant import TenantContext
    from fastapi import Depends, Header

    async def get_tenant(
        x_tenant_id: str = Header(..., alias="X-Tenant-ID")
    ):
        return x_tenant_id

    @app.get("/tasks")
    async def get_tasks(tenant_id: str = Depends(get_tenant)):
        with TenantContext(tenant_id):
            # テナントスコープ内の処理
            ...

Phase 4対応:
    - リクエストスコープでのテナント管理
    - スレッドセーフ / 非同期セーフ
    - DBコネクションへの自動テナント設定
"""

from contextvars import ContextVar
from contextlib import contextmanager
from typing import Optional
from dataclasses import dataclass


# コンテキスト変数（スレッド/非同期セーフ）
_current_tenant: ContextVar[Optional[str]] = ContextVar(
    "current_tenant", default=None
)


@dataclass
class TenantInfo:
    """テナント情報"""
    id: str
    name: Optional[str] = None
    plan: Optional[str] = None  # "starter", "standard", "professional"
    is_active: bool = True


class TenantContext:
    """
    テナントコンテキストマネージャー

    with ブロック内でテナントIDを設定し、ブロック終了時に元に戻す。
    スレッドセーフ・非同期セーフな実装。

    使用例:
        with TenantContext("org_customer1"):
            # このブロック内では org_customer1 がテナント
            tenant_id = get_current_tenant()
            print(tenant_id)  # "org_customer1"

        # ブロック外ではテナントは元に戻る
        print(get_current_tenant())  # None
    """

    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self._token = None

    def __enter__(self):
        self._token = _current_tenant.set(self.tenant_id)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        _current_tenant.reset(self._token)
        return False

    async def __aenter__(self):
        """非同期版 enter"""
        self._token = _current_tenant.set(self.tenant_id)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """非同期版 exit"""
        _current_tenant.reset(self._token)
        return False


def get_current_tenant() -> Optional[str]:
    """
    現在のテナントIDを取得

    Returns:
        テナントID（未設定の場合は None）

    使用例:
        tenant_id = get_current_tenant()
        if tenant_id:
            print(f"Current tenant: {tenant_id}")
        else:
            print("No tenant context")
    """
    return _current_tenant.get()


def set_current_tenant(tenant_id: Optional[str]) -> None:
    """
    テナントIDを設定

    注意: 通常は TenantContext を使用すること。
    この関数はリクエスト開始時の設定など、
    コンテキストマネージャーが使えない場合に使用。

    Args:
        tenant_id: テナントID（クリアする場合は None）
    """
    _current_tenant.set(tenant_id)


def require_tenant() -> str:
    """
    テナントIDを取得（必須）

    テナントが設定されていない場合は例外を送出。

    Returns:
        テナントID

    Raises:
        TenantNotSetError: テナントが設定されていない場合
    """
    tenant_id = get_current_tenant()
    if tenant_id is None:
        raise TenantNotSetError("Tenant context is not set")
    return tenant_id


@contextmanager
def tenant_scope(tenant_id: str):
    """
    テナントスコープのコンテキストマネージャー（関数版）

    TenantContext と同じ機能を関数として提供。

    使用例:
        with tenant_scope("org_customer1"):
            ...
    """
    token = _current_tenant.set(tenant_id)
    try:
        yield
    finally:
        _current_tenant.reset(token)


# =============================================================================
# Phase 4: テナントバリデーション
# =============================================================================

def validate_tenant_access(
    requested_tenant_id: str,
    user_tenant_id: str,
    allow_cross_tenant: bool = False,
) -> bool:
    """
    テナントアクセス権限を検証

    Args:
        requested_tenant_id: リクエストされたテナントID
        user_tenant_id: ユーザーが所属するテナントID
        allow_cross_tenant: クロステナントアクセスを許可するか

    Returns:
        True: アクセス許可
        False: アクセス拒否

    使用例:
        if not validate_tenant_access(request.tenant_id, user.tenant_id):
            raise HTTPException(403, "Tenant access denied")
    """
    if allow_cross_tenant:
        return True

    return requested_tenant_id == user_tenant_id


def get_tenant_filter(column_name: str = "organization_id") -> str:
    """
    SQLクエリ用のテナントフィルタ条件を生成

    Args:
        column_name: テナントIDカラム名

    Returns:
        WHERE句の条件文字列

    使用例:
        tenant_filter = get_tenant_filter()
        query = f"SELECT * FROM tasks WHERE {tenant_filter}"
        # → "SELECT * FROM tasks WHERE organization_id = :tenant_id"
    """
    return f"{column_name} = :tenant_id"


def get_tenant_params() -> dict:
    """
    SQLクエリ用のテナントパラメータを取得

    Returns:
        {"tenant_id": "org_xxx"}

    使用例:
        params = get_tenant_params()
        conn.execute(text(query), params)
    """
    return {"tenant_id": require_tenant()}


# =============================================================================
# 例外クラス
# =============================================================================

class TenantError(Exception):
    """テナント関連エラーの基底クラス"""
    pass


class TenantNotSetError(TenantError):
    """テナントが設定されていないエラー"""
    pass


class TenantAccessDeniedError(TenantError):
    """テナントへのアクセスが拒否されたエラー"""
    pass


# =============================================================================
# Phase 4: デフォルトテナント（社内用）
# =============================================================================

DEFAULT_TENANT_ID = "org_soulsyncs"


def get_default_tenant() -> str:
    """
    デフォルトテナントIDを取得

    Phase 3.5 までは社内専用のため、デフォルトテナントを使用。
    Phase 4 以降はリクエストからテナントを取得。

    Returns:
        デフォルトテナントID
    """
    return DEFAULT_TENANT_ID


def get_current_or_default_tenant() -> str:
    """
    現在のテナントID、または設定されていない場合はデフォルトを返す

    Phase 3.5 での移行期間に使用。

    Returns:
        テナントID
    """
    return get_current_tenant() or DEFAULT_TENANT_ID
