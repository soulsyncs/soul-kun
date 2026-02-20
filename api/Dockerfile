FROM python:3.11-slim

# 非root ユーザーを作成（セキュリティベストプラクティス）
RUN adduser --disabled-password --gecos '' appuser

WORKDIR /app

# 依存パッケージをインストール
COPY api/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# ルートlib/ をコピー（api/main.py が from lib.config 等を参照するため）
COPY lib/ /app/lib/

# api/ アプリケーションコードをコピー
COPY api/ /app/

# Python パスを設定（lib/ と app/ の両方を参照可能に）
ENV PYTHONPATH=/app
ENV PORT=8080

# Import smoke test（ビルド時にインポート失敗を検出）
RUN python3 -c "from lib.config import get_settings; print('✅ lib.config import OK')"

# 非root ユーザーに切り替え
USER appuser

# gunicorn で FastAPI アプリを起動
CMD exec gunicorn main:app -k uvicorn.workers.UvicornWorker --bind :$PORT --workers 2 --timeout 540
