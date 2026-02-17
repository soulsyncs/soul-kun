#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# 3AI Review (Claude + Codex + Gemini) — ローカル実行・ログイン環境・完全無料
#
# カズさんのPC上で3つのAIが独立にコードレビューする。
# 全てログイン環境（月額サブスク枠）で動くのでAPI課金0円。
#
# Usage:
#   scripts/three_ai_review.sh              # 通常レビュー
#   scripts/three_ai_review.sh --full       # フルテスト付き
#   SKIP_3AI_REVIEW=1 git push              # スキップ（緊急時のみ）
#   REVIEW_AI="claude,gemini" git push      # 特定AIだけ実行
#
# 仕組み:
#   1. git diff（変更差分）を取得
#   2. Claude Code → Codex → Gemini が順番にレビュー
#   3. 全員PASSで合格、1つでもFAILなら不合格
#   4. pre-pushフックから自動で呼ばれる
# =============================================================================

# --- 設定 ---
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
REPO_HASH=$(echo "$REPO_ROOT" | md5sum 2>/dev/null | cut -c1-8 || echo "$REPO_ROOT" | shasum | cut -c1-8)
REVIEW_DIFF_PATH="/tmp/3ai_review_diff_${REPO_HASH}.txt"
REVIEW_RESULTS_DIR="/tmp/3ai_review_results_${REPO_HASH}"
mkdir -p "$REVIEW_RESULTS_DIR"

CLAUDE_BIN="${CLAUDE_BIN:-$(command -v claude 2>/dev/null || echo "claude")}"
CODEX_BIN="${CODEX_BIN:-$(command -v codex 2>/dev/null || echo "$HOME/.npm-global/bin/codex")}"
GEMINI_BIN="${GEMINI_BIN:-$(command -v gemini 2>/dev/null || echo "$HOME/.npm-global/bin/gemini")}"

# どのAIを使うか（デフォルト: 3つ全部）
REVIEW_AI="${REVIEW_AI:-claude,codex,gemini}"

RUN_FULL_TESTS=0
if [[ "${1:-}" == "--full" ]]; then
  RUN_FULL_TESTS=1
fi

# --- 差分の取得 ---
build_diff() {
  : > "$REVIEW_DIFF_PATH"

  if [[ "${PRE_PUSH_MODE:-}" == "1" ]]; then
    # push前: mainブランチとの差分
    local base_ref
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
    # 通常: ステージング + 未ステージング
    git diff --patch >> "$REVIEW_DIFF_PATH" || true
    git diff --cached --patch >> "$REVIEW_DIFF_PATH" || true
    while IFS= read -r file; do
      [[ -z "$file" ]] && continue
      local size
      size=$(stat -f%z "$file" 2>/dev/null || stat -c%s "$file" 2>/dev/null || echo 0)
      if [[ "$size" -gt 1048576 ]]; then
        echo "  Skipping large file: $file" >&2
        continue
      fi
      git diff --no-index /dev/null "$file" >> "$REVIEW_DIFF_PATH" || true
    done < <(git ls-files --others --exclude-standard)
  fi
}

# --- レビュープロンプト（共通） ---
build_review_prompt() {
  cat <<'PROMPT'
あなたはソウルくんプロジェクトの「世界最高のエンジニア」です。
以下のコード差分を厳密にレビューしてください。

【必須チェック項目（22項目から最重要9項目）】
1. organization_idフィルタ漏れ: SELECT/INSERT/UPDATE/DELETEにorg_idがあるか
2. asyncブロッキング: async def内でpool.connect()を直接呼んでいないか
3. RLS型キャスト整合: VARCHARカラムに::uuidキャストしていないか
4. PII漏洩: ログにメッセージ本文・名前・メールが含まれていないか
5. SQLインジェクション: パラメータ化されているか
6. Brain bypass: 脳を通さずに直接テンプレート送信していないか
7. lib/同期: lib/の変更がchatwork-webhook/lib/とproactive-monitor/lib/にも反映されているか
8. fire-and-forget: asyncio.create_task()を直接使っていないか
9. デプロイ安全性: --set-env-vars（禁止）ではなく--update-env-varsを使っているか

【判定基準】
- FAIL: 上記9項目のいずれか1つでも該当すればFAIL
- PASS: 全項目で問題なしの場合のみPASS

【回答形式 — 必ずこの形式で回答】
## 判定: PASS または FAIL

## 指摘事項
- CRITICAL: (件数)
- HIGH: (件数)

## 詳細
(各指摘の説明。なければ「指摘なし」)

PROMPT
}

# --- 各AIの実行 ---
run_claude_review() {
  echo "  [1/3] Claude Code レビュー中..."
  local prompt_file="/tmp/3ai_claude_prompt_${REPO_HASH}.txt"
  {
    build_review_prompt
    echo "## コード差分"
    echo
    cat "$REVIEW_DIFF_PATH"
  } > "$prompt_file"

  # Claude Code内から実行されている場合はスキップ（ネスト不可）
  if [[ -n "${CLAUDECODE:-}" ]]; then
    echo "  ⚠️ Claude Code内から実行中のため、Claudeレビューをスキップします。"
    echo "  （実際のgit push時は正常に動作します）"
    echo "## 判定: SKIP (Claude Code nested session)" > "$REVIEW_RESULTS_DIR/claude.txt"
    return 0
  fi

  # Claude Code: -p でノンインタラクティブ実行（ログイン環境使用）
  "$CLAUDE_BIN" -p "$(cat "$prompt_file")" \
    --model claude-sonnet-4-5-20250929 \
    --max-turns 1 \
    2>/dev/null | tee "$REVIEW_RESULTS_DIR/claude.txt"
}

