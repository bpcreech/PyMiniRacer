from __future__ import annotations

from typing import TYPE_CHECKING, NewType

if TYPE_CHECKING:
    from collections.abc import Callable

RawValueHandleType = NewType("RawValueHandleType", object)


class ValueHandle:
    """An object which holds open a Python reference to a _RawValue owned by
    a C++ MiniRacer context.

    Upon construction, immediately assumes ownership of the handle. To avoid
    memory leaks, any raw handles received from the MiniRacer DLL should
    generally be wrapped in a ValueHandle as early as possible."""

    def __init__(self, free: Callable[[], None], raw: RawValueHandleType) -> None:
        self._free = free
        self._raw = raw

    def __del__(self) -> None:
        self._free()

    @property
    def raw(self) -> RawValueHandleType:
        return self._raw
