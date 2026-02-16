FROM python:3.11-slim

# 非root ユーザーを作成（セキュリティベストプラクティス）
RUN adduser --disabled-password --gecos '' appuser

WORKDIR /app

# 依存パッケージをインストール
COPY check-reply-messages/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# lib/ をルートからコピー（3コピー問題の解消）
COPY lib/ /app/lib/
COPY chatwork-webhook/lib/persona/ /app/lib/persona/

# check-reply-messages のアプリケーションコードをコピー
COPY check-reply-messages/ /app/check-reply-messages/

# Python パスを設定（lib/ と check-reply-messages/ の両方を参照可能に）
ENV PYTHONPATH=/app:/app/check-reply-messages
ENV PORT=8080

# Import smoke test（ビルド時にインポート失敗を検出）
RUN python3 -c "import sys; sys.path.insert(0, '/app/check-reply-messages'); from main import app; print('OK')"

# 非root ユーザーに切り替え
USER appuser

# gunicorn で Flask アプリを起動
CMD exec gunicorn main:app --bind :$PORT --workers 1 --threads 8 --timeout 540
