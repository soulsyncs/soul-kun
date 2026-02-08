"""
提案管理ハンドラーのテスト

chatwork-webhook/handlers/proposal_handler.py のテスト
"""

import pytest
from unittest.mock import MagicMock, patch
import sys
import os

# chatwork-webhookのパスを追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'chatwork-webhook'))

from handlers.proposal_handler import ProposalHandler


class TestProposalHandlerInit:
    """ProposalHandlerの初期化テスト"""

    def test_init(self):
        """正常に初期化できること"""
        handler = ProposalHandler(
            get_pool=MagicMock(),
            get_secret=MagicMock(),
            admin_room_id="12345",
            admin_account_id="67890",
            is_admin=MagicMock(return_value=True)
        )
        assert handler.admin_room_id == "12345"
        assert handler.admin_account_id == "67890"


class TestCreateProposal:
    """create_proposal関数のテスト"""

    def test_create_proposal_success(self):
        """提案作成が成功すること"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.begin.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchone.return_value = [123]

        handler = ProposalHandler(
            get_pool=MagicMock(return_value=mock_pool),
            get_secret=MagicMock(),
            admin_room_id="12345",
            admin_account_id="67890",
            is_admin=MagicMock()
        )

        result = handler.create_proposal(
            proposed_by_account_id="111",
            proposed_by_name="Test User",
            proposed_in_room_id="999",
            category="rules",
            key="test_key",
            value="test_value"
        )

        assert result == 123

    def test_create_proposal_error(self):
        """提案作成がエラー時にNoneを返すこと"""
        mock_pool = MagicMock()
        mock_pool.begin.side_effect = Exception("DB Error")

        handler = ProposalHandler(
            get_pool=MagicMock(return_value=mock_pool),
            get_secret=MagicMock(),
            admin_room_id="12345",
            admin_account_id="67890",
            is_admin=MagicMock()
        )

        result = handler.create_proposal(
            proposed_by_account_id="111",
            proposed_by_name="Test User",
            proposed_in_room_id="999",
            category="rules",
            key="test_key",
            value="test_value"
        )

        assert result is None


class TestGetPendingProposals:
    """get_pending_proposals関数のテスト"""

    def test_get_pending_proposals_success(self):
        """承認待ち提案が取得できること"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchall.return_value = [
            (1, "111", "User1", "999", "rules", "key1", "value1", None, "2026-01-25"),
            (2, "222", "User2", "888", "members", "key2", "value2", None, "2026-01-26"),
        ]

        handler = ProposalHandler(
            get_pool=MagicMock(return_value=mock_pool),
            get_secret=MagicMock(),
            admin_room_id="12345",
            admin_account_id="67890",
            is_admin=MagicMock()
        )

        result = handler.get_pending_proposals()

        assert len(result) == 2
        assert result[0]["id"] == 1
        assert result[0]["proposed_by_name"] == "User1"
        assert result[1]["id"] == 2

    def test_get_pending_proposals_empty(self):
        """提案がない場合に空リストを返すこと"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchall.return_value = []

        handler = ProposalHandler(
            get_pool=MagicMock(return_value=mock_pool),
            get_secret=MagicMock(),
            admin_room_id="12345",
            admin_account_id="67890",
            is_admin=MagicMock()
        )

        result = handler.get_pending_proposals()

        assert result == []


class TestGetProposalById:
    """get_proposal_by_id関数のテスト"""

    def test_get_proposal_by_id_found(self):
        """IDで提案が見つかること"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchone.return_value = (
            1, "111", "User1", "999", "rules", "key1", "value1", None, "2026-01-25", "pending"
        )

        handler = ProposalHandler(
            get_pool=MagicMock(return_value=mock_pool),
            get_secret=MagicMock(),
            admin_room_id="12345",
            admin_account_id="67890",
            is_admin=MagicMock()
        )

        result = handler.get_proposal_by_id(1)

        assert result is not None
        assert result["id"] == 1
        assert result["key"] == "key1"
        assert result["status"] == "pending"

    def test_get_proposal_by_id_not_found(self):
        """IDで提案が見つからない場合にNoneを返すこと"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchone.return_value = None

        handler = ProposalHandler(
            get_pool=MagicMock(return_value=mock_pool),
            get_secret=MagicMock(),
            admin_room_id="12345",
            admin_account_id="67890",
            is_admin=MagicMock()
        )

        result = handler.get_proposal_by_id(999)

        assert result is None


class TestApproveProposal:
    """approve_proposal関数のテスト"""

    def test_approve_proposal_success(self):
        """提案承認が成功すること"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.begin.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchone.return_value = (
            "rules", "key1", "value1", "111"
        )

        handler = ProposalHandler(
            get_pool=MagicMock(return_value=mock_pool),
            get_secret=MagicMock(),
            admin_room_id="12345",
            admin_account_id="67890",
            is_admin=MagicMock()
        )

        result = handler.approve_proposal(1, "admin_user")

        assert result is True

    def test_approve_proposal_not_found(self):
        """提案が見つからない場合にFalseを返すこと"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.begin.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchone.return_value = None

        handler = ProposalHandler(
            get_pool=MagicMock(return_value=mock_pool),
            get_secret=MagicMock(),
            admin_room_id="12345",
            admin_account_id="67890",
            is_admin=MagicMock()
        )

        result = handler.approve_proposal(999, "admin_user")

        assert result is False


class TestRejectProposal:
    """reject_proposal関数のテスト"""

    def test_reject_proposal_success(self):
        """提案却下が成功すること"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.begin.return_value.__exit__ = MagicMock(return_value=False)

        handler = ProposalHandler(
            get_pool=MagicMock(return_value=mock_pool),
            get_secret=MagicMock(),
            admin_room_id="12345",
            admin_account_id="67890",
            is_admin=MagicMock()
        )

        result = handler.reject_proposal(1, "admin_user")

        assert result is True


