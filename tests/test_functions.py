"""Tests JSFunctions"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from py_mini_racer import JSEvalException, JSTimeoutException, MiniRacer
from tests.gc_check import assert_no_v8_objects

if TYPE_CHECKING:
    from py_mini_racer import JSArray, JSFunction, JSMappedObject


def test_function() -> None:
    mr = MiniRacer()
    func = cast("JSFunction", mr.eval("(a) => a"))
    assert func(42) == 42  # noqa: PLR2004
    arr = mr.eval("[41, 42]")
    assert list(cast("JSArray", func(arr))) == [41, 42]
    thing = cast(
        "JSMappedObject",
        mr.eval(
            """\
class Thing {
    constructor(a) {
        this.blob = a;
    }

    stuff(extra) {
        return this.blob + extra;
    }
}
new Thing('start');
"""
        ),
    )
    stuff = cast("JSFunction", thing["stuff"])
    assert stuff("end", this=thing) == "startend"

    del func, arr, thing, stuff
    assert_no_v8_objects(mr)


def test_exceptions() -> None:
    mr = MiniRacer()
    func = cast(
        "JSFunction",
        mr.eval(
            """\
function func(a, b, c) {
    throw new Error('asdf');
}
func
"""
        ),
    )

    with pytest.raises(JSEvalException) as exc_info:
        func()

    assert (
        exc_info.value.args[0]
        == """\
<anonymous>:2: Error: asdf
    throw new Error('asdf');
    ^

Error: asdf
    at func (<anonymous>:2:11)
"""
    )

    del func, exc_info
    assert_no_v8_objects(mr)


def test_timeout() -> None:
    mr = MiniRacer()

    func = cast("JSFunction", mr.eval("() => { while(1) { } }"))
    with pytest.raises(JSTimeoutException) as exc_info:
        func(timeout_sec=1)

    assert exc_info.value.args[0] == "JavaScript was terminated by timeout"

    del func, exc_info
    assert_no_v8_objects(mr)
