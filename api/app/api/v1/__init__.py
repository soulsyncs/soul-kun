"""
API v1 Routes

Phase 3.5: 組織階層連携API
"""

from fastapi import APIRouter
from api.app.api.v1 import organizations, health

router = APIRouter(prefix="/v1")
router.include_router(health.router)
router.include_router(organizations.router)
