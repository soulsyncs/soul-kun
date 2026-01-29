"""
ChatWork APIユーティリティ

main.pyから分割されたChatWork API関連の関数を提供する。
レート制限対策、リトライ機構、キャッシュ機能を含む。

分割元: chatwork-webhook/main.py
分割日: 2026-01-25
バージョン: v10.24.0

v10.48.0: メッセージ処理関数を追加（2026-01-29）
- clean_chatwork_message(): メッセージのクリーニング
- is_toall_mention(): オールメンション判定
- is_mention_or_reply_to(): メンション/返信判定
- should_ignore_toall(): TO ALL無視判定
"""

import re
import time
import httpx
from typing import Optional, Dict, Any, Tuple, List


# =====================================================
# APIレート制限対策（v10.3.3）
# =====================================================

class APICallCounter:
    """
    APIコール数をカウントするクラス

    レート制限を監視し、API使用状況をログ出力するために使用
    """

    def __init__(self):
        self.count = 0
        self.start_time = time.time()

    def increment(self):
        """コール数を1増加"""
        self.count += 1

    def get_count(self) -> int:
        """現在のコール数を取得"""
        return self.count

    def log_summary(self, function_name: str):
        """API使用状況のサマリーをログ出力"""
        elapsed = time.time() - self.start_time
        print(f"[API Usage] {function_name}: {self.count} calls in {elapsed:.2f}s")


# グローバルAPIカウンター
_api_call_counter = APICallCounter()

# ルームメンバーキャッシュ（同一リクエスト内で有効）
_room_members_cache: Dict[str, List[Dict]] = {}


def get_api_call_counter() -> APICallCounter:
    """APIカウンターを取得"""
    return _api_call_counter


def reset_api_call_counter():
    """APIカウンターをリセット"""
    global _api_call_counter
    _api_call_counter = APICallCounter()


def clear_room_members_cache():
    """ルームメンバーキャッシュをクリア"""
    global _room_members_cache
    _room_members_cache = {}


