from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from py_mini_racer import (
    JSArray,
    JSFunction,
    JSObject,
    JSPromise,
    JSSymbol,
    JSUndefined,
    MiniRacer,
)
from tests.gc_check import assert_no_v8_objects

if TYPE_CHECKING:
    from py_mini_racer import JSMappedObject


def test_object_read() -> None:
    mr = MiniRacer()
    obj = cast(
        "JSMappedObject",
        mr.eval(
            """\
var a = {
    5: "key_is_number",
    "key_is_string": 42,
    undefined: "undef_value",
    null: "null_value",
};
a
"""
        ),
    )

    assert obj.__hash__()
    assert obj
    assert sorted(obj.keys(), key=str) == [5, "key_is_string", "null", "undefined"]
    assert obj["5"] == "key_is_number"
    assert obj[5] == "key_is_number"
    assert obj["key_is_string"] == 42  # noqa: PLR2004
    assert obj[None] == "null_value"
    assert obj[JSUndefined] == "undef_value"
    assert len(obj) == 4  # noqa: PLR2004

    # The following are provided by collections.abc mixins:
    assert 5 in obj  # noqa: PLR2004
    assert None in obj
    assert "elvis" not in obj
    assert sorted(obj.items(), key=lambda x: str(x[0])) == [
        (5, "key_is_number"),
        ("key_is_string", 42),
        ("null", "null_value"),
        ("undefined", "undef_value"),
    ]
    assert set(obj.values()) == {42, "key_is_number", "undef_value", "null_value"}
    obj2 = mr.eval(
        """\
var a = {
    5: "key_is_number",
    "key_is_string": 42,
    undefined: "undef_value",
    null: "null_value",
};
a
"""
    )
    assert obj == obj2

    obj3 = mr.eval(
        """\
var a = {};
a
"""
    )
    assert not obj3

    del obj, obj2, obj3
    assert_no_v8_objects(mr)


def test_object_mutation() -> None:
    mr = MiniRacer()
    obj = cast(
        "JSMappedObject",
        mr.eval(
            """\
var a = {};
a
"""
        ),
    )

    obj["some_string"] = "some_string_val"
    obj[JSUndefined] = "undefined_val"
    obj[None] = "none_val"
    obj[5] = "int_val"
    # Note that this should overwrite 5=int_val above:
    obj[5.0] = "double_val"
    assert sorted(obj.items(), key=lambda x: str(x[0])) == [
        (5, "double_val"),
        ("null", "none_val"),
        ("some_string", "some_string_val"),
        ("undefined", "undefined_val"),
    ]
    assert obj.pop(None) == "none_val"
    with pytest.raises(KeyError):
        obj.pop(None)
    with pytest.raises(KeyError):
        del obj["elvis"]
    obj.clear()
    assert not obj
    obj["foo"] = "bar"
    assert obj.setdefault("foo", "baz") == "bar"
    obj.update({"froz": "blargh"})
    assert len(obj) == 2  # noqa: PLR2004

    inner_obj = mr.eval(
        """\
var b = {"k": "v"};
b
"""
    )
    obj["inner"] = inner_obj
    assert len(obj) == 3  # noqa: PLR2004
    assert cast("JSMappedObject", obj["inner"])["k"] == "v"

    del obj, inner_obj
    assert_no_v8_objects(mr)


def test_object_prototype() -> None:
    mr = MiniRacer()
    obj = cast(
        "JSMappedObject",
        mr.eval(
            """\
var proto = { 5: "key_is_number", "key_is_string": 42 };
var a = Object.create(proto);
a.foo = "bar";
a
"""
        ),
    )
    assert sorted(obj.items(), key=lambda x: str(x[0])) == [
        (5, "key_is_number"),
        ("foo", "bar"),
        ("key_is_string", 42),
    ]

    del obj
    assert_no_v8_objects(mr)


