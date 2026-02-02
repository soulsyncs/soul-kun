# lib/brain/session_orchestrator.py
"""
セッションオーケストレーター

マルチステップセッション（目標設定、アナウンス確認、確認待ち、タスク保留）を管理。
core.pyから分離して責務を明確化。

設計書: docs/13_brain_architecture.md
"""

import asyncio
import logging
import time
from datetime import datetime
from typing import Optional, Dict, Any, Callable, List

from lib.brain.models import (
    BrainContext,
    BrainResponse,
    UnderstandingResult,
    DecisionResult,
    HandlerResult,
    ConversationState,
    StateType,
)
from lib.brain.constants import CANCEL_MESSAGE

logger = logging.getLogger(__name__)


class SessionOrchestrator:
    """
    マルチステップセッションを管理するオーケストレーター

    責務:
    - 目標設定セッションの継続
    - アナウンス確認セッションの継続
    - 確認応答の処理
    - タスク保留セッションの継続
    """

    def __init__(
        self,
        handlers: Dict[str, Callable],
        state_manager,  # BrainStateManager
        understanding_func: Callable,  # _understand method
        decision_func: Callable,  # _decide method
        execution_func: Callable,  # _execute method
        is_cancel_func: Callable,  # _is_cancel_request method
        elapsed_ms_func: Callable,  # _elapsed_ms method
    ):
        """
        Args:
            handlers: アクション名 → ハンドラー関数のマッピング
            state_manager: BrainStateManager インスタンス
            understanding_func: 意図理解関数
            decision_func: 判断関数
            execution_func: 実行関数
            is_cancel_func: キャンセル判定関数
            elapsed_ms_func: 経過時間計算関数
        """
        self.handlers = handlers
        self.state_manager = state_manager
        self._understand = understanding_func
        self._decide = decision_func
        self._execute = execution_func
        self._is_cancel_request = is_cancel_func
        self._elapsed_ms = elapsed_ms_func

    async def continue_session(
        self,
        message: str,
        state: ConversationState,
        context: BrainContext,
        room_id: str,
        account_id: str,
        sender_name: str,
        start_time: float,
    ) -> BrainResponse:
        """
        マルチステップセッションを継続

        目標設定、アナウンス確認、確認待ち等のセッション中の処理。
        """
        logger.info(
            f"Continuing session: type={state.state_type.value}, "
            f"step={state.state_step}"
        )

        if state.state_type == StateType.GOAL_SETTING:
            return await self._continue_goal_setting(
                message, state, context, room_id, account_id, sender_name, start_time
            )
        elif state.state_type == StateType.ANNOUNCEMENT:
            return await self._continue_announcement(
                message, state, context, room_id, account_id, sender_name, start_time
            )
        elif state.state_type == StateType.CONFIRMATION:
            return await self._handle_confirmation_response(
                message, state, context, room_id, account_id, sender_name, start_time
            )
        elif state.state_type == StateType.TASK_PENDING:
            return await self._continue_task_pending(
                message, state, context, room_id, account_id, sender_name, start_time
            )
        else:
            # 未知の状態タイプの場合は状態をクリアして通常処理
            await self.state_manager.clear_state(room_id, account_id, "unknown_state_type")
            # 再帰的に呼び出し（通常処理に戻る）
            # Note: この場合、呼び出し元でprocess_messageを再実行する必要がある
            return BrainResponse(
                message="状態をリセットしたウル。もう一度教えてほしいウル🐺",
                action_taken="reset_unknown_state",
                success=True,
                state_changed=True,
                new_state="normal",
                total_time_ms=self._elapsed_ms(start_time),
            )

    async def _continue_goal_setting(
        self,
        message: str,
        state: ConversationState,
        context: BrainContext,
        room_id: str,
        account_id: str,
        sender_name: str,
        start_time: float,
    ) -> BrainResponse:
        """
        目標設定セッションを継続

        v10.39.2: 意図理解を追加
        - まずユーザーの意図を理解する
        - 目標設定の回答でなければ、セッションを中断して別の意図に対応
        - 中断されたセッションは記憶し、後でフォローアップ
        """
        # =====================================================
        # Step 1: 意図を理解する（脳の本質的な役割）
        # =====================================================
        try:
            understanding = await self._understand(message, context)
            inferred_action = understanding.intent if understanding else None

            # 別の意図かどうかを判断
            is_different_intent = self._is_different_intent_from_goal_setting(
                message, understanding, inferred_action
            )

            if is_different_intent:
                logger.info(f"🧠 目標設定中に別の意図を検出: action={inferred_action}")
                return await self._handle_interrupted_goal_setting(
                    message, state, context, understanding,
                    room_id, account_id, sender_name, start_time
                )
        except Exception as e:
            logger.warning(f"Goal setting intent understanding failed: {e}")
            # 意図理解に失敗した場合は従来通り継続

        # =====================================================
        # Step 2: 目標設定の回答として処理
        # =====================================================
        handler = self.handlers.get("continue_goal_setting")

        if handler:
            try:
                result = handler(
                    message,
                    room_id,
                    account_id,
                    sender_name,
                    state.state_data if state else {},
                )

                if asyncio.iscoroutine(result):
                    result = await result

                if isinstance(result, dict):
                    response_message = result.get("message", "")
                    success = result.get("success", True)
                    new_state = result.get("new_state")
                    state_changed = result.get("state_changed", False)

                    if new_state == "normal" or result.get("session_completed"):
                        await self.state_manager.clear_state(room_id, account_id, "goal_setting_completed")
                        state_changed = True

                    return BrainResponse(
                        message=response_message,
                        action_taken="continue_goal_setting",
                        success=success,
                        state_changed=state_changed,
                        new_state=new_state,
                        total_time_ms=self._elapsed_ms(start_time),
                    )
                elif isinstance(result, str):
                    return BrainResponse(
                        message=result,
                        action_taken="continue_goal_setting",
                        success=True,
                        total_time_ms=self._elapsed_ms(start_time),
                    )

            except Exception as e:
                logger.warning(f"Goal setting handler error: {e}")
                await self.state_manager.clear_state(room_id, account_id, "goal_setting_error")
                return BrainResponse(
                    message="目標設定の処理中にエラーが発生したウル... もう一度最初からお願いするウル🐺",
                    action_taken="continue_goal_setting",
                    success=False,
                    state_changed=True,
                    new_state="normal",
                    total_time_ms=self._elapsed_ms(start_time),
                )

        logger.warning("continue_goal_setting handler not registered, using fallback")
        return BrainResponse(
            message="目標設定を続けるウル🐺 今のステップは何だったかな...？",
            action_taken="continue_goal_setting",
            total_time_ms=self._elapsed_ms(start_time),
        )

    def _is_different_intent_from_goal_setting(
        self,
        message: str,
        understanding: Optional[UnderstandingResult],
        inferred_action: Optional[str],
    ) -> bool:
        """
        目標設定の回答ではなく、別の意図かどうかを判断

        v10.40.5: 判定順序を整理
        1. STOP_WORDSチェック（明示的中断のみ許可）
        2. goal_continuation_intentsチェック（継続）
        3. 短文継続ルール（20文字以下）
        4. 既存の意図判定ロジック

        Returns:
            True: 別の意図（セッションを中断すべき）
            False: 目標設定の回答として処理すべき
        """
        message_lower = message.lower().strip()

        # 1. STOP_WORDSチェック
        STOP_WORDS = [
            "やめる", "やめたい", "中断", "キャンセル",
            "終了", "一旦止めて", "別の話", "ストップ",
            "目標設定やめ", "目標やめ",
            "一覧", "表示して", "出して", "見せて",
            "違う", "そうじゃない", "登録じゃない", "新規じゃない",
            "整理", "削除", "修正", "相談",
        ]
        if any(word in message_lower for word in STOP_WORDS):
            logger.info(f"🛑 Stop word detected, allowing interruption: {message[:30]}")
            return True

        # 2. goal_continuation_intentsチェック
        goal_continuation_intents = [
            "feedback_request",
            "doubt_or_anxiety",
            "reflection",
            "clarification",
            "question",
            "confirm",
        ]
        if inferred_action in goal_continuation_intents:
            logger.debug(f"🔄 Goal continuation intent detected: {inferred_action}")
            return False

        # 3. 短文継続ルール
        if len(message.strip()) <= 20:
            logger.debug(f"🔄 Short message, continuing session: {message}")
            return False

        # 4. 既存の意図判定ロジック
        question_endings = ["?", "？"]
        question_words = [
            "何", "なに", "どこ", "いつ", "誰", "だれ",
            "どれ", "どの", "なぜ", "どうして", "どうやって",
            "ある？", "ありますか", "できる？", "できますか",
            "知ってる", "について",
        ]
        is_question = (
            any(message.endswith(q) for q in question_endings) or
            any(qw in message for qw in question_words)
        )

        other_action_keywords = [
            "タスク", "task", "やること", "宿題", "締め切り", "期限",
            "覚えて", "記憶", "メモ", "ナレッジ",
            "検索", "探して",
            "天気", "ニュース",
        ]
        has_other_action = any(kw in message for kw in other_action_keywords)

        goal_response_keywords = [
            "なりたい", "成長", "目指", "達成", "実現",
            "目標", "ゴール", "成果", "結果",
            "毎日", "毎週", "週に", "行動", "やる", "する",
            "はい", "うん", "そう", "OK", "わかった",
            "どう思う", "アドバイス", "教えて", "確認",
        ]
        is_goal_response = any(kw in message for kw in goal_response_keywords)

        goal_actions = [
            "goal_registration", "continue_goal_setting",
            "goal_progress_report", "goal_status_check",
            "goal_setting_start",
        ]
        is_goal_action = inferred_action in goal_actions if inferred_action else False
        if inferred_action and "goal" in inferred_action.lower():
            is_goal_action = True

        if is_question and not is_goal_response and len(message) > 30:
            return True

        if has_other_action and not is_goal_action and not is_goal_response:
            return True

        if inferred_action and not is_goal_action:
            non_goal_actions = [
                "chatwork_task_search", "chatwork_task_create",
                "query_knowledge", "save_memory", "query_memory",
                "announcement_create", "daily_reflection",
            ]
            if inferred_action in non_goal_actions:
                return True

        return False

    async def _handle_interrupted_goal_setting(
        self,
        message: str,
        state: ConversationState,
        context: BrainContext,
        understanding: Optional[UnderstandingResult],
        room_id: str,
        account_id: str,
        sender_name: str,
        start_time: float,
    ) -> BrainResponse:
        """
        目標設定セッションを中断し、別の意図に対応
        """
        try:
            current_step = state.state_step if state else "unknown"
            session_data = state.state_data if state else {}
            why_answer = session_data.get("why_answer", "")
            what_answer = session_data.get("what_answer", "")
            how_answer = session_data.get("how_answer", "")

            logger.info(
                f"🧠 目標設定を中断: step={current_step}, "
                f"why={bool(why_answer)}, what={bool(what_answer)}, how={bool(how_answer)}"
            )

            interrupted_session = {
                "interrupted": True,
                "interrupted_at": datetime.now().isoformat(),
                "current_step": current_step,
                "why_answer": why_answer,
                "what_answer": what_answer,
                "how_answer": how_answer,
                "reference_id": state.reference_id if state else None,
            }

            interrupt_handler = self.handlers.get("interrupt_goal_setting")
            if interrupt_handler:
                try:
                    interrupt_handler(room_id, account_id, interrupted_session)
                except Exception as e:
                    logger.warning(f"Failed to save interrupted session: {e}")

            await self.state_manager.clear_state(room_id, account_id, "goal_setting_interrupted")

            new_context = BrainContext(
                organization_id=context.organization_id,
                room_id=room_id,
                sender_name=sender_name,
                sender_account_id=account_id,
                recent_conversation=context.recent_conversation,
                user_preferences=context.user_preferences,
                person_info=context.person_info,
                recent_tasks=context.recent_tasks,
            )

            inferred_action = understanding.intent if understanding else "general_conversation"

            decision = await self._decide(understanding, new_context)
            if decision:
                result = await self._execute(decision, new_context, room_id, account_id, sender_name)
            else:
                result = await self._execute_general_conversation(
                    message, new_context, room_id, account_id, sender_name
                )

            original_message = result.message if result else ""
            progress_info = ""
            if why_answer:
                progress_info = "WHYまで"
            if what_answer:
                progress_info = "WHATまで"

            followup = (
                f"\n\n💡 ちなみに、さっきの目標設定は{progress_info}進んでいたウル。"
                f"続きをやりたいときは「目標設定の続き」と言ってくれれば再開できるウル🐺"
            ) if progress_info else (
                "\n\n💡 さっき始めた目標設定、また続きからやりたいときは「目標設定の続き」と言ってねウル🐺"
            )

            return BrainResponse(
                message=original_message + followup,
                action_taken=f"interrupted_goal_setting_then_{inferred_action}",
                success=True,
                state_changed=True,
                new_state="normal",
                total_time_ms=self._elapsed_ms(start_time),
                debug_info={
                    "interrupted_session": interrupted_session,
                    "original_action": inferred_action,
                },
            )

        except Exception as e:
            logger.error(f"Failed to handle interrupted goal setting: {e}")
            await self.state_manager.clear_state(room_id, account_id, "goal_setting_interrupt_error")
            return BrainResponse(
                message="分かったウル！他に何かあれば聞いてねウル🐺",
                action_taken="goal_setting_interrupted",
                success=True,
                state_changed=True,
                new_state="normal",
                total_time_ms=self._elapsed_ms(start_time),
            )

    async def _execute_general_conversation(
        self,
        message: str,
        context: BrainContext,
        room_id: str,
        account_id: str,
        sender_name: str,
    ) -> Optional[HandlerResult]:
        """通常会話を実行（ヘルパーメソッド）"""
        handler = self.handlers.get("general_conversation")
        if handler:
            try:
                result = await handler({}, room_id, account_id, sender_name, context)
                if isinstance(result, HandlerResult):
                    return result
                return HandlerResult(success=True, message=str(result) if result else "")
            except Exception as e:
                logger.warning(f"General conversation handler error: {e}")
        return None

    async def _continue_announcement(
        self,
        message: str,
        state: ConversationState,
        context: BrainContext,
        room_id: str,
        account_id: str,
        sender_name: str,
        start_time: float,
    ) -> BrainResponse:
        """アナウンス確認セッションを継続"""
        handler = self.handlers.get("continue_announcement")

        if handler:
            try:
                result = handler(
                    message,
                    room_id,
                    account_id,
                    sender_name,
                    state.state_data if state else {},
                )

                if asyncio.iscoroutine(result):
                    result = await result

                if isinstance(result, dict):
                    response_message = result.get("message", "")
                    success = result.get("success", True)
                    new_state = result.get("new_state")
                    state_changed = result.get("state_changed", False)

                    if new_state == "normal" or result.get("session_completed"):
                        await self.state_manager.clear_state(room_id, account_id, "announcement_completed")
                        state_changed = True

                    return BrainResponse(
                        message=response_message,
                        action_taken="continue_announcement",
                        success=success,
                        state_changed=state_changed,
                        new_state=new_state,
                        total_time_ms=self._elapsed_ms(start_time),
                    )
                elif isinstance(result, str):
                    return BrainResponse(
                        message=result,
                        action_taken="continue_announcement",
                        success=True,
                        total_time_ms=self._elapsed_ms(start_time),
                    )

            except Exception as e:
                logger.warning(f"Announcement handler error: {e}")
                await self.state_manager.clear_state(room_id, account_id, "announcement_error")
                return BrainResponse(
                    message="アナウンス処理中にエラーが発生したウル... もう一度お願いするウル🐺",
                    action_taken="continue_announcement",
                    success=False,
                    state_changed=True,
                    new_state="normal",
                    total_time_ms=self._elapsed_ms(start_time),
                )

        logger.warning("continue_announcement handler not registered, using fallback")
        return BrainResponse(
            message="アナウンスの確認を続けるウル🐺 送信してもいいかな...？",
            action_taken="continue_announcement",
            total_time_ms=self._elapsed_ms(start_time),
        )

    async def _handle_confirmation_response(
        self,
        message: str,
        state: ConversationState,
        context: BrainContext,
        room_id: str,
        account_id: str,
        sender_name: str,
        start_time: float,
    ) -> BrainResponse:
        """
        確認への応答を処理

        v10.43.3: P5対話フロー無限ループバグ修正
        """
        pending_action = state.state_data.get("pending_action")
        pending_params = state.state_data.get("pending_params", {})
        options = state.state_data.get("confirmation_options", [])
        retry_count = state.state_data.get("confirmation_retry_count", 0)

        # P5安全装置①: 空オプション検知
        if not options:
            logger.warning(
                f"[DIALOGUE_LOOP_DETECTED] Empty confirmation_options detected. "
                f"pending_action={pending_action}, room={room_id}"
            )
            await self.state_manager.clear_state(room_id, account_id, "empty_options_fallback")
            return BrainResponse(
                message="うまく質問を理解できなかったウル🙏\nもう一度普通の言葉で教えてほしいウル！",
                action_taken="confirmation_fallback",
                state_changed=True,
                new_state="normal",
                total_time_ms=self._elapsed_ms(start_time),
            )

        selected_option = self._parse_confirmation_response(message, options)

        if selected_option is None:
            # P5安全装置②: ループ検知
            new_retry_count = retry_count + 1

            if new_retry_count >= 2:
                logger.warning(
                    f"[DIALOGUE_LOOP_DETECTED] Max retries reached. "
                    f"retry_count={new_retry_count}, pending_action={pending_action}, room={room_id}"
                )
                await self.state_manager.clear_state(room_id, account_id, "loop_detected_fallback")
                return BrainResponse(
                    message="うまく質問を理解できなかったウル🙏\nもう一度普通の言葉で教えてほしいウル！",
                    action_taken="confirmation_loop_fallback",
                    state_changed=True,
                    new_state="normal",
                    debug_info={
                        "loop_detected": True,
                        "retry_count": new_retry_count,
                        "pending_action": pending_action,
                    },
                    total_time_ms=self._elapsed_ms(start_time),
                )

            await self.state_manager.update_step(
                room_id=room_id,
                user_id=account_id,
                new_step=state.state_step or "confirmation",
                additional_data={
                    "confirmation_retry_count": new_retry_count,
                    "last_confirmation_response": "番号で教えてほしいウル🐺",
                },
            )

            options_text = "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(options)])
            retry_message = f"🐺 以下から番号で選んでほしいウル！\n\n{options_text}\n\n（「やめる」でキャンセルできるウル）"

            return BrainResponse(
                message=retry_message,
                action_taken="confirmation_retry",
                awaiting_confirmation=True,
                debug_info={
                    "retry_count": new_retry_count,
                    "options_count": len(options),
                },
                total_time_ms=self._elapsed_ms(start_time),
            )

        if selected_option == "cancel":
            await self.state_manager.clear_state(room_id, account_id, "user_cancel_confirmation")
            return BrainResponse(
                message=CANCEL_MESSAGE,
                action_taken="cancel_confirmation",
                state_changed=True,
                new_state="normal",
                total_time_ms=self._elapsed_ms(start_time),
            )

        # 確認OK → アクションを実行
        await self.state_manager.clear_state(room_id, account_id, "confirmation_accepted")

        if isinstance(selected_option, int) and selected_option < len(options):
            pending_params["confirmed_option"] = options[selected_option]

        decision = DecisionResult(
            action=pending_action,
            params=pending_params,
            confidence=1.0,
        )

        result = await self._execute(
            decision=decision,
            context=context,
            room_id=room_id,
            account_id=account_id,
            sender_name=sender_name,
        )

        return BrainResponse(
            message=result.message,
            action_taken=pending_action,
            action_params=pending_params,
            success=result.success,
            suggestions=result.suggestions,
            state_changed=True,
            new_state="normal",
            total_time_ms=self._elapsed_ms(start_time),
        )

    def _parse_confirmation_response(
        self,
        message: str,
        options: List[str],
    ) -> Optional[Any]:
        """確認への応答を解析"""
        normalized = message.strip().lower()

        if self._is_cancel_request(message):
            return "cancel"

        try:
            num = int(normalized)
            if 1 <= num <= len(options):
                return num - 1
        except ValueError:
            pass

        positive_keywords = ["はい", "yes", "ok", "オーケー", "いいよ", "お願い", "うん"]
        if any(kw in normalized for kw in positive_keywords):
            return 0

        negative_keywords = ["いいえ", "no", "やめ", "違う", "ちがう"]
        if any(kw in normalized for kw in negative_keywords):
            return "cancel"

        return None

    async def _continue_task_pending(
        self,
        message: str,
        state: ConversationState,
        context: BrainContext,
        room_id: str,
        account_id: str,
        sender_name: str,
        start_time: float,
    ) -> BrainResponse:
        """タスク作成待ち状態を継続"""
        handler = self.handlers.get("continue_task_pending")

        if handler:
            try:
                result = handler(
                    message,
                    room_id,
                    account_id,
                    sender_name,
                    state.state_data if state else {},
                )

                if asyncio.iscoroutine(result):
                    result = await result

                if result is None:
                    missing_items = (state.state_data or {}).get("missing_items", [])
                    if "limit_date" in missing_items:
                        prompt = "タスクの期限を教えてほしいウル🐺（例: 明日、来週金曜、1/31）"
                    elif "task_body" in missing_items:
                        prompt = "タスクの内容を教えてほしいウル🐺"
                    elif "assigned_to" in missing_items:
                        prompt = "誰に担当してもらうか教えてほしいウル🐺"
                    else:
                        prompt = "タスクの詳細を教えてほしいウル🐺"

                    return BrainResponse(
                        message=prompt,
                        action_taken="continue_task_pending",
                        success=True,
                        total_time_ms=self._elapsed_ms(start_time),
                    )

                if isinstance(result, dict):
                    response_message = result.get("message", "")
                    success = result.get("success", True)
                    new_state = result.get("new_state")
                    state_changed = result.get("state_changed", False)

                    if new_state == "normal" or result.get("task_created"):
                        await self.state_manager.clear_state(room_id, account_id, "task_pending_completed")
                        state_changed = True

                    return BrainResponse(
                        message=response_message,
                        action_taken="continue_task_pending",
                        success=success,
                        state_changed=state_changed,
                        new_state=new_state,
                        total_time_ms=self._elapsed_ms(start_time),
                    )
                elif isinstance(result, str):
                    await self.state_manager.clear_state(room_id, account_id, "task_pending_completed")
                    return BrainResponse(
                        message=result,
                        action_taken="continue_task_pending",
                        success=True,
                        state_changed=True,
                        new_state="normal",
                        total_time_ms=self._elapsed_ms(start_time),
                    )

            except Exception as e:
                logger.warning(f"Task pending handler error: {e}")
                await self.state_manager.clear_state(room_id, account_id, "task_pending_error")
                return BrainResponse(
                    message="タスク作成中にエラーが発生したウル... もう一度最初からお願いするウル🐺",
                    action_taken="continue_task_pending",
                    success=False,
                    state_changed=True,
                    new_state="normal",
                    total_time_ms=self._elapsed_ms(start_time),
                )

        logger.warning("continue_task_pending handler not registered, using fallback")
        missing_items = (state.state_data or {}).get("missing_items", [])
        if "limit_date" in missing_items:
            prompt = "タスクの期限を教えてほしいウル🐺（例: 明日、来週金曜、1/31）"
        elif "task_body" in missing_items:
            prompt = "タスクの内容を教えてほしいウル🐺"
        elif "assigned_to" in missing_items:
            prompt = "誰に担当してもらうか教えてほしいウル🐺"
        else:
            prompt = "タスクの詳細を教えてほしいウル🐺"

        return BrainResponse(
            message=prompt,
            action_taken="continue_task_pending",
            total_time_ms=self._elapsed_ms(start_time),
        )
