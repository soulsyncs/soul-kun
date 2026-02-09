#!/usr/bin/env bash
set -euo pipefail

# Codex review loop (ChatGPT login, no API).
# 3-pass review: Standard → Self-verification → Devil's Advocate
#
# Usage:
#   scripts/codex_review_loop.sh            # review + partial tests
#   scripts/codex_review_loop.sh --full     # review + full tests
# Env:
#   MAX_LOOPS=3
#   PARTIAL_TEST_CMD="python3 -m pytest tests/ --tb=short -k user_utils"
#   FULL_TEST_CMD="python3 -m pytest tests/ --tb=short"
#   REVIEW_DOCS=$'docs/25_llm_native_brain_architecture.md\nCLAUDE.md'
#   CODEX_BIN="$HOME/.npm-global/bin/codex"
#   REVIEW_PASSES=3  # Number of review passes (1-3)

MAX_LOOPS="${MAX_LOOPS:-3}"
REVIEW_PASSES="${REVIEW_PASSES:-3}"
PARTIAL_TEST_CMD="${PARTIAL_TEST_CMD:-python3 -m pytest tests/ --tb=short}"
FULL_TEST_CMD="${FULL_TEST_CMD:-python3 -m pytest tests/ --tb=short}"
REPO_HASH=$(git rev-parse --show-toplevel 2>/dev/null | md5 | cut -c1-8)
REVIEW_DIFF_PATH="${REVIEW_DIFF_PATH:-/tmp/codex_review_diff_${REPO_HASH}.txt}"
REVIEW_OUT_PATH="${REVIEW_OUT_PATH:-/tmp/codex_review_output_${REPO_HASH}.txt}"
REVIEW_OUT_PASS2="${REVIEW_OUT_PATH%.txt}_pass2.txt"
REVIEW_OUT_PASS3="${REVIEW_OUT_PATH%.txt}_pass3.txt"
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

# =============================================================================
# Pass 1: Standard Review (17 check items)
# =============================================================================
review_prompt_pass1() {
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
以下の17項目で厳密にレビューしてください。1項目でも該当すればFAILです。

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

## 判定基準
- **FAIL**: 項目1-17のいずれか1つでも該当すればFAIL
- **PASS**: 全17項目で問題なしの場合のみPASS

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

## 軽微な指摘（FAILにはならないが改善推奨）
```
PROMPT
}

# =============================================================================
# Pass 2: Self-Verification (自己検証)
# =============================================================================
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
- 17項目のうち、実際にはチェックしていなかった項目はないか？
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

# =============================================================================
# Pass 3: Devil's Advocate (逆視点チェック)
# =============================================================================
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
# Review execution functions
# =============================================================================

run_review_pass1() {
  echo "  [Pass 1/3] Standard Review (17 items)..."
  {
    review_prompt_pass1
    echo
    echo "## git diff"
    echo
    cat "$REVIEW_DIFF_PATH"
  } | "$CODEX_BIN" exec - | tee "$REVIEW_OUT_PATH"
}

run_review_pass2() {
  echo "  [Pass 2/3] Self-Verification..."
  {
    review_prompt_pass2
  } | "$CODEX_BIN" exec - | tee "$REVIEW_OUT_PASS2"
}

run_review_pass3() {
  echo "  [Pass 3/3] Devil's Advocate..."
  {
    review_prompt_pass3
  } | "$CODEX_BIN" exec - | tee "$REVIEW_OUT_PASS3"
}

run_multi_pass_review() {
  # Pass 1: Standard Review
  run_review_pass1
  local v1
  v1="$(parse_verdict_from "$REVIEW_OUT_PATH")"
  echo "  Pass 1 verdict: $v1"

  if [[ "$v1" == "FAIL" ]]; then
    echo "  FAIL detected at Pass 1. Skipping further passes."
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
  echo "  Pass 2 verdict: $v2"

  if [[ "$v2" == "FAIL" ]]; then
    echo "  FAIL detected at Pass 2 (self-verification found issues)."
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
  echo "  Pass 3 verdict: $v3"
}

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
  # Final verdict comes from the last pass output
  parse_verdict_from "$REVIEW_OUT_PASS3"
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
  echo "=== Codex Review Attempt $attempt/$MAX_LOOPS (${REVIEW_PASSES}-pass) ==="
  build_diff

  if [[ ! -s "$REVIEW_DIFF_PATH" ]]; then
    echo "No diffs found. Nothing to review."
    echo "Skipping review."
    exit 0
  fi

  run_multi_pass_review
  verdict="$(parse_verdict | tr -d '\r' | xargs)"

  if [[ "$verdict" == "PASS" ]]; then
    echo "Review PASS (all ${REVIEW_PASSES} passes)."
    run_tests
    echo "Review + tests completed."
    exit 0
  fi

  echo "Review FAIL. Fix issues, then press Enter to re-run (or Ctrl+C to stop)."
  read -r
done

echo "Max review attempts reached ($MAX_LOOPS). Escalate to human decision."
exit 2
