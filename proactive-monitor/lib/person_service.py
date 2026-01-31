"""
人物情報サービス

main.pyから分割された人物情報関連の関数を提供する。
人物の作成、検索、属性管理、組織図クエリを含む。

分割元: chatwork-webhook/main.py
分割日: 2026-01-29
バージョン: v10.48.0
"""

import re
import sqlalchemy
from typing import Optional, List, Dict, Any, Callable, Tuple


class PersonService:
    """
    人物情報を管理するサービスクラス

    依存注入パターンで get_pool を受け取り、DBアクセスを行う。
    """

    def __init__(self, get_pool: Callable):
        """
        Args:
            get_pool: DB接続プールを取得する関数
        """
        self.get_pool = get_pool

    def get_or_create_person(self, name: str) -> int:
        """人物を取得、なければ作成してIDを返す"""
        pool = self.get_pool()
        with pool.begin() as conn:
            result = conn.execute(
                sqlalchemy.text("SELECT id FROM persons WHERE name = :name"),
                {"name": name}
            ).fetchone()
            if result:
                return result[0]
            result = conn.execute(
                sqlalchemy.text("INSERT INTO persons (name) VALUES (:name) RETURNING id"),
                {"name": name}
            )
            return result.fetchone()[0]

    def save_person_attribute(
        self,
        person_name: str,
        attribute_type: str,
        attribute_value: str,
        source: str = "conversation"
    ) -> bool:
        """人物の属性を保存"""
        person_id = self.get_or_create_person(person_name)
        pool = self.get_pool()
        with pool.begin() as conn:
            conn.execute(
                sqlalchemy.text("""
                    INSERT INTO person_attributes (person_id, attribute_type, attribute_value, source, updated_at)
                    VALUES (:person_id, :attr_type, :attr_value, :source, CURRENT_TIMESTAMP)
                    ON CONFLICT (person_id, attribute_type)
                    DO UPDATE SET attribute_value = :attr_value, source = :source, updated_at = CURRENT_TIMESTAMP
                """),
                {"person_id": person_id, "attr_type": attribute_type, "attr_value": attribute_value, "source": source}
            )
        return True

    def get_person_info(self, person_name: str) -> Optional[Dict[str, Any]]:
        """人物情報を取得"""
        pool = self.get_pool()
        with pool.connect() as conn:
            person_result = conn.execute(
                sqlalchemy.text("SELECT id FROM persons WHERE name = :name"),
                {"name": person_name}
            ).fetchone()
            if not person_result:
                return None
            person_id = person_result[0]
            attributes = conn.execute(
                sqlalchemy.text("""
                    SELECT attribute_type, attribute_value FROM person_attributes
                    WHERE person_id = :person_id ORDER BY updated_at DESC
                """),
                {"person_id": person_id}
            ).fetchall()
            return {
                "name": person_name,
                "attributes": [{"type": a[0], "value": a[1]} for a in attributes]
            }

    def delete_person(self, person_name: str) -> bool:
        """人物を削除"""
        pool = self.get_pool()
        with pool.connect() as conn:
            trans = conn.begin()
            try:
                person_result = conn.execute(
                    sqlalchemy.text("SELECT id FROM persons WHERE name = :name"),
                    {"name": person_name}
                ).fetchone()
                if not person_result:
                    trans.rollback()
                    return False
                person_id = person_result[0]
                conn.execute(
                    sqlalchemy.text("DELETE FROM person_attributes WHERE person_id = :person_id"),
                    {"person_id": person_id}
                )
                conn.execute(
                    sqlalchemy.text("DELETE FROM person_events WHERE person_id = :person_id"),
                    {"person_id": person_id}
                )
                conn.execute(
                    sqlalchemy.text("DELETE FROM persons WHERE id = :person_id"),
                    {"person_id": person_id}
                )
                trans.commit()
                return True
            except Exception as e:
                trans.rollback()
                print(f"削除エラー: {e}")
                return False

    def get_all_persons_summary(self) -> List[Dict[str, Any]]:
        """全人物のサマリーを取得"""
        pool = self.get_pool()
        with pool.connect() as conn:
            result = conn.execute(
                sqlalchemy.text("""
                    SELECT p.name, STRING_AGG(pa.attribute_type || '=' || pa.attribute_value, ', ') as attributes
                    FROM persons p
                    LEFT JOIN person_attributes pa ON p.id = pa.person_id
                    GROUP BY p.id, p.name ORDER BY p.name
                """)
            ).fetchall()
            return [{"name": r[0], "attributes": r[1]} for r in result]

    def search_person_by_partial_name(self, partial_name: str) -> List[str]:
        """部分一致で人物を検索"""
        normalized = normalize_person_name(partial_name) if partial_name else partial_name

        pool = self.get_pool()
        with pool.connect() as conn:
            result = conn.execute(
                sqlalchemy.text("""
                    SELECT name FROM persons
                    WHERE name ILIKE :pattern
                       OR name ILIKE :pattern2
                       OR name ILIKE :normalized_pattern
                    ORDER BY
                        CASE WHEN name = :exact THEN 0
                             WHEN name = :normalized THEN 0
                             WHEN name ILIKE :starts_with THEN 1
                             ELSE 2 END,
                        LENGTH(name)
                    LIMIT 5
                """),
                {
                    "pattern": f"%{partial_name}%",
                    "pattern2": f"%{partial_name}%",
                    "normalized_pattern": f"%{normalized}%",
                    "exact": partial_name,
                    "normalized": normalized,
                    "starts_with": f"{partial_name}%"
                }
            ).fetchall()
            print(f"   🔍 search_person_by_partial_name: '{partial_name}' (normalized: '{normalized}') → {len(result)}件")
            return [r[0] for r in result]


