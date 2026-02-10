# tests/test_type_safety.py
"""
lib/brain/type_safety.py のユニットテスト

型安全なJSON変換ユーティリティの全関数・全分岐をテスト。
対象: safe_to_dict, _safe_key, validate_json_serializable, ensure_json_serializable
"""

import json
import pytest
from dataclasses import dataclass, field
from datetime import datetime, date, time, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

from lib.brain.type_safety import (
    safe_to_dict,
    _safe_key,
    validate_json_serializable,
    ensure_json_serializable,
    JSON_PRIMITIVES,
)


# =============================================================================
# テスト用データクラス・Enum
# =============================================================================


@dataclass
class SimpleDataclass:
    name: str
    age: int


@dataclass
class NestedDataclass:
    person: SimpleDataclass
    created_at: datetime


@dataclass
class DataclassWithToDict:
    """asdict()が失敗するケースをシミュレートするためのdataclass"""
    value: str

    def to_dict(self):
        return {"custom_value": self.value}


class Color(Enum):
    RED = "red"
    GREEN = "green"
    BLUE = 3


class Priority(Enum):
    HIGH = 1
    MEDIUM = 2
    LOW = 3


class ObjectWithToDict:
    """to_dict()メソッドを持つ通常オブジェクト"""
    def __init__(self, data):
        self.data = data

    def to_dict(self):
        return {"data": self.data}


class ObjectWithFailingToDict:
    """to_dict()が例外を投げるオブジェクト"""
    def to_dict(self):
        raise RuntimeError("to_dict failed")


class UnconvertibleObject:
    """str()も失敗するオブジェクト"""
    def __str__(self):
        raise RuntimeError("Cannot convert to string")


# =============================================================================
# safe_to_dict: プリミティブ型テスト
# =============================================================================


class TestSafeToDictPrimitives:
    """safe_to_dict: プリミティブ型のテスト"""

    def test_none(self):
        assert safe_to_dict(None) is None

    def test_string(self):
        assert safe_to_dict("hello") == "hello"

    def test_empty_string(self):
        assert safe_to_dict("") == ""

    def test_integer(self):
        assert safe_to_dict(42) == 42

    def test_zero(self):
        assert safe_to_dict(0) == 0

    def test_float(self):
        assert safe_to_dict(3.14) == 3.14

    def test_bool_true(self):
        assert safe_to_dict(True) is True

    def test_bool_false(self):
        assert safe_to_dict(False) is False

    def test_japanese_string(self):
        assert safe_to_dict("田中太郎") == "田中太郎"


# =============================================================================
# safe_to_dict: dict テスト
# =============================================================================


class TestSafeToDictDict:
    """safe_to_dict: 辞書のテスト"""

    def test_simple_dict(self):
        result = safe_to_dict({"key": "value"})
        assert result == {"key": "value"}

    def test_nested_dict(self):
        data = {"a": {"b": {"c": 1}}}
        result = safe_to_dict(data)
        assert result == {"a": {"b": {"c": 1}}}

    def test_dict_with_datetime_value(self):
        dt = datetime(2024, 1, 15, 10, 30)
        result = safe_to_dict({"created": dt})
        assert result == {"created": "2024-01-15T10:30:00"}

    def test_dict_with_non_string_keys(self):
        # Note: In Python, True == 1, so {1: "one", True: "yes"} -> {1: "yes"}
        # Keys are deduplicated before safe_to_dict sees them.
        data = {2: "two", 2.5: "two_point_five", None: "null_val"}
        result = safe_to_dict(data)
        assert result["2"] == "two"
        assert result["2.5"] == "two_point_five"
        assert result["null"] == "null_val"

    def test_dict_with_bool_key(self):
        data = {True: "yes", False: "no"}
        result = safe_to_dict(data)
        assert result["True"] == "yes"
        assert result["False"] == "no"

    def test_empty_dict(self):
        assert safe_to_dict({}) == {}


