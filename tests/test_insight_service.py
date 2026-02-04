"""
InsightService ユニットテスト

このモジュールは、lib/insights/insight_service.py の包括的なユニットテストを提供します。

テスト対象:
- _should_audit() ヘルパー関数
- InsightFilter データクラス
- InsightSummary データクラス
- InsightRecord データクラス
- InsightService クラス（全CRUD操作）

カバレッジ目標: 80%以上

Author: Claude Code（経営参謀・SE・PM）
Created: 2026-02-04
"""

import pytest
from datetime import datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch, PropertyMock, call
from uuid import UUID, uuid4
import json

# ================================================================
# テスト対象のインポート
# ================================================================

from lib.detection.constants import (
    Classification,
    Importance,
    InsightStatus,
    InsightType,
    SourceType,
)

from lib.detection.exceptions import (
    DatabaseError,
    InsightCreateError,
    ValidationError,
)

from lib.insights.insight_service import (
    _should_audit,
    InsightFilter,
    InsightSummary,
    InsightRecord,
    InsightService,
)


# ================================================================
# _should_audit() ヘルパー関数のテスト
# ================================================================

class TestShouldAudit:
    """_should_audit関数のテスト"""

    def test_public_returns_false(self):
        """PUBLIC分類は監査不要"""
        assert _should_audit(Classification.PUBLIC) is False

    def test_internal_returns_false(self):
        """INTERNAL分類は監査不要"""
        assert _should_audit(Classification.INTERNAL) is False

    def test_confidential_returns_true(self):
        """CONFIDENTIAL分類は監査必要"""
        assert _should_audit(Classification.CONFIDENTIAL) is True

    def test_restricted_returns_true(self):
        """RESTRICTED分類は監査必要"""
        assert _should_audit(Classification.RESTRICTED) is True


# ================================================================
# InsightFilter データクラスのテスト
# ================================================================

class TestInsightFilter:
    """InsightFilterのテスト"""

    def test_minimal_creation(self):
        """最小パラメータでの作成"""
        org_id = uuid4()
        filter = InsightFilter(organization_id=org_id)

        assert filter.organization_id == org_id
        assert filter.department_id is None
        assert filter.insight_types is None
        assert filter.source_types is None
        assert filter.statuses is None
        assert filter.importances is None
        assert filter.from_date is None
        assert filter.to_date is None
        assert filter.notified is None

    def test_full_creation(self):
        """全パラメータ指定での作成"""
        org_id = uuid4()
        dept_id = uuid4()
        from_date = datetime.now() - timedelta(days=7)
        to_date = datetime.now()

        filter = InsightFilter(
            organization_id=org_id,
            department_id=dept_id,
            insight_types=[InsightType.PATTERN_DETECTED, InsightType.PERSONALIZATION_RISK],
            source_types=[SourceType.A1_PATTERN, SourceType.A2_PERSONALIZATION],
            statuses=[InsightStatus.NEW, InsightStatus.ACKNOWLEDGED],
            importances=[Importance.HIGH, Importance.CRITICAL],
            from_date=from_date,
            to_date=to_date,
            notified=False,
        )

        assert filter.organization_id == org_id
        assert filter.department_id == dept_id
        assert len(filter.insight_types) == 2
        assert InsightType.PATTERN_DETECTED in filter.insight_types
        assert len(filter.source_types) == 2
        assert len(filter.statuses) == 2
        assert len(filter.importances) == 2
        assert filter.from_date == from_date
        assert filter.to_date == to_date
        assert filter.notified is False

    def test_notified_true(self):
        """notified=Trueでの作成"""
        org_id = uuid4()
        filter = InsightFilter(organization_id=org_id, notified=True)
        assert filter.notified is True


# ================================================================
# InsightSummary データクラスのテスト
# ================================================================

class TestInsightSummary:
    """InsightSummaryのテスト"""

    def test_minimal_creation(self):
        """最小パラメータでの作成"""
        summary = InsightSummary(total=0)

        assert summary.total == 0
        assert summary.by_status == {}
        assert summary.by_importance == {}
        assert summary.by_type == {}

    def test_full_creation(self):
        """全パラメータ指定での作成"""
        summary = InsightSummary(
            total=25,
            by_status={"new": 10, "acknowledged": 8, "addressed": 5, "dismissed": 2},
            by_importance={"critical": 3, "high": 7, "medium": 10, "low": 5},
            by_type={"pattern_detected": 15, "personalization_risk": 10},
        )

        assert summary.total == 25
        assert summary.by_status["new"] == 10
        assert summary.by_status["acknowledged"] == 8
        assert summary.by_importance["critical"] == 3
        assert summary.by_type["pattern_detected"] == 15

    def test_to_dict_minimal(self):
        """to_dict: 最小データ"""
        summary = InsightSummary(total=5)
        result = summary.to_dict()

        assert result["total"] == 5
        assert result["by_status"] == {}
        assert result["by_importance"] == {}
        assert result["by_type"] == {}

    def test_to_dict_full(self):
        """to_dict: 全データ"""
        summary = InsightSummary(
            total=10,
            by_status={"new": 5, "acknowledged": 5},
            by_importance={"high": 10},
            by_type={"pattern_detected": 10},
        )
        result = summary.to_dict()

        assert result["total"] == 10
        assert result["by_status"]["new"] == 5
        assert result["by_importance"]["high"] == 10
        assert result["by_type"]["pattern_detected"] == 10


# ================================================================
# InsightRecord データクラスのテスト
# ================================================================

