#!/bin/bash
# =============================================================================
# chatwork-webhook デプロイスクリプト
# =============================================================================
#
# 目的:
#   chatwork-webhook を安全にCloud Functionsにデプロイする
#
# 使い方:
#   ./chatwork-webhook/deploy.sh              # 本番デプロイ
#   ./chatwork-webhook/deploy.sh --dry-run    # 確認のみ（デプロイしない）
#   ./chatwork-webhook/deploy.sh --skip-tests # テストをスキップ
#
# チェック項目:
#   1. lib/ が同期されているか
#   2. テストが通るか
#   3. 環境変数が設定されているか
#
# v10.53.0: 初版作成（大規模修繕対応）
# =============================================================================

set -e

# カラー出力
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# プロジェクトルートに移動
cd "$(dirname "$0")/.."

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
echo -e "${BLUE}🚀 chatwork-webhook デプロイスクリプト${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

if [ "$DRY_RUN" = true ]; then
    echo -e "${YELLOW}📋 ドライランモード（デプロイしない）${NC}"
    echo ""
fi

# =============================================================================
# Step 1: lib/ 同期チェック
# =============================================================================

echo -e "${BLUE}🔍 Step 1: lib/ 同期チェック${NC}"
echo ""

if ! ./scripts/sync_lib.sh --check; then
    echo ""
    echo -e "${RED}❌ lib/ が同期されていません${NC}"
    echo ""
    echo "修正するには以下を実行:"
    echo "  ./scripts/sync_lib.sh"
    echo ""
    echo "または自動修正してデプロイ:"
    echo "  ./scripts/sync_lib.sh && ./chatwork-webhook/deploy.sh"
    exit 1
fi

echo ""

# =============================================================================
# Step 2: テスト実行
# =============================================================================

if [ "$SKIP_TESTS" = true ]; then
    echo -e "${YELLOW}⚠️ Step 2: テストをスキップ${NC}"
    echo ""
else
    echo -e "${BLUE}🧪 Step 2: テスト実行${NC}"
    echo ""

    # 主要テストを実行
    if ! pytest tests/test_neural_connection_repair.py tests/test_goal_handler.py -v --tb=short 2>&1 | tail -20; then
        echo ""
        echo -e "${RED}❌ テストが失敗しました${NC}"
        echo ""
        echo "テストをスキップしてデプロイする場合:"
        echo "  ./chatwork-webhook/deploy.sh --skip-tests"
        exit 1
    fi

    echo ""
    echo -e "${GREEN}✅ テスト成功${NC}"
    echo ""
fi

# =============================================================================
# Step 3: 環境確認
# =============================================================================

echo -e "${BLUE}🔧 Step 3: 環境確認${NC}"
echo ""

# gcloud が利用可能か確認
if ! command -v gcloud &> /dev/null; then
    echo -e "${RED}❌ gcloud CLI がインストールされていません${NC}"
    exit 1
fi

# プロジェクト確認
PROJECT=$(gcloud config get-value project 2>/dev/null)
if [ -z "$PROJECT" ]; then
    echo -e "${RED}❌ GCPプロジェクトが設定されていません${NC}"
    echo "  gcloud config set project <project-id>"
    exit 1
fi

echo -e "  プロジェクト: ${GREEN}$PROJECT${NC}"
echo ""

# =============================================================================
# Step 4: デプロイ
# =============================================================================

if [ "$DRY_RUN" = true ]; then
    echo -e "${BLUE}📋 Step 4: デプロイコマンド（実行されません）${NC}"
    echo ""
    echo "  gcloud functions deploy chatwork-webhook \\"
    echo "    --source=chatwork-webhook \\"
    echo "    --runtime=python311 \\"
    echo "    --trigger-http \\"
    echo "    --region=asia-northeast1 \\"
    echo "    --memory=512MB \\"
    echo "    --timeout=540s \\"
    echo "    --no-allow-unauthenticated"
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo -e "${GREEN}✅ ドライラン完了（全チェックパス）${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    exit 0
fi

echo -e "${BLUE}🚀 Step 4: デプロイ実行${NC}"
echo ""

gcloud functions deploy chatwork-webhook \
    --source=chatwork-webhook \
    --runtime=python311 \
    --trigger-http \
    --region=asia-northeast1 \
    --memory=512MB \
    --timeout=540s \
    --no-allow-unauthenticated

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${GREEN}✅ デプロイ完了${NC}"
echo ""
echo "  デプロイ先: chatwork-webhook"
echo "  プロジェクト: $PROJECT"
echo "  リージョン: asia-northeast1"
echo ""
echo "ログ確認:"
echo "  gcloud functions logs read chatwork-webhook --limit=50"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
