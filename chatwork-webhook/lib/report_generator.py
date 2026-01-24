"""
日報・週報自動生成モジュール

Phase 2C-2: B1サマリーとタスク完了履歴を集約し、報告書を自動生成する

機能:
- DailyReportGenerator: 日報自動生成
- WeeklyReportGenerator: 週報自動生成
- 本人へのChatWork送信
"""

from datetime import datetime, timedelta, date
from typing import List, Dict, Optional, Any
from dataclasses import dataclass
import json

from lib.db import get_db_pool
from lib.chatwork import ChatworkClient
from sqlalchemy import text

print("✅ lib/report_generator.py loaded for daily/weekly report generation")


# ============================================================
# 1. データクラス定義
# ============================================================

@dataclass
class DailySummary:
    """日次サマリーデータ"""
    summary_date: date
    key_topics: List[str]
    mentioned_persons: List[str]
    mentioned_tasks: List[str]
    overall_summary: str
    message_count: int


@dataclass
class CompletedTask:
    """完了タスクデータ"""
    task_id: str
    body: str
    room_name: str
    completed_at: datetime


@dataclass
class DailyReport:
    """日報データ"""
    user_id: str
    user_name: str
    report_date: date
    completed_tasks: List[CompletedTask]
    summaries: List[DailySummary]
    report_text: str


@dataclass
class WeeklyReport:
    """週報データ"""
    user_id: str
    user_name: str
    week_start: date
    week_end: date
    daily_reports: List[DailyReport]
    report_text: str


# ============================================================
# 2. 日報生成クラス
# ============================================================

class DailyReportGenerator:
    """日報自動生成"""

    def __init__(self, organization_id: str = "default"):
        self.organization_id = organization_id
        self.pool = get_db_pool()

    def generate(self, user_id: str, user_name: str, target_date: date) -> Optional[DailyReport]:
        """
        日報を生成

        Args:
            user_id: ユーザーID（chatwork_{account_id}形式）
            user_name: ユーザー名
            target_date: 対象日

        Returns:
            DailyReport or None（データ不足の場合）
        """
        # B1サマリーから当日の会話を取得
        summaries = self._get_daily_summaries(user_id, target_date)

        # 完了タスクを取得
        completed_tasks = self._get_completed_tasks(user_id, target_date)

        # データがなければNone
        if not summaries and not completed_tasks:
            print(f"📝 日報生成スキップ: user={user_name}, date={target_date} (データなし)")
            return None

        # 日報テキストを生成
        report_text = self._generate_report_text(
            user_name=user_name,
            target_date=target_date,
            summaries=summaries,
            completed_tasks=completed_tasks
        )

        return DailyReport(
            user_id=user_id,
            user_name=user_name,
            report_date=target_date,
            completed_tasks=completed_tasks,
            summaries=summaries,
            report_text=report_text
        )

    def _get_daily_summaries(self, user_id: str, target_date: date) -> List[DailySummary]:
        """B1サマリーから当日の会話サマリーを取得"""
        with self.pool.connect() as conn:
            result = conn.execute(text("""
                SELECT
                    DATE(period_end) as summary_date,
                    key_topics,
                    mentioned_persons,
                    mentioned_tasks,
                    summary,
                    message_count
                FROM conversation_summaries
                WHERE user_id = :user_id
                  AND DATE(period_end) = :target_date
                ORDER BY period_end DESC
            """), {
                "user_id": user_id,
                "target_date": target_date
            })

            rows = result.fetchall()

        summaries = []
        for row in rows:
            summaries.append(DailySummary(
                summary_date=row[0],
                key_topics=row[1] if row[1] else [],
                mentioned_persons=row[2] if row[2] else [],
                mentioned_tasks=row[3] if row[3] else [],
                overall_summary=row[4] or "",
                message_count=row[5] or 0
            ))

        return summaries

    def _get_completed_tasks(self, user_id: str, target_date: date) -> List[CompletedTask]:
        """当日の完了タスクを取得"""
        # user_idからaccount_idを抽出（chatwork_123456 -> 123456）
        account_id = user_id.replace("chatwork_", "") if user_id.startswith("chatwork_") else user_id

        with self.pool.connect() as conn:
            result = conn.execute(text("""
                SELECT
                    t.chatwork_task_id,
                    t.body,
                    r.room_name,
                    t.updated_at
                FROM chatwork_tasks t
                LEFT JOIN chatwork_rooms r ON t.room_id = r.room_id
                WHERE t.assigned_account_id = :account_id
                  AND t.status = 'done'
                  AND DATE(t.updated_at) = :target_date
                ORDER BY t.updated_at DESC
            """), {
                "account_id": account_id,
                "target_date": target_date
            })

            rows = result.fetchall()

        tasks = []
        for row in rows:
            tasks.append(CompletedTask(
                task_id=str(row[0]),
                body=row[1][:100] if row[1] else "(タスク内容なし)",  # 長すぎる場合は切り詰め
                room_name=row[2] or "(不明)",
                completed_at=row[3]
            ))

        return tasks

    def _generate_report_text(
        self,
        user_name: str,
        target_date: date,
        summaries: List[DailySummary],
        completed_tasks: List[CompletedTask]
    ) -> str:
        """日報テキストを生成"""
        date_str = target_date.strftime('%Y/%m/%d')
        weekday_ja = ["月", "火", "水", "木", "金", "土", "日"][target_date.weekday()]

        lines = [
            f"📋 **日報下書き** ({date_str} {weekday_ja})",
            f"担当: {user_name}",
            "",
            "---",
            ""
        ]

        # 本日の成果（完了タスク）
        lines.append("## 本日の成果")
        if completed_tasks:
            for task in completed_tasks:
                lines.append(f"- ✅ {task.body} ({task.room_name})")
        else:
            lines.append("- （完了タスクなし）")
        lines.append("")

        # 進行中の案件（サマリーから抽出）
        lines.append("## 進行中の案件")
        if summaries:
            all_topics = []
            for s in summaries:
                all_topics.extend(s.key_topics)
            unique_topics = list(set(all_topics))[:5]  # 最大5件
            if unique_topics:
                for topic in unique_topics:
                    lines.append(f"- {topic}")
            else:
                lines.append("- （特になし）")
        else:
            lines.append("- （特になし）")
        lines.append("")

        # 所感・気づき（サマリーから抽出）
        lines.append("## 所感・気づき")
        if summaries and any(s.overall_summary for s in summaries):
            for s in summaries:
                if s.overall_summary:
                    # 長すぎる場合は要約
                    summary_text = s.overall_summary[:200] + "..." if len(s.overall_summary) > 200 else s.overall_summary
                    lines.append(f"- {summary_text}")
        else:
            lines.append("- （後ほど記入してください）")
        lines.append("")

        # 明日の予定
        lines.append("## 明日の予定")
        lines.append("- （後ほど記入してください）")
        lines.append("")

        # フッター
        lines.append("---")
        lines.append("🐺 ソウルくんが自動生成した下書きウル！必要に応じて編集してください。")

        return "\n".join(lines)


