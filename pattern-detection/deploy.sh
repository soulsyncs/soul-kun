#!/bin/bash
# =====================================================
# Phase 2 A1: パターン検知 Cloud Functions デプロイスクリプト
# =====================================================
#
# 使い方:
#   ./deploy.sh [test|prod]
#
# オプション:
#   test (デフォルト): テストモードでデプロイ
#                     DRY_RUN=true
#   prod: 本番モードでデプロイ
#         DRY_RUN=false
#
# このスクリプトは以下を行います:
# 1. soul-kun/lib/ から必要なファイルをコピー
# 2. 2つのCloud Functions をデプロイ
#    - pattern-detection: パターン検知（毎時実行）
#    - weekly-report: 週次レポート（毎週月曜）
# =====================================================

set -e  # エラー時に停止

MODE="${1:-test}"  # デフォルトはテストモード

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LIB_SRC="$SCRIPT_DIR/../lib"
LIB_DST="$SCRIPT_DIR/lib"

# テストモード設定
if [ "$MODE" = "prod" ]; then
    DRY_RUN="false"
    TEST_MODE="false"
    echo "=============================================="
    echo "⚠️  本番モード でデプロイします"
    echo "=============================================="
    read -p "本当に本番モードでデプロイしますか？ (yes/no): " confirm
    if [ "$confirm" != "yes" ]; then
        echo "キャンセルしました"
        exit 1
    fi
else
    DRY_RUN="true"
    TEST_MODE="true"
    echo "=============================================="
    echo "🧪 テストモード でデプロイします"
    echo "   DRY_RUN=true（DBへの書き込みなし）"
    echo "=============================================="
fi

# =====================================================
# Step 1: libディレクトリをコピー
# =====================================================
echo ""
echo "📦 Step 1: libディレクトリをコピー中..."

# 既存のlibを削除
rm -rf "$LIB_DST"
mkdir -p "$LIB_DST"

# 必要なファイルをコピー
# detection モジュール
mkdir -p "$LIB_DST/detection"
cp "$LIB_SRC/detection/__init__.py" "$LIB_DST/detection/"
cp "$LIB_SRC/detection/base.py" "$LIB_DST/detection/"
cp "$LIB_SRC/detection/constants.py" "$LIB_DST/detection/"
cp "$LIB_SRC/detection/exceptions.py" "$LIB_DST/detection/"
cp "$LIB_SRC/detection/pattern_detector.py" "$LIB_DST/detection/"
cp "$LIB_SRC/detection/personalization_detector.py" "$LIB_DST/detection/"
cp "$LIB_SRC/detection/bottleneck_detector.py" "$LIB_DST/detection/"
cp "$LIB_SRC/detection/emotion_detector.py" "$LIB_DST/detection/"

# insights モジュール
mkdir -p "$LIB_DST/insights"
cp "$LIB_SRC/insights/__init__.py" "$LIB_DST/insights/"
cp "$LIB_SRC/insights/insight_service.py" "$LIB_DST/insights/"
cp "$LIB_SRC/insights/weekly_report_service.py" "$LIB_DST/insights/"

# 共通ライブラリ（main.pyが直接import）
for f in db.py secrets.py config.py audit.py text_utils.py; do
    if [ -f "$LIB_SRC/$f" ]; then
        cp "$LIB_SRC/$f" "$LIB_DST/"
    fi
done

# lib/__init__.py を作成
cat > "$LIB_DST/__init__.py" << 'EOF'
"""
Phase 2 A1/A2: パターン検知・属人化検出用 lib モジュール

このモジュールは pattern-detection Cloud Function で使用される
共通ライブラリです。
"""

# detection モジュール
from lib.detection import (
    PatternDetector,
    PersonalizationDetector,
    BaseDetector,
    DetectionResult,
    DetectionContext,
    InsightData,
)

# insights モジュール
from lib.insights import (
    InsightService,
    WeeklyReportService,
)

__all__ = [
    "PatternDetector",
    "PersonalizationDetector",
    "BaseDetector",
    "DetectionResult",
    "DetectionContext",
    "InsightData",
    "InsightService",
    "WeeklyReportService",
]
EOF

echo "✅ libディレクトリのコピー完了"

# =====================================================
# Step 2: .gcloudignore を作成
# =====================================================
echo ""
echo "📝 Step 2: .gcloudignore を作成中..."