class TestHandleProposalDecision:
    """handle_proposal_decision関数のテスト"""

    def test_handle_proposal_decision_not_admin_room(self):
        """管理部ルーム以外ではNoneを返すこと"""
        handler = ProposalHandler(
            get_pool=MagicMock(),
            get_secret=MagicMock(),
            admin_room_id="12345",
            admin_account_id="67890",
            is_admin=MagicMock(return_value=True)
        )

        result = handler.handle_proposal_decision(
            params={"decision": "approve"},
            room_id="99999",  # 管理部ルームではない
            account_id="111",
            sender_name="Test User"
        )

        assert result is None

    def test_handle_proposal_decision_no_pending(self):
        """承認待ちがない場合のメッセージ"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchall.return_value = []

        handler = ProposalHandler(
            get_pool=MagicMock(return_value=mock_pool),
            get_secret=MagicMock(),
            admin_room_id="12345",
            admin_account_id="67890",
            is_admin=MagicMock(return_value=True)
        )

        result = handler.handle_proposal_decision(
            params={"decision": "approve"},
            room_id="12345",  # 管理部ルーム
            account_id="111",
            sender_name="Test User"
        )

        assert "承認待ちの提案は今ないウル" in result


class TestHandleProposalById:
    """handle_proposal_by_id関数のテスト"""

    def test_handle_proposal_by_id_not_admin_room(self):
        """管理部ルーム以外ではエラーメッセージを返すこと"""
        handler = ProposalHandler(
            get_pool=MagicMock(),
            get_secret=MagicMock(),
            admin_room_id="12345",
            admin_account_id="67890",
            is_admin=MagicMock(return_value=True)
        )

        result = handler.handle_proposal_by_id(
            proposal_id=1,
            decision="approve",
            account_id="111",
            sender_name="Test User",
            room_id="99999"  # 管理部ルームではない
        )

        assert "管理部ルームでお願いするウル" in result

    def test_handle_proposal_by_id_not_admin(self):
        """管理者以外の場合のエラーメッセージ"""
        handler = ProposalHandler(
            get_pool=MagicMock(),
            get_secret=MagicMock(),
            admin_room_id="12345",
            admin_account_id="67890",
            is_admin=MagicMock(return_value=False)  # 管理者ではない
        )

        result = handler.handle_proposal_by_id(
            proposal_id=1,
            decision="approve",
            account_id="111",
            sender_name="Test User",
            room_id="12345"
        )

        assert "菊地さんだけができるウル" in result

    def test_handle_proposal_by_id_not_found(self):
        """提案が見つからない場合"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchone.return_value = None

        handler = ProposalHandler(
            get_pool=MagicMock(return_value=mock_pool),
            get_secret=MagicMock(),
            admin_room_id="12345",
            admin_account_id="67890",
            is_admin=MagicMock(return_value=True)
        )

        result = handler.handle_proposal_by_id(
            proposal_id=999,
            decision="approve",
            account_id="111",
            sender_name="Test User",
            room_id="12345"
        )

        assert "見つからなかったウル" in result


