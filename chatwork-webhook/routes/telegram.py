"""
Telegram Webhook ルート（社長専用窓口）

CLAUDE.md §1: 全入力は脳を通る → Telegram入力もBrain経由で処理
CLAUDE.md §8: 権限レベル6（社長/CFO）のみ → CEO chat_id検証
execution_plan: Step B-2 社長専用設定 + セキュリティ強化

v1.0.0: main.py から分割（3,245行→3,000行削減の一部）
"""

import logging
import os
import time
import threading as _threading
from typing import Dict

from flask import Blueprint, jsonify, request as flask_request

logger = logging.getLogger(__name__)

# --- Step B-2: Telegramレート制限（インメモリ） ---
_telegram_rate_limit: Dict[str, list] = {}
_telegram_rate_limit_lock = _threading.Lock()
_TELEGRAM_RATE_LIMIT_MAX = 20    # 1分あたりの上限メッセージ数
_TELEGRAM_RATE_LIMIT_WINDOW = 60  # ウィンドウ（秒）


def _check_telegram_rate_limit(chat_id: str) -> bool:
    """
    Telegramメッセージのレート制限を確認する。

    スライディングウィンドウ方式: 直近60秒以内のリクエストが20件以下ならTrue。
    スレッドセーフ（gunicorn --threads 8 対応）。
    CLAUDE.md §9-3: 監査ログにIDのみ（個人情報なし）。

    Args:
        chat_id: Telegramのchat_id

    Returns:
        True: 許可（レート制限内）、False: 拒否（レート超過）
    """
    now = time.time()
    with _telegram_rate_limit_lock:
        if chat_id not in _telegram_rate_limit:
            _telegram_rate_limit[chat_id] = []

        # 期限切れのタイムスタンプを除去
        _telegram_rate_limit[chat_id] = [
            ts for ts in _telegram_rate_limit[chat_id]
            if now - ts < _TELEGRAM_RATE_LIMIT_WINDOW
        ]

        if len(_telegram_rate_limit[chat_id]) >= _TELEGRAM_RATE_LIMIT_MAX:
            return False

        _telegram_rate_limit[chat_id].append(now)
        return True


telegram_bp = Blueprint("telegram", __name__)


