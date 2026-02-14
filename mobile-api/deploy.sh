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

deploy_service() {
    local service="$1"
    local dockerfile="$2"
    local port="$3"

    info "=== Deploying ${service} ==="

    # Docker build
    info "Building Docker image..."
    docker build -t "${REPO}/${service}:latest" -f "${dockerfile}" .

    # Push to Artifact Registry
    info "Pushing to Artifact Registry..."
    docker push "${REPO}/${service}:latest"

    # Deploy to Cloud Run
    info "Deploying to Cloud Run..."
    gcloud run deploy "${service}" \
        --image "${REPO}/${service}:latest" \
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
        --no-allow-unauthenticated \
        --quiet

    info "${service} deployed successfully!"
    gcloud run services describe "${service}" --region "${REGION}" --format "value(status.url)"
}

case "${TARGET}" in
    mobile-api)
        deploy_service "soulkun-mobile-api" "mobile-api/Dockerfile" "8081"
        ;;
    mcp-server)
        deploy_service "soulkun-mcp-server" "mcp-server/Dockerfile" "8080"
        ;;
    all)
        deploy_service "soulkun-mobile-api" "mobile-api/Dockerfile" "8081"
        echo ""
        deploy_service "soulkun-mcp-server" "mcp-server/Dockerfile" "8080"
        ;;
    *)
        error "Unknown target: ${TARGET}"
        echo "Usage: $0 [mobile-api|mcp-server|all]"
        exit 1
        ;;
esac

info "=== Deployment complete ==="
