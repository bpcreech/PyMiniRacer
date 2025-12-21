"""Test .eval() method"""

from __future__ import annotations

from asyncio import run as asyncio_run
from time import sleep, time
from typing import cast

import pytest

from py_mini_racer import (
    JSEvalException,
    JSOOMException,
    JSParseException,
    JSPromise,
    JSPromiseError,
    JSSymbol,
    JSTimeoutException,
    JSUndefined,
    MiniRacer,
)
from tests.gc_check import assert_no_v8_objects

# Wait time for async tests to finish.
_ASYNC_COMPLETION_WAIT_SEC = 10


def test_invalid() -> None:
    mr = MiniRacer()

    with pytest.raises(JSEvalException) as exc_info:
        mr.eval("invalid")

    assert (
        exc_info.value.args[0]
        == """\
<anonymous>:1: ReferenceError: invalid is not defined
invalid
^

ReferenceError: invalid is not defined
    at <anonymous>:1:1
"""
    )

    del exc_info
    assert_no_v8_objects(mr)


def test_eval() -> None:
    mr = MiniRacer()
    assert mr.eval("42") == 42  # noqa: PLR2004

    assert_no_v8_objects(mr)


def test_blank() -> None:
    mr = MiniRacer()
    assert mr.eval("") is JSUndefined
    assert mr.eval(" ") is JSUndefined
    assert mr.eval("\t") is JSUndefined

    assert_no_v8_objects(mr)


def test_global() -> None:
    mr = MiniRacer()
    mr.eval("var xabc = 22;")
    assert mr.eval("xabc") == 22  # noqa: PLR2004

    assert_no_v8_objects(mr)


def test_fun() -> None:
    mr = MiniRacer()
    mr.eval("var x = function(y) {return y+1;}")

    assert mr.eval("x(1)") == 2  # noqa: PLR2004
    assert mr.eval("x(10)") == 11  # noqa: PLR2004
    assert mr.eval("x(100)") == 101  # noqa: PLR2004

    assert_no_v8_objects(mr)


def test_multiple_ctx() -> None:
    c1 = MiniRacer()
    c2 = MiniRacer()
    c3 = MiniRacer()

    c1.eval("var x = 1")
    c2.eval("var x = 2")
    c3.eval("var x = 3")
    assert c1.eval("(x)") == 1
    assert c2.eval("(x)") == 2  # noqa: PLR2004
    assert c3.eval("(x)") == 3  # noqa: PLR2004

    assert_no_v8_objects(c1)
    assert_no_v8_objects(c2)
    assert_no_v8_objects(c3)


def test_exception_thrown() -> None:
    mr = MiniRacer()

    mr.eval("var f = function() {throw new Error('blah')};")

    with pytest.raises(JSEvalException) as exc_info:
        mr.eval("f()")

    assert (
        exc_info.value.args[0]
        == """\
<anonymous>:1: Error: blah
var f = function() {throw new Error('blah')};
                    ^

Error: blah
    at f (<anonymous>:1:27)
    at <anonymous>:1:1
"""
    )

    del exc_info
    assert_no_v8_objects(mr)


def test_string_thrown() -> None:
    mr = MiniRacer()

    mr.eval("var f = function() {throw 'blah'};")

    with pytest.raises(JSEvalException) as exc_info:
        mr.eval("f()")

    # When you throw a plain string (not wrapping it in a `new Error(...)`), you
    # get no backtrace:
    assert (
        exc_info.value.args[0]
        == """\
<anonymous>:1: blah
var f = function() {throw 'blah'};
                    ^
"""
    )

    del exc_info
    assert_no_v8_objects(mr)


def test_cannot_parse() -> None:
    mr = MiniRacer()

    with pytest.raises(JSParseException) as exc_info:
        mr.eval("var f = function(")

    assert (
        exc_info.value.args[0]
        == """\
<anonymous>:1: SyntaxError: Unexpected end of input
var f = function(
                 ^

SyntaxError: Unexpected end of input
"""
    )

    del exc_info
    assert_no_v8_objects(mr)


def test_null_byte() -> None:
    mr = MiniRacer()

    s = "\x00 my string!"

    # Try return a string including a null byte
    in_val = 'var str = "' + s + '"; str;'
    result = mr.eval(in_val)
    assert result == s

    assert_no_v8_objects(mr)


