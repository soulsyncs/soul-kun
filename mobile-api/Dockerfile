FROM python:3.11-slim

WORKDIR /app

# 非rootユーザー作成（defense-in-depth）
RUN useradd -m -r appuser

# 依存インストール
COPY mobile-api/requirements.txt /app/mobile-api/requirements.txt
RUN pip install --no-cache-dir -r /app/mobile-api/requirements.txt

# lib/ はルートからコピー（3コピー問題の解消）
COPY lib/ /app/lib/
COPY chatwork-webhook/handlers/ /app/chatwork-webhook/handlers/
COPY chatwork-webhook/lib/ /app/chatwork-webhook/lib/
COPY mobile-api/ /app/mobile-api/

RUN chown -R appuser:appuser /app
USER appuser

ENV PYTHONPATH=/app:/app/chatwork-webhook:/app/mobile-api
ENV PORT=8081

# mobile-api はPYTHONPATH上にあるので main:app で解決可能
CMD exec uvicorn main:app --host 0.0.0.0 --port $PORT --workers 2
