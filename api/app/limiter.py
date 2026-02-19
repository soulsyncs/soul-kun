"""
Rate Limiter Singleton

slowapi Limiter を一箇所で定義し、main.py と各ルートファイルが import して使う。
循環インポート防止のため、このモジュールはアプリ依存なし。

- default_limits: 全エンドポイントに 100回/分（SlowAPIMiddleware 経由）
- 認証エンドポイントは auth_routes.py で @limiter.limit("10/minute") を追加（認証系は 10/min でより厳しく制限）
- ヘルスチェックは @limiter.exempt で除外

## GCP Cloud Run 対応

GCP の Google Front End (GFE) は実クライアント IP を X-Forwarded-For ヘッダーの末尾に追記する。
slowapi 標準の get_remote_address は request.client.host（= LB IP）を返すため使用不可。
カスタム key_func で X-Forwarded-For の末尾エントリを取得することで正しく IP 判定する。
"""
from fastapi import Request
from slowapi import Limiter


def get_gcp_client_ip(request: Request) -> str:
    """
    GCP Cloud Run 対応の IP 抽出。
    GFE が X-Forwarded-For の末尾に実クライアント IP を追記するため、
    末尾のエントリを使用する。ローカル開発時は request.client.host にフォールバック。
    """
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    if forwarded_for:
        return forwarded_for.split(",")[-1].strip()
    return request.client.host or "127.0.0.1"


limiter = Limiter(key_func=get_gcp_client_ip, default_limits=["100/minute"])
