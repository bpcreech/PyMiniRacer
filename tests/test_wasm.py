"""Test executing a WASM module."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from py_mini_racer import MiniRacer
from tests.gc_check import assert_no_v8_objects

test_dir = Path(__file__).parent


def test_add() -> None:
    fn = test_dir / "add.wasm"
    mr = MiniRacer()

    # 1. Allocate a buffer to hold the WASM module code
    size = Path(fn).stat().st_size
    module_raw = cast(
        "memoryview",
        mr.eval(
            f"""
    const moduleRaw = new SharedArrayBuffer({size});
    moduleRaw
    """
        ),
    )

    # 2. Read the WASM module code
    with Path(fn).open("rb") as f:
        assert f.readinto(module_raw) == size

    # 3. Instantiate the WASM module
    mr.eval(
        """
    var res = null;
    WebAssembly.instantiate(new Uint8Array(moduleRaw)).then(result => {
        res = result.instance;
    }).catch(result => { res = result.message; });
    """
    )

    # 4. Wait for WASM module instantiation
    while mr.eval("res") is None:
        pass

    assert mr.eval("typeof res !== 'string'")

    # 5. Execute a WASM function
    assert mr.eval("res.exports.addTwo(1, 2)") == 3  # noqa: PLR2004

    del module_raw
    assert_no_v8_objects(mr)
