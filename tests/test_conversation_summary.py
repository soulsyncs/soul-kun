"""
ConversationSummary 単体テスト

conversation_summary.py の全メソッドを網羅的にテスト。
目標カバレッジ: 80%+

Author: Claude Code
Created: 2026-02-04
"""

import pytest
from datetime import datetime, timedelta
from uuid import UUID, uuid4
from unittest.mock import MagicMock, AsyncMock, patch
import asyncio


# ================================================================
# Fixtures
# ================================================================

@pytest.fixture
def mock_conn():
    """モックDBコネクション"""
    conn = MagicMock()
    conn.execute = MagicMock()
    conn.commit = MagicMock()
    return conn


@pytest.fixture
def org_id():
    """テスト用組織ID"""
    return uuid4()


@pytest.fixture
def user_id():
    """テスト用ユーザーID"""
    return uuid4()


@pytest.fixture
def conversation_summary(mock_conn, org_id):
    """ConversationSummaryインスタンス"""
    from lib.memory.conversation_summary import ConversationSummary
    return ConversationSummary(
        conn=mock_conn,
        org_id=org_id,
        openrouter_api_key="test-api-key",
        model="test-model"
    )


# ================================================================
# SummaryData テスト
# ================================================================

class TestSummaryData:
    """SummaryDataデータクラスのテスト"""

    def test_default_values(self):
        """デフォルト値のテスト"""
        from lib.memory.conversation_summary import SummaryData
        data = SummaryData()

        assert data.id is None
        assert data.organization_id is None
        assert data.user_id is None
        assert data.summary_text == ""
        assert data.key_topics == []
        assert data.mentioned_persons == []
        assert data.mentioned_tasks == []
        assert data.conversation_start is None
        assert data.conversation_end is None
        assert data.message_count == 0
        assert data.room_id is None
        assert data.generated_by == "llm"
        assert data.classification == "internal"
        assert data.created_at is None

    def test_with_all_values(self):
        """全値指定のテスト"""
        from lib.memory.conversation_summary import SummaryData
        from lib.memory.constants import GeneratedBy

        now = datetime.utcnow()
        test_id = uuid4()
        org_id = uuid4()
        user_id = uuid4()

        data = SummaryData(
            id=test_id,
            organization_id=org_id,
            user_id=user_id,
            summary_text="テストサマリー",
            key_topics=["topic1", "topic2"],
            mentioned_persons=["田中", "山田"],
            mentioned_tasks=["タスク1"],
            conversation_start=now - timedelta(hours=1),
            conversation_end=now,
            message_count=15,
            room_id="room123",
            generated_by=GeneratedBy.MANUAL.value,
            classification="confidential",
            created_at=now
        )

        assert data.id == test_id
        assert data.organization_id == org_id
        assert data.user_id == user_id
        assert data.summary_text == "テストサマリー"
        assert len(data.key_topics) == 2
        assert len(data.mentioned_persons) == 2
        assert len(data.mentioned_tasks) == 1
        assert data.message_count == 15
        assert data.room_id == "room123"
        assert data.generated_by == "manual"
        assert data.classification == "confidential"

    def test_to_dict_with_none_values(self):
        """to_dict - None値の処理"""
        from lib.memory.conversation_summary import SummaryData
        data = SummaryData()

        result = data.to_dict()

        assert result["id"] is None
        assert result["organization_id"] is None
        assert result["user_id"] is None
        assert result["summary_text"] == ""
        assert result["key_topics"] == []
        assert result["conversation_start"] is None
        assert result["conversation_end"] is None
        assert result["created_at"] is None

    def test_to_dict_with_uuid_conversion(self):
        """to_dict - UUIDの文字列変換"""
        from lib.memory.conversation_summary import SummaryData

        test_id = uuid4()
        org_id = uuid4()
        user_id = uuid4()

        data = SummaryData(
            id=test_id,
            organization_id=org_id,
            user_id=user_id
        )

        result = data.to_dict()

        assert result["id"] == str(test_id)
        assert result["organization_id"] == str(org_id)
        assert result["user_id"] == str(user_id)

    def test_to_dict_with_datetime_conversion(self):
        """to_dict - datetimeのISO形式変換"""
        from lib.memory.conversation_summary import SummaryData

        now = datetime.utcnow()
        start = now - timedelta(hours=1)

        data = SummaryData(
            conversation_start=start,
            conversation_end=now,
            created_at=now
        )

        result = data.to_dict()

        assert result["conversation_start"] == start.isoformat()
        assert result["conversation_end"] == now.isoformat()
        assert result["created_at"] == now.isoformat()

    def test_key_topics_list_independence(self):
        """key_topicsのリスト独立性"""
        from lib.memory.conversation_summary import SummaryData

        data1 = SummaryData()
        data2 = SummaryData()

        data1.key_topics.append("topic1")

        assert "topic1" not in data2.key_topics


