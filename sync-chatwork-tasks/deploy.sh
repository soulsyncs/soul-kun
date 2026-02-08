#!/bin/bash
# =====================================================
# sync-chatwork-tasks デプロイスクリプト
# ★★★ v10.14.1: lib/共通化対応 ★★★
# =====================================================
#
# 使い方:
#   ./deploy.sh
#
# このスクリプトは以下を行います:
# 1. soul-kun/lib/ から必要なファイルをコピー
# 2. gcloud functions deploy を実行
# =====================================================

set -e  # エラー時に停止

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LIB_SRC="$SCRIPT_DIR/../lib"
LIB_DST="$SCRIPT_DIR/lib"

echo "=============================================="
echo "sync-chatwork-tasks デプロイ開始"
echo "=============================================="

# 1. lib/ ディレクトリを更新
echo ""
echo "📁 共通ライブラリをコピー中..."
mkdir -p "$LIB_DST"

# 必要なファイルをコピー（v10.18.1: user_utils.py追加）
cp "$LIB_SRC/text_utils.py" "$LIB_DST/"
cp "$LIB_SRC/audit.py" "$LIB_DST/"
cp "$LIB_SRC/user_utils.py" "$LIB_DST/"

echo "   ✅ text_utils.py"
echo "   ✅ audit.py"
echo "   ✅ user_utils.py (v10.18.1)"

# __init__.py が最新か確認
if [ -f "$LIB_DST/__init__.py" ]; then
    echo "   ✅ __init__.py (existing)"
else
    echo "   ⚠️ __init__.py がありません。作成してください。"
    exit 1
fi

# 2. デプロイ実行
echo ""
echo "🚀 Cloud Functions にデプロイ中..."
gcloud functions deploy sync-chatwork-tasks \
    --gen2 \
    --runtime=python311 \
    --region=asia-northeast1 \
    --source="$SCRIPT_DIR" \
    --entry-point=sync_chatwork_tasks \
    --trigger-http \
    --no-allow-unauthenticated \
    --memory=512MB \
    --timeout=540s \
    --set-secrets=CHATWORK_API_TOKEN=CHATWORK_API_TOKEN:latest,SOULKUN_CHATWORK_TOKEN=SOULKUN_CHATWORK_TOKEN:latest,ANTHROPIC_API_KEY=ANTHROPIC_API_KEY:latest,GOOGLE_AI_API_KEY=GOOGLE_AI_API_KEY:latest

echo ""
echo "=============================================="
echo "✅ デプロイ完了"
echo "=============================================="
