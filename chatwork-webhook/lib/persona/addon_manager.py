"""
v10.43.0: Persona Add-on Manager
ユーザー/部署/ロール向けの追加指針をDBから取得

v10.48.1: SQLAlchemy 2.0互換性修正 - text()ラッパー追加
"""
from typing import Optional
import logging
from sqlalchemy import text


class TargetType:
    """Add-on対象種別"""
    USER = "user"
    DEPARTMENT = "department"  # 将来拡張
    ROLE = "role"              # 将来拡張


# カズ向けAdd-on v1（初期データ投入用）
KAZU_ADDON_V1 = """1. 5軸チェック：自由か？再現性あるか？事実ベースか？未来に繋がるか？覚悟はあるか？
2. 恐れが意思決定を歪めていないか観測。「それ、怖いからやめたい？やりたくないからやめたい？」
3. 可能性を広げる言語化を優先。「できない理由」より「どうすればできるか」を問う。
4. ワクワクしているか確認。義務感だけの目標は再設計を促す。"""


def get_user_addon(pool, org_id: str, user_id: str) -> Optional[str]:
    """
    ユーザー向けAdd-onをDBから取得

    Args:
        pool: DB接続プール
        org_id: 組織ID
        user_id: ユーザーID（ChatWork account_id）

    Returns:
        Add-on文字列。なければNone
    """
    if not pool or not org_id or not user_id:
        return None

    try:
        with pool.begin() as conn:
            result = conn.execute(
                text("""
                SELECT content
                FROM persona_addons
                WHERE organization_id = CAST(:org_id AS uuid)
                  AND target_type = :target_type
                  AND target_id = :target_id
                  AND is_active = true
                ORDER BY version DESC
                LIMIT 1
                """),
                {
                    "org_id": org_id,
                    "target_type": TargetType.USER,
                    "target_id": str(user_id),
                }
            )
            row = result.fetchone()
            if row:
                return row[0]
    except Exception as e:
        logging.warning(f"Addon fetch failed (continuing without): {e}")

    return None


def create_addon(
    pool,
    org_id: str,
    target_type: str,
    target_id: str,
    content: str,
    version: int = 1,
    created_by: Optional[str] = None,
) -> Optional[str]:
    """
    Add-onを作成

    Returns:
        作成されたAdd-onのID。失敗時はNone
    """
    if not pool:
        return None

    try:
        with pool.begin() as conn:
            result = conn.execute(
                text("""
                INSERT INTO persona_addons
                    (organization_id, target_type, target_id, content, version, is_active, created_by)
                VALUES
                    (CAST(:org_id AS uuid), :target_type, :target_id, :content, :version, true, :created_by)
                RETURNING id
                """),
                {
                    "org_id": org_id,
                    "target_type": target_type,
                    "target_id": target_id,
                    "content": content,
                    "version": version,
                    "created_by": created_by,
                }
            )
            row = result.fetchone()
            if row:
                return str(row[0])
    except Exception as e:
        logging.error(f"Addon creation failed: {e}")

    return None


__all__ = ["get_user_addon", "create_addon", "TargetType", "KAZU_ADDON_V1"]
