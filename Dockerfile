FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY api/requirements.txt .
# Force fresh install of pinecone (not pinecone-client)
RUN pip uninstall -y pinecone-client pinecone 2>/dev/null || true && \
    pip install --no-cache-dir -r requirements.txt

# Copy shared library
COPY lib ./lib

# Copy api
COPY api ./api

# Set environment variables
ENV PYTHONPATH=/app
ENV PORT=8080

# Run the application
CMD exec gunicorn api.main:app -k uvicorn.workers.UvicornWorker --bind :$PORT --workers 1 --threads 8 --timeout 0
