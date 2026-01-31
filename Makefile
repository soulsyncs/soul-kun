# =============================================================================
# ソウルくん Makefile
# =============================================================================
#
# よく使うコマンドをまとめたMakefile
#
# 使い方:
#   make help          # ヘルプ表示
#   make sync          # lib/ を全Cloud Functionsに同期
#   make test          # テスト実行
#   make deploy        # chatwork-webhookをデプロイ
#
# v10.53.0: 初版作成（大規模修繕対応）
# =============================================================================

.PHONY: help sync sync-check sync-brain test test-quick deploy deploy-dry-run deploy-all deploy-proactive logs logs-proactive clean

# デフォルトターゲット
.DEFAULT_GOAL := help

# =============================================================================
# ヘルプ
# =============================================================================

help: ## ヘルプを表示
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "🤖 ソウルくん Makefile"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo ""
	@echo "使用可能なコマンド:"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo ""

# =============================================================================
# 同期
# =============================================================================

sync: ## lib/ を全Cloud Functionsに同期
	@./scripts/sync_lib.sh

sync-check: ## lib/ の同期状態を確認（変更なし）
	@./scripts/sync_lib.sh --check

sync-brain: ## lib/brain/ のみ同期
	@./scripts/sync_lib.sh --brain

# =============================================================================
# テスト
# =============================================================================

test: ## 全テストを実行
	@echo "🧪 テスト実行中..."
	@pytest tests/ -v --tb=short

test-quick: ## 主要テストのみ実行（高速）
	@echo "🧪 クイックテスト実行中..."
	@pytest tests/test_neural_connection_repair.py tests/test_goal_handler.py -v --tb=short

test-brain: ## LLM Brain関連テストを実行
	@echo "🧪 LLM Brainテスト実行中..."
	@pytest tests/test_llm_brain*.py -v --tb=short

test-coverage: ## カバレッジ付きでテスト実行
	@echo "🧪 カバレッジテスト実行中..."
	@pytest tests/ --cov=lib --cov-report=html --cov-report=term-missing

# =============================================================================
# デプロイ
# =============================================================================

deploy: ## chatwork-webhookをデプロイ（同期チェック・テスト付き）
	@./chatwork-webhook/deploy.sh

deploy-dry-run: ## デプロイのドライラン（確認のみ）
	@./chatwork-webhook/deploy.sh --dry-run

deploy-force: ## テストをスキップしてデプロイ（緊急時のみ）
	@echo "⚠️  テストをスキップしてデプロイします"
	@./chatwork-webhook/deploy.sh --skip-tests

deploy-proactive: ## proactive-monitorをデプロイ
	@./proactive-monitor/deploy.sh

deploy-proactive-dry-run: ## proactive-monitorのドライラン
	@./proactive-monitor/deploy.sh --dry-run

deploy-all: ## 全Cloud Functionsをデプロイ
	@echo "🚀 全Cloud Functionsをデプロイします..."
	@echo ""
	@echo "=== chatwork-webhook ==="
	@./chatwork-webhook/deploy.sh --skip-tests
	@echo ""
	@echo "=== proactive-monitor ==="
	@./proactive-monitor/deploy.sh --skip-tests
	@echo ""
	@echo "✅ 全デプロイ完了"

# =============================================================================
# ログ
# =============================================================================

logs: ## 本番ログを表示（最新50件）
	@gcloud functions logs read chatwork-webhook --limit=50

logs-error: ## エラーログのみ表示
	@gcloud functions logs read chatwork-webhook --limit=100 --min-log-level=ERROR

logs-brain: ## Brain関連ログを表示
	@gcloud functions logs read chatwork-webhook --limit=100 | grep -i brain

logs-proactive: ## proactive-monitorのログを表示
	@gcloud functions logs read proactive-monitor --limit=50

logs-proactive-error: ## proactive-monitorのエラーログ
	@gcloud functions logs read proactive-monitor --limit=100 --min-log-level=ERROR

# =============================================================================
# 開発
# =============================================================================

lint: ## コードのリントチェック
	@echo "🔍 リントチェック中..."
	@python -m py_compile lib/brain/*.py
	@python -m py_compile lib/*.py
	@echo "✅ 構文エラーなし"

format: ## コードフォーマット（black）
	@echo "🎨 フォーマット中..."
	@black lib/ tests/ --line-length=100 || echo "blackがインストールされていません"

# =============================================================================
# クリーンアップ
# =============================================================================

clean: ## キャッシュファイルを削除
	@echo "🧹 クリーンアップ中..."
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	@echo "✅ クリーンアップ完了"

# =============================================================================
# 便利なショートカット
# =============================================================================

s: sync ## 'make sync' のショートカット
t: test ## 'make test' のショートカット
d: deploy ## 'make deploy' のショートカット
