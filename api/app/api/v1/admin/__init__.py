"""
Admin Dashboard API

管理ダッシュボード用APIエンドポイント。
認証、KPIサマリー、Brain分析、コスト管理、メンバー管理を提供。

セキュリティ:
    - 全エンドポイントにJWT認証必須
    - 権限レベル5以上（管理部/取締役/代表）のみアクセス可能
    - 全クエリにorganization_idフィルタ（鉄則#1）
    - SQLは全てパラメータ化（鉄則#9）
    - PII（個人情報）は集計値のみ返却、生メッセージは返さない
"""

from fastapi import APIRouter

from .auth_routes import router as auth_router
from .dashboard_routes import router as dashboard_router
from .brain_routes import router as brain_router
from .costs_routes import router as costs_router
from .members_routes import router as members_router
from .departments_routes import router as departments_router
from .member_detail_routes import router as member_detail_router
from .goals_routes import router as goals_router
from .wellness_routes import router as wellness_router
from .tasks_routes import router as tasks_router
from .insights_routes import router as insights_router
from .meetings_routes import router as meetings_router
from .proactive_routes import router as proactive_router
from .teachings_routes import router as teachings_router
from .system_routes import router as system_router
from .calendar_routes import router as calendar_router
from .drive_routes import router as drive_router
from .emergency_routes import router as emergency_router
from .zoom_routes import router as zoom_router

router = APIRouter(prefix="/admin", tags=["admin"])

# Include all sub-routers (no prefix/tags — routes already have full paths)
router.include_router(auth_router)
router.include_router(dashboard_router)
router.include_router(brain_router)
router.include_router(costs_router)
router.include_router(members_router)
router.include_router(departments_router)
router.include_router(member_detail_router)
router.include_router(goals_router)
router.include_router(wellness_router)
router.include_router(tasks_router)
router.include_router(insights_router)
router.include_router(meetings_router)
router.include_router(proactive_router)
router.include_router(teachings_router)
router.include_router(system_router)
router.include_router(calendar_router)
router.include_router(drive_router)
router.include_router(emergency_router)
router.include_router(zoom_router)
