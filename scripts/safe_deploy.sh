#!/usr/bin/env bash
# macOS互換のため bash 3.x でも動作すること（declare -A 禁止）
set -euo pipefail

# =============================================================================
# 安全デプロイスクリプト（Cloud Run版）
# =============================================================================
#
# 本番デプロイの安全性を最大化するスクリプト。
# 「壊れた状態でお客さんに届く」ことを防止する。
#
# 手順:
#   1. 全プリデプロイチェック実行（テスト・SQL検証）
#   2. Docker イメージをビルド & Artifact Registry にプッシュ
#   3. Cloud Run に新リビジョンをデプロイ
#   4. 煙テスト実行（基本動作確認）
#   5. 問題があれば自動で巻き戻し
#
# 使い方:
#   scripts/safe_deploy.sh                     # 両方デプロイ
#   scripts/safe_deploy.sh chatwork-webhook    # chatwork-webhookのみ
#   scripts/safe_deploy.sh --skip-tests        # テストをスキップ（緊急時のみ）
#   scripts/safe_deploy.sh --dry-run           # 実行せずに確認のみ
#
# 3者合意(Claude + Codex + Gemini):
#   「デプロイは Docker build → Cloud Run deploy → 煙テストの3段階で行う」
# =============================================================================

REGION="${REGION:-asia-northeast1}"
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
AR_REPO="${AR_REPO:-cloud-run}"
IMAGE_TAG="${IMAGE_TAG:-$(git rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M%S)}"

# デフォルト設定
DRY_RUN=0
SKIP_TESTS=0
TARGET_FUNCTIONS=()

# 環境変数（本番必須）— IMPORTANT: --update-env-vars を使用（--set-env-vars 禁止！）
ENV_VARS_CHATWORK="USE_BRAIN_ARCHITECTURE=true,ENVIRONMENT=production,LOG_EXECUTION_ID=true,ENABLE_MEETING_TRANSCRIPTION=true,ENABLE_MEETING_MINUTES=true,ENABLE_IMAGE_ANALYSIS=true,MEETING_GCS_BUCKET=soulkun-meeting-recordings,TELEGRAM_CEO_CHAT_ID=8304510694,TELEGRAM_BOT_USERNAME=soulsyncs_bot"
# Secret Manager からマウントするシークレット
SECRETS_CHATWORK="TAVILY_API_KEY=TAVILY_API_KEY:latest,TELEGRAM_BOT_TOKEN=TELEGRAM_BOT_TOKEN:latest,TELEGRAM_WEBHOOK_SECRET=TELEGRAM_WEBHOOK_SECRET:latest"
ENV_VARS_PROACTIVE="USE_BRAIN_ARCHITECTURE=true,ENVIRONMENT=production,LOG_EXECUTION_ID=true"
SECRETS_PROACTIVE="TAVILY_API_KEY=TAVILY_API_KEY:latest"

# サービス別設定
# bash 3.x互換: 連想配列の代わりに個別変数を使用
MEMORY_chatwork_webhook="1024Mi"
MEMORY_proactive_monitor="512Mi"
CPU_chatwork_webhook="1"
CPU_proactive_monitor="1"
MIN_INSTANCES_chatwork_webhook="1"
MIN_INSTANCES_proactive_monitor="0"
MAX_INSTANCES_chatwork_webhook="10"
MAX_INSTANCES_proactive_monitor="5"
AUTH_chatwork_webhook="--allow-unauthenticated"
AUTH_proactive_monitor="--no-allow-unauthenticated"

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
      echo ""
      echo "Environment variables:"
      echo "  REGION              GCP region (default: asia-northeast1)"
      echo "  PROJECT_ID          GCP project ID (default: gcloud config)"
      echo "  AR_REPO             Artifact Registry repo name (default: cloud-run)"
      echo "  IMAGE_TAG           Docker image tag (default: git short hash)"
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
echo "  安全デプロイ（Cloud Run）"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  対象: ${TARGET_FUNCTIONS[*]}"
echo "  リージョン: $REGION"
echo "  プロジェクト: $PROJECT_ID"
echo "  イメージタグ: $IMAGE_TAG"
echo "  コミット: $(git rev-parse --short HEAD 2>/dev/null || echo 'unknown')"
echo ""

# =====================================================
# Phase 1: プリデプロイチェック
# =====================================================

echo -e "${CYAN}[Phase 1/4] プリデプロイチェック${NC}"
echo ""

# 1a. SQL検証
echo "  [1/3] SQLカラム検証..."
if [[ -f "$REPO_ROOT/db_schema.json" ]]; then
  if ! "$REPO_ROOT/scripts/validate_sql_columns.sh" --all 2>/dev/null; then
    echo -e "  ${RED}FAIL: SQL検証に失敗${NC}"
    exit 1
  fi
  echo -e "  ${GREEN}PASS${NC}"
else
  echo -e "  ${YELLOW}SKIP (db_schema.json not found)${NC}"
fi

# 1b. テスト実行
if [[ "$SKIP_TESTS" -eq 1 ]]; then
  echo -e "  [2/3] テスト... ${YELLOW}SKIP (--skip-tests)${NC}"
