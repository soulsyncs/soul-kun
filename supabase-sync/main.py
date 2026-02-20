"""
Supabase → Cloud SQL フォームデータ同期 Cloud Function

Googleフォーム回答データ（Supabase保存）をCloud SQLに同期する。
非金融データのみ（3AI合議決定）。

同期対象:
    - employee_skills（スキル自己評価）
    - employee_work_preferences（稼働スタイル）
    - employee_contact_preferences（連絡設定、line_id除外）

同期除外:
    - employee_sensitive_data（銀行口座等）
    - employee_admin_notes（報酬・評価）
    - employee_contract（金融フィールド含む）

デプロイ:
    bash supabase-sync/deploy.sh

Cloud Scheduler:
    毎日06:00 JST

手動実行:
    curl -X POST -H 'Content-Type: application/json' \\
        -d '{"dry_run": true}' \\
        https://asia-northeast1-soulkun-production.cloudfunctions.net/supabase_sync

Author: Claude Code
Created: 2026-02-12
"""

import os
import sys
import json
import time
import uuid
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List, Any

from flask import Flask, Request, request as flask_request, jsonify
import httpx
from sqlalchemy import text as sql_text

app = Flask(__name__)

# Cloud Run / ローカル開発時のlib参照
current_dir = os.path.dirname(os.path.abspath(__file__))
if os.path.exists(os.path.join(current_dir, 'lib')):
    sys.path.insert(0, current_dir)
else:
    sys.path.insert(0, os.path.dirname(current_dir))

from lib.db import get_db_pool
from lib.secrets import get_secret_cached

# ================================================================
# 設定
# ================================================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))

ORGANIZATION_ID = os.getenv(
    'SOULKUN_ORG_ID',
    '5f98365f-e7c5-4f48-9918-7fe9aabae5df'
)
# Cloud SQL側のorganization_idはUUID文字列を使用
CLOUDSQL_ORG_ID = os.getenv('CLOUDSQL_ORG_ID', '5f98365f-e7c5-4f48-9918-7fe9aabae5df')

SUPABASE_URL = os.getenv(
    'SUPABASE_URL',
    'https://adzxpeboaoiojepcxlyc.supabase.co'
)

# 金融データテーブル（同期禁止）
FINANCIAL_TABLES = {
    'employee_sensitive_data',
    'employee_admin_notes',
    'employee_contract',
}


# ================================================================
# Supabase REST APIクライアント
# ================================================================


class SupabaseReader:
    """Supabase REST APIからフォームデータを読み取る"""

    def __init__(self, supabase_url: str, supabase_key: str):
        self.rest_url = f"{supabase_url}/rest/v1"
        self.headers = {
            'apikey': supabase_key,
            'Authorization': f'Bearer {supabase_key}',
            'Content-Type': 'application/json',
        }

    def fetch_table(self, table_name: str, select: str = '*') -> List[Dict]:
        """Supabaseテーブルからデータを取得（金融テーブルはブロック）"""
        if table_name in FINANCIAL_TABLES:
            raise ValueError(f"Refusing to fetch financial table: {table_name}")
        url = f"{self.rest_url}/{table_name}"
        params = {'select': select}

        with httpx.Client(timeout=30.0) as client:
            response = client.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            return response.json()

    def fetch_employees(self) -> List[Dict]:
        """全社員のID+名前を取得（マッチング用）"""
        return self.fetch_table('employees', select='id,name')

    def fetch_skills(self) -> List[Dict]:
        """スキル自己評価を取得"""
        return self.fetch_table(
            'employee_skills',
            select='employee_id,skill_levels,top_skills,weak_skills,'
                   'preferred_tasks,avoided_tasks,updated_at'
        )

    def fetch_work_preferences(self) -> List[Dict]:
        """稼働スタイルを取得"""
        return self.fetch_table(
            'employee_work_preferences',
            select='employee_id,monthly_hours,work_hours,work_style,'
                   'work_location,capacity,urgency_level,updated_at'
        )

    def fetch_contact_preferences(self) -> List[Dict]:
        """連絡設定を取得（line_id除外）"""
        return self.fetch_table(
            'employee_contact_preferences',
            select='employee_id,contact_available_hours,preferred_channel,'
                   'contact_ng,communication_style,ai_disclosure_level,'
                   'hobbies,updated_at'
            # line_idは意図的にselectから除外
        )


# ================================================================
# 社員IDマッチング
# ================================================================


