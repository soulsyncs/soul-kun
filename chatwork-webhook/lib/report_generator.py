"""
日報・週報自動生成モジュール

Phase 2C-2: B1サマリーとタスク完了履歴を集約し、報告書を自動生成する

v10.23.2 拡張:
- Phase 2.5目標設定との連動（目標進捗の表示）
- MVV・組織論的行動指針との統合（励ましの言葉の統一）
- 行動指針10箇条と成果の紐づけ

機能:
- DailyReportGenerator: 日報自動生成
- WeeklyReportGenerator: 週報自動生成
- GoalProgressFetcher: 目標進捗の取得
- 本人へのChatWork送信
"""

from datetime import datetime, timedelta, date
from typing import List, Dict, Optional, Any, Tuple
from dataclasses import dataclass, field
import json
import re
import random

# v10.31.4: 相対インポートに変更（googleapiclient警告修正）
from .db import get_db_pool
from .chatwork import ChatworkClient
from sqlalchemy import text

# MVVコンテキストをインポート（Phase 2C-1）
# v10.31.4: 相対インポートに変更
try:
    from .mvv_context import (
        SOULSYNC_MVV,
        BEHAVIORAL_GUIDELINES_10,
        BasicNeed,
        BASIC_NEED_KEYWORDS,
    )
    MVV_AVAILABLE = True
except ImportError:
    MVV_AVAILABLE = False
    print("⚠️ MVVコンテキストが利用不可（フォールバックモードで動作）")

print("✅ lib/report_generator.py loaded for daily/weekly report generation (v10.23.2)")


# ============================================================
# 1. データクラス定義
# ============================================================

@dataclass
class GoalProgress:
    """目標進捗データ（Phase 2.5連動）"""
    goal_id: str
    title: str
    why_answer: str  # なぜこの目標を達成したいか
    what_answer: str  # 具体的に何を達成したいか
    how_answer: str  # どのような行動で達成するか
    target_value: Optional[float] = None
    current_value: Optional[float] = None
    unit: Optional[str] = None
    progress_rate: float = 0.0  # 進捗率（0-100）
    period_end: Optional[date] = None
    status: str = "active"


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
    # v10.23.2追加: Phase 2.5連動
    goal_progress: Optional[GoalProgress] = None
    matched_guideline: Optional[Dict[str, Any]] = None
    encouragement_message: str = ""


@dataclass
class WeeklyReport:
    """週報データ"""
    user_id: str
    user_name: str
    week_start: date
    week_end: date
    daily_reports: List[DailyReport]
    report_text: str
    # v10.23.2追加: Phase 2.5連動
    goal_progress: Optional[GoalProgress] = None
    weekly_achievements: List[str] = field(default_factory=list)
    encouragement_message: str = ""


# ============================================================
# 2. 目標進捗取得クラス（Phase 2.5連動）
# ============================================================

