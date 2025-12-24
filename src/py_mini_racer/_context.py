from __future__ import annotations

from concurrent.futures import Future as SyncFuture
from concurrent.futures import TimeoutError as SyncTimeoutError
from contextlib import contextmanager, suppress
from itertools import count
from typing import TYPE_CHECKING, Any, cast

from py_mini_racer._abstract_context import AbstractContext
from py_mini_racer._dll import init_mini_racer, mr_callback_func
from py_mini_racer._exc import JSEvalException, JSTimeoutException
from py_mini_racer._types import (
    JSArray,
    JSFunction,
    JSObject,
    JSPromise,
    JSUndefined,
    JSUndefinedType,
    PythonJSConvertedTypes,
)
from py_mini_racer._value_handle import ValueHandle, python_to_value_handle

if TYPE_CHECKING:
    import ctypes
    from collections.abc import Callable, Generator, Iterator

    from py_mini_racer._abstract_context import AbstractValueHandle
    from py_mini_racer._value_handle import RawValueHandleType


def context_count() -> int:
    """For tests only: how many context handles are still allocated?"""

    dll = init_mini_racer(ignore_duplicate_init=True)
    return int(dll.mr_context_count())


class _CallbackRegistry:
    def __init__(
        self, raw_handle_wrapper: Callable[[RawValueHandleType], AbstractValueHandle]
    ) -> None:
        self._active_callbacks: dict[
            int, Callable[[PythonJSConvertedTypes | JSEvalException], None]
        ] = {}

        # define an all-purpose callback:
        @mr_callback_func
        def mr_callback(callback_id: int, raw_val_handle: RawValueHandleType) -> None:
            val_handle = raw_handle_wrapper(raw_val_handle)
            callback = self._active_callbacks[callback_id]
            callback(val_handle.to_python())

        self.mr_callback = mr_callback

        self._next_callback_id = count()

    @contextmanager
    def register(
        self, func: Callable[[PythonJSConvertedTypes | JSEvalException], None]
    ) -> Generator[int, None, None]:
        callback_id = next(self._next_callback_id)

        self._active_callbacks[callback_id] = func

        try:
            yield callback_id
        finally:
            self._active_callbacks.pop(callback_id)


class Context(AbstractContext):
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
        code_handle = python_to_value_handle(self, code)

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
        promise_handle = python_to_value_handle(self, promise)
        then_name_handle = python_to_value_handle(self, "then")
        then_func = self._wrap_raw_handle(
            self._get_dll().mr_get_object_item(
                self._ctx, promise_handle.raw, then_name_handle.raw
            )
        ).to_python_or_raise()

        then_func = cast("JSFunction", then_func)
        then_func(on_resolved, on_rejected, this=promise)

    def get_identity_hash(self, obj: JSObject) -> int:
        obj_handle = python_to_value_handle(self, obj)

        return cast(
            "int",
            self._wrap_raw_handle(
                self._get_dll().mr_get_identity_hash(self._ctx, obj_handle.raw)
            ).to_python_or_raise(),
        )

    def get_own_property_names(
        self, obj: JSObject
    ) -> tuple[PythonJSConvertedTypes, ...]:
        obj_handle = python_to_value_handle(self, obj)

        names = self._wrap_raw_handle(
            self._get_dll().mr_get_own_property_names(self._ctx, obj_handle.raw)
        ).to_python_or_raise()
        if not isinstance(names, JSArray):
            raise TypeError
        return tuple(names)

    def get_object_item(
        self, obj: JSObject, key: PythonJSConvertedTypes
    ) -> PythonJSConvertedTypes:
        obj_handle = python_to_value_handle(self, obj)
        key_handle = python_to_value_handle(self, key)

        return self._wrap_raw_handle(
            self._get_dll().mr_get_object_item(
                self._ctx, obj_handle.raw, key_handle.raw
            )
        ).to_python_or_raise()

    def set_object_item(
        self, obj: JSObject, key: PythonJSConvertedTypes, val: PythonJSConvertedTypes
    ) -> None:
        obj_handle = python_to_value_handle(self, obj)
        key_handle = python_to_value_handle(self, key)
        val_handle = python_to_value_handle(self, val)

        # Convert the value just to convert any exceptions (and GC the result)
        self._wrap_raw_handle(
            self._get_dll().mr_set_object_item(
                self._ctx, obj_handle.raw, key_handle.raw, val_handle.raw
            )
        ).to_python_or_raise()

    def del_object_item(self, obj: JSObject, key: PythonJSConvertedTypes) -> None:
        obj_handle = python_to_value_handle(self, obj)
        key_handle = python_to_value_handle(self, key)

        # Convert the value just to convert any exceptions (and GC the result)
        self._wrap_raw_handle(
            self._get_dll().mr_del_object_item(
                self._ctx, obj_handle.raw, key_handle.raw
            )
        ).to_python_or_raise()

    def del_from_array(self, arr: JSArray, index: int) -> None:
        arr_handle = python_to_value_handle(self, arr)

        # Convert the value just to convert any exceptions (and GC the result)
        self._wrap_raw_handle(
            self._get_dll().mr_splice_array(self._ctx, arr_handle.raw, index, 1, None)
        ).to_python_or_raise()

    def array_insert(
        self, arr: JSArray, index: int, new_val: PythonJSConvertedTypes
    ) -> None:
        arr_handle = python_to_value_handle(self, arr)
        new_val_handle = python_to_value_handle(self, new_val)

        # Convert the value just to convert any exceptions (and GC the result)
        self._wrap_raw_handle(
            self._get_dll().mr_splice_array(
                self._ctx, arr_handle.raw, index, 0, new_val_handle.raw
            )
        ).to_python_or_raise()

    def array_push(self, arr: JSArray, new_val: PythonJSConvertedTypes) -> None:
        arr_handle = python_to_value_handle(self, arr)
        new_val_handle = python_to_value_handle(self, new_val)

        # Convert the value just to convert any exceptions (and GC the result)
        self._wrap_raw_handle(
            self._get_dll().mr_array_push(self._ctx, arr_handle.raw, new_val_handle.raw)
        ).to_python_or_raise()

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

        func_handle = python_to_value_handle(self, func)
        this_handle = python_to_value_handle(self, this)
        argv_handle = python_to_value_handle(self, argv)

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

        with self._callback_registry.register(func) as callback_id:
            cb = self._wrap_raw_handle(
                self._get_dll().mr_make_js_callback(self._ctx, callback_id)
            )

            yield cast("JSFunction", cb.to_python_or_raise())

    def _wrap_raw_handle(self, raw: RawValueHandleType) -> ValueHandle:
        return ValueHandle(self, raw)

    def create_intish_val(self, val: int, typ: int) -> AbstractValueHandle:
        return self._wrap_raw_handle(
            self._get_dll().mr_alloc_int_val(self._ctx, val, typ)
        )

    def create_doublish_val(self, val: float, typ: int) -> AbstractValueHandle:
        return self._wrap_raw_handle(
            self._get_dll().mr_alloc_double_val(self._ctx, val, typ)
        )

    def create_string_val(self, val: str, typ: int) -> AbstractValueHandle:
        b = val.encode("utf-8")
        return self._wrap_raw_handle(
            self._get_dll().mr_alloc_string_val(self._ctx, b, len(b), typ)
        )

    def free(self, val_handle: AbstractValueHandle) -> None:
        dll = self._dll
        if dll is not None:
            dll.mr_free_value(self._ctx, val_handle.raw)

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

        def callback(value: PythonJSConvertedTypes | JSEvalException) -> None:
            if isinstance(value, JSEvalException):
                future.set_exception(value)
            else:
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
