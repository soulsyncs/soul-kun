#!/bin/bash
# supabase-sync デプロイスクリプト
# Supabase → Cloud SQL フォームデータ同期
# 3AI合議: 非金融データのみ同期

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== supabase-sync デプロイ ==="

# 1. libディレクトリ同期
echo ""
echo "=== Step 1: Syncing lib files ==="
bash "$ROOT_DIR/scripts/sync_lib.sh" 2>/dev/null || true

# supabase-syncに必要なlibファイルをコピー（HIGH-4: 未使用のorg_chart_service.py除外）
# NOTE: __init__.py はコピーしない（親lib/の__init__.pyは全モジュールをimportするため）
LIB_FILES=(
    "config.py"
    "secrets.py"
    "db.py"
)

mkdir -p "$SCRIPT_DIR/lib/"
for file in "${LIB_FILES[@]}"; do
    if [ -f "$ROOT_DIR/lib/$file" ]; then
        cp "$ROOT_DIR/lib/$file" "$SCRIPT_DIR/lib/"
        echo "  Copied: $file"
    else
        echo "  WARNING: $file not found"
    fi
done
# 最小限の__init__.py（親lib/のものは使わない）
echo '"""supabase-sync lib - minimal subset of shared lib"""' > "$SCRIPT_DIR/lib/__init__.py"
echo "  Created: __init__.py (minimal)"

# 2. Import smoke test
echo ""
echo "=== Step 2: Import smoke test ==="
python3 -c "
import sys; sys.path.insert(0, '$SCRIPT_DIR')
from lib.config import get_settings
print('  Import OK')
" || { echo "ERROR: Import test failed"; exit 1; }

# 3. Cloud Functionをデプロイ
echo ""
echo "=== Step 3: Deploying Cloud Function ==="

cd "$SCRIPT_DIR"

# IMPORTANT: --update-env-vars を使用（--set-env-vars 禁止！CLAUDE.md #22）
gcloud functions deploy supabase_sync \
    --gen2 \
    --runtime python311 \
    --trigger-http \
    --no-allow-unauthenticated \
    --timeout=120 \
    --memory=256MB \
    --region=asia-northeast1 \
    --max-instances=1 \
    --entry-point=supabase_sync \
    --update-env-vars="SUPABASE_URL=https://adzxpeboaoiojepcxlyc.supabase.co,SOULKUN_ORG_ID=5f98365f-e7c5-4f48-9918-7fe9aabae5df,CLOUDSQL_ORG_ID=5f98365f-e7c5-4f48-9918-7fe9aabae5df" \
    --set-secrets="SUPABASE_ANON_KEY=SUPABASE_ANON_KEY:latest"

# 4. Cloud Schedulerジョブ作成
echo ""
echo "=== Step 4: Creating Cloud Scheduler job ==="

if ! gcloud scheduler jobs describe supabase-sync-daily --location=asia-northeast1 &>/dev/null; then
    gcloud scheduler jobs create http supabase-sync-daily \
        --schedule="0 6 * * *" \
        --uri="https://asia-northeast1-soulkun-production.cloudfunctions.net/supabase_sync" \
        --http-method=POST \
        --time-zone="Asia/Tokyo" \
        --message-body='{"dry_run": false}' \
        --oidc-service-account-email="scheduler-invoker@soulkun-production.iam.gserviceaccount.com" \
        --location=asia-northeast1
    echo "  Created: supabase-sync-daily (06:00 JST)"
else
    echo "  Scheduler job already exists: supabase-sync-daily"
fi

echo ""
echo "=== Deployment Complete ==="
echo ""
echo "Function URL: https://asia-northeast1-soulkun-production.cloudfunctions.net/supabase_sync"
echo ""
echo "Manual execution (dry_run):"
echo "  curl -X POST -H 'Content-Type: application/json' -d '{\"dry_run\": true}' \\"
echo "    -H 'Authorization: Bearer \$(gcloud auth print-identity-token)' \\"
echo "    https://asia-northeast1-soulkun-production.cloudfunctions.net/supabase_sync"
echo ""
echo "Manual execution (actual):"
echo "  curl -X POST -H 'Content-Type: application/json' -d '{\"dry_run\": false}' \\"
echo "    -H 'Authorization: Bearer \$(gcloud auth print-identity-token)' \\"
echo "    https://asia-northeast1-soulkun-production.cloudfunctions.net/supabase_sync"
