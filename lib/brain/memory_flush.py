# lib/brain/memory_flush.py
"""
自動メモリフラッシュ

会話履歴がコンテキストから押し出される前に、重要な情報を自動的に抽出・永続化する。
OpenClawの「Auto Memory Flush」アイデアをsoul-kunの設計思想で独自実装。

【設計原則】
- 脳（Brain）を経由する: LLMで重要情報を抽出
- Truth順位準拠: 抽出結果はDB（2位）に永続化
- PII保護: 機密情報は保存しない
- 10の鉄則準拠: organization_idフィルタ必須

【フラッシュ対象】
1. 事実（FactExtraction）: 「田中さんは営業部長」
2. ユーザーの好み（PreferenceExtraction）: 「簡潔な報告を好む」
3. 約束・コミットメント（CommitmentExtraction）: 「金曜までにやる」
4. 決定事項（DecisionExtraction）: 「来月から在宅週3日」

Author: Claude Code
Created: 2026-02-07
"""

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)


# =============================================================================
# PIIフィルタ（Codexレビュー指摘: PII保護の強制）
# =============================================================================

# PIIパターン（検出時にコンテンツを永続化しない）
PII_PATTERNS = [
    re.compile(r'0\d{1,4}-\d{1,4}-\d{3,4}'),          # 電話番号（ハイフン区切り: 090-1234-5678等）
    re.compile(r'0\d{9,10}'),                           # 電話番号（ハイフンなし: 09012345678等）
    re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'),  # メールアドレス
    re.compile(r'(?:パスワード|password|pw|pass)[：:\s]*\S+', re.IGNORECASE),  # パスワード
    re.compile(r'(?:APIキー|api.?key|token|secret)[：:\s]*\S+', re.IGNORECASE),  # APIキー等
    re.compile(r'(?:給与|年収|月収|月額|時給)[：:\s]*\d+', re.IGNORECASE),  # 給与情報
]


def contains_pii(text: str) -> bool:
    """テキストにPII（個人識別情報）が含まれるか判定"""
    for pattern in PII_PATTERNS:
        if pattern.search(text):
            return True
    return False


# =============================================================================
# データクラス
# =============================================================================


@dataclass
class ExtractedMemory:
    """LLMが抽出した重要情報"""
    category: str  # "fact", "preference", "commitment", "decision"
    content: str
    subject: str  # 誰/何についてか
    confidence: float = 0.7
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "content": self.content,
            "subject": self.subject,
            "confidence": self.confidence,
            "metadata": self.metadata,
        }


@dataclass
class FlushResult:
    """フラッシュ結果"""
    flushed_count: int = 0
    skipped_count: int = 0
    error_count: int = 0
    extracted_items: List[ExtractedMemory] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.error_count == 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "flushed_count": self.flushed_count,
            "skipped_count": self.skipped_count,
            "error_count": self.error_count,
            "extracted_items": [item.to_dict() for item in self.extracted_items],
            "errors": self.errors,
        }


# =============================================================================
# フラッシュ閾値
# =============================================================================

# 会話履歴がこの件数に達したらフラッシュを実行
FLUSH_TRIGGER_COUNT: int = 8

# 抽出された情報の最小確信度（これ未満は保存しない）
MIN_FLUSH_CONFIDENCE: float = 0.6

# 1回のフラッシュで抽出する最大件数
MAX_FLUSH_ITEMS: int = 10


# =============================================================================
# LLM抽出プロンプト
# =============================================================================

EXTRACTION_SYSTEM_PROMPT = """あなたは会話から重要な情報を抽出するアシスタントです。
以下の会話履歴から、永続的に記憶すべき重要情報を抽出してください。

【抽出カテゴリ】
1. fact: 事実情報（「田中さんは営業部長」「プロジェクトAの期限は3月末」）
2. preference: ユーザーの好み（「簡潔な報告を好む」「朝9時に通知希望」）
3. commitment: 約束・コミットメント（「金曜までに資料を提出する」）
4. decision: 決定事項（「来月から在宅勤務を週3日にする」）

【抽出しないもの】
- 挨拶・雑談
- 一時的な話題（「今日は天気がいい」）
- パスワード・トークン・APIキー等の機密情報
- 第三者の個人的な連絡先（電話番号、メールアドレス）
- 給与・評価等の機密情報

【出力形式】
JSON配列で出力してください。該当する情報がなければ空配列 [] を返してください。
```json
[
  {
    "category": "fact",
    "content": "田中さんは営業部の部長",
    "subject": "田中さん",
    "confidence": 0.9
  }
]
```"""

EXTRACTION_USER_PROMPT_TEMPLATE = """以下の会話から重要情報を抽出してください。

【会話履歴】
{conversation}

重要情報をJSON配列で出力してください。"""


