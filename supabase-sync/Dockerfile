FROM python:3.11-slim

RUN adduser --disabled-password --gecos '' appuser
WORKDIR /app

COPY supabase-sync/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY lib/ /app/lib/
COPY chatwork-webhook/lib/persona/ /app/lib/persona/
COPY supabase-sync/ /app/supabase-sync/

ENV PYTHONPATH=/app:/app/supabase-sync
ENV PORT=8080

RUN python3 -c "import sys; sys.path.insert(0, '/app/supabase-sync'); from main import app; print('OK')"

USER appuser
CMD exec gunicorn main:app --bind :$PORT --workers 1 --threads 8 --timeout 540
