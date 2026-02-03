"""
組織図サービスモジュール

組織図データベース（Supabase）から社員・部署情報を取得し、
Google Drive権限管理に必要なデータを提供する。

使用例:
    from lib.org_chart_service import OrgChartService

    service = OrgChartService(supabase_url, supabase_key)

    # 部署の社員を取得
    employees = await service.get_employees_by_department("dept-uuid")

    # 役職レベル以上の社員を取得
    managers = await service.get_employees_by_role_level(min_level=4)

    # 全社員のGoogleアカウントを取得
    accounts = await service.get_all_google_accounts()

Phase B: Google Drive 自動権限管理機能
Created: 2026-01-26
"""

import os
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
import logging
import httpx


logger = logging.getLogger(__name__)


# ================================================================
# 定数
# ================================================================

# デフォルトの組織ID
DEFAULT_ORGANIZATION_ID = "org_soulsyncs"

# 役職レベルの定義（roles.levelに対応）
ROLE_LEVELS = {
    1: "一般スタッフ",
    2: "シニアスタッフ",
    3: "リーダー",
    4: "マネージャー",
    5: "部長",
    6: "役員",
}


# ================================================================
# データクラス
# ================================================================

@dataclass
class Employee:
    """社員情報"""
    id: str
    name: str
    department_id: Optional[str] = None
    department_name: Optional[str] = None
    role_id: Optional[str] = None
    role_name: Optional[str] = None
    role_level: int = 1
    google_account_email: Optional[str] = None
    chatwork_account_id: Optional[str] = None
    email_work: Optional[str] = None
    is_active: bool = True

    # 兼務部署
    additional_departments: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def has_google_account(self) -> bool:
        """Googleアカウントが設定されているか"""
        return bool(self.google_account_email)

    @property
    def all_department_ids(self) -> List[str]:
        """全ての所属部署ID（主部署 + 兼務部署）"""
        dept_ids = []
        if self.department_id:
            dept_ids.append(self.department_id)
        for dept in self.additional_departments:
            if dept.get('department_id'):
                dept_ids.append(dept['department_id'])
        return dept_ids


@dataclass
class Department:
    """部署情報"""
    id: str
    name: str
    parent_id: Optional[str] = None
    organization_id: str = DEFAULT_ORGANIZATION_ID
    path: Optional[str] = None  # LTREE形式のパス

    @property
    def is_top_level(self) -> bool:
        """トップレベル部署かどうか"""
        return self.parent_id is None


@dataclass
class Role:
    """役職情報"""
    id: str
    name: str
    level: int
    organization_id: str = DEFAULT_ORGANIZATION_ID


# ================================================================
# Org Chart Service
# ================================================================

