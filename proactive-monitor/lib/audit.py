"""
Soul-kun 監査ログモジュール

★★★ v10.14.1: 新規作成 ★★★

このモジュールは以下を提供します:
- log_audit: 監査ログをDBに記録
- AuditAction: 監査アクションの定義
- AuditResourceType: リソースタイプの定義

使用例（Flask/Cloud Functions）:
    from lib.audit import log_audit, AuditAction, AuditResourceType

    log_audit(
        conn=conn,
        cursor=cursor,
        organization_id="5f98365f-e7c5-4f48-9918-7fe9aabae5df",
        action=AuditAction.UPDATE,
        resource_type=AuditResourceType.CHATWORK_TASK,
        resource_id="task_123",
        details={"old_summary": "...", "new_summary": "..."}
    )

設計原則:
- 10の鉄則 #3: 監査ログを全confidential以上の操作で記録
- Phase 4 BPaaS対応: organization_id必須
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from enum import Enum

logger = logging.getLogger(__name__)


class AuditAction(str, Enum):
    """監査アクションの定義"""
    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"
    EXPORT = "export"
    REGENERATE = "regenerate"  # 要約再生成など
    SYNC = "sync"  # 同期処理


class AuditResourceType(str, Enum):
    """リソースタイプの定義"""
    DOCUMENT = "document"
    KNOWLEDGE = "knowledge"
    USER = "user"
    DEPARTMENT = "department"
    TASK = "task"
    CHATWORK_TASK = "chatwork_task"  # ChatWorkタスク
    MEETING = "meeting"
    ORGANIZATION = "organization"
    SUMMARY = "summary"  # 要約
    DRIVE_PERMISSION = "drive_permission"  # Google Drive権限（v10.28.0追加）
    DRIVE_FOLDER = "drive_folder"  # Google Driveフォルダ（v10.28.0追加）


def log_audit(
    conn,
    cursor,
    organization_id: str,
    action: str,
    resource_type: str,
    resource_id: Optional[str] = None,
    resource_name: Optional[str] = None,
    user_id: Optional[str] = None,
    department_id: Optional[str] = None,
    classification: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> bool:
    """
    監査ログをDBに記録する

    ★★★ v10.14.1: 新規追加 ★★★

    この関数は設計書「10の鉄則 #3」に基づき、
    全confidential以上の操作を記録します。

    Args:
        conn: DB接続
        cursor: DBカーソル
        organization_id: テナントID（必須）
        action: アクション（create, read, update, delete, regenerate等）
        resource_type: リソースタイプ（document, task, chatwork_task等）
        resource_id: リソースID
        resource_name: リソース名（オプション）
        user_id: 実行ユーザーID
        department_id: 部署ID
        classification: 機密区分（public, internal, confidential, restricted）
        details: 詳細情報（JSON）
        ip_address: IPアドレス
        user_agent: ユーザーエージェント

    Returns:
        True: 成功, False: 失敗

    Example:
        log_audit(
            conn=conn,
            cursor=cursor,
            organization_id="5f98365f-e7c5-4f48-9918-7fe9aabae5df",
            action="regenerate",
            resource_type="chatwork_task",
            resource_id="task_123",
            details={"old_summary": "お疲れ様です", "new_summary": "経費精算の確認依頼"}
        )
    """
    try:
        # audit_logs テーブルが存在するか確認
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = 'audit_logs'
            )
        """)
        table_exists = cursor.fetchone()[0]

        if not table_exists:
            # テーブルがない場合はログ出力のみ（Phase 3.5以前の互換性）
            logger.info("Audit (no table): %s %s/%s org=%s", action, resource_type, resource_id, organization_id)
            if details:
                logger.info("   Details: %s", json.dumps(details, ensure_ascii=False)[:200])
            return True

        # audit_logs テーブルに挿入
        cursor.execute("""
            INSERT INTO audit_logs (
                organization_id,
                user_id,
                action,
                resource_type,
                resource_id,
                resource_name,
                department_id,
                classification,
                details,
                ip_address,
                user_agent,
                created_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
        """, (
            organization_id,
            user_id,
            action,
            resource_type,
            resource_id,
            resource_name,
            department_id,
            classification,
            json.dumps(details, ensure_ascii=False) if details else None,
            ip_address,
            user_agent,
            datetime.now(timezone.utc)
        ))
        conn.commit()

        logger.info("Audit logged: %s %s/%s org=%s", action, resource_type, resource_id, organization_id)
        return True

    except Exception as e:
        # 監査ログの記録失敗は本処理を止めない
        logger.warning("Audit log failed (non-blocking): %s", e)
        # ただしログ出力は行う（Cloud Loggingには残る）
        logger.info("Audit (fallback): %s %s/%s org=%s", action, resource_type, resource_id, organization_id)
        if details:
            logger.info("   Details: %s", json.dumps(details, ensure_ascii=False)[:200])
        return False


