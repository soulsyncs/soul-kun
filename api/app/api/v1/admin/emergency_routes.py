"""
Admin Dashboard - Emergency Stop Endpoints

緊急停止の状態取得、有効化、解除。
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text

from lib.db import get_db_pool
from lib.logging import log_audit_event

from .deps import (
    DEFAULT_ORG_ID,
    logger,
    require_admin,
    UserContext,
)
from app.schemas.admin import (
    EmergencyStopStatusResponse,
    EmergencyStopActivateRequest,
    EmergencyStopActionResponse,
)

router = APIRouter()


@router.get(
    "/emergency-stop/status",
    response_model=EmergencyStopStatusResponse,
    summary="緊急停止の状態を取得",
)
async def get_emergency_stop_status(
    user: UserContext = Depends(require_admin),
):
    """緊急停止の現在の状態を返す。"""
    pool = get_db_pool()
    organization_id = user.organization_id or DEFAULT_ORG_ID

    try:
        with pool.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_organization_id', :org_id, true)"),
                {"org_id": organization_id},
            )
            result = conn.execute(
                text("""
                    SELECT is_active, activated_by, deactivated_by,
                           reason, activated_at, deactivated_at
                    FROM emergency_stop
                    WHERE organization_id = :org_id
                    LIMIT 1
                """),
                {"org_id": organization_id},
            )
            row = result.fetchone()

        if not row:
            return EmergencyStopStatusResponse(is_active=False)

        return EmergencyStopStatusResponse(
            is_active=bool(row[0]),
            activated_by=row[1],
            deactivated_by=row[2],
            reason=row[3],
            activated_at=row[4].isoformat() if row[4] else None,
            deactivated_at=row[5].isoformat() if row[5] else None,
        )

    except Exception as e:
        logger.exception("Emergency stop status error")
        raise HTTPException(status_code=500, detail="内部エラー")


@router.post(
    "/emergency-stop/activate",
    response_model=EmergencyStopActionResponse,
    summary="緊急停止を有効化",
)
async def activate_emergency_stop(
    body: EmergencyStopActivateRequest,
    user: UserContext = Depends(require_admin),
):
    """緊急停止を有効化する。全てのTool実行がブロックされる。"""
    pool = get_db_pool()
    organization_id = user.organization_id or DEFAULT_ORG_ID

    try:
        with pool.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_organization_id', :org_id, true)"),
                {"org_id": organization_id},
            )
            conn.execute(
                text("""
                    INSERT INTO emergency_stop (organization_id, is_active, activated_by, reason, activated_at, updated_at)
                    VALUES (:org_id, TRUE, :user_id, :reason, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    ON CONFLICT (organization_id)
                    DO UPDATE SET
                        is_active = TRUE,
                        activated_by = :user_id,
                        reason = :reason,
                        activated_at = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP
                """),
                {"org_id": organization_id, "user_id": user.user_id, "reason": body.reason},
            )
            conn.commit()

        log_audit_event(
            logger=logger, action="emergency_stop_activated",
            resource_type="system", resource_id="emergency_stop",
            user_id=user.user_id,
            details={"org_id": organization_id, "reason": body.reason},
        )
        logger.warning(
            "EMERGENCY STOP ACTIVATED via API: org=%s by=%s reason=%s",
            organization_id, user.user_id, body.reason,
        )

        return EmergencyStopActionResponse(
            message="緊急停止を有効化しました。全てのTool実行がブロックされます。",
            is_active=True,
        )

    except Exception as e:
        logger.exception("Emergency stop activate error")
        raise HTTPException(status_code=500, detail="内部エラー")


@router.post(
    "/emergency-stop/deactivate",
    response_model=EmergencyStopActionResponse,
    summary="緊急停止を解除",
)
async def deactivate_emergency_stop(
    user: UserContext = Depends(require_admin),
):
    """緊急停止を解除する。通常のTool実行が再開される。"""
    pool = get_db_pool()
    organization_id = user.organization_id or DEFAULT_ORG_ID

    try:
        with pool.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_organization_id', :org_id, true)"),
                {"org_id": organization_id},
            )
            conn.execute(
                text("""
                    UPDATE emergency_stop
                    SET is_active = FALSE,
                        deactivated_by = :user_id,
                        deactivated_at = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE organization_id = :org_id
                """),
                {"org_id": organization_id, "user_id": user.user_id},
            )
            conn.commit()

        log_audit_event(
            logger=logger, action="emergency_stop_deactivated",
            resource_type="system", resource_id="emergency_stop",
            user_id=user.user_id,
            details={"org_id": organization_id},
        )
        logger.warning(
            "EMERGENCY STOP DEACTIVATED via API: org=%s by=%s",
            organization_id, user.user_id,
        )

        return EmergencyStopActionResponse(
            message="緊急停止を解除しました。通常のTool実行が再開されます。",
            is_active=False,
        )

    except Exception as e:
        logger.exception("Emergency stop deactivate error")
        raise HTTPException(status_code=500, detail="内部エラー")
