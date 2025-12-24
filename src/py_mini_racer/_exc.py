from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from py_mini_racer._types import PythonJSConvertedTypes


class MiniRacerBaseException(Exception):  # noqa: N818
    """Base MiniRacer exception."""


class JSEvalException(MiniRacerBaseException):
    """JavaScript could not be executed."""


class JSTimeoutException(JSEvalException, TimeoutError):  # noqa: N818
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


class JSParseException(JSEvalException):
    """JavaScript could not be parsed."""


class JSKeyError(JSEvalException, KeyError):
    """No such key found."""


class JSOOMException(JSEvalException):
    """JavaScript execution ran out of memory."""


class JSTerminatedException(JSEvalException):
    """JavaScript execution terminated."""


class JSValueError(JSEvalException, ValueError):
    """Bad value passed to JavaScript engine."""


class JSConversionException(MiniRacerBaseException):
    """Type could not be converted to or from JavaScript."""