def build_employee_mapping(
    conn, supabase_employees: List[Dict], org_id: str
) -> Dict[str, str]:
    """
    Supabase employee_id → Cloud SQL employee_id のマッピングを構築

    UUIDが異なるため、名前ベースで照合する。
    結果はsupabase_employee_mappingテーブルにキャッシュ。

    Args:
        conn: SQLAlchemy connection
        supabase_employees: Supabaseの社員リスト [{id, name}, ...]
        org_id: Cloud SQL側のorganization_id

    Returns:
        {supabase_employee_id: cloudsql_employee_id}
    """
    # Cloud SQL側の社員を全取得（CRITICAL-2: 重複名検出付き）
    result = conn.execute(
        sql_text("""
            SELECT id, name FROM employees
            WHERE organization_id = :org_id AND is_active = true
        """),
        {"org_id": org_id}
    )
    cloudsql_employees: Dict[str, Optional[str]] = {}
    for row in result:
        name = row[1]
        if name in cloudsql_employees:
            logger.error(
                "Duplicate employee name in Cloud SQL (ids: %s, %s). "
                "Skipping both to prevent mismatch.",
                cloudsql_employees[name], str(row[0])
            )
            cloudsql_employees[name] = None  # 曖昧なのでスキップ
        else:
            cloudsql_employees[name] = str(row[0])

    mapping = {}
    unmatched_count = 0

    for sb_emp in supabase_employees:
        sb_id = sb_emp['id']
        sb_name = sb_emp['name']

        # 完全一致マッチング（重複名はNone → スキップ）
        cs_id = cloudsql_employees.get(sb_name)
        if cs_id is not None:
            mapping[sb_id] = cs_id

            # マッピングテーブルにキャッシュ
            conn.execute(
                sql_text("""
                    INSERT INTO supabase_employee_mapping
                        (organization_id, supabase_employee_id,
                         cloudsql_employee_id, employee_name)
                    VALUES (:org_id, CAST(:sb_id AS uuid),
                            CAST(:cs_id AS uuid), :name)
                    ON CONFLICT (supabase_employee_id, organization_id)
                    DO UPDATE SET
                        cloudsql_employee_id = CAST(:cs_id AS uuid),
                        employee_name = :name,
                        updated_at = NOW()
                """),
                {
                    "org_id": org_id,
                    "sb_id": sb_id,
                    "cs_id": cs_id,
                    "name": sb_name,
                }
            )
        else:
            unmatched_count += 1

    # MEDIUM-3: PIIをログに含めない（カウントのみ）
    if unmatched_count:
        logger.warning(
            "Unmatched employees: %d of %d",
            unmatched_count, len(supabase_employees)
        )

    logger.info(
        "Employee mapping: %d matched, %d unmatched",
        len(mapping), unmatched_count
    )
    return mapping


# ================================================================
# 組織図所属データ同期ヘルパー
# ================================================================


def build_user_mapping_by_chatwork(
    conn, sb_employees: List[Dict], org_id: str
) -> Dict[str, str]:
    """
    Supabase employee_id → Cloud SQL user_id のマッピング

    1次: chatwork_account_id マッチング（より確実）
    2次: 名前マッチング（フォールバック）
    重複名はスキップ（安全優先）
    """
    result = conn.execute(
        sql_text("""
            SELECT id, chatwork_account_id, name
            FROM users
            WHERE organization_id = :org_id AND is_active = true
        """),
        {"org_id": org_id}
    )
    cs_by_chatwork: Dict[str, str] = {}
    cs_by_name: Dict[str, Optional[str]] = {}
    for row in result:
        user_id = str(row[0])
        cw_id = str(row[1]).strip() if row[1] else None
        name = row[2]
        if cw_id:
            cs_by_chatwork[cw_id] = user_id
        if name:
            if name in cs_by_name:
                cs_by_name[name] = None  # 重複名 → スキップ
            else:
                cs_by_name[name] = user_id

    mapping: Dict[str, str] = {}
    chatwork_matched = 0
    name_matched = 0
    unmatched = 0

    for emp in sb_employees:
        sb_id = emp.get('id')
        if not sb_id:
            continue
        # 1次: chatwork_account_id
        cw_id = str(emp.get('chatwork_account_id', '') or '').strip()
        if cw_id and cw_id in cs_by_chatwork:
            mapping[sb_id] = cs_by_chatwork[cw_id]
            chatwork_matched += 1
            continue
        # 2次: 名前フォールバック
        name = emp.get('name')
        if name and cs_by_name.get(name):
            mapping[sb_id] = cs_by_name[name]  # type: ignore[assignment]
            name_matched += 1
            continue
        unmatched += 1

    logger.info(
        "User mapping: chatwork=%d, name=%d, unmatched=%d",
        chatwork_matched, name_matched, unmatched
    )
    return mapping


