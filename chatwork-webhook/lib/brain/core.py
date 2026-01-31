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
from typing import Optional, Dict, Any, List, Callable, Tuple, Union

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
    # Phase 2K: Proactive Message（鉄則1b準拠）
    ProactiveMessageResult,
    ProactiveMessageTone,
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
from lib.brain.memory_manager import BrainMemoryManager
from lib.brain.session_orchestrator import SessionOrchestrator
from lib.brain.authorization_gate import AuthorizationGate, AuthorizationResult

# Ultimate Brain - Phase 1: Chain-of-Thought & Self-Critique
from lib.brain.chain_of_thought import ChainOfThought, create_chain_of_thought
from lib.brain.self_critique import SelfCritique, create_self_critique

# Phase 2D: CEO Learning & Guardian
from lib.brain.ceo_learning import (
    CEOLearningService,
    CEO_ACCOUNT_IDS,
)
from lib.brain.guardian import (
    GuardianService,
    GuardianActionResult,
    GuardianActionType,
)

# v10.42.0 P3: Value Authority Layer
from lib.brain.value_authority import (
    ValueAuthority,
    ValueAuthorityResult,
    ValueDecision,
    create_value_authority,
)

# v10.43.0 P4: Memory Authority Layer
from lib.brain.memory_authority import (
    MemoryAuthority,
    MemoryAuthorityResult,
    MemoryDecision,
    create_memory_authority,
)

# v10.43.1 P4: Memory Authority Observation Logger
from lib.brain.memory_authority_logger import (
    get_memory_authority_logger,
)
from lib.brain.ceo_teaching_repository import CEOTeachingRepository

# Phase 2L: ExecutionExcellence（実行力強化）
from lib.brain.execution_excellence import (
    ExecutionExcellence,
    create_execution_excellence,
    is_execution_excellence_enabled,
    FEATURE_FLAG_EXECUTION_EXCELLENCE,
)
from lib.feature_flags import is_execution_excellence_enabled as ff_execution_excellence_enabled
from lib.feature_flags import is_llm_brain_enabled

# v10.50.0: LLM Brain（LLM常駐型脳 - 25章）
from lib.brain.tool_converter import get_tools_for_llm
from lib.brain.context_builder import ContextBuilder
from lib.brain.llm_brain import LLMBrain, LLMBrainResult
from lib.brain.guardian_layer import GuardianLayer, GuardianAction
from lib.brain.state_manager import LLMStateManager, LLMSessionMode, LLMPendingAction

