from __future__ import annotations

import asyncio
import json
from concurrent.futures import TimeoutError as SyncTimeoutError
from contextlib import AbstractContextManager, asynccontextmanager, contextmanager
from dataclasses import dataclass
from json import JSONEncoder
from threading import Thread
from typing import TYPE_CHECKING, Any, ClassVar, TypeVar

from py_mini_racer._context import Context, context
from py_mini_racer._exc import JSTimeoutException, MiniRacerBaseException
from py_mini_racer._set_timeout import INSTALL_SET_TIMEOUT

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Coroutine, Generator
    from types import TracebackType

    from typing_extensions import Self

    from py_mini_racer._types import (
        AsyncJSFunction,
        PyJsFunctionType,
        PythonJSConvertedTypes,
    )


class WrongReturnTypeException(MiniRacerBaseException):
    """Invalid type returned by the JavaScript runtime."""

    def __init__(self, typ: type) -> None:
        super().__init__(f"Unexpected return value type {typ}")


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

    def __init__(self) -> None:
        self._state_context_manager: (
            AbstractContextManager[_SyncMiniRacerState] | None
        ) = _sync_mini_racer_state()
        self._state: _SyncMiniRacerState | None = (
            self._state_context_manager.__enter__()
        )

    def close(self) -> None:
        """Close this MiniRacer instance.

        It is an error to use this MiniRacer instance or any JS objects returned by it
        after calling this method.
        """
        state_context_manager, self._state_context_manager = (
            self._state_context_manager,
            None,
        )
        if state_context_manager is not None:
            state_context_manager.__exit__(None, None, None)
            self._state = None

    def __del__(self) -> None:
        self.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        assert self._state_context_manager is not None
        self._state_context_manager.__exit__(exc_type, exc_val, exc_tb)
        self._state = self._state_context_manager = None

    @property
    def v8_version(self) -> str:
        """Return the V8 version string."""
        assert self._state is not None
        return self._state.ctx.v8_version()

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

        assert self._state is not None
        state = self._state

        async def run() -> PythonJSConvertedTypes:
            assert state is not None
            try:
                return await asyncio.wait_for(
                    state.ctx.evaluate(code=code), timeout=timeout_sec
                )
            except SyncTimeoutError as e:
                raise JSTimeoutException from e

        return state.run_coro(run())

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

    def set_hard_memory_limit(self, limit: int) -> None:
        """Set a hard memory limit on this V8 isolate.

        JavaScript execution will be terminated when this limit is reached.

        :param int limit: memory limit in bytes or 0 to reset the limit
        """

        assert self._state is not None
        self._state.ctx.set_hard_memory_limit(limit)

    def set_soft_memory_limit(self, limit: int) -> None:
        """Set a soft memory limit on this V8 isolate.

        The Garbage Collection will use a more aggressive strategy when
        the soft limit is reached but the execution will not be stopped.

        :param int limit: memory limit in bytes or 0 to reset the limit
        """

        assert self._state is not None
        self._state.ctx.set_soft_memory_limit(limit)

    def was_hard_memory_limit_reached(self) -> bool:
        """Return true if the hard memory limit was reached on the V8 isolate."""

        assert self._state is not None
        return self._state.ctx.was_hard_memory_limit_reached()

    def was_soft_memory_limit_reached(self) -> bool:
        """Return true if the soft memory limit was reached on the V8 isolate."""

        assert self._state is not None
        return self._state.ctx.was_soft_memory_limit_reached()

    def low_memory_notification(self) -> None:
        """Ask the V8 isolate to collect memory more aggressively."""

        assert self._state is not None
        self._state.ctx.low_memory_notification()

    def heap_stats(self) -> Any:  # noqa: ANN401
        """Return the V8 isolate heap statistics."""

        assert self._state is not None
        return self.json_impl.loads(self._state.run_coro(self._state.ctx.heap_stats()))


