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

from .models import (
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

from .constants import (
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

from .exceptions import (
    BrainError,
    UnderstandingError,
    DecisionError,
    ExecutionError,
    StateError,
    MemoryAccessError,
    HandlerNotFoundError,
    HandlerTimeoutError,
)
from .state_manager import BrainStateManager
from .memory_access import (
    BrainMemoryAccess,
    ConversationMessage as MemoryConversationMessage,
    ConversationSummaryData,
    UserPreferenceData,
    PersonInfo,
    TaskInfo,
    GoalInfo,
    KnowledgeInfo,
    InsightInfo,
)
from .understanding import BrainUnderstanding
from .decision import BrainDecision
from .execution import BrainExecution
from .learning import BrainLearning

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
        firestore_db=None,
    ):
        """
        Args:
            pool: データベース接続プール
            org_id: 組織ID
            handlers: アクション名 → ハンドラー関数のマッピング
            capabilities: SYSTEM_CAPABILITIES（機能カタログ）
            get_ai_response_func: AI応答生成関数
            firestore_db: Firestore クライアント（会話履歴用）
        """
        self.pool = pool
        self.org_id = org_id
        self.handlers = handlers or {}
        self.capabilities = capabilities or {}
        self.get_ai_response = get_ai_response_func
        self.firestore_db = firestore_db

        # 記憶アクセス層の初期化
        self.memory_access = BrainMemoryAccess(
            pool=pool,
            org_id=org_id,
            firestore_db=firestore_db,
        )

        # 状態管理層の初期化
        self.state_manager = BrainStateManager(
            pool=pool,
            org_id=org_id,
        )

        # 理解層の初期化
        self.understanding = BrainUnderstanding(
            get_ai_response_func=get_ai_response_func,
            org_id=org_id,
            use_llm=True,  # LLMを使用（曖昧表現がある場合）
        )

        # 判断層の初期化
        self.decision = BrainDecision(
            capabilities=capabilities,
            get_ai_response_func=get_ai_response_func,
            org_id=org_id,
            use_llm=False,  # ルールベース判断（高速）
        )

        # 実行層の初期化
        self.execution = BrainExecution(
            handlers=handlers,
            get_ai_response_func=get_ai_response_func,
            org_id=org_id,
            enable_suggestions=True,
            enable_retry=True,
        )

        # 学習層の初期化
        self.learning = BrainLearning(
            pool=pool,
            org_id=org_id,
            firestore_db=firestore_db,
            enable_logging=True,
            enable_learning=True,
        )

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

            # 1. 記憶層: コンテキスト取得（メッセージも渡して関連知識を検索）
            context = await self._get_context(
                room_id=room_id,
                user_id=account_id,
                sender_name=sender_name,
                message=message,
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
                self._update_memory_safely(
                    message, result, context, room_id, account_id, sender_name
                )
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
    # 記憶層（BrainMemoryAccess経由）
    # =========================================================================

    async def _get_context(
        self,
        room_id: str,
        user_id: str,
        sender_name: str,
        message: Optional[str] = None,
    ) -> BrainContext:
        """
        脳が判断に必要な全ての記憶を取得

        BrainMemoryAccessを使用して複数の記憶ソースから並列で取得し、
        統合したコンテキストを返す。

        Args:
            room_id: ChatWorkルームID
            user_id: ユーザーのアカウントID
            sender_name: 送信者名
            message: 現在のメッセージ（関連知識検索に使用）

        Returns:
            BrainContext: 統合されたコンテキスト
        """
        context = BrainContext(
            organization_id=self.org_id,
            room_id=room_id,
            sender_name=sender_name,
            sender_account_id=user_id,
            timestamp=datetime.now(),
        )

        try:
            # BrainMemoryAccessで全ての記憶を並列取得
            memory_context = await self.memory_access.get_all_context(
                room_id=room_id,
                user_id=user_id,
                sender_name=sender_name,
                message=message,
            )

            # 結果をBrainContextに統合
            # 会話履歴（ConversationMessageに変換）
            if memory_context.get("recent_conversation"):
                context.recent_conversation = [
                    ConversationMessage(
                        role=msg.role if hasattr(msg, 'role') else msg.get('role', 'user'),
                        content=msg.content if hasattr(msg, 'content') else msg.get('content', ''),
                        timestamp=msg.timestamp if hasattr(msg, 'timestamp') else msg.get('timestamp'),
                    )
                    for msg in memory_context["recent_conversation"]
                ]

            # 会話要約
            if memory_context.get("conversation_summary"):
                summary = memory_context["conversation_summary"]
                context.conversation_summary = {
                    "summary_text": summary.summary_text if hasattr(summary, 'summary_text') else summary.get('summary_text', ''),
                    "key_topics": summary.key_topics if hasattr(summary, 'key_topics') else summary.get('key_topics', []),
                    "mentioned_persons": summary.mentioned_persons if hasattr(summary, 'mentioned_persons') else summary.get('mentioned_persons', []),
                    "mentioned_tasks": summary.mentioned_tasks if hasattr(summary, 'mentioned_tasks') else summary.get('mentioned_tasks', []),
                }

            # ユーザー嗜好
            if memory_context.get("user_preferences"):
                context.user_preferences = [
                    {
                        "preference_type": pref.preference_type if hasattr(pref, 'preference_type') else pref.get('preference_type', ''),
                        "preference_key": pref.preference_key if hasattr(pref, 'preference_key') else pref.get('preference_key', ''),
                        "preference_value": pref.preference_value if hasattr(pref, 'preference_value') else pref.get('preference_value'),
                        "confidence": pref.confidence if hasattr(pref, 'confidence') else pref.get('confidence', 0.5),
                    }
                    for pref in memory_context["user_preferences"]
                ]

            # 人物情報
            if memory_context.get("person_info"):
                context.person_info = [
                    {
                        "name": person.name if hasattr(person, 'name') else person.get('name', ''),
                        "attributes": person.attributes if hasattr(person, 'attributes') else person.get('attributes', {}),
                    }
                    for person in memory_context["person_info"]
                ]

            # タスク情報
            if memory_context.get("recent_tasks"):
                context.recent_tasks = [
                    {
                        "task_id": task.task_id if hasattr(task, 'task_id') else task.get('task_id', ''),
                        "body": task.body if hasattr(task, 'body') else task.get('body', ''),
                        "summary": task.summary if hasattr(task, 'summary') else task.get('summary'),
                        "status": task.status if hasattr(task, 'status') else task.get('status', 'open'),
                        "limit_time": task.limit_time if hasattr(task, 'limit_time') else task.get('limit_time'),
                        "is_overdue": task.is_overdue if hasattr(task, 'is_overdue') else task.get('is_overdue', False),
                    }
                    for task in memory_context["recent_tasks"]
                ]

            # 目標情報
            if memory_context.get("active_goals"):
                context.active_goals = [
                    {
                        "title": goal.title if hasattr(goal, 'title') else goal.get('title', ''),
                        "why": goal.why if hasattr(goal, 'why') else goal.get('why'),
                        "what": goal.what if hasattr(goal, 'what') else goal.get('what'),
                        "how": goal.how if hasattr(goal, 'how') else goal.get('how'),
                        "status": goal.status if hasattr(goal, 'status') else goal.get('status', 'active'),
                        "progress": goal.progress if hasattr(goal, 'progress') else goal.get('progress', 0.0),
                    }
                    for goal in memory_context["active_goals"]
                ]

            # インサイト
            if memory_context.get("insights"):
                context.insights = [
                    {
                        "insight_type": insight.insight_type if hasattr(insight, 'insight_type') else insight.get('insight_type', ''),
                        "importance": insight.importance if hasattr(insight, 'importance') else insight.get('importance', 'medium'),
                        "title": insight.title if hasattr(insight, 'title') else insight.get('title', ''),
                        "description": insight.description if hasattr(insight, 'description') else insight.get('description', ''),
                        "recommended_action": insight.recommended_action if hasattr(insight, 'recommended_action') else insight.get('recommended_action'),
                    }
                    for insight in memory_context["insights"]
                ]

            # 関連知識
            if memory_context.get("relevant_knowledge"):
                context.relevant_knowledge = [
                    {
                        "keyword": knowledge.keyword if hasattr(knowledge, 'keyword') else knowledge.get('keyword', ''),
                        "answer": knowledge.answer if hasattr(knowledge, 'answer') else knowledge.get('answer', ''),
                        "category": knowledge.category if hasattr(knowledge, 'category') else knowledge.get('category'),
                        "relevance_score": knowledge.relevance_score if hasattr(knowledge, 'relevance_score') else knowledge.get('relevance_score', 0.0),
                    }
                    for knowledge in memory_context["relevant_knowledge"]
                ]

            logger.debug(
                f"Context loaded: conversation={len(context.recent_conversation)}, "
                f"tasks={len(context.recent_tasks)}, goals={len(context.active_goals)}, "
                f"insights={len(context.insights)}"
            )

        except Exception as e:
            logger.warning(f"Error fetching context via BrainMemoryAccess: {e}")
            # コンテキスト取得に失敗しても処理は続行

        return context

    async def _get_recent_conversation(
        self,
        room_id: str,
        user_id: str,
    ) -> List[ConversationMessage]:
        """直近の会話を取得（BrainMemoryAccess経由）"""
        messages = await self.memory_access.get_recent_conversation(room_id, user_id)
        return [
            ConversationMessage(
                role=msg.role,
                content=msg.content,
                timestamp=msg.timestamp,
            )
            for msg in messages
        ]

    async def _get_conversation_summary(self, user_id: str):
        """会話要約を取得（BrainMemoryAccess経由）"""
        return await self.memory_access.get_conversation_summary(user_id)

    async def _get_user_preferences(self, user_id: str):
        """ユーザー嗜好を取得（BrainMemoryAccess経由）"""
        return await self.memory_access.get_user_preferences(user_id)

    async def _get_person_info(self) -> List:
        """人物情報を取得（BrainMemoryAccess経由）"""
        return await self.memory_access.get_person_info()

    async def _get_recent_tasks(self, user_id: str) -> List:
        """直近のタスクを取得（BrainMemoryAccess経由）"""
        return await self.memory_access.get_recent_tasks(user_id)

    async def _get_active_goals(self, user_id: str) -> List:
        """アクティブな目標を取得（BrainMemoryAccess経由）"""
        return await self.memory_access.get_active_goals(user_id)

    async def _get_insights(self) -> List:
        """インサイトを取得（BrainMemoryAccess経由）"""
        return await self.memory_access.get_recent_insights()

    async def _get_relevant_knowledge(self, query: str) -> List:
        """関連知識を取得（BrainMemoryAccess経由）"""
        return await self.memory_access.get_relevant_knowledge(query)

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
        BrainStateManagerに委譲。
        """
        return await self.state_manager.get_current_state(room_id, user_id)

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
        """
        状態を遷移

        BrainStateManagerに委譲してDBにUPSERT。
        """
        return await self.state_manager.transition_to(
            room_id=room_id,
            user_id=user_id,
            state_type=state_type,
            step=step,
            data=data,
            reference_type=reference_type,
            reference_id=reference_id,
            timeout_minutes=timeout_minutes,
        )

    async def _clear_state(
        self,
        room_id: str,
        user_id: str,
        reason: str = "user_cancel",
    ) -> None:
        """
        状態をクリア（通常状態に戻す）

        BrainStateManagerに委譲してDBから削除。
        """
        await self.state_manager.clear_state(room_id, user_id, reason)

    async def _update_state_step(
        self,
        room_id: str,
        user_id: str,
        new_step: str,
        additional_data: Optional[Dict] = None,
    ) -> ConversationState:
        """
        現在の状態内でステップを進める

        BrainStateManagerに委譲してDBを更新。
        """
        return await self.state_manager.update_step(
            room_id=room_id,
            user_id=user_id,
            new_step=new_step,
            additional_data=additional_data,
        )

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

        BrainUnderstandingクラスに委譲。
        省略の補完、代名詞解決、曖昧性の解消、感情の検出等を行う。

        v10.28.3: LLM理解層に強化（Phase D完了）
        - LLMベースの意図推論（フォールバック: キーワードマッチング）
        - 代名詞解決: 「あれ」「それ」「あの人」→ 具体的な対象
        - 省略補完: 「完了にして」→ 直近のタスク
        - 感情検出: ポジティブ/ネガティブ/ニュートラル
        - 緊急度検出: 「至急」「急いで」等
        - 確認モード: 確信度0.7未満で発動
        """
        return await self.understanding.understand(message, context)

    # =========================================================================
    # 判断層
    # =========================================================================

    async def _decide(
        self,
        understanding: UnderstandingResult,
        context: BrainContext,
    ) -> DecisionResult:
        """
        BrainDecisionクラスに委譲。
        v10.28.4: 判断層に強化（Phase E完了）

        理解した意図に基づいてアクションを決定する。
        - SYSTEM_CAPABILITIESから適切な機能を選択
        - 確信度・リスクレベルに基づく確認要否判断
        - MVV整合性チェック
        - 複数アクション検出
        """
        return await self.decision.decide(understanding, context)

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
        BrainExecutionクラスに委譲。
        v10.28.6: 実行層に強化（Phase F完了）

        判断層からの指令に基づいてハンドラーを呼び出し、結果を統合する。
        - 5ステップ実行フロー（取得→検証→実行→統合→提案）
        - リトライ付き実行（最大3回）
        - タイムアウト処理（30秒）
        - 先読み提案生成
        """
        result = await self.execution.execute(
            decision=decision,
            context=context,
            room_id=room_id,
            account_id=account_id,
            sender_name=sender_name,
        )
        return result.to_handler_result()

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
        room_id: str,
        account_id: str,
        sender_name: str,
    ) -> None:
        """
        BrainLearningクラスに委譲。
        v10.28.7: 学習層に強化（Phase G完了）

        記憶を安全に更新（エラーを無視）
        """
        try:
            await self.learning.update_memory(
                message=message,
                result=result,
                context=context,
                room_id=room_id,
                account_id=account_id,
                sender_name=sender_name,
            )
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
        understanding_time_ms: int = 0,
        execution_time_ms: int = 0,
        total_time_ms: int = 0,
    ) -> None:
        """
        BrainLearningクラスに委譲。
        v10.28.7: 学習層に強化（Phase G完了）

        判断ログを安全に記録（エラーを無視）
        """
        try:
            await self.learning.log_decision(
                message=message,
                understanding=understanding,
                decision=decision,
                result=result,
                room_id=room_id,
                account_id=account_id,
                understanding_time_ms=understanding_time_ms,
                execution_time_ms=execution_time_ms,
                total_time_ms=total_time_ms,
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
