"""
Zoom Webhook ルート

CLAUDE.md §1: 全入力は脳を通る（Zoom webhook は Brain-level LLMを使用）
セキュリティ: HMAC-SHA256署名検証必須（3AI合意）
リスク対策:
  - Risk 2: 録音検索ウィンドウ2日以内
  - Risk 4: バックグラウンドスレッドで即200応答（Zoomタイムアウト防止）
  - Risk 5: dedup_hash（SHA256）で二重処理防止

トリガーイベント:
  - recording.transcript_completed: VTT生成完了時（推奨）。即座に処理可能。
  - recording.completed: 後方互換性のため継続対応。VTTが存在する場合のみ処理。

複数アカウント対応（Phase Z2 ③）:
  - Zoomペイロードの account_id から zoom_accounts テーブルを参照
  - アカウント固有の webhook_secret_token で署名検証
  - 未登録アカウントはデフォルトシークレット（Secret Manager）にフォールバック

v1.0.0: main.py から分割（Phase 5）
v1.1.0: recording.transcript_completed 対応（3AI合意: 2026-02-20）
v1.2.0: 複数アカウント対応（3AI合意: 2026-02-20）
"""

import asyncio
import json
import logging
import os
import threading as _bg_threading

from flask import Blueprint, jsonify, request as flask_request

logger = logging.getLogger(__name__)

zoom_bp = Blueprint("zoom", __name__)


_SUPPORTED_RECORDING_EVENTS = frozenset({
    "recording.completed",
    "recording.transcript_completed",
})


def _notify_zoom_delivery_failure(
    meeting_id: str,
    title: str,
    target_room_id: str,
    error_detail: str,
    admin_dm_room_id: "str | None",
) -> None:
    """
    Zoom議事録のChatWork送信が全リトライ後も失敗したときに管理者へ通知する（Phase Z2 ⑦）。

    CLAUDE.md §9-2: 議事録本文・PII は含めない。
    メタ情報（会議ID・タイトル・送信先ルームID）のみを通知する。
    NOTE: error_detail は必ず type(e).__name__ か固定文字列のみ渡すこと。
          str(e) を渡すと内部パス・接続文字列が ChatWork に送信されるリスクがある。

    Args:
        meeting_id: 内部会議ID（meetings テーブル）
        title: 会議タイトル（UIに表示される）
        target_room_id: 届けようとしたChatWorkルームID
        error_detail: エラー種別文字列（例外クラス名またはAPI拒否詳細）
        admin_dm_room_id: 管理者DM通知先ルームID（None の場合は通知スキップ）
    """
    if not admin_dm_room_id:
        logger.warning(
            "_notify_zoom_delivery_failure: admin_dm_room_id not configured, skipping"
        )
        return

    message = (
        "[info][title]🚨 Zoom議事録の送信に失敗しましたウル[/title]\n"
        f"会議タイトル: {title}\n"
        f"送信先ルーム: {target_room_id}\n"
        f"会議ID: {meeting_id}\n"
        f"エラー: {error_detail}\n"
        "[hr]\n"
        "議事録はデータベースに保存されているウル。\n"
        "管理画面から確認・手動送信をお願いしたいウル🐺\n"
        "[/info]"
    )

    try:
        from infra.chatwork_api import send_chatwork_message
        sent = send_chatwork_message(admin_dm_room_id, message)
        if sent:
            logger.info(
                "Zoom delivery failure notified to admin: meeting_id=%s", meeting_id
            )
        else:
            logger.error(
                "Admin notification send rejected: meeting_id=%s", meeting_id
            )
    except Exception as notify_err:
        # 管理者通知失敗はログのみ（二次失敗でスタックしない）
        logger.error(
            "Admin notification error: %s (meeting_id=%s)",
            type(notify_err).__name__,
            meeting_id,
        )


