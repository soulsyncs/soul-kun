# lib/brain/deep_understanding/pronoun_resolver.py
"""
強化版代名詞リゾルバー

「これ」「それ」「あれ」などの指示代名詞を文脈から解決する。

【改善点】
1. 距離感（near/middle/far）と文脈の複合評価
2. 会話の流れに基づく候補ランキング
3. トピック関連度の考慮
4. 確信度 < 0.7 で確認モード自動発動

【設計書参照】
- docs/13_brain_architecture.md セクション6「理解層」
  - 6.4 曖昧表現の解決パターン（代名詞解決）
- docs/17_brain_completion_roadmap.md セクション17.3 Phase 2I「理解力強化」
  - 暗黙の意図推測（「これ」が何を指すか）
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
from typing import Optional, List, Dict, Any, Tuple

from lib.brain.constants import (
    CONFIRMATION_THRESHOLD,
    PRONOUNS,
    JST,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Enum定義
# =============================================================================


class PronounDistance(Enum):
    """
    代名詞の心理的距離

    日本語の指示代名詞は「コ・ソ・ア」の3系列で距離を表す:
    - コ系（これ、ここ、こちら）: 話者に近い
    - ソ系（それ、そこ、そちら）: 聞き手に近い / 文脈で既出
    - ア系（あれ、あそこ、あちら）: 両者から遠い / 共有知識
    """

    NEAR = "near"  # コ系: 直前の発話、現在のタスク
    MIDDLE = "middle"  # ソ系: 相手の発話、直近の話題
    FAR = "far"  # ア系: 過去の会話、以前のタスク


class PronounType(Enum):
    """代名詞のタイプ"""

    THING = "thing"  # 物事（これ、それ、あれ）
    PLACE = "place"  # 場所（ここ、そこ、あそこ）
    DIRECTION = "direction"  # 方向（こちら、そちら、あちら）
    PERSON = "person"  # 人物（この人、その人、あの人）


# =============================================================================
# データクラス
# =============================================================================


@dataclass
class PronounCandidate:
    """
    代名詞の解決候補

    Attributes:
        entity: 候補のエンティティ（解決先の文字列）
        confidence: 確信度（0.0-1.0）
        source: 候補の出典
        distance_match: 代名詞の距離感と候補の距離が一致するか
        recency_score: 最近言及されたか（0.0-1.0、1.0が最も新しい）
        topic_relevance: 現在のトピックとの関連度（0.0-1.0）
        context_snippet: 候補が出現した文脈の抜粋
    """

    entity: str
    confidence: float = 0.5
    source: str = "unknown"
    distance_match: bool = True
    recency_score: float = 0.5
    topic_relevance: float = 0.5
    context_snippet: Optional[str] = None

    def calculate_total_score(self) -> float:
        """
        総合スコアを計算

        重み付け:
        - distance_match: 30%
        - recency_score: 30%
        - topic_relevance: 40%
        """
        distance_score = 1.0 if self.distance_match else 0.3
        return (
            distance_score * 0.30
            + self.recency_score * 0.30
            + self.topic_relevance * 0.40
        )


@dataclass
class PronounResolutionResult:
    """
    代名詞解決の結果

    Attributes:
        pronoun: 解決対象の代名詞
        resolved_to: 解決結果（Noneの場合は解決失敗）
        confidence: 確信度
        needs_confirmation: 確認が必要か
        candidates: 候補リスト（確認時に使用）
        distance: 代名詞の距離感
        pronoun_type: 代名詞のタイプ
    """

    pronoun: str
    resolved_to: Optional[str] = None
    confidence: float = 0.0
    needs_confirmation: bool = False
    candidates: List[PronounCandidate] = field(default_factory=list)
    distance: Optional[PronounDistance] = None
    pronoun_type: Optional[PronounType] = None

    def get_confirmation_options(self) -> List[str]:
        """確認用の選択肢を取得"""
        return [c.entity for c in self.candidates[:4]]  # 最大4つ


# =============================================================================
# 定数
# =============================================================================


# 指示代名詞 → 距離感のマッピング
DEMONSTRATIVE_PRONOUNS: Dict[str, Dict[str, Any]] = {
    # コ系（近称）- 話者に近い
    "これ": {"distance": PronounDistance.NEAR, "type": PronounType.THING},
    "この": {"distance": PronounDistance.NEAR, "type": PronounType.THING},
    "ここ": {"distance": PronounDistance.NEAR, "type": PronounType.PLACE},
    "こちら": {"distance": PronounDistance.NEAR, "type": PronounType.DIRECTION},
    "この人": {"distance": PronounDistance.NEAR, "type": PronounType.PERSON},
    # ソ系（中称）- 聞き手に近い / 文脈で既出
    "それ": {"distance": PronounDistance.MIDDLE, "type": PronounType.THING},
    "その": {"distance": PronounDistance.MIDDLE, "type": PronounType.THING},
    "そこ": {"distance": PronounDistance.MIDDLE, "type": PronounType.PLACE},
    "そちら": {"distance": PronounDistance.MIDDLE, "type": PronounType.DIRECTION},
    "その人": {"distance": PronounDistance.MIDDLE, "type": PronounType.PERSON},
    # ア系（遠称）- 両者から遠い / 共有知識
    "あれ": {"distance": PronounDistance.FAR, "type": PronounType.THING},
    "あの": {"distance": PronounDistance.FAR, "type": PronounType.THING},
    "あそこ": {"distance": PronounDistance.FAR, "type": PronounType.PLACE},
    "あちら": {"distance": PronounDistance.FAR, "type": PronounType.DIRECTION},
    "あの人": {"distance": PronounDistance.FAR, "type": PronounType.PERSON},
    # 人称代名詞
    "彼": {"distance": PronounDistance.FAR, "type": PronounType.PERSON},
    "彼女": {"distance": PronounDistance.FAR, "type": PronounType.PERSON},
    "あいつ": {"distance": PronounDistance.FAR, "type": PronounType.PERSON},
    "やつ": {"distance": PronounDistance.FAR, "type": PronounType.PERSON},
}

# 候補の時間による重み付け
TIME_WEIGHT_IMMEDIATE = 1.0  # 直前3件
TIME_WEIGHT_SHORT = 0.7  # 直近60分
TIME_WEIGHT_MEDIUM = 0.4  # 直近6時間
TIME_WEIGHT_LONG = 0.2  # 直近24時間


# =============================================================================
# EnhancedPronounResolver クラス
# =============================================================================


class EnhancedPronounResolver:
    """
    強化版代名詞リゾルバー

    改善点:
    1. 距離感（near/middle/far）と文脈の複合評価
    2. 会話の流れに基づく候補ランキング
    3. トピック関連度の考慮
    4. 確信度 < 0.7 で確認モード自動発動（CLAUDE.md準拠）

    使用例:
        resolver = EnhancedPronounResolver(
            conversation_history=recent_messages,
            current_context={"topic": "task_management"},
        )

        result = await resolver.resolve("これ", "これを完了にして")
        if result.needs_confirmation:
            # ユーザーに確認
            options = result.get_confirmation_options()
    """

    # 確認が必要な閾値（CLAUDE.md セクション4-1準拠）
    CONFIRMATION_THRESHOLD = CONFIRMATION_THRESHOLD

    def __init__(
        self,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        current_context: Optional[Dict[str, Any]] = None,
        recent_tasks: Optional[List[Dict[str, Any]]] = None,
        person_info: Optional[List[Dict[str, Any]]] = None,
    ):
        """
        Args:
            conversation_history: 会話履歴（新しい順）
            current_context: 現在のコンテキスト（topic, sender_name等）
            recent_tasks: 直近のタスク
            person_info: 人物情報
        """
        self._history = conversation_history or []
        self._context = current_context or {}
        self._tasks = recent_tasks or []
        self._persons = person_info or []

        logger.debug(
            f"EnhancedPronounResolver initialized: "
            f"history={len(self._history)}, "
            f"tasks={len(self._tasks)}, "
            f"persons={len(self._persons)}"
        )

    # =========================================================================
    # メインエントリーポイント
    # =========================================================================

    async def resolve(
        self,
        pronoun: str,
        message: str,
    ) -> PronounResolutionResult:
        """
        代名詞を解決

        Args:
            pronoun: 解決対象の代名詞
            message: 代名詞が含まれるメッセージ全文

        Returns:
            PronounResolutionResult: 解決結果
        """
        # 1. 代名詞の情報を取得
        pronoun_info = self._get_pronoun_info(pronoun)
        distance = pronoun_info.get("distance", PronounDistance.MIDDLE)
        pronoun_type = pronoun_info.get("type", PronounType.THING)

        logger.debug(
            f"Resolving pronoun '{pronoun}': distance={distance.value}, type={pronoun_type.value}"
        )

        # 2. 距離感に基づいて候補を収集
        candidates = await self._collect_candidates(distance, pronoun_type, message)

        # 3. スコアリングとソート
        scored_candidates = self._score_and_sort_candidates(candidates, message)

        # 4. 結果を構築
        return self._build_result(pronoun, distance, pronoun_type, scored_candidates)

    def resolve_sync(
        self,
        pronoun: str,
        message: str,
    ) -> PronounResolutionResult:
        """同期版のresolve（テスト用）

        Python 3.10+ 対応: 新しいイベントループを作成して実行
        """
        import asyncio

        # 新しいイベントループを作成して実行（Python 3.10+ 対応）
        return asyncio.run(self.resolve(pronoun, message))

    # =========================================================================
    # 代名詞情報の取得
    # =========================================================================

    def _get_pronoun_info(self, pronoun: str) -> Dict[str, Any]:
        """代名詞の情報（距離感、タイプ）を取得"""
        # 完全一致
        if pronoun in DEMONSTRATIVE_PRONOUNS:
            return DEMONSTRATIVE_PRONOUNS[pronoun]

        # 部分一致（「あの人」の「あの」部分など）
        for key, info in DEMONSTRATIVE_PRONOUNS.items():
            if pronoun.startswith(key) or key.startswith(pronoun):
                return info

        # デフォルト
        return {"distance": PronounDistance.MIDDLE, "type": PronounType.THING}

    # =========================================================================
    # 候補の収集
    # =========================================================================

    async def _collect_candidates(
        self,
        distance: PronounDistance,
        pronoun_type: PronounType,
        message: str,
    ) -> List[PronounCandidate]:
        """
        距離感に基づいて候補を収集

        near: 直前の発言、現在のタスク、話者が言及したもの
        middle: 相手の直前の発言、共有コンテキスト
        far: 過去の会話、以前のタスク
        """
        candidates: List[PronounCandidate] = []

        # 距離感に応じた候補収集
        if distance == PronounDistance.NEAR:
            candidates.extend(await self._collect_near_candidates(pronoun_type))
        elif distance == PronounDistance.MIDDLE:
            candidates.extend(await self._collect_middle_candidates(pronoun_type))
        else:  # FAR
            candidates.extend(await self._collect_far_candidates(pronoun_type))

        # 人物タイプの場合は人物情報も検索
        if pronoun_type == PronounType.PERSON:
            candidates.extend(await self._collect_person_candidates())

        # 重複を除去
        candidates = self._deduplicate_candidates(candidates)

        logger.debug(f"Collected {len(candidates)} candidates for distance={distance.value}")
        return candidates

    async def _collect_near_candidates(
        self,
        pronoun_type: PronounType,
    ) -> List[PronounCandidate]:
        """近称（コ系）の候補を収集"""
        candidates = []

        # 直前のユーザー発言から抽出（最新3件）
        for i, msg in enumerate(self._history[:3]):
            if msg.get("role") == "user":
                entities = self._extract_entities_from_text(msg.get("content", ""))
                for entity in entities:
                    candidates.append(
                        PronounCandidate(
                            entity=entity,
                            source="recent_user_message",
                            distance_match=True,
                            recency_score=TIME_WEIGHT_IMMEDIATE - (i * 0.1),
                            topic_relevance=0.8,
                            context_snippet=msg.get("content", "")[:50],
                        )
                    )

        # 直近のタスク（最新3件）
        for i, task in enumerate(self._tasks[:3]):
            task_body = task.get("body", "") or task.get("summary", "")
            if task_body:
                candidates.append(
                    PronounCandidate(
                        entity=task_body[:50],  # タスク本文を候補に
                        source="recent_task",
                        distance_match=True,
                        recency_score=TIME_WEIGHT_IMMEDIATE - (i * 0.1),
                        topic_relevance=0.7,
                        context_snippet=f"タスク: {task_body[:30]}",
                    )
                )

        return candidates

    async def _collect_middle_candidates(
        self,
        pronoun_type: PronounType,
    ) -> List[PronounCandidate]:
        """中称（ソ系）の候補を収集"""
        candidates = []

        # アシスタントの直前の発言から抽出
        for i, msg in enumerate(self._history[:5]):
            if msg.get("role") == "assistant":
                entities = self._extract_entities_from_text(msg.get("content", ""))
                for entity in entities:
                    candidates.append(
                        PronounCandidate(
                            entity=entity,
                            source="recent_assistant_message",
                            distance_match=True,
                            recency_score=TIME_WEIGHT_SHORT - (i * 0.1),
                            topic_relevance=0.7,
                            context_snippet=msg.get("content", "")[:50],
                        )
                    )

        # 共有コンテキストのトピック
        topic = self._context.get("topic")
        if topic:
            candidates.append(
                PronounCandidate(
                    entity=topic,
                    source="current_topic",
                    distance_match=True,
                    recency_score=TIME_WEIGHT_SHORT,
                    topic_relevance=1.0,
                )
            )

        return candidates

    async def _collect_far_candidates(
        self,
        pronoun_type: PronounType,
    ) -> List[PronounCandidate]:
        """遠称（ア系）の候補を収集"""
        candidates = []

        # 過去の会話から抽出（4件目以降）
        for i, msg in enumerate(self._history[3:10]):
            entities = self._extract_entities_from_text(msg.get("content", ""))
            for entity in entities:
                candidates.append(
                    PronounCandidate(
                        entity=entity,
                        source="past_conversation",
                        distance_match=True,
                        recency_score=TIME_WEIGHT_MEDIUM - (i * 0.05),
                        topic_relevance=0.5,
                        context_snippet=msg.get("content", "")[:50],
                    )
                )

        # 過去のタスク（4件目以降）
        for i, task in enumerate(self._tasks[3:10]):
            task_body = task.get("body", "") or task.get("summary", "")
            if task_body:
                candidates.append(
                    PronounCandidate(
                        entity=task_body[:50],
                        source="past_task",
                        distance_match=True,
                        recency_score=TIME_WEIGHT_MEDIUM - (i * 0.05),
                        topic_relevance=0.4,
                        context_snippet=f"タスク: {task_body[:30]}",
                    )
                )

        return candidates

    async def _collect_person_candidates(self) -> List[PronounCandidate]:
        """人物の候補を収集"""
        candidates = []

        # 会話中に言及された人物
        for msg in self._history[:10]:
            content = msg.get("content", "")
            # 人名らしいパターンを抽出（簡易版）
            names = self._extract_person_names(content)
            for name in names:
                candidates.append(
                    PronounCandidate(
                        entity=name,
                        source="mentioned_person",
                        distance_match=True,
                        recency_score=0.7,
                        topic_relevance=0.6,
                        context_snippet=content[:50],
                    )
                )

        # 人物情報から
        for person in self._persons[:5]:
            name = person.get("name", "")
            if name:
                candidates.append(
                    PronounCandidate(
                        entity=name,
                        source="person_info",
                        distance_match=True,
                        recency_score=0.5,
                        topic_relevance=0.5,
                    )
                )

        return candidates

    # =========================================================================
    # エンティティ抽出
    # =========================================================================

    def _extract_entities_from_text(self, text: str) -> List[str]:
        """テキストからエンティティを抽出"""
        entities = []

        # 「〜について」「〜の件」パターン
        patterns = [
            r"「(.+?)」",  # カギカッコ
            r"(.+?)について",  # 〜について
            r"(.+?)の件",  # 〜の件
            r"(.+?)を(?:確認|完了|送信|作成|削除)",  # 動詞の目的語
        ]

        for pattern in patterns:
            matches = re.findall(pattern, text)
            entities.extend(matches)

        # 短すぎるものを除外
        entities = [e.strip() for e in entities if len(e.strip()) >= 2]

        return entities[:5]  # 最大5つ

    def _extract_person_names(self, text: str) -> List[str]:
        """テキストから人名を抽出"""
        names = []

        # 「〜さん」「〜くん」パターン
        # 日本語の名前は通常漢字（一-龯）またはカタカナ（ァ-ン）で構成される
        # ひらがなの助詞（と、を、に等）を除外するため、漢字・カタカナのみをマッチ
        name_char_class = r"[一-龯ァ-ン]"
        patterns = [
            rf"({name_char_class}{{1,4}})さん",
            rf"({name_char_class}{{1,4}})くん",
            rf"({name_char_class}{{1,4}})君",
            rf"({name_char_class}{{1,4}})ちゃん",
        ]

        for pattern in patterns:
            matches = re.findall(pattern, text)
            names.extend(matches)

        return list(set(names))[:5]

    # =========================================================================
    # スコアリング
    # =========================================================================

    def _score_and_sort_candidates(
        self,
        candidates: List[PronounCandidate],
        message: str,
    ) -> List[PronounCandidate]:
        """候補をスコアリングしてソート"""
        if not candidates:
            return []

        # メッセージからのヒントを使ってトピック関連度を調整
        for candidate in candidates:
            # メッセージ中に候補のキーワードが含まれていたらボーナス
            if candidate.entity and candidate.entity in message:
                candidate.topic_relevance = min(1.0, candidate.topic_relevance + 0.2)

            # 確信度を計算
            candidate.confidence = candidate.calculate_total_score()

        # スコア降順でソート
        candidates.sort(key=lambda c: c.confidence, reverse=True)

        return candidates

    def _deduplicate_candidates(
        self,
        candidates: List[PronounCandidate],
    ) -> List[PronounCandidate]:
        """候補の重複を除去"""
        seen = set()
        unique = []

        for candidate in candidates:
            if candidate.entity not in seen:
                seen.add(candidate.entity)
                unique.append(candidate)

        return unique

    # =========================================================================
    # 結果構築
    # =========================================================================

    def _build_result(
        self,
        pronoun: str,
        distance: PronounDistance,
        pronoun_type: PronounType,
        candidates: List[PronounCandidate],
    ) -> PronounResolutionResult:
        """解決結果を構築"""
        if not candidates:
            # 候補なし → 確認必要
            logger.debug(f"No candidates found for '{pronoun}'")
            return PronounResolutionResult(
                pronoun=pronoun,
                resolved_to=None,
                confidence=0.0,
                needs_confirmation=True,
                candidates=[],
                distance=distance,
                pronoun_type=pronoun_type,
            )

        best = candidates[0]

        # 確信度が閾値未満 → 確認必要
        needs_confirmation = best.confidence < self.CONFIRMATION_THRESHOLD

        if needs_confirmation:
            logger.debug(
                f"Low confidence ({best.confidence:.2f} < {self.CONFIRMATION_THRESHOLD}) "
                f"for '{pronoun}' → '{best.entity}', needs confirmation"
            )
        else:
            logger.info(
                f"Resolved '{pronoun}' → '{best.entity}' "
                f"(confidence={best.confidence:.2f})"
            )

        return PronounResolutionResult(
            pronoun=pronoun,
            resolved_to=best.entity if not needs_confirmation else None,
            confidence=best.confidence,
            needs_confirmation=needs_confirmation,
            candidates=candidates[:4],  # 上位4つを保持
            distance=distance,
            pronoun_type=pronoun_type,
        )


# =============================================================================
# ファクトリー関数
# =============================================================================


def create_pronoun_resolver(
    conversation_history: Optional[List[Dict[str, Any]]] = None,
    current_context: Optional[Dict[str, Any]] = None,
    recent_tasks: Optional[List[Dict[str, Any]]] = None,
    person_info: Optional[List[Dict[str, Any]]] = None,
) -> EnhancedPronounResolver:
    """
    EnhancedPronounResolverのインスタンスを作成

    使用例:
        resolver = create_pronoun_resolver(
            conversation_history=messages,
            recent_tasks=tasks,
        )
        result = await resolver.resolve("これ", "これを完了して")
    """
    return EnhancedPronounResolver(
        conversation_history=conversation_history,
        current_context=current_context,
        recent_tasks=recent_tasks,
        person_info=person_info,
    )
