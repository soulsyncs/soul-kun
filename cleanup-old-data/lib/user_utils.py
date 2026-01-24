"""
Soul-kun ユーザー関連ユーティリティ

★★★ v10.18.1: Phase 3.5対応 ★★★

このモジュールは以下を提供します:
- get_user_primary_department: ユーザーの主所属部署IDを取得

使用例（Flask/Cloud Functions）:
    from lib.user_utils import get_user_primary_department

    pool = get_pool()
    department_id = get_user_primary_department(pool, chatwork_account_id)

対応Phase:
- Phase 3.5: 組織階層連携（department_idによるタスクの部署紐付け）
- Phase 4: BPaaS（マルチテナント対応済み）
"""

import sqlalchemy
from typing import Optional, Union

__version__ = "1.0.0"  # v10.18.1: 初版


def get_user_primary_department(
    pool: sqlalchemy.engine.Engine,
    chatwork_account_id: Union[str, int]
) -> Optional[str]:
    """
    ChatWorkアカウントIDからユーザーの主所属部署IDを取得する

    ★★★ v10.18.1: 新規追加 ★★★

    Phase 3.5の組織階層連携で、タスクを担当者の部署に紐付けるために使用。
    user_departmentsテーブルからis_primary=TRUEかつended_at IS NULLの
    現在有効な主所属部署を取得する。

    Args:
        pool: SQLAlchemy Engine (接続プール)
        chatwork_account_id: ChatWorkアカウントID（文字列または数値）

    Returns:
        部署ID (UUID文字列) または None（見つからない場合）

    Example:
        >>> pool = get_pool()
        >>> dept_id = get_user_primary_department(pool, "12345678")
        >>> if dept_id:
        ...     print(f"部署ID: {dept_id}")

    Note:
        - 見つからない場合やエラー時はNoneを返す（例外をスローしない）
        - 複数の主所属がある場合は最初の1件を返す
    """
    try:
        with pool.connect() as conn:
            result = conn.execute(
                sqlalchemy.text("""
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
            if row and row[0]:
                return str(row[0])
            return None
    except Exception as e:
        print(f"⚠️ get_user_primary_department エラー: {e}")
        return None


# =====================================================
# エクスポート
# =====================================================
__all__ = [
    "get_user_primary_department",
]
