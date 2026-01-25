FROM python:3.11-slim

# Cache buster: 2026-01-19-v2
ARG CACHE_BUST=2026-01-19-v2

WORKDIR /app

# Install dependencies
COPY api/requirements.txt .
# Force fresh install of pinecone (not pinecone-client)
RUN echo "Cache bust: $CACHE_BUST" && \
    pip uninstall -y pinecone-client pinecone 2>/dev/null || true && \
    pip install --no-cache-dir -r requirements.txt && \
    pip show pinecone || pip show pinecone-client || echo "No pinecone package found"

# Copy shared library
COPY lib ./lib

# Copy api
COPY api ./api

# Set environment variables
# /app: lib/ へのアクセス用
# /app/api: api/app/ へのアクセス用（api/main.py から from app.xxx としてインポート）
ENV PYTHONPATH=/app:/app/api
ENV PORT=8080

# Run the application
CMD exec gunicorn api.main:app -k uvicorn.workers.UvicornWorker --bind :$PORT --workers 1 --threads 8 --timeout 0
