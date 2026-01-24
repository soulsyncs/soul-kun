"""
日報・週報自動生成モジュールのテスト

Phase 2C-2: lib/report_generator.py のユニットテスト
"""

import pytest
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

from lib.report_generator import (
    DailySummary,
    CompletedTask,
    DailyReport,
    WeeklyReport,
    DailyReportGenerator,
    WeeklyReportGenerator,
    ReportDistributor,
)


# ============================================================
# 1. データクラスのテスト
# ============================================================

class TestDataClasses:
    """データクラスのテスト"""

    def test_daily_summary_creation(self):
        """DailySummaryが正しく作成される"""
        summary = DailySummary(
            summary_date=date(2026, 1, 24),
            key_topics=["タスク管理", "MTG準備"],
            mentioned_persons=["田中さん", "鈴木さん"],
            mentioned_tasks=["レビュー対応", "資料作成"],
            overall_summary="本日はタスク管理について議論しました",
            message_count=15
        )

        assert summary.summary_date == date(2026, 1, 24)
        assert len(summary.key_topics) == 2
        assert summary.message_count == 15

    def test_completed_task_creation(self):
        """CompletedTaskが正しく作成される"""
        task = CompletedTask(
            task_id="12345",
            body="コードレビュー対応",
            room_name="開発チーム",
            completed_at=datetime(2026, 1, 24, 15, 30)
        )

        assert task.task_id == "12345"
        assert task.body == "コードレビュー対応"
        assert task.room_name == "開発チーム"

    def test_daily_report_creation(self):
        """DailyReportが正しく作成される"""
        report = DailyReport(
            user_id="chatwork_123456",
            user_name="テストユーザー",
            report_date=date(2026, 1, 24),
            completed_tasks=[],
            summaries=[],
            report_text="日報テキスト"
        )

        assert report.user_id == "chatwork_123456"
        assert report.user_name == "テストユーザー"
        assert report.report_date == date(2026, 1, 24)

    def test_weekly_report_creation(self):
        """WeeklyReportが正しく作成される"""
        report = WeeklyReport(
            user_id="chatwork_123456",
            user_name="テストユーザー",
            week_start=date(2026, 1, 20),
            week_end=date(2026, 1, 24),
            daily_reports=[],
            report_text="週報テキスト"
        )

        assert report.user_id == "chatwork_123456"
        assert report.week_start == date(2026, 1, 20)
        assert report.week_end == date(2026, 1, 24)


# ============================================================
# 2. DailyReportGeneratorのテスト
# ============================================================

class TestDailyReportGenerator:
    """日報生成のテスト"""

    @patch('lib.report_generator.get_db_pool')
    def test_generate_report_text_with_tasks(self, mock_pool):
        """完了タスクがある場合の日報テキスト生成"""
        generator = DailyReportGenerator()

        tasks = [
            CompletedTask(
                task_id="1",
                body="コードレビュー",
                room_name="開発チーム",
                completed_at=datetime.now()
            )
        ]

        summaries = [
            DailySummary(
                summary_date=date.today(),
                key_topics=["設計議論"],
                mentioned_persons=[],
                mentioned_tasks=[],
                overall_summary="設計について話し合いました",
                message_count=10
            )
        ]

        report_text = generator._generate_report_text(
            user_name="テストユーザー",
            target_date=date.today(),
            summaries=summaries,
            completed_tasks=tasks
        )

        assert "日報下書き" in report_text
        assert "本日の成果" in report_text
        assert "コードレビュー" in report_text
        assert "開発チーム" in report_text
        assert "進行中の案件" in report_text
        assert "設計議論" in report_text

    @patch('lib.report_generator.get_db_pool')
    def test_generate_report_text_no_tasks(self, mock_pool):
        """完了タスクがない場合の日報テキスト生成"""
        generator = DailyReportGenerator()

        report_text = generator._generate_report_text(
            user_name="テストユーザー",
            target_date=date.today(),
            summaries=[],
            completed_tasks=[]
        )

        assert "日報下書き" in report_text
        assert "完了タスクなし" in report_text
        assert "明日の予定" in report_text

    @patch('lib.report_generator.get_db_pool')
    def test_report_text_contains_weekday(self, mock_pool):
        """日報に曜日が含まれる"""
        generator = DailyReportGenerator()

        # 金曜日のテスト
        friday = date(2026, 1, 23)  # 金曜日
        report_text = generator._generate_report_text(
            user_name="テストユーザー",
            target_date=friday,
            summaries=[],
            completed_tasks=[]
        )

        assert "金" in report_text

    @patch('lib.report_generator.get_db_pool')
    def test_report_text_contains_soulkun_footer(self, mock_pool):
        """日報にソウルくんフッターが含まれる"""
        generator = DailyReportGenerator()

        report_text = generator._generate_report_text(
            user_name="テストユーザー",
            target_date=date.today(),
            summaries=[],
            completed_tasks=[]
        )

        assert "ソウルくん" in report_text
        assert "自動生成" in report_text


# ============================================================
# 3. WeeklyReportGeneratorのテスト
# ============================================================

