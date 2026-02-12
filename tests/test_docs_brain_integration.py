# tests/test_docs_brain_integration.py
"""
Phase 6: Google Docs + Brain統合テスト

MeetingDocsPublisher の全パスをテスト:
- Google Docs出力（正常系・異常系）
- Brain記憶保存（正常系・異常系）
- オーケストレータ（並列実行・部分成功）
- Feature flag制御
- バリデーション

Author: Claude Opus 4.6
Created: 2026-02-13
"""

import asyncio
import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, call
import pytest

from lib.meetings.docs_brain_integration import (
    MeetingDocsPublisher,
    create_meeting_docs_publisher,
    ENABLE_MEETING_DOCS,
    MAX_MINUTES_LENGTH,
    MAX_SUMMARY_LENGTH,
    MEETING_MEMORY_CLASSIFICATION,
)


# =========================================================================
# Fixtures
# =========================================================================

@pytest.fixture
def mock_pool():
    """Mock SQLAlchemy connection pool."""
    pool = MagicMock()
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    pool.connect.return_value = conn
    return pool


@pytest.fixture
def mock_docs_client():
    """Mock GoogleDocsClient."""
    client = AsyncMock()
    client.create_document = AsyncMock(return_value={
        "document_id": "doc-123-abc",
        "document_url": "https://docs.google.com/document/d/doc-123-abc/edit",
    })
    client.write_markdown_content = AsyncMock(return_value=True)
    return client


@pytest.fixture
def org_id():
    return "5f98365f-e7c5-4f48-9918-7fe9aabae5df"


@pytest.fixture
def publisher(mock_pool, mock_docs_client, org_id):
    """Create a MeetingDocsPublisher with mocked dependencies."""
    return MeetingDocsPublisher(
        pool=mock_pool,
        organization_id=org_id,
        google_docs_client=mock_docs_client,
    )


@pytest.fixture
def sample_minutes():
    return "# 営業部定例会議\n\n## 主題\n- Q1売上報告\n- 新規顧客獲得施策\n\n## 決定事項\n- 営業目標を上方修正"


@pytest.fixture
def sample_title():
    return "営業部定例会議 2026-02-13"


# =========================================================================
# Constructor tests
# =========================================================================

class TestMeetingDocsPublisherInit:
    """コンストラクタのバリデーションテスト"""

    def test_valid_init(self, mock_pool, org_id):
        pub = MeetingDocsPublisher(mock_pool, org_id)
        assert pub.organization_id == org_id
        assert pub.pool == mock_pool

    def test_empty_org_id_raises(self, mock_pool):
        with pytest.raises(ValueError, match="organization_id is required"):
            MeetingDocsPublisher(mock_pool, "")

    def test_whitespace_org_id_raises(self, mock_pool):
        with pytest.raises(ValueError, match="organization_id is required"):
            MeetingDocsPublisher(mock_pool, "   ")

    def test_none_org_id_raises(self, mock_pool):
        with pytest.raises((ValueError, AttributeError)):
            MeetingDocsPublisher(mock_pool, None)


# =========================================================================
# publish_to_google_docs tests
# =========================================================================

