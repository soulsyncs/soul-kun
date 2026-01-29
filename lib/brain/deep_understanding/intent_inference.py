# lib/brain/deep_understanding/intent_inference.py
"""
Phase 2I: 理解力強化（Deep Understanding）- 暗黙の意図推測

設計書: docs/17_brain_completion_roadmap.md セクション17.3 Phase 2I

このファイルには、ユーザーの発話から暗黙の意図を推測する機能を実装します。

【主な機能】
- 指示代名詞の解決（「これ」「それ」「あれ」が何を指すか）
- 省略表現の補完（「完了にして」の対象特定）
- 婉曲表現の解釈（「ちょっと見てもらえます？」→依頼）
- 文脈依存表現の解決（「いつもの」「例の」の意味特定）
- 人名エイリアス解決（「田中さん」→「田中太郎」）

【Phase 6統合（2026-01-29）】
- EnhancedPronounResolver: 距離感に基づく代名詞解決
- PersonAliasResolver: 人名エイリアス解決
- ContextExpressionResolver: 文脈依存表現解決

Author: Claude Opus 4.5
Created: 2026-01-27
Updated: 2026-01-29 (Phase 6 統合)
"""

import logging
import re
import time
from typing import Optional, List, Dict, Any, Tuple, Callable, TYPE_CHECKING

from .constants import (
    ImplicitIntentType,
    ReferenceResolutionStrategy,
    DEMONSTRATIVE_PRONOUNS,
    PERSONAL_PRONOUNS,
    VAGUE_TIME_EXPRESSIONS,
    INDIRECT_REQUEST_PATTERNS,
    INDIRECT_NEGATION_PATTERNS,
    INTENT_CONFIDENCE_THRESHOLDS,
    MAX_CONTEXT_RECOVERY_ATTEMPTS,
)
from .models import (
    ResolvedReference,
    ImplicitIntent,
    IntentInferenceResult,
    DeepUnderstandingInput,
)

# Feature Flags
from lib.brain.constants import (
    DEFAULT_FEATURE_FLAGS,
    FEATURE_FLAG_ENHANCED_PRONOUN,
    FEATURE_FLAG_PERSON_ALIAS,
    FEATURE_FLAG_CONTEXT_EXPRESSION,
)

# 新しいリゾルバー（遅延インポート用の型ヒント）
if TYPE_CHECKING:
    from .pronoun_resolver import EnhancedPronounResolver
    from .person_alias import PersonAliasResolver
    from .context_expression import ContextExpressionResolver

logger = logging.getLogger(__name__)