def test_array() -> None:
    mr = MiniRacer()
    obj = mr.eval(
        """\
var a = [ "some_string", 42, undefined, null ];
a
"""
    )

    assert isinstance(obj, JSArray)
    assert obj.__hash__()
    assert obj
    assert obj[0] == "some_string"
    assert obj[1] == 42  # noqa: PLR2004
    assert obj[2] is JSUndefined
    assert obj[2] == JSUndefined
    assert obj[3] is None
    assert obj[-3] == 42  # noqa: PLR2004
    with pytest.raises(IndexError):
        obj[4]
    with pytest.raises(IndexError):
        obj[-5]

    assert list(obj) == ["some_string", 42, JSUndefined, None]
    assert len(obj) == 4  # noqa: PLR2004
    assert list(obj) == ["some_string", 42, JSUndefined, None]
    assert 42 in obj  # noqa: PLR2004
    assert JSUndefined in obj
    assert None in obj
    assert "elvis" not in obj

    obj2 = mr.eval(
        """\
var a = [];
a
"""
    )
    assert not obj2

    del obj, obj2
    assert_no_v8_objects(mr)


def test_array_mutation() -> None:
    mr = MiniRacer()
    obj = cast(
        "JSArray",
        mr.eval(
            """\
var a = [];
a
"""
        ),
    )

    obj.append("some_string")
    obj.append(JSUndefined)
    obj.insert(1, 42)
    obj.insert(-1, None)
    assert list(obj) == ["some_string", 42, None, JSUndefined]

    del obj[-1]
    assert list(obj) == ["some_string", 42, None]

    del obj[0]
    assert list(obj) == [42, None]

    with pytest.raises(IndexError):
        del obj[-3]

    with pytest.raises(IndexError):
        del obj[2]

    inner_obj = mr.eval(
        """\
var b = {"k": "v"};
b
"""
    )
    obj.append(inner_obj)
    assert len(obj) == 3  # noqa: PLR2004
    assert cast("JSMappedObject", obj[-1])["k"] == "v"

    del obj, inner_obj
    assert_no_v8_objects(mr)


def test_function() -> None:
    mr = MiniRacer()
    obj = mr.eval(
        """\
function foo() {};
foo
"""
    )

    assert isinstance(obj, JSFunction)
    assert obj.__hash__()
    assert tuple(obj.keys()) == ()

    del obj
    assert_no_v8_objects(mr)


def test_symbol() -> None:
    mr = MiniRacer()
    obj = mr.eval(
        """\
var sym = Symbol("foo");
sym
"""
    )

    assert isinstance(obj, JSSymbol)
    assert obj.__hash__()
    assert tuple(obj.keys()) == ()

    del obj
    assert_no_v8_objects(mr)


def test_promise() -> None:
    mr = MiniRacer()
    promise = mr.eval(
        """\
var p = Promise.resolve(42);
p
"""
    )

    assert isinstance(promise, JSPromise)
    assert promise.__hash__()

    del promise
    assert_no_v8_objects(mr)


def test_nested_object() -> None:
    mr = MiniRacer()
    obj = cast(
        "JSMappedObject",
        mr.eval(
            """\
var a = {
    5: "key_is_number",
    "key_is_string": 42,
    "some_func": () => {},
    "some_obj": {"a": 12},
    "some_promise": Promise.resolve(42),
    "some_symbol": Symbol("sym"),
};
a
"""
        ),
    )

    assert obj.__hash__()
    assert sorted(obj.keys(), key=str) == [
        5,
        "key_is_string",
        "some_func",
        "some_obj",
        "some_promise",
        "some_symbol",
    ]
    assert obj["5"] == "key_is_number"
    assert obj[5] == "key_is_number"
    assert obj["key_is_string"] == 42  # noqa: PLR2004
    assert isinstance(obj["some_func"], JSFunction)
    assert isinstance(obj["some_obj"], JSObject)
    assert cast("JSMappedObject", obj["some_obj"])["a"] == 12  # noqa: PLR2004
    assert isinstance(obj["some_promise"], JSPromise)
    assert isinstance(obj["some_symbol"], JSSymbol)

    del obj
    assert_no_v8_objects(mr)
