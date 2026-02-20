"""
Admin Dashboard - Zoom連携設定 Endpoints

Zoom議事録の送信先設定を一元管理する。
「この会議名パターン → このChatWorkルームへ送信」という設定をCRUDで管理。

エンドポイント:
    GET  /admin/zoom/configs       - 設定一覧
    POST /admin/zoom/configs       - 設定追加
    PUT  /admin/zoom/configs/{id}  - 設定更新
    DELETE /admin/zoom/configs/{id} - 設定削除

セキュリティ:
    - Level 5以上（管理部/取締役/代表）のみアクセス可。
      書き込み（POST/PUT/DELETE）も同レベルで許可する。
      理由: Zoom送信先はインフラ設定ではなく運用設定のため、
      Level 5（管理部）が業務上変更権限を持つことが自然な運用フロー。
    - 全クエリにorganization_idフィルタ（鉄則#1）
    - SQLは全てパラメータ化（鉄則#9）
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path, status
from pydantic import BaseModel, Field
from sqlalchemy import text

from lib.db import get_db_pool

from .deps import (
    DEFAULT_ORG_ID,
    logger,
    require_admin,
    UserContext,
)

router = APIRouter()


# ===== Request/Response schemas =====


class ZoomConfigCreate(BaseModel):
    meeting_name_pattern: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="会議名に含まれるキーワード（例: '朝会'）",
    )
    chatwork_room_id: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="送信先ChatWorkルームID",
    )
    room_name: Optional[str] = Field(
        None,
        max_length=255,
        description="管理用ラベル（例: '営業チームルーム'）",
    )
    is_active: bool = Field(True, description="有効/無効")


class ZoomConfigUpdate(BaseModel):
    meeting_name_pattern: Optional[str] = Field(
        None, min_length=1, max_length=255
    )
    chatwork_room_id: Optional[str] = Field(
        None, min_length=1, max_length=50
    )
    room_name: Optional[str] = Field(None, max_length=255)
    is_active: Optional[bool] = None


# ===== Endpoints =====


@router.get(
    "/zoom/configs",
    summary="Zoom連携設定一覧取得",
    description="Zoom議事録の送信先設定を一覧で取得（Level 5+）",
)
async def get_zoom_configs(
    user: UserContext = Depends(require_admin),
):
    organization_id = user.organization_id or DEFAULT_ORG_ID
    try:
        pool = get_db_pool()
        with pool.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT id, meeting_name_pattern, chatwork_room_id,
                           room_name, is_active, created_at, updated_at
                    FROM zoom_meeting_configs
                    WHERE organization_id = :org_id
                    ORDER BY created_at DESC
                """),
                {"org_id": organization_id},
            )
            rows = result.mappings().fetchall()

        return {
            "status": "ok",
            "configs": [
                {
                    "id": str(row["id"]),
                    "meeting_name_pattern": row["meeting_name_pattern"],
                    "chatwork_room_id": row["chatwork_room_id"],
                    "room_name": row["room_name"],
                    "is_active": row["is_active"],
                    "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                    "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
                }
                for row in rows
            ],
            "total": len(rows),
        }
    except Exception as e:
        logger.error("zoom configs fetch failed: %s", type(e).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="設定の取得に失敗しました",
        )


