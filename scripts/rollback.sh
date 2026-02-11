#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# ワンクリック巻き戻しスクリプト
# =============================================================================
#
# 本番障害発生時に、1コマンドで前回の正常なリビジョンに戻す。
# 復旧時間: 数時間 → 1分以内
#
# 使い方:
#   scripts/rollback.sh                    # 両方の関数を巻き戻し
#   scripts/rollback.sh chatwork-webhook   # chatwork-webhookのみ
#   scripts/rollback.sh proactive-monitor  # proactive-monitorのみ
#   scripts/rollback.sh --dry-run          # 実行せずに確認のみ
#   scripts/rollback.sh --list             # リビジョン一覧を表示
#
# 3者合意(Claude + Codex + Gemini):
#   「障害復旧の第一手はロールバック。前進修正は落ち着いてから。」
# =============================================================================

REGION="${REGION:-asia-northeast1}"
FUNCTIONS=("chatwork-webhook" "proactive-monitor")
DRY_RUN=0
LIST_ONLY=0

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# 引数解析
TARGET_FUNCTIONS=()
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --list) LIST_ONLY=1 ;;
    chatwork-webhook|proactive-monitor)
      TARGET_FUNCTIONS+=("$arg")
      ;;
    -h|--help)
      echo "Usage: $0 [chatwork-webhook|proactive-monitor] [--dry-run] [--list]"
      echo ""
      echo "Options:"
      echo "  chatwork-webhook    Rollback chatwork-webhook only"
      echo "  proactive-monitor   Rollback proactive-monitor only"
      echo "  --dry-run           Show what would happen without executing"
      echo "  --list              List recent revisions for each function"
      echo ""
      echo "Examples:"
      echo "  $0                  # Rollback both functions"
      echo "  $0 chatwork-webhook # Rollback chatwork-webhook only"
      echo "  $0 --dry-run        # Preview rollback"
      exit 0
      ;;
    *)
      echo -e "${RED}Unknown option: $arg${NC}"
      echo "Usage: $0 [chatwork-webhook|proactive-monitor] [--dry-run] [--list]"
      exit 1
      ;;
  esac
done

# ターゲットが指定されなければ両方
if [[ ${#TARGET_FUNCTIONS[@]} -eq 0 ]]; then
  TARGET_FUNCTIONS=("${FUNCTIONS[@]}")
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [[ "$LIST_ONLY" -eq 1 ]]; then
  echo "  リビジョン一覧"
elif [[ "$DRY_RUN" -eq 1 ]]; then
  echo "  ロールバック（ドライラン）"
else
  echo -e "  ${RED}ロールバック実行${NC}"
fi
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

get_revisions() {
  local func_name="$1"
  gcloud run revisions list \
    --service="$func_name" \
    --region="$REGION" \
    --sort-by='~creationTimestamp' \
    --limit=5 \
    --format='table(name, status.conditions[0].status, spec.containers[0].resources.limits.memory, metadata.creationTimestamp.date())' \
    2>/dev/null
}

get_current_revision() {
  local func_name="$1"
  gcloud run services describe "$func_name" \
    --region="$REGION" \
    --format='value(status.traffic[0].revisionName)' \
    2>/dev/null
}

get_previous_revision() {
  local func_name="$1"
  local current_rev="$2"
  gcloud run revisions list \
    --service="$func_name" \
    --region="$REGION" \
    --sort-by='~creationTimestamp' \
    --limit=5 \
    --format='value(name)' \
    2>/dev/null | grep -v "^${current_rev}$" | head -1
}

# --list モード
if [[ "$LIST_ONLY" -eq 1 ]]; then
  for func in "${TARGET_FUNCTIONS[@]}"; do
    echo -e "${CYAN}=== $func ===${NC}"
    current=$(get_current_revision "$func")
    echo -e "  Current (serving): ${GREEN}${current}${NC}"
    echo ""
    get_revisions "$func"
    echo ""
  done
  exit 0
fi

# ロールバック実行
ROLLBACK_COUNT=0
for func in "${TARGET_FUNCTIONS[@]}"; do
  echo -e "${CYAN}=== $func ===${NC}"

  current_rev=$(get_current_revision "$func")
  if [[ -z "$current_rev" ]]; then
    echo -e "  ${RED}FAIL: Could not get current revision${NC}"
    continue
  fi
  echo -e "  Current revision: ${YELLOW}${current_rev}${NC}"

  prev_rev=$(get_previous_revision "$func" "$current_rev")
  if [[ -z "$prev_rev" ]]; then
    echo -e "  ${RED}FAIL: No previous revision found to rollback to${NC}"
    continue
  fi
  echo -e "  Rollback target:  ${GREEN}${prev_rev}${NC}"

  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo -e "  ${YELLOW}[DRY RUN] Would execute:${NC}"
    echo "    gcloud run services update-traffic $func --region=$REGION --to-revisions=${prev_rev}=100"
  else
    echo "  Rolling back..."
    if gcloud run services update-traffic "$func" \
      --region="$REGION" \
      --to-revisions="${prev_rev}=100" 2>&1; then
      echo -e "  ${GREEN}SUCCESS: $func rolled back to $prev_rev${NC}"
      ROLLBACK_COUNT=$((ROLLBACK_COUNT + 1))
    else
      echo -e "  ${RED}FAIL: Could not rollback $func${NC}"
    fi
  fi
  echo ""
done

# サマリ
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [[ "$DRY_RUN" -eq 1 ]]; then
  echo -e "  ${YELLOW}ドライラン完了。実行するには --dry-run を外してください。${NC}"
elif [[ "$ROLLBACK_COUNT" -eq ${#TARGET_FUNCTIONS[@]} ]]; then
  echo -e "  ${GREEN}ロールバック完了 (${ROLLBACK_COUNT}/${#TARGET_FUNCTIONS[@]} functions)${NC}"
  echo ""
  echo "  次のステップ:"
  echo "    1. ChatWorkでソウルくんに話しかけて動作確認"
  echo "    2. Cloud Loggingでエラーがないか確認"
  echo "    3. 落ち着いてから原因調査・修正"
else
  echo -e "  ${RED}一部失敗 (${ROLLBACK_COUNT}/${#TARGET_FUNCTIONS[@]} functions)${NC}"
fi
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
