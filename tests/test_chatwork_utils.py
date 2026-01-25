"""
ChatWork APIユーティリティのテスト

chatwork-webhook/utils/chatwork_utils.py のテスト
"""

import pytest
from unittest.mock import patch, MagicMock
import time
import sys
import os

# chatwork-webhookのパスを追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'chatwork-webhook'))

from utils.chatwork_utils import (
    APICallCounter,
    get_api_call_counter,
    reset_api_call_counter,
    clear_room_members_cache,
    call_chatwork_api_with_retry,
    get_room_members,
    get_room_members_cached,
    is_room_member,
)


class TestAPICallCounter:
    """APICallCounterクラスのテスト"""

    def test_initial_count_is_zero(self):
        """初期カウントが0であること"""
        counter = APICallCounter()
        assert counter.get_count() == 0

    def test_increment(self):
        """incrementでカウントが増加すること"""
        counter = APICallCounter()
        counter.increment()
        assert counter.get_count() == 1
        counter.increment()
        assert counter.get_count() == 2

    def test_log_summary(self, capsys):
        """log_summaryがログを出力すること"""
        counter = APICallCounter()
        counter.increment()
        counter.increment()
        counter.log_summary("test_function")
        captured = capsys.readouterr()
        assert "[API Usage]" in captured.out
        assert "test_function" in captured.out
        assert "2 calls" in captured.out


class TestGlobalFunctions:
    """グローバル関数のテスト"""

    def test_get_api_call_counter(self):
        """get_api_call_counterがカウンターを返すこと"""
        counter = get_api_call_counter()
        assert isinstance(counter, APICallCounter)

    def test_reset_api_call_counter(self):
        """reset_api_call_counterがカウンターをリセットすること"""
        counter = get_api_call_counter()
        counter.increment()
        reset_api_call_counter()
        new_counter = get_api_call_counter()
        assert new_counter.get_count() == 0

    def test_clear_room_members_cache(self):
        """clear_room_members_cacheがキャッシュをクリアすること"""
        # クリアしてもエラーにならないことを確認
        clear_room_members_cache()


class TestCallChatworkApiWithRetry:
    """call_chatwork_api_with_retry関数のテスト"""

    @patch('utils.chatwork_utils.httpx.get')
    def test_get_success(self, mock_get):
        """GET成功時のテスト"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": "ok"}
        mock_get.return_value = mock_response

        response, success = call_chatwork_api_with_retry(
            method="GET",
            url="https://api.chatwork.com/v2/test",
            headers={"X-ChatWorkToken": "test_token"}
        )

        assert success is True
        assert response.status_code == 200

    @patch('utils.chatwork_utils.httpx.post')
    def test_post_success(self, mock_post):
        """POST成功時のテスト"""
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_post.return_value = mock_response

        response, success = call_chatwork_api_with_retry(
            method="POST",
            url="https://api.chatwork.com/v2/test",
            headers={"X-ChatWorkToken": "test_token"},
            data={"key": "value"}
        )

        assert success is True
        assert response.status_code == 201

    @patch('utils.chatwork_utils.httpx.put')
    def test_put_success(self, mock_put):
        """PUT成功時のテスト"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_put.return_value = mock_response

        response, success = call_chatwork_api_with_retry(
            method="PUT",
            url="https://api.chatwork.com/v2/test",
            headers={"X-ChatWorkToken": "test_token"},
            data={"key": "value"}
        )

        assert success is True

    @patch('utils.chatwork_utils.httpx.delete')
    def test_delete_success(self, mock_delete):
        """DELETE成功時のテスト"""
        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_delete.return_value = mock_response

        response, success = call_chatwork_api_with_retry(
            method="DELETE",
            url="https://api.chatwork.com/v2/test",
            headers={"X-ChatWorkToken": "test_token"}
        )

        assert success is True

    @patch('utils.chatwork_utils.httpx.get')
    def test_client_error(self, mock_get):
        """クライアントエラー時のテスト（リトライなし）"""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_get.return_value = mock_response

        response, success = call_chatwork_api_with_retry(
            method="GET",
            url="https://api.chatwork.com/v2/test",
            headers={"X-ChatWorkToken": "test_token"}
        )

        assert success is False
        assert response.status_code == 400
        # クライアントエラーはリトライしない
        assert mock_get.call_count == 1

    @patch('utils.chatwork_utils.httpx.get')
    @patch('utils.chatwork_utils.time.sleep')
    def test_rate_limit_retry(self, mock_sleep, mock_get):
        """レート制限時のリトライテスト"""
        mock_429_response = MagicMock()
        mock_429_response.status_code = 429

        mock_200_response = MagicMock()
        mock_200_response.status_code = 200

        # 最初は429、2回目で200
        mock_get.side_effect = [mock_429_response, mock_200_response]

        response, success = call_chatwork_api_with_retry(
            method="GET",
            url="https://api.chatwork.com/v2/test",
            headers={"X-ChatWorkToken": "test_token"},
            max_retries=3,
            initial_wait=0.1
        )

        assert success is True
        assert response.status_code == 200
        assert mock_get.call_count == 2
        assert mock_sleep.called

    @patch('utils.chatwork_utils.httpx.get')
    @patch('utils.chatwork_utils.time.sleep')
    def test_rate_limit_max_retries_exceeded(self, mock_sleep, mock_get):
        """レート制限でリトライ回数超過時のテスト"""
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_get.return_value = mock_response

        response, success = call_chatwork_api_with_retry(
            method="GET",
            url="https://api.chatwork.com/v2/test",
            headers={"X-ChatWorkToken": "test_token"},
            max_retries=2,
            initial_wait=0.1
        )

        assert success is False
        assert response.status_code == 429
        # 初回 + リトライ2回 = 3回
        assert mock_get.call_count == 3

    def test_unsupported_method(self):
        """サポートされていないHTTPメソッドのテスト"""
        response, success = call_chatwork_api_with_retry(
            method="PATCH",
            url="https://api.chatwork.com/v2/test",
            headers={"X-ChatWorkToken": "test_token"}
        )

        assert success is False
        assert response is None


