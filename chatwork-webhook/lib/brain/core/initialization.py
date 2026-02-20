# lib/brain/core/initialization.py
"""
SoulkunBrain 初期化・設定関連メソッド

__init__、fire-and-forget管理、学習同期、各サブシステム初期化を含む。
"""

import asyncio
import logging
import os
from typing import Optional, Dict, Callable

from lib.brain.memory_flush import AutoMemoryFlusher
from lib.brain.hybrid_search import HybridSearcher
from lib.brain.memory_sanitizer import mask_pii
from lib.brain.state_manager import BrainStateManager
from lib.brain.memory_access import BrainMemoryAccess
from lib.brain.understanding import BrainUnderstanding
from lib.brain.decision import BrainDecision
from lib.brain.execution import BrainExecution
from lib.brain.learning import BrainLearning
from lib.brain.learning_loop import create_learning_loop
from lib.brain.memory_manager import BrainMemoryManager
from lib.brain.session_orchestrator import SessionOrchestrator
from lib.brain.authorization_gate import AuthorizationGate

# Ultimate Brain - Phase 1: Chain-of-Thought & Self-Critique
from lib.brain.chain_of_thought import ChainOfThought
from lib.brain.self_critique import SelfCritique

# Phase 2D: CEO Learning & Guardian
from lib.brain.ceo_learning import CEOLearningService
from lib.brain.guardian import GuardianService
from lib.brain.ceo_teaching_repository import CEOTeachingRepository

# Phase 2L: ExecutionExcellence（実行力強化）
from lib.brain.execution_excellence import (
    ExecutionExcellence,
    create_execution_excellence,
)
from lib.feature_flags import is_execution_excellence_enabled as ff_execution_excellence_enabled
from lib.feature_flags import is_llm_brain_enabled

# v10.50.0: LLM Brain（LLM常駐型脳 - 25章）
from lib.brain.llm_brain import LLMBrain
from lib.brain.guardian_layer import GuardianLayer
from lib.brain.state_manager import LLMStateManager
from lib.brain.context_builder import ContextBuilder
from lib.brain.deep_understanding.emotion_reader import create_emotion_reader

# v10.46.0: 観測機能（Observability Layer）
from lib.brain.observability import create_observability

# タスクD: エピソード記憶（過去の出来事を想起）
from lib.brain.episodic_memory import create_episodic_memory

logger = logging.getLogger(__name__)


