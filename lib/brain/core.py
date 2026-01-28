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

from sqlalchemy import text

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
    # Phase 2D: CEO Learning
    CEOTeachingContext,
    CEOTeaching,
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
from lib.brain.state_manager import BrainStateManager
from lib.brain.memory_access import (
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
from lib.brain.understanding import BrainUnderstanding
from lib.brain.decision import BrainDecision
from lib.brain.execution import BrainExecution
from lib.brain.learning import BrainLearning

# Ultimate Brain - Phase 1: Chain-of-Thought & Self-Critique
from lib.brain.chain_of_thought import ChainOfThought, create_chain_of_thought
from lib.brain.self_critique import SelfCritique, create_self_critique

# Phase 2D: CEO Learning & Guardian
from lib.brain.ceo_learning import (
    CEOLearningService,
    CEO_ACCOUNT_IDS,
)
from lib.brain.guardian import GuardianService
from lib.brain.ceo_teaching_repository import CEOTeachingRepository

# Phase 2L: ExecutionExcellence（実行力強化）
from lib.brain.execution_excellence import (
    ExecutionExcellence,
    create_execution_excellence,
    is_execution_excellence_enabled,
    FEATURE_FLAG_EXECUTION_EXCELLENCE,
)
from lib.feature_flags import is_execution_excellence_enabled as ff_execution_excellence_enabled

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

        # Phase 2D: CEO Learning層の初期化
        self.ceo_teaching_repo = CEOTeachingRepository(
            pool=pool,
            organization_id=org_id,
        )
        self.ceo_learning = CEOLearningService(
            pool=pool,
            organization_id=org_id,
            llm_caller=get_ai_response_func,
        )
        self.guardian = GuardianService(
            pool=pool,
            organization_id=org_id,
            llm_caller=get_ai_response_func,
        )

        # Ultimate Brain - Phase 1
        # 思考連鎖エンジン
        self.chain_of_thought = ChainOfThought(llm_client=None)

        # 自己批判エンジン
        self.self_critique = SelfCritique(llm_client=None)

        # Ultimate Brain設定
        self.use_chain_of_thought = True  # 思考連鎖を使用
        self.use_self_critique = True      # 自己批判を使用

        # Phase 2L: ExecutionExcellence（実行力強化）
        self.execution_excellence: Optional[ExecutionExcellence] = None
        self._init_execution_excellence()

        # 内部状態
        self._initialized = False

        logger.info(f"SoulkunBrain initialized for org_id={org_id}, "
                   f"chain_of_thought={self.use_chain_of_thought}, "
                   f"self_critique={self.use_self_critique}, "
                   f"execution_excellence={self.execution_excellence is not None}")

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

            # 1.5 Phase 2D: CEO教え処理
            # CEOからのメッセージなら教えを抽出（非同期で実行）
            if self._is_ceo_user(account_id):
                asyncio.create_task(
                    self._process_ceo_message_safely(message, room_id, account_id, sender_name)
                )

            # 関連するCEO教えをコンテキストに追加
            ceo_context = await self._get_ceo_teachings_context(message, account_id)
            if ceo_context:
                context.ceo_teachings = ceo_context

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

            # 2.5 Ultimate Brain: 思考連鎖で事前分析
            thought_chain = None
            if self.use_chain_of_thought:
                thought_chain = self._analyze_with_thought_chain(
                    message=message,
                    context={
                        "state": current_state.state_type.value if current_state else "normal",
                        "topic": getattr(context, "topic", None),
                    }
                )
                logger.info(
                    f"🔗 Chain-of-Thought: input_type={thought_chain.input_type.value}, "
                    f"intent={thought_chain.final_intent}, "
                    f"confidence={thought_chain.confidence:.2f}"
                )

            # 3. 理解層: 意図を推論（思考連鎖の結果を考慮）
            understanding = await self._understand(
                message, context, thought_chain=thought_chain
            )

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

            # 5.5 Ultimate Brain: 自己批判で回答品質をチェック
            final_message = result.message
            critique_applied = False
            if self.use_self_critique and result.message:
                refined = self._critique_and_refine_response(
                    response=result.message,
                    original_message=message,
                    context={
                        "expected_topic": getattr(context, "topic", None),
                        "previous_response": getattr(context, "last_ai_response", None),
                    }
                )
                if refined.refinement_applied:
                    final_message = refined.refined
                    critique_applied = True
                    logger.info(
                        f"✨ Self-Critique: {len(refined.improvements)} improvements applied, "
                        f"time={refined.refinement_time_ms:.1f}ms"
                    )

            # resultのメッセージを更新
            if critique_applied:
                result = HandlerResult(
                    success=result.success,
                    message=final_message,
                    data=result.data,
                    suggestions=result.suggestions,
                    update_state=result.update_state,
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

            # デバッグ情報を構築
            debug_info = {
                "understanding": {
                    "intent": understanding.intent,
                    "confidence": understanding.intent_confidence,
                },
                "decision": {
                    "action": decision.action,
                    "confidence": decision.confidence,
                },
            }

            # 思考連鎖の情報を追加
            if thought_chain:
                debug_info["thought_chain"] = {
                    "input_type": thought_chain.input_type.value,
                    "final_intent": thought_chain.final_intent,
                    "confidence": thought_chain.confidence,
                    "analysis_time_ms": thought_chain.analysis_time_ms,
                }

            # 自己批判の情報を追加
            if critique_applied:
                debug_info["self_critique"] = {
                    "applied": True,
                    "improvements_count": len(refined.improvements) if refined else 0,
                }

            return BrainResponse(
                message=result.message,
                action_taken=decision.action,
                action_params=decision.params,
                success=result.success,
                suggestions=result.suggestions,
                state_changed=result.update_state is not None,
                debug_info=debug_info,
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
        現在の状態を取得（v10.40.1: 神経接続修理 - brain_conversation_statesのみ参照）

        v10.40.1: goal_setting_sessionsへのフォールバックを削除
        - goal_setting.py が brain_conversation_states を使用するように書き換えられたため
        - 全ての状態は brain_conversation_states で一元管理

        v10.39.3: brain_conversation_states だけでなく goal_setting_sessions も確認
        - 脳がバイパスなしで全てを処理するため、両方のテーブルをチェック

        タイムアウトしている場合は自動的にクリアしてNoneを返す。
        """
        # brain_conversation_statesのみをチェック（goal_setting_sessionsは参照しない）
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
        """
        目標設定セッションを継続

        v10.39.2: 意図理解を追加
        - まずユーザーの意図を理解する
        - 目標設定の回答でなければ、セッションを中断して別の意図に対応
        - 中断されたセッションは記憶し、後でフォローアップ

        handlers辞書から'continue_goal_setting'ハンドラーを取得し、
        実際のGoalSettingDialogueと連携します。
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
                # ハンドラーを呼び出し
                # ハンドラーのシグネチャ: (message, room_id, account_id, sender_name, state_data) -> dict or str
                result = handler(
                    message,
                    room_id,
                    account_id,
                    sender_name,
                    state.state_data if state else {},
                )

                # 非同期ハンドラーの場合はawait
                if asyncio.iscoroutine(result):
                    result = await result

                # 結果の処理
                if isinstance(result, dict):
                    response_message = result.get("message", "")
                    success = result.get("success", True)
                    new_state = result.get("new_state")
                    state_changed = result.get("state_changed", False)

                    # 状態遷移が必要な場合
                    if new_state == "normal" or result.get("session_completed"):
                        await self._clear_state(room_id, account_id, "goal_setting_completed")
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
                # エラー時はセッションをクリアして安全に終了
                await self._clear_state(room_id, account_id, "goal_setting_error")
                return BrainResponse(
                    message="目標設定の処理中にエラーが発生したウル... もう一度最初からお願いするウル🐺",
                    action_taken="continue_goal_setting",
                    success=False,
                    state_changed=True,
                    new_state="normal",
                    total_time_ms=self._elapsed_ms(start_time),
                )

        # ハンドラー未登録時のフォールバック
        logger.warning("continue_goal_setting handler not registered, using fallback")
        return BrainResponse(
            message="目標設定を続けるウル🐺 今のステップは何だったかな...？",
            action_taken="continue_goal_setting",
            total_time_ms=self._elapsed_ms(start_time),
        )

    def _is_different_intent_from_goal_setting(
        self,
        message: str,
        understanding,
        inferred_action: str,
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

        # =====================================================
        # 1. STOP_WORDSチェック（明示的中断のみ許可）
        # =====================================================
        STOP_WORDS = [
            "やめる", "やめたい", "中断", "キャンセル",
            "終了", "一旦止めて", "別の話", "ストップ",
            "目標設定やめ", "目標やめ",
        ]
        if any(word in message_lower for word in STOP_WORDS):
            logger.info(f"🛑 Stop word detected, allowing interruption: {message[:30]}")
            return True

        # =====================================================
        # 2. goal_continuation_intentsチェック（継続）
        # =====================================================
        # v10.40.5: general_conversationを除外（雑談吸い込み事故防止）
        goal_continuation_intents = [
            "feedback_request",      # フィードバック依頼
            "doubt_or_anxiety",      # 不安・迷い
            "reflection",            # 振り返り
            "clarification",         # 確認・明確化
            "question",              # 質問（目標設定についての）
            "confirm",               # 確認
        ]
        if inferred_action in goal_continuation_intents:
            logger.debug(f"🔄 Goal continuation intent detected: {inferred_action}")
            return False  # セッション継続

        # =====================================================
        # 3. 短文継続ルール（20文字以下）
        # =====================================================
        # 相槌や短い確認は中断すべきでない
        if len(message.strip()) <= 20:
            logger.debug(f"🔄 Short message, continuing session: {message}")
            return False

        # =====================================================
        # 4. 既存の意図判定ロジック
        # =====================================================

        # 4.1 質問形式の検出
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

        # 4.2 別のアクションを示唆するキーワード
        # v10.40.5: 「どう思う」「アドバイス」「教えて」は除外（FB要求のため）
        other_action_keywords = [
            # タスク関連
            "タスク", "task", "やること", "宿題", "締め切り", "期限",
            # ナレッジ・記憶関連
            "覚えて", "記憶", "メモ", "ナレッジ",
            # 検索関連
            "検索", "探して",
            # 雑談
            "天気", "ニュース",
        ]
        has_other_action = any(kw in message for kw in other_action_keywords)

        # 4.3 目標設定の回答っぽいキーワード
        goal_response_keywords = [
            # WHY関連
            "なりたい", "成長", "目指", "達成", "実現",
            # WHAT関連
            "目標", "ゴール", "成果", "結果",
            # HOW関連
            "毎日", "毎週", "週に", "行動", "やる", "する",
            # 肯定的回答
            "はい", "うん", "そう", "OK", "わかった",
            # フィードバック系（継続扱い）
            "どう思う", "アドバイス", "教えて", "確認",
        ]
        is_goal_response = any(kw in message for kw in goal_response_keywords)

        # 4.4 goal関連アクション
        goal_actions = [
            "goal_registration", "continue_goal_setting",
            "goal_progress_report", "goal_status_check",
            "goal_setting_start",
        ]
        is_goal_action = inferred_action in goal_actions if inferred_action else False
        if inferred_action and "goal" in inferred_action.lower():
            is_goal_action = True

        # 4.5 判定ロジック
        # 明確に質問 + 目標設定の回答っぽくない + 長文 → 別の意図
        if is_question and not is_goal_response and len(message) > 30:
            return True

        # 別のアクションキーワード + 目標設定アクションでない → 別の意図
        if has_other_action and not is_goal_action and not is_goal_response:
            return True

        # inferred_actionが明確に別のアクション
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
        understanding,
        room_id: str,
        account_id: str,
        sender_name: str,
        start_time: float,
    ) -> BrainResponse:
        """
        目標設定セッションを中断し、別の意図に対応

        v10.39.2: 中断されたセッションを記憶し、後でフォローアップ

        処理:
        1. 現在のセッション進捗を記憶に保存
        2. セッションを「中断」状態に更新
        3. 別の意図を処理
        4. 処理結果にフォローアップメッセージを追加
        """
        try:
            # 1. セッション進捗を取得
            current_step = state.state_step if state else "unknown"
            session_data = state.state_data if state else {}
            why_answer = session_data.get("why_answer", "")
            what_answer = session_data.get("what_answer", "")
            how_answer = session_data.get("how_answer", "")

            logger.info(
                f"🧠 目標設定を中断: step={current_step}, "
                f"why={bool(why_answer)}, what={bool(what_answer)}, how={bool(how_answer)}"
            )

            # 2. 中断情報をstate_dataに保存
            interrupted_session = {
                "interrupted": True,
                "interrupted_at": datetime.now().isoformat(),
                "current_step": current_step,
                "why_answer": why_answer,
                "what_answer": what_answer,
                "how_answer": how_answer,
                "reference_id": state.reference_id if state else None,
            }

            # 3. セッションを中断状態で保存（handlersを通じて）
            interrupt_handler = self.handlers.get("interrupt_goal_setting")
            if interrupt_handler:
                try:
                    interrupt_handler(room_id, account_id, interrupted_session)
                except Exception as e:
                    logger.warning(f"Failed to save interrupted session: {e}")

            # 4. 状態をクリア（通常処理に戻すため）
            await self._clear_state(room_id, account_id, "goal_setting_interrupted")

            # 5. 別の意図を処理
            # 新しいコンテキストで通常のprocess_messageフローを実行
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

            # 決定を実行
            inferred_action = understanding.intent if understanding else "general_conversation"
            params = understanding.entities if understanding else {}

            decision = await self._decide(understanding, new_context)
            if decision:
                result = await self._execute(decision, new_context, room_id, account_id, sender_name)
            else:
                # フォールバック: 通常会話として処理
                result = await self._execute_general_conversation(
                    message, new_context, room_id, account_id, sender_name
                )

            # 6. フォローアップメッセージを追加
            original_message = result.message if result else ""
            step_name = {"why": "WHY", "what": "WHAT", "how": "HOW"}.get(current_step, "")
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
                metadata={
                    "interrupted_session": interrupted_session,
                    "original_action": inferred_action,
                },
            )

        except Exception as e:
            logger.error(f"Failed to handle interrupted goal setting: {e}")
            # エラー時は単純にセッションをクリアして通常処理
            await self._clear_state(room_id, account_id, "goal_setting_interrupt_error")
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
    ):
        """通常会話を実行（ヘルパーメソッド）"""
        handler = self.handlers.get("general_conversation")
        if handler:
            try:
                from lib.brain.models import HandlerResult
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
        """
        アナウンス確認セッションを継続

        handlers辞書から'continue_announcement'ハンドラーを取得し、
        実際のAnnouncementHandlerと連携します。

        ハンドラーが未登録の場合はフォールバックメッセージを返します。
        """
        handler = self.handlers.get("continue_announcement")

        if handler:
            try:
                # ハンドラーを呼び出し
                # ハンドラーのシグネチャ: (message, room_id, account_id, sender_name, state_data) -> dict or str
                result = handler(
                    message,
                    room_id,
                    account_id,
                    sender_name,
                    state.state_data if state else {},
                )

                # 非同期ハンドラーの場合はawait
                if asyncio.iscoroutine(result):
                    result = await result

                # 結果の処理
                if isinstance(result, dict):
                    response_message = result.get("message", "")
                    success = result.get("success", True)
                    new_state = result.get("new_state")
                    state_changed = result.get("state_changed", False)

                    # 状態遷移が必要な場合
                    if new_state == "normal" or result.get("session_completed"):
                        await self._clear_state(room_id, account_id, "announcement_completed")
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
                # エラー時はセッションをクリアして安全に終了
                await self._clear_state(room_id, account_id, "announcement_error")
                return BrainResponse(
                    message="アナウンス処理中にエラーが発生したウル... もう一度お願いするウル🐺",
                    action_taken="continue_announcement",
                    success=False,
                    state_changed=True,
                    new_state="normal",
                    total_time_ms=self._elapsed_ms(start_time),
                )

        # ハンドラー未登録時のフォールバック
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
        """
        タスク作成待ち状態を継続

        handlers辞書から'continue_task_pending'ハンドラーを取得し、
        handle_pending_task_followup()と連携します。

        ハンドラーが未登録の場合はフォールバックメッセージを返します。
        """
        handler = self.handlers.get("continue_task_pending")

        if handler:
            try:
                # ハンドラーを呼び出し
                # ハンドラーのシグネチャ: (message, room_id, account_id, sender_name, state_data) -> dict or str or None
                result = handler(
                    message,
                    room_id,
                    account_id,
                    sender_name,
                    state.state_data if state else {},
                )

                # 非同期ハンドラーの場合はawait
                if asyncio.iscoroutine(result):
                    result = await result

                # Noneの場合は何も補完できなかった
                if result is None:
                    # 再度質問
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

                # 結果の処理
                if isinstance(result, dict):
                    response_message = result.get("message", "")
                    success = result.get("success", True)
                    new_state = result.get("new_state")
                    state_changed = result.get("state_changed", False)

                    # タスク作成が完了した場合は状態をクリア
                    if new_state == "normal" or result.get("task_created"):
                        await self._clear_state(room_id, account_id, "task_pending_completed")
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
                    # タスク作成成功時は状態をクリア
                    await self._clear_state(room_id, account_id, "task_pending_completed")
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
                # エラー時はセッションをクリアして安全に終了
                await self._clear_state(room_id, account_id, "task_pending_error")
                return BrainResponse(
                    message="タスク作成中にエラーが発生したウル... もう一度最初からお願いするウル🐺",
                    action_taken="continue_task_pending",
                    success=False,
                    state_changed=True,
                    new_state="normal",
                    total_time_ms=self._elapsed_ms(start_time),
                )

        # ハンドラー未登録時のフォールバック
        logger.warning("continue_task_pending handler not registered, using fallback")

        # state_dataから不足項目を取得してプロンプトを生成
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

    # =========================================================================
    # 理解層
    # =========================================================================

    async def _understand(
        self,
        message: str,
        context: BrainContext,
        thought_chain=None,
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

        v10.34.0: Ultimate Brain Phase 1
        - thought_chain: 思考連鎖の結果（あれば活用）
        """
        # 思考連鎖の結果がある場合、コンテキストに追加
        if thought_chain:
            # 思考連鎖で低確信度（<0.7）なら確認モードを促す
            if thought_chain.confidence < 0.7:
                logger.debug(
                    f"Thought chain suggests confirmation: "
                    f"confidence={thought_chain.confidence:.2f}"
                )

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
    # Phase 2L: ExecutionExcellence初期化
    # =========================================================================

    def _init_execution_excellence(self) -> None:
        """
        ExecutionExcellence（実行力強化）を初期化

        Phase 2L: 複合タスクの自動分解・計画・実行

        Feature Flag `ENABLE_EXECUTION_EXCELLENCE` が有効な場合のみ初期化。
        """
        if not ff_execution_excellence_enabled():
            logger.info("ExecutionExcellence is disabled by feature flag")
            return

        try:
            self.execution_excellence = create_execution_excellence(
                handlers=self.handlers,
                capabilities=self.capabilities,
                pool=self.pool,
                org_id=self.org_id,
                llm_client=self.get_ai_response,
            )
            logger.info("ExecutionExcellence initialized successfully")
        except Exception as e:
            logger.warning(f"Failed to initialize ExecutionExcellence: {e}")
            self.execution_excellence = None

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
        v10.39.0: Phase 2L ExecutionExcellence統合

        判断層からの指令に基づいてハンドラーを呼び出し、結果を統合する。
        - 5ステップ実行フロー（取得→検証→実行→統合→提案）
        - リトライ付き実行（最大3回）
        - タイムアウト処理（30秒）
        - 先読み提案生成
        - Phase 2L: 複合タスクはExecutionExcellenceで自動分解・実行
        """
        # Phase 2L: 複合タスクの場合はExecutionExcellenceを使用
        if self.execution_excellence:
            # 元のメッセージを取得（最新の会話履歴から）
            original_message = ""
            if context.recent_conversation:
                # 最新のユーザーメッセージを取得
                for msg in reversed(context.recent_conversation):
                    if msg.role == "user":
                        original_message = msg.content
                        break

            # 複合タスク判定
            if original_message and self.execution_excellence.should_use_workflow(original_message, context):
                logger.info(f"🔄 Using ExecutionExcellence for complex request: {original_message[:50]}...")
                try:
                    ee_result = await self.execution_excellence.execute_request(
                        request=original_message,
                        context=context,
                    )

                    # 単一タスク判定（ExecutionExcellenceが分解不要と判断した場合）
                    if ee_result.plan_id == "single_task":
                        # 従来の実行フローにフォールバック
                        logger.debug("ExecutionExcellence: Single task detected, falling back to normal execution")
                    else:
                        # ExecutionExcellenceの結果をHandlerResultに変換
                        return HandlerResult(
                            success=ee_result.success,
                            message=ee_result.message,
                            suggestions=ee_result.suggestions,
                        )
                except Exception as e:
                    logger.warning(f"ExecutionExcellence failed, falling back to normal execution: {e}")
                    # ExecutionExcellenceが失敗した場合は従来の実行フローにフォールバック

        # 従来の実行フロー
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

    # =========================================================================
    # Ultimate Brain - Phase 1: 思考連鎖 & 自己批判
    # =========================================================================

    def _analyze_with_thought_chain(
        self,
        message: str,
        context: Optional[Dict[str, Any]] = None,
    ):
        """
        思考連鎖で入力を事前分析

        Args:
            message: ユーザーメッセージ
            context: コンテキスト情報

        Returns:
            ThoughtChain: 思考連鎖の結果
        """
        try:
            return self.chain_of_thought.analyze(message, context)
        except Exception as e:
            logger.warning(f"Chain-of-thought analysis failed: {e}")
            # 失敗してもNoneを返すだけで処理は続行
            return None

    def _critique_and_refine_response(
        self,
        response: str,
        original_message: str,
        context: Optional[Dict[str, Any]] = None,
    ):
        """
        自己批判で回答を評価・改善

        Args:
            response: 生成された回答
            original_message: 元のユーザーメッセージ
            context: コンテキスト情報

        Returns:
            RefinedResponse: 改善された回答
        """
        try:
            return self.self_critique.evaluate_and_refine(
                response, original_message, context
            )
        except Exception as e:
            logger.warning(f"Self-critique failed: {e}")
            # 失敗した場合は元の回答をそのまま返す
            from lib.brain.self_critique import RefinedResponse
            return RefinedResponse(
                original=response,
                refined=response,
                improvements=[],
                refinement_applied=False,
                refinement_time_ms=0,
            )

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

    # =========================================================================
    # Phase 2D: CEO Learning層
    # =========================================================================

    def _is_ceo_user(self, account_id: str) -> bool:
        """
        CEOユーザーかどうかを判定

        Args:
            account_id: ユーザーのアカウントID

        Returns:
            bool: CEOユーザーならTrue
        """
        return account_id in CEO_ACCOUNT_IDS

    async def _process_ceo_message_safely(
        self,
        message: str,
        room_id: str,
        account_id: str,
        sender_name: str,
    ) -> None:
        """
        CEOメッセージから教えを抽出（エラーを無視）

        非同期で実行され、メイン処理をブロックしない。
        抽出された教えはCEOLearningServiceで処理・保存される。

        Args:
            message: CEOのメッセージ
            room_id: ChatWorkルームID
            account_id: CEOのアカウントID
            sender_name: CEOの名前
        """
        try:
            logger.info(f"🎓 Processing CEO message from {sender_name}")

            # CEOLearningServiceで教えを抽出・保存
            result = await self.ceo_learning.process_ceo_message(
                message=message,
                room_id=room_id,
                account_id=account_id,
            )

            if result.success and result.teachings_saved > 0:
                logger.info(
                    f"📚 Saved {result.teachings_saved} teachings from CEO message"
                )
            elif result.teachings_extracted == 0:
                logger.debug("No teachings detected in CEO message")

        except Exception as e:
            logger.warning(f"Error processing CEO message: {e}")

    async def _get_ceo_teachings_context(
        self,
        message: str,
        account_id: Optional[str] = None,
    ) -> Optional[CEOTeachingContext]:
        """
        関連するCEO教えをコンテキストに追加

        現在のメッセージに関連する教えを取得し、
        CEOTeachingContextとして返す。

        Args:
            message: 現在のメッセージ
            account_id: ユーザーのアカウントID（CEOかどうかの判定用）

        Returns:
            Optional[CEOTeachingContext]: 関連するCEO教えのコンテキスト
        """
        try:
            # CEOLearningServiceのget_ceo_teaching_contextを使用
            is_ceo = self._is_ceo_user(account_id) if account_id else False

            ceo_context = self.ceo_learning.get_ceo_teaching_context(
                query=message,
                is_ceo=is_ceo,
            )

            # 関連する教えがなければNoneを返す
            if not ceo_context.relevant_teachings:
                return None

            return ceo_context

        except Exception as e:
            logger.warning(f"Error getting CEO teachings context: {e}")
            return None


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
