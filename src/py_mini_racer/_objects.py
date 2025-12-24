"""Python wrappers for JavaScript object types."""

from __future__ import annotations

from asyncio import get_running_loop
from concurrent.futures import Future as SyncFuture
from operator import index as op_index
from typing import TYPE_CHECKING, Any, cast

from py_mini_racer._exc import JSArrayIndexError, JSPromiseError
from py_mini_racer._types import (
    JSArray,
    JSFunction,
    JSMappedObject,
    JSObject,
    JSPromise,
    JSSymbol,
    JSUndefined,
    JSUndefinedType,
    PythonJSConvertedTypes,
)
from py_mini_racer._wrap_py_function import wrap_py_function_as_js_function

if TYPE_CHECKING:
    from asyncio import Future
    from collections.abc import Generator, Iterator

    from py_mini_racer._exc import JSEvalException
    from py_mini_racer._js_value_manipulator import JSValueManipulator
    from py_mini_racer._value_handle import ValueHandle


def _get_exception_msg(reason: PythonJSConvertedTypes) -> str:
    if not isinstance(reason, JSMappedObject):
        return str(reason)

    if "stack" in reason:
        return cast("str", reason["stack"])

    return str(reason)


class JSObjectImpl(JSObject):
    """A JavaScript object."""

    def __init__(
        self, val_manipulator: JSValueManipulator, handle: ValueHandle
    ) -> None:
        self._val_manipulator = val_manipulator
        self._handle = handle

    def __hash__(self) -> int:
        return self._val_manipulator.get_identity_hash(self)

    @property
    def raw_handle(self) -> ValueHandle:
        return self._handle


class JSMappedObjectImpl(JSObjectImpl, JSMappedObject):
    """A JavaScript object with Pythonic MutableMapping methods (`keys()`,
    `__getitem__()`, etc).

    `keys()` and `__iter__()` will return properties from any prototypes as well as this
    object, as if using a for-in statement in JavaScript.
    """

    def __iter__(self) -> Iterator[PythonJSConvertedTypes]:
        return iter(self._get_own_property_names())

    def __getitem__(self, key: PythonJSConvertedTypes) -> PythonJSConvertedTypes:
        return self._val_manipulator.get_object_item(self, key)

    def __setitem__(
        self, key: PythonJSConvertedTypes, val: PythonJSConvertedTypes
    ) -> None:
        self._val_manipulator.set_object_item(self, key, val)

    def __delitem__(self, key: PythonJSConvertedTypes) -> None:
        self._val_manipulator.del_object_item(self, key)

    def __len__(self) -> int:
        return len(self._get_own_property_names())

    def _get_own_property_names(self) -> tuple[PythonJSConvertedTypes, ...]:
        return self._val_manipulator.get_own_property_names(self)


class JSArrayImpl(JSArray, JSObjectImpl):
    """JavaScript array.

    Has Pythonic MutableSequence methods (e.g., `insert()`, `__getitem__()`, ...).
    """

    def __len__(self) -> int:
        return cast("int", self._val_manipulator.get_object_item(self, "length"))

    def __getitem__(self, index: int | slice) -> Any:  # noqa: ANN401
        if not isinstance(index, int):
            raise TypeError

        index = op_index(index)
        if index < 0:
            index += len(self)

        if 0 <= index < len(self):
            return self._val_manipulator.get_object_item(self, index)

        raise IndexError

    def __setitem__(self, index: int | slice, val: Any) -> None:  # noqa: ANN401
        if not isinstance(index, int):
            raise TypeError

        self._val_manipulator.set_object_item(self, index, val)

    def __delitem__(self, index: int | slice) -> None:
        if not isinstance(index, int):
            raise TypeError

        if index >= len(self) or index < -len(self):
            # JavaScript Array.prototype.splice() just ignores deletion beyond the
            # end of the array, meaning if you pass a very large value here it would
            # do nothing. Likewise, it just caps negative values at the length of the
            # array, meaning if you pass a very negative value here it would just
            # delete element 0.
            # For consistency with Python lists, let's tell the caller they're out of
            # bounds:
            raise JSArrayIndexError

        self._val_manipulator.del_from_array(self, index)

    def insert(self, index: int, new_obj: PythonJSConvertedTypes) -> None:
        self._val_manipulator.array_insert(self, index, new_obj)

    def __iter__(self) -> Iterator[PythonJSConvertedTypes]:
        for i in range(len(self)):
            yield self._val_manipulator.get_object_item(self, i)

    def append(self, value: PythonJSConvertedTypes) -> None:
        self._val_manipulator.array_push(self, value)


class JSFunctionImpl(JSMappedObjectImpl, JSFunction):
    """JavaScript function.

    You can call this object from Python, passing in positional args to match what the
    JavaScript function expects, along with a keyword argument, `timeout_sec`.
    """

    def __call__(
        self,
        *args: PythonJSConvertedTypes,
        this: JSObject | JSUndefinedType = JSUndefined,
        timeout_sec: float | None = None,
    ) -> PythonJSConvertedTypes:
        return self._val_manipulator.call_function(
            self, *args, this=this, timeout_sec=timeout_sec
        )


class JSSymbolImpl(JSMappedObjectImpl, JSSymbol):
    """JavaScript symbol."""


class JSPromiseImpl(JSObjectImpl, JSPromise):
    """JavaScript Promise.

    To get a value, call `promise.get()` to block, or `await promise` from within an
    `async` coroutine. Either will raise a Python exception if the JavaScript Promise
    is rejected.
    """

    def get(self, *, timeout: float | None = None) -> PythonJSConvertedTypes:
        """Get the value, or raise an exception. This call blocks.

        Args:
            timeout: number of milliseconds after which the execution is interrupted.
                This is deprecated; use timeout_sec instead.
        """

        future: SyncFuture[JSArray] = SyncFuture()
        is_rejected = False

        def on_resolved(value: PythonJSConvertedTypes | JSEvalException) -> None:
            future.set_result(cast("JSArray", value))

        def on_rejected(value: PythonJSConvertedTypes | JSEvalException) -> None:
            nonlocal is_rejected
            is_rejected = True
            future.set_result(cast("JSArray", value))

        with (
            self._val_manipulator.js_to_py_callback(on_resolved) as on_resolved_js_func,
            self._val_manipulator.js_to_py_callback(on_rejected) as on_rejected_js_func,
        ):
            self._val_manipulator.promise_then(
                self, on_resolved_js_func, on_rejected_js_func
            )

            result = future.result(timeout=timeout)

        if is_rejected:
            msg = _get_exception_msg(result[0])
            raise JSPromiseError(msg)

        return result[0]

    def __await__(self) -> Generator[Any, None, Any]:
        return self._do_await().__await__()

    async def _do_await(self) -> PythonJSConvertedTypes:
        future: Future[PythonJSConvertedTypes] = get_running_loop().create_future()

        async def on_resolved(value: PythonJSConvertedTypes) -> None:
            future.set_result(value)

        async def on_rejected(value: PythonJSConvertedTypes) -> None:
            future.set_exception(JSPromiseError(_get_exception_msg(value)))

        async with (
            wrap_py_function_as_js_function(
                self._val_manipulator, on_resolved
            ) as on_resolved_js_func,
            wrap_py_function_as_js_function(
                self._val_manipulator, on_rejected
            ) as on_rejected_js_func,
        ):
            self._val_manipulator.promise_then(
                self, on_resolved_js_func, on_rejected_js_func
            )

            return await future