class InitializationMixin:
    """SoulkunBrain初期化関連メソッドを提供するMixin"""

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

        # Phase 1-A: 自動メモリフラッシュ
        memory_flusher = AutoMemoryFlusher(
            pool=pool,
            org_id=org_id,
            ai_client=get_ai_response_func,
        )

        # Phase 1-B: ハイブリッド検索（Pinecone/Embeddingは後から設定可能）
        hybrid_searcher = HybridSearcher(
            pool=pool,
            org_id=org_id,
        )

        # Phase 1-C: PIIマスキング関数（ログ出力時に使用）
        self.mask_pii = mask_pii

        # 記憶アクセス層の初期化
        self.memory_access = BrainMemoryAccess(
            pool=pool,
            org_id=org_id,
            firestore_db=firestore_db,
            memory_flusher=memory_flusher,
            hybrid_searcher=hybrid_searcher,
        )

        # タスクD: エピソード記憶（過去の出来事を記憶・想起）
        self.episodic_memory = create_episodic_memory(
            pool=pool,
            organization_id=org_id,
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

        # Phase 2E: 学習ループの初期化（フィードバック→判断改善）
        self.learning_loop = create_learning_loop(
            pool=pool,
            organization_id=org_id,
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
            handlers=self.handlers,  # v10.54.4: selfを使ってNoneではないことを保証
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

        # Phase 2F: Outcome Learning（結果からの学習）
        from lib.brain.outcome_learning import create_outcome_learning, TRACKABLE_ACTIONS
        self._trackable_actions = TRACKABLE_ACTIONS
        self.outcome_learning = create_outcome_learning(org_id)

        # v10.46.0: 観測機能（Observability Layer）
        self.observability = create_observability(
            org_id=org_id,
            enable_cloud_logging=True,
            enable_persistence=True,
            pool=pool,
        )

        # v10.50.0: LLM Brain（LLM常駐型脳 - 25章）
        self.llm_brain: Optional[LLMBrain] = None
        self.llm_guardian: Optional[GuardianLayer] = None
        self.llm_state_manager: Optional[LLMStateManager] = None
        self.llm_context_builder: Optional[ContextBuilder] = None
        self._init_llm_brain()

        # Step 0-3: 緊急停止チェッカー
        from lib.brain.emergency_stop import EmergencyStopChecker
        self.emergency_stop_checker = EmergencyStopChecker(
            pool=pool,
            org_id=org_id,
        )

        # Phase 3: LangGraph Brain処理グラフ
        self._brain_graph = None
        self._init_brain_graph()

        # 内部状態
        self._initialized = False

        # v10.74.0: fire-and-forgetタスク追跡（タスク消滅防止）
        self._background_tasks: set = set()

        logger.debug(f"SoulkunBrain initialized: "
                    f"chain_of_thought={self.use_chain_of_thought}, "
                    f"self_critique={self.use_self_critique}, "
                    f"execution_excellence={self.execution_excellence is not None}")

    # =========================================================================
    # v10.74.0: fire-and-forgetタスク安全管理
    # =========================================================================

    def _fire_and_forget(self, coro) -> None:
        """create_taskの安全ラッパー: 参照保持+エラーログ"""
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        task.add_done_callback(self._log_background_error)

    @staticmethod
    def _log_background_error(task: asyncio.Task) -> None:
        if not task.cancelled() and task.exception():
            logger.warning("Background task failed: %s", type(task.exception()).__name__)

    # =========================================================================
    # Phase 2E: 学習データ同期
    # =========================================================================

    def _sync_learning_to_decision(self) -> None:
        """LearningLoopの学習済みデータをDecision/Guardianに同期"""
        try:
            self.decision.set_learned_adjustments(
                score_adjustments=self.learning_loop._applied_weight_adjustments,
                exceptions=self.learning_loop.get_learned_exceptions(),
            )
            if self.llm_guardian:
                self.llm_guardian.set_learned_rules(
                    self.learning_loop.get_learned_rules()
                )
        except Exception as e:
            logger.warning("[Phase2E] Sync to decision failed: %s", type(e).__name__)

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
            logger.warning(f"Failed to initialize ExecutionExcellence: {type(e).__name__}")
            self.execution_excellence = None

    def _init_llm_brain(self) -> None:
        """
        LLM Brain（LLM常駐型脳）を初期化

        v10.50.0: Claude Opus 4.5を使用したFunction Calling方式の脳
        設計書: docs/25_llm_native_brain_architecture.md

        Feature Flag `ENABLE_LLM_BRAIN` が有効な場合のみ初期化。
        """
        _flag_enabled = is_llm_brain_enabled()
        logger.info(
            "🧠 [DIAG] Feature flag check: is_llm_brain_enabled=%s, env_USE_BRAIN_ARCHITECTURE=%s",
            _flag_enabled, os.environ.get("USE_BRAIN_ARCHITECTURE", "(unset)"),
        )
        if not _flag_enabled:
            logger.info("LLM Brain is disabled by feature flag")
            return

        try:
            # LLM Brain コンポーネントの初期化
            logger.info("🧠 [DIAG] LLMBrain init: attempting...")
            self.llm_brain = LLMBrain()
            self.llm_guardian = GuardianLayer(
                ceo_teachings=[],  # CEO教えは実行時に取得
            )
            self.llm_state_manager = LLMStateManager(
                brain_state_manager=self.state_manager,
            )
            self.emotion_reader = create_emotion_reader()
            self.llm_context_builder = ContextBuilder(
                pool=self.pool,
                memory_access=self.memory_access,
                state_manager=self.llm_state_manager,
                ceo_teaching_repository=self.ceo_teaching_repo,
                phase2e_learning=self.learning.phase2e_learning,
                outcome_learning=self.outcome_learning,
                emotion_reader=self.emotion_reader,
            )
            logger.info(
                "🧠 [DIAG] LLMBrain init: SUCCESS model=%s, provider=%s",
                self.llm_brain.model, self.llm_brain.api_provider.value,
            )
        except Exception as e:
            logger.error("🧠❌ [DIAG] LLMBrain init: FAILED %s", type(e).__name__, exc_info=True)
            self.llm_brain = None
            self.llm_guardian = None
            self.llm_state_manager = None
            self.llm_context_builder = None

    def _init_brain_graph(self) -> None:
        """
        Phase 3: LangGraph Brain処理グラフを初期化

        LLM Brainが有効な場合のみグラフを構築。
        _process_with_llm_brain() の処理フローをStateGraphに分解。
        """
        if self.llm_brain is None:
            logger.debug("LangGraph: LLM Brain disabled, skipping graph init")
            return

        try:
            from lib.brain.graph import create_brain_graph
            self._brain_graph = create_brain_graph(self)
            logger.info("🧠 LangGraph Brain graph initialized (11 nodes)")
        except Exception as e:
            logger.warning(f"Failed to initialize Brain graph: {type(e).__name__}: {e}")
            self._brain_graph = None
