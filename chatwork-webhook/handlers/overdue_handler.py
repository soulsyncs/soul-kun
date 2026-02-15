"""
遅延管理ハンドラー

main.pyから分割された遅延タスク管理・エスカレーションの機能を提供する。

分割元: chatwork-webhook/main.py
分割日: 2026-01-25
バージョン: v10.24.9 (営業日判定追加)
"""

import httpx
import traceback
import sqlalchemy
from sqlalchemy import bindparam
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any, Callable, Tuple

# 日本標準時
JST = timezone(timedelta(hours=9))

# ★★★ v10.24.9: 営業日判定（土日祝日リマインドスキップ） ★★★
try:
    from lib.business_day import (
        is_business_day,
        get_non_business_day_reason,
    )
    _BUSINESS_DAY_AVAILABLE = True
except ImportError:
    _BUSINESS_DAY_AVAILABLE = False
    print("⚠️ lib/business_day が見つかりません。営業日判定をスキップ")

    # フォールバック: 土日のみ判定
    def is_business_day(target_date=None):
        if target_date is None:
            target_date = datetime.now(JST).date()
        return target_date.weekday() < 5  # 月〜金

    def get_non_business_day_reason(target_date=None):
        if target_date is None:
            target_date = datetime.now(JST).date()
        weekday = target_date.weekday()
        if weekday == 5:
            return "土曜日"
        if weekday == 6:
            return "日曜日"
        return None