@telegram_bp.route("/telegram", methods=["POST"])
def telegram_webhook():
    """
    Telegram Bot APIのWebhookエンドポイント

    社長専用窓口。TELEGRAM_CEO_CHAT_IDに一致するユーザーからの
    メッセージのみ処理する。

    セキュリティ層（Step B-2）:
    1. 署名検証（X-Telegram-Bot-Api-Secret-Token）
    2. グループチャット制限（privateまたはsupergroup+topicのみ許可）
    3. CEO権限チェック
    4. レート制限（1分20メッセージ）
    5. 監査ログ（IDのみ、個人情報なし）

    Telegram Bot API Webhook format:
      https://core.telegram.org/bots/api#update
    """
    request = flask_request

    try:
        # --- 署名検証 ---
        secret_token = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
        received_token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")

        if secret_token:
            from lib.channels.telegram_adapter import verify_telegram_webhook
            if not verify_telegram_webhook(request.get_data(), secret_token, received_token):
                logger.warning("Telegram: signature verification failed")
                return jsonify({"status": "error"}), 403
        else:
            logger.warning("TELEGRAM_WEBHOOK_SECRET not set — signature verification skipped")

        # --- メッセージ解析 ---
        from lib.channels.telegram_adapter import TelegramChannelAdapter
        adapter = TelegramChannelAdapter()

        data = request.get_json(silent=True)
        if not data:
            return jsonify({"status": "ok"})

        channel_msg = adapter.parse_webhook(data)
        if not channel_msg:
            return jsonify({"status": "ok", "skip": "no_text"})

        chat_id = channel_msg.metadata.get("chat_id", channel_msg.room_id)
        chat_type = channel_msg.metadata.get("chat_type", "unknown")
        is_topic = channel_msg.metadata.get("is_topic", False)

        # --- Step B-2: グループチャット制限 ---
        # private → OK、supergroup + topic → OK、それ以外 → 拒否
        is_private = channel_msg.metadata.get("is_private", False)
        if not is_private and not (chat_type == "supergroup" and is_topic):
            logger.info(
                "Telegram: group chat rejected chat_id=%s type=%s",
                chat_id, chat_type,
            )
            return jsonify({"status": "ok", "skip": "group_not_allowed"})

        # --- Step B-2: 社長専用権限チェック ---
        is_ceo = channel_msg.metadata.get("is_ceo", False)
        if not is_ceo:
            logger.info("Telegram: non-CEO access denied chat_id=%s", chat_id)
            adapter.send_message(
                room_id=chat_id,
                message="🐺 この窓口は社長専用です。ChatWorkからお話しかけてくださいウル！",
            )
            return jsonify({"status": "ok", "skip": "not_ceo"})

        # --- Step B-2: レート制限 ---
        if not _check_telegram_rate_limit(chat_id):
            logger.warning("Telegram: rate limit exceeded chat_id=%s", chat_id)
            adapter.send_message(
                room_id=chat_id,
                message="🐺 メッセージが多すぎるウル！少し待ってからもう一度送ってほしいウル🐺",
            )
            return jsonify({"status": "ok", "skip": "rate_limited"}), 429

        # --- 処理不要な判定 ---
        if not channel_msg.should_process:
            logger.debug("Telegram: skip reason=%s", channel_msg.skip_reason)
            return jsonify({"status": "ok", "skip": channel_msg.skip_reason})

        media_info = channel_msg.metadata.get("media", {})
        if media_info:
            logger.info(
                "Telegram: message received len=%d media_type=%s",
                len(channel_msg.body), media_info.get("media_type", "unknown"),
            )
        else:
            logger.info("Telegram: message received len=%d", len(channel_msg.body))

        # --- 画像検出（file_idのみ記録、ダウンロードはバイパスハンドラー内で非同期実行） ---
        telegram_bypass_context = {}
        if (
            os.environ.get("ENABLE_IMAGE_ANALYSIS", "false").lower() == "true"
            and media_info
        ):
            from lib.channels.telegram_adapter import is_image_media
            if is_image_media(media_info):
                file_id = media_info.get("file_id", "")
                if file_id:
                    telegram_bypass_context["has_image"] = True
                    telegram_bypass_context["image_file_id"] = file_id
                    telegram_bypass_context["image_source"] = "telegram"
                    logger.info("Telegram: image detected for vision AI, file_id=%s", file_id[:20])

        # --- Brain処理 ---
        # _get_brain_integration は main.py のシングルトン管理を参照
        from main import _get_brain_integration
        integration = _get_brain_integration()
        if not integration or not integration.is_brain_enabled():
            adapter.send_message(
                room_id=chat_id,
                message="🤔 ソウルくんの脳が準備できていないウル...しばらく待ってほしいウル🐺",
            )
            return jsonify({"status": "error", "message": "Brain not ready"}), 503

        from lib.brain.handler_wrappers.bypass_handlers import build_bypass_handlers
        bypass_handlers = build_bypass_handlers()

        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            ceo_account_id = os.environ.get("CEO_CHATWORK_ACCOUNT_ID", "")
            result = loop.run_until_complete(
                integration.process_message(
                    message=channel_msg.body,
                    room_id=channel_msg.room_id,
                    account_id=ceo_account_id or channel_msg.sender_id,
                    sender_name=channel_msg.sender_name,
                    fallback_func=None,
                    bypass_context=telegram_bypass_context or None,
                    bypass_handlers=bypass_handlers if telegram_bypass_context else None,
                )
            )
        finally:
            loop.close()

        # --- 応答送信（Telegram経由、Step B-3: トピック内返信対応） ---
        topic_id = channel_msg.metadata.get("topic_id", "")
        send_kwargs = {}
        if topic_id:
            send_kwargs["message_thread_id"] = topic_id

        if result and result.message and not result.error:
            adapter.send_message(room_id=chat_id, message=result.message, **send_kwargs)
            logger.info(
                "Telegram: response sent brain=%s time=%sms",
                result.used_brain, result.processing_time_ms,
            )
            return jsonify({"status": "ok", "brain": result.used_brain, "platform": "telegram"})
        else:
            adapter.send_message(
                room_id=chat_id,
                message="🤔 処理中に問題が発生したウル...もう一度試してほしいウル🐺",
                **send_kwargs,
            )
            return jsonify({"status": "ok", "brain": True, "error": "no_response"})

    except Exception as e:
        logger.error("Telegram webhook error: %s", type(e).__name__, exc_info=True)
        return jsonify({"status": "error", "message": "Internal server error"}), 500