def _get_webhook_secret_for_account(zoom_account_id: str | None) -> str | None:
    """
    Zoomの account_id に対応する webhook_secret_token をDBから取得する。

    フォールバック順:
    1. zoom_accounts テーブルの zoom_account_id が一致するアクティブなレコード
    2. Secret Manager の "zoom-webhook-secret-token"（既存のデフォルト）

    SECURITY NOTES:
    - account_idの読み取りはJSONパース後・署名検証前に行う（正しいsecretを選ぶため）。
      署名検証はこの関数が返したsecretで行うため、セキュリティは損なわれない。
    - org_idフィルタを省略する理由:
      (1) zoom_account_id はZoomが発行するグローバル一意IDのため、他組織のIDと衝突しない
      (2) 返値はシークレットのみで組織固有の業務データは含まない
      (3) 間違ったシークレットが返っても署名検証が失敗する（自己修正的）
      (4) webhookエンドポイントはユーザーセッションがなくorg_idを特定する手段がない
      → CLAUDE.md §1-1「読み取り専用・判断なし」相当の例外として意図的に省略。
    - INFRA RATE LIMIT REQUIRED: このDB lookupは署名検証前に実行されるため、
      未認証リクエストがDB hitを引き起こす。Cloud Run または Cloud Armor で
      /zoom-webhook への max-requests-per-second を必ず設定すること（推奨: 30req/s）。
    """
    if zoom_account_id:
        try:
            from infra.db import get_pool
            from sqlalchemy import text

            pool = get_pool()
            with pool.connect() as conn:
                row = conn.execute(
                    text("""
                        SELECT webhook_secret_token
                        FROM zoom_accounts
                        WHERE zoom_account_id = :aid
                          AND is_active = true
                        LIMIT 1
                    """),
                    {"aid": zoom_account_id},
                ).fetchone()
            if row and row[0]:
                logger.debug("zoom_accounts hit for account_id=%s", zoom_account_id[:8])
                return row[0]
        except Exception as lookup_err:
            # DB参照失敗時はデフォルトシークレットにフォールバック
            logger.warning(
                "zoom_accounts lookup failed, falling back to default secret: %s",
                type(lookup_err).__name__,
            )

    # フォールバック: 既存のSecret Manager（後方互換）
    from lib.secrets import get_secret_cached
    return get_secret_cached("zoom-webhook-secret-token")


@zoom_bp.route("/zoom-webhook", methods=["POST", "GET"])
def zoom_webhook():
    """
    Cloud Function: Zoom recording Webhook受信

    フロー:
    1. JSONパース → account_id 取得
    2. zoom_accounts テーブルから account_id に対応するシークレット取得
    3. 署名検証（x-zm-signature + x-zm-request-timestamp）
    4. endpoint.url_validation → チャレンジ応答
    5. recording.transcript_completed / recording.completed → 議事録自動生成パイプライン

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

        request_body = request.get_data()
        if not request_body:
            return jsonify({"status": "error", "message": "Empty body"}), 400

        timestamp = request.headers.get("x-zm-request-timestamp", "")
        signature = request.headers.get("x-zm-signature", "")

        # JSONパース（署名検証前にaccount_idを取得するため）
        try:
            data = json.loads(request_body)
        except json.JSONDecodeError:
            return jsonify({"status": "error", "message": "Invalid JSON"}), 400

        event_type = data.get("event", "")
        # Zoomペイロードのaccount_idでアカウント固有のシークレットを選択
        zoom_account_id = data.get("account_id")

        # 複数アカウント対応: zoom_account_id に対応するシークレットを取得
        zoom_secret = _get_webhook_secret_for_account(zoom_account_id)
        if not zoom_secret:
            print("❌ Zoom webhook secret token not configured")
            return jsonify({"status": "error", "message": "Server configuration error"}), 500

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

        # recording.completed / recording.transcript_completed のみ処理
        if event_type not in _SUPPORTED_RECORDING_EVENTS:
            return jsonify({"status": "ok", "message": f"Event '{event_type}' acknowledged"}), 200

        # Risk 4: 即座に200を返してZoomのタイムアウトを防ぐ（非同期分離）
        # Zoomは応答が5秒を超えるとリトライを繰り返す。
        # 議事録生成（VTT取得+LLM）はバックグラウンドで実行する。
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
                        _meeting_id = (result.data or {}).get("meeting_id", "unknown")
                        _title = (result.data or {}).get("title", "（タイトル不明）")
                        print(f"✅ Zoom議事録生成完了: {_meeting_id} → room={room_id}")
                        try:
                            sent = send_chatwork_message(room_id, result.message)
                            if sent:
                                print(f"✅ ChatWork送信完了: room={room_id}")
                            else:
                                # send_chatwork_message内部でリトライ済み（3回）でも失敗
                                print(
                                    f"❌ ChatWork送信失敗（リトライ後・API拒否）: room={room_id}"
                                    " 議事録はDB保存済み"
                                )
                                _notify_zoom_delivery_failure(
                                    meeting_id=_meeting_id,
                                    title=_title,
                                    target_room_id=str(room_id),
                                    error_detail="ChatWork API がリトライ3回後も送信を拒否",
                                    admin_dm_room_id=DEFAULT_ADMIN_DM_ROOM_ID,
                                )
                        except Exception as send_err:
                            # ChatWork送信例外（議事録はDB保存済み）
                            print(
                                f"❌ ChatWork送信例外（議事録はDB保存済み）: {type(send_err).__name__}"
                            )
                            _notify_zoom_delivery_failure(
                                meeting_id=_meeting_id,
                                title=_title,
                                target_room_id=str(room_id),
                                error_detail=type(send_err).__name__,
                                admin_dm_room_id=DEFAULT_ADMIN_DM_ROOM_ID,
                            )
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
