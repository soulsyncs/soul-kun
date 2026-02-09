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
# 同期方針:
#   - 既存ファイル同期: ターゲットに同名ファイルが存在する場合は自動同期
#   - 必須ファイル作成: __init__.pyのeager importが参照するモジュールは
#     ターゲットに存在しなくても自動作成する（デプロイ失敗防止）
#   - サブディレクトリ: ターゲットにディレクトリが存在する場合のみ同期
#
# v10.53.0: 初版作成（大規模修繕対応）
# v10.54.0: 自動検出方式に変更（手動リスト→既存ファイル自動同期）
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
    local src="$1"
    local dst="$2"

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
    local src="$1"
    local dst="$2"

    if [ ! -d "$src" ]; then
        return 0
    fi

    # ターゲットディレクトリが存在しない場合
    if [ ! -d "$dst" ]; then
        if [ "$CHECK_ONLY" = true ]; then
            echo -e "  ${RED}⚠️ Missing dir:${NC} $dst"
            ERRORS_FOUND=1
        fi
        return 0
    fi

    if [ "$CHECK_ONLY" = true ]; then
        # 差分確認（handler_wrappers.pyは本番専用なので除外）
        local diff_output
        diff_output=$(diff -rq "$src" "$dst" --exclude="__pycache__" --exclude="*.pyc" --exclude="handler_wrappers.py" 2>&1 || true)
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
        rsync -av --exclude="__pycache__" --exclude="*.pyc" --exclude="handler_wrappers.py" "$src/" "$dst/" > /dev/null
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
# 2. __init__.pyのeager importが参照する必須ファイル
# =============================================================================
# lib/__init__.py が起動時にimportするモジュールは、全デプロイターゲットに
# 存在しなければならない。存在しない場合は自動作成する。

echo -e "${BLUE}📦 [2/4] 必須モジュール（__init__.py eager imports）${NC}"
echo ""

# __init__.pyのeager importから参照されるモジュール一覧
REQUIRED_MODULES=(
    config.py
    secrets.py
    db.py
    chatwork.py
    tenant.py
)

# 主要デプロイターゲット（__init__.pyを持つサービス）
DEPLOY_TARGETS=(
    chatwork-webhook
    proactive-monitor
)

for target in "${DEPLOY_TARGETS[@]}"; do
    if [ ! -d "$target/lib" ]; then
        continue
    fi
    for module in "${REQUIRED_MODULES[@]}"; do
        sync_file "lib/$module" "$target/lib/$module"
    done
    # __init__.py自体も必須
    sync_file "lib/__init__.py" "$target/lib/__init__.py"
done

echo ""

# =============================================================================
# 3. 全Cloud Functionのlib/を自動同期
# =============================================================================
# 方針: lib/ 内の各.pyファイルについて、ターゲットに同名ファイルが
# 既に存在する場合は同期する。
# =============================================================================

# 同期対象のCloud Function一覧
SYNC_TARGETS=(
    chatwork-webhook
    proactive-monitor
    pattern-detection
    sync-chatwork-tasks
    remind-tasks
    watch-google-drive
    check-reply-messages
    cleanup-old-data
    report-generator
)

echo -e "${BLUE}📦 [3/4] 共通ファイル（自動検出）${NC}"
echo ""

for target in "${SYNC_TARGETS[@]}"; do
    if [ ! -d "$target/lib" ]; then
        continue
    fi

    # トップレベル .py ファイル同期（find -print0 でスペース安全）
    while IFS= read -r -d '' lib_file; do
        filename=$(basename "$lib_file")
        dst="$target/lib/$filename"
        if [ -f "$dst" ]; then
            sync_file "$lib_file" "$dst"
        fi
    done < <(find lib -maxdepth 1 -name "*.py" -type f -print0 2>/dev/null)
done

echo ""

# =============================================================================
# 4. サブディレクトリ同期（自動検出）
# =============================================================================

echo -e "${BLUE}📦 [4/4] サブディレクトリ（自動検出）${NC}"
echo ""

# lib/ 直下のサブディレクトリを列挙（find -print0 でスペース安全）
while IFS= read -r -d '' lib_subdir; do
    subdir_name=$(basename "$lib_subdir")

    # __pycache__ はスキップ
    if [ "$subdir_name" = "__pycache__" ]; then
        continue
    fi

    # brain/ は Section 1 で処理済み
    if [ "$subdir_name" = "brain" ]; then
        continue
    fi

    for target in "${SYNC_TARGETS[@]}"; do
        dst="$target/lib/$subdir_name"
        if [ -d "$dst" ]; then
            echo "  → $dst/"
            sync_directory "$lib_subdir" "$dst"
        fi
    done
done < <(find lib -maxdepth 1 -mindepth 1 -type d -print0 2>/dev/null)

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
