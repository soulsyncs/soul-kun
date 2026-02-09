"""infra/chatwork_api.py - ChatWork API基盤

Phase 11-1b: main.pyから抽出されたChatWork API関連関数。
Webhook署名検証、メッセージ送受信、ルーム管理、コンタクト管理を提供。

依存: infra/db.py (get_pool, get_secret)
"""

import base64
import hashlib
import hmac
import httpx
import traceback
import sqlalchemy

from infra.db import get_pool, get_secret
from utils.chatwork_utils import (
    call_chatwork_api_with_retry as _new_call_chatwork_api_with_retry,
    is_room_member as _new_is_room_member,
    clean_chatwork_message as _utils_clean_chatwork_message,
    is_mention_or_reply_to as _utils_is_mention_or_reply_to,
    should_ignore_toall as _utils_should_ignore_toall,
)

# ソウルくんのaccount_id
MY_ACCOUNT_ID = "10909425"

# メモリ用デフォルト組織ID
MEMORY_DEFAULT_ORG_ID = "5f98365f-e7c5-4f48-9918-7fe9aabae5df"

# 管理者ルームID（DM不可通知用）
try:
    from lib.admin_config import get_admin_config
    _admin_config = get_admin_config()
    ADMIN_ROOM_ID = int(_admin_config.admin_room_id)
except ImportError:
    ADMIN_ROOM_ID = 405315911

# 実行内メモリキャッシュ
_runtime_dm_cache = {}
_runtime_direct_rooms = None
_runtime_contacts_cache = None
_runtime_contacts_fetched_ok = None
_dm_unavailable_buffer = []


def reset_runtime_caches():
    """実行内メモリキャッシュをリセット（ウォームスタート対策）"""
    global _runtime_dm_cache, _runtime_direct_rooms, _runtime_contacts_cache, _runtime_contacts_fetched_ok, _dm_unavailable_buffer
    _runtime_dm_cache = {}
    _runtime_direct_rooms = None
    _runtime_contacts_cache = None
    _runtime_contacts_fetched_ok = None
    _dm_unavailable_buffer = []
    print("✅ メモリキャッシュをリセット")


def verify_chatwork_webhook_signature(request_body: bytes, signature: str, token: str) -> bool:
    """
    ChatWork Webhookの署名を検証する
    
    Args:
        request_body: リクエストボディ（バイト列）
        signature: X-ChatWorkWebhookSignatureヘッダーの値
        token: ChatWork Webhook編集画面で取得したトークン
    
    Returns:
        True: 署名が正しい（正当なリクエスト）
        False: 署名が不正（攻撃の可能性）
    """
    try:
        # トークンをBase64デコードしてバイト列に変換
        token_bytes = base64.b64decode(token)
        
        # HMAC-SHA256でダイジェストを計算
        calculated_hmac = hmac.new(
            token_bytes,
            request_body,
            hashlib.sha256
        ).digest()
        
        # Base64エンコード
        calculated_signature = base64.b64encode(calculated_hmac).decode('utf-8')
        
        # タイミング攻撃対策: hmac.compare_digestで比較
        return hmac.compare_digest(calculated_signature, signature)
    
    except Exception as e:
        print(f"❌ 署名検証エラー: {e}")
        return False

def get_chatwork_webhook_token():
    """ChatWork Webhookトークンを取得"""
    try:
        return get_secret("CHATWORK_WEBHOOK_TOKEN")
    except Exception as e:
        print(f"⚠️ Webhookトークン取得エラー: {e}")
        return None

def clean_chatwork_message(body):
    """ChatWorkメッセージをクリーニング（utils/chatwork_utils.py に委譲）"""
    return _utils_clean_chatwork_message(body)

def is_mention_or_reply_to_soulkun(body):
    """ソウルくんへのメンションまたは返信かどうかを判断"""
    return _utils_is_mention_or_reply_to(body, MY_ACCOUNT_ID)

def should_ignore_toall(body):
    """TO ALLメンションを無視すべきか判定（utils/chatwork_utils.py に委譲）"""
    return _utils_should_ignore_toall(body, MY_ACCOUNT_ID)

