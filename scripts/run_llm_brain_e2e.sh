#!/bin/bash
#
# LLM Brain E2Eテスト実行スクリプト
#
# 使い方:
#
#   【ローカル開発】
#   export OPENROUTER_API_KEY="sk-or-..."
#   ./scripts/run_llm_brain_e2e.sh
#
#   【本番環境】
#   GCP Secret Manager に "openrouter-api-key" が設定されていれば自動取得
#
# 設計書: docs/25_llm_native_brain_architecture.md
#
# APIキー取得優先順位:
#   1. 環境変数 OPENROUTER_API_KEY
#   2. GCP Secret Manager (openrouter-api-key)
#   3. 環境変数 ANTHROPIC_API_KEY (フォールバック)
#

set -e

echo "🐺 ソウルくん LLM Brain E2Eテスト 🐺"
echo "========================================"

# プロジェクトルートに移動
cd "$(dirname "$0")/.."

# 環境変数チェック（情報表示のみ、テスト自体が詳細チェックを行う）
echo ""
echo "📋 環境変数チェック:"

if [ -n "$OPENROUTER_API_KEY" ]; then
    echo "✅ OPENROUTER_API_KEY: 設定済み (環境変数)"
elif [ -n "$ANTHROPIC_API_KEY" ]; then
    echo "⚠️  OPENROUTER_API_KEY: 未設定"
    echo "✅ ANTHROPIC_API_KEY: 設定済み (フォールバック)"
else
    echo "⚠️  環境変数にAPIキーなし"
    echo "   → GCP Secret Manager から取得を試みます"
fi

# ENABLE_LLM_BRAIN を強制有効化（テスト用）
export ENABLE_LLM_BRAIN=true
echo "✅ ENABLE_LLM_BRAIN: true (テスト用に強制有効化)"

# 仮想環境のアクティベート（存在する場合）
if [ -d "venv" ]; then
    echo ""
    echo "📦 仮想環境をアクティベート (venv)..."
    source venv/bin/activate
elif [ -d ".venv" ]; then
    echo ""
    echo "📦 仮想環境をアクティベート (.venv)..."
    source .venv/bin/activate
fi

echo ""
echo "🧪 E2Eテストを実行..."
echo "========================================"
echo ""

# E2Eテスト実行
python3 -m tests.e2e.test_llm_brain_e2e

echo ""
echo "========================================"
echo "✅ テスト完了"
