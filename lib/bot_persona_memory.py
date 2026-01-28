"""
ボットペルソナ記憶管理

ソウルくんのキャラ設定・好み・性格などを管理。
全ユーザー共通で参照される設定（例：好物=10円パン、モチーフ動物=狼）

Author: Claude Code
Created: 2026-01-28
Version: 1.0.0
"""

import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from sqlalchemy import text

logger = logging.getLogger(__name__)


# =====================================================
# 定数
# =====================================================

# ボットペルソナのカテゴリ
class PersonaCategory:
    CHARACTER = "character"      # キャラ設定（名前、モチーフなど）
    PERSONALITY = "personality"  # 性格（明るい、元気など）
    PREFERENCE = "preference"    # 好み（好物、趣味など）


# ボットペルソナを示すキーワードパターン
BOT_PERSONA_PATTERNS = [
    # ソウルくん自身への設定
    r"(ソウルくん|そうるくん|soul.?kun)の",
    r"(君|きみ|お前|おまえ)の(好物|好み|性格|名前|口調)",
    r"(好物|好み|性格|名前|口調)は",  # 主語がない場合もボット設定と推定

    # キャラ設定キーワード
    r"キャラ(設定|クター)",
    r"モチーフ(動物)?",
    r"語尾(は|を)",
    r"口調(は|を)",
]

# ボット設定のキーワードリスト
BOT_SETTING_KEYWORDS = [
    "好物", "好み", "モチーフ", "口調", "語尾", "性格", "キャラ",
    "名前", "呼び方", "一人称", "趣味", "特技", "苦手",
]

# カテゴリの日本語ラベル
PERSONA_CATEGORY_LABELS = {
    PersonaCategory.CHARACTER: "キャラ設定",
    PersonaCategory.PERSONALITY: "性格",
    PersonaCategory.PREFERENCE: "好み・趣味",
}


# =====================================================
# 判定関数
# =====================================================

def is_bot_persona_setting(message: str) -> bool:
    """
    メッセージがボットペルソナ設定かどうかを判定

    Args:
        message: ユーザーメッセージ

    Returns:
        True: ボットペルソナ設定
        False: それ以外
    """
    message_lower = message.lower()

    # 「ソウルくんの〜」は明示的にボット設定
    if re.search(r"(ソウルくん|そうるくん|soul.?kun)の", message_lower, re.IGNORECASE):
        return True

    # 「〜さんの好物」「〜様の趣味」は人物情報なので除外（ソウルくん以外の人名）
    # 注意: ソウルくんは上で処理済みなので、ここに来るのはソウルくん以外
    if re.search(r"[ぁ-んァ-ン一-龥](さん|様|くん|君)の(好物|好み|性格|名前|趣味|特技)", message_lower):
        return False

    # パターンマッチ
    for pattern in BOT_PERSONA_PATTERNS:
        if re.search(pattern, message_lower, re.IGNORECASE):
            return True

    # キーワードマッチ（「〜は〜」形式）
    for keyword in BOT_SETTING_KEYWORDS:
        if keyword in message_lower:
            # 「好物は〜」形式はボット設定（主語がない=ソウルくんの設定と推定）
            if re.search(r"^" + keyword + r"(は|を|が)", message_lower):
                return True
            # 文頭でなくても、直前に人名がなければボット設定
            if re.search(keyword + r"(は|を|が)", message_lower):
                # 人名が直前にあるかチェック（ソウルくん以外）
                if not re.search(r"[ぁ-んァ-ン一-龥](さん|様|くん|君)の" + keyword, message_lower):
                    return True

    return False


def detect_persona_category(message: str) -> str:
    """
    メッセージからペルソナカテゴリを推定

    Args:
        message: ユーザーメッセージ

    Returns:
        カテゴリ（デフォルト: character）
    """
    message_lower = message.lower()

    # 性格
    if any(kw in message_lower for kw in ["性格", "明るい", "元気", "真面目"]):
        return PersonaCategory.PERSONALITY

    # 好み
    if any(kw in message_lower for kw in ["好物", "好み", "趣味", "好き"]):
        return PersonaCategory.PREFERENCE

    # デフォルト: キャラ設定
    return PersonaCategory.CHARACTER


