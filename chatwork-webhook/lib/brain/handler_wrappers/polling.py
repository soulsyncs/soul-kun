# lib/brain/handler_wrappers/polling.py
"""
ポーリング処理ヘルパー関数

v10.40.3: check_reply_messages から抽出
"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


def validate_polling_message(msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    ポーリングメッセージのバリデーションとフィールド抽出

    v10.40.3: check_reply_messages から抽出

    Args:
        msg: ChatWork APIから取得したメッセージ辞書

    Returns:
        バリデーション済みデータ辞書、または無効な場合None
        {
            "message_id": str,
            "body": str,
            "account_id": str or None,
            "sender_name": str,
            "send_time": int or None,
        }
    """
    if not isinstance(msg, dict):
        print(f"⚠️ 不正なメッセージデータ型: {type(msg)}")
        return None

    message_id = msg.get("message_id")
    if message_id is None:
        print(f"⚠️ message_idがNone")
        return None

    body = msg.get("body")
    if body is None:
        body = ""
        logger.debug("[バリデーション] bodyがNone")
    if not isinstance(body, str):
        logger.debug(f"[バリデーション] bodyが文字列ではない: type={type(body)}")
        body = str(body) if body else ""

    account_data = msg.get("account")
    if account_data is None or not isinstance(account_data, dict):
        logger.debug("[バリデーション] accountデータが不正")
        account_id = None
        sender_name = "ゲスト"
    else:
        account_id = account_data.get("account_id")
        sender_name = account_data.get("name", "ゲスト")

    send_time = msg.get("send_time")

    # デバッグログ（PII除去）
    logger.debug(f"[バリデーション] メッセージチェック: body_len={len(body)}")

    return {
        "message_id": message_id,
        "body": body,
        "account_id": account_id,
        "sender_name": sender_name,
        "send_time": send_time,
    }


def should_skip_polling_message(
    data: Dict[str, Any],
    five_minutes_ago: int,
    my_account_id: str,
) -> bool:
    """
    ポーリングメッセージをスキップすべきかチェック

    v10.40.3: check_reply_messages から抽出

    Args:
        data: validate_polling_messageの戻り値
        five_minutes_ago: 5分前のタイムスタンプ
        my_account_id: 自分のアカウントID

    Returns:
        スキップすべき場合True
    """
    import sys
    main = sys.modules.get('main')
    if not main:
        print("⚠️ [ポーリング] mainモジュールが見つかりません")
        return True

    is_mention_or_reply_to_soulkun = getattr(main, 'is_mention_or_reply_to_soulkun', None)
    should_ignore_toall = getattr(main, 'should_ignore_toall', None)
    is_processed = getattr(main, 'is_processed', None)

    message_id = data["message_id"]
    body = data["body"]
    account_id = data["account_id"]
    send_time = data["send_time"]

    # メンション/返信チェック
    try:
        is_mention_or_reply = is_mention_or_reply_to_soulkun(body) if body and is_mention_or_reply_to_soulkun else False
        print(f"   is_mention_or_reply: {is_mention_or_reply}")
    except Exception as e:
        print(f"   ❌ is_mention_or_reply_to_soulkun エラー: {e}")
        is_mention_or_reply = False

    # 5分以内のメッセージのみ処理
    if send_time is not None:
        try:
            if int(send_time) < five_minutes_ago:
                return True
        except (ValueError, TypeError) as e:
            print(f"⚠️ send_time変換エラー: {send_time}, error={e}")

    # 自分自身のメッセージを無視
    if account_id is not None and str(account_id) == my_account_id:
        return True

    # オールメンション（toall）の判定
    if should_ignore_toall and should_ignore_toall(body):
        print(f"   ⏭️ オールメンション（toall）のみのため無視")
        return True

    # メンションまたは返信を検出
    if not is_mention_or_reply:
        return True

    # 処理済みならスキップ
    try:
        if is_processed and is_processed(message_id):
            logger.debug("[スキップ判定] すでに処理済み")
            return True
    except Exception as e:
        logger.debug(f"[スキップ判定] 処理済みチェックエラー（続行）: {e}")

    return False


