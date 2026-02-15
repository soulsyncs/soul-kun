"""
Google Drive 権限同期 Cloud Function

組織図と連携してGoogle Driveフォルダの共有権限を自動同期する。

デプロイ:
    gcloud functions deploy sync_drive_permissions \
        --runtime python311 \
        --trigger-http \
        --allow-unauthenticated=false \
        --timeout=540 \
        --memory=512MB \
        --region=asia-northeast1 \
        --max-instances=1 \
        --env-vars-file=env-vars.yaml

Cloud Scheduler:
    gcloud scheduler jobs create http sync-drive-permissions-daily \
        --schedule="0 2 * * *" \
        --uri="https://asia-northeast1-soulkun-production.cloudfunctions.net/sync_drive_permissions" \
        --http-method=POST \
        --time-zone="Asia/Tokyo" \
        --oidc-service-account-email="scheduler-invoker@soulkun-production.iam.gserviceaccount.com"

Phase F: Google Drive 自動権限管理機能
Created: 2026-01-26
"""

import os
import sys
import json
import asyncio
from datetime import datetime
from typing import Optional
import logging
import tempfile

import functions_framework
from flask import Request, jsonify

# Cloud Functions デプロイ時はlibが同じディレクトリにある
# ローカル開発時はプロジェクトルートから参照
current_dir = os.path.dirname(os.path.abspath(__file__))
if os.path.exists(os.path.join(current_dir, 'lib')):
    sys.path.insert(0, current_dir)
else:
    sys.path.insert(0, os.path.dirname(current_dir))

from lib.drive_permission_sync_service import (
    DrivePermissionSyncService,
    SyncReport,
)
from lib.drive_permission_snapshot import (
    SnapshotManager,
    PermissionSnapshot,
)
from lib.drive_permission_change_detector import (
    ChangeDetector,
    ChangeDetectionConfig,
    create_detector_from_env,
    EMERGENCY_STOP_FLAG,
)
from lib.secrets import get_secret


# ================================================================
# 設定
# ================================================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 環境変数
ORGANIZATION_ID = os.getenv('ORGANIZATION_ID', '5f98365f-e7c5-4f48-9918-7fe9aabae5df')
ROOT_FOLDER_ID = os.getenv('SOULKUN_DRIVE_ROOT_FOLDER_ID')
SUPABASE_URL = os.getenv('SUPABASE_URL')
SNAPSHOT_STORAGE_PATH = os.getenv(
    'SNAPSHOT_STORAGE_PATH',
    '/tmp/drive_permission_snapshots'
)

# デフォルト設定
DEFAULT_DRY_RUN = True  # デフォルトはdry_run
DEFAULT_REMOVE_UNLISTED = False  # 未登録ユーザーの削除はデフォルトOFF
DEFAULT_CREATE_SNAPSHOT = True  # 事前スナップショットを作成


def get_service_account_info() -> Optional[dict]:
    """サービスアカウント情報を取得

    Returns:
        dict: サービスアカウント情報
        None: ADC（Application Default Credentials）を使用する場合

    優先順位:
    1. Secret Manager の GOOGLE_SERVICE_ACCOUNT_JSON
    2. 環境変数 GOOGLE_APPLICATION_CREDENTIALS のファイル
    3. None（ADCを使用）
    """
    # Secret Managerから取得
    try:
        sa_json = get_secret('GOOGLE_SERVICE_ACCOUNT_JSON')
        if sa_json:
            logger.info("Using service account from Secret Manager")
            return json.loads(sa_json)
    except Exception as e:
        logger.debug(f"Secret Manager lookup failed (expected): {e}")

    # ファイルから読み込み（ローカル開発用）
    sa_file = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
    if sa_file and os.path.exists(sa_file):
        logger.info(f"Using service account from file: {sa_file}")
        with open(sa_file, 'r') as f:
            return json.load(f)

    # ADCを使用
    logger.info("Using Application Default Credentials (ADC)")
    return None


