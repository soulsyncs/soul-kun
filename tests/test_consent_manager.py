# tests/test_consent_manager.py
"""
ConsentManager のテスト

同意記録、撤回、全員確認、ステータス集約、メッセージ生成をテスト。
"""

import pytest
from unittest.mock import MagicMock

from lib.meetings.consent_manager import ConsentManager


@pytest.fixture
def mock_pool():
    pool = MagicMock()
    conn = MagicMock()
    pool.connect.return_value.__enter__ = MagicMock(return_value=conn)
    pool.connect.return_value.__exit__ = MagicMock(return_value=None)
    return pool


@pytest.fixture
def manager(mock_pool):
    return ConsentManager(mock_pool, "org_test")


class TestInit:
    def test_valid_org_id(self, mock_pool):
        mgr = ConsentManager(mock_pool, "org_test")
        assert mgr.organization_id == "org_test"

    def test_empty_org_id_raises(self, mock_pool):
        with pytest.raises(ValueError, match="organization_id is required"):
            ConsentManager(mock_pool, "")

    def test_none_org_id_raises(self, mock_pool):
        with pytest.raises(ValueError):
            ConsentManager(mock_pool, None)


class TestRecordConsent:
    def test_records_granted(self, manager, mock_pool):
        result = manager.record_consent("m1", "user1", "granted")
        assert result is True

        conn = mock_pool.connect.return_value.__enter__.return_value
        params = conn.execute.call_args[0][1]
        assert params["org_id"] == "org_test"
        assert params["meeting_id"] == "m1"
        assert params["user_id"] == "user1"
        assert params["consent_type"] == "granted"
        conn.commit.assert_called_once()

    def test_records_withdrawn(self, manager, mock_pool):
        result = manager.record_consent("m1", "user1", "withdrawn")
        assert result is True

        conn = mock_pool.connect.return_value.__enter__.return_value
        params = conn.execute.call_args[0][1]
        assert params["consent_type"] == "withdrawn"

    def test_records_opted_out(self, manager, mock_pool):
        result = manager.record_consent("m1", "user1", "opted_out")
        assert result is True

    def test_invalid_consent_type_raises(self, manager):
        with pytest.raises(ValueError, match="Invalid consent_type"):
            manager.record_consent("m1", "user1", "invalid")

    def test_custom_consent_method(self, manager, mock_pool):
        manager.record_consent("m1", "user1", "granted", consent_method="api")

        conn = mock_pool.connect.return_value.__enter__.return_value
        params = conn.execute.call_args[0][1]
        assert params["method"] == "api"


class TestCheckAllConsented:
    def test_all_consented(self, manager, mock_pool):
        conn = mock_pool.connect.return_value.__enter__.return_value
        conn.execute.return_value.fetchall.return_value = [
            ("user1", "granted"), ("user2", "granted"),
        ]

        all_ok, missing = manager.check_all_consented("m1", ["user1", "user2"])
        assert all_ok is True
        assert missing == []

    def test_some_missing(self, manager, mock_pool):
        conn = mock_pool.connect.return_value.__enter__.return_value
        conn.execute.return_value.fetchall.return_value = [("user1", "granted")]

        all_ok, missing = manager.check_all_consented("m1", ["user1", "user2"])
        assert all_ok is False
        assert missing == ["user2"]

    def test_withdrawn_user_not_counted(self, manager, mock_pool):
        """撤回済みユーザーはgrantedとみなさない"""
        conn = mock_pool.connect.return_value.__enter__.return_value
        # DISTINCT ON (user_id) ORDER BY created_at DESC → 最新がwithdrawn
        conn.execute.return_value.fetchall.return_value = [
            ("user1", "withdrawn"), ("user2", "granted"),
        ]

        all_ok, missing = manager.check_all_consented("m1", ["user1", "user2"])
        assert all_ok is False
        assert "user1" in missing

    def test_empty_required_returns_true(self, manager):
        all_ok, missing = manager.check_all_consented("m1", [])
        assert all_ok is True
        assert missing == []

    def test_org_id_filter_in_query(self, manager, mock_pool):
        conn = mock_pool.connect.return_value.__enter__.return_value
        conn.execute.return_value.fetchall.return_value = []

        manager.check_all_consented("m1", ["user1"])
        params = conn.execute.call_args[0][1]
        assert params["org_id"] == "org_test"


class TestHasWithdrawal:
    def test_has_withdrawal(self, manager, mock_pool):
        conn = mock_pool.connect.return_value.__enter__.return_value
        conn.execute.return_value.fetchone.return_value = (1,)

        assert manager.has_withdrawal("m1") is True

    def test_no_withdrawal(self, manager, mock_pool):
        conn = mock_pool.connect.return_value.__enter__.return_value
        conn.execute.return_value.fetchone.return_value = None

        assert manager.has_withdrawal("m1") is False

    def test_org_id_filter(self, manager, mock_pool):
        conn = mock_pool.connect.return_value.__enter__.return_value
        conn.execute.return_value.fetchone.return_value = None

        manager.has_withdrawal("m1")
        params = conn.execute.call_args[0][1]
        assert params["org_id"] == "org_test"


class TestGetConsentStatus:
    def test_aggregates_latest_per_user(self, manager, mock_pool):
        conn = mock_pool.connect.return_value.__enter__.return_value
        # user1: 最初granted→後でwithdrawn（withdrawnが最新）
        # user2: granted（最新）
        conn.execute.return_value.mappings.return_value.fetchall.return_value = [
            {"user_id": "user1", "consent_type": "withdrawn", "created_at": "2026-02-10T02:00:00"},
            {"user_id": "user2", "consent_type": "granted", "created_at": "2026-02-10T01:30:00"},
            {"user_id": "user1", "consent_type": "granted", "created_at": "2026-02-10T01:00:00"},
        ]

        status = manager.get_consent_status("m1")
        assert status["meeting_id"] == "m1"
        assert "user2" in status["granted"]
        assert "user1" in status["withdrawn"]
        assert status["total_responses"] == 2

    def test_empty_status(self, manager, mock_pool):
        conn = mock_pool.connect.return_value.__enter__.return_value
        conn.execute.return_value.mappings.return_value.fetchall.return_value = []

        status = manager.get_consent_status("m1")
        assert status["granted"] == []
        assert status["withdrawn"] == []
        assert status["opted_out"] == []
        assert status["total_responses"] == 0


class TestBuildConsentRequestMessage:
    def test_with_title(self):
        msg = ConsentManager.build_consent_request_message(meeting_title="朝会")
        assert "朝会" in msg
        assert "同意" in msg
        assert "拒否" in msg
        assert "同意撤回" in msg

    def test_without_title(self):
        msg = ConsentManager.build_consent_request_message()
        assert "会議" in msg

    def test_is_static_method(self):
        # Brain bypass防止: メッセージ生成のみ、送信しない
        msg = ConsentManager.build_consent_request_message(meeting_title="Test")
        assert isinstance(msg, str)
        assert len(msg) > 0