class TestGetRoomMembers:
    """get_room_members関数のテスト"""

    @patch('utils.chatwork_utils.call_chatwork_api_with_retry')
    def test_success(self, mock_api):
        """メンバー取得成功時のテスト"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {"account_id": 123, "name": "Test User 1"},
            {"account_id": 456, "name": "Test User 2"}
        ]
        mock_api.return_value = (mock_response, True)

        members = get_room_members("room123", "test_token")

        assert len(members) == 2
        assert members[0]["account_id"] == 123

    @patch('utils.chatwork_utils.call_chatwork_api_with_retry')
    def test_failure(self, mock_api):
        """メンバー取得失敗時のテスト"""
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.text = "Forbidden"
        mock_api.return_value = (mock_response, False)

        members = get_room_members("room123", "test_token")

        assert members == []


class TestGetRoomMembersCached:
    """get_room_members_cached関数のテスト"""

    def setup_method(self):
        """テスト前にキャッシュをクリア"""
        clear_room_members_cache()

    @patch('utils.chatwork_utils.get_room_members')
    def test_cache_hit(self, mock_get_members):
        """キャッシュヒット時のテスト"""
        mock_get_members.return_value = [{"account_id": 123}]

        # 1回目
        members1 = get_room_members_cached("room123", "test_token")
        # 2回目（キャッシュから）
        members2 = get_room_members_cached("room123", "test_token")

        # APIは1回しか呼ばれない
        assert mock_get_members.call_count == 1
        assert members1 == members2

    @patch('utils.chatwork_utils.get_room_members')
    def test_different_rooms_no_cache(self, mock_get_members):
        """異なるルームはキャッシュされないテスト"""
        mock_get_members.return_value = [{"account_id": 123}]

        get_room_members_cached("room1", "test_token")
        get_room_members_cached("room2", "test_token")

        # 異なるルームなので2回呼ばれる
        assert mock_get_members.call_count == 2


class TestIsRoomMember:
    """is_room_member関数のテスト"""

    def setup_method(self):
        """テスト前にキャッシュをクリア"""
        clear_room_members_cache()

    @patch('utils.chatwork_utils.get_room_members_cached')
    def test_is_member(self, mock_get_members):
        """メンバーである場合のテスト"""
        mock_get_members.return_value = [
            {"account_id": 123},
            {"account_id": 456}
        ]

        result = is_room_member("room123", 123, "test_token")

        assert result is True

    @patch('utils.chatwork_utils.get_room_members_cached')
    def test_is_not_member(self, mock_get_members):
        """メンバーでない場合のテスト"""
        mock_get_members.return_value = [
            {"account_id": 123},
            {"account_id": 456}
        ]

        result = is_room_member("room123", 789, "test_token")

        assert result is False

    @patch('utils.chatwork_utils.get_room_members_cached')
    def test_string_account_id(self, mock_get_members):
        """文字列のaccount_idでもマッチするテスト"""
        mock_get_members.return_value = [{"account_id": 123}]

        result = is_room_member("room123", "123", "test_token")

        assert result is True

    @patch('utils.chatwork_utils.get_room_members_cached')
    def test_empty_members(self, mock_get_members):
        """メンバーリストが空の場合のテスト"""
        mock_get_members.return_value = []

        result = is_room_member("room123", 123, "test_token")

        assert result is False


class TestExponentialBackoff:
    """指数バックオフのテスト"""

    @patch('utils.chatwork_utils.httpx.get')
    @patch('utils.chatwork_utils.time.sleep')
    def test_exponential_backoff_timing(self, mock_sleep, mock_get):
        """指数バックオフの待機時間が正しいこと"""
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_get.return_value = mock_response

        call_chatwork_api_with_retry(
            method="GET",
            url="https://api.chatwork.com/v2/test",
            headers={"X-ChatWorkToken": "test_token"},
            max_retries=3,
            initial_wait=1.0
        )

        # 待機時間の確認
        sleep_calls = [call[0][0] for call in mock_sleep.call_args_list]
        # 1.0, 2.0, 4.0 と倍増していく
        assert len(sleep_calls) == 3
        assert sleep_calls[0] == 1.0
        assert sleep_calls[1] == 2.0
        assert sleep_calls[2] == 4.0