def process_polling_message(
    room_id: str,
    data: Dict[str, Any],
) -> int:
    """
    検出されたポーリングメッセージを処理

    v10.40.3: check_reply_messages から抽出
    Brain統合でメッセージを処理し、応答を送信

    Args:
        room_id: ルームID
        data: validate_polling_messageの戻り値

    Returns:
        処理した場合1、スキップした場合0
    """
    import sys
    from datetime import datetime

    main = sys.modules.get('main')
    if not main:
        print("⚠️ [ポーリング] mainモジュールが見つかりません")
        return 0

    # main.py関数の取得
    mark_as_processed = getattr(main, 'mark_as_processed', None)
    save_room_message = getattr(main, 'save_room_message', None)
    clean_chatwork_message = getattr(main, 'clean_chatwork_message', None)
    handle_pending_task_followup = getattr(main, 'handle_pending_task_followup', None)
    match_local_command = getattr(main, 'match_local_command', None)
    execute_local_command = getattr(main, 'execute_local_command', None)
    _get_brain_integration = getattr(main, '_get_brain_integration', None)
    _build_bypass_context = getattr(main, '_build_bypass_context', None)
    build_bypass_handlers_fn = getattr(main, 'build_bypass_handlers', None)
    send_chatwork_message = getattr(main, 'send_chatwork_message', None)
    USE_BRAIN_ARCHITECTURE = getattr(main, 'USE_BRAIN_ARCHITECTURE', False)
    JST = getattr(main, 'JST', None)

    message_id = data["message_id"]
    body = data["body"]
    account_id = data["account_id"]
    sender_name = data["sender_name"]
    send_time = data["send_time"]

    logger.debug("[ポーリング] メッセージ検出、処理開始")

    # ★★★ 2重処理防止: 即座にマーク ★★★
    if mark_as_processed:
        mark_as_processed(message_id, room_id)
        logger.debug("[ポーリング] 処理開始マーク完了")

    # メッセージをDBに保存
    try:
        if save_room_message and JST:
            save_room_message(
                room_id=room_id,
                message_id=message_id,
                account_id=account_id,
                account_name=sender_name,
                body=body,
                send_time=datetime.fromtimestamp(send_time, tz=JST) if send_time else None
            )
    except Exception as e:
        print(f"⚠️ メッセージ保存エラー（続行）: {e}")

    # メッセージをクリーニング
    try:
        clean_message = clean_chatwork_message(body) if body and clean_chatwork_message else ""
    except Exception as e:
        print(f"⚠️ メッセージクリーニングエラー: {e}")
        clean_message = body

    if not clean_message:
        return 1

    try:
        # ★★★ pending_taskのフォローアップを最初にチェック ★★★
        if handle_pending_task_followup:
            pending_response = handle_pending_task_followup(clean_message, room_id, account_id, sender_name)
            if pending_response:
                print(f"📋 pending_taskのフォローアップを処理")
                if send_chatwork_message:
                    send_chatwork_message(room_id, pending_response, None, False)
                return 1

        # =====================================================
        # v6.9.1: ローカルコマンド判定（API制限対策）
        # =====================================================
        if match_local_command and execute_local_command:
            local_action, local_groups = match_local_command(clean_message)
            if local_action:
                print(f"🏠 ローカルコマンド検出: {local_action}")
                local_response = execute_local_command(
                    local_action, local_groups,
                    account_id, sender_name, room_id
                )
                if local_response and send_chatwork_message:
                    send_chatwork_message(room_id, local_response, None, False)
                    return 1

        # =====================================================
        # v10.40: Brain統合（ai_commander + execute_action削除）
        # 設計原則「全入力は脳を通る」に準拠
        # =====================================================
        if USE_BRAIN_ARCHITECTURE and _get_brain_integration:
            try:
                integration = _get_brain_integration()
                if integration and integration.is_brain_enabled():
                    bypass_context = _build_bypass_context(room_id, account_id) if _build_bypass_context else {}
                    bypass_handlers = build_bypass_handlers_fn() if build_bypass_handlers_fn else {}

                    import asyncio
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        result = loop.run_until_complete(
                            integration.process_message(
                                message=clean_message,
                                room_id=room_id,
                                account_id=account_id,
                                sender_name=sender_name,
                                fallback_func=None,
                                bypass_context=bypass_context,
                                bypass_handlers=bypass_handlers,
                            )
                        )
                    finally:
                        loop.close()

                    if result and result.success and result.message:
                        logger.debug(f"[ポーリング] Brain応答成功: brain={result.used_brain}, time={result.processing_time_ms}ms")
                        if send_chatwork_message:
                            send_chatwork_message(room_id, result.message, None, False)
                    else:
                        logger.debug("[ポーリング] Brain処理が応答なし")
                else:
                    logger.debug("[ポーリング] Brain統合が無効")
            except Exception as brain_e:
                logger.error(f"[ポーリング] Brain処理エラー: {brain_e}")
                import traceback
                traceback.print_exc()
        else:
            logger.debug("[ポーリング] USE_BRAIN_ARCHITECTURE=false, スキップ")

        return 1

    except Exception as e:
        logger.error(f"[ポーリング] メッセージ処理エラー: {e}")
        import traceback
        traceback.print_exc()
        return 0


