from __future__ import annotations

import ctypes
from concurrent.futures import Future as SyncFuture
from concurrent.futures import TimeoutError as SyncTimeoutError
from contextlib import contextmanager, suppress
from datetime import datetime, timezone
from itertools import count
from typing import TYPE_CHECKING, Any, ClassVar, cast

from py_mini_racer._dll import init_mini_racer, mr_callback_func
from py_mini_racer._exc import (
    JSConversionException,
    JSEvalException,
    JSKeyError,
    JSOOMException,
    JSParseException,
    JSTerminatedException,
    JSTimeoutException,
    JSValueError,
)
from py_mini_racer._js_value_manipulator import JSValueManipulator
from py_mini_racer._objects import (
    JSArrayImpl,
    JSFunctionImpl,
    JSMappedObjectImpl,
    JSObjectImpl,
    JSPromiseImpl,
    JSSymbolImpl,
)
from py_mini_racer._types import (
    JSArray,
    JSFunction,
    JSObject,
    JSPromise,
    JSUndefined,
    JSUndefinedType,
    PythonJSConvertedTypes,
)
from py_mini_racer._value_handle import ValueHandle

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Iterator, Sequence

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


class _CallbackRegistry:
    def __init__(
        self, raw_handle_wrapper: Callable[[RawValueHandleType], ValueHandle]
    ) -> None:
        self._active_callbacks: dict[int, Callable[[ValueHandle], None]] = {}

        # define an all-purpose callback:
        @mr_callback_func
        def mr_callback(callback_id: int, raw_val_handle: RawValueHandleType) -> None:
            val_handle = raw_handle_wrapper(raw_val_handle)
            callback = self._active_callbacks[callback_id]
            callback(val_handle)

        self.mr_callback = mr_callback

        self._next_callback_id = count()

    @contextmanager
    def register(
        self, func: Callable[[ValueHandle], None]
    ) -> Generator[int, None, None]:
        callback_id = next(self._next_callback_id)

        self._active_callbacks[callback_id] = func

        try:
            yield callback_id
        finally:
            self._active_callbacks.pop(callback_id)


