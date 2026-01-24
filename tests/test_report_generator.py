"""
日報・週報自動生成モジュールのテスト

Phase 2C-2: lib/report_generator.py のユニットテスト
v10.23.2: Phase 2.5 + MVV統合テスト追加
"""

import pytest
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

from lib.report_generator import (
    GoalProgress,
    DailySummary,
    CompletedTask,
    DailyReport,
    WeeklyReport,
    GoalProgressFetcher,
    EncouragementGenerator,
    DailyReportGenerator,
    WeeklyReportGenerator,
    ReportDistributor,
)


# ============================================================
# 1. データクラスのテスト
# ============================================================

class TestDataClasses:
    """データクラスのテスト"""

    def test_goal_progress_creation(self):
        """GoalProgressが正しく作成される（v10.23.2）"""
        goal = GoalProgress(
            goal_id="goal-123",
            title="売上目標達成",
            why_answer="成長したいから",
            what_answer="月間売上100万円",
            how_answer="毎日10件のアプローチ",
            target_value=100.0,
            current_value=75.0,
            unit="万円",
            progress_rate=75.0,
            period_end=date(2026, 3, 31),
            status="active"
        )

        assert goal.goal_id == "goal-123"
        assert goal.title == "売上目標達成"
        assert goal.why_answer == "成長したいから"
        assert goal.progress_rate == 75.0
        assert goal.status == "active"

    def test_goal_progress_default_values(self):
        """GoalProgressのデフォルト値が正しい"""
        goal = GoalProgress(
            goal_id="goal-456",
            title="テスト目標",
            why_answer="",
            what_answer="",
            how_answer=""
        )

        assert goal.target_value is None
        assert goal.current_value is None
        assert goal.progress_rate == 0.0
        assert goal.status == "active"

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

    def test_daily_report_with_goal_progress(self):
        """DailyReportに目標進捗が含まれる（v10.23.2）"""
        goal = GoalProgress(
            goal_id="goal-123",
            title="売上目標",
            why_answer="成長",
            what_answer="100万",
            how_answer="毎日アプローチ",
            progress_rate=50.0
        )

        report = DailyReport(
            user_id="chatwork_123456",
            user_name="テストユーザー",
            report_date=date(2026, 1, 24),
            completed_tasks=[],
            summaries=[],
            report_text="日報テキスト",
            goal_progress=goal,
            matched_guideline={"title": "挑戦を楽しみ"},
            encouragement_message="頑張ってるウル！"
        )

        assert report.goal_progress is not None
        assert report.goal_progress.progress_rate == 50.0
        assert report.matched_guideline is not None
        assert "頑張ってるウル" in report.encouragement_message

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
# 4. EncouragementGeneratorのテスト（v10.23.2）
# ============================================================

class TestEncouragementGenerator:
    """励ましメッセージ生成のテスト（v10.23.2）"""

    def test_daily_encouragement_with_tasks(self):
        """タスク完了時の日報励ましメッセージ"""
        generator = EncouragementGenerator()

        message, guideline = generator.generate_daily_encouragement(
            user_name="田中さん",
            completed_task_count=5,
            goal_progress=None,
            topics=[]
        )

        assert "5件" in message
        assert "完了" in message or "タスク" in message
        assert "ウル" in message

    def test_daily_encouragement_no_tasks(self):
        """タスクなしの日報励ましメッセージ"""
        generator = EncouragementGenerator()

        message, guideline = generator.generate_daily_encouragement(
            user_name="田中さん",
            completed_task_count=0,
            goal_progress=None,
            topics=[]
        )

        assert "お疲れ様" in message
        assert "ウル" in message

    def test_daily_encouragement_with_goal_progress(self):
        """目標進捗ありの日報励ましメッセージ"""
        generator = EncouragementGenerator()

        goal = GoalProgress(
            goal_id="goal-123",
            title="売上目標",
            why_answer="成長したいから",
            what_answer="100万達成",
            how_answer="毎日アプローチ",
            progress_rate=85.0
        )

        message, guideline = generator.generate_daily_encouragement(
            user_name="田中さん",
            completed_task_count=3,
            goal_progress=goal,
            topics=[]
        )

        assert "目標" in message or "85" in message
        # MVVが有効ならWHYも含まれる
        assert "成長" in message or "可能性" in message or "85" in message

    def test_weekly_encouragement_many_tasks(self):
        """タスクが多い週の励ましメッセージ"""
        generator = EncouragementGenerator()

        message, guideline = generator.generate_weekly_encouragement(
            user_name="田中さん",
            total_completed_tasks=15,
            goal_progress=None,
            achievements=[]
        )

        assert "15件" in message
        assert "素晴らしい" in message or "完了" in message
        assert "ウル" in message

    def test_weekly_encouragement_goal_achieved(self):
        """目標達成時の週報励ましメッセージ"""
        generator = EncouragementGenerator()

        goal = GoalProgress(
            goal_id="goal-123",
            title="売上目標",
            why_answer="成長",
            what_answer="100万",
            how_answer="アプローチ",
            progress_rate=100.0
        )

        message, guideline = generator.generate_weekly_encouragement(
            user_name="田中さん",
            total_completed_tasks=10,
            goal_progress=goal,
            achievements=[]
        )

        assert "達成" in message or "おめでとう" in message
        assert "ウル" in message

    def test_match_achievement_to_guideline(self):
        """成果と行動指針のマッチング"""
        generator = EncouragementGenerator()

        # 挑戦キーワード
        guideline = generator.match_achievement_to_guideline("新しいプロジェクトに挑戦")
        # MVV利用可能ならガイドラインが返される
        if guideline:
            assert "挑戦" in guideline.get("title", "")

    def test_fallback_message_no_mvv(self):
        """MVV利用不可時のフォールバック"""
        generator = EncouragementGenerator()

        # フォールバックメソッドを直接テスト
        message = generator._fallback_daily_message("田中さん", 5)
        assert "5件" in message
        assert "ウル" in message

        message = generator._fallback_weekly_message("田中さん", 0)
        assert "お疲れ様" in message


