"""
main.py - 求人問い合わせメール → ChatWork集約サービス

【動作の流れ】
  Gmail → Pub/Sub → このCloud Runサービス → ChatWork

【エンドポイント】
  POST /receive         : Gmail Pub/Sub push notification を受信（OIDC認証必須）
  POST /weekly-forecast : 先読み採用アラートをChatWorkに投稿（Cloud Scheduler→OIDC認証必須）
  POST /renew-watch     : Gmail watchを更新（6日ごとのCloud Scheduler→OIDC認証必須）
  POST /test            : 動作テスト用（APIキー認証必須）
  GET  /health          : ヘルスチェック

【セキュリティ設計】
  - Cloud Run は --no-allow-unauthenticated でデプロイ
  - Pub/Sub サービスアカウントに roles/run.invoker を付与
  - /receive: Cloud Run が OIDC トークンを自動検証
  - /test: TEST_API_KEY 環境変数で保護（本番では未設定にして無効化）
"""
import base64
import json
import logging
import os
import sys
from typing import Optional

from flask import Flask, jsonify, request

# 共有ライブラリ（soul-kun/lib/ 以下）を import するため PYTHONPATH に /app/lib を含む想定
# ローカル実行時は PYTHONPATH=/path/to/soul-kun を設定すること
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.chatwork import ChatworkClient
from lib.secrets import get_secret_cached
from lib.renk_os_client import RenkOsClient

from gmail_client import GmailClient
from mail_parser import parse_raw_email, format_chatwork_message

# Firestore（historyId永続化用）
try:
    from google.cloud import firestore as _firestore
    _FIRESTORE_AVAILABLE = True
except ImportError:
    _FIRESTORE_AVAILABLE = False

# Firestoreドキュメントパス（historyIdを保存する場所）
_HISTORY_ID_COLLECTION = "job_inquiry_mail_state"
_HISTORY_ID_DOC = "gmail_watch"

# =============================================================================
# ログ設定
# =============================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

# =============================================================================
# 設定（環境変数 or Secret Manager）
# =============================================================================

# ChatWork の通知先グループID（環境変数 RECRUIT_CHATWORK_ROOM_ID で指定）
RECRUIT_CHATWORK_ROOM_ID = os.getenv("RECRUIT_CHATWORK_ROOM_ID", "")

# Gmail の監視対象メールアドレス（環境変数 RECRUIT_GMAIL_ADDRESS で指定）
RECRUIT_GMAIL_ADDRESS = os.getenv("RECRUIT_GMAIL_ADDRESS", "")

# Cloud Run サービスアカウントの Google Project ID
GOOGLE_PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", os.getenv("GCLOUD_PROJECT", ""))

# /test エンドポイントの保護用 API キー（未設定の場合は /test エンドポイントを無効化）
TEST_API_KEY = os.getenv("TEST_API_KEY", "")

# =============================================================================
# Flask アプリ
# =============================================================================
app = Flask(__name__)


def _load_history_id() -> Optional[str]:
    """Firestore から前回の historyId を読み込む"""
    if not _FIRESTORE_AVAILABLE:
        return None
    try:
        db = _firestore.Client()
        doc = db.collection(_HISTORY_ID_COLLECTION).document(_HISTORY_ID_DOC).get()
        if doc.exists:
            return doc.to_dict().get("history_id")
    except Exception as e:
        logger.warning(f"historyId 読み込み失敗（無視して続行）: {e}")
    return None


def _save_history_id(history_id: str) -> None:
    """Firestore に最新の historyId を保存する"""
    if not _FIRESTORE_AVAILABLE:
        return
    try:
        db = _firestore.Client()
        db.collection(_HISTORY_ID_COLLECTION).document(_HISTORY_ID_DOC).set(
            {"history_id": history_id, "updated_at": _firestore.SERVER_TIMESTAMP}
        )
    except Exception as e:
        logger.warning(f"historyId 保存失敗（無視して続行）: {e}")