# ================================================================
# ConversationSummary 初期化テスト
# ================================================================

class TestConversationSummaryInit:
    """ConversationSummary初期化のテスト"""

    def test_basic_init(self, mock_conn, org_id):
        """基本初期化"""
        from lib.memory.conversation_summary import ConversationSummary

        summary = ConversationSummary(conn=mock_conn, org_id=org_id)

        assert summary.conn == mock_conn
        assert summary.org_id == org_id
        assert summary.memory_type == "b1_summary"

    def test_init_with_api_key(self, mock_conn, org_id):
        """APIキー指定の初期化"""
        from lib.memory.conversation_summary import ConversationSummary

        summary = ConversationSummary(
            conn=mock_conn,
            org_id=org_id,
            openrouter_api_key="test-key"
        )

        assert summary.openrouter_api_key == "test-key"

    def test_init_with_custom_model(self, mock_conn, org_id):
        """カスタムモデル指定の初期化"""
        from lib.memory.conversation_summary import ConversationSummary

        summary = ConversationSummary(
            conn=mock_conn,
            org_id=org_id,
            model="custom-model"
        )

        assert summary.model == "custom-model"

    def test_default_model(self, mock_conn, org_id):
        """デフォルトモデルの確認"""
        from lib.memory.conversation_summary import ConversationSummary

        summary = ConversationSummary(conn=mock_conn, org_id=org_id)

        assert summary.model == "google/gemini-3-flash-preview"


# ================================================================
# save メソッドテスト
# ================================================================