def process_polling_room(
    room: Dict[str, Any],
    five_minutes_ago: int,
    my_account_id: str,
) -> Dict[str, int]:
    """
    ポーリングで1つのルームを処理

    v10.40.3: check_reply_messages から抽出

    Args:
        room: ルーム情報辞書
        five_minutes_ago: 5分前のタイムスタンプ
        my_account_id: 自分のアカウントID

    Returns:
        カウント辞書 {
            "processed_count": int,
            "skipped_my": int,
            "processed_rooms": int,
            "error_rooms": int,
            "skipped_messages": int,
        }
    """
    import sys

    main = sys.modules.get('main')
    if not main:
        print("⚠️ [ポーリング] mainモジュールが見つかりません")
        return {"processed_count": 0, "skipped_my": 0, "processed_rooms": 0, "error_rooms": 1, "skipped_messages": 0}

    get_room_messages = getattr(main, 'get_room_messages', None)

    counts = {
        "processed_count": 0,
        "skipped_my": 0,
        "processed_rooms": 0,
        "error_rooms": 0,
        "skipped_messages": 0,
    }

    room_id = None

    try:
        # ルームデータの検証
        if not isinstance(room, dict):
            print(f"⚠️ 不正なルームデータ型: {type(room)}")
            counts["error_rooms"] += 1
            return counts

        room_id = room.get("room_id")
        room_type = room.get("type")
        room_name = room.get("name", "不明")

        # room_idの検証
        if room_id is None:
            logger.debug("[ポーリング] room_idがNone")
            counts["error_rooms"] += 1
            return counts

        logger.debug(f"[ポーリング] ルームチェック開始: type={room_type}")

        # マイチャットをスキップ
        if room_type == "my":
            counts["skipped_my"] += 1
            logger.debug("[ポーリング] マイチャットをスキップ")
            return counts

        counts["processed_rooms"] += 1

        # メッセージを取得
        logger.debug("[ポーリング] get_room_messages呼び出し")

        try:
            messages = get_room_messages(room_id, force=True) if get_room_messages else []
        except Exception as e:
            logger.error(f"[ポーリング] メッセージ取得エラー: {e}")
            counts["error_rooms"] += 1
            return counts

        # messagesの検証
        if messages is None:
            logger.debug("[ポーリング] messagesがNone")
            messages = []

        if not isinstance(messages, list):
            logger.debug(f"[ポーリング] messagesが不正な型: {type(messages)}")
            messages = []

        logger.debug(f"[ポーリング] {len(messages)}件のメッセージを取得")

        # メッセージがない場合はスキップ
        if not messages:
            return counts

        for msg in messages:
            try:
                # バリデーション
                data = validate_polling_message(msg)
                if data is None:
                    counts["skipped_messages"] += 1
                    continue

                # スキップ判定
                if should_skip_polling_message(data, five_minutes_ago, my_account_id):
                    continue

                # 処理実行
                result = process_polling_message(room_id, data)
                counts["processed_count"] += result

            except Exception as e:
                logger.error(f"[ポーリング] メッセージ処理中に予期しないエラー: {e}")
                import traceback
                traceback.print_exc()
                counts["skipped_messages"] += 1
                continue

    except Exception as e:
        counts["error_rooms"] += 1
        logger.error(f"[ポーリング] ルーム処理中にエラー: {e}")
        import traceback
        traceback.print_exc()

    return counts
