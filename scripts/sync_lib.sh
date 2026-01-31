#!/bin/bash
# =============================================================================
# lib/ 同期スクリプト
# =============================================================================
#
# 目的:
#   lib/ ディレクトリの変更を全てのCloud Functionsに同期する
#
# 使い方:
#   ./scripts/sync_lib.sh         # 全て同期
#   ./scripts/sync_lib.sh --check # 差分確認のみ（変更なし）
#   ./scripts/sync_lib.sh --brain # brain/のみ同期
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
CHECK_ONLY=false
BRAIN_ONLY=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --check)
            CHECK_ONLY=true
            shift
            ;;
        --brain)
            BRAIN_ONLY=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${BLUE}🔄 lib/ 同期スクリプト${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

if [ "$CHECK_ONLY" = true ]; then
    echo -e "${YELLOW}📋 差分確認モード（変更なし）${NC}"
    echo ""
fi

ERRORS_FOUND=0
SYNCED_COUNT=0

# =============================================================================
# 同期関数
# =============================================================================

sync_file() {
    local src=$1
    local dst=$2

    if [ ! -f "$src" ]; then
        return 0
    fi

    if [ ! -f "$dst" ]; then
        if [ "$CHECK_ONLY" = true ]; then
            echo -e "  ${RED}⚠️ Missing:${NC} $dst"
            ERRORS_FOUND=1
        else
            echo -e "  ${GREEN}➕ Creating:${NC} $dst"
            mkdir -p "$(dirname "$dst")"
            cp "$src" "$dst"
            SYNCED_COUNT=$((SYNCED_COUNT + 1))
        fi
        return 0
    fi

    if ! diff -q "$src" "$dst" > /dev/null 2>&1; then
        if [ "$CHECK_ONLY" = true ]; then
            echo -e "  ${RED}❌ Out of sync:${NC} $dst"
            ERRORS_FOUND=1
        else
            echo -e "  ${GREEN}✏️ Updating:${NC} $dst"
            cp "$src" "$dst"
            SYNCED_COUNT=$((SYNCED_COUNT + 1))
        fi
    fi
}

sync_directory() {
    local src=$1
    local dst=$2

    if [ ! -d "$src" ]; then
        return 0
    fi

    if [ "$CHECK_ONLY" = true ]; then
        # 差分確認（handler_wrappers.pyは本番専用なので除外）
        local diff_output
        diff_output=$(diff -rq "$src" "$dst" --exclude="__pycache__" --exclude="*.pyc" --exclude="handler_wrappers.py" 2>/dev/null || true)
        if [ -n "$diff_output" ]; then
            echo -e "  ${RED}❌ Out of sync:${NC} $dst"
            echo "$diff_output" | head -5 | sed 's/^/      /'
            ERRORS_FOUND=1
        else
            echo -e "  ${GREEN}✅ In sync:${NC} $dst"
        fi
    else
        echo -e "  ${GREEN}📁 Syncing:${NC} $dst"
        mkdir -p "$dst"
        rsync -av --exclude="__pycache__" --exclude="*.pyc" "$src/" "$dst/" > /dev/null
        SYNCED_COUNT=$((SYNCED_COUNT + 1))
    fi
}

# =============================================================================
# 1. brain/ ディレクトリ
# =============================================================================

echo -e "${BLUE}📦 [1/4] brain/ ディレクトリ${NC}"
echo ""

# chatwork-webhook
echo "  → chatwork-webhook/lib/brain/"
sync_directory "lib/brain" "chatwork-webhook/lib/brain"

# proactive-monitor
echo "  → proactive-monitor/lib/brain/"
sync_directory "lib/brain" "proactive-monitor/lib/brain"

echo ""

if [ "$BRAIN_ONLY" = true ]; then
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    if [ "$CHECK_ONLY" = true ]; then
        if [ $ERRORS_FOUND -eq 0 ]; then
            echo -e "${GREEN}✅ brain/ は全て同期済み${NC}"
        else
            echo -e "${RED}❌ 同期が必要なファイルがあります${NC}"
            exit 1
        fi
    else
        echo -e "${GREEN}✅ brain/ 同期完了（$SYNCED_COUNT 件）${NC}"
    fi
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    exit 0
fi

# =============================================================================
# 2. feature_flags.py
# =============================================================================

echo -e "${BLUE}📦 [2/4] feature_flags.py${NC}"
echo ""

for dir in chatwork-webhook proactive-monitor sync-chatwork-tasks remind-tasks watch-google-drive pattern-detection; do
    if [ -d "$dir/lib" ]; then
        sync_file "lib/feature_flags.py" "$dir/lib/feature_flags.py"
    fi
done

echo ""

# =============================================================================
# 3. 共通ファイル
# =============================================================================

echo -e "${BLUE}📦 [3/4] 共通ファイル${NC}"
echo ""

# text_utils.py
for dir in remind-tasks sync-chatwork-tasks chatwork-webhook check-reply-messages cleanup-old-data pattern-detection; do
    if [ -d "$dir/lib" ]; then
        sync_file "lib/text_utils.py" "$dir/lib/text_utils.py"
    fi
done

# goal_setting.py
sync_file "lib/goal_setting.py" "chatwork-webhook/lib/goal_setting.py"

# mvv_context.py
sync_file "lib/mvv_context.py" "chatwork-webhook/lib/mvv_context.py"
sync_file "lib/mvv_context.py" "report-generator/lib/mvv_context.py"

# report_generator.py
sync_file "lib/report_generator.py" "chatwork-webhook/lib/report_generator.py"
sync_file "lib/report_generator.py" "report-generator/lib/report_generator.py"

# audit.py
sync_file "lib/audit.py" "chatwork-webhook/lib/audit.py"
sync_file "lib/audit.py" "sync-chatwork-tasks/lib/audit.py"
sync_file "lib/audit.py" "pattern-detection/lib/audit.py"

# business_day.py
sync_file "lib/business_day.py" "remind-tasks/lib/business_day.py"
sync_file "lib/business_day.py" "chatwork-webhook/lib/business_day.py"

# config.py, db.py, secrets.py
sync_file "lib/config.py" "chatwork-webhook/lib/config.py"
sync_file "lib/db.py" "chatwork-webhook/lib/db.py"
sync_file "lib/secrets.py" "chatwork-webhook/lib/secrets.py"

echo ""

# =============================================================================
# 4. ディレクトリ同期
# =============================================================================

echo -e "${BLUE}📦 [4/4] ディレクトリ${NC}"
echo ""

# memory/
echo "  → memory/"
sync_directory "lib/memory" "chatwork-webhook/lib/memory"

# detection/
echo "  → detection/"
sync_directory "lib/detection" "pattern-detection/lib/detection"

echo ""

# =============================================================================
# 結果
# =============================================================================

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ "$CHECK_ONLY" = true ]; then
    if [ $ERRORS_FOUND -eq 0 ]; then
        echo -e "${GREEN}✅ 全てのlib/は同期されています${NC}"
    else
        echo -e "${RED}❌ 同期が必要なファイルがあります${NC}"
        echo ""
        echo "修正するには以下を実行:"
        echo "  ./scripts/sync_lib.sh"
        exit 1
    fi
else
    echo -e "${GREEN}✅ lib/ 同期完了${NC}"
    if [ $SYNCED_COUNT -gt 0 ]; then
        echo -e "   同期したファイル/ディレクトリ: ${SYNCED_COUNT} 件"
    else
        echo "   (変更なし)"
    fi
fi

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
