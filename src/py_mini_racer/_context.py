from __future__ import annotations

import asyncio
import queue
from contextlib import asynccontextmanager, contextmanager, suppress
from dataclasses import dataclass, field
from traceback import format_exc
from typing import TYPE_CHECKING, Any, NewType, Protocol, cast

from py_mini_racer._dll import init_mini_racer
from py_mini_racer._exc import JSEvalException, JSPromiseError
from py_mini_racer._types import (
    CancelableJSFunction,
    JSArray,
    JSFunction,
    JSMappedObject,
    JSObject,
    JSPromise,
    JSUndefined,
    JSUndefinedType,
    PyJsFunctionType,
    PythonJSConvertedTypes,
)
from py_mini_racer._value_handle import ValueHandle

if TYPE_CHECKING:
    import ctypes
    from collections.abc import AsyncGenerator, Callable, Coroutine, Generator, Iterator

    from py_mini_racer._value_handle import RawValueHandleType


def context_count() -> int:
    """For tests only: how many context handles are still allocated?"""

    dll = init_mini_racer(ignore_duplicate_init=True)
    return int(dll.mr_context_count())


ContextType = NewType("ContextType", object)
_UNCANCELABLE_TASK_CALLBACK_ID = 0


@dataclass(frozen=True)
class _TaskSet:
    """This is a very very simplistic standin for Python 3.11+ TaskGroups (whereas we
    are still targeting Python 3.10)."""

    _event_loop: asyncio.AbstractEventLoop
    _ongoing_tasks: set[asyncio.Task[PythonJSConvertedTypes]]

    def start_task(self, coro: Coroutine[Any, Any, None]) -> None:
        task = self._event_loop.create_task(coro)
        self._ongoing_tasks.add(task)
        task.add_done_callback(self._ongoing_tasks.discard)


@asynccontextmanager
async def _make_task_set(
    event_loop: asyncio.AbstractEventLoop,
) -> AsyncGenerator[_TaskSet, None]:
    ongoing_tasks: set[asyncio.Task[PythonJSConvertedTypes]] = set()

    try:
        yield _TaskSet(event_loop, ongoing_tasks)
    finally:
        for t in list(ongoing_tasks):
            with suppress(asyncio.CancelledError):
                t.cancel()
                await t


class ObjectFactory(Protocol):
    def value_handle_to_python(
        self, ctx: Context, val_handle: ValueHandle
    ) -> PythonJSConvertedTypes: ...

    def python_to_value_handle(
        self, ctx: Context, obj: PythonJSConvertedTypes
    ) -> ValueHandle: ...


def get_running_loop_or_none() -> asyncio.AbstractEventLoop | None:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


