"""Declarations for Python renderings of basic JavaScript types."""

from __future__ import annotations

from collections.abc import (
    Awaitable,
    Callable,
    Generator,
    MutableMapping,
    MutableSequence,
)
from datetime import datetime
from typing import Any, TypeAlias


class JSUndefinedType:
    """The JavaScript undefined type.

    Where JavaScript null is represented as None, undefined is represented as this
    type."""

    def __bool__(self) -> bool:
        return False

    def __repr__(self) -> str:
        return "JSUndefined"


JSUndefined = JSUndefinedType()


class JSObject:
    """A JavaScript object."""


class JSMappedObject(
    MutableMapping["PythonJSConvertedTypes", "PythonJSConvertedTypes"], JSObject
):
    """A JavaScript object with Pythonic MutableMapping methods (`keys()`,
    `__getitem__()`, etc).

    `keys()` and `__iter__()` will return properties from any prototypes as well as this
    object, as if using a for-in statement in JavaScript.
    """


class JSArray(MutableSequence["PythonJSConvertedTypes"], JSObject):
    """JavaScript array.

    Has Pythonic MutableSequence methods (e.g., `insert()`, `__getitem__()`, ...).
    """


class JSFunction(JSMappedObject):
    """JavaScript function.

    This type is returned by synchronous MiniRacer contexts.

    You can call this object from Python, passing in positional args to match what the
    JavaScript function expects.

    In synchronous code you may supply an additional keyword argument, `timeout_sec`.

    If you are running in an async context in the same event loop as Miniracer, you must
    not supply a non-None value for timeout_sec. Instead call func.cancelable() to
    obtain a CancellableJSFunction, and use a construct like asyncio.wait_for(...) to
    apply a timeout.
    """

    def __call__(
        self,
        *args: PythonJSConvertedTypes,
        this: JSObject | JSUndefinedType = JSUndefined,
        timeout_sec: float | None = None,
    ) -> PythonJSConvertedTypes:
        raise NotImplementedError

    def cancelable(self) -> CancelableJSFunction:
        raise NotImplementedError


class CancelableJSFunction(JSMappedObject):
    """JavaScript function.

    This type is returned by JSFunction.cancelable().

    You can call this object from Python, passing in positional args to match what the
    JavaScript function expects. Calls on the Python side are async, regardless of
    whether the underlying JS function is async (so a call to an async JS function will
    return a JSPromise, requiring a "double await" in Python to get the result).
    """

    async def __call__(
        self,
        *args: PythonJSConvertedTypes,
        this: JSObject | JSUndefinedType = JSUndefined,
    ) -> PythonJSConvertedTypes:
        raise NotImplementedError


class JSSymbol(JSMappedObject):
    """JavaScript symbol."""


class JSPromise(JSObject):
    """JavaScript Promise.

    To get a value, call `promise.get()` (which blocks) or `await promise` (in async
    code). Both operations will raise a Python exception if the JavaScript Promise is
    rejected.
    """

    def get(self, *, timeout: float | None = None) -> PythonJSConvertedTypes:
        raise NotImplementedError

    def __await__(self) -> Generator[Any, None, Any]:
        raise NotImplementedError


PythonJSConvertedTypes: TypeAlias = (
    JSUndefinedType
    | bool
    | int
    | float
    | str
    | JSObject
    | datetime
    | memoryview
    | JSPromise
    | JSFunction
    | CancelableJSFunction
    | JSMappedObject
    | JSSymbol
    | JSArray
    | None
)


PyJsFunctionType = Callable[..., Awaitable[PythonJSConvertedTypes]]
