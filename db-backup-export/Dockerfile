FROM python:3.11-slim

RUN adduser --disabled-password --gecos '' appuser
WORKDIR /app

COPY db-backup-export/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY db-backup-export/ /app/db-backup-export/

ENV PYTHONPATH=/app:/app/db-backup-export
ENV PORT=8080

# Import smoke test
RUN python3 -c "import sys; sys.path.insert(0, '/app/db-backup-export'); from main import app; print('OK')"

USER appuser
CMD exec gunicorn main:app --bind :$PORT --workers 1 --threads 8 --timeout 540
