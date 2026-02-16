#!/bin/bash
# =============================================================================
# remind-tasks デプロイスクリプト（Cloud Run版）
# =============================================================================
set -eo pipefail
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'
cd "$(dirname "$0")/.."
REGION="${REGION:-asia-northeast1}"
PROJECT=$(gcloud config get-value project 2>/dev/null)
AR_REPO="${AR_REPO:-cloud-run}"
SERVICE="remind-tasks"
IMAGE_TAG="${IMAGE_TAG:-$(git rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M%S)}"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/${AR_REPO}/${SERVICE}:${IMAGE_TAG}"
DRY_RUN=false
SKIP_TESTS=false
while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run) DRY_RUN=true; shift ;;
        --skip-tests) SKIP_TESTS=true; shift ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${BLUE}remind-tasks Cloud Run デプロイ${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "  プロジェクト: ${GREEN}$PROJECT${NC}"
echo -e "  イメージ: $IMAGE"
if [ "$DRY_RUN" = true ]; then
    echo -e "${YELLOW}ドライランモード${NC}"
fi
if [ "$SKIP_TESTS" = true ]; then
    echo -e "  [1/4] テスト... ${YELLOW}SKIP${NC}"
else
    echo -e "  ${BLUE}[1/4] Import smoke test${NC}"
    python3 -c "import sys; sys.path.insert(0, 'remind-tasks'); from main import app; print('OK')" || exit 1
    echo -e "  ${GREEN}PASS${NC}"
fi
echo -e "  ${BLUE}[2/4] 環境確認${NC}"
command -v gcloud &>/dev/null || { echo -e "  ${RED}FAIL: gcloud未インストール${NC}"; exit 1; }
[ -z "$PROJECT" ] && { echo -e "  ${RED}FAIL: プロジェクト未設定${NC}"; exit 1; }
echo -e "  ${GREEN}PASS${NC}"
if [ "$DRY_RUN" = true ]; then
    echo "  docker build -f remind-tasks/Dockerfile -t $IMAGE ."
    echo "  gcloud run deploy $SERVICE --image=$IMAGE --region=$REGION"
    echo -e "${GREEN}ドライラン完了${NC}"
    exit 0
fi
echo -e "  ${BLUE}[3/4] Docker ビルド & プッシュ${NC}"
docker build -f remind-tasks/Dockerfile -t "$IMAGE" .
docker push "$IMAGE"
echo -e "  ${GREEN}PASS${NC}"
echo -e "  ${BLUE}[4/4] Cloud Run デプロイ${NC}"
gcloud run deploy "$SERVICE" \
    --image="$IMAGE" \
    --region="$REGION" \
    --memory=512Mi \
    --timeout=540s \
    --no-allow-unauthenticated \
    --min-instances=0 \
    --max-instances=5 \
    --update-env-vars="ENVIRONMENT=production"
echo -e "${GREEN}デプロイ完了${NC}"
echo "  ログ確認: gcloud run services logs read $SERVICE --region=$REGION --limit=50"
