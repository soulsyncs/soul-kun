"""
API v1 Routes

Phase 1-B: タスク自動検知API
Phase 3: ナレッジ検索API
Phase 3.5: 組織階層連携API
Admin Dashboard API
"""

from fastapi import APIRouter
from app.api.v1 import organizations, health, knowledge, tasks, admin

router = APIRouter(prefix="/v1")
router.include_router(health.router)
router.include_router(organizations.router)
router.include_router(knowledge.router)
router.include_router(tasks.router)
router.include_router(admin.router)