# =============================================================================
# safe_to_dict: list/tuple/set/frozenset テスト
# =============================================================================


class TestSafeToDictSequences:
    """safe_to_dict: シーケンス型のテスト"""

    def test_list(self):
        result = safe_to_dict([1, 2, 3])
        assert result == [1, 2, 3]

    def test_tuple(self):
        result = safe_to_dict((1, "a", True))
        assert result == [1, "a", True]

    def test_set(self):
        result = safe_to_dict({1})
        assert result == [1]

    def test_frozenset(self):
        result = safe_to_dict(frozenset([42]))
        assert result == [42]

    def test_list_with_nested_objects(self):
        data = [datetime(2024, 1, 1), Color.RED, 42]
        result = safe_to_dict(data)
        assert result == ["2024-01-01T00:00:00", "red", 42]

    def test_empty_list(self):
        assert safe_to_dict([]) == []


# =============================================================================
# safe_to_dict: max_depth テスト (line 73)
# =============================================================================


class TestSafeToDictMaxDepth:
    """safe_to_dict: 深度制限のテスト (line 73)"""

    def test_max_depth_exceeded(self):
        """深度制限を超えた場合にメッセージが返る (line 73)"""
        result = safe_to_dict({"a": "b"}, max_depth=0, _current_depth=1)
        assert result == "<max depth 0 exceeded>"

    def test_max_depth_exact_boundary(self):
        """深度がちょうどmax_depthの場合は変換される"""
        result = safe_to_dict("hello", max_depth=5, _current_depth=5)
        assert result == "hello"

    def test_max_depth_exceeded_by_one(self):
        """深度がmax_depth+1の場合にメッセージが返る"""
        result = safe_to_dict({"a": "b"}, max_depth=5, _current_depth=6)
        assert result == "<max depth 5 exceeded>"

    def test_deeply_nested_structure_within_limit(self):
        """デフォルト深度10以内のネスト構造は正常変換"""
        data = {"l1": {"l2": {"l3": "value"}}}
        result = safe_to_dict(data)
        assert result == {"l1": {"l2": {"l3": "value"}}}

    def test_custom_max_depth(self):
        """カスタムmax_depthが正常に動作"""
        # depth 0: outer dict {"a": ...} -> recurse value with depth 1
        # depth 1: inner dict {"b": "c"} -> recurse value "c" with depth 2
        # depth 2: 2 > max_depth(1) -> "<max depth 1 exceeded>"
        data = {"a": {"b": "c"}}
        result = safe_to_dict(data, max_depth=1)
        assert result == {"a": {"b": "<max depth 1 exceeded>"}}


# =============================================================================
# safe_to_dict: dataclass テスト (lines 104-106)
# =============================================================================


class TestSafeToDictDataclass:
    """safe_to_dict: dataclassのテスト"""

    def test_simple_dataclass(self):
        obj = SimpleDataclass(name="田中", age=30)
        result = safe_to_dict(obj)
        assert result == {"name": "田中", "age": 30}

    def test_nested_dataclass(self):
        person = SimpleDataclass(name="山田", age=25)
        obj = NestedDataclass(person=person, created_at=datetime(2024, 6, 1, 12, 0))
        result = safe_to_dict(obj)
        assert result == {
            "person": {"name": "山田", "age": 25},
            "created_at": "2024-06-01T12:00:00",
        }

    def test_dataclass_asdict_fails_falls_through(self):
        """asdict()が失敗するdataclassでto_dict()にフォールバック (lines 104-106)"""
        # asdict()を失敗させるために、パッチを当てる
        obj = DataclassWithToDict(value="test")
        with patch("lib.brain.type_safety.asdict", side_effect=Exception("asdict failed")):
            result = safe_to_dict(obj)
        # to_dict()で変換されるはず
        assert result == {"custom_value": "test"}

    def test_dataclass_type_not_instance(self):
        """dataclassの型自体（インスタンスでなくクラス）はdataclass変換されない"""
        result = safe_to_dict(SimpleDataclass)
        # クラスオブジェクトはstr()にフォールバック
        assert "SimpleDataclass" in result