# ============================================================
# 3. 週報生成クラス
# ============================================================

class WeeklyReportGenerator:
    """週報自動生成"""

    def __init__(self, organization_id: str = "default"):
        self.organization_id = organization_id
        self.daily_generator = DailyReportGenerator(organization_id)
        self.pool = get_db_pool()

    def generate(self, user_id: str, user_name: str, week_end: date) -> Optional[WeeklyReport]:
        """
        週報を生成

        Args:
            user_id: ユーザーID
            user_name: ユーザー名
            week_end: 週末日（金曜日）

        Returns:
            WeeklyReport or None
        """
        # 週の開始日（月曜日）を計算
        week_start = week_end - timedelta(days=week_end.weekday())

        # 1週間分の日報を収集
        daily_reports = []
        all_completed_tasks = []
        all_topics = []

        for i in range(5):  # 月〜金
            day = week_start + timedelta(days=i)
            report = self.daily_generator.generate(user_id, user_name, day)
            if report:
                daily_reports.append(report)
                all_completed_tasks.extend(report.completed_tasks)
                for s in report.summaries:
                    all_topics.extend(s.key_topics)

        # データがなければNone
        if not daily_reports:
            print(f"📝 週報生成スキップ: user={user_name}, week={week_start}〜{week_end} (データなし)")
            return None

        # 週報テキストを生成
        report_text = self._generate_report_text(
            user_name=user_name,
            week_start=week_start,
            week_end=week_end,
            all_completed_tasks=all_completed_tasks,
            all_topics=all_topics,
            daily_reports=daily_reports
        )

        return WeeklyReport(
            user_id=user_id,
            user_name=user_name,
            week_start=week_start,
            week_end=week_end,
            daily_reports=daily_reports,
            report_text=report_text
        )

    def _generate_report_text(
        self,
        user_name: str,
        week_start: date,
        week_end: date,
        all_completed_tasks: List[CompletedTask],
        all_topics: List[str],
        daily_reports: List[DailyReport]
    ) -> str:
        """週報テキストを生成"""
        start_str = week_start.strftime('%Y/%m/%d')
        end_str = week_end.strftime('%Y/%m/%d')

        lines = [
            f"📊 **週報下書き** ({start_str} 〜 {end_str})",
            f"担当: {user_name}",
            "",
            "---",
            ""
        ]

        # 今週の成果サマリー
        lines.append("## 今週の成果")
        if all_completed_tasks:
            lines.append(f"- 完了タスク数: **{len(all_completed_tasks)}件**")
            # 主要なタスクを最大5件表示
            for task in all_completed_tasks[:5]:
                lines.append(f"  - ✅ {task.body}")
            if len(all_completed_tasks) > 5:
                lines.append(f"  - ... 他 {len(all_completed_tasks) - 5}件")
        else:
            lines.append("- （完了タスクなし）")
        lines.append("")

        # 主要な取り組み
        lines.append("## 主要な取り組み")
        unique_topics = list(set(all_topics))[:7]  # 最大7件
        if unique_topics:
            for topic in unique_topics:
                lines.append(f"- {topic}")
        else:
            lines.append("- （特になし）")
        lines.append("")

        # 来週の予定
        lines.append("## 来週の予定")
        lines.append("- （後ほど記入してください）")
        lines.append("")

        # 課題・相談事項
        lines.append("## 課題・相談事項")
        lines.append("- （後ほど記入してください）")
        lines.append("")

        # フッター
        lines.append("---")
        lines.append(f"🐺 ソウルくんが{len(daily_reports)}日分のデータから自動生成した下書きウル！")
        lines.append("必要に応じて編集してから提出してください。")

        return "\n".join(lines)


