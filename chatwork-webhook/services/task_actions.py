"""services/task_actions.py - タスクアクションハンドラー

Phase 11-4b: main.pyから抽出されたタスク作成・完了・検索のアクションハンドラー。

依存: services/task_ops.py, infra/db.py, infra/chatwork_api.py
"""

import re
import json
from datetime import datetime, timedelta, timezone
import sqlalchemy
import traceback

from google.cloud import firestore
from infra.db import get_pool, PROJECT_ID
from infra.chatwork_api import is_room_member, _get_room_tasks_safe
from services.task_ops import (
    _get_task_handler,
    create_chatwork_task,
    complete_chatwork_task,
    search_tasks_from_db,
    update_task_status_in_db,
    save_chatwork_task_to_db,
    log_analytics_event,
    get_chatwork_account_id_by_name,
)
from utils.date_utils import (
    parse_date_from_text as _new_parse_date_from_text,
    check_deadline_proximity as _new_check_deadline_proximity,
)

from lib import (
    clean_chatwork_tags,
    prepare_task_display_text,
    validate_summary,
)

# Firestore client for pending tasks
db = firestore.Client(project=PROJECT_ID)

# JST タイムゾーン
JST = timezone(timedelta(hours=9))

# 期限ガードレール設定
DEADLINE_ALERT_DAYS = {
    0: "今日",
    1: "明日",
}



def get_pending_task(room_id, account_id):
    """pending_taskを取得（Firestore）"""
    try:
        doc_ref = db.collection("pending_tasks").document(f"{room_id}_{account_id}")
        doc = doc_ref.get()
        if doc.exists:
            data = doc.to_dict()
            # 10分以上前のpending_taskは無効
            created_at = data.get("created_at")
            if created_at:
                expiry_time = datetime.now(timezone.utc) - timedelta(minutes=10)
                if created_at.replace(tzinfo=timezone.utc) < expiry_time:
                    # 期限切れなので削除
                    doc_ref.delete()
                    return None
            return data
    except Exception as e:
        print(f"pending_task取得エラー: {e}")
    return None

def save_pending_task(room_id, account_id, task_data):
    """pending_taskを保存（Firestore）"""
    try:
        doc_ref = db.collection("pending_tasks").document(f"{room_id}_{account_id}")
        task_data["created_at"] = datetime.now(timezone.utc)
        doc_ref.set(task_data)
        print(f"✅ pending_task保存: room={room_id}, account={account_id}, data={task_data}")
        return True
    except Exception as e:
        print(f"pending_task保存エラー: {e}")
        return False

def delete_pending_task(room_id, account_id):
    """pending_taskを削除（Firestore）"""
    try:
        doc_ref = db.collection("pending_tasks").document(f"{room_id}_{account_id}")
        doc_ref.delete()
        print(f"🗑️ pending_task削除: room={room_id}, account={account_id}")
        return True
    except Exception as e:
        print(f"pending_task削除エラー: {e}")
        return False

def parse_date_from_text(text):
    """
    自然言語の日付表現をYYYY-MM-DD形式に変換
    例: "明日", "明後日", "12/27", "来週金曜日"

    v10.24.0: utils/date_utils.py に移動済み
    """
    return _new_parse_date_from_text(text)

def check_deadline_proximity(limit_date_str: str) -> tuple:
    """
    期限が近すぎるかチェックする

    Args:
        limit_date_str: タスクの期限日（YYYY-MM-DD形式）

    Returns:
        (needs_alert: bool, days_until: int, limit_date: date or None)
        - needs_alert: アラートが必要か
        - days_until: 期限までの日数（0=今日, 1=明日, 負=過去）
        - limit_date: 期限日（date型）

    v10.24.0: utils/date_utils.py に移動済み
    """
    return _new_check_deadline_proximity(limit_date_str)

