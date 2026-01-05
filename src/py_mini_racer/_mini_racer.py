from __future__ import annotations

import asyncio
import json
from contextlib import (
    AbstractContextManager,
    asynccontextmanager,
    contextmanager,
    suppress,
)
from itertools import count
from json import JSONEncoder
from threading import Thread
from typing import TYPE_CHECKING, Any, ClassVar

from py_mini_racer._context import Context, ContextType, get_running_loop_or_none
from py_mini_racer._dll import init_mini_racer, mr_callback_func
from py_mini_racer._exc import JSTimeoutException, WrongReturnTypeException
from py_mini_racer._objects import ObjectFactoryImpl
from py_mini_racer._set_timeout import INSTALL_SET_TIMEOUT

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator
    from types import TracebackType

    from typing_extensions import Self

    from py_mini_racer._types import (
        JSFunction,
        PyJsFunctionType,
        PythonJSConvertedTypes,
    )
    from py_mini_racer._value_handle import RawValueHandleType


class MiniRacer:
    """
    MiniRacer evaluates JavaScript code using a V8 isolate.

    A MiniRacer instance can be explicitly closed using the close() method, or by using
    the MiniRacer as a context manager, i.e,:

    with MiniRacer() as mr:
        ...

    The MiniRacer instance will otherwise clean up the underlying V8 resources upon
    garbage collection.

    Attributes:
        json_impl: JSON module used by helper methods default is
            [json](https://docs.python.org/3/library/json.html)
    """

    json_impl: ClassVar[Any] = json

    def __init__(self, context: Context | None = None) -> None:
        if context is None:
            self._own_context_maker: AbstractContextManager[Context] | None = (
                _make_context()
            )
            self._ctx: Context | None = self._own_context_maker.__enter__()
        else:
            self._own_context_maker = None
            self._ctx = context

        self.eval(INSTALL_SET_TIMEOUT)

    def close(
        self,
        exc_type: type[BaseException] | None = None,
        exc_val: BaseException | None = None,
        exc_tb: TracebackType | None = None,
    ) -> None:
        """Close this MiniRacer instance.

        It is an error to use this MiniRacer instance or any JS objects returned by it
        after calling this method.
        """
        own_context_maker = self._own_context_maker
        self._own_context_maker = None
        self._ctx = None

        if own_context_maker is not None:
            own_context_maker.__exit__(exc_type, exc_val, exc_tb)

    def __del__(self) -> None:
        # Ignore ordering problems on process teardown.
        # (A user who wants consistent teardown should use `with MiniRacer() as ctx`
        # which makes the cleanup deterministic.)
        with suppress(Exception):
            self.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close(exc_type, exc_val, exc_tb)

    @property
    def v8_version(self) -> str:
        """Return the V8 version string."""
        assert self._ctx is not None
        return self._ctx.v8_version()

    def eval(
        self,
        code: str,
        timeout: float | None = None,
        timeout_sec: float | None = None,
        max_memory: int | None = None,
    ) -> PythonJSConvertedTypes:
        """Evaluate JavaScript code in the V8 isolate.

        Side effects from the JavaScript evaluation is persisted inside a context
        (meaning variables set are kept for the next evaluation).

        The JavaScript value returned by the last expression in `code` is converted to
        a Python value and returned by this method. Only primitive types are supported
        (numbers, strings, buffers...). Use the
        [py_mini_racer.MiniRacer.execute][] method to return more complex
        types such as arrays or objects.

        The evaluation can be interrupted by an exception for several reasons: a limit
        was reached, the code could not be parsed, a returned value could not be
        converted to a Python value.

        Args:
            code: JavaScript code
            timeout: number of milliseconds after which the execution is interrupted.
                This is deprecated; use timeout_sec instead.
            timeout_sec: number of seconds after which the execution is interrupted
            max_memory: hard memory limit, in bytes, after which the execution is
                interrupted.
        """

        if max_memory is not None:
            self.set_hard_memory_limit(max_memory)

        if timeout:
            # PyMiniRacer unfortunately uses milliseconds while Python and
            # Système international d'unités use seconds.
            timeout_sec = timeout / 1000

        ctx = self._ctx
        assert ctx is not None

        if not ctx.are_we_running_on_the_mini_racer_event_loop():

            async def run() -> PythonJSConvertedTypes:
                try:
                    return await asyncio.wait_for(
                        ctx.eval_cancelable(code), timeout=timeout_sec
                    )
                except asyncio.TimeoutError as e:
                    raise JSTimeoutException from e

            return asyncio.run_coroutine_threadsafe(run(), ctx.event_loop).result()

        assert timeout_sec is None, (
            "To apply a timeout in an async context, use "
            "`await asyncio.wait_for(mr.eval_cancelable(your_params), "
            "timeout=your_timeout)`"
        )

        return ctx.eval(code)

    async def eval_cancelable(self, code: str) -> PythonJSConvertedTypes:
        """Evaluate JavaScript code in the V8 isolate.

        Similar to eval(), but runaway calls can be canceled by canceling the
        coroutine's task, e.g., using:

            await asyncio.wait_for(mr.eval_cancelable(...), timeout=some_timeout)

        """

        assert self._ctx is not None

        return await self._ctx.eval_cancelable(code)

    def execute(
        self,
        expr: str,
        timeout: float | None = None,
        timeout_sec: float | None = None,
        max_memory: int | None = None,
    ) -> Any:  # noqa: ANN401
        """Helper to evaluate a JavaScript expression and return composite types.

        Returned value is serialized to JSON inside the V8 isolate and deserialized
        using `json_impl`.

        Args:
            expr: JavaScript expression
            timeout: number of milliseconds after which the execution is interrupted.
                This is deprecated; use timeout_sec instead.
            timeout_sec: number of seconds after which the execution is interrupted
            max_memory: hard memory limit, in bytes, after which the execution is
                interrupted.
        """

        if timeout:
            # PyMiniRacer unfortunately uses milliseconds while Python and
            # Système international d'unités use seconds.
            timeout_sec = timeout / 1000

        wrapped_expr = f"JSON.stringify((function(){{return ({expr})}})())"
        ret = self.eval(wrapped_expr, timeout_sec=timeout_sec, max_memory=max_memory)
        if not isinstance(ret, str):
            raise WrongReturnTypeException(type(ret))
        return self.json_impl.loads(ret)

    def call(
        self,
        expr: str,
        *args: Any,  # noqa: ANN401
        encoder: type[JSONEncoder] | None = None,
        timeout: float | None = None,
        timeout_sec: float | None = None,
        max_memory: int | None = None,
    ) -> Any:  # noqa: ANN401
        """Helper to call a JavaScript function and return compositve types.

        The `expr` argument refers to a JavaScript function in the current V8
        isolate context. Further positional arguments are serialized using the JSON
        implementation `json_impl` and passed to the JavaScript function as arguments.

        Returned value is serialized to JSON inside the V8 isolate and deserialized
        using `json_impl`.

        Args:
            expr: JavaScript expression referring to a function
            encoder: Custom JSON encoder
            timeout: number of milliseconds after which the execution is
                interrupted.
            timeout_sec: number of seconds after which the execution is interrupted
            max_memory: hard memory limit, in bytes, after which the execution is
                interrupted
        """

        if timeout:
            # PyMiniRacer unfortunately uses milliseconds while Python and
            # Système international d'unités use seconds.
            timeout_sec = timeout / 1000

        json_args = self.json_impl.dumps(args, separators=(",", ":"), cls=encoder)
        js = f"{expr}.apply(this, {json_args})"
        return self.execute(js, timeout_sec=timeout_sec, max_memory=max_memory)

    @asynccontextmanager
    async def wrap_py_function(
        self, func: PyJsFunctionType
    ) -> AsyncGenerator[JSFunction, None]:
        """Wrap a Python function such that it can be called from JS.

        To be wrapped and exposed in JavaScript, a Python function should:

          1. Be async,
          2. Accept variable positional arguments each of type PythonJSConvertedTypes,
             and
          3. Return one value of type PythonJSConvertedTypes (a type union which
             includes None).

        The function is rendered on the JavaScript side as an async function (i.e., a
        function which returns a Promise).

        Returns:
            An async context manager which, when entered, yields a JS Function which
            can be passed into MiniRacer and called by JS code.
        """

        assert self._ctx is not None

        async with self._ctx.wrap_py_function_as_js_function(func) as js_func:
            yield js_func

    def set_hard_memory_limit(self, limit: int) -> None:
        """Set a hard memory limit on this V8 isolate.

        JavaScript execution will be terminated when this limit is reached.

        :param int limit: memory limit in bytes or 0 to reset the limit
        """

        assert self._ctx is not None
        self._ctx.set_hard_memory_limit(limit)

    def set_soft_memory_limit(self, limit: int) -> None:
        """Set a soft memory limit on this V8 isolate.

        The Garbage Collection will use a more aggressive strategy when
        the soft limit is reached but the execution will not be stopped.

        :param int limit: memory limit in bytes or 0 to reset the limit
        """

        assert self._ctx is not None
        self._ctx.set_soft_memory_limit(limit)

    def was_hard_memory_limit_reached(self) -> bool:
        """Return true if the hard memory limit was reached on the V8 isolate."""

        assert self._ctx is not None
        return self._ctx.was_hard_memory_limit_reached()

    def was_soft_memory_limit_reached(self) -> bool:
        """Return true if the soft memory limit was reached on the V8 isolate."""

        assert self._ctx is not None
        return self._ctx.was_soft_memory_limit_reached()

    def low_memory_notification(self) -> None:
        """Ask the V8 isolate to collect memory more aggressively."""

        assert self._ctx is not None
        self._ctx.low_memory_notification()

    def heap_stats(self) -> Any:  # noqa: ANN401
        """Return the V8 isolate heap statistics."""

        assert self._ctx is not None
        return self.json_impl.loads(self._ctx.heap_stats())

    def heap_snapshot(self) -> Any:  # noqa: ANN401
        """Return a snapshot of the V8 isolate heap."""

        assert self._ctx is not None
        return self.json_impl.loads(self._ctx.heap_snapshot())


