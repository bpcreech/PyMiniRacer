from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from py_mini_racer._types import (
    JSArray,
    JSFunction,
    JSObject,
    JSPromise,
    JSUndefined,
    JSUndefinedType,
    PythonJSConvertedTypes,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractContextManager

    from py_mini_racer._exc import JSEvalException


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

    def call_function(
        self,
        func: JSFunction,
        *args: PythonJSConvertedTypes,
        this: JSObject | JSUndefinedType = JSUndefined,
        timeout_sec: float | None = None,
    ) -> PythonJSConvertedTypes: ...

    def js_to_py_callback(
        self, func: Callable[[PythonJSConvertedTypes | JSEvalException], None]
    ) -> AbstractContextManager[JSFunction]: ...

    def promise_then(
        self, promise: JSPromise, on_resolved: JSFunction, on_rejected: JSFunction
    ) -> None: ...

    def evaluate(
        self, code: str, timeout_sec: float | None = None
    ) -> PythonJSConvertedTypes: ...
