"""
Access Control Service

Phase 3.5: 6段階権限レベルに基づくアクセス制御

権限レベル（level）:
    1 = 業務委託（自部署のみ、制限あり）
    2 = 一般社員（自部署のみ）
    3 = リーダー/課長（自部署＋直下部署）
    4 = 幹部/部長（自部署＋配下全部署）
    5 = 管理部（全組織、最高機密除く）
    6 = 代表/CFO（全組織、全情報）
"""

from typing import List, Optional, Set
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class AccessControlService:
    """アクセス制御サービス"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def compute_accessible_departments(
        self,
        user_id: str,
        organization_id: str
    ) -> List[str]:
        """
        ユーザーがアクセス可能な部署IDのリストを返す

        Args:
            user_id: ユーザーID
            organization_id: 組織ID

        Returns:
            アクセス可能な部署IDのリスト
        """
        # ユーザーの権限レベルを取得
        role_level = await self.get_user_role_level(user_id)

        # 権限レベルに応じたアクセス範囲を計算
        if role_level >= 5:
            # Level 5-6: 全組織アクセス
            return await self.get_all_departments(organization_id)

        # ユーザーの所属部署を取得
        user_depts = await self.get_user_departments(user_id)

        if not user_depts:
            return []

        accessible_depts: Set[str] = set()

        for dept_id in user_depts:
            # 自部署は常にアクセス可能
            accessible_depts.add(dept_id)

            if role_level >= 4:
                # Level 4: 自部署＋配下全部署
                descendants = await self.get_all_descendants(dept_id, organization_id)
                accessible_depts.update(descendants)
            elif role_level >= 3:
                # Level 3: 自部署＋直下部署のみ
                direct_children = await self.get_direct_children(dept_id, organization_id)
                accessible_depts.update(direct_children)
            # Level 1-2: 自部署のみ（既に追加済み）

        return list(accessible_depts)

    async def get_user_role_level(self, user_id: str) -> int:
        """
        ユーザーの権限レベルを取得

        Args:
            user_id: ユーザーID

        Returns:
            権限レベル（1-6）、未設定の場合は2（一般社員）
        """
        query = text("""
            SELECT COALESCE(MAX(r.level), 2) as max_level
            FROM user_departments ud
            JOIN roles r ON ud.role_id = r.id
            WHERE ud.user_id = :user_id
              AND ud.ended_at IS NULL
        """)

        result = await self.db.execute(query, {"user_id": user_id})
        row = result.fetchone()

        if row and row[0]:
            return row[0]

        # user_departmentsにrole_idがない場合、usersからrole_idを確認
        # （将来の拡張用、現在はuser_departmentsを優先）
        return 2  # デフォルト: 一般社員

    async def get_user_departments(self, user_id: str) -> List[str]:
        """
        ユーザーの所属部署IDリストを取得

        Args:
            user_id: ユーザーID

        Returns:
            部署IDのリスト
        """
        query = text("""
            SELECT department_id
            FROM user_departments
            WHERE user_id = :user_id
              AND ended_at IS NULL
        """)

        result = await self.db.execute(query, {"user_id": user_id})
        return [row[0] for row in result.fetchall()]

    async def get_all_departments(self, organization_id: str) -> List[str]:
        """
        組織内の全部署IDを取得

        Args:
            organization_id: 組織ID

        Returns:
            部署IDのリスト
        """
        query = text("""
            SELECT id
            FROM departments
            WHERE organization_id = :organization_id
              AND is_active = TRUE
        """)

        result = await self.db.execute(query, {"organization_id": organization_id})
        return [row[0] for row in result.fetchall()]

    async def get_all_descendants(self, dept_id: str, organization_id: str) -> List[str]:
        """
        部署の全配下部署を取得（LTREEを使用）

        Args:
            dept_id: 部署ID
            organization_id: 組織ID（テナント分離用）

        Returns:
            配下部署IDのリスト（自部署は含まない）
        """
        # LTREE拡張を使った階層クエリ
        query = text("""
            WITH dept_path AS (
                SELECT path
                FROM departments
                WHERE id = :dept_id
                  AND organization_id = :organization_id
            )
            SELECT d.id
            FROM departments d, dept_path dp
            WHERE d.path <@ dp.path
              AND d.id != :dept_id
              AND d.organization_id = :organization_id
              AND d.is_active = TRUE
        """)

        result = await self.db.execute(query, {"dept_id": dept_id, "organization_id": organization_id})
        return [row[0] for row in result.fetchall()]

    async def get_direct_children(self, dept_id: str, organization_id: str) -> List[str]:
        """
        部署の直下の子部署のみを取得

        Args:
            dept_id: 部署ID
            organization_id: 組織ID（テナント分離用）

        Returns:
            直下の子部署IDのリスト
        """
        query = text("""
            SELECT id
            FROM departments
            WHERE parent_id = :dept_id
              AND organization_id = :organization_id
              AND is_active = TRUE
        """)

        result = await self.db.execute(query, {"dept_id": dept_id, "organization_id": organization_id})
        return [row[0] for row in result.fetchall()]

    async def can_access_department(
        self,
        user_id: str,
        department_id: str,
        organization_id: str
    ) -> bool:
        """
        ユーザーが特定の部署にアクセスできるかチェック

        Args:
            user_id: ユーザーID
            department_id: 部署ID
            organization_id: 組織ID

        Returns:
            アクセス可能な場合True
        """
        accessible = await self.compute_accessible_departments(user_id, organization_id)
        return department_id in accessible

    async def can_access_task(
        self,
        user_id: str,
        task_department_id: Optional[str],
        organization_id: str
    ) -> bool:
        """
        ユーザーが特定のタスクにアクセスできるかチェック

        Args:
            user_id: ユーザーID
            task_department_id: タスクの部署ID（NULLの場合あり）
            organization_id: 組織ID

        Returns:
            アクセス可能な場合True
        """
        # 部署未設定のタスクは全員アクセス可能（後方互換性）
        if task_department_id is None:
            return True

        return await self.can_access_department(user_id, task_department_id, organization_id)


# 同期版のヘルパー関数（Cloud Functions用）
def get_user_role_level_sync(conn, user_id: str) -> int:
    """
    ユーザーの権限レベルを取得（同期版）

    Args:
        conn: データベース接続
        user_id: ユーザーID

    Returns:
        権限レベル（1-6）、未設定の場合は2
    """
    result = conn.execute(
        text("""
            SELECT COALESCE(MAX(r.level), 2) as max_level
            FROM user_departments ud
            JOIN roles r ON ud.role_id = r.id
            WHERE ud.user_id = :user_id
              AND ud.ended_at IS NULL
        """),
        {"user_id": user_id}
    )
    row = result.fetchone()
    return row[0] if row and row[0] else 2


def compute_accessible_departments_sync(
    conn,
    user_id: str,
    organization_id: str
) -> List[str]:
    """
    ユーザーがアクセス可能な部署IDのリストを返す（同期版）

    Args:
        conn: データベース接続
        user_id: ユーザーID
        organization_id: 組織ID

    Returns:
        アクセス可能な部署IDのリスト
    """
    # ユーザーの権限レベルを取得
    role_level = get_user_role_level_sync(conn, user_id)

    # Level 5-6: 全組織アクセス
    if role_level >= 5:
        result = conn.execute(
            text("""
                SELECT id FROM departments
                WHERE organization_id = :org_id AND is_active = TRUE
            """),
            {"org_id": organization_id}
        )
        return [row[0] for row in result.fetchall()]

    # ユーザーの所属部署を取得
    result = conn.execute(
        text("""
            SELECT department_id FROM user_departments
            WHERE user_id = :user_id AND ended_at IS NULL
        """),
        {"user_id": user_id}
    )
    user_depts = [row[0] for row in result.fetchall()]

    if not user_depts:
        return []

    accessible_depts: Set[str] = set()

    for dept_id in user_depts:
        accessible_depts.add(dept_id)

        if role_level >= 4:
            # 配下全部署（organization_idでフィルタ）
            result = conn.execute(
                text("""
                    WITH dept_path AS (
                        SELECT path FROM departments
                        WHERE id = :dept_id AND organization_id = :org_id
                    )
                    SELECT d.id FROM departments d, dept_path dp
                    WHERE d.path <@ dp.path
                      AND d.id != :dept_id
                      AND d.organization_id = :org_id
                      AND d.is_active = TRUE
                """),
                {"dept_id": dept_id, "org_id": organization_id}
            )
            accessible_depts.update([row[0] for row in result.fetchall()])
        elif role_level >= 3:
            # 直下部署のみ（organization_idでフィルタ）
            result = conn.execute(
                text("""
                    SELECT id FROM departments
                    WHERE parent_id = :dept_id
                      AND organization_id = :org_id
                      AND is_active = TRUE
                """),
                {"dept_id": dept_id, "org_id": organization_id}
            )
            accessible_depts.update([row[0] for row in result.fetchall()])

    return list(accessible_depts)