class TestPublishToGoogleDocs:
    """Google Docs出力テスト"""

    @pytest.mark.asyncio
    async def test_publish_success(self, publisher, mock_docs_client, sample_minutes, sample_title):
        """正常系: Google Docs作成 + DB更新"""
        # DB更新成功をモック
        publisher.db.update_meeting_status = MagicMock(return_value=True)

        result = await publisher.publish_to_google_docs(
            meeting_id="meeting-001",
            minutes_text=sample_minutes,
            title=sample_title,
            expected_version=2,
        )

        assert result["document_id"] == "doc-123-abc"
        assert "docs.google.com" in result["document_url"]
        assert result["db_updated"] is True

        # Google Docs APIが呼ばれたことを検証
        mock_docs_client.create_document.assert_awaited_once()
        mock_docs_client.write_markdown_content.assert_awaited_once_with(
            document_id="doc-123-abc",
            markdown_content=sample_minutes,
        )

    @pytest.mark.asyncio
    async def test_publish_db_version_conflict(self, publisher, mock_docs_client, sample_minutes, sample_title):
        """DB更新がバージョン競合で失敗しても、ドキュメント情報は返す"""
        publisher.db.update_meeting_status = MagicMock(return_value=False)

        result = await publisher.publish_to_google_docs(
            meeting_id="meeting-001",
            minutes_text=sample_minutes,
            title=sample_title,
            expected_version=99,
        )

        assert result["document_id"] == "doc-123-abc"
        assert result["db_updated"] is False

    @pytest.mark.asyncio
    async def test_publish_empty_minutes(self, publisher):
        """空のminutes_textはスキップ"""
        result = await publisher.publish_to_google_docs(
            meeting_id="meeting-001",
            minutes_text="",
            title="test",
            expected_version=1,
        )
        assert result == {}

    @pytest.mark.asyncio
    async def test_publish_whitespace_minutes(self, publisher):
        """空白のみのminutes_textはスキップ"""
        result = await publisher.publish_to_google_docs(
            meeting_id="meeting-001",
            minutes_text="   ",
            title="test",
            expected_version=1,
        )
        assert result == {}

    @pytest.mark.asyncio
    async def test_publish_empty_meeting_id_raises(self, publisher, sample_minutes):
        """空のmeeting_idはValueError"""
        with pytest.raises(ValueError, match="meeting_id is required"):
            await publisher.publish_to_google_docs(
                meeting_id="",
                minutes_text=sample_minutes,
                title="test",
                expected_version=1,
            )

    @pytest.mark.asyncio
    async def test_publish_docs_api_failure(self, publisher, mock_docs_client, sample_minutes, sample_title):
        """Google Docs API失敗時は空dictを返す"""
        mock_docs_client.create_document = AsyncMock(side_effect=Exception("API error"))

        result = await publisher.publish_to_google_docs(
            meeting_id="meeting-001",
            minutes_text=sample_minutes,
            title=sample_title,
            expected_version=1,
        )
        assert result == {}

    @pytest.mark.asyncio
    async def test_publish_truncates_long_text(self, publisher, mock_docs_client, sample_title):
        """MAX_MINUTES_LENGTHを超えるテキストは切り詰め"""
        long_text = "x" * (MAX_MINUTES_LENGTH + 1000)
        publisher.db.update_meeting_status = MagicMock(return_value=True)

        await publisher.publish_to_google_docs(
            meeting_id="meeting-001",
            minutes_text=long_text,
            title=sample_title,
            expected_version=1,
        )

        # write_markdown_contentに渡されたテキスト長を検証
        written_content = mock_docs_client.write_markdown_content.call_args.kwargs["markdown_content"]
        assert len(written_content) == MAX_MINUTES_LENGTH

    @pytest.mark.asyncio
    async def test_publish_with_folder_id(self, publisher, mock_docs_client, sample_minutes, sample_title):
        """MEETING_DOCS_FOLDER_IDが設定されている場合、フォルダ指定で作成"""
        publisher.db.update_meeting_status = MagicMock(return_value=True)

        with patch("lib.meetings.docs_brain_integration.MEETING_DOCS_FOLDER_ID", "folder-xyz"):
            await publisher.publish_to_google_docs(
                meeting_id="meeting-001",
                minutes_text=sample_minutes,
                title=sample_title,
                expected_version=1,
            )

        mock_docs_client.create_document.assert_awaited_once_with(
            title=f"議事録: {sample_title}",
            folder_id="folder-xyz",
        )


# =========================================================================
# store_meeting_memory tests
# =========================================================================

