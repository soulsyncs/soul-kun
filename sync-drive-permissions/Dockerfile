FROM python:3.11-slim
RUN adduser --disabled-password --gecos '' appuser
WORKDIR /app

COPY sync-drive-permissions/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY lib/ /app/lib/
COPY chatwork-webhook/lib/persona/ /app/lib/persona/
COPY sync-drive-permissions/ /app/sync-drive-permissions/

ENV PYTHONPATH=/app:/app/sync-drive-permissions
ENV PORT=8080

RUN python3 -c "import sys; sys.path.insert(0, '/app/sync-drive-permissions'); from main import app; print('OK')"

USER appuser
CMD exec gunicorn main:app --bind :$PORT --workers 1 --threads 8 --timeout 540
