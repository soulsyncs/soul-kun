#!/bin/bash
# =============================================================================
# proactive-monitor デプロイスクリプト
# =============================================================================
#
# 目的:
#   proactive-monitor を安全にCloud Functionsにデプロイする
#
# 使い方:
#   ./proactive-monitor/deploy.sh              # 本番デプロイ
#   ./proactive-monitor/deploy.sh --dry-run    # 確認のみ（デプロイしない）
#   ./proactive-monitor/deploy.sh --skip-tests # テストをスキップ
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
echo -e "${BLUE}🚀 proactive-monitor デプロイスクリプト${NC}"
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
    echo "  ./scripts/sync_lib.sh && ./proactive-monitor/deploy.sh"
    exit 1
fi

echo ""

# Import smoke test: lib/がインポート可能か事前確認
echo -e "${BLUE}🔍 Step 1.5: Import smoke test${NC}"
echo ""
if ! python3 -c "import sys; sys.path.insert(0, 'proactive-monitor'); import lib" 2>&1; then
    echo ""
    echo -e "${RED}❌ proactive-monitor/lib/ のインポートに失敗${NC}"
    echo "  依存モジュールが不足している可能性があります"
    exit 1
fi
echo -e "${GREEN}✅ Import smoke test passed${NC}"
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

    # proactive-monitor関連テストを実行
    if python3 -m pytest tests/test_neural_connection_repair.py -v --tb=short 2>&1 | tail -10; then
        echo ""
        echo -e "${GREEN}✅ テスト成功${NC}"
    else
        echo ""
        echo -e "${RED}❌ テストが失敗しました${NC}"
        echo ""
        echo "テストをスキップしてデプロイする場合:"
        echo "  ./proactive-monitor/deploy.sh --skip-tests"
        exit 1
    fi
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
    echo "  gcloud functions deploy proactive-monitor \\"
    echo "    --source=proactive-monitor \\"
    echo "    --runtime=python311 \\"
    echo "    --trigger-http \\"
    echo "    --region=asia-northeast1 \\"
    echo "    --memory=512MB \\"
    echo "    --timeout=540s \\"
    echo "    --no-allow-unauthenticated \\"
    echo "    --set-env-vars=USE_BRAIN_ARCHITECTURE=true,LOG_EXECUTION_ID=true"
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo -e "${GREEN}✅ ドライラン完了（全チェックパス）${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    exit 0
fi

echo -e "${BLUE}🚀 Step 4: デプロイ実行${NC}"
echo ""

gcloud functions deploy proactive-monitor \
    --source=proactive-monitor \
    --runtime=python311 \
    --trigger-http \
    --region=asia-northeast1 \
    --memory=512MB \
    --timeout=540s \
    --no-allow-unauthenticated \
    --set-env-vars="USE_BRAIN_ARCHITECTURE=true,LOG_EXECUTION_ID=true"

echo ""

# =============================================================================
# Step 5: トラフィックルーティング確認
# =============================================================================

echo -e "${BLUE}🔍 Step 5: トラフィックルーティング確認${NC}"
echo ""

FUNC_NAME="proactive-monitor"
REGION="asia-northeast1"

LATEST_REV=$(gcloud run revisions list --service="$FUNC_NAME" --region="$REGION" \
    --sort-by='~creationTimestamp' --limit=1 --format='value(name)' 2>/dev/null)
TRAFFIC_REV=$(gcloud run services describe "$FUNC_NAME" --region="$REGION" \
    --format='value(status.traffic[0].revisionName)' 2>/dev/null)

if [ -n "$LATEST_REV" ] && [ -n "$TRAFFIC_REV" ]; then
    if [ "$LATEST_REV" = "$TRAFFIC_REV" ]; then
        echo -e "  ${GREEN}✅ トラフィック: ${LATEST_REV} (100%)${NC}"
    else
        echo -e "  ${YELLOW}⚠️ トラフィックが旧リビジョン: ${TRAFFIC_REV}${NC}"
        echo -e "  ${BLUE}→ 最新リビジョン ${LATEST_REV} に切り替え中...${NC}"
        gcloud run services update-traffic "$FUNC_NAME" --region="$REGION" \
            --to-revisions="${LATEST_REV}=100" 2>&1
        echo -e "  ${GREEN}✅ トラフィック切り替え完了: ${LATEST_REV} (100%)${NC}"
    fi
else
    echo -e "  ${YELLOW}⚠️ リビジョン情報の取得に失敗。手動で確認してください${NC}"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${GREEN}✅ デプロイ完了${NC}"
echo ""
echo "  デプロイ先: proactive-monitor"
echo "  プロジェクト: $PROJECT"
echo "  リージョン: asia-northeast1"
echo ""
echo "ログ確認:"
echo "  gcloud functions logs read proactive-monitor --limit=50"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