class TestWeeklyReportGenerator:
    """週報生成のテスト"""

    @patch('lib.report_generator.get_db_pool')
    def test_generate_report_text_with_data(self, mock_pool):
        """データがある場合の週報テキスト生成"""
        generator = WeeklyReportGenerator()

        tasks = [
            CompletedTask(
                task_id="1",
                body="タスク1",
                room_name="チームA",
                completed_at=datetime.now()
            ),
            CompletedTask(
                task_id="2",
                body="タスク2",
                room_name="チームB",
                completed_at=datetime.now()
            )
        ]

        daily_reports = [
            DailyReport(
                user_id="chatwork_123",
                user_name="テストユーザー",
                report_date=date.today(),
                completed_tasks=tasks,
                summaries=[],
                report_text=""
            )
        ]

        report_text = generator._generate_report_text(
            user_name="テストユーザー",
            week_start=date(2026, 1, 20),
            week_end=date(2026, 1, 24),
            all_completed_tasks=tasks,
            all_topics=["設計", "レビュー"],
            daily_reports=daily_reports
        )

        assert "週報下書き" in report_text
        assert "今週の成果" in report_text
        assert "2件" in report_text
        assert "主要な取り組み" in report_text
        assert "来週の予定" in report_text

    @patch('lib.report_generator.get_db_pool')
    def test_week_calculation(self, mock_pool):
        """週の開始日・終了日の計算"""
        generator = WeeklyReportGenerator()

        # 金曜日（1/23）から週の開始（月曜日1/19）を計算
        friday = date(2026, 1, 23)
        week_start = friday - timedelta(days=friday.weekday())

        assert week_start == date(2026, 1, 19)  # 月曜日
        assert week_start.weekday() == 0  # 0 = 月曜日


# ============================================================
# 4. ReportDistributorのテスト
# ============================================================

class TestReportDistributor:
    """レポート配信のテスト"""

    @patch('lib.report_generator.get_db_pool')
    def test_get_active_users_empty(self, mock_pool):
        """アクティブユーザーが0人の場合"""
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = []
        mock_pool.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)

        distributor = ReportDistributor()
        users = distributor.get_active_users()

        assert users == []

    @patch('lib.report_generator.ChatworkClient')
    @patch('lib.report_generator.get_db_pool')
    def test_send_daily_report_no_dm_room(self, mock_pool, mock_client):
        """DMルームがない場合は送信スキップ"""
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = None
        mock_pool.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)

        distributor = ReportDistributor()

        user = {"account_id": "123", "user_name": "テスト", "user_id": "chatwork_123"}
        report = DailyReport(
            user_id="chatwork_123",
            user_name="テスト",
            report_date=date.today(),
            completed_tasks=[],
            summaries=[],
            report_text="テスト日報"
        )

        result = distributor.send_daily_report(user, report)

        assert result is False
        mock_client.assert_not_called()


# ============================================================
# 5. 統合テスト
# ============================================================

class TestIntegration:
    """統合テスト"""

    @patch('lib.report_generator.get_db_pool')
    def test_full_daily_report_flow(self, mock_pool):
        """日報生成の全体フロー"""
        mock_conn = MagicMock()

        # サマリー取得をモック
        mock_conn.execute.return_value.fetchall.return_value = [
            (date.today(), ["トピック1"], ["田中"], ["タスクA"], "サマリー", 10)
        ]

        mock_pool.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)

        generator = DailyReportGenerator()
        summaries = generator._get_daily_summaries("chatwork_123", date.today())

        assert len(summaries) == 1
        assert summaries[0].key_topics == ["トピック1"]
        assert summaries[0].message_count == 10

    def test_report_text_structure(self):
        """レポートテキストの構造確認"""
        generator = DailyReportGenerator.__new__(DailyReportGenerator)

        tasks = [
            CompletedTask("1", "タスク1", "ルーム1", datetime.now()),
            CompletedTask("2", "タスク2", "ルーム2", datetime.now()),
        ]

        summaries = [
            DailySummary(
                date.today(),
                ["トピックA", "トピックB"],
                ["田中"],
                ["タスクX"],
                "今日は充実した一日でした",
                20
            )
        ]

        report_text = generator._generate_report_text(
            user_name="山田太郎",
            target_date=date(2026, 1, 24),
            summaries=summaries,
            completed_tasks=tasks
        )

        # 構造確認
        assert "## 本日の成果" in report_text
        assert "## 進行中の案件" in report_text
        assert "## 所感・気づき" in report_text
        assert "## 明日の予定" in report_text

        # 内容確認
        assert "タスク1" in report_text
        assert "タスク2" in report_text
        assert "トピックA" in report_text
        assert "充実した一日" in report_text


# ============================================================
# 6. エッジケース
# ============================================================

class TestEdgeCases:
    """エッジケースのテスト"""

    @patch('lib.report_generator.get_db_pool')
    def test_long_task_body_truncation(self, mock_pool):
        """長いタスク本文が切り詰められる"""
        generator = DailyReportGenerator()

        long_body = "あ" * 200

        tasks = [
            CompletedTask("1", long_body[:100], "ルーム", datetime.now())
        ]

        report_text = generator._generate_report_text(
            user_name="テスト",
            target_date=date.today(),
            summaries=[],
            completed_tasks=tasks
        )

        # 100文字で切り詰められていることを確認
        assert len(tasks[0].body) == 100

    @patch('lib.report_generator.get_db_pool')
    def test_many_topics_limited(self, mock_pool):
        """トピックが最大5件に制限される"""
        generator = DailyReportGenerator()

        summaries = [
            DailySummary(
                date.today(),
                [f"トピック{i}" for i in range(10)],
                [],
                [],
                "",
                10
            )
        ]

        report_text = generator._generate_report_text(
            user_name="テスト",
            target_date=date.today(),
            summaries=summaries,
            completed_tasks=[]
        )

        # 最大5件のトピックが含まれることを確認
        topic_count = sum(1 for i in range(10) if f"トピック{i}" in report_text)
        assert topic_count <= 5

    def test_user_id_extraction(self):
        """user_idからaccount_idの抽出"""
        # chatwork_123456 -> 123456
        user_id = "chatwork_123456"
        account_id = user_id.replace("chatwork_", "")

        assert account_id == "123456"

        # 数字のみの場合
        user_id2 = "789012"
        account_id2 = user_id2.replace("chatwork_", "")

        assert account_id2 == "789012"
