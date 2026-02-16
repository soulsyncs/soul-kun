FROM python:3.11-slim
RUN adduser --disabled-password --gecos '' appuser
WORKDIR /app

COPY sync-chatwork-tasks/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY lib/ /app/lib/
COPY chatwork-webhook/lib/persona/ /app/lib/persona/
COPY sync-chatwork-tasks/ /app/sync-chatwork-tasks/
# サービスローカルのlib/を削除（ルートのlib/を使用するため）
RUN rm -rf /app/sync-chatwork-tasks/lib/

ENV PYTHONPATH=/app:/app/sync-chatwork-tasks
ENV PORT=8080

RUN python3 -c "import sys; sys.path.insert(0, '/app/sync-chatwork-tasks'); from main import app; print('OK')"

USER appuser
CMD exec gunicorn main:app --bind :$PORT --workers 1 --threads 8 --timeout 540
