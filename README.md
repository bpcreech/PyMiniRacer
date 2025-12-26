[![PyPI status indicator](https://img.shields.io/pypi/v/mini_racer.svg)](https://pypi.python.org/pypi/mini_racer)
[![Github workflow status indicator](https://github.com/bpcreech/PyMiniRacer/actions/workflows/build.yml/badge.svg)](https://github.com/bpcreech/PyMiniRacer/actions/workflows/build.yml)
[![ISC License](https://img.shields.io/badge/License-ISC-blue.svg)](https://opensource.org/licenses/ISC)

Minimal, modern embedded V8 for Python.

![MiniRacer logo: a V8 with a very snakey 8](py_mini_racer.png)

[Full documentation](https://bpcreech.com/PyMiniRacer/).

## In brief

- Latest ECMAScript support
- Web Assembly support
- Unicode support
- Thread safe
- Re-usable contexts

MiniRacer can be easily used by Django or Flask projects to minify assets, run babel or
WASM modules.

PyMiniRacer was created by [Sqreen](https://github.com/sqreen), and originally lived at
<https://github.com/sqreen/PyMiniRacer> with the PyPI package
[`py-mini-racer`](https://pypi.org/project/py-mini-racer/). After dicussion with the
original Sqreen team, [I](https://bpcreech.com) have created a new official home for at
<https://github.com/bpcreech/PyMiniRacer> with a new PyPI package
[`mini-racer`](https://pypi.org/project/mini-racer/) (_note: no `py-`_). See
[the full history](https://bpcreech.com/PyMiniRacer/history) for more.

## Examples

MiniRacer is straightforward to use:

```sh
    $ pip install mini-racer
```

and then:

```python
    $ python3
    >>> from py_mini_racer import MiniRacer
    >>> ctx = MiniRacer()
    >>> ctx.eval("1+1")
    2
    >>> ctx.eval("var x = {company: 'Sqreen'}; x.company")
    'Sqreen'
    >>> print(ctx.eval("'❤'"))
    ❤
    >>> ctx.eval("var fun = () => ({ foo: 1 });")
```

Variables are kept inside of a context:

```python
    >>> ctx.eval("x.company")
    'Sqreen'
```

You can evaluate whole scripts within JavaScript, or define and return JavaScript
function objects and call them from Python (_new in v0.11.0_):

```python
    >>> square = ctx.eval("a => a*a")
    >>> square(4)
    16
```

JavaScript Objects and Arrays are modeled in Python as dictionaries and lists (or, more
precisely,
[`MutableMapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableMapping)
and
[`MutableSequence`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableSequence)
instances), respectively (_new in v0.11.0_):

```python
    >>> obj = ctx.eval("var obj = {'foo': 'bar'}; obj")
    >>> obj["foo"]
    'bar'
    >>> list(obj.keys())
    ['foo']
    >>> arr = ctx.eval("var arr = ['a', 'b']; arr")
    >>> arr[1]
    'b'
    >>> 'a' in arr
    True
    >>> arr.append(obj)
    >>> ctx.eval("JSON.stringify(arr)")
    '["a","b",{"foo":"bar"}]'
```

Meanwhile, `call` uses JSON to transfer data between JavaScript and Python, and converts
data in bulk:

```python
    >>> ctx.call("fun")
    {'foo': 1}
```

Composite values are serialized using JSON. Use a custom JSON encoder when sending
non-JSON encodable parameters:

```python
    import json

    from datetime import datetime

    class CustomEncoder(json.JSONEncoder):

            def default(self, obj):
                if isinstance(obj, datetime):
                    return obj.isoformat()

                return json.JSONEncoder.default(self, obj)
```

```python
    >>> ctx.eval("var f = function(args) { return args; }")
    >>> ctx.call("f", datetime.now(), encoder=CustomEncoder)
    '2017-03-31T16:51:02.474118'
```

MiniRacer is ES6 capable:

```python
    >>> ctx.execute("[1,2,3].includes(5)")
    False
```

JavaScript `null` and `undefined` are modeled in Python as `None` and `JSUndefined`,
respectively:

```python
    >>> list(ctx.eval("[null, undefined]"))
    [None, JSUndefined]
```

You can prevent runaway execution in synchronous code using the `timeout_sec` parameter:

```python
    >>> ctx.eval('while (true) {}', timeout_sec=2)
    # Spins for 2 seconds and then emits a traceback ending with...
        raise JSTimeoutException from e
    py_mini_racer._exc.JSTimeoutException: JavaScript was terminated by timeout
    >>> func = ctx.eval('() => {while (true) {}}')
    >>> func(timeout_sec=2)
    # Spins for 2 seconds and then emits a traceback ending with...
        raise JSTimeoutException from e
    py_mini_racer._exc.JSTimeoutException: JavaScript was terminated by timeout
```

MiniRacer supports asynchronous execution using JS `Promise` instances (_new in
v0.10.0_):

```python
    >>> promise = ctx.eval(
    ...     "new Promise((res, rej) => setTimeout(() => res(42), 10000))")
    >>> promise.get()  # blocks for 10 seconds, and then:
    42
```

For more deterministic cleanup behavior, we strongly recommend allocating a MiniRacer
from a context manager (_new in v0.14.0_):

```python
    >>> from py_mini_racer import mini_racer
    >>> with mini_racer() as ctx:
    ...     print(ctx.eval("Array.from('foobar').reverse().join('')"))
    raboof
```

MiniRacer uses `asyncio` internally to manage V8. Both `MiniRacer()` and the
`mini_racer()` context manager will capture the currently-running event loop, or you can
specify a loop explicitly, and in non-async contexts, `MiniRacer` will launch its own
event loop with its own background thread to service it. (_new in v0.14.0_)

```python
    >>> from py_mini_racer import MiniRacer, mini_racer
    >>> ctx = MiniRacer()  # launches a new event loop in a new thread
    >>> with mini_racer() as ctx:  # same: launches a new event loop in a new thread
    ...     pass
    ...
    >>> async def demo():
    ...     with mini_racer() as ctx:  # reuses the running event loop
    ...         pass
    ...
    >>> import asyncio
    >>> asyncio.run(demo())
    >>> my_loop = asyncio.new_event_loop()
    >>> with mini_racer(my_loop) as ctx:  # uses the specified event loop
    ...     pass
```

When calling into MiniRacer from async code, you must await promises using `await`
(instead of `promise.get()`):

```python
    % python -m asyncio
    >>> from py_mini_racer import mini_racer
    >>> with mini_racer() as ctx:
    ...     promise = ctx.eval(
    ...         "new Promise((res, rej) => setTimeout(() => res(42), 10000))")
    ...     print(await promise)  # yields for 10 seconds, and then:
    ...
    42
```

`MiniRacer` does not support the `timeout_sec` parameter in async evaluation. Instead
request a cancelable evaluation and use a construct like `asyncio.wait_for`:

```python
    % python -m asyncio
    >>> from py_mini_racer import mini_racer
    >>> with mini_racer() as ctx:
    ...     # Use eval_cancelable(...), which has async semantics:
    ...     await asyncio.wait_for(ctx.eval_cancelable('while (true) {}'), timeout=2)
    # Spins for 2 seconds and then emits a traceback ending with...
        raise TimeoutError from exc_val
    TimeoutError
    >>> with mini_racer() as ctx:
    ...     func = ctx.eval('() => {while (true) {}}')
    ...     # Upgrade func using .cancelable(), which introduces async semantics:
    ...     cancelable_func = func.cancelable()
    ...     await asyncio.wait_for(cancelable_func(), timeout=2)
    # Spins for 2 seconds and then emits a traceback ending with...
        raise TimeoutError from exc_val
    TimeoutError
```

You can install callbacks from JavaScript to Python (_new in v0.12.0_). Only async
callbacks are supported:

```python
    % python -m asyncio
    >>> from py_mini_racer import mini_racer
    >>> async def read_file(fn):
    ...     with open(fn) as f:  # (or aiofiles would be even better here)
    ...         return f.read()
    ...
    >>> with mini_racer() as ctx:
    ...     async with ctx.wrap_py_function(read_file) as jsfunc:
    ...         # "Install" our (async) JS function on the global "this" object:
    ...         ctx.eval('this')['read_file'] = jsfunc
    ...         d = await ctx.eval('read_file("/usr/share/dict/words")')
    ...         print(d.split()[0:10])
    ['A', 'AA', 'AAA', "AA's", 'AB', 'ABC', "ABC's", 'ABCs', 'ABM', "ABM's"]
```

_Note that adding Python callbacks may degrade the security properties of PyMiniRacer!
See [PyMiniRacer's security goals](ARCHITECTURE.md#security-goals)._

MiniRacer supports [the ECMA `Intl` API](https://tc39.es/ecma402/):

```python
    # Indonesian dates!
    >>> ctx.eval('Intl.DateTimeFormat(["ban", "id"]).format(new Date())')
    '16/3/2024'
```

V8 heap information can be retrieved:

```python
    >>> ctx.heap_stats()
    {'total_physical_size': 1613896,
     'used_heap_size': 1512520,
     'total_heap_size': 3997696,
     'total_heap_size_executable': 3145728,
     'heap_size_limit': 1501560832}
```

A WASM example is available in the
[`tests`](https://github.com/bpcreech/PyMiniRacer/blob/master/tests/test_wasm.py).

## Compatibility

PyMiniRacer is compatible with Python 3.10-3.14 and is based on `ctypes`.

PyMiniRacer is distributed using [wheels](https://pythonwheels.com/) on
[PyPI](https://pypi.org/). The wheels are intended to provide compatibility with:

| OS                              | x86_64 | aarch64 |
| ------------------------------- | ------ | ------- |
| macOS ≥ 10.9                    | ✓      | ✓       |
| Windows ≥ 10                    | ✓      | ✓       |
| Ubuntu ≥ 20.04                  | ✓      | ✓       |
| Debian ≥ 11                     | ✓      | ✓       |
| RHEL ≥ 9                        | ✓      | ✓       |
| other Linuxes with glibc ≥ 2.27 | ✓      | ✓       |
| Alpine ≥ 3.19                   | ✓      | ✓       |
| other Linux with musl ≥ 1.2     | ✓      | ✓       |

In order to run on Alpine you must install `gcompat` and run with
`LD_PRELOAD="/lib/libgcompat.so.0"`.

If you have a up-to-date pip and it doesn't use a wheel, you might have an environment
for which no wheel is built. Please open an issue.

## Developing and releasing PyMiniRacer

See [the contribution guide](CONTRIBUTING.md).

## Credits

Built with love by [Sqreen](https://www.sqreen.com).

PyMiniRacer launch was described in
[`this blog post`](https://web.archive.org/web/20230526172627/https://blog.sqreen.com/embedding-javascript-into-python/).

PyMiniRacer is inspired by [mini_racer](https://github.com/SamSaffron/mini_racer), built
for the Ruby world by Sam Saffron.

In 2024, PyMiniRacer was revived, and adopted by [Ben Creech](https://bpcreech.com).
Upon discussion with the original Sqreen authors, we decided to re-launch PyMiniRacer as
a fork under <https://github.com/bpcreech/PyMiniRacer> and
<https://pypi.org/project/mini-racer/>.
