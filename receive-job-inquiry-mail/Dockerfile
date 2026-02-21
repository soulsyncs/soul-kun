FROM python:3.11-slim

# 非root ユーザーを作成（セキュリティベストプラクティス）
RUN adduser --disabled-password --gecos '' appuser

WORKDIR /app

# 依存パッケージをインストール
COPY receive-job-inquiry-mail/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# 共有ライブラリ（lib/ 以下）をコピー
COPY lib/ /app/lib/

# サービス固有のコードをコピー
COPY receive-job-inquiry-mail/ /app/receive-job-inquiry-mail/

# Python パスを設定
ENV PYTHONPATH=/app:/app/receive-job-inquiry-mail
ENV PORT=8080

# Import smoke test（ビルド時にインポート失敗を検出）
RUN python3 -c "from mail_parser import parse_raw_email, format_chatwork_message; print('✅ mail_parser import OK')"

# 非root ユーザーに切り替え
USER appuser

# gunicorn で Flask アプリを起動
CMD exec gunicorn main:app --bind :$PORT --workers 1 --threads 8 --timeout 120