# =============================================================================
# safe_to_dict: to_dict()メソッド テスト (lines 110-115)
# =============================================================================


class TestSafeToDictToDict:
    """safe_to_dict: to_dict()メソッドのテスト (lines 110-115)"""

    def test_object_with_to_dict(self):
        """to_dict()メソッドを持つオブジェクトが正常に変換される (lines 110-112)"""
        obj = ObjectWithToDict(data="test_data")
        result = safe_to_dict(obj)
        assert result == {"data": "test_data"}

    def test_to_dict_with_nested_objects(self):
        """to_dict()の返り値にネストされたオブジェクトがある場合"""
        obj = ObjectWithToDict(data=datetime(2024, 3, 15))
        result = safe_to_dict(obj)
        assert result == {"data": "2024-03-15T00:00:00"}

    def test_to_dict_raises_exception(self):
        """to_dict()が例外を投げた場合はフォールバック (lines 113-115)"""
        obj = ObjectWithFailingToDict()
        result = safe_to_dict(obj)
        # str()にフォールバックされるはず
        assert isinstance(result, str)

    def test_non_callable_to_dict_attribute(self):
        """to_dict属性が呼び出し可能でない場合はスキップ"""
        obj = MagicMock()
        obj.to_dict = "not_callable"
        # callable check fails, so it falls through
        result = safe_to_dict(obj)
        assert isinstance(result, str)


# =============================================================================
# safe_to_dict: Enum テスト (line 119)
# =============================================================================


class TestSafeToDictEnum:
    """safe_to_dict: Enumのテスト (line 119)"""

    def test_string_enum(self):
        assert safe_to_dict(Color.RED) == "red"

    def test_int_enum(self):
        assert safe_to_dict(Color.BLUE) == 3

    def test_priority_enum(self):
        assert safe_to_dict(Priority.HIGH) == 1


# =============================================================================
# safe_to_dict: datetime/date/time テスト (lines 125, 127)
# =============================================================================


class TestSafeToDictDatetime:
    """safe_to_dict: datetime系のテスト (lines 122-127)"""

    def test_datetime(self):
        dt = datetime(2024, 1, 15, 10, 30, 45)
        assert safe_to_dict(dt) == "2024-01-15T10:30:45"

    def test_date_only(self):
        """date型の変換 (line 125)"""
        d = date(2024, 6, 15)
        assert safe_to_dict(d) == "2024-06-15"

    def test_time_only(self):
        """time型の変換 (line 127)"""
        t = time(14, 30, 0)
        assert safe_to_dict(t) == "14:30:00"

    def test_time_with_microseconds(self):
        t = time(10, 20, 30, 456789)
        result = safe_to_dict(t)
        assert "10:20:30" in result


# =============================================================================
# safe_to_dict: UUID テスト
# =============================================================================


class TestSafeToDictUUID:
    """safe_to_dict: UUIDのテスト"""

    def test_uuid(self):
        uid = UUID("12345678-1234-5678-1234-567812345678")
        result = safe_to_dict(uid)
        assert result == "12345678-1234-5678-1234-567812345678"

    def test_uuid4(self):
        uid = uuid4()
        result = safe_to_dict(uid)
        assert isinstance(result, str)
        # UUIDの文字列形式を検証
        assert len(result) == 36


# =============================================================================
# safe_to_dict: Decimal テスト (lines 134-135)
# =============================================================================


class TestSafeToDictDecimal:
    """safe_to_dict: Decimalのテスト (lines 134-135)"""

    def test_decimal_to_float(self):
        """Decimal型がfloatに変換される (lines 134-135)"""
        result = safe_to_dict(Decimal("3.14"))
        assert result == 3.14
        assert isinstance(result, float)

    def test_decimal_integer_value(self):
        result = safe_to_dict(Decimal("100"))
        assert result == 100.0

    def test_decimal_negative(self):
        result = safe_to_dict(Decimal("-42.5"))
        assert result == -42.5


