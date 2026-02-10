# lib/brain/deep_understanding/deep_understanding.py
"""
Phase 2I: 理解力強化（Deep Understanding）- 統合クラス

設計書: docs/17_brain_completion_roadmap.md セクション17.3 Phase 2I

このファイルには、深い理解層の全コンポーネントを統合するクラスを実装します。

【Phase 2I の能力】
- 暗黙の意図推測（「これ」が何を指すか）
- 組織文脈の理解（「いつものやつ」の解釈）
- 感情・ニュアンスの読み取り（「ちょっと急いでる」の緊急度判断）

Author: Claude Opus 4.5
Created: 2026-01-27
"""

import logging
import time
from typing import Optional, List, Dict, Any, Callable

from .constants import (
    INTENT_CONFIDENCE_THRESHOLDS,
    FEATURE_FLAG_DEEP_UNDERSTANDING,
    FEATURE_FLAG_IMPLICIT_INTENT,
    FEATURE_FLAG_ORGANIZATION_CONTEXT,
    FEATURE_FLAG_EMOTION_READING,
)
from .models import (
    DeepUnderstandingInput,
    DeepUnderstandingOutput,
    IntentInferenceResult,
    OrganizationContextResult,
    EmotionReadingResult,
    RecoveredContext,
)
from .intent_inference import IntentInferenceEngine, create_intent_inference_engine
from .emotion_reader import EmotionReader, create_emotion_reader
from .vocabulary_manager import VocabularyManager, create_vocabulary_manager
from .history_analyzer import HistoryAnalyzer, create_history_analyzer

logger = logging.getLogger(__name__)


