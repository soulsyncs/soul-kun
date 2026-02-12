# lib/meetings/zoom_webhook_verify.py
"""
Zoom Webhook署名検証モジュール

Zoom Server-to-Server Webhook通知の署名を検証する。
不正リクエスト・リプレイ攻撃を防止。

署名方式:
  message = "v0:{timestamp}:{request_body}"
  signature = HMAC-SHA256(secret_token, message)
  header value = "v0={signature_hex}"

参考: https://developers.zoom.us/docs/api/rest/webhook-reference/#verify-webhook-events

Author: Claude Opus 4.6
Created: 2026-02-13
"""

import hashlib
import hmac
import logging
import time

logger = logging.getLogger(__name__)

# リプレイ攻撃防止: 5分以上古いリクエストを拒否
MAX_TIMESTAMP_AGE_SECONDS = 300


def verify_zoom_webhook_signature(
    request_body: bytes,
    timestamp: str,
    signature: str,
    secret_token: str,
) -> bool:
    """
    Zoom Webhookリクエストの署名を検証する。

    Args:
        request_body: HTTPリクエストボディ（生バイト列）
        timestamp: x-zm-request-timestamp ヘッダー値
        signature: x-zm-signature ヘッダー値（"v0=..." 形式）
        secret_token: Zoom Appで設定したWebhook secret token

    Returns:
        True: 署名が正当
        False: 署名が不正、タイムスタンプが古い、またはパラメータが不正
    """
    if not request_body or not timestamp or not signature or not secret_token:
        logger.warning("Zoom webhook verification: missing required parameter")
        return False

    # タイムスタンプ検証（リプレイ攻撃防止）
    try:
        request_ts = int(timestamp)
        current_ts = int(time.time())
        if abs(current_ts - request_ts) > MAX_TIMESTAMP_AGE_SECONDS:
            logger.warning(
                "Zoom webhook timestamp too old: delta=%ds",
                abs(current_ts - request_ts),
            )
            return False
    except (ValueError, TypeError):
        logger.warning("Zoom webhook timestamp invalid: %s", timestamp)
        return False

    # HMAC-SHA256署名検証
    try:
        body_str = request_body.decode("utf-8")
    except UnicodeDecodeError:
        logger.warning("Zoom webhook body is not valid UTF-8")
        return False

    message = f"v0:{timestamp}:{body_str}"
    expected_sig = "v0=" + hmac.new(
        secret_token.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_sig, signature):
        logger.warning("Zoom webhook signature mismatch")
        return False

    return True


def generate_zoom_url_validation_response(
    plain_token: str,
    secret_token: str,
) -> dict:
    """
    Zoom Webhook endpoint.url_validation チャレンジへの応答を生成する。

    Zoom AppでWebhook URLを登録する際にZoomが送信するバリデーションリクエスト。
    plainTokenをHMAC-SHA256で暗号化して返す必要がある。

    Args:
        plain_token: Zoomから送信されたplainToken
        secret_token: Zoom Appで設定したWebhook secret token

    Returns:
        {"plainToken": ..., "encryptedToken": ...}
    """
    encrypted_token = hmac.new(
        secret_token.encode("utf-8"),
        plain_token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return {
        "plainToken": plain_token,
        "encryptedToken": encrypted_token,
    }
