"""Python wrappers for JavaScript object types."""

from __future__ import annotations

import asyncio
import ctypes
from datetime import datetime, timezone
from operator import index as op_index
from typing import TYPE_CHECKING, Any, ClassVar, cast

from py_mini_racer._exc import (
    JSArrayIndexError,
    JSConversionException,
    JSEvalException,
    JSKeyError,
    JSOOMException,
    JSParseException,
    JSTerminatedException,
    JSTimeoutException,
    JSValueError,
)
from py_mini_racer._types import (
    CancelableJSFunction,
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
    from collections.abc import Generator, Iterator, Sequence

    from py_mini_racer._context import Context
    from py_mini_racer._dll import RawValueHandleTypeImpl
    from py_mini_racer._value_handle import ValueHandle


class JSObjectImpl(JSObject):
    def __init__(self, ctx: Context, handle: ValueHandle) -> None:
        self._ctx = ctx
        self._handle = handle

    def __hash__(self) -> int:
        return self._ctx.get_identity_hash(self)

    @property
    def raw_handle(self) -> ValueHandle:
        return self._handle


class JSMappedObjectImpl(JSObjectImpl, JSMappedObject):
    def __iter__(self) -> Iterator[PythonJSConvertedTypes]:
        return iter(self._get_own_property_names())

    def __getitem__(self, key: PythonJSConvertedTypes) -> PythonJSConvertedTypes:
        return self._ctx.get_object_item(self, key)

    def __setitem__(
        self, key: PythonJSConvertedTypes, val: PythonJSConvertedTypes
    ) -> None:
        self._ctx.set_object_item(self, key, val)

    def __delitem__(self, key: PythonJSConvertedTypes) -> None:
        self._ctx.del_object_item(self, key)

    def __len__(self) -> int:
        return len(self._get_own_property_names())

    def _get_own_property_names(self) -> tuple[PythonJSConvertedTypes, ...]:
        return self._ctx.get_own_property_names(self)


class JSArrayImpl(JSArray, JSObjectImpl):
    def __len__(self) -> int:
        return cast("int", self._ctx.get_object_item(self, "length"))

    def __getitem__(self, index: int | slice) -> Any:  # noqa: ANN401
        if not isinstance(index, int):
            raise TypeError

        index = op_index(index)
        if index < 0:
            index += len(self)

        if 0 <= index < len(self):
            return self._ctx.get_object_item(self, index)

        raise IndexError

    def __setitem__(self, index: int | slice, val: Any) -> None:  # noqa: ANN401
        if not isinstance(index, int):
            raise TypeError

        self._ctx.set_object_item(self, index, val)

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

        self._ctx.del_from_array(self, index)

    def insert(self, index: int, new_obj: PythonJSConvertedTypes) -> None:
        self._ctx.array_insert(self, index, new_obj)

    def __iter__(self) -> Iterator[PythonJSConvertedTypes]:
        for i in range(len(self)):
            yield self._ctx.get_object_item(self, i)

    def append(self, value: PythonJSConvertedTypes) -> None:
        self._ctx.array_push(self, value)


class JSFunctionImpl(JSMappedObjectImpl, JSFunction):
    def __call__(
        self,
        *args: PythonJSConvertedTypes,
        this: JSObject | JSUndefinedType = JSUndefined,
        timeout_sec: float | None = None,
    ) -> PythonJSConvertedTypes:
        if not self._ctx.are_we_running_on_the_mini_racer_event_loop():

            async def run() -> PythonJSConvertedTypes:
                try:
                    return await asyncio.wait_for(
                        self._ctx.call_function_cancelable(self, *args, this=this),
                        timeout=timeout_sec,
                    )
                except asyncio.TimeoutError as e:
                    raise JSTimeoutException from e

            return asyncio.run_coroutine_threadsafe(
                run(), self._ctx.event_loop
            ).result()

        assert timeout_sec is None, (
            "To apply a timeout in an async context, use "
            "`await asyncio.wait_for(your_func.cancelable()(your_params), "
            "timeout=your_timeout)`"
        )

        return self._ctx.call_function(self, *args, this=this)

    def cancelable(self) -> CancelableJSFunction:
        return CancelableJSFunctionImpl(self._ctx, self._handle)


class CancelableJSFunctionImpl(JSMappedObjectImpl, CancelableJSFunction):
    async def __call__(
        self,
        *args: PythonJSConvertedTypes,
        this: JSObject | JSUndefinedType = JSUndefined,
    ) -> PythonJSConvertedTypes:
        return await self._ctx.call_function_cancelable(self, *args, this=this)


class JSSymbolImpl(JSMappedObjectImpl, JSSymbol):
    pass


class JSPromiseImpl(JSObjectImpl, JSPromise):
    def get(self, *, timeout: float | None = None) -> PythonJSConvertedTypes:
        assert not self._ctx.are_we_running_on_the_mini_racer_event_loop(), (
            "In an async context, call `await promise` instead of promise.get()"
        )

        async def run() -> PythonJSConvertedTypes:
            try:
                return await asyncio.wait_for(
                    self._ctx.await_promise(self), timeout=timeout
                )
            except asyncio.TimeoutError as e:
                raise JSTimeoutException from e

        return asyncio.run_coroutine_threadsafe(run(), self._ctx.event_loop).result()

    def __await__(self) -> Generator[Any, None, Any]:
        return self._ctx.await_promise(self).__await__()


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


class ObjectFactoryImpl:
    def value_handle_to_python(  # noqa: C901, PLR0911, PLR0912
        self, ctx: Context, val_handle: ValueHandle
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
            return JSFunctionImpl(ctx, val_handle)
        if typ == _MiniRacerTypes.date:
            timestamp = val.double_val
            # JS timestamps are milliseconds. In Python we are in seconds:
            return datetime.fromtimestamp(timestamp / 1000.0, timezone.utc)
        if typ == _MiniRacerTypes.symbol:
            return JSSymbolImpl(ctx, val_handle)
        if typ in (_MiniRacerTypes.shared_array_buffer, _MiniRacerTypes.array_buffer):
            buf = _ArrayBufferByte * length
            cdata = buf.from_address(val.value_ptr)
            # Save a reference to the context to prevent garbage collection of the
            # backing store:
            cdata._origin = ctx  # noqa: SLF001
            result = memoryview(cdata)
            # Avoids "NotImplementedError: memoryview: unsupported format T{<B:b:}"
            # in Python 3.12:
            return result.cast("B")

        if typ == _MiniRacerTypes.promise:
            return JSPromiseImpl(ctx, val_handle)

        if typ == _MiniRacerTypes.array:
            return JSArrayImpl(ctx, val_handle)

        if typ == _MiniRacerTypes.object:
            return JSMappedObjectImpl(ctx, val_handle)

        raise JSConversionException

    def python_to_value_handle(  # noqa: PLR0911
        self, ctx: Context, obj: PythonJSConvertedTypes
    ) -> ValueHandle:
        if isinstance(obj, JSObjectImpl):
            # JSObjects originate from the V8 side. We can just send back the handle
            # we originally got. (This also covers derived types JSFunction, JSSymbol,
            # JSPromise, and JSArray.)
            return obj.raw_handle

        if obj is None:
            return ctx.create_intish_val(0, _MiniRacerTypes.null)
        if obj is JSUndefined:
            return ctx.create_intish_val(0, _MiniRacerTypes.undefined)
        if isinstance(obj, bool):
            return ctx.create_intish_val(1 if obj else 0, _MiniRacerTypes.bool)
        if isinstance(obj, int):
            if obj - 2**31 <= obj < 2**31:
                return ctx.create_intish_val(obj, _MiniRacerTypes.integer)

            # We transmit ints as int32, so "upgrade" to double upon overflow.
            # (ECMAScript numeric is double anyway, but V8 does internally distinguish
            # int types, so we try and preserve integer-ness for round-tripping
            # purposes.)
            # JS BigInt would be a closer representation of Python int, but upgrading
            # to BigInt would probably be surprising for most applications, so for now,
            # we approximate with double:
            return ctx.create_doublish_val(obj, _MiniRacerTypes.double)
        if isinstance(obj, float):
            return ctx.create_doublish_val(obj, _MiniRacerTypes.double)
        if isinstance(obj, str):
            return ctx.create_string_val(obj, _MiniRacerTypes.str_utf8)
        if isinstance(obj, datetime):
            # JS timestamps are milliseconds. In Python we are in seconds:
            return ctx.create_doublish_val(
                obj.timestamp() * 1000.0, _MiniRacerTypes.date
            )

        # Note: we skip shared array buffers, so for now at least, handles to shared
        # array buffers can only be transmitted from JS to Python.

        raise JSConversionException
