from __future__ import annotations

import asyncio
import ctypes
from concurrent.futures import TimeoutError as SyncTimeoutError
from contextlib import asynccontextmanager, contextmanager, suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone
from itertools import count
from traceback import format_exc
from typing import TYPE_CHECKING, Any, ClassVar, NewType, TypeVar, cast

from py_mini_racer._dll import init_mini_racer, mr_callback_func
from py_mini_racer._exc import (
    JSConversionException,
    JSEvalException,
    JSKeyError,
    JSOOMException,
    JSParseException,
    JSPromiseError,
    JSTerminatedException,
    JSTimeoutException,
    JSValueError,
)
from py_mini_racer._js_value_manipulator import JSValueManipulator
from py_mini_racer._objects import (
    AsyncJSFunctionImpl,
    AsyncJSPromiseImpl,
    JSArrayImpl,
    JSFunctionImpl,
    JSMappedObjectImpl,
    JSObjectImpl,
    JSPromiseImpl,
    JSSymbolImpl,
)
from py_mini_racer._types import (
    AsyncJSFunction,
    AsyncJSPromise,
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
    from collections.abc import (
        AsyncGenerator,
        Callable,
        Coroutine,
        Generator,
        Iterator,
        Sequence,
    )

    from py_mini_racer._dll import RawValueHandleTypeImpl
    from py_mini_racer._value_handle import RawValueHandleType


def context_count() -> int:
    """For tests only: how many context handles are still allocated?"""

    dll = init_mini_racer(ignore_duplicate_init=True)
    return int(dll.mr_context_count())


class _ArrayBufferByte(ctypes.Structure):
    # Cannot use c_ubyte directly because it uses <B
    # as an internal type but we need B for memoryview.
    _fields_: ClassVar[Sequence[tuple[str, type]]] = [("b", ctypes.c_ubyte)]
    _pack_ = 1


class _MiniRacerTypes:
    """MiniRacer types identifier

    Note: it needs to be coherent with mini_racer.cc.
    """

    invalid = 0
    null = 1
    bool = 2
    integer = 3
    double = 4
    str_utf8 = 5
    array = 6
    # deprecated:
    hash = 7
    date = 8
    symbol = 9
    object = 10
    undefined = 11

    function = 100
    shared_array_buffer = 101
    array_buffer = 102
    promise = 103

    execute_exception = 200
    parse_exception = 201
    oom_exception = 202
    timeout_exception = 203
    terminated_exception = 204
    value_exception = 205
    key_exception = 206


_ERRORS: dict[int, tuple[type[JSEvalException], str]] = {
    _MiniRacerTypes.parse_exception: (
        JSParseException,
        "Unknown JavaScript error during parse",
    ),
    _MiniRacerTypes.execute_exception: (
        JSEvalException,
        "Uknown JavaScript error during execution",
    ),
    _MiniRacerTypes.oom_exception: (JSOOMException, "JavaScript memory limit reached"),
    _MiniRacerTypes.terminated_exception: (
        JSTerminatedException,
        "JavaScript was terminated",
    ),
    _MiniRacerTypes.key_exception: (JSKeyError, "No such key found in object"),
    _MiniRacerTypes.value_exception: (
        JSValueError,
        "Bad value passed to JavaScript engine",
    ),
}


_ContextType = NewType("_ContextType", object)


@contextmanager
def context(
    event_loop: asyncio.AbstractEventLoop, *, prefer_async_objects: bool
) -> Generator[Context, None, None]:
    dll = init_mini_racer(ignore_duplicate_init=True)

    context: Context

    # define an all-purpose callback:
    @mr_callback_func
    def mr_callback(callback_id: int, raw_val_handle: RawValueHandleType) -> None:
        nonlocal context
        context.handle_callback_from_v8(callback_id, raw_val_handle)

    ctx = _ContextType(dll.mr_init_context(mr_callback))
    try:
        context = Context(dll, ctx, event_loop, prefer_async_objects)
        yield context
    finally:
        dll.mr_free_context(ctx)


T = TypeVar("T")


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


@dataclass(frozen=True)
class Context(JSValueManipulator):
    """Wrapper for all operations involving the DLL and C++ MiniRacer::Context."""

    _dll: ctypes.CDLL
    _ctx: _ContextType
    _event_loop: asyncio.AbstractEventLoop
    _prefer_async_objects: bool
    _active_callbacks: dict[int, Callable[[ValueHandle], None]] = field(
        default_factory=dict
    )
    _next_callback_id: Iterator[int] = field(default_factory=count)

    def v8_version(self) -> str:
        return str(self._dll.mr_v8_version().decode("utf-8"))

    def v8_is_using_sandbox(self) -> bool:
        """Checks for enablement of the V8 Sandbox. See https://v8.dev/blog/sandbox."""

        return bool(self._dll.mr_v8_is_using_sandbox())

    def handle_callback_from_v8(
        self, callback_id: int, raw_val_handle: RawValueHandleType
    ) -> None:
        self._event_loop.call_soon_threadsafe(
            self._handle_callback_from_v8_on_event_loop,
            callback_id,
            self._wrap_raw_handle(raw_val_handle),
        )

    def _handle_callback_from_v8_on_event_loop(
        self, callback_id: int, val_handle: ValueHandle
    ) -> None:
        try:
            callback = self._active_callbacks[callback_id]
        except KeyError:
            # Assume this callback was intentionally cancelled:
            return

        callback(val_handle)

    @contextmanager
    def _register_callback(
        self, func: Callable[[ValueHandle], None]
    ) -> Generator[int, None, None]:
        callback_id = next(self._next_callback_id)

        self._active_callbacks[callback_id] = func

        try:
            yield callback_id
        finally:
            self._active_callbacks.pop(callback_id)

    async def evaluate(self, code: str) -> PythonJSConvertedTypes:
        code_handle = self._python_to_value_handle(code)

        return await self._run_mr_task(self._dll.mr_eval, code_handle.raw)

    def sync_await_promise(
        self, promise: JSPromise, timeout: float | None = None
    ) -> PythonJSConvertedTypes:
        async def run() -> PythonJSConvertedTypes:
            return await asyncio.wait_for(self._await_promise(promise), timeout=timeout)

        return self._run_coro_on_event_loop(run())

    async def async_await_promise(
        self, promise: AsyncJSPromise
    ) -> PythonJSConvertedTypes:
        return await self._await_promise(promise)

    async def _await_promise(
        self, promise: AsyncJSPromise | JSPromise
    ) -> PythonJSConvertedTypes:
        promise_handle = self._python_to_value_handle(promise)
        then_name_handle = self._python_to_value_handle("then")

        then_func = cast(
            "AsyncJSFunction",
            self._value_handle_to_python(
                self._wrap_raw_handle(
                    self._dll.mr_get_object_item(
                        self._ctx, promise_handle.raw, then_name_handle.raw
                    )
                ),
                prefer_async_objects=True,
            ),
        )

        future: asyncio.Future[PythonJSConvertedTypes] = (
            self._event_loop.create_future()
        )

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
            await then_func(on_resolved_js_func, on_rejected_js_func, this=promise)

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

    def sync_call_function(
        self,
        func: JSFunction,
        *args: PythonJSConvertedTypes,
        this: JSObject | JSUndefinedType = JSUndefined,
        timeout_sec: float | None = None,
    ) -> PythonJSConvertedTypes:
        async def run() -> PythonJSConvertedTypes:
            try:
                return await asyncio.wait_for(
                    self._call_function(func, *args, this=this), timeout=timeout_sec
                )
            except SyncTimeoutError as e:
                raise JSTimeoutException from e

        return self._run_coro_on_event_loop(run())

    def _run_coro_on_event_loop(self, coro: Coroutine[Any, Any, T]) -> T:
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            assert running_loop is not self._event_loop, (
                "Cannot run a synchronous operation from our own event loop"
            )

        return asyncio.run_coroutine_threadsafe(coro, self._event_loop).result()

    async def async_call_function(
        self,
        func: AsyncJSFunction,
        *args: PythonJSConvertedTypes,
        this: JSObject | JSUndefinedType = JSUndefined,
    ) -> PythonJSConvertedTypes:
        return await self._call_function(func, *args, this=this)

    async def _call_function(
        self,
        func: AsyncJSFunction | JSFunction,
        *args: PythonJSConvertedTypes,
        this: JSObject | JSUndefinedType = JSUndefined,
    ) -> PythonJSConvertedTypes:
        argv = cast("JSArray", await self.evaluate("[]"))
        for arg in args:
            argv.append(arg)

        func_handle = self._python_to_value_handle(func)
        this_handle = self._python_to_value_handle(this)
        argv_handle = self._python_to_value_handle(argv)

        return await self._run_mr_task(
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

    async def heap_stats(self) -> str:
        return cast("str", await self._run_mr_task(self._dll.mr_heap_stats))

    async def heap_snapshot(self) -> str:
        """Return a snapshot of the V8 isolate heap."""

        return cast("str", await self._run_mr_task(self._dll.mr_heap_snapshot))

    def value_count(self) -> int:
        """For tests only: how many value handles are still allocated?"""

        return int(self._dll.mr_value_count(self._ctx))

    @contextmanager
    def _register_js_notification(
        self, func: Callable[[ValueHandle], None]
    ) -> Generator[AsyncJSFunction, None, None]:
        """Create a "notification": an async, one-way callback function, from JavaScript
        to Python.

        "One-way" here means the function returns nothing. "async" means that on the JS
        side, the function returns before it has been processed on the Python side."""

        with self._register_callback(func) as callback_id:
            yield cast(
                "AsyncJSFunction",
                self._value_handle_to_python(
                    self._wrap_raw_handle(
                        self._dll.mr_make_js_callback(self._ctx, callback_id)
                    ),
                    prefer_async_objects=True,
                ),
            )

    @asynccontextmanager
    async def wrap_py_function_as_js_function(
        self, func: PyJsFunctionType
    ) -> AsyncGenerator[AsyncJSFunction, None]:
        async def await_into_js_promise_resolvers(val_handle: ValueHandle) -> None:
            params = self._value_handle_to_python(val_handle)
            arguments, resolve, reject = cast("JSArray", params)
            try:
                result = await func(*cast("JSArray", arguments))
                await cast("AsyncJSFunction", resolve)(result)
            except Exception:  # noqa: BLE001
                # Convert this Python exception into a JS exception so we can send
                # it into JS:
                err_maker = cast(
                    "AsyncJSFunction", await self.evaluate("s => new Error(s)")
                )
                await cast("AsyncJSFunction", reject)(
                    await err_maker(f"Error running Python function:\n{format_exc()}")
                )

        async with _make_task_set(self._event_loop) as task_set:
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
                    "AsyncJSFunction",
                    await self.evaluate(
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
                    "AsyncJSFunction",
                    await wrap_outbound_calls_with_js_promises(js_to_py_notification),
                )

    def _wrap_raw_handle(self, raw: RawValueHandleType) -> ValueHandle:
        return ValueHandle(lambda: self._free(raw), raw)

    def _create_intish_val(self, val: int, typ: int) -> ValueHandle:
        return self._wrap_raw_handle(self._dll.mr_alloc_int_val(self._ctx, val, typ))

    def _create_doublish_val(self, val: float, typ: int) -> ValueHandle:
        return self._wrap_raw_handle(self._dll.mr_alloc_double_val(self._ctx, val, typ))

    def _create_string_val(self, val: str, typ: int) -> ValueHandle:
        b = val.encode("utf-8")
        return self._wrap_raw_handle(
            self._dll.mr_alloc_string_val(self._ctx, b, len(b), typ)
        )

    def _free(self, raw: RawValueHandleType) -> None:
        self._dll.mr_free_value(self._ctx, raw)

    async def _run_mr_task(
        self,
        dll_method: Any,  # noqa: ANN401
        *args: Any,  # noqa: ANN401
    ) -> PythonJSConvertedTypes:
        """Manages those tasks which generate callbacks from the MiniRacer DLL.

        Several MiniRacer functions (JS evaluation and 2 heap stats calls) are
        asynchronous. They take a function callback and callback data parameter, and
        they return a task handle.

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

        with self._register_callback(callback) as callback_id:
            # Start the task:
            task_id = dll_method(self._ctx, *args, callback_id)
            try:
                return await future
            finally:
                # Cancel the task if it's not already done (this call is ignored if it's
                # already done)
                self._dll.mr_cancel_task(self._ctx, task_id)

    def _value_handle_to_python(  # noqa: C901, PLR0911, PLR0912
        self, val_handle: ValueHandle, *, prefer_async_objects: bool | None = None
    ) -> PythonJSConvertedTypes:
        """Convert a binary value handle from the C++ side into a Python object."""

        # A MiniRacer binary value handle is a pointer to a structure which, for some
        # simple types like ints, floats, and strings, is sufficient to describe the
        # data, enabling us to convert the value immediately and free the handle.

        # For more complex types, like Objects and Arrays, the handle is just an opaque
        # pointer to a V8 object. In these cases, we retain the binary value handle,
        # wrapping it in a Python object. We can then use the handle in follow-on API
        # calls to work with the underlying V8 object.

        # In either case the handle is owned by the C++ side. It's the responsibility
        # of the Python side to call mr_free_value() when done with with the handle
        # to free up memory, but the C++ side will eventually free it on context
        # teardown either way.

        if prefer_async_objects is None:
            prefer_async_objects = self._prefer_async_objects

        raw = cast("RawValueHandleTypeImpl", val_handle.raw)

        typ = raw.contents.type
        val = raw.contents.value
        length = raw.contents.len

        error_info = _ERRORS.get(raw.contents.type)
        if error_info:
            klass, generic_msg = error_info

            msg = val.bytes_val[0:length].decode("utf-8") or generic_msg
            raise klass(msg)

        if typ == _MiniRacerTypes.null:
            return None
        if typ == _MiniRacerTypes.undefined:
            return JSUndefined
        if typ == _MiniRacerTypes.bool:
            return bool(val.int_val == 1)
        if typ == _MiniRacerTypes.integer:
            return int(val.int_val)
        if typ == _MiniRacerTypes.double:
            return float(val.double_val)
        if typ == _MiniRacerTypes.str_utf8:
            return str(val.bytes_val[0:length].decode("utf-8"))
        if typ == _MiniRacerTypes.function:
            return (
                AsyncJSFunctionImpl(self, val_handle)
                if prefer_async_objects
                else JSFunctionImpl(self, val_handle)
            )
        if typ == _MiniRacerTypes.date:
            timestamp = val.double_val
            # JS timestamps are milliseconds. In Python we are in seconds:
            return datetime.fromtimestamp(timestamp / 1000.0, timezone.utc)
        if typ == _MiniRacerTypes.symbol:
            return JSSymbolImpl(self, val_handle)
        if typ in (_MiniRacerTypes.shared_array_buffer, _MiniRacerTypes.array_buffer):
            buf = _ArrayBufferByte * length
            cdata = buf.from_address(val.value_ptr)
            # Save a reference to ourselves to prevent garbage collection of the
            # backing store:
            cdata._origin = self  # noqa: SLF001
            result = memoryview(cdata)
            # Avoids "NotImplementedError: memoryview: unsupported format T{<B:b:}"
            # in Python 3.12:
            return result.cast("B")

        if typ == _MiniRacerTypes.promise:
            return (
                AsyncJSPromiseImpl(self, val_handle)
                if prefer_async_objects
                else JSPromiseImpl(self, val_handle)
            )

        if typ == _MiniRacerTypes.array:
            return JSArrayImpl(self, val_handle)

        if typ == _MiniRacerTypes.object:
            return JSMappedObjectImpl(self, val_handle)

        raise JSConversionException

    def _python_to_value_handle(  # noqa: PLR0911
        self, obj: PythonJSConvertedTypes
    ) -> ValueHandle:
        if isinstance(obj, JSObjectImpl):
            # JSObjects originate from the V8 side. We can just send back the handle
            # we originally got. (This also covers derived types JSFunction, JSSymbol,
            # JSPromise, and JSArray.)
            return obj.raw_handle

        if obj is None:
            return self._create_intish_val(0, _MiniRacerTypes.null)
        if obj is JSUndefined:
            return self._create_intish_val(0, _MiniRacerTypes.undefined)
        if isinstance(obj, bool):
            return self._create_intish_val(1 if obj else 0, _MiniRacerTypes.bool)
        if isinstance(obj, int):
            if obj - 2**31 <= obj < 2**31:
                return self._create_intish_val(obj, _MiniRacerTypes.integer)

            # We transmit ints as int32, so "upgrade" to double upon overflow.
            # (ECMAScript numeric is double anyway, but V8 does internally distinguish
            # int types, so we try and preserve integer-ness for round-tripping
            # purposes.)
            # JS BigInt would be a closer representation of Python int, but upgrading
            # to BigInt would probably be surprising for most applications, so for now,
            # we approximate with double:
            return self._create_doublish_val(obj, _MiniRacerTypes.double)
        if isinstance(obj, float):
            return self._create_doublish_val(obj, _MiniRacerTypes.double)
        if isinstance(obj, str):
            return self._create_string_val(obj, _MiniRacerTypes.str_utf8)
        if isinstance(obj, datetime):
            # JS timestamps are milliseconds. In Python we are in seconds:
            return self._create_doublish_val(
                obj.timestamp() * 1000.0, _MiniRacerTypes.date
            )

        # Note: we skip shared array buffers, so for now at least, handles to shared
        # array buffers can only be transmitted from JS to Python.

        raise JSConversionException
