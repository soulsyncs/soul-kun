"""
日報・週報自動生成 Cloud Function

Phase 2C-2: B1サマリーとタスク完了履歴から日報・週報を自動生成

エンドポイント:
- POST /daily-report: 日報生成
- POST /weekly-report: 週報生成
"""

import functions_framework
from flask import Request, jsonify
import json

from lib.report_generator import (
    run_daily_report_generation,
    run_weekly_report_generation,
)


@functions_framework.http
def report_generator(request: Request):
    """
    レポート生成 Cloud Function エントリポイント

    リクエストパス:
    - /daily-report: 日報生成
    - /weekly-report: 週報生成

    リクエストボディ:
    - dry_run: bool (デフォルト: false)
    """
    print(f"📋 Report Generator called: path={request.path}, method={request.method}")

    # CORSヘッダー
    headers = {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'POST, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type',
    }

    # OPTIONSリクエスト（CORS preflight）
    if request.method == 'OPTIONS':
        return ('', 204, headers)

    # POSTのみ許可
    if request.method != 'POST':
        return (jsonify({"error": "Method not allowed"}), 405, headers)

    # リクエストボディを解析
    try:
        request_json = request.get_json(silent=True) or {}
    except Exception:
        request_json = {}

    dry_run = request_json.get('dry_run', False)

    # パスに基づいて処理を分岐
    path = request.path.rstrip('/')

    try:
        if path == '/daily-report' or path.endswith('/daily-report'):
            print(f"📋 日報生成リクエスト: dry_run={dry_run}")
            result = run_daily_report_generation(dry_run=dry_run)
            return (jsonify({
                "success": True,
                "report_type": "daily",
                "result": result
            }), 200, headers)

        elif path == '/weekly-report' or path.endswith('/weekly-report'):
            print(f"📊 週報生成リクエスト: dry_run={dry_run}")
            result = run_weekly_report_generation(dry_run=dry_run)
            return (jsonify({
                "success": True,
                "report_type": "weekly",
                "result": result
            }), 200, headers)

        else:
            # ルートパスの場合はヘルプを返す
            return (jsonify({
                "message": "Report Generator API",
                "endpoints": {
                    "/daily-report": "日報生成（POST）",
                    "/weekly-report": "週報生成（POST）"
                },
                "parameters": {
                    "dry_run": "true の場合、送信せずにログのみ（デフォルト: false）"
                }
            }), 200, headers)

    except Exception as e:
        print(f"❌ レポート生成エラー: {e}")
        import traceback
        traceback.print_exc()
        return (jsonify({
            "success": False,
            "error": str(e)
        }), 500, headers)


# ============================================================
# ローカルテスト用
# ============================================================

if __name__ == "__main__":
    """ローカルテスト用"""
    from flask import Flask
    app = Flask(__name__)

    @app.route('/', defaults={'path': ''}, methods=['GET', 'POST', 'OPTIONS'])
    @app.route('/<path:path>', methods=['GET', 'POST', 'OPTIONS'])
    def handle_request(path):
        from flask import request
        return report_generator(request)

    print("🚀 Report Generator ローカルサーバー起動: http://localhost:8081")
    app.run(host='0.0.0.0', port=8081, debug=True)
