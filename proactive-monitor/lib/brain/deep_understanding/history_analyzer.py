# lib/brain/deep_understanding/history_analyzer.py
"""
Phase 2I: 理解力強化（Deep Understanding）- 会話履歴からの文脈復元

設計書: docs/17_brain_completion_roadmap.md セクション17.3 Phase 2I

このファイルには、会話履歴から文脈を復元する機能を実装します。

【主な機能】
- 会話履歴からの文脈断片抽出
- 複数ソースからの文脈統合
- トピックの追跡と関連付け
- 時間経過を考慮した文脈の重み付け

Author: Claude Opus 4.5
Created: 2026-01-27
"""

import logging
import re
import time
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Set, Tuple

from .constants import (
    ContextRecoverySource,
    CONTEXT_WINDOW_CONFIG,
    MAX_CONTEXT_RECOVERY_ATTEMPTS,
)
from .models import (
    ContextFragment,
    RecoveredContext,
    DeepUnderstandingInput,
)

logger = logging.getLogger(__name__)


class HistoryAnalyzer:
    """
    会話履歴分析器

    会話履歴やタスク履歴から文脈を復元し、
    現在のメッセージの理解に役立てる。

    使用例:
        analyzer = HistoryAnalyzer()
        context = await analyzer.analyze(
            message="あれどうなった？",
            input_context=deep_understanding_input,
        )
    """

    def __init__(
        self,
        pool: Optional[Any] = None,
        organization_id: str = "",
    ):
        """
        Args:
            pool: データベース接続プール
            organization_id: 組織ID
        """
        self.pool = pool
        self.organization_id = organization_id

        logger.info(
            f"HistoryAnalyzer initialized: organization_id={organization_id}"
        )

    # =========================================================================
    # メインエントリーポイント
    # =========================================================================

    async def analyze(
        self,
        message: str,
        input_context: DeepUnderstandingInput,
    ) -> RecoveredContext:
        """
        会話履歴から文脈を復元

        Args:
            message: ユーザーのメッセージ
            input_context: 深い理解層への入力コンテキスト

        Returns:
            RecoveredContext: 復元された文脈
        """
        start_time = time.time()

        try:
            fragments: List[ContextFragment] = []

            # Step 1: 会話履歴から文脈を抽出
            conversation_fragments = await self._extract_from_conversation(
                message=message,
                recent_conversation=input_context.recent_conversation,
            )
            fragments.extend(conversation_fragments)

            # Step 2: タスク履歴から文脈を抽出
            task_fragments = await self._extract_from_tasks(
                message=message,
                recent_tasks=input_context.recent_tasks,
            )
            fragments.extend(task_fragments)

            # Step 3: 人物情報から文脈を抽出
            person_fragments = await self._extract_from_persons(
                message=message,
                person_info=input_context.person_info,
            )
            fragments.extend(person_fragments)

            # Step 4: 目標情報から文脈を抽出
            goal_fragments = await self._extract_from_goals(
                message=message,
                active_goals=input_context.active_goals,
            )
            fragments.extend(goal_fragments)

            # Step 5: 関連度でソートしてフィルタ
            fragments = self._rank_and_filter_fragments(fragments)

            # Step 6: トピックの抽出
            main_topics = self._extract_main_topics(fragments, message)

            # Step 7: 関連人物の抽出
            related_persons = self._extract_related_persons(fragments, input_context)

            # Step 8: 関連タスクの抽出
            related_tasks = self._extract_related_tasks(fragments, input_context)

            # Step 9: サマリーの生成
            summary = self._generate_summary(fragments, main_topics)

            # Step 10: 全体の信頼度を計算
            overall_confidence = self._calculate_overall_confidence(fragments)

            result = RecoveredContext(
                fragments=fragments,
                summary=summary,
                main_topics=main_topics,
                related_persons=related_persons,
                related_tasks=related_tasks,
                overall_confidence=overall_confidence,
                processing_time_ms=self._elapsed_ms(start_time),
            )

            logger.info(
                f"History analysis complete: "
                f"fragments={len(fragments)}, "
                f"topics={len(main_topics)}, "
                f"confidence={overall_confidence:.2f}"
            )

            return result

        except Exception as e:
            logger.error(f"Error in history analysis: {type(e).__name__}")
            return RecoveredContext(
                fragments=[],
                summary="文脈の復元に失敗しました",
                overall_confidence=0.0,
                processing_time_ms=self._elapsed_ms(start_time),
            )

    # =========================================================================
    # 会話履歴からの抽出
    # =========================================================================

    async def _extract_from_conversation(
        self,
        message: str,
        recent_conversation: List[Dict[str, Any]],
    ) -> List[ContextFragment]:
        """
        会話履歴から関連する文脈を抽出
        """
        fragments: List[ContextFragment] = []

        if not recent_conversation:
            return fragments

        # キーワードを抽出（メッセージから）
        keywords = self._extract_keywords(message)

        for i, msg in enumerate(reversed(recent_conversation)):
            content = msg.get("content", "")
            timestamp = msg.get("timestamp")
            role = msg.get("role", "user")

            # 関連度スコアの計算
            relevance = self._calculate_relevance(
                content=content,
                keywords=keywords,
                position=i,
                total=len(recent_conversation),
            )

            if relevance > 0.2:  # 閾値以上のみ採用
                fragments.append(ContextFragment(
                    source=ContextRecoverySource.CONVERSATION_HISTORY,
                    content=content[:200],  # 200文字に制限
                    relevance_score=relevance,
                    timestamp=timestamp,
                    metadata={
                        "role": role,
                        "position": i,
                        "keywords_matched": self._get_matched_keywords(content, keywords),
                    },
                    source_id=msg.get("message_id"),
                ))

        return fragments

    def _extract_keywords(self, message: str) -> List[str]:
        """
        メッセージからキーワードを抽出
        """
        keywords = []

        # 名詞・動詞を抽出（簡易的な実装）
        # 日本語の場合、助詞で区切る
        parts = re.split(r'[をにがでは、。！？\s]+', message)
        keywords.extend([p for p in parts if len(p) >= 2])

        # 指示代名詞は除外
        pronouns = ["これ", "それ", "あれ", "この", "その", "あの", "ここ", "そこ", "あそこ"]
        keywords = [k for k in keywords if k not in pronouns]

        return keywords

    def _calculate_relevance(
        self,
        content: str,
        keywords: List[str],
        position: int,
        total: int,
    ) -> float:
        """
        文脈断片の関連度を計算
        """
        score = 0.0

        # キーワードマッチ
        content_lower = content.lower()
        matched_count = sum(1 for kw in keywords if kw.lower() in content_lower)
        if keywords:
            score += (matched_count / len(keywords)) * 0.5

        # 位置による重み付け（新しいほど高い）
        # CONTEXT_WINDOW_CONFIGの設定を使用
        if position < CONTEXT_WINDOW_CONFIG["immediate"]["message_count"]:
            position_weight = CONTEXT_WINDOW_CONFIG["immediate"]["weight"]
        elif position < CONTEXT_WINDOW_CONFIG["short_term"]["message_count"]:
            position_weight = CONTEXT_WINDOW_CONFIG["short_term"]["weight"]
        elif position < CONTEXT_WINDOW_CONFIG["medium_term"]["message_count"]:
            position_weight = CONTEXT_WINDOW_CONFIG["medium_term"]["weight"]
        else:
            position_weight = CONTEXT_WINDOW_CONFIG["long_term"]["weight"]

        score += position_weight * 0.3

        # 内容の長さによる重み付け（ある程度の長さがあると情報量が多い）
        content_length = len(content)
        if 20 <= content_length <= 200:
            score += 0.2
        elif content_length > 200:
            score += 0.15
        else:
            score += 0.05

        return min(score, 1.0)

    def _get_matched_keywords(
        self,
        content: str,
        keywords: List[str],
    ) -> List[str]:
        """
        マッチしたキーワードを取得
        """
        content_lower = content.lower()
        return [kw for kw in keywords if kw.lower() in content_lower]

    # =========================================================================
    # タスク履歴からの抽出
    # =========================================================================

    async def _extract_from_tasks(
        self,
        message: str,
        recent_tasks: List[Dict[str, Any]],
    ) -> List[ContextFragment]:
        """
        タスク履歴から関連する文脈を抽出
        """
        fragments: List[ContextFragment] = []

        if not recent_tasks:
            return fragments

        keywords = self._extract_keywords(message)

        for i, task in enumerate(recent_tasks):
            body = task.get("body", "")
            task_id = task.get("task_id")
            assignee = task.get("assignee_name", "")
            status = task.get("status", "")
            created_at = task.get("created_at")

            # 関連度スコアの計算
            relevance = self._calculate_task_relevance(
                body=body,
                assignee=assignee,
                keywords=keywords,
                position=i,
            )

            if relevance > 0.3:  # タスクは閾値をやや高めに
                fragments.append(ContextFragment(
                    source=ContextRecoverySource.TASK_HISTORY,
                    content=f"タスク: {body[:100]}",
                    relevance_score=relevance,
                    timestamp=created_at,
                    metadata={
                        "task_id": task_id,
                        "assignee": assignee,
                        "status": status,
                        "position": i,
                    },
                    source_id=task_id,
                ))

        return fragments

    def _calculate_task_relevance(
        self,
        body: str,
        assignee: str,
        keywords: List[str],
        position: int,
    ) -> float:
        """
        タスクの関連度を計算
        """
        score = 0.0

        # キーワードマッチ
        body_lower = body.lower()
        matched_count = sum(1 for kw in keywords if kw.lower() in body_lower)
        if keywords:
            score += (matched_count / len(keywords)) * 0.6

        # 担当者名がキーワードに含まれる場合
        if assignee and any(kw in assignee for kw in keywords):
            score += 0.2

        # 位置による重み付け
        if position == 0:
            score += 0.2
        elif position < 3:
            score += 0.1

        return min(score, 1.0)

    # =========================================================================
    # 人物情報からの抽出
    # =========================================================================

    async def _extract_from_persons(
        self,
        message: str,
        person_info: List[Dict[str, Any]],
    ) -> List[ContextFragment]:
        """
        人物情報から関連する文脈を抽出
        """
        fragments: List[ContextFragment] = []

        if not person_info:
            return fragments

        for person in person_info:
            name = person.get("name", "")
            department = person.get("department", "")
            role = person.get("role", "")
            notes = person.get("notes", "")

            # メッセージに名前が含まれているか
            if name and name in message:
                content = f"{name}さん"
                if department:
                    content += f"（{department}）"
                if role:
                    content += f" - {role}"

                fragments.append(ContextFragment(
                    source=ContextRecoverySource.PERSON_INFO,
                    content=content,
                    relevance_score=0.8,
                    metadata={
                        "name": name,
                        "department": department,
                        "role": role,
                    },
                ))

        return fragments

    # =========================================================================
    # 目標情報からの抽出
    # =========================================================================

    async def _extract_from_goals(
        self,
        message: str,
        active_goals: List[Dict[str, Any]],
    ) -> List[ContextFragment]:
        """
        アクティブな目標から関連する文脈を抽出
        """
        fragments: List[ContextFragment] = []

        if not active_goals:
            return fragments

        keywords = self._extract_keywords(message)

        for goal in active_goals:
            title = goal.get("title", "")
            description = goal.get("description", "")
            progress = goal.get("progress", 0)

            # 関連度の計算
            relevance = 0.0
            goal_text = f"{title} {description}".lower()
            matched = sum(1 for kw in keywords if kw.lower() in goal_text)
            if keywords:
                relevance = (matched / len(keywords)) * 0.7

            if relevance > 0.3:
                fragments.append(ContextFragment(
                    source=ContextRecoverySource.ORGANIZATION_KNOWLEDGE,
                    content=f"目標: {title}（進捗{progress}%）",
                    relevance_score=relevance,
                    metadata={
                        "goal_title": title,
                        "progress": progress,
                    },
                ))

        return fragments

    # =========================================================================
    # 文脈の統合
    # =========================================================================

    def _rank_and_filter_fragments(
        self,
        fragments: List[ContextFragment],
        max_fragments: int = 10,
    ) -> List[ContextFragment]:
        """
        文脈断片をランキングしてフィルタ
        """
        # 関連度でソート
        sorted_fragments = sorted(
            fragments,
            key=lambda f: f.relevance_score,
            reverse=True,
        )

        # 上位を選択
        return sorted_fragments[:max_fragments]

    def _extract_main_topics(
        self,
        fragments: List[ContextFragment],
        message: str,
    ) -> List[str]:
        """
        主要なトピックを抽出
        """
        topics: Dict[str, int] = {}

        # メッセージからキーワードを抽出
        keywords = self._extract_keywords(message)
        for kw in keywords:
            if len(kw) >= 2:
                topics[kw] = topics.get(kw, 0) + 1

        # 文脈断片からキーワードを抽出
        for fragment in fragments:
            fragment_keywords = self._extract_keywords(fragment.content)
            for kw in fragment_keywords:
                if len(kw) >= 2:
                    # 関連度で重み付け
                    weight = int(fragment.relevance_score * 3)
                    topics[kw] = topics.get(kw, 0) + weight

        # 頻出順にソート
        sorted_topics = sorted(topics.items(), key=lambda x: x[1], reverse=True)

        return [topic for topic, count in sorted_topics[:5]]

    def _extract_related_persons(
        self,
        fragments: List[ContextFragment],
        input_context: DeepUnderstandingInput,
    ) -> List[str]:
        """
        関連する人物を抽出
        """
        persons: Set[str] = set()

        # 文脈断片から人物を抽出
        for fragment in fragments:
            if fragment.source == ContextRecoverySource.PERSON_INFO:
                name = fragment.metadata.get("name")
                if name:
                    persons.add(name)

            # 会話履歴の送信者
            if fragment.source == ContextRecoverySource.CONVERSATION_HISTORY:
                # content から人名を探す（簡易的）
                for person in input_context.person_info:
                    person_name = person.get("name", "")
                    if person_name and person_name in fragment.content:
                        persons.add(person_name)

        return list(persons)[:5]

    def _extract_related_tasks(
        self,
        fragments: List[ContextFragment],
        input_context: DeepUnderstandingInput,
    ) -> List[str]:
        """
        関連するタスクを抽出
        """
        tasks: List[str] = []

        for fragment in fragments:
            if fragment.source == ContextRecoverySource.TASK_HISTORY:
                task_id = fragment.source_id or fragment.metadata.get("task_id")
                if task_id and task_id not in tasks:
                    tasks.append(task_id)

        return tasks[:5]

    def _generate_summary(
        self,
        fragments: List[ContextFragment],
        main_topics: List[str],
    ) -> str:
        """
        復元された文脈のサマリーを生成
        """
        if not fragments:
            return "関連する文脈が見つかりませんでした"

        parts = []

        # 主要トピック
        if main_topics:
            parts.append(f"主なトピック: {', '.join(main_topics[:3])}")

        # ソース別の情報
        sources: Dict[str, int] = {}
        for fragment in fragments:
            source_name = fragment.source.value
            sources[source_name] = sources.get(source_name, 0) + 1

        source_desc = []
        if sources.get(ContextRecoverySource.CONVERSATION_HISTORY.value):
            source_desc.append(f"会話{sources[ContextRecoverySource.CONVERSATION_HISTORY.value]}件")
        if sources.get(ContextRecoverySource.TASK_HISTORY.value):
            source_desc.append(f"タスク{sources[ContextRecoverySource.TASK_HISTORY.value]}件")
        if sources.get(ContextRecoverySource.PERSON_INFO.value):
            source_desc.append(f"人物{sources[ContextRecoverySource.PERSON_INFO.value]}件")

        if source_desc:
            parts.append(f"関連情報: {', '.join(source_desc)}")

        # 最も関連度の高い断片の内容
        if fragments:
            top_fragment = fragments[0]
            parts.append(f"最も関連: {top_fragment.content[:50]}...")

        return " / ".join(parts)

    def _calculate_overall_confidence(
        self,
        fragments: List[ContextFragment],
    ) -> float:
        """
        全体の信頼度を計算
        """
        if not fragments:
            return 0.0

        # 上位断片の関連度の平均
        top_fragments = fragments[:5]
        avg_relevance = sum(f.relevance_score for f in top_fragments) / len(top_fragments)

        # 断片の数による補正
        count_factor = min(len(fragments) / 5, 1.0)

        return avg_relevance * 0.7 + count_factor * 0.3

    # =========================================================================
    # ヘルパーメソッド
    # =========================================================================

    def _elapsed_ms(self, start_time: float) -> int:
        """経過時間をミリ秒で返す"""
        return int((time.time() - start_time) * 1000)


# =============================================================================
# ファクトリー関数
# =============================================================================

def create_history_analyzer(
    pool: Optional[Any] = None,
    organization_id: str = "",
) -> HistoryAnalyzer:
    """
    HistoryAnalyzerを作成

    Args:
        pool: データベース接続プール
        organization_id: 組織ID

    Returns:
        HistoryAnalyzer: 履歴分析器
    """
    return HistoryAnalyzer(
        pool=pool,
        organization_id=organization_id,
    )


# =============================================================================
# エクスポート
# =============================================================================

__all__ = [
    "HistoryAnalyzer",
    "create_history_analyzer",
]
