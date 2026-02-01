# lib/brain/deep_understanding/person_alias.py
"""
人名エイリアスリゾルバー

「崇樹さん」→「崇樹」のような敬称除去、エイリアス生成、DB照合を行う。

【機能】
1. 敬称の除去（崇樹さん → 崇樹）
2. エイリアス自動生成（崇樹 → 崇樹さん, 崇樹くん, 崇樹君）
3. DBとの照合
4. 複数候補時は確認モード

【設計書参照】
- docs/13_brain_architecture.md セクション6「理解層」
  - 6.4 曖昧表現の解決パターン（敬称バリエーション）
- docs/17_brain_completion_roadmap.md セクション17.3 Phase 2I「理解力強化」
  - 暗黙の意図推測
- CLAUDE.md セクション4「意図の取り違え検知ルール」
  - 確信度70%未満で確認質問

Author: Claude Opus 4.5
Created: 2026-01-29
"""

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any, Callable, Protocol

from lib.brain.constants import CONFIRMATION_THRESHOLD

logger = logging.getLogger(__name__)


# =============================================================================
# 定数
# =============================================================================


# 敬称リスト（除去対象）
HONORIFICS: List[str] = [
    "さん",
    "くん",
    "君",
    "ちゃん",
    "氏",
    "様",
    "殿",
    "先生",
    "部長",
    "課長",
    "社長",
    "代表",
]

# エイリアス生成用敬称（よく使われるもの）
COMMON_HONORIFICS: List[str] = [
    "さん",
    "くん",
    "ちゃん",
]

# 読み仮名パターン（括弧内のカタカナ）
READING_PATTERN = re.compile(r'\s*[\(（][^)）]*[\)）]\s*')

# スペースパターン（全角・半角）
SPACE_PATTERN = re.compile(r'[\s　]+')


# =============================================================================
# データクラス
# =============================================================================


class MatchType(Enum):
    """マッチの種類"""
    EXACT = "exact"  # 完全一致
    NORMALIZED = "normalized"  # 正規化後一致
    ALIAS = "alias"  # エイリアス一致
    PARTIAL = "partial"  # 部分一致


@dataclass
class PersonCandidate:
    """
    人名解決の候補

    Attributes:
        name: 正式名（DB上の名前）
        input_name: 入力された名前
        match_type: マッチの種類
        confidence: 確信度（0.0-1.0）
        matched_alias: マッチしたエイリアス（エイリアスマッチの場合）
    """
    name: str
    input_name: str
    match_type: MatchType
    confidence: float = 0.5
    matched_alias: Optional[str] = None

    def __post_init__(self):
        """確信度をマッチタイプに基づいて調整"""
        if self.confidence == 0.5:  # デフォルト値の場合
            type_confidence = {
                MatchType.EXACT: 1.0,
                MatchType.NORMALIZED: 0.95,
                MatchType.ALIAS: 0.85,
                MatchType.PARTIAL: 0.6,
            }
            self.confidence = type_confidence.get(self.match_type, 0.5)


@dataclass
class PersonResolutionResult:
    """
    人名解決の結果

    Attributes:
        input_name: 入力された名前
        resolved_to: 解決結果（Noneの場合は解決失敗）
        confidence: 確信度
        needs_confirmation: 確認が必要か
        candidates: 候補リスト（確認時に使用）
        match_type: マッチの種類
    """
    input_name: str
    resolved_to: Optional[str] = None
    confidence: float = 0.0
    needs_confirmation: bool = False
    candidates: List[PersonCandidate] = field(default_factory=list)
    match_type: Optional[MatchType] = None

    def get_confirmation_options(self) -> List[str]:
        """確認用の選択肢を取得"""
        return [c.name for c in self.candidates[:4]]  # 最大4つ


# =============================================================================
# Protocol定義（依存注入用）
# =============================================================================


class PersonLookupProtocol(Protocol):
    """人名検索のプロトコル"""

    def search_by_name(self, name: str) -> List[str]:
        """名前で人物を検索し、マッチした名前のリストを返す"""
        ...

    def get_all_names(self) -> List[str]:
        """全人物名を取得"""
        ...


# =============================================================================
# PersonAliasResolver クラス
# =============================================================================