class DeepUnderstanding:
    """
    深い理解層

    ソウルくんの理解力を強化する統合クラス。
    暗黙の意図推測、組織文脈の理解、感情・ニュアンスの読み取りを行う。

    使用例:
        deep_understanding = DeepUnderstanding(
            pool=db_pool,
            organization_id="org_001",
            get_ai_response_func=get_ai_response,
        )

        result = await deep_understanding.understand(
            message="あれどうなった？急いでるんだけど",
            input_context=DeepUnderstandingInput(
                message="あれどうなった？急いでるんだけど",
                organization_id="org_001",
                recent_conversation=[...],
                recent_tasks=[...],
            ),
        )

        # 結果の利用
        print(result.enhanced_message)  # 解決済み参照を含むメッセージ
        print(result.emotion_reading.urgency)  # 緊急度
        print(result.intent_inference.primary_intent)  # 主要な意図
    """

    def __init__(
        self,
        pool: Optional[Any] = None,
        organization_id: str = "",
        get_ai_response_func: Optional[Callable] = None,
        use_llm: bool = True,
        feature_flags: Optional[Dict[str, bool]] = None,
    ):
        """
        Args:
            pool: データベース接続プール
            organization_id: 組織ID
            get_ai_response_func: AI応答生成関数（オプション）
            use_llm: LLMを使用するかどうか
            feature_flags: Feature Flags（オプション）
        """
        self.pool = pool
        self.organization_id = organization_id
        self.get_ai_response = get_ai_response_func
        self.use_llm = use_llm
        self.feature_flags = feature_flags or {}

        # コンポーネントの初期化
        self._intent_inference = create_intent_inference_engine(
            get_ai_response_func=get_ai_response_func,
            use_llm=use_llm,
        )

        self._emotion_reader = create_emotion_reader()

        self._vocabulary_manager = create_vocabulary_manager(
            pool=pool,
            organization_id=organization_id,
        )

        self._history_analyzer = create_history_analyzer(
            pool=pool,
            organization_id=organization_id,
        )

        logger.info(
            f"DeepUnderstanding initialized: "
            f"organization_id={organization_id}, "
            f"use_llm={use_llm}"
        )

    # =========================================================================
    # メインエントリーポイント
    # =========================================================================

    async def understand(
        self,
        message: str,
        input_context: Optional[DeepUnderstandingInput] = None,
    ) -> DeepUnderstandingOutput:
        """
        メッセージを深く理解する

        Args:
            message: ユーザーのメッセージ
            input_context: 深い理解層への入力コンテキスト

        Returns:
            DeepUnderstandingOutput: 深い理解の結果
        """
        start_time = time.time()

        # 入力コンテキストの準備
        if input_context is None:
            input_context = DeepUnderstandingInput(
                message=message,
                organization_id=self.organization_id,
            )
        else:
            input_context.message = message

        try:
            # Feature Flagのチェック
            if not self._is_feature_enabled(FEATURE_FLAG_DEEP_UNDERSTANDING):
                return self._create_disabled_output(message, input_context, start_time)

            errors: List[str] = []
            warnings: List[str] = []

            # Step 1: 会話履歴からの文脈復元
            recovered_context: Optional[RecoveredContext] = None
            try:
                recovered_context = await self._history_analyzer.analyze(
                    message=message,
                    input_context=input_context,
                )
            except Exception as e:
                logger.warning(f"History analysis failed: {type(e).__name__}")
                warnings.append("会話履歴の分析に失敗しました")

            # Step 2: 暗黙の意図推測
            intent_inference: Optional[IntentInferenceResult] = None
            if self._is_feature_enabled(FEATURE_FLAG_IMPLICIT_INTENT):
                try:
                    intent_inference = await self._intent_inference.infer(
                        message=message,
                        input_context=input_context,
                    )
                except Exception as e:
                    logger.warning(f"Intent inference failed: {type(e).__name__}")
                    warnings.append("意図推測に失敗しました")

            # Step 3: 組織文脈の解決
            organization_context: Optional[OrganizationContextResult] = None
            if self._is_feature_enabled(FEATURE_FLAG_ORGANIZATION_CONTEXT):
                try:
                    organization_context = await self._vocabulary_manager.resolve_vocabulary_in_message(
                        message=message,
                        context=input_context,
                    )
                except Exception as e:
                    logger.warning(f"Organization context resolution failed: {type(e).__name__}")
                    warnings.append("組織文脈の解決に失敗しました")

            # Step 4: 感情・ニュアンスの読み取り
            emotion_reading: Optional[EmotionReadingResult] = None
            if self._is_feature_enabled(FEATURE_FLAG_EMOTION_READING):
                try:
                    emotion_reading = await self._emotion_reader.read(
                        message=message,
                        input_context=input_context,
                    )
                except Exception as e:
                    logger.warning(f"Emotion reading failed: {type(e).__name__}")
                    warnings.append("感情読み取りに失敗しました")

            # Step 5: 強化されたメッセージの生成
            enhanced_message = self._generate_enhanced_message(
                original_message=message,
                intent_inference=intent_inference,
                organization_context=organization_context,
            )

            # Step 6: 全体の信頼度を計算
            overall_confidence = self._calculate_overall_confidence(
                intent_inference=intent_inference,
                organization_context=organization_context,
                emotion_reading=emotion_reading,
                recovered_context=recovered_context,
            )

            # Step 7: 確認が必要かどうかを判定
            needs_confirmation, confirmation_reason, confirmation_options = self._determine_confirmation_need(
                intent_inference=intent_inference,
                overall_confidence=overall_confidence,
            )

            # Step 8: 語彙の学習（バックグラウンド）
            await self._learn_vocabulary(message, input_context)

            result = DeepUnderstandingOutput(
                input=input_context,
                intent_inference=intent_inference,
                organization_context=organization_context,
                emotion_reading=emotion_reading,
                recovered_context=recovered_context,
                enhanced_message=enhanced_message,
                overall_confidence=overall_confidence,
                needs_confirmation=needs_confirmation,
                confirmation_reason=confirmation_reason,
                confirmation_options=confirmation_options,
                processing_time_ms=self._elapsed_ms(start_time),
                errors=errors,
                warnings=warnings,
            )

            logger.info(
                f"Deep understanding complete: "
                f"confidence={overall_confidence:.2f}, "
                f"needs_confirmation={needs_confirmation}, "
                f"time={result.processing_time_ms}ms"
            )

            return result

        except Exception as e:
            logger.error(f"Error in deep understanding: {type(e).__name__}")
            return DeepUnderstandingOutput(
                input=input_context,
                enhanced_message=message,
                overall_confidence=0.0,
                needs_confirmation=True,
                confirmation_reason="理解処理中にエラーが発生しました",
                processing_time_ms=self._elapsed_ms(start_time),
                errors=[type(e).__name__],
            )

    # =========================================================================
    # 強化されたメッセージの生成
    # =========================================================================

    def _generate_enhanced_message(
        self,
        original_message: str,
        intent_inference: Optional[IntentInferenceResult],
        organization_context: Optional[OrganizationContextResult],
    ) -> str:
        """
        解決済み参照を含む強化されたメッセージを生成
        """
        enhanced = original_message

        # 意図推測からの解決を適用
        if intent_inference and intent_inference.primary_intent:
            primary = intent_inference.primary_intent
            for ref in primary.resolved_references:
                if ref.resolved_value and ref.original_expression != ref.resolved_value:
                    # 元の表現を解決後の値で置き換え
                    enhanced = enhanced.replace(
                        ref.original_expression,
                        f"{ref.original_expression}（{ref.resolved_value}）",
                    )

        # 組織文脈からの解決を適用
        if organization_context:
            for ctx in organization_context.contexts:
                if ctx.resolved_meaning and ctx.original_expression not in enhanced:
                    # 補足情報を追加
                    enhanced += f" [{ctx.original_expression}={ctx.resolved_meaning}]"

        return enhanced

    # =========================================================================
    # 信頼度と確認の判定
    # =========================================================================

    def _calculate_overall_confidence(
        self,
        intent_inference: Optional[IntentInferenceResult],
        organization_context: Optional[OrganizationContextResult],
        emotion_reading: Optional[EmotionReadingResult],
        recovered_context: Optional[RecoveredContext],
    ) -> float:
        """
        全体の信頼度を計算
        """
        confidences = []

        if intent_inference:
            confidences.append(intent_inference.overall_confidence)

        if organization_context:
            confidences.append(organization_context.overall_confidence)

        if emotion_reading:
            confidences.append(emotion_reading.overall_confidence)

        if recovered_context:
            confidences.append(recovered_context.overall_confidence)

        if not confidences:
            return 0.5

        # 加重平均（意図推測に重み付け）
        weights = [0.4, 0.2, 0.2, 0.2][:len(confidences)]
        weighted_sum = sum(c * w for c, w in zip(confidences, weights))
        total_weight = sum(weights)

        return weighted_sum / total_weight if total_weight > 0 else 0.5

    def _determine_confirmation_need(
        self,
        intent_inference: Optional[IntentInferenceResult],
        overall_confidence: float,
    ) -> tuple:
        """
        確認が必要かどうかを判定

        Returns:
            tuple: (needs_confirmation, reason, options)
        """
        needs_confirmation = False
        reason = ""
        options: List[str] = []

        # 信頼度が低い場合
        if overall_confidence < INTENT_CONFIDENCE_THRESHOLDS["medium"]:
            needs_confirmation = True
            reason = "意図の特定に確信が持てません"

        # 意図推測で確認が必要な場合
        if intent_inference and intent_inference.needs_confirmation:
            needs_confirmation = True
            reason = intent_inference.confirmation_reason or "曖昧な表現があります"

            # 確認用選択肢を収集
            if intent_inference.primary_intent:
                for ref in intent_inference.primary_intent.resolved_references:
                    options.extend(ref.alternative_candidates)
                options.extend(intent_inference.primary_intent.confirmation_options)

        return needs_confirmation, reason, list(dict.fromkeys(options))[:4]

    # =========================================================================
    # 語彙の学習
    # =========================================================================

    async def _learn_vocabulary(
        self,
        message: str,
        input_context: DeepUnderstandingInput,
    ) -> None:
        """
        メッセージから新しい語彙を学習（バックグラウンド）
        """
        try:
            candidates = await self._vocabulary_manager.learn_from_message(
                message=message,
                context=input_context,
            )
            if candidates:
                logger.debug(f"Vocabulary learning candidates: {candidates}")
        except Exception as e:
            logger.debug(f"Vocabulary learning failed: {type(e).__name__}")

    # =========================================================================
    # Feature Flags
    # =========================================================================

    def _is_feature_enabled(self, flag_name: str) -> bool:
        """
        Feature Flagが有効かどうかをチェック
        """
        # デフォルトは有効
        return self.feature_flags.get(flag_name, True)

    def _create_disabled_output(
        self,
        message: str,
        input_context: DeepUnderstandingInput,
        start_time: float,
    ) -> DeepUnderstandingOutput:
        """
        機能が無効な場合の出力を生成
        """
        return DeepUnderstandingOutput(
            input=input_context,
            enhanced_message=message,
            overall_confidence=1.0,  # 機能無効時は確信度1.0
            needs_confirmation=False,
            processing_time_ms=self._elapsed_ms(start_time),
            warnings=["Deep Understanding機能は無効です"],
        )

    # =========================================================================
    # ヘルパーメソッド
    # =========================================================================

    def _elapsed_ms(self, start_time: float) -> int:
        """経過時間をミリ秒で返す"""
        return int((time.time() - start_time) * 1000)

    # =========================================================================
    # コンポーネントへのアクセス
    # =========================================================================

    @property
    def intent_inference(self) -> IntentInferenceEngine:
        """意図推測エンジンへのアクセス"""
        return self._intent_inference

    @property
    def emotion_reader(self) -> EmotionReader:
        """感情読み取りエンジンへのアクセス"""
        return self._emotion_reader

    @property
    def vocabulary_manager(self) -> VocabularyManager:
        """語彙管理へのアクセス"""
        return self._vocabulary_manager

    @property
    def history_analyzer(self) -> HistoryAnalyzer:
        """履歴分析器へのアクセス"""
        return self._history_analyzer


# =============================================================================
# ファクトリー関数
# =============================================================================

def create_deep_understanding(
    pool: Optional[Any] = None,
    organization_id: str = "",
    get_ai_response_func: Optional[Callable] = None,
    use_llm: bool = True,
    feature_flags: Optional[Dict[str, bool]] = None,
) -> DeepUnderstanding:
    """
    DeepUnderstandingを作成

    Args:
        pool: データベース接続プール
        organization_id: 組織ID
        get_ai_response_func: AI応答生成関数
        use_llm: LLMを使用するかどうか
        feature_flags: Feature Flags

    Returns:
        DeepUnderstanding: 深い理解層インスタンス
    """
    return DeepUnderstanding(
        pool=pool,
        organization_id=organization_id,
        get_ai_response_func=get_ai_response_func,
        use_llm=use_llm,
        feature_flags=feature_flags,
    )


# =============================================================================
# エクスポート
# =============================================================================

__all__ = [
    "DeepUnderstanding",
    "create_deep_understanding",
]