def test_timeout() -> None:
    timeout = 0.3
    start_time = time()

    mr = MiniRacer()
    with pytest.raises(JSTimeoutException) as exc_info:
        mr.eval("while(1) { }", timeout_sec=timeout)

    duration = time() - start_time
    # Make sure it timed out on time, and allow a large leeway
    assert timeout * 0.9 <= duration <= timeout + 2

    assert exc_info.value.args[0] == "JavaScript was terminated by timeout"

    del exc_info
    assert_no_v8_objects(mr)


def test_timeout_ms() -> None:
    # Same as above but with the deprecated timeout millisecond argument
    timeout = 0.3
    start_time = time()

    mr = MiniRacer()
    with pytest.raises(JSTimeoutException) as exc_info:
        mr.eval("while(1) { }", timeout=int(timeout * 1000))

    duration = time() - start_time
    # Make sure it timed out on time, and allow a large leeway
    assert timeout * 0.9 <= duration <= timeout + 2

    assert exc_info.value.args[0] == "JavaScript was terminated by timeout"

    del exc_info
    assert_no_v8_objects(mr)


def test_max_memory_soft() -> None:
    mr = MiniRacer()
    mr.set_soft_memory_limit(100000000)
    mr.set_hard_memory_limit(100000000)
    with pytest.raises(JSOOMException) as exc_info:
        mr.eval(
            """\
let s = 1000;
var a = new Array(s);
a.fill(0);
while(true) {
    s *= 1.1;
    let n = new Array(Math.floor(s));
    n.fill(0);
    a = a.concat(n);
}
"""
        )

    assert mr.was_soft_memory_limit_reached()
    assert mr.was_hard_memory_limit_reached()
    assert exc_info.value.args[0] == "JavaScript memory limit reached"

    del exc_info
    assert_no_v8_objects(mr)


def test_max_memory_hard() -> None:
    mr = MiniRacer()
    mr.set_hard_memory_limit(100000000)
    with pytest.raises(JSOOMException) as exc_info:
        mr.eval(
            """\
let s = 1000;
var a = new Array(s);
a.fill(0);
while(true) {
    s *= 1.1;
    let n = new Array(Math.floor(s));
    n.fill(0);
    a = a.concat(n);
}"""
        )

    assert not mr.was_soft_memory_limit_reached()
    assert mr.was_hard_memory_limit_reached()
    assert exc_info.value.args[0] == "JavaScript memory limit reached"

    del exc_info
    assert_no_v8_objects(mr)


def test_max_memory_hard_eval_arg() -> None:
    # Same as above but passing the argument into the eval method (which is a
    # deprecated thing to do because the parameter is really affine to the
    # MiniRacer object)
    mr = MiniRacer()
    with pytest.raises(JSOOMException) as exc_info:
        mr.eval(
            """\
let s = 1000;
var a = new Array(s);
a.fill(0);
while(true) {
    s *= 1.1;
    let n = new Array(Math.floor(s));
    n.fill(0);
    a = a.concat(n);
}""",
            max_memory=200000000,
        )

    assert exc_info.value.args[0] == "JavaScript memory limit reached"

    del exc_info
    assert_no_v8_objects(mr)


def test_symbol() -> None:
    mr = MiniRacer()
    res = mr.eval("Symbol.toPrimitive")
    assert isinstance(res, JSSymbol)

    del res
    assert_no_v8_objects(mr)


def test_microtask() -> None:
    # PyMiniRacer uses V8 microtasks (things, like certain promise callbacks, which run
    # immediately after an evaluation ends).
    # By default, V8 runs any microtasks before it returns control to PyMiniRacer.
    # Let's test that they actually work.
    # PyMiniRacer does not expose the web standard `window.queueMicrotask` (because it
    # does not expose a `window` to begin with). We can, however, trigger a microtask
    # by triggering one as a side effect of a `then` on a resolved promise:
    mr = MiniRacer()
    assert not mr.eval(
        """
let p = Promise.resolve();

var done = false;

p.then(() => {done = true});

done
"""
    )
    assert mr.eval("done")

    assert_no_v8_objects(mr)


def test_longer_microtask() -> None:
    # Verifies a bug fix wherein failure to set a v8::Isolate::Scope on the message
    # pump thread would otherwise result in a segmentation fault:
    mr = MiniRacer()
    mr.eval(
        """
var done = false;
async function foo() {
    await new Promise((res, rej) => setTimeout(res, 1000));
    for (let i = 0; i < 10000000; i++) { }
    done = true;
}
foo();
"""
    )

    assert not mr.eval("done")
    start = time()
    while time() - start < _ASYNC_COMPLETION_WAIT_SEC and not mr.eval("done"):
        sleep(0.1)
    assert mr.eval("done")

    assert_no_v8_objects(mr)