def build_dept_mapping(
    conn, sb_departments: List[Dict], org_id: str
) -> Dict[str, str]:
    """
    Supabase dept_id → Cloud SQL dept_id のマッピング（部署名で照合）
    重複名はスキップ（安全優先）
    """
    result = conn.execute(
        sql_text("""
            SELECT id, name FROM departments
            WHERE organization_id = :org_id AND is_active = true
        """),
        {"org_id": org_id}
    )
    cs_by_name: Dict[str, Optional[str]] = {}
    for row in result:
        name = row[1]
        if name in cs_by_name:
            cs_by_name[name] = None  # 重複 → スキップ
        else:
            cs_by_name[name] = str(row[0])

    mapping: Dict[str, str] = {}
    unmatched_count = 0
    for dept in sb_departments:
        sb_id = dept.get('id')
        name = dept.get('name')
        if not sb_id or not name:
            continue
        cs_id = cs_by_name.get(name)
        if cs_id:
            mapping[sb_id] = cs_id
        else:
            unmatched_count += 1

    logger.info(
        "Dept mapping: %d matched, %d unmatched",
        len(mapping), unmatched_count
    )
    return mapping


def get_default_role_id(conn, org_id: str) -> Optional[str]:
    """組織の最も低いレベルのロールIDを返す（role_idのデフォルト値）"""
    result = conn.execute(
        sql_text("""
            SELECT id FROM roles
            WHERE organization_id = :org_id
            ORDER BY level ASC
            LIMIT 1
        """),
        {"org_id": org_id}
    )
    row = result.fetchone()
    return str(row[0]) if row else None


def sync_org_assignments(
    conn,
    sb_employees: List[Dict],
    user_map: Dict[str, str],
    dept_map: Dict[str, str],
    default_role_id: Optional[str],
    org_id: str,
    dry_run: bool = True,
) -> Dict[str, int]:
    """
    Supabaseの所属データを user_departments に同期（UPSERT）

    - 主所属 (department_id) と兼務 (departments_json) を両方処理
    - 既存レコードがあれば is_primary のみ更新
    - 新規レコードは default_role_id を使用
    - dry_run=True では DB書き込みを行わずカウントのみ返す
    """
    inserted = 0
    updated = 0
    skipped = 0

    for emp in sb_employees:
        sb_id = emp.get('id')
        cs_user_id = user_map.get(sb_id)
        if not cs_user_id:
            skipped += 1
            continue

        # 主所属 + 兼務部署のリストを作成
        assignments: List[Dict[str, Any]] = []

        main_dept_sb_id = emp.get('department_id')
        if main_dept_sb_id:
            cs_dept_id = dept_map.get(main_dept_sb_id)
            if cs_dept_id:
                assignments.append({'dept_id': cs_dept_id, 'is_primary': True})

        departments_json_raw = emp.get('departments_json')
        if departments_json_raw:
            try:
                additional = (
                    json.loads(departments_json_raw)
                    if isinstance(departments_json_raw, str)
                    else departments_json_raw
                )
                for extra in (additional or []):
                    extra_sb_dept_id = extra.get('department_id')
                    if extra_sb_dept_id and extra_sb_dept_id != main_dept_sb_id:
                        cs_dept_id = dept_map.get(extra_sb_dept_id)
                        if cs_dept_id:
                            assignments.append({'dept_id': cs_dept_id, 'is_primary': False})
            except (json.JSONDecodeError, TypeError, AttributeError) as e:
                logger.warning("Failed to parse departments_json: %s", e)

        if not assignments:
            skipped += 1
            continue

        for assignment in assignments:
            cs_dept_id = assignment['dept_id']
            is_primary = assignment['is_primary']

            if dry_run:
                inserted += 1  # dry_run では新規扱いでカウント
                continue

            # 既存の有効な所属レコードを確認
            existing_row = conn.execute(
                sql_text("""
                    SELECT id, is_primary FROM user_departments
                    WHERE user_id = CAST(:user_id AS uuid)
                      AND department_id = CAST(:dept_id AS uuid)
                      AND ended_at IS NULL
                    LIMIT 1
                """),
                {"user_id": cs_user_id, "dept_id": cs_dept_id}
            ).fetchone()

            if existing_row:
                if bool(existing_row[1]) != is_primary:
                    conn.execute(
                        sql_text("""
                            UPDATE user_departments
                            SET is_primary = :is_primary, updated_at = NOW()
                            WHERE id = CAST(:id AS uuid)
                        """),
                        {"id": str(existing_row[0]), "is_primary": is_primary}
                    )
                    updated += 1
            else:
                if not default_role_id:
                    logger.warning(
                        "No default role in org %s, skipping assignment", org_id
                    )
                    skipped += 1
                    continue
                conn.execute(
                    sql_text("""
                        INSERT INTO user_departments
                            (id, user_id, department_id, role_id, is_primary, started_at)
                        VALUES
                            (gen_random_uuid(),
                             CAST(:user_id AS uuid),
                             CAST(:dept_id AS uuid),
                             CAST(:role_id AS uuid),
                             :is_primary,
                             NOW())
                    """),
                    {
                        "user_id": cs_user_id,
                        "dept_id": cs_dept_id,
                        "role_id": default_role_id,
                        "is_primary": is_primary,
                    }
                )
                inserted += 1

    return {"inserted": inserted, "updated": updated, "skipped": skipped}


