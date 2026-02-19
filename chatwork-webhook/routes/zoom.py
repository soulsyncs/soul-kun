"""
Zoom Webhook ルート

CLAUDE.md §1: 全入力は脳を通る（Zoom webhook は Brain-level LLMを使用）
セキュリティ: HMAC-SHA256署名検証必須（3AI合意）
リスク対策:
  - Risk 1: 指数バックオフリトライ（30s+60s+120s）— zoom_brain_interface.py
  - Risk 2: 録音検索ウィンドウ2日以内
  - Risk 4: バックグラウンドスレッドで即200応答（Zoomタイムアウト防止）
  - Risk 5: dedup_hash（SHA256）で二重処理防止

v1.0.0: main.py から分割（Phase 5）
"""

import asyncio
import json
import logging
import os
import threading as _bg_threading

from flask import Blueprint, jsonify, request as flask_request

logger = logging.getLogger(__name__)

zoom_bp = Blueprint("zoom", __name__)


@zoom_bp.route("/zoom-webhook", methods=["POST", "GET"])
def zoom_webhook():
    """
    Cloud Function: Zoom recording.completed Webhook受信

    フロー:
    1. 署名検証（x-zm-signature + x-zm-request-timestamp）
    2. endpoint.url_validation → チャレンジ応答
    3. recording.completed → 議事録自動生成パイプライン

    セキュリティ:
    - HMAC-SHA256署名検証必須（3AI合意）
    - タイムスタンプ検証（5分以内、リプレイ攻撃防止）
    - フィーチャーフラグ: ENABLE_ZOOM_WEBHOOK
    """
    request = flask_request

    try:
        from lib.meetings.zoom_webhook_verify import (
            verify_zoom_webhook_signature,
            generate_zoom_url_validation_response,
        )
        from lib.secrets import get_secret_cached

        request_body = request.get_data()
        if not request_body:
            return jsonify({"status": "error", "message": "Empty body"}), 400

        # 署名検証
        zoom_secret = get_secret_cached("zoom-webhook-secret-token")
        if not zoom_secret:
            print("❌ Zoom webhook secret token not configured")
            return jsonify({"status": "error", "message": "Server configuration error"}), 500

        timestamp = request.headers.get("x-zm-request-timestamp", "")
        signature = request.headers.get("x-zm-signature", "")

        # JSONパース
        try:
            data = json.loads(request_body)
        except json.JSONDecodeError:
            return jsonify({"status": "error", "message": "Invalid JSON"}), 400

        event_type = data.get("event", "")

        # 全イベントで署名検証（url_validationも含む）
        # SECURITY: 署名検証を最初に行い、不正リクエストを全て拒否
        if not verify_zoom_webhook_signature(request_body, timestamp, signature, zoom_secret):
            print("❌ Zoom webhook signature verification failed")
            return jsonify({"status": "error", "message": "Invalid signature"}), 403

        print(f"✅ Zoom webhook signature verified: event={event_type}")

        # endpoint.url_validation: Zoom URL登録時のチャレンジ（署名検証済み）
        # NOTE: url_validationはフィーチャーフラグに関係なく応答する（Webhook登録に必要）
        if event_type == "endpoint.url_validation":
            plain_token = data.get("payload", {}).get("plainToken", "")
            if not plain_token:
                return jsonify({"status": "error", "message": "Missing plainToken"}), 400
            response = generate_zoom_url_validation_response(plain_token, zoom_secret)
            print(f"✅ Zoom URL validation challenge responded")
            return jsonify(response), 200

        # フィーチャーフラグチェック（url_validation以外のイベント）
        if os.environ.get("ENABLE_ZOOM_WEBHOOK", "").lower() not in ("true", "1"):
            return jsonify({"status": "disabled", "message": "Zoom webhook is disabled"}), 200

        # recording.completed のみ処理
        if event_type != "recording.completed":
            return jsonify({"status": "ok", "message": f"Event '{event_type}' acknowledged"}), 200

        # Risk 4: 即座に200を返してZoomのタイムアウトを防ぐ（非同期分離）
        # Zoomは応答が5秒を超えるとリトライを繰り返す。
        # 議事録生成（VTT取得+LLM）は2〜5分かかるためバックグラウンドで実行する。
        # Risk 1（指数バックオフ3回: 30s+60s+120s）でVTT未準備も自己解決するため
        # 503リトライ誘発は不要。
        payload = data.get("payload", {})

        from handlers.zoom_webhook_handler import handle_zoom_webhook_event
        from infra.db import get_pool
        from infra.chatwork_api import send_chatwork_message

        # main.py の get_ai_response_raw を参照（遅延インポートで循環参照回避）
        from main import get_ai_response_raw, _ORGANIZATION_ID

        # DEFAULT_ADMIN_DM_ROOM_ID は lib.admin_config から取得
        try:
            from lib.admin_config import DEFAULT_ADMIN_DM_ROOM_ID
        except ImportError:
            DEFAULT_ADMIN_DM_ROOM_ID = None

        pool = get_pool()
        get_ai_func = get_ai_response_raw

        # recording_filesのタイプをデバッグ出力
        _rf = payload.get("object", {}).get("recording_files", [])
        logger.debug("recording_files types: %s", [f.get("file_type") for f in _rf])

        def _run_zoom_processing():
            """バックグラウンドで議事録生成を実行するスレッドターゲット"""
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(
                    handle_zoom_webhook_event(
                        event_type=event_type,
                        payload=payload,
                        pool=pool,
                        organization_id=_ORGANIZATION_ID,
                        get_ai_response_func=get_ai_func,
                    )
                )
                if result.success and result.message:
                    # 冪等性ガード: already_processedの場合は送信済みなのでスキップ
                    already_sent = (result.data or {}).get("already_processed", False)
                    if already_sent:
                        print(f"✅ Zoom議事録は既に処理済み（二重送信防止）: {result.data.get('meeting_id', 'unknown')}")
                    else:
                        room_id = (result.data or {}).get("room_id") or DEFAULT_ADMIN_DM_ROOM_ID
                        print(f"✅ Zoom議事録生成完了: {result.data.get('meeting_id', 'unknown')} → room={room_id}")
                        try:
                            sent = send_chatwork_message(room_id, result.message)
                            if sent:
                                print(f"✅ ChatWork送信完了: room={room_id}")
                            else:
                                print(f"⚠️ ChatWork送信失敗（API拒否 room={room_id}）。議事録はDB保存済み")
                        except Exception as send_err:
                            # ChatWork送信失敗は致命的ではない（議事録生成はDB保存済み）
                            print(f"⚠️ ChatWork送信失敗（議事録はDB保存済み）: {type(send_err).__name__}")
                else:
                    print(f"⚠️ Zoom議事録生成失敗: {result.message}")
            except Exception as bg_err:
                print(f"❌ Zoom議事録バックグラウンド処理エラー: {type(bg_err).__name__}: {bg_err}")
                import traceback as _tb
                _tb.print_exc()
            finally:
                loop.close()

        bg_thread = _bg_threading.Thread(target=_run_zoom_processing, daemon=True)
        bg_thread.start()
        print(f"✅ Zoom議事録処理をバックグラウンド開始: event={event_type}", flush=True)

        return jsonify({"status": "accepted", "message": "Processing started"}), 200

    except Exception as e:
        print(f"❌ Zoom webhook処理エラー: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": "Internal server error"}), 500
