# tests/test_brain_memory_access.py
"""
BrainMemoryAccess（脳の記憶アクセス層）のユニットテスト

Phase B: 記憶統合のテストケース
- 各アダプターの正常系テスト
- エラーハンドリングテスト
- 境界値テスト
"""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

# テスト対象のインポート
from lib.brain.memory_access import (
    BrainMemoryAccess,
    ConversationMessage,
    ConversationSummaryData,
    UserPreferenceData,
    PersonInfo,
    TaskInfo,
    GoalInfo,
    KnowledgeInfo,
    InsightInfo,
)


# =============================================================================
# フィクスチャ
# =============================================================================


@pytest.fixture
def mock_pool():
    """データベース接続プールのモック"""
    pool = Mock()
    return pool


@pytest.fixture
def mock_firestore():
    """Firestoreクライアントのモック"""
    firestore = Mock()
    return firestore


@pytest.fixture
def brain_memory(mock_pool, mock_firestore):
    """BrainMemoryAccessインスタンス"""
    return BrainMemoryAccess(
        pool=mock_pool,
        org_id="org_test",
        firestore_db=mock_firestore,
    )


@pytest.fixture
def brain_memory_no_firestore(mock_pool):
    """Firestoreなしのインスタンス"""
    return BrainMemoryAccess(
        pool=mock_pool,
        org_id="org_test",
        firestore_db=None,
    )


@pytest.fixture
def brain_memory_uuid(mock_pool, mock_firestore):
    """UUID形式のorg_idを使用するBrainMemoryAccessインスタンス

    goals/insightsテーブルはUUID型のorganization_idを使用するため、
    これらのテストにはこのフィクスチャを使用する。
    """
    return BrainMemoryAccess(
        pool=mock_pool,
        org_id="550e8400-e29b-41d4-a716-446655440000",  # Valid UUID format
        firestore_db=mock_firestore,
    )


# =============================================================================
# データクラスのテスト
# =============================================================================


class TestDataClasses:
    """データクラスのテスト"""

    def test_conversation_message_to_dict(self):
        """ConversationMessageがdict変換できる"""
        msg = ConversationMessage(
            role="user",
            content="Hello",
            timestamp=datetime(2026, 1, 26, 12, 0, 0),
        )
        result = msg.to_dict()
        assert result["role"] == "user"
        assert result["content"] == "Hello"
        assert "2026-01-26" in result["timestamp"]

    def test_conversation_message_to_dict_no_timestamp(self):
        """タイムスタンプなしでもdict変換できる"""
        msg = ConversationMessage(role="assistant", content="Hi")
        result = msg.to_dict()
        assert result["timestamp"] is None

    def test_conversation_summary_data_to_dict(self):
        """ConversationSummaryDataがdict変換できる"""
        summary = ConversationSummaryData(
            id=uuid4(),
            summary_text="テストの要約",
            key_topics=["トピック1", "トピック2"],
            mentioned_persons=["山田", "田中"],
            mentioned_tasks=["タスクA"],
            message_count=10,
        )
        result = summary.to_dict()
        assert result["summary_text"] == "テストの要約"
        assert len(result["key_topics"]) == 2
        assert result["message_count"] == 10

    def test_user_preference_data_to_dict(self):
        """UserPreferenceDataがdict変換できる"""
        pref = UserPreferenceData(
            preference_type="response_style",
            preference_key="formality",
            preference_value="casual",
            confidence=0.8,
        )
        result = pref.to_dict()
        assert result["preference_type"] == "response_style"
        assert result["confidence"] == 0.8

    def test_person_info_to_dict(self):
        """PersonInfoがdict変換できる"""
        # 統一版PersonInfo（SoT: lib/brain/models.py）を使用
        person = PersonInfo(
            person_id=str(uuid4()),
            name="山田太郎",
            attributes={"役職": "部長", "部署": "営業部"},
        )
        result = person.to_dict()
        assert result["name"] == "山田太郎"
        assert result["attributes"]["役職"] == "部長"

    def test_task_info_to_dict(self):
        """TaskInfoがdict変換できる"""
        # 統一版TaskInfo（SoT: lib/brain/models.py）を使用
        task = TaskInfo(
            task_id="12345",
            body="テストタスク",
            summary="要約",
            status="open",
            due_date=datetime(2026, 1, 27, 18, 0, 0),  # limit_time -> due_date
            is_overdue=False,
        )
        result = task.to_dict()
        assert result["task_id"] == "12345"
        assert result["is_overdue"] is False

    def test_task_info_overdue(self):
        """期限超過フラグが正しく設定される"""
        task = TaskInfo(
            task_id="12345",
            body="期限切れタスク",
            is_overdue=True,
        )
        assert task.is_overdue is True

    def test_goal_info_to_dict(self):
        """GoalInfoがdict変換できる"""
        # 統一版GoalInfo（SoT: lib/brain/models.py）を使用
        goal = GoalInfo(
            goal_id=str(uuid4()),  # id -> goal_id
            title="売上目標達成",
            why="会社の成長のため",
            what="月間売上100万円",
            how="新規顧客開拓",
            status="active",
            progress=0.5,
        )
        result = goal.to_dict()
        assert result["title"] == "売上目標達成"
        assert result["progress"] == 0.5

    def test_knowledge_info_to_dict(self):
        """KnowledgeInfoがdict変換できる"""
        knowledge = KnowledgeInfo(
            id=uuid4(),
            keyword="有給",
            answer="有給休暇は年間20日付与されます",
            category="人事",
            relevance_score=0.95,
        )
        result = knowledge.to_dict()
        assert result["keyword"] == "有給"
        assert result["relevance_score"] == 0.95

    def test_insight_info_to_dict(self):
        """InsightInfoがdict変換できる"""
        insight = InsightInfo(
            id=uuid4(),
            insight_type="frequent_question",
            importance="high",
            title="同じ質問が繰り返されています",
            description="「有給の申請方法」が5回質問されました",
            recommended_action="FAQに追加することを検討してください",
            status="new",
        )
        result = insight.to_dict()
        assert result["insight_type"] == "frequent_question"
        assert result["importance"] == "high"


