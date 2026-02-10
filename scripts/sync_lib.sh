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
# 同期方式:
#   - chatwork-webhook/lib/: rsyncミラー（lib/の完全コピー + 独自ファイル保護）
#   - proactive-monitor/lib/: rsyncミラー（lib/の完全コピー）
#   - その他Functions: 選択的ファイル同期（必要なファイルのみ）
#
# v10.53.0: 初版作成（大規模修繕対応）
# v10.70.0: rsyncミラー方式に改修（Codexレビュー C-4/D-4 対応）
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

# rsyncミラー同期（lib/ → target/lib/ の完全ミラー）
# target独自ファイルを保護するexcludeリスト対応
sync_mirror() {
    local src=$1
    local dst=$2
    shift 2
    # 残りの引数はrsyncの--excludeオプション
    local excludes=("$@")

    if [ ! -d "$src" ]; then
        return 0
    fi

    # rsync用のexcludeオプションを構築
    local rsync_excludes=("--exclude=__pycache__" "--exclude=*.pyc")
    for exc in "${excludes[@]}"; do
        rsync_excludes+=("--exclude=$exc")
    done

    if [ "$CHECK_ONLY" = true ]; then
        # --dry-run で差分確認
        local diff_output
        diff_output=$(rsync -avcn --delete "${rsync_excludes[@]}" "$src/" "$dst/" 2>/dev/null | grep -v '^$' | grep -v '^sending' | grep -v '^sent ' | grep -v '^total ' | grep -v '^\./$' | grep -v '/$' | grep -v '^Transfer ' || true)
        if [ -n "$diff_output" ]; then
            echo -e "  ${RED}❌ Out of sync:${NC} $dst"
            echo "$diff_output" | head -10 | sed 's/^/      /'
            local count
            count=$(echo "$diff_output" | wc -l | tr -d ' ')
            if [ "$count" -gt 10 ]; then
                echo "      ... and $((count - 10)) more"
            fi
            ERRORS_FOUND=1
        else
            echo -e "  ${GREEN}✅ In sync:${NC} $dst"
        fi
    else
        echo -e "  ${GREEN}📁 Mirror syncing:${NC} $dst"
        mkdir -p "$dst"
        rsync -av --delete "${rsync_excludes[@]}" "$src/" "$dst/" > /dev/null
        SYNCED_COUNT=$((SYNCED_COUNT + 1))
    fi
}

# =============================================================================
# 1. chatwork-webhook/lib/ (rsyncミラー)
# =============================================================================

echo -e "${BLUE}📦 [1/3] chatwork-webhook/lib/ (ミラー同期)${NC}"
echo ""

if [ "$BRAIN_ONLY" = true ]; then
    echo "  → brain/ のみ"
    sync_mirror "lib/brain" "chatwork-webhook/lib/brain" "handler_wrappers.py"
else
    # chatwork-webhook独自ファイルを保護（lib/に存在しないもの）
    # - brain/handler_wrappers.py: chatwork-webhook専用のハンドラーラッパー
    # - persona/: chatwork-webhook専用のペルソナモジュール
    sync_mirror "lib" "chatwork-webhook/lib" "brain/handler_wrappers.py" "persona"
fi

echo ""

# =============================================================================
# 2. proactive-monitor/lib/ (rsyncミラー)
# =============================================================================

echo -e "${BLUE}📦 [2/3] proactive-monitor/lib/ (ミラー同期)${NC}"
echo ""

if [ "$BRAIN_ONLY" = true ]; then
    echo "  → brain/ のみ"
    sync_mirror "lib/brain" "proactive-monitor/lib/brain"
else
    # proactive-monitorには独自ファイルなし → 完全ミラー
    sync_mirror "lib" "proactive-monitor/lib"
fi

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
# 3. その他のCloud Functions（選択的同期）
# =============================================================================

echo -e "${BLUE}📦 [3/3] その他のCloud Functions（選択的同期）${NC}"
echo ""

# feature_flags.py
for dir in sync-chatwork-tasks remind-tasks watch-google-drive pattern-detection; do
    if [ -d "$dir/lib" ]; then
        sync_file "lib/feature_flags.py" "$dir/lib/feature_flags.py"
    fi
done

# text_utils.py
for dir in remind-tasks sync-chatwork-tasks check-reply-messages cleanup-old-data pattern-detection; do
    if [ -d "$dir/lib" ]; then
        sync_file "lib/text_utils.py" "$dir/lib/text_utils.py"
    fi
done

# mvv_context.py
sync_file "lib/mvv_context.py" "report-generator/lib/mvv_context.py"

# report_generator.py
sync_file "lib/report_generator.py" "report-generator/lib/report_generator.py"

# audit.py
for dir in sync-chatwork-tasks pattern-detection; do
    if [ -d "$dir/lib" ]; then
        sync_file "lib/audit.py" "$dir/lib/audit.py"
    fi
done

# business_day.py
sync_file "lib/business_day.py" "remind-tasks/lib/business_day.py"

# detection/ → pattern-detection
if [ -d "pattern-detection/lib" ]; then
    echo ""
    echo "  → pattern-detection/lib/detection/"
    sync_mirror "lib/detection" "pattern-detection/lib/detection"
fi

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
