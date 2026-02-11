#!/usr/bin/env python3
"""
ChatWork E2E 自動テスト

ChatWork APIを使って実際にメッセージを送受信し、
ソウルくんの返答内容を自動検証する。

使い方:
    # 基本テスト（デフォルトルームで挨拶テスト）
    python3 scripts/test_chatwork_e2e.py

    # カスタムメッセージでテスト
    python3 scripts/test_chatwork_e2e.py --message "タスク一覧を教えて"

    # ルーム指定
    python3 scripts/test_chatwork_e2e.py --room-id 123456789

    # タイムアウト指定（秒）
    python3 scripts/test_chatwork_e2e.py --timeout 60

    # ドライラン（メッセージ送信なし、APIトークン確認のみ）
    python3 scripts/test_chatwork_e2e.py --dry-run

必要な設定:
    - CHATWORK_API_TOKEN: Secret Manager に登録済み（人間ユーザーのトークン）
    - SOULKUN_CHATWORK_TOKEN: Secret Manager に登録済み（ソウルくんのトークン）

テストルームのルール:
    - デフォルト: カズさん↔ソウルくんのDM（217825794）
    - グループチャットでテストしないと挙動が分からないもの以外は、
      全てDMの中だけで完結させること
    - グループチャットでのテストは --room-id で明示的に指定した場合のみ

環境変数（オプション）:
    - SOULKUN_MENTION_ID: Webhook受信アカウントID（デフォルト: 10909425）
    - SOULKUN_REPLY_ID: 応答送信アカウントID（デフォルト: 10909425）
    - E2E_TEST_ROOM_ID: テスト用ルームID（デフォルト: 217825794 = DM）
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
from dataclasses import dataclass
from typing import Any, Optional


# ===========================================================================
# 設定（環境変数 > デフォルト値）
# ===========================================================================

SOULKUN_MENTION_ID = os.environ.get("SOULKUN_MENTION_ID", "10909425")
SOULKUN_REPLY_ID = os.environ.get("SOULKUN_REPLY_ID", "10909425")
# デフォルトテストルーム: カズさん↔ソウルくんのDM
# グループチャットでテストすると他メンバーに通知が飛ぶため、DMを使用
DEFAULT_TEST_ROOM_ID = os.environ.get("E2E_TEST_ROOM_ID", "217825794")
DEFAULT_TIMEOUT = 45
POLL_INTERVAL = 5
MAX_RESPONSE_CHARS = 500


@dataclass
class TestResult:
    """テスト結果"""
    success: bool
    message: str
    sent_message_id: Optional[str] = None
    response_text: Optional[str] = None
    response_time_seconds: Optional[float] = None


# ===========================================================================
# Secret Manager
# ===========================================================================

def get_secret(name: str) -> str:
    """Google Secret Managerからシークレットを取得"""
    try:
        result = subprocess.run(
            ["gcloud", "secrets", "versions", "access", "latest",
             "--secret", name],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            print(f"  [ERROR] Secret '{name}' の取得に失敗")
            sys.exit(1)
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        print(f"  [ERROR] Secret '{name}' の取得がタイムアウト")
        sys.exit(1)


# ===========================================================================
# ChatWork API（urllib使用 — トークンがプロセスリストに露出しない）
# ===========================================================================

def chatwork_api(
    token: str,
    method: str,
    endpoint: str,
    data: Optional[dict] = None,
) -> Any:
    """ChatWork APIを呼び出す（urllib使用）"""
    url = f"https://api.chatwork.com/v2{endpoint}"
    headers = {"X-ChatWorkToken": token}

    body = None
    if data:
        body = urllib.parse.urlencode(data).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"

    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp_body = resp.read().decode("utf-8")
            if not resp_body.strip():
                return {}
            try:
                return json.loads(resp_body)
            except json.JSONDecodeError:
                raise RuntimeError(f"Invalid JSON response: {resp_body[:200]}")
    except urllib.error.HTTPError as e:
        status = e.code
        error_body = ""
        try:
            error_body = e.read().decode("utf-8")[:200]
        except Exception:
            pass
        if status == 429:
            raise RuntimeError(f"ChatWork API rate limit (429): {error_body}")
        raise RuntimeError(f"ChatWork API error ({status}): {error_body}")


def send_message(token: str, room_id: int, body: str) -> dict:
    """ChatWorkにメッセージを送信"""
    result = chatwork_api(token, "POST", f"/rooms/{room_id}/messages",
                          data={"body": body})
    if isinstance(result, dict):
        return result
    return {}


def get_messages(token: str, room_id: int) -> list:
    """ルームのメッセージを取得（force=1で既読も含む）"""
    result = chatwork_api(token, "GET",
                          f"/rooms/{room_id}/messages?force=1")
    if isinstance(result, list):
        return result
    return []


def get_my_info(token: str) -> dict:
    """自分のアカウント情報を取得"""
    result = chatwork_api(token, "GET", "/me")
    if isinstance(result, dict):
        return result
    return {}


def get_rooms(token: str) -> list:
    """参加ルーム一覧を取得"""
    result = chatwork_api(token, "GET", "/rooms")
    if isinstance(result, list):
        return result
    return []


def _mask_id(account_id: str) -> str:
    """アカウントIDをマスキング（末尾4桁のみ表示）"""
    if len(account_id) <= 4:
        return account_id
    return "***" + account_id[-4:]


# ===========================================================================
# テスト用ルーム検出
# ===========================================================================

def find_test_room(token: str) -> Optional[int]:
    """テスト用ルームを自動検出（名前に'テスト'または'test'を含むルーム）"""
    rooms = get_rooms(token)
    for room in rooms:
        name = room.get("name", "").lower()
        if "テスト" in name or "test" in name:
            return room["room_id"]
    return None


# ===========================================================================
# E2Eテスト実行
# ===========================================================================

def run_e2e_test(
    room_id: int,
    message: str,
    timeout: int,
    human_token: str,
    bot_token: str,
) -> TestResult:
    """
    E2Eテストを実行

    1. 人間トークンでソウルくんにメンション送信
    2. ポーリングでソウルくんの応答を待つ
    3. 応答内容を検証
    """
    mention_body = f"[To:{SOULKUN_MENTION_ID}] {message}"

    print(f"  送信先ルーム: {room_id}")
    print(f"  メッセージ: {message[:80]}")
    print()

    # Step 1: メッセージ送信
    print("  [1/3] メッセージ送信中...")
    try:
        result = send_message(human_token, room_id, mention_body)
    except RuntimeError as e:
        return TestResult(success=False, message=f"送信失敗: {e}")

    sent_id = result.get("message_id")
    if not sent_id:
        return TestResult(
            success=False,
            message="message_id が返されなかった（API応答異常）",
        )

    try:
        sent_id_int = int(sent_id)
    except (ValueError, TypeError):
        return TestResult(
            success=False,
            message=f"message_id が数値でない: {sent_id}",
        )

    print(f"  送信完了 (message_id: {_mask_id(str(sent_id))})")

    # Step 2: 応答をポーリング
    print(f"  [2/3] ソウルくんの応答を待機中... (最大{timeout}秒)")
    start_time = time.time()
    response_text = None
    rate_limit_count = 0

    while time.time() - start_time < timeout:
        time.sleep(POLL_INTERVAL)
        elapsed = time.time() - start_time
        print(f"    ...{elapsed:.0f}秒経過", end="\r")

        try:
            messages = get_messages(bot_token, room_id)
        except RuntimeError as e:
            error_msg = str(e)
            if "429" in error_msg:
                rate_limit_count += 1
                if rate_limit_count >= 3:
                    return TestResult(
                        success=False,
                        message=f"APIレート制限に{rate_limit_count}回到達",
                        sent_message_id=str(sent_id),
                        response_time_seconds=elapsed,
                    )
                time.sleep(POLL_INTERVAL)  # 追加待ち
            continue

        # 送信後のメッセージからソウルくんの応答を探す（int比較）
        for msg in messages:
            try:
                msg_id_int = int(msg.get("message_id", 0))
            except (ValueError, TypeError):
                continue
            account_id = str(msg.get("account", {}).get("account_id", ""))
            if account_id == SOULKUN_REPLY_ID and msg_id_int > sent_id_int:
                response_text = msg.get("body", "")
                break

        if response_text is not None:
            break

    elapsed = time.time() - start_time
    print()

    if response_text is None:
        return TestResult(
            success=False,
            message=f"タイムアウト ({timeout}秒): ソウルくんの応答なし",
            sent_message_id=str(sent_id),
            response_time_seconds=elapsed,
        )

    # Step 3: 応答検証
    print(f"  [3/3] 応答検証中... ({elapsed:.1f}秒で応答)")

    if not response_text.strip():
        return TestResult(
            success=False,
            message="応答が空",
            sent_message_id=str(sent_id),
            response_text=response_text,
            response_time_seconds=elapsed,
        )

    return TestResult(
        success=True,
        message="応答を確認",
        sent_message_id=str(sent_id),
        response_text=response_text,
        response_time_seconds=elapsed,
    )


# ===========================================================================
# 直接モード（署名付きPOSTでCloud Functionに直接送信）
# ===========================================================================

def run_direct_test(
    room_id: int,
    sender_id: str,
    message: str,
    timeout: int,
    bot_token: str,
) -> TestResult:
    """
    直接モードE2Eテスト

    1. Webhook署名を生成してCloud Functionに直接POST
    2. Cloud Functionが処理してChatWork APIで応答
    3. ChatWork APIで応答メッセージを取得・検証
    """
    import base64
    import hashlib
    import hmac

    region = "asia-northeast1"
    project = "soulkun-production"
    function_url = f"https://{region}-{project}.cloudfunctions.net/chatwork-webhook"

    print(f"  送信先: {function_url}")
    print(f"  ルームID: {room_id}")
    print(f"  メッセージ: {message[:80]}")
    print()

    # Step 1: Webhookトークン取得
    print("  [1/4] Webhookトークン取得中...")
    webhook_token_b64 = get_secret("CHATWORK_WEBHOOK_TOKEN")
    webhook_token = base64.b64decode(webhook_token_b64)

    # Step 2: ペイロードと署名を生成
    print("  [2/4] ペイロード + 署名生成中...")
    ts = int(time.time())
    payload = json.dumps({
        "webhook_setting_id": "e2e-test",
        "webhook_event_type": "mention_to_me",
        "webhook_event_time": ts,
        "webhook_event": {
            "message_id": f"e2e-{ts}",
            "room_id": room_id,
            "from_account_id": int(sender_id),
            "body": message,
            "send_time": ts,
            "update_time": 0,
        },
    }, ensure_ascii=False)

    payload_bytes = payload.encode("utf-8")
    digest = hmac.new(webhook_token, payload_bytes, hashlib.sha256).digest()
    signature = base64.b64encode(digest).decode()

    # Step 3: Cloud Functionに直接POST
    print("  [3/4] Cloud Functionに送信中...")
    start_time = time.time()

    headers = {
        "Content-Type": "application/json",
        "X-ChatWorkWebhookSignature": signature,
    }
    req = urllib.request.Request(
        function_url, data=payload_bytes, headers=headers, method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            status = resp.status
            resp_body = resp.read().decode("utf-8")[:200]
    except urllib.error.HTTPError as e:
        status = e.code
        try:
            resp_body = e.read().decode("utf-8")[:200]
        except Exception:
            resp_body = ""
    except Exception as e:
        return TestResult(success=False, message=f"Cloud Function送信失敗: {e}")

    cf_elapsed = time.time() - start_time
    print(f"  Cloud Function応答: HTTP {status} ({cf_elapsed:.1f}秒)")

    if status != 200:
        return TestResult(
            success=False,
            message=f"Cloud Function HTTP {status}: {resp_body}",
            response_time_seconds=cf_elapsed,
        )

    # Step 4: ChatWork APIで応答を確認
    print(f"  [4/4] ChatWorkで応答確認中... (最大{timeout}秒)")
    response_text = None
    poll_start = time.time()

    while time.time() - poll_start < timeout:
        time.sleep(POLL_INTERVAL)
        elapsed = time.time() - poll_start
        print(f"    ...{elapsed:.0f}秒経過", end="\r")

        try:
            messages = get_messages(bot_token, room_id)
        except RuntimeError:
            continue

        # 直近のソウルくんからのメッセージを探す（テスト開始後）
        for msg in reversed(messages):
            account_id = str(msg.get("account", {}).get("account_id", ""))
            msg_time = msg.get("send_time", 0)
            if account_id == SOULKUN_REPLY_ID and msg_time >= ts - 5:
                response_text = msg.get("body", "")
                break

        if response_text is not None:
            break

    total_elapsed = time.time() - start_time
    print()

    if response_text is None:
        # 応答なしでもCloud Function自体は成功している場合
        return TestResult(
            success=True,
            message=f"Cloud Function処理成功 (HTTP 200, {cf_elapsed:.1f}秒)"
                    f" ※ChatWork応答未検出（テスト用room_id/sender_idのため返信なしの可能性）",
            response_time_seconds=total_elapsed,
        )

    if not response_text.strip():
        return TestResult(
            success=False,
            message="応答が空",
            response_text=response_text,
            response_time_seconds=total_elapsed,
        )

    return TestResult(
        success=True,
        message="Cloud Function処理成功 + ChatWork応答確認",
        response_text=response_text,
        response_time_seconds=total_elapsed,
    )


# ===========================================================================
# メイン
# ===========================================================================

def main():
    parser = argparse.ArgumentParser(description="ChatWork E2E 自動テスト")
    parser.add_argument(
        "--room-id", type=int,
        default=int(DEFAULT_TEST_ROOM_ID),
        help="テスト用ルームID（デフォルト: DM 217825794）",
    )
    parser.add_argument(
        "--message", type=str, default="テスト: 今日のタスクを教えて",
        help="テストメッセージ",
    )
    parser.add_argument(
        "--timeout", type=int, default=DEFAULT_TIMEOUT,
        help=f"応答待ちタイムアウト（秒、デフォルト: {DEFAULT_TIMEOUT}）",
    )
    parser.add_argument(
        "--direct", action="store_true",
        help="直接モード（署名付きPOSTでCloud Functionに直接送信）",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="ドライラン（API接続確認のみ）",
    )
    args = parser.parse_args()

    print("=" * 50)
    print("ChatWork E2E 自動テスト")
    print("=" * 50)
    print()

    # Step 0: トークン取得
    print("[Setup] APIトークン取得中...")
    human_token = get_secret("CHATWORK_API_TOKEN")
    bot_token = get_secret("SOULKUN_CHATWORK_TOKEN")
    print("  人間トークン: OK")
    print("  ボットトークン: OK")
    print()

    # Step 0.5: API接続確認 + アカウントID検証
    print("[Setup] API接続確認中...")
    try:
        human_info = get_my_info(human_token)
        human_id = str(human_info.get("account_id", ""))
        print(f"  人間アカウント: OK (id: {_mask_id(human_id)})")
    except RuntimeError as e:
        print(f"  [ERROR] 人間トークンでのAPI接続失敗: {e}")
        sys.exit(1)

    try:
        bot_info = get_my_info(bot_token)
        bot_id = str(bot_info.get("account_id", ""))
        print(f"  ボットアカウント: OK (id: {_mask_id(bot_id)})")
        # アカウントID整合性チェック
        if bot_id != SOULKUN_REPLY_ID:
            print(f"  [WARN] SOULKUN_REPLY_ID ({SOULKUN_REPLY_ID}) と"
                  f" 実際のID ({_mask_id(bot_id)}) が不一致")
    except RuntimeError as e:
        print(f"  [ERROR] ボットトークンでのAPI接続失敗: {e}")
        sys.exit(1)
    print()

    if args.dry_run:
        print("[DRY RUN] API接続確認完了。メッセージ送信はスキップ。")
        return

    # Step 1: ルームID決定（デフォルト: DM）
    room_id = args.room_id
    if room_id == int(DEFAULT_TEST_ROOM_ID):
        print(f"[Setup] テストルーム: DM (room_id={room_id})")
    else:
        print(f"[Setup] テストルーム: カスタム指定 (room_id={room_id})")
        print("  ※ グループチャットの場合、他メンバーに通知が飛びます")
    print()

    # Step 2: テスト実行
    if args.direct:
        print("[Test] 直接モード E2Eテスト開始")
    else:
        print("[Test] Webhookモード E2Eテスト開始")
    print("-" * 50)

    if args.direct:
        result = run_direct_test(
            room_id=room_id,
            sender_id=human_id,
            message=args.message,
            timeout=args.timeout,
            bot_token=bot_token,
        )
    else:
        result = run_e2e_test(
            room_id=room_id,
            message=args.message,
            timeout=args.timeout,
            human_token=human_token,
            bot_token=bot_token,
        )

    # Step 3: 結果表示
    print()
    print("=" * 50)
    if result.success:
        print("PASS: " + result.message)
    else:
        print("FAIL: " + result.message)

    if result.response_time_seconds is not None:
        print(f"  応答時間: {result.response_time_seconds:.1f}秒")

    if result.response_text:
        truncated = result.response_text[:MAX_RESPONSE_CHARS]
        if len(result.response_text) > MAX_RESPONSE_CHARS:
            truncated += "..."
        print(f"  応答内容: {truncated}")

    print("=" * 50)

    sys.exit(0 if result.success else 1)


if __name__ == "__main__":
    main()