@dataclass(frozen=True)
class Context:
    """Wrapper for all operations involving the DLL and C++ MiniRacer::Context."""

    _dll: ctypes.CDLL
    _ctx: ContextType
    event_loop: asyncio.AbstractEventLoop
    _object_factory: ObjectFactory
    _next_async_callback_id: Iterator[int]
    _active_cancelable_mr_task_callbacks: dict[int, Callable[[ValueHandle], None]] = (
        field(default_factory=dict)
    )
    _non_cancelable_mr_task_results_queue: queue.Queue[ValueHandle] = field(
        default_factory=queue.Queue
    )

    def v8_version(self) -> str:
        return str(self._dll.mr_v8_version().decode("utf-8"))

    def v8_is_using_sandbox(self) -> bool:
        """Checks for enablement of the V8 Sandbox. See https://v8.dev/blog/sandbox."""

        return bool(self._dll.mr_v8_is_using_sandbox())

    def handle_callback_from_v8(
        self, callback_id: int, raw_val_handle: RawValueHandleType
    ) -> None:
        # Handle a callback from within the v8::Isolate.
        # All work on the Isolate is blocked until this callback returns. That may
        # may in turn be blocking incoming calls from Python, including other threads,
        # asyncio event loops, etc. So we need to get out fast!
        # We limit ourselves to wrapping the incoming handle (so we don't leak memory)
        # and enqueing the incoming work for decoupled processing.

        val_handle = self._wrap_raw_handle(raw_val_handle)

        if callback_id == _UNCANCELABLE_TASK_CALLBACK_ID:
            self._non_cancelable_mr_task_results_queue.put(val_handle)
        else:
            self.event_loop.call_soon_threadsafe(
                self._handle_callback_from_v8_on_event_loop, callback_id, val_handle
            )

    def _handle_callback_from_v8_on_event_loop(
        self, callback_id: int, val_handle: ValueHandle
    ) -> None:
        try:
            callback = self._active_cancelable_mr_task_callbacks[callback_id]
        except KeyError:
            # Assume this callback was intentionally cancelled:
            return

        callback(val_handle)

    @contextmanager
    def _register_cancelable_mr_task_callback(
        self, func: Callable[[ValueHandle], None]
    ) -> Generator[int, None, None]:
        callback_id = next(self._next_async_callback_id)

        self._active_cancelable_mr_task_callbacks[callback_id] = func

        try:
            yield callback_id
        finally:
            self._active_cancelable_mr_task_callbacks.pop(callback_id)

    async def eval_cancelable(self, code: str) -> PythonJSConvertedTypes:
        code_handle = self._python_to_value_handle(code)

        return await self._run_cancelable_mr_task(self._dll.mr_eval, code_handle.raw)

    def eval(self, code: str) -> PythonJSConvertedTypes:
        code_handle = self._python_to_value_handle(code)

        return self._run_uncancelable_mr_task(self._dll.mr_eval, code_handle.raw)

    async def await_promise(self, promise: JSPromise) -> PythonJSConvertedTypes:
        promise_handle = self._python_to_value_handle(promise)
        then_name_handle = self._python_to_value_handle("then")

        then_func = cast(
            "JSFunction",
            self._value_handle_to_python(
                self._wrap_raw_handle(
                    self._dll.mr_get_object_item(
                        self._ctx, promise_handle.raw, then_name_handle.raw
                    )
                )
            ),
        )

        future: asyncio.Future[PythonJSConvertedTypes] = self.event_loop.create_future()

        def on_resolved(val_handle: ValueHandle) -> None:
            if future.cancelled():
                return

            future.set_result(
                cast("JSArray", self._value_handle_to_python(val_handle))[0]
            )

        def on_rejected(val_handle: ValueHandle) -> None:
            if future.cancelled():
                return

            value = cast("JSArray", self._value_handle_to_python(val_handle))[0]
            if not isinstance(value, JSMappedObject):
                msg = str(value)
            elif "stack" in value:
                msg = cast("str", value["stack"])
            else:
                msg = str(value)

            future.set_exception(JSPromiseError(msg))

        with (
            self._register_js_notification(on_resolved) as on_resolved_js_func,
            self._register_js_notification(on_rejected) as on_rejected_js_func,
        ):
            then_func(on_resolved_js_func, on_rejected_js_func, this=promise)

            return await future

    def get_identity_hash(self, obj: JSObject) -> int:
        obj_handle = self._python_to_value_handle(obj)

        return cast(
            "int",
            self._value_handle_to_python(
                self._wrap_raw_handle(
                    self._dll.mr_get_identity_hash(self._ctx, obj_handle.raw)
                )
            ),
        )

    def get_own_property_names(
        self, obj: JSObject
    ) -> tuple[PythonJSConvertedTypes, ...]:
        obj_handle = self._python_to_value_handle(obj)

        names = self._value_handle_to_python(
            self._wrap_raw_handle(
                self._dll.mr_get_own_property_names(self._ctx, obj_handle.raw)
            )
        )
        if not isinstance(names, JSArray):
            raise TypeError
        return tuple(names)

    def get_object_item(
        self, obj: JSObject, key: PythonJSConvertedTypes
    ) -> PythonJSConvertedTypes:
        obj_handle = self._python_to_value_handle(obj)
        key_handle = self._python_to_value_handle(key)

        return self._value_handle_to_python(
            self._wrap_raw_handle(
                self._dll.mr_get_object_item(self._ctx, obj_handle.raw, key_handle.raw)
            )
        )

    def set_object_item(
        self, obj: JSObject, key: PythonJSConvertedTypes, val: PythonJSConvertedTypes
    ) -> None:
        obj_handle = self._python_to_value_handle(obj)
        key_handle = self._python_to_value_handle(key)
        val_handle = self._python_to_value_handle(val)

        # Convert the value just to convert any exceptions (and GC the result)
        self._value_handle_to_python(
            self._wrap_raw_handle(
                self._dll.mr_set_object_item(
                    self._ctx, obj_handle.raw, key_handle.raw, val_handle.raw
                )
            )
        )

    def del_object_item(self, obj: JSObject, key: PythonJSConvertedTypes) -> None:
        obj_handle = self._python_to_value_handle(obj)
        key_handle = self._python_to_value_handle(key)

        # Convert the value just to convert any exceptions (and GC the result)
        self._value_handle_to_python(
            self._wrap_raw_handle(
                self._dll.mr_del_object_item(self._ctx, obj_handle.raw, key_handle.raw)
            )
        )

    def del_from_array(self, arr: JSArray, index: int) -> None:
        arr_handle = self._python_to_value_handle(arr)

        # Convert the value just to convert any exceptions (and GC the result)
        self._value_handle_to_python(
            self._wrap_raw_handle(
                self._dll.mr_splice_array(self._ctx, arr_handle.raw, index, 1, None)
            )
        )

    def array_insert(
        self, arr: JSArray, index: int, new_val: PythonJSConvertedTypes
    ) -> None:
        arr_handle = self._python_to_value_handle(arr)
        new_val_handle = self._python_to_value_handle(new_val)

        # Convert the value just to convert any exceptions (and GC the result)
        self._value_handle_to_python(
            self._wrap_raw_handle(
                self._dll.mr_splice_array(
                    self._ctx, arr_handle.raw, index, 0, new_val_handle.raw
                )
            )
        )

    def array_push(self, arr: JSArray, new_val: PythonJSConvertedTypes) -> None:
        arr_handle = self._python_to_value_handle(arr)
        new_val_handle = self._python_to_value_handle(new_val)

        # Convert the value just to convert any exceptions (and GC the result)
        self._value_handle_to_python(
            self._wrap_raw_handle(
                self._dll.mr_array_push(self._ctx, arr_handle.raw, new_val_handle.raw)
            )
        )

    def are_we_running_on_the_mini_racer_event_loop(self) -> bool:
        return get_running_loop_or_none() is self.event_loop

    async def call_function_cancelable(
        self,
        func: CancelableJSFunction | JSFunction,
        *args: PythonJSConvertedTypes,
        this: JSObject | JSUndefinedType = JSUndefined,
    ) -> PythonJSConvertedTypes:
        argv = cast("JSArray", self.eval("[]"))
        for arg in args:
            argv.append(arg)

        func_handle = self._python_to_value_handle(func)
        this_handle = self._python_to_value_handle(this)
        argv_handle = self._python_to_value_handle(argv)

        return await self._run_cancelable_mr_task(
            self._dll.mr_call_function,
            func_handle.raw,
            this_handle.raw,
            argv_handle.raw,
        )

    def call_function(
        self,
        func: JSFunction,
        *args: PythonJSConvertedTypes,
        this: JSObject | JSUndefinedType = JSUndefined,
    ) -> PythonJSConvertedTypes:
        argv = cast("JSArray", self.eval("[]"))
        for arg in args:
            argv.append(arg)

        func_handle = self._python_to_value_handle(func)
        this_handle = self._python_to_value_handle(this)
        argv_handle = self._python_to_value_handle(argv)

        return self._run_uncancelable_mr_task(
            self._dll.mr_call_function,
            func_handle.raw,
            this_handle.raw,
            argv_handle.raw,
        )

    def set_hard_memory_limit(self, limit: int) -> None:
        self._dll.mr_set_hard_memory_limit(self._ctx, limit)

    def set_soft_memory_limit(self, limit: int) -> None:
        self._dll.mr_set_soft_memory_limit(self._ctx, limit)

    def was_hard_memory_limit_reached(self) -> bool:
        return bool(self._dll.mr_hard_memory_limit_reached(self._ctx))

    def was_soft_memory_limit_reached(self) -> bool:
        return bool(self._dll.mr_soft_memory_limit_reached(self._ctx))

    def low_memory_notification(self) -> None:
        self._dll.mr_low_memory_notification(self._ctx)

    def heap_stats(self) -> str:
        return cast(
            "str",
            self._value_handle_to_python(
                self._wrap_raw_handle(self._dll.mr_heap_stats(self._ctx))
            ),
        )

    def heap_snapshot(self) -> str:
        """Return a snapshot of the V8 isolate heap."""

        return cast(
            "str",
            self._value_handle_to_python(
                self._wrap_raw_handle(self._dll.mr_heap_snapshot(self._ctx))
            ),
        )

    def value_count(self) -> int:
        """For tests only: how many value handles are still allocated?"""

        return int(self._dll.mr_value_count(self._ctx))

    @contextmanager
    def _register_js_notification(
        self, func: Callable[[ValueHandle], None]
    ) -> Generator[JSFunction, None, None]:
        """Create a "notification": an async, one-way callback function, from JavaScript
        to Python.

        "One-way" here means the function returns nothing. "async" means that on the JS
        side, the function returns before it has been processed on the Python side."""

        with self._register_cancelable_mr_task_callback(func) as callback_id:
            yield cast(
                "JSFunction",
                self._value_handle_to_python(
                    self._wrap_raw_handle(
                        self._dll.mr_make_js_callback(self._ctx, callback_id)
                    )
                ),
            )

    @asynccontextmanager
    async def wrap_py_function_as_js_function(
        self, func: PyJsFunctionType
    ) -> AsyncGenerator[JSFunction, None]:
        async def await_into_js_promise_resolvers(val_handle: ValueHandle) -> None:
            params = self._value_handle_to_python(val_handle)
            arguments, resolve, reject = cast("JSArray", params)
            try:
                result = await func(*cast("JSArray", arguments))
                cast("JSFunction", resolve)(result)
            except Exception:  # noqa: BLE001
                # Convert this Python exception into a JS exception so we can send
                # it into JS:
                err_maker = cast("JSFunction", self.eval("s => new Error(s)"))
                cast("JSFunction", reject)(
                    err_maker(f"Error running Python function:\n{format_exc()}")
                )

        async with _make_task_set(self.event_loop) as task_set:
            with self._register_js_notification(
                lambda val_handle: task_set.start_task(
                    await_into_js_promise_resolvers(val_handle)
                )
            ) as js_to_py_notification:
                # Every time our callback is called from JS, on the JS side we
                # instantiate a JS Promise and immediately pass its resolution functions
                # into our Python callback function. While we wait on Python's asyncio
                # loop to process this call, we can return the Promise to the JS caller,
                # thus exposing what looks like an ordinary async function on the JS
                # side of things.
                wrap_outbound_calls_with_js_promises = cast(
                    "JSFunction",
                    self.eval(
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
                    "JSFunction",
                    wrap_outbound_calls_with_js_promises(js_to_py_notification),
                )

    def _wrap_raw_handle(self, raw: RawValueHandleType) -> ValueHandle:
        return ValueHandle(lambda: self._free(raw), raw)

    def create_intish_val(self, val: int, typ: int) -> ValueHandle:
        return self._wrap_raw_handle(self._dll.mr_alloc_int_val(self._ctx, val, typ))

    def create_doublish_val(self, val: float, typ: int) -> ValueHandle:
        return self._wrap_raw_handle(self._dll.mr_alloc_double_val(self._ctx, val, typ))

    def create_string_val(self, val: str, typ: int) -> ValueHandle:
        b = val.encode("utf-8")
        return self._wrap_raw_handle(
            self._dll.mr_alloc_string_val(self._ctx, b, len(b), typ)
        )

    def _free(self, raw: RawValueHandleType) -> None:
        self._dll.mr_free_value(self._ctx, raw)

    async def _run_cancelable_mr_task(
        self,
        dll_method: Any,  # noqa: ANN401
        *args: Any,  # noqa: ANN401
    ) -> PythonJSConvertedTypes:
        """Manages cancelable tasks within the MiniRacer DLL.

        Several MiniRacer functions (JS evaluation and 2 heap stats calls) are
        cancelable and asynchronous. They take a function callback and callback data
        parameter, and they return a task handle.

        In this method, we create a future for each callback to get the right data to
        the right caller, and we manage the lifecycle of the task and task handle.
        """

        future: asyncio.Future[PythonJSConvertedTypes] = asyncio.Future()

        def callback(val_handle: ValueHandle) -> None:
            if future.cancelled():
                return

            try:
                value = self._value_handle_to_python(val_handle)
            except JSEvalException as e:
                future.set_exception(e)
                return

            future.set_result(value)

        with self._register_cancelable_mr_task_callback(callback) as callback_id:
            # Start the task:
            task_id = dll_method(self._ctx, *args, callback_id)
            try:
                return await future
            finally:
                # Cancel the task if it's not already done (this call is ignored if it's
                # already done)
                self._dll.mr_cancel_task(self._ctx, task_id)

    def _run_uncancelable_mr_task(
        self,
        dll_method: Any,  # noqa: ANN401
        *args: Any,  # noqa: ANN401
    ) -> PythonJSConvertedTypes:
        """Like _run_cancelable_mr_task, but eschewing cancellation semantics and
        instead just waiting on a result synchronously."""

        # self._non_cancelable_mr_task_results_queue is single file, with no
        # higher-level ordering mechanism, so it's important that we use it only from
        # the event loop thread, to keep things in order:
        assert self.are_we_running_on_the_mini_racer_event_loop()

        _task_id = dll_method(self._ctx, *args, _UNCANCELABLE_TASK_CALLBACK_ID)
        val_handle = self._non_cancelable_mr_task_results_queue.get()
        return self._value_handle_to_python(val_handle)

    def _value_handle_to_python(
        self, val_handle: ValueHandle
    ) -> PythonJSConvertedTypes:
        return self._object_factory.value_handle_to_python(self, val_handle)

    def _python_to_value_handle(self, obj: PythonJSConvertedTypes) -> ValueHandle:
        return self._object_factory.python_to_value_handle(self, obj)
