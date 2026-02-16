"""
DBバックアップエクスポート - Cloud Run

毎月1日にCloud SQLからCloud Storageにエクスポートする。
10年保存用のアーカイブバックアップ。

Cloud Scheduler: 毎月1日 03:00 JST
"""

import os
from flask import Flask, jsonify
from googleapiclient.discovery import build
from google.auth import default
from datetime import datetime
import pytz
import json

app = Flask(__name__)

# 設定
PROJECT_ID = "soulkun-production"
INSTANCE_ID = "soulkun-db"
DATABASE_NAME = "soulkun_tasks"
BUCKET_NAME = "soulkun-backup-archive"


@app.route("/", methods=["POST"])
def db_backup_export():
    """
    Cloud SQLをCloud Storageにエクスポート

    Returns:
        JSON response with export status
    """
    try:
        # 日本時間で日付を取得
        jst = pytz.timezone('Asia/Tokyo')
        now = datetime.now(jst)
        export_date = now.strftime('%Y%m')

        # エクスポート先URI
        export_uri = f"gs://{BUCKET_NAME}/monthly/{export_date}_soulkun_tasks.sql.gz"

        # 認証情報を取得
        credentials, project = default()

        # Cloud SQL Admin APIクライアント
        service = build('sqladmin', 'v1beta4', credentials=credentials)

        # エクスポートリクエスト
        export_body = {
            'exportContext': {
                'fileType': 'SQL',
                'uri': export_uri,
                'databases': [DATABASE_NAME],
            }
        }

        # エクスポート実行
        operation = service.instances().export(
            project=PROJECT_ID,
            instance=INSTANCE_ID,
            body=export_body
        ).execute()

        return json.dumps({
            "success": True,
            "message": f"Export started: {export_uri}",
            "operation_name": operation.get('name'),
            "export_date": export_date,
        }), 200, {'Content-Type': 'application/json'}

    except Exception as e:
        print(f"Export failed: {e}")
        return json.dumps({
            "success": False,
            "error": str(e),
        }), 500, {'Content-Type': 'application/json'}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
