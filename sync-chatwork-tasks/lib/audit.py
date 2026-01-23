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
        organization_id="org_soulsyncs",
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
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from enum import Enum


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
            organization_id="org_soulsyncs",
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
            # テーブルがない場合はprint出力のみ（Phase 3.5以前の互換性）
            print(f"📝 Audit (no table): {action} {resource_type}/{resource_id} org={organization_id}")
            if details:
                print(f"   Details: {json.dumps(details, ensure_ascii=False)[:200]}")
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

        print(f"📝 Audit logged: {action} {resource_type}/{resource_id} org={organization_id}")
        return True

    except Exception as e:
        # 監査ログの記録失敗は本処理を止めない
        print(f"⚠️ Audit log failed (non-blocking): {e}")
        # ただしprint出力は行う（ログには残る）
        print(f"📝 Audit (fallback): {action} {resource_type}/{resource_id} org={organization_id}")
        if details:
            print(f"   Details: {json.dumps(details, ensure_ascii=False)[:200]}")
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
            organization_id="org_soulsyncs",
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
# エクスポート
# =====================================================
__all__ = [
    "AuditAction",
    "AuditResourceType",
    "log_audit",
    "log_audit_batch",
]