def get_supabase_key() -> str:
    """Supabase APIキーを取得

    優先順位:
    1. Secret Manager の SUPABASE_SERVICE_ROLE_KEY
    2. 環境変数 SUPABASE_SERVICE_ROLE_KEY
    3. 環境変数 SUPABASE_ANON_KEY（読み取り専用操作用）
    """
    # Service Role Key from Secret Manager（推奨）
    try:
        key = get_secret('SUPABASE_SERVICE_ROLE_KEY')
        if key:
            logger.info("Using Supabase service role key from Secret Manager")
            return key
    except Exception as e:
        logger.debug(f"Secret Manager lookup for SUPABASE_SERVICE_ROLE_KEY failed (expected): {e}")

    # Service Role Key from environment
    key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')
    if key:
        logger.info("Using Supabase service role key from environment")
        return key

    # Anon Key（フォールバック - 読み取り専用操作には十分）
    key = os.getenv('SUPABASE_ANON_KEY')
    if key:
        logger.info("Using Supabase anon key (read-only operations)")
        return key

    raise ValueError("Supabase API key not found (SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY)")


# ================================================================
# メインエントリポイント
# ================================================================

@functions_framework.http
def sync_drive_permissions(request: Request):
    """
    Google Drive権限同期のメインエントリポイント

    リクエストパラメータ:
        dry_run: bool = True        # Trueの場合は変更を適用しない
        remove_unlisted: bool = False  # 未登録ユーザーの権限を削除するか
        create_snapshot: bool = True   # 事前スナップショットを作成するか
        folder_ids: list = None     # 同期対象フォルダID（省略時は全フォルダ）
        send_alerts: bool = True    # アラートをChatworkに送信するか

    レスポンス:
        {
            "success": bool,
            "dry_run": bool,
            "snapshot_id": str | null,
            "report": {
                "folders_processed": int,
                "permissions_added": int,
                "permissions_removed": int,
                "permissions_updated": int,
                "errors": int,
                "warnings": list
            },
            "message": str
        }
    """
    try:
        # リクエストパラメータを取得
        if request.is_json:
            data = request.get_json()
        else:
            data = {}

        dry_run = data.get('dry_run', DEFAULT_DRY_RUN)
        remove_unlisted = data.get('remove_unlisted', DEFAULT_REMOVE_UNLISTED)
        create_snapshot = data.get('create_snapshot', DEFAULT_CREATE_SNAPSHOT)
        folder_ids = data.get('folder_ids')
        send_alerts = data.get('send_alerts', True)

        logger.info(
            f"Starting permission sync: dry_run={dry_run}, "
            f"remove_unlisted={remove_unlisted}, create_snapshot={create_snapshot}"
        )

        # 同期を非同期で実行
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            result = loop.run_until_complete(
                _run_sync(
                    dry_run=dry_run,
                    remove_unlisted=remove_unlisted,
                    create_snapshot=create_snapshot,
                    folder_ids=folder_ids,
                    send_alerts=send_alerts,
                )
            )
        finally:
            loop.close()

        return jsonify(result)

    except Exception as e:
        logger.error(f"Error in sync_drive_permissions: {e}", exc_info=True)
        return jsonify({
            "success": False,
            "error": str(e),
            "message": "権限同期中にエラーが発生しました",
        }), 500


