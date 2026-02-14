FROM python:3.11-slim

WORKDIR /app

# 依存パッケージをインストール
COPY proactive-monitor/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# lib/ をルートからコピー（3コピー問題の解消）
# シンボリックリンク lib/persona → chatwork-webhook/lib/persona を実体コピーで解決
COPY lib/ /app/lib/
COPY chatwork-webhook/lib/persona/ /app/lib/persona/

# proactive-monitor のアプリケーションコードをコピー
COPY proactive-monitor/ /app/proactive-monitor/

# Python パスを設定（lib/ と proactive-monitor/ の両方を参照可能に）
ENV PYTHONPATH=/app:/app/proactive-monitor
ENV PORT=8080

# gunicorn で Flask アプリを起動（PYTHONPATH に /app/proactive-monitor が含まれるため main:app で参照可能）
CMD exec gunicorn main:app --bind :$PORT --workers 1 --threads 8 --timeout 540
