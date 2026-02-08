"""
タスク管理ハンドラー

main.pyから分割されたChatWorkタスク管理の機能を提供する。

分割元: chatwork-webhook/main.py
分割日: 2026-01-25
バージョン: v10.24.4
"""

import json
import traceback
import sqlalchemy
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List, Callable, Tuple


class TaskHandler:
    """
    ChatWorkタスクの管理を行うハンドラークラス

    外部依存を注入することで、main.pyとの疎結合を実現。
    """

    def __init__(
        self,
        get_pool: Callable,
        get_secret: Callable,
        call_chatwork_api_with_retry: Callable,
        extract_task_subject: Callable = None,
        clean_chatwork_tags: Callable = None,
        prepare_task_display_text: Callable = None,
        validate_summary: Callable = None,
        get_user_primary_department: Callable = None,
        use_text_utils: bool = False,
        organization_id: str = ""
    ):
        """
        Args:
            get_pool: DB接続プールを取得する関数
            get_secret: Secret Managerから秘密情報を取得する関数
            call_chatwork_api_with_retry: ChatWork APIリトライ付き呼び出し関数
            extract_task_subject: タスク件名抽出関数（オプション）
            clean_chatwork_tags: ChatWorkタグクリーニング関数（オプション）
            prepare_task_display_text: タスク表示テキスト準備関数（オプション）
            validate_summary: サマリーバリデーション関数（オプション）
            get_user_primary_department: ユーザーのメイン部署取得関数（オプション）
            use_text_utils: テキストユーティリティを使用するか
            organization_id: テナントID（CLAUDE.md 鉄則#1: 全クエリにorg_idフィルター必須）
        """
        if not organization_id:
            raise ValueError("organization_id is required for TaskHandler")
        self.get_pool = get_pool
        self.get_secret = get_secret
        self.call_chatwork_api_with_retry = call_chatwork_api_with_retry
        self.extract_task_subject = extract_task_subject
        self.clean_chatwork_tags = clean_chatwork_tags
        self.prepare_task_display_text = prepare_task_display_text
        self.validate_summary = validate_summary
        self.get_user_primary_department_func = get_user_primary_department
        self.use_text_utils = use_text_utils
        self.organization_id = organization_id

    @staticmethod
    def _fallback_truncate(text: str, max_length: int = 40) -> str:
        """
        フォールバック用の切り詰め処理

        自然な位置（句点、読点、助詞の後）で切る

        Args:
            text: 切り詰める文字列
            max_length: 最大文字数

        Returns:
            切り詰めた文字列
        """
        if not text:
            return "（タスク内容なし）"

        if len(text) <= max_length:
            return text

        truncated = text[:max_length]

        # 句点、読点、助詞の後ろで切る
        for sep in ["。", "、", "を", "に", "で", "が", "は", "の"]:
            pos = truncated.rfind(sep)
            if pos > max_length // 2:
                return truncated[:pos + 1] + "..."

        return truncated + "..."

    def create_chatwork_task(
        self,
        room_id: str,
        task_body: str,
        assigned_to_account_id: str,
        limit: int = None
    ) -> Optional[Dict]:
        """
        ChatWork APIでタスクを作成（リトライ機構付き）

        Args:
            room_id: ルームID
            task_body: タスク本文
            assigned_to_account_id: 担当者のアカウントID
            limit: 期限（UNIXタイムスタンプ）

        Returns:
            成功時はAPIレスポンス、失敗時はNone
        """
        api_token = self.get_secret("SOULKUN_CHATWORK_TOKEN")
        url = f"https://api.chatwork.com/v2/rooms/{room_id}/tasks"

        data = {
            "body": task_body,
            "to_ids": str(assigned_to_account_id)
        }

        if limit:
            data["limit"] = limit

        print(f"📤 ChatWork API リクエスト: URL={url}, data={data}")

        response, success = self.call_chatwork_api_with_retry(
            method="POST",
            url=url,
            headers={"X-ChatWorkToken": api_token},
            data=data
        )

        if response:
            print(f"📥 ChatWork API レスポンス: status={response.status_code}, body={response.text}")
            if success and response.status_code == 200:
                return response.json()
            else:
                print(f"ChatWork API エラー: {response.status_code} - {response.text}")
        return None

    def complete_chatwork_task(self, room_id: str, task_id: str) -> Optional[Dict]:
        """
        ChatWork APIでタスクを完了にする（リトライ機構付き）

        Args:
            room_id: ルームID
            task_id: タスクID

        Returns:
            成功時はAPIレスポンス、失敗時はNone
        """
        api_token = self.get_secret("SOULKUN_CHATWORK_TOKEN")
        url = f"https://api.chatwork.com/v2/rooms/{room_id}/tasks/{task_id}/status"

        print(f"📤 ChatWork API タスク完了リクエスト: URL={url}")

        response, success = self.call_chatwork_api_with_retry(
            method="PUT",
            url=url,
            headers={"X-ChatWorkToken": api_token},
            data={"body": "done"}
        )

        if response:
            print(f"📥 ChatWork API レスポンス: status={response.status_code}, body={response.text}")
            if success and response.status_code == 200:
                return response.json()
            else:
                print(f"ChatWork API エラー: {response.status_code} - {response.text}")
        return None

    def search_tasks_from_db(
        self,
        room_id: str,
        assigned_to_account_id: str = None,
        assigned_by_account_id: str = None,
        status: str = "open",
        enable_dept_filter: bool = False,
        organization_id: str = None,
        search_all_rooms: bool = False,
        get_user_id_func: Callable = None,
        get_accessible_departments_func: Callable = None
    ) -> List[Dict]:
        """
        DBからタスクを検索

        Args:
            room_id: チャットルームID（search_all_rooms=Trueの場合は無視）
            assigned_to_account_id: 担当者のChatWorkアカウントID
            assigned_by_account_id: 依頼者のChatWorkアカウントID
            status: タスクステータス（"open", "done", "all"）
            enable_dept_filter: True=部署フィルタを有効化（Phase 3.5対応）
            organization_id: 組織ID（部署フィルタ有効時に必要）
            search_all_rooms: True=全ルームからタスクを検索（v10.22.0 BUG-001修正）
            get_user_id_func: ユーザーID取得関数（オプション）
            get_accessible_departments_func: アクセス可能部署取得関数（オプション）

        Returns:
            タスクのリスト
        """
        try:
            pool = self.get_pool()
            with pool.connect() as conn:
                # Phase 3.5: アクセス可能部署の取得（オプション）
                accessible_dept_ids = None
                if enable_dept_filter and assigned_to_account_id:
                    if get_user_id_func and get_accessible_departments_func:
                        user_id = get_user_id_func(conn, assigned_to_account_id)
                        if user_id and organization_id:
                            accessible_dept_ids = get_accessible_departments_func(conn, user_id, organization_id)

                # クエリ構築（v10.22.0: room_id, room_nameを追加、v10.25.0: summaryを追加）
                query = """
                    SELECT task_id, body, limit_time, status, assigned_to_account_id, assigned_by_account_id, department_id, room_id, room_name, summary
                    FROM chatwork_tasks
                """
                params = {}

                # CLAUDE.md 鉄則#1: 全クエリにorganization_idフィルター必須
                query += " WHERE organization_id = :org_id"
                params["org_id"] = self.organization_id

                # v10.22.0: search_all_rooms=Trueの場合はroom_idフィルタをスキップ
                if not search_all_rooms:
                    query += " AND room_id = :room_id"
                    params["room_id"] = room_id

                if assigned_to_account_id:
                    query += " AND assigned_to_account_id = :assigned_to"
                    params["assigned_to"] = assigned_to_account_id

                if assigned_by_account_id:
                    query += " AND assigned_by_account_id = :assigned_by"
                    params["assigned_by"] = assigned_by_account_id

                if status and status != "all":
                    query += " AND status = :status"
                    params["status"] = status

                # Phase 3.5: 部署フィルタ（アクセス可能部署またはNULL）
                if accessible_dept_ids is not None and len(accessible_dept_ids) > 0:
                    placeholders = ", ".join([f":dept_{i}" for i in range(len(accessible_dept_ids))])
                    query += f" AND (department_id IN ({placeholders}) OR department_id IS NULL)"
                    for i, dept_id in enumerate(accessible_dept_ids):
                        params[f"dept_{i}"] = dept_id
                elif accessible_dept_ids is not None and len(accessible_dept_ids) == 0:
                    query += " AND department_id IS NULL"

                query += " ORDER BY limit_time ASC NULLS LAST"

                result = conn.execute(sqlalchemy.text(query), params)
                tasks = result.fetchall()

                return [
                    {
                        "task_id": row[0],
                        "body": row[1],
                        "limit_time": row[2],
                        "status": row[3],
                        "assigned_to_account_id": row[4],
                        "assigned_by_account_id": row[5],
                        "department_id": row[6],
                        "room_id": row[7],
                        "room_name": row[8],
                        "summary": row[9]  # v10.25.0追加: AI生成の要約
                    }
                    for row in tasks
                ]
        except Exception as e:
            print(f"タスク検索エラー: {e}")
            return []

    def update_task_status_in_db(self, task_id: str, status: str) -> bool:
        """
        DBのタスクステータスを更新

        Args:
            task_id: タスクID
            status: 新しいステータス

        Returns:
            成功時True
        """
        try:
            pool = self.get_pool()
            with pool.begin() as conn:
                conn.execute(
                    sqlalchemy.text("""
                        UPDATE chatwork_tasks SET status = :status WHERE task_id = :task_id AND organization_id = :org_id
                    """),
                    {"task_id": task_id, "status": status, "org_id": self.organization_id}
                )
            print(f"✅ タスクステータス更新: task_id={task_id}, status={status}")
            return True
        except Exception as e:
            print(f"タスクステータス更新エラー: {e}")
            traceback.print_exc()
            return False

    def save_chatwork_task_to_db(
        self,
        task_id: str,
        room_id: str,
        assigned_by_account_id: str,
        assigned_to_account_id: str,
        body: str,
        limit_time: int = None
    ) -> bool:
        """
        ChatWorkタスクをデータベースに保存

        v10.18.1: summary生成機能追加

        Args:
            task_id: タスクID
            room_id: ルームID
            assigned_by_account_id: 依頼者のアカウントID
            assigned_to_account_id: 担当者のアカウントID
            body: タスク本文
            limit_time: 期限（UNIXタイムスタンプ）

        Returns:
            成功時True
        """
        try:
            # summary生成
            summary = self._generate_task_summary(body)

            pool = self.get_pool()

            # department_id取得
            department_id = None
            if self.get_user_primary_department_func and assigned_to_account_id:
                try:
                    department_id = self.get_user_primary_department_func(pool, assigned_to_account_id)
                    if department_id:
                        print(f"📁 department_id取得成功: {department_id}")
                except Exception as e:
                    print(f"⚠️ department_id取得エラー: {e}")

            with pool.begin() as conn:
                conn.execute(
                    sqlalchemy.text("""
                        INSERT INTO chatwork_tasks
                        (task_id, room_id, assigned_by_account_id, assigned_to_account_id, body, limit_time, status, department_id, summary, organization_id)
                        VALUES (:task_id, :room_id, :assigned_by, :assigned_to, :body, :limit_time, :status, :department_id, :summary, :org_id)
                        ON CONFLICT (task_id) DO NOTHING
                    """),
                    {
                        "task_id": task_id,
                        "room_id": room_id,
                        "assigned_by": assigned_by_account_id,
                        "assigned_to": assigned_to_account_id,
                        "body": body,
                        "limit_time": limit_time,
                        "status": "open",
                        "department_id": department_id,
                        "summary": summary,
                        "org_id": self.organization_id
                    }
                )

            summary_preview = summary[:30] + "..." if summary and len(summary) > 30 else summary
            print(f"✅ タスクをDBに保存: task_id={task_id}, department_id={department_id}, summary={summary_preview}")
            return True
        except Exception as e:
            print(f"データベース保存エラー: {e}")
            traceback.print_exc()
            return False

    def _generate_task_summary(self, body: str) -> Optional[str]:
        """タスクのサマリーを生成"""
        if not body:
            return None

        summary = None

        if self.use_text_utils and self.extract_task_subject and self.prepare_task_display_text:
            try:
                # 1. まず【件名】形式を探す
                subject = self.extract_task_subject(body)
                if subject and len(subject) <= 40:
                    summary = subject
                    print(f"📝 件名を抽出: {summary}")
                else:
                    # 2. タグを除去して整形
                    if self.clean_chatwork_tags:
                        clean_body = self.clean_chatwork_tags(body)
                    else:
                        clean_body = body
                    summary = self.prepare_task_display_text(clean_body, max_length=40)
                    print(f"📝 要約を生成: {summary}")

                # 3. バリデーション
                if summary and self.validate_summary and not self.validate_summary(summary, body):
                    print(f"⚠️ 要約がバリデーション失敗、再生成: {summary}")
                    if self.clean_chatwork_tags:
                        clean_body = self.clean_chatwork_tags(body)
                    else:
                        clean_body = body
                    summary = self.prepare_task_display_text(clean_body, max_length=40)
                    if summary == "（タスク内容なし）":
                        summary = self._fallback_truncate(body, max_length=40)
            except Exception as e:
                print(f"⚠️ summary生成エラー（続行）: {e}")
                summary = self._fallback_truncate(body, max_length=40)
        else:
            # lib未使用時のフォールバック
            summary = self._fallback_truncate(body, max_length=40)

        return summary

    def log_analytics_event(
        self,
        event_type: str,
        actor_account_id: str,
        actor_name: str,
        room_id: str,
        event_data: Dict = None,
        success: bool = True,
        error_message: str = None,
        event_subtype: str = None
    ) -> None:
        """
        分析用イベントログを記録

        Args:
            event_type: イベントタイプ（'task_created', 'task_completed'等）
            actor_account_id: 実行者のChatWork account_id
            actor_name: 実行者の名前
            room_id: ChatWorkルームID
            event_data: 詳細データ（辞書形式）
            success: 成功したかどうか
            error_message: エラーメッセージ（失敗時）
            event_subtype: 詳細分類（オプション）

        Note:
            この関数はエラーが発生しても例外を投げない
        """
        try:
            pool = self.get_pool()
            with pool.begin() as conn:
                conn.execute(
                    sqlalchemy.text("""
                        INSERT INTO analytics_events
                        (event_type, event_subtype, actor_account_id, actor_name, room_id, event_data, success, error_message)
                        VALUES (:event_type, :event_subtype, :actor_id, :actor_name, :room_id, :event_data, :success, :error_message)
                    """),
                    {
                        "event_type": event_type,
                        "event_subtype": event_subtype,
                        "actor_id": actor_account_id,
                        "actor_name": actor_name,
                        "room_id": room_id,
                        "event_data": json.dumps(event_data, ensure_ascii=False) if event_data else None,
                        "success": success,
                        "error_message": error_message
                    }
                )
            print(f"📊 分析ログ記録: {event_type} by {actor_name}")
        except Exception as e:
            print(f"⚠️ 分析ログ記録エラー（処理は継続）: {e}")

    def get_task_by_id(self, task_id: str) -> Optional[Dict]:
        """
        タスクIDでタスクを取得

        Args:
            task_id: タスクID

        Returns:
            タスクデータ、またはNone
        """
        try:
            pool = self.get_pool()
            with pool.connect() as conn:
                result = conn.execute(
                    sqlalchemy.text("""
                        SELECT task_id, room_id, body, limit_time, status, assigned_to_account_id, assigned_by_account_id, department_id, summary
                        FROM chatwork_tasks
                        WHERE task_id = :task_id AND organization_id = :org_id
                    """),
                    {"task_id": task_id, "org_id": self.organization_id}
                )
                row = result.fetchone()
                if row:
                    return {
                        "task_id": row[0],
                        "room_id": row[1],
                        "body": row[2],
                        "limit_time": row[3],
                        "status": row[4],
                        "assigned_to_account_id": row[5],
                        "assigned_by_account_id": row[6],
                        "department_id": row[7],
                        "summary": row[8]
                    }
                return None
        except Exception as e:
            print(f"タスク取得エラー: {e}")
            return None
