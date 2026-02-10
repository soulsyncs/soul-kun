#!/bin/bash
# sync-drive-permissions デプロイスクリプト
# Phase F: Google Drive 自動権限管理機能

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== sync-drive-permissions デプロイ ==="
echo "Script directory: $SCRIPT_DIR"
echo "Root directory: $ROOT_DIR"

# 1. libディレクトリにファイルをコピー
echo ""
echo "=== Step 1: Copying lib files ==="

LIB_FILES=(
    "__init__.py"
    "config.py"
    "secrets.py"
    "audit.py"
    "chatwork.py"
    "google_drive.py"
    "drive_permission_manager.py"
    "drive_permission_sync_service.py"
    "drive_permission_snapshot.py"
    "drive_permission_change_detector.py"
    "org_chart_service.py"
)

for file in "${LIB_FILES[@]}"; do
    if [ -f "$ROOT_DIR/lib/$file" ]; then
        cp "$ROOT_DIR/lib/$file" "$SCRIPT_DIR/lib/"
        echo "  Copied: $file"
    else
        echo "  WARNING: $file not found in $ROOT_DIR/lib/"
    fi
done

# 2. Cloud Functionをデプロイ
echo ""
echo "=== Step 2: Deploying Cloud Function ==="

cd "$SCRIPT_DIR"

# SUPABASE_ANON_KEYはSecret Managerから取得（JWTをソースコードにハードコードしない）
# SUPABASE_URLは機密情報ではないため環境変数で設定
gcloud functions deploy sync_drive_permissions \
    --gen2 \
    --runtime python311 \
    --trigger-http \
    --allow-unauthenticated=false \
    --timeout=540 \
    --memory=512MB \
    --region=asia-northeast1 \
    --max-instances=1 \
    --entry-point=sync_drive_permissions \
    --update-env-vars="ORGANIZATION_ID=org_soulsyncs,SUPABASE_URL=https://adzxpeboaoiojepcxlyc.supabase.co,SOULKUN_DRIVE_ROOT_FOLDER_ID=1Bw03U0rmjnkAYeFQDEFB75EsouNaOysp" \
    --set-secrets="SUPABASE_ANON_KEY=SUPABASE_ANON_KEY:latest"

echo ""
echo "=== Step 3: Creating Cloud Scheduler job ==="

# Cloud Schedulerジョブを作成（既存の場合はスキップ）
if ! gcloud scheduler jobs describe sync-drive-permissions-daily --location=asia-northeast1 &>/dev/null; then
    gcloud scheduler jobs create http sync-drive-permissions-daily \
        --schedule="0 2 * * *" \
        --uri="https://asia-northeast1-soulkun-production.cloudfunctions.net/sync_drive_permissions" \
        --http-method=POST \
        --time-zone="Asia/Tokyo" \
        --message-body='{"dry_run": false, "remove_unlisted": false, "create_snapshot": true}' \
        --oidc-service-account-email="scheduler-invoker@soulkun-production.iam.gserviceaccount.com" \
        --location=asia-northeast1
    echo "  Created: sync-drive-permissions-daily (02:00 JST)"
else
    echo "  Scheduler job already exists: sync-drive-permissions-daily"
fi

echo ""
echo "=== Deployment Complete ==="
echo ""
echo "Function URL: https://asia-northeast1-soulkun-production.cloudfunctions.net/sync_drive_permissions"
echo ""
echo "Manual execution (dry_run):"
echo "  curl -X POST -H 'Content-Type: application/json' -d '{\"dry_run\": true}' \\"
echo "    https://asia-northeast1-soulkun-production.cloudfunctions.net/sync_drive_permissions"
echo ""
echo "Manual execution (actual):"
echo "  curl -X POST -H 'Content-Type: application/json' -d '{\"dry_run\": false}' \\"
echo "    https://asia-northeast1-soulkun-production.cloudfunctions.net/sync_drive_permissions"
