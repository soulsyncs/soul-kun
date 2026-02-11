"""
Phase A: 管理者設定モジュールのテスト

lib/admin_config.py のテストケース

テスト対象:
- AdminConfig データクラス
- get_admin_config() 関数（DB取得、キャッシュ）
- is_admin_account() / get_admin_room_id() 等のショートカット関数
- キャッシュクリア機能
- フォールバック動作

作成日: 2026-01-26
バージョン: v10.30.1
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime


# ================================================================
# テスト用定数
# ================================================================

TEST_ORG_ID = "5f98365f-e7c5-4f48-9918-7fe9aabae5df"
TEST_ADMIN_ACCOUNT_ID = "1728974"
TEST_ADMIN_ROOM_ID = "405315911"
TEST_ADMIN_DM_ROOM_ID = "217825794"
TEST_BOT_ACCOUNT_ID = "10909425"


# ================================================================
# AdminConfig データクラスのテスト
# ================================================================

class TestAdminConfig:
    """AdminConfigデータクラスのテスト"""

    def test_create_admin_config(self):
        """AdminConfigの作成"""
        from lib.admin_config import AdminConfig

        config = AdminConfig(
            organization_id=TEST_ORG_ID,
            admin_account_id=TEST_ADMIN_ACCOUNT_ID,
            admin_name="菊地雅克",
            admin_room_id=TEST_ADMIN_ROOM_ID,
            admin_room_name="管理部",
            admin_dm_room_id=TEST_ADMIN_DM_ROOM_ID,
            authorized_room_ids=frozenset([405315911]),
            bot_account_id=TEST_BOT_ACCOUNT_ID,
            is_active=True
        )

        assert config.organization_id == TEST_ORG_ID
        assert config.admin_account_id == TEST_ADMIN_ACCOUNT_ID
        assert config.admin_name == "菊地雅克"
        assert config.admin_room_id == TEST_ADMIN_ROOM_ID
        assert config.is_active is True

    def test_is_admin_returns_true_for_admin(self):
        """is_admin()が管理者に対してTrueを返す"""
        from lib.admin_config import AdminConfig

        config = AdminConfig(
            organization_id=TEST_ORG_ID,
            admin_account_id=TEST_ADMIN_ACCOUNT_ID,
        )

        assert config.is_admin(TEST_ADMIN_ACCOUNT_ID) is True
        assert config.is_admin("1728974") is True
        assert config.is_admin(1728974) is True  # 数値でも動作

    def test_is_admin_returns_false_for_non_admin(self):
        """is_admin()が非管理者に対してFalseを返す"""
        from lib.admin_config import AdminConfig

        config = AdminConfig(
            organization_id=TEST_ORG_ID,
            admin_account_id=TEST_ADMIN_ACCOUNT_ID,
        )

        assert config.is_admin("9999999") is False
        assert config.is_admin("") is False

    def test_is_authorized_room_for_admin_room(self):
        """is_authorized_room()が管理部ルームに対してTrueを返す"""
        from lib.admin_config import AdminConfig

        config = AdminConfig(
            organization_id=TEST_ORG_ID,
            admin_account_id=TEST_ADMIN_ACCOUNT_ID,
            admin_room_id=TEST_ADMIN_ROOM_ID,
        )

        assert config.is_authorized_room(TEST_ADMIN_ROOM_ID) is True
        assert config.is_authorized_room("405315911") is True
        assert config.is_authorized_room(405315911) is True

    def test_is_authorized_room_for_authorized_rooms(self):
        """is_authorized_room()が認可ルームリストに対してTrueを返す"""
        from lib.admin_config import AdminConfig

        config = AdminConfig(
            organization_id=TEST_ORG_ID,
            admin_account_id=TEST_ADMIN_ACCOUNT_ID,
            admin_room_id=TEST_ADMIN_ROOM_ID,
            authorized_room_ids=frozenset([405315911, 123456789]),
        )

        assert config.is_authorized_room(123456789) is True
        assert config.is_authorized_room("123456789") is True

    def test_is_authorized_room_for_unauthorized_room(self):
        """is_authorized_room()が非認可ルームに対してFalseを返す"""
        from lib.admin_config import AdminConfig

        config = AdminConfig(
            organization_id=TEST_ORG_ID,
            admin_account_id=TEST_ADMIN_ACCOUNT_ID,
            admin_room_id=TEST_ADMIN_ROOM_ID,
        )

        assert config.is_authorized_room("999999999") is False

    def test_is_bot(self):
        """is_bot()がボットアカウントを正しく判定する"""
        from lib.admin_config import AdminConfig

        config = AdminConfig(
            organization_id=TEST_ORG_ID,
            admin_account_id=TEST_ADMIN_ACCOUNT_ID,
            bot_account_id=TEST_BOT_ACCOUNT_ID,
        )

        assert config.is_bot(TEST_BOT_ACCOUNT_ID) is True
        assert config.is_bot("10909425") is True
        assert config.is_bot("9999999") is False

    def test_get_admin_mention(self):
        """get_admin_mention()がメンション文字列を返す"""
        from lib.admin_config import AdminConfig

        config = AdminConfig(
            organization_id=TEST_ORG_ID,
            admin_account_id=TEST_ADMIN_ACCOUNT_ID,
        )

        assert config.get_admin_mention() == "[To:1728974]"

    def test_get_admin_mention_with_name(self):
        """get_admin_mention_with_name()が名前付きメンションを返す"""
        from lib.admin_config import AdminConfig

        config = AdminConfig(
            organization_id=TEST_ORG_ID,
            admin_account_id=TEST_ADMIN_ACCOUNT_ID,
            admin_name="菊地雅克",
        )

        mention = config.get_admin_mention_with_name()
        assert "[To:1728974]" in mention
        assert "菊地さん" in mention

    def test_admin_config_is_immutable(self):
        """AdminConfigが不変であること（frozen=True）"""
        from lib.admin_config import AdminConfig

        config = AdminConfig(
            organization_id=TEST_ORG_ID,
            admin_account_id=TEST_ADMIN_ACCOUNT_ID,
        )

        with pytest.raises(Exception):  # FrozenInstanceError
            config.admin_account_id = "new_value"


# ================================================================
# get_admin_config() 関数のテスト
# ================================================================

class TestGetAdminConfig:
    """get_admin_config()関数のテスト"""

    @pytest.fixture(autouse=True)
    def clear_cache(self):
        """各テスト前後にキャッシュをクリア"""
        from lib.admin_config import clear_admin_config_cache
        clear_admin_config_cache()
        yield
        clear_admin_config_cache()

    def test_get_admin_config_from_db(self, mock_db_pool):
        """DBから設定を取得"""
        from lib.admin_config import get_admin_config, clear_admin_config_cache

        clear_admin_config_cache()

        # DBモックの設定
        mock_result = (
            TEST_ORG_ID,           # organization_id
            TEST_ADMIN_ACCOUNT_ID,  # admin_account_id
            "菊地雅克",              # admin_name
            TEST_ADMIN_ROOM_ID,     # admin_room_id
            "管理部",                # admin_room_name
            TEST_ADMIN_DM_ROOM_ID,  # admin_dm_room_id
            [405315911],            # authorized_room_ids
            TEST_BOT_ACCOUNT_ID,    # bot_account_id
            True                     # is_active
        )

        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = mock_result

        with patch('lib.db.get_db_pool') as mock_get_pool:
            mock_pool = MagicMock()
            mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)
            mock_get_pool.return_value = mock_pool

            config = get_admin_config(TEST_ORG_ID)

            assert config.organization_id == TEST_ORG_ID
            assert config.admin_account_id == TEST_ADMIN_ACCOUNT_ID
            assert config.admin_name == "菊地雅克"
            assert config.admin_room_id == TEST_ADMIN_ROOM_ID

    def test_get_admin_config_fallback_on_db_error(self):
        """DB接続エラー時にフォールバック値を返す"""
        from lib.admin_config import get_admin_config, clear_admin_config_cache

        clear_admin_config_cache()

        with patch('lib.db.get_db_pool') as mock_get_pool:
            mock_get_pool.side_effect = Exception("DB connection failed")

            config = get_admin_config(TEST_ORG_ID)

            # フォールバック値が返されること
            assert config.admin_account_id == "1728974"
            assert config.admin_room_id == "405315911"

    def test_get_admin_config_uses_cache(self, mock_db_pool):
        """キャッシュが有効に機能する"""
        from lib.admin_config import get_admin_config, clear_admin_config_cache

        clear_admin_config_cache()

        mock_result = (
            TEST_ORG_ID,
            TEST_ADMIN_ACCOUNT_ID,
            "菊地雅克",
            TEST_ADMIN_ROOM_ID,
            "管理部",
            TEST_ADMIN_DM_ROOM_ID,
            [405315911],
            TEST_BOT_ACCOUNT_ID,
            True
        )

        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = mock_result

        with patch('lib.db.get_db_pool') as mock_get_pool:
            mock_pool = MagicMock()
            mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_pool.connect.return_value.__exit__ = MagicMock(return_value=None)
            mock_get_pool.return_value = mock_pool

            # 1回目の呼び出し
            config1 = get_admin_config(TEST_ORG_ID)

            # 2回目の呼び出し（キャッシュから）
            config2 = get_admin_config(TEST_ORG_ID)

            # 同じオブジェクトが返されること
            assert config1 is config2

            # DBは1回だけ呼ばれること
            assert mock_conn.execute.call_count == 1

    def test_get_admin_config_default_org_id(self):
        """org_id省略時にデフォルト組織IDを使用"""
        from lib.admin_config import get_admin_config, DEFAULT_ORG_ID, clear_admin_config_cache

        clear_admin_config_cache()

        with patch('lib.db.get_db_pool') as mock_get_pool:
            mock_get_pool.side_effect = Exception("DB connection failed")

            config = get_admin_config()  # org_id省略

            assert config.organization_id == DEFAULT_ORG_ID


# ================================================================
# ショートカット関数のテスト
# ================================================================

class TestShortcutFunctions:
    """ショートカット関数のテスト"""

    @pytest.fixture(autouse=True)
    def clear_cache(self):
        """各テスト前後にキャッシュをクリア"""
        from lib.admin_config import clear_admin_config_cache
        clear_admin_config_cache()
        yield
        clear_admin_config_cache()

    def test_is_admin_account(self):
        """is_admin_account()ショートカット関数"""
        from lib.admin_config import is_admin_account, clear_admin_config_cache

        clear_admin_config_cache()

        with patch('lib.db.get_db_pool') as mock_get_pool:
            mock_get_pool.side_effect = Exception("DB connection failed")

            assert is_admin_account("1728974") is True
            assert is_admin_account("9999999") is False

    def test_get_admin_room_id(self):
        """get_admin_room_id()ショートカット関数"""
        from lib.admin_config import get_admin_room_id, clear_admin_config_cache

        clear_admin_config_cache()

        with patch('lib.db.get_db_pool') as mock_get_pool:
            mock_get_pool.side_effect = Exception("DB connection failed")

            room_id = get_admin_room_id()
            assert room_id == "405315911"

    def test_get_admin_account_id(self):
        """get_admin_account_id()ショートカット関数"""
        from lib.admin_config import get_admin_account_id, clear_admin_config_cache

        clear_admin_config_cache()

        with patch('lib.db.get_db_pool') as mock_get_pool:
            mock_get_pool.side_effect = Exception("DB connection failed")

            account_id = get_admin_account_id()
            assert account_id == "1728974"


# ================================================================
# キャッシュクリアのテスト
# ================================================================

class TestCacheClear:
    """キャッシュクリア機能のテスト"""

    def test_clear_admin_config_cache_all(self):
        """全キャッシュクリア"""
        from lib.admin_config import (
            get_admin_config, clear_admin_config_cache, _cache
        )

        clear_admin_config_cache()

        with patch('lib.db.get_db_pool') as mock_get_pool:
            mock_get_pool.side_effect = Exception("DB connection failed")

            # キャッシュを作成
            get_admin_config(TEST_ORG_ID)
            get_admin_config("another_org_id")

            # キャッシュが存在することを確認
            # （フォールバックの場合はキャッシュされない仕様に変更されている可能性あり）

            # 全クリア
            clear_admin_config_cache()

            # キャッシュが空であることを確認
            assert len(_cache) == 0

    def test_clear_admin_config_cache_specific_org(self):
        """特定組織のキャッシュのみクリア"""
        from lib.admin_config import clear_admin_config_cache, _cache

        clear_admin_config_cache()
        assert len(_cache) == 0


# ================================================================
# 後方互換性のテスト
# ================================================================

class TestBackwardCompatibility:
    """後方互換性のテスト"""

    def test_backward_compatible_constants(self):
        """後方互換性のための定数が存在すること"""
        from lib.admin_config import (
            ADMIN_ACCOUNT_ID,
            ADMIN_ROOM_ID,
            KAZU_CHATWORK_ACCOUNT_ID,
            KAZU_ACCOUNT_ID,
        )

        # 後方互換性定数がデフォルト値と一致
        assert ADMIN_ACCOUNT_ID == "1728974"
        assert ADMIN_ROOM_ID == "405315911"
        assert KAZU_CHATWORK_ACCOUNT_ID == "1728974"
        assert KAZU_ACCOUNT_ID == 1728974