class OverdueHandler:
    """
    遅延タスクの管理とエスカレーションを行うハンドラークラス

    外部依存を注入することで、main.pyとの疎結合を実現。
    """

    def __init__(
        self,
        get_pool: Callable,
        get_secret: Callable,
        get_direct_room: Callable,
        get_overdue_days_func: Callable = None,
        admin_room_id: str = None,
        escalation_days: int = 3,
        prepare_task_display_text: Callable = None
    ):
        """
        Args:
            get_pool: DB接続プールを取得する関数
            get_secret: Secret Managerから秘密情報を取得する関数
            get_direct_room: DMルームIDを取得する関数
            get_overdue_days_func: 期限超過日数を計算する関数（オプション）
            admin_room_id: 管理部のルームID
            escalation_days: エスカレーションまでの日数
            prepare_task_display_text: タスク本文を適切に要約する関数（オプション）
        """
        self.get_pool = get_pool
        self.get_secret = get_secret
        self.get_direct_room = get_direct_room
        self.get_overdue_days_func = get_overdue_days_func
        self.admin_room_id = admin_room_id
        self.escalation_days = escalation_days
        self.prepare_task_display_text = prepare_task_display_text

        # DM不可通知バッファ（まとめ送信用）
        self._dm_unavailable_buffer: List[Dict] = []

    def _format_body_short(self, body: str, max_length: int = 40) -> str:
        """
        タスク本文を表示用に適切な長さに整形する

        Args:
            body: タスク本文
            max_length: 最大文字数（デフォルト40）

        Returns:
            整形されたタスク本文
        """
        if not body:
            return "（タスク内容なし）"

        # 注入されたprepare_task_display_textがあれば使用
        if self.prepare_task_display_text:
            try:
                return self.prepare_task_display_text(body, max_length=max_length)
            except Exception:
                pass  # フォールバックへ

        # フォールバック: 自然な位置で切る
        if len(body) <= max_length:
            return body

        # 句点、読点、助詞の後ろで切る（途切れ防止）
        truncated = body[:max_length]

        # 句点「。」の位置を探す
        last_period = truncated.rfind("。")
        if last_period > max_length // 2:
            return truncated[:last_period + 1]

        # 読点「、」の位置を探す
        last_comma = truncated.rfind("、")
        if last_comma > max_length // 2:
            return truncated[:last_comma + 1] + "..."

        # 助詞の後ろで切る
        for particle in ["を", "に", "で", "が", "は", "の", "と", "へ"]:
            pos = truncated.rfind(particle)
            if pos > max_length // 2:
                return truncated[:pos + 1] + "..."

        # どれも見つからなければ、そのまま切って「...」を付ける
        return truncated + "..."

    def _get_task_display_text(self, task: Dict, max_length: int = 40) -> str:
        """
        タスクの表示用テキストを取得（v10.25.0追加）

        summaryがあればそのまま使用、なければbodyから生成

        Args:
            task: タスク情報（"summary", "body"キーを持つdict）
            max_length: 最大文字数（summaryがない場合のフォールバック用）

        Returns:
            表示用テキスト
        """
        summary = task.get("summary")
        if summary:
            return summary
        return self._format_body_short(task.get("body", ""), max_length=max_length)

    def get_overdue_days(self, limit_time: int) -> int:
        """
        期限超過日数を計算

        Args:
            limit_time: UNIXタイムスタンプ

        Returns:
            超過日数（0以上）
        """
        if self.get_overdue_days_func:
            return self.get_overdue_days_func(limit_time)

        # フォールバック: 内部実装
        if limit_time is None:
            return 0

        try:
            now = datetime.now(JST)
            today = now.date()

            if isinstance(limit_time, (int, float)):
                limit_date = datetime.fromtimestamp(limit_time, tz=JST).date()
            elif hasattr(limit_time, 'date'):
                limit_date = limit_time.date()
            else:
                print(f"⚠️ get_overdue_days: 不明なlimit_time型: {type(limit_time)}")
                return 0
        except Exception as e:
            print(f"⚠️ get_overdue_days: 変換エラー: {limit_time}, error={e}")
            return 0

        delta = (today - limit_date).days
        return max(0, delta)

    def ensure_overdue_tables(self) -> None:
        """遅延管理用テーブルが存在しない場合は作成"""
        try:
            pool = self.get_pool()
            with pool.begin() as conn:
                # 督促履歴テーブル
                conn.execute(sqlalchemy.text("""
                    CREATE TABLE IF NOT EXISTS task_overdue_reminders (
                        id SERIAL PRIMARY KEY,
                        task_id BIGINT NOT NULL,
                        account_id BIGINT NOT NULL,
                        organization_id VARCHAR(100) NOT NULL DEFAULT '5f98365f-e7c5-4f48-9918-7fe9aabae5df',
                        reminder_date DATE NOT NULL,
                        overdue_days INTEGER NOT NULL,
                        escalated BOOLEAN DEFAULT FALSE,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(task_id, reminder_date)
                    );
                """))
                conn.execute(sqlalchemy.text("""
                    CREATE INDEX IF NOT EXISTS idx_overdue_reminders_task_id
                    ON task_overdue_reminders(task_id);
                """))

                # 期限変更履歴テーブル
                conn.execute(sqlalchemy.text("""
                    CREATE TABLE IF NOT EXISTS task_limit_changes (
                        id SERIAL PRIMARY KEY,
                        task_id BIGINT NOT NULL,
                        organization_id VARCHAR(100) NOT NULL DEFAULT '5f98365f-e7c5-4f48-9918-7fe9aabae5df',
                        old_limit_time BIGINT,
                        new_limit_time BIGINT,
                        detected_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        reason_asked BOOLEAN DEFAULT FALSE,
                        reason_received BOOLEAN DEFAULT FALSE,
                        reason_text TEXT,
                        reported_to_admin BOOLEAN DEFAULT FALSE
                    );
                """))
                conn.execute(sqlalchemy.text("""
                    CREATE INDEX IF NOT EXISTS idx_limit_changes_task_id
                    ON task_limit_changes(task_id);
                """))

                # DMルームキャッシュテーブル
                conn.execute(sqlalchemy.text("""
                    CREATE TABLE IF NOT EXISTS dm_room_cache (
                        account_id BIGINT PRIMARY KEY,
                        dm_room_id BIGINT NOT NULL,
                        organization_id VARCHAR(100) NOT NULL DEFAULT '5f98365f-e7c5-4f48-9918-7fe9aabae5df',
                        cached_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    );
                """))

                # エスカレーション専用テーブル
                conn.execute(sqlalchemy.text("""
                    CREATE TABLE IF NOT EXISTS task_escalations (
                        id SERIAL PRIMARY KEY,
                        task_id BIGINT NOT NULL,
                        organization_id VARCHAR(100) NOT NULL DEFAULT '5f98365f-e7c5-4f48-9918-7fe9aabae5df',
                        escalated_date DATE NOT NULL,
                        escalated_to_requester BOOLEAN DEFAULT FALSE,
                        escalated_to_admin BOOLEAN DEFAULT FALSE,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(task_id, escalated_date)
                    );
                """))
                conn.execute(sqlalchemy.text("""
                    CREATE INDEX IF NOT EXISTS idx_task_escalations_task_id
                    ON task_escalations(task_id);
                """))

                print("✅ 遅延管理テーブルの確認/作成完了")
        except Exception as e:
            print(f"⚠️ 遅延管理テーブル作成エラー: {e}")
            traceback.print_exc()

    def process_overdue_tasks(self) -> dict:
        """
        遅延タスクを処理：督促送信 + エスカレーション
        毎日8:30に実行（remind_tasksから呼び出し）

        ★★★ v10.24.9: 営業日判定 ★★★
        - 土日祝日は遅延タスク報告をスキップ

        Returns:
            処理結果を含む辞書
        """
        # ★★★ v10.24.9: 営業日判定 ★★★
        if not is_business_day():
            reason = get_non_business_day_reason()
            print(f"📅 本日は{reason}のため、遅延タスク報告をスキップします")
            return {
                "status": "skipped",
                "reason": f"本日は{reason}のため、遅延タスク報告をスキップしました",
                "is_business_day": False
            }

        # バッファをリセット
        self._dm_unavailable_buffer = []

        print("=" * 50)
        print("🔔 遅延タスク処理開始")
        print("=" * 50)

        try:
            # テーブル確認
            self.ensure_overdue_tables()

            pool = self.get_pool()
            now = datetime.now(JST)
            today = now.date()

            # 期限超過の未完了タスクを取得
            with pool.connect() as conn:
                result = conn.execute(sqlalchemy.text("""
                    SELECT
                        task_id, room_id, assigned_to_account_id, assigned_by_account_id,
                        body, limit_time, assigned_to_name, assigned_by_name
                    FROM chatwork_tasks
                    WHERE status = 'open'
                      AND skip_tracking = FALSE
                      AND limit_time IS NOT NULL
                      AND limit_time < :today_timestamp
                    ORDER BY assigned_to_account_id, limit_time
                """), {"today_timestamp": int(datetime.combine(today, datetime.min.time()).replace(tzinfo=JST).timestamp())})

                overdue_tasks = result.fetchall()

            if not overdue_tasks:
                print("✅ 期限超過タスクはありません")
                return

            print(f"📋 期限超過タスク数: {len(overdue_tasks)}")

            # 担当者ごとにグループ化
            tasks_by_assignee = {}
            unassigned_tasks = []

            for task in overdue_tasks:
                account_id = task[2]  # assigned_to_account_id

                if account_id is None:
                    unassigned_tasks.append({
                        "task_id": task[0],
                        "room_id": task[1],
                        "assigned_to_account_id": task[2],
                        "assigned_by_account_id": task[3],
                        "body": task[4],
                        "limit_time": task[5],
                        "assigned_to_name": task[6] or "（未設定）",
                        "assigned_by_name": task[7]
                    })
                    continue

                if account_id not in tasks_by_assignee:
                    tasks_by_assignee[account_id] = []
                tasks_by_assignee[account_id].append({
                    "task_id": task[0],
                    "room_id": task[1],
                    "assigned_to_account_id": task[2],
                    "assigned_by_account_id": task[3],
                    "body": task[4],
                    "limit_time": task[5],
                    "assigned_to_name": task[6],
                    "assigned_by_name": task[7]
                })

            # 担当者未設定タスクがあれば管理部に報告
            if unassigned_tasks:
                self.report_unassigned_overdue_tasks(unassigned_tasks)

            # 担当者ごとに個人チャットへ督促送信
            for account_id, tasks in tasks_by_assignee.items():
                self.send_overdue_reminder_to_dm(account_id, tasks, today)

            # エスカレーション処理
            self.process_escalations(overdue_tasks, today)

            # DM不可通知をまとめて送信
            self.flush_dm_unavailable_notifications()

            print("=" * 50)
            print("🔔 遅延タスク処理完了")
            print("=" * 50)

        except Exception as e:
            print(f"❌ 遅延タスク処理エラー: {e}")
            traceback.print_exc()
            # エラー時もバッファをフラッシュ
            try:
                self.flush_dm_unavailable_notifications()
            except:
                pass

    def send_overdue_reminder_to_dm(
        self,
        account_id: str,
        tasks: List[Dict],
        today
    ) -> None:
        """
        担当者の個人チャットに遅延タスクをまとめて督促送信

        Args:
            account_id: 担当者のアカウントID
            tasks: タスクのリスト
            today: 今日の日付
        """
        if not tasks:
            return

        assignee_name = tasks[0].get("assigned_to_name", "担当者")

        # 個人チャットを取得
        dm_room_id = self.get_direct_room(account_id)
        if not dm_room_id:
            print(f"⚠️ {assignee_name}さんの個人チャットが取得できませんでした → 管理部に通知")
            self.notify_dm_not_available(assignee_name, account_id, tasks, "督促")
            return

        pool = self.get_pool()

        # 今日既に督促済みか確認
        with pool.connect() as conn:
            task_ids = [t["task_id"] for t in tasks]
            stmt = sqlalchemy.text("""
                SELECT task_id FROM task_overdue_reminders
                WHERE task_id IN :task_ids AND reminder_date = :today
            """).bindparams(bindparam("task_ids", expanding=True))
            result = conn.execute(stmt, {"task_ids": task_ids, "today": today})
            already_reminded = set(row[0] for row in result.fetchall())

        # 未督促のタスクだけ抽出
        tasks_to_remind = [t for t in tasks if t["task_id"] not in already_reminded]

        if not tasks_to_remind:
            print(f"✅ {assignee_name}さんへの督促は今日既に送信済み")
            return

        # メッセージ作成
        message_lines = [f"{assignee_name}さん\n", "📌 期限超過のタスクがありますウル！\n"]

        for i, task in enumerate(tasks_to_remind, 1):
            overdue_days = self.get_overdue_days(task["limit_time"])
            limit_date = datetime.fromtimestamp(task["limit_time"], tz=JST).strftime("%m/%d") if task["limit_time"] else "不明"
            requester = task.get("assigned_by_name") or "依頼者"
            # v10.25.0: summaryを優先使用
            body_short = self._get_task_display_text(task, max_length=40)

            message_lines.append(f"{i}. 「{body_short}」（依頼者: {requester} / 期限: {limit_date} / {overdue_days}日超過）")

        message_lines.append("\n遅れている理由と、いつ頃完了できそうか教えてほしいウル🐺")
        message = "\n".join(message_lines)

        # 送信
        api_token = self.get_secret("SOULKUN_CHATWORK_TOKEN")
        response = httpx.post(
            f"https://api.chatwork.com/v2/rooms/{dm_room_id}/messages",
            headers={"X-ChatWorkToken": api_token},
            data={"body": message},
            timeout=10.0
        )

        if response.status_code == 200:
            print(f"✅ {assignee_name}さんへの督促送信成功（{len(tasks_to_remind)}件）")

            # 督促履歴を記録
            with pool.begin() as conn:
                for task in tasks_to_remind:
                    overdue_days = self.get_overdue_days(task["limit_time"])
                    conn.execute(
                        sqlalchemy.text("""
                            INSERT INTO task_overdue_reminders (task_id, account_id, reminder_date, overdue_days)
                            VALUES (:task_id, :account_id, :reminder_date, :overdue_days)
                            ON CONFLICT (task_id, reminder_date) DO NOTHING
                        """),
                        {
                            "task_id": task["task_id"],
                            "account_id": account_id,
                            "reminder_date": today,
                            "overdue_days": overdue_days
                        }
                    )
        else:
            print(f"❌ {assignee_name}さんへの督促送信失敗: {response.status_code}")

    def process_escalations(self, overdue_tasks: List, today) -> None:
        """
        3日以上超過のタスクをエスカレーション（依頼者+管理部に報告）

        Args:
            overdue_tasks: 期限超過タスクのリスト
            today: 今日の日付
        """
        pool = self.get_pool()

        # エスカレーション対象を抽出
        escalation_tasks = []
        for task in overdue_tasks:
            task_dict = {
                "task_id": task[0],
                "room_id": task[1],
                "assigned_to_account_id": task[2],
                "assigned_by_account_id": task[3],
                "body": task[4],
                "limit_time": task[5],
                "assigned_to_name": task[6],
                "assigned_by_name": task[7]
            }
            overdue_days = self.get_overdue_days(task_dict["limit_time"])
            if overdue_days >= self.escalation_days:
                task_dict["overdue_days"] = overdue_days
                escalation_tasks.append(task_dict)

        if not escalation_tasks:
            print("✅ エスカレーション対象タスクはありません")
            return

        # 今日のエスカレーション済みを確認
        with pool.connect() as conn:
            task_ids = [t["task_id"] for t in escalation_tasks]
            stmt = sqlalchemy.text("""
                SELECT task_id FROM task_escalations
                WHERE task_id IN :task_ids AND escalated_date = :today
            """).bindparams(bindparam("task_ids", expanding=True))
            result = conn.execute(stmt, {"task_ids": task_ids, "today": today})
            already_escalated = set(row[0] for row in result.fetchall())

        tasks_to_escalate = [t for t in escalation_tasks if t["task_id"] not in already_escalated]

        if not tasks_to_escalate:
            print("✅ エスカレーションは今日既に送信済み")
            return

        print(f"🚨 エスカレーション対象: {len(tasks_to_escalate)}件")

        # 送信前に記録（スパム防止）
        with pool.begin() as conn:
            for task in tasks_to_escalate:
                conn.execute(
                    sqlalchemy.text("""
                        INSERT INTO task_escalations (task_id, escalated_date)
                        VALUES (:task_id, :today)
                        ON CONFLICT (task_id, escalated_date) DO NOTHING
                    """),
                    {"task_id": task["task_id"], "today": today}
                )
        print(f"✅ エスカレーション記録を作成（{len(tasks_to_escalate)}件）")

        # 依頼者ごとにグループ化して報告
        tasks_by_requester = {}
        for task in tasks_to_escalate:
            requester_id = task["assigned_by_account_id"]
            if requester_id and requester_id not in tasks_by_requester:
                tasks_by_requester[requester_id] = []
            if requester_id:
                tasks_by_requester[requester_id].append(task)

        # 依頼者ごとの送信結果を記録
        requester_success_map = {}
        for requester_id, tasks in tasks_by_requester.items():
            requester_success_map[requester_id] = self.send_escalation_to_requester(requester_id, tasks)

        # 管理部への報告
        admin_success = self.send_escalation_to_admin(tasks_to_escalate)

        # 送信結果を更新
        with pool.begin() as conn:
            for task in tasks_to_escalate:
                task_requester_id = task["assigned_by_account_id"]
                task_requester_success = requester_success_map.get(task_requester_id, False)

                conn.execute(
                    sqlalchemy.text("""
                        UPDATE task_escalations
                        SET escalated_to_requester = :requester_success,
                            escalated_to_admin = :admin_success
                        WHERE task_id = :task_id AND escalated_date = :today
                    """),
                    {
                        "task_id": task["task_id"],
                        "today": today,
                        "requester_success": task_requester_success,
                        "admin_success": admin_success
                    }
                )

    def send_escalation_to_requester(self, requester_id: str, tasks: List[Dict]) -> bool:
        """
        依頼者へのエスカレーション報告

        Args:
            requester_id: 依頼者のアカウントID
            tasks: タスクのリスト

        Returns:
            送信成功ならTrue
        """
        if not tasks:
            return False

        requester_name = f"依頼者(ID:{requester_id})"

        dm_room_id = self.get_direct_room(requester_id)
        if not dm_room_id:
            print(f"⚠️ {requester_name}の個人チャットが取得できませんでした → 管理部に通知")
            self.notify_dm_not_available(requester_name, requester_id, tasks, "エスカレーション")
            return False

        message_lines = ["📋 タスク遅延のお知らせウル\n", "あなたが依頼したタスクが3日以上遅延しています：\n"]

        for task in tasks:
            assignee = task.get("assigned_to_name", "担当者")
            # v10.25.0: summaryを優先使用
            body_short = self._get_task_display_text(task, max_length=40)
            limit_date = datetime.fromtimestamp(task["limit_time"], tz=JST).strftime("%m/%d") if task["limit_time"] else "不明"

            message_lines.append(f"・「{body_short}」")
            message_lines.append(f"  担当者: {assignee} / 期限: {limit_date} / {task['overdue_days']}日超過")

        message_lines.append("\nソウルくんから毎日督促していますが、対応が必要かもしれませんウル🐺")
        message = "\n".join(message_lines)

        api_token = self.get_secret("SOULKUN_CHATWORK_TOKEN")
        response = httpx.post(
            f"https://api.chatwork.com/v2/rooms/{dm_room_id}/messages",
            headers={"X-ChatWorkToken": api_token},
            data={"body": message},
            timeout=10.0
        )

        if response.status_code == 200:
            print(f"✅ 依頼者(ID:{requester_id})へのエスカレーション送信成功")
            return True
        else:
            print(f"❌ 依頼者(ID:{requester_id})へのエスカレーション送信失敗: {response.status_code}")
            return False

    def send_escalation_to_admin(self, tasks: List[Dict]) -> bool:
        """
        管理部へのエスカレーション報告

        Args:
            tasks: タスクのリスト

        Returns:
            送信成功ならTrue
        """
        if not tasks:
            return False

        if not self.admin_room_id:
            print("❌ admin_room_idが設定されていません")
            return False

        message_lines = ["[info][title]📊 長期遅延タスク報告[/title]", "以下のタスクが3日以上遅延しています：\n"]

        for i, task in enumerate(tasks, 1):
            assignee = task.get("assigned_to_name", "担当者")
            requester = task.get("assigned_by_name", "依頼者")
            # v10.25.0: summaryを優先使用
            body_short = self._get_task_display_text(task, max_length=40)
            limit_date = datetime.fromtimestamp(task["limit_time"], tz=JST).strftime("%m/%d") if task["limit_time"] else "不明"

            message_lines.append(f"{i}. {assignee}さん「{body_short}」")
            message_lines.append(f"   依頼者: {requester} / 期限: {limit_date} / {task['overdue_days']}日超過")

        message_lines.append("\n引き続き督促を継続しますウル🐺[/info]")
        message = "\n".join(message_lines)

        api_token = self.get_secret("SOULKUN_CHATWORK_TOKEN")
        response = httpx.post(
            f"https://api.chatwork.com/v2/rooms/{self.admin_room_id}/messages",
            headers={"X-ChatWorkToken": api_token},
            data={"body": message},
            timeout=10.0
        )

        if response.status_code == 200:
            print(f"✅ 管理部へのエスカレーション送信成功（{len(tasks)}件）")
            return True
        else:
            print(f"❌ 管理部へのエスカレーション送信失敗: {response.status_code}")
            return False

    def detect_and_report_limit_changes(
        self,
        task_id: str,
        old_limit: int,
        new_limit: int,
        task_info: Dict
    ) -> None:
        """
        タスクの期限変更を検知して報告

        Args:
            task_id: タスクID
            old_limit: 変更前の期限（UNIXタイムスタンプ）
            new_limit: 変更後の期限（UNIXタイムスタンプ）
            task_info: タスク情報
        """
        if old_limit == new_limit:
            return

        if old_limit is None or new_limit is None:
            return

        print(f"🔍 期限変更検知: task_id={task_id}, {old_limit} → {new_limit}")

        pool = self.get_pool()
        api_token = self.get_secret("SOULKUN_CHATWORK_TOKEN")

        # 変更履歴を記録
        try:
            with pool.begin() as conn:
                conn.execute(
                    sqlalchemy.text("""
                        INSERT INTO task_limit_changes (task_id, old_limit_time, new_limit_time)
                        VALUES (:task_id, :old_limit, :new_limit)
                    """),
                    {"task_id": task_id, "old_limit": old_limit, "new_limit": new_limit}
                )
        except Exception as e:
            print(f"⚠️ 期限変更履歴記録エラー: {e}")

        # 日付フォーマット
        old_date_str = datetime.fromtimestamp(old_limit, tz=JST).strftime("%m/%d") if old_limit else "不明"
        new_date_str = datetime.fromtimestamp(new_limit, tz=JST).strftime("%m/%d") if new_limit else "不明"

        # 延長日数計算
        if old_limit and new_limit:
            days_diff = (new_limit - old_limit) // 86400
            diff_str = f"{abs(days_diff)}日{'延長' if days_diff > 0 else '短縮'}"
        else:
            diff_str = "変更"

        assignee_name = task_info.get("assigned_to_name", "担当者")
        assignee_id = task_info.get("assigned_to_account_id")
        requester_name = task_info.get("assigned_by_name", "依頼者")
        # v10.25.0: summaryを優先使用
        body_short = self._get_task_display_text(task_info, max_length=40)

        if not self.admin_room_id:
            print("❌ admin_room_idが設定されていません")
            return

        # 管理部への即時報告
        admin_message = f"""[info][title]📝 タスク期限変更の検知[/title]
以下のタスクの期限が変更されました：

タスク: {body_short}
担当者: {assignee_name}
依頼者: {requester_name}
変更前: {old_date_str}
変更後: {new_date_str}（{diff_str}）

理由を確認中ですウル🐺[/info]"""

        response = httpx.post(
            f"https://api.chatwork.com/v2/rooms/{self.admin_room_id}/messages",
            headers={"X-ChatWorkToken": api_token},
            data={"body": admin_message},
            timeout=10.0
        )

        if response.status_code == 200:
            print("✅ 管理部への期限変更報告送信成功")
        else:
            print(f"❌ 管理部への期限変更報告送信失敗: {response.status_code}")

        # 担当者への理由質問
        if assignee_id:
            dm_room_id = self.get_direct_room(assignee_id)
            if dm_room_id:
                dm_message = f"""{assignee_name}さん

📝 タスクの期限変更を検知しましたウル！

タスク: {body_short}
変更前: {old_date_str} → 変更後: {new_date_str}（{diff_str}）

期限を変更した理由を教えてほしいウル🐺"""

                response = httpx.post(
                    f"https://api.chatwork.com/v2/rooms/{dm_room_id}/messages",
                    headers={"X-ChatWorkToken": api_token},
                    data={"body": dm_message},
                    timeout=10.0
                )

                if response.status_code == 200:
                    print(f"✅ {assignee_name}さんへの期限変更理由質問送信成功")

                    # 理由質問済みフラグを更新
                    try:
                        with pool.begin() as conn:
                            conn.execute(
                                sqlalchemy.text("""
                                    UPDATE task_limit_changes
                                    SET reason_asked = TRUE
                                    WHERE id = (
                                        SELECT id FROM task_limit_changes
                                        WHERE task_id = :task_id
                                        ORDER BY detected_at DESC
                                        LIMIT 1
                                    )
                                """),
                                {"task_id": task_id}
                            )
                    except Exception as e:
                        print(f"⚠️ 理由質問フラグ更新エラー: {e}")
                else:
                    print(f"❌ {assignee_name}さんへの期限変更理由質問送信失敗: {response.status_code}")
            else:
                print(f"⚠️ {assignee_name}さんの個人チャットが取得できませんでした → 管理部に通知")
                task_for_notify = [{"body": task_info["body"]}]
                self.notify_dm_not_available(assignee_name, assignee_id, task_for_notify, "期限変更理由質問")

    def report_unassigned_overdue_tasks(self, tasks: List[Dict]) -> None:
        """
        担当者未設定の遅延タスクを管理部に報告

        Args:
            tasks: タスクのリスト
        """
        if not tasks:
            return

        if not self.admin_room_id:
            print("❌ admin_room_idが設定されていません")
            return

        api_token = self.get_secret("SOULKUN_CHATWORK_TOKEN")

        message_lines = ["[info][title]⚠️ 担当者未設定の遅延タスク[/title]",
                         "以下のタスクは担当者が設定されておらず、督促できません：\n"]

        for i, task in enumerate(tasks[:10], 1):
            # v10.25.0: summaryを優先使用
            body_short = self._get_task_display_text(task, max_length=40)
            requester = task.get("assigned_by_name") or "依頼者不明"
            overdue_days = self.get_overdue_days(task["limit_time"])
            limit_date = datetime.fromtimestamp(task["limit_time"], tz=JST).strftime("%m/%d") if task["limit_time"] else "不明"

            message_lines.append(f"{i}. 「{body_short}」")
            message_lines.append(f"   依頼者: {requester} / 期限: {limit_date} / {overdue_days}日超過")

        if len(tasks) > 10:
            message_lines.append(f"\n...他{len(tasks) - 10}件")

        message_lines.append("\n担当者を設定してくださいウル🐺[/info]")
        message = "\n".join(message_lines)

        try:
            response = httpx.post(
                f"https://api.chatwork.com/v2/rooms/{self.admin_room_id}/messages",
                headers={"X-ChatWorkToken": api_token},
                data={"body": message},
                timeout=10.0
            )

            if response.status_code == 200:
                print(f"✅ 担当者未設定タスク報告送信成功（{len(tasks)}件）")
            else:
                print(f"❌ 担当者未設定タスク報告送信失敗: {response.status_code}")
        except Exception as e:
            print(f"❌ 担当者未設定タスク報告エラー: {e}")

    def notify_dm_not_available(
        self,
        person_name: str,
        account_id: str,
        tasks: List[Dict],
        action_type: str
    ) -> None:
        """
        DMが送れない場合にバッファに追加（まとめ送信用）

        Args:
            person_name: 対象者の名前
            account_id: 対象者のaccount_id
            tasks: 関連タスクのリスト
            action_type: "督促" or "エスカレーション" or "期限変更質問"
        """
        self._dm_unavailable_buffer.append({
            "person_name": person_name,
            "account_id": account_id,
            "tasks": tasks,
            "action_type": action_type
        })
        print(f"📝 DM不可通知をバッファに追加: {person_name}さん（{action_type}）")

    def flush_dm_unavailable_notifications(self) -> None:
        """バッファに溜まったDM不可通知をまとめて1通で送信"""
        if not self._dm_unavailable_buffer:
            return

        if not self.admin_room_id:
            print("❌ admin_room_idが設定されていません")
            self._dm_unavailable_buffer = []
            return

        print(f"📤 DM不可通知をまとめて送信（{len(self._dm_unavailable_buffer)}件）")

        api_token = self.get_secret("SOULKUN_CHATWORK_TOKEN")

        # まとめメッセージを作成
        message_lines = ["[info][title]⚠️ DM送信できなかった通知一覧[/title]"]
        message_lines.append(f"以下の{len(self._dm_unavailable_buffer)}名にDMを送信できませんでした：\n")

        for i, item in enumerate(self._dm_unavailable_buffer[:20], 1):
            person_name = item["person_name"]
            account_id = item["account_id"]
            action_type = item["action_type"]
            tasks = item.get("tasks", [])

            task_hint = ""
            if tasks and len(tasks) > 0:
                # v10.25.0: summaryを優先使用
                body_short = self._get_task_display_text(tasks[0], max_length=25)
                task_hint = f"「{body_short}」"

            message_lines.append(f"{i}. {person_name}（ID:{account_id}）- {action_type} {task_hint}")

        if len(self._dm_unavailable_buffer) > 20:
            message_lines.append(f"\n...他{len(self._dm_unavailable_buffer) - 20}名")

        message_lines.append("\n【対応】")
        message_lines.append("ChatWorkで上記の方々がソウルくんをコンタクト追加するか、")
        message_lines.append("管理者がソウルくんアカウントからコンタクト追加してください。[/info]")

        message = "\n".join(message_lines)

        try:
            response = httpx.post(
                f"https://api.chatwork.com/v2/rooms/{self.admin_room_id}/messages",
                headers={"X-ChatWorkToken": api_token},
                data={"body": message},
                timeout=10.0
            )

            if response.status_code == 200:
                print(f"✅ 管理部へのDM不可通知まとめ送信成功（{len(self._dm_unavailable_buffer)}件）")
            else:
                print(f"❌ 管理部へのDM不可通知まとめ送信失敗: {response.status_code}")
        except Exception as e:
            print(f"❌ 管理部通知エラー: {e}")

        # バッファをクリア
        self._dm_unavailable_buffer = []
