#!/bin/bash
# =============================================================
# test_webhook.sh - ChatWork Webhookテストスクリプト
#
# 署名付きのテストリクエストをchatwork-webhookに送信し、
# 診断ログを確認する。
#
# 使い方:
#   bash scripts/test_webhook.sh              # デフォルトのテストメッセージ
#   bash scripts/test_webhook.sh "こんにちは"  # カスタムメッセージ
#   bash scripts/test_webhook.sh --logs-only   # ログ確認のみ
# =============================================================

set -euo pipefail

# 設定
REGION="asia-northeast1"
PROJECT="soulkun-production"
SERVICE_URL="https://chatwork-webhook-898513057014.${REGION}.run.app"
TEST_SENDER_ID="99999999"  # テスト用の送信者ID（存在しないアカウント）
TEST_ROOM_ID="000000000"   # テスト用のルームID（存在しないルーム → 返信失敗するが診断ログは出る）
TEST_MESSAGE="${1:-診断ログ確認テスト}"

# ログ確認のみモード
if [[ "${1:-}" == "--logs-only" ]]; then
    echo "📋 最新のchatwork-webhookログ（DIAGフィルタ）:"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    gcloud run logs read chatwork-webhook \
        --region="${REGION}" \
        --limit=50 2>/dev/null \
        | grep -E 'DIAG|LearningLoop|db_data|timed out' \
        | head -30
    exit 0
fi

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🧪 ChatWork Webhook テスト"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  URL: ${SERVICE_URL}"
echo "  メッセージ: ${TEST_MESSAGE}"
echo "  送信者ID: ${TEST_SENDER_ID} (テスト)"
echo "  ルームID: ${TEST_ROOM_ID} (テスト)"
echo ""

# Step 1: Secret ManagerからWebhookトークンを取得
echo "🔑 Webhookトークンを取得中..."
WEBHOOK_TOKEN=$(gcloud secrets versions access latest --secret="CHATWORK_WEBHOOK_TOKEN" 2>/dev/null)
if [[ -z "$WEBHOOK_TOKEN" ]]; then
    echo "❌ CHATWORK_WEBHOOK_TOKEN の取得に失敗しました"
    exit 1
fi
echo "✅ トークン取得成功"

# Step 2+3: ペイロード作成 + HMAC署名（Python で安全に生成）
echo "🔐 ペイロード + 署名を生成中..."
python3 - "${WEBHOOK_TOKEN}" "${TEST_ROOM_ID}" "${TEST_SENDER_ID}" "${TEST_MESSAGE}" <<'PYEOF'
import json, base64, hmac, hashlib, time, sys

token = base64.b64decode(sys.argv[1])
room_id = int(sys.argv[2])
sender_id = int(sys.argv[3])
message = sys.argv[4]
ts = int(time.time())
payload = json.dumps({
    'webhook_setting_id': 'test-diagnostic',
    'webhook_event_type': 'mention_to_me',
    'webhook_event_time': ts,
    'webhook_event': {
        'message_id': f'test-{ts}',
        'room_id': room_id,
        'from_account_id': sender_id,
        'body': message,
        'send_time': ts,
        'update_time': 0,
    },
}, ensure_ascii=False)
body = payload.encode('utf-8')
digest = hmac.new(token, body, hashlib.sha256).digest()
sig = base64.b64encode(digest).decode()
with open('/tmp/webhook_test_payload.json', 'w') as f:
    f.write(payload)
with open('/tmp/webhook_test_sig.txt', 'w') as f:
    f.write(sig)
PYEOF
PAYLOAD=$(cat /tmp/webhook_test_payload.json)
SIGNATURE=$(cat /tmp/webhook_test_sig.txt)
echo "✅ 署名生成完了"

# Step 4: リクエスト送信
echo ""
echo "📤 テストリクエスト送信中..."
HTTP_CODE=$(curl -s -o /tmp/webhook_test_response.json -w "%{http_code}" \
    -X POST "${SERVICE_URL}" \
    -H "Content-Type: application/json" \
    -H "X-ChatWorkWebhookSignature: ${SIGNATURE}" \
    -d "${PAYLOAD}")

echo "  HTTP Status: ${HTTP_CODE}"
echo "  Response: $(cat /tmp/webhook_test_response.json 2>/dev/null | head -c 200)"
echo ""

# Step 5: ログ確認（数秒待ち）
echo "⏳ 5秒待ってからログを確認..."
sleep 5

echo ""
echo "📋 診断ログ（最新）:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
gcloud functions logs read chatwork-webhook \
    --region="${REGION}" \
    --limit=50 \
    --format='table(time_utc,severity,log)' 2>/dev/null \
    | grep -E 'DIAG|LearningLoop|db_data|timed out|テスト' \
    | head -30

echo ""
echo "✅ テスト完了"
