#!/bin/bash
# =============================================================================
# check-reply-messages デプロイスクリプト（Cloud Run版）
# =============================================================================
#
# 目的:
#   check-reply-messages を安全にCloud Runにデプロイする
#
# 使い方:
#   ./check-reply-messages/deploy.sh              # 本番デプロイ
#   ./check-reply-messages/deploy.sh --dry-run    # 確認のみ（デプロイしない）
#   ./check-reply-messages/deploy.sh --skip-tests # テストをスキップ
#
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
SERVICE="check-reply-messages"
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
echo -e "${BLUE}check-reply-messages Cloud Run デプロイ${NC}"
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
    echo -e "  ${BLUE}[1/4] Import smoke test${NC}"
    if ! python3 -c "import sys; sys.path.insert(0, 'check-reply-messages'); from main import app; print('OK')"; then
        echo -e "  ${RED}FAIL: Import test に失敗${NC}"
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
    echo "  docker build -f check-reply-messages/Dockerfile -t $IMAGE ."
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
docker build -f check-reply-messages/Dockerfile -t "$IMAGE" .
docker push "$IMAGE"
echo -e "  ${GREEN}PASS${NC}"
echo ""

# =============================================================================
# Step 4: Cloud Run デプロイ
# =============================================================================

echo -e "  ${BLUE}[4/4] Cloud Run デプロイ${NC}"

# IMPORTANT: --update-env-vars を使用（--set-env-vars 禁止！CLAUDE.md #22）
gcloud run deploy "$SERVICE" \
    --image="$IMAGE" \
    --region="$REGION" \
    --memory=1Gi \
    --timeout=540s \
    --no-allow-unauthenticated \
    --min-instances=0 \
    --max-instances=6 \
    --update-env-vars="ENVIRONMENT=production"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${GREEN}デプロイ完了${NC}"
echo ""
echo "  ログ確認: gcloud run services logs read $SERVICE --region=$REGION --limit=50"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
