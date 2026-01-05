"""Test Python functions exposed as JS."""

from __future__ import annotations

from asyncio import Future, gather
from asyncio import run as asyncio_run
from asyncio import sleep as asyncio_sleep
from time import time
from typing import TYPE_CHECKING, Any, NoReturn, cast

import pytest

from py_mini_racer import JSFunction, JSPromise, JSPromiseError, mini_racer
from tests.gc_check import async_assert_no_v8_objects

if TYPE_CHECKING:
    from py_mini_racer import JSFunction
    from py_mini_racer._mini_racer import MiniRacer


_NUM_LOOPS = 10


def test_basic() -> None:
    data = []

    async def append(*args: Any) -> str:  # noqa: ANN401
        data.append(args)
        return "foobar"

    async def define_and_use_function(mr: MiniRacer) -> None:
        async with mr.wrap_py_function(append) as jsfunc:
            # "Install" our JS function on the global "this" object:
            cast("JSFunction", mr.eval("x => this.func = x"))(jsfunc)

            # Call our function a couple times, through JS:
            assert await cast("JSPromise", mr.eval("this.func(42)")) == "foobar"
            assert await cast("JSPromise", mr.eval('this.func("blah")')) == "foobar"

        assert data == [(42,), ("blah",)]
        data[:] = []

    async def run() -> None:
        with mini_racer() as mr:
            for _ in range(_NUM_LOOPS):
                await define_and_use_function(mr)

            await async_assert_no_v8_objects(mr)

    for _ in range(_NUM_LOOPS):
        asyncio_run(run())


def test_exception() -> None:
    # Test a Python callback which raises exceptions

    async def append(*args: Any) -> NoReturn:  # noqa: ANN401
        del args
        boo = "boo"
        raise RuntimeError(boo)

    async def run() -> None:
        with mini_racer() as mr:
            async with mr.wrap_py_function(append) as jsfunc:
                # "Install" our JS function on the global "this" object:
                cast("JSFunction", mr.eval("x => this.func = x"))(jsfunc)

                with pytest.raises(JSPromiseError) as exc_info:
                    await cast("JSPromise", mr.eval("this.func(42)"))

                assert exc_info.value.args[0].startswith(
                    """\
JavaScript rejected promise with reason: Error: Error running Python function:
Traceback (most recent call last):
"""
                )

                assert exc_info.value.args[0].endswith(
                    """\

    at <anonymous>:1:6
"""
                )

            del exc_info, jsfunc
            await async_assert_no_v8_objects(mr)

    for _ in range(_NUM_LOOPS):
        asyncio_run(run())


def test_slow() -> None:
    # Test a Python callback which runs slowly, but is faster in parallel.
    data = []

    async def append(*args: Any) -> str:  # noqa: ANN401
        await asyncio_sleep(1)
        data.append(args)
        return "foobar"

    async def run() -> None:
        with mini_racer() as mr:
            async with mr.wrap_py_function(append) as jsfunc:
                # "Install" our JS function on the global "this" object:
                cast("JSFunction", mr.eval("x => this.func = x"))(jsfunc)

                pending = [
                    cast("JSPromise", mr.eval("this.func(42)")) for _ in range(100)
                ]

                assert await gather(*pending) == ["foobar"] * 100

            assert data == [(42,)] * 100
            data.clear()
            del pending, jsfunc
            await async_assert_no_v8_objects(mr)

    data.clear()

    start = time()
    asyncio_run(run())
    # The above should run in just over a second.
    # Just verify it didn't take 100 seconds (i.e., that things didn't execute
    # sequentially):
    assert time() - start < 10  # noqa: PLR2004


def test_call_on_exit() -> None:
    """Checks that calls from JS made while we're trying to tear down the wrapped
    function are ignored and don't break anything."""

    data = []

    async def run() -> None:
        append_called_fut: Future[None] = Future()

        async def append(*args: Any) -> str:  # noqa: ANN401
            data.append(args)
            append_called_fut.set_result(None)
            # sleep long enough that the test will fail unless this is either
            # interrupted, or never started to begin with:
            await asyncio_sleep(10000)
            return "foobar"

        with mini_racer() as mr:
            async with mr.wrap_py_function(append) as jsfunc:
                # "Install" our JS function on the global "this" object:
                cast("JSFunction", mr.eval("x => this.func = x"))(jsfunc)

                # Note: we don't await the promise, meaning we just start a call and
                # never finish it:
                assert isinstance(mr.eval("this.func(42)"), JSPromise)

                await append_called_fut

                # After this line, we start tearing down the mr.wrap_py_function context
                # manager, which entails stopping the call processor.
                # Let's make sure we don't fall over ourselves (it's fair to either
                # process the last straggling calls, or ignore them, but make sure we
                # don't hang).

        del jsfunc
        await async_assert_no_v8_objects(mr)

    for _ in range(_NUM_LOOPS):
        data[:] = []
        asyncio_run(run())