async def _run_sync(
    dry_run: bool,
    remove_unlisted: bool,
    create_snapshot: bool,
    folder_ids: Optional[list],
    send_alerts: bool,
) -> dict:
    """
    同期処理の実行

    Returns:
        結果を含む辞書
    """
    result = {
        "success": False,
        "dry_run": dry_run,
        "snapshot_id": None,
        "report": None,
        "message": "",
    }

    # サービスアカウント情報を取得
    try:
        service_account_info = get_service_account_info()
    except Exception as e:
        result["message"] = f"サービスアカウント情報の取得に失敗: {e}"
        return result

    # Supabase設定を取得
    try:
        supabase_url = SUPABASE_URL
        supabase_key = get_supabase_key()
        if not supabase_url:
            raise ValueError("SUPABASE_URL is not set")
    except Exception as e:
        result["message"] = f"Supabase設定の取得に失敗: {e}"
        return result

    # ルートフォルダIDを確認
    if not ROOT_FOLDER_ID:
        result["message"] = "SOULKUN_DRIVE_ROOT_FOLDER_ID is not set"
        return result

    # 変更検知器を初期化
    detector = create_detector_from_env()

    # 緊急停止チェック
    if detector.check_emergency_stop():
        result["message"] = "緊急停止フラグが有効なため、同期を中止しました"
        if send_alerts:
            detector.send_all_critical_alerts()
        return result

    # スナップショットマネージャーを初期化
    snapshot_manager = None
    if create_snapshot:
        try:
            os.makedirs(SNAPSHOT_STORAGE_PATH, exist_ok=True)
            snapshot_manager = SnapshotManager(
                storage_path=SNAPSHOT_STORAGE_PATH,
                service_account_info=service_account_info,
                organization_id=ORGANIZATION_ID,  # テナント分離（v10.28.0）
            )
        except Exception as e:
            logger.warning(f"Failed to initialize snapshot manager: {e}")

    # 事前スナップショットを作成
    if snapshot_manager and not dry_run:
        try:
            # 同期対象フォルダを取得（または全フォルダ）
            target_folders = folder_ids or [ROOT_FOLDER_ID]

            snapshot = await snapshot_manager.create_snapshot(
                folder_ids=target_folders,
                description=f"Pre-sync snapshot ({datetime.now().strftime('%Y-%m-%d %H:%M')})",
                created_by='sync_drive_permissions',
            )
            result["snapshot_id"] = snapshot.id
            logger.info(f"Created pre-sync snapshot: {snapshot.id}")
        except Exception as e:
            logger.warning(f"Failed to create snapshot: {e}")

    # 同期サービスを初期化
    sync_service = DrivePermissionSyncService(
        supabase_url=supabase_url,
        supabase_key=supabase_key,
        service_account_info=service_account_info,
        organization_id=ORGANIZATION_ID,
        root_folder_id=ROOT_FOLDER_ID,
    )

    # 同期を実行
    try:
        report = await sync_service.sync_all_folders(
            dry_run=dry_run,
            remove_unlisted=remove_unlisted,
            change_detector=detector,
            send_alerts=send_alerts,
        )

        result["success"] = report.errors == 0
        result["report"] = {
            "folders_processed": report.folders_processed,
            "permissions_added": report.permissions_added,
            "permissions_removed": report.permissions_removed,
            "permissions_updated": report.permissions_updated,
            "permissions_unchanged": report.permissions_unchanged,
            "total_changes": report.total_changes,
            "errors": report.errors,
            "warnings": report.warnings,
            "duration_seconds": report.duration_seconds,
        }

        if dry_run:
            result["message"] = (
                f"[DRY RUN] 同期シミュレーション完了: "
                f"{report.folders_processed}フォルダ, "
                f"{report.total_changes}件の変更予定"
            )
        else:
            result["message"] = (
                f"同期完了: {report.folders_processed}フォルダ, "
                f"追加{report.permissions_added}/削除{report.permissions_removed}/"
                f"更新{report.permissions_updated}"
            )

        logger.info(report.to_summary())

    except Exception as e:
        logger.error(f"Error during sync: {e}", exc_info=True)
        result["message"] = f"同期中にエラー: {e}"

    return result


# ================================================================
# 管理用エンドポイント
# ================================================================