# ================================================================
# Cloud SQL同期（UPSERT）
# ================================================================


def sync_skills(
    conn, data: List[Dict], mapping: Dict[str, str], org_id: str
) -> int:
    """スキル自己評価をCloud SQLに同期"""
    synced = 0
    for row in data:
        cs_id = mapping.get(row['employee_id'])
        if not cs_id:
            continue

        conn.execute(
            sql_text("""
                INSERT INTO form_employee_skills
                    (organization_id, employee_id, skill_levels,
                     top_skills, weak_skills, preferred_tasks,
                     avoided_tasks, supabase_updated_at, synced_at)
                VALUES
                    (:org_id, CAST(:emp_id AS uuid),
                     CAST(:skill_levels AS jsonb),
                     CAST(:top_skills AS jsonb),
                     CAST(:weak_skills AS jsonb),
                     CAST(:preferred_tasks AS jsonb),
                     CAST(:avoided_tasks AS jsonb),
                     CAST(:updated_at AS timestamptz), NOW())
                ON CONFLICT (employee_id, organization_id)
                DO UPDATE SET
                    skill_levels = CAST(:skill_levels AS jsonb),
                    top_skills = CAST(:top_skills AS jsonb),
                    weak_skills = CAST(:weak_skills AS jsonb),
                    preferred_tasks = CAST(:preferred_tasks AS jsonb),
                    avoided_tasks = CAST(:avoided_tasks AS jsonb),
                    supabase_updated_at = CAST(:updated_at AS timestamptz),
                    synced_at = NOW(),
                    updated_at = NOW()
            """),
            {
                "org_id": org_id,
                "emp_id": cs_id,
                "skill_levels": json.dumps(
                    row.get('skill_levels') or {}, ensure_ascii=False
                ),
                "top_skills": json.dumps(
                    row.get('top_skills') or [], ensure_ascii=False
                ),
                "weak_skills": json.dumps(
                    row.get('weak_skills') or [], ensure_ascii=False
                ),
                "preferred_tasks": json.dumps(
                    row.get('preferred_tasks') or [], ensure_ascii=False
                ),
                "avoided_tasks": json.dumps(
                    row.get('avoided_tasks') or [], ensure_ascii=False
                ),
                "updated_at": row.get('updated_at'),
            }
        )
        synced += 1
    return synced


