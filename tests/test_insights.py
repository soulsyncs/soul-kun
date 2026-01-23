"""
Phase 2 進化版 A1: インサイト管理のユニットテスト

このモジュールは、lib/insights/ パッケージのユニットテストを提供します。

テスト対象:
- insight_service.py: InsightService
- weekly_report_service.py: WeeklyReportService

Author: Claude Code（経営参謀・SE・PM）
Created: 2026-01-23
"""

import pytest
from datetime import date, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch, PropertyMock
from uuid import UUID, uuid4

# ================================================================
# テスト対象のインポート
# ================================================================

from lib.detection.constants import (
    Classification,
    Importance,
    InsightStatus,
    InsightType,
    SourceType,
    WeeklyReportStatus,
)

from lib.detection.exceptions import (
    DatabaseError,
    InsightCreateError,
    ValidationError,
)

from lib.insights.insight_service import (
    InsightFilter,
    InsightSummary,
    InsightRecord,
    InsightService,
)

from lib.insights.weekly_report_service import (
    WeeklyReportRecord,
    ReportInsightItem,
    GeneratedReport,
    WeeklyReportService,
)


# ================================================================
# InsightFilter のテスト
# ================================================================

class TestInsightFilter:
    """InsightFilterのテスト"""

    def test_basic_creation(self):
        """基本的な作成"""
        org_id = uuid4()
        filter = InsightFilter(organization_id=org_id)
        assert filter.organization_id == org_id
        assert filter.department_id is None
        assert filter.insight_types is None
        assert filter.statuses is None

    def test_full_creation(self):
        """全パラメータ指定での作成"""
        org_id = uuid4()
        dept_id = uuid4()
        filter = InsightFilter(
            organization_id=org_id,
            department_id=dept_id,
            insight_types=[InsightType.PATTERN_DETECTED],
            source_types=[SourceType.A1_PATTERN],
            statuses=[InsightStatus.NEW, InsightStatus.ACKNOWLEDGED],
            importances=[Importance.HIGH, Importance.CRITICAL],
            from_date=datetime.now() - timedelta(days=7),
            to_date=datetime.now(),
            notified=False,
        )
        assert filter.department_id == dept_id
        assert len(filter.statuses) == 2
        assert len(filter.importances) == 2


# ================================================================
# InsightSummary のテスト
# ================================================================

class TestInsightSummary:
    """InsightSummaryのテスト"""

    def test_basic_creation(self):
        """基本的な作成"""
        summary = InsightSummary(total=10)
        assert summary.total == 10
        assert summary.by_status == {}
        assert summary.by_importance == {}
        assert summary.by_type == {}

    def test_full_creation(self):
        """全パラメータ指定での作成"""
        summary = InsightSummary(
            total=10,
            by_status={"new": 5, "acknowledged": 3, "addressed": 2},
            by_importance={"high": 3, "medium": 5, "low": 2},
            by_type={"pattern_detected": 10},
        )
        assert summary.by_status["new"] == 5
        assert summary.by_importance["high"] == 3

    def test_to_dict(self):
        """辞書変換"""
        summary = InsightSummary(
            total=10,
            by_status={"new": 5},
        )
        result = summary.to_dict()
        assert result["total"] == 10
        assert result["by_status"]["new"] == 5


# ================================================================
# InsightRecord のテスト
# ================================================================

