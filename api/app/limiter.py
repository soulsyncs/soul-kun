"""
Rate Limiter Singleton

slowapi Limiter を一箇所で定義し、main.py と各ルートファイルが import して使う。
循環インポート防止のため、このモジュールはアプリ依存なし。

- default_limits: 全エンドポイントに 100回/分（SlowAPIMiddleware 経由）
- 認証エンドポイントは auth_routes.py で @limiter.limit("10/minute") で上書き
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])