def _get_chatwork_client() -> Optional[ChatworkClient]:
    """ChatworkClient を初期化して返す。トークン取得失敗時は None"""
    try:
        token = get_secret_cached("chatwork-api-token")
        return ChatworkClient(token)
    except Exception as e:
        logger.error(f"ChatWork トークン取得失敗: {e}")
        return None


# =============================================================================
# エンドポイント: Gmail Pub/Sub push notification 受信
# =============================================================================

@app.route("/receive", methods=["POST"])
def receive_gmail_push():
    """
    Gmail Pub/Sub push notification を受信するエンドポイント。

    Gmail watch() API が新着メールを検知すると、Pub/Sub が
    このエンドポイントに JSON を POST してくる。

    リクエスト形式:
    {
        "message": {
            "data": "<base64エンコードされた JSON>",
            "messageId": "xxx",
            "publishTime": "xxx"
        },
        "subscription": "projects/.../subscriptions/..."
    }

    data を base64 デコードすると:
    {
        "emailAddress": "recruit@soulsyncs.jp",
        "historyId": "12345"
    }
    """
    try:
        envelope = request.get_json(force=True, silent=True)
        if not envelope or "message" not in envelope:
            logger.warning("不正なリクエスト（message フィールドなし）")
            return jsonify({"error": "invalid request"}), 400

        # Pub/Sub メッセージをデコード
        pubsub_message = envelope["message"]
        raw_data = pubsub_message.get("data", "")
        if not raw_data:
            logger.warning("Pub/Sub data フィールドが空")
            return jsonify({"status": "ignored", "reason": "empty data"}), 200

        decoded = json.loads(base64.b64decode(raw_data).decode("utf-8"))
        history_id = decoded.get("historyId")

        # emailAddress は環境変数固定（ペイロードの値は使わない → メールボックス乗っ取り防止）
        email_address = RECRUIT_GMAIL_ADDRESS

        logger.info(f"Gmail push受信: historyId={history_id}, address={email_address}")

        if not history_id:
            return jsonify({"status": "ignored", "reason": "no historyId"}), 200

        # 前回保存した historyId を使う（なければ通知の historyId を使用）
        stored_id = _load_history_id()
        start_history_id = stored_id if stored_id else history_id

        # Gmail API で新着メールを取得・処理
        processed_count = _process_new_emails(start_history_id, email_address)

        # 今回の historyId を保存（次回の起点）
        _save_history_id(history_id)

        return jsonify({
            "status": "ok",
            "processed": processed_count,
        }), 200

    except Exception as e:
        logger.error(f"receive エラー: {e}", exc_info=True)
        # Pub/Sub は 2xx 以外を返すとリトライするため 200 で返す
        return jsonify({"status": "error", "message": str(e)}), 200


