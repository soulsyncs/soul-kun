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
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
import time

from lib.config import get_settings
from lib.logging import get_logger
from lib.tenant import TenantContext, get_current_or_default_tenant
from app.api.v1 import router as v1_router
from app.limiter import limiter

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

# レート制限（slowapi）
# SlowAPIMiddleware が全ルートに default_limits=["100/minute"] を適用
# 認証系エンドポイントは auth_routes.py で @limiter.limit("10/minute") を追加
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

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
    """リクエストにテナントコンテキストを設定（JWT優先）"""
    tenant_id = None

    # JWT Bearer tokenからorg_idを取得（認証エラーはルートハンドラで処理）
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        try:
            from app.deps.auth import decode_jwt
            token = auth_header[7:]
            payload = decode_jwt(token)
            tenant_id = payload.get("org_id")
        except Exception as e:
            logger.debug(f"JWT decode in tenant middleware: {type(e).__name__}")

    # フォールバック: ヘッダー → デフォルト
    if not tenant_id:
        tenant_id = request.headers.get("X-Tenant-ID") or get_current_or_default_tenant()

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