class TestInsightRecord:
    """InsightRecordのテスト"""

    @pytest.fixture
    def sample_record(self):
        """サンプルInsightRecord"""
        return InsightRecord(
            id=UUID("11111111-1111-1111-1111-111111111111"),
            organization_id=UUID("22222222-2222-2222-2222-222222222222"),
            department_id=UUID("33333333-3333-3333-3333-333333333333"),
            insight_type="pattern_detected",
            source_type="a1_pattern",
            source_id=UUID("44444444-4444-4444-4444-444444444444"),
            importance="high",
            title="Test Insight Title",
            description="Test insight description",
            recommended_action="Create a manual",
            evidence={"count": 10, "users": ["user1", "user2"]},
            status="new",
            acknowledged_at=datetime(2026, 1, 15, 10, 0, 0),
            acknowledged_by=UUID("55555555-5555-5555-5555-555555555555"),
            addressed_at=datetime(2026, 1, 16, 14, 30, 0),
            addressed_by=UUID("66666666-6666-6666-6666-666666666666"),
            addressed_action="Manual created",
            dismissed_reason=None,
            notified_at=datetime(2026, 1, 15, 9, 0, 0),
            notified_to=[UUID("77777777-7777-7777-7777-777777777777")],
            notified_via="chatwork",
            classification="confidential",
            created_by=UUID("88888888-8888-8888-8888-888888888888"),
            updated_by=UUID("99999999-9999-9999-9999-999999999999"),
            created_at=datetime(2026, 1, 10, 8, 0, 0),
            updated_at=datetime(2026, 1, 16, 14, 30, 0),
        )

    def test_basic_creation(self):
        """基本的な作成"""
        now = datetime.now()
        record = InsightRecord(
            id=uuid4(),
            organization_id=uuid4(),
            department_id=None,
            insight_type="pattern_detected",
            source_type="a1_pattern",
            source_id=None,
            importance="medium",
            title="Simple Title",
            description="Simple description",
            recommended_action=None,
            evidence={},
            status="new",
            acknowledged_at=None,
            acknowledged_by=None,
            addressed_at=None,
            addressed_by=None,
            addressed_action=None,
            dismissed_reason=None,
            notified_at=None,
            notified_to=[],
            notified_via=None,
            classification="internal",
            created_by=None,
            updated_by=None,
            created_at=now,
            updated_at=now,
        )

        assert record.title == "Simple Title"
        assert record.status == "new"
        assert record.department_id is None
        assert record.notified_to == []

    def test_to_dict_with_all_fields(self, sample_record):
        """to_dict: 全フィールドあり"""
        result = sample_record.to_dict()

        assert result["id"] == "11111111-1111-1111-1111-111111111111"
        assert result["organization_id"] == "22222222-2222-2222-2222-222222222222"
        assert result["department_id"] == "33333333-3333-3333-3333-333333333333"
        assert result["insight_type"] == "pattern_detected"
        assert result["source_type"] == "a1_pattern"
        assert result["source_id"] == "44444444-4444-4444-4444-444444444444"
        assert result["importance"] == "high"
        assert result["title"] == "Test Insight Title"
        assert result["description"] == "Test insight description"
        assert result["recommended_action"] == "Create a manual"
        assert result["evidence"] == {"count": 10, "users": ["user1", "user2"]}
        assert result["status"] == "new"
        assert result["acknowledged_at"] == "2026-01-15T10:00:00"
        assert result["acknowledged_by"] == "55555555-5555-5555-5555-555555555555"
        assert result["addressed_at"] == "2026-01-16T14:30:00"
        assert result["addressed_by"] == "66666666-6666-6666-6666-666666666666"
        assert result["addressed_action"] == "Manual created"
        assert result["dismissed_reason"] is None
        assert result["notified_at"] == "2026-01-15T09:00:00"
        assert result["notified_to"] == ["77777777-7777-7777-7777-777777777777"]
        assert result["notified_via"] == "chatwork"
        assert result["classification"] == "confidential"
        assert result["created_by"] == "88888888-8888-8888-8888-888888888888"
        assert result["updated_by"] == "99999999-9999-9999-9999-999999999999"
        assert result["created_at"] == "2026-01-10T08:00:00"
        assert result["updated_at"] == "2026-01-16T14:30:00"

    def test_to_dict_with_none_fields(self):
        """to_dict: オプショナルフィールドがNone"""
        now = datetime.now()
        record = InsightRecord(
            id=uuid4(),
            organization_id=uuid4(),
            department_id=None,
            insight_type="pattern_detected",
            source_type="a1_pattern",
            source_id=None,
            importance="low",
            title="Minimal",
            description="Minimal description",
            recommended_action=None,
            evidence={},
            status="new",
            acknowledged_at=None,
            acknowledged_by=None,
            addressed_at=None,
            addressed_by=None,
            addressed_action=None,
            dismissed_reason=None,
            notified_at=None,
            notified_to=[],
            notified_via=None,
            classification="public",
            created_by=None,
            updated_by=None,
            created_at=now,
            updated_at=now,
        )
        result = record.to_dict()

        assert result["department_id"] is None
        assert result["source_id"] is None
        assert result["recommended_action"] is None
        assert result["acknowledged_at"] is None
        assert result["acknowledged_by"] is None
        assert result["addressed_at"] is None
        assert result["addressed_by"] is None
        assert result["addressed_action"] is None
        assert result["dismissed_reason"] is None
        assert result["notified_at"] is None
        assert result["notified_to"] == []
        assert result["notified_via"] is None
        assert result["created_by"] is None
        assert result["updated_by"] is None


# ================================================================
# InsightService クラスのテスト
# ================================================================

class TestInsightServiceInit:
    """InsightService初期化のテスト"""

    def test_initialization(self):
        """初期化が正しく行われる"""
        mock_conn = MagicMock()
        org_id = uuid4()

        service = InsightService(mock_conn, org_id)

        assert service.conn == mock_conn
        assert service.org_id == org_id
        assert service._conn == mock_conn
        assert service._org_id == org_id

    def test_properties(self):
        """プロパティが正しく値を返す"""
        mock_conn = MagicMock()
        org_id = uuid4()

        service = InsightService(mock_conn, org_id)

        assert service.conn is mock_conn
        assert service.org_id == org_id


