# lib/brain/core/__init__.py
"""
ソウルくんの脳 - コアパッケージ

このパッケージには、脳の中央処理装置（SoulkunBrain）を定義します。
全てのユーザー入力は、このクラスのprocess_message()メソッドを通じて処理されます。

設計書: docs/13_brain_architecture.md

【7つの鉄則】
1. 全ての入力は脳を通る（バイパスルート禁止）
2. 脳は全ての記憶にアクセスできる
3. 脳が判断し、機能は実行するだけ
4. 機能拡張しても脳の構造は変わらない
5. 確認は脳の責務
6. 状態管理は脳が統一管理
7. 速度より正確性を優先

後方互換性:
    `from lib.brain.core import SoulkunBrain` は引き続き動作します。
    `from lib.brain.core import create_brain` も引き続き動作します。
    `from lib.brain.core import _validate_llm_result_type` 等も引き続き動作します。
"""

# メインクラス
from lib.brain.core.brain_class import SoulkunBrain

# ファクトリー関数
from lib.brain.core.utilities import create_brain

# 境界型検証ヘルパー（外部から使用される）
from lib.brain.core.validators import (
    _validate_llm_result_type,
    _extract_confidence_value,
    _safe_confidence_to_dict,
)

__all__ = [
    "SoulkunBrain",
    "create_brain",
    "_validate_llm_result_type",
    "_extract_confidence_value",
    "_safe_confidence_to_dict",
]
