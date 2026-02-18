#!/bin/bash
# validate_async_patterns.sh — 非同期パターン+運用安全性の自動検証
# CLAUDE.md §3-2 セクションF（項目19-22）に対応
# pre-pushフック、CI、手動実行で使用
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

ERRORS=0
WARNINGS=0

check() {
    local code="$1"
    local desc="$2"
    local pattern="$3"
    local target="$4"
    local severity="${5:-ERROR}"
    local exclude="${6:-}"

    local grep_args=(-rn "$pattern" "$target" --include="*.py")
    if [ -n "$exclude" ]; then
        grep_args+=(--exclude="$exclude")
    fi

    local matches
    matches=$(grep "${grep_args[@]}" 2>/dev/null || true)

    if [ -n "$matches" ]; then
        if [ "$severity" = "ERROR" ]; then
            echo -e "${RED}FAIL${NC} [$code] $desc"
            ERRORS=$((ERRORS + 1))
        else
            echo -e "${YELLOW}WARN${NC} [$code] $desc"
            WARNINGS=$((WARNINGS + 1))
        fi
        echo "$matches" | head -5
        local count
        count=$(echo "$matches" | wc -l | tr -d ' ')
        if [ "$count" -gt 5 ]; then
            echo "  ... and $((count - 5)) more"
        fi
        echo ""
    else
        echo -e "${GREEN}PASS${NC} [$code] $desc"
    fi
}

echo "========================================"
echo "  Async Pattern & Safety Validator"
echo "  CLAUDE.md §3-2 Section F (#19-22)"
echo "========================================"
echo ""

# AP-01: fire-and-forget安全性（#19）
# asyncio.create_task() が _fire_and_forget の外で使われていないか
# v11.2.0: core.py（旧）からlib/brain/全体に拡張。分割後のcore/サブパッケージに対応。
echo "--- #19: fire-and-forget安全性 ---"
# 許可: _fire_and_forget ヘルパー内の "task = asyncio.create_task(coro)"
# 許可: shadow mode の gather パターン（integration.py: brain_task/fallback_task）
# 禁止: それ以外の全 asyncio.create_task() 呼び出し
ap01_matches=$(grep -rn "asyncio\.create_task(" lib/brain/ --include="*.py" 2>/dev/null \
    | grep -v "task = asyncio\.create_task(coro)" \
    | grep -v "brain_task = asyncio\.create_task\|fallback_task = asyncio\.create_task" \
    || true)
if [ -n "$ap01_matches" ]; then
    echo -e "${RED}FAIL${NC} [AP-01] asyncio.create_task() outside _fire_and_forget detected"
    echo "$ap01_matches" | head -10
    ap01_count=$(echo "$ap01_matches" | wc -l | tr -d ' ')
    if [ "$ap01_count" -gt 10 ]; then
        echo "  ... and $((ap01_count - 10)) more"
    fi
    ERRORS=$((ERRORS + 1))
else
    echo -e "${GREEN}PASS${NC} [AP-01] All create_task inside _fire_and_forget (or gather pattern)"
fi
echo ""

# AP-02: wait_for+to_thread組み合わせ禁止（#20）
echo "--- #20: 接続/クライアント管理 ---"
check "AP-02" "wait_for(asyncio.to_thread) combo (connection leak risk)" \
    "wait_for.*to_thread\|to_thread.*wait_for" "lib/brain/"

# AP-03: per-call httpx.AsyncClient（#20）
check "AP-03" "Per-call httpx.AsyncClient() creation" \
    "async with httpx.AsyncClient()" "lib/brain/"

# AP-04: str(e) PII漏洩（#8 強化）
# WARN: str(e)はエラーメッセージをログに出力する際に使われる。
# 新規コードでは type(e).__name__ を使うこと。既存コードは段階的に移行予定。
echo "--- #8: PII漏洩チェック（強化） ---"
check "AP-04" "str(e) in error handling (PII leak — use type(e).__name__ instead)" \
    'str(e)\|str(err)' "lib/brain/" "WARN"

# AP-05: shutdown(wait=False) 禁止（#21）
echo "--- #21: イベントループライフサイクル ---"
# observability.pyのThreadPoolExecutor.shutdown(wait=False)は意図的（非同期フラッシュ）なので除外
ap05_matches=$(grep -rn "shutdown(wait=False)" chatwork-webhook/ --include="*.py" 2>/dev/null | grep -v "observability.py" || true)
if [ -n "$ap05_matches" ]; then
    echo -e "${RED}FAIL${NC} [AP-05] shutdown(wait=False) — tasks may be lost"
    echo "$ap05_matches"
    ERRORS=$((ERRORS + 1))
else
    echo -e "${GREEN}PASS${NC} [AP-05] No unsafe shutdown(wait=False)"
fi

# AP-06: 診断ログ残存（情報品質）
check "AP-06" "Debug markers in production code" \
    '\[STEP-[0-9]\]\|\[DEBUG-\]\|\[TEMP\]' "lib/brain/" "WARN"

# AP-07: --set-env-vars 禁止（#22）
echo "--- #22: デプロイスクリプト安全性 ---"
set_env_matches=$(grep -rn "\-\-set-env-vars" . --include="*.sh" --include="*.yaml" --include="*.yml" 2>/dev/null | grep -v "update-env-vars\|validate_async\|#.*AP-07\|# " || true)
if [ -n "$set_env_matches" ]; then
    echo -e "${RED}FAIL${NC} [AP-07] --set-env-vars found (use --update-env-vars instead)"
    echo "$set_env_matches"
    ERRORS=$((ERRORS + 1))
else
    echo -e "${GREEN}PASS${NC} [AP-07] No --set-env-vars (all use --update-env-vars)"
fi
echo ""

# AP-08: bare except: pass（#12 強化）
echo "--- #12: エラーハンドリング漏れ（強化） ---"
bare_pass=$(grep -rn "except.*:" lib/brain/ --include="*.py" -A1 2>/dev/null | grep -B1 "^\s*pass$" | grep "except" | grep -v "rb_err\|reset_err\|retry_err\|rollback" || true)
if [ -n "$bare_pass" ]; then
    echo -e "${YELLOW}WARN${NC} [AP-08] Bare except:pass without logging"
    echo "$bare_pass" | head -5
    WARNINGS=$((WARNINGS + 1))
else
    echo -e "${GREEN}PASS${NC} [AP-08] No bare except:pass without logging"
fi
echo ""

# Summary
echo "========================================"
if [ $ERRORS -gt 0 ]; then
    echo -e "${RED}FAILED: $ERRORS error(s), $WARNINGS warning(s)${NC}"
    exit 1
elif [ $WARNINGS -gt 0 ]; then
    echo -e "${YELLOW}PASSED with $WARNINGS warning(s)${NC}"
    exit 0
else
    echo -e "${GREEN}ALL PASSED: 0 errors, 0 warnings${NC}"
    exit 0
fi
