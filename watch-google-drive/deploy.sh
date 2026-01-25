#!/bin/bash
# =====================================================
# watch-google-drive デプロイスクリプト
# ★★★ v10.25.0: google-genai SDK対応 ★★★
# =====================================================
#
# 使い方:
#   ./deploy.sh
#
# このスクリプトは以下を行います:
# 1. soul-kun/lib/ から必要なファイルをコピー
# 2. gcloud functions deploy を実行
# =====================================================

set -e  # エラー時に停止

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LIB_SRC="$SCRIPT_DIR/../lib"
LIB_DST="$SCRIPT_DIR/lib"

echo "=============================================="
echo "watch-google-drive デプロイ開始"
echo "=============================================="

# 1. lib/ ディレクトリを更新
echo ""
echo "📁 共通ライブラリをコピー中..."
mkdir -p "$LIB_DST"

# 必要なファイルをコピー
# ★ v10.25.0: embedding.py は google-genai SDK に更新済み
cp "$LIB_SRC/embedding.py" "$LIB_DST/"
cp "$LIB_SRC/pinecone_client.py" "$LIB_DST/"
cp "$LIB_SRC/google_drive.py" "$LIB_DST/"
cp "$LIB_SRC/db.py" "$LIB_DST/"
cp "$LIB_SRC/config.py" "$LIB_DST/"
cp "$LIB_SRC/secrets.py" "$LIB_DST/"

echo "   ✅ embedding.py (v10.25.0 google-genai SDK)"
echo "   ✅ pinecone_client.py"
echo "   ✅ google_drive.py"
echo "   ✅ db.py"
echo "   ✅ config.py"
echo "   ✅ secrets.py"

# document_processor.py は既存のものを使用
if [ -f "$LIB_DST/document_processor.py" ]; then
    echo "   ✅ document_processor.py (existing)"
fi

# __init__.py を作成
cat > "$LIB_DST/__init__.py" << 'EOF'
"""
watch-google-drive用 lib パッケージ

★★★ v10.25.0: google-genai SDK対応 ★★★
"""

from lib.embedding import EmbeddingClient
from lib.pinecone_client import PineconeClient
from lib.google_drive import GoogleDriveClient
from lib.db import get_db_pool
from lib.config import get_settings
from lib.secrets import get_secret
from lib.document_processor import DocumentProcessor, ExtractedDocument, Chunk

__all__ = [
    'EmbeddingClient',
    'PineconeClient',
    'GoogleDriveClient',
    'get_db_pool',
    'get_settings',
    'get_secret',
    'DocumentProcessor',
    'ExtractedDocument',
    'Chunk',
]
EOF
echo "   ✅ __init__.py (created)"

# 2. デプロイ実行
echo ""
echo "🚀 Cloud Functions Gen 2 にデプロイ中..."
gcloud functions deploy watch_google_drive \
    --gen2 \
    --runtime=python311 \
    --region=asia-northeast1 \
    --source="$SCRIPT_DIR" \
    --entry-point=watch_google_drive \
    --trigger-http \
    --allow-unauthenticated \
    --memory=1024MB \
    --timeout=540s \
    --max-instances=5 \
    --env-vars-file="$SCRIPT_DIR/env-vars.yaml" \
    --set-secrets=GOOGLE_AI_API_KEY=GOOGLE_AI_API_KEY:latest,PINECONE_API_KEY=PINECONE_API_KEY:latest

echo ""
echo "=============================================="
echo "✅ デプロイ完了"
echo "=============================================="
echo ""
echo "注意: lib/ ディレクトリにコピーしたファイルはgitで追跡されません。"
echo "      デプロイ時に必ずこのスクリプトを使用してください。"