class IntentInferenceEngine:
    """
    暗黙の意図推測エンジン

    ユーザーの発話から暗黙的な意図を推測し、
    指示代名詞や省略表現を解決する。

    使用例:
        engine = IntentInferenceEngine()
        result = await engine.infer(
            message="あれどうなった？",
            input_context=deep_understanding_input,
        )

    【Phase 6統合】強化版リゾルバーを使用可能:
        from lib.brain.deep_understanding.pronoun_resolver import create_pronoun_resolver
        from lib.brain.deep_understanding.person_alias import create_person_alias_resolver
        from lib.brain.deep_understanding.context_expression import create_context_expression_resolver

        engine = IntentInferenceEngine(
            pronoun_resolver=create_pronoun_resolver(conversation_history=history),
            person_alias_resolver=create_person_alias_resolver(known_persons=persons),
            context_expression_resolver=create_context_expression_resolver(user_habits=habits),
            feature_flags={
                FEATURE_FLAG_ENHANCED_PRONOUN: True,
                FEATURE_FLAG_PERSON_ALIAS: True,
                FEATURE_FLAG_CONTEXT_EXPRESSION: True,
            },
        )
    """

    def __init__(
        self,
        get_ai_response_func: Optional[Callable] = None,
        use_llm: bool = True,
        # Phase 6: 強化版リゾルバー
        pronoun_resolver: Optional["EnhancedPronounResolver"] = None,
        person_alias_resolver: Optional["PersonAliasResolver"] = None,
        context_expression_resolver: Optional["ContextExpressionResolver"] = None,
        feature_flags: Optional[Dict[str, bool]] = None,
    ):
        """
        Args:
            get_ai_response_func: AI応答生成関数（オプション）
            use_llm: LLMを使用するかどうか
            pronoun_resolver: 強化版代名詞リゾルバー（オプション）
            person_alias_resolver: 人名エイリアスリゾルバー（オプション）
            context_expression_resolver: 文脈依存表現リゾルバー（オプション）
            feature_flags: Feature Flags（デフォルトは全て無効）
        """
        self.get_ai_response = get_ai_response_func
        self.use_llm = use_llm and get_ai_response_func is not None

        # Phase 6: 強化版リゾルバー
        self._pronoun_resolver = pronoun_resolver
        self._person_alias_resolver = person_alias_resolver
        self._context_expression_resolver = context_expression_resolver

        # Feature Flags（デフォルトは全て無効）
        self._feature_flags = feature_flags or DEFAULT_FEATURE_FLAGS.copy()

        logger.info(
            f"IntentInferenceEngine initialized: use_llm={self.use_llm}, "
            f"enhanced_pronoun={self._is_feature_enabled(FEATURE_FLAG_ENHANCED_PRONOUN)}, "
            f"person_alias={self._is_feature_enabled(FEATURE_FLAG_PERSON_ALIAS)}, "
            f"context_expression={self._is_feature_enabled(FEATURE_FLAG_CONTEXT_EXPRESSION)}"
        )

    def _is_feature_enabled(self, flag_name: str) -> bool:
        """Feature Flagが有効かどうかを確認"""
        return self._feature_flags.get(flag_name, False)

    # =========================================================================
    # メインエントリーポイント
    # =========================================================================

    async def infer(
        self,
        message: str,
        input_context: DeepUnderstandingInput,
    ) -> IntentInferenceResult:
        """
        暗黙の意図を推測

        Args:
            message: ユーザーのメッセージ
            input_context: 深い理解層への入力コンテキスト

        Returns:
            IntentInferenceResult: 意図推測の結果
        """
        start_time = time.time()

        try:
            implicit_intents: List[ImplicitIntent] = []
            strategies_used: List[ReferenceResolutionStrategy] = []

            # Step 1: 指示代名詞の検出と解決
            # Phase 6: 強化版が有効な場合はそちらを使用
            if (self._is_feature_enabled(FEATURE_FLAG_ENHANCED_PRONOUN)
                    and self._pronoun_resolver):
                pronoun_intents = await self._resolve_pronouns_enhanced(
                    message=message,
                    context=input_context,
                )
            else:
                pronoun_intents = await self._resolve_demonstrative_pronouns(
                    message=message,
                    context=input_context,
                )
            implicit_intents.extend(pronoun_intents)
            if pronoun_intents:
                strategies_used.append(ReferenceResolutionStrategy.IMMEDIATE_CONTEXT)

            # Step 2: 省略表現の検出と補完
            ellipsis_intents = await self._resolve_ellipsis(
                message=message,
                context=input_context,
            )
            implicit_intents.extend(ellipsis_intents)
            if ellipsis_intents:
                strategies_used.append(ReferenceResolutionStrategy.CONVERSATION_HISTORY)

            # Step 3: 婉曲表現の解釈
            indirect_intents = await self._interpret_indirect_expressions(
                message=message,
                context=input_context,
            )
            implicit_intents.extend(indirect_intents)

            # Step 4: 文脈依存表現の解決
            # Phase 6: 強化版が有効な場合はそちらを使用
            if (self._is_feature_enabled(FEATURE_FLAG_CONTEXT_EXPRESSION)
                    and self._context_expression_resolver):
                context_dependent_intents = await self._resolve_context_expression_enhanced(
                    message=message,
                    context=input_context,
                )
            else:
                context_dependent_intents = await self._resolve_context_dependent(
                    message=message,
                    context=input_context,
                )
            implicit_intents.extend(context_dependent_intents)
            if context_dependent_intents:
                strategies_used.append(ReferenceResolutionStrategy.ORGANIZATION_VOCABULARY)

            # Step 5: 人名エイリアス解決（Phase 6追加）
            if (self._is_feature_enabled(FEATURE_FLAG_PERSON_ALIAS)
                    and self._person_alias_resolver):
                person_alias_intents = await self._resolve_person_aliases(
                    message=message,
                    context=input_context,
                )
                implicit_intents.extend(person_alias_intents)
                if person_alias_intents:
                    strategies_used.append(ReferenceResolutionStrategy.ORGANIZATION_VOCABULARY)

            # Step 6: LLMによる高度な推論（必要な場合）
            if self.use_llm and self._needs_llm_inference(implicit_intents):
                llm_intents = await self._llm_inference(
                    message=message,
                    context=input_context,
                    existing_intents=implicit_intents,
                )
                implicit_intents.extend(llm_intents)
                if llm_intents:
                    strategies_used.append(ReferenceResolutionStrategy.LLM_INFERENCE)

            # Step 7: 結果の統合
            primary_intent = self._select_primary_intent(implicit_intents)
            overall_confidence = self._calculate_overall_confidence(implicit_intents)
            needs_confirmation = overall_confidence < INTENT_CONFIDENCE_THRESHOLDS["medium"]

            result = IntentInferenceResult(
                implicit_intents=implicit_intents,
                primary_intent=primary_intent,
                overall_confidence=overall_confidence,
                needs_confirmation=needs_confirmation,
                confirmation_reason="意図の特定に確信が持てません" if needs_confirmation else "",
                processing_time_ms=self._elapsed_ms(start_time),
                strategies_used=strategies_used,
            )

            logger.info(
                f"Intent inference complete: "
                f"intents={len(implicit_intents)}, "
                f"confidence={overall_confidence:.2f}, "
                f"needs_confirmation={needs_confirmation}"
            )

            return result

        except Exception as e:
            logger.error(f"Error in intent inference: {e}")
            return IntentInferenceResult(
                implicit_intents=[],
                overall_confidence=0.0,
                needs_confirmation=True,
                confirmation_reason="意図の推測中にエラーが発生しました",
                processing_time_ms=self._elapsed_ms(start_time),
            )

    # =========================================================================
    # 指示代名詞の解決
    # =========================================================================

    async def _resolve_demonstrative_pronouns(
        self,
        message: str,
        context: DeepUnderstandingInput,
    ) -> List[ImplicitIntent]:
        """
        指示代名詞を解決

        「これ」「それ」「あれ」等の指示代名詞が何を指しているかを特定。
        """
        intents: List[ImplicitIntent] = []

        # 指示代名詞の検出
        detected_pronouns = self._detect_pronouns(message)

        for pronoun, info in detected_pronouns.items():
            # 候補の取得
            candidates = self._get_pronoun_candidates(
                pronoun=pronoun,
                info=info,
                context=context,
            )

            if not candidates:
                # 候補なし：確認が必要
                intents.append(ImplicitIntent(
                    intent_type=ImplicitIntentType.PRONOUN_REFERENCE,
                    inferred_intent="",
                    confidence=0.2,
                    resolved_references=[],
                    original_message=message,
                    reasoning=f"「{pronoun}」の参照先が特定できません",
                    needs_confirmation=True,
                    confirmation_options=[],
                ))
            elif len(candidates) == 1:
                # 候補が1つ：自動解決
                resolved = ResolvedReference(
                    original_expression=pronoun,
                    resolved_value=candidates[0]["value"],
                    reference_type=ImplicitIntentType.PRONOUN_REFERENCE,
                    resolution_strategy=ReferenceResolutionStrategy.IMMEDIATE_CONTEXT,
                    confidence=0.85,
                    source_info=candidates[0],
                    reasoning=f"直近の文脈から「{pronoun}」は「{candidates[0]['value']}」と推定",
                )
                intents.append(ImplicitIntent(
                    intent_type=ImplicitIntentType.PRONOUN_REFERENCE,
                    inferred_intent=f"「{pronoun}」→「{candidates[0]['value']}」",
                    confidence=0.85,
                    resolved_references=[resolved],
                    original_message=message,
                    reasoning=resolved.reasoning,
                    needs_confirmation=False,
                ))
            else:
                # 候補が複数：確認が必要
                resolved = ResolvedReference(
                    original_expression=pronoun,
                    resolved_value="",
                    reference_type=ImplicitIntentType.PRONOUN_REFERENCE,
                    resolution_strategy=ReferenceResolutionStrategy.IMMEDIATE_CONTEXT,
                    confidence=0.5,
                    alternative_candidates=[c["value"] for c in candidates[:4]],
                    reasoning=f"「{pronoun}」の候補が複数あります",
                )
                intents.append(ImplicitIntent(
                    intent_type=ImplicitIntentType.PRONOUN_REFERENCE,
                    inferred_intent="",
                    confidence=0.5,
                    resolved_references=[resolved],
                    original_message=message,
                    reasoning=resolved.reasoning,
                    needs_confirmation=True,
                    confirmation_options=resolved.alternative_candidates,
                ))

        return intents

    def _detect_pronouns(self, message: str) -> Dict[str, Dict[str, str]]:
        """
        メッセージから指示代名詞を検出
        """
        detected = {}

        for pronoun, info in DEMONSTRATIVE_PRONOUNS.items():
            if pronoun in message:
                detected[pronoun] = info

        return detected

    def _get_pronoun_candidates(
        self,
        pronoun: str,
        info: Dict[str, str],
        context: DeepUnderstandingInput,
    ) -> List[Dict[str, Any]]:
        """
        指示代名詞の参照先候補を取得
        """
        candidates = []
        pronoun_type = info.get("type", "")
        distance = info.get("distance", "")

        # 「近称」（これ、この）→ 直前の発話から
        # 「中称」（それ、その）→ 相手の発話から
        # 「遠称」（あれ、あの）→ 過去の会話・共有記憶から

        if pronoun_type in ("thing", "thing_casual", "modifier"):
            # 物事を指す代名詞

            # 直近の会話から候補を抽出
            if context.recent_conversation:
                for i, msg in enumerate(reversed(context.recent_conversation[-5:])):
                    # 距離に応じてフィルタ
                    if distance == "near" and i > 1:
                        continue
                    if distance == "middle" and i > 3:
                        continue

                    content = msg.get("content", "")
                    if content and len(content) > 2:
                        candidates.append({
                            "value": content[:50],
                            "type": "conversation",
                            "source": "recent_conversation",
                            "index": i,
                        })
                        if len(candidates) >= 3:
                            break

            # 直近のタスクから候補を抽出
            if context.recent_tasks:
                for i, task in enumerate(context.recent_tasks[:3]):
                    body = task.get("body", "")
                    if body:
                        candidates.append({
                            "value": body[:50],
                            "type": "task",
                            "source": "recent_tasks",
                            "index": i,
                        })

        elif "人" in pronoun_type or pronoun_type == "direction":
            # 人を指す代名詞

            # 人物情報から候補を抽出
            if context.person_info:
                for person in context.person_info[:5]:
                    name = person.get("name", "")
                    if name:
                        candidates.append({
                            "value": name,
                            "type": "person",
                            "source": "person_info",
                        })

            # 直近の会話から人物を抽出
            if context.recent_conversation:
                for msg in reversed(context.recent_conversation[-3:]):
                    sender = msg.get("sender_name", "")
                    if sender and sender not in [c["value"] for c in candidates]:
                        candidates.append({
                            "value": sender,
                            "type": "person",
                            "source": "conversation_sender",
                        })

        # 重複を除去しつつ上位5件を返す
        seen = set()
        unique_candidates = []
        for c in candidates:
            if c["value"] not in seen:
                seen.add(c["value"])
                unique_candidates.append(c)
                if len(unique_candidates) >= 5:
                    break

        return unique_candidates

    # =========================================================================
    # 省略表現の解決
    # =========================================================================

    async def _resolve_ellipsis(
        self,
        message: str,
        context: DeepUnderstandingInput,
    ) -> List[ImplicitIntent]:
        """
        省略表現を補完

        「完了にして」「送って」等の目的語が省略された表現を補完。
        """
        intents: List[ImplicitIntent] = []

        # 省略パターンの検出
        ellipsis_patterns = [
            (r"(完了|終了)(にして|して|した|させて)", "タスク完了", "task"),
            (r"(送って|送信して|転送して)", "送信", "message"),
            (r"(教えて|教えてください)$", "情報提供", "info"),
            (r"(作って|作成して|追加して)$", "作成", "create"),
            (r"(削除して|消して|取り消して)$", "削除", "delete"),
            (r"(確認して|チェックして|見て)$", "確認", "check"),
        ]

        for pattern, action_name, action_type in ellipsis_patterns:
            if re.search(pattern, message):
                # 補完候補を取得
                candidates = self._get_ellipsis_candidates(
                    action_type=action_type,
                    context=context,
                )

                if not candidates:
                    intents.append(ImplicitIntent(
                        intent_type=ImplicitIntentType.ELLIPSIS_REFERENCE,
                        inferred_intent="",
                        confidence=0.3,
                        original_message=message,
                        reasoning=f"「{action_name}」の対象が特定できません",
                        needs_confirmation=True,
                        confirmation_options=[],
                    ))
                elif len(candidates) == 1:
                    resolved = ResolvedReference(
                        original_expression=action_name,
                        resolved_value=candidates[0]["value"],
                        reference_type=ImplicitIntentType.ELLIPSIS_REFERENCE,
                        resolution_strategy=ReferenceResolutionStrategy.CONVERSATION_HISTORY,
                        confidence=0.8,
                        source_info=candidates[0],
                    )
                    intents.append(ImplicitIntent(
                        intent_type=ImplicitIntentType.ELLIPSIS_REFERENCE,
                        inferred_intent=f"「{candidates[0]['value']}」を{action_name}",
                        confidence=0.8,
                        resolved_references=[resolved],
                        original_message=message,
                        reasoning=f"直近のコンテキストから対象を特定",
                        needs_confirmation=False,
                    ))
                else:
                    resolved = ResolvedReference(
                        original_expression=action_name,
                        resolved_value="",
                        reference_type=ImplicitIntentType.ELLIPSIS_REFERENCE,
                        resolution_strategy=ReferenceResolutionStrategy.CONVERSATION_HISTORY,
                        confidence=0.5,
                        alternative_candidates=[c["value"] for c in candidates[:4]],
                    )
                    intents.append(ImplicitIntent(
                        intent_type=ImplicitIntentType.ELLIPSIS_REFERENCE,
                        inferred_intent="",
                        confidence=0.5,
                        resolved_references=[resolved],
                        original_message=message,
                        reasoning="対象の候補が複数あります",
                        needs_confirmation=True,
                        confirmation_options=resolved.alternative_candidates,
                    ))

        return intents

    def _get_ellipsis_candidates(
        self,
        action_type: str,
        context: DeepUnderstandingInput,
    ) -> List[Dict[str, Any]]:
        """
        省略された目的語の候補を取得
        """
        candidates = []

        if action_type == "task":
            # タスク関連の操作 → 直近のタスクから
            for task in context.recent_tasks[:3]:
                body = task.get("body", "")
                task_id = task.get("task_id", "")
                if body:
                    candidates.append({
                        "value": body[:50],
                        "type": "task",
                        "task_id": task_id,
                    })

        elif action_type == "message":
            # 送信操作 → 直近の会話相手
            if context.recent_conversation:
                for msg in reversed(context.recent_conversation[-3:]):
                    sender = msg.get("sender_name", "")
                    if sender:
                        candidates.append({
                            "value": sender,
                            "type": "person",
                        })
                        break

        elif action_type in ("info", "check"):
            # 情報・確認操作 → 直近の話題
            if context.recent_conversation:
                for msg in reversed(context.recent_conversation[-3:]):
                    content = msg.get("content", "")
                    if content and len(content) > 5:
                        candidates.append({
                            "value": content[:50],
                            "type": "topic",
                        })
                        break

        return candidates

    # =========================================================================
    # 婉曲表現の解釈
    # =========================================================================

    async def _interpret_indirect_expressions(
        self,
        message: str,
        context: DeepUnderstandingInput,
    ) -> List[ImplicitIntent]:
        """
        婉曲表現を解釈

        「できたら見てもらえます？」→「確認をお願いしたい」
        「ちょっと難しいかも」→「否定的な回答」
        """
        intents: List[ImplicitIntent] = []

        # 婉曲的依頼パターンの検出
        for pattern in INDIRECT_REQUEST_PATTERNS:
            if re.search(pattern, message):
                intents.append(ImplicitIntent(
                    intent_type=ImplicitIntentType.IMPLICIT_REQUEST,
                    inferred_intent="依頼・お願い",
                    confidence=0.75,
                    original_message=message,
                    reasoning="婉曲的な依頼表現を検出",
                    needs_confirmation=False,
                ))
                break  # 最初のマッチのみ

        # 婉曲的否定パターンの検出
        for pattern in INDIRECT_NEGATION_PATTERNS:
            if re.search(pattern, message):
                intents.append(ImplicitIntent(
                    intent_type=ImplicitIntentType.IMPLICIT_NEGATION,
                    inferred_intent="否定的・消極的な回答",
                    confidence=0.7,
                    original_message=message,
                    reasoning="婉曲的な否定表現を検出",
                    needs_confirmation=False,
                ))
                break

        # 確認・同意の暗黙表現
        confirmation_patterns = [
            (r"(そうですね|そうだね|確かに|なるほど)", "同意"),
            (r"(まあ|一応|とりあえず)", "消極的同意"),
            (r"(本当ですか|マジ|えっ)", "驚き・疑問"),
        ]

        for pattern, meaning in confirmation_patterns:
            if re.search(pattern, message):
                intents.append(ImplicitIntent(
                    intent_type=ImplicitIntentType.IMPLICIT_CONFIRMATION,
                    inferred_intent=meaning,
                    confidence=0.65,
                    original_message=message,
                    reasoning=f"「{meaning}」の表現を検出",
                    needs_confirmation=False,
                ))

        return intents

    # =========================================================================
    # 文脈依存表現の解決
    # =========================================================================

    async def _resolve_context_dependent(
        self,
        message: str,
        context: DeepUnderstandingInput,
    ) -> List[ImplicitIntent]:
        """
        文脈依存表現を解決

        「いつもの」「例の」「毎週のあれ」等の表現を解決。
        """
        intents: List[ImplicitIntent] = []

        # 文脈依存パターン
        context_patterns = [
            (r"(いつもの|普段の|毎回の)", "習慣的な事項"),
            (r"(例の|あの件の|前の)", "既出の事項"),
            (r"(毎週の|毎月の|定例の)", "定期的な事項"),
        ]

        for pattern, category in context_patterns:
            matches = re.findall(pattern, message)
            if matches:
                # 後続の名詞を抽出
                following = re.search(pattern + r"(.+?)($|[。、！？])", message)
                if following:
                    subject = following.group(2).strip()
                else:
                    subject = ""

                intents.append(ImplicitIntent(
                    intent_type=ImplicitIntentType.CONTEXT_DEPENDENT,
                    inferred_intent=f"{category}: {subject}" if subject else category,
                    confidence=0.6,
                    original_message=message,
                    reasoning=f"「{matches[0]}」は{category}を示唆",
                    needs_confirmation=True,
                    confirmation_options=[],
                ))

        return intents

    # =========================================================================
    # Phase 6: 強化版リゾルバーを使用した解決
    # =========================================================================

    async def _resolve_pronouns_enhanced(
        self,
        message: str,
        context: DeepUnderstandingInput,
    ) -> List[ImplicitIntent]:
        """
        強化版代名詞リゾルバーを使用して指示代名詞を解決

        距離感（コ・ソ・ア系）に基づく高精度な解決を行う。
        """
        intents: List[ImplicitIntent] = []

        if not self._pronoun_resolver:
            return intents

        # メッセージから代名詞を検出
        detected_pronouns = self._detect_pronouns(message)

        for pronoun in detected_pronouns.keys():
            try:
                # 強化版リゾルバーで解決
                result = await self._pronoun_resolver.resolve(pronoun, message)

                if result.needs_confirmation:
                    # 確認が必要
                    resolved = ResolvedReference(
                        original_expression=pronoun,
                        resolved_value="",
                        reference_type=ImplicitIntentType.PRONOUN_REFERENCE,
                        resolution_strategy=ReferenceResolutionStrategy.IMMEDIATE_CONTEXT,
                        confidence=result.confidence,
                        alternative_candidates=result.get_confirmation_options(),
                        reasoning=f"「{pronoun}」の参照先を特定できませんでした（確信度: {result.confidence:.2f}）",
                    )
                    intents.append(ImplicitIntent(
                        intent_type=ImplicitIntentType.PRONOUN_REFERENCE,
                        inferred_intent="",
                        confidence=result.confidence,
                        resolved_references=[resolved],
                        original_message=message,
                        reasoning=resolved.reasoning,
                        needs_confirmation=True,
                        confirmation_options=result.get_confirmation_options(),
                    ))
                elif result.resolved_to:
                    # 解決成功
                    resolved = ResolvedReference(
                        original_expression=pronoun,
                        resolved_value=result.resolved_to,
                        reference_type=ImplicitIntentType.PRONOUN_REFERENCE,
                        resolution_strategy=ReferenceResolutionStrategy.IMMEDIATE_CONTEXT,
                        confidence=result.confidence,
                        reasoning=f"「{pronoun}」は「{result.resolved_to}」を指していると推定（距離感: {result.distance.value if result.distance else 'unknown'}）",
                    )
                    intents.append(ImplicitIntent(
                        intent_type=ImplicitIntentType.PRONOUN_REFERENCE,
                        inferred_intent=f"「{pronoun}」→「{result.resolved_to}」",
                        confidence=result.confidence,
                        resolved_references=[resolved],
                        original_message=message,
                        reasoning=resolved.reasoning,
                        needs_confirmation=False,
                    ))

            except Exception as e:
                logger.warning(f"Enhanced pronoun resolution failed for '{pronoun}': {e}")
                # フォールバック: 通常の解決を試行
                continue

        return intents

    async def _resolve_context_expression_enhanced(
        self,
        message: str,
        context: DeepUnderstandingInput,
    ) -> List[ImplicitIntent]:
        """
        強化版文脈依存表現リゾルバーを使用して解決

        「いつもの」「あの件」「例の」などの表現を高精度で解決する。
        """
        intents: List[ImplicitIntent] = []

        if not self._context_expression_resolver:
            return intents

        try:
            # メッセージ内の文脈依存表現を検出
            detected = self._context_expression_resolver.detect_expressions(message)

            for expression, expr_type in detected:
                # 各表現を解決
                result = await self._context_expression_resolver.resolve(expression, message)

                if result.needs_confirmation:
                    # 確認が必要
                    intents.append(ImplicitIntent(
                        intent_type=ImplicitIntentType.CONTEXT_DEPENDENT,
                        inferred_intent="",
                        confidence=result.confidence,
                        original_message=message,
                        reasoning=f"「{expression}」（{result.expression_type.value}）の参照先を特定できませんでした",
                        needs_confirmation=True,
                        confirmation_options=result.get_confirmation_options(),
                    ))
                elif result.resolved_to:
                    # 解決成功
                    intents.append(ImplicitIntent(
                        intent_type=ImplicitIntentType.CONTEXT_DEPENDENT,
                        inferred_intent=f"「{expression}」→「{result.resolved_to}」",
                        confidence=result.confidence,
                        original_message=message,
                        reasoning=f"「{expression}」は「{result.resolved_to}」を指していると推定（タイプ: {result.expression_type.value}）",
                        needs_confirmation=False,
                    ))

        except Exception as e:
            logger.warning(f"Enhanced context expression resolution failed: {e}")

        return intents

    async def _resolve_person_aliases(
        self,
        message: str,
        context: DeepUnderstandingInput,
    ) -> List[ImplicitIntent]:
        """
        人名エイリアスリゾルバーを使用して人名を解決

        「田中さん」「山田くん」などの敬称付き人名を正式名に解決する。
        """
        intents: List[ImplicitIntent] = []

        if not self._person_alias_resolver:
            return intents

        # メッセージから人名らしきパターンを抽出
        # 「〜さん」「〜くん」「〜ちゃん」などのパターン
        person_patterns = [
            r"([一-龯ァ-ン]{1,4})さん",
            r"([一-龯ァ-ン]{1,4})くん",
            r"([一-龯ァ-ン]{1,4})君",
            r"([一-龯ァ-ン]{1,4})ちゃん",
        ]

        extracted_names = set()
        for pattern in person_patterns:
            matches = re.findall(pattern, message)
            for match in matches:
                # 敬称付きの元の形を保持
                full_match = re.search(rf"{match}(さん|くん|君|ちゃん)", message)
                if full_match:
                    extracted_names.add(full_match.group(0))

        for name_with_honorific in extracted_names:
            try:
                result = await self._person_alias_resolver.resolve(name_with_honorific)

                if result.needs_confirmation:
                    # 確認が必要（複数候補または低確信度）
                    intents.append(ImplicitIntent(
                        intent_type=ImplicitIntentType.PRONOUN_REFERENCE,  # 人名参照として扱う
                        inferred_intent="",
                        confidence=result.confidence,
                        original_message=message,
                        reasoning=f"「{name_with_honorific}」の正式名を特定できませんでした（候補: {len(result.candidates)}件）",
                        needs_confirmation=True,
                        confirmation_options=result.get_confirmation_options(),
                    ))
                elif result.resolved_to:
                    # 解決成功
                    resolved = ResolvedReference(
                        original_expression=name_with_honorific,
                        resolved_value=result.resolved_to,
                        reference_type=ImplicitIntentType.PRONOUN_REFERENCE,
                        resolution_strategy=ReferenceResolutionStrategy.ORGANIZATION_VOCABULARY,
                        confidence=result.confidence,
                        reasoning=f"「{name_with_honorific}」は「{result.resolved_to}」を指していると推定（マッチタイプ: {result.match_type.value if result.match_type else 'unknown'}）",
                    )
                    intents.append(ImplicitIntent(
                        intent_type=ImplicitIntentType.PRONOUN_REFERENCE,
                        inferred_intent=f"「{name_with_honorific}」→「{result.resolved_to}」",
                        confidence=result.confidence,
                        resolved_references=[resolved],
                        original_message=message,
                        reasoning=resolved.reasoning,
                        needs_confirmation=False,
                    ))

            except Exception as e:
                logger.warning(f"Person alias resolution failed for '{name_with_honorific}': {e}")
                continue

        return intents

    # =========================================================================
    # LLMによる高度な推論
    # =========================================================================

    def _needs_llm_inference(self, intents: List[ImplicitIntent]) -> bool:
        """
        LLM推論が必要かどうかを判定
        """
        if not intents:
            return False

        # 確認が必要な意図がある場合、または信頼度が低い場合
        for intent in intents:
            if intent.needs_confirmation:
                return True
            if intent.confidence < INTENT_CONFIDENCE_THRESHOLDS["medium"]:
                return True

        return False

    async def _llm_inference(
        self,
        message: str,
        context: DeepUnderstandingInput,
        existing_intents: List[ImplicitIntent],
    ) -> List[ImplicitIntent]:
        """
        LLMを使った高度な意図推論
        """
        if not self.get_ai_response:
            return []

        try:
            # プロンプトの構築
            prompt = self._build_llm_prompt(message, context, existing_intents)

            # LLM呼び出し
            import asyncio
            if asyncio.iscoroutinefunction(self.get_ai_response):
                response = await self.get_ai_response(prompt)
            else:
                response = self.get_ai_response(prompt)

            if response:
                # レスポンスのパース
                return self._parse_llm_response(response, message)

        except Exception as e:
            logger.warning(f"LLM inference failed: {e}")

        return []

    def _build_llm_prompt(
        self,
        message: str,
        context: DeepUnderstandingInput,
        existing_intents: List[ImplicitIntent],
    ) -> str:
        """
        LLMプロンプトを構築
        """
        context_parts = []

        # 直近の会話
        if context.recent_conversation:
            context_parts.append("【直近の会話】")
            for msg in context.recent_conversation[-5:]:
                role = "ユーザー" if msg.get("role") == "user" else "ソウルくん"
                content = msg.get("content", "")[:100]
                context_parts.append(f"  {role}: {content}")

        # 直近のタスク
        if context.recent_tasks:
            context_parts.append("\n【直近のタスク】")
            for task in context.recent_tasks[:3]:
                body = task.get("body", "")[:50]
                context_parts.append(f"  - {body}")

        # 既存の推論結果
        if existing_intents:
            context_parts.append("\n【既存の推論】")
            for intent in existing_intents:
                context_parts.append(f"  - {intent.intent_type.value}: {intent.inferred_intent}")

        context_text = "\n".join(context_parts) if context_parts else "（コンテキストなし）"

        return f"""以下のユーザーメッセージに含まれる暗黙の意図を分析してください。

【コンテキスト】
{context_text}

【ユーザーのメッセージ】
{message}

【分析項目】
1. 「これ」「それ」「あれ」等の指示代名詞が何を指しているか
2. 省略されている主語・目的語は何か
3. 婉曲表現の真意は何か
4. 「いつもの」「例の」等が何を指しているか

【出力形式】
JSON形式で回答してください：
{{
  "resolved_references": [
    {{"original": "元の表現", "resolved": "解決後の意味", "confidence": 0.0-1.0}}
  ],
  "implicit_intent": "推測された暗黙の意図",
  "confidence": 0.0-1.0,
  "reasoning": "推論の根拠"
}}
"""

    def _parse_llm_response(
        self,
        response: str,
        original_message: str,
    ) -> List[ImplicitIntent]:
        """
        LLMレスポンスをパース
        """
        import json

        try:
            # JSON部分を抽出
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                parsed = json.loads(json_match.group())

                resolved_refs = []
                for ref in parsed.get("resolved_references", []):
                    resolved_refs.append(ResolvedReference(
                        original_expression=ref.get("original", ""),
                        resolved_value=ref.get("resolved", ""),
                        reference_type=ImplicitIntentType.CONTEXT_DEPENDENT,
                        resolution_strategy=ReferenceResolutionStrategy.LLM_INFERENCE,
                        confidence=ref.get("confidence", 0.7),
                        reasoning="LLM推論による解決",
                    ))

                return [ImplicitIntent(
                    intent_type=ImplicitIntentType.CONTEXT_DEPENDENT,
                    inferred_intent=parsed.get("implicit_intent", ""),
                    confidence=parsed.get("confidence", 0.7),
                    resolved_references=resolved_refs,
                    original_message=original_message,
                    reasoning=parsed.get("reasoning", "LLM推論"),
                    needs_confirmation=parsed.get("confidence", 0.7) < 0.6,
                )]

        except json.JSONDecodeError:
            logger.warning("Failed to parse LLM response as JSON")

        return []

    # =========================================================================
    # ヘルパーメソッド
    # =========================================================================

    def _select_primary_intent(
        self,
        intents: List[ImplicitIntent],
    ) -> Optional[ImplicitIntent]:
        """
        最も信頼度の高い意図を選択
        """
        if not intents:
            return None

        return max(intents, key=lambda x: x.confidence)

    def _calculate_overall_confidence(
        self,
        intents: List[ImplicitIntent],
    ) -> float:
        """
        全体の信頼度を計算
        """
        if not intents:
            return 0.0

        # 加重平均（信頼度が高いものに重み付け）
        total_weight = 0.0
        weighted_sum = 0.0

        for intent in intents:
            weight = intent.confidence
            weighted_sum += intent.confidence * weight
            total_weight += weight

        return weighted_sum / total_weight if total_weight > 0 else 0.0

    def _elapsed_ms(self, start_time: float) -> int:
        """経過時間をミリ秒で返す"""
        return int((time.time() - start_time) * 1000)


