# lib/brain/deep_understanding/emotion_reader.py
"""
Phase 2I: 理解力強化（Deep Understanding）- 感情・ニュアンスの読み取り

設計書: docs/17_brain_completion_roadmap.md セクション17.3 Phase 2I

このファイルには、ユーザーの発話から感情・緊急度・ニュアンスを読み取る機能を実装します。

【主な機能】
- 感情の検出（喜怒哀楽、ストレス等）
- 緊急度の判定（「ちょっと急いでる」の解釈）
- ニュアンスの読み取り（確信度、丁寧さ、トーン）
- 文脈を考慮した感情の補正

Author: Claude Opus 4.5
Created: 2026-01-27
"""

import logging
import re
import time
from typing import Optional, List, Dict, Any, Tuple

from .constants import (
    EmotionCategory,
    UrgencyLevel,
    NuanceType,
    EMOTION_INDICATORS,
    URGENCY_INDICATORS,
    EMOTION_CONFIDENCE_THRESHOLDS,
)
from .models import (
    DetectedEmotion,
    DetectedUrgency,
    DetectedNuance,
    EmotionReadingResult,
    DeepUnderstandingInput,
)

logger = logging.getLogger(__name__)


class EmotionReader:
    """
    感情・ニュアンス読み取りエンジン

    ユーザーの発話から感情、緊急度、ニュアンスを検出し、
    文脈を考慮した解釈を行う。

    使用例:
        reader = EmotionReader()
        result = await reader.read(
            message="ちょっと急いでるんだけど、これお願いできる？",
            input_context=deep_understanding_input,
        )
    """

    def __init__(self):
        """初期化"""
        logger.info("EmotionReader initialized")

    # =========================================================================
    # メインエントリーポイント
    # =========================================================================

    async def read(
        self,
        message: str,
        input_context: DeepUnderstandingInput,
    ) -> EmotionReadingResult:
        """
        感情・ニュアンスを読み取る

        Args:
            message: ユーザーのメッセージ
            input_context: 深い理解層への入力コンテキスト

        Returns:
            EmotionReadingResult: 感情読み取りの結果
        """
        start_time = time.time()

        try:
            # Step 1: 感情の検出
            emotions = self._detect_emotions(message)

            # Step 2: 緊急度の検出
            urgency = self._detect_urgency(message)

            # Step 3: ニュアンスの検出
            nuances = self._detect_nuances(message)

            # Step 4: 文脈を考慮した補正
            emotions, urgency = self._apply_context_correction(
                emotions=emotions,
                urgency=urgency,
                context=input_context,
            )

            # Step 5: 主要な感情を選択
            primary_emotion = self._select_primary_emotion(emotions)

            # Step 6: サマリーの生成
            summary = self._generate_summary(emotions, urgency, nuances)

            # Step 7: 全体の信頼度を計算
            overall_confidence = self._calculate_overall_confidence(
                emotions=emotions,
                urgency=urgency,
                nuances=nuances,
            )

            result = EmotionReadingResult(
                emotions=emotions,
                primary_emotion=primary_emotion,
                urgency=urgency,
                nuances=nuances,
                original_message=message,
                overall_confidence=overall_confidence,
                processing_time_ms=self._elapsed_ms(start_time),
                summary=summary,
            )

            logger.info(
                f"Emotion reading complete: "
                f"emotions={len(emotions)}, "
                f"primary={primary_emotion.category.value if primary_emotion else 'none'}, "
                f"urgency={urgency.level.value if urgency else 'none'}"
            )

            return result

        except Exception as e:
            logger.error(f"Error in emotion reading: {e}")
            return EmotionReadingResult(
                emotions=[],
                urgency=None,
                nuances=[],
                original_message=message,
                overall_confidence=0.0,
                processing_time_ms=self._elapsed_ms(start_time),
                summary="感情の読み取りに失敗しました",
            )

    # =========================================================================
    # 感情の検出
    # =========================================================================

    def _detect_emotions(self, message: str) -> List[DetectedEmotion]:
        """
        メッセージから感情を検出
        """
        detected_emotions: List[DetectedEmotion] = []
        normalized = message.lower()

        for emotion_value, indicators in EMOTION_INDICATORS.items():
            keywords = indicators.get("keywords", [])
            expressions = indicators.get("expressions", [])
            intensity_words = indicators.get("intensity", [])

            # キーワードマッチ
            matched_keywords = []
            for keyword in keywords:
                if keyword in message or keyword in normalized:
                    matched_keywords.append(keyword)

            # 表現マッチ（絵文字、顔文字等）
            matched_expressions = []
            for expr in expressions:
                if expr in message:
                    matched_expressions.append(expr)

            # 強度修飾語のチェック
            has_intensity = any(word in message for word in intensity_words)

            # マッチがあれば感情として検出
            total_matches = len(matched_keywords) + len(matched_expressions)
            if total_matches > 0:
                # 信頼度の計算
                confidence = min(0.5 + (total_matches * 0.15), 0.95)

                # 強度の計算
                intensity = 0.5
                if has_intensity:
                    intensity = 0.8
                if total_matches >= 3:
                    intensity = min(intensity + 0.2, 1.0)

                try:
                    category = EmotionCategory(emotion_value)
                except ValueError:
                    continue

                detected_emotions.append(DetectedEmotion(
                    category=category,
                    intensity=intensity,
                    confidence=confidence,
                    indicators=matched_keywords + matched_expressions,
                    reasoning=f"キーワード「{', '.join(matched_keywords[:3])}」を検出",
                ))

        # 追加のパターンベース検出
        additional = self._detect_emotion_patterns(message)
        detected_emotions.extend(additional)

        # 重複を除去（同じカテゴリは信頼度が高い方を残す）
        return self._deduplicate_emotions(detected_emotions)

    def _detect_emotion_patterns(self, message: str) -> List[DetectedEmotion]:
        """
        パターンベースの感情検出
        """
        emotions: List[DetectedEmotion] = []

        # 繰り返し表現（強い感情の表れ）
        if re.search(r'(.)\1{2,}', message):  # 同じ文字の3回以上の繰り返し
            # 文脈から感情を推定
            if any(word in message for word in ["うれしい", "やった", "最高"]):
                emotions.append(DetectedEmotion(
                    category=EmotionCategory.EXCITED,
                    intensity=0.9,
                    confidence=0.7,
                    indicators=["文字の繰り返し"],
                    reasoning="強調表現から興奮を検出",
                ))

        # 疑問符の連続（困惑・疑問）
        if re.search(r'\?{2,}|？{2,}', message):
            emotions.append(DetectedEmotion(
                category=EmotionCategory.CONFUSED,
                intensity=0.7,
                confidence=0.65,
                indicators=["複数の疑問符"],
                reasoning="複数の疑問符から困惑を検出",
            ))

        # 感嘆符の連続（強い感情）
        if re.search(r'!{2,}|！{2,}', message):
            emotions.append(DetectedEmotion(
                category=EmotionCategory.EXCITED,
                intensity=0.8,
                confidence=0.6,
                indicators=["複数の感嘆符"],
                reasoning="複数の感嘆符から強い感情を検出",
            ))

        # 省略記号（ためらい、困惑）
        if re.search(r'\.{3,}|…+', message):
            emotions.append(DetectedEmotion(
                category=EmotionCategory.UNCERTAIN,
                intensity=0.5,
                confidence=0.55,
                indicators=["省略記号"],
                reasoning="省略記号からためらいを検出",
            ))

        # 敬語の崩れ（フラストレーション）
        if re.search(r'(なんで|どうして|ふざけ)', message) and not re.search(r'(ですか|ますか|でしょうか)', message):
            emotions.append(DetectedEmotion(
                category=EmotionCategory.FRUSTRATED,
                intensity=0.7,
                confidence=0.6,
                indicators=["敬語の崩れ"],
                reasoning="敬語を使わない疑問からフラストレーションを検出",
            ))

        return emotions

    def _deduplicate_emotions(
        self,
        emotions: List[DetectedEmotion],
    ) -> List[DetectedEmotion]:
        """
        感情の重複を除去（同じカテゴリは信頼度が高い方を残す）
        """
        by_category: Dict[EmotionCategory, DetectedEmotion] = {}

        for emotion in emotions:
            existing = by_category.get(emotion.category)
            if existing is None or emotion.confidence > existing.confidence:
                by_category[emotion.category] = emotion

        return list(by_category.values())

    # =========================================================================
    # 緊急度の検出
    # =========================================================================

    def _detect_urgency(self, message: str) -> Optional[DetectedUrgency]:
        """
        メッセージから緊急度を検出
        """
        # 各緊急度レベルのキーワードをチェック
        for level_value in [
            UrgencyLevel.CRITICAL.value,
            UrgencyLevel.VERY_HIGH.value,
            UrgencyLevel.HIGH.value,
            UrgencyLevel.MEDIUM.value,
            UrgencyLevel.LOW.value,
            UrgencyLevel.VERY_LOW.value,
        ]:
            keywords = URGENCY_INDICATORS.get(level_value, [])
            matched = []

            for keyword in keywords:
                if keyword in message:
                    matched.append(keyword)

            if matched:
                level = UrgencyLevel(level_value)

                # 推定期限（時間）
                deadline_hours = self._estimate_deadline_hours(level)

                # 信頼度の計算
                confidence = 0.7 + (len(matched) * 0.1)
                confidence = min(confidence, 0.95)

                return DetectedUrgency(
                    level=level,
                    confidence=confidence,
                    estimated_deadline_hours=deadline_hours,
                    indicators=matched,
                    reasoning=f"緊急度キーワード「{', '.join(matched[:2])}」を検出",
                )

        # 緊急度キーワードがない場合は中程度と推定
        return DetectedUrgency(
            level=UrgencyLevel.MEDIUM,
            confidence=0.5,
            estimated_deadline_hours=None,
            indicators=[],
            reasoning="緊急度を示す明確なキーワードなし",
        )

    def _estimate_deadline_hours(self, level: UrgencyLevel) -> float:
        """
        緊急度レベルから推定期限を計算
        """
        mapping = {
            UrgencyLevel.CRITICAL: 1.0,
            UrgencyLevel.VERY_HIGH: 4.0,
            UrgencyLevel.HIGH: 8.0,
            UrgencyLevel.MEDIUM: 48.0,
            UrgencyLevel.LOW: 168.0,  # 1週間
            UrgencyLevel.VERY_LOW: 720.0,  # 1ヶ月
        }
        return mapping.get(level, 48.0)

    # =========================================================================
    # ニュアンスの検出
    # =========================================================================

    def _detect_nuances(self, message: str) -> List[DetectedNuance]:
        """
        メッセージからニュアンスを検出
        """
        nuances: List[DetectedNuance] = []

        # 確信度の検出
        certainty_nuance = self._detect_certainty(message)
        if certainty_nuance:
            nuances.append(certainty_nuance)

        # 丁寧さの検出
        formality_nuance = self._detect_formality(message)
        if formality_nuance:
            nuances.append(formality_nuance)

        # トーンの検出
        tone_nuance = self._detect_tone(message)
        if tone_nuance:
            nuances.append(tone_nuance)

        return nuances

    def _detect_certainty(self, message: str) -> Optional[DetectedNuance]:
        """
        確信度のニュアンスを検出
        """
        high_certainty_patterns = [
            r"(絶対|必ず|確実|間違いなく|100%|まちがいない)",
            r"(断言|確信|自信あり)",
        ]

        medium_certainty_patterns = [
            r"(たぶん|おそらく|多分|恐らく|思う|はず)",
        ]

        low_certainty_patterns = [
            r"(もしかしたら|ひょっとしたら|かもしれない|わからない|不明)",
            r"(自信ない|確証ない)",
        ]

        for pattern in high_certainty_patterns:
            if re.search(pattern, message):
                return DetectedNuance(
                    nuance_type=NuanceType.CERTAINTY_HIGH,
                    confidence=0.8,
                    indicators=[pattern],
                    reasoning="高い確信度を示す表現を検出",
                )

        for pattern in medium_certainty_patterns:
            if re.search(pattern, message):
                return DetectedNuance(
                    nuance_type=NuanceType.CERTAINTY_MEDIUM,
                    confidence=0.7,
                    indicators=[pattern],
                    reasoning="中程度の確信度を示す表現を検出",
                )

        for pattern in low_certainty_patterns:
            if re.search(pattern, message):
                return DetectedNuance(
                    nuance_type=NuanceType.CERTAINTY_LOW,
                    confidence=0.75,
                    indicators=[pattern],
                    reasoning="低い確信度を示す表現を検出",
                )

        return None

    def _detect_formality(self, message: str) -> Optional[DetectedNuance]:
        """
        丁寧さのニュアンスを検出
        """
        # 敬語のチェック
        formal_patterns = [
            r"(です|ます|ございます|いたします|存じます)",
            r"(お願いいたします|ご確認ください|恐れ入りますが)",
        ]

        casual_patterns = [
            r"(だよ|だね|じゃん|っす|だぜ|だな)",
            r"(やって|頼む|教えて$)",
        ]

        formal_count = sum(1 for p in formal_patterns if re.search(p, message))
        casual_count = sum(1 for p in casual_patterns if re.search(p, message))

        if formal_count > casual_count and formal_count > 0:
            return DetectedNuance(
                nuance_type=NuanceType.FORMAL,
                confidence=0.7 + (formal_count * 0.1),
                indicators=["敬語使用"],
                reasoning="敬語の使用からフォーマルなトーンを検出",
            )
        elif casual_count > formal_count and casual_count > 0:
            return DetectedNuance(
                nuance_type=NuanceType.CASUAL,
                confidence=0.7 + (casual_count * 0.1),
                indicators=["カジュアル表現"],
                reasoning="カジュアルな表現を検出",
            )

        return None

    def _detect_tone(self, message: str) -> Optional[DetectedNuance]:
        """
        トーンのニュアンスを検出
        """
        # ポジティブなトーン
        positive_patterns = [
            r"(嬉しい|楽しい|ありがとう|助かる|良い|素晴らしい|最高)",
            r"(♪|☆|★|😊|👍)",
        ]

        # ネガティブなトーン
        negative_patterns = [
            r"(残念|困った|問題|エラー|失敗|だめ|ダメ)",
            r"(😢|😞|💔)",
        ]

        # 皮肉・ユーモア
        sarcastic_patterns = [
            r"(笑|www|ｗｗｗ|草)",
            r"(\(笑\)|\(爆\))",
        ]

        positive_count = sum(1 for p in positive_patterns if re.search(p, message))
        negative_count = sum(1 for p in negative_patterns if re.search(p, message))
        sarcastic_count = sum(1 for p in sarcastic_patterns if re.search(p, message))

        if positive_count > negative_count and positive_count > sarcastic_count:
            return DetectedNuance(
                nuance_type=NuanceType.POSITIVE,
                confidence=0.65 + (positive_count * 0.1),
                indicators=["ポジティブ表現"],
                reasoning="ポジティブなトーンを検出",
            )
        elif negative_count > positive_count and negative_count > sarcastic_count:
            return DetectedNuance(
                nuance_type=NuanceType.NEGATIVE,
                confidence=0.65 + (negative_count * 0.1),
                indicators=["ネガティブ表現"],
                reasoning="ネガティブなトーンを検出",
            )
        elif sarcastic_count > 0:
            return DetectedNuance(
                nuance_type=NuanceType.HUMOROUS,
                confidence=0.6 + (sarcastic_count * 0.1),
                indicators=["ユーモア表現"],
                reasoning="ユーモアのあるトーンを検出",
            )

        return None

    # =========================================================================
    # 文脈補正
    # =========================================================================

    def _apply_context_correction(
        self,
        emotions: List[DetectedEmotion],
        urgency: Optional[DetectedUrgency],
        context: DeepUnderstandingInput,
    ) -> Tuple[List[DetectedEmotion], Optional[DetectedUrgency]]:
        """
        文脈を考慮して感情・緊急度を補正
        """
        # 直近の会話の感情トレンドを考慮
        if context.recent_conversation:
            emotion_trend = self._analyze_emotion_trend(context.recent_conversation)

            if emotion_trend:
                # 突然の感情変化は信頼度を下げる
                for emotion in emotions:
                    if emotion.category.value != emotion_trend:
                        emotion.confidence *= 0.9

        # タスクの状況を考慮
        if context.recent_tasks:
            # 未完了タスクが多い場合はストレスを強化
            incomplete_count = sum(
                1 for task in context.recent_tasks
                if task.get("status") != "done"
            )
            if incomplete_count >= 3:
                # ストレス感情がある場合は強化
                for emotion in emotions:
                    if emotion.category == EmotionCategory.STRESSED:
                        emotion.intensity = min(emotion.intensity * 1.2, 1.0)
                        emotion.confidence = min(emotion.confidence * 1.1, 0.95)

        return emotions, urgency

    def _analyze_emotion_trend(
        self,
        recent_conversation: List[Dict[str, Any]],
    ) -> Optional[str]:
        """
        直近の会話から感情のトレンドを分析
        """
        emotion_counts: Dict[str, int] = {}

        for msg in recent_conversation[-5:]:
            content = msg.get("content", "")
            # 簡易的な感情検出
            for emotion_value, indicators in EMOTION_INDICATORS.items():
                keywords = indicators.get("keywords", [])
                if any(kw in content for kw in keywords):
                    emotion_counts[emotion_value] = emotion_counts.get(emotion_value, 0) + 1

        if emotion_counts:
            return max(emotion_counts, key=emotion_counts.get)

        return None

    # =========================================================================
    # ヘルパーメソッド
    # =========================================================================

    def _select_primary_emotion(
        self,
        emotions: List[DetectedEmotion],
    ) -> Optional[DetectedEmotion]:
        """
        主要な感情を選択
        """
        if not emotions:
            return None

        # 信頼度と強度の組み合わせで選択
        return max(emotions, key=lambda e: e.confidence * e.intensity)

    def _generate_summary(
        self,
        emotions: List[DetectedEmotion],
        urgency: Optional[DetectedUrgency],
        nuances: List[DetectedNuance],
    ) -> str:
        """
        感情読み取りのサマリーを生成
        """
        parts = []

        if emotions:
            primary = max(emotions, key=lambda e: e.confidence)
            emotion_names = {
                EmotionCategory.HAPPY: "喜び",
                EmotionCategory.EXCITED: "興奮・期待",
                EmotionCategory.GRATEFUL: "感謝",
                EmotionCategory.FRUSTRATED: "困惑・イライラ",
                EmotionCategory.ANXIOUS: "不安",
                EmotionCategory.ANGRY: "怒り",
                EmotionCategory.STRESSED: "ストレス",
                EmotionCategory.CONFUSED: "困惑",
                EmotionCategory.NEUTRAL: "中立",
            }
            emotion_name = emotion_names.get(primary.category, primary.category.value)
            intensity_desc = "強い" if primary.intensity > 0.7 else "やや" if primary.intensity > 0.4 else "軽い"
            parts.append(f"{intensity_desc}{emotion_name}を感じています")

        if urgency and urgency.level in (UrgencyLevel.CRITICAL, UrgencyLevel.VERY_HIGH, UrgencyLevel.HIGH):
            urgency_names = {
                UrgencyLevel.CRITICAL: "非常に急いでいる様子",
                UrgencyLevel.VERY_HIGH: "急いでいる様子",
                UrgencyLevel.HIGH: "やや急いでいる様子",
            }
            parts.append(urgency_names.get(urgency.level, ""))

        if nuances:
            for nuance in nuances[:2]:
                if nuance.nuance_type == NuanceType.FORMAL:
                    parts.append("丁寧な口調")
                elif nuance.nuance_type == NuanceType.CASUAL:
                    parts.append("カジュアルな口調")
                elif nuance.nuance_type == NuanceType.CERTAINTY_LOW:
                    parts.append("確信が低そう")

        return "、".join(parts) if parts else "特に強い感情は検出されませんでした"

    def _calculate_overall_confidence(
        self,
        emotions: List[DetectedEmotion],
        urgency: Optional[DetectedUrgency],
        nuances: List[DetectedNuance],
    ) -> float:
        """
        全体の信頼度を計算
        """
        confidences = []

        for emotion in emotions:
            confidences.append(emotion.confidence)

        if urgency:
            confidences.append(urgency.confidence)

        for nuance in nuances:
            confidences.append(nuance.confidence)

        if not confidences:
            return 0.5

        return sum(confidences) / len(confidences)

    def _elapsed_ms(self, start_time: float) -> int:
        """経過時間をミリ秒で返す"""
        return int((time.time() - start_time) * 1000)


# =============================================================================
# ファクトリー関数
# =============================================================================

def create_emotion_reader() -> EmotionReader:
    """
    EmotionReaderを作成

    Returns:
        EmotionReader: 感情読み取りエンジン
    """
    return EmotionReader()


# =============================================================================
# エクスポート
# =============================================================================

__all__ = [
    "EmotionReader",
    "create_emotion_reader",
]
