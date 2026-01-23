#!/bin/bash
# =====================================================
# Phase 2.5 目標達成支援 Cloud Functions デプロイスクリプト
# =====================================================
#
# 使い方:
#   ./deploy_goal_functions.sh [test|prod]
#
# オプション:
#   test (デフォルト): テストモードでデプロイ
#                     GOAL_TEST_MODE=true
#                     GOAL_TEST_ROOM_IDS=417892193 (カズさんDM)
#   prod: 本番モードでデプロイ
#         GOAL_TEST_MODE=false
#
# このスクリプトは以下を行います:
# 1. soul-kun/lib/ から必要なファイルをコピー
# 2. 4つの目標通知 Cloud Functions をデプロイ
# =====================================================

set -e  # エラー時に停止

MODE="${1:-test}"  # デフォルトはテストモード

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LIB_SRC="$SCRIPT_DIR/../lib"
LIB_DST="$SCRIPT_DIR/lib"
ENV_FILE="$SCRIPT_DIR/.env.goal.yaml"

# 組織ID（ソウルシンクス）
ORG_ID="5f98365f-e7c5-4f48-9918-7fe9aabae5df"

# テストモード設定
if [ "$MODE" = "prod" ]; then
    GOAL_TEST_MODE="false"
    GOAL_TEST_ROOM_IDS=""
    echo "=============================================="
    echo "⚠️  本番モード でデプロイします"
    echo "=============================================="
    read -p "本当に本番モードでデプロイしますか？ (yes/no): " confirm
    if [ "$confirm" != "yes" ]; then
        echo "キャンセルしました"
        exit 1
    fi
else
    GOAL_TEST_MODE="true"
    GOAL_TEST_ROOM_IDS="417892193"  # カズさんDM
    echo "=============================================="
    echo "🧪 テストモード でデプロイします"
    echo "   許可ルームID: $GOAL_TEST_ROOM_IDS (カズさんDM)"
    echo "=============================================="
fi

echo ""
echo "📁 共通ライブラリをコピー中..."
mkdir -p "$LIB_DST"

# goal_notification.py をコピー
cp "$LIB_SRC/goal_notification.py" "$LIB_DST/"
echo "   ✅ goal_notification.py"

# __init__.py を作成（存在しない場合）
if [ ! -f "$LIB_DST/__init__.py" ]; then
    cat > "$LIB_DST/__init__.py" << 'EOF'
"""
remind-tasks/lib - Cloud Functions用ローカルライブラリ

このディレクトリにはデプロイ時にsoul-kun/lib/からコピーされた
モジュールが配置されます。
"""
from .goal_notification import (
    scheduled_daily_check,
    scheduled_daily_reminder,
    scheduled_morning_feedback,
    scheduled_consecutive_unanswered_check,
    GOAL_TEST_MODE,
    GOAL_TEST_ALLOWED_ROOM_IDS,
    is_goal_test_send_allowed,
    log_goal_test_mode_status,
)
EOF
    echo "   ✅ __init__.py (新規作成)"
else
    echo "   ✅ __init__.py (既存)"
fi

# 環境変数YAMLファイルを作成（特殊文字を含む値を安全に渡すため）
echo "📝 環境変数ファイルを作成中..."
cat > "$ENV_FILE" << EOF
CORS_ORIGINS: "https://org-chart.soulsyncs.jp,https://soulsyncs.jp,http://localhost:3000,http://localhost:8080"
DB_NAME: soulkun_tasks
DB_USER: soulkun_user
DEBUG: "false"
ENVIRONMENT: production
INSTANCE_CONNECTION_NAME: soulkun-production:asia-northeast1:soulkun-db
LOG_EXECUTION_ID: "true"
PROJECT_ID: soulkun-production
GOAL_TEST_MODE: "$GOAL_TEST_MODE"
DEFAULT_ORG_ID: "$ORG_ID"
EOF

# テストモードの場合のみ GOAL_TEST_ROOM_IDS を追加
if [ -n "$GOAL_TEST_ROOM_IDS" ]; then
    echo "GOAL_TEST_ROOM_IDS: \"$GOAL_TEST_ROOM_IDS\"" >> "$ENV_FILE"
fi

echo "   ✅ .env.goal.yaml 作成完了"

echo ""
echo "🚀 Cloud Functions にデプロイ中..."
echo ""