# =============================================================================
# safe_to_dict: timedelta テスト (lines 138-139)
# =============================================================================


class TestSafeToDictTimedelta:
    """safe_to_dict: timedeltaのテスト (lines 138-139)"""

    def test_timedelta_to_seconds(self):
        """timedelta型が秒数に変換される (lines 138-139)"""
        td = timedelta(hours=1, minutes=30)
        result = safe_to_dict(td)
        assert result == 5400.0

    def test_timedelta_days(self):
        td = timedelta(days=2)
        result = safe_to_dict(td)
        assert result == 172800.0

    def test_timedelta_zero(self):
        td = timedelta(0)
        result = safe_to_dict(td)
        assert result == 0.0


# =============================================================================
# safe_to_dict: bytes テスト (lines 142-144)
# =============================================================================


class TestSafeToDictBytes:
    """safe_to_dict: bytesのテスト (lines 142-144)"""

    def test_bytes_to_base64(self):
        """bytes型がbase64エンコードされる (lines 142-144)"""
        import base64
        data = b"hello world"
        result = safe_to_dict(data)
        expected = base64.b64encode(data).decode("ascii")
        assert result == expected

    def test_empty_bytes(self):
        result = safe_to_dict(b"")
        assert result == ""


# =============================================================================
# safe_to_dict: フォールバック テスト (lines 147-150)
# =============================================================================


class TestSafeToDictFallback:
    """safe_to_dict: フォールバックのテスト (lines 147-150)"""

    def test_custom_object_str_fallback(self):
        """通常のオブジェクトはstr()にフォールバック (line 148)"""

        class MyObject:
            def __str__(self):
                return "MyObject(custom)"

        result = safe_to_dict(MyObject())
        assert result == "MyObject(custom)"

    def test_unconvertible_object(self):
        """str()も失敗するオブジェクトのフォールバック (line 150)"""
        obj = UnconvertibleObject()
        result = safe_to_dict(obj)
        assert result == "<unconvertible: UnconvertibleObject>"

    def test_complex_number_fallback(self):
        """complex型はstr()にフォールバック"""
        result = safe_to_dict(complex(1, 2))
        assert result == "(1+2j)"


# =============================================================================
# _safe_key テスト (lines 162-168)
# =============================================================================


class TestSafeKey:
    """_safe_key: 辞書キー変換のテスト (lines 160-168)"""

    def test_string_key_passthrough(self):
        """文字列キーはそのまま返る"""
        assert _safe_key("hello") == "hello"

    def test_int_key(self):
        """int型キーが文字列に変換される (line 162-163)"""
        assert _safe_key(42) == "42"

    def test_float_key(self):
        """float型キーが文字列に変換される (line 162-163)"""
        assert _safe_key(3.14) == "3.14"

    def test_bool_key(self):
        """bool型キーが文字列に変換される (line 162-163)"""
        assert _safe_key(True) == "True"
        assert _safe_key(False) == "False"

    def test_enum_key(self):
        """Enum型キーが値の文字列に変換される (lines 164-165)"""
        assert _safe_key(Color.RED) == "red"
        assert _safe_key(Color.BLUE) == "3"

    def test_none_key(self):
        """Noneキーが'null'に変換される (lines 166-167)"""
        assert _safe_key(None) == "null"

    def test_other_key_type(self):
        """その他の型がstr()で変換される (line 168)"""
        uid = UUID("12345678-1234-5678-1234-567812345678")
        result = _safe_key(uid)
        assert result == "12345678-1234-5678-1234-567812345678"

    def test_tuple_key(self):
        """タプルキーがstr()で変換される"""
        result = _safe_key((1, 2))
        assert result == "(1, 2)"


# =============================================================================
# validate_json_serializable テスト (lines 190-198)
# =============================================================================