def extract_persona_key_value(message: str) -> Dict[str, str]:
    """
    メッセージからキーと値を抽出

    例：「好物は10円パン」→ {"key": "好物", "value": "10円パン"}
    例：「ソウルくんの口調はウル」→ {"key": "口調", "value": "ウル"}
    例：「口調はウル」→ {"key": "口調", "value": "ウル"}

    Args:
        message: ユーザーメッセージ

    Returns:
        {"key": str, "value": str}
    """
    result = {"key": "", "value": ""}

    # 「〜は〜」形式を検出（末尾の「だよ」「です」などを考慮）
    match = re.search(
        r"(好物|好み|性格|名前|口調|語尾|モチーフ|キャラ|一人称|趣味|特技|苦手)(は|を|が)(.+?)(?:だよ|です|だウル)?$",
        message
    )
    if match:
        result["key"] = match.group(1)
        result["value"] = match.group(3).strip()
        # 末尾の「だよ」「です」などをさらに除去（念のため）
        result["value"] = re.sub(r"(だよ|です|だウル)$", "", result["value"]).strip()
        return result

    # 「ソウルくんの〜は〜」形式
    match = re.search(
        r"(ソウルくん|そうるくん|soul.?kun)の(.+?)(は|を|が)(.+?)(?:だよ|です|だウル)?$",
        message,
        re.IGNORECASE
    )
    if match:
        result["key"] = match.group(2).strip()
        result["value"] = match.group(4).strip()
        result["value"] = re.sub(r"(だよ|です|だウル)$", "", result["value"]).strip()
        return result

    return result


# =====================================================
# 保存・取得クラス
# =====================================================

