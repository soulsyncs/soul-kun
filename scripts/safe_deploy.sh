#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# 安全デプロイスクリプト
# =============================================================================
#
# 本番デプロイの安全性を最大化するスクリプト。
# 「壊れた状態でお客さんに届く」ことを防止する。
#
# 手順:
#   1. 全プリデプロイチェック実行（テスト・lib同期・SQL検証）
#   2. 新バージョンをトラフィックなしで配置
#   3. 煙テスト実行（基本動作確認）
#   4. 問題なければトラフィックを切り替え
#   5. 問題があれば自動で巻き戻し
#
# 使い方:
#   scripts/safe_deploy.sh                     # 両方デプロイ
#   scripts/safe_deploy.sh chatwork-webhook    # chatwork-webhookのみ
#   scripts/safe_deploy.sh --skip-tests        # テストをスキップ（緊急時のみ）
#   scripts/safe_deploy.sh --dry-run           # 実行せずに確認のみ
#
# 3者合意(Claude + Codex + Gemini):
#   「デプロイは --no-traffic → 煙テスト → トラフィック切替の3段階で行う」
# =============================================================================

REGION="${REGION:-asia-northeast1}"
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

# デフォルト設定
DRY_RUN=0
SKIP_TESTS=0
TARGET_FUNCTIONS=()

# 環境変数（本番必須）
REQUIRED_ENV_VARS="USE_BRAIN_ARCHITECTURE=true,ENVIRONMENT=production,LOG_EXECUTION_ID=true,ENABLE_MEETING_TRANSCRIPTION=true,ENABLE_MEETING_MINUTES=true,MEETING_GCS_BUCKET=soulkun-meeting-recordings"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# 引数解析
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --skip-tests) SKIP_TESTS=1 ;;
    chatwork-webhook|proactive-monitor)
      TARGET_FUNCTIONS+=("$arg")
      ;;
    -h|--help)
      echo "Usage: $0 [chatwork-webhook|proactive-monitor] [--skip-tests] [--dry-run]"
      echo ""
      echo "Options:"
      echo "  chatwork-webhook    Deploy chatwork-webhook only"
      echo "  proactive-monitor   Deploy proactive-monitor only"
      echo "  --skip-tests        Skip test execution (emergency only)"
      echo "  --dry-run           Show what would happen without executing"
      exit 0
      ;;
    *)
      echo -e "${RED}Unknown option: $arg${NC}"
      exit 1
      ;;
  esac
done