class TestConversationSummarySave:
    """saveメソッドのテスト"""

    @pytest.mark.asyncio
    async def test_save_success(self, conversation_summary, user_id, mock_conn):
        """正常保存"""
        summary_id = uuid4()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (summary_id,)
        mock_conn.execute.return_value = mock_result

        now = datetime.utcnow()
        result = await conversation_summary.save(
            user_id=user_id,
            summary_text="テストサマリー",
            key_topics=["topic1", "topic2"],
            mentioned_persons=["田中"],
            mentioned_tasks=["タスク1"],
            conversation_start=now - timedelta(hours=1),
            conversation_end=now,
            message_count=10
        )

        assert result.success is True
        assert result.memory_id == summary_id
        assert "Summary saved successfully" in result.message
        assert result.data["message_count"] == 10
        mock_conn.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_with_room_id(self, conversation_summary, user_id, mock_conn):
        """room_id指定での保存"""
        summary_id = uuid4()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (summary_id,)
        mock_conn.execute.return_value = mock_result

        now = datetime.utcnow()
        result = await conversation_summary.save(
            user_id=user_id,
            summary_text="テスト",
            key_topics=[],
            mentioned_persons=[],
            mentioned_tasks=[],
            conversation_start=now,
            conversation_end=now,
            message_count=5,
            room_id="room123"
        )

        assert result.success is True
        # SQLパラメータにroom_idが含まれることを確認
        call_args = mock_conn.execute.call_args
        assert "room123" in str(call_args)

    @pytest.mark.asyncio
    async def test_save_with_custom_classification(self, conversation_summary, user_id, mock_conn):
        """カスタム機密区分での保存"""
        summary_id = uuid4()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (summary_id,)
        mock_conn.execute.return_value = mock_result

        now = datetime.utcnow()
        result = await conversation_summary.save(
            user_id=user_id,
            summary_text="機密サマリー",
            key_topics=[],
            mentioned_persons=[],
            mentioned_tasks=[],
            conversation_start=now,
            conversation_end=now,
            message_count=5,
            classification="confidential"
        )

        assert result.success is True

    @pytest.mark.asyncio
    async def test_save_truncates_long_summary(self, conversation_summary, user_id, mock_conn):
        """長いサマリーの切り詰め"""
        from lib.memory.constants import MemoryParameters

        summary_id = uuid4()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (summary_id,)
        mock_conn.execute.return_value = mock_result

        # 500文字を超えるサマリー
        long_summary = "A" * 1000
        now = datetime.utcnow()

        await conversation_summary.save(
            user_id=user_id,
            summary_text=long_summary,
            key_topics=[],
            mentioned_persons=[],
            mentioned_tasks=[],
            conversation_start=now,
            conversation_end=now,
            message_count=5
        )

        # 呼び出し時にtruncateされているか確認
        call_args = mock_conn.execute.call_args
        params = call_args[0][1]
        assert len(params["summary_text"]) <= MemoryParameters.SUMMARY_MAX_LENGTH

    @pytest.mark.asyncio
    async def test_save_truncates_topics(self, conversation_summary, user_id, mock_conn):
        """トピック数の制限"""
        from lib.memory.constants import MemoryParameters

        summary_id = uuid4()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (summary_id,)
        mock_conn.execute.return_value = mock_result

        # 制限を超えるトピック数
        many_topics = [f"topic{i}" for i in range(20)]
        now = datetime.utcnow()

        await conversation_summary.save(
            user_id=user_id,
            summary_text="test",
            key_topics=many_topics,
            mentioned_persons=[],
            mentioned_tasks=[],
            conversation_start=now,
            conversation_end=now,
            message_count=5
        )

        call_args = mock_conn.execute.call_args
        params = call_args[0][1]
        assert len(params["key_topics"]) <= MemoryParameters.SUMMARY_MAX_TOPICS

    @pytest.mark.asyncio
    async def test_save_truncates_persons(self, conversation_summary, user_id, mock_conn):
        """人物数の制限"""
        from lib.memory.constants import MemoryParameters

        summary_id = uuid4()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (summary_id,)
        mock_conn.execute.return_value = mock_result

        many_persons = [f"person{i}" for i in range(20)]
        now = datetime.utcnow()

        await conversation_summary.save(
            user_id=user_id,
            summary_text="test",
            key_topics=[],
            mentioned_persons=many_persons,
            mentioned_tasks=[],
            conversation_start=now,
            conversation_end=now,
            message_count=5
        )

        call_args = mock_conn.execute.call_args
        params = call_args[0][1]
        assert len(params["mentioned_persons"]) <= MemoryParameters.SUMMARY_MAX_PERSONS

    @pytest.mark.asyncio
    async def test_save_truncates_tasks(self, conversation_summary, user_id, mock_conn):
        """タスク数の制限"""
        from lib.memory.constants import MemoryParameters

        summary_id = uuid4()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (summary_id,)
        mock_conn.execute.return_value = mock_result

        many_tasks = [f"task{i}" for i in range(20)]
        now = datetime.utcnow()

        await conversation_summary.save(
            user_id=user_id,
            summary_text="test",
            key_topics=[],
            mentioned_persons=[],
            mentioned_tasks=many_tasks,
            conversation_start=now,
            conversation_end=now,
            message_count=5
        )

        call_args = mock_conn.execute.call_args
        params = call_args[0][1]
        assert len(params["mentioned_tasks"]) <= MemoryParameters.SUMMARY_MAX_TASKS

    @pytest.mark.asyncio
    async def test_save_with_string_user_id(self, conversation_summary, mock_conn):
        """文字列user_idでの保存"""
        summary_id = uuid4()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (summary_id,)
        mock_conn.execute.return_value = mock_result

        user_id_str = str(uuid4())
        now = datetime.utcnow()

        result = await conversation_summary.save(
            user_id=user_id_str,
            summary_text="test",
            key_topics=[],
            mentioned_persons=[],
            mentioned_tasks=[],
            conversation_start=now,
            conversation_end=now,
            message_count=5
        )

        assert result.success is True

    @pytest.mark.asyncio
    async def test_save_invalid_user_id(self, conversation_summary):
        """無効なuser_idでのエラー"""
        from lib.memory.exceptions import ValidationError

        now = datetime.utcnow()

        with pytest.raises(ValidationError):
            await conversation_summary.save(
                user_id="invalid-uuid",
                summary_text="test",
                key_topics=[],
                mentioned_persons=[],
                mentioned_tasks=[],
                conversation_start=now,
                conversation_end=now,
                message_count=5
            )

    @pytest.mark.asyncio
    async def test_save_database_error(self, conversation_summary, user_id, mock_conn):
        """DB保存エラー"""
        from lib.memory.exceptions import SummarySaveError

        mock_conn.execute.side_effect = Exception("DB error")
        now = datetime.utcnow()

        with pytest.raises(SummarySaveError):
            await conversation_summary.save(
                user_id=user_id,
                summary_text="test",
                key_topics=[],
                mentioned_persons=[],
                mentioned_tasks=[],
                conversation_start=now,
                conversation_end=now,
                message_count=5
            )