def sync_work_preferences(
    conn, data: List[Dict], mapping: Dict[str, str], org_id: str
) -> int:
    """稼働スタイルをCloud SQLに同期"""
    synced = 0
    for row in data:
        cs_id = mapping.get(row['employee_id'])
        if not cs_id:
            continue

        conn.execute(
            sql_text("""
                INSERT INTO form_employee_work_prefs
                    (organization_id, employee_id, monthly_hours,
                     work_hours, work_style, work_location,
                     capacity, urgency_level,
                     supabase_updated_at, synced_at)
                VALUES
                    (:org_id, CAST(:emp_id AS uuid), :monthly_hours,
                     CAST(:work_hours AS jsonb),
                     CAST(:work_style AS jsonb),
                     :work_location, :capacity, :urgency_level,
                     CAST(:updated_at AS timestamptz), NOW())
                ON CONFLICT (employee_id, organization_id)
                DO UPDATE SET
                    monthly_hours = :monthly_hours,
                    work_hours = CAST(:work_hours AS jsonb),
                    work_style = CAST(:work_style AS jsonb),
                    work_location = :work_location,
                    capacity = :capacity,
                    urgency_level = :urgency_level,
                    supabase_updated_at = CAST(:updated_at AS timestamptz),
                    synced_at = NOW(),
                    updated_at = NOW()
            """),
            {
                "org_id": org_id,
                "emp_id": cs_id,
                "monthly_hours": row.get('monthly_hours'),
                "work_hours": json.dumps(
                    row.get('work_hours') or [], ensure_ascii=False
                ),
                "work_style": json.dumps(
                    row.get('work_style') or [], ensure_ascii=False
                ),
                "work_location": row.get('work_location'),
                "capacity": row.get('capacity'),
                "urgency_level": row.get('urgency_level'),
                "updated_at": row.get('updated_at'),
            }
        )
        synced += 1
    return synced


def sync_contact_preferences(
    conn, data: List[Dict], mapping: Dict[str, str], org_id: str
) -> int:
    """連絡設定をCloud SQLに同期（line_id除外済み）"""
    synced = 0
    for row in data:
        cs_id = mapping.get(row['employee_id'])
        if not cs_id:
            continue

        conn.execute(
            sql_text("""
                INSERT INTO form_employee_contact_prefs
                    (organization_id, employee_id,
                     contact_available_hours, preferred_channel,
                     contact_ng, communication_style,
                     ai_disclosure_level, hobbies,
                     supabase_updated_at, synced_at)
                VALUES
                    (:org_id, CAST(:emp_id AS uuid),
                     :contact_hours, :channel,
                     CAST(:contact_ng AS jsonb),
                     :comm_style, :ai_level, :hobbies,
                     CAST(:updated_at AS timestamptz), NOW())
                ON CONFLICT (employee_id, organization_id)
                DO UPDATE SET
                    contact_available_hours = :contact_hours,
                    preferred_channel = :channel,
                    contact_ng = CAST(:contact_ng AS jsonb),
                    communication_style = :comm_style,
                    ai_disclosure_level = :ai_level,
                    hobbies = :hobbies,
                    supabase_updated_at = CAST(:updated_at AS timestamptz),
                    synced_at = NOW(),
                    updated_at = NOW()
            """),
            {
                "org_id": org_id,
                "emp_id": cs_id,
                "contact_hours": row.get('contact_available_hours'),
                "channel": row.get('preferred_channel'),
                "contact_ng": json.dumps(
                    row.get('contact_ng') or [], ensure_ascii=False
                ),
                "comm_style": row.get('communication_style'),
                "ai_level": row.get('ai_disclosure_level', 'full'),
                "hobbies": row.get('hobbies'),
                "updated_at": row.get('updated_at'),
            }
        )
        synced += 1
    return synced


# ================================================================
# person_attributes ブリッジ
# ================================================================