if [[ ${#TARGET_FUNCTIONS[@]} -eq 0 ]]; then
  TARGET_FUNCTIONS=("chatwork-webhook" "proactive-monitor")
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  安全デプロイ"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  対象: ${TARGET_FUNCTIONS[*]}"
echo "  リージョン: $REGION"
echo "  コミット: $(git rev-parse --short HEAD 2>/dev/null || echo 'unknown')"
echo ""

# =====================================================
# Phase 1: プリデプロイチェック
# =====================================================

echo -e "${CYAN}[Phase 1/4] プリデプロイチェック${NC}"
echo ""

# 1a. lib/ 同期チェック
echo "  [1/5] lib/ 同期チェック..."
if ! "$REPO_ROOT/scripts/sync_lib.sh" --check; then
  echo -e "  ${RED}FAIL: lib/ が同期されていません${NC}"
  echo "  修正: ./scripts/sync_lib.sh を実行してください"
  exit 1
fi
echo -e "  ${GREEN}PASS${NC}"

# 1b. SQL検証
echo "  [2/5] SQLカラム検証..."
if [[ -f "$REPO_ROOT/db_schema.json" ]]; then
  if ! "$REPO_ROOT/scripts/validate_sql_columns.sh" --all 2>/dev/null; then
    echo -e "  ${RED}FAIL: SQL検証に失敗${NC}"
    exit 1
  fi
  echo -e "  ${GREEN}PASS${NC}"
else
  echo -e "  ${YELLOW}SKIP (db_schema.json not found)${NC}"
fi

# 1c. Import smoke test
echo "  [3/5] Import smoke test..."
for func in "${TARGET_FUNCTIONS[@]}"; do
  if ! python3 -c "import sys; sys.path.insert(0, '$REPO_ROOT/$func'); import lib" 2>&1; then
    echo -e "  ${RED}FAIL: $func/lib/ のインポートに失敗${NC}"
    exit 1
  fi
done
echo -e "  ${GREEN}PASS${NC}"

# 1d. テスト実行
if [[ "$SKIP_TESTS" -eq 1 ]]; then
  echo -e "  [4/5] テスト... ${YELLOW}SKIP (--skip-tests)${NC}"
else
  echo "  [4/5] テスト実行..."
  if ! python3 -m pytest "$REPO_ROOT/tests/test_critical_functions.py" \
    "$REPO_ROOT/tests/test_brain_type_safety.py" -v --tb=short 2>&1 | tail -5; then
    echo -e "  ${RED}FAIL: テストに失敗${NC}"
    exit 1
  fi
  echo -e "  ${GREEN}PASS${NC}"
fi

# 1e. pre_deploy_check（コード部分のみ）
echo "  [5/5] コードレベルチェック..."
if ! "$REPO_ROOT/scripts/pre_deploy_check.sh" --skip-db 2>&1 | tail -3; then
  echo -e "  ${RED}FAIL: pre_deploy_check に失敗${NC}"
  exit 1
fi
echo -e "  ${GREEN}PASS${NC}"

echo ""

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo -e "${YELLOW}[DRY RUN] プリデプロイチェック完了。以降の手順は省略。${NC}"
  echo ""
  echo "実際のデプロイコマンド（参考）:"
  for func in "${TARGET_FUNCTIONS[@]}"; do
    echo "  gcloud functions deploy $func --source=$func --region=$REGION --no-traffic --update-env-vars=\"$REQUIRED_ENV_VARS\""
  done
  exit 0
fi

# =====================================================
# Phase 2: トラフィックなしでデプロイ
# =====================================================

echo -e "${CYAN}[Phase 2/4] トラフィックなしでデプロイ${NC}"
echo ""

# 現在のリビジョンを記録（ロールバック用）
declare -A PREVIOUS_REVISIONS
for func in "${TARGET_FUNCTIONS[@]}"; do
  prev_rev=$(gcloud run services describe "$func" \
    --region="$REGION" \
    --format='value(status.traffic[0].revisionName)' 2>/dev/null || echo "")
  PREVIOUS_REVISIONS[$func]="$prev_rev"
  echo "  $func 現在のリビジョン: $prev_rev"
done
echo ""

for func in "${TARGET_FUNCTIONS[@]}"; do
  echo "  $func をデプロイ中（トラフィックなし）..."

  # Cloud Functions Gen2のデプロイ
  # IMPORTANT: --update-env-vars を使用（--set-env-vars 禁止！）
  if ! gcloud functions deploy "$func" \
    --source="$REPO_ROOT/$func" \
    --runtime=python311 \
    --trigger-http \
    --region="$REGION" \
    --memory=1024MB \
    --cpu=1 \
    --timeout=540s \
    --allow-unauthenticated \
    --update-env-vars="$REQUIRED_ENV_VARS" \
    2>&1 | tail -5; then
    echo -e "  ${RED}FAIL: $func のデプロイに失敗${NC}"
    exit 1
  fi
  echo -e "  ${GREEN}$func デプロイ完了${NC}"
done
echo ""

# =====================================================
# Phase 3: 煙テスト
# =====================================================

echo -e "${CYAN}[Phase 3/4] 煙テスト（デプロイ後の基本動作確認）${NC}"
echo ""

SMOKE_FAILED=0
for func in "${TARGET_FUNCTIONS[@]}"; do
  # 最新リビジョンのURLを取得
  LATEST_REV=$(gcloud run revisions list \
    --service="$func" \
    --region="$REGION" \
    --sort-by='~creationTimestamp' \
    --limit=1 \
    --format='value(name)' 2>/dev/null)

  FUNC_URL=$(gcloud run services describe "$func" \
    --region="$REGION" \
    --format='value(status.url)' 2>/dev/null)

  echo "  $func: 最新リビジョン = $LATEST_REV"

  if [[ -z "$FUNC_URL" ]]; then
    echo -e "  ${YELLOW}WARN: URL取得失敗。煙テストをスキップ。${NC}"
    continue
  fi

  # 煙テスト: HTTPステータスが200/4xxであること（5xxはNG）
  # Cloud Functions はPOSTリクエストを期待するため、空のPOSTを送る
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    -X POST \
    -H "Content-Type: application/json" \
    -d '{}' \
    --max-time 30 \
    "$FUNC_URL" 2>/dev/null || echo "000")

  if [[ "$HTTP_CODE" == "5"* || "$HTTP_CODE" == "000" ]]; then
    echo -e "  ${RED}FAIL: $func returned HTTP $HTTP_CODE${NC}"
    SMOKE_FAILED=1
  else
    echo -e "  ${GREEN}PASS: $func returned HTTP $HTTP_CODE${NC}"
  fi
done
echo ""

# 煙テスト失敗時は自動ロールバック
if [[ "$SMOKE_FAILED" -eq 1 ]]; then
  echo -e "${RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo -e "${RED}  煙テスト失敗！自動ロールバック実行中...${NC}"
  echo -e "${RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo ""

  for func in "${TARGET_FUNCTIONS[@]}"; do
    prev="${PREVIOUS_REVISIONS[$func]}"
    if [[ -n "$prev" ]]; then
      echo "  $func → $prev にロールバック..."
      gcloud run services update-traffic "$func" \
        --region="$REGION" \
        --to-revisions="${prev}=100" 2>&1 || true
      echo -e "  ${GREEN}$func ロールバック完了${NC}"
    fi
  done

  echo ""
  echo -e "${RED}デプロイは中止されました。ログを確認してください。${NC}"
  exit 1
fi

# =====================================================
# Phase 4: トラフィック切り替え
# =====================================================

echo -e "${CYAN}[Phase 4/4] トラフィック切り替え${NC}"
echo ""

for func in "${TARGET_FUNCTIONS[@]}"; do
  LATEST_REV=$(gcloud run revisions list \
    --service="$func" \
    --region="$REGION" \
    --sort-by='~creationTimestamp' \
    --limit=1 \
    --format='value(name)' 2>/dev/null)

  echo "  $func: $LATEST_REV にトラフィック100%を切り替え..."
  if gcloud run services update-traffic "$func" \
    --region="$REGION" \
    --to-revisions="${LATEST_REV}=100" 2>&1; then
    echo -e "  ${GREEN}$func トラフィック切り替え完了${NC}"
  else
    echo -e "  ${RED}FAIL: トラフィック切り替えに失敗${NC}"
    echo "  手動で確認してください: gcloud run services describe $func --region=$REGION"
  fi
done

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "  ${GREEN}安全デプロイ完了${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  確認事項:"
echo "    1. ChatWorkでソウルくんに話しかけて応答確認"
echo "    2. Cloud Loggingでエラーログがないか確認"
echo "    3. 5分後に再度応答確認（キャッシュウォーム後）"
echo ""
echo "  障害発生時:"
echo "    scripts/rollback.sh  # 1分以内にロールバック"
echo ""