def test_polling() -> None:
    mr = MiniRacer()
    assert not mr.eval(
        """
var done = false;
setTimeout(() => { done = true; }, 1000);
done
"""
    )
    assert not mr.eval("done")
    start = time()
    while time() - start < _ASYNC_COMPLETION_WAIT_SEC and not mr.eval("done"):
        sleep(0.1)
    assert mr.eval("done")

    assert_no_v8_objects(mr)


def test_settimeout() -> None:
    mr = MiniRacer()
    mr.eval(
        """
var results = [];
let a = setTimeout(() => { results.push("a"); }, 2000);
let b = setTimeout(() => { results.push("b"); }, 3000);
let c = setTimeout(() => { results.push("c"); }, 1000);
let d = setTimeout(() => { results.push("d"); }, 4000);
clearTimeout(b)
"""
    )
    start = time()
    while (
        time() - start < _ASYNC_COMPLETION_WAIT_SEC and mr.eval("results.length") != 3  # noqa: PLR2004
    ):
        sleep(0.1)
    assert mr.eval("results.length") == 3  # noqa: PLR2004
    assert mr.eval("results[0]") == "c"
    assert mr.eval("results[1]") == "a"
    assert mr.eval("results[2]") == "d"

    assert_no_v8_objects(mr)


def test_promise_sync() -> None:
    mr = MiniRacer()
    p = cast(
        "JSPromise",
        mr.eval(
            """
new Promise((res, rej) => setTimeout(() => res(42), 1000)); // 1 s timeout
"""
        ),
    )
    start = time()
    result = p.get(timeout=10)
    assert time() - start > 0.5  # noqa: PLR2004
    assert result == 42  # noqa: PLR2004

    del p
    assert_no_v8_objects(mr)


def test_promise_async() -> None:
    mr = MiniRacer()

    async def run_test() -> None:
        p = cast(
            "JSPromise",
            mr.eval(
                """
new Promise((res, rej) => setTimeout(() => res(42), 1000)); // 1 s timeout
"""
            ),
        )
        start = time()
        result = await p
        assert time() - start > 0.5  # noqa: PLR2004
        assert time() - start < _ASYNC_COMPLETION_WAIT_SEC
        assert result == 42  # noqa: PLR2004

    asyncio_run(run_test())
    assert_no_v8_objects(mr)


def test_resolved_promise_sync() -> None:
    mr = MiniRacer()
    p = cast("JSPromise", mr.eval("Promise.resolve(6*7)"))
    val = p.get()
    assert val == 42  # noqa: PLR2004

    del val, p

    assert_no_v8_objects(mr)


def test_resolved_promise_async() -> None:
    mr = MiniRacer()

    async def run_test() -> None:
        p = cast("JSPromise", mr.eval("Promise.resolve(6*7)"))
        val = await p
        assert val == 42  # noqa: PLR2004

    asyncio_run(run_test())
    assert_no_v8_objects(mr)


def test_rejected_promise_sync() -> None:
    mr = MiniRacer()

    p = cast("JSPromise", mr.eval("Promise.reject(new Error('this is an error'))"))
    with pytest.raises(JSPromiseError) as exc_info:
        p.get()

    assert (
        exc_info.value.args[0]
        == """\
JavaScript rejected promise with reason: Error: this is an error
    at <anonymous>:1:16
"""
    )

    del exc_info, p
    assert_no_v8_objects(mr)


def test_rejected_promise_async() -> None:
    mr = MiniRacer()

    async def run_test() -> None:
        p = cast("JSPromise", mr.eval("Promise.reject(new Error('this is an error'))"))
        with pytest.raises(JSPromiseError) as exc_info:
            await p

        assert (
            exc_info.value.args[0]
            == """\
JavaScript rejected promise with reason: Error: this is an error
    at <anonymous>:1:16
"""
        )

    asyncio_run(run_test())
    assert_no_v8_objects(mr)


def test_rejected_promise_sync_stringerror() -> None:
    mr = MiniRacer()

    p = cast("JSPromise", mr.eval("Promise.reject('this is a string')"))
    with pytest.raises(JSPromiseError) as exc_info:
        p.get()

    assert (
        exc_info.value.args[0]
        == """\
JavaScript rejected promise with reason: this is a string
"""
    )

    del exc_info, p
    assert_no_v8_objects(mr)