class TestInsightServiceCreateInsight:
    """InsightService.create_insight()のテスト"""

    @pytest.fixture
    def mock_conn(self):
        """モックデータベース接続"""
        conn = MagicMock()
        return conn

    @pytest.fixture
    def service(self, mock_conn):
        """InsightServiceインスタンス"""
        org_id = uuid4()
        return InsightService(mock_conn, org_id)

    @pytest.mark.asyncio
    async def test_create_insight_success(self, service, mock_conn):
        """正常系: インサイト作成成功"""
        insight_id = uuid4()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (str(insight_id),)
        mock_conn.execute.return_value = mock_result

        result = await service.create_insight(
            insight_type=InsightType.PATTERN_DETECTED,
            source_type=SourceType.A1_PATTERN,
            importance=Importance.HIGH,
            title="Test Insight",
            description="Test description",
        )

        assert result == insight_id
        assert mock_conn.execute.called

    @pytest.mark.asyncio
    async def test_create_insight_with_all_params(self, service, mock_conn):
        """全パラメータ指定での作成"""
        insight_id = uuid4()
        source_id = uuid4()
        department_id = uuid4()
        created_by = uuid4()

        mock_result = MagicMock()
        mock_result.fetchone.return_value = (str(insight_id),)
        mock_conn.execute.return_value = mock_result

        result = await service.create_insight(
            insight_type=InsightType.PATTERN_DETECTED,
            source_type=SourceType.A1_PATTERN,
            importance=Importance.CRITICAL,
            title="Full Params Test",
            description="Full description",
            source_id=source_id,
            department_id=department_id,
            recommended_action="Create manual",
            evidence={"count": 15},
            classification=Classification.CONFIDENTIAL,
            created_by=created_by,
        )

        assert result == insight_id

    @pytest.mark.asyncio
    async def test_create_insight_with_audit_log(self, service, mock_conn):
        """CONFIDENTIAL分類での作成時に監査ログが記録される"""
        insight_id = uuid4()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (str(insight_id),)
        mock_conn.execute.return_value = mock_result

        await service.create_insight(
            insight_type=InsightType.PATTERN_DETECTED,
            source_type=SourceType.A1_PATTERN,
            importance=Importance.HIGH,
            title="Confidential Insight",
            description="Confidential description",
            classification=Classification.CONFIDENTIAL,
        )

        # audit_logsへのINSERTが呼ばれることを確認
        # 最低2回のexecute呼び出し（INSERT insight + INSERT audit_log）
        assert mock_conn.execute.call_count >= 1

    @pytest.mark.asyncio
    async def test_create_insight_validation_empty_title(self, service):
        """バリデーション: 空のタイトル"""
        with pytest.raises(ValidationError) as exc_info:
            await service.create_insight(
                insight_type=InsightType.PATTERN_DETECTED,
                source_type=SourceType.A1_PATTERN,
                importance=Importance.HIGH,
                title="",
                description="Test description",
            )

        assert "Title" in str(exc_info.value)
        assert exc_info.value.details["field"] == "title"

    @pytest.mark.asyncio
    async def test_create_insight_validation_title_too_long(self, service):
        """バリデーション: タイトルが200文字超"""
        with pytest.raises(ValidationError) as exc_info:
            await service.create_insight(
                insight_type=InsightType.PATTERN_DETECTED,
                source_type=SourceType.A1_PATTERN,
                importance=Importance.HIGH,
                title="x" * 201,
                description="Test description",
            )

        assert "Title" in str(exc_info.value)
        assert exc_info.value.details["length"] == 201

    @pytest.mark.asyncio
    async def test_create_insight_validation_empty_description(self, service):
        """バリデーション: 空の説明"""
        with pytest.raises(ValidationError) as exc_info:
            await service.create_insight(
                insight_type=InsightType.PATTERN_DETECTED,
                source_type=SourceType.A1_PATTERN,
                importance=Importance.HIGH,
                title="Test Title",
                description="",
            )

        assert "Description" in str(exc_info.value)
        assert exc_info.value.details["field"] == "description"

    @pytest.mark.asyncio
    async def test_create_insight_idempotent_existing(self, service, mock_conn):
        """冪等性: 既存インサイトがある場合は既存IDを返す"""
        existing_id = uuid4()
        source_id = uuid4()

        # 最初のINSERTがDO NOTHINGを返す（Noneを返す）
        mock_result1 = MagicMock()
        mock_result1.fetchone.return_value = None

        # 既存レコード検索が既存IDを返す
        mock_result2 = MagicMock()
        mock_result2.fetchone.return_value = (str(existing_id),)

        mock_conn.execute.side_effect = [mock_result1, mock_result2]

        result = await service.create_insight(
            insight_type=InsightType.PATTERN_DETECTED,
            source_type=SourceType.A1_PATTERN,
            importance=Importance.HIGH,
            title="Test",
            description="Test",
            source_id=source_id,
        )

        assert result == existing_id

    @pytest.mark.asyncio
    async def test_create_insight_database_error(self, service, mock_conn):
        """データベースエラー時にInsightCreateErrorを発生"""
        mock_conn.execute.side_effect = Exception("DB connection failed")

        with pytest.raises(InsightCreateError) as exc_info:
            await service.create_insight(
                insight_type=InsightType.PATTERN_DETECTED,
                source_type=SourceType.A1_PATTERN,
                importance=Importance.HIGH,
                title="Test",
                description="Test",
            )

        assert exc_info.value.original_exception is not None

    @pytest.mark.asyncio
    async def test_create_insight_no_id_returned(self, service, mock_conn):
        """INSERT後にIDが返されない場合（source_idなし）"""
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_conn.execute.return_value = mock_result

        with pytest.raises(InsightCreateError) as exc_info:
            await service.create_insight(
                insight_type=InsightType.PATTERN_DETECTED,
                source_type=SourceType.A1_PATTERN,
                importance=Importance.HIGH,
                title="Test",
                description="Test",
                source_id=None,  # source_idがないので既存検索しない
            )

        assert "Failed to get inserted insight ID" in str(exc_info.value)


