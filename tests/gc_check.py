from __future__ import annotations

from gc import collect
from time import sleep, time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from py_mini_racer import MiniRacer


def assert_no_v8_objects(mr: MiniRacer) -> None:
    """Test helper for garbage collection.

    PyMiniRacer does somewhat tricky things with object lifecycle management
    (basically, various __del__ methods, backed by C++ keeping its own track of
    all allocated objects). This is a somewhat kludgey test helper to verify
    those tricks are working.

    The Python gc doesn't seem particularly deterministic, so we do 2 collects
    and a sleep here to reduce the flake rate.
    """
    start = time()
    while time() - start < 5 and mr._ctx.value_count() != 0:  # noqa: PLR2004, SLF001
        collect()
        sleep(0.05)

    assert mr._ctx.value_count() == 0  # noqa: SLF001