def call_chatwork_api_with_retry(
    method: str,
    url: str,
    headers: dict,
    data: dict = None,
    params: dict = None,
    max_retries: int = 3,
    initial_wait: float = 1.0,
    timeout: float = 10.0
):
    """
    ChatWork APIを呼び出す（レート制限時は自動リトライ）

    Args:
        method: HTTPメソッド（GET, POST, PUT, DELETE）
        url: APIのURL
        headers: リクエストヘッダー
        data: リクエストボディ
        params: クエリパラメータ
        max_retries: 最大リトライ回数
        initial_wait: 初回待機時間（秒）
        timeout: タイムアウト（秒）

    Returns:
        (response, success): レスポンスと成功フラグのタプル

    v10.24.0: utils/chatwork_utils.py に移動済み
    """
    return _new_call_chatwork_api_with_retry(
        method, url, headers, data, params, max_retries, initial_wait, timeout
    )

def is_room_member(room_id, account_id):
    """
    指定したアカウントがルームのメンバーかどうかを確認（キャッシュ使用）

    v10.24.0: utils/chatwork_utils.py に移動済み
    """
    api_token = get_secret("SOULKUN_CHATWORK_TOKEN")
    return _new_is_room_member(room_id, account_id, api_token)

def send_chatwork_message(room_id, message, reply_to=None, show_guide=False, return_details=False):
    """メッセージを送信（リトライ機構付き）

    Args:
        room_id: 送信先ルームID
        message: 送信メッセージ
        reply_to: 返信先アカウントID（オプション）
        show_guide: 案内文を追加するか
        return_details: Trueの場合、message_idを含む詳細を返す（v10.26.1追加）

    Returns:
        return_details=False (デフォルト): bool - 成功/失敗
        return_details=True: dict - {"success": bool, "message_id": str or None}
    """
    api_token = get_secret("SOULKUN_CHATWORK_TOKEN")

    # 案内文を追加（条件を満たす場合のみ）
    if show_guide:
        message += "\n\n💬 グループチャットでは @ソウルくん をつけて話しかけてウル🐕"

    # v10.40.3: 返信タグ機能は未使用のためコメント削除

    response, success = call_chatwork_api_with_retry(
        method="POST",
        url=f"https://api.chatwork.com/v2/rooms/{room_id}/messages",
        headers={"X-ChatWorkToken": api_token},
        data={"body": message}
    )

    # v10.26.1: return_details=True の場合、message_idを含む詳細を返す
    if return_details:
        result = {"success": False, "message_id": None}
        if success and response and response.status_code == 200:
            try:
                json_data = response.json()
                result = {
                    "success": True,
                    "message_id": json_data.get("message_id")
                }
            except Exception:
                result = {"success": True, "message_id": None}
        return result

    # デフォルト: 後方互換性のためboolを返す
    return success and response and response.status_code == 200

def get_all_rooms():
    """ソウルくんが参加している全ルームを取得（リトライ機構付き）"""
    api_token = get_secret("SOULKUN_CHATWORK_TOKEN")

    response, success = call_chatwork_api_with_retry(
        method="GET",
        url="https://api.chatwork.com/v2/rooms",
        headers={"X-ChatWorkToken": api_token}
    )

    if success and response and response.status_code == 200:
        return response.json()
    elif response:
        print(f"ルーム一覧取得エラー: {response.status_code}")
    return []

