"""
ConnectionService ユニットテスト

テスト項目:
1. OWNER判定テスト（CEO/Admin）
2. 非OWNER拒否テスト
3. ChatWork API呼び出しテスト（モック）
4. ログ出力テスト
5. 意図判定テスト
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from dataclasses import dataclass

from lib.connection_service import (
    ConnectionService,
    AsyncConnectionService,
    ConnectionPolicy,
    ConnectionQueryResult,
    DirectMessageRoom,
    CEO_ACCOUNT_IDS,
)
from lib.connection_logger import (
    ConnectionLogger,
    ConnectionQueryLog,
    get_connection_logger,
)


# =============================================================================
# フィクスチャ
# =============================================================================

@dataclass
class MockChatworkRoom:
    """ChatworkRoom のモック"""
    room_id: int
    name: str
    type: str
    role: str = "member"
    sticky: bool = False
    unread_num: int = 0
    mention_num: int = 0


@pytest.fixture
def mock_chatwork_client():
    """モックChatWorkクライアント"""
    client = MagicMock()
    client.list_direct_message_rooms.return_value = [
        MockChatworkRoom(room_id=1, name="田中太郎", type="direct", unread_num=0),
        MockChatworkRoom(room_id=2, name="佐藤花子", type="direct", unread_num=2),
        MockChatworkRoom(room_id=3, name="鈴木一郎", type="direct", unread_num=0),
    ]
    return client


@pytest.fixture
def mock_chatwork_client_empty():
    """空のDMリストを返すモッククライアント"""
    client = MagicMock()
    client.list_direct_message_rooms.return_value = []
    return client


@pytest.fixture
def connection_service(mock_chatwork_client):
    """ConnectionService インスタンス"""
    return ConnectionService(
        chatwork_client=mock_chatwork_client,
        org_id="test_org_id",
    )


# =============================================================================
# OWNER判定テスト
# =============================================================================

class TestConnectionServiceOwner:
    """OWNER判定テスト"""

    def test_ceo_is_owner(self, connection_service):
        """CEOはOWNER"""
        # CEO_ACCOUNT_IDS = ["1728974"]
        assert connection_service.is_owner("1728974") is True

    def test_ceo_is_owner_int(self, connection_service):
        """CEOはOWNER（int型でも）"""
        assert connection_service.is_owner(1728974) is True

    def test_non_ceo_is_not_owner(self, connection_service):
        """非CEOはOWNERではない"""
        with patch("lib.admin_config.get_admin_config", return_value=None):
            assert connection_service.is_owner("9999999") is False

    def test_admin_is_owner(self, connection_service):
        """AdminもOWNER"""
        mock_config = MagicMock()
        mock_config.is_admin.return_value = True

        with patch("lib.admin_config.get_admin_config", return_value=mock_config):
            assert connection_service.is_owner("1234567") is True

    def test_non_admin_is_not_owner(self, connection_service):
        """非AdminはOWNERではない"""
        mock_config = MagicMock()
        mock_config.is_admin.return_value = False

        with patch("lib.admin_config.get_admin_config", return_value=mock_config):
            assert connection_service.is_owner("1234567") is False


# =============================================================================
# クエリテスト
# =============================================================================

class TestConnectionServiceQuery:
    """クエリテスト"""

    def test_owner_gets_dm_list(self, connection_service):
        """OWNERはDMリストを取得できる"""
        result = connection_service.query_connections("1728974")

        assert result.allowed is True
        assert result.policy == ConnectionPolicy.OWNER
        assert result.total_count == 3
        assert len(result.rooms) == 3
        assert "田中太郎" in result.message
        assert "佐藤花子" in result.message
        assert "鈴木一郎" in result.message

    def test_non_owner_denied(self, connection_service):
        """非OWNERは拒否される"""
        with patch("lib.admin_config.get_admin_config", return_value=None):
            result = connection_service.query_connections("9999999")

        assert result.allowed is False
        assert result.policy == ConnectionPolicy.NON_OWNER
        assert "代表のみ" in result.message
        assert result.total_count == 0
        assert len(result.rooms) == 0

    def test_empty_dm_list(self, mock_chatwork_client_empty):
        """DMリストが空の場合"""
        service = ConnectionService(
            chatwork_client=mock_chatwork_client_empty,
            org_id="test_org",
        )
        result = service.query_connections("1728974")

        assert result.allowed is True
        assert result.total_count == 0
        assert "まだ誰とも" in result.message

    def test_truncated_dm_list(self, mock_chatwork_client):
        """表示上限を超えた場合"""
        # 大量のDMルームを返すモック
        mock_chatwork_client.list_direct_message_rooms.return_value = [
            MockChatworkRoom(room_id=i, name=f"テストユーザー{i}", type="direct")
            for i in range(50)
        ]

        service = ConnectionService(
            chatwork_client=mock_chatwork_client,
            org_id="test_org",
        )
        result = service.query_connections("1728974", max_count=10)

        assert result.allowed is True
        assert result.total_count == 50
        assert result.truncated is True
        assert len(result.rooms) == 10
        assert "上位10件" in result.message

    def test_api_error_handling(self, mock_chatwork_client):
        """API呼び出しエラー時"""
        mock_chatwork_client.list_direct_message_rooms.side_effect = Exception("API Error")

        service = ConnectionService(
            chatwork_client=mock_chatwork_client,
            org_id="test_org",
        )
        result = service.query_connections("1728974")

        assert result.allowed is True  # 権限はあった
        assert "失敗" in result.message


# =============================================================================
# 非同期版テスト
# =============================================================================

class TestAsyncConnectionService:
    """非同期版のテスト"""

    @pytest.fixture
    def mock_async_client(self):
        """非同期モッククライアント"""
        client = MagicMock()
        client.list_direct_message_rooms = AsyncMock(return_value=[
            MockChatworkRoom(room_id=1, name="山田太郎", type="direct"),
            MockChatworkRoom(room_id=2, name="佐藤花子", type="direct"),
        ])
        return client

    @pytest.mark.asyncio
    async def test_async_owner_gets_dm_list(self, mock_async_client):
        """非同期版: OWNERはDMリストを取得できる"""
        service = AsyncConnectionService(
            chatwork_client=mock_async_client,
            org_id="test_org",
        )
        result = await service.query_connections("1728974")

        assert result.allowed is True
        assert result.total_count == 2

    @pytest.mark.asyncio
    async def test_async_non_owner_denied(self, mock_async_client):
        """非同期版: 非OWNERは拒否される"""
        service = AsyncConnectionService(
            chatwork_client=mock_async_client,
            org_id="test_org",
        )

        with patch("lib.admin_config.get_admin_config", return_value=None):
            result = await service.query_connections("9999999")

        assert result.allowed is False
        assert "代表のみ" in result.message


# =============================================================================
# ロガーテスト
# =============================================================================

class TestConnectionLogger:
    """ログ出力テスト"""

    def test_log_entry_to_dict(self):
        """ログエントリの辞書変換"""
        log = ConnectionQueryLog(
            timestamp="2026-01-29T10:00:00",
            allowed=True,
            requester_user_id="1728974",
            result_count=10,
            organization_id="org_id",
            room_id="12345",
        )
        d = log.to_dict()

        assert d["event_type"] == "CONNECTION_QUERY"
        assert d["data_source"] == "chatwork_1on1"
        assert d["allowed"] is True
        assert d["requester_user_id"] == "1728974"
        assert d["result_count"] == 10

    def test_logger_disabled(self):
        """無効化時はログ出力しない"""
        logger = ConnectionLogger(enabled=False)
        # エラーなく完了すればOK
        logger.log_query(
            requester_user_id="1728974",
            allowed=True,
            result_count=10,
        )

    def test_logger_singleton(self):
        """シングルトンパターン"""
        import lib.connection_logger as module
        module._logger_instance = None  # リセット

        logger1 = get_connection_logger()
        logger2 = get_connection_logger()

        assert logger1 is logger2


# =============================================================================
# 意図判定テスト
# =============================================================================

class TestConnectionQueryIntent:
    """意図判定テスト（INTENT_KEYWORDSの確認）"""

    def test_keywords_defined(self):
        """connection_query がINTENT_KEYWORDSに定義されている"""
        from lib.brain.understanding import INTENT_KEYWORDS

        assert "connection_query" in INTENT_KEYWORDS
        keywords = INTENT_KEYWORDS["connection_query"]

        assert "primary" in keywords
        assert "secondary" in keywords
        assert "negative" in keywords
        assert keywords["confidence_boost"] == 1.2  # v10.44.1: 優先度強化

    def test_decision_keywords_defined(self):
        """connection_query がCAPABILITY_KEYWORDSに定義されている"""
        from lib.brain.decision import CAPABILITY_KEYWORDS

        assert "connection_query" in CAPABILITY_KEYWORDS
        keywords = CAPABILITY_KEYWORDS["connection_query"]

        assert "primary" in keywords
        assert "DM" in keywords["primary"]
        assert "1on1" in keywords["primary"]

    @pytest.mark.parametrize("keyword", [
        "DM", "1on1", "個別", "繋がってる", "直接", "話せる", "チャットできる"
    ])
    def test_secondary_keywords(self, keyword):
        """セカンダリキーワードが含まれている"""
        from lib.brain.understanding import INTENT_KEYWORDS

        keywords = INTENT_KEYWORDS["connection_query"]
        all_keywords = keywords["primary"] + keywords["secondary"]

        # キーワードが含まれているか確認（部分一致）
        found = any(keyword in kw for kw in all_keywords)
        assert found, f"キーワード '{keyword}' が見つからない"


# =============================================================================
# CEO_ACCOUNT_IDS 同期テスト
# =============================================================================

class TestCEOAccountSync:
    """CEO_ACCOUNT_IDSがceo_learning.pyと同期しているか確認"""

    def test_ceo_account_ids_sync(self):
        """CEO_ACCOUNT_IDSの同期確認"""
        from lib.brain.ceo_learning import CEO_ACCOUNT_IDS as ORIGINAL_IDS
        from lib.connection_service import CEO_ACCOUNT_IDS as SERVICE_IDS

        # 両方に同じIDが含まれている
        assert "1728974" in ORIGINAL_IDS
        assert "1728974" in SERVICE_IDS


# =============================================================================
# DMルーティングテスト（v10.44.1）
# =============================================================================

class TestDMQuestionRouting:
    """DMに関する質問が connection_query にルーティングされるかテスト"""

    def test_dm_question_keyword_match(self):
        """「DMできる相手は誰？」がキーワードマッチする"""
        from lib.brain.understanding import INTENT_KEYWORDS

        keywords = INTENT_KEYWORDS["connection_query"]
        message = "DMできる相手は誰？"

        # primaryキーワードが含まれる
        primary_match = any(kw in message for kw in keywords["primary"])
        # secondaryキーワードが含まれる
        secondary_match = any(kw in message for kw in keywords["secondary"])
        # modifierキーワードが含まれる
        modifier_match = any(kw in message for kw in keywords["modifiers"])

        assert primary_match or secondary_match, "DM関連キーワードがマッチしない"
        assert modifier_match, "modifierキーワードがマッチしない"

    @pytest.mark.parametrize("message", [
        "DMできる相手は誰？",
        "DMできる人を教えて",
        "1on1で繋がってる人は？",
        "ソウルくんと直接チャットできる相手は？",
        "個別で繋がってる人の一覧",
    ])
    def test_dm_messages_match_keywords(self, message):
        """DMメッセージがキーワードにマッチする"""
        from lib.brain.understanding import INTENT_KEYWORDS

        keywords = INTENT_KEYWORDS["connection_query"]

        # primary, secondary, modifiers のいずれかにマッチ
        all_keywords = (
            keywords["primary"]
            + keywords["secondary"]
            + keywords["modifiers"]
        )
        matches = [kw for kw in all_keywords if kw in message]

        assert len(matches) > 0, f"'{message}' がキーワードにマッチしない"

    def test_confidence_boost_is_high(self):
        """confidence_boost が高く設定されている"""
        from lib.brain.understanding import INTENT_KEYWORDS

        keywords = INTENT_KEYWORDS["connection_query"]

        # 1.0以上で優先されるはず
        assert keywords["confidence_boost"] >= 1.0, (
            f"confidence_boost が低い: {keywords['confidence_boost']}"
        )

    def test_priority_in_decision_keywords(self):
        """decision.py で priority が設定されている"""
        from lib.brain.decision import CAPABILITY_KEYWORDS

        keywords = CAPABILITY_KEYWORDS["connection_query"]

        # priority が設定されている
        assert "priority" in keywords, "priority が設定されていない"
        assert keywords["priority"] >= 100, "priority が低い"