def _fallback_truncate_text(text: str, max_length: int = 40) -> str:
    """
    フォールバック用の切り詰め処理（自然な位置で切る）

    prepare_task_display_text()が使えない場合の最終手段。
    句点、読点、助詞の後ろで切ることで、途中で途切れる感を軽減。

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

def clean_task_body_for_summary(body: str) -> str:
    """
    タスク本文からChatWorkのタグや記号を完全に除去（要約用）

    ★★★ v10.13.4: chatwork-webhookにも追加 ★★★
    TODO: Phase 3.5でlib/に共通化予定
    """
    if not body:
        return ""

    if not isinstance(body, str):
        try:
            body = str(body)
        except:
            return ""

    try:
        # 1. 引用ブロックの処理
        non_quote_text = re.sub(r'\[qt\].*?\[/qt\]', '', body, flags=re.DOTALL)
        non_quote_text = non_quote_text.strip()

        if non_quote_text and len(non_quote_text) > 10:
            body = non_quote_text
        else:
            quote_matches = re.findall(
                r'\[qt\]\[qtmeta[^\]]*\](.*?)\[/qt\]',
                body,
                flags=re.DOTALL
            )
            if quote_matches:
                extracted_text = ' '.join(quote_matches)
                if extracted_text.strip():
                    body = extracted_text

        # 2. [qtmeta ...] タグを除去
        body = re.sub(r'\[qtmeta[^\]]*\]', '', body)

        # 3. [qt] [/qt] の単独タグを除去
        body = re.sub(r'\[/?qt\]', '', body)

        # 4. [To:xxx] タグを除去
        body = re.sub(r'\[To:\d+\]\s*[^\n\[]*(?:さん|くん|ちゃん|様|氏)?', '', body)
        body = re.sub(r'\[To:\d+\]', '', body)

        # 5. [piconname:xxx] タグを除去
        body = re.sub(r'\[piconname:\d+\]', '', body)

        # 6. [info]...[/info] タグを除去（内容は残す）
        body = re.sub(r'\[/?info\]', '', body)
        body = re.sub(r'\[/?title\]', '', body)

        # 7. [rp aid=xxx to=xxx-xxx] タグを除去
        body = re.sub(r'\[rp aid=\d+[^\]]*\]', '', body)
        body = re.sub(r'\[/rp\]', '', body)

        # 8. [dtext:xxx] タグを除去
        body = re.sub(r'\[dtext:[^\]]*\]', '', body)

        # 9. [preview ...] タグを除去
        body = re.sub(r'\[preview[^\]]*\]', '', body)
        body = re.sub(r'\[/preview\]', '', body)

        # 10. [code]...[/code] タグを除去（内容は残す）
        body = re.sub(r'\[/?code\]', '', body)

        # 11. [hr] タグを除去
        body = re.sub(r'\[hr\]', '', body)

        # 12. その他の [...] 形式のタグを除去
        body = re.sub(r'\[/?[a-z]+(?::[^\]]+)?\]', '', body, flags=re.IGNORECASE)

        # 13. 連続する改行を整理
        body = re.sub(r'\n{3,}', '\n\n', body)

        # 14. 連続するスペースを整理
        body = re.sub(r' {2,}', ' ', body)

        # 15. 前後の空白を除去
        body = body.strip()

        return body

    except Exception as e:
        print(f"⚠️ clean_task_body_for_summary エラー: {e}")
        return body

def generate_deadline_alert_message(
    task_name: str,
    limit_date,
    days_until: int,
    requester_account_id: str = None,
    requester_name: str = None
) -> str:
    """
    期限が近いタスクのアラートメッセージを生成する

    v10.3.1: カズさんの意図を反映したメッセージに修正
    - 依頼する側の配慮を促す文化づくり
    - 依頼された側が大変にならないように

    v10.3.2: メンション機能追加
    - グループチャットでアラートを送る時、依頼者にメンションをかける

    Args:
        task_name: タスク名
        limit_date: 期限日（date型）
        days_until: 期限までの日数（0=今日, 1=明日）
        requester_account_id: 依頼者のChatWorkアカウントID（メンション用）
        requester_name: 依頼者の名前

    Returns:
        アラートメッセージ文字列
    v10.13.4: 改善
    - タスク名からChatWorkタグを除去
    - 「あなたが依頼した」を明記
    """
    day_label = DEADLINE_ALERT_DAYS.get(days_until, f"{days_until}日後")
    formatted_date = limit_date.strftime("%m/%d")

    # タスク名からChatWorkタグを除去（v10.13.4）
    # ★★★ v10.24.8: prepare_task_display_text()で自然な位置で切る ★★★
    clean_task_name = clean_task_body_for_summary(task_name)
    if not clean_task_name:
        clean_task_name = "（タスク内容なし）"
    else:
        clean_task_name = prepare_task_display_text(clean_task_name, max_length=30)

    # メンション部分を生成（v10.13.4: 「あなたが」に統一）
    mention_line = ""
    if requester_account_id:
        if requester_name:
            mention_line = f"[To:{requester_account_id}] {requester_name}さん\n\n"
        else:
            mention_line = f"[To:{requester_account_id}]\n\n"

    message = f"""{mention_line}⚠️ あなたが依頼した期限が近いタスクだウル！

