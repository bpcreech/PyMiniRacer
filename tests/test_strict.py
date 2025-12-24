from __future__ import annotations

import pytest

from py_mini_racer import JSEvalException, JSUndefined, StrictMiniRacer
from tests.gc_check import assert_no_v8_objects


def test_basic_int() -> None:
    mr = StrictMiniRacer()
    assert mr.execute("42") == 42  # noqa: PLR2004

    assert_no_v8_objects(mr)


def test_basic_string() -> None:
    mr = StrictMiniRacer()
    assert mr.execute('"42"') == "42"

    assert_no_v8_objects(mr)


def test_basic_hash() -> None:
    mr = StrictMiniRacer()
    assert mr.execute("{}") == {}

    assert_no_v8_objects(mr)


def test_basic_array() -> None:
    mr = StrictMiniRacer()
    assert mr.execute("[1, 2, 3]") == [1, 2, 3]

    assert_no_v8_objects(mr)


def test_call() -> None:
    js_func = """var f = function(args) {
        return args.length;
    }"""

    mr = StrictMiniRacer()

    assert mr.eval(js_func) is JSUndefined
    assert mr.call("f", list(range(5))) == 5  # noqa: PLR2004

    assert_no_v8_objects(mr)


def test_message() -> None:
    mr = StrictMiniRacer()
    with pytest.raises(JSEvalException) as exc_info:
        mr.eval("throw new EvalError('Hello', 'someFile.js', 10);")

    del exc_info
    assert_no_v8_objects(mr)
