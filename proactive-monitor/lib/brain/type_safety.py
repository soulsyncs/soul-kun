# lib/brain/type_safety.py
"""
型安全なJSON変換ユーティリティ

debug_info等のオブジェクトをJSON化する際のエラーを防止するために、
安全な辞書変換と検証機能を提供します。

使用例:
    from lib.brain.type_safety import safe_to_dict, validate_json_serializable

    # オブジェクトを安全に辞書化
    debug_info = safe_to_dict(some_object)

    # JSON化可能かを検証
    is_valid, error = validate_json_serializable(data)
"""

from dataclasses import asdict, is_dataclass
from datetime import datetime, date, time, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from uuid import UUID
import json


# JSON化可能なプリミティブ型
JSON_PRIMITIVES = (str, int, float, bool, type(None))


def safe_to_dict(obj: Any, *, max_depth: int = 10, _current_depth: int = 0) -> Any:
    """
    オブジェクトを安全にJSON化可能な形式に変換する。

    以下の優先順位で変換を試みる:
    1. None/str/int/float/bool → そのまま返す
    2. dict → 各値を再帰的に変換
    3. list/tuple/set → リストに変換し、各要素を再帰的に変換
    4. dataclass → asdict()で辞書化し、値を再帰的に変換
    5. to_dict()メソッドを持つ → 呼び出して結果を再帰的に変換
    6. Enum → 値を返す
    7. datetime/date/time → ISO形式の文字列
    8. UUID → 文字列
    9. Decimal → float
    10. timedelta → 秒数（float）
    11. その他 → str(obj)にフォールバック

    Args:
        obj: 変換対象のオブジェクト
        max_depth: 再帰の最大深度（無限ループ防止、デフォルト10）
        _current_depth: 現在の再帰深度（内部使用）

    Returns:
        JSON化可能な値（dict, list, str, int, float, bool, None）

    Examples:
        >>> from dataclasses import dataclass
        >>> @dataclass
        ... class Person:
        ...     name: str
        ...     age: int
        >>> safe_to_dict(Person("田中", 30))
        {'name': '田中', 'age': 30}

        >>> safe_to_dict(datetime(2024, 1, 15, 10, 30))
        '2024-01-15T10:30:00'

        >>> safe_to_dict([1, 2, {"key": "value"}])
        [1, 2, {'key': 'value'}]
    """
    # 深度制限チェック（無限ループ防止）
    if _current_depth > max_depth:
        return f"<max depth {max_depth} exceeded>"

    next_depth = _current_depth + 1

    # 1. プリミティブ型はそのまま返す
    if obj is None or isinstance(obj, JSON_PRIMITIVES):
        return obj

    # 2. dict → 各値を再帰的に変換
    if isinstance(obj, dict):
        return {
            _safe_key(k): safe_to_dict(v, max_depth=max_depth, _current_depth=next_depth)
            for k, v in obj.items()
        }

    # 3. list/tuple/set → リストに変換
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [
            safe_to_dict(item, max_depth=max_depth, _current_depth=next_depth)
            for item in obj
        ]

    # 4. dataclass → asdict()で辞書化
    if is_dataclass(obj) and not isinstance(obj, type):
        try:
            # asdict()の結果を再帰的に変換
            # （asdict()はネストされたdataclassも辞書化するが、
            #   datetime等の特殊型は変換しないため再帰処理が必要）
            return safe_to_dict(
                asdict(obj), max_depth=max_depth, _current_depth=next_depth
            )
        except Exception:
            # asdict()が失敗した場合はto_dict()を試す
            pass

    # 5. to_dict()メソッドを持つオブジェクト
    if hasattr(obj, "to_dict") and callable(getattr(obj, "to_dict")):
        try:
            result = obj.to_dict()
            return safe_to_dict(result, max_depth=max_depth, _current_depth=next_depth)
        except Exception:
            # to_dict()が失敗した場合はフォールバック
            pass

    # 6. Enum → 値を返す
    if isinstance(obj, Enum):
        return obj.value

    # 7. datetime系 → ISO形式文字列
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, time):
        return obj.isoformat()

    # 8. UUID → 文字列
    if isinstance(obj, UUID):
        return str(obj)

    # 9. Decimal → float
    if isinstance(obj, Decimal):
        return float(obj)

    # 10. timedelta → 秒数
    if isinstance(obj, timedelta):
        return obj.total_seconds()

    # 11. bytes → base64エンコード
    if isinstance(obj, bytes):
        import base64
        return base64.b64encode(obj).decode("ascii")

    # 12. その他 → str()にフォールバック
    try:
        return str(obj)
    except Exception:
        return f"<unconvertible: {type(obj).__name__}>"


def _safe_key(key: Any) -> str:
    """
    辞書のキーを安全に文字列に変換する。

    JSONでは辞書のキーは文字列でなければならないため、
    非文字列キーを文字列に変換する。
    """
    if isinstance(key, str):
        return key
    if isinstance(key, (int, float, bool)):
        return str(key)
    if isinstance(key, Enum):
        return str(key.value)
    if key is None:
        return "null"
    return str(key)


def validate_json_serializable(obj: Any) -> Tuple[bool, Optional[str]]:
    """
    オブジェクトがJSON化可能かどうかを検証する。

    Args:
        obj: 検証対象のオブジェクト

    Returns:
        Tuple[bool, Optional[str]]:
            - (True, None): JSON化可能
            - (False, error_message): JSON化不可能（エラーメッセージ付き）

    Examples:
        >>> validate_json_serializable({"name": "田中", "age": 30})
        (True, None)

        >>> validate_json_serializable({"func": lambda x: x})
        (False, 'Object of type function is not JSON serializable')
    """
    try:
        json.dumps(obj, ensure_ascii=False)
        return (True, None)
    except TypeError as e:
        return (False, type(e).__name__)
    except ValueError as e:
        return (False, type(e).__name__)
    except Exception as e:
        return (False, f"Unexpected error: {type(e).__name__}: {type(e).__name__}")


def ensure_json_serializable(obj: Any, *, max_depth: int = 10) -> Dict[str, Any]:
    """
    オブジェクトを確実にJSON化可能な辞書に変換する。

    validate_json_serializableで検証し、失敗した場合はsafe_to_dictで変換する。
    最終的に辞書形式で返す（元がdictでない場合は{"value": ...}でラップ）。

    Args:
        obj: 変換対象のオブジェクト
        max_depth: safe_to_dictの再帰最大深度

    Returns:
        JSON化可能な辞書

    Examples:
        >>> from dataclasses import dataclass
        >>> @dataclass
        ... class Info:
        ...     name: str
        >>> ensure_json_serializable(Info("test"))
        {'name': 'test'}

        >>> ensure_json_serializable("simple string")
        {'value': 'simple string'}
    """
    # まず検証
    is_valid, _ = validate_json_serializable(obj)

    if is_valid and isinstance(obj, dict):
        return obj

    # 変換が必要
    converted = safe_to_dict(obj, max_depth=max_depth)

    # 辞書でない場合はラップ
    if not isinstance(converted, dict):
        return {"value": converted}

    return converted