class PersonAliasResolver:
    """
    人名エイリアスリゾルバー

    機能:
    1. 敬称の除去（崇樹さん → 崇樹）
    2. エイリアス自動生成（崇樹 → 崇樹さん, 崇樹くん, 崇樹君）
    3. DBとの照合
    4. 複数候補時は確認モード（CLAUDE.md準拠）

    使用例:
        resolver = PersonAliasResolver(
            person_lookup=person_service_adapter,
        )

        result = await resolver.resolve("田中さん")
        if result.needs_confirmation:
            options = result.get_confirmation_options()
    """

    # 確認が必要な閾値（CLAUDE.md セクション4-1準拠）
    CONFIRMATION_THRESHOLD = CONFIRMATION_THRESHOLD

    def __init__(
        self,
        person_lookup: Optional[PersonLookupProtocol] = None,
        known_persons: Optional[List[str]] = None,
    ):
        """
        Args:
            person_lookup: 人名検索サービス（オプション）
            known_persons: 既知の人物名リスト（person_lookupがない場合に使用）
        """
        self._person_lookup = person_lookup
        self._known_persons = known_persons or []

        logger.debug(
            f"PersonAliasResolver initialized: "
            f"lookup={'yes' if person_lookup else 'no'}, "
            f"known_persons={len(self._known_persons)}"
        )

    # =========================================================================
    # メインエントリーポイント
    # =========================================================================

    async def resolve(
        self,
        input_name: str,
    ) -> PersonResolutionResult:
        """
        人名を解決

        Args:
            input_name: 入力された人名（敬称付きでも可）

        Returns:
            PersonResolutionResult: 解決結果
        """
        if not input_name or not input_name.strip():
            return PersonResolutionResult(
                input_name=input_name,
                resolved_to=None,
                confidence=0.0,
                needs_confirmation=True,
            )

        input_name = input_name.strip()

        # 1. 正規化
        normalized = self.normalize_name(input_name)

        # 2. エイリアスを生成
        aliases = self.generate_aliases(normalized)

        # 3. 候補を検索
        candidates = await self._find_candidates(input_name, normalized, aliases)

        # 4. 結果を構築
        return self._build_result(input_name, candidates)

    def resolve_sync(
        self,
        input_name: str,
    ) -> PersonResolutionResult:
        """同期版のresolve（テスト用）

        Python 3.10+ 対応: 新しいイベントループを作成して実行
        """
        import asyncio

        # 新しいイベントループを作成して実行（Python 3.10+ 対応）
        return asyncio.run(self.resolve(input_name))

    # =========================================================================
    # 正規化
    # =========================================================================

    def normalize_name(self, name: str) -> str:
        """
        人名を正規化

        1. 読み仮名部分 (xxx) を除去
        2. 敬称を除去
        3. スペース（全角・半角）を除去

        Args:
            name: 正規化前の名前

        Returns:
            正規化された名前
        """
        if not name:
            return name

        # 1. 読み仮名部分を除去
        normalized = READING_PATTERN.sub('', name)

        # 2. 敬称を除去
        normalized = self.remove_honorific(normalized)

        # 3. スペースを除去
        normalized = SPACE_PATTERN.sub('', normalized)

        logger.debug(f"Normalized name: '{name}' → '{normalized}'")
        return normalized.strip()

    def remove_honorific(self, name: str) -> str:
        """
        敬称を除去

        Args:
            name: 敬称付きの名前

        Returns:
            敬称を除去した名前
        """
        if not name:
            return name

        for honorific in HONORIFICS:
            if name.endswith(honorific):
                return name[:-len(honorific)]

        return name

    # =========================================================================
    # エイリアス生成
    # =========================================================================

    def generate_aliases(self, base_name: str) -> List[str]:
        """
        エイリアスを生成

        Args:
            base_name: ベースとなる名前（敬称なし）

        Returns:
            エイリアスのリスト
        """
        if not base_name:
            return []

        aliases = [base_name]  # 本体も含める

        # 敬称付きのエイリアスを生成
        for honorific in COMMON_HONORIFICS:
            aliases.append(f"{base_name}{honorific}")

        # 名字だけ、名前だけのパターン（2文字以上の場合）
        if len(base_name) >= 4:
            # 日本人の名前は通常2文字ずつ
            # 名字（最初の2文字）
            aliases.append(base_name[:2])
            # 名前（残りの文字）
            aliases.append(base_name[2:])

        logger.debug(f"Generated aliases for '{base_name}': {aliases}")
        return aliases

    # =========================================================================
    # 候補検索
    # =========================================================================

    async def _find_candidates(
        self,
        input_name: str,
        normalized: str,
        aliases: List[str],
    ) -> List[PersonCandidate]:
        """
        候補を検索

        Args:
            input_name: 入力された名前
            normalized: 正規化された名前
            aliases: エイリアスリスト

        Returns:
            候補リスト
        """
        candidates: List[PersonCandidate] = []

        # 既知の人物名を取得
        known_names = await self._get_known_names()

        if not known_names:
            # 既知の名前がない場合、入力をそのまま候補に
            logger.debug("No known persons, using input as candidate")
            candidates.append(
                PersonCandidate(
                    name=normalized,
                    input_name=input_name,
                    match_type=MatchType.NORMALIZED,
                    confidence=0.5,  # 低確信度
                )
            )
            return candidates

        # 1. 完全一致を検索
        for known_name in known_names:
            if known_name == input_name:
                candidates.append(
                    PersonCandidate(
                        name=known_name,
                        input_name=input_name,
                        match_type=MatchType.EXACT,
                    )
                )
                # 完全一致が見つかったら早期リターン
                return candidates

        # 2. 正規化後一致を検索
        for known_name in known_names:
            known_normalized = self.normalize_name(known_name)
            if known_normalized == normalized:
                candidates.append(
                    PersonCandidate(
                        name=known_name,
                        input_name=input_name,
                        match_type=MatchType.NORMALIZED,
                    )
                )

        if candidates:
            return candidates

        # 3. エイリアス一致を検索
        for known_name in known_names:
            known_normalized = self.normalize_name(known_name)
            known_aliases = self.generate_aliases(known_normalized)

            for alias in aliases:
                if alias in known_aliases or known_normalized == alias:
                    candidates.append(
                        PersonCandidate(
                            name=known_name,
                            input_name=input_name,
                            match_type=MatchType.ALIAS,
                            matched_alias=alias,
                        )
                    )
                    break  # 同じ人物が複数回追加されないように

        if candidates:
            return candidates

        # 4. 部分一致を検索
        for known_name in known_names:
            known_normalized = self.normalize_name(known_name)
            # 入力が既知の名前に含まれる、または既知の名前が入力に含まれる
            if normalized in known_normalized or known_normalized in normalized:
                candidates.append(
                    PersonCandidate(
                        name=known_name,
                        input_name=input_name,
                        match_type=MatchType.PARTIAL,
                    )
                )

        return candidates

    async def _get_known_names(self) -> List[str]:
        """既知の人物名を取得"""
        if self._person_lookup:
            try:
                return self._person_lookup.get_all_names()
            except Exception as e:
                logger.error(f"Failed to get known names: {e}")
                return self._known_persons
        return self._known_persons

    # =========================================================================
    # 結果構築
    # =========================================================================

    def _build_result(
        self,
        input_name: str,
        candidates: List[PersonCandidate],
    ) -> PersonResolutionResult:
        """解決結果を構築"""
        if not candidates:
            # 候補なし → 確認必要
            logger.debug(f"No candidates found for '{input_name}'")
            return PersonResolutionResult(
                input_name=input_name,
                resolved_to=None,
                confidence=0.0,
                needs_confirmation=True,
                candidates=[],
            )

        # 確信度でソート
        candidates.sort(key=lambda c: c.confidence, reverse=True)

        best = candidates[0]

        # 複数候補がある場合、または確信度が低い場合は確認必要
        needs_confirmation = (
            len(candidates) > 1
            or best.confidence < self.CONFIRMATION_THRESHOLD
        )

        if needs_confirmation:
            logger.debug(
                f"Multiple candidates or low confidence for '{input_name}': "
                f"{len(candidates)} candidates, best confidence={best.confidence:.2f}"
            )
            return PersonResolutionResult(
                input_name=input_name,
                resolved_to=None,
                confidence=best.confidence,
                needs_confirmation=True,
                candidates=candidates[:4],  # 上位4つ
                match_type=best.match_type,
            )

        logger.info(
            f"Resolved '{input_name}' → '{best.name}' "
            f"(type={best.match_type.value}, confidence={best.confidence:.2f})"
        )
        return PersonResolutionResult(
            input_name=input_name,
            resolved_to=best.name,
            confidence=best.confidence,
            needs_confirmation=False,
            candidates=[best],
            match_type=best.match_type,
        )