@app.route("/test", methods=["POST"])
def test_post():
    """
    動作テスト用エンドポイント。
    生のメール（RFC 2822形式）を送ると ChatWork に通知する。

    【セキュリティ】
    - TEST_API_KEY 環境変数が設定されていない場合は 403 を返す
    - Authorization: Bearer <TEST_API_KEY> ヘッダーが必要

    使い方:
      curl -X POST https://<cloud-run-url>/test \\
           -H "Authorization: Bearer <TEST_API_KEY>" \\
           -H "Content-Type: application/json" \\
           -d '{"raw_email": "From: noreply@indeed.com\\nSubject: 山田太郎さんが...", "dry_run": true}'
    """
    # テストAPIキーが未設定の場合は本番環境として無効化
    if not TEST_API_KEY:
        return jsonify({"error": "test endpoint is disabled in production"}), 403

    # APIキー認証
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer ") or auth_header[7:] != TEST_API_KEY:
        return jsonify({"error": "unauthorized"}), 401

    body = request.get_json(force=True, silent=True) or {}
    raw_email_str = body.get("raw_email", "")
    dry_run = body.get("dry_run", False)

    if not raw_email_str:
        return jsonify({"error": "raw_email フィールドが必要です"}), 400

    inquiry = parse_raw_email(raw_email_str.encode("utf-8"))
    if inquiry is None:
        return jsonify({"result": "skipped", "reason": "求人問い合わせと判定されませんでした"}), 200

    message = format_chatwork_message(inquiry)

    if dry_run:
        return jsonify({
            "result": "dry_run",
            "would_post": message,
            "platform": inquiry.platform,
            "applicant": inquiry.applicant_name,
        }), 200

    # 実際に ChatWork に投稿
    room_id = RECRUIT_CHATWORK_ROOM_ID
    if not room_id:
        return jsonify({"error": "RECRUIT_CHATWORK_ROOM_ID が設定されていません"}), 500

    cw = _get_chatwork_client()
    if cw is None:
        return jsonify({"error": "ChatWork 初期化失敗"}), 500

    cw.send_message(int(room_id), message)
    logger.info(f"テスト投稿完了: {inquiry.platform} / {inquiry.applicant_name}")

    return jsonify({
        "result": "posted",
        "platform": inquiry.platform,
        "applicant": inquiry.applicant_name,
        "message": message,
    }), 200


@app.route("/health", methods=["GET"])
def health():
    """ヘルスチェック"""
    return jsonify({"status": "ok", "service": "receive-job-inquiry-mail"}), 200


@app.route("/weekly-forecast", methods=["POST"])
def weekly_forecast():
    """
    先読み採用アラートを ChatWork に投稿するエンドポイント。

    Cloud Scheduler から毎週月曜朝9時に呼び出される想定。
    Re:nk OS から「今後30〜60日以内に終了する案件」を取得して
    ChatWork の求人グループに週次レポートとして投稿する。

    【セキュリティ】
    - Cloud Run は --no-allow-unauthenticated でデプロイ済み
    - Cloud Scheduler の OIDC 認証で保護
    """
    try:
        room_id = RECRUIT_CHATWORK_ROOM_ID
        if not room_id:
            logger.error("RECRUIT_CHATWORK_ROOM_ID が設定されていません")
            return jsonify({"error": "RECRUIT_CHATWORK_ROOM_ID 未設定"}), 500

        # Re:nk OS から先読み予測を取得
        try:
            renk = RenkOsClient()
            message = renk.format_forecast_chatwork_message()
        except Exception as e:
            logger.error(f"Re:nk OS 先読み取得失敗: {e}")
            return jsonify({"error": "Re:nk OS 接続失敗"}), 500

        if message is None:
            logger.info("終了予定案件なし → 先読みアラートをスキップ")
            return jsonify({"status": "skipped", "reason": "終了予定案件なし"}), 200

        # ChatWork に投稿
        cw = _get_chatwork_client()
        if cw is None:
            return jsonify({"error": "ChatWork 初期化失敗"}), 500

        cw.send_message(int(room_id), message)
        logger.info("先読み採用アラートを ChatWork に投稿しました")

        return jsonify({"status": "posted"}), 200

    except Exception as e:
        logger.error(f"weekly-forecast エラー: {e}", exc_info=True)
<<<<<<< HEAD
        return jsonify({"error": str(e)}), 500


# =============================================================================
# 内部処理: 採否判断付き ChatWork メッセージ生成
# =============================================================================

