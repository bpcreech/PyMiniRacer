lint:
    uv lock --check

    uv run --dev mypy .

    uv run --dev ruff format --check

    uv run --dev ruff check

    npx prettier --check .

    uv run --dev mkdocs build --strict

    clang-format --style=Chromium -i src/v8_py_frontend/*.cc src/v8_py_frontend/*.h --dry-run -Werror

clang-tidy:
    uv run --dev builder/v8_build.py --fetch-only

    # Things we're disabling:
    # lvmlibc-* is intended for the llvm project itself
    # llvm-header-guard is likewise hard-coded for the llvm project itself
    # llvm-include-order fights clang-format --style=Chromium
    # fuchsia has some odd opinions, so disable it globally.
    # altera-* is designed for FPGAs and gives weird performance advice.
    # we aren't using Google's absl lib, so disable its suggestions.
    clang-tidy \
          -checks=*,-llvmlibc-*,-llvm-header-guard,-llvm-include-order,-fuchsia-*,-altera-*,-abseil-* \
          -warnings-as-errors=* \
          -extra-arg-before=-xc++ \
          -extra-arg=-std=c++20 \
          -extra-arg=-stdlib=libstdc++ \
          -extra-arg=-isystem \
          -extra-arg=v8_workspace/v8/include \
          -extra-arg=-DV8_ENABLE_SANDBOX \
          -extra-arg=-DV8_COMPRESS_POINTERS \
          src/v8_py_frontend/*.cc \
          src/v8_py_frontend/*.h

fix:
    uv lock

    uv run --dev ruff format

    npx prettier --write .

    clang-format --style=Chromium -i src/v8_py_frontend/*.cc src/v8_py_frontend/*.h

serve-docs:
    uv run --dev mkdocs serve

deploy-docs:
    uv run --dev mkdocs gh-deploy --force

build:
    # We build v8 outside of the Python packaging system because it's not
    # linking with the C Python API (so the Python packaging system doesn't
    # provide a lot of value), and the build is very time-consuming and
    # fragile, which makes the Python build idioms (including, e.g., uv's
    # way of building in a temporary isolated environment every time) very
    # awkward.
    uv sync --no-install-project
    uv run --no-project builder/v8_build.py

    uv build

test:
    uv run --dev pytest tests

test-matrix:
    uv run --dev --python 3.10 pytest tests
    uv run --dev --python 3.11 pytest tests
    uv run --dev --python 3.12 pytest tests
    uv run --dev --python 3.13 pytest tests
    uv run --dev --python 3.14 pytest tests

git-config-global:
    git config --global core.symlinks true
    git config --global user.name 'github-actions[bot]'
    git config --global user.email '41898282+github-actions[bot]@users.noreply.github.com'
