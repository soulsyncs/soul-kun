FROM python:3.11-slim
RUN adduser --disabled-password --gecos '' appuser
WORKDIR /app

COPY pattern-detection/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY lib/ /app/lib/
COPY chatwork-webhook/lib/persona/ /app/lib/persona/
COPY pattern-detection/ /app/pattern-detection/

ENV PYTHONPATH=/app:/app/pattern-detection
ENV PORT=8080

RUN python3 -c "import sys; sys.path.insert(0, '/app/pattern-detection'); from main import app; print('OK')"

USER appuser
CMD exec gunicorn main:app --bind :$PORT --workers 1 --threads 8 --timeout 540
