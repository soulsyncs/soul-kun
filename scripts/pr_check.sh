#!/usr/bin/env bash
set -euo pipefail

echo "=== PR Check Script ==="

echo ""
echo "[1] git status"
git status

echo ""
echo "[2] diff summary vs origin/main"
git fetch origin main >/dev/null 2>&1 || true
git diff --stat origin/main...HEAD || true

echo ""
echo "[3] changed files"
git diff --name-only origin/main...HEAD || true

echo ""
echo "[4] basic secret scan (best effort)"
# 軽い検出だけ（誤検知あり）
grep -RIn --exclude-dir=.git --exclude='*.lock' \
  -E '(OPENAI_API_KEY|OPENROUTER|API_KEY|SECRET|TOKEN|PASSWORD|BEGIN PRIVATE KEY)' \
  . || echo "No obvious secrets found."

echo ""
echo "[5] suggested checks"
if [ -f "pyproject.toml" ]; then
  echo "Run: python -m pytest"
  echo "Run: ruff check ."
fi
if [ -f "package.json" ]; then
  echo "Run: npm test"
  echo "Run: npm run lint"
fi

echo ""
echo "=== Done ==="
