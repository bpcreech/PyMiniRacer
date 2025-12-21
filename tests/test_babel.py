"""Test loading and executing babel.js"""

from __future__ import annotations

from pathlib import Path

from py_mini_racer import MiniRacer
from tests.gc_check import assert_no_v8_objects


def test_babel() -> None:
    mr = MiniRacer()

    mr.eval(f"""
      var self = this;
      {(Path(__file__).parent / "fixtures" / "babel.js").read_text(encoding="utf-8")}
      babel.eval = function(code) {{
        return eval(babel.transform(code)["code"]);
      }}
    """)

    assert mr.eval("babel.eval(((x) => x * x)(8))") == 64  # noqa: PLR2004
    assert_no_v8_objects(mr)