# =============================================================================
# BrainMemoryAccess 初期化テスト
# =============================================================================


class TestBrainMemoryAccessInit:
    """初期化テスト"""

    def test_init_basic(self, mock_pool):
        """基本的な初期化"""
        memory = BrainMemoryAccess(
            pool=mock_pool,
            org_id="org_test",
        )
        assert memory.org_id == "org_test"
        assert memory.pool is mock_pool
        assert memory.firestore_db is None

    def test_init_with_firestore(self, mock_pool, mock_firestore):
        """Firestore付きで初期化"""
        memory = BrainMemoryAccess(
            pool=mock_pool,
            org_id="org_test",
            firestore_db=mock_firestore,
        )
        assert memory.firestore_db is mock_firestore

    def test_validate_org_id(self, brain_memory):
        """organization_idの検証"""
        assert brain_memory.validate_org_id() is True

    def test_validate_org_id_empty(self, mock_pool):
        """空のorganization_id"""
        memory = BrainMemoryAccess(pool=mock_pool, org_id="")
        assert memory.validate_org_id() is False


# =============================================================================
# 会話履歴アダプターのテスト
# =============================================================================


class TestConversationHistoryAdapter:
    """会話履歴（Firestore）アダプターのテスト"""

    @pytest.mark.asyncio
    async def test_get_recent_conversation_no_firestore(self, brain_memory_no_firestore):
        """Firestoreが設定されていない場合は空リスト"""
        result = await brain_memory_no_firestore.get_recent_conversation("room1", "user1")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_recent_conversation_doc_not_exists(self, brain_memory, mock_firestore):
        """ドキュメントが存在しない場合"""
        mock_doc = Mock()
        mock_doc.exists = False
        mock_doc_ref = Mock()
        mock_doc_ref.get.return_value = mock_doc
        mock_firestore.collection.return_value.document.return_value = mock_doc_ref

        result = await brain_memory.get_recent_conversation("room1", "user1")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_recent_conversation_success(self, brain_memory, mock_firestore):
        """正常に会話履歴を取得"""
        mock_doc = Mock()
        mock_doc.exists = True
        mock_doc.to_dict.return_value = {
            "history": [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi there!"},
            ],
            "updated_at": datetime.now(timezone.utc),
        }
        mock_doc_ref = Mock()
        mock_doc_ref.get.return_value = mock_doc
        mock_firestore.collection.return_value.document.return_value = mock_doc_ref

        result = await brain_memory.get_recent_conversation("room1", "user1")
        assert len(result) == 2
        assert result[0].role == "user"
        assert result[0].content == "Hello"

    @pytest.mark.asyncio
    async def test_get_recent_conversation_expired(self, brain_memory, mock_firestore):
        """有効期限切れの履歴は返さない"""
        mock_doc = Mock()
        mock_doc.exists = True
        # 25時間前（有効期限24時間を超えている）
        old_time = datetime.now(timezone.utc) - timedelta(hours=25)
        mock_doc.to_dict.return_value = {
            "history": [{"role": "user", "content": "Old message"}],
            "updated_at": old_time,
        }
        mock_doc_ref = Mock()
        mock_doc_ref.get.return_value = mock_doc
        mock_firestore.collection.return_value.document.return_value = mock_doc_ref

        result = await brain_memory.get_recent_conversation("room1", "user1")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_recent_conversation_error(self, brain_memory, mock_firestore):
        """エラー時は空リストを返す"""
        mock_firestore.collection.side_effect = Exception("Firestore error")

        result = await brain_memory.get_recent_conversation("room1", "user1")
        assert result == []