class TestInsightRecord:
    """InsightRecordのテスト"""

    def test_basic_creation(self):
        """基本的な作成"""
        record = InsightRecord(
            id=uuid4(),
            organization_id=uuid4(),
            department_id=None,
            insight_type="pattern_detected",
            source_type="a1_pattern",
            source_id=None,
            importance="high",
            title="Test Insight",
            description="Test description",
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
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        assert record.title == "Test Insight"
        assert record.status == "new"

    def test_to_dict(self):
        """辞書変換"""
        record_id = uuid4()
        org_id = uuid4()
        now = datetime.now()
        record = InsightRecord(
            id=record_id,
            organization_id=org_id,
            department_id=None,
            insight_type="pattern_detected",
            source_type="a1_pattern",
            source_id=None,
            importance="high",
            title="Test Insight",
            description="Test description",
            recommended_action=None,
            evidence={"count": 10},
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
        result = record.to_dict()
        assert result["id"] == str(record_id)
        assert result["organization_id"] == str(org_id)
        assert result["evidence"] == {"count": 10}


# ================================================================
# InsightService のテスト
# ================================================================

class TestInsightService:
    """InsightServiceのテスト"""

    @pytest.fixture
    def mock_conn(self):
        """モックデータベース接続"""
        return MagicMock()

    @pytest.fixture
    def service(self, mock_conn):
        """InsightServiceインスタンス"""
        org_id = uuid4()
        return InsightService(mock_conn, org_id)

    def test_initialization(self, mock_conn):
        """初期化"""
        org_id = uuid4()
        service = InsightService(mock_conn, org_id)
        assert service.org_id == org_id
        assert service.conn == mock_conn

    @pytest.mark.asyncio
    async def test_create_insight_validation_title_empty(self, service):
        """タイトルが空の場合バリデーションエラー"""
        with pytest.raises(ValidationError) as exc_info:
            await service.create_insight(
                insight_type=InsightType.PATTERN_DETECTED,
                source_type=SourceType.A1_PATTERN,
                importance=Importance.HIGH,
                title="",
                description="Test description",
            )
        assert "Title" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_create_insight_validation_title_too_long(self, service):
        """タイトルが長すぎる場合バリデーションエラー"""
        with pytest.raises(ValidationError) as exc_info:
            await service.create_insight(
                insight_type=InsightType.PATTERN_DETECTED,
                source_type=SourceType.A1_PATTERN,
                importance=Importance.HIGH,
                title="x" * 201,  # 201文字
                description="Test description",
            )
        assert "Title" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_create_insight_validation_description_empty(self, service):
        """説明が空の場合バリデーションエラー"""
        with pytest.raises(ValidationError) as exc_info:
            await service.create_insight(
                insight_type=InsightType.PATTERN_DETECTED,
                source_type=SourceType.A1_PATTERN,
                importance=Importance.HIGH,
                title="Test",
                description="",
            )
        assert "Description" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_address_validation_action_required(self, service):
        """対応内容が空の場合バリデーションエラー"""
        with pytest.raises(ValidationError) as exc_info:
            await service.address(
                insight_id=uuid4(),
                user_id=uuid4(),
                action="",
            )
        assert "Action" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_dismiss_validation_reason_required(self, service):
        """無視理由が空の場合バリデーションエラー"""
        with pytest.raises(ValidationError) as exc_info:
            await service.dismiss(
                insight_id=uuid4(),
                user_id=uuid4(),
                reason="",
            )
        assert "Reason" in str(exc_info.value)


# ================================================================
# WeeklyReportRecord のテスト
# ================================================================

class TestWeeklyReportRecord:
    """WeeklyReportRecordのテスト"""

    def test_basic_creation(self):
        """基本的な作成"""
        record = WeeklyReportRecord(
            id=uuid4(),
            organization_id=uuid4(),
            week_start=date(2026, 1, 20),
            week_end=date(2026, 1, 26),
            report_content="# Test Report",
            insights_summary={"total": 5},
            included_insight_ids=[],
            sent_at=None,
            sent_to=[],
            sent_via=None,
            chatwork_room_id=None,
            chatwork_message_id=None,
            status="draft",
            error_message=None,
            retry_count=0,
            classification="internal",
            created_by=None,
            updated_by=None,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        assert record.week_start == date(2026, 1, 20)
        assert record.status == "draft"

    def test_to_dict(self):
        """辞書変換"""
        record_id = uuid4()
        org_id = uuid4()
        now = datetime.now()
        record = WeeklyReportRecord(
            id=record_id,
            organization_id=org_id,
            week_start=date(2026, 1, 20),
            week_end=date(2026, 1, 26),
            report_content="# Test Report",
            insights_summary={"total": 5},
            included_insight_ids=[],
            sent_at=None,
            sent_to=[],
            sent_via=None,
            chatwork_room_id=None,
            chatwork_message_id=None,
            status="draft",
            error_message=None,
            retry_count=0,
            classification="internal",
            created_by=None,
            updated_by=None,
            created_at=now,
            updated_at=now,
        )
        result = record.to_dict()
        assert result["id"] == str(record_id)
        assert result["week_start"] == "2026-01-20"
        assert result["insights_summary"]["total"] == 5


# ================================================================
# ReportInsightItem のテスト
# ================================================================

class TestReportInsightItem:
    """ReportInsightItemのテスト"""

    def test_basic_creation(self):
        """基本的な作成"""
        item = ReportInsightItem(
            id=uuid4(),
            insight_type="pattern_detected",
            importance="high",
            title="Test Insight",
            description="Test description",
            recommended_action="Create manual",
            status="new",
            created_at=datetime.now(),
        )
        assert item.title == "Test Insight"
        assert item.importance == "high"


# ================================================================
# GeneratedReport のテスト
# ================================================================

class TestGeneratedReport:
    """GeneratedReportのテスト"""

    def test_basic_creation(self):
        """基本的な作成"""
        insight_ids = [uuid4(), uuid4()]
        report = GeneratedReport(
            content="# Weekly Report",
            summary={"total": 2, "by_importance": {"high": 2}},
            insight_ids=insight_ids,
        )
        assert "Weekly Report" in report.content
        assert report.summary["total"] == 2
        assert len(report.insight_ids) == 2


# ================================================================
# WeeklyReportService のテスト
# ================================================================

class TestWeeklyReportService:
    """WeeklyReportServiceのテスト"""

    @pytest.fixture
    def mock_conn(self):
        """モックデータベース接続"""
        return MagicMock()

    @pytest.fixture
    def service(self, mock_conn):
        """WeeklyReportServiceインスタンス"""
        org_id = uuid4()
        return WeeklyReportService(mock_conn, org_id)

    def test_initialization(self, mock_conn):
        """初期化"""
        org_id = uuid4()
        service = WeeklyReportService(mock_conn, org_id)
        assert service.org_id == org_id
        assert service.conn == mock_conn

    def test_get_current_week_start(self, service):
        """今週の月曜日を取得"""
        result = service.get_current_week_start()
        # 結果は月曜日（weekday=0）
        assert result.weekday() == 0

    def test_get_last_week_start(self, service):
        """先週の月曜日を取得"""
        current = service.get_current_week_start()
        last = service.get_last_week_start()
        # 7日前
        assert (current - last).days == 7

    def test_is_report_day(self, service):
        """レポート送信日の判定"""
        # このテストは現在の曜日によって結果が変わる
        result = service.is_report_day()
        assert isinstance(result, bool)

    def test_get_importance_emoji(self, service):
        """重要度の絵文字取得"""
        assert service._get_importance_emoji("critical") == "🔴"
        assert service._get_importance_emoji("high") == "🟠"
        assert service._get_importance_emoji("medium") == "🟡"
        assert service._get_importance_emoji("low") == "🟢"
        assert service._get_importance_emoji("unknown") == "⚪"

    def test_get_insight_type_label(self, service):
        """インサイトタイプのラベル取得"""
        assert service._get_insight_type_label("pattern_detected") == "頻出パターン検出"
        assert service._get_insight_type_label("personalization_risk") == "属人化リスク"
        assert service._get_insight_type_label("bottleneck") == "ボトルネック"
        assert service._get_insight_type_label("emotion_change") == "感情変化"
        assert service._get_insight_type_label("unknown") == "unknown"

    def test_generate_report_content(self, service):
        """レポート本文の生成"""
        insights = [
            ReportInsightItem(
                id=uuid4(),
                insight_type="pattern_detected",
                importance="high",
                title="Test Insight 1",
                description="Description 1",
                recommended_action="Action 1",
                status="new",
                created_at=datetime.now(),
            ),
            ReportInsightItem(
                id=uuid4(),
                insight_type="pattern_detected",
                importance="medium",
                title="Test Insight 2",
                description="Description 2",
                recommended_action=None,
                status="new",
                created_at=datetime.now(),
            ),
        ]
        week_start = date(2026, 1, 20)
        week_end = date(2026, 1, 26)

        result = service._generate_report_content(
            insights=insights,
            week_start=week_start,
            week_end=week_end,
            organization_name="テスト組織",
        )

        assert isinstance(result, GeneratedReport)
        assert "ソウルくん週次レポート" in result.content
        assert "テスト組織" in result.content
        assert result.summary["total"] == 2
        assert result.summary["by_importance"]["high"] == 1
        assert result.summary["by_importance"]["medium"] == 1
        assert len(result.insight_ids) == 2

    def test_format_for_chatwork(self, service):
        """ChatWork形式へのフォーマット"""
        record = WeeklyReportRecord(
            id=uuid4(),
            organization_id=uuid4(),
            week_start=date(2026, 1, 20),
            week_end=date(2026, 1, 26),
            report_content="# Test Title\n\n## Section\n\n### Item\n\nContent\n\n---\n\n- List item",
            insights_summary={},
            included_insight_ids=[],
            sent_at=None,
            sent_to=[],
            sent_via=None,
            chatwork_room_id=None,
            chatwork_message_id=None,
            status="draft",
            error_message=None,
            retry_count=0,
            classification="internal",
            created_by=None,
            updated_by=None,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        result = service.format_for_chatwork(record)

        # ChatWork形式に変換されていること
        assert "[title]" in result  # # -> [title]
        assert "[hr]" in result  # --- -> [hr]
        assert "・" in result  # - -> ・


# ================================================================
# __init__.py のテスト（インポートテスト）
# ================================================================

class TestInsightsImports:
    """lib/insights/ からのインポートテスト"""

    def test_import_all(self):
        """__all__で定義されたものがインポートできること"""
        from lib.insights import (
            __version__,
            __author__,
            InsightFilter,
            InsightSummary,
            InsightRecord,
            InsightService,
            WeeklyReportRecord,
            ReportInsightItem,
            GeneratedReport,
            WeeklyReportService,
        )
        assert __version__ is not None
        assert __author__ is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
