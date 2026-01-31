from __future__ import annotations

from py_mini_racer import MiniRacer
from tests.gc_check import assert_no_v8_objects


def test_heap_stats() -> None:
    mr = MiniRacer()

    assert mr.heap_stats()["used_heap_size"] > 0
    assert mr.heap_stats()["total_heap_size"] > 0

    assert_no_v8_objects(mr)


def test_heap_snapshot() -> None:
    mr = MiniRacer()

    assert mr.heap_snapshot()["edges"]
    assert mr.heap_snapshot()["strings"]

    assert_no_v8_objects(mr)


def test_no_handle_leak() -> None:
    mr = MiniRacer()

    big_obj_maker = "Array.from({ length: 1000000 }, (_, i) => i)"

    mr.eval(big_obj_maker)

    one_object_size = mr.heap_stats()["used_heap_size"]

    for _ in range(100):
        mr.eval(big_obj_maker)

    many_object_size = mr.heap_stats()["used_heap_size"]

    # It's okay if making a lot of big objects and disposing causes V8 to increase the
    # heap, but only to a point. Let it allocate 3x the memory for a repeated operation
    # that, in principle, uses a fixed amount of memory and freess it on every loop:
    allowable_ratio = 3
    assert many_object_size / one_object_size < allowable_ratio

    assert_no_v8_objects(mr)