def bridge_to_person_attributes(
    conn, mapping: Dict[str, str],
    skills_data: List[Dict],
    work_data: List[Dict],
    contact_data: List[Dict],
) -> int:
    """
    フォームデータをperson_attributes EAVに要約展開する。
    Brain の context_builder が既存パスで読めるようにする。

    Note: persons/person_attributes は ORGANIZATION_ID (UUID) を使用。
          form_employee_* テーブルの CLOUDSQL_ORG_ID ('5f98365f-e7c5-4f48-9918-7fe9aabae5df') とは異なる。

    Returns:
        更新した属性数
    """
    updated = 0

    # HIGH-1: バッチクエリで employee_id → persons.id を一括取得
    cs_ids = list(set(mapping.values()))
    if not cs_ids:
        return 0

    result = conn.execute(
        sql_text("""
            SELECT CAST(e.id AS text), p.id
            FROM persons p
            JOIN employees e ON LOWER(TRIM(e.name)) = LOWER(TRIM(p.name))
            WHERE CAST(e.id AS text) = ANY(:emp_ids)
              AND p.organization_id = :org_id
        """),
        {"emp_ids": cs_ids, "org_id": ORGANIZATION_ID}
    )

    # cs_id → person_id マップ（UUID文字列）
    cs_to_person: Dict[str, str] = {}
    for row in result:
        cs_to_person[row[0]] = str(row[1])

    # sb_id → person_id マップ（UUID文字列）
    emp_to_person: Dict[str, str] = {}
    for sb_id, cs_id in mapping.items():
        pid = cs_to_person.get(cs_id)
        if pid is not None:
            emp_to_person[sb_id] = pid

    def _upsert_attr(person_id: str, attr_type: str, attr_value: str):
        """person_attributesにUPSERT"""
        nonlocal updated
        if not attr_value:
            return
        conn.execute(
            sql_text("""
                INSERT INTO person_attributes
                    (person_id, attribute_type, attribute_value,
                     source, organization_id, updated_at)
                VALUES
                    (:pid, :atype, :aval,
                     'form_sync', :org_id, NOW())
                ON CONFLICT (person_id, attribute_type)
                DO UPDATE SET
                    attribute_value = :aval,
                    source = 'form_sync',
                    updated_at = NOW()
            """),
            {
                "pid": person_id,
                "atype": attr_type,
                "aval": attr_value,
                "org_id": ORGANIZATION_ID,
            }
        )
        updated += 1

    # スキルデータ → person_attributes
    for row in skills_data:
        person_id = emp_to_person.get(row['employee_id'])
        if not person_id:
            continue

        top = row.get('top_skills') or []
        if isinstance(top, list):
            _upsert_attr(person_id, 'スキル（得意）', ', '.join(top))

        weak = row.get('weak_skills') or []
        if isinstance(weak, list):
            _upsert_attr(person_id, 'スキル（苦手）', ', '.join(weak))

    # 稼働データ → person_attributes
    for row in work_data:
        person_id = emp_to_person.get(row['employee_id'])
        if not person_id:
            continue

        _upsert_attr(person_id, '稼働スタイル', row.get('work_location', ''))
        _upsert_attr(person_id, 'キャパシティ', row.get('capacity', ''))
        _upsert_attr(person_id, '月間稼働', row.get('monthly_hours', ''))

    # 連絡設定 → person_attributes
    for row in contact_data:
        person_id = emp_to_person.get(row['employee_id'])
        if not person_id:
            continue

        _upsert_attr(
            person_id, '連絡手段',
            row.get('preferred_channel', '')
        )
        _upsert_attr(
            person_id, 'コミュニケーション',
            row.get('communication_style', '')
        )
        _upsert_attr(person_id, '趣味', row.get('hobbies', ''))
        _upsert_attr(
            person_id, '連絡可能時間',
            row.get('contact_available_hours', '')
        )

    return updated


# ================================================================
# 同期ログ
# ================================================================


def log_sync_result(
    conn, org_id: str, sync_id: str,
    status: str, counts: Dict[str, int],
    duration_ms: int,
    error_message: Optional[str] = None,
    trigger_source: str = 'scheduled',
):
    """org_chart_sync_logsに同期結果を記録（CRITICAL-1: request_payloadに詳細格納）"""
    conn.execute(
        sql_text("""
            INSERT INTO org_chart_sync_logs
                (sync_id, organization_id, sync_type, source_system,
                 status, started_at, completed_at, duration_ms,
                 error_message, trigger_source, request_payload)
            VALUES
                (:sync_id, :org_id, 'form_data', 'supabase_forms',
                 :status,
                 NOW() - INTERVAL '1 millisecond' * :duration,
                 NOW(), :duration,
                 :error_msg, :trigger,
                 CAST(:payload AS jsonb))
        """),
        {
            "sync_id": sync_id,
            "org_id": org_id,
            "status": status,
            "duration": duration_ms,
            "error_msg": error_message,
            "trigger": trigger_source,
            "payload": json.dumps(counts),
        }
    )


# ================================================================
# メインエントリーポイント
# ================================================================


