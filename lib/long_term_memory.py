"""
ユーザー長期記憶（プロフィール）管理

人生軸・価値観・長期WHYなど、目標設定とは別の
ユーザーの根本的な信念や価値観を保存・取得する。

v10.40.9: メモリ分離・アクセス制御
- MemoryScope追加（PRIVATE/ORG_SHARED）
- requester_user_idによるアクセス制御

Author: Claude Code
Created: 2026-01-28
Version: 1.1.0
"""

import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from sqlalchemy import text

logger = logging.getLogger(__name__)


# =====================================================
# 定数
# =====================================================

# 長期記憶タイプ
class MemoryType:
    LIFE_WHY = "life_why"          # 人生のWHY・存在意義
    VALUES = "values"              # 価値観・判断基準
    IDENTITY = "identity"          # アイデンティティ・自己認識
    PRINCIPLES = "principles"      # 行動原則・信条
    LONG_TERM_GOAL = "long_term_goal"  # 長期目標（5年以上）


# v10.40.9: メモリスコープ
class MemoryScope:
    PRIVATE = "PRIVATE"          # 本人のみアクセス可能（デフォルト）
    ORG_SHARED = "ORG_SHARED"    # 組織内で共有可能


# 長期記憶を示すパターン
LONG_TERM_MEMORY_PATTERNS = [
    # 人生の軸・WHY
    r"人生の(軸|why|ワイ)",
    r"生き方としての",
    r"存在意義",
    r"生きる(目的|理由|意味)",
    r"俺の軸",
    r"私の軸",
    r"自分の軸",

    # 価値観・判断基準
    r"判断基準",
    r"価値観",
    r"大切にして(いる|いきたい)",
    r"信条",
    r"信念",
    r"ポリシー",

    # 覚えておいてほしい表現
    r"(軸|基準)として覚えて",
    r"目標じゃなくて",
    r"これは目標(では|じゃ)ない",
    r"今後の(判断|行動)の(基準|軸)",
    r"常に(意識|念頭)",
    r"ずっと(覚えて|忘れないで)",
]

# 長期記憶保存成功メッセージ
SUCCESS_MESSAGE = """🐺✨ {user_name}さんの人生の軸として覚えたウル！

━━━━━━━━━━━━━━━━━━
🔥 【{user_name}さんの{memory_type_label}】
{content}
━━━━━━━━━━━━━━━━━━

今後の目標設定や行動提案は、この価値観に沿ってサポートするウル🐺
いつでも「軸を確認して」と言ってくれたら見せるウル！"""

# メモリタイプの日本語ラベル
MEMORY_TYPE_LABELS = {
    MemoryType.LIFE_WHY: "人生の軸",
    MemoryType.VALUES: "価値観",
    MemoryType.IDENTITY: "アイデンティティ",
    MemoryType.PRINCIPLES: "行動原則",
    MemoryType.LONG_TERM_GOAL: "長期ビジョン",
}


# =====================================================
# 判定関数
# =====================================================

def is_long_term_memory_request(message: str) -> bool:
    """
    メッセージが長期記憶保存リクエストかどうかを判定

    Args:
        message: ユーザーメッセージ

    Returns:
        True: 長期記憶保存リクエスト
        False: 通常のメッセージ
    """
    message_lower = message.lower()

    for pattern in LONG_TERM_MEMORY_PATTERNS:
        if re.search(pattern, message_lower):
            return True

    return False


def detect_memory_type(message: str) -> str:
    """
    メッセージから記憶タイプを推定

    Args:
        message: ユーザーメッセージ

    Returns:
        記憶タイプ（デフォルト: life_why）
    """
    message_lower = message.lower()

    # 価値観・判断基準
    if any(kw in message_lower for kw in ["判断基準", "価値観", "大切にして"]):
        return MemoryType.VALUES

    # アイデンティティ
    if any(kw in message_lower for kw in ["自分とは", "アイデンティティ", "私は何者"]):
        return MemoryType.IDENTITY

    # 行動原則
    if any(kw in message_lower for kw in ["信条", "ポリシー", "行動原則"]):
        return MemoryType.PRINCIPLES

    # 長期ビジョン
    if any(kw in message_lower for kw in ["長期目標", "10年後", "将来"]):
        return MemoryType.LONG_TERM_GOAL

    # デフォルト: 人生のWHY
    return MemoryType.LIFE_WHY


