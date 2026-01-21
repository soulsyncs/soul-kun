# watch-google-drive Cloud Function Dockerfile
# .doc形式サポートのためantiwordとLibreOfficeをインストール

# Google Cloud Functions Python 3.11 base image
FROM python:3.11-slim

# 環境変数の設定
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

# 作業ディレクトリの設定
WORKDIR /app

# Pythonの依存関係をインストール
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# アプリケーションコードをコピー
COPY . .

# Cloud Functionsのエントリーポイント
# functions-frameworkがPORT環境変数で指定されたポートでリッスン
ENV PORT=8080
CMD exec functions-framework --target=watch_google_drive --port=${PORT}
