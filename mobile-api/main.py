"""
ソウルくん Mobile API — iPhoneアプリ / Web UI 用 REST API

ChatWork以外の「入口」を提供するFastAPIサーバー。
JWT認証 + WebSocket リアルタイムチャット + 音声対話対応。

【設計方針】
- 全リクエストは Brain 経由（bypass禁止: CLAUDE.md 鉄則1）
- organization_id フィルタ必須（鉄則#1）
- PII はレスポンスに含めない（鉄則#8）
- SQL はパラメータ化（鉄則#9）

【エンドポイント】
  POST /api/v1/auth/login          — ログイン（JWT発行）
  POST /api/v1/auth/refresh        — トークンリフレッシュ
  POST /api/v1/chat                — メッセージ送信（Brain経由）
  GET  /api/v1/tasks               — タスク一覧
  GET  /api/v1/goals               — 目標一覧
  GET  /api/v1/persons             — メンバー一覧（PII除外）
  WS   /api/v1/ws                  — WebSocket リアルタイムチャット
  POST /api/v1/voice/stt           — 音声→テキスト（Whisper）
  POST /api/v1/voice/tts           — テキスト→音声（Google TTS）
  POST /api/v1/notifications/register — プッシュ通知登録

Author: Claude Opus 4.6
Created: 2026-02-14
"""

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

# lib/ を import path に追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "chatwork-webhook"))

logger = logging.getLogger(__name__)

# =============================================================================
# FastAPI アプリケーション
# =============================================================================