class Context(JSValueManipulator):
    """Wrapper for all operations involving the DLL and C++ MiniRacer::Context."""

    def __init__(self, dll: ctypes.CDLL) -> None:
        self._dll: ctypes.CDLL | None = dll

        self._callback_registry = _CallbackRegistry(self._wrap_raw_handle)
        self._ctx = dll.mr_init_context(self._callback_registry.mr_callback)

    def _get_dll(self) -> ctypes.CDLL:
        if self._dll is None:
            msg = "Operation on closed Context"
            raise ValueError(msg)

        return self._dll

    def v8_version(self) -> str:
        return str(self._get_dll().mr_v8_version().decode("utf-8"))

    def v8_is_using_sandbox(self) -> bool:
        """Checks for enablement of the V8 Sandbox. See https://v8.dev/blog/sandbox."""

        return bool(self._get_dll().mr_v8_is_using_sandbox())

    def evaluate(
        self, code: str, timeout_sec: float | None = None
    ) -> PythonJSConvertedTypes:
        code_handle = self._python_to_value_handle(code)

        with self._run_mr_task(
            self._get_dll().mr_eval, self._ctx, code_handle.raw
        ) as future:
            try:
                return future.result(timeout=timeout_sec)
            except SyncTimeoutError as e:
                raise JSTimeoutException from e

    def promise_then(
        self, promise: JSPromise, on_resolved: JSFunction, on_rejected: JSFunction
    ) -> None:
        promise_handle = self._python_to_value_handle(promise)
        then_name_handle = self._python_to_value_handle("then")

        then_func = cast(
            "JSFunction",
            self._value_handle_to_python(
                self._wrap_raw_handle(
                    self._get_dll().mr_get_object_item(
                        self._ctx, promise_handle.raw, then_name_handle.raw
                    )
                )
            ),
        )

        then_func(on_resolved, on_rejected, this=promise)

    def get_identity_hash(self, obj: JSObject) -> int:
        obj_handle = self._python_to_value_handle(obj)

        return cast(
            "int",
            self._value_handle_to_python(
                self._wrap_raw_handle(
                    self._get_dll().mr_get_identity_hash(self._ctx, obj_handle.raw)
                )
            ),
        )

    def get_own_property_names(
        self, obj: JSObject
    ) -> tuple[PythonJSConvertedTypes, ...]:
        obj_handle = self._python_to_value_handle(obj)

        names = self._value_handle_to_python(
            self._wrap_raw_handle(
                self._get_dll().mr_get_own_property_names(self._ctx, obj_handle.raw)
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
                self._get_dll().mr_get_object_item(
                    self._ctx, obj_handle.raw, key_handle.raw
                )
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
                self._get_dll().mr_set_object_item(
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
                self._get_dll().mr_del_object_item(
                    self._ctx, obj_handle.raw, key_handle.raw
                )
            )
        )

    def del_from_array(self, arr: JSArray, index: int) -> None:
        arr_handle = self._python_to_value_handle(arr)

        # Convert the value just to convert any exceptions (and GC the result)
        self._value_handle_to_python(
            self._wrap_raw_handle(
                self._get_dll().mr_splice_array(
                    self._ctx, arr_handle.raw, index, 1, None
                )
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
                self._get_dll().mr_splice_array(
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
                self._get_dll().mr_array_push(
                    self._ctx, arr_handle.raw, new_val_handle.raw
                )
            )
        )

    def call_function(
        self,
        func: JSFunction,
        *args: PythonJSConvertedTypes,
        this: JSObject | JSUndefinedType = JSUndefined,
        timeout_sec: float | None = None,
    ) -> PythonJSConvertedTypes:
        argv = cast("JSArray", self.evaluate("[]"))
        for arg in args:
            argv.append(arg)

        func_handle = self._python_to_value_handle(func)
        this_handle = self._python_to_value_handle(this)
        argv_handle = self._python_to_value_handle(argv)

        with self._run_mr_task(
            self._get_dll().mr_call_function,
            self._ctx,
            func_handle.raw,
            this_handle.raw,
            argv_handle.raw,
        ) as future:
            try:
                return future.result(timeout=timeout_sec)
            except SyncTimeoutError as e:
                raise JSTimeoutException from e

    def set_hard_memory_limit(self, limit: int) -> None:
        self._get_dll().mr_set_hard_memory_limit(self._ctx, limit)

    def set_soft_memory_limit(self, limit: int) -> None:
        self._get_dll().mr_set_soft_memory_limit(self._ctx, limit)

    def was_hard_memory_limit_reached(self) -> bool:
        return bool(self._get_dll().mr_hard_memory_limit_reached(self._ctx))

    def was_soft_memory_limit_reached(self) -> bool:
        return bool(self._get_dll().mr_soft_memory_limit_reached(self._ctx))

    def low_memory_notification(self) -> None:
        self._get_dll().mr_low_memory_notification(self._ctx)

    def heap_stats(self) -> str:
        with self._run_mr_task(self._get_dll().mr_heap_stats, self._ctx) as future:
            return cast("str", future.result())

    def heap_snapshot(self) -> str:
        """Return a snapshot of the V8 isolate heap."""

        with self._run_mr_task(self._get_dll().mr_heap_snapshot, self._ctx) as future:
            return cast("str", future.result())

    def value_count(self) -> int:
        """For tests only: how many value handles are still allocated?"""

        return int(self._get_dll().mr_value_count(self._ctx))

    @contextmanager
    def js_to_py_callback(
        self, func: Callable[[PythonJSConvertedTypes | JSEvalException], None]
    ) -> Iterator[JSFunction]:
        """Make a JS callback which forwards to the given Python function.

        Note that it's crucial that the given Python function *not* call back
        into the C++ MiniRacer context, or it will deadlock. Instead it should
        signal another thread; e.g., by putting received data onto a queue or
        future.
        """

        def func_py(val_handle: ValueHandle) -> None:
            try:
                value = self._value_handle_to_python(val_handle)
            except JSEvalException as e:
                func(e)
                return

            func(value)

        with self._callback_registry.register(func_py) as callback_id:
            cb = self._wrap_raw_handle(
                self._get_dll().mr_make_js_callback(self._ctx, callback_id)
            )

            yield cast("JSFunction", self._value_handle_to_python(cb))

    def _wrap_raw_handle(self, raw: RawValueHandleType) -> ValueHandle:
        return ValueHandle(lambda: self._free(raw), raw)

    def _create_intish_val(self, val: int, typ: int) -> ValueHandle:
        return self._wrap_raw_handle(
            self._get_dll().mr_alloc_int_val(self._ctx, val, typ)
        )

    def _create_doublish_val(self, val: float, typ: int) -> ValueHandle:
        return self._wrap_raw_handle(
            self._get_dll().mr_alloc_double_val(self._ctx, val, typ)
        )

    def _create_string_val(self, val: str, typ: int) -> ValueHandle:
        b = val.encode("utf-8")
        return self._wrap_raw_handle(
            self._get_dll().mr_alloc_string_val(self._ctx, b, len(b), typ)
        )

    def _free(self, raw: RawValueHandleType) -> None:
        dll = self._dll
        if dll is not None:
            dll.mr_free_value(self._ctx, raw)

    @contextmanager
    def _run_mr_task(
        self,
        dll_method: Any,  # noqa: ANN401
        *args: Any,  # noqa: ANN401
    ) -> Iterator[SyncFuture[PythonJSConvertedTypes]]:
        """Manages those tasks which generate callbacks from the MiniRacer DLL.

        Several MiniRacer functions (JS evaluation and 2 heap stats calls) are
        asynchronous. They take a function callback and callback data parameter, and
        they return a task handle.

        In this method, we create a future for each callback to get the right data to
        the right caller, and we manage the lifecycle of the task and task handle.
        """

        future: SyncFuture[PythonJSConvertedTypes] = SyncFuture()

        def callback(val_handle: ValueHandle) -> None:
            try:
                value = self._value_handle_to_python(val_handle)
            except JSEvalException as e:
                future.set_exception(e)
                return

            future.set_result(value)

        with self._callback_registry.register(callback) as callback_id:
            # Start the task:
            task_id = dll_method(*args, callback_id)
            try:
                # Let the caller handle waiting on the result:
                yield future
            finally:
                # Cancel the task if it's not already done (this call is ignored if it's
                # already done)
                self._get_dll().mr_cancel_task(self._ctx, task_id)

                # If the caller gives up on waiting, let's at least await the
                # cancelation error for GC purposes:
                with suppress(Exception):
                    future.result()

    def close(self) -> None:
        dll, self._dll = self._dll, None
        if dll:
            dll.mr_free_context(self._ctx)

    def __del__(self) -> None:
        self.close()

    def _value_handle_to_python(  # noqa: C901, PLR0911, PLR0912
        self, val_handle: ValueHandle
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
            return JSFunctionImpl(self, val_handle)
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
            return JSPromiseImpl(self, val_handle)

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