def get_room_messages(room_id, force=False):
    """ルームのメッセージを取得
    
    堅牢なエラーハンドリング版
    """
    # room_idの検証
    if room_id is None:
        print(f"   ⚠️ room_idがNone")
        return []
    
    try:
        api_token = get_secret("SOULKUN_CHATWORK_TOKEN")
    except Exception as e:
        print(f"   ❌ APIトークン取得エラー: {e}")
        return []
    
    if not api_token:
        print(f"   ❌ APIトークンが空")
        return []
    
    try:
        params = {"force": 1} if force else {}
        
        print(f"   🌐 API呼び出し: GET /rooms/{room_id}/messages, force={force}")
        
        response = httpx.get(
            f"https://api.chatwork.com/v2/rooms/{room_id}/messages",
            headers={"X-ChatWorkToken": api_token},
            params=params,
            timeout=10.0
        )
        
        print(f"   📬 APIレスポンス: status={response.status_code}")
        
        if response.status_code == 200:
            try:
                messages = response.json()
                
                # レスポンスの検証
                if messages is None:
                    print(f"   ⚠️ APIレスポンスがNone")
                    return []
                
                if not isinstance(messages, list):
                    print(f"   ⚠️ APIレスポンスが配列ではない: {type(messages)}")
                    return []
                
                return messages
            except Exception as e:
                print(f"   ❌ JSONパースエラー: {e}")
                return []
        
        elif response.status_code == 204:
            # 新しいメッセージなし（正常）
            return []
        
        elif response.status_code == 429:
            # レートリミット
            print(f"   ⚠️ レートリミット: room_id={room_id}")
            return []
        
        else:
            # その他のエラー
            try:
                error_body = response.text[:200] if response.text else "No body"
            except:
                error_body = "Could not read body"
            print(f"   ⚠️ メッセージ取得エラー: status={response.status_code}, body={error_body}")
            return []
    
    except httpx.TimeoutException:
        print(f"   ⚠️ タイムアウト: room_id={room_id}")
        return []
    
    except httpx.RequestError as e:
        print(f"   ❌ リクエストエラー: {e}")
        return []
    
    except Exception as e:
        print(f"   ❌ メッセージ取得で予期しないエラー: {e}")
        import traceback
        traceback.print_exc()
        return []

def get_sender_name(room_id, account_id):
    try:
        api_token = get_secret("SOULKUN_CHATWORK_TOKEN")
        response = httpx.get(
            f"https://api.chatwork.com/v2/rooms/{room_id}/members",
            headers={"X-ChatWorkToken": api_token}, timeout=10.0
        )
        if response.status_code == 200:
            for member in response.json():
                if str(member.get("account_id")) == str(account_id):
                    return member.get("name", "ゲスト")
    except:
        pass
    return "ゲスト"

def get_all_contacts():
    """
    ★★★ v6.8.3: /contacts APIでコンタクト一覧を取得 ★★★
    ★★★ v6.8.4: fetched_okフラグ導入 & 429時もキャッシュセット ★★★
    
    ChatWork /contacts APIを使用して、全コンタクトのaccount_idとroom_id（DMルームID）を取得。
    これにより、N+1問題が完全に解消される。
    
    Returns:
        tuple: (contacts_map, fetched_ok)
            - contacts_map: {account_id: room_id} のマッピング
            - fetched_ok: True=API成功, False=API失敗（429含む）
        
    Note:
        - 429時も空dictをキャッシュ（同一実行内でリトライ連打を防止）
        - fetched_okで成功/失敗を判定（空dict=成功の可能性あり）
    """
    global _runtime_contacts_cache, _runtime_contacts_fetched_ok
    
    # 実行内キャッシュがあればそれを返す（成功/失敗問わず）
    if _runtime_contacts_cache is not None:
        status = "成功" if _runtime_contacts_fetched_ok else "失敗（キャッシュ済み）"
        print(f"✅ コンタクト一覧 メモリキャッシュ使用（{len(_runtime_contacts_cache)}件, {status}）")
        return _runtime_contacts_cache, _runtime_contacts_fetched_ok  # ★★★ v6.8.4: タプルで返す ★★★
    
    api_token = get_secret("SOULKUN_CHATWORK_TOKEN")
    
    try:
        print("🔍 /contacts APIでコンタクト一覧を取得中...")
        response = httpx.get(
            "https://api.chatwork.com/v2/contacts",
            headers={"X-ChatWorkToken": api_token},
            timeout=30.0
        )
        
        if response.status_code == 200:
            contacts = response.json()
            # {account_id: room_id} のマッピングを作成
            contacts_map = {}
            for contact in contacts:
                account_id = contact.get("account_id")
                room_id = contact.get("room_id")
                if account_id and room_id:
                    contacts_map[int(account_id)] = int(room_id)
            
            print(f"✅ コンタクト一覧取得成功: {len(contacts_map)}件")
            
            # ★★★ v6.8.4: 成功フラグをセット ★★★
            _runtime_contacts_cache = contacts_map
            _runtime_contacts_fetched_ok = True
            
            return contacts_map, True  # ★★★ v6.8.4: タプルで返す ★★★
        
        elif response.status_code == 429:
            print(f"⚠️ /contacts API レート制限に達しました")
            # ★★★ v6.8.4: 429でも空dictをキャッシュ（リトライ連打防止）★★★
            _runtime_contacts_cache = {}
            _runtime_contacts_fetched_ok = False
            return {}, False  # ★★★ v6.8.4: タプルで返す ★★★
        
        else:
            print(f"❌ /contacts API エラー: {response.status_code}")
            # ★★★ v6.8.4: エラーでも空dictをキャッシュ ★★★
            _runtime_contacts_cache = {}
            _runtime_contacts_fetched_ok = False
            return {}, False  # ★★★ v6.8.4: タプルで返す ★★★
    
    except Exception as e:
        print(f"❌ /contacts API 取得エラー: {e}")
        traceback.print_exc()
        # ★★★ v6.8.4: 例外でも空dictをキャッシュ ★★★
        _runtime_contacts_cache = {}
        _runtime_contacts_fetched_ok = False
        return {}, False  # ★★★ v6.8.4: タプルで返す ★★★

