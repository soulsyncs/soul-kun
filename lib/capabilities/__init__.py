# lib/capabilities/__init__.py
"""
ソウルくん能力層パッケージ

脳（lib/brain/）に「手足」を追加する能力層。
各能力は脳の指示に従って動作する。

設計書: docs/20_next_generation_capabilities.md

能力一覧:
- multimodal: 入力能力（Phase M）- 画像/PDF/URL読み込み
- generation: 出力能力（Phase G）- 文書/画像/動画生成（予定）
- autonomous: 行動能力（Phase AA）- 自律エージェント（予定）
- feedback: 分析能力（Phase F）- ファクト分析・レポート（予定）

Author: Claude Opus 4.5
Created: 2026-01-27
"""

__version__ = "1.0.0"
__author__ = "Claude Opus 4.5"

# サブパッケージは必要に応じてインポート
# from .multimodal import ...