# =============================================================================
# 会話要約アダプターのテスト
# =============================================================================


class TestConversationSummaryAdapter:
    """会話要約（B1）アダプターのテスト"""

    @pytest.mark.asyncio
    async def test_get_conversation_summary_non_uuid_org_id(self, brain_memory):
        """非UUID形式のorg_idの場合はクエリをスキップしてNoneを返す"""
        # brain_memoryはorg_id="org_test"（非UUID形式）
        result = await brain_memory.get_conversation_summary("user1")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_conversation_summary_not_found(self, brain_memory_uuid, mock_pool):
        """要約が見つからない場合"""
        mock_conn = Mock()
        mock_result = Mock()
        mock_result.fetchone.return_value = None
        mock_conn.execute.return_value = mock_result
        mock_pool.connect.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = Mock(return_value=False)

        result = await brain_memory_uuid.get_conversation_summary("user1")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_conversation_summary_success(self, brain_memory_uuid, mock_pool):
        """正常に要約を取得（UUID形式のorg_idが必要）"""
        test_id = uuid4()
        mock_conn = Mock()
        mock_result = Mock()
        mock_result.fetchone.return_value = (
            test_id,
            "テストの会話要約",
            ["トピック1"],
            ["山田"],
            ["タスクA"],
            5,
            datetime.now(),
        )
        mock_conn.execute.return_value = mock_result
        mock_pool.connect.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = Mock(return_value=False)

        result = await brain_memory_uuid.get_conversation_summary("user1")
        assert result is not None
        assert result.summary_text == "テストの会話要約"
        assert result.message_count == 5

    @pytest.mark.asyncio
    async def test_get_conversation_summary_error(self, brain_memory_uuid, mock_pool):
        """エラー時はNoneを返す"""
        mock_pool.connect.side_effect = Exception("DB error")

        result = await brain_memory_uuid.get_conversation_summary("user1")
        assert result is None


# =============================================================================
# ユーザー嗜好アダプターのテスト
# =============================================================================


class TestUserPreferencesAdapter:
    """ユーザー嗜好（B2）アダプターのテスト"""

    @pytest.mark.asyncio
    async def test_get_user_preferences_non_uuid_org_id(self, brain_memory):
        """非UUID形式のorg_idの場合はクエリをスキップして空リストを返す"""
        # brain_memoryはorg_id="org_test"（非UUID形式）
        result = await brain_memory.get_user_preferences("user1")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_user_preferences_empty(self, brain_memory_uuid, mock_pool):
        """嗜好がない場合は空リスト（UUID形式のorg_idが必要）"""
        mock_conn = Mock()
        mock_result = Mock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result
        mock_pool.connect.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = Mock(return_value=False)

        result = await brain_memory_uuid.get_user_preferences("user1")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_user_preferences_success(self, brain_memory_uuid, mock_pool):
        """正常に嗜好を取得（UUID形式のorg_idが必要）"""
        mock_conn = Mock()
        mock_result = Mock()
        mock_result.fetchall.return_value = [
            ("response_style", "formality", "casual", 0.9),
            ("feature_usage", "task_search", 50, 0.8),
        ]
        mock_conn.execute.return_value = mock_result
        mock_pool.connect.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = Mock(return_value=False)

        result = await brain_memory_uuid.get_user_preferences("user1")
        assert len(result) == 2
        assert result[0].preference_type == "response_style"
        assert result[0].confidence == 0.9