class BotPersonaMemoryManager:
    """
    ボットペルソナ記憶の保存・取得を管理

    組織ごとにボット設定を持つ（将来的にマルチテナント対応）
    """

    def __init__(self, pool, org_id: str):
        """
        初期化

        Args:
            pool: DB接続プール
            org_id: 組織ID
        """
        self.pool = pool
        self.org_id = org_id

    def save(
        self,
        key: str,
        value: str,
        category: str = PersonaCategory.CHARACTER,
        created_by_account_id: str = None,
        created_by_name: str = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        ボットペルソナ設定を保存（UPSERT）

        Args:
            key: 設定キー（例：好物）
            value: 設定値（例：10円パン）
            category: カテゴリ
            created_by_account_id: 作成者アカウントID
            created_by_name: 作成者名
            metadata: 追加メタデータ

        Returns:
            保存結果
        """
        try:
            metadata = metadata or {}
            metadata["saved_at"] = datetime.utcnow().isoformat()

            with self.pool.connect() as conn:
                conn.execute(
                    text("""
                        INSERT INTO bot_persona_memory (
                            organization_id, key, value, category,
                            created_by_account_id, created_by_name, metadata
                        ) VALUES (
                            :org_id, :key, :value, :category,
                            :created_by_account_id, :created_by_name, CAST(:metadata AS jsonb)
                        )
                        ON CONFLICT (organization_id, key)
                        DO UPDATE SET
                            value = :value,
                            category = :category,
                            metadata = bot_persona_memory.metadata || CAST(:metadata AS jsonb),
                            updated_at = CURRENT_TIMESTAMP
                    """),
                    {
                        "org_id": self.org_id,
                        "key": key,
                        "value": value,
                        "category": category,
                        "created_by_account_id": created_by_account_id,
                        "created_by_name": created_by_name,
                        "metadata": json.dumps(metadata),
                    }
                )
                conn.commit()

            logger.info(f"Bot persona saved: {key} = {value}")

            category_label = PERSONA_CATEGORY_LABELS.get(category, "設定")
            return {
                "success": True,
                "message": f"覚えたウル！\n\n【{category_label}】\n・{key}: {value}",
                "key": key,
                "value": value,
            }

        except Exception as e:
            logger.error(f"Bot persona save error: {e}")
            return {
                "success": False,
                "message": f"設定の保存中にエラーが発生したウル: {str(e)}",
                "error": str(e),
            }

    def get(self, key: str) -> Optional[str]:
        """
        特定のキーの値を取得

        Args:
            key: 設定キー

        Returns:
            値（なければNone）
        """
        try:
            with self.pool.connect() as conn:
                result = conn.execute(
                    text("""
                        SELECT value FROM bot_persona_memory
                        WHERE organization_id = :org_id AND key = :key
                    """),
                    {"org_id": self.org_id, "key": key}
                ).fetchone()

                if result:
                    return result[0]
                return None

        except Exception as e:
            logger.error(f"Bot persona get error: {e}")
            return None

    def get_all(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        全設定を取得

        Args:
            category: 絞り込むカテゴリ（省略時は全て）

        Returns:
            設定リスト
        """
        try:
            with self.pool.connect() as conn:
                if category:
                    result = conn.execute(
                        text("""
                            SELECT key, value, category, created_at
                            FROM bot_persona_memory
                            WHERE organization_id = :org_id AND category = :category
                            ORDER BY key
                        """),
                        {"org_id": self.org_id, "category": category}
                    ).fetchall()
                else:
                    result = conn.execute(
                        text("""
                            SELECT key, value, category, created_at
                            FROM bot_persona_memory
                            WHERE organization_id = :org_id
                            ORDER BY category, key
                        """),
                        {"org_id": self.org_id}
                    ).fetchall()

                return [
                    {
                        "key": row[0],
                        "value": row[1],
                        "category": row[2],
                        "created_at": row[3].isoformat() if row[3] else None,
                    }
                    for row in result
                ]

        except Exception as e:
            logger.error(f"Bot persona get_all error: {e}")
            return []

    def delete(self, key: str) -> bool:
        """
        設定を削除

        Args:
            key: 設定キー

        Returns:
            成功時True
        """
        try:
            with self.pool.connect() as conn:
                conn.execute(
                    text("""
                        DELETE FROM bot_persona_memory
                        WHERE organization_id = :org_id AND key = :key
                    """),
                    {"org_id": self.org_id, "key": key}
                )
                conn.commit()
            logger.info(f"Bot persona deleted: {key}")
            return True

        except Exception as e:
            logger.error(f"Bot persona delete error: {e}")
            return False

    def format_for_display(self) -> str:
        """
        全設定を表示用にフォーマット

        Returns:
            表示用テキスト
        """
        settings = self.get_all()
        if not settings:
            return "ソウルくんの設定はまだないウル"

        lines = []

        # カテゴリごとにグループ化
        by_category = {}
        for s in settings:
            cat = s["category"]
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(f"・{s['key']}: {s['value']}")

        for cat, items in by_category.items():
            cat_label = PERSONA_CATEGORY_LABELS.get(cat, cat)
            lines.append(f"\n【{cat_label}】")
            lines.extend(items)

        return "\n".join(lines)


# =====================================================
# 便利関数
# =====================================================

def save_bot_persona(
    pool,
    org_id: str,
    message: str,
    account_id: str = None,
    sender_name: str = None
) -> Dict[str, Any]:
    """
    メッセージからボットペルソナ設定を保存

    Args:
        pool: DB接続プール
        org_id: 組織ID
        message: ユーザーメッセージ
        account_id: 作成者アカウントID
        sender_name: 作成者名

    Returns:
        保存結果
    """
    # キーと値を抽出
    kv = extract_persona_key_value(message)
    if not kv["key"] or not kv["value"]:
        return {
            "success": False,
            "message": "設定内容を理解できなかったウル...「好物は〇〇」のように教えてほしいウル！",
        }

    # カテゴリを推定
    category = detect_persona_category(message)

    # 保存
    manager = BotPersonaMemoryManager(pool, org_id)
    return manager.save(
        key=kv["key"],
        value=kv["value"],
        category=category,
        created_by_account_id=account_id,
        created_by_name=sender_name
    )


def get_bot_persona(pool, org_id: str, key: str) -> Optional[str]:
    """
    ボットペルソナ設定を取得

    Args:
        pool: DB接続プール
        org_id: 組織ID
        key: 設定キー

    Returns:
        値（なければNone）
    """
    manager = BotPersonaMemoryManager(pool, org_id)
    return manager.get(key)