app = FastAPI(
    title="ソウルくん Mobile API",
    description="soul-kun REST API for mobile apps and web clients",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# 認証
# =============================================================================

JWT_SECRET = os.getenv("JWT_SECRET", "")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24
security = HTTPBearer()


def _create_token(user_id: str, org_id: str) -> str:
    """JWT トークン生成"""
    import jwt

    payload = {
        "sub": user_id,
        "org_id": org_id,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRATION_HOURS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _verify_token(token: str) -> Dict[str, Any]:
    """JWT トークン検証"""
    import jwt

    if not JWT_SECRET:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="JWT_SECRET not configured",
        )
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> Dict[str, Any]:
    """現在のユーザーを取得（JWT認証）"""
    return _verify_token(credentials.credentials)


# =============================================================================
# リクエスト / レスポンスモデル
# =============================================================================


class LoginRequest(BaseModel):
    """ログインリクエスト"""
    email: str
    password: str


class LoginResponse(BaseModel):
    """ログインレスポンス"""
    access_token: str
    token_type: str = "bearer"
    expires_in: int = JWT_EXPIRATION_HOURS * 3600
    user: Dict[str, Any]


class ChatRequest(BaseModel):
    """チャットリクエスト"""
    message: str = Field(..., min_length=1, max_length=10000)
    context: Optional[Dict[str, Any]] = None


class ChatResponse(BaseModel):
    """チャットレスポンス"""
    response: str
    action: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class TaskResponse(BaseModel):
    """タスクレスポンス"""
    id: int
    title: str
    status: str
    assigned_to: Optional[str] = None
    due_date: Optional[str] = None


class GoalResponse(BaseModel):
    """目標レスポンス"""
    id: int
    title: str
    description: Optional[str] = None
    status: str
    progress_percentage: Optional[float] = None


class PersonResponse(BaseModel):
    """メンバーレスポンス（PII除外）"""
    id: int
    display_name: str
    department: Optional[str] = None
    position: Optional[str] = None


class NotificationRegisterRequest(BaseModel):
    """プッシュ通知登録"""
    device_token: str
    platform: str = Field(..., pattern="^(ios|android)$")


class VoiceSTTResponse(BaseModel):
    """音声認識結果"""
    text: str
    confidence: float
    language: str = "ja"


class VoiceTTSRequest(BaseModel):
    """音声合成リクエスト"""
    text: str = Field(..., min_length=1, max_length=5000)
    voice: str = "ja-JP-Neural2-B"
    speed: float = Field(default=1.0, ge=0.5, le=2.0)


# =============================================================================
# DB接続
# =============================================================================

_db_pool = None


def _get_pool():
    """DB接続プール取得"""
    global _db_pool
    if _db_pool is None:
        from lib.db import get_db_pool
        _db_pool = get_db_pool()
    return _db_pool


# =============================================================================
# 認証エンドポイント
# =============================================================================


@app.post("/api/v1/auth/login", response_model=LoginResponse)
async def login(req: LoginRequest):
    """ログイン — DB認証 + JWT発行"""
    pool = _get_pool()
    conn = pool.connect()
    try:
        # パスワードはハッシュ化して照合（bcrypt）
        result = conn.execute(
            """SELECT id, display_name, email, organization_id, password_hash
               FROM users
               WHERE email = %s AND organization_id IS NOT NULL
               LIMIT 1""",
            [req.email],
        )
        row = result.fetchone()
        if not row:
            raise HTTPException(status_code=401, detail="Invalid credentials")

        import bcrypt
        if not bcrypt.checkpw(
            req.password.encode("utf-8"),
            row["password_hash"].encode("utf-8"),
        ):
            raise HTTPException(status_code=401, detail="Invalid credentials")

        token = _create_token(str(row["id"]), str(row["organization_id"]))

        return LoginResponse(
            access_token=token,
            user={
                "id": str(row["id"]),
                "display_name": row["display_name"],
                "email": row["email"],
            },
        )
    finally:
        conn.close()


@app.post("/api/v1/auth/refresh", response_model=LoginResponse)
async def refresh_token(user: Dict = Depends(get_current_user)):
    """トークンリフレッシュ"""
    new_token = _create_token(user["sub"], user["org_id"])
    return LoginResponse(
        access_token=new_token,
        user={"id": user["sub"]},
    )


# =============================================================================
# チャットエンドポイント
# =============================================================================


@app.post("/api/v1/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, user: Dict = Depends(get_current_user)):
    """
    メッセージ送信 — Brain経由で処理

    全リクエストはBrainを通る（鉄則1: bypass禁止）
    """
    try:
        pool = _get_pool()

        from handlers.registry import SYSTEM_CAPABILITIES, build_handlers
        from lib.brain.integration import BrainIntegration
        from lib.brain.llm import get_ai_response_raw

        handlers = build_handlers()
        integration = BrainIntegration(
            pool=pool,
            org_id=user["org_id"],
            handlers=handlers,
            capabilities=SYSTEM_CAPABILITIES,
            get_ai_response_func=get_ai_response_raw,
        )

        result = await integration.process_message(
            message=req.message,
            room_id=f"mobile-{user['sub']}",
            account_id=user["sub"],
            sender_name=user.get("display_name", "Mobile User"),
        )

        response_text = (
            result.to_chatwork_message()
            if hasattr(result, "to_chatwork_message")
            else str(result)
        )

        return ChatResponse(
            response=response_text,
            action=getattr(result, "action", None),
            metadata=getattr(result, "metadata", None),
        )

    except Exception as e:
        logger.exception("Chat processing failed")
        raise HTTPException(status_code=500, detail="処理中にエラーが発生しました")


# =============================================================================
# データ取得エンドポイント
# =============================================================================


@app.get("/api/v1/tasks", response_model=List[TaskResponse])
async def get_tasks(
    status_filter: Optional[str] = None,
    limit: int = 50,
    user: Dict = Depends(get_current_user),
):
    """タスク一覧（organization_idフィルタ付き）"""
    pool = _get_pool()
    conn = pool.connect()
    try:
        conn.execute(
            "SELECT set_config('app.current_organization_id', %s, true)",
            [user["org_id"]],
        )

        query = """
            SELECT id, title, status, assigned_to,
                   to_char(due_date, 'YYYY-MM-DD') as due_date
            FROM tasks
            WHERE organization_id = %s
        """
        params: list = [user["org_id"]]

        if status_filter:
            query += " AND status = %s"
            params.append(status_filter)

        query += " ORDER BY due_date ASC NULLS LAST LIMIT %s"
        params.append(min(limit, 100))  # 鉄則#5: 最大100件

        result = conn.execute(query, params)
        return [TaskResponse(**dict(r)) for r in result]
    finally:
        conn.close()


@app.get("/api/v1/goals", response_model=List[GoalResponse])
async def get_goals(user: Dict = Depends(get_current_user)):
    """目標一覧"""
    pool = _get_pool()
    conn = pool.connect()
    try:
        conn.execute(
            "SELECT set_config('app.current_organization_id', %s, true)",
            [user["org_id"]],
        )
        result = conn.execute(
            """SELECT id, title, description, status, progress_percentage
               FROM goals
               WHERE organization_id = %s AND status = 'active'
               ORDER BY created_at DESC
               LIMIT 50""",
            [user["org_id"]],
        )
        return [GoalResponse(**dict(r)) for r in result]
    finally:
        conn.close()


@app.get("/api/v1/persons", response_model=List[PersonResponse])
async def get_persons(user: Dict = Depends(get_current_user)):
    """メンバー一覧（PII除外: メール・電話番号は返さない）"""
    pool = _get_pool()
    conn = pool.connect()
    try:
        conn.execute(
            "SELECT set_config('app.current_organization_id', %s, true)",
            [user["org_id"]],
        )
        result = conn.execute(
            """SELECT id, display_name, department, position
               FROM persons
               WHERE organization_id = %s
               ORDER BY display_name
               LIMIT 200""",
            [user["org_id"]],
        )
        return [PersonResponse(**dict(r)) for r in result]
    finally:
        conn.close()


# =============================================================================
# WebSocket — リアルタイムチャット
# =============================================================================


class ConnectionManager:
    """WebSocket接続管理"""

    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, user_id: str):
        await websocket.accept()
        self.active_connections[user_id] = websocket

    def disconnect(self, user_id: str):
        self.active_connections.pop(user_id, None)

    async def send_message(self, user_id: str, message: Dict[str, Any]):
        ws = self.active_connections.get(user_id)
        if ws:
            await ws.send_json(message)


ws_manager = ConnectionManager()


@app.websocket("/api/v1/ws")
async def websocket_chat(websocket: WebSocket):
    """
    WebSocket リアルタイムチャット

    接続フロー:
    1. クライアントが token を最初のメッセージで送信
    2. サーバーが認証してセッション開始
    3. 以降はメッセージの送受信
    """
    await websocket.accept()

    # 最初のメッセージで認証
    try:
        auth_msg = await asyncio.wait_for(websocket.receive_json(), timeout=10)
        token = auth_msg.get("token", "")
        user = _verify_token(token)
        user_id = user["sub"]
    except Exception:
        await websocket.send_json({"error": "Authentication failed"})
        await websocket.close(code=4001)
        return

    ws_manager.active_connections[user_id] = websocket
    await websocket.send_json({"type": "connected", "user_id": user_id})

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type", "chat")

            if msg_type == "chat":
                message = data.get("message", "")
                if not message:
                    continue

                # Brain経由で処理
                await websocket.send_json({"type": "thinking", "status": "processing"})

                try:
                    pool = _get_pool()
                    from handlers.registry import SYSTEM_CAPABILITIES, build_handlers
                    from lib.brain.integration import BrainIntegration
                    from lib.brain.llm import get_ai_response_raw

                    handlers = build_handlers()
                    integration = BrainIntegration(
                        pool=pool,
                        org_id=user["org_id"],
                        handlers=handlers,
                        capabilities=SYSTEM_CAPABILITIES,
                        get_ai_response_func=get_ai_response_raw,
                    )

                    result = await integration.process_message(
                        message=message,
                        room_id=f"ws-{user_id}",
                        account_id=user_id,
                        sender_name="Mobile User",
                    )

                    response_text = (
                        result.to_chatwork_message()
                        if hasattr(result, "to_chatwork_message")
                        else str(result)
                    )

                    await websocket.send_json({
                        "type": "response",
                        "message": response_text,
                        "action": getattr(result, "action", None),
                    })

                except Exception as e:
                    logger.exception("WebSocket chat error")
                    await websocket.send_json({
                        "type": "error",
                        "message": "処理中にエラーが発生しました",
                    })

            elif msg_type == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        ws_manager.disconnect(user_id)


# =============================================================================
# 音声エンドポイント
# =============================================================================


@app.post("/api/v1/voice/stt", response_model=VoiceSTTResponse)
async def speech_to_text(user: Dict = Depends(get_current_user)):
    """
    音声→テキスト変換（Whisper API）

    クライアントからの音声データ（WAV/MP3）を受け取り、
    OpenAI Whisper APIでテキストに変換する。
    """
    from fastapi import UploadFile, File

    # Note: FastAPIのUploadFileは関数引数で受け取る必要がある
    # ここではエンドポイントの型定義のみ。実際の実装はvoice.pyに委譲
    raise HTTPException(
        status_code=501,
        detail="Voice STT endpoint — see voice.py for implementation",
    )


@app.post("/api/v1/voice/tts")
async def text_to_speech(
    req: VoiceTTSRequest,
    user: Dict = Depends(get_current_user),
):
    """
    テキスト→音声変換（Google Cloud TTS）

    テキストを日本語音声に変換して返す。
    """
    raise HTTPException(
        status_code=501,
        detail="Voice TTS endpoint — see voice.py for implementation",
    )


# =============================================================================
# プッシュ通知
# =============================================================================


@app.post("/api/v1/notifications/register")
async def register_notification(
    req: NotificationRegisterRequest,
    user: Dict = Depends(get_current_user),
):
    """プッシュ通知デバイス登録"""
    pool = _get_pool()
    conn = pool.connect()
    try:
        conn.execute(
            """INSERT INTO push_notification_devices
               (user_id, device_token, platform, organization_id, registered_at)
               VALUES (%s, %s, %s, %s, NOW())
               ON CONFLICT (user_id, device_token)
               DO UPDATE SET platform = EXCLUDED.platform, registered_at = NOW()""",
            [user["sub"], req.device_token, req.platform, user["org_id"]],
        )
        conn.commit()
        return {"status": "registered"}
    finally:
        conn.close()


# =============================================================================
# ヘルスチェック
# =============================================================================


@app.get("/health")
async def health():
    """ヘルスチェック"""
    return {"status": "ok", "service": "soulkun-mobile-api", "version": "1.0.0"}


# =============================================================================
# メイン
# =============================================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8081")),
        reload=os.getenv("ENVIRONMENT") != "production",
    )