@contextmanager
def _running_event_loop(
    event_loop: asyncio.AbstractEventLoop | None = None,
) -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Pick an asyncio loop. In descending order of precedence:

    1. The caller-specified one,
    2. The running one (defined if we're being called from async context), or
    3. One we create and launch a thread for, on the spot.
    """

    event_loop = event_loop or get_running_loop_or_none()

    if event_loop is not None:
        yield event_loop
        return

    event_loop = asyncio.new_event_loop()

    def run_event_loop() -> None:
        asyncio.set_event_loop(event_loop)
        assert event_loop is not None
        event_loop.run_forever()
        event_loop.close()

    event_loop_thread = Thread(target=run_event_loop, daemon=True)
    event_loop_thread.start()

    try:
        yield event_loop
    finally:
        event_loop.call_soon_threadsafe(event_loop.stop)
        event_loop_thread.join()


@contextmanager
def _make_context(
    event_loop: asyncio.AbstractEventLoop | None = None,
) -> Generator[Context, None, None]:
    dll = init_mini_racer(ignore_duplicate_init=True)

    context: Context

    # define an all-purpose callback:
    @mr_callback_func
    def mr_callback(callback_id: int, raw_val_handle: RawValueHandleType) -> None:
        nonlocal context
        context.handle_callback_from_v8(callback_id, raw_val_handle)

    next_cancelable_task_callback_id = count()
    # reserve 0 as the callback for tasks we don't bother canceling; see
    # _UNCANCELABLE_TASK_CALLBACK_ID:
    _ = next(next_cancelable_task_callback_id)

    ctx = ContextType(dll.mr_init_context(mr_callback))
    try:
        with _running_event_loop(event_loop) as loop:
            context = Context(
                dll, ctx, loop, ObjectFactoryImpl(), next_cancelable_task_callback_id
            )
            yield context
    finally:
        dll.mr_free_context(ctx)


@contextmanager
def mini_racer(
    event_loop: asyncio.AbstractEventLoop | None = None,
) -> Generator[MiniRacer, None]:
    with _make_context(event_loop) as ctx:
        yield MiniRacer(ctx)


# Compatibility with versions 0.4 & 0.5
StrictMiniRacer = MiniRacer