run_codex_review() {
  echo "  [2/3] Codex レビュー中..."
  {
    build_review_prompt
    echo "## コード差分"
    echo
    cat "$REVIEW_DIFF_PATH"
  } | "$CODEX_BIN" exec \
    --model gpt-5.2-codex \
    --sandbox read-only \
    --full-auto \
    - 2>/dev/null | tee "$REVIEW_RESULTS_DIR/codex.txt"
}

run_gemini_review() {
  echo "  [3/3] Gemini レビュー中..."
  local prompt_file="/tmp/3ai_gemini_prompt_${REPO_HASH}.txt"
  {
    build_review_prompt
    echo "## コード差分"
    echo
    cat "$REVIEW_DIFF_PATH"
  } > "$prompt_file"

  # Gemini CLI: ファイルからプロンプトを渡す
  "$GEMINI_BIN" < "$prompt_file" \
    2>/dev/null | tee "$REVIEW_RESULTS_DIR/gemini.txt"
}

# --- 判定パーサー ---
parse_verdict_from() {
  local file="$1"
  if [[ ! -s "$file" ]]; then
    echo "FAIL"
    return 0
  fi

  local cleaned
  cleaned="$(tr -d '\r' < "$file" | sed -E 's/\x1B\[[0-9;]*[mK]//g')"

  # FAILを先にチェック（FAILとPASS両方含む場合はFAIL優先）
  if printf "%s" "$cleaned" | grep -E "判定[:：][[:space:]]*FAIL" >/dev/null 2>&1; then
    echo "FAIL"
    return 0
  fi
  if printf "%s" "$cleaned" | grep -E "判定[:：][[:space:]]*PASS" >/dev/null 2>&1; then
    echo "PASS"
    return 0
  fi
  # フォールバック
  if printf "%s" "$cleaned" | grep -E '(^|[^A-Z])FAIL([^A-Z]|$)' >/dev/null 2>&1; then
    echo "FAIL"
    return 0
  fi
  if printf "%s" "$cleaned" | grep -E '(^|[^A-Z])PASS([^A-Z]|$)' >/dev/null 2>&1; then
    echo "PASS"
    return 0
  fi
  echo "FAIL"
}

# --- メイン処理 ---
echo "============================================"
echo "  3AI Code Review (ローカル・無料)"
echo "  対象AI: $REVIEW_AI"
echo "============================================"

build_diff

if [[ ! -s "$REVIEW_DIFF_PATH" ]]; then
  echo "変更差分なし。レビュー不要。"
  exit 0
fi

diff_lines=$(wc -l < "$REVIEW_DIFF_PATH" | tr -d ' ')
echo "  差分: ${diff_lines}行"

# 差分が大きすぎる場合は先頭だけ使う（AIの入力制限対策）
MAX_DIFF_LINES="${MAX_DIFF_LINES:-3000}"
if [[ "$diff_lines" -gt "$MAX_DIFF_LINES" ]]; then
  echo "  差分が${MAX_DIFF_LINES}行を超えています。先頭${MAX_DIFF_LINES}行のみレビューします。"
  tmp_truncated="${REVIEW_DIFF_PATH}.truncated"
  head -n "$MAX_DIFF_LINES" "$REVIEW_DIFF_PATH" > "$tmp_truncated"
  mv "$tmp_truncated" "$REVIEW_DIFF_PATH"
fi
echo

# 各AIを実行
claude_verdict="SKIP"
codex_verdict="SKIP"
gemini_verdict="SKIP"

if [[ "$REVIEW_AI" == *"claude"* ]]; then
  run_claude_review
  claude_verdict="$(parse_verdict_from "$REVIEW_RESULTS_DIR/claude.txt")"
  echo "  → Claude 判定: $claude_verdict"
  echo
fi

if [[ "$REVIEW_AI" == *"codex"* ]]; then
  run_codex_review
  codex_verdict="$(parse_verdict_from "$REVIEW_RESULTS_DIR/codex.txt")"
  echo "  → Codex 判定: $codex_verdict"
  echo
fi

if [[ "$REVIEW_AI" == *"gemini"* ]]; then
  run_gemini_review
  gemini_verdict="$(parse_verdict_from "$REVIEW_RESULTS_DIR/gemini.txt")"
  echo "  → Gemini 判定: $gemini_verdict"
  echo
fi

# --- 統合判定 ---
echo "============================================"
echo "  3AI Review 結果"
echo "============================================"
echo "  Claude: $claude_verdict"
echo "  Codex:  $codex_verdict"
echo "  Gemini: $gemini_verdict"

all_pass=true
for v in "$claude_verdict" "$codex_verdict" "$gemini_verdict"; do
  if [[ "$v" == "FAIL" ]]; then
    all_pass=false
    break
  fi
done

if $all_pass; then
  echo "============================================"
  echo "  ✅ 3AI Review: ALL PASS"
  echo "============================================"

  # テスト実行
  if [[ "$RUN_FULL_TESTS" -eq 1 ]]; then
    echo "  テスト実行中..."
    python3 -m pytest "$REPO_ROOT/tests/" --tb=short 2>&1 || {
      echo "  ❌ テスト失敗。push中止。"
      exit 1
    }
  fi

  exit 0
else
  echo "============================================"
  echo "  ❌ 3AI Review: FAIL"
  echo "============================================"
  echo
  echo "  FAILの詳細は以下のファイルを確認:"
  echo "    Claude: $REVIEW_RESULTS_DIR/claude.txt"
  echo "    Codex:  $REVIEW_RESULTS_DIR/codex.txt"
  echo "    Gemini: $REVIEW_RESULTS_DIR/gemini.txt"
  echo
  exit 1
fi