T = TypeVar("T")


@dataclass(frozen=True)
class _SyncMiniRacerState:
    event_loop: asyncio.AbstractEventLoop
    ctx: Context

    def run_coro(self, coro: Coroutine[Any, Any, T]) -> T:
        return asyncio.run_coroutine_threadsafe(coro, self.event_loop).result()


@contextmanager
def _sync_mini_racer_state() -> Generator[_SyncMiniRacerState, None, None]:
    with (
        _running_event_loop() as event_loop,
        context(event_loop, prefer_async_objects=False) as ctx,
    ):
        state = _SyncMiniRacerState(event_loop, ctx)
        state.run_coro(ctx.evaluate(INSTALL_SET_TIMEOUT))
        yield state


@dataclass(frozen=True)
class AsyncMiniRacer:
    """
    AsyncMiniRacer evaluates JavaScript code using a V8 isolate, using Python async
    semantics.

    An AsyncMiniRacer instance must be created as an async context manager:

    async with async_mini_racer() as mr:
        ...

    AsyncMiniRacer will run tasks and coroutines in the currently-running asyncio event
    loop.
    """

    _ctx: Context

    @property
    def v8_version(self) -> str:
        """Return the V8 version string."""
        return self._ctx.v8_version()

    async def eval(self, code: str) -> PythonJSConvertedTypes:
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
        """

        return await self._ctx.evaluate(code=code)

    @asynccontextmanager
    async def wrap_py_function(
        self, func: PyJsFunctionType
    ) -> AsyncGenerator[AsyncJSFunction, None]:
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

        async with self._ctx.wrap_py_function_as_js_function(func) as js_func:
            yield js_func

    def set_hard_memory_limit(self, limit: int) -> None:
        """Set a hard memory limit on this V8 isolate.

        JavaScript execution will be terminated when this limit is reached.

        :param int limit: memory limit in bytes or 0 to reset the limit
        """
        self._ctx.set_hard_memory_limit(limit)

    def set_soft_memory_limit(self, limit: int) -> None:
        """Set a soft memory limit on this V8 isolate.

        The Garbage Collection will use a more aggressive strategy when
        the soft limit is reached but the execution will not be stopped.

        :param int limit: memory limit in bytes or 0 to reset the limit
        """
        self._ctx.set_soft_memory_limit(limit)

    def was_hard_memory_limit_reached(self) -> bool:
        """Return true if the hard memory limit was reached on the V8 isolate."""
        return self._ctx.was_hard_memory_limit_reached()

    def was_soft_memory_limit_reached(self) -> bool:
        """Return true if the soft memory limit was reached on the V8 isolate."""
        return self._ctx.was_soft_memory_limit_reached()

    def low_memory_notification(self) -> None:
        """Ask the V8 isolate to collect memory more aggressively."""
        self._ctx.low_memory_notification()

    async def heap_stats(self) -> Any:  # noqa: ANN401
        """Return the V8 isolate heap statistics."""

        return json.loads(await self._ctx.heap_stats())


@asynccontextmanager
async def async_mini_racer() -> AsyncGenerator[AsyncMiniRacer, None]:
    with context(asyncio.get_running_loop(), prefer_async_objects=True) as ctx:
        mr = AsyncMiniRacer(ctx)
        await mr.eval(INSTALL_SET_TIMEOUT)
        yield mr


@contextmanager
def _running_event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    event_loop = asyncio.new_event_loop()

    def run_event_loop() -> None:
        asyncio.set_event_loop(event_loop)
        assert event_loop is not None
        event_loop.run_forever()

    event_loop_thread = Thread(target=run_event_loop, daemon=True)
    event_loop_thread.start()

    try:
        yield event_loop
    finally:
        event_loop.call_soon_threadsafe(event_loop.stop)
        event_loop_thread.join()


# Compatibility with versions 0.4 & 0.5
StrictMiniRacer = MiniRacer
