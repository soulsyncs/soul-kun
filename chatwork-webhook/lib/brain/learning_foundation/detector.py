"""
Phase 2E: 学習基盤 - フィードバック検出

設計書: docs/18_phase2e_learning_foundation.md v1.1.0
セクション: 3. フィードバック検出

ユーザーの発言から「これは教えている」ことを検出する。
"""

from typing import Any, Dict, List, Optional, Tuple

from .constants import (
    CONFIDENCE_THRESHOLD_AUTO_LEARN,
    CONFIDENCE_THRESHOLD_CONFIRM,
    CONFIDENCE_THRESHOLD_MIN,
    LearningCategory,
)
from .models import (
    ConversationContext,
    FeedbackDetectionResult,
    PatternMatch,
)
from .patterns import (
    ALL_PATTERNS,
    PATTERNS_BY_NAME,
    DetectionPattern,
)


class FeedbackDetector:
    """フィードバック検出クラス

    ユーザーの発言から「教えている」ことを検出し、
    学習候補として抽出する。

    Attributes:
        patterns: 検出に使用するパターンリスト
    """

    def __init__(
        self,
        patterns: Optional[List[DetectionPattern]] = None,
        custom_patterns: Optional[List[DetectionPattern]] = None,
    ):
        """初期化

        Args:
            patterns: 使用するパターンリスト（指定しない場合はALL_PATTERNS）
            custom_patterns: 追加のカスタムパターン
        """
        self.patterns = patterns if patterns is not None else ALL_PATTERNS

        # カスタムパターンを追加
        if custom_patterns:
            self.patterns = list(self.patterns) + custom_patterns
            # 優先度順にソート
            self.patterns.sort(key=lambda p: -p.priority)

    def detect(
        self,
        message: str,
        context: Optional[ConversationContext] = None,
    ) -> Optional[FeedbackDetectionResult]:
        """メッセージからフィードバックを検出

        Args:
            message: 検査対象のメッセージ
            context: 会話コンテキスト（省略時は文脈なし）

        Returns:
            検出結果。検出されなかった場合はNone。
        """
        if not message or not message.strip():
            return None

        # 正規化
        normalized_message = self._normalize_message(message)

        # 全パターンを優先度順にチェック
        for pattern in self.patterns:
            # 文脈が必要なパターンで文脈がない場合はスキップ
            if pattern.requires_context and not context:
                continue

            # パターンマッチ
            match_result = pattern.match(normalized_message)
            if match_result:
                # 確信度を計算
                confidence = self._calculate_confidence(
                    pattern, match_result, context
                )

                # 最低閾値以下は無視
                if confidence < CONFIDENCE_THRESHOLD_MIN:
                    continue

                # 抽出情報を整理
                extracted = self._extract_info(
                    pattern, match_result, message, context
                )

                # 検出結果を生成
                return FeedbackDetectionResult(
                    pattern_name=pattern.name,
                    pattern_category=pattern.category,
                    match=PatternMatch(
                        groups=match_result.get("groups", {}),
                        start=match_result.get("start", 0),
                        end=match_result.get("end", 0),
                        matched_text=match_result.get("matched_text", ""),
                    ),
                    extracted=extracted,
                    confidence=confidence,
                    context_support=self._has_context_support(pattern, context),
                    recent_error_support=self._has_error_support(context),
                )

        return None

    def detect_all(
        self,
        message: str,
        context: Optional[ConversationContext] = None,
    ) -> List[FeedbackDetectionResult]:
        """メッセージから全てのフィードバックを検出

        複数のパターンにマッチする可能性がある場合に使用。

        Args:
            message: 検査対象のメッセージ
            context: 会話コンテキスト

        Returns:
            検出結果のリスト（確信度の高い順）
        """
        if not message or not message.strip():
            return []

        normalized_message = self._normalize_message(message)
        results = []

        for pattern in self.patterns:
            if pattern.requires_context and not context:
                continue

            match_result = pattern.match(normalized_message)
            if match_result:
                confidence = self._calculate_confidence(
                    pattern, match_result, context
                )

                if confidence < CONFIDENCE_THRESHOLD_MIN:
                    continue

                extracted = self._extract_info(
                    pattern, match_result, message, context
                )

                results.append(FeedbackDetectionResult(
                    pattern_name=pattern.name,
                    pattern_category=pattern.category,
                    match=PatternMatch(
                        groups=match_result.get("groups", {}),
                        start=match_result.get("start", 0),
                        end=match_result.get("end", 0),
                        matched_text=match_result.get("matched_text", ""),
                    ),
                    extracted=extracted,
                    confidence=confidence,
                    context_support=self._has_context_support(pattern, context),
                    recent_error_support=self._has_error_support(context),
                ))

        # 確信度の高い順にソート
        results.sort(key=lambda r: -r.confidence)
        return results

    def _normalize_message(self, message: str) -> str:
        """メッセージを正規化

        Args:
            message: 元のメッセージ

        Returns:
            正規化されたメッセージ
        """
        # 前後の空白を除去
        normalized = message.strip()

        # 全角スペースを半角に
        normalized = normalized.replace("　", " ")

        # 連続する空白を1つに
        while "  " in normalized:
            normalized = normalized.replace("  ", " ")

        return normalized

    def _calculate_confidence(
        self,
        pattern: DetectionPattern,
        match_result: Dict[str, Any],
        context: Optional[ConversationContext],
    ) -> float:
        """確信度を計算

        Args:
            pattern: マッチしたパターン
            match_result: マッチ結果
            context: 会話コンテキスト

        Returns:
            確信度（0.0-1.0）
        """
        # 基本確信度
        confidence = pattern.base_confidence

        # 文脈サポートによる調整
        if context:
            # 文脈が一致すれば確信度アップ
            if self._has_context_support(pattern, context):
                confidence += 0.1

            # 直前に間違いがあれば確信度アップ
            if self._has_error_support(context):
                confidence += 0.15

            # 直前のソウルくんの応答と関連があれば確信度アップ
            if self._is_related_to_last_response(match_result, context):
                confidence += 0.1

        # マッチの質による調整
        groups = match_result.get("groups", {})

        # 全ての期待グループが取得できていれば確信度アップ
        if pattern.extract_groups:
            extracted_count = sum(
                1 for g in pattern.extract_groups if groups.get(g)
            )
            extraction_ratio = extracted_count / len(pattern.extract_groups)
            confidence += 0.05 * extraction_ratio

        # マッチしたテキストが長いほど確信度アップ（ノイズ除去）
        matched_text = match_result.get("matched_text", "")
        if len(matched_text) > 10:
            confidence += 0.05

        # 上限は1.0
        return min(confidence, 1.0)

    def _has_context_support(
        self,
        pattern: DetectionPattern,
        context: Optional[ConversationContext],
    ) -> bool:
        """文脈サポートがあるか判定

        Args:
            pattern: パターン
            context: 会話コンテキスト

        Returns:
            文脈サポートがある場合True
        """
        if not context:
            return False

        # 直前のメッセージがある場合
        if context.previous_messages:
            # correctionパターンの場合、直前にソウルくんの応答があればサポート
            if pattern.category == LearningCategory.CORRECTION.value:
                return context.soulkun_last_response is not None

        return False

    def _has_error_support(
        self,
        context: Optional[ConversationContext],
    ) -> bool:
        """エラーサポートがあるか判定

        Args:
            context: 会話コンテキスト

        Returns:
            直前にエラーがあった場合True
        """
        if not context:
            return False

        return context.has_recent_error

    def _is_related_to_last_response(
        self,
        match_result: Dict[str, Any],
        context: Optional[ConversationContext],
    ) -> bool:
        """直前のソウルくんの応答と関連があるか判定

        Args:
            match_result: マッチ結果
            context: 会話コンテキスト

        Returns:
            関連がある場合True
        """
        if not context or not context.soulkun_last_response:
            return False

        # マッチした部分に直前の応答に含まれる単語があれば関連あり
        matched_text = match_result.get("matched_text", "")
        groups = match_result.get("groups", {})

        last_response = context.soulkun_last_response.lower()

        # グループの値が直前の応答に含まれているか
        for value in groups.values():
            if value and value.lower() in last_response:
                return True

        return False

    def _extract_info(
        self,
        pattern: DetectionPattern,
        match_result: Dict[str, Any],
        original_message: str,
        context: Optional[ConversationContext],
    ) -> Dict[str, Any]:
        """マッチ結果から学習に必要な情報を抽出

        Args:
            pattern: マッチしたパターン
            match_result: マッチ結果
            original_message: 元のメッセージ
            context: 会話コンテキスト

        Returns:
            抽出された情報の辞書
        """
        groups = match_result.get("groups", {})
        extracted: Dict[str, Any] = {
            "category": pattern.category,
            "original_message": original_message,
        }

        # カテゴリ別の抽出
        if pattern.category == LearningCategory.ALIAS.value:
            extracted.update(self._extract_alias_info(groups, context))

        elif pattern.category == LearningCategory.CORRECTION.value:
            extracted.update(self._extract_correction_info(groups, context))

        elif pattern.category == LearningCategory.RULE.value:
            extracted.update(self._extract_rule_info(groups, context))

        elif pattern.category == LearningCategory.PREFERENCE.value:
            extracted.update(self._extract_preference_info(groups, context))

        elif pattern.category == LearningCategory.FACT.value:
            extracted.update(self._extract_fact_info(groups, context))

        elif pattern.category == LearningCategory.RELATIONSHIP.value:
            extracted.update(self._extract_relationship_info(groups, context))

        elif pattern.category == LearningCategory.PROCEDURE.value:
            extracted.update(self._extract_procedure_info(groups, context))

        elif pattern.category == LearningCategory.CONTEXT.value:
            extracted.update(self._extract_context_info(groups, context))

        return extracted

    def _extract_alias_info(
        self,
        groups: Dict[str, str],
        context: Optional[ConversationContext],
    ) -> Dict[str, Any]:
        """別名情報を抽出"""
        return {
            "type": "alias",
            "from_value": groups.get("from_value", "").strip(),
            "to_value": groups.get("to_value", "").strip(),
            "bidirectional": False,
        }

    def _extract_correction_info(
        self,
        groups: Dict[str, str],
        context: Optional[ConversationContext],
    ) -> Dict[str, Any]:
        """修正情報を抽出"""
        wrong = groups.get("wrong", "").strip()
        correct = groups.get("correct", "").strip()

        # 文脈から間違いを補完
        if not wrong and context and context.soulkun_last_response:
            # 直前のソウルくんの応答から間違いを推測
            wrong = self._infer_wrong_from_context(correct, context)

        return {
            "type": "correction",
            "wrong_pattern": wrong,
            "correct_pattern": correct,
        }

    def _extract_rule_info(
        self,
        groups: Dict[str, str],
        context: Optional[ConversationContext],
    ) -> Dict[str, Any]:
        """ルール情報を抽出"""
        condition = groups.get("condition", "").strip()
        action = groups.get("action", "").strip()
        subject = groups.get("subject", "").strip()
        rule = groups.get("rule", "").strip()

        # 禁止ルールの場合
        if action and not condition:
            return {
                "type": "rule",
                "condition": "常に",
                "action": f"{action}しない",
                "is_prohibition": True,
            }

        # 条件付きルールの場合
        if condition and action:
            return {
                "type": "rule",
                "condition": condition,
                "action": action,
                "is_prohibition": False,
            }

        # ルール明示の場合
        if subject and rule:
            return {
                "type": "rule",
                "condition": subject,
                "action": rule,
                "is_prohibition": False,
            }

        return {
            "type": "rule",
            "condition": condition or subject or "",
            "action": action or rule or "",
        }

    def _extract_preference_info(
        self,
        groups: Dict[str, str],
        context: Optional[ConversationContext],
    ) -> Dict[str, Any]:
        """好み情報を抽出"""
        preference = groups.get("preference", "").strip()

        # ユーザー名を取得
        user_name = ""
        if context and context.user_name:
            user_name = context.user_name

        return {
            "type": "preference",
            "preference": preference,
            "user_name": user_name,
        }

    def _extract_fact_info(
        self,
        groups: Dict[str, str],
        context: Optional[ConversationContext],
    ) -> Dict[str, Any]:
        """事実情報を抽出"""
        subject = groups.get("subject", "").strip()
        value = groups.get("value", "").strip()
        fact = groups.get("fact", "").strip()

        if subject and value:
            return {
                "type": "fact",
                "subject": subject,
                "value": value,
                "description": f"{subject}は{value}",
            }

        if fact:
            return {
                "type": "fact",
                "description": fact,
            }

        return {"type": "fact"}

    def _extract_relationship_info(
        self,
        groups: Dict[str, str],
        context: Optional[ConversationContext],
    ) -> Dict[str, Any]:
        """関係情報を抽出"""
        return {
            "type": "relationship",
            "person1": groups.get("person1", "").strip(),
            "person2": groups.get("person2", "").strip(),
            "relationship": groups.get("relationship", "").strip(),
        }

    def _extract_procedure_info(
        self,
        groups: Dict[str, str],
        context: Optional[ConversationContext],
    ) -> Dict[str, Any]:
        """手順情報を抽出"""
        return {
            "type": "procedure",
            "task": groups.get("task", "").strip(),
            "action": groups.get("action", "").strip(),
        }

    def _extract_context_info(
        self,
        groups: Dict[str, str],
        context: Optional[ConversationContext],
    ) -> Dict[str, Any]:
        """文脈情報を抽出"""
        return {
            "type": "context",
            "period": groups.get("period", "").strip(),
            "context": groups.get("context", "").strip(),
        }

    def _infer_wrong_from_context(
        self,
        correct: str,
        context: ConversationContext,
    ) -> str:
        """文脈から間違いを推測

        直前のソウルくんの応答から、修正された可能性のある部分を抽出。

        Args:
            correct: 正しい値
            context: 会話コンテキスト

        Returns:
            推測された間違い（推測できない場合は空文字）
        """
        if not context.soulkun_last_response:
            return ""

        last_response = context.soulkun_last_response

        # 名前の場合：応答に含まれる「〇〇さん」を探す
        if "さん" in correct:
            import re
            names = re.findall(r"([^\s、。]+さん)", last_response)
            for name in names:
                if name != correct and name != correct + "さん":
                    return str(name)

        # 数値の場合：応答に含まれる数値を探す
        if correct.isdigit():
            import re
            numbers = re.findall(r"(\d+)", last_response)
            for num in numbers:
                if num != correct:
                    return str(num)

        return ""

    def requires_confirmation(self, detection_result: FeedbackDetectionResult) -> bool:
        """確認が必要かどうか判定

        Args:
            detection_result: 検出結果

        Returns:
            確認が必要な場合True
        """
        return (
            detection_result.confidence < CONFIDENCE_THRESHOLD_AUTO_LEARN
            and detection_result.confidence >= CONFIDENCE_THRESHOLD_CONFIRM
        )

    def should_auto_learn(self, detection_result: FeedbackDetectionResult) -> bool:
        """自動学習すべきかどうか判定

        Args:
            detection_result: 検出結果

        Returns:
            自動学習すべき場合True
        """
        return detection_result.confidence >= CONFIDENCE_THRESHOLD_AUTO_LEARN


# ============================================================================
# ファクトリ関数
# ============================================================================

def create_detector(
    custom_patterns: Optional[List[DetectionPattern]] = None,
) -> FeedbackDetector:
    """フィードバック検出器を作成

    Args:
        custom_patterns: 追加のカスタムパターン

    Returns:
        FeedbackDetector インスタンス
    """
    return FeedbackDetector(custom_patterns=custom_patterns)
