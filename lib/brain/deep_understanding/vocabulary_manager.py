# lib/brain/deep_understanding/vocabulary_manager.py
"""
Phase 2I: 理解力強化（Deep Understanding）- 組織固有語彙辞書

設計書: docs/17_brain_completion_roadmap.md セクション17.3 Phase 2I

このファイルには、組織固有の語彙・表現を管理する機能を実装します。

【主な機能】
- 組織固有語彙の登録・検索・更新
- 会話からの自動語彙学習
- エイリアスと関連語の管理
- 語彙の使用頻度トラッキング

Author: Claude Opus 4.5
Created: 2026-01-27
"""

import logging
import re
import time
from datetime import datetime
from typing import Optional, List, Dict, Any, Set
from uuid import uuid4

from .constants import (
    VocabularyCategory,
    OrganizationContextType,
    DEFAULT_ORGANIZATION_VOCABULARY,
    MAX_VOCABULARY_ENTRIES_PER_ORG,
    MIN_OCCURRENCE_FOR_VOCABULARY_LEARNING,
)
from .models import (
    VocabularyEntry,
    VocabularyEntryDB,
    OrganizationContext,
    OrganizationContextResult,
    DeepUnderstandingInput,
)

logger = logging.getLogger(__name__)


class VocabularyManager:
    """
    組織固有語彙管理

    組織ごとの固有語彙（社内用語、略語、プロジェクト名等）を管理し、
    メッセージ内での使用を検出・解決する。

    使用例:
        manager = VocabularyManager(pool=db_pool, organization_id="org_001")
        await manager.initialize()

        # 語彙の検索
        entries = await manager.search("ソウルくん")

        # メッセージ内の語彙解決
        result = await manager.resolve_vocabulary_in_message(
            message="ソウルくんの件どうなった？",
            context=deep_understanding_input,
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

        # メモリキャッシュ（DB接続がない場合の代替）
        self._vocabulary_cache: Dict[str, VocabularyEntry] = {}

        # 出現カウント（語彙学習用）
        self._occurrence_counts: Dict[str, int] = {}

        # 初期化済みフラグ
        self._initialized = False

        logger.info(
            f"VocabularyManager created: organization_id={organization_id}"
        )

    # =========================================================================
    # 初期化
    # =========================================================================

    async def initialize(self) -> None:
        """
        語彙管理の初期化

        DBから語彙をロードし、デフォルト語彙をマージする。
        """
        if self._initialized:
            return

        try:
            # DBから組織の語彙をロード
            if self.pool:
                await self._load_vocabulary_from_db()

            # デフォルト語彙をキャッシュに追加（存在しない場合のみ）
            for term, info in DEFAULT_ORGANIZATION_VOCABULARY.items():
                if term not in self._vocabulary_cache:
                    entry = VocabularyEntry(
                        id=uuid4(),
                        organization_id=self.organization_id,
                        term=term,
                        category=VocabularyCategory(info.get("category", VocabularyCategory.IDIOM.value)),
                        meaning=info.get("meaning", ""),
                        aliases=info.get("aliases", []),
                        is_active=True,
                    )
                    self._vocabulary_cache[term.lower()] = entry

            self._initialized = True
            logger.info(
                f"VocabularyManager initialized: "
                f"entries={len(self._vocabulary_cache)}"
            )

        except Exception as e:
            logger.error(f"Failed to initialize VocabularyManager: {e}")
            self._initialized = True  # 失敗しても続行

    async def _load_vocabulary_from_db(self) -> None:
        """
        DBから語彙をロード
        """
        if not self.pool:
            return

        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT
                        id, organization_id, term, category, meaning,
                        aliases, related_terms, usage_examples,
                        occurrence_count, last_used_at,
                        created_at, updated_at, is_active, metadata
                    FROM organization_vocabulary
                    WHERE organization_id = $1 AND is_active = TRUE
                    ORDER BY occurrence_count DESC
                    LIMIT $2
                    """,
                    self.organization_id,
                    MAX_VOCABULARY_ENTRIES_PER_ORG,
                )

                for row in rows:
                    entry = VocabularyEntry(
                        id=row["id"],
                        organization_id=row["organization_id"],
                        term=row["term"],
                        category=VocabularyCategory(row["category"]),
                        meaning=row["meaning"],
                        aliases=row["aliases"] or [],
                        related_terms=row["related_terms"] or [],
                        usage_examples=row["usage_examples"] or [],
                        occurrence_count=row["occurrence_count"],
                        last_used_at=row["last_used_at"],
                        created_at=row["created_at"],
                        updated_at=row["updated_at"],
                        is_active=row["is_active"],
                        metadata=row["metadata"] or {},
                    )
                    self._vocabulary_cache[entry.term.lower()] = entry

                    # エイリアスもキャッシュに登録
                    for alias in entry.aliases:
                        if alias.lower() not in self._vocabulary_cache:
                            self._vocabulary_cache[alias.lower()] = entry

        except Exception as e:
            logger.warning(f"Failed to load vocabulary from DB: {e}")

    # =========================================================================
    # 語彙の検索
    # =========================================================================

    async def search(
        self,
        query: str,
        limit: int = 10,
    ) -> List[VocabularyEntry]:
        """
        語彙を検索

        Args:
            query: 検索クエリ
            limit: 最大結果数

        Returns:
            List[VocabularyEntry]: マッチした語彙エントリ
        """
        await self.initialize()

        query_lower = query.lower()
        results: List[VocabularyEntry] = []
        seen_ids: Set[str] = set()

        # 完全一致
        if query_lower in self._vocabulary_cache:
            entry = self._vocabulary_cache[query_lower]
            if str(entry.id) not in seen_ids:
                results.append(entry)
                seen_ids.add(str(entry.id))

        # 部分一致
        for term, entry in self._vocabulary_cache.items():
            if str(entry.id) in seen_ids:
                continue
            if query_lower in term or term in query_lower:
                results.append(entry)
                seen_ids.add(str(entry.id))
                if len(results) >= limit:
                    break

        # 関連語・エイリアスでの検索
        if len(results) < limit:
            for term, entry in self._vocabulary_cache.items():
                if str(entry.id) in seen_ids:
                    continue
                # エイリアスをチェック
                for alias in entry.aliases:
                    if query_lower in alias.lower() or alias.lower() in query_lower:
                        results.append(entry)
                        seen_ids.add(str(entry.id))
                        break
                if len(results) >= limit:
                    break

        return results[:limit]

    async def get_by_term(self, term: str) -> Optional[VocabularyEntry]:
        """
        語彙を正確に取得

        Args:
            term: 語彙

        Returns:
            Optional[VocabularyEntry]: 語彙エントリ（存在しない場合はNone）
        """
        await self.initialize()
        return self._vocabulary_cache.get(term.lower())

    # =========================================================================
    # メッセージ内の語彙解決
    # =========================================================================

    async def resolve_vocabulary_in_message(
        self,
        message: str,
        context: DeepUnderstandingInput,
    ) -> OrganizationContextResult:
        """
        メッセージ内の組織語彙を解決

        Args:
            message: ユーザーのメッセージ
            context: 深い理解層への入力コンテキスト

        Returns:
            OrganizationContextResult: 組織文脈解決の結果
        """
        start_time = time.time()
        await self.initialize()

        contexts: List[OrganizationContext] = []
        entries_used: List[VocabularyEntry] = []

        # メッセージ内の語彙を検出
        for term, entry in self._vocabulary_cache.items():
            # メインの語彙をチェック
            if self._contains_term(message, entry.term):
                org_context = OrganizationContext(
                    context_type=self._category_to_context_type(entry.category),
                    original_expression=entry.term,
                    resolved_meaning=entry.meaning,
                    vocabulary_entry=entry,
                    confidence=0.9,
                    source="vocabulary_manager",
                )
                contexts.append(org_context)
                entries_used.append(entry)

                # 使用回数をカウント
                await self._record_usage(entry)

            # エイリアスをチェック
            for alias in entry.aliases:
                if self._contains_term(message, alias) and entry not in entries_used:
                    org_context = OrganizationContext(
                        context_type=self._category_to_context_type(entry.category),
                        original_expression=alias,
                        resolved_meaning=entry.meaning,
                        vocabulary_entry=entry,
                        confidence=0.85,
                        source="vocabulary_manager_alias",
                    )
                    contexts.append(org_context)
                    entries_used.append(entry)
                    await self._record_usage(entry)
                    break

        # 「いつもの」「例の」等の文脈依存表現を処理
        context_dependent = await self._resolve_context_dependent_terms(message, context)
        contexts.extend(context_dependent)

        # 全体の信頼度を計算
        overall_confidence = 0.0
        if contexts:
            overall_confidence = sum(c.confidence for c in contexts) / len(contexts)

        return OrganizationContextResult(
            contexts=contexts,
            vocabulary_entries_used=entries_used,
            overall_confidence=overall_confidence,
            processing_time_ms=self._elapsed_ms(start_time),
        )

    def _contains_term(self, message: str, term: str) -> bool:
        """
        メッセージに語彙が含まれているかチェック
        """
        # 大文字小文字を無視して検索
        message_lower = message.lower()
        term_lower = term.lower()

        # 単純な含有チェック
        if term_lower in message_lower:
            return True

        # 全角・半角の揺れを考慮
        import unicodedata
        message_normalized = unicodedata.normalize("NFKC", message).lower()
        term_normalized = unicodedata.normalize("NFKC", term).lower()

        return term_normalized in message_normalized

    def _category_to_context_type(self, category: VocabularyCategory) -> OrganizationContextType:
        """
        語彙カテゴリを組織文脈タイプに変換
        """
        mapping = {
            VocabularyCategory.PROJECT_NAME: OrganizationContextType.PROJECT,
            VocabularyCategory.PRODUCT_NAME: OrganizationContextType.INTERNAL_TERM,
            VocabularyCategory.ABBREVIATION: OrganizationContextType.INTERNAL_TERM,
            VocabularyCategory.TEAM_NAME: OrganizationContextType.PERSON_ROLE,
            VocabularyCategory.ROLE_NAME: OrganizationContextType.PERSON_ROLE,
            VocabularyCategory.EVENT_NAME: OrganizationContextType.RECURRING_EVENT,
            VocabularyCategory.SYSTEM_NAME: OrganizationContextType.INTERNAL_TERM,
            VocabularyCategory.IDIOM: OrganizationContextType.INTERNAL_TERM,
        }
        return mapping.get(category, OrganizationContextType.INTERNAL_TERM)

    async def _resolve_context_dependent_terms(
        self,
        message: str,
        context: DeepUnderstandingInput,
    ) -> List[OrganizationContext]:
        """
        文脈依存表現（「いつもの」「例の」等）を解決
        """
        contexts: List[OrganizationContext] = []

        # 「いつもの」パターン
        usual_patterns = [
            (r"いつもの(.+?)([をにでがは]|$)", "習慣的な"),
            (r"普段の(.+?)([をにでがは]|$)", "普段の"),
            (r"毎回の(.+?)([をにでがは]|$)", "定例の"),
        ]

        for pattern, prefix in usual_patterns:
            match = re.search(pattern, message)
            if match:
                subject = match.group(1).strip()

                # 直近のコンテキストから候補を探す
                resolved = await self._find_usual_item(subject, context)

                if resolved:
                    contexts.append(OrganizationContext(
                        context_type=OrganizationContextType.INTERNAL_PROCESS,
                        original_expression=f"いつもの{subject}",
                        resolved_meaning=resolved,
                        confidence=0.7,
                        source="context_dependent_resolution",
                    ))

        # 「例の」パターン
        example_patterns = [
            (r"例の(.+?)([をにでがは]|$)", "既出の"),
            (r"あの件の(.+?)([をにでがは]|$)", "前回の"),
        ]

        for pattern, prefix in example_patterns:
            match = re.search(pattern, message)
            if match:
                subject = match.group(1).strip()

                # 直近の会話から候補を探す
                resolved = await self._find_mentioned_item(subject, context)

                if resolved:
                    contexts.append(OrganizationContext(
                        context_type=OrganizationContextType.PROJECT,
                        original_expression=f"例の{subject}",
                        resolved_meaning=resolved,
                        confidence=0.65,
                        source="context_dependent_resolution",
                    ))

        return contexts

    async def _find_usual_item(
        self,
        subject: str,
        context: DeepUnderstandingInput,
    ) -> Optional[str]:
        """
        「いつもの」が指すものを探す
        """
        # 語彙辞書から探す
        for term, entry in self._vocabulary_cache.items():
            if subject in entry.term or entry.term in subject:
                return entry.meaning

        # タスクの履歴から頻出パターンを探す
        if context.recent_tasks:
            for task in context.recent_tasks:
                body = task.get("body", "")
                if subject in body:
                    return str(body[:50])

        return None

    async def _find_mentioned_item(
        self,
        subject: str,
        context: DeepUnderstandingInput,
    ) -> Optional[str]:
        """
        「例の」が指すものを直近の会話から探す
        """
        if context.recent_conversation:
            for msg in reversed(context.recent_conversation):
                msg_content = msg.get("content", "")
                if subject in msg_content:
                    return str(msg_content[:50])

        return None

    # =========================================================================
    # 語彙の追加・更新
    # =========================================================================

    async def add_vocabulary(
        self,
        term: str,
        category: VocabularyCategory,
        meaning: str,
        aliases: Optional[List[str]] = None,
        usage_examples: Optional[List[str]] = None,
    ) -> VocabularyEntry:
        """
        語彙を追加

        Args:
            term: 語彙
            category: カテゴリ
            meaning: 意味
            aliases: エイリアス
            usage_examples: 使用例

        Returns:
            VocabularyEntry: 追加された語彙エントリ
        """
        await self.initialize()

        entry = VocabularyEntry(
            id=uuid4(),
            organization_id=self.organization_id,
            term=term,
            category=category,
            meaning=meaning,
            aliases=aliases or [],
            usage_examples=usage_examples or [],
            occurrence_count=1,
            last_used_at=datetime.now(),
            created_at=datetime.now(),
            updated_at=datetime.now(),
            is_active=True,
        )

        # キャッシュに追加
        self._vocabulary_cache[term.lower()] = entry
        for alias in entry.aliases:
            self._vocabulary_cache[alias.lower()] = entry

        # DBに保存
        if self.pool:
            await self._save_vocabulary_to_db(entry)

        logger.info(f"Added vocabulary: {term} ({category.value})")
        return entry

    async def update_vocabulary(
        self,
        term: str,
        meaning: Optional[str] = None,
        aliases: Optional[List[str]] = None,
        usage_examples: Optional[List[str]] = None,
    ) -> Optional[VocabularyEntry]:
        """
        語彙を更新

        Args:
            term: 語彙
            meaning: 新しい意味（Noneの場合は更新しない）
            aliases: 新しいエイリアス（Noneの場合は更新しない）
            usage_examples: 新しい使用例（Noneの場合は更新しない）

        Returns:
            Optional[VocabularyEntry]: 更新された語彙エントリ
        """
        await self.initialize()

        entry = self._vocabulary_cache.get(term.lower())
        if not entry:
            return None

        if meaning is not None:
            entry.meaning = meaning
        if aliases is not None:
            # 古いエイリアスをキャッシュから削除
            for old_alias in entry.aliases:
                if old_alias.lower() in self._vocabulary_cache:
                    del self._vocabulary_cache[old_alias.lower()]
            entry.aliases = aliases
            # 新しいエイリアスをキャッシュに追加
            for alias in aliases:
                self._vocabulary_cache[alias.lower()] = entry
        if usage_examples is not None:
            entry.usage_examples = usage_examples

        entry.updated_at = datetime.now()

        # DBに保存
        if self.pool:
            await self._save_vocabulary_to_db(entry)

        logger.info(f"Updated vocabulary: {term}")
        return entry

    async def _save_vocabulary_to_db(self, entry: VocabularyEntry) -> None:
        """
        語彙をDBに保存
        """
        if not self.pool:
            return

        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO organization_vocabulary (
                        id, organization_id, term, category, meaning,
                        aliases, related_terms, usage_examples,
                        occurrence_count, last_used_at,
                        created_at, updated_at, is_active, metadata
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
                    ON CONFLICT (organization_id, term)
                    DO UPDATE SET
                        meaning = EXCLUDED.meaning,
                        aliases = EXCLUDED.aliases,
                        related_terms = EXCLUDED.related_terms,
                        usage_examples = EXCLUDED.usage_examples,
                        occurrence_count = EXCLUDED.occurrence_count,
                        last_used_at = EXCLUDED.last_used_at,
                        updated_at = EXCLUDED.updated_at,
                        is_active = EXCLUDED.is_active,
                        metadata = EXCLUDED.metadata
                    """,
                    entry.id,
                    entry.organization_id,
                    entry.term,
                    entry.category.value,
                    entry.meaning,
                    entry.aliases,
                    entry.related_terms,
                    entry.usage_examples,
                    entry.occurrence_count,
                    entry.last_used_at,
                    entry.created_at,
                    entry.updated_at,
                    entry.is_active,
                    entry.metadata,
                )
        except Exception as e:
            logger.warning(f"Failed to save vocabulary to DB: {e}")

    # =========================================================================
    # 使用記録と自動学習
    # =========================================================================

    async def _record_usage(self, entry: VocabularyEntry) -> None:
        """
        語彙の使用を記録
        """
        entry.occurrence_count += 1
        entry.last_used_at = datetime.now()

        # DBに更新（非同期で）
        if self.pool:
            try:
                async with self.pool.acquire() as conn:
                    await conn.execute(
                        """
                        UPDATE organization_vocabulary
                        SET occurrence_count = occurrence_count + 1,
                            last_used_at = $1
                        WHERE id = $2
                        """,
                        entry.last_used_at,
                        entry.id,
                    )
            except Exception as e:
                logger.debug(f"Failed to record usage: {e}")

    async def learn_from_message(
        self,
        message: str,
        context: DeepUnderstandingInput,
    ) -> List[str]:
        """
        メッセージから新しい語彙を学習

        頻出する未知の表現を検出し、語彙候補として記録する。

        Args:
            message: ユーザーのメッセージ
            context: 深い理解層への入力コンテキスト

        Returns:
            List[str]: 学習候補として検出された語彙
        """
        await self.initialize()

        candidates: List[str] = []

        # カギカッコで囲まれた表現を抽出（新語の可能性）
        quoted_patterns = [
            r"「(.+?)」",
            r"『(.+?)』",
            r"\u201c(.+?)\u201d",  # Unicode double quotes
        ]

        for pattern in quoted_patterns:
            matches = re.findall(pattern, message)
            for match in matches:
                if len(match) >= 2 and match.lower() not in self._vocabulary_cache:
                    self._occurrence_counts[match] = self._occurrence_counts.get(match, 0) + 1

                    if self._occurrence_counts[match] >= MIN_OCCURRENCE_FOR_VOCABULARY_LEARNING:
                        candidates.append(match)

        # 英字の略語を抽出
        abbrev_pattern = r"\b([A-Z]{2,6})\b"
        abbrev_matches = re.findall(abbrev_pattern, message)
        for abbrev in abbrev_matches:
            if abbrev.lower() not in self._vocabulary_cache:
                self._occurrence_counts[abbrev] = self._occurrence_counts.get(abbrev, 0) + 1

                if self._occurrence_counts[abbrev] >= MIN_OCCURRENCE_FOR_VOCABULARY_LEARNING:
                    candidates.append(abbrev)

        return candidates

    # =========================================================================
    # ヘルパーメソッド
    # =========================================================================

    def _elapsed_ms(self, start_time: float) -> int:
        """経過時間をミリ秒で返す"""
        return int((time.time() - start_time) * 1000)


# =============================================================================
# ファクトリー関数
# =============================================================================

def create_vocabulary_manager(
    pool: Optional[Any] = None,
    organization_id: str = "",
) -> VocabularyManager:
    """
    VocabularyManagerを作成

    Args:
        pool: データベース接続プール
        organization_id: 組織ID

    Returns:
        VocabularyManager: 語彙管理インスタンス
    """
    return VocabularyManager(
        pool=pool,
        organization_id=organization_id,
    )


# =============================================================================
# エクスポート
# =============================================================================

__all__ = [
    "VocabularyManager",
    "create_vocabulary_manager",
]
