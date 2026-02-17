FROM python:3.11-slim

# 非root ユーザーを作成（セキュリティベストプラクティス）
RUN adduser --disabled-password --gecos '' appuser

WORKDIR /app

# 依存パッケージをインストール
COPY chatwork-webhook/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# lib/ をルートからコピー（3コピー問題の解消）
# シンボリックリンク lib/persona → chatwork-webhook/lib/persona を実体コピーで解決
COPY lib/ /app/lib/
COPY chatwork-webhook/lib/persona/ /app/lib/persona/
# chatwork-webhook固有のモジュールをオーバーレイ
# handler_wrappers/ パッケージは root lib/brain/ には存在しないため明示的にコピー
# NOTE: chatwork-webhook/lib/brain/ に新しい固有ファイルを追加した場合、
# ここにCOPY行を追加すること（PYTHONPATHで /app/lib/ が優先されるため）
COPY chatwork-webhook/lib/brain/handler_wrappers/ /app/lib/brain/handler_wrappers/

# chatwork-webhook のアプリケーションコードをコピー
COPY chatwork-webhook/ /app/chatwork-webhook/

# Python パスを設定（lib/ と chatwork-webhook/ の両方を参照可能に）
ENV PYTHONPATH=/app:/app/chatwork-webhook
ENV PORT=8080

# Import smoke test（ビルド時にインポート失敗を検出 — 再発防止）
RUN python3 -c "from lib.brain.handler_wrappers import build_brain_handlers, _brain_handle_task_search; print('✅ handler_wrappers import OK')"

# 非root ユーザーに切り替え
USER appuser

# gunicorn で Flask アプリを起動（PYTHONPATH に /app/chatwork-webhook が含まれるため main:app で参照可能）
CMD exec gunicorn main:app --bind :$PORT --workers 1 --threads 8 --timeout 540