class OrgChartService:
    """
    組織図サービス

    Supabase REST APIを使用して組織図データを取得する。
    """

    def __init__(
        self,
        supabase_url: Optional[str] = None,
        supabase_key: Optional[str] = None,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        skip_organization_filter: bool = True  # 単一テナント環境ではTrueに
    ):
        """
        Args:
            supabase_url: Supabase REST API URL
            supabase_key: Supabase API Key (anon key)
            organization_id: 組織ID
            skip_organization_filter: organization_idフィルタをスキップするか
                                       （単一テナント環境ではTrueに設定）
        """
        self.supabase_url = supabase_url or os.getenv('SUPABASE_URL')
        self.supabase_key = supabase_key or os.getenv('SUPABASE_ANON_KEY')
        self.organization_id = organization_id
        self.skip_organization_filter = skip_organization_filter

        if not self.supabase_url or not self.supabase_key:
            raise ValueError("Supabase URL and Key are required")

        self.rest_url = f"{self.supabase_url}/rest/v1"
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """HTTPクライアントを取得"""
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers={
                    'apikey': self.supabase_key,
                    'Authorization': f'Bearer {self.supabase_key}',
                    'Content-Type': 'application/json',
                },
                timeout=30.0
            )
        return self._client

    async def close(self):
        """クライアントを閉じる"""
        if self._client:
            await self._client.aclose()
            self._client = None

    # ================================================================
    # 社員取得
    # ================================================================

    async def get_all_employees(
        self,
        with_google_account_only: bool = False
    ) -> List[Employee]:
        """
        全社員を取得

        Args:
            with_google_account_only: Googleアカウント設定済みの社員のみ

        Returns:
            社員リスト
        """
        client = await self._get_client()

        # 社員データを取得
        url = f"{self.rest_url}/employees"
        params = {
            'select': '*,departments(*),roles(*)',
            'is_active': 'eq.true'
        }

        # マルチテナント環境の場合のみorganization_idフィルタを追加
        if not self.skip_organization_filter:
            params['organization_id'] = f'eq.{self.organization_id}'

        if with_google_account_only:
            params['google_account_email'] = 'not.is.null'

        response = await client.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        employees = []
        for emp_data in data:
            employee = self._parse_employee(emp_data)
            employees.append(employee)

        logger.info(f"Fetched {len(employees)} employees")
        return employees

    async def get_employees_by_department(
        self,
        department_id: str,
        include_sub_departments: bool = False
    ) -> List[Employee]:
        """
        部署に所属する社員を取得

        Args:
            department_id: 部署ID
            include_sub_departments: 子部署の社員も含めるか

        Returns:
            社員リスト
        """
        all_employees = await self.get_all_employees()

        # 対象部署IDリスト
        target_dept_ids = {department_id}

        if include_sub_departments:
            # 子部署を取得
            departments = await self.get_all_departments()
            child_ids = self._get_child_department_ids(departments, department_id)
            target_dept_ids.update(child_ids)

        # フィルタリング
        result = []
        for emp in all_employees:
            emp_dept_ids = set(emp.all_department_ids)
            if emp_dept_ids & target_dept_ids:
                result.append(emp)

        return result

    async def get_employees_by_role_level(
        self,
        min_level: int = 1,
        max_level: int = 6
    ) -> List[Employee]:
        """
        役職レベル範囲の社員を取得

        Args:
            min_level: 最小レベル
            max_level: 最大レベル

        Returns:
            社員リスト
        """
        all_employees = await self.get_all_employees()
        return [
            emp for emp in all_employees
            if min_level <= emp.role_level <= max_level
        ]

    async def get_employee_by_id(self, employee_id: str) -> Optional[Employee]:
        """社員をIDで取得"""
        client = await self._get_client()

        url = f"{self.rest_url}/employees"
        params = {
            'select': '*,departments(*),roles(*)',
            'id': f'eq.{employee_id}',
        }

        # マルチテナント環境の場合のみorganization_idフィルタを追加
        if not self.skip_organization_filter:
            params['organization_id'] = f'eq.{self.organization_id}'

        response = await client.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        if data:
            return self._parse_employee(data[0])
        return None

    # ================================================================
    # 部署取得
    # ================================================================

    async def get_all_departments(self) -> List[Department]:
        """全部署を取得"""
        client = await self._get_client()

        url = f"{self.rest_url}/departments"
        params = {
            'select': '*',
            'order': 'name'
        }

        # マルチテナント環境の場合のみorganization_idフィルタを追加
        if not self.skip_organization_filter:
            params['organization_id'] = f'eq.{self.organization_id}'

        response = await client.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        departments = []
        for dept_data in data:
            department = Department(
                id=dept_data['id'],
                name=dept_data['name'],
                parent_id=dept_data.get('parent_id'),
                organization_id=dept_data.get('organization_id', self.organization_id),
                path=dept_data.get('path')
            )
            departments.append(department)

        logger.info(f"Fetched {len(departments)} departments")
        return departments

    async def get_department_by_id(self, department_id: str) -> Optional[Department]:
        """部署をIDで取得"""
        client = await self._get_client()

        url = f"{self.rest_url}/departments"
        params = {
            'select': '*',
            'id': f'eq.{department_id}',
        }

        # マルチテナント環境の場合のみorganization_idフィルタを追加
        if not self.skip_organization_filter:
            params['organization_id'] = f'eq.{self.organization_id}'

        response = await client.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        if data:
            dept_data = data[0]
            return Department(
                id=dept_data['id'],
                name=dept_data['name'],
                parent_id=dept_data.get('parent_id'),
                organization_id=dept_data.get('organization_id', self.organization_id),
                path=dept_data.get('path')
            )
        return None

    async def get_department_by_name(self, name: str) -> Optional[Department]:
        """部署を名前で取得"""
        client = await self._get_client()

        url = f"{self.rest_url}/departments"
        params = {
            'select': '*',
            'name': f'eq.{name}',
        }

        # マルチテナント環境の場合のみorganization_idフィルタを追加
        if not self.skip_organization_filter:
            params['organization_id'] = f'eq.{self.organization_id}'

        response = await client.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        if data:
            dept_data = data[0]
            return Department(
                id=dept_data['id'],
                name=dept_data['name'],
                parent_id=dept_data.get('parent_id'),
                organization_id=dept_data.get('organization_id', self.organization_id),
                path=dept_data.get('path')
            )
        return None

    # ================================================================
    # 役職取得
    # ================================================================

    async def get_all_roles(self) -> List[Role]:
        """全役職を取得"""
        client = await self._get_client()

        url = f"{self.rest_url}/roles"
        params = {
            'select': '*',
            'order': 'level'
        }

        # マルチテナント環境の場合のみorganization_idフィルタを追加
        if not self.skip_organization_filter:
            params['organization_id'] = f'eq.{self.organization_id}'

        response = await client.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        roles = []
        for role_data in data:
            role = Role(
                id=role_data['id'],
                name=role_data['name'],
                level=role_data.get('level', 1),
                organization_id=role_data.get('organization_id', self.organization_id)
            )
            roles.append(role)

        return roles

    # ================================================================
    # Googleアカウント関連
    # ================================================================

    async def get_all_google_accounts(self) -> Dict[str, Employee]:
        """
        Googleアカウントをキーとした社員マップを取得

        Returns:
            {google_account_email: Employee}
        """
        employees = await self.get_all_employees(with_google_account_only=True)
        return {
            emp.google_account_email.lower(): emp
            for emp in employees
            if emp.google_account_email
        }

    async def get_department_google_accounts(
        self,
        department_id: str,
        include_sub_departments: bool = False
    ) -> List[str]:
        """
        部署に所属する社員のGoogleアカウントを取得

        Args:
            department_id: 部署ID
            include_sub_departments: 子部署も含めるか

        Returns:
            Googleアカウントメールのリスト
        """
        employees = await self.get_employees_by_department(
            department_id,
            include_sub_departments
        )
        return [
            emp.google_account_email
            for emp in employees
            if emp.google_account_email
        ]

    async def get_accounts_by_role_level(
        self,
        min_level: int
    ) -> List[str]:
        """
        指定レベル以上の社員のGoogleアカウントを取得

        Args:
            min_level: 最小役職レベル

        Returns:
            Googleアカウントメールのリスト
        """
        employees = await self.get_employees_by_role_level(min_level=min_level)
        return [
            emp.google_account_email
            for emp in employees
            if emp.google_account_email
        ]

    # ================================================================
    # ユーティリティ
    # ================================================================

    def _parse_employee(self, emp_data: dict) -> Employee:
        """APIレスポンスをEmployeeに変換"""
        # 部署情報
        dept_data = emp_data.get('departments') or {}
        role_data = emp_data.get('roles') or {}

        # 兼務部署のパース
        additional_depts = []
        if emp_data.get('departments_json'):
            try:
                import json
                additional_depts = json.loads(emp_data['departments_json'])
            except (json.JSONDecodeError, TypeError):
                pass

        return Employee(
            id=emp_data['id'],
            name=emp_data.get('name', ''),
            department_id=emp_data.get('department_id'),
            department_name=dept_data.get('name') if isinstance(dept_data, dict) else None,
            role_id=emp_data.get('role_id'),
            role_name=role_data.get('name') if isinstance(role_data, dict) else None,
            role_level=role_data.get('level', 1) if isinstance(role_data, dict) else 1,
            google_account_email=emp_data.get('google_account_email'),
            chatwork_account_id=emp_data.get('chatwork_account_id'),
            email_work=emp_data.get('email_work'),
            is_active=emp_data.get('is_active', True),
            additional_departments=additional_depts
        )

    def _get_child_department_ids(
        self,
        departments: List[Department],
        parent_id: str
    ) -> set:
        """子部署IDを再帰的に取得"""
        child_ids = set()
        for dept in departments:
            if dept.parent_id == parent_id:
                child_ids.add(dept.id)
                # 再帰的に孫部署も取得
                child_ids.update(
                    self._get_child_department_ids(departments, dept.id)
                )
        return child_ids


# ================================================================
# エクスポート
# ================================================================

__all__ = [
    'OrgChartService',
    'Employee',
    'Department',
    'Role',
    'ROLE_LEVELS',
    'DEFAULT_ORGANIZATION_ID',
]
