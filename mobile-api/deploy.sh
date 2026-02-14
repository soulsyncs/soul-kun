#!/usr/bin/env bash
set -euo pipefail
################################################################################
# Mobile API + MCP Server デプロイスクリプト
#
# Cloud Run にデプロイ（Phase 2 Cloud Run 移行と連携）
#
# 使い方:
#   bash mobile-api/deploy.sh [mobile-api|mcp-server|all]
################################################################################

PROJECT="soulkun-production"
REGION="asia-northeast1"
REPO="asia-northeast1-docker.pkg.dev/${PROJECT}/soulkun"

# カラー出力
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

TARGET="${1:-all}"

COMMIT_SHA=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")

deploy_service() {
    local service="$1"
    local dockerfile="$2"
    local port="$3"
    local allow_unauth="${4:-no}"

    info "=== Deploying ${service} (${COMMIT_SHA}) ==="

    # Docker build with commit SHA tag
    info "Building Docker image..."
    docker build \
        -t "${REPO}/${service}:${COMMIT_SHA}" \
        -t "${REPO}/${service}:latest" \
        -f "${dockerfile}" .

    # Push to Artifact Registry (both tags)
    info "Pushing to Artifact Registry..."
    docker push "${REPO}/${service}:${COMMIT_SHA}"
    docker push "${REPO}/${service}:latest"

    # 認証設定: mobile-apiはJWT自前認証なのでCloud Run認証は不要
    local auth_flag="--no-allow-unauthenticated"
    if [ "${allow_unauth}" = "yes" ]; then
        auth_flag="--allow-unauthenticated"
    fi

    # Deploy to Cloud Run
    info "Deploying to Cloud Run..."
    gcloud run deploy "${service}" \
        --image "${REPO}/${service}:${COMMIT_SHA}" \
        --region "${REGION}" \
        --platform managed \
        --port "${port}" \
        --memory 512Mi \
        --cpu 1 \
        --min-instances 0 \
        --max-instances 5 \
        --timeout 540 \
        --service-account "cloud-functions-sa@${PROJECT}.iam.gserviceaccount.com" \
        --update-env-vars "ENVIRONMENT=production,USE_BRAIN_ARCHITECTURE=true,DB_NAME=soulkun_tasks,DB_USER=soulkun_user,INSTANCE_CONNECTION_NAME=${PROJECT}:${REGION}:soulkun-db,PROJECT_ID=${PROJECT}" \
        --update-secrets "DB_PASSWORD=cloudsql-password:latest,OPENROUTER_API_KEY=openrouter-api-key:latest,JWT_SECRET=jwt-secret:latest" \
        --add-cloudsql-instances "${PROJECT}:${REGION}:soulkun-db" \
        ${auth_flag} \
        --quiet

    info "${service} deployed successfully!"
    gcloud run services describe "${service}" --region "${REGION}" --format "value(status.url)"
}

case "${TARGET}" in
    mobile-api)
        # mobile-apiはJWT自前認証 → Cloud Run認証不要（iPhoneアプリから直接アクセス）
        deploy_service "soulkun-mobile-api" "mobile-api/Dockerfile" "8081" "yes"
        ;;
    mcp-server)
        # mcp-serverはCloud Run IAM認証 + アプリレベルAPI Key認証の二重防御
        deploy_service "soulkun-mcp-server" "mcp-server/Dockerfile" "8080" "no"
        ;;
    all)
        deploy_service "soulkun-mobile-api" "mobile-api/Dockerfile" "8081" "yes"
        echo ""
        deploy_service "soulkun-mcp-server" "mcp-server/Dockerfile" "8080" "no"
        ;;
    *)
        error "Unknown target: ${TARGET}"
        echo "Usage: $0 [mobile-api|mcp-server|all]"
        exit 1
        ;;
esac

info "=== Deployment complete ==="