@app.route("/", methods=["POST"])
def supabase_sync():
    """
    Supabase → Cloud SQL フォームデータ同期

    Request body (JSON):
        dry_run: bool (default: false) - trueの場合、読み取りのみ
    """
    request = flask_request
    start_time = time.time()
    # MEDIUM-6: UUID suffix で一意性を保証
    sync_id = f"FORM-SYNC-{datetime.now(JST).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"

    # リクエスト解析
    try:
        body = request.get_json(silent=True) or {}
    except Exception:
        body = {}
    dry_run = body.get('dry_run', False)

    # MEDIUM-5: Cloud Schedulerヘッダーで判定
    is_scheduled = bool(request.headers.get('X-CloudScheduler'))
    trigger_source = 'scheduled' if is_scheduled else 'manual'

    logger.info(
        "[%s] Starting form data sync (dry_run=%s)", sync_id, dry_run
    )

    try:
        # Supabase接続設定
        supabase_key = _get_supabase_key()
        if not supabase_key:
            return jsonify({
                "error": "SUPABASE_ANON_KEY not configured"
            }), 500

        reader = SupabaseReader(SUPABASE_URL, supabase_key)

        # Step 1: Supabaseからデータ読み取り
        logger.info("[%s] Fetching data from Supabase...", sync_id)
        sb_employees = reader.fetch_employees()
        skills_data = reader.fetch_skills()
        work_data = reader.fetch_work_preferences()
        contact_data = reader.fetch_contact_preferences()

        logger.info(
            "[%s] Fetched: %d employees, %d skills, "
            "%d work_prefs, %d contact_prefs",
            sync_id, len(sb_employees), len(skills_data),
            len(work_data), len(contact_data)
        )

        if dry_run:
            duration_ms = int((time.time() - start_time) * 1000)
            return jsonify({
                "sync_id": sync_id,
                "dry_run": True,
                "supabase_counts": {
                    "employees": len(sb_employees),
                    "skills": len(skills_data),
                    "work_preferences": len(work_data),
                    "contact_preferences": len(contact_data),
                },
                "duration_ms": duration_ms,
            })

        # Step 2: Cloud SQLに同期
        pool = get_db_pool()
        with pool.connect() as conn:
            # statement_timeout設定（PR #471パターン）
            conn.execute(sql_text(
                "SELECT set_config('statement_timeout', '10000', false)"
            ))

            # マッピング構築
            mapping = build_employee_mapping(
                conn, sb_employees, CLOUDSQL_ORG_ID
            )

            if not mapping:
                logger.warning("[%s] No employee mapping found", sync_id)
                conn.commit()
                duration_ms = int((time.time() - start_time) * 1000)
                return jsonify({
                    "sync_id": sync_id,
                    "error": "No employee mapping found",
                    "duration_ms": duration_ms,
                }), 200

            # 同期実行
            skills_count = sync_skills(
                conn, skills_data, mapping, CLOUDSQL_ORG_ID
            )
            work_count = sync_work_preferences(
                conn, work_data, mapping, CLOUDSQL_ORG_ID
            )
            contact_count = sync_contact_preferences(
                conn, contact_data, mapping, CLOUDSQL_ORG_ID
            )

            # person_attributes ブリッジ（ORGANIZATION_ID使用、CLOUDSQL_ORG_IDとは異なる）
            bridge_count = bridge_to_person_attributes(
                conn, mapping,
                skills_data, work_data, contact_data,
            )

            # 同期ログ記録
            duration_ms = int((time.time() - start_time) * 1000)
            counts = {
                "skills": skills_count,
                "work_prefs": work_count,
                "contact_prefs": contact_count,
                "person_attributes": bridge_count,
            }
            log_sync_result(
                conn, CLOUDSQL_ORG_ID, sync_id,
                'success', counts, duration_ms,
                trigger_source=trigger_source,
            )

            conn.commit()

        logger.info(
            "[%s] Sync complete: skills=%d, work=%d, contact=%d, "
            "bridge=%d (duration=%dms)",
            sync_id, skills_count, work_count, contact_count,
            bridge_count, duration_ms,
        )

        return jsonify({
            "sync_id": sync_id,
            "status": "success",
            "counts": counts,
            "mapping_count": len(mapping),
            "duration_ms": duration_ms,
        })

    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        logger.error(
            "[%s] Sync failed: %s: %s",
            sync_id, type(e).__name__, e
        )

        # エラーログをDBに記録（可能であれば）
        try:
            pool = get_db_pool()
            with pool.connect() as conn:
                log_sync_result(
                    conn, CLOUDSQL_ORG_ID, sync_id,
                    'failed', {}, duration_ms,
                    error_message=f"{type(e).__name__}: {str(e)[:200]}",
                    trigger_source=trigger_source,
                )
                conn.commit()
        except Exception:
            pass

        return jsonify({
            "sync_id": sync_id,
            "status": "failed",
            "error": type(e).__name__,
            "duration_ms": duration_ms,
        }), 500


def _get_supabase_key() -> Optional[str]:
    """Supabase anon keyを取得"""
    # 1. Secret Manager
    try:
        return get_secret_cached('SUPABASE_ANON_KEY')
    except Exception:
        pass

    # 2. 環境変数
    key = os.getenv('SUPABASE_ANON_KEY')
    if key:
        return key

    return None