# ================================================================
# retrieve メソッドテスト
# ================================================================

class TestConversationSummaryRetrieve:
    """retrieveメソッドのテスト"""

    @pytest.mark.asyncio
    async def test_retrieve_no_filters(self, conversation_summary, mock_conn):
        """フィルタなしで取得"""
        now = datetime.utcnow()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            (uuid4(), uuid4(), uuid4(), "Summary 1", ["topic1"], ["person1"], ["task1"],
             now - timedelta(hours=2), now - timedelta(hours=1), 10, "room1", "llm", "internal", now)
        ]
        mock_conn.execute.return_value = mock_result

        results = await conversation_summary.retrieve()

        assert len(results) == 1
        assert results[0].summary_text == "Summary 1"
        assert results[0].key_topics == ["topic1"]

    @pytest.mark.asyncio
    async def test_retrieve_with_user_id(self, conversation_summary, user_id, mock_conn):
        """user_id指定で取得"""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result

        await conversation_summary.retrieve(user_id=user_id)

        call_args = mock_conn.execute.call_args
        params = call_args[0][1]
        assert "user_id" in params

    @pytest.mark.asyncio
    async def test_retrieve_with_date_filters(self, conversation_summary, mock_conn):
        """日付フィルタで取得"""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result

        from_date = datetime.utcnow() - timedelta(days=7)
        to_date = datetime.utcnow()

        await conversation_summary.retrieve(from_date=from_date, to_date=to_date)

        call_args = mock_conn.execute.call_args
        params = call_args[0][1]
        assert "from_date" in params
        assert "to_date" in params

    @pytest.mark.asyncio
    async def test_retrieve_with_limit(self, conversation_summary, mock_conn):
        """limit指定で取得"""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result

        await conversation_summary.retrieve(limit=5)

        call_args = mock_conn.execute.call_args
        params = call_args[0][1]
        assert params["limit"] == 5

    @pytest.mark.asyncio
    async def test_retrieve_limit_capped_at_100(self, conversation_summary, mock_conn):
        """limitは100で制限"""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result

        await conversation_summary.retrieve(limit=500)

        call_args = mock_conn.execute.call_args
        params = call_args[0][1]
        assert params["limit"] == 100

    @pytest.mark.asyncio
    async def test_retrieve_with_offset(self, conversation_summary, mock_conn):
        """offset指定で取得"""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result

        await conversation_summary.retrieve(offset=10)

        call_args = mock_conn.execute.call_args
        params = call_args[0][1]
        assert params["offset"] == 10

    @pytest.mark.asyncio
    async def test_retrieve_with_none_arrays(self, conversation_summary, mock_conn):
        """配列がNoneの場合の処理"""
        now = datetime.utcnow()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            (uuid4(), uuid4(), uuid4(), "Summary", None, None, None,
             now - timedelta(hours=1), now, 5, None, "llm", "internal", now)
        ]
        mock_conn.execute.return_value = mock_result

        results = await conversation_summary.retrieve()

        assert results[0].key_topics == []
        assert results[0].mentioned_persons == []
        assert results[0].mentioned_tasks == []

    @pytest.mark.asyncio
    async def test_retrieve_database_error(self, conversation_summary, mock_conn):
        """DB取得エラー"""
        from lib.memory.exceptions import DatabaseError

        mock_conn.execute.side_effect = Exception("DB error")

        with pytest.raises(DatabaseError):
            await conversation_summary.retrieve()

    @pytest.mark.asyncio
    async def test_retrieve_string_user_id(self, conversation_summary, mock_conn):
        """文字列user_idでの取得"""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result

        user_id_str = str(uuid4())
        await conversation_summary.retrieve(user_id=user_id_str)

        # エラーなく実行完了


# ================================================================
# generate_and_save メソッドテスト
# ================================================================