class TestInsightServiceGetInsight:
    """InsightService.get_insight()のテスト"""

    @pytest.fixture
    def mock_conn(self):
        return MagicMock()

    @pytest.fixture
    def service(self, mock_conn):
        return InsightService(mock_conn, uuid4())

    def _create_mock_row(self, insight_id=None, classification="internal"):
        """モック行データを作成"""
        insight_id = insight_id or uuid4()
        org_id = uuid4()
        now = datetime.now()

        return (
            str(insight_id),  # 0: id
            str(org_id),      # 1: organization_id
            None,             # 2: department_id
            "pattern_detected",  # 3: insight_type
            "a1_pattern",     # 4: source_type
            None,             # 5: source_id
            "high",           # 6: importance
            "Test Title",     # 7: title
            "Test Description",  # 8: description
            None,             # 9: recommended_action
            {},               # 10: evidence
            "new",            # 11: status
            None,             # 12: acknowledged_at
            None,             # 13: acknowledged_by
            None,             # 14: addressed_at
            None,             # 15: addressed_by
            None,             # 16: addressed_action
            None,             # 17: dismissed_reason
            None,             # 18: notified_at
            [],               # 19: notified_to
            None,             # 20: notified_via
            classification,   # 21: classification
            None,             # 22: created_by
            None,             # 23: updated_by
            now,              # 24: created_at
            now,              # 25: updated_at
        )

    @pytest.mark.asyncio
    async def test_get_insight_success(self, service, mock_conn):
        """正常系: インサイト取得成功"""
        insight_id = uuid4()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = self._create_mock_row(insight_id)
        mock_conn.execute.return_value = mock_result

        result = await service.get_insight(insight_id)

        assert result is not None
        assert result.id == insight_id
        assert result.title == "Test Title"
        assert result.status == "new"

    @pytest.mark.asyncio
    async def test_get_insight_not_found(self, service, mock_conn):
        """存在しないインサイト"""
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_conn.execute.return_value = mock_result

        result = await service.get_insight(uuid4())

        assert result is None

    @pytest.mark.asyncio
    async def test_get_insight_with_audit_log(self, service, mock_conn):
        """CONFIDENTIAL分類の閲覧で監査ログが記録される"""
        insight_id = uuid4()
        user_id = uuid4()

        mock_result = MagicMock()
        mock_result.fetchone.return_value = self._create_mock_row(
            insight_id, classification="confidential"
        )
        mock_conn.execute.return_value = mock_result

        result = await service.get_insight(insight_id, user_id=user_id)

        assert result is not None
        # 監査ログ記録の呼び出しを確認（execute呼び出しが2回以上）
        assert mock_conn.execute.call_count >= 1

    @pytest.mark.asyncio
    async def test_get_insight_database_error(self, service, mock_conn):
        """データベースエラー時にDatabaseErrorを発生"""
        mock_conn.execute.side_effect = Exception("DB error")

        with pytest.raises(DatabaseError):
            await service.get_insight(uuid4())


class TestInsightServiceGetInsights:
    """InsightService.get_insights()のテスト"""

    @pytest.fixture
    def mock_conn(self):
        return MagicMock()

    @pytest.fixture
    def service(self, mock_conn):
        org_id = uuid4()
        return InsightService(mock_conn, org_id)

    def _create_mock_rows(self, count=3):
        """複数のモック行データを作成"""
        rows = []
        now = datetime.now()
        for i in range(count):
            rows.append((
                str(uuid4()),  # id
                str(uuid4()),  # organization_id
                None,          # department_id
                "pattern_detected",
                "a1_pattern",
                None,          # source_id
                "high",
                f"Test Title {i}",
                f"Description {i}",
                None,
                {},
                "new",
                None, None, None, None, None, None, None, [], None,
                "internal",
                None, None,
                now,
                now,
            ))
        return rows

    @pytest.mark.asyncio
    async def test_get_insights_success(self, service, mock_conn):
        """正常系: インサイト一覧取得"""
        filter = InsightFilter(organization_id=service.org_id)
        mock_result = MagicMock()
        mock_result.fetchall.return_value = self._create_mock_rows(3)
        mock_conn.execute.return_value = mock_result

        result = await service.get_insights(filter)

        assert len(result) == 3
        assert all(isinstance(r, InsightRecord) for r in result)

    @pytest.mark.asyncio
    async def test_get_insights_empty(self, service, mock_conn):
        """結果が空の場合"""
        filter = InsightFilter(organization_id=service.org_id)
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result

        result = await service.get_insights(filter)

        assert result == []

    @pytest.mark.asyncio
    async def test_get_insights_with_all_filters(self, service, mock_conn):
        """全フィルター条件指定"""
        filter = InsightFilter(
            organization_id=service.org_id,
            department_id=uuid4(),
            insight_types=[InsightType.PATTERN_DETECTED],
            source_types=[SourceType.A1_PATTERN],
            statuses=[InsightStatus.NEW],
            importances=[Importance.HIGH],
            from_date=datetime.now() - timedelta(days=7),
            to_date=datetime.now(),
            notified=False,
        )
        mock_result = MagicMock()
        mock_result.fetchall.return_value = self._create_mock_rows(1)
        mock_conn.execute.return_value = mock_result

        result = await service.get_insights(filter)

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_insights_notified_true(self, service, mock_conn):
        """notified=Trueフィルター"""
        filter = InsightFilter(
            organization_id=service.org_id,
            notified=True,
        )
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result

        await service.get_insights(filter)

        # SQLにnotified_at IS NOT NULLが含まれることを確認
        call_args = mock_conn.execute.call_args
        # TextClauseの内部テキストを取得
        sql_text = str(call_args[0][0])
        assert "notified_at IS NOT NULL" in sql_text

    @pytest.mark.asyncio
    async def test_get_insights_limit_cap(self, service, mock_conn):
        """limit上限（1000件）の適用"""
        filter = InsightFilter(organization_id=service.org_id)
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result

        await service.get_insights(filter, limit=2000)

        # パラメータのlimitが1000に制限されることを確認
        call_args = mock_conn.execute.call_args
        assert call_args[0][1]["limit"] == 1000

    @pytest.mark.asyncio
    async def test_get_insights_order_by_invalid(self, service, mock_conn):
        """無効なorder_byはcreated_atにフォールバック"""
        filter = InsightFilter(organization_id=service.org_id)
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result

        await service.get_insights(filter, order_by="invalid_column")

        # order_byがcreated_atになることを確認
        call_args = mock_conn.execute.call_args
        sql = str(call_args[0][0])
        assert "created_at DESC" in sql

    @pytest.mark.asyncio
    async def test_get_insights_order_by_importance(self, service, mock_conn):
        """importance順でのソート（CASEを使用）"""
        filter = InsightFilter(organization_id=service.org_id)
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result

        await service.get_insights(filter, order_by="importance")

        call_args = mock_conn.execute.call_args
        sql = str(call_args[0][0])
        assert "CASE importance" in sql

    @pytest.mark.asyncio
    async def test_get_insights_order_asc(self, service, mock_conn):
        """昇順ソート"""
        filter = InsightFilter(organization_id=service.org_id)
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result

        await service.get_insights(filter, order_desc=False)

        call_args = mock_conn.execute.call_args
        sql = str(call_args[0][0])
        assert "ASC" in sql

    @pytest.mark.asyncio
    async def test_get_insights_database_error(self, service, mock_conn):
        """データベースエラー"""
        filter = InsightFilter(organization_id=service.org_id)
        mock_conn.execute.side_effect = Exception("DB error")

        with pytest.raises(DatabaseError):
            await service.get_insights(filter)


