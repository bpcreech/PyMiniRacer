from __future__ import annotations

import asyncio
import gc
from time import sleep, time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from py_mini_racer import MiniRacer


_GC_WAIT_SECS = 5


def assert_no_v8_objects(mr: MiniRacer) -> None:
    """Test helper for garbage collection.

    PyMiniRacer does somewhat tricky things with object lifecycle management
    (basically, various __del__ methods, backed by C++ keeping its own track of
    all allocated objects). This is a somewhat kludgey test helper to verify
    those tricks are working.

    The Python gc doesn't seem particularly deterministic, so we do multiple
    collects and a sleep here to reduce the test flake rate.
    """

    ctx = mr._ctx  # noqa: SLF001
    assert ctx is not None

    start = time()
    while time() - start < _GC_WAIT_SECS and ctx.value_count() != 0:
        gc.collect()
        sleep(0.05)

    # Thus should only be reachable if we forgot to wrap an incoming pointer with a
    # ValueHandle (because ValueHandle.__del__ should otherwise take care of disposing
    # the C++ object):
    assert ctx.value_count() == 0, "Foud uncollected Values on the C++ side"


async def async_assert_no_v8_objects(mr: MiniRacer) -> None:
    """See assert_no_v8_objects."""

    ctx = mr._ctx  # noqa: SLF001
    assert ctx is not None

    start = time()
    while time() - start < _GC_WAIT_SECS and ctx.value_count() != 0:
        gc.collect()
        await asyncio.sleep(0.05)

    # Thus should only be reachable if we forgot to wrap an incoming pointer with a
    # ValueHandle (because ValueHandle.__del__ should otherwise take care of disposing
    # the C++ object):
    assert ctx.value_count() == 0, "Foud uncollected Values on the C++ side"
