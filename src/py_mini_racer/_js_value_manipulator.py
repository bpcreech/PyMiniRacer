from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from py_mini_racer._types import (
    AsyncJSFunction,
    AsyncJSPromise,
    JSArray,
    JSFunction,
    JSObject,
    JSPromise,
    JSUndefined,
    JSUndefinedType,
    PyJsFunctionType,
    PythonJSConvertedTypes,
)

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager


class JSValueManipulator(Protocol):
    def get_identity_hash(self, obj: JSObject) -> int: ...

    def get_own_property_names(
        self, obj: JSObject
    ) -> tuple[PythonJSConvertedTypes, ...]: ...

    def get_object_item(
        self, obj: JSObject, key: PythonJSConvertedTypes
    ) -> PythonJSConvertedTypes: ...

    def set_object_item(
        self, obj: JSObject, key: PythonJSConvertedTypes, val: PythonJSConvertedTypes
    ) -> None: ...

    def del_object_item(self, obj: JSObject, key: PythonJSConvertedTypes) -> None: ...

    def del_from_array(self, arr: JSArray, index: int) -> None: ...

    def array_insert(
        self, arr: JSArray, index: int, new_val: PythonJSConvertedTypes
    ) -> None: ...

    def array_push(self, arr: JSArray, new_val: PythonJSConvertedTypes) -> None: ...

    def sync_call_function(
        self,
        func: JSFunction,
        *args: PythonJSConvertedTypes,
        this: JSObject | JSUndefinedType = JSUndefined,
        timeout_sec: float | None = None,
    ) -> PythonJSConvertedTypes: ...

    async def async_call_function(
        self,
        func: AsyncJSFunction,
        *args: PythonJSConvertedTypes,
        this: JSObject | JSUndefinedType = JSUndefined,
    ) -> PythonJSConvertedTypes: ...

    def wrap_py_function_as_js_function(
        self, func: PyJsFunctionType
    ) -> AbstractAsyncContextManager[AsyncJSFunction]: ...

    def sync_await_promise(
        self, promise: JSPromise, timeout: float | None = None
    ) -> PythonJSConvertedTypes: ...

    async def async_await_promise(
        self, promise: AsyncJSPromise
    ) -> PythonJSConvertedTypes: ...

    async def evaluate(self, code: str) -> PythonJSConvertedTypes: ...