def extract_memory_content(message: str) -> str:
    """
    メッセージから記憶内容を抽出

    「〜として覚えて」などの指示部分を除去し、
    本質的な内容だけを抽出する。

    Args:
        message: ユーザーメッセージ

    Returns:
        抽出された記憶内容
    """
    content = message

    # 指示部分を除去するパターン
    remove_patterns = [
        r"(これは)?目標(では|じゃ)なくて",
        r"人生の軸として",
        r"軸として覚えて",
        r"覚えておいて",
        r"忘れないで",
        r"(俺|私|自分)の軸(は|として)?",
    ]

    for pattern in remove_patterns:
        content = re.sub(pattern, "", content)

    # 前後の空白・改行を整理
    content = content.strip()

    # 空になった場合は元のメッセージを返す
    if not content:
        content = message

    return content


# =====================================================
# 保存・取得クラス
# =====================================================

class LongTermMemoryManager:
    """
    ユーザー長期記憶の保存・取得を管理

    目標設定フローとは独立して、ユーザーの
    人生軸・価値観・長期WHYを保存する。
    """

    def __init__(self, pool, org_id: str, user_id, user_name: str = ""):
        # user_id: int or str (DBはintegerだが文字列でも動作)
        """
        初期化

        Args:
            pool: DB接続プール
            org_id: 組織ID
            user_id: ユーザーID（users.id）
            user_name: ユーザー名（表示用）
        """
        self.pool = pool
        self.org_id = org_id
        self.user_id = user_id
        self.user_name = user_name or "あなた"

    def save(
        self,
        content: str,
        memory_type: str = MemoryType.LIFE_WHY,
        scope: str = MemoryScope.PRIVATE,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        長期記憶を保存

        v10.40.9: scopeパラメータ追加

        Args:
            content: 記憶内容
            memory_type: 記憶タイプ
            scope: アクセススコープ（PRIVATE/ORG_SHARED）
            metadata: 追加メタデータ

        Returns:
            保存結果 {"success": bool, "message": str, "memory_id": str}
        """
        try:
            memory_id = str(uuid4())
            metadata = metadata or {}

            # 保存日時を追加
            metadata["saved_at"] = datetime.utcnow().isoformat()

            with self.pool.connect() as conn:
                conn.execute(
                    text("""
                        INSERT INTO user_long_term_memory (
                            id, organization_id, user_id,
                            memory_type, content, scope, metadata
                        ) VALUES (
                            :id, :org_id, :user_id,
                            :memory_type, :content, :scope, CAST(:metadata AS jsonb)
                        )
                    """),
                    {
                        "id": memory_id,
                        "org_id": self.org_id,
                        "user_id": self.user_id,
                        "memory_type": memory_type,
                        "content": content,
                        "scope": scope,
                        "metadata": json.dumps(metadata),
                    }
                )
                conn.commit()

            logger.info(f"✅ 長期記憶保存成功: {memory_id} ({memory_type}, scope={scope})")

            # 成功メッセージを生成
            type_label = MEMORY_TYPE_LABELS.get(memory_type, "人生の軸")
            response_message = SUCCESS_MESSAGE.format(
                user_name=self.user_name,
                memory_type_label=type_label,
                content=content
            )

            return {
                "success": True,
                "message": response_message,
                "memory_id": memory_id,
                "memory_type": memory_type,
                "scope": scope,
            }

        except Exception as e:
            logger.error(f"❌ 長期記憶保存失敗: {e}")
            return {
                "success": False,
                "message": f"長期記憶の保存中にエラーが発生しました: {str(e)}",
                "error": str(e),
            }

    def get_all(self, memory_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        ユーザーの長期記憶を取得（本人のみ、アクセス制御なし）

        注意: このメソッドはself.user_idの記憶のみを取得する。
              他ユーザーの記憶にアクセスする場合はget_all_for_requester()を使用。

        Args:
            memory_type: 絞り込む記憶タイプ（省略時は全て）

        Returns:
            記憶リスト
        """
        try:
            with self.pool.connect() as conn:
                if memory_type:
                    result = conn.execute(
                        text("""
                            SELECT id, memory_type, content, metadata, created_at, updated_at, scope
                            FROM user_long_term_memory
                            WHERE organization_id = :org_id
                              AND user_id = :user_id
                              AND memory_type = :memory_type
                            ORDER BY created_at DESC
                        """),
                        {
                            "org_id": self.org_id,
                            "user_id": self.user_id,
                            "memory_type": memory_type,
                        }
                    ).fetchall()
                else:
                    result = conn.execute(
                        text("""
                            SELECT id, memory_type, content, metadata, created_at, updated_at, scope
                            FROM user_long_term_memory
                            WHERE organization_id = :org_id
                              AND user_id = :user_id
                            ORDER BY created_at DESC
                        """),
                        {
                            "org_id": self.org_id,
                            "user_id": self.user_id,
                        }
                    ).fetchall()

                memories = []
                for row in result:
                    memories.append({
                        "id": str(row[0]),
                        "memory_type": row[1],
                        "content": row[2],
                        "metadata": row[3] or {},
                        "created_at": row[4].isoformat() if row[4] else None,
                        "updated_at": row[5].isoformat() if row[5] else None,
                        "scope": row[6] if len(row) > 6 else MemoryScope.PRIVATE,
                    })

                return memories

        except Exception as e:
            logger.error(f"❌ 長期記憶取得失敗: {e}")
            return []

    def get_all_for_requester(
        self,
        requester_user_id: int,
        memory_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        v10.40.9: アクセス制御付きで長期記憶を取得

        セキュリティルール:
        - requester_user_id == self.user_id: 全ての記憶を取得可能
        - requester_user_id != self.user_id: ORG_SHARED のみ取得可能
        - PRIVATEスコープの記憶は本人以外には絶対に返さない

        Args:
            requester_user_id: リクエストしているユーザーのID
            memory_type: 絞り込む記憶タイプ（省略時は全て）

        Returns:
            アクセス可能な記憶リスト
        """
        try:
            is_owner = (requester_user_id == self.user_id)

            with self.pool.connect() as conn:
                if is_owner:
                    # 本人なら全ての記憶を取得
                    if memory_type:
                        result = conn.execute(
                            text("""
                                SELECT id, memory_type, content, metadata, created_at, updated_at, scope
                                FROM user_long_term_memory
                                WHERE organization_id = :org_id
                                  AND user_id = :user_id
                                  AND memory_type = :memory_type
                                ORDER BY created_at DESC
                            """),
                            {
                                "org_id": self.org_id,
                                "user_id": self.user_id,
                                "memory_type": memory_type,
                            }
                        ).fetchall()
                    else:
                        result = conn.execute(
                            text("""
                                SELECT id, memory_type, content, metadata, created_at, updated_at, scope
                                FROM user_long_term_memory
                                WHERE organization_id = :org_id
                                  AND user_id = :user_id
                                ORDER BY created_at DESC
                            """),
                            {
                                "org_id": self.org_id,
                                "user_id": self.user_id,
                            }
                        ).fetchall()
                else:
                    # 他ユーザーからのリクエストはORG_SHAREDのみ
                    logger.warning(
                        f"Non-owner access attempt: requester={requester_user_id}, owner={self.user_id}"
                    )
                    if memory_type:
                        result = conn.execute(
                            text("""
                                SELECT id, memory_type, content, metadata, created_at, updated_at, scope
                                FROM user_long_term_memory
                                WHERE organization_id = :org_id
                                  AND user_id = :user_id
                                  AND memory_type = :memory_type
                                  AND scope = 'ORG_SHARED'
                                ORDER BY created_at DESC
                            """),
                            {
                                "org_id": self.org_id,
                                "user_id": self.user_id,
                                "memory_type": memory_type,
                            }
                        ).fetchall()
                    else:
                        result = conn.execute(
                            text("""
                                SELECT id, memory_type, content, metadata, created_at, updated_at, scope
                                FROM user_long_term_memory
                                WHERE organization_id = :org_id
                                  AND user_id = :user_id
                                  AND scope = 'ORG_SHARED'
                                ORDER BY created_at DESC
                            """),
                            {
                                "org_id": self.org_id,
                                "user_id": self.user_id,
                            }
                        ).fetchall()

                memories = []
                for row in result:
                    memories.append({
                        "id": str(row[0]),
                        "memory_type": row[1],
                        "content": row[2],
                        "metadata": row[3] or {},
                        "created_at": row[4].isoformat() if row[4] else None,
                        "updated_at": row[5].isoformat() if row[5] else None,
                        "scope": row[6] if len(row) > 6 else MemoryScope.PRIVATE,
                    })

                return memories

        except Exception as e:
            logger.error(f"❌ 長期記憶取得失敗（アクセス制御）: {e}")
            return []

    def get_life_why(self) -> Optional[str]:
        """
        ユーザーの人生のWHYを取得

        Returns:
            人生のWHY（なければNone）
        """
        memories = self.get_all(memory_type=MemoryType.LIFE_WHY)
        if memories:
            return memories[0]["content"]
        return None

    def format_for_display(self, show_scope: bool = False) -> str:
        """
        全長期記憶を表示用にフォーマット

        v10.40.9: show_scopeオプション追加

        Args:
            show_scope: スコープを表示するか

        Returns:
            表示用テキスト
        """
        memories = self.get_all()
        if not memories:
            return f"{self.user_name}さんの長期記憶はまだ登録されていないウル"

        lines = [f"🐺 {self.user_name}さんの長期記憶ウル！", ""]

        for memory in memories:
            type_label = MEMORY_TYPE_LABELS.get(memory["memory_type"], "記憶")
            scope = memory.get("scope", MemoryScope.PRIVATE)
            scope_indicator = "" if scope == MemoryScope.PRIVATE else " [共有]"

            if show_scope:
                lines.append(f"【{type_label}】{scope_indicator}")
            else:
                lines.append(f"【{type_label}】")
            lines.append(memory["content"])
            lines.append("")

        return "\n".join(lines)


# =====================================================
# 便利関数
# =====================================================

def save_long_term_memory(
    pool,
    org_id: str,
    user_id,  # int or str
    user_name: str,
    message: str,
    scope: str = MemoryScope.PRIVATE
) -> Dict[str, Any]:
    """
    メッセージから長期記憶を保存するヘルパー関数

    v10.40.9: scopeパラメータ追加

    Args:
        pool: DB接続プール
        org_id: 組織ID (UUID string)
        user_id: ユーザーID (integer, users.user_id)
        user_name: ユーザー名
        message: ユーザーメッセージ
        scope: アクセススコープ（デフォルト: PRIVATE）

    Returns:
        保存結果
    """
    # 記憶タイプを検出
    memory_type = detect_memory_type(message)

    # 内容を抽出
    content = extract_memory_content(message)

    # 保存
    manager = LongTermMemoryManager(pool, org_id, user_id, user_name)
    return manager.save(content, memory_type, scope=scope)


def get_user_life_why(pool, org_id: str, user_id: str) -> Optional[str]:
    """
    ユーザーの人生のWHYを取得するヘルパー関数

    Args:
        pool: DB接続プール
        org_id: 組織ID
        user_id: ユーザーID

    Returns:
        人生のWHY（なければNone）
    """
    manager = LongTermMemoryManager(pool, org_id, user_id)
    return manager.get_life_why()
