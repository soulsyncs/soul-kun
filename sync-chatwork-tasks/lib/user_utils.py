"""
ユーザー関連ユーティリティ

Phase 3.5対応: ユーザーの部署情報取得など

使用例:
    from lib.user_utils import get_user_primary_department

    department_id = get_user_primary_department(pool, chatwork_account_id)
"""

from typing import Optional, Any
from sqlalchemy import text


def get_user_primary_department(
    pool: Any,
    chatwork_account_id: int,
) -> Optional[str]:
    """
    担当者のメイン部署IDを取得（Phase 3.5対応）

    user_departmentsテーブルからis_primary=TRUEかつended_at=NULLの
    部署を取得する。

    Args:
        pool: SQLAlchemy Engine (get_db_pool()の戻り値)
        chatwork_account_id: Chatwork アカウントID

    Returns:
        部署ID（UUID文字列）。見つからない場合はNone。

    使用例:
        from lib import get_db_pool
        from lib.user_utils import get_user_primary_department

        pool = get_db_pool()
        department_id = get_user_primary_department(pool, 12345678)

        # タスク保存時に使用
        INSERT INTO chatwork_tasks (..., department_id)
        VALUES (..., :department_id)

    設計書参照:
        - docs/03_database_design.md: user_departmentsテーブル
        - Phase 3.5: 組織階層連携
    """
    try:
        with pool.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT ud.department_id
                    FROM user_departments ud
                    JOIN users u ON ud.user_id = u.id
                    WHERE u.chatwork_account_id = :chatwork_account_id
                      AND ud.is_primary = TRUE
                      AND ud.ended_at IS NULL
                    LIMIT 1
                """),
                {"chatwork_account_id": str(chatwork_account_id)}
            )
            row = result.fetchone()
            return str(row[0]) if row else None
    except Exception as e:
        print(f"[get_user_primary_department] 部署取得エラー: {e}")
        return None


def get_user_by_chatwork_id(
    pool: Any,
    chatwork_account_id: int,
) -> Optional[dict]:
    """
    Chatwork IDからユーザー情報を取得

    Args:
        pool: SQLAlchemy Engine
        chatwork_account_id: Chatwork アカウントID

    Returns:
        ユーザー情報の辞書。見つからない場合はNone。
        {
            "id": UUID,
            "chatwork_account_id": str,
            "name": str,
            "email": str,
            "organization_id": UUID,
        }
    """
    try:
        with pool.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT id, chatwork_account_id, name, email, organization_id
                    FROM users
                    WHERE chatwork_account_id = :chatwork_account_id
                    LIMIT 1
                """),
                {"chatwork_account_id": str(chatwork_account_id)}
            )
            row = result.fetchone()
            if row:
                return {
                    "id": str(row[0]),
                    "chatwork_account_id": str(row[1]),
                    "name": row[2],
                    "email": row[3],
                    "organization_id": str(row[4]) if row[4] else None,
                }
            return None
    except Exception as e:
        print(f"[get_user_by_chatwork_id] ユーザー取得エラー: {e}")
        return None