def _build_screened_message(
    inquiry,
    is_hiring_needed: bool,
    understaffed_projects: list,
    fill_rate: Optional[float],
) -> str:
    """
    採否判断の結果を先頭に付加した ChatWork 投稿メッセージを生成する。

    採用ニーズあり → 🔥【優先対応】
    採用充足中    → 📋【確認待ち】
    """
    base_message = format_chatwork_message(inquiry)

    if is_hiring_needed:
        header_lines = ["🔥【優先対応】採用ニーズが確認されました"]
        if understaffed_projects:
            # 不足案件を最大3件まで表示
            names = "、".join(
                p.get("project_name", "不明") for p in understaffed_projects[:3]
            )
            header_lines.append(f"人員不足の案件: {names}")
        if fill_rate is not None:
            header_lines.append(f"現在の充足率: {int(fill_rate)}%")
    else:
        header_lines = ["📋【確認待ち】現在は採用充足中です"]
        if fill_rate is not None:
            header_lines.append(f"現在の充足率: {int(fill_rate)}%（不足案件なし）")
        header_lines.append("採用ニーズが発生した際に再度ご検討ください。")

    header = "\n".join(header_lines)
    return f"{header}\n{'-' * 30}\n{base_message}"
=======
        return jsonify({"error": "予期しないエラーが発生しました"}), 500


@app.route("/renew-watch", methods=["POST"])
def renew_watch():
    """
    Gmail watch を更新するエンドポイント。

    Gmail の push 通知（= 新着メールをリアルタイムで受け取る設定）は
    7日で期限切れになるため、6日ごとに Cloud Scheduler から呼び出す。

    【セキュリティ】
    - Cloud Run は --no-allow-unauthenticated でデプロイ済み
    - Cloud Scheduler の OIDC 認証で保護
    """
    import httpx

    GMAIL_PUBSUB_TOPIC = (
        f"projects/{GOOGLE_PROJECT_ID}/topics/gmail-job-inquiry-notifications"
    )
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    WATCH_URL = "https://gmail.googleapis.com/gmail/v1/users/me/watch"

    try:
        # Secret Manager から OAuth2 認証情報を取得
        refresh_token = get_secret_cached("gmail-oauth-refresh-token")
        client_id = get_secret_cached("gmail-oauth-client-id")
        client_secret = get_secret_cached("gmail-oauth-client-secret")

        # アクセストークンを取得
        with httpx.Client(timeout=10) as client:
            token_resp = client.post(TOKEN_URL, data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            })
            if token_resp.status_code != 200:
                logger.error(f"OAuth2 トークン取得失敗: {token_resp.status_code}")
                return jsonify({"error": "OAuth2 トークン取得失敗"}), 500

            access_token = token_resp.json().get("access_token")
            if not access_token:
                logger.error("アクセストークンが空")
                return jsonify({"error": "アクセストークン取得失敗"}), 500

            # Gmail Watch API を呼び出し
            watch_resp = client.post(
                WATCH_URL,
                headers={"Authorization": f"Bearer {access_token}"},
                json={"topicName": GMAIL_PUBSUB_TOPIC, "labelIds": ["INBOX"]},
            )

        if watch_resp.status_code != 200:
            logger.error(f"Gmail watch 更新失敗: {watch_resp.status_code}")
            return jsonify({"error": "Gmail watch 更新失敗"}), 500

        watch_data = watch_resp.json()
        history_id = watch_data.get("historyId", "")
        expiration = watch_data.get("expiration", "")
        logger.info(f"Gmail watch 更新成功: historyId={history_id}")

        return jsonify({
            "status": "renewed",
            "history_id": history_id,
            "expiration_ms": expiration,
        }), 200

    except Exception as e:
        logger.error(f"renew-watch エラー: {e}", exc_info=True)
        return jsonify({"error": "予期しないエラーが発生しました"}), 500
>>>>>>> 2ebf1e6 (feat(phase5+): weekly-forecast / renew-watch エンドポイント追加 + RenkOsClientを追加)


# =============================================================================
# 内部処理: 採否判断付き ChatWork メッセージ生成
# =============================================================================