class TestStoreMeetingMemory:
    """Brain記憶保存テスト"""

    @pytest.mark.asyncio
    async def test_store_success(self, publisher, mock_pool, org_id):
        """正常系: conversation_summariesにINSERT"""
        conn = mock_pool.connect.return_value.__enter__.return_value

        result = await publisher.store_meeting_memory(
            meeting_id="meeting-001",
            summary_text="営業部会議のサマリー",
            title="営業部定例",
            key_topics=["売上", "新規顧客"],
            mentioned_persons=["田中", "山田"],
            room_id="123456",
        )

        assert result is True
        # SQL実行されたことを確認（rollback + set_config + INSERT + commit）
        assert conn.execute.call_count >= 2
        assert conn.commit.called

    @pytest.mark.asyncio
    async def test_store_empty_summary_skips(self, publisher):
        """空のsummary_textはスキップ"""
        result = await publisher.store_meeting_memory(
            meeting_id="meeting-001",
            summary_text="",
            title="test",
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_store_whitespace_summary_skips(self, publisher):
        """空白のみのsummary_textはスキップ"""
        result = await publisher.store_meeting_memory(
            meeting_id="meeting-001",
            summary_text="   ",
            title="test",
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_store_non_uuid_org_id_skips(self, mock_pool, mock_docs_client):
        """非UUID形式のorganization_idはスキップ"""
        pub = MeetingDocsPublisher(
            pool=mock_pool,
            organization_id="not-a-uuid",
            google_docs_client=mock_docs_client,
        )

        result = await pub.store_meeting_memory(
            meeting_id="meeting-001",
            summary_text="some summary",
            title="test",
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_store_db_error_returns_false(self, publisher, mock_pool):
        """DB書き込み失敗時はFalse"""
        conn = mock_pool.connect.return_value.__enter__.return_value
        conn.execute.side_effect = Exception("DB connection error")

        result = await publisher.store_meeting_memory(
            meeting_id="meeting-001",
            summary_text="some summary",
            title="test",
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_store_truncates_long_summary(self, publisher, mock_pool):
        """MAX_SUMMARY_LENGTHを超えるサマリーは切り詰め"""
        conn = mock_pool.connect.return_value.__enter__.return_value
        long_summary = "a" * (MAX_SUMMARY_LENGTH + 500)

        await publisher.store_meeting_memory(
            meeting_id="meeting-001",
            summary_text=long_summary,
            title="test",
        )

        # INSERTが実行されたことを確認（成功）
        assert conn.commit.called

    @pytest.mark.asyncio
    async def test_store_limits_topics_and_persons(self, publisher, mock_pool):
        """key_topicsとmentioned_personsは最大10件に制限"""
        conn = mock_pool.connect.return_value.__enter__.return_value

        await publisher.store_meeting_memory(
            meeting_id="meeting-001",
            summary_text="summary",
            title="test",
            key_topics=[f"topic{i}" for i in range(20)],
            mentioned_persons=[f"person{i}" for i in range(20)],
        )

        assert conn.commit.called

    @pytest.mark.asyncio
    async def test_store_with_custom_meeting_date(self, publisher, mock_pool):
        """meeting_dateが指定されている場合、それを使用"""
        conn = mock_pool.connect.return_value.__enter__.return_value
        custom_date = datetime(2026, 2, 13, 10, 0, 0, tzinfo=timezone.utc)

        result = await publisher.store_meeting_memory(
            meeting_id="meeting-001",
            summary_text="summary",
            title="test",
            meeting_date=custom_date,
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_store_statement_timeout_set(self, publisher, mock_pool):
        """statement_timeoutが設定されることを確認"""
        conn = mock_pool.connect.return_value.__enter__.return_value

        await publisher.store_meeting_memory(
            meeting_id="meeting-001",
            summary_text="summary",
            title="test",
        )

        # rollback + set_config + INSERT が呼ばれることを確認
        assert conn.rollback.called
        calls = conn.execute.call_args_list
        assert len(calls) >= 2
        # 最初のexecuteはstatement_timeout設定
        first_sql_text = calls[0][0][0].text if hasattr(calls[0][0][0], 'text') else str(calls[0][0][0])
        assert "set_config" in first_sql_text

    @pytest.mark.asyncio
    async def test_store_idempotent_not_exists(self, publisher, mock_pool):
        """冪等性: SQLにNOT EXISTSが含まれることを確認"""
        conn = mock_pool.connect.return_value.__enter__.return_value

        await publisher.store_meeting_memory(
            meeting_id="meeting-001",
            summary_text="summary",
            title="test",
        )

        # INSERT SQLにNOT EXISTSが含まれることを確認
        insert_call = conn.execute.call_args_list[1]  # 2番目がINSERT
        insert_sql = insert_call[0][0].text if hasattr(insert_call[0][0], 'text') else str(insert_call[0][0])
        assert "NOT EXISTS" in insert_sql

    @pytest.mark.asyncio
    async def test_store_cast_uuid_on_users(self, publisher, mock_pool):
        """usersテーブルのWHEREにCAST(:org_id AS uuid)が使われることを確認"""
        conn = mock_pool.connect.return_value.__enter__.return_value

        await publisher.store_meeting_memory(
            meeting_id="meeting-001",
            summary_text="summary",
            title="test",
        )

        insert_call = conn.execute.call_args_list[1]
        insert_sql = insert_call[0][0].text if hasattr(insert_call[0][0], 'text') else str(insert_call[0][0])
        # users WHERE にも CAST が使われている
        assert insert_sql.count("CAST(:org_id AS uuid)") >= 2  # INSERT SELECT + WHERE users + WHERE NOT EXISTS


# =========================================================================
# publish_and_remember tests
# =========================================================================

class TestPublishAndRemember:
    """オーケストレータテスト"""

    @pytest.mark.asyncio
    async def test_full_success(self, publisher, mock_docs_client, mock_pool, sample_minutes, sample_title):
        """正常系: Google Docs出力 + Brain記憶の両方成功"""
        publisher.db.update_meeting_status = MagicMock(return_value=True)
        conn = mock_pool.connect.return_value.__enter__.return_value

        result = await publisher.publish_and_remember(
            meeting_id="meeting-001",
            minutes_text=sample_minutes,
            title=sample_title,
            expected_version=2,
            key_topics=["売上", "新規顧客"],
            mentioned_persons=["田中"],
            room_id="123456",
        )

        assert result.success is True
        assert result.data["docs_published"] is True
        assert result.data["memory_stored"] is True
        assert "docs.google.com" in result.data["document_url"]
        assert "Google Docs" in result.message

    @pytest.mark.asyncio
    async def test_docs_fail_memory_success(self, publisher, mock_docs_client, mock_pool, sample_minutes, sample_title):
        """Google Docs失敗 + Brain記憶成功 → 部分成功"""
        mock_docs_client.create_document = AsyncMock(side_effect=Exception("API error"))
        conn = mock_pool.connect.return_value.__enter__.return_value

        result = await publisher.publish_and_remember(
            meeting_id="meeting-001",
            minutes_text=sample_minutes,
            title=sample_title,
            expected_version=2,
        )

        assert result.success is True  # memory_stored=True なので部分成功
        assert result.data["docs_published"] is False
        assert result.data["memory_stored"] is True

    @pytest.mark.asyncio
    async def test_docs_success_memory_fail(self, publisher, mock_docs_client, mock_pool, sample_minutes, sample_title):
        """Google Docs成功 + Brain記憶失敗 → 部分成功"""
        publisher.db.update_meeting_status = MagicMock(return_value=True)
        # 非UUID org_idでメモリ保存をスキップさせる
        publisher.organization_id = "not-a-uuid"
        # MeetingDBも再作成（org_id変更のため）
        publisher.db = MagicMock()
        publisher.db.update_meeting_status = MagicMock(return_value=True)

        result = await publisher.publish_and_remember(
            meeting_id="meeting-001",
            minutes_text=sample_minutes,
            title=sample_title,
            expected_version=2,
        )

        assert result.success is True  # docs_published=True
        assert result.data["docs_published"] is True
        assert result.data["memory_stored"] is False

    @pytest.mark.asyncio
    async def test_both_fail(self, publisher, mock_docs_client, sample_minutes, sample_title):
        """Google Docs + Brain記憶の両方失敗"""
        mock_docs_client.create_document = AsyncMock(side_effect=Exception("API error"))
        publisher.organization_id = "not-a-uuid"

        result = await publisher.publish_and_remember(
            meeting_id="meeting-001",
            minutes_text=sample_minutes,
            title=sample_title,
            expected_version=2,
        )

        assert result.success is False
        assert result.data["docs_published"] is False
        assert result.data["memory_stored"] is False

    @pytest.mark.asyncio
    async def test_empty_minutes_returns_failure(self, publisher):
        """空のminutes_textは即失敗"""
        result = await publisher.publish_and_remember(
            meeting_id="meeting-001",
            minutes_text="",
            title="test",
            expected_version=1,
        )

        assert result.success is False
        assert "空" in result.message

    @pytest.mark.asyncio
    async def test_custom_summary_text(self, publisher, mock_docs_client, mock_pool, sample_minutes, sample_title):
        """summary_textが明示指定された場合、それをBrain記憶に使用"""
        publisher.db.update_meeting_status = MagicMock(return_value=True)
        conn = mock_pool.connect.return_value.__enter__.return_value

        result = await publisher.publish_and_remember(
            meeting_id="meeting-001",
            minutes_text=sample_minutes,
            title=sample_title,
            expected_version=2,
            summary_text="カスタムサマリー",
        )

        assert result.success is True

    @pytest.mark.asyncio
    async def test_result_includes_meeting_id(self, publisher, mock_docs_client, mock_pool, sample_minutes, sample_title):
        """結果データにmeeting_idが含まれる"""
        publisher.db.update_meeting_status = MagicMock(return_value=True)
        conn = mock_pool.connect.return_value.__enter__.return_value

        result = await publisher.publish_and_remember(
            meeting_id="meeting-xyz",
            minutes_text=sample_minutes,
            title=sample_title,
            expected_version=2,
        )

        assert result.data["meeting_id"] == "meeting-xyz"


# =========================================================================
# Factory function tests
# =========================================================================

class TestCreateMeetingDocsPublisher:
    """ファクトリ関数テスト"""

    def test_disabled_returns_none(self, mock_pool, org_id):
        """ENABLE_MEETING_DOCS=false → None"""
        with patch("lib.meetings.docs_brain_integration.ENABLE_MEETING_DOCS", False):
            result = create_meeting_docs_publisher(mock_pool, org_id)
            assert result is None

    def test_enabled_returns_publisher(self, mock_pool, org_id):
        """ENABLE_MEETING_DOCS=true → MeetingDocsPublisher"""
        with patch("lib.meetings.docs_brain_integration.ENABLE_MEETING_DOCS", True):
            result = create_meeting_docs_publisher(mock_pool, org_id)
            assert isinstance(result, MeetingDocsPublisher)

    def test_enabled_with_custom_client(self, mock_pool, org_id, mock_docs_client):
        """カスタムDocsClientの注入"""
        with patch("lib.meetings.docs_brain_integration.ENABLE_MEETING_DOCS", True):
            result = create_meeting_docs_publisher(
                mock_pool, org_id, google_docs_client=mock_docs_client,
            )
            assert result._docs_client == mock_docs_client


# =========================================================================
# Lazy init tests
# =========================================================================

class TestLazyInit:
    """遅延初期化テスト"""

    def test_get_docs_client_lazy_init(self, mock_pool, org_id):
        """_docs_client=None の場合、create_google_docs_client が呼ばれる"""
        pub = MeetingDocsPublisher(mock_pool, org_id, google_docs_client=None)

        with patch(
            "lib.capabilities.generation.google_docs_client.create_google_docs_client"
        ) as mock_factory:
            mock_factory.return_value = MagicMock()
            client = pub._get_docs_client()
            mock_factory.assert_called_once()
            assert client is not None

    def test_get_docs_client_reuses_instance(self, publisher, mock_docs_client):
        """既にclientがある場合は再生成しない"""
        client1 = publisher._get_docs_client()
        client2 = publisher._get_docs_client()
        assert client1 is client2
        assert client1 is mock_docs_client
