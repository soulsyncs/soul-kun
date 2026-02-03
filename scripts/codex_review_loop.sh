#!/usr/bin/env bash
set -euo pipefail

# Codex review loop (ChatGPT login, no API).
# Usage:
#   scripts/codex_review_loop.sh            # review + partial tests
#   scripts/codex_review_loop.sh --full     # review + full tests
# Env:
#   MAX_LOOPS=3
#   PARTIAL_TEST_CMD="python3 -m pytest tests/ --tb=short -k user_utils"
#   FULL_TEST_CMD="python3 -m pytest tests/ --tb=short"
#   REVIEW_DOCS=$'docs/25_llm_native_brain_architecture.md\nCLAUDE.md'
#   CODEX_BIN="$HOME/.npm-global/bin/codex"

MAX_LOOPS="${MAX_LOOPS:-3}"
PARTIAL_TEST_CMD="${PARTIAL_TEST_CMD:-python3 -m pytest tests/ --tb=short}"
FULL_TEST_CMD="${FULL_TEST_CMD:-python3 -m pytest tests/ --tb=short}"
REPO_HASH=$(git rev-parse --show-toplevel 2>/dev/null | md5 | cut -c1-8)
REVIEW_DIFF_PATH="${REVIEW_DIFF_PATH:-/tmp/codex_review_diff_${REPO_HASH}.txt}"
REVIEW_OUT_PATH="${REVIEW_OUT_PATH:-/tmp/codex_review_output_${REPO_HASH}.txt}"
REVIEW_DOCS="${REVIEW_DOCS:-docs/25_llm_native_brain_architecture.md
CLAUDE.md}"
CODEX_BIN="${CODEX_BIN:-$HOME/.npm-global/bin/codex}"

RUN_FULL_TESTS=0
if [[ "${1:-}" == "--full" ]]; then
  RUN_FULL_TESTS=1
fi

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

require_cmd git
require_cmd "$CODEX_BIN"

build_diff() {
  : > "$REVIEW_DIFF_PATH"

  # pre-push の場合: mainブランチとのコミット済み差分のみ
  # それ以外: ステージング + 未ステージング + 未追跡ファイル
  if [[ "${PRE_PUSH_MODE:-}" == "1" ]]; then
    # コミット済みの変更のみ（リモートとの差分を優先）
    base_ref="$(git rev-parse --abbrev-ref --symbolic-full-name @{u} 2>/dev/null || true)"
    if [[ -z "$base_ref" ]]; then
      if git show-ref --verify --quiet refs/remotes/origin/main; then
        base_ref="origin/main"
      else
        base_ref="main"
      fi
    fi
    git diff "$base_ref"...HEAD --patch >> "$REVIEW_DIFF_PATH" || true
  else
    # Staged + unstaged diffs
    git diff --patch >> "$REVIEW_DIFF_PATH" || true
    git diff --cached --patch >> "$REVIEW_DIFF_PATH" || true

    # Include untracked files (full content) - 巨大ファイルは除外
    while IFS= read -r file; do
      [[ -z "$file" ]] && continue
      # 1MB以上のファイルはスキップ
      local size
      size=$(stat -f%z "$file" 2>/dev/null || stat -c%s "$file" 2>/dev/null || echo 0)
      if [[ "$size" -gt 1048576 ]]; then
        echo "Skipping large file: $file ($size bytes)" >&2
        continue
      fi
      git diff --no-index /dev/null "$file" >> "$REVIEW_DIFF_PATH" || true
    done < <(git ls-files --others --exclude-standard)
  fi
}

review_prompt() {
  local docs_list
  docs_list="$(printf "%s\n" "$REVIEW_DOCS" | sed '/^$/d' | sed 's/^/- /')"
  cat <<'PROMPT'
## 設計書参照
PROMPT
  printf "%s\n\n" "$docs_list"
  cat <<'PROMPT'

## 変更内容
差分レビュー（git diff）

## レビュー依頼
以下の観点でレビューしてください：
1. 重大バグ: ロジックエラー、クラッシュの可能性
2. セキュリティ: 脆弱性、情報漏洩リスク
3. 設計書との矛盾: CLAUDE.mdの原則違反
4. テストカバレッジ: テスト対象の全パスをカバーしているか

判定基準
- FAIL: 重大バグ / セキュリティ / 設計矛盾 が1つでもあれば
- PASS: それらが0件ならOK

回答形式
## 判定: PASS または FAIL
## 重大バグ
## セキュリティ
## 設計書との矛盾
## 軽微な指摘（次回対応可）
PROMPT
}

run_review() {
  # Codex exec reads prompt from stdin when "-" or no prompt is provided.
  {
    review_prompt
    echo
    echo "## git diff"
    echo
    cat "$REVIEW_DIFF_PATH"
  } | "$CODEX_BIN" exec - | tee "$REVIEW_OUT_PATH"
}

parse_verdict() {
  # Strip CR and ANSI color codes, then detect verdict via grep (no rg dependency)
  local cleaned
  cleaned="$(tr -d '\r' < "$REVIEW_OUT_PATH" | sed -E 's/\x1B\[[0-9;]*[mK]//g')"

  if printf "%s" "$cleaned" | grep -E "判定[:：][[:space:]]*PASS" >/dev/null 2>&1; then
    echo "PASS"
    return 0
  fi
  if printf "%s" "$cleaned" | grep -E "判定[:：][[:space:]]*FAIL" >/dev/null 2>&1; then
    echo "FAIL"
    return 0
  fi
  # Fallback: detect PASS word boundary-ish
  if printf "%s" "$cleaned" | grep -E '(^|[^A-Z])PASS([^A-Z]|$)' >/dev/null 2>&1; then
    echo "PASS"
    return 0
  fi
  echo "FAIL"
}

run_tests() {
  if [[ "$RUN_FULL_TESTS" -eq 1 ]]; then
    echo "Running full tests: $FULL_TEST_CMD"
    eval "$FULL_TEST_CMD"
  else
    echo "Running partial tests: $PARTIAL_TEST_CMD"
    eval "$PARTIAL_TEST_CMD"
  fi
}

for attempt in $(seq 1 "$MAX_LOOPS"); do
  echo "=== Codex Review Attempt $attempt/$MAX_LOOPS ==="
  build_diff

  if [[ ! -s "$REVIEW_DIFF_PATH" ]]; then
    echo "No diffs found. Nothing to review."
    echo "Skipping review."
    exit 0
  fi

  run_review
  verdict="$(parse_verdict | tr -d '\r' | xargs)"

  if [[ "$verdict" == "PASS" ]]; then
    echo "Review PASS."
    run_tests
    echo "Review + tests completed."
    exit 0
  fi

  echo "Review FAIL. Fix issues, then press Enter to re-run (or Ctrl+C to stop)."
  read -r
done

echo "Max review attempts reached ($MAX_LOOPS). Escalate to human decision."
exit 2