class TestValidateJsonSerializable:
    """validate_json_serializable のテスト (lines 190-198)"""

    def test_valid_dict(self):
        """JSON化可能な辞書 (lines 190-192)"""
        is_valid, error = validate_json_serializable({"name": "田中", "age": 30})
        assert is_valid is True
        assert error is None

    def test_valid_list(self):
        is_valid, error = validate_json_serializable([1, 2, 3])
        assert is_valid is True
        assert error is None

    def test_valid_string(self):
        is_valid, error = validate_json_serializable("hello")
        assert is_valid is True
        assert error is None

    def test_valid_none(self):
        is_valid, error = validate_json_serializable(None)
        assert is_valid is True
        assert error is None

    def test_invalid_with_lambda(self):
        """lambda関数を含む場合はTypeError (lines 193-194)"""
        is_valid, error = validate_json_serializable({"func": lambda x: x})
        assert is_valid is False
        assert error is not None
        assert "TypeError" in error

    def test_invalid_with_set(self):
        """set型はJSON化不可"""
        is_valid, error = validate_json_serializable({1, 2, 3})
        assert is_valid is False
        assert error is not None

    def test_invalid_with_datetime(self):
        """datetime型はJSON化不可"""
        is_valid, error = validate_json_serializable(datetime.now())
        assert is_valid is False
        assert error is not None

    def test_invalid_with_custom_object(self):
        """カスタムオブジェクトはJSON化不可"""
        is_valid, error = validate_json_serializable(ObjectWithToDict(data="test"))
        assert is_valid is False
        assert error is not None

    def test_value_error_handling(self):
        """ValueErrorが発生するケース (lines 195-196)"""
        # json.dumpsがValueErrorを発生させるケースを作る
        with patch("lib.brain.type_safety.json.dumps", side_effect=ValueError("Circular ref")):
            is_valid, error = validate_json_serializable({"a": 1})
        assert is_valid is False
        assert "ValueError" in error

    def test_unexpected_error_handling(self):
        """予期しないエラーのハンドリング (lines 197-198)"""
        with patch("lib.brain.type_safety.json.dumps", side_effect=OverflowError("Too big")):
            is_valid, error = validate_json_serializable({"a": 1})
        assert is_valid is False
        assert "Unexpected error" in error
        assert "OverflowError" in error


# =============================================================================
# ensure_json_serializable テスト (lines 227-239)
# =============================================================================