# =============================================================================
# 人物情報アダプターのテスト
# =============================================================================


class TestPersonInfoAdapter:
    """人物情報アダプターのテスト"""

    @pytest.mark.asyncio
    async def test_get_person_info_empty(self, brain_memory, mock_pool):
        """人物情報がない場合は空リスト"""
        mock_conn = Mock()
        mock_result = Mock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result
        mock_pool.connect.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = Mock(return_value=False)

        result = await brain_memory.get_person_info()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_person_info_success(self, brain_memory, mock_pool):
        """正常に人物情報を取得"""
        person_id = uuid4()
        mock_conn = Mock()

        # 人物リストのモック
        person_result = Mock()
        person_result.fetchall.return_value = [(person_id, "山田太郎")]

        # 属性のモック
        attr_result = Mock()
        attr_result.fetchall.return_value = [("役職", "部長"), ("部署", "営業部")]

        mock_conn.execute.side_effect = [person_result, attr_result]
        mock_pool.connect.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = Mock(return_value=False)

        result = await brain_memory.get_person_info()
        assert len(result) == 1
        assert result[0].name == "山田太郎"
        assert result[0].attributes["役職"] == "部長"


# =============================================================================
# タスク情報アダプターのテスト
# =============================================================================


class TestTaskInfoAdapter:
    """タスク情報アダプターのテスト"""

    @pytest.mark.asyncio
    async def test_get_recent_tasks_empty(self, brain_memory, mock_pool):
        """タスクがない場合は空リスト"""
        mock_conn = Mock()
        mock_result = Mock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result
        mock_pool.connect.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = Mock(return_value=False)

        result = await brain_memory.get_recent_tasks("user1")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_recent_tasks_success(self, brain_memory, mock_pool):
        """正常にタスクを取得"""
        tomorrow = datetime.now() + timedelta(days=1)
        mock_conn = Mock()
        mock_result = Mock()
        mock_result.fetchall.return_value = [
            ("12345", "テストタスク", "タスク要約", "open", tomorrow, "room1", "テストルーム", "山田", "田中"),
        ]
        mock_conn.execute.return_value = mock_result
        mock_pool.connect.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = Mock(return_value=False)

        result = await brain_memory.get_recent_tasks("user1")
        assert len(result) == 1
        assert result[0].task_id == "12345"
        assert result[0].is_overdue is False  # 明日が期限なので超過していない

    @pytest.mark.asyncio
    async def test_get_recent_tasks_overdue(self, brain_memory, mock_pool):
        """期限超過タスクの検出"""
        yesterday = datetime.now() - timedelta(days=1)
        mock_conn = Mock()
        mock_result = Mock()
        mock_result.fetchall.return_value = [
            ("12345", "期限切れタスク", None, "open", yesterday, "room1", "テストルーム", "山田", "田中"),
        ]
        mock_conn.execute.return_value = mock_result
        mock_pool.connect.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = Mock(return_value=False)

        result = await brain_memory.get_recent_tasks("user1")
        assert len(result) == 1
        assert result[0].is_overdue is True


# =============================================================================
# 目標情報アダプターのテスト
# =============================================================================


class TestGoalInfoAdapter:
    """目標情報アダプターのテスト"""

    @pytest.mark.asyncio
    async def test_get_active_goals_non_uuid_org_id(self, brain_memory):
        """非UUID形式のorg_idの場合はクエリをスキップして空リストを返す"""
        # brain_memoryはorg_id="org_test"（非UUID形式）
        result = await brain_memory.get_active_goals("user1")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_active_goals_empty(self, brain_memory_uuid, mock_pool):
        """目標がない場合は空リスト"""
        mock_conn = Mock()
        mock_result = Mock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result
        mock_pool.connect.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = Mock(return_value=False)

        result = await brain_memory_uuid.get_active_goals("user1")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_active_goals_success(self, brain_memory_uuid, mock_pool):
        """正常に目標を取得（UUID形式のorg_idが必要）"""
        goal_id = uuid4()
        deadline = datetime.now() + timedelta(days=30)
        mock_conn = Mock()
        mock_result = Mock()
        # 実際のgoalsテーブルのカラム: title, description, target_value, current_value, status, progress, deadline
        mock_result.fetchall.return_value = [
            (goal_id, "売上目標達成", "月100万円の売上", 1000000, 300000, "active", deadline),
        ]
        mock_conn.execute.return_value = mock_result
        mock_pool.connect.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = Mock(return_value=False)

        result = await brain_memory_uuid.get_active_goals("user1")
        assert len(result) == 1
        assert result[0].title == "売上目標達成"
        # progress = current_value / target_value * 100 = 300000 / 1000000 * 100 = 30.0%
        assert result[0].progress == 30.0