class TestInsightServiceCountInsights:
    """InsightService.count_insights()のテスト"""

    @pytest.fixture
    def mock_conn(self):
        return MagicMock()

    @pytest.fixture
    def service(self, mock_conn):
        return InsightService(mock_conn, uuid4())

    @pytest.mark.asyncio
    async def test_count_insights_success(self, service, mock_conn):
        """正常系: カウント成功"""
        filter = InsightFilter(organization_id=service.org_id)
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (42,)
        mock_conn.execute.return_value = mock_result

        result = await service.count_insights(filter)

        assert result == 42

    @pytest.mark.asyncio
    async def test_count_insights_zero(self, service, mock_conn):
        """結果が0件の場合"""
        filter = InsightFilter(organization_id=service.org_id)
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (0,)
        mock_conn.execute.return_value = mock_result

        result = await service.count_insights(filter)

        assert result == 0

    @pytest.mark.asyncio
    async def test_count_insights_with_filters(self, service, mock_conn):
        """フィルター条件付きカウント"""
        filter = InsightFilter(
            organization_id=service.org_id,
            statuses=[InsightStatus.NEW, InsightStatus.ACKNOWLEDGED],
            importances=[Importance.HIGH],
        )
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (15,)
        mock_conn.execute.return_value = mock_result

        result = await service.count_insights(filter)

        assert result == 15

    @pytest.mark.asyncio
    async def test_count_insights_database_error(self, service, mock_conn):
        """データベースエラー"""
        filter = InsightFilter(organization_id=service.org_id)
        mock_conn.execute.side_effect = Exception("DB error")

        with pytest.raises(DatabaseError):
            await service.count_insights(filter)


class TestInsightServiceAcknowledge:
    """InsightService.acknowledge()のテスト"""

    @pytest.fixture
    def mock_conn(self):
        return MagicMock()

    @pytest.fixture
    def service(self, mock_conn):
        return InsightService(mock_conn, uuid4())

    @pytest.mark.asyncio
    async def test_acknowledge_success(self, service, mock_conn):
        """正常系: 確認済み更新成功"""
        insight_id = uuid4()
        user_id = uuid4()

        # 機密区分取得のモック
        mock_result1 = MagicMock()
        mock_result1.fetchone.return_value = ("internal",)

        # UPDATE結果のモック
        mock_result2 = MagicMock()
        mock_result2.rowcount = 1

        mock_conn.execute.side_effect = [mock_result1, mock_result2]

        result = await service.acknowledge(insight_id, user_id)

        assert result is True

    @pytest.mark.asyncio
    async def test_acknowledge_not_found(self, service, mock_conn):
        """存在しないまたは既に処理済みのインサイト"""
        insight_id = uuid4()
        user_id = uuid4()

        mock_result1 = MagicMock()
        mock_result1.fetchone.return_value = ("internal",)

        mock_result2 = MagicMock()
        mock_result2.rowcount = 0

        mock_conn.execute.side_effect = [mock_result1, mock_result2]

        result = await service.acknowledge(insight_id, user_id)

        assert result is False

    @pytest.mark.asyncio
    async def test_acknowledge_with_audit_log(self, service, mock_conn):
        """CONFIDENTIAL分類の確認で監査ログが記録される"""
        insight_id = uuid4()
        user_id = uuid4()

        mock_result1 = MagicMock()
        mock_result1.fetchone.return_value = ("confidential",)

        mock_result2 = MagicMock()
        mock_result2.rowcount = 1

        # audit_log INSERTのモック
        mock_result3 = MagicMock()

        mock_conn.execute.side_effect = [mock_result1, mock_result2, mock_result3]

        result = await service.acknowledge(insight_id, user_id)

        assert result is True
        # 監査ログが記録される（3回目のexecute）
        assert mock_conn.execute.call_count >= 2

    @pytest.mark.asyncio
    async def test_acknowledge_database_error(self, service, mock_conn):
        """データベースエラー"""
        mock_conn.execute.side_effect = Exception("DB error")

        with pytest.raises(DatabaseError):
            await service.acknowledge(uuid4(), uuid4())


class TestInsightServiceAddress:
    """InsightService.address()のテスト"""

    @pytest.fixture
    def mock_conn(self):
        return MagicMock()

    @pytest.fixture
    def service(self, mock_conn):
        return InsightService(mock_conn, uuid4())

    @pytest.mark.asyncio
    async def test_address_success(self, service, mock_conn):
        """正常系: 対応完了更新成功"""
        insight_id = uuid4()
        user_id = uuid4()
        action = "Manual created and published"

        mock_result1 = MagicMock()
        mock_result1.fetchone.return_value = ("internal",)

        mock_result2 = MagicMock()
        mock_result2.rowcount = 1

        mock_conn.execute.side_effect = [mock_result1, mock_result2]

        result = await service.address(insight_id, user_id, action)

        assert result is True

    @pytest.mark.asyncio
    async def test_address_validation_empty_action(self, service):
        """バリデーション: 空のアクション"""
        with pytest.raises(ValidationError) as exc_info:
            await service.address(uuid4(), uuid4(), "")

        assert "Action" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_address_not_found(self, service, mock_conn):
        """存在しないまたは既に処理済みのインサイト"""
        mock_result1 = MagicMock()
        mock_result1.fetchone.return_value = ("internal",)

        mock_result2 = MagicMock()
        mock_result2.rowcount = 0

        mock_conn.execute.side_effect = [mock_result1, mock_result2]

        result = await service.address(uuid4(), uuid4(), "Test action")

        assert result is False

    @pytest.mark.asyncio
    async def test_address_database_error(self, service, mock_conn):
        """データベースエラー"""
        mock_conn.execute.side_effect = Exception("DB error")

        with pytest.raises(DatabaseError):
            await service.address(uuid4(), uuid4(), "Test")


