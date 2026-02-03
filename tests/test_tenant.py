"""
lib/tenant.py のテスト

マルチテナント管理モジュールのユニットテスト
"""

import pytest
from unittest.mock import patch, MagicMock

from lib.tenant import (
    TenantInfo,
    TenantContext,
    get_current_tenant,
    set_current_tenant,
    require_tenant,
    tenant_scope,
    validate_tenant_access,
    get_tenant_filter,
    get_tenant_params,
    get_default_tenant,
    get_current_or_default_tenant,
    TenantError,
    TenantNotSetError,
    TenantAccessDeniedError,
    DEFAULT_TENANT_ID,
)


class TestTenantInfo:
    """TenantInfo データクラスのテスト"""

    def test_create_with_id_only(self):
        """IDのみで作成"""
        info = TenantInfo(id="org_test")
        assert info.id == "org_test"
        assert info.name is None
        assert info.plan is None
        assert info.is_active is True

    def test_create_with_all_fields(self):
        """全フィールドで作成"""
        info = TenantInfo(
            id="org_test",
            name="テスト会社",
            plan="professional",
            is_active=True,
        )
        assert info.id == "org_test"
        assert info.name == "テスト会社"
        assert info.plan == "professional"
        assert info.is_active is True

    def test_inactive_tenant(self):
        """非アクティブテナント"""
        info = TenantInfo(id="org_old", is_active=False)
        assert info.is_active is False


class TestTenantContext:
    """TenantContext のテスト"""

    def test_context_manager_sets_tenant(self):
        """コンテキストマネージャーでテナント設定"""
        with TenantContext("org_test"):
            assert get_current_tenant() == "org_test"

    def test_context_manager_resets_tenant(self):
        """コンテキストマネージャー終了時にリセット"""
        set_current_tenant(None)  # 初期化

        with TenantContext("org_test"):
            assert get_current_tenant() == "org_test"

        # ブロック外ではNoneに戻る
        assert get_current_tenant() is None

    def test_nested_context_managers(self):
        """ネストしたコンテキストマネージャー"""
        with TenantContext("org_outer"):
            assert get_current_tenant() == "org_outer"

            with TenantContext("org_inner"):
                assert get_current_tenant() == "org_inner"

            # 内側のブロック終了後は外側に戻る
            assert get_current_tenant() == "org_outer"

    def test_context_manager_with_exception(self):
        """例外発生時もリセットされる"""
        set_current_tenant(None)

        try:
            with TenantContext("org_test"):
                assert get_current_tenant() == "org_test"
                raise ValueError("Test exception")
        except ValueError:
            pass

        # 例外後もリセットされる
        assert get_current_tenant() is None

    def test_context_manager_returns_self(self):
        """__enter__がselfを返す"""
        ctx = TenantContext("org_test")
        with ctx as result:
            assert result is ctx
            assert result.tenant_id == "org_test"


class TestTenantContextAsync:
    """TenantContext の非同期版テスト"""

    @pytest.mark.asyncio
    async def test_async_context_manager_sets_tenant(self):
        """非同期コンテキストマネージャーでテナント設定"""
        async with TenantContext("org_async"):
            assert get_current_tenant() == "org_async"

    @pytest.mark.asyncio
    async def test_async_context_manager_resets_tenant(self):
        """非同期コンテキストマネージャー終了時にリセット"""
        set_current_tenant(None)

        async with TenantContext("org_async"):
            assert get_current_tenant() == "org_async"

        assert get_current_tenant() is None

    @pytest.mark.asyncio
    async def test_async_nested_context_managers(self):
        """ネストした非同期コンテキストマネージャー"""
        async with TenantContext("org_outer"):
            assert get_current_tenant() == "org_outer"

            async with TenantContext("org_inner"):
                assert get_current_tenant() == "org_inner"

            assert get_current_tenant() == "org_outer"


class TestGetCurrentTenant:
    """get_current_tenant のテスト"""

    def test_returns_none_when_not_set(self):
        """未設定時はNoneを返す"""
        set_current_tenant(None)
        assert get_current_tenant() is None

    def test_returns_tenant_when_set(self):
        """設定時はテナントIDを返す"""
        set_current_tenant("org_test")
        assert get_current_tenant() == "org_test"
        set_current_tenant(None)  # クリーンアップ


class TestSetCurrentTenant:
    """set_current_tenant のテスト"""

    def test_set_tenant(self):
        """テナント設定"""
        set_current_tenant("org_new")
        assert get_current_tenant() == "org_new"
        set_current_tenant(None)

    def test_clear_tenant(self):
        """テナントクリア"""
        set_current_tenant("org_test")
        set_current_tenant(None)
        assert get_current_tenant() is None

    def test_overwrite_tenant(self):
        """テナント上書き"""
        set_current_tenant("org_old")
        set_current_tenant("org_new")
        assert get_current_tenant() == "org_new"
        set_current_tenant(None)