# =============================================================================
# メインクラス
# =============================================================================


class AutoMemoryFlusher:
    """
    コンテキスト圧縮前の重要情報自動保存

    会話履歴が閾値に達した時点で、LLMを使って重要情報を抽出し、
    カテゴリ別に永続化する。
    """

    def __init__(
        self,
        pool,
        org_id: str,
        ai_client=None,
    ):
        """
        Args:
            pool: SQLAlchemyデータベース接続プール
            org_id: 組織ID
            ai_client: AI呼び出しクライアント（LLM抽出用）
        """
        self.pool = pool
        self.org_id = org_id
        self.ai_client = ai_client

    def should_flush(self, conversation_count: int) -> bool:
        """フラッシュが必要かどうかを判定"""
        return conversation_count >= FLUSH_TRIGGER_COUNT

    async def flush(
        self,
        conversation_history: List[Dict[str, Any]],
        user_id: str,
        room_id: str,
    ) -> FlushResult:
        """
        会話履歴から重要情報を抽出して永続化する

        Args:
            conversation_history: 会話履歴（role, content, timestamp）
            user_id: ユーザーのアカウントID
            room_id: ルームID

        Returns:
            FlushResult: フラッシュ結果
        """
        result = FlushResult()

        if not conversation_history:
            return result

        try:
            # Step 1: LLMで重要情報を抽出
            extracted = await self._extract_important_info(conversation_history)
            result.extracted_items = extracted

            if not extracted:
                logger.debug(f"No important info extracted from {len(conversation_history)} messages")
                return result

            # Step 2: 確信度フィルタ
            filtered = [
                item for item in extracted
                if item.confidence >= MIN_FLUSH_CONFIDENCE
            ]
            result.skipped_count = len(extracted) - len(filtered)

            # Step 3: カテゴリ別に永続化
            for item in filtered[:MAX_FLUSH_ITEMS]:
                try:
                    persisted = await self._persist_item(item, user_id, room_id)
                    if persisted:
                        result.flushed_count += 1
                    else:
                        result.skipped_count += 1  # PIIスキップ等
                except Exception as e:
                    logger.warning(f"Failed to persist flush item: {e}")
                    result.error_count += 1
                    result.errors.append(str(e))

            logger.info(
                f"Memory flush completed: {result.flushed_count} saved, "
                f"{result.skipped_count} skipped, {result.error_count} errors"
            )

        except Exception as e:
            logger.error(f"Memory flush failed: {e}")
            result.error_count += 1
            result.errors.append(str(e))

        return result

    async def _extract_important_info(
        self,
        conversation_history: List[Dict[str, Any]],
    ) -> List[ExtractedMemory]:
        """LLMを使って会話から重要情報を抽出"""

        # 会話履歴をテキスト化
        conversation_text = self._format_conversation(conversation_history)

        if not conversation_text.strip():
            return []

        # AIクライアントがない場合はルールベースフォールバック
        if not self.ai_client:
            logger.debug("No AI client configured, using rule-based extraction")
            return self._rule_based_extraction(conversation_history)

        try:
            prompt = EXTRACTION_USER_PROMPT_TEMPLATE.format(
                conversation=conversation_text
            )

            response = await self.ai_client.generate(
                system_prompt=EXTRACTION_SYSTEM_PROMPT,
                user_prompt=prompt,
            )

            return self._parse_extraction_response(response)

        except Exception as e:
            logger.warning(f"LLM extraction failed, falling back to rule-based: {e}")
            return self._rule_based_extraction(conversation_history)

    def _format_conversation(
        self,
        conversation_history: List[Dict[str, Any]],
    ) -> str:
        """会話履歴をLLMに渡すテキスト形式に変換"""
        lines = []
        for msg in conversation_history:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            speaker = "ユーザー" if role == "user" else "ソウルくん"
            lines.append(f"{speaker}: {content}")
        return "\n".join(lines)

    def _parse_extraction_response(self, response: str) -> List[ExtractedMemory]:
        """LLMの応答をパースしてExtractedMemoryリストに変換"""
        try:
            # JSON部分を抽出（マークダウンコードブロックに対応）
            text = response.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            items = json.loads(text)

            if not isinstance(items, list):
                return []

            result = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                category = item.get("category", "")
                if category not in ("fact", "preference", "commitment", "decision"):
                    continue
                result.append(ExtractedMemory(
                    category=category,
                    content=item.get("content", ""),
                    subject=item.get("subject", ""),
                    confidence=float(item.get("confidence", 0.7)),
                    metadata=item.get("metadata", {}),
                ))

            return result

        except (json.JSONDecodeError, ValueError, KeyError) as e:
            logger.warning(f"Failed to parse LLM extraction response: {e}")
            return []

    def _rule_based_extraction(
        self,
        conversation_history: List[Dict[str, Any]],
    ) -> List[ExtractedMemory]:
        """
        ルールベースの重要情報抽出（LLMフォールバック）

        シンプルなパターンマッチで最低限の情報を抽出する。
        """
        extracted = []

        for msg in conversation_history:
            if msg.get("role") != "user":
                continue
            content = msg.get("content", "")

            # 「覚えて」パターン
            if "覚えて" in content or "記憶して" in content or "メモして" in content:
                extracted.append(ExtractedMemory(
                    category="fact",
                    content=content,
                    subject="ユーザー指示",
                    confidence=0.9,
                    metadata={"source": "explicit_request"},
                ))

            # 「好き」「嫌い」「好む」パターン
            for keyword in ("好き", "嫌い", "好む", "苦手", "得意"):
                if keyword in content:
                    extracted.append(ExtractedMemory(
                        category="preference",
                        content=content,
                        subject="ユーザー",
                        confidence=0.7,
                        metadata={"source": "keyword_match", "keyword": keyword},
                    ))
                    break

            # 「までに」「期限」パターン（コミットメント）
            for keyword in ("までに", "期限", "約束", "やります", "やる"):
                if keyword in content:
                    extracted.append(ExtractedMemory(
                        category="commitment",
                        content=content,
                        subject="ユーザー",
                        confidence=0.6,
                        metadata={"source": "keyword_match", "keyword": keyword},
                    ))
                    break

        return extracted

    async def _persist_item(
        self,
        item: ExtractedMemory,
        user_id: str,
        room_id: str,
    ) -> bool:
        """
        抽出された情報をカテゴリ別に永続化

        Codexレビュー対応:
        - PIIチェック: PII含有コンテンツは永続化しない
        - org_idスコープ: soulkun_knowledgeにもorg_idフィルタを適用
        - ロールバック: DB例外時に明示的にrollback
        """
        from sqlalchemy import text as sql_text

        # PIIチェック（Codexレビュー指摘#1）
        if contains_pii(item.content):
            logger.info(f"Skipping flush item with PII: category={item.category}")
            return False
        if contains_pii(item.subject):
            logger.info(f"Skipping flush item with PII in subject: category={item.category}")
            return False

        with self.pool.connect() as conn:
            try:
                if item.category == "preference":
                    # user_preferences テーブルに保存（org_idスコープ済み）
                    conn.execute(
                        sql_text("""
                            INSERT INTO user_preferences
                                (organization_id, user_id, preference_type, preference_key,
                                 preference_value, learned_from, confidence, classification)
                            SELECT
                                o.id, u.id, 'communication', :key, :value,
                                'auto_flush', :confidence, 'internal'
                            FROM organizations o
                            JOIN users u ON u.organization_id = o.id
                            WHERE o.slug = :org_id
                              AND u.chatwork_account_id = :user_id
                            ON CONFLICT (organization_id, user_id, preference_type, preference_key)
                            DO UPDATE SET
                                preference_value = EXCLUDED.preference_value,
                                confidence = GREATEST(user_preferences.confidence, EXCLUDED.confidence),
                                updated_at = CURRENT_TIMESTAMP
                        """),
                        {
                            "org_id": self.org_id,
                            "user_id": user_id,
                            "key": item.subject[:100],
                            "value": json.dumps(item.content, ensure_ascii=False),
                            "confidence": item.confidence,
                        },
                    )
                    conn.commit()

                elif item.category in ("fact", "decision", "commitment"):
                    # soulkun_knowledge テーブルに保存（Phase 4: org_idカラム対応）
                    conn.execute(
                        sql_text("""
                            INSERT INTO soulkun_knowledge
                                (organization_id, key, value, category, created_by)
                            SELECT
                                :org_id, :key, :value, :category, 'auto_flush'
                            WHERE EXISTS (
                                SELECT 1 FROM organizations WHERE slug = :org_id
                            )
                            ON CONFLICT (organization_id, category, key) DO UPDATE SET
                                value = EXCLUDED.value,
                                updated_at = CURRENT_TIMESTAMP
                        """),
                        {
                            "org_id": self.org_id,
                            "key": item.subject[:200],
                            "value": item.content,
                            "category": item.category,
                        },
                    )
                    conn.commit()

                else:
                    logger.warning(
                        "Unknown flush category: %s (skipping)", item.category
                    )
                    return False

                logger.debug(
                    f"Persisted flush item: category={item.category}, "
                    f"subject={item.subject}, confidence={item.confidence}"
                )
                return True

            except Exception as e:
                # Codexレビュー指摘#3: 明示的なロールバック
                try:
                    conn.rollback()
                except Exception:
                    pass
                raise