def _build_screened_message(
    inquiry,
    is_hiring_needed: bool,
    understaffed_projects: list,
    fill_rate: Optional[float],
) -> str:
    """
    採否判断の結果を先頭に付加した ChatWork 投稿メッセージを生成する。

    採用ニーズあり → 🔥【優先対応】
    採用充足中    → 📋【確認待ち】
    """
    base_message = format_chatwork_message(inquiry)

    if is_hiring_needed:
        header_lines = ["🔥【優先対応】採用ニーズが確認されました"]
        if understaffed_projects:
            # 不足案件を最大3件まで表示
            names = "、".join(
                p.get("project_name", "不明") for p in understaffed_projects[:3]
            )
            header_lines.append(f"人員不足の案件: {names}")
        if fill_rate is not None:
            header_lines.append(f"現在の充足率: {int(fill_rate)}%")
    else:
        header_lines = ["📋【確認待ち】現在は採用充足中です"]
        if fill_rate is not None:
            header_lines.append(f"現在の充足率: {int(fill_rate)}%（不足案件なし）")
        header_lines.append("採用ニーズが発生した際に再度ご検討ください。")

    header = "\n".join(header_lines)
    return f"{header}\n{'-' * 30}\n{base_message}"


# =============================================================================
# 内部処理: 新着メールを取得して ChatWork に投稿
# =============================================================================

def _process_new_emails(history_id: str, email_address: str) -> int:
    """
    Gmail history API で新着メールを取得し、
    求人問い合わせであれば採否判断付きで ChatWork に投稿する。
    処理したメール数を返す。
    """
    room_id = RECRUIT_CHATWORK_ROOM_ID
    if not room_id:
        logger.error("RECRUIT_CHATWORK_ROOM_ID が設定されていません")
        return 0

    try:
        gmail = GmailClient(email_address)
        new_messages = gmail.get_new_messages_since(history_id)
    except Exception as e:
        logger.error(f"Gmail API エラー: {e}", exc_info=True)
        return 0

    if not new_messages:
        logger.info("新着メールなし")
        return 0

    cw = _get_chatwork_client()
    if cw is None:
        return 0

    # ── AI スクリーニング: Re:nk OS から採用状況を取得（ループ前に1回だけ）──
    try:
        renk = RenkOsClient()
        staffing = renk.get_staffing_summary()
        if staffing:
            is_hiring = renk.is_hiring_needed()
            understaffed = renk.get_understaffed_projects()
            fill_rate = renk.get_fill_rate()
            logger.info(
                f"Re:nk OS 採用状況: 採用必要={is_hiring}, "
                f"充足率={fill_rate}%, 不足案件数={len(understaffed)}"
            )
        else:
            # データ取得失敗時は「採用必要」として扱う（見逃し防止）
            is_hiring = True
            understaffed = []
            fill_rate = None
            logger.warning("Re:nk OS データ取得失敗 → 採用必要として扱います")
    except Exception as e:
        # 例外時も「採用必要」として安全側に倒す（Re:nk OSの障害で通知を止めない）
        is_hiring = True
        understaffed = []
        fill_rate = None
        logger.warning(f"Re:nk OS 呼び出し例外 → 採用必要として扱います: {e}")

    processed = 0
    for raw_bytes in new_messages:
        try:
            inquiry = parse_raw_email(raw_bytes)
            if inquiry is None:
                logger.info("スキップ（求人問い合わせでない）")
                continue

            # 採否判断付きメッセージを生成して投稿
            message = _build_screened_message(
                inquiry, is_hiring, understaffed, fill_rate
            )
            cw.send_message(int(room_id), message)
            # 個人情報はログに残さない（氏名・職種はマスキング）
            logger.info(
                f"ChatWork投稿完了 [{'優先' if is_hiring else '確認待ち'}]: "
                f"platform={inquiry.platform}"
            )
            processed += 1

        except Exception as e:
            logger.error(f"メール処理エラー: {e}", exc_info=True)
            # 1件のエラーで全体を止めない
            continue

    return processed


# =============================================================================
# エントリポイント（ローカル実行用）
# =============================================================================
if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=False)
