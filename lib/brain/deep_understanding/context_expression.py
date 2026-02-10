# lib/brain/deep_understanding/context_expression.py
"""
文脈依存表現リゾルバー

「いつもの」「あの件」「例の」などの文脈依存表現を解決する。

【対象表現】
- 「いつもの」→ ユーザーの習慣的な選択
- 「あの件」→ 最近話題になった案件
- 「例の」→ 共有済みの話題
- 「この前の」→ 過去の特定イベント

【設計書参照】
- docs/13_brain_architecture.md セクション6「理解層」
  - 6.4 曖昧表現の解決パターン（省略、相対時間）
- docs/17_brain_completion_roadmap.md セクション17.3 Phase 2I「理解力強化」
  - 組織文脈の理解（「いつものやつ」の解釈）
- CLAUDE.md セクション4「意図の取り違え検知ルール」
  - 確信度70%未満で確認質問

Author: Claude Opus 4.5
Created: 2026-01-29
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, List, Dict, Any, Protocol, Tuple

from lib.brain.constants import CONFIRMATION_THRESHOLD, JST

logger = logging.getLogger(__name__)


# =============================================================================
# 定数
# =============================================================================


# 習慣的表現パターン
HABITUAL_PATTERNS: List[str] = [
    "いつもの",
    "いつも通り",
    "いつもどおり",
    "普段の",
    "いつもみたいに",
    "毎回の",
    "定番の",
]

# 参照表現パターン
REFERENCE_PATTERNS: List[str] = [
    "あの件",
    "この件",
    "その件",
    "例の件",
    "例の",
    "例のやつ",
    "あのやつ",
    "さっきの",
    "先ほどの",
]

# 時間参照表現パターン
TEMPORAL_PATTERNS: List[str] = [
    "この前の",
    "先日の",
    "前回の",
    "前の",
    "昨日の",
    "先週の",
    "先月の",
]

# 最近参照表現パターン
RECENT_PATTERNS: List[str] = [
    "さっきの",
    "先ほどの",
    "今の",
    "最近の",
    "ついさっきの",
]


# =============================================================================
# Enum定義
# =============================================================================


class ExpressionType(Enum):
    """文脈依存表現のタイプ"""
    HABITUAL = "habitual"  # 習慣的表現（いつもの）
    REFERENCE = "reference"  # 参照表現（あの件）
    TEMPORAL = "temporal"  # 時間参照表現（この前の）
    RECENT = "recent"  # 最近参照表現（さっきの）
    UNKNOWN = "unknown"  # 不明


# =============================================================================
# データクラス
# =============================================================================


@dataclass
class ContextCandidate:
    """
    文脈依存表現の解決候補

    Attributes:
        entity: 解決先のエンティティ
        confidence: 確信度（0.0-1.0）
        source: 候補の出典
        expression_type: 表現タイプ
        context_snippet: 文脈の抜粋
        timestamp: 候補に関連する時刻
    """
    entity: str
    confidence: float = 0.5
    source: str = "unknown"
    expression_type: ExpressionType = ExpressionType.UNKNOWN
    context_snippet: Optional[str] = None
    timestamp: Optional[datetime] = None


@dataclass
class ContextResolutionResult:
    """
    文脈依存表現解決の結果

    Attributes:
        expression: 入力された表現
        resolved_to: 解決結果（Noneの場合は解決失敗）
        confidence: 確信度
        needs_confirmation: 確認が必要か
        candidates: 候補リスト（確認時に使用）
        expression_type: 表現タイプ
    """
    expression: str
    resolved_to: Optional[str] = None
    confidence: float = 0.0
    needs_confirmation: bool = False
    candidates: List[ContextCandidate] = field(default_factory=list)
    expression_type: ExpressionType = ExpressionType.UNKNOWN

    def get_confirmation_options(self) -> List[str]:
        """確認用の選択肢を取得"""
        return [c.entity for c in self.candidates[:4]]  # 最大4つ


# =============================================================================
# Protocol定義（依存注入用）
# =============================================================================


class HabitLookupProtocol(Protocol):
    """習慣情報検索のプロトコル"""

    def get_user_habit(self, user_id: str, context: str) -> Optional[str]:
        """ユーザーの習慣を取得"""
        ...


class TopicHistoryProtocol(Protocol):
    """話題履歴のプロトコル"""

    def get_recent_topics(self, limit: int = 10) -> List[Dict[str, Any]]:
        """最近の話題を取得"""
        ...


# =============================================================================
# ContextExpressionResolver クラス
# =============================================================================


class ContextExpressionResolver:
    """
    文脈依存表現リゾルバー

    対象表現:
    - 「いつもの」→ ユーザーの習慣的な選択
    - 「あの件」→ 最近話題になった案件
    - 「例の」→ 共有済みの話題
    - 「この前の」→ 過去の特定イベント

    使用例:
        resolver = ContextExpressionResolver(
            conversation_history=recent_messages,
            user_habits={"coffee_order": "アメリカン"},
        )

        result = await resolver.resolve("いつもの", "いつものでお願い")
        if result.needs_confirmation:
            options = result.get_confirmation_options()
    """

    # 確認が必要な閾値（CLAUDE.md セクション4-1準拠）
    CONFIRMATION_THRESHOLD = CONFIRMATION_THRESHOLD

    def __init__(
        self,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        user_habits: Optional[Dict[str, str]] = None,
        recent_topics: Optional[List[Dict[str, Any]]] = None,
        habit_lookup: Optional[HabitLookupProtocol] = None,
        topic_history: Optional[TopicHistoryProtocol] = None,
        user_id: Optional[str] = None,
    ):
        """
        Args:
            conversation_history: 会話履歴（新しい順）
            user_habits: ユーザーの習慣（コンテキスト → 値）
            recent_topics: 最近の話題
            habit_lookup: 習慣検索サービス（オプション）
            topic_history: 話題履歴サービス（オプション）
            user_id: ユーザーID
        """
        self._history = conversation_history or []
        self._habits = user_habits or {}
        self._topics = recent_topics or []
        self._habit_lookup = habit_lookup
        self._topic_history = topic_history
        self._user_id = user_id

        logger.debug(
            f"ContextExpressionResolver initialized: "
            f"history={len(self._history)}, "
            f"habits={len(self._habits)}, "
            f"topics={len(self._topics)}"
        )

    # =========================================================================
    # メインエントリーポイント
    # =========================================================================

    async def resolve(
        self,
        expression: str,
        message: str,
    ) -> ContextResolutionResult:
        """
        文脈依存表現を解決

        Args:
            expression: 解決対象の表現
            message: 表現が含まれるメッセージ全文

        Returns:
            ContextResolutionResult: 解決結果
        """
        # 1. 表現タイプを判定
        expression_type = self._classify_expression(expression)

        logger.debug(
            f"Resolving expression '{expression}': type={expression_type.value}"
        )

        # 2. タイプに基づいて候補を収集
        candidates = await self._collect_candidates(expression, message, expression_type)

        # 3. 結果を構築
        return self._build_result(expression, expression_type, candidates)

    def resolve_sync(
        self,
        expression: str,
        message: str,
    ) -> ContextResolutionResult:
        """同期版のresolve（テスト用）"""
        import asyncio
        return asyncio.get_event_loop().run_until_complete(
            self.resolve(expression, message)
        )

    # =========================================================================
    # 表現分類
    # =========================================================================

    def _classify_expression(self, expression: str) -> ExpressionType:
        """表現タイプを分類"""
        # 習慣的表現
        for pattern in HABITUAL_PATTERNS:
            if pattern in expression:
                return ExpressionType.HABITUAL

        # 最近参照表現（RECENTを先にチェック）
        for pattern in RECENT_PATTERNS:
            if pattern in expression:
                return ExpressionType.RECENT

        # 参照表現
        for pattern in REFERENCE_PATTERNS:
            if pattern in expression:
                return ExpressionType.REFERENCE

        # 時間参照表現
        for pattern in TEMPORAL_PATTERNS:
            if pattern in expression:
                return ExpressionType.TEMPORAL

        return ExpressionType.UNKNOWN

    def detect_expressions(self, message: str) -> List[Tuple[str, ExpressionType]]:
        """
        メッセージ内の文脈依存表現を検出

        Args:
            message: 検索対象のメッセージ

        Returns:
            (表現, タイプ) のリスト
        """
        found = []

        # 全パターンをチェック
        all_patterns = [
            (HABITUAL_PATTERNS, ExpressionType.HABITUAL),
            (RECENT_PATTERNS, ExpressionType.RECENT),
            (REFERENCE_PATTERNS, ExpressionType.REFERENCE),
            (TEMPORAL_PATTERNS, ExpressionType.TEMPORAL),
        ]

        for patterns, expr_type in all_patterns:
            for pattern in patterns:
                if pattern in message:
                    found.append((pattern, expr_type))

        return found

    # =========================================================================
    # 候補収集
    # =========================================================================

    async def _collect_candidates(
        self,
        expression: str,
        message: str,
        expression_type: ExpressionType,
    ) -> List[ContextCandidate]:
        """
        タイプに基づいて候補を収集

        Args:
            expression: 表現
            message: メッセージ全文
            expression_type: 表現タイプ

        Returns:
            候補リスト
        """
        candidates: List[ContextCandidate] = []

        if expression_type == ExpressionType.HABITUAL:
            candidates = await self._collect_habitual_candidates(expression, message)
        elif expression_type == ExpressionType.REFERENCE:
            candidates = await self._collect_reference_candidates(expression, message)
        elif expression_type == ExpressionType.TEMPORAL:
            candidates = await self._collect_temporal_candidates(expression, message)
        elif expression_type == ExpressionType.RECENT:
            candidates = await self._collect_recent_candidates(expression, message)

        return candidates

    async def _collect_habitual_candidates(
        self,
        expression: str,
        message: str,
    ) -> List[ContextCandidate]:
        """習慣的表現の候補を収集"""
        candidates = []

        # メッセージからコンテキストを推測
        context = self._infer_context_from_message(message)

        # ユーザーの習慣から検索
        if context and context in self._habits:
            habit_value = self._habits[context]
            candidates.append(
                ContextCandidate(
                    entity=habit_value,
                    confidence=0.9,
                    source="user_habit",
                    expression_type=ExpressionType.HABITUAL,
                    context_snippet=f"習慣: {context} → {habit_value}",
                )
            )

        # 習慣検索サービスがあれば使用
        if self._habit_lookup and self._user_id and context:
            try:
                habit = self._habit_lookup.get_user_habit(self._user_id, context)
                if habit:
                    candidates.append(
                        ContextCandidate(
                            entity=habit,
                            confidence=0.85,
                            source="habit_service",
                            expression_type=ExpressionType.HABITUAL,
                        )
                    )
            except Exception as e:
                logger.warning(f"Failed to lookup habit: {type(e).__name__}")

        # 会話履歴から習慣的なパターンを検索
        for msg in self._history[:10]:
            content = msg.get("content", "")
            if context and context in content:
                # コンテキストに関連する内容を抽出
                entity = self._extract_entity_near_context(content, context)
                if entity:
                    candidates.append(
                        ContextCandidate(
                            entity=entity,
                            confidence=0.6,
                            source="conversation_history",
                            expression_type=ExpressionType.HABITUAL,
                            context_snippet=content[:50],
                        )
                    )

        return candidates

    async def _collect_reference_candidates(
        self,
        expression: str,
        message: str,
    ) -> List[ContextCandidate]:
        """参照表現の候補を収集"""
        candidates = []

        # 最近の話題から検索
        for i, topic in enumerate(self._topics[:5]):
            topic_name = topic.get("name") or topic.get("subject") or topic.get("title", "")
            if topic_name:
                # 最近ほど高いスコア
                recency_score = 1.0 - (i * 0.1)
                candidates.append(
                    ContextCandidate(
                        entity=topic_name,
                        confidence=0.7 * recency_score,
                        source="recent_topic",
                        expression_type=ExpressionType.REFERENCE,
                        context_snippet=topic.get("snippet", ""),
                        timestamp=topic.get("timestamp"),
                    )
                )

        # 会話履歴から「〜の件」「〜について」を抽出
        for msg in self._history[:10]:
            content = msg.get("content", "")
            entities = self._extract_topic_entities(content)
            for entity in entities:
                candidates.append(
                    ContextCandidate(
                        entity=entity,
                        confidence=0.5,
                        source="conversation_history",
                        expression_type=ExpressionType.REFERENCE,
                        context_snippet=content[:50],
                    )
                )

        return candidates

    async def _collect_temporal_candidates(
        self,
        expression: str,
        message: str,
    ) -> List[ContextCandidate]:
        """時間参照表現の候補を収集"""
        candidates = []

        # 時間範囲を推測
        time_range = self._infer_time_range(expression)

        # 話題履歴サービスがあれば使用
        if self._topic_history:
            try:
                topics = self._topic_history.get_recent_topics(limit=10)
                for topic in topics:
                    topic_time = topic.get("timestamp")
                    if topic_time and time_range:
                        start, end = time_range
                        if start <= topic_time <= end:
                            candidates.append(
                                ContextCandidate(
                                    entity=topic.get("name", ""),
                                    confidence=0.75,
                                    source="topic_history",
                                    expression_type=ExpressionType.TEMPORAL,
                                    timestamp=topic_time,
                                )
                            )
            except Exception as e:
                logger.warning(f"Failed to get topic history: {type(e).__name__}")

        # 会話履歴から過去の出来事を抽出
        for msg in self._history[3:15]:  # 少し前の会話
            content = msg.get("content", "")
            entities = self._extract_event_entities(content)
            for entity in entities:
                candidates.append(
                    ContextCandidate(
                        entity=entity,
                        confidence=0.4,
                        source="past_conversation",
                        expression_type=ExpressionType.TEMPORAL,
                        context_snippet=content[:50],
                    )
                )

        return candidates

    async def _collect_recent_candidates(
        self,
        expression: str,
        message: str,
    ) -> List[ContextCandidate]:
        """最近参照表現の候補を収集"""
        candidates = []

        # 直近の会話から検索（最新3件）
        for i, msg in enumerate(self._history[:3]):
            content = msg.get("content", "")
            entities = self._extract_topic_entities(content)
            for entity in entities:
                # 直近ほど高いスコア
                recency_score = 1.0 - (i * 0.15)
                candidates.append(
                    ContextCandidate(
                        entity=entity,
                        confidence=0.8 * recency_score,
                        source="recent_conversation",
                        expression_type=ExpressionType.RECENT,
                        context_snippet=content[:50],
                    )
                )

        # 最近の話題から
        for topic in self._topics[:3]:
            topic_name = topic.get("name") or topic.get("subject", "")
            if topic_name:
                candidates.append(
                    ContextCandidate(
                        entity=topic_name,
                        confidence=0.7,
                        source="recent_topic",
                        expression_type=ExpressionType.RECENT,
                    )
                )

        return candidates

    # =========================================================================
    # ヘルパーメソッド
    # =========================================================================

    def _infer_context_from_message(self, message: str) -> Optional[str]:
        """メッセージからコンテキストを推測"""
        # キーワードに基づくコンテキスト推測
        context_keywords = {
            "コーヒー": "coffee_order",
            "珈琲": "coffee_order",
            "お茶": "tea_order",
            "ドリンク": "drink_order",
            "飲み物": "drink_order",
            "ランチ": "lunch_order",
            "昼食": "lunch_order",
            "お弁当": "bento_order",
            "注文": "order",
            "席": "seat_preference",
            "場所": "location_preference",
            "報告": "report_format",
            "レポート": "report_format",
        }

        for keyword, context in context_keywords.items():
            if keyword in message:
                return context

        return None

    def _extract_entity_near_context(self, text: str, context: str) -> Optional[str]:
        """コンテキスト周辺のエンティティを抽出"""
        # 「〜は〇〇」パターン
        pattern = rf"({context}[^\s]*)(?:は|を|に)([^\s、。]+)"
        match = re.search(pattern, text)
        if match:
            return match.group(2)
        return None

    def _extract_topic_entities(self, text: str) -> List[str]:
        """テキストから話題エンティティを抽出"""
        entities = []

        patterns = [
            r"「(.+?)」",  # カギカッコ
            r"(.+?)(?:の件|について|に関して)",  # 〜の件、〜について
            r"(.+?)(?:プロジェクト|タスク|案件)",  # プロジェクト名など
        ]

        for pattern in patterns:
            matches = re.findall(pattern, text)
            entities.extend([m.strip() for m in matches if len(m.strip()) >= 2])

        return entities[:3]

    def _extract_event_entities(self, text: str) -> List[str]:
        """テキストからイベントエンティティを抽出"""
        entities = []

        patterns = [
            r"(.+?)(?:ミーティング|会議|打ち合わせ)",
            r"(.+?)(?:イベント|セミナー|勉強会)",
            r"(.+?)(?:の時|のとき|した時)",
        ]

        for pattern in patterns:
            matches = re.findall(pattern, text)
            entities.extend([m.strip() for m in matches if len(m.strip()) >= 2])

        return entities[:3]

    def _infer_time_range(
        self,
        expression: str,
    ) -> Optional[Tuple[datetime, datetime]]:
        """表現から時間範囲を推測"""
        now = datetime.now(JST)

        if "この前" in expression or "先日" in expression:
            # 1週間前から昨日まで
            return (now - timedelta(days=7), now - timedelta(days=1))
        elif "前回" in expression or "前の" in expression:
            # 過去1ヶ月
            return (now - timedelta(days=30), now)
        elif "昨日" in expression:
            yesterday = now - timedelta(days=1)
            return (
                yesterday.replace(hour=0, minute=0, second=0, microsecond=0),
                yesterday.replace(hour=23, minute=59, second=59, microsecond=999999),
            )
        elif "先週" in expression:
            last_week_start = now - timedelta(days=now.weekday() + 7)
            last_week_end = last_week_start + timedelta(days=6)
            return (last_week_start, last_week_end)
        elif "先月" in expression:
            # 簡略化: 30日前から今月1日まで
            this_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            return (now - timedelta(days=60), this_month_start)

        return None

    # =========================================================================
    # 結果構築
    # =========================================================================

    def _build_result(
        self,
        expression: str,
        expression_type: ExpressionType,
        candidates: List[ContextCandidate],
    ) -> ContextResolutionResult:
        """解決結果を構築"""
        if not candidates:
            # 候補なし → 確認必要
            logger.debug(f"No candidates found for '{expression}'")
            return ContextResolutionResult(
                expression=expression,
                resolved_to=None,
                confidence=0.0,
                needs_confirmation=True,
                candidates=[],
                expression_type=expression_type,
            )

        # 重複を除去してスコア順にソート
        unique_candidates = self._deduplicate_candidates(candidates)
        unique_candidates.sort(key=lambda c: c.confidence, reverse=True)

        best = unique_candidates[0]

        # 確信度が閾値未満 → 確認必要
        needs_confirmation = best.confidence < self.CONFIRMATION_THRESHOLD

        if needs_confirmation:
            logger.debug(
                f"Low confidence ({best.confidence:.2f} < {self.CONFIRMATION_THRESHOLD}) "
                f"for '{expression}' → '{best.entity}', needs confirmation"
            )
        else:
            logger.info(
                f"Resolved '{expression}' → '{best.entity}' "
                f"(confidence={best.confidence:.2f})"
            )

        return ContextResolutionResult(
            expression=expression,
            resolved_to=best.entity if not needs_confirmation else None,
            confidence=best.confidence,
            needs_confirmation=needs_confirmation,
            candidates=unique_candidates[:4],
            expression_type=expression_type,
        )

    def _deduplicate_candidates(
        self,
        candidates: List[ContextCandidate],
    ) -> List[ContextCandidate]:
        """候補の重複を除去"""
        seen = set()
        unique = []

        for candidate in candidates:
            if candidate.entity not in seen:
                seen.add(candidate.entity)
                unique.append(candidate)

        return unique


# =============================================================================
# ファクトリー関数
# =============================================================================


def create_context_expression_resolver(
    conversation_history: Optional[List[Dict[str, Any]]] = None,
    user_habits: Optional[Dict[str, str]] = None,
    recent_topics: Optional[List[Dict[str, Any]]] = None,
) -> ContextExpressionResolver:
    """
    ContextExpressionResolverのインスタンスを作成

    使用例:
        resolver = create_context_expression_resolver(
            conversation_history=messages,
            user_habits={"coffee_order": "アメリカン"},
        )
        result = await resolver.resolve("いつもの", "いつものでお願い")
    """
    return ContextExpressionResolver(
        conversation_history=conversation_history,
        user_habits=user_habits,
        recent_topics=recent_topics,
    )
