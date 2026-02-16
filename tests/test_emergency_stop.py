"""
緊急停止チェッカー（EmergencyStopChecker）テスト — Step 0-3

EmergencyStopCheckerのTTLキャッシュ、有効化/無効化、ブロック/通過をテスト。
DBモックを使用するため、実際のDB接続は不要。
"""

import time
import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from lib.brain.emergency_stop import EmergencyStopChecker


def _make_mock_pool(is_active=False, row_exists=True):
    """モックDBプールを生成する"""
    pool = MagicMock()
    conn = MagicMock()
    pool.connect.return_value.__enter__ = MagicMock(return_value=conn)
    pool.connect.return_value.__exit__ = MagicMock(return_value=False)

    result = MagicMock()
    if row_exists:
        row = MagicMock()
        row.__getitem__ = lambda self, idx: is_active if idx == 0 else None
        result.fetchone.return_value = row
    else:
        result.fetchone.return_value = None

    conn.execute.return_value = result
    return pool, conn


class TestEmergencyStopChecker:
    """EmergencyStopCheckerの基本テスト"""

    def test_not_stopped_by_default(self):
        """デフォルト（is_active=False）では停止していない"""
        pool, _ = _make_mock_pool(is_active=False)
        checker = EmergencyStopChecker(pool=pool, org_id="test-org")
        assert checker.is_stopped() is False

    def test_stopped_when_active(self):
        """is_active=Trueなら停止中"""
        pool, _ = _make_mock_pool(is_active=True)
        checker = EmergencyStopChecker(pool=pool, org_id="test-org")
        assert checker.is_stopped() is True

    def test_not_stopped_when_no_row(self):
        """レコードが存在しない場合は停止していない"""
        pool, _ = _make_mock_pool(row_exists=False)
        checker = EmergencyStopChecker(pool=pool, org_id="test-org")
        assert checker.is_stopped() is False

    def test_db_error_returns_false(self):
        """DB障害時は安全側（停止しない）"""
        pool = MagicMock()
        pool.connect.side_effect = Exception("DB connection failed")
        checker = EmergencyStopChecker(pool=pool, org_id="test-org")
        assert checker.is_stopped() is False


class TestEmergencyStopCache:
    """TTLキャッシュのテスト"""

    def test_cache_hit(self):
        """TTL内はキャッシュされた値を返す"""
        pool, _ = _make_mock_pool(is_active=False)
        checker = EmergencyStopChecker(pool=pool, org_id="test-org", cache_ttl_seconds=10)

        # 1回目: DBクエリ
        result1 = checker.is_stopped()
        call_count_after_first = pool.connect.call_count

        # 2回目: キャッシュヒット（DBクエリなし）
        result2 = checker.is_stopped()
        call_count_after_second = pool.connect.call_count

        assert result1 is False
        assert result2 is False
        assert call_count_after_second == call_count_after_first

    def test_cache_expiry(self):
        """TTL超過後はDBを再クエリ"""
        pool, _ = _make_mock_pool(is_active=False)
        checker = EmergencyStopChecker(pool=pool, org_id="test-org", cache_ttl_seconds=0)

        # TTL=0なので毎回DBクエリ
        checker.is_stopped()
        count1 = pool.connect.call_count
        checker.is_stopped()
        count2 = pool.connect.call_count

        assert count2 > count1

    def test_invalidate_cache(self):
        """invalidate_cache()でキャッシュをリセット"""
        pool, _ = _make_mock_pool(is_active=False)
        checker = EmergencyStopChecker(pool=pool, org_id="test-org", cache_ttl_seconds=60)

        checker.is_stopped()  # キャッシュに保存
        checker.invalidate_cache()

        assert checker._cached_is_stopped is None
        assert checker._cache_timestamp == 0.0


class TestEmergencyStopActivateDeactivate:
    """有効化/無効化のテスト"""

    def test_activate_success(self):
        """有効化が成功する"""
        pool, _ = _make_mock_pool()
        checker = EmergencyStopChecker(pool=pool, org_id="test-org")

        result = checker.activate(user_id="admin-user", reason="テスト停止")
        assert result is True
        assert checker._cached_is_stopped is True

    def test_deactivate_success(self):
        """無効化が成功する"""
        pool, _ = _make_mock_pool()
        checker = EmergencyStopChecker(pool=pool, org_id="test-org")

        result = checker.deactivate(user_id="admin-user")
        assert result is True
        assert checker._cached_is_stopped is False

    def test_activate_failure(self):
        """DB障害時の有効化は失敗を返す"""
        pool = MagicMock()
        pool.connect.side_effect = Exception("DB error")
        checker = EmergencyStopChecker(pool=pool, org_id="test-org")

        result = checker.activate(user_id="admin-user")
        assert result is False

    def test_deactivate_failure(self):
        """DB障害時の無効化は失敗を返す"""
        pool = MagicMock()
        pool.connect.side_effect = Exception("DB error")
        checker = EmergencyStopChecker(pool=pool, org_id="test-org")

        result = checker.deactivate(user_id="admin-user")
        assert result is False


class TestEmergencyStopGetStatus:
    """ステータス取得のテスト"""

    def test_get_status_active(self):
        """有効な停止状態の取得"""
        pool, conn = _make_mock_pool()
        # get_status用のモックを設定
        from unittest.mock import MagicMock as MM
        from datetime import datetime, timezone

        dt_now = datetime.now(timezone.utc)
        status_row = (True, "admin-user", None, "テスト停止", dt_now, None)
        result_mock = MagicMock()
        result_mock.fetchone.return_value = status_row
        # 2番目のexecute呼び出しの結果をカスタマイズ
        conn.execute.return_value = result_mock

        checker = EmergencyStopChecker(pool=pool, org_id="test-org")
        status = checker.get_status()

        assert status["is_active"] is True
        assert status["activated_by"] == "admin-user"
        assert status["reason"] == "テスト停止"

    def test_get_status_no_row(self):
        """レコードなしの場合"""
        pool, _ = _make_mock_pool(row_exists=False)
        checker = EmergencyStopChecker(pool=pool, org_id="test-org")
        status = checker.get_status()

        assert status["is_active"] is False

    def test_get_status_db_error(self):
        """DB障害時のステータス取得"""
        pool = MagicMock()
        pool.connect.side_effect = Exception("DB error")
        checker = EmergencyStopChecker(pool=pool, org_id="test-org")
        status = checker.get_status()

        assert status["is_active"] is False
        assert "error" in status
