#!/bin/bash
#
# Promptfoo LLMテスト実行スクリプト
#
# 使い方:
#   ./scripts/run_promptfoo.sh              # 通常実行
#   ./scripts/run_promptfoo.sh --no-cache   # キャッシュなし
#   ./scripts/run_promptfoo.sh --view       # 結果をブラウザで表示
#
# 環境変数:
#   OPENROUTER_API_KEY: OpenRouter APIキー（必須）
#     1. 環境変数から取得
#     2. GCP Secret Manager から取得（openrouter-api-key）
#

set -e

echo "🐺 ソウルくん Promptfoo LLMテスト 🐺"
echo "========================================"

# プロジェクトルートに移動
cd "$(dirname "$0")/.."

# promptfoo がインストールされているか確認
if ! command -v promptfoo &> /dev/null; then
    echo "❌ promptfoo がインストールされていません"
    echo "   npm install -g promptfoo"
    exit 1
fi

# OpenRouter APIキー取得
if [ -z "$OPENROUTER_API_KEY" ]; then
    echo "📡 GCP Secret Manager から OPENROUTER_API_KEY を取得中..."
    OPENROUTER_API_KEY=$(gcloud secrets versions access latest --secret="openrouter-api-key" 2>/dev/null || true)
    if [ -z "$OPENROUTER_API_KEY" ]; then
        echo "❌ OPENROUTER_API_KEY が設定されていません"
        echo "   export OPENROUTER_API_KEY='sk-or-...'"
        echo "   または GCP Secret Manager に openrouter-api-key を登録してください"
        exit 1
    fi
    export OPENROUTER_API_KEY
    echo "✅ Secret Manager から取得完了"
fi

# 引数処理
VIEW_MODE=false
EXTRA_ARGS=""
for arg in "$@"; do
    case "$arg" in
        --view)
            VIEW_MODE=true
            ;;
        *)
            EXTRA_ARGS="$EXTRA_ARGS $arg"
            ;;
    esac
done

# 結果ディレクトリ作成
mkdir -p promptfoo/results

if [ "$VIEW_MODE" = true ]; then
    echo "📊 前回の結果をブラウザで表示..."
    cd promptfoo && promptfoo view
else
    echo ""
    echo "🔍 テスト実行中..."
    echo "   Config: promptfoo/promptfooconfig.yaml"
    echo "   Provider: OpenRouter (gpt-4o-mini)"
    echo ""
    cd promptfoo && promptfoo eval $EXTRA_ARGS

    echo ""
    echo "========================================"
    echo "✅ テスト完了！"
    echo ""
    echo "結果ファイル: promptfoo/results/latest.json"
    echo "ブラウザで確認: ./scripts/run_promptfoo.sh --view"
fi