class TestEnsureJsonSerializable:
    """ensure_json_serializable のテスト (lines 227-239)"""

    def test_valid_dict_returned_as_is(self):
        """既にJSON化可能な辞書はそのまま返る (lines 229-230)"""
        data = {"name": "test", "value": 42}
        result = ensure_json_serializable(data)
        assert result == data

    def test_non_serializable_dict_is_converted(self):
        """JSON化不可能な辞書はsafe_to_dictで変換 (lines 232-233)"""
        data = {"created": datetime(2024, 1, 15), "id": uuid4()}
        result = ensure_json_serializable(data)
        assert isinstance(result, dict)
        assert result["created"] == "2024-01-15T00:00:00"
        assert isinstance(result["id"], str)

    def test_dataclass_converted_to_dict(self):
        """dataclassは辞書に変換される (lines 232-239)"""
        obj = SimpleDataclass(name="test", age=25)
        result = ensure_json_serializable(obj)
        assert result == {"name": "test", "age": 25}

    def test_string_wrapped_in_dict(self):
        """文字列は{'value': ...}にラップされる (lines 236-237)"""
        result = ensure_json_serializable("simple string")
        assert result == {"value": "simple string"}

    def test_int_wrapped_in_dict(self):
        """整数は{'value': ...}にラップされる (lines 236-237)"""
        result = ensure_json_serializable(42)
        assert result == {"value": 42}

    def test_list_wrapped_in_dict(self):
        """リストは{'value': ...}にラップされる (lines 236-237)"""
        result = ensure_json_serializable([1, 2, 3])
        assert result == {"value": [1, 2, 3]}

    def test_none_wrapped_in_dict(self):
        """Noneは{'value': None}にラップされる"""
        result = ensure_json_serializable(None)
        assert result == {"value": None}

    def test_enum_wrapped_in_dict(self):
        """Enumは値が{'value': ...}にラップされる"""
        result = ensure_json_serializable(Color.RED)
        assert result == {"value": "red"}

    def test_datetime_wrapped_in_dict(self):
        """datetimeはISO文字列が{'value': ...}にラップされる"""
        result = ensure_json_serializable(datetime(2024, 6, 1))
        assert result == {"value": "2024-06-01T00:00:00"}

    def test_max_depth_parameter(self):
        """max_depthパラメータがsafe_to_dictに渡される"""
        data = {"a": {"b": {"c": "deep"}}}
        # max_depth=1: depth 0 outer dict, depth 1 inner {"b":...},
        # depth 2 inner {"c":"deep"} exceeds, so "c" key's value at depth 3 exceeds
        # Actually: ensure_json_serializable calls validate first (fails for valid dict? no, this is valid)
        # This dict IS json serializable and IS a dict, so it returns as-is on line 229-230.
        # Use a non-serializable dict to force conversion path.
        data_ns = {"a": {"b": {"c": datetime(2024, 1, 1)}}}
        result = ensure_json_serializable(data_ns, max_depth=1)
        # depth 0: dict, depth 1: {"b":...}, depth 2: {"c": datetime},
        # depth 2 > 1: "<max depth 1 exceeded>"
        assert result["a"] == {"b": "<max depth 1 exceeded>"}

    def test_object_with_to_dict_converted(self):
        """to_dict()を持つオブジェクトは辞書に変換される (line 239)"""
        obj = ObjectWithToDict(data="hello")
        result = ensure_json_serializable(obj)
        assert result == {"data": "hello"}

    def test_valid_non_dict_is_still_converted(self):
        """JSON化可能でもdictでない場合はラップされる (line 229の条件)"""
        # "hello"はjson.dumps可能だが、dictではない
        result = ensure_json_serializable("hello")
        assert result == {"value": "hello"}

    def test_result_is_json_serializable(self):
        """ensure_json_serializableの結果は必ずJSON化可能"""
        complex_obj = {
            "person": SimpleDataclass(name="太郎", age=30),
            "time": datetime(2024, 1, 1),
            "id": uuid4(),
            "amount": Decimal("99.99"),
            "color": Color.GREEN,
            "duration": timedelta(hours=2),
        }
        result = ensure_json_serializable(complex_obj)
        # json.dumpsが例外を投げないことを確認
        json_str = json.dumps(result, ensure_ascii=False)
        assert isinstance(json_str, str)


# =============================================================================
# safe_to_dict: dict内のEnum キーとの統合テスト
# =============================================================================


class TestSafeToDictEnumKeyIntegration:
    """safe_to_dict: Enumをキーとして使った辞書のテスト"""

    def test_enum_key_in_dict(self):
        data = {Color.RED: "stop", Color.GREEN: "go"}
        result = safe_to_dict(data)
        assert result == {"red": "stop", "green": "go"}

    def test_priority_enum_key_in_dict(self):
        data = {Priority.HIGH: "urgent"}
        result = safe_to_dict(data)
        assert result == {"1": "urgent"}


# =============================================================================
# JSON_PRIMITIVES 定数テスト
# =============================================================================


class TestJsonPrimitives:
    """JSON_PRIMITIVES定数のテスト"""

    def test_primitives_tuple_contents(self):
        assert str in JSON_PRIMITIVES
        assert int in JSON_PRIMITIVES
        assert float in JSON_PRIMITIVES
        assert bool in JSON_PRIMITIVES
        assert type(None) in JSON_PRIMITIVES

    def test_primitives_count(self):
        assert len(JSON_PRIMITIVES) == 5
