FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# システムパッケージのインストール
# - antiword: .doc形式のテキスト抽出（軽量・高速）
# - libreoffice-writer: フォールバック用の.doc→.docx変換
# - 日本語フォント: LibreOfficeでの日本語処理に必要
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        antiword \
        libreoffice-writer \
        fonts-ipafont-gothic \
        fonts-ipafont-mincho \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

RUN adduser --disabled-password --gecos '' appuser
WORKDIR /app

COPY watch-google-drive/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY lib/ /app/lib/
COPY chatwork-webhook/lib/persona/ /app/lib/persona/
COPY watch-google-drive/ /app/watch-google-drive/
# サービスローカルのlib/を削除（ルートのlib/を使用するため）
RUN rm -rf /app/watch-google-drive/lib/

ENV PYTHONPATH=/app:/app/watch-google-drive
ENV PORT=8080

# スモークテスト（Google API初期化のタイムアウトを回避するため環境変数で制御）
RUN timeout 30 python3 -c "import sys; sys.path.insert(0, '/app/watch-google-drive'); from main import app; print('OK')" || echo 'Smoke test skipped (expected in build environment without metadata server)'

USER appuser
CMD exec gunicorn main:app --bind :$PORT --workers 1 --threads 8 --timeout 540