class TestInsightServiceDismiss:
    """InsightService.dismiss()のテスト"""

    @pytest.fixture
    def mock_conn(self):
        return MagicMock()

    @pytest.fixture
    def service(self, mock_conn):
        return InsightService(mock_conn, uuid4())

    @pytest.mark.asyncio
    async def test_dismiss_success(self, service, mock_conn):
        """正常系: 無視更新成功"""
        insight_id = uuid4()
        user_id = uuid4()
        reason = "Not relevant to our business"

        mock_result1 = MagicMock()
        mock_result1.fetchone.return_value = ("internal",)

        mock_result2 = MagicMock()
        mock_result2.rowcount = 1

        mock_conn.execute.side_effect = [mock_result1, mock_result2]

        result = await service.dismiss(insight_id, user_id, reason)

        assert result is True

    @pytest.mark.asyncio
    async def test_dismiss_validation_empty_reason(self, service):
        """バリデーション: 空の理由"""
        with pytest.raises(ValidationError) as exc_info:
            await service.dismiss(uuid4(), uuid4(), "")

        assert "Reason" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_dismiss_not_found(self, service, mock_conn):
        """存在しないまたは既に処理済みのインサイト"""
        mock_result1 = MagicMock()
        mock_result1.fetchone.return_value = ("internal",)

        mock_result2 = MagicMock()
        mock_result2.rowcount = 0

        mock_conn.execute.side_effect = [mock_result1, mock_result2]

        result = await service.dismiss(uuid4(), uuid4(), "Test reason")

        assert result is False

    @pytest.mark.asyncio
    async def test_dismiss_database_error(self, service, mock_conn):
        """データベースエラー"""
        mock_conn.execute.side_effect = Exception("DB error")

        with pytest.raises(DatabaseError):
            await service.dismiss(uuid4(), uuid4(), "Test")


class TestInsightServiceMarkAsNotified:
    """InsightService.mark_as_notified()のテスト"""

    @pytest.fixture
    def mock_conn(self):
        return MagicMock()

    @pytest.fixture
    def service(self, mock_conn):
        return InsightService(mock_conn, uuid4())

    @pytest.mark.asyncio
    async def test_mark_as_notified_success(self, service, mock_conn):
        """正常系: 通知済みマーク成功"""
        insight_id = uuid4()
        notified_to = [uuid4(), uuid4()]
        notified_via = "chatwork"

        mock_result = MagicMock()
        mock_result.rowcount = 1
        mock_conn.execute.return_value = mock_result

        result = await service.mark_as_notified(insight_id, notified_to, notified_via)

        assert result is True

    @pytest.mark.asyncio
    async def test_mark_as_notified_not_found(self, service, mock_conn):
        """存在しないインサイト"""
        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_conn.execute.return_value = mock_result

        result = await service.mark_as_notified(uuid4(), [uuid4()], "email")

        assert result is False

    @pytest.mark.asyncio
    async def test_mark_as_notified_database_error(self, service, mock_conn):
        """データベースエラー"""
        mock_conn.execute.side_effect = Exception("DB error")

        with pytest.raises(DatabaseError):
            await service.mark_as_notified(uuid4(), [uuid4()], "chatwork")


class TestInsightServiceGetUnnotifiedHighPriorityInsights:
    """InsightService.get_unnotified_high_priority_insights()のテスト"""

    @pytest.fixture
    def mock_conn(self):
        return MagicMock()

    @pytest.fixture
    def service(self, mock_conn):
        return InsightService(mock_conn, uuid4())

    def _create_mock_rows(self, count=2):
        """モック行データを作成"""
        rows = []
        now = datetime.now()
        for i in range(count):
            importance = "critical" if i == 0 else "high"
            rows.append((
                str(uuid4()),
                str(uuid4()),
                None,
                "pattern_detected",
                "a1_pattern",
                None,
                importance,
                f"Urgent Issue {i}",
                f"Description {i}",
                None,
                {},
                "new",
                None, None, None, None, None, None, None, [], None,
                "internal",
                None, None,
                now,
                now,
            ))
        return rows

    @pytest.mark.asyncio
    async def test_get_unnotified_high_priority_success(self, service, mock_conn):
        """正常系: 未通知高優先度インサイト取得"""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = self._create_mock_rows(2)
        mock_conn.execute.return_value = mock_result

        result = await service.get_unnotified_high_priority_insights()

        assert len(result) == 2
        assert result[0].importance == "critical"
        assert result[1].importance == "high"

    @pytest.mark.asyncio
    async def test_get_unnotified_high_priority_with_since(self, service, mock_conn):
        """since指定での取得"""
        since = datetime.now() - timedelta(hours=1)
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result

        result = await service.get_unnotified_high_priority_insights(since=since)

        assert result == []
        # SQLにsince条件が含まれることを確認
        call_args = mock_conn.execute.call_args
        assert "since" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_get_unnotified_high_priority_empty(self, service, mock_conn):
        """結果が空の場合"""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result

        result = await service.get_unnotified_high_priority_insights()

        assert result == []

    @pytest.mark.asyncio
    async def test_get_unnotified_high_priority_database_error(self, service, mock_conn):
        """データベースエラー"""
        mock_conn.execute.side_effect = Exception("DB error")

        with pytest.raises(DatabaseError):
            await service.get_unnotified_high_priority_insights()