else
  echo "  [2/3] テスト実行..."
  if ! python3 -m pytest "$REPO_ROOT/tests/test_critical_functions.py" \
    "$REPO_ROOT/tests/test_brain_type_safety.py" -v --tb=short 2>&1 | tail -5; then
    echo -e "  ${RED}FAIL: テストに失敗${NC}"
    exit 1
  fi
  echo -e "  ${GREEN}PASS${NC}"
fi

# 1c. pre_deploy_check（コード部分のみ）
echo "  [3/3] コードレベルチェック..."
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
    IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}/${func}:${IMAGE_TAG}"
    echo "  docker build -f $func/Dockerfile -t $IMAGE ."
    echo "  docker push $IMAGE"
    echo "  gcloud run deploy $func --image=$IMAGE --region=$REGION --update-env-vars=..."
  done
  exit 0
fi

# =====================================================
# Phase 2: Docker ビルド & プッシュ
# =====================================================

echo -e "${CYAN}[Phase 2/4] Docker ビルド & Artifact Registry プッシュ${NC}"
echo ""

# 現在のリビジョンを記録（ロールバック用）
PREV_REV_chatwork_webhook=""
PREV_REV_proactive_monitor=""
for func in "${TARGET_FUNCTIONS[@]}"; do
  prev_rev=$(gcloud run services describe "$func" \
    --region="$REGION" \
    --format='value(status.traffic[0].revisionName)' 2>/dev/null || echo "")
  var_name="PREV_REV_${func//-/_}"
  eval "$var_name=\"$prev_rev\""
  echo "  $func 現在のリビジョン: $prev_rev"
done
echo ""

for func in "${TARGET_FUNCTIONS[@]}"; do
  IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}/${func}:${IMAGE_TAG}"
  IMAGE_LATEST="${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}/${func}:latest"

  echo "  $func: Docker ビルド中..."
  if ! docker build --platform linux/amd64 -f "$REPO_ROOT/$func/Dockerfile" \
    -t "$IMAGE" \
    -t "$IMAGE_LATEST" \
    "$REPO_ROOT" 2>&1 | tail -3; then
    echo -e "  ${RED}FAIL: $func の Docker ビルドに失敗${NC}"
    exit 1
  fi
  echo -e "  ${GREEN}ビルド完了${NC}"

  echo "  $func: Artifact Registry にプッシュ中..."
  if ! docker push "$IMAGE" 2>&1 | tail -3; then
    echo -e "  ${RED}FAIL: $func のプッシュに失敗${NC}"
    exit 1
  fi
  docker push "$IMAGE_LATEST" 2>&1 | tail -1 || true
  echo -e "  ${GREEN}プッシュ完了${NC}"
  echo ""
done

# =====================================================
# Phase 3: Cloud Run デプロイ & 煙テスト
# =====================================================

echo -e "${CYAN}[Phase 3/4] Cloud Run デプロイ${NC}"
echo ""

for func in "${TARGET_FUNCTIONS[@]}"; do
  IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}/${func}:${IMAGE_TAG}"
  var_name_mem="MEMORY_${func//-/_}"
  var_name_cpu="CPU_${func//-/_}"
  var_name_min="MIN_INSTANCES_${func//-/_}"
  var_name_max="MAX_INSTANCES_${func//-/_}"
  var_name_auth="AUTH_${func//-/_}"
  eval "memory=\"\${$var_name_mem}\""
  eval "cpu=\"\${$var_name_cpu}\""
  eval "min_inst=\"\${$var_name_min}\""
  eval "max_inst=\"\${$var_name_max}\""
  eval "auth=\"\${$var_name_auth}\""

  # 環境変数とシークレットを選択
  if [[ "$func" == "chatwork-webhook" ]]; then
    env_vars="$ENV_VARS_CHATWORK"
    secrets="$SECRETS_CHATWORK"
  else
    env_vars="$ENV_VARS_PROACTIVE"
    secrets="$SECRETS_PROACTIVE"
  fi

  echo "  $func をデプロイ中..."
  # IMPORTANT: --update-env-vars を使用（--set-env-vars 禁止！）
  deploy_cmd=(gcloud run deploy "$func"
    --image="$IMAGE"
    --region="$REGION"
    --memory="$memory"
    --cpu="$cpu"
    --timeout=540s
    --min-instances="$min_inst"
    --max-instances="$max_inst"
    $auth
    --update-env-vars="$env_vars")
  if [[ -n "$secrets" ]]; then
    deploy_cmd+=(--update-secrets="$secrets")
  fi
  if ! "${deploy_cmd[@]}" 2>&1 | tail -5; then
    echo -e "  ${RED}FAIL: $func のデプロイに失敗${NC}"
    exit 1
  fi
  echo -e "  ${GREEN}$func デプロイ完了${NC}"
done
echo ""

# =====================================================
# Phase 4: 煙テスト
# =====================================================

echo -e "${CYAN}[Phase 4/4] 煙テスト（デプロイ後の基本動作確認）${NC}"
echo ""

SMOKE_FAILED=0
for func in "${TARGET_FUNCTIONS[@]}"; do
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
    var_name="PREV_REV_${func//-/_}"
    eval "prev=\"\${$var_name}\""
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

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "  ${GREEN}安全デプロイ完了（Cloud Run）${NC}"
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