# ============================================================
# 4. レポート配信クラス
# ============================================================

class ReportDistributor:
    """レポート配信"""

    def __init__(self):
        self.pool = get_db_pool()

    def get_active_users(self) -> List[Dict[str, Any]]:
        """
        アクティブユーザー一覧を取得

        過去7日間に会話があったユーザーを対象とする
        """
        with self.pool.connect() as conn:
            result = conn.execute(text("""
                SELECT DISTINCT
                    u.chatwork_account_id,
                    u.chatwork_user_name,
                    u.id as user_id
                FROM users u
                INNER JOIN conversation_summaries cs
                    ON cs.user_id = CONCAT('chatwork_', u.chatwork_account_id::text)
                WHERE cs.period_end >= NOW() - INTERVAL '7 days'
                  AND u.chatwork_account_id IS NOT NULL
                ORDER BY u.chatwork_user_name
            """))

            rows = result.fetchall()

        users = []
        for row in rows:
            users.append({
                "account_id": str(row[0]),
                "user_name": row[1] or f"ユーザー{row[0]}",
                "user_id": f"chatwork_{row[0]}"
            })

        return users

    def send_daily_report(self, user: Dict, report: DailyReport) -> bool:
        """日報を本人に送信"""
        try:
            # 本人のDMルームを取得（なければスキップ）
            dm_room_id = self._get_dm_room(user["account_id"])
            if not dm_room_id:
                print(f"⚠️ DMルームなし: user={user['user_name']}")
                return False

            # 送信
            message = f"[info][title]日報下書きが完成しました[/title]{report.report_text}[/info]"
            client = ChatworkClient()
            client.send_message(room_id=dm_room_id, message=message)
            print(f"✅ 日報送信完了: user={user['user_name']}, room={dm_room_id}")
            return True

        except Exception as e:
            print(f"❌ 日報送信エラー: user={user['user_name']}, error={e}")
            return False

    def send_weekly_report(self, user: Dict, report: WeeklyReport) -> bool:
        """週報を本人に送信"""
        try:
            dm_room_id = self._get_dm_room(user["account_id"])
            if not dm_room_id:
                print(f"⚠️ DMルームなし: user={user['user_name']}")
                return False

            message = f"[info][title]週報下書きが完成しました[/title]{report.report_text}[/info]"
            client = ChatworkClient()
            client.send_message(room_id=dm_room_id, message=message)
            print(f"✅ 週報送信完了: user={user['user_name']}, room={dm_room_id}")
            return True

        except Exception as e:
            print(f"❌ 週報送信エラー: user={user['user_name']}, error={e}")
            return False

    def _get_dm_room(self, account_id: str) -> Optional[str]:
        """
        ユーザーのDMルームIDを取得

        ソウルくんとのDMルーム（2人だけのルーム）を探す
        """
        with self.pool.connect() as conn:
            # ソウルくんのアカウントIDを取得
            soulkun_result = conn.execute(text("""
                SELECT chatwork_account_id
                FROM users
                WHERE chatwork_user_name LIKE '%ソウルくん%'
                   OR chatwork_user_name LIKE '%soulkun%'
                LIMIT 1
            """))
            soulkun_row = soulkun_result.fetchone()

            if not soulkun_row:
                # ソウルくんが見つからない場合は、ユーザーがメンバーの最初のルームを使用
                result = conn.execute(text("""
                    SELECT room_id
                    FROM chatwork_room_members
                    WHERE account_id = :account_id
                    LIMIT 1
                """), {"account_id": account_id})
                row = result.fetchone()
                return str(row[0]) if row else None

            # ソウルくんとのDMルームを探す
            result = conn.execute(text("""
                SELECT rm1.room_id
                FROM chatwork_room_members rm1
                INNER JOIN chatwork_room_members rm2
                    ON rm1.room_id = rm2.room_id
                INNER JOIN chatwork_rooms r
                    ON rm1.room_id = r.room_id
                WHERE rm1.account_id = :account_id
                  AND rm2.account_id = :soulkun_id
                  AND r.room_type = 'direct'
                LIMIT 1
            """), {
                "account_id": account_id,
                "soulkun_id": str(soulkun_row[0])
            })

            row = result.fetchone()
            return str(row[0]) if row else None


