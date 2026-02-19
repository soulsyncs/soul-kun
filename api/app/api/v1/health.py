"""
Health Check Endpoint

ヘルスチェック用のエンドポイント
"""

from fastapi import APIRouter
from sqlalchemy import text

from lib.db import get_db_pool
from app.limiter import limiter

router = APIRouter(tags=["health"])


@router.get("/health")
@limiter.exempt
async def health_check():
    """
    ヘルスチェック

    Returns:
        status: サービス状態
        db: データベース接続状態
    """
    db_status = "unknown"

    try:
        pool = get_db_pool()
        with pool.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_status = "healthy"
    except Exception as e:
        db_status = f"unhealthy: {str(e)}"

    return {
        "status": "healthy",
        "db": db_status,
        "version": "3.5.0",
    }
