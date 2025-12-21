"""Basic JS call functions"""

from __future__ import annotations

from datetime import datetime, timezone
from json import JSONEncoder
from typing import Any

from py_mini_racer import MiniRacer
from tests.gc_check import assert_no_v8_objects


def test_call_js() -> None:
    js_func = """var f = function() {
        return arguments.length;
    }"""

    mr = MiniRacer()
    mr.eval(js_func)

    assert mr.call("f") == 0
    assert mr.call("f", *list(range(5))) == 5  # noqa: PLR2004
    assert mr.call("f", *list(range(10))) == 10  # noqa: PLR2004
    assert mr.call("f", *list(range(20))) == 20  # noqa: PLR2004

    assert_no_v8_objects(mr)


def test_call_custom_encoder() -> None:
    # Custom encoder for dates
    class CustomEncoder(JSONEncoder):
        def default(self, obj: Any) -> str:  # noqa: ANN401
            if isinstance(obj, datetime):
                return obj.isoformat()

            return str(JSONEncoder.default(self, obj))

    now = datetime.now(tz=timezone.utc)
    mr = MiniRacer()
    mr.eval("""var f = function(args) {
        return args;
    }""")
    assert mr.call("f", now, encoder=CustomEncoder) == now.isoformat()

    assert_no_v8_objects(mr)
