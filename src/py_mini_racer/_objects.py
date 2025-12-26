"""Python wrappers for JavaScript object types."""

from __future__ import annotations

from operator import index as op_index
from typing import TYPE_CHECKING, Any, cast

from py_mini_racer._exc import JSArrayIndexError
from py_mini_racer._types import (
    AsyncJSFunction,
    AsyncJSPromise,
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

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator

    from py_mini_racer._js_value_manipulator import JSValueManipulator
    from py_mini_racer._value_handle import ValueHandle


class JSObjectImpl(JSObject):
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
    def __call__(
        self,
        *args: PythonJSConvertedTypes,
        this: JSObject | JSUndefinedType = JSUndefined,
        timeout_sec: float | None = None,
    ) -> PythonJSConvertedTypes:
        return self._val_manipulator.sync_call_function(
            self, *args, this=this, timeout_sec=timeout_sec
        )


class AsyncJSFunctionImpl(JSMappedObjectImpl, AsyncJSFunction):
    async def __call__(
        self,
        *args: PythonJSConvertedTypes,
        this: JSObject | JSUndefinedType = JSUndefined,
    ) -> PythonJSConvertedTypes:
        return await self._val_manipulator.async_call_function(self, *args, this=this)


class JSSymbolImpl(JSMappedObjectImpl, JSSymbol):
    pass


class JSPromiseImpl(JSObjectImpl, JSPromise):
    def get(self, *, timeout: float | None = None) -> PythonJSConvertedTypes:
        return self._val_manipulator.sync_await_promise(self, timeout)


class AsyncJSPromiseImpl(JSObjectImpl, AsyncJSPromise):
    def __await__(self) -> Generator[Any, None, Any]:
        return self._val_manipulator.async_await_promise(self).__await__()
