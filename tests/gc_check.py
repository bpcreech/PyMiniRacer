from __future__ import annotations

import asyncio
import gc
from time import sleep, time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from py_mini_racer import MiniRacer
    from py_mini_racer._context import Context
    from py_mini_racer._mini_racer import AsyncMiniRacer


def assert_no_v8_objects(mr: MiniRacer) -> None:
    state = mr._state  # noqa: SLF001
    assert state is not None

    _assert_no_v8_objects(state.ctx)


async def async_assert_no_v8_objects(mr: AsyncMiniRacer) -> None:
    # Encourage asyncio to close out any dangling coroutines:
    await asyncio.sleep(0)

    _assert_no_v8_objects(mr._ctx)  # noqa: SLF001


def _assert_no_v8_objects(ctx: Context) -> None:
    """Test helper for garbage collection.

    PyMiniRacer does somewhat tricky things with object lifecycle management
    (basically, various __del__ methods, backed by C++ keeping its own track of
    all allocated objects). This is a somewhat kludgey test helper to verify
    those tricks are working.

    The Python gc doesn't seem particularly deterministic, so we do multiple
    collects and a sleep here to reduce the test flake rate.
    """
    start = time()
    while time() - start < 5 and ctx.value_count() != 0:  # noqa: PLR2004
        gc.collect()
        sleep(0.05)

    # Thus should only be reachable if we forgot to wrap an incoming pointer with a
    # ValueHandle (because ValueHandle.__del__ should otherwise take care of disposing
    # the C++ object):
    assert ctx.value_count() == 0, "Foud uncollected BinaryValues on the C++ side"