def get_direct_room(account_id):
    """
    指定アカウントとの個人チャット（ダイレクト）のroom_idを取得
    
    ★★★ v6.8.3: /contacts APIベースに完全刷新 ★★★
    - N+1問題が完全解消（API 1回で全コンタクト取得）
    - メモリキャッシュ→DBキャッシュ→/contacts APIの順で探索
    
    ★★★ v6.8.4: fetched_okフラグでネガティブキャッシュ判定 ★★★
    - 空dict判定の誤りを修正（コンタクト0件でも成功は成功）
    - 429/エラー時はネガティブキャッシュしない
    
    ★ 運用ルール: 新社員はソウルくんとコンタクト追加が必要
    """
    global _runtime_dm_cache
    
    if not account_id:
        return None
    
    account_id_int = int(account_id)
    
    # 1. まず実行内メモリキャッシュを確認（最速）
    if account_id_int in _runtime_dm_cache:
        cached_room = _runtime_dm_cache[account_id_int]
        if cached_room is not None:
            print(f"✅ DMルーム メモリキャッシュヒット: account_id={account_id}, room_id={cached_room}")
            return cached_room
        elif cached_room is None and _runtime_dm_cache.get(f"{account_id_int}_negative"):
            # ネガティブキャッシュ（API成功で本当に見つからなかった場合のみ）
            print(f"⚠️ DMルーム メモリキャッシュ: account_id={account_id} は見つからない（キャッシュ済み）")
            return None
    
    pool = get_pool()
    
    try:
        # 2. DBキャッシュを確認（API 0回で済む）
        with pool.connect() as conn:
            result = conn.execute(
                sqlalchemy.text("SELECT dm_room_id FROM dm_room_cache WHERE account_id = :account_id"),
                {"account_id": account_id_int}
            )
            cached = result.fetchone()
            if cached:
                room_id = cached[0]
                print(f"✅ DMルーム DBキャッシュヒット: account_id={account_id}, room_id={room_id}")
                # メモリキャッシュにも保存
                _runtime_dm_cache[account_id_int] = room_id
                return room_id
        
        # 3. /contacts APIで探索（API 1回で全コンタクト取得）
        print(f"🔍 DMルーム探索開始: account_id={account_id}")
        contacts_map, fetched_ok = get_all_contacts()  # ★★★ v6.8.5: タプルで受け取る ★★★
        
        if account_id_int in contacts_map:
            room_id = contacts_map[account_id_int]
            print(f"✅ DMルーム発見（/contacts API）: account_id={account_id}, room_id={room_id}")
            
            # メモリキャッシュに保存
            _runtime_dm_cache[account_id_int] = room_id
            
            # DBにキャッシュ保存
            try:
                with pool.begin() as conn:
                    conn.execute(
                        sqlalchemy.text("""
                            INSERT INTO dm_room_cache (account_id, dm_room_id)
                            VALUES (:account_id, :dm_room_id)
                            ON CONFLICT (account_id) DO UPDATE SET 
                                dm_room_id = :dm_room_id,
                                cached_at = CURRENT_TIMESTAMP
                        """),
                        {"account_id": account_id_int, "dm_room_id": room_id}
                    )
            except Exception as e:
                print(f"⚠️ DMキャッシュ保存エラー（続行）: {e}")
            
            return room_id
        
        # 4. 見つからなかった場合
        print(f"❌ DMルームが見つかりません: account_id={account_id}")
        print(f"   → この人とソウルくんがコンタクト追加されていない可能性があります")
        
        # ★★★ v6.8.5: ローカル変数fetched_okで判定 ★★★
        # API成功時のみネガティブキャッシュ（429/エラー時はキャッシュしない）
        if fetched_ok:
            _runtime_dm_cache[account_id_int] = None
            _runtime_dm_cache[f"{account_id_int}_negative"] = True
        
        return None
        
    except Exception as e:
        print(f"❌ DMルーム取得エラー: {e}")
        traceback.print_exc()
        return None