# =============================================================================
# ファクトリー関数
# =============================================================================

def create_intent_inference_engine(
    get_ai_response_func: Optional[Callable] = None,
    use_llm: bool = True,
    # Phase 6: 強化版リゾルバー
    pronoun_resolver: Optional["EnhancedPronounResolver"] = None,
    person_alias_resolver: Optional["PersonAliasResolver"] = None,
    context_expression_resolver: Optional["ContextExpressionResolver"] = None,
    feature_flags: Optional[Dict[str, bool]] = None,
) -> IntentInferenceEngine:
    """
    IntentInferenceEngineを作成

    Args:
        get_ai_response_func: AI応答生成関数
        use_llm: LLMを使用するかどうか
        pronoun_resolver: 強化版代名詞リゾルバー（オプション）
        person_alias_resolver: 人名エイリアスリゾルバー（オプション）
        context_expression_resolver: 文脈依存表現リゾルバー（オプション）
        feature_flags: Feature Flags（デフォルトは全て無効）

    Returns:
        IntentInferenceEngine: 意図推測エンジン

    Example:
        # 基本的な使い方
        engine = create_intent_inference_engine()

        # Phase 6の強化版リゾルバーを使う場合
        from lib.brain.deep_understanding.pronoun_resolver import create_pronoun_resolver
        from lib.brain.deep_understanding.person_alias import create_person_alias_resolver
        from lib.brain.deep_understanding.context_expression import create_context_expression_resolver

        engine = create_intent_inference_engine(
            pronoun_resolver=create_pronoun_resolver(conversation_history=history),
            person_alias_resolver=create_person_alias_resolver(known_persons=persons),
            context_expression_resolver=create_context_expression_resolver(user_habits=habits),
            feature_flags={
                FEATURE_FLAG_ENHANCED_PRONOUN: True,
                FEATURE_FLAG_PERSON_ALIAS: True,
                FEATURE_FLAG_CONTEXT_EXPRESSION: True,
            },
        )
    """
    return IntentInferenceEngine(
        get_ai_response_func=get_ai_response_func,
        use_llm=use_llm,
        pronoun_resolver=pronoun_resolver,
        person_alias_resolver=person_alias_resolver,
        context_expression_resolver=context_expression_resolver,
        feature_flags=feature_flags,
    )


# =============================================================================
# エクスポート
# =============================================================================

__all__ = [
    "IntentInferenceEngine",
    "create_intent_inference_engine",
    # Feature Flag名もエクスポート
    "FEATURE_FLAG_ENHANCED_PRONOUN",
    "FEATURE_FLAG_PERSON_ALIAS",
    "FEATURE_FLAG_CONTEXT_EXPRESSION",
]