class TestConversationSummaryGenerateAndSave:
    """generate_and_saveメソッドのテスト"""

    @pytest.mark.asyncio
    async def test_generate_and_save_not_enough_messages(self, conversation_summary, user_id):
        """メッセージ数不足"""
        from lib.memory.constants import MemoryParameters

        history = [{"role": "user", "content": "Hi"}]  # 1件のみ

        result = await conversation_summary.generate_and_save(
            user_id=user_id,
            conversation_history=history
        )

        assert result.success is False
        assert f"need {MemoryParameters.SUMMARY_TRIGGER_COUNT}" in result.message

    @pytest.mark.asyncio
    async def test_generate_and_save_success(self, conversation_summary, user_id, mock_conn):
        """正常な生成と保存"""
        from lib.memory.constants import MemoryParameters

        # LLMレスポンスのモック
        with patch.object(
            conversation_summary,
            '_generate_summary',
            new_callable=AsyncMock
        ) as mock_generate:
            mock_generate.return_value = {
                "summary": "Test summary",
                "key_topics": ["topic1"],
                "mentioned_persons": ["person1"],
                "mentioned_tasks": ["task1"]
            }

            # DB保存のモック
            summary_id = uuid4()
            mock_result = MagicMock()
            mock_result.fetchone.return_value = (summary_id,)
            mock_conn.execute.return_value = mock_result

            now = datetime.utcnow()
            history = [
                {"role": "user", "content": f"Message {i}", "timestamp": now - timedelta(minutes=i)}
                for i in range(MemoryParameters.SUMMARY_TRIGGER_COUNT)
            ]

            result = await conversation_summary.generate_and_save(
                user_id=user_id,
                conversation_history=history
            )

            assert result.success is True
            mock_generate.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_and_save_with_room_id(self, conversation_summary, user_id, mock_conn):
        """room_id指定での生成と保存"""
        from lib.memory.constants import MemoryParameters

        with patch.object(
            conversation_summary,
            '_generate_summary',
            new_callable=AsyncMock
        ) as mock_generate:
            mock_generate.return_value = {
                "summary": "Test",
                "key_topics": [],
                "mentioned_persons": [],
                "mentioned_tasks": []
            }

            summary_id = uuid4()
            mock_result = MagicMock()
            mock_result.fetchone.return_value = (summary_id,)
            mock_conn.execute.return_value = mock_result

            now = datetime.utcnow()
            history = [
                {"role": "user", "content": f"Msg {i}", "timestamp": now}
                for i in range(MemoryParameters.SUMMARY_TRIGGER_COUNT)
            ]

            result = await conversation_summary.generate_and_save(
                user_id=user_id,
                conversation_history=history,
                room_id="room123"
            )

            assert result.success is True

    @pytest.mark.asyncio
    async def test_generate_and_save_no_timestamps(self, conversation_summary, user_id, mock_conn):
        """タイムスタンプなしの会話履歴"""
        from lib.memory.constants import MemoryParameters

        with patch.object(
            conversation_summary,
            '_generate_summary',
            new_callable=AsyncMock
        ) as mock_generate:
            mock_generate.return_value = {
                "summary": "Test",
                "key_topics": [],
                "mentioned_persons": [],
                "mentioned_tasks": []
            }

            summary_id = uuid4()
            mock_result = MagicMock()
            mock_result.fetchone.return_value = (summary_id,)
            mock_conn.execute.return_value = mock_result

            # タイムスタンプなしの履歴
            history = [
                {"role": "user", "content": f"Msg {i}"}
                for i in range(MemoryParameters.SUMMARY_TRIGGER_COUNT)
            ]

            result = await conversation_summary.generate_and_save(
                user_id=user_id,
                conversation_history=history
            )

            assert result.success is True

    @pytest.mark.asyncio
    async def test_generate_and_save_with_created_at(self, conversation_summary, user_id, mock_conn):
        """created_atフィールドでのタイムスタンプ取得"""
        from lib.memory.constants import MemoryParameters

        with patch.object(
            conversation_summary,
            '_generate_summary',
            new_callable=AsyncMock
        ) as mock_generate:
            mock_generate.return_value = {
                "summary": "Test",
                "key_topics": [],
                "mentioned_persons": [],
                "mentioned_tasks": []
            }

            summary_id = uuid4()
            mock_result = MagicMock()
            mock_result.fetchone.return_value = (summary_id,)
            mock_conn.execute.return_value = mock_result

            now = datetime.utcnow()
            history = [
                {"role": "user", "content": f"Msg {i}", "created_at": now - timedelta(minutes=i)}
                for i in range(MemoryParameters.SUMMARY_TRIGGER_COUNT)
            ]

            result = await conversation_summary.generate_and_save(
                user_id=user_id,
                conversation_history=history
            )

            assert result.success is True