# =============================================================================
# 会社知識アダプターのテスト
# =============================================================================


class TestKnowledgeAdapter:
    """会社知識アダプターのテスト"""

    @pytest.mark.asyncio
    async def test_get_relevant_knowledge_empty_query(self, brain_memory):
        """クエリが空の場合は空リスト"""
        result = await brain_memory.get_relevant_knowledge("")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_relevant_knowledge_success(self, brain_memory, mock_pool):
        """正常に知識を取得

        Note: soulkun_knowledgeテーブルはkey/valueカラムを使用。
        relevance_scoreは類似度関数がないため固定値1.0を使用。
        """
        knowledge_id = uuid4()
        mock_conn = Mock()
        mock_result = Mock()
        # soulkun_knowledgeは id, key, value, category の4カラム
        mock_result.fetchall.return_value = [
            (knowledge_id, "有給", "有給休暇は年間20日です", "人事"),
        ]
        mock_conn.execute.return_value = mock_result
        mock_pool.connect.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = Mock(return_value=False)

        result = await brain_memory.get_relevant_knowledge("有給の日数")
        assert len(result) == 1
        assert result[0].keyword == "有給"
        assert result[0].relevance_score == 1.0  # 固定値（類似度関数なし）

    @pytest.mark.asyncio
    async def test_get_relevant_knowledge_error(self, brain_memory, mock_pool):
        """エラー時は空リストを返す"""
        mock_pool.connect.side_effect = Exception("DB error")

        result = await brain_memory.get_relevant_knowledge("有給")
        assert result == []


# =============================================================================
# インサイトアダプターのテスト
# =============================================================================


class TestInsightAdapter:
    """インサイトアダプターのテスト"""

    @pytest.mark.asyncio
    async def test_get_recent_insights_non_uuid_org_id(self, brain_memory):
        """非UUID形式のorg_idの場合はクエリをスキップして空リストを返す"""
        # brain_memoryはorg_id="org_test"（非UUID形式）
        result = await brain_memory.get_recent_insights()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_recent_insights_empty(self, brain_memory_uuid, mock_pool):
        """インサイトがない場合は空リスト（UUID形式のorg_idが必要）"""
        mock_conn = Mock()
        mock_result = Mock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result
        mock_pool.connect.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = Mock(return_value=False)

        result = await brain_memory_uuid.get_recent_insights()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_recent_insights_success(self, brain_memory_uuid, mock_pool):
        """正常にインサイトを取得（UUID形式のorg_idが必要）"""
        insight_id = uuid4()
        mock_conn = Mock()
        mock_result = Mock()
        mock_result.fetchall.return_value = [
            (insight_id, "frequent_question", "high", "同じ質問が多い", "詳細説明", "FAQに追加", "new", datetime.now()),
        ]
        mock_conn.execute.return_value = mock_result
        mock_pool.connect.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = Mock(return_value=False)

        result = await brain_memory_uuid.get_recent_insights()
        assert len(result) == 1
        assert result[0].insight_type == "frequent_question"
        assert result[0].importance == "high"


# =============================================================================
# 統合アクセス（get_all_context）のテスト
# =============================================================================


