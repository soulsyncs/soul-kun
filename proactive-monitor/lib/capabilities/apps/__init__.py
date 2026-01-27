# lib/capabilities/apps/__init__.py
"""
ソウルくんアプリケーション層パッケージ

能力層（multimodal, generation, feedback）を組み合わせた
実用的なアプリケーションを提供する。

設計書: docs/20_next_generation_capabilities.md セクション9

アプリ一覧:
- meeting_minutes: 議事録自動生成（M2 + G1統合）

Author: Claude Opus 4.5
Created: 2026-01-27
"""

__version__ = "1.0.0"
__author__ = "Claude Opus 4.5"

# サブパッケージは必要に応じてインポート
# from .meeting_minutes import MeetingMinutesGenerator
