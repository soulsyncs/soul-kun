# lib/brain/handler_wrappers/bypass_handlers.py
"""
バイパスハンドラー

脳の意図理解を経由せず、特定の状態（pending）に対して直接処理を行うハンドラー。
"""

from typing import Dict, Any, Callable, Optional


def _bypass_handle_announcement(room_id, account_id, sender_name, message, context):
    """
    アナウンスのpending状態をバイパス処理

    v10.33.1: ハンドラー必須化により_get_announcement_handler()を使用
    """
    # 遅延インポート（循環参照回避）
    try:
        import sys
        main = sys.modules.get('main')
        if not main:
            print("⚠️ [バイパス] mainモジュールが見つかりません")
            return None

        _get_announcement_handler = getattr(main, '_get_announcement_handler', None)
        if not _get_announcement_handler:
            print("⚠️ [バイパス] _get_announcement_handler が見つかりません")
            return None

        handler = _get_announcement_handler()
        if not handler:
            return None

        # pending announcementを確認
        pending = handler._get_pending_announcement(room_id, account_id)
        if not pending:
            return None

        # フォローアップ処理
        response = handler.handle_announcement_request(
            params={"raw_message": message},
            room_id=room_id,
            account_id=account_id,
            sender_name=sender_name,
        )

        if response is None:
            return None

        return response

    except Exception as e:
        print(f"❌ [バイパス] announcement エラー: {e}")
        return None


async def _bypass_handle_meeting_audio(message, room_id, account_id, sender_name, context):
    """
    会議音声ファイルの文字起こしバイパスハンドラー

    Phase C: ChatWork [download:FILE_ID] → 音声ダウンロード → 文字起こし
    音声バイナリはbypass_contextに前処理済みで格納されている。
    """
    import logging
    logger = logging.getLogger(__name__)

    try:
        audio_data = context.get("meeting_audio_data")
        audio_filename = context.get("meeting_audio_filename", "audio.mp3")

        if not audio_data:
            return None  # 音声データなし → 通常処理へフォールスルー

        import sys
        main = sys.modules.get("main")
        if not main:
            logger.warning("[bypass] main module not found for meeting audio")
            return None

        _get_capability_bridge = getattr(main, "_get_capability_bridge", None)
        if not _get_capability_bridge:
            return None

        bridge = _get_capability_bridge()
        if not bridge:
            return None

        result = await bridge._handle_meeting_transcription(
            room_id=str(room_id),
            account_id=str(account_id),
            sender_name=sender_name,
            params={
                "audio_data": audio_data,
                "meeting_title": audio_filename,
            },
        )

        if result and result.success:
            logger.info("Meeting transcription completed via bypass")
            return result.message

        logger.warning(
            "Meeting transcription failed: success=%s",
            getattr(result, "success", None),
        )
        return getattr(result, "message", None)

    except Exception as e:
        logger.error("Meeting audio bypass error: %s", type(e).__name__)
        return None


async def _bypass_handle_task_pending(
    message: str,
    room_id: str,
    account_id: str,
    sender_name: str,
    context: dict = None,
) -> Optional[str]:
    """
    タスク作成待ち状態のバイパス処理（v10.56.14追加）

    pending_taskがある場合に呼び出され、不足情報を補完してタスク作成を継続。
    """
    try:
        import sys
        main = sys.modules.get('main')
        if not main:
            print("⚠️ [バイパス] mainモジュールが見つかりません")
            return None

        # pending_taskを取得
        get_pending_task = getattr(main, 'get_pending_task', None)
        handle_pending_task_followup = getattr(main, 'handle_pending_task_followup', None)

        if not get_pending_task or not handle_pending_task_followup:
            print("⚠️ [バイパス] task関連関数が見つかりません")
            return None

        # pending_taskを確認
        pending = get_pending_task(room_id, account_id)
        if not pending:
            print("📋 [バイパス] pending_taskなし、通常処理へ")
            return None

        print(f"📋 [バイパス] pending_task発見: {pending.get('missing_items', [])}")

        # フォローアップ処理
        response = handle_pending_task_followup(message, room_id, account_id, sender_name)

        if response is None:
            # 補完できなかった場合、不足項目を再度質問
            missing_items = pending.get("missing_items", [])
            if "task_body" in missing_items:
                return "何のタスクか教えてウル！🐺"
            elif "assigned_to" in missing_items:
                return "誰に依頼するか教えてウル！🐺"
            elif "limit_date" in missing_items:
                return "期限はいつにするウル？（例: 12/27、明日、来週金曜日）🐺"
            else:
                return "タスクの詳細を教えてウル！🐺"

        return response

    except Exception as e:
        print(f"❌ [バイパス] task_pending エラー: {e}")
        return None