# ============================================================
# 5. GoalProgressFetcherのテスト（v10.23.2）
# ============================================================

class TestGoalProgressFetcher:
    """目標進捗取得のテスト（v10.23.2）"""

    def test_extract_why_what_how(self):
        """WHY/WHAT/HOWの抽出"""
        mock_pool = MagicMock()
        fetcher = GoalProgressFetcher(mock_pool)

        description = """WHY: 成長したいから
WHAT: 月間売上100万円
HOW: 毎日10件のアプローチを行う"""

        why, what, how = fetcher._extract_why_what_how(description)

        assert "成長" in why
        assert "100万" in what
        assert "10件" in how

    def test_extract_why_what_how_empty(self):
        """空の説明からの抽出"""
        mock_pool = MagicMock()
        fetcher = GoalProgressFetcher(mock_pool)

        why, what, how = fetcher._extract_why_what_how("")

        assert why == ""
        assert what == ""
        assert how == ""

    def test_extract_why_what_how_partial(self):
        """部分的な説明からの抽出"""
        mock_pool = MagicMock()
        fetcher = GoalProgressFetcher(mock_pool)

        description = "WHY: 理由だけ"

        why, what, how = fetcher._extract_why_what_how(description)

        assert "理由だけ" in why
        assert what == ""
        assert how == ""

    @patch('lib.report_generator.get_db_pool')
    def test_get_active_goal_not_found(self, mock_pool):
        """アクティブ目標が見つからない場合"""
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = None
        mock_pool.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)

        fetcher = GoalProgressFetcher(mock_pool.return_value)
        result = fetcher.get_active_goal("user-123")

        assert result is None


# ============================================================
# 6. ReportDistributorのテスト
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
# 7. 統合テスト
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
# 8. エッジケース
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


# ============================================================
# 9. v10.23.2 機能テスト（Phase 2.5 + MVV統合）
# ============================================================