cat > "$SCRIPT_DIR/.gcloudignore" << 'EOF'
# Git
.git
.gitignore

# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib64/
parts/
sdist/
var/
wheels/
*.egg-info/
.installed.cfg
*.egg

# Virtual environments
.env
.venv
env/
venv/
ENV/
env.bak/
venv.bak/

# IDE
.idea/
.vscode/
*.swp
*.swo

# Test
tests/
test_*.py
*_test.py
pytest.ini
.pytest_cache/

# Documentation
*.md
docs/

# Scripts (except deploy.sh)
*.sh
!deploy.sh

# Temporary files
*.log
*.tmp
temp.txt
EOF

echo "✅ .gcloudignore 作成完了"

# =====================================================
# Step 3: パターン検知関数をデプロイ
# =====================================================
echo ""
echo "🚀 Step 3: pattern-detection 関数をデプロイ中..."

gcloud functions deploy pattern-detection \
    --gen2 \
    --runtime=python311 \
    --region=asia-northeast1 \
    --source="$SCRIPT_DIR" \
    --entry-point=pattern_detection \
    --trigger-http \
    --no-allow-unauthenticated \
    --memory=512MB \
    --timeout=300s \
    --update-env-vars="DRY_RUN=$DRY_RUN,TEST_MODE=$TEST_MODE" \
    --min-instances=0 \
    --max-instances=5

echo "✅ pattern-detection デプロイ完了"

# =====================================================
# Step 4: 属人化検出関数をデプロイ
# =====================================================
echo ""
echo "🚀 Step 4: personalization-detection 関数をデプロイ中..."

gcloud functions deploy personalization-detection \
    --gen2 \
    --runtime=python311 \
    --region=asia-northeast1 \
    --source="$SCRIPT_DIR" \
    --entry-point=personalization_detection \
    --trigger-http \
    --no-allow-unauthenticated \
    --memory=512MB \
    --timeout=300s \
    --update-env-vars="DRY_RUN=$DRY_RUN,TEST_MODE=$TEST_MODE" \
    --min-instances=0 \
    --max-instances=3

echo "✅ personalization-detection デプロイ完了"

# =====================================================
# Step 5: 週次レポート関数をデプロイ
# =====================================================
echo ""
echo "🚀 Step 5: weekly-report 関数をデプロイ中..."

gcloud functions deploy weekly-report \
    --gen2 \
    --runtime=python311 \
    --region=asia-northeast1 \
    --source="$SCRIPT_DIR" \
    --entry-point=weekly_report \
    --trigger-http \
    --no-allow-unauthenticated \
    --memory=512MB \
    --timeout=300s \
    --update-env-vars="DRY_RUN=$DRY_RUN,TEST_MODE=$TEST_MODE" \
    --min-instances=0 \
    --max-instances=1

echo "✅ weekly-report デプロイ完了"

# =====================================================
# Step 6: Cloud Scheduler ジョブを作成/更新
# =====================================================
echo ""
echo "⏰ Step 6: Cloud Scheduler ジョブを設定中..."

# パターン検知: 毎時実行（毎時15分に実行）
PATTERN_JOB_EXISTS=$(gcloud scheduler jobs list --location=asia-northeast1 --format="value(name)" 2>/dev/null | grep "pattern-detection-hourly" || true)

if [ -z "$PATTERN_JOB_EXISTS" ]; then
    echo "   新規作成: pattern-detection-hourly"
    gcloud scheduler jobs create http pattern-detection-hourly \
        --location=asia-northeast1 \
        --schedule="15 * * * *" \
        --time-zone="Asia/Tokyo" \
        --uri="https://asia-northeast1-soulkun-production.cloudfunctions.net/pattern-detection" \
        --http-method=POST \
        --headers="Content-Type=application/json" \
        --message-body='{"hours_back": 1}' \
        --attempt-deadline=300s \
        --description="Phase 2 A1: パターン検知（毎時実行）"
else
    echo "   更新: pattern-detection-hourly"
    gcloud scheduler jobs update http pattern-detection-hourly \
        --location=asia-northeast1 \
        --schedule="15 * * * *" \
        --time-zone="Asia/Tokyo" \
        --uri="https://asia-northeast1-soulkun-production.cloudfunctions.net/pattern-detection" \
        --http-method=POST \
        --update-headers="Content-Type=application/json" \
        --message-body='{"hours_back": 1}' \
        --attempt-deadline=300s