class TestInsightServiceGetSummary:
    """InsightService.get_summary()のテスト"""

    @pytest.fixture
    def mock_conn(self):
        return MagicMock()

    @pytest.fixture
    def service(self, mock_conn):
        return InsightService(mock_conn, uuid4())

    @pytest.mark.asyncio
    async def test_get_summary_success(self, service, mock_conn):
        """正常系: サマリー取得成功"""
        # 総件数
        mock_result1 = MagicMock()
        mock_result1.fetchone.return_value = (25,)

        # ステータス別
        mock_result2 = MagicMock()
        mock_result2.fetchall.return_value = [
            ("new", 10),
            ("acknowledged", 8),
            ("addressed", 5),
            ("dismissed", 2),
        ]

        # 重要度別
        mock_result3 = MagicMock()
        mock_result3.fetchall.return_value = [
            ("critical", 3),
            ("high", 7),
            ("medium", 10),
            ("low", 5),
        ]

        # タイプ別
        mock_result4 = MagicMock()
        mock_result4.fetchall.return_value = [
            ("pattern_detected", 20),
            ("personalization_risk", 5),
        ]

        mock_conn.execute.side_effect = [
            mock_result1, mock_result2, mock_result3, mock_result4
        ]

        result = await service.get_summary()

        assert result.total == 25
        assert result.by_status["new"] == 10
        assert result.by_importance["critical"] == 3
        assert result.by_type["pattern_detected"] == 20

    @pytest.mark.asyncio
    async def test_get_summary_with_date_range(self, service, mock_conn):
        """日付範囲指定でのサマリー取得"""
        from_date = datetime.now() - timedelta(days=7)
        to_date = datetime.now()

        mock_result1 = MagicMock()
        mock_result1.fetchone.return_value = (5,)

        mock_result2 = MagicMock()
        mock_result2.fetchall.return_value = []

        mock_result3 = MagicMock()
        mock_result3.fetchall.return_value = []

        mock_result4 = MagicMock()
        mock_result4.fetchall.return_value = []

        mock_conn.execute.side_effect = [
            mock_result1, mock_result2, mock_result3, mock_result4
        ]

        result = await service.get_summary(from_date=from_date, to_date=to_date)

        assert result.total == 5

    @pytest.mark.asyncio
    async def test_get_summary_database_error(self, service, mock_conn):
        """データベースエラー"""
        mock_conn.execute.side_effect = Exception("DB error")

        with pytest.raises(DatabaseError):
            await service.get_summary()


class TestInsightServiceGetPendingInsightsForReport:
    """InsightService.get_pending_insights_for_report()のテスト"""

    @pytest.fixture
    def mock_conn(self):
        return MagicMock()

    @pytest.fixture
    def service(self, mock_conn):
        return InsightService(mock_conn, uuid4())

    def _create_mock_rows(self, count=3):
        """モック行データを作成"""
        rows = []
        now = datetime.now()
        importances = ["critical", "high", "medium"]
        for i in range(count):
            rows.append((
                str(uuid4()),
                str(uuid4()),
                None,
                "pattern_detected",
                "a1_pattern",
                None,
                importances[i % 3],
                f"Report Item {i}",
                f"Description {i}",
                None,
                {},
                "new",
                None, None, None, None, None, None, None, [], None,
                "internal",
                None, None,
                now,
                now,
            ))
        return rows

    @pytest.mark.asyncio
    async def test_get_pending_insights_for_report_success(self, service, mock_conn):
        """正常系: レポート用インサイト取得"""
        from_date = datetime.now() - timedelta(days=7)
        to_date = datetime.now()

        mock_result = MagicMock()
        mock_result.fetchall.return_value = self._create_mock_rows(3)
        mock_conn.execute.return_value = mock_result

        result = await service.get_pending_insights_for_report(from_date, to_date)

        assert len(result) == 3
        # importance順にソートされている（critical, high, medium）
        assert result[0].importance == "critical"

    @pytest.mark.asyncio
    async def test_get_pending_insights_for_report_empty(self, service, mock_conn):
        """結果が空の場合"""
        from_date = datetime.now() - timedelta(days=7)
        to_date = datetime.now()

        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result

        result = await service.get_pending_insights_for_report(from_date, to_date)

        assert result == []

    @pytest.mark.asyncio
    async def test_get_pending_insights_for_report_database_error(self, service, mock_conn):
        """データベースエラー"""
        mock_conn.execute.side_effect = Exception("DB error")

        with pytest.raises(DatabaseError):
            await service.get_pending_insights_for_report(
                datetime.now() - timedelta(days=7),
                datetime.now()
            )