class GoalProgressFetcher:
    """
    Phase 2.5の目標設定データを取得し、日報・週報に連動させる

    取得データ:
    - 現在アクティブな目標（goals テーブル）
    - WHY/WHAT/HOW回答（goal_setting_sessions テーブル）
    - 進捗状況（current_value / target_value）
    """

    def __init__(self, pool):
        self.pool = pool

    def get_active_goal(self, user_id: str) -> Optional[GoalProgress]:
        """
        ユーザーの現在アクティブな目標を取得

        Args:
            user_id: ユーザーID（UUID形式）

        Returns:
            GoalProgress or None
        """
        with self.pool.connect() as conn:
            # 最新のアクティブ目標を取得
            result = conn.execute(text("""
                SELECT
                    g.id,
                    g.title,
                    g.description,
                    g.target_value,
                    g.current_value,
                    g.unit,
                    g.period_end,
                    g.status
                FROM goals g
                WHERE g.user_id = :user_id
                  AND g.status = 'active'
                ORDER BY g.created_at DESC
                LIMIT 1
            """), {"user_id": user_id})

            row = result.fetchone()

            if not row:
                return None

            goal_id = str(row[0])
            title = row[1] or ""
            description = row[2] or ""
            target_value = float(row[3]) if row[3] else None
            current_value = float(row[4]) if row[4] else 0.0
            unit = row[5]
            period_end = row[6]
            status = row[7]

            # 進捗率を計算
            progress_rate = 0.0
            if target_value and target_value > 0:
                progress_rate = min((current_value / target_value) * 100, 100)

            # descriptionからWHY/WHAT/HOWを抽出
            why_answer, what_answer, how_answer = self._extract_why_what_how(description)

            return GoalProgress(
                goal_id=goal_id,
                title=title,
                why_answer=why_answer,
                what_answer=what_answer,
                how_answer=how_answer,
                target_value=target_value,
                current_value=current_value,
                unit=unit,
                progress_rate=progress_rate,
                period_end=period_end,
                status=status
            )

    def _extract_why_what_how(self, description: str) -> Tuple[str, str, str]:
        """
        goal.descriptionからWHY/WHAT/HOWを抽出

        フォーマット: "WHY: {内容}\\nWHAT: {内容}\\nHOW: {内容}"
        """
        why_answer = ""
        what_answer = ""
        how_answer = ""

        if not description:
            return why_answer, what_answer, how_answer

        # WHYを抽出
        why_match = re.search(r'WHY[:：]\s*(.+?)(?=WHAT[:：]|HOW[:：]|$)', description, re.DOTALL)
        if why_match:
            why_answer = why_match.group(1).strip()

        # WHATを抽出
        what_match = re.search(r'WHAT[:：]\s*(.+?)(?=HOW[:：]|$)', description, re.DOTALL)
        if what_match:
            what_answer = what_match.group(1).strip()

        # HOWを抽出
        how_match = re.search(r'HOW[:：]\s*(.+?)$', description, re.DOTALL)
        if how_match:
            how_answer = how_match.group(1).strip()

        return why_answer, what_answer, how_answer

    def get_user_id_from_account_id(self, account_id: str) -> Optional[str]:
        """
        ChatWorkアカウントIDからユーザーID（UUID）を取得
        """
        with self.pool.connect() as conn:
            result = conn.execute(text("""
                SELECT id FROM users
                WHERE chatwork_account_id = :account_id
                LIMIT 1
            """), {"account_id": account_id})

            row = result.fetchone()
            return str(row[0]) if row else None


# ============================================================
# 3. 励ましメッセージ生成（MVV・組織論ベース）
# ============================================================

