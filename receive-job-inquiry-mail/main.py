"""
main.py - 求人問い合わせメール → ChatWork集約サービス

【動作の流れ】
  Gmail → Pub/Sub → このCloud Runサービス → ChatWork

【エンドポイント】
  POST /receive   : Gmail Pub/Sub push notification を受信（OIDC認証必須）
  POST /test      : 動作テスト用（APIキー認証必須）
  GET  /health    : ヘルスチェック

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


# =============================================================================
# 内部処理: 新着メールを取得して ChatWork に投稿
# =============================================================================

def _process_new_emails(history_id: str, email_address: str) -> int:
    """
    Gmail history API で新着メールを取得し、
    求人問い合わせであれば ChatWork に投稿する。
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

    processed = 0
    for raw_bytes in new_messages:
        try:
            inquiry = parse_raw_email(raw_bytes)
            if inquiry is None:
                logger.info("スキップ（求人問い合わせでない）")
                continue

            message = format_chatwork_message(inquiry)
            cw.send_message(int(room_id), message)
            logger.info(
                f"ChatWork投稿完了: {inquiry.platform} / "
                f"{inquiry.applicant_name} / {inquiry.job_title}"
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
