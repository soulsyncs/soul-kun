# lib/channels/__init__.py
"""
チャネルアダプター

プラットフォーム固有のメッセージング機能を統一インターフェースに抽象化。
Phase 2-A: ChatWork依存をmain.pyから分離し、将来のSlack/LINE対応を可能にする。
"""

from lib.channels.base import (
    ChannelMessage,
    ChannelAdapter,
    SendResult,
)

__all__ = [
    "ChannelMessage",
    "ChannelAdapter",
    "SendResult",
]
