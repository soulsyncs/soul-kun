FROM python:3.11-slim

WORKDIR /app

# 依存インストール
COPY mcp-server/requirements.txt /app/mcp-server/requirements.txt
RUN pip install --no-cache-dir -r /app/mcp-server/requirements.txt

# lib/ はルートからコピー（3コピー問題の解消）
COPY lib/ /app/lib/
COPY chatwork-webhook/handlers/ /app/chatwork-webhook/handlers/
COPY chatwork-webhook/lib/ /app/chatwork-webhook/lib/
COPY mcp-server/ /app/mcp-server/

ENV PYTHONPATH=/app:/app/chatwork-webhook:/app/mcp-server
ENV PORT=8080

# SSEモードで起動（HTTP経由のMCPクライアント用）
CMD exec python3 /app/mcp-server/server.py --transport sse --port $PORT