# ================================================================
# get_recent_context メソッドテスト
# ================================================================

class TestConversationSummaryGetRecentContext:
    """get_recent_contextメソッドのテスト"""

    @pytest.mark.asyncio
    async def test_get_recent_context_empty(self, conversation_summary, user_id, mock_conn):
        """サマリーがない場合"""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result

        result = await conversation_summary.get_recent_context(user_id=user_id)

        assert result == ""

    @pytest.mark.asyncio
    async def test_get_recent_context_with_summaries(self, conversation_summary, user_id, mock_conn):
        """サマリーがある場合"""
        now = datetime.utcnow()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            (uuid4(), uuid4(), user_id, "Summary 1", ["topic1", "topic2"], [], [],
             now - timedelta(hours=2), now - timedelta(hours=1), 10, None, "llm", "internal", now),
            (uuid4(), uuid4(), user_id, "Summary 2", [], [], [],
             now - timedelta(hours=4), now - timedelta(hours=3), 5, None, "llm", "internal", now)
        ]
        mock_conn.execute.return_value = mock_result

        result = await conversation_summary.get_recent_context(user_id=user_id)

        assert "Summary 1" in result
        assert "Summary 2" in result
        assert "topic1" in result
        assert "topic2" in result

    @pytest.mark.asyncio
    async def test_get_recent_context_custom_days(self, conversation_summary, user_id, mock_conn):
        """カスタム日数指定"""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result

        await conversation_summary.get_recent_context(user_id=user_id, days=30)

        call_args = mock_conn.execute.call_args
        params = call_args[0][1]
        # from_dateが30日前になっていることを確認
        assert "from_date" in params

    @pytest.mark.asyncio
    async def test_get_recent_context_formatting(self, conversation_summary, user_id, mock_conn):
        """フォーマットの確認"""
        now = datetime(2026, 2, 4, 12, 0, 0)
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            (uuid4(), uuid4(), user_id, "Test summary text", ["topic_a"], [], [],
             now - timedelta(hours=1), now, 10, None, "llm", "internal", now)
        ]
        mock_conn.execute.return_value = mock_result

        result = await conversation_summary.get_recent_context(user_id=user_id)

        assert "2026-02-04" in result
        assert "Test summary text" in result
        assert "topic_a" in result


# ================================================================
# _format_conversation_history メソッドテスト
# ================================================================

class TestFormatConversationHistory:
    """_format_conversation_historyメソッドのテスト"""

    def test_format_basic(self, conversation_summary):
        """基本フォーマット"""
        history = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"}
        ]

        result = conversation_summary._format_conversation_history(history)

        assert "user: Hello" in result
        assert "assistant: Hi there" in result

    def test_format_with_timestamp(self, conversation_summary):
        """タイムスタンプ付きフォーマット"""
        history = [
            {"role": "user", "content": "Hello", "timestamp": "2026-02-04 10:00:00"}
        ]

        result = conversation_summary._format_conversation_history(history)

        assert "[2026-02-04 10:00:00]" in result
        assert "user: Hello" in result

    def test_format_empty_history(self, conversation_summary):
        """空の履歴"""
        result = conversation_summary._format_conversation_history([])

        assert result == ""

    def test_format_with_message_field(self, conversation_summary):
        """messageフィールドでのコンテンツ取得"""
        history = [
            {"role": "user", "message": "Using message field"}
        ]

        result = conversation_summary._format_conversation_history(history)

        assert "Using message field" in result

    def test_format_missing_role(self, conversation_summary):
        """roleがない場合のデフォルト"""
        history = [
            {"content": "No role specified"}
        ]

        result = conversation_summary._format_conversation_history(history)

        assert "user: No role specified" in result


# ================================================================
# _generate_summary メソッドテスト
# ================================================================