def call_chatwork_api_with_retry(
    method: str,
    url: str,
    headers: dict,
    data: dict = None,
    params: dict = None,
    max_retries: int = 3,
    initial_wait: float = 1.0,
    timeout: float = 10.0
) -> Tuple[Optional[httpx.Response], bool]:
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
    """
    wait_time = initial_wait
    counter = get_api_call_counter()

    for attempt in range(max_retries + 1):
        try:
            counter.increment()

            if method.upper() == "GET":
                response = httpx.get(url, headers=headers, params=params, timeout=timeout)
            elif method.upper() == "POST":
                response = httpx.post(url, headers=headers, data=data, timeout=timeout)
            elif method.upper() == "PUT":
                response = httpx.put(url, headers=headers, data=data, timeout=timeout)
            elif method.upper() == "DELETE":
                response = httpx.delete(url, headers=headers, timeout=timeout)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            # 成功（2xx）
            if response.status_code < 400:
                return response, True

            # レート制限（429）
            if response.status_code == 429:
                if attempt < max_retries:
                    print(f"⚠️ Rate limit hit (429). Waiting {wait_time}s before retry {attempt + 1}/{max_retries}")
                    time.sleep(wait_time)
                    wait_time *= 2  # 指数バックオフ
                    continue
                else:
                    print(f"❌ Rate limit hit (429). Max retries exceeded.")
                    return response, False

            # その他のエラー（リトライしない）
            return response, False

        except httpx.TimeoutException:
            print(f"⚠️ API timeout on attempt {attempt + 1}")
            if attempt < max_retries:
                time.sleep(wait_time)
                wait_time *= 2
                continue
            return None, False

        except Exception as e:
            print(f"❌ API error: {e}")
            return None, False

    return None, False


def get_room_members(room_id, api_token: str) -> List[Dict]:
    """
    ルームのメンバー一覧を取得（リトライ機構付き）

    Args:
        room_id: ChatWorkルームID
        api_token: ChatWork APIトークン

    Returns:
        メンバー情報のリスト
    """
    url = f"https://api.chatwork.com/v2/rooms/{room_id}/members"

    response, success = call_chatwork_api_with_retry(
        method="GET",
        url=url,
        headers={"X-ChatWorkToken": api_token}
    )

    if success and response and response.status_code == 200:
        return response.json()
    elif response:
        print(f"ルームメンバー取得エラー: {response.status_code} - {response.text}")
    return []


def get_room_members_cached(room_id, api_token: str) -> List[Dict]:
    """
    ルームメンバーを取得（キャッシュあり）

    同一リクエスト内で同じルームを複数回参照する場合に効率的

    Args:
        room_id: ChatWorkルームID
        api_token: ChatWork APIトークン

    Returns:
        メンバー情報のリスト
    """
    room_id_str = str(room_id)
    if room_id_str in _room_members_cache:
        return _room_members_cache[room_id_str]

    members = get_room_members(room_id, api_token)
    _room_members_cache[room_id_str] = members
    return members


def is_room_member(room_id, account_id, api_token: str) -> bool:
    """
    指定したアカウントがルームのメンバーかどうかを確認（キャッシュ使用）

    Args:
        room_id: ChatWorkルームID
        account_id: 確認するアカウントID
        api_token: ChatWork APIトークン

    Returns:
        メンバーであればTrue
    """
    members = get_room_members_cached(room_id, api_token)
    member_ids = [m.get("account_id") for m in members]
    return int(account_id) in member_ids


# =====================================================
# v10.48.0: メッセージ処理関数
# =====================================================


def clean_chatwork_message(body: Optional[str]) -> str:
    """
    ChatWorkメッセージをクリーニング

    メンションタグ、返信タグ、その他のChatWork固有タグを除去する。

    Args:
        body: メッセージ本文

    Returns:
        クリーニングされたメッセージ
    """
    if body is None:
        return ""

    if not isinstance(body, str):
        try:
            body = str(body)
        except:
            return ""

    if not body:
        return ""

    try:
        clean_message = body
        # メンションタグ: [To:12345] 名前さん
        clean_message = re.sub(r'\[To:\d+\]\s*[^\n\[]*(?:さん|くん|ちゃん|様|氏)?', '', clean_message)
        # 返信ボタンタグ: [rp aid=12345 ...][/rp]
        clean_message = re.sub(r'\[rp aid=\d+[^\]]*\]\[/rp\]', '', clean_message)
        # 一般的なタグ: [xxx] [/xxx]
        clean_message = re.sub(r'\[/?[a-zA-Z]+\]', '', clean_message)
        # 残りの角括弧タグ
        clean_message = re.sub(r'\[.*?\]', '', clean_message)
        # 前後の空白を除去
        clean_message = clean_message.strip()
        # 連続する空白を1つに
        clean_message = re.sub(r'\s+', ' ', clean_message)
        return clean_message
    except Exception as e:
        print(f"⚠️ clean_chatwork_message エラー: {e}")
        return body


def is_toall_mention(body: Optional[str]) -> bool:
    """
    オールメンション（[toall]）かどうかを判定

    オールメンションはアナウンス用途で使われるため、
    通常ソウルくんは反応しない。

    Args:
        body: メッセージ本文

    Returns:
        [toall]が含まれていればTrue
    """
    if body is None:
        return False

    if not isinstance(body, str):
        try:
            body = str(body)
        except:
            return False

    if not body:
        return False

    try:
        # ChatWorkのオールメンションパターン: [toall]
        # 大文字小文字を区別しない
        if "[toall]" in body.lower():
            return True
        return False
    except Exception as e:
        print(f"⚠️ is_toall_mention エラー: {e}")
        return False


def is_mention_or_reply_to(body: Optional[str], account_id: int) -> bool:
    """
    指定されたアカウントへのメンションまたは返信かどうかを判断

    Args:
        body: メッセージ本文
        account_id: 対象のアカウントID

    Returns:
        メンションまたは返信であればTrue
    """
    if body is None:
        return False

    if not isinstance(body, str):
        try:
            body = str(body)
        except:
            return False

    if not body:
        return False

    try:
        # メンションパターン: [To:12345]
        if f"[To:{account_id}]" in body:
            return True

        # 返信ボタンパターン: [rp aid=12345 to=...]
        if f"[rp aid={account_id}" in body:
            return True

        return False
    except Exception as e:
        print(f"⚠️ is_mention_or_reply_to エラー: {e}")
        return False


def should_ignore_toall(body: Optional[str], my_account_id: int) -> bool:
    """
    TO ALLメンションを無視すべきか判定

    判定ロジック:
    - [toall]がなければ → 無視しない（通常処理）
    - [toall]があっても、直接メンションがあれば → 無視しない（反応する）
    - [toall]のみの場合 → 無視する

    Args:
        body: メッセージ本文
        my_account_id: 自分のアカウントID

    Returns:
        無視すべきならTrue、反応すべきならFalse
    """
    # TO ALLでなければ無視しない
    if not is_toall_mention(body):
        return False

    # TO ALLでも、直接メンションがあれば反応する
    if body and f"[to:{my_account_id}]" in body.lower():
        print(f"📌 TO ALL + 直接メンションのため反応する")
        return False

    # TO ALLのみなので無視
    return True