class EncouragementGenerator:
    """
    MVV・組織論的行動指針に基づく励ましメッセージを生成

    設計原則:
    - 選択理論の5つの基本欲求を意識
    - 行動指針10箇条と成果を紐づけ
    - 内発的動機づけを高める言葉かけ
    - 心理的安全性を高める表現
    """

    def __init__(self):
        if MVV_AVAILABLE:
            self.guidelines = BEHAVIORAL_GUIDELINES_10
            self.mvv = SOULSYNC_MVV
        else:
            self.guidelines = []
            self.mvv = {}

    def generate_daily_encouragement(
        self,
        user_name: str,
        completed_task_count: int,
        goal_progress: Optional[GoalProgress] = None,
        topics: List[str] = None
    ) -> Tuple[str, Optional[Dict[str, Any]]]:
        """
        日報用の励ましメッセージを生成

        Args:
            user_name: ユーザー名
            completed_task_count: 完了タスク数
            goal_progress: 目標進捗
            topics: 取り組んだトピック

        Returns:
            (励ましメッセージ, マッチした行動指針)
        """
        matched_guideline = None

        if not MVV_AVAILABLE:
            return self._fallback_daily_message(user_name, completed_task_count), None

        # 状況に応じたメッセージを生成
        messages = []

        # 1. タスク完了への承認（力の欲求 - 達成感）
        if completed_task_count > 0:
            messages.append(f"今日は{completed_task_count}件のタスクを完了したウル！着実に前に進んでるウル🐺")
            # 行動指針7「プロとして期待を超える」にマッチ
            matched_guideline = self.guidelines[6] if len(self.guidelines) > 6 else None
        else:
            messages.append("今日もお疲れ様ウル🐺")

        # 2. 目標進捗への励まし（MVV連動）
        if goal_progress:
            if goal_progress.progress_rate >= 80:
                messages.append(f"目標達成まであと少しウル！（{goal_progress.progress_rate:.0f}%）")
                messages.append("ソウルくんは{name}さんの可能性を信じてるウル✨".format(name=user_name))
                # 行動指針6「相手以上に相手の未来を信じる」
                matched_guideline = self.guidelines[5] if len(self.guidelines) > 5 else None
            elif goal_progress.progress_rate >= 50:
                messages.append(f"目標の半分を超えたウル！（{goal_progress.progress_rate:.0f}%）")
                messages.append("この調子で進めようウル🐺")
            elif goal_progress.progress_rate > 0:
                messages.append(f"目標に向かって進んでるウル（{goal_progress.progress_rate:.0f}%）")
                messages.append("一歩一歩が『可能性の解放』に繋がるウル✨")

            # WHYを思い出させる（内発的動機づけ）
            if goal_progress.why_answer:
                why_short = goal_progress.why_answer[:50] + "..." if len(goal_progress.why_answer) > 50 else goal_progress.why_answer
                messages.append(f"「{why_short}」という想い、大切にしようウル🐺")

        # 3. トピックに基づく行動指針マッチング
        if topics and self.guidelines:
            for guideline in self.guidelines:
                for topic in topics:
                    if any(keyword in topic for keyword in ["挑戦", "新しい", "チャレンジ"]):
                        # 行動指針2「挑戦を楽しみ、その楽しさを伝える」
                        messages.append("新しいことに挑戦してるウル！ワクワクするウル🐺✨")
                        matched_guideline = self.guidelines[1] if len(self.guidelines) > 1 else None
                        break
                    elif any(keyword in topic for keyword in ["チーム", "協力", "一緒"]):
                        # 行動指針9「良いことは即シェアし、分かち合う」
                        messages.append("チームで協力してるウル！素晴らしいウル🐺")
                        matched_guideline = self.guidelines[8] if len(self.guidelines) > 8 else None
                        break

        # 4. 締めの言葉（心理的安全性）
        messages.append("困ったらいつでも話しかけてウル🐺💙")

        return "\n".join(messages), matched_guideline

    def generate_weekly_encouragement(
        self,
        user_name: str,
        total_completed_tasks: int,
        goal_progress: Optional[GoalProgress] = None,
        achievements: List[str] = None
    ) -> Tuple[str, Optional[Dict[str, Any]]]:
        """
        週報用の励ましメッセージを生成

        より振り返り重視・成長を可視化する内容
        """
        matched_guideline = None

        if not MVV_AVAILABLE:
            return self._fallback_weekly_message(user_name, total_completed_tasks), None

        messages = []

        # 1. 週の成果を称える（力の欲求 - 達成感）
        if total_completed_tasks >= 10:
            messages.append(f"今週は{total_completed_tasks}件のタスクを完了！素晴らしい成果ウル🐺✨")
            # 行動指針7「プロとして期待を超える」
            matched_guideline = self.guidelines[6] if len(self.guidelines) > 6 else None
        elif total_completed_tasks >= 5:
            messages.append(f"今週は{total_completed_tasks}件のタスクを完了したウル！着実に進んでるウル🐺")
        elif total_completed_tasks > 0:
            messages.append(f"今週は{total_completed_tasks}件のタスクを完了したウル！一歩一歩前進ウル🐺")
        else:
            messages.append("今週もお疲れ様ウル🐺")

        # 2. 目標進捗の振り返り
        if goal_progress:
            if goal_progress.progress_rate >= 100:
                messages.append("🎉 目標達成おめでとうウル！やったウル！🎉")
                messages.append("この経験が次の挑戦に繋がるウル✨")
                # 行動指針1「理想の未来のために何をすべきか考え、行動する」
                matched_guideline = self.guidelines[0] if len(self.guidelines) > 0 else None
            elif goal_progress.progress_rate >= 80:
                messages.append(f"目標達成まであと少し！（{goal_progress.progress_rate:.0f}%）来週で決めようウル🐺")
            elif goal_progress.progress_rate >= 50:
                messages.append(f"目標の半分を超えたウル！（{goal_progress.progress_rate:.0f}%）順調ウル🐺")
            else:
                messages.append(f"目標に向けて{goal_progress.progress_rate:.0f}%まで進んだウル")
                messages.append("小さな進歩も大切ウル。焦らず進もうウル🐺")

        # 3. MVVに繋げる言葉
        messages.append("")
        messages.append("━━━━━━━━━━━━━━━━━━")
        if self.mvv:
            messages.append(f"🐺 ソウルシンクスのミッション「{self.mvv.get('mission', {}).get('statement', '可能性の解放')}」")
            messages.append(f"{user_name}さんの今週の頑張りが、まさに可能性の解放に繋がってるウル✨")

        # 4. 来週への期待（未来志向）
        messages.append("")
        messages.append("来週も一緒に頑張ろうウル！いつでも話しかけてウル🐺💙")

        return "\n".join(messages), matched_guideline

    def match_achievement_to_guideline(self, achievement: str) -> Optional[Dict[str, Any]]:
        """
        成果と行動指針10箇条をマッチング

        Args:
            achievement: 成果の説明

        Returns:
            マッチした行動指針 or None
        """
        if not MVV_AVAILABLE or not self.guidelines:
            return None

        # キーワードベースのマッチング
        keyword_map = {
            0: ["未来", "将来", "ビジョン", "3年後", "理想"],  # 1. 理想の未来のために
            1: ["挑戦", "新しい", "チャレンジ", "初めて", "やったことない"],  # 2. 挑戦を楽しみ
            2: ["自分で", "主体的", "率先", "自ら"],  # 3. 自分が源
            3: ["関わり方", "アプローチ", "コミュニケーション"],  # 4. 人を変えず自分の関わり方を
            4: ["先", "将来", "繋がる", "影響"],  # 5. 目の前の人の『その先』まで
            5: ["信じる", "可能性", "期待"],  # 6. 相手以上に相手の未来を信じる
            6: ["プロ", "期待以上", "品質", "完璧"],  # 7. プロとして期待を超える
            7: ["事実", "現実", "データ", "数字"],  # 8. 事実と向き合い
            8: ["共有", "シェア", "チーム", "教える"],  # 9. 良いことは即シェア
            9: ["魂", "全力", "込める", "こだわり"],  # 10. 目の前のことに魂を込める
        }

        achievement_lower = achievement.lower()
        for idx, keywords in keyword_map.items():
            for keyword in keywords:
                if keyword in achievement_lower:
                    return self.guidelines[idx] if idx < len(self.guidelines) else None

        return None

    def _fallback_daily_message(self, user_name: str, task_count: int) -> str:
        """MVV利用不可時のフォールバック"""
        if task_count > 0:
            return f"今日は{task_count}件のタスクを完了したウル！お疲れ様ウル🐺"
        return f"{user_name}さん、今日もお疲れ様ウル🐺"

    def _fallback_weekly_message(self, user_name: str, task_count: int) -> str:
        """MVV利用不可時のフォールバック"""
        if task_count > 0:
            return f"今週は{task_count}件のタスクを完了したウル！お疲れ様ウル🐺"
        return f"{user_name}さん、今週もお疲れ様ウル🐺"