@router.post(
    "/zoom/configs",
    summary="Zoom連携設定追加",
    description="Zoom議事録の送信先設定を追加（Level 5+）",
    status_code=status.HTTP_201_CREATED,
)
async def create_zoom_config(
    body: ZoomConfigCreate,
    user: UserContext = Depends(require_admin),
):
    organization_id = user.organization_id or DEFAULT_ORG_ID
    try:
        pool = get_db_pool()
        with pool.connect() as conn:
            # 重複チェック
            existing = conn.execute(
                text("""
                    SELECT id FROM zoom_meeting_configs
                    WHERE organization_id = :org_id
                      AND meeting_name_pattern = :pattern
                """),
                {"org_id": organization_id, "pattern": body.meeting_name_pattern},
            ).fetchone()
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"「{body.meeting_name_pattern}」は既に登録されています",
                )

            row = conn.execute(
                text("""
                    INSERT INTO zoom_meeting_configs
                        (organization_id, meeting_name_pattern, chatwork_room_id, room_name, is_active)
                    VALUES (:org_id, :pattern, :room_id, :room_name, :is_active)
                    RETURNING id, meeting_name_pattern, chatwork_room_id, room_name, is_active,
                              created_at, updated_at
                """),
                {
                    "org_id": organization_id,
                    "pattern": body.meeting_name_pattern,
                    "room_id": body.chatwork_room_id,
                    "room_name": body.room_name,
                    "is_active": body.is_active,
                },
            ).mappings().fetchone()
            conn.commit()

        logger.info("zoom config created: org=%s", organization_id[:8])
        return {
            "status": "created",
            "config": {
                "id": str(row["id"]),
                "meeting_name_pattern": row["meeting_name_pattern"],
                "chatwork_room_id": row["chatwork_room_id"],
                "room_name": row["room_name"],
                "is_active": row["is_active"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("zoom config create failed: %s", type(e).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="設定の追加に失敗しました",
        )


@router.put(
    "/zoom/configs/{config_id}",
    summary="Zoom連携設定更新",
    description="Zoom議事録の送信先設定を更新（Level 5+）",
)
async def update_zoom_config(
    config_id: str = Path(..., description="設定ID"),
    body: ZoomConfigUpdate = ...,
    user: UserContext = Depends(require_admin),
):
    organization_id = user.organization_id or DEFAULT_ORG_ID
    try:
        pool = get_db_pool()
        with pool.connect() as conn:
            # 存在確認（org_id フィルタで他テナントを保護）
            existing = conn.execute(
                text("""
                    SELECT id FROM zoom_meeting_configs
                    WHERE id = :config_id AND organization_id = :org_id
                """),
                {"config_id": config_id, "org_id": organization_id},
            ).fetchone()
            if not existing:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="設定が見つかりません",
                )

            # 更新フィールドを動的に構築
            # SAFE: set_clauses はハードコードされたカラム名定数のみ。
            # ユーザー入力は全て params のバインド変数経由で渡す（鉄則#9準拠）。
            set_clauses = ["updated_at = NOW()"]
            params: dict = {"config_id": config_id, "org_id": organization_id}

            if body.meeting_name_pattern is not None:
                set_clauses.append("meeting_name_pattern = :pattern")
                params["pattern"] = body.meeting_name_pattern
            if body.chatwork_room_id is not None:
                set_clauses.append("chatwork_room_id = :room_id")
                params["room_id"] = body.chatwork_room_id
            if body.room_name is not None:
                set_clauses.append("room_name = :room_name")
                params["room_name"] = body.room_name
            if body.is_active is not None:
                set_clauses.append("is_active = :is_active")
                params["is_active"] = body.is_active

            row = conn.execute(
                text(f"""
                    UPDATE zoom_meeting_configs
                    SET {', '.join(set_clauses)}
                    WHERE id = :config_id AND organization_id = :org_id
                    RETURNING id, meeting_name_pattern, chatwork_room_id,
                              room_name, is_active, updated_at
                """),
                params,
            ).mappings().fetchone()
            conn.commit()

        logger.info("zoom config updated: id=%s", config_id[:8])
        return {
            "status": "updated",
            "config": {
                "id": str(row["id"]),
                "meeting_name_pattern": row["meeting_name_pattern"],
                "chatwork_room_id": row["chatwork_room_id"],
                "room_name": row["room_name"],
                "is_active": row["is_active"],
                "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("zoom config update failed: %s", type(e).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="設定の更新に失敗しました",
        )


@router.delete(
    "/zoom/configs/{config_id}",
    summary="Zoom連携設定削除",
    description="Zoom議事録の送信先設定を削除（Level 5+）",
)
async def delete_zoom_config(
    config_id: str = Path(..., description="設定ID"),
    user: UserContext = Depends(require_admin),
):
    organization_id = user.organization_id or DEFAULT_ORG_ID
    try:
        pool = get_db_pool()
        with pool.connect() as conn:
            result = conn.execute(
                text("""
                    DELETE FROM zoom_meeting_configs
                    WHERE id = :config_id AND organization_id = :org_id
                """),
                {"config_id": config_id, "org_id": organization_id},
            )
            conn.commit()

            if result.rowcount == 0:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="設定が見つかりません",
                )

        logger.info("zoom config deleted: id=%s", config_id[:8])
        return {"status": "deleted"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("zoom config delete failed: %s", type(e).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="設定の削除に失敗しました",
        )
