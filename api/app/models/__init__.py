"""
SQLAlchemy Models for Soul-kun API

Phase 3.5: 組織階層連携用モデル
Phase 2.5: 目標達成支援用モデル
"""

from app.models.organization import (
    Organization,
    Department,
    UserDepartment,
    DepartmentAccessScope,
    DepartmentHierarchy,
    OrgChartSyncLog,
)
from app.models.user import User, Role
from app.models.goal import (
    Goal,
    GoalProgress,
    GoalReminder,
    AuditLog,
)

__all__ = [
    # Phase 3.5: 組織階層
    "Organization",
    "Department",
    "UserDepartment",
    "DepartmentAccessScope",
    "DepartmentHierarchy",
    "OrgChartSyncLog",
    "User",
    "Role",
    # Phase 2.5: 目標達成支援
    "Goal",
    "GoalProgress",
    "GoalReminder",
    "AuditLog",
]