@functions_framework.http
def list_snapshots(request: Request):
    """
    スナップショット一覧を取得

    レスポンス:
        {
            "snapshots": [
                {
                    "id": str,
                    "description": str,
                    "created_at": str,
                    "folder_count": int
                }
            ]
        }
    """
    try:
        service_account_info = get_service_account_info()
        os.makedirs(SNAPSHOT_STORAGE_PATH, exist_ok=True)

        manager = SnapshotManager(
            storage_path=SNAPSHOT_STORAGE_PATH,
            service_account_info=service_account_info,
            organization_id=ORGANIZATION_ID,  # テナント分離（v10.28.0）
        )

        snapshots = manager.list_snapshots()

        return jsonify({
            "success": True,
            "snapshots": snapshots,
        })

    except Exception as e:
        logger.error(f"Error listing snapshots: {e}", exc_info=True)
        return jsonify({
            "success": False,
            "error": str(e),
        }), 500


@functions_framework.http
def rollback_snapshot(request: Request):
    """
    スナップショットからロールバック

    リクエストパラメータ:
        snapshot_id: str            # ロールバック対象のスナップショットID
        dry_run: bool = True        # Trueの場合は変更を適用しない
        folder_ids: list = None     # ロールバック対象フォルダ（省略時は全フォルダ）

    レスポンス:
        {
            "success": bool,
            "dry_run": bool,
            "result": {
                "folders_processed": int,
                "permissions_added": int,
                "permissions_removed": int,
                "errors": int
            },
            "message": str
        }
    """
    try:
        if request.is_json:
            data = request.get_json()
        else:
            data = {}

        snapshot_id = data.get('snapshot_id')
        if not snapshot_id:
            return jsonify({
                "success": False,
                "error": "snapshot_id is required",
            }), 400

        dry_run = data.get('dry_run', True)
        folder_ids = data.get('folder_ids')

        service_account_info = get_service_account_info()
        os.makedirs(SNAPSHOT_STORAGE_PATH, exist_ok=True)

        manager = SnapshotManager(
            storage_path=SNAPSHOT_STORAGE_PATH,
            service_account_info=service_account_info,
            organization_id=ORGANIZATION_ID,  # テナント分離（v10.28.0）
        )

        # ロールバックを非同期で実行
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            result = loop.run_until_complete(
                manager.rollback(
                    snapshot_id=snapshot_id,
                    dry_run=dry_run,
                    folder_ids=folder_ids,
                )
            )
        finally:
            loop.close()

        return jsonify({
            "success": result.success,
            "dry_run": result.dry_run,
            "result": {
                "folders_processed": result.folders_processed,
                "permissions_added": result.permissions_added,
                "permissions_removed": result.permissions_removed,
                "permissions_updated": result.permissions_updated,
                "errors": result.errors,
            },
            "message": result.to_summary(),
        })

    except Exception as e:
        logger.error(f"Error during rollback: {e}", exc_info=True)
        return jsonify({
            "success": False,
            "error": str(e),
        }), 500


# ================================================================
# ローカル実行用
# ================================================================

if __name__ == '__main__':
    """ローカルテスト用"""
    import argparse

    parser = argparse.ArgumentParser(description='Drive Permission Sync')
    parser.add_argument('--dry-run', action='store_true', default=True,
                        help='Dry run mode (default: True)')
    parser.add_argument('--execute', action='store_true',
                        help='Actually execute changes')
    parser.add_argument('--remove-unlisted', action='store_true',
                        help='Remove permissions for unlisted users')
    parser.add_argument('--no-snapshot', action='store_true',
                        help='Skip snapshot creation')
    parser.add_argument('--no-alerts', action='store_true',
                        help='Skip Chatwork alerts')

    args = parser.parse_args()

    dry_run = not args.execute
    create_snapshot = not args.no_snapshot
    send_alerts = not args.no_alerts

    print(f"Running permission sync...")
    print(f"  dry_run: {dry_run}")
    print(f"  remove_unlisted: {args.remove_unlisted}")
    print(f"  create_snapshot: {create_snapshot}")
    print(f"  send_alerts: {send_alerts}")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        result = loop.run_until_complete(
            _run_sync(
                dry_run=dry_run,
                remove_unlisted=args.remove_unlisted,
                create_snapshot=create_snapshot,
                folder_ids=None,
                send_alerts=send_alerts,
            )
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
    finally:
        loop.close()