def flush_dm_unavailable_notifications():
    """
    ★★★ v6.8.3: バッファに溜まったDM不可通知をまとめて1通で送信 ★★★
    
    これにより、per-room制限（10秒10回）を回避できる。
    process_overdue_tasks()の最後に呼び出す。
    """
    global _dm_unavailable_buffer
    
    if not _dm_unavailable_buffer:
        return
    
    print(f"📤 DM不可通知をまとめて送信（{len(_dm_unavailable_buffer)}件）")
    
    api_token = get_secret("SOULKUN_CHATWORK_TOKEN")
    
    # まとめメッセージを作成
    message_lines = ["[info][title]⚠️ DM送信できなかった通知一覧[/title]"]
    message_lines.append(f"以下の{len(_dm_unavailable_buffer)}名にDMを送信できませんでした：\n")
    
    for i, item in enumerate(_dm_unavailable_buffer[:20], 1):  # 最大20件まで
        person_name = item["person_name"]
        account_id = item["account_id"]
        action_type = item["action_type"]
        tasks = item.get("tasks", [])
        
        # タスク情報（1件のみ表示）
        task_hint = ""
        if tasks and len(tasks) > 0:
            body = tasks[0].get("body", "")
            body_short = (body[:15] + "...") if len(body) > 15 else body
            task_hint = f"「{body_short}」"
        
        message_lines.append(f"{i}. {person_name}（ID:{account_id}）- {action_type} {task_hint}")
    
    if len(_dm_unavailable_buffer) > 20:
        message_lines.append(f"\n...他{len(_dm_unavailable_buffer) - 20}名")
    
    message_lines.append("\n【対応】")
    message_lines.append("ChatWorkで上記の方々がソウルくんをコンタクト追加するか、")
    message_lines.append("管理者がソウルくんアカウントからコンタクト追加してください。[/info]")
    
    message = "\n".join(message_lines)
    
    try:
        response = httpx.post(
            f"https://api.chatwork.com/v2/rooms/{ADMIN_ROOM_ID}/messages",
            headers={"X-ChatWorkToken": api_token},
            data={"body": message},
            timeout=10.0
        )
        
        if response.status_code == 200:
            print(f"✅ 管理部へのDM不可通知まとめ送信成功（{len(_dm_unavailable_buffer)}件）")
        else:
            print(f"❌ 管理部へのDM不可通知まとめ送信失敗: {response.status_code}")
    except Exception as e:
        print(f"❌ 管理部通知エラー: {e}")

    # バッファをクリア
    _dm_unavailable_buffer = []

def get_all_chatwork_users(organization_id: str = None):
    """ChatWorkユーザー一覧を取得（AI司令塔用）

    v10.30.0: 10の鉄則準拠 - organization_idフィルタ必須化
    """
    if organization_id is None:
        organization_id = MEMORY_DEFAULT_ORG_ID

    try:
        pool = get_pool()
        with pool.connect() as conn:
            result = conn.execute(
                sqlalchemy.text("""
                    SELECT DISTINCT account_id, name
                    FROM chatwork_users
                    WHERE organization_id = :org_id
                      AND name IS NOT NULL AND name != ''
                    ORDER BY name
                """),
                {"org_id": organization_id}
            ).fetchall()
            return [{"account_id": row[0], "name": row[1]} for row in result]
    except Exception as e:
        print(f"ChatWorkユーザー取得エラー: {e}")
        return []