# v10.46.0: 観測機能（Observability Layer）
from lib.brain.observability import (
    BrainObservability,
    ContextType,
    create_observability,
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

        # Phase 2D: CEO Learning層の初期化（memory_manager初期化後に参照）
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

        # 記憶マネージャーの初期化（学習・CEO Learning統括）
        self.memory_manager = BrainMemoryManager(
            learning=self.learning,
            ceo_learning=self.ceo_learning,
            organization_id=org_id,
        )

        # セッションオーケストレーターの初期化（マルチステップセッション管理）
        # 注: _understand, _decide, _execute等のメソッドは後で定義されるが、
        # Pythonでは呼び出し時に解決されるので問題なし
        self.session_orchestrator = SessionOrchestrator(
            handlers=handlers,
            state_manager=self.state_manager,
            understanding_func=self._understand,
            decision_func=self._decide,
            execution_func=self._execute,
            is_cancel_func=self._is_cancel_request,
            elapsed_ms_func=self._elapsed_ms,
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

        # 認可ゲートの初期化（権限チェック統括）
        self.authorization_gate = AuthorizationGate(
            guardian=self.guardian,
            execution_excellence=self.execution_excellence,
            organization_id=org_id,
        )

        # v10.46.0: 観測機能（Observability Layer）
        self.observability = create_observability(
            org_id=org_id,
            enable_cloud_logging=True,
            enable_persistence=False,  # 将来的にTrue
        )

        # v10.50.0: LLM Brain（LLM常駐型脳 - 25章）
        self.llm_brain: Optional[LLMBrain] = None
        self.llm_guardian: Optional[GuardianLayer] = None
        self.llm_state_manager: Optional[LLMStateManager] = None
        self.llm_context_builder: Optional[ContextBuilder] = None
        self._init_llm_brain()

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
            if self.memory_manager.is_ceo_user(account_id):
                asyncio.create_task(
                    self.memory_manager.process_ceo_message_safely(
                        message, room_id, account_id, sender_name
                    )
                )

            # 関連するCEO教えをコンテキストに追加
            ceo_context = await self.memory_manager.get_ceo_teachings_context(
                message, account_id
            )
            if ceo_context:
                context.ceo_teachings = ceo_context

            # =========================================================
            # v10.50.0: LLM Brain ルーティング
            # Feature Flag `ENABLE_LLM_BRAIN` が有効な場合、LLM脳で処理
            # =========================================================
            if is_llm_brain_enabled() and self.llm_brain is not None:
                logger.info("🧠 Routing to LLM Brain (Claude Opus 4.5)")
                return await self._process_with_llm_brain(
                    message=message,
                    room_id=room_id,
                    account_id=account_id,
                    sender_name=sender_name,
                    context=context,
                    start_time=start_time,
                )

            # =========================================================
            # 以下は従来のキーワードマッチング方式（LLM Brain無効時）
            # =========================================================

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

            # 2.2 セッション中なら、そのフローを継続（session_orchestratorに委譲）
            if current_state and current_state.is_active:
                return await self.session_orchestrator.continue_session(
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

            # v10.46.0: 観測ログ - 意図判定（脳が統一管理）
            self.observability.log_intent(
                intent=understanding.intent,
                route=decision.action,
                confidence=decision.confidence,
                account_id=account_id,
                raw_message=message,
            )

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

            # v10.46.0: 観測ログ - 実行結果（脳が統一管理）
            self.observability.log_execution(
                action=decision.action,
                success=result.success,
                account_id=account_id,
                execution_time_ms=self._elapsed_ms(start_time),
                error_code=result.data.get("error_code") if result.data and not result.success else None,
            )

            # 6. 記憶更新（非同期で実行、エラーは無視）
            asyncio.create_task(
                self.memory_manager.update_memory_safely(
                    message, result, context, room_id, account_id, sender_name
                )
            )

            # 7. 判断ログ記録（非同期で実行）
            if SAVE_DECISION_LOGS:
                asyncio.create_task(
                    self.memory_manager.log_decision_safely(
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
    # 能動的メッセージ生成（CLAUDE.md鉄則1b準拠）
    # =========================================================================

    async def generate_proactive_message(
        self,
        trigger_type: str,
        trigger_details: Dict[str, Any],
        user_id: str,
        organization_id: str,
        room_id: Optional[str] = None,
        account_id: Optional[str] = None,
    ) -> "ProactiveMessageResult":
        """
        能動的メッセージを生成する（脳経由）

        CLAUDE.md鉄則1b: 能動的出力も脳が生成
        システムが自発的に送るメッセージも脳が判断・生成する。

        【処理フロー】
        1. 記憶層: ユーザーのコンテキスト取得
           - 過去の会話履歴
           - ユーザーの好み・性格
           - 最近の感情傾向

        2. 理解層: トリガー状況の理解
           - なぜこのトリガーが発火したか
           - ユーザーにとってどういう状況か

        3. 判断層: 送信判断
           - 今このタイミングで送るべきか
           - どのようなトーンで送るべきか

        4. 生成層: メッセージ生成
           - ユーザーの好みに合わせた言葉遣い
           - 状況に応じた内容
           - ソウルくんらしい表現

        Args:
            trigger_type: トリガータイプ（goal_abandoned, task_overload等）
            trigger_details: トリガーの詳細情報
            user_id: ユーザーID
            organization_id: 組織ID
            room_id: ChatWorkルームID（オプション）
            account_id: ChatWorkアカウントID（オプション）

        Returns:
            ProactiveMessageResult: 生成結果
        """
        from lib.brain.models import ProactiveMessageResult, ProactiveMessageTone

        try:
            logger.info(
                f"🧠 Brain generating proactive message: "
                f"trigger={trigger_type}, user={user_id}"
            )

            # 1. 記憶層: ユーザーのコンテキスト取得
            context_used = {}

            # ユーザー情報を取得
            user_info = None
            try:
                if self.memory_access:
                    user_info = await self.memory_access.get_person_info(
                        organization_id=organization_id,
                        name=None,  # user_idで取得
                        user_id=user_id,
                    )
                    if user_info:
                        context_used["user_name"] = user_info.name
                        context_used["user_department"] = user_info.department
            except Exception as e:
                logger.warning(f"Failed to get user info: {e}")

            # 最近の会話履歴を取得
            recent_conversations = []
            try:
                if self.memory_access and room_id:
                    recent_conversations = await self.memory_access.get_conversation_history(
                        room_id=room_id,
                        organization_id=organization_id,
                        limit=5,
                    )
                    context_used["recent_conversations_count"] = len(recent_conversations)
            except Exception as e:
                logger.warning(f"Failed to get conversation history: {e}")

            # 2. 理解層: トリガー状況の理解
            trigger_context = self._understand_trigger_context(
                trigger_type=trigger_type,
                trigger_details=trigger_details,
                user_info=user_info,
            )
            context_used["trigger_context"] = trigger_context

            # 3. 判断層: 送信判断
            should_send, send_reason, tone = self._decide_proactive_action(
                trigger_type=trigger_type,
                trigger_details=trigger_details,
                recent_conversations=recent_conversations,
                user_info=user_info,
            )

            if not should_send:
                logger.info(f"🧠 Brain decided not to send: {send_reason}")
                return ProactiveMessageResult(
                    should_send=False,
                    reason=send_reason,
                    confidence=0.8,
                    context_used=context_used,
                )

            # 4. 生成層: メッセージ生成
            message = await self._generate_proactive_message_content(
                trigger_type=trigger_type,
                trigger_details=trigger_details,
                tone=tone,
                user_info=user_info,
                recent_conversations=recent_conversations,
            )

            logger.info(f"🧠 Brain generated proactive message: {message[:50]}...")

            return ProactiveMessageResult(
                should_send=True,
                message=message,
                reason=send_reason,
                confidence=0.85,
                tone=tone,
                context_used=context_used,
            )

        except Exception as e:
            logger.error(f"Error generating proactive message: {e}")
            return ProactiveMessageResult(
                should_send=False,
                reason=f"Error: {str(e)}",
                confidence=0.0,
                debug_info={"error": str(e)},
            )

    def _understand_trigger_context(
        self,
        trigger_type: str,
        trigger_details: Dict[str, Any],
        user_info: Optional[Any] = None,
    ) -> str:
        """トリガーの状況を理解する"""
        trigger_contexts = {
            "goal_abandoned": "目標が{days}日間更新されていない。進捗確認が必要。",
            "task_overload": "タスクが{count}件溜まっている。サポートが必要かもしれない。",
            "emotion_decline": "ネガティブな感情が続いている。気遣いが必要。",
            "goal_achieved": "目標を達成した。お祝いと次のステップへの励まし。",
            "task_completed_streak": "タスクを{count}件連続で完了。励ましと称賛。",
            "long_absence": "{days}日間活動がない。久しぶりの声かけ。",
        }

        template = trigger_contexts.get(trigger_type, "状況を確認する必要がある。")
        try:
            return template.format(**trigger_details)
        except KeyError:
            return template

    def _decide_proactive_action(
        self,
        trigger_type: str,
        trigger_details: Dict[str, Any],
        recent_conversations: List[Any],
        user_info: Optional[Any] = None,
    ) -> tuple:
        """送信判断を行う"""
        from lib.brain.models import ProactiveMessageTone

        # トリガータイプごとのデフォルト設定
        trigger_configs = {
            "goal_abandoned": (True, "目標進捗の確認", ProactiveMessageTone.SUPPORTIVE),
            "task_overload": (True, "タスク過多のサポート", ProactiveMessageTone.SUPPORTIVE),
            "emotion_decline": (True, "感情的なサポート", ProactiveMessageTone.CONCERNED),
            "goal_achieved": (True, "目標達成のお祝い", ProactiveMessageTone.CELEBRATORY),
            "task_completed_streak": (True, "連続完了の称賛", ProactiveMessageTone.ENCOURAGING),
            "long_absence": (True, "久しぶりの挨拶", ProactiveMessageTone.FRIENDLY),
        }

        config = trigger_configs.get(
            trigger_type,
            (True, "一般的なフォローアップ", ProactiveMessageTone.FRIENDLY)
        )

        # 最近の会話がネガティブな場合は慎重に
        if recent_conversations:
            # TODO: 会話内容を分析して判断を調整
            pass

        return config

    async def _generate_proactive_message_content(
        self,
        trigger_type: str,
        trigger_details: Dict[str, Any],
        tone: "ProactiveMessageTone",
        user_info: Optional[Any] = None,
        recent_conversations: List[Any] = None,
    ) -> str:
        """メッセージ内容を生成する"""
        from lib.brain.models import ProactiveMessageTone

        # ユーザー名を取得
        user_name = ""
        if user_info and hasattr(user_info, "name"):
            user_name = f"{user_info.name}さん、"

        # トリガータイプごとのメッセージテンプレート
        # ソウルくんのキャラクター（語尾「ウル」、絵文字🐺）を維持
        message_templates = {
            "goal_abandoned": {
                ProactiveMessageTone.SUPPORTIVE: [
                    f"{user_name}目標の進捗はどうですかウル？🐺 何か手伝えることがあれば言ってくださいね",
                    f"{user_name}目標について、最近どんな感じですかウル？🐺 一緒に確認してみましょうか",
                ],
                ProactiveMessageTone.FRIENDLY: [
                    f"{user_name}目標のこと、ちょっと気になってましたウル🐺 調子はどうですか？",
                ],
            },
            "task_overload": {
                ProactiveMessageTone.SUPPORTIVE: [
                    f"{user_name}タスクがたくさんあるみたいですねウル🐺 優先順位を一緒に整理しましょうか？",
                    f"{user_name}お仕事が忙しそうですねウル🐺 何かお手伝いできることはありますか？",
                ],
            },
            "emotion_decline": {
                ProactiveMessageTone.CONCERNED: [
                    f"{user_name}最近どうですかウル？🐺 何か気になることがあれば聞きますよ",
                    f"{user_name}少し心配してましたウル🐺 大丈夫ですか？無理しないでくださいね",
                ],
            },
            "goal_achieved": {
                ProactiveMessageTone.CELEBRATORY: [
                    f"{user_name}おめでとうございますウル！🎉🐺 目標達成、すごいですね！次はどんなことに挑戦しますか？",
                    f"{user_name}やりましたねウル！🎉🐺 素晴らしい成果です！この調子で頑張りましょう！",
                ],
            },
            "task_completed_streak": {
                ProactiveMessageTone.ENCOURAGING: [
                    f"{user_name}タスクをどんどん片付けてますねウル！🎉🐺 すごい調子です！",
                    f"{user_name}いい感じでタスクが進んでますねウル！✨🐺 この調子です！",
                ],
            },
            "long_absence": {
                ProactiveMessageTone.FRIENDLY: [
                    f"{user_name}お久しぶりですウル！🐺 最近どうしてましたか？",
                    f"{user_name}しばらくでしたねウル！🐺 元気にしてましたか？",
                ],
            },
        }

        # テンプレートを取得
        templates = message_templates.get(trigger_type, {})
        tone_templates = templates.get(tone, templates.get(ProactiveMessageTone.FRIENDLY, []))

        if not tone_templates:
            # フォールバック
            return f"{user_name}何かお手伝いできることはありますかウル？🐺"

        # ランダムに選択
        import random
        template = random.choice(tone_templates)

        # プレースホルダを置換
        try:
            return template.format(**trigger_details)
        except KeyError:
            return template

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

    def _init_llm_brain(self) -> None:
        """
        LLM Brain（LLM常駐型脳）を初期化

        v10.50.0: Claude Opus 4.5を使用したFunction Calling方式の脳
        設計書: docs/25_llm_native_brain_architecture.md

        Feature Flag `ENABLE_LLM_BRAIN` が有効な場合のみ初期化。
        """
        if not is_llm_brain_enabled():
            logger.info("LLM Brain is disabled by feature flag")
            return

        try:
            # LLM Brain コンポーネントの初期化
            self.llm_brain = LLMBrain()
            self.llm_guardian = GuardianLayer(
                ceo_teachings=[],  # CEO教えは実行時に取得
            )
            self.llm_state_manager = LLMStateManager(
                brain_state_manager=self.state_manager,
            )
            self.llm_context_builder = ContextBuilder(
                pool=self.pool,
                memory_access=self.memory_access,
                state_manager=self.llm_state_manager,
                ceo_teaching_repository=self.ceo_teaching_repo,
            )
            logger.info("🧠 LLM Brain initialized successfully (Claude Opus 4.5)")
        except Exception as e:
            logger.warning(f"Failed to initialize LLM Brain: {e}")
            self.llm_brain = None
            self.llm_guardian = None
            self.llm_state_manager = None
            self.llm_context_builder = None

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
        v10.47.0: authorization_gateに権限チェックを統合

        判断層からの指令に基づいてハンドラーを呼び出し、結果を統合する。
        """
        # =================================================================
        # 権限チェック（authorization_gateに委譲）
        # =================================================================
        auth_result = await self.authorization_gate.evaluate(
            decision=decision,
            context=context,
            room_id=room_id,
            account_id=account_id,
            sender_name=sender_name,
        )

        # ブロック/確認が必要な場合は早期リターン
        if auth_result.blocked and auth_result.response:
            return auth_result.response

        # ExecutionExcellenceが使用された場合
        if auth_result.execution_excellence_used and auth_result.execution_excellence_result:
            ee_result = auth_result.execution_excellence_result
            return HandlerResult(
                success=ee_result.success,
                message=ee_result.message,
                suggestions=getattr(ee_result, 'suggestions', None),
            )

        # =================================================================
        # 従来の実行フロー
        # =================================================================
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

    def _elapsed_ms(self, start_time: float) -> int:
        """経過時間をミリ秒で取得"""
        return int((time.time() - start_time) * 1000)

    # =========================================================================
    # v10.50.0: LLM Brain 処理（25章: LLM常駐型脳アーキテクチャ）
    # =========================================================================

    async def _process_with_llm_brain(
        self,
        message: str,
        room_id: str,
        account_id: str,
        sender_name: str,
        context: BrainContext,
        start_time: float,
    ) -> BrainResponse:
        """
        LLM Brain（Claude Opus 4.5）でメッセージを処理

        設計書: docs/25_llm_native_brain_architecture.md

        【処理フロー】
        1. ContextBuilder: LLMに渡すコンテキストを構築
        2. LLMBrain: Claude API + Function Callingで意図理解・Tool選択
        3. GuardianLayer: LLMの提案を検証（ALLOW/CONFIRM/BLOCK/MODIFY）
        4. Execution: Toolを実行

        Args:
            message: ユーザーのメッセージ
            room_id: ChatWorkルームID
            account_id: ユーザーのアカウントID
            sender_name: 送信者名
            context: 既に取得済みのBrainContext
            start_time: 処理開始時刻

        Returns:
            BrainResponse: 処理結果
        """
        try:
            logger.info(
                f"🧠 LLM Brain processing: room={room_id}, user={sender_name}, "
                f"message={message[:50]}..."
            )

            # 1. LLMコンテキストを構築
            llm_context = await self.llm_context_builder.build(
                user_id=account_id,
                room_id=room_id,
                organization_id=self.org_id,
                message=message,
                sender_name=sender_name,
            )

            # 2. Toolカタログを取得（SYSTEM_CAPABILITIESから変換）
            tools = get_tools_for_llm()

            # 3. LLM Brainで処理
            llm_result: LLMBrainResult = await self.llm_brain.process(
                context=llm_context,
                message=message,
                tools=tools,
            )

            logger.info(
                f"🧠 LLM Brain result: tool_calls={len(llm_result.tool_calls or [])}, "
                f"has_text={llm_result.text_response is not None}, "
                f"confidence={llm_result.confidence.overall:.2f}"
            )

            # 4. Guardian Layerで検証
            guardian_result = await self.llm_guardian.check(llm_result, llm_context)

            logger.info(
                f"🛡️ Guardian result: action={guardian_result.action.value}, "
                f"reason={guardian_result.reason[:50] if guardian_result.reason else 'N/A'}..."
            )

            # 5. Guardianの判断に基づいて処理を分岐
            if guardian_result.action == GuardianAction.BLOCK:
                # ブロック: 実行しない
                block_message = guardian_result.blocked_reason or guardian_result.reason or "その操作は実行できませんウル🐺"
                return BrainResponse(
                    message=block_message,
                    action_taken="guardian_block",
                    success=False,
                    debug_info={
                        "llm_brain": {
                            "tool_calls": [tc.to_dict() for tc in llm_result.tool_calls] if llm_result.tool_calls else [],
                            "confidence": llm_result.confidence,
                            "reasoning": llm_result.reasoning[:200] if llm_result.reasoning else None,
                        },
                        "guardian": {
                            "action": guardian_result.action.value,
                            "reason": guardian_result.reason,
                        },
                    },
                    total_time_ms=self._elapsed_ms(start_time),
                )

            elif guardian_result.action == GuardianAction.CONFIRM:
                # 確認が必要: 確認状態に遷移
                import uuid as uuid_mod
                tool_call = llm_result.tool_calls[0] if llm_result.tool_calls else None
                confirm_question = guardian_result.confirmation_question or guardian_result.reason or "確認させてほしいウル🐺"
                # ConfidenceScoresオブジェクトをfloatに変換（シリアライズ対応）
                confidence_value = (
                    llm_result.confidence.overall
                    if hasattr(llm_result.confidence, 'overall')
                    else float(llm_result.confidence) if llm_result.confidence else 0.0
                )
                pending_action = LLMPendingAction(
                    action_id=str(uuid_mod.uuid4()),
                    tool_name=tool_call.tool_name if tool_call else "",
                    parameters=tool_call.parameters if tool_call else {},
                    confirmation_question=confirm_question,
                    confirmation_type=guardian_result.risk_level or "ambiguous",
                    original_message=message,
                    original_reasoning=llm_result.reasoning or "",
                    confidence=confidence_value,
                )
                await self.llm_state_manager.set_pending_action(
                    user_id=account_id,
                    room_id=room_id,
                    pending_action=pending_action,
                )

                return BrainResponse(
                    message=confirm_question,
                    action_taken="request_confirmation",
                    success=True,
                    awaiting_confirmation=True,
                    state_changed=True,
                    new_state="llm_confirmation_pending",
                    debug_info={
                        "llm_brain": {
                            "tool_calls": [tc.to_dict() for tc in llm_result.tool_calls] if llm_result.tool_calls else [],
                            "confidence": llm_result.confidence,
                        },
                        "guardian": {
                            "action": guardian_result.action.value,
                            "reason": guardian_result.reason,
                        },
                    },
                    total_time_ms=self._elapsed_ms(start_time),
                )

            elif guardian_result.action == GuardianAction.MODIFY:
                # 修正が必要: Guardianが修正したパラメータを使用
                tool_calls_to_execute = llm_result.tool_calls
                # パラメータを修正（最初のTool呼び出しのみ）
                if tool_calls_to_execute and guardian_result.modified_params:
                    tool_calls_to_execute[0].parameters.update(guardian_result.modified_params)

            else:
                # ALLOW: そのまま実行
                tool_calls_to_execute = llm_result.tool_calls

            # 6. テキスト応答のみの場合（Tool呼び出しなし）
            if not tool_calls_to_execute:
                return BrainResponse(
                    message=llm_result.text_response or "お手伝いできることはありますかウル？🐺",
                    action_taken="llm_text_response",
                    success=True,
                    debug_info={
                        "llm_brain": {
                            "confidence": llm_result.confidence,
                            "reasoning": llm_result.reasoning[:200] if llm_result.reasoning else None,
                        },
                    },
                    total_time_ms=self._elapsed_ms(start_time),
                )

            # 7. Tool実行（既存のexecution層を活用）
            # 最初のTool呼び出しを実行（複数Toolは将来対応）
            tool_call = tool_calls_to_execute[0]

            # DecisionResultを構築して既存のexecution層に渡す
            decision = DecisionResult(
                action=tool_call.tool_name,
                params=tool_call.parameters,
                confidence=llm_result.confidence,
                needs_confirmation=False,  # Guardianで既にチェック済み
            )

            result = await self._execute(
                decision=decision,
                context=context,
                room_id=room_id,
                account_id=account_id,
                sender_name=sender_name,
            )

            # v10.46.0: 観測ログ - LLM Brain実行結果
            self.observability.log_execution(
                action=tool_call.tool_name,
                success=result.success,
                account_id=account_id,
                execution_time_ms=self._elapsed_ms(start_time),
                error_code=result.data.get("error_code") if result.data and not result.success else None,
            )

            # 記憶更新（非同期）
            asyncio.create_task(
                self.memory_manager.update_memory_safely(
                    message, result, context, room_id, account_id, sender_name
                )
            )

            return BrainResponse(
                message=result.message,
                action_taken=tool_call.tool_name,
                action_params=tool_call.parameters,
                success=result.success,
                suggestions=result.suggestions,
                debug_info={
                    "llm_brain": {
                        "tool_calls": [tc.to_dict() for tc in tool_calls_to_execute],
                        "confidence": llm_result.confidence,
                        "reasoning": llm_result.reasoning[:200] if llm_result.reasoning else None,
                    },
                    "guardian": {
                        "action": guardian_result.action.value,
                    },
                },
                total_time_ms=self._elapsed_ms(start_time),
            )

        except Exception as e:
            logger.exception(f"LLM Brain error: {e}")

            # フォールバック: 従来の処理に戻る
            logger.warning("🧠 LLM Brain failed, no fallback available in this version")
            return BrainResponse(
                message="申し訳ありませんウル、うまく処理できませんでしたウル🐺",
                action_taken="llm_brain_error",
                success=False,
                debug_info={"error": str(e)},
                total_time_ms=self._elapsed_ms(start_time),
            )

    def _parse_confirmation_response(
        self,
        message: str,
        options: List[str],
    ) -> Optional[Union[int, str]]:
        """
        確認応答をパースする（session_orchestratorへの委譲）

        Args:
            message: ユーザーの応答メッセージ
            options: 選択肢リスト

        Returns:
            int: 選択されたオプションのインデックス（0始まり）
            "cancel": キャンセル
            None: 解析不能
        """
        return self.session_orchestrator._parse_confirmation_response(message, options)

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
        確認への応答を処理（session_orchestratorへの委譲）

        Args:
            message: ユーザーの応答メッセージ
            state: 現在の会話状態
            context: コンテキスト情報
            room_id: ルームID
            account_id: アカウントID
            sender_name: 送信者名
            start_time: 処理開始時刻

        Returns:
            BrainResponse: 処理結果
        """
        return await self.session_orchestrator._handle_confirmation_response(
            message=message,
            state=state,
            context=context,
            room_id=room_id,
            account_id=account_id,
            sender_name=sender_name,
            start_time=start_time,
        )


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