class TestGenerateSummary:
    """_generate_summaryメソッドのテスト"""

    @pytest.mark.asyncio
    async def test_generate_summary_success(self, conversation_summary):
        """正常なサマリー生成"""
        # プロンプトテンプレートとcall_llmの両方をモック
        mock_prompt = "Test prompt with {conversation_history}"
        with patch(
            'lib.memory.conversation_summary.CONVERSATION_SUMMARY_PROMPT',
            mock_prompt
        ):
            with patch.object(
                conversation_summary,
                'call_llm',
                new_callable=AsyncMock
            ) as mock_llm:
                mock_llm.return_value = '{"summary": "Generated summary", "key_topics": ["topic1"], "mentioned_persons": [], "mentioned_tasks": []}'

                result = await conversation_summary._generate_summary("test history")

                assert result["summary"] == "Generated summary"
                assert "topic1" in result["key_topics"]

    @pytest.mark.asyncio
    async def test_generate_summary_llm_error_fallback(self, conversation_summary):
        """LLMエラー時のフォールバック"""
        mock_prompt = "Test prompt with {conversation_history}"
        with patch(
            'lib.memory.conversation_summary.CONVERSATION_SUMMARY_PROMPT',
            mock_prompt
        ):
            with patch.object(
                conversation_summary,
                'call_llm',
                new_callable=AsyncMock
            ) as mock_llm:
                mock_llm.side_effect = Exception("LLM error")

                result = await conversation_summary._generate_summary("test history with 100 chars")

                # フォールバック結果を確認
                assert "サマリー生成に失敗" in result["summary"]
                assert result["key_topics"] == []
                assert result["mentioned_persons"] == []
                assert result["mentioned_tasks"] == []

    @pytest.mark.asyncio
    async def test_generate_summary_uses_prompt_template(self, conversation_summary):
        """プロンプトテンプレートの使用確認"""
        mock_prompt = "Test prompt with {conversation_history}"
        with patch(
            'lib.memory.conversation_summary.CONVERSATION_SUMMARY_PROMPT',
            mock_prompt
        ):
            with patch.object(
                conversation_summary,
                'call_llm',
                new_callable=AsyncMock
            ) as mock_llm:
                mock_llm.return_value = '{"summary": "test", "key_topics": [], "mentioned_persons": [], "mentioned_tasks": []}'

                await conversation_summary._generate_summary("My test history")

                call_args = mock_llm.call_args
                prompt = call_args[0][0]
                assert "My test history" in prompt

    @pytest.mark.asyncio
    async def test_generate_summary_json_extraction(self, conversation_summary):
        """JSONレスポンスの抽出テスト"""
        mock_prompt = "Test prompt with {conversation_history}"
        with patch(
            'lib.memory.conversation_summary.CONVERSATION_SUMMARY_PROMPT',
            mock_prompt
        ):
            with patch.object(
                conversation_summary,
                'call_llm',
                new_callable=AsyncMock
            ) as mock_llm:
                # JSONがコードブロックに包まれている場合
                mock_llm.return_value = '''```json
{"summary": "Extracted summary", "key_topics": ["extracted"], "mentioned_persons": ["person"], "mentioned_tasks": ["task"]}
```'''

                result = await conversation_summary._generate_summary("test")

                assert result["summary"] == "Extracted summary"
                assert result["key_topics"] == ["extracted"]


# ================================================================
# cleanup_old_summaries メソッドテスト
# ================================================================

class TestCleanupOldSummaries:
    """cleanup_old_summariesメソッドのテスト"""

    @pytest.mark.asyncio
    async def test_cleanup_success(self, conversation_summary, mock_conn):
        """正常な削除"""
        mock_result = MagicMock()
        mock_result.rowcount = 5
        mock_conn.execute.return_value = mock_result

        deleted = await conversation_summary.cleanup_old_summaries()

        assert deleted == 5
        mock_conn.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_with_custom_retention(self, conversation_summary, mock_conn):
        """カスタム保持期間での削除"""
        mock_result = MagicMock()
        mock_result.rowcount = 3
        mock_conn.execute.return_value = mock_result

        deleted = await conversation_summary.cleanup_old_summaries(retention_days=30)

        assert deleted == 3

    @pytest.mark.asyncio
    async def test_cleanup_default_retention(self, conversation_summary, mock_conn):
        """デフォルト保持期間での削除"""
        from lib.memory.constants import MemoryParameters

        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_conn.execute.return_value = mock_result

        await conversation_summary.cleanup_old_summaries()

        # デフォルト保持期間が使用されることを確認
        call_args = mock_conn.execute.call_args
        params = call_args[0][1]
        assert "cutoff_date" in params

    @pytest.mark.asyncio
    async def test_cleanup_database_error(self, conversation_summary, mock_conn):
        """DBエラー時の例外"""
        from lib.memory.exceptions import DatabaseError

        mock_conn.execute.side_effect = Exception("DB error")

        with pytest.raises(DatabaseError):
            await conversation_summary.cleanup_old_summaries()

    @pytest.mark.asyncio
    async def test_cleanup_no_records(self, conversation_summary, mock_conn):
        """削除対象なしの場合"""
        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_conn.execute.return_value = mock_result

        deleted = await conversation_summary.cleanup_old_summaries()

        assert deleted == 0


