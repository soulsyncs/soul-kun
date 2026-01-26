# lib/brain/core.py
"""
ソウルくんの脳 - コアクラス

このファイルには、脳の中央処理装置（SoulkunBrain）を定義します。
全てのユーザー入力は、このクラスのprocess_message()メソッドを通じて処理されます。

設計書: docs/13_brain_architecture.md

【7つの鉄則】
1. 全ての入力は脳を通る（バイパスルート禁止）
2. 脳は全ての記憶にアクセスできる
3. 脳が判断し、機能は実行するだけ
4. 機能拡張しても脳の構造は変わらない
5. 確認は脳の責務
6. 状態管理は脳が統一管理
7. 速度より正確性を優先
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Callable, Tuple

from lib.brain.models import (
    BrainContext,
    BrainResponse,
    UnderstandingResult,
    DecisionResult,
    HandlerResult,
    ConversationState,
    ConfirmationRequest,
    ActionCandidate,
    StateType,
    ConfidenceLevel,
    ConversationMessage,
)

from lib.brain.constants import (
    CANCEL_KEYWORDS,
    CONFIRMATION_THRESHOLD,
    AUTO_EXECUTE_THRESHOLD,
    SESSION_TIMEOUT_MINUTES,
    DANGEROUS_ACTIONS,
    CANCEL_MESSAGE,
    ERROR_MESSAGE,
    UNDERSTANDING_TIMEOUT_SECONDS,
    DECISION_TIMEOUT_SECONDS,
    EXECUTION_TIMEOUT_SECONDS,
    SAVE_DECISION_LOGS,
)

from lib.brain.exceptions import (
    BrainError,
    UnderstandingError,
    DecisionError,
    ExecutionError,
    StateError,
    MemoryAccessError,
    HandlerNotFoundError,
    HandlerTimeoutError,
)

logger = logging.getLogger(__name__)


class SoulkunBrain:
    """
    ソウルくんの脳（中央処理装置）

    全てのユーザー入力を受け取り、記憶を参照し、意図を理解し、
    適切な機能を選択して実行する。

    使用例:
        brain = SoulkunBrain(pool=db_pool, org_id="org_soulsyncs")
        response = await brain.process_message(
            message="自分のタスク教えて",
            room_id="123456",
            account_id="7890",
            sender_name="菊地"
        )
    """

    def __init__(
        self,
        pool,
        org_id: str,
        handlers: Optional[Dict[str, Callable]] = None,
        capabilities: Optional[Dict[str, Dict]] = None,
        get_ai_response_func: Optional[Callable] = None,
    ):
        """
        Args:
            pool: データベース接続プール
            org_id: 組織ID
            handlers: アクション名 → ハンドラー関数のマッピング
            capabilities: SYSTEM_CAPABILITIES（機能カタログ）
            get_ai_response_func: AI応答生成関数
        """
        self.pool = pool
        self.org_id = org_id
        self.handlers = handlers or {}
        self.capabilities = capabilities or {}
        self.get_ai_response = get_ai_response_func

        # 内部状態
        self._initialized = False

        logger.info(f"SoulkunBrain initialized for org_id={org_id}")

    # =========================================================================
    # メインエントリーポイント
    # =========================================================================

    async def process_message(
        self,
        message: str,
        room_id: str,
        account_id: str,
        sender_name: str,
    ) -> BrainResponse:
        """
        メッセージを処理して応答を返す

        これが脳の唯一のエントリーポイント。
        全ての入力はここを通る。

        Args:
            message: ユーザーのメッセージ
            room_id: ChatWorkルームID
            account_id: ユーザーのアカウントID
            sender_name: 送信者名

        Returns:
            BrainResponse: 処理結果
        """
        start_time = time.time()

        try:
            logger.info(
                f"🧠 Brain processing: room={room_id}, user={sender_name}, "
                f"message={message[:50]}..."
            )

            # 1. 記憶層: コンテキスト取得
            context = await self._get_context(
                room_id=room_id,
                user_id=account_id,
                sender_name=sender_name,
            )

            # 2. 状態チェック: マルチステップセッション中？
            current_state = await self._get_current_state(room_id, account_id)

            # 2.1 キャンセルリクエスト？
            if self._is_cancel_request(message) and current_state and current_state.is_active:
                await self._clear_state(room_id, account_id, "user_cancel")
                return BrainResponse(
                    message=CANCEL_MESSAGE,
                    action_taken="cancel_session",
                    success=True,
                    state_changed=True,
                    new_state="normal",
                    total_time_ms=self._elapsed_ms(start_time),
                )

            # 2.2 セッション中なら、そのフローを継続
            if current_state and current_state.is_active:
                return await self._continue_session(
                    message=message,
                    state=current_state,
                    context=context,
                    room_id=room_id,
                    account_id=account_id,
                    sender_name=sender_name,
                    start_time=start_time,
                )

            # 3. 理解層: 意図を推論
            understanding = await self._understand(message, context)

            # 4. 判断層: アクションを決定
            decision = await self._decide(understanding, context)

            # 4.1 確認が必要？
            if decision.needs_confirmation:
                # 確認状態に遷移
                await self._transition_to_state(
                    room_id=room_id,
                    user_id=account_id,
                    state_type=StateType.CONFIRMATION,
                    data={
                        "pending_action": decision.action,
                        "pending_params": decision.params,
                        "confirmation_options": decision.confirmation_options,
                        "confirmation_question": decision.confirmation_question,
                    },
                    timeout_minutes=5,
                )
                return BrainResponse(
                    message=decision.confirmation_question or "確認させてほしいウル🐺",
                    action_taken="request_confirmation",
                    success=True,
                    awaiting_confirmation=True,
                    state_changed=True,
                    new_state="confirmation",
                    debug_info={
                        "pending_action": decision.action,
                        "confidence": decision.confidence,
                    },
                    total_time_ms=self._elapsed_ms(start_time),
                )

            # 5. 実行層: アクションを実行
            result = await self._execute(
                decision=decision,
                context=context,
                room_id=room_id,
                account_id=account_id,
                sender_name=sender_name,
            )

            # 6. 記憶更新（非同期で実行、エラーは無視）
            asyncio.create_task(
                self._update_memory_safely(message, result, context, account_id)
            )

            # 7. 判断ログ記録（非同期で実行）
            if SAVE_DECISION_LOGS:
                asyncio.create_task(
                    self._log_decision_safely(
                        message, understanding, decision, result, room_id, account_id
                    )
                )

            return BrainResponse(
                message=result.message,
                action_taken=decision.action,
                action_params=decision.params,
                success=result.success,
                suggestions=result.suggestions,
                state_changed=result.update_state is not None,
                debug_info={
                    "understanding": {
                        "intent": understanding.intent,
                        "confidence": understanding.intent_confidence,
                    },
                    "decision": {
                        "action": decision.action,
                        "confidence": decision.confidence,
                    },
                },
                total_time_ms=self._elapsed_ms(start_time),
            )

        except BrainError as e:
            logger.error(f"Brain error: {e.to_dict()}")
            return BrainResponse(
                message=ERROR_MESSAGE,
                action_taken="error",
                success=False,
                debug_info={"error": e.to_dict()},
                total_time_ms=self._elapsed_ms(start_time),
            )
        except Exception as e:
            logger.exception(f"Unexpected error in brain: {e}")
            return BrainResponse(
                message=ERROR_MESSAGE,
                action_taken="error",
                success=False,
                debug_info={"error": str(e)},
                total_time_ms=self._elapsed_ms(start_time),
            )

    # =========================================================================
    # 記憶層
    # =========================================================================

    async def _get_context(
        self,
        room_id: str,
        user_id: str,
        sender_name: str,
    ) -> BrainContext:
        """
        脳が判断に必要な全ての記憶を取得

        複数の記憶ソースから並列で取得し、統合したコンテキストを返す。
        """
        context = BrainContext(
            organization_id=self.org_id,
            room_id=room_id,
            sender_name=sender_name,
            sender_account_id=user_id,
            timestamp=datetime.now(),
        )

        try:
            # 並列で記憶を取得（エラーは個別に処理）
            results = await asyncio.gather(
                self._get_recent_conversation(room_id, user_id),
                self._get_conversation_summary(user_id),
                self._get_user_preferences(user_id),
                self._get_person_info(),
                self._get_recent_tasks(user_id),
                self._get_active_goals(user_id),
                self._get_insights(),
                return_exceptions=True,
            )

            # 結果を統合
            if not isinstance(results[0], Exception):
                context.recent_conversation = results[0]
            if not isinstance(results[1], Exception):
                context.conversation_summary = results[1]
            if not isinstance(results[2], Exception):
                context.user_preferences = results[2]
            if not isinstance(results[3], Exception):
                context.person_info = results[3]
            if not isinstance(results[4], Exception):
                context.recent_tasks = results[4]
            if not isinstance(results[5], Exception):
                context.active_goals = results[5]
            if not isinstance(results[6], Exception):
                context.insights = results[6]

        except Exception as e:
            logger.warning(f"Error fetching context: {e}")
            # コンテキスト取得に失敗しても処理は続行

        return context

    async def _get_recent_conversation(
        self,
        room_id: str,
        user_id: str,
    ) -> List[ConversationMessage]:
        """直近の会話を取得"""
        # TODO: Firestoreから取得する実装
        # 現在は空リストを返す（既存のget_conversation_history()を呼び出す予定）
        return []

    async def _get_conversation_summary(self, user_id: str):
        """会話要約を取得"""
        # TODO: conversation_summariesテーブルから取得
        return None

    async def _get_user_preferences(self, user_id: str):
        """ユーザー嗜好を取得"""
        # TODO: user_preferencesテーブルから取得
        return None

    async def _get_person_info(self) -> List:
        """人物情報を取得"""
        # TODO: personsテーブルから取得
        return []

    async def _get_recent_tasks(self, user_id: str) -> List:
        """直近のタスクを取得"""
        # TODO: chatwork_tasksテーブルから取得
        return []

    async def _get_active_goals(self, user_id: str) -> List:
        """アクティブな目標を取得"""
        # TODO: goalsテーブルから取得
        return []

    async def _get_insights(self) -> List:
        """インサイトを取得"""
        # TODO: soulkun_insightsテーブルから取得
        return []

    # =========================================================================
    # 状態管理層
    # =========================================================================

    async def _get_current_state(
        self,
        room_id: str,
        user_id: str,
    ) -> Optional[ConversationState]:
        """
        現在の状態を取得

        タイムアウトしている場合は自動的にクリアしてNoneを返す。
        """
        # TODO: brain_conversation_statesテーブルから取得
        # 現在はNoneを返す（状態なし = 通常状態）
        return None

    async def _transition_to_state(
        self,
        room_id: str,
        user_id: str,
        state_type: StateType,
        step: Optional[str] = None,
        data: Optional[Dict] = None,
        reference_type: Optional[str] = None,
        reference_id: Optional[str] = None,
        timeout_minutes: int = SESSION_TIMEOUT_MINUTES,
    ) -> ConversationState:
        """状態を遷移"""
        # TODO: brain_conversation_statesテーブルにUPSERT
        expires_at = datetime.now() + timedelta(minutes=timeout_minutes)
        state = ConversationState(
            organization_id=self.org_id,
            room_id=room_id,
            user_id=user_id,
            state_type=state_type,
            state_step=step,
            state_data=data or {},
            reference_type=reference_type,
            reference_id=reference_id,
            expires_at=expires_at,
        )
        logger.info(f"State transition: {state_type.value}, step={step}")
        return state

    async def _clear_state(
        self,
        room_id: str,
        user_id: str,
        reason: str = "user_cancel",
    ) -> None:
        """状態をクリア（通常状態に戻す）"""
        # TODO: brain_conversation_statesテーブルから削除
        logger.info(f"State cleared: room={room_id}, user={user_id}, reason={reason}")

    async def _update_state_step(
        self,
        room_id: str,
        user_id: str,
        new_step: str,
        additional_data: Optional[Dict] = None,
    ) -> ConversationState:
        """現在の状態内でステップを進める"""
        # TODO: brain_conversation_statesテーブルを更新
        logger.info(f"State step updated: {new_step}")
        return ConversationState(state_step=new_step)

    # =========================================================================
    # セッション継続処理
    # =========================================================================

    async def _continue_session(
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
            await self._clear_state(room_id, account_id, "unknown_state_type")
            # 再帰的に呼び出し（通常処理に戻る）
            return await self.process_message(message, room_id, account_id, sender_name)

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
        """目標設定セッションを継続"""
        # TODO: 既存のGoalSettingHandlerと連携
        # 現在は仮実装
        return BrainResponse(
            message="目標設定を続けるウル🐺",
            action_taken="continue_goal_setting",
            total_time_ms=self._elapsed_ms(start_time),
        )

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
        """アナウンス確認を継続"""
        # TODO: 既存のAnnouncementHandlerと連携
        # 現在は仮実装
        return BrainResponse(
            message="アナウンスの確認を続けるウル🐺",
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
        """確認への応答を処理"""
        pending_action = state.state_data.get("pending_action")
        pending_params = state.state_data.get("pending_params", {})
        options = state.state_data.get("confirmation_options", [])

        # 応答を解析
        selected_option = self._parse_confirmation_response(message, options)

        if selected_option is None:
            # 理解できない応答
            return BrainResponse(
                message="番号で教えてほしいウル🐺",
                action_taken="confirmation_retry",
                awaiting_confirmation=True,
                total_time_ms=self._elapsed_ms(start_time),
            )

        if selected_option == "cancel":
            # キャンセル
            await self._clear_state(room_id, account_id, "user_cancel_confirmation")
            return BrainResponse(
                message=CANCEL_MESSAGE,
                action_taken="cancel_confirmation",
                state_changed=True,
                new_state="normal",
                total_time_ms=self._elapsed_ms(start_time),
            )

        # 確認OK → アクションを実行
        await self._clear_state(room_id, account_id, "confirmation_accepted")

        # 選択されたオプションに基づいてパラメータを更新
        if isinstance(selected_option, int) and selected_option < len(options):
            pending_params["confirmed_option"] = options[selected_option]

        decision = DecisionResult(
            action=pending_action,
            params=pending_params,
            confidence=1.0,  # 確認済みなので確信度は1.0
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
        # TODO: 既存のhandle_pending_task_followup()と連携
        return BrainResponse(
            message="タスクの詳細を教えてほしいウル🐺",
            action_taken="continue_task_pending",
            total_time_ms=self._elapsed_ms(start_time),
        )

    # =========================================================================
    # 理解層
    # =========================================================================

    async def _understand(
        self,
        message: str,
        context: BrainContext,
    ) -> UnderstandingResult:
        """
        ユーザーの入力から意図を推論

        省略の補完、曖昧性の解消、感情の検出等を行う。

        v10.28.0: 19種のアクションを認識可能
        """
        start_time = time.time()
        normalized = message.lower().strip()

        # TODO: LLMを使った本格的な意図推論を実装（Phase B-D）
        # 現在は簡易的なキーワードマッチング

        intent = "general_conversation"
        confidence = 0.5
        entities = {}

        # =================================================================
        # タスク関連のキーワード（高優先度）
        # =================================================================
        task_keywords = ["タスク", "仕事", "やること", "todo", "作業"]
        if any(kw in message for kw in task_keywords):
            if any(kw in message for kw in ["作成", "追加", "作って", "お願い", "依頼"]):
                intent = "chatwork_task_create"
                confidence = 0.85
            elif any(kw in message for kw in ["検索", "教えて", "見せて", "一覧", "確認"]):
                intent = "chatwork_task_search"
                confidence = 0.85
            elif any(kw in message for kw in ["完了", "終わった", "できた", "done", "済み"]):
                intent = "chatwork_task_complete"
                confidence = 0.85

        # =================================================================
        # 目標関連のキーワード
        # =================================================================
        goal_keywords = ["目標", "ゴール"]
        if any(kw in message for kw in goal_keywords):
            if any(kw in message for kw in ["設定", "立てたい", "決めたい", "作りたい"]):
                intent = "goal_setting_start"
                confidence = 0.85
            elif any(kw in message for kw in ["進捗", "報告", "どれくらい"]):
                intent = "goal_progress_report"
                confidence = 0.8
            elif any(kw in message for kw in ["状況", "どうなった", "確認"]):
                intent = "goal_status_check"
                confidence = 0.8
            else:
                intent = "goal_setting_start"
                confidence = 0.7

        # =================================================================
        # 記憶・ナレッジ関連のキーワード
        # =================================================================
        # 覚える系
        if any(kw in message for kw in ["覚えて", "記憶して", "メモして"]):
            if any(kw in message for kw in ["人", "さん", "社員"]):
                intent = "save_memory"
                confidence = 0.85
            else:
                intent = "learn_knowledge"
                confidence = 0.8

        # 忘れる系
        if any(kw in message for kw in ["忘れて", "削除して", "消して"]):
            if any(kw in message for kw in ["人", "さん", "社員"]):
                intent = "delete_memory"
                confidence = 0.85
            else:
                intent = "forget_knowledge"
                confidence = 0.8

        # 一覧系
        if any(kw in message for kw in ["覚えてること", "何覚えてる", "一覧"]):
            if any(kw in message for kw in ["知識", "ナレッジ", "設定"]):
                intent = "list_knowledge"
                confidence = 0.8
            elif any(kw in message for kw in ["人", "さん"]):
                intent = "query_memory"
                confidence = 0.8

        # ナレッジ検索（会社知識クエリ）
        knowledge_query_keywords = ["就業規則", "規則", "ルール", "マニュアル", "手順", "方法"]
        if any(kw in message for kw in knowledge_query_keywords):
            intent = "query_knowledge"
            confidence = 0.8
            entities["query"] = message

        # =================================================================
        # 組織図関連のキーワード
        # =================================================================
        org_keywords = ["組織", "部署", "チーム", "誰が", "担当者", "上司", "部下"]
        if any(kw in message for kw in org_keywords):
            intent = "query_org_chart"
            confidence = 0.75

        # =================================================================
        # アナウンス関連のキーワード
        # =================================================================
        announcement_keywords = ["アナウンス", "お知らせ", "連絡して", "送って"]
        if any(kw in message for kw in announcement_keywords):
            intent = "announcement_create"
            confidence = 0.8

        # =================================================================
        # 提案関連のキーワード
        # =================================================================
        proposal_keywords = ["承認", "却下", "提案"]
        if any(kw in message for kw in proposal_keywords):
            intent = "proposal_decision"
            confidence = 0.75

        # =================================================================
        # 振り返り関連のキーワード
        # =================================================================
        reflection_keywords = ["振り返り", "今日一日", "反省", "日報"]
        if any(kw in message for kw in reflection_keywords):
            intent = "daily_reflection"
            confidence = 0.75

        # =================================================================
        # 汎用検索（上記で判定できなかった場合）
        # =================================================================
        if intent == "general_conversation" and confidence < 0.6:
            general_query_keywords = ["教えて", "知りたい", "どう", "何"]
            if any(kw in message for kw in general_query_keywords):
                intent = "query_knowledge"
                confidence = 0.55
                entities["query"] = message

        # 確認が必要か判定
        needs_confirmation = confidence < CONFIRMATION_THRESHOLD

        return UnderstandingResult(
            raw_message=message,
            intent=intent,
            intent_confidence=confidence,
            entities=entities,
            needs_confirmation=needs_confirmation,
            reasoning=f"Keyword matching: {intent} (confidence: {confidence:.2f})",
            processing_time_ms=self._elapsed_ms(start_time),
        )

    # =========================================================================
    # 判断層
    # =========================================================================

    async def _decide(
        self,
        understanding: UnderstandingResult,
        context: BrainContext,
    ) -> DecisionResult:
        """
        理解した意図に基づいてアクションを決定

        SYSTEM_CAPABILITIESから適切な機能を選択する。
        """
        start_time = time.time()

        # 意図に対応するアクションを探す
        action = understanding.intent
        params = understanding.entities.copy()

        # 確信度の判定
        confidence = understanding.intent_confidence
        needs_confirmation = False
        confirmation_question = None
        confirmation_options = []

        # 確信度が低い場合、または危険な操作の場合は確認
        if confidence < CONFIRMATION_THRESHOLD:
            needs_confirmation = True
            confirmation_question = (
                f"「{understanding.raw_message}」は「{action}」でいいウル？"
            )
            confirmation_options = ["はい", "いいえ"]
        elif action in DANGEROUS_ACTIONS:
            needs_confirmation = True
            confirmation_question = f"本当に{action}を実行していいウル？"
            confirmation_options = ["はい", "いいえ"]

        return DecisionResult(
            action=action,
            params=params,
            confidence=confidence,
            needs_confirmation=needs_confirmation,
            confirmation_question=confirmation_question,
            confirmation_options=confirmation_options,
            reasoning=f"Selected {action} with confidence {confidence}",
            processing_time_ms=self._elapsed_ms(start_time),
        )

    # =========================================================================
    # 実行層
    # =========================================================================

    async def _execute(
        self,
        decision: DecisionResult,
        context: BrainContext,
        room_id: str,
        account_id: str,
        sender_name: str,
    ) -> HandlerResult:
        """
        アクションを実行

        対応するハンドラーを呼び出し、結果を返す。
        """
        action = decision.action
        params = decision.params

        # ハンドラーを取得
        handler = self.handlers.get(action)

        if handler is None:
            # ハンドラーがない場合は汎用応答
            logger.warning(f"No handler for action: {action}")

            # 汎用AI応答を生成
            if self.get_ai_response:
                try:
                    response = self.get_ai_response(
                        context.recent_conversation[-5:] if context.recent_conversation else [],
                        context.to_prompt_context(),
                    )
                    return HandlerResult(
                        success=True,
                        message=response,
                    )
                except Exception as e:
                    logger.error(f"Error generating AI response: {e}")

            return HandlerResult(
                success=True,
                message="了解ウル！🐺",
            )

        # ハンドラーを実行
        try:
            result = await asyncio.wait_for(
                self._call_handler(
                    handler=handler,
                    params=params,
                    room_id=room_id,
                    account_id=account_id,
                    sender_name=sender_name,
                    context=context,
                ),
                timeout=EXECUTION_TIMEOUT_SECONDS,
            )
            return result
        except asyncio.TimeoutError:
            logger.error(f"Handler timeout: {action}")
            raise HandlerTimeoutError(
                message=f"Handler {action} timed out",
                action=action,
                timeout_seconds=EXECUTION_TIMEOUT_SECONDS,
            )
        except Exception as e:
            logger.error(f"Handler error: {action}, {e}")
            return HandlerResult(
                success=False,
                message=ERROR_MESSAGE,
                error_code="HANDLER_ERROR",
                error_details=str(e),
            )

    async def _call_handler(
        self,
        handler: Callable,
        params: Dict[str, Any],
        room_id: str,
        account_id: str,
        sender_name: str,
        context: BrainContext,
    ) -> HandlerResult:
        """ハンドラーを呼び出す"""
        # ハンドラーが同期関数か非同期関数かを判定
        if asyncio.iscoroutinefunction(handler):
            result = await handler(
                params=params,
                room_id=room_id,
                account_id=account_id,
                sender_name=sender_name,
                context=context,
            )
        else:
            # 同期関数の場合はスレッドプールで実行
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: handler(
                    params=params,
                    room_id=room_id,
                    account_id=account_id,
                    sender_name=sender_name,
                    context=context,
                ),
            )

        # 結果をHandlerResultに変換
        if isinstance(result, HandlerResult):
            return result
        elif isinstance(result, str):
            return HandlerResult(success=True, message=result)
        elif isinstance(result, dict):
            return HandlerResult(
                success=result.get("success", True),
                message=result.get("message", "完了ウル🐺"),
                data=result,
            )
        else:
            return HandlerResult(success=True, message="完了ウル🐺")

    # =========================================================================
    # ユーティリティ
    # =========================================================================

    def _is_cancel_request(self, message: str) -> bool:
        """キャンセルリクエストかどうかを判定"""
        normalized = message.strip().lower()
        return any(kw in normalized for kw in CANCEL_KEYWORDS)

    def _parse_confirmation_response(
        self,
        message: str,
        options: List[str],
    ) -> Optional[Any]:
        """確認への応答を解析"""
        normalized = message.strip().lower()

        # キャンセルキーワード
        if self._is_cancel_request(message):
            return "cancel"

        # 数字で回答
        try:
            num = int(normalized)
            if 1 <= num <= len(options):
                return num - 1  # 0-indexed
        except ValueError:
            pass

        # キーワードで回答
        positive_keywords = ["はい", "yes", "ok", "オーケー", "いいよ", "お願い", "うん"]
        if any(kw in normalized for kw in positive_keywords):
            return 0  # 最初の選択肢

        negative_keywords = ["いいえ", "no", "やめ", "違う", "ちがう"]
        if any(kw in normalized for kw in negative_keywords):
            return "cancel"

        return None

    def _elapsed_ms(self, start_time: float) -> int:
        """経過時間をミリ秒で取得"""
        return int((time.time() - start_time) * 1000)

    async def _update_memory_safely(
        self,
        message: str,
        result: HandlerResult,
        context: BrainContext,
        account_id: str,
    ) -> None:
        """記憶を安全に更新（エラーを無視）"""
        try:
            # TODO: 記憶更新の実装
            pass
        except Exception as e:
            logger.warning(f"Error updating memory: {e}")

    async def _log_decision_safely(
        self,
        message: str,
        understanding: UnderstandingResult,
        decision: DecisionResult,
        result: HandlerResult,
        room_id: str,
        account_id: str,
    ) -> None:
        """判断ログを安全に記録（エラーを無視）"""
        try:
            # TODO: brain_decision_logsテーブルへの記録
            logger.debug(
                f"Decision log: intent={understanding.intent}, "
                f"action={decision.action}, success={result.success}"
            )
        except Exception as e:
            logger.warning(f"Error logging decision: {e}")


# =============================================================================
# ファクトリー関数
# =============================================================================


def create_brain(
    pool,
    org_id: str,
    handlers: Optional[Dict[str, Callable]] = None,
    capabilities: Optional[Dict[str, Dict]] = None,
    get_ai_response_func: Optional[Callable] = None,
) -> SoulkunBrain:
    """
    SoulkunBrainのインスタンスを作成

    使用例:
        brain = create_brain(
            pool=db_pool,
            org_id="org_soulsyncs",
            handlers=HANDLERS,
            capabilities=SYSTEM_CAPABILITIES,
        )
    """
    return SoulkunBrain(
        pool=pool,
        org_id=org_id,
        handlers=handlers,
        capabilities=capabilities,
        get_ai_response_func=get_ai_response_func,
    )