def get_room_tasks(room_id, status='open'):
    """
    指定されたルームのタスク一覧を取得

    Args:
        room_id: ルームID
        status: タスクのステータス ('open' or 'done')

    Returns:
        タスクのリスト
    """
    url = f"https://api.chatwork.com/v2/rooms/{room_id}/tasks"
    # ★★★ v10.4.0: 全タスク同期対応 ★★★
    # assigned_by_account_id フィルタを削除し、全ユーザーが作成したタスクを取得
    params = {
        'status': status,
    }

    headers = {"X-ChatWorkToken": get_secret("SOULKUN_CHATWORK_TOKEN")}
    response = httpx.get(url, headers=headers, params=params, timeout=10.0)

    if response.status_code == 200:
        return response.json()
    else:
        print(f"Failed to get tasks for room {room_id}: {response.status_code}")
        return []

def _get_room_tasks_safe(room_id, status='open'):
    """
    リアルタイム同期用: タスク一覧を取得し、API成功/失敗を区別

    v10.54.5: リアルタイム同期でAPI失敗を検出するための内部関数

    Args:
        room_id: ルームID
        status: タスクのステータス ('open' or 'done')

    Returns:
        tuple: (tasks: list, success: bool)
        - success=True: API成功、tasksはリスト（空の場合もある）
        - success=False: API失敗、tasksは空リスト
    """
    url = f"https://api.chatwork.com/v2/rooms/{room_id}/tasks"
    params = {'status': status}

    try:
        headers = {"X-ChatWorkToken": get_secret("SOULKUN_CHATWORK_TOKEN")}
        response = httpx.get(url, headers=headers, params=params, timeout=10.0)

        if response.status_code == 200:
            return response.json(), True
        else:
            print(f"API失敗 (room={room_id}): status={response.status_code}")
            return [], False
    except Exception as e:
        print(f"API例外 (room={room_id}): {e}")
        return [], False

def sync_room_members():
    """全ルームのメンバーをchatwork_usersテーブルに同期

    v10.30.0: 10の鉄則準拠 - organization_id追加
    """
    api_token = get_secret("SOULKUN_CHATWORK_TOKEN")
    organization_id = MEMORY_DEFAULT_ORG_ID

    try:
        # 全ルームを取得
        rooms = get_all_rooms()

        if not rooms:
            print("No rooms found")
            return

        pool = get_pool()
        synced_count = 0

        for room in rooms:
            room_id = room.get("room_id")
            room_type = room.get("type")

            # マイチャットはスキップ
            if room_type == "my":
                continue

            try:
                # ルームメンバーを取得
                response = httpx.get(
                    f"https://api.chatwork.com/v2/rooms/{room_id}/members",
                    headers={"X-ChatWorkToken": api_token},
                    timeout=10.0
                )

                if response.status_code != 200:
                    print(f"Failed to get members for room {room_id}: {response.status_code}")
                    continue

                members = response.json()

                with pool.begin() as conn:
                    for member in members:
                        account_id = member.get("account_id")
                        name = member.get("name", "")

                        if not account_id or not name:
                            continue

                        # UPSERT: 存在すれば更新、なければ挿入
                        # v10.30.0: organization_id追加（複合ユニーク制約対応）
                        conn.execute(
                            sqlalchemy.text("""
                                INSERT INTO chatwork_users (organization_id, account_id, name, room_id, updated_at)
                                VALUES (:org_id, :account_id, :name, :room_id, CURRENT_TIMESTAMP)
                                ON CONFLICT (organization_id, account_id)
                                DO UPDATE SET name = :name, room_id = :room_id, updated_at = CURRENT_TIMESTAMP
                            """),
                            {
                                "org_id": organization_id,
                                "account_id": account_id,
                                "name": name,
                                "room_id": room_id
                            }
                        )
                        synced_count += 1

            except Exception as e:
                print(f"Error syncing members for room {room_id}: {e}")
                traceback.print_exc()
                continue

        print(f"Synced {synced_count} members")

    except Exception as e:
        print(f"Error in sync_room_members: {e}")
        traceback.print_exc()


