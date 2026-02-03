#!/bin/bash
# =============================================================================
# Git Hooks セットアップスクリプト
# =============================================================================
#
# 使い方:
#   ./scripts/setup_hooks.sh
#
# このスクリプトは以下のhooksをインストールします：
#   - pre-commit: lib/ 同期チェック
#   - pre-push: Codexレビュー
# =============================================================================

set -euo pipefail

# カラー出力
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
HOOKS_SRC="$SCRIPT_DIR/hooks"
HOOKS_DST="$REPO_ROOT/.git/hooks"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${YELLOW}🔧 Git Hooks セットアップ${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# pre-commit
if [ -f "$HOOKS_SRC/pre-commit" ]; then
    cp "$HOOKS_SRC/pre-commit" "$HOOKS_DST/pre-commit"
    chmod +x "$HOOKS_DST/pre-commit"
    echo -e "${GREEN}✅ pre-commit hook をインストールしました${NC}"
else
    echo -e "${RED}❌ pre-commit hook が見つかりません${NC}"
fi

# pre-push
if [ -f "$HOOKS_SRC/pre-push" ]; then
    cp "$HOOKS_SRC/pre-push" "$HOOKS_DST/pre-push"
    chmod +x "$HOOKS_DST/pre-push"
    echo -e "${GREEN}✅ pre-push hook をインストールしました${NC}"
else
    echo -e "${RED}❌ pre-push hook が見つかりません${NC}"
fi

echo ""
echo -e "${GREEN}セットアップ完了！${NC}"
echo ""
echo "インストールされたhooks:"
echo "  - pre-commit: コミット前にlib/の同期をチェック"
echo "  - pre-push: プッシュ前にCodexレビューを実行"
echo ""
