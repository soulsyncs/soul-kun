FROM python:3.11-slim

WORKDIR /app

# 依存パッケージをインストール
COPY chatwork-webhook/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# lib/ をルートからコピー（3コピー問題の解消）
# シンボリックリンク lib/persona → chatwork-webhook/lib/persona を実体コピーで解決
COPY lib/ /app/lib/
COPY chatwork-webhook/lib/persona/ /app/lib/persona/

# chatwork-webhook のアプリケーションコードをコピー
COPY chatwork-webhook/ /app/chatwork-webhook/

# Python パスを設定（lib/ と chatwork-webhook/ の両方を参照可能に）
ENV PYTHONPATH=/app:/app/chatwork-webhook
ENV PORT=8080

# gunicorn で Flask アプリを起動（PYTHONPATH に /app/chatwork-webhook が含まれるため main:app で参照可能）
CMD exec gunicorn main:app --bind :$PORT --workers 1 --threads 8 --timeout 540
