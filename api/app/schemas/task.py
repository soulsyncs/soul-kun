"""
Task Schemas

Phase 1-B: 期限超過タスク検索API用Pydanticスキーマ
"""

from datetime import date, datetime
from typing import Optional, List
from pydantic import BaseModel, Field


# =============================================================================
# レスポンススキーマ
# =============================================================================


class TaskAssigneeInfo(BaseModel):
    """タスク担当者情報"""

    account_id: Optional[int] = Field(None, description="ChatWork account_id")
    name: Optional[str] = Field(None, description="担当者名")


class TaskRequesterInfo(BaseModel):
    """タスク依頼者情報"""

    account_id: Optional[int] = Field(None, description="ChatWork account_id")
    name: Optional[str] = Field(None, description="依頼者名")


class OverdueTaskResponse(BaseModel):
    """期限超過タスクレスポンス"""

    task_id: int = Field(..., description="ChatWork task_id")
    room_id: int = Field(..., description="ChatWork room_id")
    room_name: Optional[str] = Field(None, description="ルーム名")
    body: str = Field(..., description="タスク本文")
    summary: Optional[str] = Field(None, description="AI要約（40文字以内）")
    limit_date: date = Field(..., description="期限日")
    limit_time: Optional[datetime] = Field(None, description="期限日時（タイムスタンプから変換）")
    days_overdue: int = Field(..., ge=1, description="超過日数")
    severity: str = Field(..., description="重度（severe/moderate/mild）")
    severity_label: str = Field(..., description="重度ラベル（🔴重度/🟠中度/🟡軽度）")
    assigned_to: TaskAssigneeInfo = Field(..., description="担当者情報")
    assigned_by: TaskRequesterInfo = Field(..., description="依頼者情報")
    department_id: Optional[str] = Field(None, description="部署ID（Phase 3.5）")
    status: str = Field(..., description="ステータス（open/done）")
    created_at: Optional[datetime] = Field(None, description="作成日時")

    class Config:
        json_schema_extra = {
            "example": {
                "task_id": 12345678,
                "room_id": 405315911,
                "room_name": "管理部",
                "body": "月次レポートを作成する",
                "summary": "月次レポート作成",
                "limit_date": "2026-01-15",
                "limit_time": "2026-01-15T23:59:59+09:00",
                "days_overdue": 5,
                "severity": "moderate",
                "severity_label": "🟠中度遅延",
                "assigned_to": {
                    "account_id": 1234567,
                    "name": "田中太郎"
                },
                "assigned_by": {
                    "account_id": 1728974,
                    "name": "菊地雅克"
                },
                "department_id": "dept_001",
                "status": "open",
                "created_at": "2026-01-10T10:00:00+09:00"
            }
        }


class OverdueSummary(BaseModel):
    """期限超過サマリー"""

    total: int = Field(..., description="期限超過タスク総数")
    severe_count: int = Field(..., description="🔴重度（7日以上）の件数")
    moderate_count: int = Field(..., description="🟠中度（3-6日）の件数")
    mild_count: int = Field(..., description="🟡軽度（1-2日）の件数")


class OverdueTaskListResponse(BaseModel):
    """期限超過タスク一覧レスポンス"""

    status: str = Field("success", description="ステータス")
    summary: OverdueSummary = Field(..., description="サマリー")
    tasks: List[OverdueTaskResponse] = Field(..., description="期限超過タスク一覧")
    checked_at: datetime = Field(..., description="確認日時")

    class Config:
        json_schema_extra = {
            "example": {
                "status": "success",
                "summary": {
                    "total": 15,
                    "severe_count": 3,
                    "moderate_count": 7,
                    "mild_count": 5
                },
                "tasks": [
                    {
                        "task_id": 12345678,
                        "room_id": 405315911,
                        "room_name": "管理部",
                        "body": "月次レポートを作成する",
                        "summary": "月次レポート作成",
                        "limit_date": "2026-01-15",
                        "days_overdue": 5,
                        "severity": "moderate",
                        "severity_label": "🟠中度遅延",
                        "assigned_to": {"account_id": 1234567, "name": "田中太郎"},
                        "assigned_by": {"account_id": 1728974, "name": "菊地雅克"},
                        "status": "open",
                        "created_at": "2026-01-10T10:00:00+09:00"
                    }
                ],
                "checked_at": "2026-01-20T08:30:00+09:00"
            }
        }


class TaskErrorResponse(BaseModel):
    """タスクAPIエラーレスポンス"""

    status: str = Field("failed", description="ステータス")
    error_code: str = Field(..., description="エラーコード")
    error_message: str = Field(..., description="エラーメッセージ")
