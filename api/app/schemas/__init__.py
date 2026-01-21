"""
Pydantic Schemas for Soul-kun API

Phase 1-B: タスク自動検知用スキーマ
Phase 3.5: 組織階層連携用スキーマ
"""

from app.schemas.organization import (
    DepartmentInput,
    RoleInput,
    EmployeeInput,
    SyncOptions,
    OrgChartSyncRequest,
    OrgChartSyncResponse,
    SyncSummary,
    DepartmentResponse,
    DepartmentListResponse,
)

from app.schemas.task import (
    OverdueTaskResponse,
    OverdueTaskListResponse,
    OverdueSummary,
    TaskAssigneeInfo,
    TaskRequesterInfo,
    TaskErrorResponse,
)

__all__ = [
    # Organization schemas
    "DepartmentInput",
    "RoleInput",
    "EmployeeInput",
    "SyncOptions",
    "OrgChartSyncRequest",
    "OrgChartSyncResponse",
    "SyncSummary",
    "DepartmentResponse",
    "DepartmentListResponse",
    # Task schemas
    "OverdueTaskResponse",
    "OverdueTaskListResponse",
    "OverdueSummary",
    "TaskAssigneeInfo",
    "TaskRequesterInfo",
    "TaskErrorResponse",
]