class TestRequireTenant:
    """require_tenant のテスト"""

    def test_returns_tenant_when_set(self):
        """設定時はテナントIDを返す"""
        with TenantContext("org_test"):
            assert require_tenant() == "org_test"

    def test_raises_when_not_set(self):
        """未設定時は例外を送出"""
        set_current_tenant(None)

        with pytest.raises(TenantNotSetError) as exc_info:
            require_tenant()

        assert "Tenant context is not set" in str(exc_info.value)


class TestTenantScope:
    """tenant_scope のテスト"""

    def test_sets_tenant_in_scope(self):
        """スコープ内でテナント設定"""
        with tenant_scope("org_scope"):
            assert get_current_tenant() == "org_scope"

    def test_resets_tenant_after_scope(self):
        """スコープ終了後にリセット"""
        set_current_tenant(None)

        with tenant_scope("org_scope"):
            assert get_current_tenant() == "org_scope"

        assert get_current_tenant() is None

    def test_resets_on_exception(self):
        """例外発生時もリセット"""
        set_current_tenant(None)

        try:
            with tenant_scope("org_scope"):
                raise ValueError("Test")
        except ValueError:
            pass

        assert get_current_tenant() is None


class TestValidateTenantAccess:
    """validate_tenant_access のテスト"""

    def test_same_tenant_allowed(self):
        """同一テナントはアクセス許可"""
        assert validate_tenant_access("org_a", "org_a") is True

    def test_different_tenant_denied(self):
        """異なるテナントはアクセス拒否"""
        assert validate_tenant_access("org_a", "org_b") is False

    def test_cross_tenant_allowed_when_flag_set(self):
        """クロステナントフラグ有効時は許可"""
        assert validate_tenant_access("org_a", "org_b", allow_cross_tenant=True) is True

    def test_same_tenant_with_cross_flag(self):
        """同一テナント+クロステナントフラグ"""
        assert validate_tenant_access("org_a", "org_a", allow_cross_tenant=True) is True


class TestGetTenantFilter:
    """get_tenant_filter のテスト"""

    def test_default_column_name(self):
        """デフォルトカラム名"""
        result = get_tenant_filter()
        assert result == "organization_id = :tenant_id"

    def test_custom_column_name(self):
        """カスタムカラム名"""
        result = get_tenant_filter("tenant_id")
        assert result == "tenant_id = :tenant_id"

    def test_another_column_name(self):
        """別のカラム名"""
        result = get_tenant_filter("org_id")
        assert result == "org_id = :tenant_id"


class TestGetTenantParams:
    """get_tenant_params のテスト"""

    def test_returns_params_dict(self):
        """パラメータ辞書を返す"""
        with TenantContext("org_test"):
            params = get_tenant_params()
            assert params == {"tenant_id": "org_test"}

    def test_raises_when_no_tenant(self):
        """テナント未設定時は例外"""
        set_current_tenant(None)

        with pytest.raises(TenantNotSetError):
            get_tenant_params()


class TestGetDefaultTenant:
    """get_default_tenant のテスト"""

    def test_returns_default_tenant(self):
        """デフォルトテナントIDを返す"""
        assert get_default_tenant() == DEFAULT_TENANT_ID
        assert get_default_tenant() == "org_soulsyncs"


class TestGetCurrentOrDefaultTenant:
    """get_current_or_default_tenant のテスト"""

    def test_returns_current_when_set(self):
        """設定時は現在のテナントを返す"""
        with TenantContext("org_custom"):
            assert get_current_or_default_tenant() == "org_custom"

    def test_returns_default_when_not_set(self):
        """未設定時はデフォルトを返す"""
        set_current_tenant(None)
        assert get_current_or_default_tenant() == DEFAULT_TENANT_ID


class TestTenantExceptions:
    """テナント例外クラスのテスト"""

    def test_tenant_error_is_exception(self):
        """TenantErrorはExceptionを継承"""
        assert issubclass(TenantError, Exception)

    def test_tenant_not_set_error_is_tenant_error(self):
        """TenantNotSetErrorはTenantErrorを継承"""
        assert issubclass(TenantNotSetError, TenantError)

    def test_tenant_access_denied_error_is_tenant_error(self):
        """TenantAccessDeniedErrorはTenantErrorを継承"""
        assert issubclass(TenantAccessDeniedError, TenantError)

    def test_can_raise_tenant_not_set_error(self):
        """TenantNotSetErrorを送出できる"""
        with pytest.raises(TenantNotSetError):
            raise TenantNotSetError("Test message")

    def test_can_raise_tenant_access_denied_error(self):
        """TenantAccessDeniedErrorを送出できる"""
        with pytest.raises(TenantAccessDeniedError):
            raise TenantAccessDeniedError("Access denied")


class TestThreadSafety:
    """スレッドセーフティのテスト"""

    def test_context_var_isolation(self):
        """ContextVarの分離"""
        import threading
        results = {}

        def thread_func(tenant_id, thread_name):
            with TenantContext(tenant_id):
                results[thread_name] = get_current_tenant()

        t1 = threading.Thread(target=thread_func, args=("org_1", "thread1"))
        t2 = threading.Thread(target=thread_func, args=("org_2", "thread2"))

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # 各スレッドで独立したテナントが設定される
        assert results.get("thread1") == "org_1"
        assert results.get("thread2") == "org_2"
