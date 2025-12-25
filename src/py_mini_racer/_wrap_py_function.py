from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from traceback import format_exc
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from py_mini_racer._exc import JSEvalException
    from py_mini_racer._js_value_manipulator import JSValueManipulator
    from py_mini_racer._types import (
        JSArray,
        JSFunction,
        PyJsFunctionType,
        PythonJSConvertedTypes,
    )


@asynccontextmanager
async def wrap_py_function_as_js_function(
    context: JSValueManipulator, func: PyJsFunctionType
) -> AsyncGenerator[JSFunction, None]:
    with context.js_to_py_callback(
        _JsToPyCallbackProcessor(
            func, context, asyncio.get_running_loop()
        ).process_one_invocation_from_js
    ) as js_to_py_callback:
        # Every time our callback is called from JS, on the JS side we
        # instantiate a JS Promise and immediately pass its resolution functions
        # into our Python callback function. While we wait on Python's asyncio
        # loop to process this call, we can return the Promise to the JS caller,
        # thus exposing what looks like an ordinary async function on the JS
        # side of things.
        wrap_outbound_calls_with_js_promises = cast(
            "JSFunction",
            context.evaluate(
                """
fn => {
    return (...arguments) => {
        let p = Promise.withResolvers();

        fn(arguments, p.resolve, p.reject);

        return p.promise;
    }
}
"""
            ),
        )

        yield cast(
            "JSFunction", wrap_outbound_calls_with_js_promises(js_to_py_callback)
        )


@dataclass(frozen=True)
class _JsToPyCallbackProcessor:
    """Processes incoming calls from JS into Python.

    Note that this is not thread-safe and is thus suitable for use with only one asyncio
    loop."""

    _py_func: PyJsFunctionType
    _val_manipulator: JSValueManipulator
    _loop: asyncio.AbstractEventLoop
    _ongoing_callbacks: set[asyncio.Task[PythonJSConvertedTypes | JSEvalException]] = (
        field(default_factory=set)
    )

    def process_one_invocation_from_js(
        self, params: PythonJSConvertedTypes | JSEvalException
    ) -> None:
        async def await_into_js_promise_resolvers(
            arguments: JSArray, resolve: JSFunction, reject: JSFunction
        ) -> None:
            try:
                result = await self._py_func(*arguments)
                resolve(result)
            except Exception:  # noqa: BLE001
                # Convert this Python exception into a JS exception so we can send
                # it into JS:
                err_maker = cast(
                    "JSFunction", self._val_manipulator.evaluate("s => new Error(s)")
                )
                reject(err_maker(f"Error running Python function:\n{format_exc()}"))

        # Start a new task to await this invocation:
        def start_task() -> None:
            arguments, resolve, reject = cast("JSArray", params)
            task = self._loop.create_task(
                await_into_js_promise_resolvers(
                    cast("JSArray", arguments),
                    cast("JSFunction", resolve),
                    cast("JSFunction", reject),
                )
            )

            self._ongoing_callbacks.add(task)

            task.add_done_callback(self._ongoing_callbacks.discard)

        self._loop.call_soon_threadsafe(start_task)