# ================================================================
# 組織図所属データ同期エンドポイント
# ================================================================


@app.route("/sync-org", methods=["POST"])
def sync_org():
    """
    Supabase → Cloud SQL 組織図所属データ同期

    Supabase の employees.department_id / departments_json を
    Cloud SQL の user_departments テーブルに同期する。

    Request body (JSON):
        dry_run: bool (default: true) - trueの場合、読み取りのみ（書き込みなし）

    手動実行例:
        # ドライラン（安全確認）
        curl -X POST -H 'Content-Type: application/json' \\
            -d '{"dry_run": true}' \\
            https://supabase-sync-xxxxx-an.a.run.app/sync-org

        # 本番実行
        curl -X POST -H 'Content-Type: application/json' \\
            -d '{"dry_run": false}' \\
            https://supabase-sync-xxxxx-an.a.run.app/sync-org
    """
    request = flask_request
    start_time = time.time()
    sync_id = f"ORG-SYNC-{datetime.now(JST).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"

    try:
        body = request.get_json(silent=True) or {}
    except Exception:
        body = {}
    dry_run = body.get('dry_run', True)  # 安全のためデフォルトはTrue

    logger.info("[%s] Starting org sync (dry_run=%s)", sync_id, dry_run)

    try:
        supabase_key = _get_supabase_key()
        if not supabase_key:
            return jsonify({"error": "SUPABASE_ANON_KEY not configured"}), 500

        reader = SupabaseReader(SUPABASE_URL, supabase_key)

        # Step 1: Supabaseから組織データ読み取り
        logger.info("[%s] Fetching org data from Supabase...", sync_id)
        # select=* でテーブル全列取得（org_chart_serviceと同じパターン）
        sb_employees_raw = reader.fetch_table('employees', select='*')
        sb_departments = reader.fetch_table('departments', select='id,name')

        # アクティブ社員のみ絞り込み
        sb_employees = [e for e in sb_employees_raw if e.get('is_active', True)]

        logger.info(
            "[%s] Fetched: %d active employees (of %d), %d departments",
            sync_id, len(sb_employees), len(sb_employees_raw), len(sb_departments)
        )

        # Step 2: Cloud SQL マッピング構築 + 同期
        pool = get_db_pool()
        with pool.connect() as conn:
            conn.execute(sql_text(
                "SELECT set_config('statement_timeout', '30000', false)"
            ))

            user_map = build_user_mapping_by_chatwork(
                conn, sb_employees, CLOUDSQL_ORG_ID
            )
            dept_map = build_dept_mapping(
                conn, sb_departments, CLOUDSQL_ORG_ID
            )
            default_role_id = get_default_role_id(conn, CLOUDSQL_ORG_ID)

            logger.info(
                "[%s] Mappings: users=%d/%d, depts=%d/%d, default_role=%s",
                sync_id,
                len(user_map), len(sb_employees),
                len(dept_map), len(sb_departments),
                default_role_id,
            )

            if not user_map:
                duration_ms = int((time.time() - start_time) * 1000)
                return jsonify({
                    "sync_id": sync_id,
                    "warning": "No user mapping found. Check chatwork_account_id in Supabase.",
                    "supabase_employee_count": len(sb_employees),
                    "duration_ms": duration_ms,
                }), 200

            # Step 3: 所属データ同期
            counts = sync_org_assignments(
                conn, sb_employees, user_map, dept_map,
                default_role_id, CLOUDSQL_ORG_ID, dry_run=dry_run
            )

            if not dry_run:
                conn.commit()

        duration_ms = int((time.time() - start_time) * 1000)
        logger.info(
            "[%s] Org sync complete: %s (duration=%dms)", sync_id, counts, duration_ms
        )

        return jsonify({
            "sync_id": sync_id,
            "dry_run": dry_run,
            "supabase_employee_count": len(sb_employees),
            "supabase_dept_count": len(sb_departments),
            "user_mapping_count": len(user_map),
            "dept_mapping_count": len(dept_map),
            "default_role_id": default_role_id,
            "counts": counts,
            "duration_ms": duration_ms,
        })

    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        logger.error("[%s] Org sync failed: %s: %s", sync_id, type(e).__name__, e)
        return jsonify({
            "sync_id": sync_id,
            "status": "failed",
            "error": type(e).__name__,
            "duration_ms": duration_ms,
        }), 500