fi

# 属人化検出: 毎日実行（毎日6:00 JSTに実行）
PERSONALIZATION_JOB_EXISTS=$(gcloud scheduler jobs list --location=asia-northeast1 --format="value(name)" 2>/dev/null | grep "personalization-detection-daily" || true)

if [ -z "$PERSONALIZATION_JOB_EXISTS" ]; then
    echo "   新規作成: personalization-detection-daily"
    gcloud scheduler jobs create http personalization-detection-daily \
        --location=asia-northeast1 \
        --schedule="0 6 * * *" \
        --time-zone="Asia/Tokyo" \
        --uri="https://asia-northeast1-soulkun-production.cloudfunctions.net/personalization-detection" \
        --http-method=POST \
        --headers="Content-Type=application/json" \
        --message-body='{}' \
        --attempt-deadline=300s \
        --description="Phase 2 A2: 属人化検出（毎日実行）"
else
    echo "   更新: personalization-detection-daily"
    gcloud scheduler jobs update http personalization-detection-daily \
        --location=asia-northeast1 \
        --schedule="0 6 * * *" \
        --time-zone="Asia/Tokyo" \
        --uri="https://asia-northeast1-soulkun-production.cloudfunctions.net/personalization-detection" \
        --http-method=POST \
        --update-headers="Content-Type=application/json" \
        --message-body='{}' \
        --attempt-deadline=300s
fi

# 週次レポート: 毎週月曜 9:00 JST
WEEKLY_JOB_EXISTS=$(gcloud scheduler jobs list --location=asia-northeast1 --format="value(name)" 2>/dev/null | grep "weekly-report-monday" || true)

if [ -z "$WEEKLY_JOB_EXISTS" ]; then
    echo "   新規作成: weekly-report-monday"
    gcloud scheduler jobs create http weekly-report-monday \
        --location=asia-northeast1 \
        --schedule="0 9 * * 1" \
        --time-zone="Asia/Tokyo" \
        --uri="https://asia-northeast1-soulkun-production.cloudfunctions.net/weekly-report" \
        --http-method=POST \
        --headers="Content-Type=application/json" \
        --message-body='{"room_id": 417892193}' \
        --attempt-deadline=300s \
        --description="Phase 2 A1: 週次レポート（毎週月曜9:00）"
else
    echo "   更新: weekly-report-monday"
    gcloud scheduler jobs update http weekly-report-monday \
        --location=asia-northeast1 \
        --schedule="0 9 * * 1" \
        --time-zone="Asia/Tokyo" \
        --uri="https://asia-northeast1-soulkun-production.cloudfunctions.net/weekly-report" \
        --http-method=POST \
        --update-headers="Content-Type=application/json" \
        --message-body='{"room_id": 417892193}' \
        --attempt-deadline=300s
fi

echo "✅ Cloud Scheduler 設定完了"

# =====================================================
# 完了
# =====================================================
echo ""
echo "=============================================="
echo "🎉 デプロイ完了！"
echo "=============================================="
echo ""
echo "デプロイされた関数:"
echo "  - pattern-detection: https://asia-northeast1-soulkun-production.cloudfunctions.net/pattern-detection"
echo "  - personalization-detection: https://asia-northeast1-soulkun-production.cloudfunctions.net/personalization-detection"
echo "  - weekly-report: https://asia-northeast1-soulkun-production.cloudfunctions.net/weekly-report"
echo ""
echo "Cloud Scheduler ジョブ:"
echo "  - pattern-detection-hourly: 毎時15分に実行"
echo "  - personalization-detection-daily: 毎日6:00 JSTに実行"
echo "  - weekly-report-monday: 毎週月曜9:00 JSTに実行"
echo ""
if [ "$MODE" = "test" ]; then
    echo "⚠️  テストモードでデプロイされています"
    echo "   本番モードでデプロイするには: ./deploy.sh prod"
fi
echo ""
echo "手動テスト:"
echo "  curl -X POST https://asia-northeast1-soulkun-production.cloudfunctions.net/pattern-detection \\"
echo "       -H 'Content-Type: application/json' \\"
echo "       -d '{\"hours_back\": 24, \"dry_run\": true}'"
echo ""
