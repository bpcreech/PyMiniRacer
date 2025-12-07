from __future__ import annotations

from py_mini_racer import MiniRacer
from tests.gc_check import assert_no_v8_objects


def test_heap_stats() -> None:
    mr = MiniRacer()

    assert mr.heap_stats()["used_heap_size"] > 0
    assert mr.heap_stats()["total_heap_size"] > 0

    assert_no_v8_objects(mr)
