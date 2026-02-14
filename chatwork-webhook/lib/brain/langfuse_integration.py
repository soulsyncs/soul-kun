# lib/brain/langfuse_integration.py
"""
Langfuse統合モジュール — AIの「カルテ」

ソウルくんのLLM呼び出しをLangfuseでトレースし、
「なぜその答えを出したか」を画面で見られるようにする。

【使い方】
1. 環境変数を設定:
   - LANGFUSE_SECRET_KEY: Langfuseのシークレットキー
   - LANGFUSE_PUBLIC_KEY: Langfuseのパブリックキー
   - LANGFUSE_HOST: Langfuseのホスト（省略時はクラウド版）
2. 各メソッドに @observe() デコレータを付ける
3. Langfuse画面でトレースを確認

【設計原則】
- Langfuse未設定時はno-op（何もしない）→ 本番を壊さない
- 既存のBrainObservability（observability.py）と共存
- PIIはLangfuseに送らない（CLAUDE.md 3-2 #8 / 9-4準拠）
- 遅延初期化: import時にネットワーク接続しない

【環境変数】
- LANGFUSE_SECRET_KEY: 必須（設定されていない場合は無効化）
- LANGFUSE_PUBLIC_KEY: 必須
- LANGFUSE_HOST: 任意（デフォルト: https://cloud.langfuse.com）
- LANGFUSE_ENABLED: 任意（"false"で明示的に無効化）
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Langfuseの利用可否フラグ（遅延初期化）
_langfuse_available = False
_langfuse_client: Any = None
_langfuse_init_done = False

# SDKのインポート状態（ImportError時はNone）
_observe_func: Any = None
_langfuse_context_mod: Any = None
_langfuse_class: Any = None

try:
    from langfuse.decorators import observe as _observe_func_imported
    from langfuse.decorators import langfuse_context as _langfuse_context_imported
    from langfuse import Langfuse as _Langfuse_imported

    _observe_func = _observe_func_imported
    _langfuse_context_mod = _langfuse_context_imported
    _langfuse_class = _Langfuse_imported
except ImportError:
    logger.info("Langfuse package not installed, tracing disabled")


def _ensure_initialized() -> None:
    """
    Langfuseクライアントを遅延初期化する。

    初回呼び出し時にのみ実行され、ネットワーク接続はこのタイミングで発生する。
    import時にはネットワーク接続しない。
    """
    global _langfuse_available, _langfuse_client, _langfuse_init_done

    if _langfuse_init_done:
        return
    _langfuse_init_done = True

    if _langfuse_class is None:
        return

    # 明示的に無効化されていないかチェック
    if os.getenv("LANGFUSE_ENABLED", "true").lower() == "false":
        logger.info("Langfuse explicitly disabled via LANGFUSE_ENABLED=false")
        return

    if os.getenv("LANGFUSE_SECRET_KEY") and os.getenv("LANGFUSE_PUBLIC_KEY"):
        try:
            _langfuse_client = _langfuse_class()
            _langfuse_available = True
            logger.info(
                "Langfuse initialized: host=%s",
                os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"),
            )
        except Exception as e:
            logger.warning("Failed to initialize Langfuse: %s", e)
    else:
        logger.info(
            "Langfuse keys not configured (LANGFUSE_SECRET_KEY / LANGFUSE_PUBLIC_KEY), "
            "tracing disabled"
        )


# =============================================================================
# Public API
# =============================================================================


def observe(*args: Any, **kwargs: Any) -> Any:
    """
    Langfuse @observe デコレータ（安全ラッパー）

    Langfuse SDKがインストールされている場合: 本物の @observe() を返す
    （実際のトレース送信は環境変数の有無で初回呼び出し時に判定）
    Langfuse SDKが未インストールの場合: 何もしないデコレータを返す

    Usage:
        @observe(name="process_message")
        async def process_message(self, ...):
            ...

        @observe(as_type="generation", name="llm_call")
        async def process(self, ...):
            ...
    """
    # SDKがインストールされていればデコレータは常に適用
    # （キー未設定時はLangfuse側で自動的にno-opになる）
    if _observe_func is not None:
        return _observe_func(*args, **kwargs)

    # SDK未インストール: No-op デコレータ
    def _identity_decorator(func: Any) -> Any:
        return func

    # @observe のように引数なしで呼ばれた場合
    if args and callable(args[0]):
        return args[0]

    # @observe(name="...") のように引数ありで呼ばれた場合
    return _identity_decorator


def update_current_observation(**kwargs: Any) -> None:
    """
    現在のLangfuse観測を更新（安全ラッパー）

    Langfuseが利用不可の場合は何もしない。
    PIIを含むデータは絶対に渡さないこと（CLAUDE.md 3-2 #8）。
    """
    _ensure_initialized()
    if not _langfuse_available or _langfuse_context_mod is None:
        return

    try:
        _langfuse_context_mod.update_current_observation(**kwargs)
    except Exception as e:
        # トレース失敗で本体処理を止めない
        logger.debug("Failed to update Langfuse observation: %s", e)


def update_current_trace(**kwargs: Any) -> None:
    """
    現在のLangfuseトレースを更新（安全ラッパー）

    PIIを含むデータは絶対に渡さないこと（CLAUDE.md 3-2 #8）。
    メッセージはmask_pii()でマスキング済みの値のみ渡すこと。
    """
    _ensure_initialized()
    if not _langfuse_available or _langfuse_context_mod is None:
        return

    try:
        _langfuse_context_mod.update_current_trace(**kwargs)
    except Exception as e:
        logger.debug("Failed to update Langfuse trace: %s", e)


def get_langfuse() -> Optional[Any]:
    """Langfuseクライアントインスタンスを取得（未設定時はNone）"""
    _ensure_initialized()
    return _langfuse_client


def is_langfuse_enabled() -> bool:
    """Langfuseが有効かどうかを返す"""
    _ensure_initialized()
    return _langfuse_available


def flush() -> None:
    """
    保留中のLangfuseイベントを送信。

    Cloud Functionsではリクエスト終了前に必ず呼ぶこと。
    バックグラウンドスレッドのバッファがフラッシュされる。
    """
    if not _langfuse_init_done:
        return
    if _langfuse_available and _langfuse_client:
        try:
            _langfuse_client.flush()
        except Exception as e:
            logger.debug("Failed to flush Langfuse events: %s", e)


def shutdown() -> None:
    """Langfuseクライアントをシャットダウン"""
    if not _langfuse_init_done:
        return
    if _langfuse_available and _langfuse_client:
        try:
            _langfuse_client.shutdown()
        except Exception as e:
            logger.debug("Failed to shutdown Langfuse: %s", e)
