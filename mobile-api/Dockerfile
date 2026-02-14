FROM python:3.11-slim

WORKDIR /app

# 依存インストール
COPY mobile-api/requirements.txt /app/mobile-api/requirements.txt
RUN pip install --no-cache-dir -r /app/mobile-api/requirements.txt

# lib/ はルートからコピー（3コピー問題の解消）
COPY lib/ /app/lib/
COPY chatwork-webhook/handlers/ /app/chatwork-webhook/handlers/
COPY chatwork-webhook/lib/ /app/chatwork-webhook/lib/
COPY mobile-api/ /app/mobile-api/

ENV PYTHONPATH=/app:/app/chatwork-webhook:/app/mobile-api
ENV PORT=8081

CMD exec uvicorn mobile-api.main:app --host 0.0.0.0 --port $PORT --workers 2