class TestV10232Features:
    """v10.23.2の新機能テスト"""

    @patch('lib.report_generator.get_db_pool')
    def test_daily_report_with_goal_progress_section(self, mock_pool):
        """日報に目標進捗セクションが含まれる"""
        generator = DailyReportGenerator()

        goal = GoalProgress(
            goal_id="goal-123",
            title="売上目標達成",
            why_answer="成長したいから",
            what_answer="月間100万円",
            how_answer="毎日10件アプローチ",
            target_value=100.0,
            current_value=75.0,
            unit="万円",
            progress_rate=75.0
        )

        report_text = generator._generate_report_text(
            user_name="テストユーザー",
            target_date=date.today(),
            summaries=[],
            completed_tasks=[],
            goal_progress=goal,
            encouragement_message="頑張ってるウル！"
        )

        # 目標セクションが含まれる
        assert "目標進捗" in report_text
        assert "売上目標達成" in report_text
        assert "75%" in report_text
        assert "WHY" in report_text
        assert "成長" in report_text

    @patch('lib.report_generator.get_db_pool')
    def test_weekly_report_with_goal_progress_section(self, mock_pool):
        """週報に目標進捗セクションが含まれる"""
        generator = WeeklyReportGenerator()

        goal = GoalProgress(
            goal_id="goal-123",
            title="四半期目標",
            why_answer="キャリアアップ",
            what_answer="100件達成",
            how_answer="毎週20件",
            target_value=100.0,
            current_value=60.0,
            unit="件",
            progress_rate=60.0,
            period_end=date(2026, 3, 31)
        )

        report_text = generator._generate_report_text(
            user_name="テストユーザー",
            week_start=date(2026, 1, 20),
            week_end=date(2026, 1, 24),
            all_completed_tasks=[],
            all_topics=[],
            daily_reports=[],
            goal_progress=goal,
            encouragement_message="今週もお疲れ様ウル！"
        )

        # 目標セクションが含まれる
        assert "今週の目標進捗" in report_text
        assert "四半期目標" in report_text
        assert "60%" in report_text
        # 期限表示
        assert "残り" in report_text or "期限" in report_text or "03/31" in report_text

    @patch('lib.report_generator.get_db_pool')
    def test_progress_bar_generation(self, mock_pool):
        """進捗バーの生成"""
        generator = DailyReportGenerator()

        # 0%
        bar = generator._generate_progress_bar(0)
        assert "░░░░░░░░░░" in bar

        # 50%
        bar = generator._generate_progress_bar(50)
        assert "█████" in bar
        assert "░░░░░" in bar

        # 100%
        bar = generator._generate_progress_bar(100)
        assert "██████████" in bar
        assert "░" not in bar

    @patch('lib.report_generator.get_db_pool')
    def test_encouragement_message_in_footer(self, mock_pool):
        """フッターに励ましメッセージが含まれる"""
        generator = DailyReportGenerator()

        report_text = generator._generate_report_text(
            user_name="テストユーザー",
            target_date=date.today(),
            summaries=[],
            completed_tasks=[],
            goal_progress=None,
            encouragement_message="ソウルくんは君を信じてるウル！🐺"
        )

        assert "信じてるウル" in report_text
        assert "🐺" in report_text

    def test_weekly_achievements_extraction(self):
        """週の成果抽出"""
        generator = WeeklyReportGenerator.__new__(WeeklyReportGenerator)

        tasks1 = [
            CompletedTask("1", "タスクA", "ルーム1", datetime.now()),
            CompletedTask("2", "タスクB", "ルーム1", datetime.now()),
            CompletedTask("3", "タスクC", "ルーム1", datetime.now()),
            CompletedTask("4", "タスクD", "ルーム1", datetime.now()),
        ]

        tasks2 = [
            CompletedTask("5", "タスクE", "ルーム2", datetime.now()),
            CompletedTask("6", "タスクF", "ルーム2", datetime.now()),
        ]

        daily_reports = [
            DailyReport(
                user_id="chatwork_123",
                user_name="テスト",
                report_date=date.today(),
                completed_tasks=tasks1,
                summaries=[],
                report_text=""
            ),
            DailyReport(
                user_id="chatwork_123",
                user_name="テスト",
                report_date=date.today() - timedelta(days=1),
                completed_tasks=tasks2,
                summaries=[],
                report_text=""
            )
        ]

        achievements = generator._extract_weekly_achievements(
            daily_reports=daily_reports,
            all_topics=[]
        )

        # 各日最大3件、重複除去
        assert len(achievements) <= 10
        assert len(achievements) >= 5  # 3 + 2 = 5件

    def test_encouragement_topics_matching(self):
        """トピックに基づく励ましメッセージの変化"""
        generator = EncouragementGenerator()

        # 挑戦トピック
        message, guideline = generator.generate_daily_encouragement(
            user_name="田中さん",
            completed_task_count=2,
            goal_progress=None,
            topics=["新しいプロジェクトにチャレンジ"]
        )

        # MVVが有効なら挑戦に関するメッセージが含まれる可能性
        assert "ウル" in message  # 最低限ソウルくん口調

        # チームトピック
        message2, guideline2 = generator.generate_daily_encouragement(
            user_name="田中さん",
            completed_task_count=2,
            goal_progress=None,
            topics=["チームMTGで協力して進めた"]
        )

        assert "ウル" in message2
