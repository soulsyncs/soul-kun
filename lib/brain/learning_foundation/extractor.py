"""
Phase 2E: 学習基盤 - 学習内容抽出

設計書: docs/18_phase2e_learning_foundation.md v1.1.0
セクション: 4. 学習の保存

検出されたフィードバックから学習オブジェクトを生成する。
"""

import json
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
from uuid import uuid4

from .constants import (
    AuthorityLevel,
    LearningCategory,
    LearningScope,
    TriggerType,
    DEFAULT_LEARNED_CONTENT_VERSION,
    DEFAULT_CLASSIFICATION,
)
from .models import (
    ConversationContext,
    FeedbackDetectionResult,
    Learning,
)


class LearningExtractor:
    """学習内容抽出クラス

    フィードバック検出結果から学習オブジェクトを生成する。

    設計書セクション4.2に従い、カテゴリごとに適切な
    learned_content構造を生成する。
    """

    def __init__(self, organization_id: str):
        """初期化

        Args:
            organization_id: 組織ID
        """
        self.organization_id = organization_id

    def extract(
        self,
        detection_result: FeedbackDetectionResult,
        message: str,
        context: Optional[ConversationContext] = None,
        taught_by_account_id: str = "",
        taught_by_name: Optional[str] = None,
        taught_by_authority: str = AuthorityLevel.USER.value,
        room_id: Optional[str] = None,
    ) -> Learning:
        """検出結果から学習オブジェクトを生成

        Args:
            detection_result: フィードバック検出結果
            message: 元のメッセージ
            context: 会話コンテキスト
            taught_by_account_id: 教えた人のアカウントID
            taught_by_name: 教えた人の名前
            taught_by_authority: 教えた人の権限レベル
            room_id: ルームID

        Returns:
            生成された学習オブジェクト
        """
        category = detection_result.pattern_category
        extracted = detection_result.extracted

        # カテゴリ別に学習内容を生成
        learned_content = self._build_learned_content(category, extracted)

        # トリガー情報を決定
        trigger_type, trigger_value = self._determine_trigger(
            category, extracted, learned_content
        )

        # スコープを決定
        scope, scope_target_id = self._determine_scope(
            category, extracted, context, taught_by_account_id, room_id
        )

        # 有効期間を決定
        valid_from, valid_until = self._determine_validity(category, extracted)

        # 学習オブジェクトを生成
        return Learning(
            id=str(uuid4()),
            organization_id=self.organization_id,
            category=category,
            trigger_type=trigger_type,
            trigger_value=trigger_value,
            learned_content=learned_content,
            learned_content_version=DEFAULT_LEARNED_CONTENT_VERSION,
            scope=scope,
            scope_target_id=scope_target_id,
            authority_level=taught_by_authority,
            valid_from=valid_from,
            valid_until=valid_until,
            taught_by_account_id=taught_by_account_id,
            taught_by_name=taught_by_name or (context.user_name if context else None),
            taught_in_room_id=room_id or (context.room_id if context else None),
            source_message=message,
            source_context=context.to_dict() if context else None,
            detection_pattern=detection_result.pattern_name,
            detection_confidence=detection_result.confidence,
            classification=self._determine_classification(category, extracted),
        )

    def _build_learned_content(
        self,
        category: str,
        extracted: Dict[str, Any],
    ) -> Dict[str, Any]:
        """カテゴリに応じたlearned_content構造を生成

        設計書セクション4.2に準拠。

        Args:
            category: 学習カテゴリ
            extracted: 抽出された情報

        Returns:
            learned_content辞書
        """
        if category == LearningCategory.ALIAS.value:
            return self._build_alias_content(extracted)

        elif category == LearningCategory.PREFERENCE.value:
            return self._build_preference_content(extracted)

        elif category == LearningCategory.FACT.value:
            return self._build_fact_content(extracted)

        elif category == LearningCategory.RULE.value:
            return self._build_rule_content(extracted)

        elif category == LearningCategory.CORRECTION.value:
            return self._build_correction_content(extracted)

        elif category == LearningCategory.CONTEXT.value:
            return self._build_context_content(extracted)

        elif category == LearningCategory.RELATIONSHIP.value:
            return self._build_relationship_content(extracted)

        elif category == LearningCategory.PROCEDURE.value:
            return self._build_procedure_content(extracted)

        # デフォルト
        return {
            "type": category,
            "raw": extracted,
        }

    def _build_alias_content(self, extracted: Dict[str, Any]) -> Dict[str, Any]:
        """別名のlearned_content構造を生成

        設計書セクション4.2.1参照
        """
        from_value = extracted.get("from_value", "")
        to_value = extracted.get("to_value", "")

        return {
            "type": "alias",
            "from": from_value,
            "to": to_value,
            "bidirectional": extracted.get("bidirectional", False),
            "description": f"{from_value}は{to_value}の略称",
        }

    def _build_preference_content(self, extracted: Dict[str, Any]) -> Dict[str, Any]:
        """好みのlearned_content構造を生成

        設計書セクション4.2.2参照
        """
        preference = extracted.get("preference", "")
        subject = extracted.get("subject", "形式")
        user_name = extracted.get("user_name", "")

        return {
            "type": "preference",
            "subject": subject,
            "preference": preference,
            "priority": "medium",
            "description": f"{user_name}は{preference}を好む" if user_name else f"{preference}を好む",
        }

    def _build_fact_content(self, extracted: Dict[str, Any]) -> Dict[str, Any]:
        """事実のlearned_content構造を生成

        設計書セクション4.2.3参照
        """
        subject = extracted.get("subject", "")
        value = extracted.get("value", "")
        description = extracted.get("description", "")

        if subject and value:
            description = description or f"{subject}は{value}"

        return {
            "type": "fact",
            "subject": subject,
            "value": value,
            "confidence": "high",
            "source": "ユーザーからの直接教示",
            "description": description,
        }

    def _build_rule_content(self, extracted: Dict[str, Any]) -> Dict[str, Any]:
        """ルールのlearned_content構造を生成

        設計書セクション4.2.4参照
        """
        condition = extracted.get("condition", "")
        action = extracted.get("action", "")
        is_prohibition = extracted.get("is_prohibition", False)

        if is_prohibition:
            description = f"{action}は禁止"
        else:
            description = f"{condition}の時は{action}"

        return {
            "type": "rule",
            "condition": condition,
            "action": action,
            "priority": "high" if is_prohibition else "medium",
            "exceptions": [],
            "is_prohibition": is_prohibition,
            "description": description,
        }

    def _build_correction_content(self, extracted: Dict[str, Any]) -> Dict[str, Any]:
        """修正のlearned_content構造を生成

        設計書セクション4.2.5参照
        """
        wrong_pattern = extracted.get("wrong_pattern", "")
        correct_pattern = extracted.get("correct_pattern", "")

        return {
            "type": "correction",
            "wrong_pattern": wrong_pattern,
            "correct_pattern": correct_pattern,
            "reason": "",
            "description": f"{wrong_pattern}ではなく{correct_pattern}",
        }

    def _build_context_content(self, extracted: Dict[str, Any]) -> Dict[str, Any]:
        """文脈のlearned_content構造を生成

        設計書セクション4.2.6参照
        """
        period = extracted.get("period", "")
        context_value = extracted.get("context", "")

        # 有効期限を推測
        valid_until = None
        if period:
            valid_until = self._estimate_period_end(period)

        content = {
            "type": "context",
            "subject": period,
            "context": context_value,
            "implications": [],
            "description": f"{period}は{context_value}",
        }

        if valid_until:
            content["valid_until"] = valid_until.isoformat()

        return content

    def _build_relationship_content(self, extracted: Dict[str, Any]) -> Dict[str, Any]:
        """関係のlearned_content構造を生成

        設計書セクション4.2.7参照
        """
        person1 = extracted.get("person1", "")
        person2 = extracted.get("person2", "")
        relationship = extracted.get("relationship", "")

        return {
            "type": "relationship",
            "person1": person1,
            "person2": person2,
            "relationship": relationship,
            "notes": "",
            "description": f"{person1}と{person2}は{relationship}",
        }

    def _build_procedure_content(self, extracted: Dict[str, Any]) -> Dict[str, Any]:
        """手順のlearned_content構造を生成

        設計書セクション4.2.8参照
        """
        task = extracted.get("task", "")
        action = extracted.get("action", "")

        return {
            "type": "procedure",
            "task": task,
            "steps": [action] if action else [],
            "notes": "",
            "description": f"{task}は{action}に回す" if action else task,
        }

    def _determine_trigger(
        self,
        category: str,
        extracted: Dict[str, Any],
        learned_content: Dict[str, Any],
    ) -> tuple[str, str]:
        """トリガー情報を決定

        Args:
            category: 学習カテゴリ
            extracted: 抽出された情報
            learned_content: 生成された学習内容

        Returns:
            (trigger_type, trigger_value) のタプル
        """
        # 別名の場合：キーワードトリガー
        if category == LearningCategory.ALIAS.value:
            from_value = learned_content.get("from", "")
            return TriggerType.KEYWORD.value, from_value

        # 修正の場合：パターントリガー
        if category == LearningCategory.CORRECTION.value:
            wrong_pattern = learned_content.get("wrong_pattern", "")
            return TriggerType.PATTERN.value, wrong_pattern

        # ルールの場合：条件トリガー
        if category == LearningCategory.RULE.value:
            condition = learned_content.get("condition", "")
            return TriggerType.CONTEXT.value, condition

        # 好みの場合：常に適用
        if category == LearningCategory.PREFERENCE.value:
            subject = learned_content.get("subject", "")
            return TriggerType.ALWAYS.value, subject or "*"

        # 事実の場合：キーワードトリガー
        if category == LearningCategory.FACT.value:
            subject = learned_content.get("subject", "")
            return TriggerType.KEYWORD.value, subject

        # 関係の場合：キーワードトリガー（両者の名前）
        if category == LearningCategory.RELATIONSHIP.value:
            person1 = learned_content.get("person1", "")
            person2 = learned_content.get("person2", "")
            return TriggerType.KEYWORD.value, f"{person1},{person2}"

        # 手順の場合：キーワードトリガー
        if category == LearningCategory.PROCEDURE.value:
            task = learned_content.get("task", "")
            return TriggerType.KEYWORD.value, task

        # 文脈の場合：キーワードトリガー
        if category == LearningCategory.CONTEXT.value:
            subject = learned_content.get("subject", "")
            return TriggerType.KEYWORD.value, subject

        # デフォルト
        return TriggerType.ALWAYS.value, "*"

    def _determine_scope(
        self,
        category: str,
        extracted: Dict[str, Any],
        context: Optional[ConversationContext],
        taught_by_account_id: str,
        room_id: Optional[str],
    ) -> tuple[str, Optional[str]]:
        """スコープを決定

        Args:
            category: 学習カテゴリ
            extracted: 抽出された情報
            context: 会話コンテキスト
            taught_by_account_id: 教えた人のアカウントID
            room_id: ルームID

        Returns:
            (scope, scope_target_id) のタプル
        """
        # 好みはユーザースコープ
        if category == LearningCategory.PREFERENCE.value:
            return LearningScope.USER.value, taught_by_account_id

        # 文脈は期間限定スコープ
        if category == LearningCategory.CONTEXT.value:
            return LearningScope.TEMPORARY.value, None

        # その他はグローバルスコープ
        return LearningScope.GLOBAL.value, None

    def _determine_validity(
        self,
        category: str,
        extracted: Dict[str, Any],
    ) -> tuple[Optional[datetime], Optional[datetime]]:
        """有効期間を決定

        Args:
            category: 学習カテゴリ
            extracted: 抽出された情報

        Returns:
            (valid_from, valid_until) のタプル
        """
        valid_from = datetime.now()

        # 文脈の場合は期間を推測
        if category == LearningCategory.CONTEXT.value:
            period = extracted.get("period", "")
            valid_until = self._estimate_period_end(period)
            return valid_from, valid_until

        # その他は無期限
        return valid_from, None

    def _estimate_period_end(self, period: str) -> Optional[datetime]:
        """期間の終了日を推測

        Args:
            period: 期間を表す文字列

        Returns:
            推測された終了日（推測できない場合はNone）
        """
        now = datetime.now()

        if "今月" in period:
            # 月末
            if now.month == 12:
                return datetime(now.year + 1, 1, 1) - timedelta(days=1)
            else:
                return datetime(now.year, now.month + 1, 1) - timedelta(days=1)

        if "今週" in period:
            # 週末（日曜日）
            days_until_sunday = 6 - now.weekday()
            return now + timedelta(days=days_until_sunday)

        if "今日" in period:
            # 今日の終わり
            return datetime(now.year, now.month, now.day, 23, 59, 59)

        if "来月" in period:
            # 来月末
            if now.month == 11:
                return datetime(now.year + 1, 1, 1) - timedelta(days=1)
            elif now.month == 12:
                return datetime(now.year + 1, 2, 1) - timedelta(days=1)
            else:
                return datetime(now.year, now.month + 2, 1) - timedelta(days=1)

        if "来週" in period:
            # 来週末
            days_until_sunday = 6 - now.weekday() + 7
            return now + timedelta(days=days_until_sunday)

        return None

    def _determine_classification(
        self,
        category: str,
        extracted: Dict[str, Any],
    ) -> str:
        """機密区分を決定

        Args:
            category: 学習カテゴリ
            extracted: 抽出された情報

        Returns:
            機密区分
        """
        # 関係性は機密性が高い
        if category == LearningCategory.RELATIONSHIP.value:
            return "confidential"

        # 好みも個人情報
        if category == LearningCategory.PREFERENCE.value:
            return "confidential"

        # その他は内部情報
        return DEFAULT_CLASSIFICATION


# ============================================================================
# ファクトリ関数
# ============================================================================

def create_extractor(organization_id: str) -> LearningExtractor:
    """学習内容抽出器を作成

    Args:
        organization_id: 組織ID

    Returns:
        LearningExtractor インスタンス
    """
    return LearningExtractor(organization_id)