# =====================================================
# Phase C: ファイルダウンロード（会議文字起こし用）
# =====================================================

MAX_AUDIO_FILE_SIZE = 100 * 1024 * 1024  # 100 MB


def download_chatwork_file(room_id, file_id):
    """ChatWork APIからファイルをダウンロードする。

    1. GET /rooms/{room_id}/files/{file_id}?create_download_url=1 でダウンロードURL取得
    2. ファイルサイズ確認（100MB上限）
    3. ダウンロードURLからファイル取得（30秒有効）

    Args:
        room_id: ChatWorkルームID
        file_id: ChatWorkファイルID

    Returns:
        (file_bytes, filename) or (None, None) on failure
    """
    import logging
    logger = logging.getLogger(__name__)

    api_token = get_secret("SOULKUN_CHATWORK_TOKEN")
    if not api_token:
        logger.warning("CHATWORK_API_TOKEN not available for file download")
        return None, None

    try:
        # Step 1: ファイル情報 + ダウンロードURL取得
        response, success = call_chatwork_api_with_retry(
            method="GET",
            url=f"https://api.chatwork.com/v2/rooms/{room_id}/files/{file_id}",
            headers={"X-ChatWorkToken": api_token},
            params={"create_download_url": "1"},
            timeout=15.0,
        )

        if not success or not response or response.status_code != 200:
            logger.warning(
                "Failed to get file info: file_id=%s, status=%s",
                file_id, getattr(response, "status_code", None),
            )
            return None, None

        file_info = response.json()
        filename = file_info.get("filename", "")
        download_url = file_info.get("download_url", "")

        if not download_url:
            logger.warning("No download_url in response: file_id=%s", file_id)
            return None, None

        # Step 2: ファイルサイズ確認（OOM防止）
        file_size = file_info.get("filesize", 0)
        if file_size > MAX_AUDIO_FILE_SIZE:
            logger.warning(
                "File too large: file_id=%s, size=%d, max=%d",
                file_id, file_size, MAX_AUDIO_FILE_SIZE,
            )
            return None, None

        # Step 3: ダウンロードURLからファイル取得（30秒有効）
        with httpx.Client(timeout=60.0) as client:
            dl_response = client.get(download_url)

        if dl_response.status_code != 200:
            logger.warning(
                "File download failed: file_id=%s, status=%s",
                file_id, dl_response.status_code,
            )
            return None, None

        logger.info(
            "File downloaded: file_id=%s, size=%d",
            file_id, len(dl_response.content),
        )
        return dl_response.content, filename

    except Exception as e:
        logger.warning("File download error: file_id=%s, error=%s", file_id, type(e).__name__)
        return None, None


def get_room_recent_files(room_id, account_id=None):
    """ChatWorkルームの最新ファイル一覧を取得する。

    GET /rooms/{room_id}/files?account_id={account_id}

    Args:
        room_id: ChatWorkルームID
        account_id: 送信者でフィルタ（省略時は全ファイル）

    Returns:
        list: ファイル情報のリスト（新しい順）。エラー時は空リスト。
    """
    import logging
    logger = logging.getLogger(__name__)

    try:
        token = get_secret("CHATWORK_API_TOKEN")
        if not token:
            return []

        params = {}
        if account_id:
            params["account_id"] = account_id

        response, success = call_chatwork_api_with_retry(
            url=f"https://api.chatwork.com/v2/rooms/{room_id}/files",
            token=token,
            params=params,
        )

        if not success or response.status_code != 200:
            return []

        files = response.json()
        # 新しい順にソート（upload_timeの降順）
        files.sort(key=lambda f: f.get("upload_time", 0), reverse=True)
        return files[:5]  # 直近5件のみ返す

    except Exception as e:
        logger.warning("Room files lookup error: %s", type(e).__name__)
        return []
