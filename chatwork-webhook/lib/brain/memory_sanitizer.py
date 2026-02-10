# lib/brain/memory_sanitizer.py
"""
メモリ表示時のPIIマスキング

ユーザーに記憶内容を表示する際、機密情報をマスキングする。
Phase 1-C: メモリ可視化UXの安全性レイヤー。

【設計原則】
- CLAUDE.md 8-2: PIIは保存しない（memory_flush.pyで防止）
- 万一PIIが保存されていた場合の二重防御として表示時もマスキング
- CLAUDE.md 8-4: 思考過程のPIIマスキングと同じパターンを適用

Author: Claude Code
Created: 2026-02-07
"""

import re
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# マスキングパターン
# =============================================================================

# パターン名とマスク文字列のペア
MASK_PATTERNS = [
    (re.compile(r'0\d{1,4}-\d{1,4}-\d{3,4}'), "[PHONE]"),
    (re.compile(r'0\d{9,10}'), "[PHONE]"),
    (re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'), "[EMAIL]"),
    (re.compile(r'(?:パスワード|password|pw|pass)[：:\s]*\S+', re.IGNORECASE), "[PASSWORD]"),
    (re.compile(r'(?:APIキー|api.?key|token|secret)[：:\s]*\S+', re.IGNORECASE), "[API_KEY]"),
    (re.compile(r'(?:給与|年収|月収|月額|時給)[：:\s]*\d+', re.IGNORECASE), "[SALARY]"),
]

# カテゴリの日本語表示名
CATEGORY_LABELS = {
    "fact": "事実",
    "preference": "好み・設定",
    "commitment": "約束・コミットメント",
    "decision": "決定事項",
    "communication": "コミュニケーション設定",
    "response_style": "回答スタイル",
    "feature_usage": "機能の使い方",
    "schedule": "スケジュール",
    "emotion_trend": "感情傾向",
}


# =============================================================================
# データクラス
# =============================================================================


@dataclass
class SanitizedMemory:
    """マスキング済みメモリ項目"""
    id: str
    category: str
    category_label: str
    title: str
    content: str
    confidence: float = 0.0
    source: str = ""  # "auto_flush", "explicit", "inferred"
    was_masked: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "category": self.category,
            "category_label": self.category_label,
            "title": self.title,
            "content": self.content,
            "confidence": self.confidence,
            "source": self.source,
        }


@dataclass
class MemoryViewResult:
    """メモリ閲覧結果"""
    memories: List[SanitizedMemory] = field(default_factory=list)
    total_count: int = 0
    masked_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "memories": [m.to_dict() for m in self.memories],
            "total_count": self.total_count,
            "masked_count": self.masked_count,
        }

    def to_display_text(self) -> str:
        """ChatWork向けの表示テキスト生成"""
        if not self.memories:
            return "現在、覚えている情報はありません。"

        lines = [f"覚えている情報（{self.total_count}件）:"]
        # カテゴリ別にグルーピング
        by_category: Dict[str, List[SanitizedMemory]] = {}
        for m in self.memories:
            by_category.setdefault(m.category_label, []).append(m)

        for cat_label, items in by_category.items():
            lines.append(f"\n[{cat_label}]")
            for item in items:
                lines.append(f"  - {item.title}: {item.content}")

        return "\n".join(lines)


# =============================================================================
# マスキング関数
# =============================================================================


def mask_pii(text: str) -> tuple[str, bool]:
    """
    テキスト内のPIIをマスキング

    Args:
        text: 元テキスト

    Returns:
        (マスキング済みテキスト, マスキングが適用されたか)
    """
    if not text:
        return text, False

    masked = text
    was_masked = False

    for pattern, replacement in MASK_PATTERNS:
        new_text = pattern.sub(replacement, masked)
        if new_text != masked:
            was_masked = True
            masked = new_text

    return masked, was_masked


def get_category_label(category: str) -> str:
    """カテゴリの日本語表示名を取得"""
    return CATEGORY_LABELS.get(category, category)


# =============================================================================
# メモリ閲覧・削除
# =============================================================================