def log_audit_batch(
    conn,
    cursor,
    organization_id: str,
    action: str,
    resource_type: str,
    items: list,
    user_id: Optional[str] = None,
    summary_details: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    バッチ操作の監査ログを記録する

    ★★★ v10.14.1: 新規追加 ★★★

    複数件の操作をまとめて1件の監査ログとして記録。
    個別のログは items に含める。

    Args:
        conn: DB接続
        cursor: DBカーソル
        organization_id: テナントID
        action: アクション
        resource_type: リソースタイプ
        items: 処理したアイテムのリスト [{"id": "...", "old": "...", "new": "..."}, ...]
        user_id: 実行ユーザーID
        summary_details: サマリー情報

    Returns:
        True: 成功, False: 失敗

    Example:
        log_audit_batch(
            conn=conn,
            cursor=cursor,
            organization_id="5f98365f-e7c5-4f48-9918-7fe9aabae5df",
            action="regenerate",
            resource_type="chatwork_task",
            items=[
                {"id": "task_1", "old_summary": "お疲れ様", "new_summary": "経費精算"},
                {"id": "task_2", "old_summary": "いつも", "new_summary": "報告書提出"},
            ],
            summary_details={"total": 2, "success": 2, "failed": 0}
        )
    """
    details = {
        "batch": True,
        "item_count": len(items),
        "items": items[:10],  # 最初の10件のみ記録（容量制限）
        **(summary_details or {})
    }

    return log_audit(
        conn=conn,
        cursor=cursor,
        organization_id=organization_id,
        action=action,
        resource_type=resource_type,
        resource_id=f"batch_{len(items)}_items",
        user_id=user_id,
        details=details,
    )


# =====================================================
# 非同期版（Google Drive権限管理等で使用）
# =====================================================


async def log_audit_async(
    organization_id: str,
    action: str,
    resource_type: str,
    resource_id: Optional[str] = None,
    resource_name: Optional[str] = None,
    user_id: Optional[str] = None,
    classification: str = "confidential",
    details: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    非同期版監査ログ記録

    ★★★ v10.28.0: 新規追加 ★★★

    Google Drive権限管理などの非同期処理から呼び出される。
    DB接続がない場合はログ出力のみ行う（フォールバック設計）。

    Args:
        organization_id: テナントID（必須）
        action: アクション（create, update, delete, sync等）
        resource_type: リソースタイプ（drive_permission, drive_folder等）
        resource_id: リソースID
        resource_name: リソース名
        user_id: 実行ユーザーID（省略時はsystem）
        classification: 機密区分（デフォルト: confidential）
        details: 詳細情報（JSON）

    Returns:
        True: 成功, False: 失敗

    Example:
        await log_audit_async(
            organization_id="5f98365f-e7c5-4f48-9918-7fe9aabae5df",
            action="create",
            resource_type="drive_permission",
            resource_id="folder_abc123",
            resource_name="営業部",
            details={"email": "user@example.com", "role": "reader"}
        )
    """
    try:
        # 構造化ログ出力（Cloud Loggingで検索可能）
        log_entry = {
            "audit": True,
            "organization_id": organization_id,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "resource_name": resource_name,
            "user_id": user_id or "system",
            "classification": classification,
            "details": details,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        logger.info(f"📝 Audit: {json.dumps(log_entry, ensure_ascii=False)}")

        # TODO: Phase 4でDB書き込みを追加
        # async with get_async_db_pool() as conn:
        #     await conn.execute(...)

        return True

    except Exception as e:
        logger.warning(f"⚠️ Audit log failed (non-blocking): {e}")
        return False


async def log_drive_permission_change(
    organization_id: str,
    folder_id: str,
    folder_name: str,
    action: str,
    email: str,
    role: Optional[str] = None,
    old_role: Optional[str] = None,
    dry_run: bool = False,
) -> bool:
    """
    Google Drive権限変更の監査ログ

    ★★★ v10.28.0: 新規追加 ★★★

    Args:
        organization_id: テナントID
        folder_id: フォルダID
        folder_name: フォルダ名
        action: アクション（add, remove, update）
        email: 対象メールアドレス
        role: 新しい権限ロール（add/updateの場合）
        old_role: 旧権限ロール（remove/updateの場合）
        dry_run: dry_runモードかどうか

    Returns:
        True: 成功
    """
    details = {
        "email": email,
        "dry_run": dry_run,
    }
    if role:
        details["role"] = role
    if old_role:
        details["old_role"] = old_role

    return await log_audit_async(
        organization_id=organization_id,
        action=f"drive_permission_{action}",
        resource_type="drive_permission",
        resource_id=folder_id,
        resource_name=folder_name,
        classification="confidential",
        details=details,
    )


async def log_drive_sync_summary(
    organization_id: str,
    folders_processed: int,
    permissions_added: int,
    permissions_removed: int,
    permissions_updated: int,
    errors: int,
    dry_run: bool = False,
    snapshot_id: Optional[str] = None,
) -> bool:
    """
    Google Drive権限同期のサマリー監査ログ

    ★★★ v10.28.0: 新規追加 ★★★

    Args:
        organization_id: テナントID
        folders_processed: 処理フォルダ数
        permissions_added: 追加された権限数
        permissions_removed: 削除された権限数
        permissions_updated: 更新された権限数
        errors: エラー数
        dry_run: dry_runモードかどうか
        snapshot_id: 事前スナップショットID

    Returns:
        True: 成功
    """
    return await log_audit_async(
        organization_id=organization_id,
        action="drive_permission_sync",
        resource_type="drive_folder",
        resource_id=f"batch_{folders_processed}_folders",
        classification="confidential",
        details={
            "folders_processed": folders_processed,
            "permissions_added": permissions_added,
            "permissions_removed": permissions_removed,
            "permissions_updated": permissions_updated,
            "total_changes": permissions_added + permissions_removed + permissions_updated,
            "errors": errors,
            "dry_run": dry_run,
            "snapshot_id": snapshot_id,
        },
    )


# =====================================================
# エクスポート
# =====================================================
__all__ = [
    "AuditAction",
    "AuditResourceType",
    "log_audit",
    "log_audit_batch",
    # 非同期版（v10.28.0追加）
    "log_audit_async",
    "log_drive_permission_change",
    "log_drive_sync_summary",
]