# ============================================================
# 5. メイン実行関数
# ============================================================

def run_daily_report_generation(dry_run: bool = False) -> Dict[str, Any]:
    """
    日報生成バッチ処理

    Args:
        dry_run: Trueの場合、送信せずにログのみ

    Returns:
        実行結果
    """
    print(f"📋 日報生成開始 (dry_run={dry_run})")

    target_date = date.today()
    distributor = ReportDistributor()
    daily_generator = DailyReportGenerator()

    users = distributor.get_active_users()
    print(f"   対象ユーザー: {len(users)}人")

    results = {
        "target_date": str(target_date),
        "total_users": len(users),
        "generated": 0,
        "sent": 0,
        "skipped": 0,
        "errors": []
    }

    for user in users:
        try:
            report = daily_generator.generate(
                user_id=user["user_id"],
                user_name=user["user_name"],
                target_date=target_date
            )

            if not report:
                results["skipped"] += 1
                continue

            results["generated"] += 1

            if not dry_run:
                if distributor.send_daily_report(user, report):
                    results["sent"] += 1

        except Exception as e:
            print(f"❌ エラー: user={user['user_name']}, error={e}")
            results["errors"].append({
                "user": user["user_name"],
                "error": str(e)
            })

    print(f"📋 日報生成完了: 生成={results['generated']}, 送信={results['sent']}, スキップ={results['skipped']}")
    return results


def run_weekly_report_generation(dry_run: bool = False) -> Dict[str, Any]:
    """
    週報生成バッチ処理

    Args:
        dry_run: Trueの場合、送信せずにログのみ

    Returns:
        実行結果
    """
    print(f"📊 週報生成開始 (dry_run={dry_run})")

    today = date.today()
    # 金曜日を週末とする
    week_end = today - timedelta(days=(today.weekday() - 4) % 7)

    distributor = ReportDistributor()
    weekly_generator = WeeklyReportGenerator()

    users = distributor.get_active_users()
    print(f"   対象ユーザー: {len(users)}人")
    print(f"   対象週: {week_end - timedelta(days=4)} 〜 {week_end}")

    results = {
        "week_end": str(week_end),
        "total_users": len(users),
        "generated": 0,
        "sent": 0,
        "skipped": 0,
        "errors": []
    }

    for user in users:
        try:
            report = weekly_generator.generate(
                user_id=user["user_id"],
                user_name=user["user_name"],
                week_end=week_end
            )

            if not report:
                results["skipped"] += 1
                continue

            results["generated"] += 1

            if not dry_run:
                if distributor.send_weekly_report(user, report):
                    results["sent"] += 1

        except Exception as e:
            print(f"❌ エラー: user={user['user_name']}, error={e}")
            results["errors"].append({
                "user": user["user_name"],
                "error": str(e)
            })

    print(f"📊 週報生成完了: 生成={results['generated']}, 送信={results['sent']}, スキップ={results['skipped']}")
    return results


# ============================================================
# 6. エクスポート
# ============================================================

__all__ = [
    # データクラス
    "DailySummary",
    "CompletedTask",
    "DailyReport",
    "WeeklyReport",
    # クラス
    "DailyReportGenerator",
    "WeeklyReportGenerator",
    "ReportDistributor",
    # 関数
    "run_daily_report_generation",
    "run_weekly_report_generation",
]
