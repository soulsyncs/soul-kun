FROM python:3.11-slim
RUN adduser --disabled-password --gecos '' appuser
WORKDIR /app

COPY cleanup-old-data/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY lib/ /app/lib/
COPY chatwork-webhook/lib/persona/ /app/lib/persona/
COPY cleanup-old-data/ /app/cleanup-old-data/
# サービスローカルのlib/を削除（ルートのlib/を使用するため）
RUN rm -rf /app/cleanup-old-data/lib/

ENV PYTHONPATH=/app:/app/cleanup-old-data
ENV PORT=8080

RUN python3 -c "import sys; sys.path.insert(0, '/app/cleanup-old-data'); from main import app; print('OK')"

USER appuser
CMD exec gunicorn main:app --bind :$PORT --workers 1 --threads 8 --timeout 540