class TestGetAllContext:
    """統合アクセスのテスト"""

    @pytest.mark.asyncio
    async def test_get_all_context_empty(self, brain_memory, mock_pool, mock_firestore):
        """全て空の場合"""
        # Firestoreモック
        mock_doc = Mock()
        mock_doc.exists = False
        mock_doc_ref = Mock()
        mock_doc_ref.get.return_value = mock_doc
        mock_firestore.collection.return_value.document.return_value = mock_doc_ref

        # DBモック（空の結果）
        mock_conn = Mock()
        mock_result = Mock()
        mock_result.fetchone.return_value = None
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result
        mock_pool.connect.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = Mock(return_value=False)

        result = await brain_memory.get_all_context(
            room_id="room1",
            user_id="user1",
            sender_name="テスト太郎",
        )

        assert result["organization_id"] == "org_test"
        assert result["room_id"] == "room1"
        assert result["sender_name"] == "テスト太郎"
        assert result["recent_conversation"] == []
        assert result["recent_tasks"] == []

    @pytest.mark.asyncio
    async def test_get_all_context_partial_error(self, brain_memory, mock_pool, mock_firestore):
        """一部でエラーが発生しても他は取得できる"""
        # Firestoreはエラー
        mock_firestore.collection.side_effect = Exception("Firestore error")

        # DBは正常
        mock_conn = Mock()
        mock_result = Mock()
        mock_result.fetchone.return_value = None
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result
        mock_pool.connect.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = Mock(return_value=False)

        result = await brain_memory.get_all_context(
            room_id="room1",
            user_id="user1",
            sender_name="テスト太郎",
        )

        # エラーがあっても結果は返る
        assert result["organization_id"] == "org_test"
        assert result["recent_conversation"] == []


# =============================================================================
# get_context_summary のテスト
# =============================================================================


class TestGetContextSummary:
    """コンテキスト要約のテスト"""

    def test_get_context_summary_empty(self, brain_memory):
        """空のコンテキスト"""
        context = {
            "recent_conversation": [],
            "conversation_summary": None,
            "user_preferences": [],
            "person_info": [],
            "recent_tasks": [],
            "active_goals": [],
            "relevant_knowledge": [],
            "insights": [],
        }

        result = brain_memory.get_context_summary(context)
        assert result == "（記憶なし）"

    def test_get_context_summary_with_data(self, brain_memory):
        """データがある場合の要約"""
        context = {
            "recent_conversation": [],
            "conversation_summary": ConversationSummaryData(summary_text="会話の要約テスト"),
            "user_preferences": [
                UserPreferenceData(preference_key="style", preference_value="casual"),
            ],
            "person_info": [],
            "recent_tasks": [
                TaskInfo(task_id="1", body="タスク1", is_overdue=True),
                TaskInfo(task_id="2", body="タスク2", is_overdue=False),
            ],
            "active_goals": [
                GoalInfo(title="テスト目標"),
            ],
            "relevant_knowledge": [],
            "insights": [
                InsightInfo(importance="critical", title="重要"),
            ],
        }

        result = brain_memory.get_context_summary(context)

        assert "会話要約" in result
        assert "会話の要約テスト" in result
        assert "嗜好" in result
        assert "期限超過タスク" in result
        assert "1件" in result
        assert "未完了タスク" in result
        assert "2件" in result
        assert "目標" in result
        assert "テスト目標" in result
        assert "重要インサイト" in result

    def test_get_context_summary_dict_format(self, brain_memory):
        """dict形式のデータでも動作する"""
        context = {
            "recent_conversation": [],
            "conversation_summary": {"summary_text": "辞書形式の要約"},
            "user_preferences": [
                {"preference_key": "key1", "preference_value": "value1"},
            ],
            "person_info": [],
            "recent_tasks": [
                {"task_id": "1", "is_overdue": False},
            ],
            "active_goals": [
                {"title": "辞書形式目標"},
            ],
            "relevant_knowledge": [],
            "insights": [
                {"importance": "medium"},
            ],
        }

        result = brain_memory.get_context_summary(context)

        assert "辞書形式の要約" in result
        assert "辞書形式目標" in result


# =============================================================================
# 会話検索アダプターのテスト
# =============================================================================


class TestConversationSearchAdapter:
    """会話検索アダプターのテスト"""

    @pytest.mark.asyncio
    async def test_search_conversation_success(self, brain_memory, mock_pool):
        """正常に会話検索"""
        mock_conn = Mock()
        mock_result = Mock()
        mock_result.fetchall.return_value = [
            ("user", "テストメッセージ", datetime.now()),
        ]
        mock_conn.execute.return_value = mock_result
        mock_pool.connect.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = Mock(return_value=False)

        result = await brain_memory.search_conversation("テスト")
        assert len(result) == 1
        assert result[0].content == "テストメッセージ"

    @pytest.mark.asyncio
    async def test_search_conversation_error(self, brain_memory, mock_pool):
        """エラー時は空リストを返す"""
        mock_pool.connect.side_effect = Exception("DB error")

        result = await brain_memory.search_conversation("テスト")
        assert result == []
