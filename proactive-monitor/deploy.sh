#!/bin/bash
# =============================================================================
# proactive-monitor デプロイスクリプト（Cloud Run版）
# =============================================================================
#
# 目的:
#   proactive-monitor を安全にCloud Runにデプロイする
#
# 使い方:
#   ./proactive-monitor/deploy.sh              # 本番デプロイ
#   ./proactive-monitor/deploy.sh --dry-run    # 確認のみ（デプロイしない）
#   ./proactive-monitor/deploy.sh --skip-tests # テストをスキップ
#
# 推奨: scripts/safe_deploy.sh proactive-monitor（煙テスト＋自動ロールバック付き）
#
# v10.53.0: 初版作成（大規模修繕対応）
# v11.0.0: Cloud Run移行（Docker build + gcloud run deploy）
# =============================================================================

set -eo pipefail

# カラー出力
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# プロジェクトルートに移動
cd "$(dirname "$0")/.."

# 設定
REGION="${REGION:-asia-northeast1}"
PROJECT=$(gcloud config get-value project 2>/dev/null)
AR_REPO="${AR_REPO:-cloud-run}"
SERVICE="proactive-monitor"
IMAGE_TAG="${IMAGE_TAG:-$(git rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M%S)}"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/${AR_REPO}/${SERVICE}:${IMAGE_TAG}"

# オプション解析
DRY_RUN=false
SKIP_TESTS=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --skip-tests)
            SKIP_TESTS=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${BLUE}proactive-monitor Cloud Run デプロイ${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo -e "  プロジェクト: ${GREEN}$PROJECT${NC}"
echo -e "  イメージ: $IMAGE"
echo ""

if [ "$DRY_RUN" = true ]; then
    echo -e "${YELLOW}ドライランモード（デプロイしない）${NC}"
    echo ""
fi

# =============================================================================
# Step 1: テスト実行
# =============================================================================

if [ "$SKIP_TESTS" = true ]; then
    echo -e "  [1/4] テスト... ${YELLOW}SKIP${NC}"
else
    echo -e "  ${BLUE}[1/4] テスト実行${NC}"
    if ! python3 -m pytest tests/test_critical_functions.py -v --tb=short 2>&1 | tail -10; then
        echo -e "  ${RED}FAIL: テストに失敗${NC}"
        exit 1
    fi
    echo -e "  ${GREEN}PASS${NC}"
fi
echo ""

# =============================================================================
# Step 2: gcloud 確認
# =============================================================================

echo -e "  ${BLUE}[2/4] 環境確認${NC}"
if ! command -v gcloud &> /dev/null; then
    echo -e "  ${RED}FAIL: gcloud CLI がインストールされていません${NC}"
    exit 1
fi
if [ -z "$PROJECT" ]; then
    echo -e "  ${RED}FAIL: GCPプロジェクトが設定されていません${NC}"
    exit 1
fi
echo -e "  ${GREEN}PASS${NC}"
echo ""

if [ "$DRY_RUN" = true ]; then
    echo "実行コマンド（参考）:"
    echo "  docker build -f proactive-monitor/Dockerfile -t $IMAGE ."
    echo "  docker push $IMAGE"
    echo "  gcloud run deploy $SERVICE --image=$IMAGE --region=$REGION ..."
    echo ""
    echo -e "${GREEN}ドライラン完了${NC}"
    exit 0
fi

# =============================================================================
# Step 3: Docker ビルド & プッシュ
# =============================================================================

echo -e "  ${BLUE}[3/4] Docker ビルド & プッシュ${NC}"
docker build -f proactive-monitor/Dockerfile -t "$IMAGE" .
docker push "$IMAGE"
echo -e "  ${GREEN}PASS${NC}"
echo ""

# =============================================================================
# Step 4: Cloud Run デプロイ
# =============================================================================

echo -e "  ${BLUE}[4/4] Cloud Run デプロイ${NC}"

# IMPORTANT: --update-env-vars を使用（--set-env-vars 禁止！）
gcloud run deploy "$SERVICE" \
    --image="$IMAGE" \
    --region="$REGION" \
    --memory=512Mi \
    --timeout=540s \
    --no-allow-unauthenticated \
    --min-instances=0 \
    --max-instances=5 \
    --update-env-vars="USE_BRAIN_ARCHITECTURE=true,ENVIRONMENT=production,LOG_EXECUTION_ID=true" \
    --update-secrets="TAVILY_API_KEY=TAVILY_API_KEY:latest"

echo ""

# =============================================================================
# Step 5: トラフィックルーティング確認
# =============================================================================

echo -e "  ${BLUE}トラフィックルーティング確認${NC}"

LATEST_REV=$(gcloud run revisions list --service="$SERVICE" --region="$REGION" \
    --sort-by='~creationTimestamp' --limit=1 --format='value(name)' 2>/dev/null)
TRAFFIC_REV=$(gcloud run services describe "$SERVICE" --region="$REGION" \
    --format='value(status.traffic[0].revisionName)' 2>/dev/null)

if [ -n "$LATEST_REV" ] && [ -n "$TRAFFIC_REV" ]; then
    if [ "$LATEST_REV" = "$TRAFFIC_REV" ]; then
        echo -e "  ${GREEN}トラフィック: ${LATEST_REV} (100%)${NC}"
    else
        echo -e "  ${YELLOW}旧リビジョン: ${TRAFFIC_REV} → ${LATEST_REV} に切り替え中...${NC}"
        gcloud run services update-traffic "$SERVICE" --region="$REGION" \
            --to-revisions="${LATEST_REV}=100" 2>&1
        echo -e "  ${GREEN}切り替え完了${NC}"
    fi
else
    echo -e "  ${YELLOW}リビジョン情報の取得に失敗。手動で確認してください${NC}"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${GREEN}デプロイ完了${NC}"
echo ""
echo "  ログ確認: gcloud run services logs read $SERVICE --region=$REGION --limit=50"
echo "  障害時:   scripts/rollback.sh proactive-monitor"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