# ============================================================
# 4. 日報生成クラス
# ============================================================

class DailyReportGenerator:
    """日報自動生成（v10.23.2: Phase 2.5 + MVV統合）"""

    def __init__(self, organization_id: str = "default"):
        self.organization_id = organization_id
        self.pool = get_db_pool()
        self.goal_fetcher = GoalProgressFetcher(self.pool)
        self.encouragement_generator = EncouragementGenerator()

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

        # v10.23.2: Phase 2.5目標進捗を取得
        goal_progress = None
        account_id = user_id.replace("chatwork_", "") if user_id.startswith("chatwork_") else user_id
        uuid_user_id = self.goal_fetcher.get_user_id_from_account_id(account_id)
        if uuid_user_id:
            goal_progress = self.goal_fetcher.get_active_goal(uuid_user_id)

        # v10.23.2: MVV・組織論ベースの励ましメッセージを生成
        all_topics = []
        for s in summaries:
            all_topics.extend(s.key_topics)

        encouragement_message, matched_guideline = self.encouragement_generator.generate_daily_encouragement(
            user_name=user_name,
            completed_task_count=len(completed_tasks),
            goal_progress=goal_progress,
            topics=all_topics
        )

        # 日報テキストを生成
        report_text = self._generate_report_text(
            user_name=user_name,
            target_date=target_date,
            summaries=summaries,
            completed_tasks=completed_tasks,
            goal_progress=goal_progress,
            encouragement_message=encouragement_message
        )

        return DailyReport(
            user_id=user_id,
            user_name=user_name,
            report_date=target_date,
            completed_tasks=completed_tasks,
            summaries=summaries,
            report_text=report_text,
            goal_progress=goal_progress,
            matched_guideline=matched_guideline,
            encouragement_message=encouragement_message
        )

    def _get_daily_summaries(self, user_id: str, target_date: date) -> List[DailySummary]:
        """B1サマリーから当日の会話サマリーを取得"""
        with self.pool.connect() as conn:
            result = conn.execute(text("""
                SELECT
                    DATE(conversation_end) as summary_date,
                    key_topics,
                    mentioned_persons,
                    mentioned_tasks,
                    summary_text,
                    message_count
                FROM conversation_summaries
                WHERE user_id::text = :user_id
                  AND DATE(conversation_end) = :target_date
                ORDER BY conversation_end DESC
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
        completed_tasks: List[CompletedTask],
        goal_progress: Optional[GoalProgress] = None,
        encouragement_message: str = ""
    ) -> str:
        """日報テキストを生成（v10.23.2: 目標進捗 + MVV励ましメッセージ追加）"""
        date_str = target_date.strftime('%Y/%m/%d')
        weekday_ja = ["月", "火", "水", "木", "金", "土", "日"][target_date.weekday()]

        lines = [
            f"📋 **日報下書き** ({date_str} {weekday_ja})",
            f"担当: {user_name}",
            "",
            "---",
            ""
        ]

        # v10.23.2追加: 目標進捗セクション（Phase 2.5連動）
        if goal_progress:
            lines.append("## 🎯 目標進捗")
            lines.append(f"**{goal_progress.title}**")

            # 進捗バーを生成
            progress_bar = self._generate_progress_bar(goal_progress.progress_rate)
            lines.append(f"進捗: {progress_bar} {goal_progress.progress_rate:.0f}%")

            if goal_progress.target_value and goal_progress.unit:
                lines.append(f"（{goal_progress.current_value:.0f} / {goal_progress.target_value:.0f} {goal_progress.unit}）")

            # WHY（なぜこの目標か）を表示
            if goal_progress.why_answer:
                why_short = goal_progress.why_answer[:100] + "..." if len(goal_progress.why_answer) > 100 else goal_progress.why_answer
                lines.append(f"")
                lines.append(f"💡 **WHY（想い）**: {why_short}")

            # HOW（行動目標）を表示
            if goal_progress.how_answer:
                how_short = goal_progress.how_answer[:100] + "..." if len(goal_progress.how_answer) > 100 else goal_progress.how_answer
                lines.append(f"💪 **HOW（行動）**: {how_short}")

            lines.append("")

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

        # v10.23.2追加: MVV・組織論ベースの励ましメッセージ
        lines.append("---")
        lines.append("")
        if encouragement_message:
            lines.append(encouragement_message)
        else:
            lines.append("🐺 ソウルくんが自動生成した下書きウル！必要に応じて編集してください。")

        return "\n".join(lines)

    def _generate_progress_bar(self, progress_rate: float, width: int = 10) -> str:
        """
        テキストベースの進捗バーを生成

        例: [████████░░] 80%
        """
        filled = int(progress_rate / 100 * width)
        empty = width - filled
        return "[" + "█" * filled + "░" * empty + "]"


# ============================================================
# 5. 週報生成クラス
# ============================================================

class WeeklyReportGenerator:
    """週報自動生成（v10.23.2: Phase 2.5 + MVV統合）"""

    def __init__(self, organization_id: str = "default"):
        self.organization_id = organization_id
        self.daily_generator = DailyReportGenerator(organization_id)
        self.pool = get_db_pool()
        self.goal_fetcher = GoalProgressFetcher(self.pool)
        self.encouragement_generator = EncouragementGenerator()

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

        # v10.23.2: Phase 2.5目標進捗を取得
        goal_progress = None
        account_id = user_id.replace("chatwork_", "") if user_id.startswith("chatwork_") else user_id
        uuid_user_id = self.goal_fetcher.get_user_id_from_account_id(account_id)
        if uuid_user_id:
            goal_progress = self.goal_fetcher.get_active_goal(uuid_user_id)

        # v10.23.2: 週の成果リストを生成
        weekly_achievements = self._extract_weekly_achievements(daily_reports, all_topics)

        # v10.23.2: MVV・組織論ベースの励ましメッセージを生成
        encouragement_message, _ = self.encouragement_generator.generate_weekly_encouragement(
            user_name=user_name,
            total_completed_tasks=len(all_completed_tasks),
            goal_progress=goal_progress,
            achievements=weekly_achievements
        )

        # 週報テキストを生成
        report_text = self._generate_report_text(
            user_name=user_name,
            week_start=week_start,
            week_end=week_end,
            all_completed_tasks=all_completed_tasks,
            all_topics=all_topics,
            daily_reports=daily_reports,
            goal_progress=goal_progress,
            encouragement_message=encouragement_message
        )

        return WeeklyReport(
            user_id=user_id,
            user_name=user_name,
            week_start=week_start,
            week_end=week_end,
            daily_reports=daily_reports,
            report_text=report_text,
            goal_progress=goal_progress,
            weekly_achievements=weekly_achievements,
            encouragement_message=encouragement_message
        )

    def _extract_weekly_achievements(
        self,
        daily_reports: List[DailyReport],
        all_topics: List[str]
    ) -> List[str]:
        """
        週の成果を抽出

        - 完了タスクから主要な成果を抽出
        - トピックから取り組み事項を抽出
        """
        achievements = []

        # 完了タスクから抽出
        for report in daily_reports:
            for task in report.completed_tasks[:3]:  # 各日最大3件
                achievements.append(task.body)

        # 重複を除去して最大10件
        unique_achievements = list(set(achievements))[:10]
        return unique_achievements

    def _generate_report_text(
        self,
        user_name: str,
        week_start: date,
        week_end: date,
        all_completed_tasks: List[CompletedTask],
        all_topics: List[str],
        daily_reports: List[DailyReport],
        goal_progress: Optional[GoalProgress] = None,
        encouragement_message: str = ""
    ) -> str:
        """週報テキストを生成（v10.23.2: 目標進捗 + MVV励ましメッセージ追加）"""
        start_str = week_start.strftime('%Y/%m/%d')
        end_str = week_end.strftime('%Y/%m/%d')

        lines = [
            f"📊 **週報下書き** ({start_str} 〜 {end_str})",
            f"担当: {user_name}",
            "",
            "---",
            ""
        ]

        # v10.23.2追加: 目標進捗セクション（Phase 2.5連動）
        if goal_progress:
            lines.append("## 🎯 今週の目標進捗")
            lines.append(f"**{goal_progress.title}**")

            # 進捗バーを生成
            progress_bar = self._generate_progress_bar(goal_progress.progress_rate)
            lines.append(f"進捗: {progress_bar} {goal_progress.progress_rate:.0f}%")

            if goal_progress.target_value and goal_progress.unit:
                lines.append(f"（{goal_progress.current_value:.0f} / {goal_progress.target_value:.0f} {goal_progress.unit}）")

            # WHY（なぜこの目標か）を表示
            if goal_progress.why_answer:
                why_short = goal_progress.why_answer[:100] + "..." if len(goal_progress.why_answer) > 100 else goal_progress.why_answer
                lines.append(f"")
                lines.append(f"💡 **WHY（想い）**: {why_short}")

            # 期限表示
            if goal_progress.period_end:
                days_left = (goal_progress.period_end - date.today()).days
                if days_left > 0:
                    lines.append(f"📅 残り{days_left}日（{goal_progress.period_end.strftime('%m/%d')}まで）")
                elif days_left == 0:
                    lines.append(f"📅 今日が期限！")
                else:
                    lines.append(f"📅 期限を過ぎました（{-days_left}日超過）")

            lines.append("")

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

        # v10.23.2追加: MVV・組織論ベースの励ましメッセージ
        lines.append("---")
        lines.append("")
        if encouragement_message:
            lines.append(encouragement_message)
        else:
            lines.append(f"🐺 ソウルくんが{len(daily_reports)}日分のデータから自動生成した下書きウル！")
            lines.append("必要に応じて編集してから提出してください。")

        return "\n".join(lines)

    def _generate_progress_bar(self, progress_rate: float, width: int = 10) -> str:
        """テキストベースの進捗バーを生成"""
        filled = int(progress_rate / 100 * width)
        empty = width - filled
        return "[" + "█" * filled + "░" * empty + "]"


# ============================================================
# 6. レポート配信クラス
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
                    cu.account_id,
                    cu.name,
                    cu.account_id as user_id
                FROM chatwork_users cu
                INNER JOIN conversation_summaries cs
                    ON cs.user_id::text = CONCAT('chatwork_', cu.account_id::text)
                WHERE cs.conversation_end >= NOW() - INTERVAL '7 days'
                  AND cu.account_id IS NOT NULL
                ORDER BY cu.name
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
# 7. メイン実行関数
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
# 8. エクスポート
# ============================================================

__all__ = [
    # データクラス
    "GoalProgress",
    "DailySummary",
    "CompletedTask",
    "DailyReport",
    "WeeklyReport",
    # クラス
    "GoalProgressFetcher",
    "EncouragementGenerator",
    "DailyReportGenerator",
    "WeeklyReportGenerator",
    "ReportDistributor",
    # 関数
    "run_daily_report_generation",
    "run_weekly_report_generation",
]