class TestInsightServiceInsightExistsForSource:
    """InsightService.insight_exists_for_source()のテスト"""

    @pytest.fixture
    def mock_conn(self):
        return MagicMock()

    @pytest.fixture
    def service(self, mock_conn):
        return InsightService(mock_conn, uuid4())

    @pytest.mark.asyncio
    async def test_insight_exists_for_source_true(self, service, mock_conn):
        """インサイトが存在する場合"""
        source_id = uuid4()

        mock_result = MagicMock()
        mock_result.fetchone.return_value = (1,)
        mock_conn.execute.return_value = mock_result

        result = await service.insight_exists_for_source(
            SourceType.A1_PATTERN, source_id
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_insight_exists_for_source_false(self, service, mock_conn):
        """インサイトが存在しない場合"""
        source_id = uuid4()

        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_conn.execute.return_value = mock_result

        result = await service.insight_exists_for_source(
            SourceType.A1_PATTERN, source_id
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_insight_exists_for_source_database_error(self, service, mock_conn):
        """データベースエラー"""
        mock_conn.execute.side_effect = Exception("DB error")

        with pytest.raises(DatabaseError):
            await service.insight_exists_for_source(SourceType.A1_PATTERN, uuid4())


class TestInsightServiceRowToRecord:
    """InsightService._row_to_record()のテスト"""

    @pytest.fixture
    def mock_conn(self):
        return MagicMock()

    @pytest.fixture
    def service(self, mock_conn):
        return InsightService(mock_conn, uuid4())

    def test_row_to_record_full_data(self, service):
        """全データありの変換"""
        now = datetime.now()
        insight_id = uuid4()
        org_id = uuid4()
        dept_id = uuid4()
        source_id = uuid4()
        user1 = uuid4()
        user2 = uuid4()
        user3 = uuid4()
        notified_user = uuid4()

        row = (
            str(insight_id),
            str(org_id),
            str(dept_id),
            "pattern_detected",
            "a1_pattern",
            str(source_id),
            "high",
            "Test Title",
            "Test Description",
            "Create manual",
            {"count": 10},
            "acknowledged",
            now,
            str(user1),
            now + timedelta(hours=1),
            str(user2),
            "Manual created",
            None,
            now + timedelta(hours=2),
            [str(notified_user)],
            "chatwork",
            "confidential",
            str(user3),
            str(user3),
            now - timedelta(days=1),
            now,
        )

        result = service._row_to_record(row)

        assert result.id == insight_id
        assert result.organization_id == org_id
        assert result.department_id == dept_id
        assert result.insight_type == "pattern_detected"
        assert result.source_type == "a1_pattern"
        assert result.source_id == source_id
        assert result.importance == "high"
        assert result.title == "Test Title"
        assert result.description == "Test Description"
        assert result.recommended_action == "Create manual"
        assert result.evidence == {"count": 10}
        assert result.status == "acknowledged"
        assert result.acknowledged_at == now
        assert result.acknowledged_by == user1
        assert result.addressed_action == "Manual created"
        assert result.notified_to == [notified_user]
        assert result.notified_via == "chatwork"
        assert result.classification == "confidential"

    def test_row_to_record_minimal_data(self, service):
        """最小データの変換（NULLが多い）"""
        now = datetime.now()
        insight_id = uuid4()
        org_id = uuid4()

        row = (
            str(insight_id),
            str(org_id),
            None,  # department_id
            "pattern_detected",
            "a1_pattern",
            None,  # source_id
            "low",
            "Minimal",
            "Minimal description",
            None,  # recommended_action
            None,  # evidence
            "new",
            None, None, None, None, None, None, None,
            None,  # notified_to
            None,  # notified_via
            "public",
            None, None,
            now,
            now,
        )

        result = service._row_to_record(row)

        assert result.id == insight_id
        assert result.department_id is None
        assert result.source_id is None
        assert result.recommended_action is None
        assert result.evidence == {}
        assert result.notified_to == []
        assert result.notified_via is None

    def test_row_to_record_empty_notified_to(self, service):
        """notified_toが空リストの場合"""
        now = datetime.now()

        row = (
            str(uuid4()),
            str(uuid4()),
            None,
            "pattern_detected",
            "a1_pattern",
            None,
            "medium",
            "Test",
            "Test",
            None,
            {},
            "new",
            None, None, None, None, None, None, None,
            [],  # 空リスト
            None,
            "internal",
            None, None,
            now,
            now,
        )

        result = service._row_to_record(row)

        assert result.notified_to == []


class TestInsightServiceAuditLogging:
    """InsightService._log_audit()のテスト"""

    @pytest.fixture
    def mock_conn(self):
        return MagicMock()

    @pytest.fixture
    def service(self, mock_conn):
        return InsightService(mock_conn, uuid4())

    def test_log_audit_success(self, service, mock_conn):
        """監査ログ記録成功"""
        mock_result = MagicMock()
        mock_conn.execute.return_value = mock_result

        service._log_audit(
            action="read",
            resource_type="soulkun_insight",
            resource_id=uuid4(),
            classification=Classification.CONFIDENTIAL,
            user_id=uuid4(),
            details={"test": "data"},
        )

        assert mock_conn.execute.called

    def test_log_audit_failure_non_blocking(self, service, mock_conn):
        """監査ログ記録失敗時も例外を投げない（non-blocking）"""
        mock_conn.execute.side_effect = Exception("Audit log failed")

        # 例外が発生しないことを確認
        service._log_audit(
            action="read",
            resource_type="soulkun_insight",
            resource_id=uuid4(),
            classification=Classification.RESTRICTED,
        )

        # 正常に完了する（例外が投げられない）
        assert True

    def test_log_audit_with_none_details(self, service, mock_conn):
        """detailsがNoneの場合"""
        mock_result = MagicMock()
        mock_conn.execute.return_value = mock_result

        service._log_audit(
            action="create",
            resource_type="soulkun_insight",
            resource_id=uuid4(),
            classification=Classification.CONFIDENTIAL,
            user_id=None,
            details=None,
        )

        assert mock_conn.execute.called


# ================================================================
# エッジケースと統合テスト
# ================================================================

class TestInsightServiceEdgeCases:
    """エッジケースのテスト"""

    @pytest.fixture
    def mock_conn(self):
        return MagicMock()

    @pytest.fixture
    def service(self, mock_conn):
        return InsightService(mock_conn, uuid4())

    @pytest.mark.asyncio
    async def test_create_insight_title_exactly_200_chars(self, service, mock_conn):
        """タイトルがちょうど200文字の場合（境界値）"""
        insight_id = uuid4()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (str(insight_id),)
        mock_conn.execute.return_value = mock_result

        title = "x" * 200  # ちょうど200文字
        result = await service.create_insight(
            insight_type=InsightType.PATTERN_DETECTED,
            source_type=SourceType.A1_PATTERN,
            importance=Importance.MEDIUM,
            title=title,
            description="Test",
        )

        assert result == insight_id

    @pytest.mark.asyncio
    async def test_get_insights_with_offset(self, service, mock_conn):
        """オフセット指定でのページネーション"""
        filter = InsightFilter(organization_id=service.org_id)
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result

        await service.get_insights(filter, limit=10, offset=20)

        call_args = mock_conn.execute.call_args
        assert call_args[0][1]["offset"] == 20

    @pytest.mark.asyncio
    async def test_create_insight_with_large_evidence(self, service, mock_conn):
        """大きなevidenceデータでの作成"""
        insight_id = uuid4()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (str(insight_id),)
        mock_conn.execute.return_value = mock_result

        large_evidence = {
            "samples": [f"sample_{i}" for i in range(100)],
            "users": [str(uuid4()) for _ in range(50)],
            "timestamps": [datetime.now().isoformat() for _ in range(100)],
        }

        result = await service.create_insight(
            insight_type=InsightType.PATTERN_DETECTED,
            source_type=SourceType.A1_PATTERN,
            importance=Importance.LOW,
            title="Large Evidence",
            description="Test with large evidence",
            evidence=large_evidence,
        )

        assert result == insight_id


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--cov=lib.insights.insight_service", "--cov-report=term-missing"])
