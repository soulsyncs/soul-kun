"""
lib/user_utils.py のテスト

カバレッジ: 0% → 目標100%
"""

import pytest
from unittest.mock import MagicMock, patch

from lib.user_utils import get_user_primary_department


class TestGetUserPrimaryDepartment:
    """get_user_primary_department関数のテスト"""

    def test_returns_department_id_when_found(self):
        """ユーザーの主所属部署が見つかった場合、部署IDを返す"""
        # モックプールとコネクションを作成
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_result = MagicMock()

        # 部署IDを返すようモック
        mock_result.fetchone.return_value = ("dept-uuid-123",)
        mock_conn.execute.return_value = mock_result
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)

        result = get_user_primary_department(mock_pool, "12345678")

        assert result == "dept-uuid-123"
        mock_conn.execute.assert_called_once()

    def test_returns_none_when_user_not_found(self):
        """ユーザーが見つからない場合、Noneを返す"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_result = MagicMock()

        # fetchoneがNoneを返す（ユーザー未登録）
        mock_result.fetchone.return_value = None
        mock_conn.execute.return_value = mock_result
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)

        result = get_user_primary_department(mock_pool, "99999999")

        assert result is None

    def test_returns_none_when_department_is_null(self):
        """部署IDがNULLの場合、Noneを返す"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_result = MagicMock()

        # 行は返すが、部署IDがNone
        mock_result.fetchone.return_value = (None,)
        mock_conn.execute.return_value = mock_result
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)

        result = get_user_primary_department(mock_pool, "12345678")

        assert result is None

    def test_returns_none_on_exception(self):
        """DB例外が発生した場合、Noneを返す（例外をスローしない）"""
        mock_pool = MagicMock()

        # connect()で例外を発生させる
        mock_pool.connect.side_effect = Exception("DB接続エラー")

        result = get_user_primary_department(mock_pool, "12345678")

        assert result is None

    def test_accepts_integer_account_id(self):
        """アカウントIDが整数でも動作する"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_result = MagicMock()

        mock_result.fetchone.return_value = ("dept-uuid-456",)
        mock_conn.execute.return_value = mock_result
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)

        # 整数でも動作することを確認
        result = get_user_primary_department(mock_pool, 12345678)

        assert result == "dept-uuid-456"

    def test_converts_uuid_to_string(self):
        """UUIDオブジェクトが返された場合も文字列に変換する"""
        from uuid import UUID

        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_result = MagicMock()

        # UUIDオブジェクトを返す
        uuid_obj = UUID("12345678-1234-5678-1234-567812345678")
        mock_result.fetchone.return_value = (uuid_obj,)
        mock_conn.execute.return_value = mock_result
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)

        result = get_user_primary_department(mock_pool, "12345678")

        assert result == "12345678-1234-5678-1234-567812345678"
        assert isinstance(result, str)
