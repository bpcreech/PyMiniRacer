"""Basic JS types tests"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from json import dumps
from time import time
from typing import Any, cast

import pytest

from py_mini_racer import (
    JSArray,
    JSEvalException,
    JSFunction,
    JSObject,
    JSSymbol,
    JSUndefined,
    MiniRacer,
)
from tests.gc_check import assert_no_v8_objects


def _test_round_trip(mr: MiniRacer, val: Any) -> None:  # noqa: ANN401
    a = cast("JSArray", mr.eval("[]"))
    a.append(val)  # force conversion into a JS type
    assert a[0] == val  # get it back again and verify it


@dataclass(frozen=True)
class Validator:
    round_trip: bool = True
    mr: MiniRacer = field(default_factory=MiniRacer)

    def __call__(self, py_val: Any) -> None:  # noqa: ANN401
        testee = py_val
        js_str = dumps(py_val)

        parsed = self.mr.execute(js_str)
        assert testee == parsed

        if self.round_trip:
            _test_round_trip(self.mr, py_val)

        assert_no_v8_objects(self.mr)


def test_undefined() -> None:
    mr = MiniRacer()
    undef = mr.eval("undefined")
    assert undef is JSUndefined
    assert undef == JSUndefined
    assert not undef
    _test_round_trip(mr, undef)

    del undef
    assert_no_v8_objects(mr)


def test_str() -> None:
    v = Validator()
    v("'a string'")
    v("'a ' + 'string'")
    v("string with null \0 byte")


def test_unicode() -> None:
    ustr = "\N{GREEK CAPITAL LETTER DELTA}"
    mr = MiniRacer()
    res = mr.eval("'" + ustr + "'")
    assert ustr == res
    _test_round_trip(mr, ustr)

    assert_no_v8_objects(mr)


def test_numbers() -> None:
    v = Validator()
    v(1)
    v(1.0)
    v(2**16)
    v(2**31 - 1)
    v(2**31)
    v(2**33)


def test_arrays() -> None:
    v = Validator(round_trip=False)
    v([1])
    v([])
    v([1, 2, 3])
    # Nested
    v([1, 2, ["a", 1]])


def test_none() -> None:
    v = Validator()
    v(None)


def test_hash() -> None:
    v = Validator(round_trip=False)
    v({})
    v("{}")
    v({"a": 1})
    v({" ": {"z": "www"}})


def test_complex() -> None:
    v = Validator(round_trip=False)
    v(
        {
            "1": [
                1,
                2,
                "qwe",
                {"z": [4, 5, 6, {"eqewr": 1, "zxczxc": "qweqwe", "z": {"1": 2}}]},
            ],
            "qwe": 1,
        }
    )


def test_object() -> None:
    mr = MiniRacer()
    res = mr.eval("var a = {}; a")
    assert isinstance(res, JSObject)
    assert res.__hash__() is not None
    _test_round_trip(mr, res)

    del res
    assert_no_v8_objects(mr)


def test_timestamp() -> None:
    val = int(time())
    mr = MiniRacer()
    res = mr.eval(f"var a = new Date({val * 1000}); a")
    assert res == datetime.fromtimestamp(val, timezone.utc)
    _test_round_trip(mr, res)

    assert_no_v8_objects(mr)


def test_symbol() -> None:
    mr = MiniRacer()
    res = mr.eval('Symbol("my_symbol")')
    assert isinstance(res, JSSymbol)
    assert res.__hash__() is not None
    _test_round_trip(mr, res)

    del res
    assert_no_v8_objects(mr)


def test_function() -> None:
    mr = MiniRacer()
    res = mr.eval("function func() {}; func")
    assert isinstance(res, JSFunction)
    assert res.__hash__() is not None
    _test_round_trip(mr, res)

    del res
    assert_no_v8_objects(mr)


def test_date() -> None:
    mr = MiniRacer()
    res = mr.eval("var a = new Date(Date.UTC(2014, 0, 2, 3, 4, 5)); a")
    assert res == datetime(2014, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    _test_round_trip(mr, res)

    del res
    assert_no_v8_objects(mr)


def test_exception() -> None:
    js_source = """
    var f = function(arg) {
        throw 'error: '+arg
        return nil
    }"""

    mr = MiniRacer()
    mr.eval(js_source)

    with pytest.raises(JSEvalException) as exc_info:
        mr.eval("f(42)")

    assert "error: 42" in exc_info.value.args[0]

    del exc_info
    assert_no_v8_objects(mr)


def test_array_buffer() -> None:
    js_source = """
    var b = new ArrayBuffer(1024);
    var v = new Uint8Array(b);
    v[0] = 0x42;
    b
    """
    mr = MiniRacer()
    ret = cast("memoryview", mr.eval(js_source))
    assert len(ret) == 1024  # noqa: PLR2004
    assert ret[0:1].tobytes() == b"\x42"

    del ret
    assert_no_v8_objects(mr)


def test_array_buffer_view() -> None:
    js_source = """
    var b = new ArrayBuffer(1024);
    var v = new Uint8Array(b, 1, 1);
    v[0] = 0x42;
    v
    """
    mr = MiniRacer()
    ret = cast("memoryview", mr.eval(js_source))
    assert len(ret) == 1
    assert ret.tobytes() == b"\x42"

    del ret
    assert_no_v8_objects(mr)


def test_shared_array_buffer() -> None:
    js_source = """
    var b = new SharedArrayBuffer(1024);
    var v = new Uint8Array(b);
    v[0] = 0x42;
    b
    """
    mr = MiniRacer()
    ret = cast("memoryview", mr.eval(js_source))
    assert len(ret) == 1024  # noqa: PLR2004
    assert ret[0:1].tobytes() == b"\x42"
    ret[1:2] = b"\xff"
    assert mr.eval("v[1]") == 0xFF  # noqa: PLR2004

    del ret
    assert_no_v8_objects(mr)
