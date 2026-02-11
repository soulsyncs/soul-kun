#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# 3AI Review Loop — Codex + Claude Code + Gemini (CLI/login auth, no API keys)
# =============================================================================
#
# All 3 AIs run locally using CLI login authentication.
#   1. Codex:       18-item 3-pass review (Standard -> Self-verify -> Devil's Advocate)
#   2. Claude Code: Architecture + design coherence (CLAUDE.md rules)
#   3. Gemini:      Security + performance + code quality
#
# Usage:
#   scripts/codex_review_loop.sh              # 3AI review + partial tests
#   scripts/codex_review_loop.sh --full       # 3AI review + full tests
#   scripts/codex_review_loop.sh --codex-only # Codex only (legacy)
#
# Env:
#   MAX_LOOPS=3                          # Max retry attempts
#   REVIEW_PASSES=3                      # Codex passes (1-3)
#   ENABLE_CLAUDE=1                      # Enable Claude Code review (0 to disable)
#   ENABLE_GEMINI=1                      # Enable Gemini review (0 to disable)
#   CLAUDE_BIN=claude                    # Claude Code CLI path
#   GEMINI_BIN=gemini                    # Gemini CLI path
#   CODEX_BIN=codex                      # Codex CLI path
#   CLAUDE_MODEL=sonnet                  # Claude model for review
#   GEMINI_MODEL=gemini-2.5-flash        # Gemini model for review
#   PARTIAL_TEST_CMD="python3 -m pytest tests/ --tb=short"
#   FULL_TEST_CMD="python3 -m pytest tests/ --tb=short"
#   REVIEW_DOCS=$'docs/25_llm_native_brain_architecture.md\nCLAUDE.md'
# =============================================================================

# --- Configuration ---
MAX_LOOPS="${MAX_LOOPS:-3}"
REVIEW_PASSES="${REVIEW_PASSES:-3}"
PARTIAL_TEST_CMD="${PARTIAL_TEST_CMD:-python3 -m pytest tests/ --tb=short}"
FULL_TEST_CMD="${FULL_TEST_CMD:-python3 -m pytest tests/ --tb=short}"
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
REPO_HASH=$(echo "$REPO_ROOT" | md5 | cut -c1-8)

# AI CLIs
CODEX_BIN="${CODEX_BIN:-codex}"
CLAUDE_BIN="${CLAUDE_BIN:-claude}"
GEMINI_BIN="${GEMINI_BIN:-gemini}"
CLAUDE_MODEL="${CLAUDE_MODEL:-sonnet}"
GEMINI_MODEL="${GEMINI_MODEL:-gemini-2.5-flash}"

# Enable/disable individual AIs
ENABLE_CLAUDE="${ENABLE_CLAUDE:-1}"
ENABLE_GEMINI="${ENABLE_GEMINI:-1}"

# Temp files
REVIEW_DIFF_PATH="${REVIEW_DIFF_PATH:-/tmp/codex_review_diff_${REPO_HASH}.txt}"
REVIEW_OUT_PATH="${REVIEW_OUT_PATH:-/tmp/codex_review_output_${REPO_HASH}.txt}"
REVIEW_OUT_PASS2="${REVIEW_OUT_PATH%.txt}_pass2.txt"
REVIEW_OUT_PASS3="${REVIEW_OUT_PATH%.txt}_pass3.txt"
REVIEW_OUT_CLAUDE="/tmp/claude_review_output_${REPO_HASH}.txt"
REVIEW_OUT_GEMINI="/tmp/gemini_review_output_${REPO_HASH}.txt"
REVIEW_DOCS="${REVIEW_DOCS:-docs/25_llm_native_brain_architecture.md
CLAUDE.md}"

# --- Flag parsing ---
RUN_FULL_TESTS=0
CODEX_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --full) RUN_FULL_TESTS=1 ;;
    --codex-only) CODEX_ONLY=1; ENABLE_CLAUDE=0; ENABLE_GEMINI=0 ;;
  esac
done

# --- CLI availability check ---
check_ai_tools() {
  if ! command -v "$CODEX_BIN" >/dev/null 2>&1; then
    echo "ERROR: Codex CLI not found: $CODEX_BIN" >&2
    echo "  Install: npm install -g @openai/codex" >&2
    exit 1
  fi

  if [[ "$ENABLE_CLAUDE" == "1" ]] && ! command -v "$CLAUDE_BIN" >/dev/null 2>&1; then
    echo "WARNING: Claude Code CLI not found ($CLAUDE_BIN). Skipping Claude review." >&2
    ENABLE_CLAUDE=0
  fi

  if [[ "$ENABLE_GEMINI" == "1" ]] && ! command -v "$GEMINI_BIN" >/dev/null 2>&1; then
    echo "WARNING: Gemini CLI not found ($GEMINI_BIN). Skipping Gemini review." >&2
    ENABLE_GEMINI=0
  fi
}
check_ai_tools