async def _bypass_handle_image_analysis(message, room_id, account_id, sender_name, context):
    """
    画像解析バイパスハンドラー（Telegram / ChatWork 両対応）

    bypass_contextにはfile_idとimage_source（"telegram" or "chatwork"）が格納されている。
    このハンドラー内で非同期にダウンロード→Vision API解析を実行し、
    解析結果テキストを直接返す（process_message再帰呼び出しなし）。

    音声処理(_bypass_handle_meeting_audio)と同じパターン:
    バイパスハンドラー → 機能モジュール呼び出し → 結果を返す
    """
    import logging
    import asyncio
    logger = logging.getLogger(__name__)

    try:
        image_file_id = context.get("image_file_id")
        if not image_file_id:
            return None

        image_source = context.get("image_source", "telegram")

        # Step 1: プラットフォームに応じて非同期でファイルをダウンロード
        if image_source == "chatwork":
            image_room_id = context.get("image_room_id", str(room_id))
            from infra.chatwork_api import download_chatwork_file
            file_bytes, _ = await asyncio.to_thread(
                download_chatwork_file, image_room_id, image_file_id,
            )
            image_data = file_bytes
        else:
            from lib.channels.telegram_adapter import download_telegram_file
            image_data = await asyncio.to_thread(download_telegram_file, image_file_id)

        if not image_data:
            logger.warning(
                "Image download failed: source=%s file_id=%s",
                image_source, str(image_file_id)[:20],
            )
            return None

        logger.info(
            "Image downloaded in bypass handler: source=%s size=%d",
            image_source, len(image_data),
        )

        # Step 2: ユーザーの指示を抽出（プレースホルダーを除去）
        instruction = message.strip() if message and message.strip() else ""
        for tag in ["[写真を送信]", "[動画を送信]", "[ファイルを送信]", "[音声メッセージを送信]"]:
            instruction = instruction.replace(tag, "").strip()
        if not instruction:
            instruction = "この画像の内容を詳しく教えてください。"

        # Step 3: Vision APIで画像を解析
        from lib.capabilities.multimodal.base import VisionAPIClient

        vision_client = VisionAPIClient()
        vision_result = await vision_client.analyze_image(
            image_data=image_data,
            prompt=instruction,
        )

        if not vision_result or not vision_result.get("content"):
            logger.warning("Vision API returned empty result")
            return None

        vision_content = vision_result["content"]
        logger.info("Image analysis completed via bypass handler: source=%s", image_source)

        # Step 4: 解析結果を含む応答テキストを返す（Brainの再帰呼び出しなし）
        return (
            f"🐺 画像を確認したウル！\n\n"
            f"📷 **画像解析結果:**\n{vision_content}\n\n"
            f"（ユーザーの質問: {instruction}）"
        )

    except Exception as e:
        logger.error("Image analysis bypass error: %s", type(e).__name__, exc_info=True)
        return None


def build_bypass_handlers() -> Dict[str, Callable]:
    """
    バイパスハンドラーのマッピングを構築

    v10.39.3: goal_sessionバイパスを削除
    - 脳の意図理解を通すため、バイパスを使わない
    - 脳のcore.py _continue_goal_setting() で意図を理解してから処理

    Returns:
        dict: バイパスタイプ -> ハンドラー関数のマッピング
    """
    return {
        # v10.39.3: goal_session バイパスを削除（脳が意図理解してからハンドラーを呼ぶ）
        # "goal_session": _bypass_handle_goal_session,
        "announcement_pending": _bypass_handle_announcement,
        "meeting_audio": _bypass_handle_meeting_audio,
        "image_analysis": _bypass_handle_image_analysis,
        # v10.56.14: task_pending バイパスを追加（pending_taskがある場合の処理）
        "task_pending": _bypass_handle_task_pending,
        # "local_command" は既存の脳内処理で対応可能
    }
