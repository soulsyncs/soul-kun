"""
lib/db.py のRLS関連関数テスト

対象:
- set_organization_context
- get_db_session_with_org
"""

import pytest
from unittest.mock import MagicMock, patch, call
from sqlalchemy import text

from lib.db import (
    set_organization_context,
    set_organization_context_async,
    get_db_session_with_org,
)


# =============================================================================
# set_organization_context テスト
# =============================================================================


class TestSetOrganizationContext:
    """set_organization_context()のテスト"""

    def test_sets_organization_id(self):
        """organization_idを設定する"""
        mock_conn = MagicMock()
        org_id = "12345678-1234-1234-1234-123456789012"

        set_organization_context(mock_conn, org_id)

        # executeが呼ばれたことを確認
        mock_conn.execute.assert_called_once()
        # 引数を確認（TextClause と パラメータ）
        call_args = mock_conn.execute.call_args
        # 第2位置引数がパラメータdict
        params = call_args.args[1]
        assert params["org_id"] == org_id

    def test_raises_on_empty_org_id(self):
        """空のorganization_idでエラー"""
        mock_conn = MagicMock()

        with pytest.raises(ValueError) as exc_info:
            set_organization_context(mock_conn, "")

        assert "organization_id is required" in str(exc_info.value)

    def test_raises_on_none_org_id(self):
        """Noneのorganization_idでエラー"""
        mock_conn = MagicMock()

        with pytest.raises(ValueError) as exc_info:
            set_organization_context(mock_conn, None)

        assert "organization_id is required" in str(exc_info.value)


# =============================================================================
# set_organization_context_async テスト
# =============================================================================


class TestSetOrganizationContextAsync:
    """set_organization_context_async()のテスト"""

    @pytest.mark.asyncio
    async def test_sets_organization_id(self):
        """organization_idを設定する（非同期）"""
        from unittest.mock import AsyncMock

        mock_conn = MagicMock()
        mock_conn.execute = AsyncMock()

        org_id = "12345678-1234-1234-1234-123456789012"

        await set_organization_context_async(mock_conn, org_id)

        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args
        params = call_args.args[1]
        assert params["org_id"] == org_id

    @pytest.mark.asyncio
    async def test_raises_on_empty_org_id(self):
        """空のorganization_idでエラー（非同期）"""
        mock_conn = MagicMock()

        with pytest.raises(ValueError) as exc_info:
            await set_organization_context_async(mock_conn, "")

        assert "organization_id is required" in str(exc_info.value)


# =============================================================================
# get_db_session_with_org テスト
# =============================================================================


class TestGetDbSessionWithOrg:
    """get_db_session_with_org()のテスト"""

    @patch("lib.db.get_db_pool")
    def test_sets_org_context_and_yields_conn(self, mock_get_pool):
        """organization_idを設定してコネクションを返す"""
        mock_conn = MagicMock()
        mock_pool = MagicMock()
        mock_pool.connect.return_value = mock_conn
        mock_get_pool.return_value = mock_pool

        org_id = "12345678-1234-1234-1234-123456789012"

        with get_db_session_with_org(org_id) as conn:
            # コネクションが返される
            assert conn == mock_conn
            # SET文が実行される
            mock_conn.execute.assert_called_once()
            # パラメータを確認
            call_args = mock_conn.execute.call_args
            params = call_args.args[1]
            assert params["org_id"] == org_id

        # 終了時にcloseが呼ばれる
        mock_conn.close.assert_called_once()

    @patch("lib.db.get_db_pool")
    def test_closes_conn_on_exception(self, mock_get_pool):
        """例外時もコネクションをクローズする"""
        mock_conn = MagicMock()
        mock_pool = MagicMock()
        mock_pool.connect.return_value = mock_conn
        mock_get_pool.return_value = mock_pool

        org_id = "12345678-1234-1234-1234-123456789012"

        with pytest.raises(RuntimeError):
            with get_db_session_with_org(org_id) as conn:
                raise RuntimeError("Test error")

        # 例外時もcloseが呼ばれる
        mock_conn.close.assert_called_once()

    def test_raises_on_empty_org_id(self):
        """空のorganization_idでエラー"""
        with pytest.raises(ValueError) as exc_info:
            with get_db_session_with_org("") as conn:
                pass

        assert "organization_id is required" in str(exc_info.value)

    def test_raises_on_none_org_id(self):
        """Noneのorganization_idでエラー"""
        with pytest.raises(ValueError) as exc_info:
            with get_db_session_with_org(None) as conn:
                pass

        assert "organization_id is required" in str(exc_info.value)


# =============================================================================
# 統合テスト（RLSポリシーの検証用コメント）
# =============================================================================


class TestRLSIntegration:
    """RLS統合テスト用プレースホルダー

    実際のDB接続が必要なため、ステージング環境で実行。

    テストシナリオ:
    1. organization_id Aでデータを挿入
    2. organization_id Aでセッション開始 → データが見える
    3. organization_id Bでセッション開始 → データが見えない
    4. organization_id未設定でセッション開始 → データが見えない
    """

    @pytest.mark.skip(reason="ステージング環境で実行")
    def test_rls_isolates_data_by_organization(self):
        """RLSがorganization_idでデータを分離する"""
        # ステージング環境で実装
        pass

    @pytest.mark.skip(reason="ステージング環境で実行")
    def test_rls_blocks_without_org_context(self):
        """organization_id未設定だとデータが見えない"""
        # ステージング環境で実装
        pass