class OrgChartService:
    """
    組織図関連の機能を提供するサービスクラス
    """

    def __init__(self, get_pool: Callable):
        """
        Args:
            get_pool: DB接続プールを取得する関数
        """
        self.get_pool = get_pool

    def get_org_chart_overview(self) -> List[Dict[str, Any]]:
        """組織図の全体構造を取得（兼務を含む）"""
        pool = self.get_pool()
        with pool.connect() as conn:
            result = conn.execute(
                sqlalchemy.text("""
                    SELECT d.id, d.name, d.level, d.parent_id,
                           (SELECT COUNT(DISTINCT e.id)
                            FROM employees e
                            WHERE e.department_id = d.id
                               OR EXISTS (
                                   SELECT 1 FROM jsonb_array_elements(e.metadata->'departments') AS dept
                                   WHERE dept->>'department_id' = d.external_id
                               )
                           ) as member_count
                    FROM departments d
                    WHERE d.is_active = true
                    ORDER BY d.level, d.display_order, d.name
                """)
            ).fetchall()

            departments = []
            for r in result:
                departments.append({
                    "id": str(r[0]),
                    "name": r[1],
                    "level": r[2],
                    "parent_id": str(r[3]) if r[3] else None,
                    "member_count": r[4] or 0
                })
            return departments

    def search_department_by_name(self, partial_name: str) -> List[Dict[str, Any]]:
        """部署名で検索（部分一致、兼務を含む）"""
        pool = self.get_pool()
        with pool.connect() as conn:
            result = conn.execute(
                sqlalchemy.text("""
                    SELECT id, name, level,
                           (SELECT COUNT(DISTINCT e.id)
                            FROM employees e
                            WHERE e.department_id = d.id
                               OR EXISTS (
                                   SELECT 1 FROM jsonb_array_elements(e.metadata->'departments') AS dept
                                   WHERE dept->>'department_id' = d.external_id
                               )
                           ) as member_count
                    FROM departments d
                    WHERE d.is_active = true AND d.name ILIKE :pattern
                    ORDER BY d.level, d.name
                    LIMIT 10
                """),
                {"pattern": f"%{partial_name}%"}
            ).fetchall()

            return [{"id": str(r[0]), "name": r[1], "level": r[2], "member_count": r[3] or 0} for r in result]

    def get_department_members(self, dept_name: str) -> Tuple[Optional[str], List[Dict[str, Any]]]:
        """部署のメンバー一覧を取得（兼務者を含む）"""
        pool = self.get_pool()
        with pool.connect() as conn:
            # まず部署を検索
            dept_result = conn.execute(
                sqlalchemy.text("""
                    SELECT id, name, external_id FROM departments
                    WHERE is_active = true AND name ILIKE :pattern
                    LIMIT 1
                """),
                {"pattern": f"%{dept_name}%"}
            ).fetchone()

            if not dept_result:
                return None, []

            dept_id = dept_result[0]
            dept_full_name = dept_result[1]
            dept_external_id = dept_result[2]

            # 部署のメンバーを取得（主所属 + 兼務者）
            members_result = conn.execute(
                sqlalchemy.text("""
                    SELECT name, position, employment_type, is_concurrent, position_order
                    FROM (
                        SELECT e.name,
                               COALESCE(
                                   (SELECT dept->>'position'
                                    FROM jsonb_array_elements(e.metadata->'departments') AS dept
                                    WHERE dept->>'department_id' = :ext_id
                                    LIMIT 1),
                                   e.position
                               ) as position,
                               e.employment_type,
                               CASE WHEN e.department_id = :dept_id THEN 0 ELSE 1 END as is_concurrent,
                               CASE
                                   WHEN COALESCE(
                                       (SELECT dept->>'position'
                                        FROM jsonb_array_elements(e.metadata->'departments') AS dept
                                        WHERE dept->>'department_id' = :ext_id
                                        LIMIT 1),
                                       e.position
                                   ) LIKE '%代表%' THEN 1
                                   WHEN COALESCE(
                                       (SELECT dept->>'position'
                                        FROM jsonb_array_elements(e.metadata->'departments') AS dept
                                        WHERE dept->>'department_id' = :ext_id
                                        LIMIT 1),
                                       e.position
                                   ) LIKE '%部長%' THEN 2
                                   WHEN COALESCE(
                                       (SELECT dept->>'position'
                                        FROM jsonb_array_elements(e.metadata->'departments') AS dept
                                        WHERE dept->>'department_id' = :ext_id
                                        LIMIT 1),
                                       e.position
                                   ) LIKE '%課長%' THEN 3
                                   WHEN COALESCE(
                                       (SELECT dept->>'position'
                                        FROM jsonb_array_elements(e.metadata->'departments') AS dept
                                        WHERE dept->>'department_id' = :ext_id
                                        LIMIT 1),
                                       e.position
                                   ) LIKE '%リーダー%' THEN 4
                                   ELSE 10
                               END as position_order
                        FROM employees e
                        WHERE e.is_active = true
                          AND (e.department_id = :dept_id
                               OR EXISTS (
                                   SELECT 1 FROM jsonb_array_elements(e.metadata->'departments') AS dept
                                   WHERE dept->>'department_id' = :ext_id
                               ))
                    ) AS subquery
                    ORDER BY is_concurrent, position_order, name
                """),
                {"dept_id": dept_id, "ext_id": dept_external_id}
            ).fetchall()

            members = []
            for r in members_result:
                member = {
                    "name": r[0],
                    "position": r[1] or "メンバー",
                    "employment_type": r[2] or "正社員",
                }
                if r[3] == 1:
                    member["is_concurrent"] = True
                members.append(member)

            return dept_full_name, members


# =====================================================
# ユーティリティ関数
# =====================================================

def normalize_person_name(name: Optional[str]) -> Optional[str]:
    """
    人物名を正規化

    ChatWorkのユーザー名形式「高野　義浩 (タカノ ヨシヒロ)」を
    DBの形式「高野義浩」に変換する

    Args:
        name: 正規化前の名前

    Returns:
        正規化された名前
    """
    if not name:
        return name

    # 1. 読み仮名部分 (xxx) を除去
    normalized = re.sub(r'\s*\([^)]*\)\s*', '', name)

    # 2. 敬称を除去
    normalized = re.sub(r'(さん|くん|ちゃん|様|氏)$', '', normalized)

    # 3. スペース（全角・半角）を除去
    normalized = normalized.replace(' ', '').replace('　', '')

    print(f"   📝 名前正規化: '{name}' → '{normalized}'")

    return normalized.strip()


# =====================================================
# エクスポート
# =====================================================

__all__ = [
    "PersonService",
    "OrgChartService",
    "normalize_person_name",
]
