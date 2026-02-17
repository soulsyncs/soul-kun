# lib/brain/core/message_processing.py
"""
SoulkunBrain メッセージ処理パイプライン

process_message（メインエントリーポイント）と
_process_with_llm_brain（LLM Brain処理フロー）、
_synthesize_knowledge_answer（ナレッジ回答合成）を含む。
"""

import logging
import time
from datetime import datetime
from typing import Optional, Dict, Any

from lib.brain.models import (
    BrainContext,
    BrainResponse,
    HandlerResult,
    StateType,
)

from lib.brain.constants import (
    CANCEL_MESSAGE,
    ERROR_MESSAGE,
    SAVE_DECISION_LOGS,
)

from lib.brain.exceptions import BrainError

from lib.feature_flags import is_llm_brain_enabled

# Langfuseトレーシング
from lib.brain.langfuse_integration import (
    observe,
    update_current_trace,
    flush as langfuse_flush,
)

logger = logging.getLogger(__name__)


class MessageProcessingMixin:
    """SoulkunBrainメッセージ処理関連メソッドを提供するMixin"""

    # =========================================================================
    # メインエントリーポイント
    # =========================================================================

    @observe(name="brain.process_message", capture_input=False, capture_output=False)
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

        # Langfuseトレース: ユーザー・セッション情報を設定
        # CLAUDE.md 3-2 #8 / 9-4準拠: PIIをマスキングして送信
        _masked_preview, _ = self.mask_pii(message[:50])
        update_current_trace(
            user_id=account_id,
            session_id=room_id,
            input={"message_preview": _masked_preview},
            tags=["brain", "process_message"],
        )

        # Phase 2E: 初回呼び出し時に永続化済み改善を復元
        if not self._initialized:
            self._initialized = True
            try:
                loaded = await self.learning_loop.load_persisted_improvements()
                if loaded > 0:
                    self._sync_learning_to_decision()
                    logger.info("[Phase2E] Loaded %d persisted improvements", loaded)
            except Exception as e:
                logger.warning("[Phase2E] Init load failed: %s", type(e).__name__)

        try:
            logger.debug("[DIAG] process_message START t=0.000s")
            logger.info(
                f"🧠 Brain processing: room={room_id}, user={sender_name}, "
                f"message={message[:50]}..."
            )

            _flag = is_llm_brain_enabled()
            _brain_obj = self.llm_brain is not None
            llm_brain_enabled = _flag and _brain_obj
            logger.info(
                "🧠 [DIAG] routing: flag=%s, brain_obj=%s, result=%s",
                _flag, "SET" if _brain_obj else "NONE", llm_brain_enabled,
            )

            # 1. 記憶層: コンテキスト取得（メッセージも渡して関連知識を検索）
            if llm_brain_enabled:
                # LLM BrainパスではContextBuilderが必要情報を取得するため、
                # ここでは最小のメタ情報のみ作成してDBクエリを避ける
                context = BrainContext(
                    organization_id=self.org_id,
                    room_id=room_id,
                    sender_name=sender_name,
                    sender_account_id=account_id,
                    timestamp=datetime.now(),
                )
            else:
                t0 = time.time()
                context = await self._get_context(
                    room_id=room_id,
                    user_id=account_id,
                    sender_name=sender_name,
                    message=message,
                )
                logger.debug("[DIAG] _get_context DONE t=%.3fs (took %.3fs)", time.time()-start_time, time.time()-t0)

            # 1.5 Phase 2D: CEO教え処理
            # CEOからのメッセージなら教えを抽出（非同期で実行）
            if self.memory_manager.is_ceo_user(account_id):
                self._fire_and_forget(
                    self.memory_manager.process_ceo_message_safely(
                        message, room_id, account_id, sender_name
                    )
                )

            # 関連するCEO教えをコンテキストに追加
            if not llm_brain_enabled:
                t0 = time.time()
                ceo_context = await self.memory_manager.get_ceo_teachings_context(
                    message, account_id
                )
                if ceo_context:
                    context.ceo_teachings = ceo_context
                logger.debug("[DIAG] ceo_teachings DONE t=%.3fs (took %.3fs)", time.time()-start_time, time.time()-t0)

            # =========================================================
            # v10.50.0: LLM Brain ルーティング
            # Feature Flag `ENABLE_LLM_BRAIN` が有効な場合、LLM脳で処理
            # =========================================================
            if llm_brain_enabled:
                logger.debug("[DIAG] routing to LLM Brain t=%.3fs", time.time()-start_time)
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
                # Phase 1-C: CoTログのPIIマスキング（CLAUDE.md 8-4準拠）
                sanitized_intent, _ = self.mask_pii(str(thought_chain.final_intent))
                logger.info(
                    f"🔗 Chain-of-Thought: input_type={thought_chain.input_type.value}, "
                    f"intent={sanitized_intent}, "
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

            # 5.8 Phase 2F: 結果からの学習 — アクション記録（fire-and-forget）
            if getattr(self, '_trackable_actions', None) and decision.action in self._trackable_actions:
                self._fire_and_forget(
                    self._record_outcome_event(
                        action=decision.action,
                        target_account_id=account_id,
                        target_room_id=room_id,
                        action_params=decision.params,
                        context_snapshot={"intent": understanding.intent},
                    )
                )

            # 6. 記憶更新（非同期で実行、エラーは無視）
            self._fire_and_forget(
                self.memory_manager.update_memory_safely(
                    message, result, context, room_id, account_id, sender_name
                )
            )

            # 7. 判断ログ記録（非同期で実行）
            if SAVE_DECISION_LOGS:
                self._fire_and_forget(
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

            # v10.56.15: パラメータ不足時の状態保存
            # update_stateがある場合、状態をDBに保存して次の入力で文脈を維持
            if result.update_state:
                try:
                    # タスク作成のパラメータ不足は TASK_PENDING 状態として保存
                    if decision.action == "chatwork_task_create":
                        # v10.56.16: パラメータ名をregistry.pyと統一
                        # LLM/Handler共通: task_body, assigned_to, limit_date, limit_time
                        params = decision.params or {}
                        task_data = {
                            "task_body": params.get("task_body", ""),
                            "assigned_to": params.get("assigned_to", ""),
                            "limit_date": params.get("limit_date", ""),
                            "limit_time": params.get("limit_time", ""),
                            "missing_items": ["task_body"] if not params.get("task_body") else [],
                            "sender_name": sender_name,
                        }

                        # PostgreSQL状態を保存
                        await self._transition_to_state(
                            room_id=room_id,
                            user_id=account_id,
                            state_type=StateType.TASK_PENDING,
                            data={
                                "pending_action": decision.action,
                                "pending_params": params,
                                "task_data": task_data,  # Handler形式のデータも保存
                                "reason": result.update_state.get("reason", "parameter_missing"),
                            },
                            timeout_minutes=10,
                        )

                        # Firestoreにも保存（handle_pending_task_followup互換）
                        try:
                            from services.task_actions import save_pending_task
                            save_pending_task(room_id, account_id, task_data)
                            logger.info(f"📋 TASK_PENDING状態保存（PG+Firestore）: room={room_id}")
                        except ImportError:
                            logger.info(f"📋 TASK_PENDING状態保存（PGのみ）: room={room_id}")
                    else:
                        # その他のアクションは CONFIRMATION 状態として保存
                        state_type_str = result.update_state.get("state_type", "confirmation")
                        state_type = StateType(state_type_str) if state_type_str in [e.value for e in StateType] else StateType.CONFIRMATION
                        await self._transition_to_state(
                            room_id=room_id,
                            user_id=account_id,
                            state_type=state_type,
                            data={
                                "pending_action": decision.action,
                                "pending_params": decision.params,
                                "reason": result.update_state.get("reason"),
                            },
                            timeout_minutes=5,
                        )
                except Exception as e:
                    logger.warning(f"状態保存失敗（処理は継続）: {e}")

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
            logger.exception(f"Unexpected error in brain: {type(e).__name__}")
            return BrainResponse(
                message=ERROR_MESSAGE,
                action_taken="error",
                success=False,
                debug_info={"error": type(e).__name__},
                total_time_ms=self._elapsed_ms(start_time),
            )
        finally:
            # Cloud Functions: リクエスト終了前にLangfuseトレースを確実に送信
            langfuse_flush()

    # =========================================================================
    # v10.50.0 → v11.0 Phase 3: LangGraph Brain処理
    # 旧 _process_with_llm_brain() を StateGraph に分解
    # 設計書: docs/25_llm_native_brain_architecture.md
    # =========================================================================

    @observe(name="brain.llm_brain_flow", capture_input=False, capture_output=False)
    async def _process_with_llm_brain(
        self,
        message: str,
        room_id: str,
        account_id: str,
        sender_name: str,
        context: "BrainContext",
        start_time: float,
    ) -> BrainResponse:
        """
        LLM Brain（Claude Opus 4.5）でメッセージを処理

        Phase 3: LangGraph StateGraph による処理。
        各ステップは lib/brain/graph/nodes/ に分離。

        【グラフフロー】
        state_check → build_context → llm_inference → guardian_check
            → (block|confirm|text_only|execute) → [synthesize] → response

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
            # Null安全チェック
            if self.llm_context_builder is None:
                raise BrainError("LLM context builder is not initialized")
            if self.llm_brain is None:
                raise BrainError("LLM brain is not initialized")
            if self.llm_guardian is None:
                raise BrainError("LLM guardian is not initialized")
            if self.llm_state_manager is None:
                raise BrainError("LLM state manager is not initialized")

            logger.debug("[DIAG] _process_with_llm_brain START t=%.3fs", time.time()-start_time)

            # 遅延初期化: テスト等でllm_brainが後からセットされた場合に対応
            if self._brain_graph is None:
                self._init_brain_graph()
            if self._brain_graph is None:
                raise BrainError("Brain graph is not initialized")

            # LangGraphの初期状態を構築
            initial_state = {
                "message": message,
                "room_id": room_id,
                "account_id": account_id,
                "sender_name": sender_name,
                "start_time": start_time,
                "organization_id": self.org_id,
                "context": context,
            }

            # グラフを実行
            logger.debug("[DIAG] graph.ainvoke START t=%.3fs", time.time()-start_time)
            final_state = await self._brain_graph.ainvoke(initial_state)
            logger.debug("[DIAG] graph.ainvoke DONE t=%.3fs", time.time()-start_time)

            # グラフが生成したレスポンスを返す
            response = final_state.get("response")
            if response is not None:
                return response

            # レスポンスが設定されていない場合（通常は発生しない）
            logger.warning("🧠 Graph completed without response")
            return BrainResponse(
                message="お手伝いできることはありますかウル？🐺",
                action_taken="graph_no_response",
                success=True,
                total_time_ms=self._elapsed_ms(start_time),
            )

        except Exception as e:
            logger.exception(f"LLM Brain error: {type(e).__name__}")

            logger.warning("🧠 LLM Brain failed, no fallback available in this version")
            return BrainResponse(
                message="申し訳ありませんウル、うまく処理できませんでしたウル🐺",
                action_taken="llm_brain_error",
                success=False,
                debug_info={"error": type(e).__name__},
                total_time_ms=self._elapsed_ms(start_time),
            )

    async def _synthesize_knowledge_answer(
        self,
        search_data: Dict[str, Any],
        original_query: str,
    ) -> Optional[str]:
        """
        Brain層でナレッジ検索結果から回答を合成する（Phase 3.5）

        CLAUDE.md §1準拠: 全出力は脳を通る。ハンドラーはデータ取得のみ、
        回答生成はBrain（LLM Brain）が担当する。

        Args:
            search_data: ハンドラーが返した検索データ
            original_query: ユーザーの元の質問

        Returns:
            合成された回答テキスト、またはNone（エラー時）
        """
        if self.llm_brain is None:
            logger.warning("LLM Brain not available for knowledge synthesis")
            return None

        formatted_context = search_data.get("formatted_context", "")
        # トークン制限を考慮してコンテキストを切り詰め（約1000トークン相当）
        MAX_CONTEXT_CHARS = 4000
        if len(formatted_context) > MAX_CONTEXT_CHARS:
            formatted_context = formatted_context[:MAX_CONTEXT_CHARS] + "\n...(以下省略)"
        source = search_data.get("source", "unknown")
        confidence = search_data.get("confidence", 0)
        source_note = search_data.get("source_note", "")

        system_prompt = f"""あなたは「ソウルくん」です。会社の知識ベースから情報を参照して回答します。

【重要なルール】
1. 提供された参考情報に基づいて回答してください
2. 情報源を明示してください（例：「就業規則によると...」「社内マニュアルでは...」）
3. 参考情報にない内容は推測せず、「その点は確認できませんでした」と伝えてください
4. ソウルくんのキャラクターを保ってください（語尾：〜ウル、時々🐺を使う）
5. 簡潔に、わかりやすく回答してください

【参考情報の出典】
検索方法: {source}（{"旧システム" if source == "legacy" else "Phase 3 Pinecone検索"}）
信頼度: {confidence:.2f}

【参考情報】
{formatted_context}
"""

        try:
            answer = await self.llm_brain.synthesize_text(
                system_prompt=system_prompt,
                user_message=f"質問: {original_query}",
            )

            if answer and source_note:
                answer += source_note

            return answer

        except Exception as e:
            logger.error(f"Knowledge synthesis error: {type(e).__name__}", exc_info=True)
            return None