# =============================================================================
# アダプタークラス
# =============================================================================


class PersonServiceAdapter:
    """
    PersonServiceをPersonLookupProtocolに適合させるアダプター

    使用例:
        from lib.person_service import PersonService

        person_service = PersonService(get_pool)
        adapter = PersonServiceAdapter(person_service)
        resolver = PersonAliasResolver(person_lookup=adapter)
    """

    def __init__(self, person_service: Any):
        """
        Args:
            person_service: PersonServiceインスタンス
        """
        self._service = person_service
        self._cached_names: Optional[List[str]] = None

    def search_by_name(self, name: str) -> List[str]:
        """名前で人物を検索"""
        return self._service.search_person_by_partial_name(name)

    def get_all_names(self) -> List[str]:
        """全人物名を取得（キャッシュあり）"""
        if self._cached_names is None:
            summaries = self._service.get_all_persons_summary()
            self._cached_names = [s["name"] for s in summaries]
        return self._cached_names

    def clear_cache(self):
        """キャッシュをクリア"""
        self._cached_names = None


# =============================================================================
# ファクトリー関数
# =============================================================================


def create_person_alias_resolver(
    person_lookup: Optional[PersonLookupProtocol] = None,
    known_persons: Optional[List[str]] = None,
) -> PersonAliasResolver:
    """
    PersonAliasResolverのインスタンスを作成

    使用例:
        resolver = create_person_alias_resolver(
            known_persons=["田中太郎", "山田花子"],
        )
        result = await resolver.resolve("田中さん")
    """
    return PersonAliasResolver(
        person_lookup=person_lookup,
        known_persons=known_persons,
    )