# ================================================================
# GeneratedBy Enum テスト
# ================================================================

class TestGeneratedByEnum:
    """GeneratedBy Enumのテスト"""

    def test_llm_value(self):
        """LLM値"""
        from lib.memory.constants import GeneratedBy
        assert GeneratedBy.LLM.value == "llm"

    def test_manual_value(self):
        """MANUAL値"""
        from lib.memory.constants import GeneratedBy
        assert GeneratedBy.MANUAL.value == "manual"


# ================================================================
# 統合テスト
# ================================================================

class TestConversationSummaryIntegration:
    """統合テスト"""

    @pytest.mark.asyncio
    async def test_full_workflow(self, conversation_summary, user_id, mock_conn):
        """保存→取得→削除の完全ワークフロー"""
        # 1. 保存
        summary_id = uuid4()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (summary_id,)
        mock_conn.execute.return_value = mock_result

        now = datetime.utcnow()
        save_result = await conversation_summary.save(
            user_id=user_id,
            summary_text="Integration test summary",
            key_topics=["integration", "test"],
            mentioned_persons=["tester"],
            mentioned_tasks=["testing"],
            conversation_start=now - timedelta(hours=1),
            conversation_end=now,
            message_count=20
        )

        assert save_result.success is True

        # 2. 取得
        mock_result.fetchall.return_value = [
            (summary_id, uuid4(), user_id, "Integration test summary",
             ["integration", "test"], ["tester"], ["testing"],
             now - timedelta(hours=1), now, 20, None, "llm", "internal", now)
        ]
        mock_conn.execute.return_value = mock_result

        summaries = await conversation_summary.retrieve(user_id=user_id)

        assert len(summaries) == 1
        assert summaries[0].summary_text == "Integration test summary"

        # 3. クリーンアップ
        mock_result.rowcount = 1
        mock_conn.execute.return_value = mock_result

        deleted = await conversation_summary.cleanup_old_summaries(retention_days=0)

        assert deleted >= 0


# ================================================================
# エッジケーステスト
# ================================================================

class TestEdgeCases:
    """エッジケーステスト"""

    def test_summary_data_empty_lists_are_independent(self):
        """各SummaryDataインスタンスのリストが独立している"""
        from lib.memory.conversation_summary import SummaryData

        data1 = SummaryData()
        data2 = SummaryData()

        data1.mentioned_persons.append("person1")
        data1.mentioned_tasks.append("task1")

        assert data2.mentioned_persons == []
        assert data2.mentioned_tasks == []

    @pytest.mark.asyncio
    async def test_save_empty_strings(self, conversation_summary, user_id, mock_conn):
        """空文字列での保存"""
        summary_id = uuid4()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (summary_id,)
        mock_conn.execute.return_value = mock_result

        now = datetime.utcnow()
        result = await conversation_summary.save(
            user_id=user_id,
            summary_text="",
            key_topics=[],
            mentioned_persons=[],
            mentioned_tasks=[],
            conversation_start=now,
            conversation_end=now,
            message_count=0
        )

        assert result.success is True

    @pytest.mark.asyncio
    async def test_retrieve_all_filters_combined(self, conversation_summary, user_id, mock_conn):
        """全フィルタの組み合わせ"""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result

        now = datetime.utcnow()
        await conversation_summary.retrieve(
            user_id=user_id,
            limit=5,
            offset=10,
            from_date=now - timedelta(days=30),
            to_date=now
        )

        call_args = mock_conn.execute.call_args
        params = call_args[0][1]

        assert "user_id" in params
        assert params["limit"] == 5
        assert params["offset"] == 10
        assert "from_date" in params
        assert "to_date" in params


# ================================================================
# 実行
# ================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