「{clean_task_name}」の期限が【{formatted_date}（{day_label}）】だウル。

期限が当日・明日だと、依頼された側も大変かもしれないウル。
もし余裕があるなら、期限を少し先に編集してあげてね。

※ 明後日以降ならこのアラートは出ないウル
※ このままでOKなら、何もしなくて大丈夫だウル！"""

    return message

def log_deadline_alert(task_id, room_id: str, account_id: str, limit_date, days_until: int) -> None:
    """
    期限アラートの送信をnotification_logsに記録する

    Args:
        task_id: タスクID
        room_id: ルームID
        account_id: 依頼者のアカウントID
        limit_date: 期限日（date型）
        days_until: 期限までの日数
    """
    try:
        pool = get_pool()
        with pool.begin() as conn:
            # まずテーブルが存在するか確認し、なければ作成
            conn.execute(sqlalchemy.text("""
                CREATE TABLE IF NOT EXISTS notification_logs (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    organization_id VARCHAR(100) DEFAULT 'org_soulsyncs',
                    notification_type VARCHAR(50) NOT NULL,
                    target_type VARCHAR(50) NOT NULL,
                    target_id TEXT,  -- BIGINTから変更: task_id（数値）とuser_id（UUID）両方対応
                    notification_date DATE NOT NULL,
                    sent_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    status VARCHAR(20) NOT NULL,
                    error_message TEXT,
                    retry_count INTEGER DEFAULT 0,
                    channel VARCHAR(20),
                    channel_target VARCHAR(255),
                    metadata JSONB,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    created_by VARCHAR(100),
                    UNIQUE(organization_id, target_type, target_id, notification_date, notification_type)
                )
            """))

            # アラートをログに記録
            conn.execute(
                sqlalchemy.text("""
                    INSERT INTO notification_logs (
                        organization_id,
                        notification_type,
                        target_type,
                        target_id,
                        notification_date,
                        sent_at,
                        status,
                        channel,
                        channel_target,
                        metadata
                    ) VALUES (
                        '5f98365f-e7c5-4f48-9918-7fe9aabae5df',
                        'deadline_alert',
                        'task',
                        :task_id,
                        :notification_date,
                        NOW(),
                        'sent',
                        'chatwork',
                        :room_id,
                        :metadata
                    )
                    ON CONFLICT (organization_id, target_type, target_id, notification_date, notification_type)
                    DO UPDATE SET
                        retry_count = notification_logs.retry_count + 1,
                        updated_at = NOW()
                """),
                {
                    "task_id": int(task_id) if task_id else 0,
                    "notification_date": datetime.now(JST).date(),
                    "room_id": str(room_id),
                    "metadata": json.dumps({
                        "room_id": str(room_id),
                        "account_id": str(account_id),
                        "limit_date": limit_date.isoformat() if limit_date else None,
                        "days_until": days_until,
                        "alert_type": "deadline_proximity"
                    }, ensure_ascii=False)
                }
            )
        print(f"📝 期限アラートをログに記録: task_id={task_id}, days_until={days_until}")
    except Exception as e:
        print(f"⚠️ 期限アラートのログ記録に失敗（タスク作成は成功）: {e}")

def handle_chatwork_task_create(params, room_id, account_id, sender_name, context=None):
    """ChatWorkタスク作成を処理（必須項目確認機能付き）"""
    print(f"📝 handle_chatwork_task_create 開始")
    
    assigned_to_name = params.get("assigned_to", "")
    task_body = params.get("task_body", "")
    limit_date = params.get("limit_date")
    limit_time = params.get("limit_time")
    needs_confirmation = params.get("needs_confirmation", False)
    
    print(f"   assigned_to_name: '{assigned_to_name}'")
    print(f"   task_body: '{task_body}'")
    print(f"   limit_date: {limit_date}")
    print(f"   limit_time: {limit_time}")
    print(f"   needs_confirmation: {needs_confirmation}")
    
    
    # 「俺」「自分」「私」の場合は依頼者自身に変換
    if assigned_to_name in ["依頼者自身", "俺", "自分", "私", "僕"]:
        print(f"   → '{assigned_to_name}' を '{sender_name}' に変換")
        assigned_to_name = sender_name
    
    # 必須項目の確認
    missing_items = []
    
    if not task_body or task_body.strip() == "":
        missing_items.append("task_body")
    
    if not assigned_to_name or assigned_to_name.strip() == "":
        missing_items.append("assigned_to")
    
    if not limit_date:
        missing_items.append("limit_date")
    
    # 不足項目がある場合は確認メッセージを返し、pending_taskを保存
    if missing_items:
        # pending_taskを保存
        pending_data = {
            "assigned_to": assigned_to_name,
            "task_body": task_body,
            "limit_date": limit_date,
            "limit_time": limit_time,
            "missing_items": missing_items,
            "sender_name": sender_name
        }
        save_pending_task(room_id, account_id, pending_data)
        
        response = "了解ウル！タスクを作成する前に確認させてウル🐕\n\n"
        
        # 入力済み項目を表示
        if task_body:
            response += f"📝 タスク内容: {task_body}\n"
        else:
            response += "📝 タスク内容: ❓ 未指定\n"
        
        if assigned_to_name:
            response += f"👤 担当者: {assigned_to_name}さん\n"
        else:
            response += "👤 担当者: ❓ 未指定\n"
        
        if limit_date:
            response += f"📅 期限: {limit_date}"
            if limit_time:
                response += f" {limit_time}"
            response += "\n"
        else:
            response += "📅 期限: ❓ 未指定\n"
        
        response += "\n"
        
        # 不足項目を質問
        if "task_body" in missing_items:
            response += "何のタスクか教えてウル！\n"
        elif "assigned_to" in missing_items:
            response += "誰に依頼するか教えてウル！\n"
        elif "limit_date" in missing_items:
            response += "期限はいつにするウル？（例: 12/27、明日、来週金曜日）\n"
        
        return response
    
    # --- 以下、全項目が揃っている場合のタスク作成処理 ---
    
    # pending_taskがあれば削除
    delete_pending_task(room_id, account_id)
    
    assigned_to_account_id = get_chatwork_account_id_by_name(assigned_to_name)
    print(f"👤 担当者ID解決: {assigned_to_name} → {assigned_to_account_id}")
    
    if not assigned_to_account_id:
        error_msg = f"❌ 担当者解決失敗: '{assigned_to_name}' が見つかりません"
        print(error_msg)
        print(f"💡 ヒント: データベースに '{assigned_to_name}' が登録されているか確認してください")
        return f"🤔 {assigned_to_name}さんが見つからなかったウル...\nデータベースに登録されているか確認してほしいウル！"

    # ルームメンバーシップチェック
    if not is_room_member(room_id, assigned_to_account_id):
        print(f"❌ ルームメンバーシップエラー: {assigned_to_name}（ID: {assigned_to_account_id}）はルーム {room_id} のメンバーではありません")
        return f"🤔 {assigned_to_name}さんはこのルームのメンバーじゃないみたいウル...\n{assigned_to_name}さんがいるルームでタスクを作成してほしいウル！"

    limit_timestamp = None
    if limit_date:
        try:
            time_str = limit_time if limit_time else "23:59"
            dt_str = f"{limit_date} {time_str}"
            dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
            jst = timezone(timedelta(hours=9))
            dt_jst = dt.replace(tzinfo=jst)
            limit_timestamp = int(dt_jst.timestamp())
            print(f"期限設定: {dt_str} → {limit_timestamp}")
        except Exception as e:
            print(f"期限の解析エラー: {e}")
    
    print(f"タスク作成開始: room_id={room_id}, assigned_to={assigned_to_account_id}, body={task_body}, limit={limit_timestamp}")
    
    task_data = create_chatwork_task(
        room_id=room_id,
        task_body=task_body,
        assigned_to_account_id=assigned_to_account_id,
        limit=limit_timestamp
    )
    
    if not task_data:
        return "❌ タスクの作成に失敗したウル...\nもう一度試してみてほしいウル！"
    
    # ChatWork APIのレスポンス形式: {"task_ids": [1234]}
    task_ids = task_data.get("task_ids", [])
    if not task_ids:
        print(f"⚠️ 予期しないAPIレスポンス形式: {task_data}")
        return "❌ タスクの作成に失敗したウル...\nもう一度試してみてほしいウル！"
    
    task_id = task_ids[0]
    print(f"✅ ChatWorkタスク作成成功: task_id={task_id}")
    
    # DBに保存（既に持っている情報を使う）
    save_success = save_chatwork_task_to_db(
        task_id=task_id,
        room_id=room_id,
        assigned_by_account_id=account_id,
        assigned_to_account_id=assigned_to_account_id,
        body=task_body,
        limit_time=limit_timestamp
    )
    
    if not save_success:
        print("警告: データベースへの保存に失敗しましたが、ChatWorkタスクは作成されました")
    
    # 分析ログ記録
    log_analytics_event(
        event_type="task_created",
        actor_account_id=account_id,
        actor_name=sender_name,
        room_id=room_id,
        event_data={
            "task_id": task_id,
            "assigned_to": assigned_to_name,
            "assigned_to_account_id": assigned_to_account_id,
            "task_body": task_body,
            "limit_timestamp": limit_timestamp
        }
    )
    
    # 成功メッセージ（既に持っている情報を使う）
    message = f"✅ {assigned_to_name}さんにタスクを作成したウル！🎉\n\n"
    message += f"📝 タスク内容: {task_body}\n"
    message += f"タスクID: {task_id}"

    if limit_timestamp:
        limit_dt = datetime.fromtimestamp(limit_timestamp, tz=timezone(timedelta(hours=9)))
        message += f"\n⏰ 期限: {limit_dt.strftime('%Y年%m月%d日 %H:%M')}"

    # =====================================================
    # v10.3.0: 期限ガードレール
    # =====================================================
    # タスク作成成功後、期限が近すぎる場合はアラートを追加
    # =====================================================
    needs_alert, days_until, parsed_limit_date = check_deadline_proximity(limit_date)

    if needs_alert:
        print(f"⚠️ 期限ガードレール発動: days_until={days_until}")
        alert_message = generate_deadline_alert_message(
            task_name=task_body,
            limit_date=parsed_limit_date,
            days_until=days_until,
            requester_account_id=str(account_id),
            requester_name=sender_name
        )
        message = message + "\n\n" + "─" * 20 + "\n\n" + alert_message

        # アラート送信をログに記録（ノンブロッキング）
        log_deadline_alert(
            task_id=task_id,
            room_id=room_id,
            account_id=account_id,
            limit_date=parsed_limit_date,
            days_until=days_until
        )

    return message

def handle_chatwork_task_complete(params, room_id, account_id, sender_name, context=None):
    """
    タスク完了ハンドラー
    
    contextに recent_tasks_context があれば、番号でタスクを特定できる
    """
    print(f"✅ handle_chatwork_task_complete 開始")
    print(f"   params: {params}")
    print(f"   context: {context}")
    
    task_identifier = params.get("task_identifier", "")
    
    # contextから最近のタスクリストを取得
    recent_tasks = []
    if context and "recent_tasks_context" in context:
        recent_tasks = context.get("recent_tasks_context", [])
    
    # タスクを特定
    target_task = None
    
    # 番号指定の場合（例: "1", "1番", "1のタスク"）
    import re
    number_match = re.search(r'(\d+)', task_identifier)
    if number_match and recent_tasks:
        task_index = int(number_match.group(1)) - 1  # 1-indexed → 0-indexed
        if 0 <= task_index < len(recent_tasks):
            target_task = recent_tasks[task_index]
            print(f"   番号指定でタスク特定: index={task_index}, task={target_task}")
    
    # タスク内容で検索（番号で見つからない場合）
    if not target_task and task_identifier:
        # DBからタスクを検索
        tasks = search_tasks_from_db(room_id, assigned_to_account_id=account_id, status="open")
        for task in tasks:
            if task_identifier.lower() in task["body"].lower():
                target_task = task
                print(f"   内容検索でタスク特定: {target_task}")
                break
    
    if not target_task:
        return f"🤔 どのタスクを完了にするか分からなかったウル...\n「1のタスクを完了」や「資料作成のタスクを完了」のように教えてウル！"
    
    task_id = target_task.get("task_id")
    task_body = target_task.get("body", "")
    
    # ChatWork APIでタスクを完了に
    result = complete_chatwork_task(room_id, task_id)
    
    if result:
        # DBのステータスも更新
        update_task_status_in_db(task_id, "done")
        
        # 分析ログ記録
        log_analytics_event(
            event_type="task_completed",
            actor_account_id=account_id,
            actor_name=sender_name,
            room_id=room_id,
            event_data={
                "task_id": task_id,
                "task_body": task_body
            }
        )
        
        # ★★★ v10.24.8: prepare_task_display_text()で自然な位置で切る ★★★
        task_display = prepare_task_display_text(clean_chatwork_tags(task_body), max_length=30)
        return f"✅ タスク「{task_display}」を完了にしたウル🎉\nお疲れ様ウル！他にも何か手伝えることがあったら教えてウル🐺✨"
    else:
        return f"❌ タスクの完了に失敗したウル...\nもう一度試してみてほしいウル！"

def handle_chatwork_task_search(params, room_id, account_id, sender_name, context=None):
    """
    タスク検索ハンドラー

    params:
        person_name: 検索する人物名（"sender"の場合は質問者自身）
        status: タスクの状態（open/done/all）
        assigned_by: タスクを依頼した人物名

    v10.22.0: BUG-001修正 - 自分のタスクを検索する場合は全ルームから検索
    """
    # v10.78: PII漏洩防止 — paramsにperson_name等が含まれるためキーのみログ出力（CLAUDE.md §3-2 #8）
    print(f"🔍 handle_chatwork_task_search 開始 (keys={list(params.keys())})")

    person_name = params.get("person_name", "")
    status = params.get("status", "open")
    assigned_by = params.get("assigned_by", "")

    # "sender" または "自分" の場合は質問者自身
    # v10.22.0: 自分のタスク検索時は全ルームから検索
    is_self_search = person_name.lower() in ["sender", "自分", "俺", "私", "僕", ""]
    if is_self_search:
        assigned_to_account_id = account_id
        display_name = "あなた"
    else:
        # 名前からaccount_idを取得
        assigned_to_account_id = get_chatwork_account_id_by_name(person_name)
        if not assigned_to_account_id:
            return f"🤔 {person_name}さんが見つからなかったウル...\n正確な名前を教えてほしいウル！"
        display_name = person_name

    # assigned_byの解決
    assigned_by_account_id = None
    if assigned_by:
        assigned_by_account_id = get_chatwork_account_id_by_name(assigned_by)

    # DBからタスクを検索
    # v10.22.0: 自分のタスク検索時は全ルームから検索（BUG-001修正）
    tasks = search_tasks_from_db(
        room_id,
        assigned_to_account_id=assigned_to_account_id,
        assigned_by_account_id=assigned_by_account_id,
        status=status,
        search_all_rooms=is_self_search  # 自分のタスク→全ルーム検索
    )

    # v10.54.5: リアルタイム同期 - ChatWork APIで完了済みのタスクをDBから除外
    if status == "open" and tasks:
        try:
            # 対象ルームのユニークリストを取得
            target_room_ids = set()
            if is_self_search:
                for task in tasks:
                    task_room_id = task.get("room_id")
                    if task_room_id:
                        target_room_ids.add(str(task_room_id))
            else:
                target_room_ids.add(str(room_id))

            # 各ルームのopen タスクをAPIから取得
            # v10.54.5: _get_room_tasks_safe でAPI成功/失敗を区別
            api_open_task_ids = set()
            successfully_fetched_rooms = set()  # API取得成功したルームのみ
            for target_room_id in target_room_ids:
                api_tasks, api_success = _get_room_tasks_safe(target_room_id, 'open')
                if not api_success:
                    print(f"⚠️ リアルタイム同期: room={target_room_id} のAPI取得失敗、スキップ")
                    continue  # API失敗時はこのルームをスキップ
                for api_task in api_tasks:
                    api_open_task_ids.add(str(api_task.get('task_id')))
                successfully_fetched_rooms.add(target_room_id)  # 成功時のみ追加

            # DB上はopenだがAPI上に存在しないタスクを検出・更新
            completed_task_ids = []
            for task in tasks:
                task_id = str(task.get("task_id"))
                task_room_id = str(task.get("room_id", room_id))

                # API取得成功したルームのタスクのみチェック（失敗したルームはスキップ）
                if task_room_id in successfully_fetched_rooms and task_id not in api_open_task_ids:
                    # API上に存在しない → 完了済み
                    completed_task_ids.append(task_id)
                    print(f"🔄 タスク同期: task_id={task_id} がAPI上で完了済み → DBを更新")
                    try:
                        update_task_status_in_db(task_id, "done")
                    except Exception as e:
                        print(f"⚠️ タスクステータス更新エラー: {e}")

            # 完了タスクを表示リストから除外
            if completed_task_ids:
                tasks = [t for t in tasks if str(t.get("task_id")) not in completed_task_ids]
                print(f"🔄 リアルタイム同期完了: {len(completed_task_ids)}件のタスクを完了扱いに")

        except Exception as e:
            # v10.78: PII漏洩防止 — エラー型のみログ記録（CLAUDE.md §3-2 #8, #12）
            print(f"⚠️ リアルタイム同期エラー（DBデータで続行）: {type(e).__name__}")

    if not tasks:
        status_text = "未完了の" if status == "open" else "完了済みの" if status == "done" else ""
        return f"📋 {display_name}の{status_text}タスクは見つからなかったウル！\nタスクがないか、まだ同期されていないかもウル🤔"

    # タスク一覧を作成
    status_text = "未完了" if status == "open" else "完了済み" if status == "done" else "全て"
    response = f"📋 **{display_name}の{status_text}タスク**ウル！\n\n"

    # v10.22.0: 全ルーム検索の場合はルーム別にグループ化
    if is_self_search:
        # ルーム別にグループ化
        tasks_by_room = {}
        for task in tasks:
            room_name = task.get("room_name") or "不明なルーム"
            if room_name not in tasks_by_room:
                tasks_by_room[room_name] = []
            tasks_by_room[room_name].append(task)

        # ルーム別に表示
        task_num = 1
        for room_name, room_tasks in tasks_by_room.items():
            response += f"📁 **{room_name}**\n"
            for task in room_tasks:
                body = task["body"]
                summary = task.get("summary")  # v10.25.0: AI生成の要約を優先
                limit_time = task.get("limit_time")

                # 期限の表示
                limit_str = ""
                if limit_time:
                    try:
                        limit_dt = datetime.fromtimestamp(limit_time, tz=timezone(timedelta(hours=9)))
                        limit_str = f"（期限: {limit_dt.strftime('%m/%d')}）"
                    except:
                        pass

                # v10.27.0: AI生成のsummaryを優先使用（有効な場合のみ）
                body_short = None
                if summary:
                    if validate_summary(summary, body):
                        body_short = summary
                    else:
                        print(f"⚠️ summary検証失敗、bodyから生成: task_id={task.get('task_id')}")

                if not body_short:
                    clean_body = clean_chatwork_tags(body)
                    body_short = prepare_task_display_text(clean_body, max_length=40)
                response += f"  {task_num}. {body_short} {limit_str}\n"
                task_num += 1
            response += "\n"
    else:
        # 従来の表示（単一ルーム）
        for i, task in enumerate(tasks, 1):
            body = task["body"]
            summary = task.get("summary")  # v10.25.0: AI生成の要約を優先
            limit_time = task.get("limit_time")

            # 期限の表示
            limit_str = ""
            if limit_time:
                try:
                    limit_dt = datetime.fromtimestamp(limit_time, tz=timezone(timedelta(hours=9)))
                    limit_str = f"（期限: {limit_dt.strftime('%m/%d')}）"
                except:
                    pass

            # v10.27.0: AI生成のsummaryを優先使用（有効な場合のみ）
            body_short = None
            if summary:
                if validate_summary(summary, body):
                    body_short = summary
                else:
                    print(f"⚠️ summary検証失敗、bodyから生成: task_id={task.get('task_id')}")

            if not body_short:
                clean_body = clean_chatwork_tags(body)
                body_short = prepare_task_display_text(clean_body, max_length=40)
            response += f"{i}. {body_short} {limit_str}\n"

    response += f"この{len(tasks)}つが{status_text}タスクだよウル！頑張ってねウル💪✨"
    
    # 分析ログ記録
    log_analytics_event(
        event_type="task_searched",
        actor_account_id=account_id,
        actor_name=sender_name,
        room_id=room_id,
        event_data={
            "searched_for": display_name,
            "status": status,
            "result_count": len(tasks)
        }
    )
    
    return response

def handle_pending_task_followup(message, room_id, account_id, sender_name):
    """
    pending_taskがある場合のフォローアップ処理
    
    Returns:
        応答メッセージ（処理した場合）またはNone（pending_taskがない場合）
    """
    pending = get_pending_task(room_id, account_id)
    if not pending:
        return None
    
    print(f"📋 pending_task発見: {pending}")
    
    missing_items = pending.get("missing_items", [])
    assigned_to = pending.get("assigned_to", "")
    task_body = pending.get("task_body", "")
    limit_date = pending.get("limit_date")
    limit_time = pending.get("limit_time")
    
    # 不足項目を補完
    updated = False
    
    # 期限が不足している場合
    if "limit_date" in missing_items:
        parsed_date = parse_date_from_text(message)
        if parsed_date:
            limit_date = parsed_date
            missing_items.remove("limit_date")
            updated = True
            print(f"   → 期限を補完: {parsed_date}")
    
    # タスク内容が不足している場合
    if "task_body" in missing_items and not updated:
        # メッセージ全体をタスク内容として使用
        task_body = message
        missing_items.remove("task_body")
        updated = True
        print(f"   → タスク内容を補完: {task_body}")
    
    # 担当者が不足している場合
    if "assigned_to" in missing_items and not updated:
        # メッセージから名前を抽出（簡易的）
        assigned_to = message.strip()
        missing_items.remove("assigned_to")
        updated = True
        print(f"   → 担当者を補完: {assigned_to}")
    
    if updated:
        # 補完後の情報でタスク作成を再試行
        params = {
            "assigned_to": assigned_to,
            "task_body": task_body,
            "limit_date": limit_date,
            "limit_time": limit_time,
            "needs_confirmation": False
        }
        return handle_chatwork_task_create(params, room_id, account_id, sender_name, None)
    
    # 何も補完できなかった場合
    return None
