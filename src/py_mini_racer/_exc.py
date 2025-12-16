from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from py_mini_racer._types import PythonJSConvertedTypes


class MiniRacerBaseException(Exception):  # noqa: N818
    """Base MiniRacer exception."""


class JSEvalException(MiniRacerBaseException):
    """JavaScript could not be executed."""


class JSTimeoutException(JSEvalException):
    """JavaScript execution timed out."""

    def __init__(self) -> None:
        super().__init__("JavaScript was terminated by timeout")


class JSPromiseError(MiniRacerBaseException):
    """JavaScript rejected a promise."""

    def __init__(self, reason: PythonJSConvertedTypes) -> None:
        super().__init__(f"JavaScript rejected promise with reason: {reason}\n")
        self.reason = reason


class JSArrayIndexError(IndexError, MiniRacerBaseException):
    """Invalid index into a JSArray."""

    def __init__(self) -> None:
        super().__init__("JSArray deletion out of range")