# --- Count active AIs ---
count_active_ais() {
  local count=1  # Codex is always active
  [[ "$ENABLE_CLAUDE" == "1" ]] && count=$((count + 1))
  [[ "$ENABLE_GEMINI" == "1" ]] && count=$((count + 1))
  echo "$count"
}

# =============================================================================
# Diff building
# =============================================================================
build_diff() {
  : > "$REVIEW_DIFF_PATH"

  # pre-push: committed changes vs remote only
  # otherwise: staged + unstaged + untracked
  if [[ "${PRE_PUSH_MODE:-}" == "1" ]]; then
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

    # Include untracked files (full content) - skip large files
    while IFS= read -r file; do
      [[ -z "$file" ]] && continue
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

# =============================================================================
# Codex Review Prompts (Pass 1/2/3)
# =============================================================================
review_prompt_pass1() {
  local docs_list
  docs_list="$(printf "%s\n" "$REVIEW_DOCS" | sed '/^$/d' | sed 's/^/- /')"
  cat <<'PROMPT'
## 設計書参照
PROMPT
  printf "%s\n\n" "$docs_list"

  # db_schema.json があればスキーマ情報を埋め込む
  local schema_file
  schema_file="$(git rev-parse --show-toplevel 2>/dev/null || pwd)/db_schema.json"
  if [[ -f "$schema_file" ]]; then
    echo "## 本番DBスキーマ（db_schema.json）"
    echo "以下は本番DBの全テーブル・カラム定義です。項目18のチェックで使用してください。"
    echo '```json'
    # tables セクションのみ抽出（コンパクトに）
    python3 -c "
import json, sys
with open('$schema_file') as f:
    schema = json.load(f)
print(json.dumps(schema.get('tables', {}), indent=1, ensure_ascii=False))
" 2>/dev/null || echo "(schema load failed)"
    echo '```'
    echo
  else
    echo "## 本番DBスキーマ不在"
    echo "db_schema.jsonが見つかりません。"
    echo "項目18（SQLカラム名整合）は検証不可能なため、FAILにしてください。"
    echo "スキーマを生成するには: scripts/dump_db_schema.sh"
    echo
  fi

  cat <<'PROMPT'

## 変更内容
差分レビュー（git diff）

## レビュー依頼
以下の18項目で厳密にレビューしてください。1項目でも該当すればFAILです。

### A. 基本チェック（4項目）
1. **重大バグ**: ロジックエラー、クラッシュの可能性、無限ループ
2. **セキュリティ脆弱性**: SQLインジェクション、XSS、認証バイパス、OWASP Top 10
3. **設計書との矛盾**: CLAUDE.mdの原則違反、Brain bypass、Truth順位違反
4. **テストカバレッジ**: 変更箇所の全パス（正常系・異常系・境界値）をテストしているか

### B. 再発防止チェック（6項目）— 過去の本番障害実績に基づく
5. **org_idフィルタ漏れ**: SELECT/INSERT/UPDATE/DELETEの全SQLにorganization_idフィルタがあるか（CLAUDE.md鉄則#1）
6. **asyncブロッキング**: async def内でpool.connect()等の同期I/Oを直接呼んでいないか。asyncio.to_thread()で包んでいるか
7. **RLS型キャスト整合**: RLSポリシーのキャスト型（::uuid / ::text）がカラムの実際の型と一致しているか。VARCHARに::uuidは致命的エラー
8. **PII漏洩**: ログ出力、debug_info、DB保存に個人情報（名前、メール、電話、メッセージ本文）が含まれていないか
9. **pg8000ドライバ互換**: SET文を使っていないか（set_config()関数を使うこと）。pg8000非対応の構文がないか
10. **データ整合性**: `x or ""`パターンで空文字をDBに保存していないか。必須IDにNullガードがあるか

### C. 未然防止チェック（6項目）— まだ起きていないが起こりうる問題
11. **リソースリーク**: DB接続、ファイルハンドル、HTTPセッションをwith文またはtry/finallyで確実に閉じているか
12. **エラーハンドリング漏れ**: bare `except Exception`で握りつぶしていないか。必ず`as e` + ログ記録があるか
13. **N+1クエリ**: ループ内で1件ずつDBクエリを発行していないか。JOINまたはIN句でまとめて取得すべき
14. **冪等性**: 同じリクエストが2回来ても安全か。ChatWork Webhook二重送信、DB重複INSERTへの対策があるか
15. **ロールバック安全性**: マイグレーションSQLに対応するロールバックSQLが存在するか
16. **ハードコード検出**: URL、APIキー、アカウントID、ポート番号等が環境変数ではなく直書きされていないか

### D. 横展開チェック（1項目）— 修正漏れ防止
17. **横展開（修正の波及確認）**: 変更箇所と同じパターン（同じSQL、同じ関数、同じファイル構造のコピー）がコードベース内の他の場所にも存在する場合、それらも同様に修正されているか。特にlib/→chatwork-webhook/lib/→proactive-monitor/lib/の3箇所同期を確認。1箇所だけ直して他が古いままの場合はFAIL

### E. DBスキーマ整合チェック（1項目）— 2/9本番障害の再発防止
18. **SQLカラム名整合**: diff内のSQL文（SELECT, INSERT, UPDATE, WHERE）で参照しているカラム名が、上記の本番DBスキーマ（db_schema.json）に実在するか確認。存在しないカラム名、テーブル名の参照はFAIL。型キャスト（CAST AS uuid/text/integer）がカラムの実際の型と一致しているかも確認

## 判定基準
- **FAIL**: 項目1-18のいずれか1つでも該当すればFAIL
- **PASS**: 全18項目で問題なしの場合のみPASS

## 回答形式（必ずこの形式で回答すること）
```
## 判定: PASS または FAIL

## A. 基本チェック（項目1-4）
- 各項目の結果

## B. 再発防止チェック（項目5-10）
- 各項目の結果

## C. 未然防止チェック（項目11-16）
- 各項目の結果

## D. 横展開チェック（項目17）
- 結果

## E. DBスキーマ整合チェック（項目18）
- 結果

## 軽微な指摘（FAILにはならないが改善推奨）
```
PROMPT
}

review_prompt_pass2() {
  cat <<'PROMPT'
## 自己検証（Pass 2/3）

あなたは先ほどこのコード差分に対してレビューを行いました。
以下があなたの先ほどのレビュー結果です：

---
PROMPT
  cat "$REVIEW_OUT_PATH"
  cat <<'PROMPT'
---

もう一度diffを最初から読み直してください。
先ほどのレビューで**見落とした問題**がないか確認してください。

特に以下に注意：
- 18項目のうち、実際にはチェックしていなかった項目はないか？
- 「問題なし」と判定した箇所に、本当に問題はなかったか？
- diff全体を通して読んだとき、個別には問題なくても組み合わせで問題になるケースはないか？

## 回答形式
```
## Pass 2 判定: PASS または FAIL

## 見落とし発見
- あれば記載（なければ「見落としなし」）

## 補足・修正
- Pass 1の判定を修正する場合はここに記載
```

## git diff（再確認用）

PROMPT
  cat "$REVIEW_DIFF_PATH"
}

review_prompt_pass3() {
  cat <<'PROMPT'
## 逆視点チェック（Pass 3/3 — Devil's Advocate）

あなたはこのコード差分に対して2回レビューを行い、以下の結果を出しました：

### Pass 1の結果：
---
PROMPT
  cat "$REVIEW_OUT_PATH"
  cat <<'PROMPT'
---

### Pass 2の結果：
---
PROMPT
  cat "$REVIEW_OUT_PASS2"
  cat <<'PROMPT'
---

今回は**あなたの過去2回のレビューが間違っている前提**で、もう一度diffを読んでください。

指示：
- PASSと判定した箇所について「本当にPASSで正しいのか？」を疑え
- 「問題ない」と書いた箇所の**反証**を探せ
- 過去2回で一貫して見落としている盲点がないか確認せよ
- 最終的に問題がなければPASS、新たに問題を発見したらFAIL

## 回答形式
```
## 最終判定: PASS または FAIL

## 反証の試み
- PASSとした各項目に対する反証（見つからなければ「反証なし — PASSを確認」）

## 新規発見事項
- あれば記載（なければ「なし」）

## 最終結論
- 3パスの総合判定と根拠
```

## git diff（最終確認用）

PROMPT
  cat "$REVIEW_DIFF_PATH"
}

# =============================================================================
# Codex Review Execution
# =============================================================================
run_review_pass1() {
  echo "    [Pass 1/3] Standard Review (18 items)..."
  {
    review_prompt_pass1
    echo
    echo "## git diff"
    echo
    cat "$REVIEW_DIFF_PATH"
  } | "$CODEX_BIN" exec - | tee "$REVIEW_OUT_PATH"
}

run_review_pass2() {
  echo "    [Pass 2/3] Self-Verification..."
  {
    review_prompt_pass2
  } | "$CODEX_BIN" exec - | tee "$REVIEW_OUT_PASS2"
}

run_review_pass3() {
  echo "    [Pass 3/3] Devil's Advocate..."
  {
    review_prompt_pass3
  } | "$CODEX_BIN" exec - | tee "$REVIEW_OUT_PASS3"
}

run_multi_pass_review() {
  # Pass 1: Standard Review
  run_review_pass1
  local v1
  v1="$(parse_verdict_from "$REVIEW_OUT_PATH")"
  echo "    Pass 1 verdict: $v1"

  if [[ "$v1" == "FAIL" ]]; then
    echo "    FAIL detected at Pass 1. Skipping further passes."
    cp "$REVIEW_OUT_PATH" "$REVIEW_OUT_PASS3"  # Use pass1 output as final
    return 0
  fi

  if [[ "$REVIEW_PASSES" -lt 2 ]]; then
    cp "$REVIEW_OUT_PATH" "$REVIEW_OUT_PASS3"
    return 0
  fi

  # Pass 2: Self-Verification
  run_review_pass2
  local v2
  v2="$(parse_verdict_from "$REVIEW_OUT_PASS2")"
  echo "    Pass 2 verdict: $v2"

  if [[ "$v2" == "FAIL" ]]; then
    echo "    FAIL detected at Pass 2 (self-verification found issues)."
    cp "$REVIEW_OUT_PASS2" "$REVIEW_OUT_PASS3"
    return 0
  fi

  if [[ "$REVIEW_PASSES" -lt 3 ]]; then
    cp "$REVIEW_OUT_PASS2" "$REVIEW_OUT_PASS3"
    return 0
  fi

  # Pass 3: Devil's Advocate
  run_review_pass3
  local v3
  v3="$(parse_verdict_from "$REVIEW_OUT_PASS3")"
  echo "    Pass 3 verdict: $v3"
}

# =============================================================================
# Claude Code Review (Architecture + Design Coherence)
# =============================================================================
review_prompt_claude() {
  cat <<'PROMPT'
あなたはソウルくんプロジェクトの「世界最高のエンジニア」として、
このdiffをアーキテクチャ観点でレビューしてください。
CLAUDE.mdとAGENTS.mdを参照し、以下の重要項目をチェックすること。

【チェック項目（アーキテクチャ重点9項目）】
1. organization_idフィルタ漏れ: SELECT/INSERT/UPDATE/DELETEにorg_idがあるか
2. asyncブロッキング: async def内でpool.connect()を直接呼んでいないか
3. RLS型キャスト: VARCHARカラムに::uuidキャストしていないか
4. Brain bypass: 脳を通さずに直接テンプレート送信していないか
5. lib/同期: lib/の変更がchatwork-webhook/lib/とproactive-monitor/lib/にも反映されているか
6. fire-and-forget: asyncio.create_task()を直接使っていないか（_fire_and_forget()必須）
7. 設計書との矛盾: Truth順位違反、脳アーキテクチャ違反がないか
8. デプロイ安全性: --set-env-vars（禁止）ではなく--update-env-varsを使っているか
9. PII漏洩: ログにメッセージ本文・名前・メールが含まれていないか

【出力フォーマット（必ずこの形式で）】
```
## 判定: PASS または FAIL

## 指摘事項
- CRITICAL: (件数)
- HIGH: (件数)
- MEDIUM: (件数)

## 詳細
(各指摘の説明)

## 推奨修正
(具体的な修正提案。なければ「なし」)
```

## git diff

PROMPT
}

# CLAUDE_SKIPPED is set by run_claude_review if CLI fails
CLAUDE_SKIPPED=0

run_claude_review() {
  CLAUDE_SKIPPED=0
  echo "  [Claude Code] Architecture review..."
  local prompt_file="/tmp/claude_review_prompt_${REPO_HASH}.txt"
  {
    review_prompt_claude
    cat "$REVIEW_DIFF_PATH"
  } > "$prompt_file"

  : > "$REVIEW_OUT_CLAUDE"

  # Run Claude Code CLI in print mode from project root
  # Claude Code auto-reads CLAUDE.md and AGENTS.md from project directory
  (
    cd "$REPO_ROOT"
    cat "$prompt_file" | "$CLAUDE_BIN" --print \
      --model "$CLAUDE_MODEL" \
      --max-turns 1 \
      --no-session-persistence 2>/dev/null
  ) | tee "$REVIEW_OUT_CLAUDE" || true

  if [[ ! -s "$REVIEW_OUT_CLAUDE" ]]; then
    echo "  WARNING: Claude Code review produced no output. Skipping." >&2
    CLAUDE_SKIPPED=1
  fi
}

# =============================================================================
# Gemini Review (Security + Performance + Code Quality)
# =============================================================================
review_prompt_gemini() {
  cat <<'PROMPT'
あなたはセキュリティとパフォーマンスの専門家です。
このdiffをセキュリティ・パフォーマンス観点でレビューしてください。

【重点チェック項目】
1. セキュリティ脆弱性（OWASP Top 10）
   - SQLインジェクション（パラメータ化されているか）
   - XSS
   - 認証バイパス
   - 機密情報のハードコード
   - SSRF

2. パフォーマンス問題
   - N+1クエリ（ループ内DB問い合わせ）
   - 不要なDB接続（pool.connect()多重呼び出し）
   - メモリリーク
   - 無限ループリスク

3. コード品質
   - エラーハンドリング漏れ（bare except禁止）
   - リソースリーク（DB接続、ファイルハンドル、HTTPクライアント）
   - 冪等性の欠如（二重送信対策）
   - デッドコード

4. Python固有の問題
   - asyncio.to_thread()の不適切な使用
   - mutableなデフォルト引数
   - 接続リーク（asyncio.wait_for + asyncio.to_thread の組み合わせ禁止）

【出力フォーマット（必ずこの形式で）】
```
## 判定: PASS または FAIL

## セキュリティ
(指摘事項。なければ「問題なし」)

## パフォーマンス
(指摘事項。なければ「問題なし」)

## コード品質
(指摘事項。なければ「問題なし」)

## 推奨修正
(具体的な修正提案。なければ「なし」)
```

## git diff

PROMPT
}

# GEMINI_SKIPPED is set by run_gemini_review if CLI fails
GEMINI_SKIPPED=0

run_gemini_review() {
  GEMINI_SKIPPED=0
  echo "  [Gemini] Security & Performance review..."
  local prompt_file="/tmp/gemini_review_prompt_${REPO_HASH}.txt"
  {
    review_prompt_gemini
    cat "$REVIEW_DIFF_PATH"
  } > "$prompt_file"

  : > "$REVIEW_OUT_GEMINI"

  cat "$prompt_file" | "$GEMINI_BIN" \
    -m "$GEMINI_MODEL" \
    -o text \
    2>/dev/null | tee "$REVIEW_OUT_GEMINI" || true

  if [[ ! -s "$REVIEW_OUT_GEMINI" ]]; then
    echo "  WARNING: Gemini review produced no output. Skipping." >&2
    GEMINI_SKIPPED=1
  fi
}

# =============================================================================
# Verdict parsing
# =============================================================================
parse_verdict_from() {
  local file="$1"
  local cleaned
  cleaned="$(tr -d '\r' < "$file" | sed -E 's/\x1B\[[0-9;]*[mK]//g')"

  # IMPORTANT: Check FAIL before PASS to avoid false positives
  # (if output contains both "判定: FAIL" and "PASS" text, FAIL wins)

  # Check for 最終判定 first (Pass 3 format)
  if printf "%s" "$cleaned" | grep -E "(最終)?判定[:：][[:space:]]*FAIL" >/dev/null 2>&1; then
    echo "FAIL"
    return 0
  fi
  if printf "%s" "$cleaned" | grep -E "(最終)?判定[:：][[:space:]]*PASS" >/dev/null 2>&1; then
    echo "PASS"
    return 0
  fi
  # Check Pass 2 format
  if printf "%s" "$cleaned" | grep -E "Pass 2 判定[:：][[:space:]]*FAIL" >/dev/null 2>&1; then
    echo "FAIL"
    return 0
  fi
  if printf "%s" "$cleaned" | grep -E "Pass 2 判定[:：][[:space:]]*PASS" >/dev/null 2>&1; then
    echo "PASS"
    return 0
  fi
  # Fallback: detect FAIL word boundary-ish first
  if printf "%s" "$cleaned" | grep -E '(^|[^A-Z])FAIL([^A-Z]|$)' >/dev/null 2>&1; then
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

parse_verdict() {
  # Final Codex verdict comes from the last pass output
  parse_verdict_from "$REVIEW_OUT_PASS3"
}

# =============================================================================
# Test execution
# =============================================================================
run_tests() {
  if [[ "$RUN_FULL_TESTS" -eq 1 ]]; then
    echo "Running full tests: $FULL_TEST_CMD"
    eval "$FULL_TEST_CMD"
  else
    echo "Running partial tests: $PARTIAL_TEST_CMD"
    eval "$PARTIAL_TEST_CMD"
  fi
}

# =============================================================================
# Main loop — 3AI review + tests
# =============================================================================
ACTIVE_AIS=$(count_active_ais)

for attempt in $(seq 1 "$MAX_LOOPS"); do
  echo ""
  echo "=== 3AI Review Attempt $attempt/$MAX_LOOPS ($ACTIVE_AIS AIs active) ==="
  build_diff

  if [[ ! -s "$REVIEW_DIFF_PATH" ]]; then
    echo "No diffs found. Nothing to review."
    echo "Skipping review."
    exit 0
  fi

  ALL_PASS=1
  AI_INDEX=1
  CODEX_VERDICT=""
  CLAUDE_VERDICT=""
  GEMINI_VERDICT=""

  # --- [1] Codex 3-pass review (18 items) ---
  echo ""
  echo "  [$AI_INDEX/$ACTIVE_AIS] Codex 3-pass Review (18 items, ${REVIEW_PASSES} passes)"
  run_multi_pass_review
  CODEX_VERDICT="$(parse_verdict | tr -d '\r' | xargs)"
  echo "  => Codex: $CODEX_VERDICT"
  [[ "$CODEX_VERDICT" != "PASS" ]] && ALL_PASS=0
  AI_INDEX=$((AI_INDEX + 1))

  # --- [2] Claude Code review (Architecture) ---
  if [[ "$ENABLE_CLAUDE" == "1" ]]; then
    echo ""
    echo "  [$AI_INDEX/$ACTIVE_AIS] Claude Code Review (Architecture)"
    run_claude_review
    if [[ "$CLAUDE_SKIPPED" -eq 1 ]]; then
      CLAUDE_VERDICT="SKIP"
      echo "  => Claude: SKIPPED (CLI error)"
    else
      CLAUDE_VERDICT="$(parse_verdict_from "$REVIEW_OUT_CLAUDE" | tr -d '\r' | xargs)"
      echo "  => Claude: $CLAUDE_VERDICT"
      [[ "$CLAUDE_VERDICT" != "PASS" ]] && ALL_PASS=0
    fi
    AI_INDEX=$((AI_INDEX + 1))
  fi

  # --- [3] Gemini review (Security & Performance) ---
  if [[ "$ENABLE_GEMINI" == "1" ]]; then
    echo ""
    echo "  [$AI_INDEX/$ACTIVE_AIS] Gemini Review (Security & Performance)"
    run_gemini_review
    if [[ "$GEMINI_SKIPPED" -eq 1 ]]; then
      GEMINI_VERDICT="SKIP"
      echo "  => Gemini: SKIPPED (CLI error)"
    else
      GEMINI_VERDICT="$(parse_verdict_from "$REVIEW_OUT_GEMINI" | tr -d '\r' | xargs)"
      echo "  => Gemini: $GEMINI_VERDICT"
      [[ "$GEMINI_VERDICT" != "PASS" ]] && ALL_PASS=0
    fi
  fi

  # --- Summary ---
  echo ""
  echo "  ======================================="
  echo "  3AI Review Summary"
  echo "  ======================================="
  echo "  Codex:       $CODEX_VERDICT"
  [[ "$ENABLE_CLAUDE" == "1" ]] && echo "  Claude Code: $CLAUDE_VERDICT"
  [[ "$ENABLE_GEMINI" == "1" ]] && echo "  Gemini:      $GEMINI_VERDICT"
  echo "  ======================================="

  if [[ "$ALL_PASS" -eq 1 ]]; then
    echo "  ALL PASS"
    echo ""
    run_tests
    echo "3AI Review + tests completed."
    exit 0
  fi

  echo "  FAIL detected. Fix issues, then press Enter to re-run (or Ctrl+C to stop)."
  read -r
done

echo "Max review attempts reached ($MAX_LOOPS). Escalate to human decision."
exit 2