class TestRetryProposalNotification:
    """retry_proposal_notification関数のテスト"""

    def test_retry_notification_not_found(self):
        """提案が見つからない場合"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchone.return_value = None

        handler = ProposalHandler(
            get_pool=MagicMock(return_value=mock_pool),
            get_secret=MagicMock(),
            admin_room_id="12345",
            admin_account_id="67890",
            is_admin=MagicMock()
        )

        success, message = handler.retry_proposal_notification(999)

        assert success is False
        assert "見つからない" in message

    def test_retry_notification_already_processed(self):
        """既に処理済みの場合"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchone.return_value = (
            1, "111", "User1", "999", "rules", "key1", "value1", None, "2026-01-25", "approved"
        )

        handler = ProposalHandler(
            get_pool=MagicMock(return_value=mock_pool),
            get_secret=MagicMock(),
            admin_room_id="12345",
            admin_account_id="67890",
            is_admin=MagicMock()
        )

        success, message = handler.retry_proposal_notification(1)

        assert success is False
        assert "既に処理済み" in message


class TestOrgIdIsolation:
    """organization_idによるテナント分離テスト"""

    def test_create_proposal_includes_org_id(self):
        """create_proposalがorganization_idをINSERTに含むこと"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.begin.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchone.return_value = [1]

        handler = ProposalHandler(
            get_pool=MagicMock(return_value=mock_pool),
            get_secret=MagicMock(),
            admin_room_id="12345",
            admin_account_id="67890",
            is_admin=MagicMock(),
            organization_id="org_test"
        )

        handler.create_proposal("111", "User", "999", "rules", "key1", "value1")

        sql_str = str(mock_conn.execute.call_args[0][0])
        params = mock_conn.execute.call_args[0][1]
        assert "organization_id" in sql_str
        assert params["org_id"] == "org_test"

    def test_get_pending_proposals_filters_by_org_id(self):
        """get_pending_proposalsがorganization_idでフィルタすること"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchall.return_value = []

        handler = ProposalHandler(
            get_pool=MagicMock(return_value=mock_pool),
            get_secret=MagicMock(),
            admin_room_id="12345",
            admin_account_id="67890",
            is_admin=MagicMock(),
            organization_id="org_other"
        )

        handler.get_pending_proposals()

        sql_str = str(mock_conn.execute.call_args[0][0])
        params = mock_conn.execute.call_args[0][1]
        assert "organization_id = :org_id" in sql_str
        assert params["org_id"] == "org_other"

    def test_approve_proposal_scoped_by_org_id(self):
        """approve_proposalがorganization_idでスコープされること"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.begin.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchone.return_value = (
            "rules", "key1", "value1", "111"
        )

        handler = ProposalHandler(
            get_pool=MagicMock(return_value=mock_pool),
            get_secret=MagicMock(),
            admin_room_id="12345",
            admin_account_id="67890",
            is_admin=MagicMock(),
            organization_id="org_test"
        )

        handler.approve_proposal(1, "admin")

        # 全てのexecute呼び出しがorg_idを含むことを確認
        for call in mock_conn.execute.call_args_list:
            params = call[0][1]
            assert params["org_id"] == "org_test"

    def test_reject_proposal_scoped_by_org_id(self):
        """reject_proposalがorganization_idでスコープされること"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.begin.return_value.__exit__ = MagicMock(return_value=False)

        handler = ProposalHandler(
            get_pool=MagicMock(return_value=mock_pool),
            get_secret=MagicMock(),
            admin_room_id="12345",
            admin_account_id="67890",
            is_admin=MagicMock(),
            organization_id="org_test"
        )

        handler.reject_proposal(1, "admin")

        params = mock_conn.execute.call_args[0][1]
        assert params["org_id"] == "org_test"

    def test_default_org_id(self):
        """organization_idのデフォルト値がorg_soulsyncsであること"""
        handler = ProposalHandler(
            get_pool=MagicMock(),
            get_secret=MagicMock(),
            admin_room_id="12345",
            admin_account_id="67890",
            is_admin=MagicMock()
        )
        assert handler.organization_id == "org_soulsyncs"
