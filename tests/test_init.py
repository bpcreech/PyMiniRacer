from __future__ import annotations

from gc import collect
from re import match
from time import sleep, time

import pytest

from py_mini_racer import LibAlreadyInitializedError, MiniRacer, init_mini_racer
from py_mini_racer._context import context_count


def test_init() -> None:
    init_mini_racer(ignore_duplicate_init=True)

    with pytest.raises(LibAlreadyInitializedError):
        init_mini_racer()

    init_mini_racer(ignore_duplicate_init=True)


# Unfortunately while init_mini_racer allows changing V8 flags, it's hard to test
# automatically because only the first use of V8 can set flags. We'd need to
# restart Python between tests.
# Here's a manual test:
@pytest.mark.skip("Has to be run manually")
def test_init_flags() -> None:
    from py_mini_racer import (  # noqa: PLC0415
        DEFAULT_V8_FLAGS,
        MiniRacer,
        init_mini_racer,
    )

    init_mini_racer(flags=(*DEFAULT_V8_FLAGS, "--no-use-strict"))
    mr = MiniRacer()
    # this would normally fail in strict JS mode because foo is not declared:
    mr.eval("foo = 4")


def test_version() -> None:
    mr = MiniRacer()
    assert match(r"^\d+\.\d+\.\d+\.\d+$", mr.v8_version) is not None


def test_sandbox() -> None:
    mr = MiniRacer()
    assert mr._ctx.v8_is_using_sandbox()  # noqa: SLF001


def test_del() -> None:
    # Collect any leftover contexts:
    start = time()
    while time() - start < 10 and context_count() != 0:  # noqa: PLR2004
        collect()
        sleep(0.1)

    assert context_count() == 0

    mr = MiniRacer()
    del mr

    start = time()
    while time() - start < 10 and context_count() != 0:  # noqa: PLR2004
        collect()
        sleep(0.1)

    assert context_count() == 0


def test_interrupts_background_task_on_shutdown() -> None:
    with MiniRacer() as mr:
        # Schedule a never-ending background task:
        mr.eval("setTimeout(() => { while (1); }, 1);")
        # Make sure the task starts:
        sleep(0.1)
        # Now at the end of the with statement, we explicitly close the instance, which
        # should terminate the background task (as oppposed to hanging indefinitely
        # here).