class MemoryViewer:
    """
    ユーザーの記憶閲覧・削除機能

    ユーザーが「何を覚えてる？」と聞いたときに、
    カテゴリ別の記憶一覧をPIIマスキング付きで返す。
    """

    def __init__(self, pool, org_id: str):
        """
        Args:
            pool: SQLAlchemyデータベース接続プール
            org_id: 組織ID
        """
        self.pool = pool
        self.org_id = org_id

    def get_user_memories(
        self,
        user_id: str,
        category: Optional[str] = None,
        limit: int = 50,
    ) -> MemoryViewResult:
        """
        ユーザーの記憶を取得（PIIマスキング付き）

        user_preferencesはユーザー個人にスコープされる。
        soulkun_knowledgeは組織共有ナレッジ（事実・決定・約束）であり、
        同一組織の全ユーザーに表示される（Phase 4でuser_idカラム追加予定）。

        Args:
            user_id: ユーザーのchatwork_account_id
            category: フィルタするカテゴリ（省略時は全カテゴリ）
            limit: 最大取得件数（上限100）

        Returns:
            MemoryViewResult
        """
        from sqlalchemy import text as sql_text

        # HIGH-1: limit clamping（CLAUDE.md Rule #5: 1000件超えはページネーション）
        limit = max(1, min(limit, 100))

        memories = []
        masked_count = 0

        try:
            with self.pool.connect() as conn:
                # 1. user_preferences（好み・設定）
                pref_query = """
                    SELECT
                        up.id::text,
                        up.preference_type,
                        up.preference_key,
                        up.preference_value,
                        up.confidence,
                        up.learned_from
                    FROM user_preferences up
                    JOIN users u ON u.id = up.user_id
                    JOIN organizations o ON o.id = up.organization_id
                    WHERE o.id = CAST(:org_id AS uuid)
                      AND u.chatwork_account_id = :user_id
                """
                params: Dict[str, Any] = {
                    "org_id": self.org_id,
                    "user_id": user_id,
                    "limit": limit,
                }

                if category and category in ("preference", "communication",
                                               "response_style", "feature_usage",
                                               "schedule", "emotion_trend"):
                    pref_query += " AND up.preference_type = :category"
                    params["category"] = category

                pref_query += " ORDER BY up.updated_at DESC LIMIT :limit"

                rows = conn.execute(sql_text(pref_query), params).fetchall()

                for row in rows:
                    content, was_masked = mask_pii(str(row[3] or ""))
                    title, title_masked = mask_pii(str(row[2] or ""))
                    if was_masked or title_masked:
                        masked_count += 1

                    memories.append(SanitizedMemory(
                        id=row[0],
                        category=row[1] or "preference",
                        category_label=get_category_label(row[1] or "preference"),
                        title=title,
                        content=content,
                        confidence=float(row[4] or 0.5),
                        source=row[5] or "unknown",
                        was_masked=was_masked or title_masked,
                    ))

                # 2. soulkun_knowledge（自動フラッシュされた事実・決定・約束）
                # Phase 4完了: org_idカラムでテナント分離
                # 注意: このテーブルにはuser_idがなく、組織共有ナレッジとして扱う
                knowledge_query = """
                    SELECT
                        id::text,
                        category,
                        key,
                        value
                    FROM soulkun_knowledge
                    WHERE organization_id = :org_id
                      AND source = 'auto_flush'
                """
                k_params: Dict[str, Any] = {
                    "org_id": self.org_id,
                    "limit": limit,
                }

                if category and category in ("fact", "decision", "commitment"):
                    knowledge_query += " AND category = :category"
                    k_params["category"] = category

                knowledge_query += " ORDER BY updated_at DESC LIMIT :limit"

                k_rows = conn.execute(sql_text(knowledge_query), k_params).fetchall()

                for row in k_rows:
                    content, was_masked = mask_pii(str(row[3] or ""))
                    raw_title = str(row[2] or "")
                    title, title_masked = mask_pii(raw_title)

                    if was_masked or title_masked:
                        masked_count += 1

                    memories.append(SanitizedMemory(
                        id=row[0],
                        category=row[1] or "fact",
                        category_label=get_category_label(row[1] or "fact"),
                        title=title,
                        content=content,
                        confidence=0.8,
                        source="auto_flush",
                        was_masked=was_masked or title_masked,
                    ))

        except Exception as e:
            logger.warning("Error fetching user memories: %s", e)

        return MemoryViewResult(
            memories=memories,
            total_count=len(memories),
            masked_count=masked_count,
        )

    def delete_user_memory(
        self,
        memory_id: str,
        user_id: str,
        memory_type: str = "preference",
    ) -> bool:
        """
        ユーザーの記憶を削除

        preferenceはユーザー個人の記憶（所有者確認付き削除）。
        knowledgeは組織共有ナレッジ（org_idスコープで削除）。

        Args:
            memory_id: 削除する記憶のID
            user_id: リクエストしたユーザーのchatwork_account_id（所有者確認用）
            memory_type: "preference" or "knowledge"

        Returns:
            削除成功したかどうか
        """
        from sqlalchemy import text as sql_text

        # HIGH-2: memory_idのフォーマット検証
        if memory_type == "preference":
            import uuid
            try:
                uuid.UUID(memory_id)
            except (ValueError, AttributeError):
                logger.warning("Invalid preference memory_id (not UUID): %s", memory_id)
                return False
        elif memory_type == "knowledge":
            try:
                int(memory_id)
            except (ValueError, TypeError):
                logger.warning("Invalid knowledge memory_id (not integer): %s", memory_id)
                return False
        else:
            logger.warning("Unknown memory_type: %s", memory_type)
            return False

        try:
            with self.pool.connect() as conn:
                if memory_type == "preference":
                    # 所有者確認付き削除
                    result = conn.execute(
                        sql_text("""
                            DELETE FROM user_preferences
                            WHERE id = CAST(:memory_id AS UUID)
                              AND organization_id = (
                                  SELECT id FROM organizations WHERE id = CAST(:org_id AS uuid)
                              )
                              AND user_id = (
                                  SELECT u.id FROM users u
                                  JOIN organizations o ON o.id = u.organization_id
                                  WHERE o.id = CAST(:org_id AS uuid)
                                    AND u.chatwork_account_id = :user_id
                              )
                        """),
                        {
                            "memory_id": memory_id,
                            "org_id": self.org_id,
                            "user_id": user_id,
                        },
                    )
                    conn.commit()
                    deleted = result.rowcount > 0

                else:  # knowledge
                    # Phase 4完了: org_idカラムでテナント分離
                    result = conn.execute(
                        sql_text("""
                            DELETE FROM soulkun_knowledge
                            WHERE id = CAST(:memory_id AS INTEGER)
                              AND organization_id = :org_id
                              AND source = 'auto_flush'
                        """),
                        {
                            "memory_id": memory_id,
                            "org_id": self.org_id,
                        },
                    )
                    conn.commit()
                    deleted = result.rowcount > 0

                if deleted:
                    logger.info(
                        "Memory deleted: id=%s type=%s user=%s",
                        memory_id, memory_type, user_id,
                    )
                return deleted

        except Exception as e:
            # HIGH-3: connはwithブロック内でのみ有効。
            # SQLAlchemyのコンテキストマネージャが自動rollbackするため手動不要。
            logger.warning("Error deleting memory: %s", e)
            return False