# 1. goal_daily_check (17:00 進捗確認)
echo "📤 [1/4] goal-daily-check をデプロイ中..."
gcloud functions deploy goal-daily-check \
    --gen2 \
    --runtime=python311 \
    --region=asia-northeast1 \
    --source="$SCRIPT_DIR" \
    --entry-point=goal_daily_check \
    --trigger-http \
    --allow-unauthenticated \
    --memory=512MB \
    --timeout=540s \
    --env-vars-file="$ENV_FILE" \
    --set-secrets=CHATWORK_API_TOKEN=CHATWORK_API_TOKEN:latest,SOULKUN_CHATWORK_TOKEN=SOULKUN_CHATWORK_TOKEN:latest

echo "   ✅ goal-daily-check デプロイ完了"

# 2. goal_daily_reminder (18:00 未回答リマインド)
echo "📤 [2/4] goal-daily-reminder をデプロイ中..."
gcloud functions deploy goal-daily-reminder \
    --gen2 \
    --runtime=python311 \
    --region=asia-northeast1 \
    --source="$SCRIPT_DIR" \
    --entry-point=goal_daily_reminder \
    --trigger-http \
    --allow-unauthenticated \
    --memory=512MB \
    --timeout=540s \
    --env-vars-file="$ENV_FILE" \
    --set-secrets=CHATWORK_API_TOKEN=CHATWORK_API_TOKEN:latest,SOULKUN_CHATWORK_TOKEN=SOULKUN_CHATWORK_TOKEN:latest

echo "   ✅ goal-daily-reminder デプロイ完了"

# 3. goal_morning_feedback (08:00 朝フィードバック)
echo "📤 [3/4] goal-morning-feedback をデプロイ中..."
gcloud functions deploy goal-morning-feedback \
    --gen2 \
    --runtime=python311 \
    --region=asia-northeast1 \
    --source="$SCRIPT_DIR" \
    --entry-point=goal_morning_feedback \
    --trigger-http \
    --allow-unauthenticated \
    --memory=512MB \
    --timeout=540s \
    --env-vars-file="$ENV_FILE" \
    --set-secrets=CHATWORK_API_TOKEN=CHATWORK_API_TOKEN:latest,SOULKUN_CHATWORK_TOKEN=SOULKUN_CHATWORK_TOKEN:latest

echo "   ✅ goal-morning-feedback デプロイ完了"

# 4. goal_consecutive_unanswered (連続未回答チェック)
echo "📤 [4/4] goal-consecutive-unanswered をデプロイ中..."
gcloud functions deploy goal-consecutive-unanswered \
    --gen2 \
    --runtime=python311 \
    --region=asia-northeast1 \
    --source="$SCRIPT_DIR" \
    --entry-point=goal_consecutive_unanswered_check \
    --trigger-http \
    --allow-unauthenticated \
    --memory=512MB \
    --timeout=540s \
    --env-vars-file="$ENV_FILE" \
    --set-secrets=CHATWORK_API_TOKEN=CHATWORK_API_TOKEN:latest,SOULKUN_CHATWORK_TOKEN=SOULKUN_CHATWORK_TOKEN:latest

echo "   ✅ goal-consecutive-unanswered デプロイ完了"

# 環境変数ファイルを削除（機密情報を含まないがクリーンアップ）
rm -f "$ENV_FILE"

echo ""
echo "=============================================="
echo "✅ 全ての Cloud Functions デプロイ完了"
echo ""
echo "デプロイされた関数:"
echo "  - goal-daily-check (17:00 進捗確認)"
echo "  - goal-daily-reminder (18:00 未回答リマインド)"
echo "  - goal-morning-feedback (08:00 朝フィードバック)"
echo "  - goal-consecutive-unanswered (連続未回答チェック)"
echo ""
if [ "$MODE" = "test" ]; then
    echo "🧪 テストモード有効 (GOAL_TEST_MODE=true)"
    echo "   送信先: カズさんDM (room_id: $GOAL_TEST_ROOM_IDS) のみ"
    echo ""
    echo "📋 テスト実行コマンド:"
    echo "   curl -X POST https://asia-northeast1-soulkun-production.cloudfunctions.net/goal-daily-check"
else
    echo "⚠️  本番モード (GOAL_TEST_MODE=false)"
    echo "   全ユーザーに送信されます"
fi
echo "=============================================="
