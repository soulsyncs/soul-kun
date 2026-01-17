"""
Soul-kun API - FastAPI Entry Point

Phase 3.5: 組織階層連携API

使用方法（ローカル開発）:
    uvicorn api.main:app --reload --port 8080

使用方法（Cloud Run）:
    gunicorn api.main:app -k uvicorn.workers.UvicornWorker
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import time

from lib.config import get_settings
from lib.logging import get_logger
from lib.tenant import TenantContext, get_current_or_default_tenant
from api.app.api.v1 import router as v1_router

logger = get_logger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """アプリケーションのライフサイクル管理"""
    logger.info("Soul-kun API starting up...")
    yield
    logger.info("Soul-kun API shutting down...")


app = FastAPI(
    title="Soul-kun API",
    description="ソウル君 AI バックオフィスシステム API",
    version="3.5.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
)

# CORS設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_tenant_context(request: Request, call_next):
    """リクエストにテナントコンテキストを設定"""
    # X-Tenant-ID ヘッダーからテナントIDを取得
    tenant_id = request.headers.get("X-Tenant-ID")
    if not tenant_id:
        tenant_id = get_current_or_default_tenant()

    with TenantContext(tenant_id):
        response = await call_next(request)

    return response


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """リクエストログ"""
    start_time = time.time()

    response = await call_next(request)

    duration_ms = (time.time() - start_time) * 1000
    logger.info(
        f"{request.method} {request.url.path} -> {response.status_code}",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=round(duration_ms, 2),
    )

    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """グローバル例外ハンドラー"""
    logger.error(
        f"Unhandled exception: {exc}",
        exc_info=True,
        path=request.url.path,
    )
    return JSONResponse(
        status_code=500,
        content={
            "status": "error",
            "error_code": "INTERNAL_ERROR",
            "error_message": "内部エラーが発生しました",
        },
    )


# API v1 ルーターを登録
app.include_router(v1_router, prefix="/api")


@app.get("/")
async def root():
    """ルートエンドポイント"""
    return {
        "name": "Soul-kun API",
        "version": "3.5.0",
        "status": "running",
    }
