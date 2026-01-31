#!/bin/bash
# =============================================================================
# デプロイ設定検証スクリプト
# =============================================================================
#
# 目的:
#   デプロイ関連ファイルの整合性を検証する
#
# 使い方:
#   ./scripts/validate_deploy_config.sh
#
# チェック項目:
#   1. 環境変数名の一貫性
#   2. デプロイ設定の一貫性
#   3. 同期状態
#
# v10.53.1: 初版作成（環境変数不一致問題の再発防止）
# =============================================================================

set -e

# カラー出力
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${BLUE}🔍 デプロイ設定検証${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

ERRORS=0

# =============================================================================
# チェック1: 環境変数名の一貫性
# =============================================================================

echo -e "${BLUE}📋 [1/4] 環境変数名の一貫性チェック${NC}"

# 正しい環境変数名
CORRECT_VAR="USE_BRAIN_ARCHITECTURE"
# 間違った環境変数名（使ってはいけない）
WRONG_VAR="ENABLE_LLM_BRAIN"

# cloudbuild.yamlで正しい変数が使われているか
if grep -q "$CORRECT_VAR" cloudbuild.yaml 2>/dev/null; then
    echo -e "  ✅ cloudbuild.yaml: $CORRECT_VAR 使用"
else
    echo -e "  ${RED}❌ cloudbuild.yaml: $CORRECT_VAR が見つからない${NC}"
    ERRORS=$((ERRORS + 1))
fi

if grep -q "$WRONG_VAR" cloudbuild.yaml 2>/dev/null; then
    echo -e "  ${RED}❌ cloudbuild.yaml: 非推奨の $WRONG_VAR が使われている${NC}"
    ERRORS=$((ERRORS + 1))
fi

# cloudbuild-proactive-monitor.yamlも同様
if grep -q "$CORRECT_VAR" cloudbuild-proactive-monitor.yaml 2>/dev/null; then
    echo -e "  ✅ cloudbuild-proactive-monitor.yaml: $CORRECT_VAR 使用"
else
    echo -e "  ${RED}❌ cloudbuild-proactive-monitor.yaml: $CORRECT_VAR が見つからない${NC}"
    ERRORS=$((ERRORS + 1))
fi

echo ""

# =============================================================================
# チェック2: デプロイ設定の一貫性
# =============================================================================

echo -e "${BLUE}📋 [2/4] デプロイ設定の一貫性チェック${NC}"

# --allow-unauthenticated が設定されているか
for file in cloudbuild.yaml cloudbuild-proactive-monitor.yaml chatwork-webhook/deploy.sh proactive-monitor/deploy.sh; do
    if [ -f "$file" ]; then
        if grep -q "\-\-allow-unauthenticated" "$file" 2>/dev/null; then
            echo -e "  ✅ $file: --allow-unauthenticated 設定済み"
        else
            echo -e "  ${RED}❌ $file: --allow-unauthenticated がない${NC}"
            ERRORS=$((ERRORS + 1))
        fi
    fi
done

echo ""

# =============================================================================
# チェック3: lib/同期状態
# =============================================================================

echo -e "${BLUE}📋 [3/4] lib/ 同期状態チェック${NC}"

./scripts/sync_lib.sh --check 2>&1 | tail -5

echo ""

# =============================================================================
# チェック4: async/sync対応チェック
# =============================================================================

echo -e "${BLUE}📋 [4/4] コードパターンチェック${NC}"

# state_manager.pyに_update_step_syncがあるか
if grep -q "_update_step_sync" lib/brain/state_manager.py 2>/dev/null; then
    echo -e "  ✅ state_manager.py: sync対応済み"
else
    echo -e "  ${YELLOW}⚠️ state_manager.py: _update_step_sync が見つからない${NC}"
fi

# NO_CONFIRMATION_ACTIONSがあるか
if grep -q "NO_CONFIRMATION_ACTIONS" lib/brain/constants.py 2>/dev/null; then
    echo -e "  ✅ constants.py: NO_CONFIRMATION_ACTIONS 定義済み"
else
    echo -e "  ${YELLOW}⚠️ constants.py: NO_CONFIRMATION_ACTIONS が見つからない${NC}"
fi

echo ""

# =============================================================================
# 結果
# =============================================================================

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [ $ERRORS -gt 0 ]; then
    echo -e "${RED}❌ 検証失敗: $ERRORS 個のエラー${NC}"
    exit 1
else
    echo -e "${GREEN}✅ 全ての検証に合格${NC}"
fi
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
