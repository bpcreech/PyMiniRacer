from __future__ import annotations

from argparse import ArgumentParser
from dataclasses import dataclass
from functools import cache
from logging import DEBUG, basicConfig, getLogger
from os import environ, pathsep
from pathlib import Path
from platform import machine
from re import match
from shlex import join as shlexjoin
from shutil import copyfile, rmtree
from subprocess import check_call
from sys import executable, platform
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


# ruff: noqa: S603

basicConfig()
LOGGER = getLogger(__name__)
LOGGER.setLevel(DEBUG)
ROOT_DIR = Path(__file__).absolute().parents[1]
V8_VERSION = "branch-heads/14.3"


@cache
def is_win() -> bool:
    return platform.startswith("win")


@cache
def is_linux() -> bool:
    return platform == "linux"


@cache
def is_mac() -> bool:
    return platform == "darwin"


class UnknownArchError(RuntimeError):
    def __init__(self, arch: str) -> None:
        super().__init__(f"Unknown arch {arch!r}")


def get_local_v8_target_cpu() -> str:
    m = machine().lower()
    if m in ("arm64", "aarch64"):
        return "arm64"
    if m == "arm":
        return "arm"
    if (not m) or (match("(x|i[3-6]?)86$", m) is not None):
        return "ia32"
    if m in ("x86_64", "amd64"):
        return "x64"
    if m == "s390x":
        return "s390x"
    if m == "ppc64":
        return "ppc64"

    raise UnknownArchError(m)


@cache
def get_dll_filename() -> str:
    if is_mac():
        return "libmini_racer.dylib"

    if is_win():
        return "mini_racer.dll"

    return "libmini_racer.so"


@cache
def get_data_files_list() -> Sequence[Path]:
    """List the files which v8 builds and then needs at runtime."""

    return (
        # V8 i18n data:
        Path("icudtl.dat"),
        # And obviously, the V8 build itself:
        Path(get_dll_filename()),
    )


@cache
def get_workspace_path() -> Path:
    return (ROOT_DIR / "v8_workspace").absolute()


@cache
def get_depot_tools_path() -> Path:
    return get_workspace_path() / "depot_tools"


@cache
def get_v8_path() -> Path:
    return get_workspace_path() / "v8"


def run(*args: str, cwd: Path) -> None:
    LOGGER.debug("Calling: '%s' from working directory %s", shlexjoin(args), cwd)
    env = environ.copy()

    env["PATH"] = pathsep.join([str(get_depot_tools_path()), environ["PATH"]])
    env["DEPOT_TOOLS_WIN_TOOLCHAIN"] = "0"

    # vpython is V8's Python environment manager; it downloads Python binaries
    # dynamically. This doesn't work on Alpine (because it downloads a glibc binary,
    # but needs a musl binary), so let's just disable it on all environments:
    env["VPYTHON_BYPASS"] = "manually managed python not supported by chrome operations"
    # Goma is a remote build system which we aren't using. depot_tools/autoninja.py
    # tries to run the goma client, which is checked into depot_tools as a glibc binary.
    # This fails on musl (on Alpine), so let's just disable the thing:
    env["GOMA_DISABLED"] = "1"

    check_call(args, env=env, cwd=cwd)


def ensure_depot_tools() -> None:
    if get_depot_tools_path().exists():
        LOGGER.debug("Using already cloned depot tools")
        return

    LOGGER.debug("Cloning depot tools")
    get_workspace_path().mkdir(parents=True, exist_ok=True)
    run(
        "git",
        "clone",
        "https://chromium.googlesource.com/chromium/tools/depot_tools.git",
        cwd=get_workspace_path(),
    )

    # depot_tools will auto-update when we run various commands. This creates extra
    # dependencies, e.g., on goma (which has trouble running on Alpine due to musl).
    # We just created a fresh single-use depot_tools checkout. There is no reason to
    # update it, so let's just disable that functionality:
    (get_depot_tools_path() / ".disable_auto_update").write_text("")

    if is_win():
        # Create git.bit and maybe other shortcuts used by the Windows V8 build tools:
        run(
            str(get_depot_tools_path() / "bootstrap" / "win_tools.bat"),
            cwd=get_depot_tools_path(),
        )


def ensure_v8_src(revision: str) -> None:
    """Ensure that v8 src are present and up-to-date."""

    # We create our own .gclient config instead of creating it via fetch.py so we can
    # control (non-)installation of a sysroot.
    gclient_file = get_workspace_path() / ".gclient"
    if not gclient_file.exists():
        get_workspace_path().mkdir(parents=True, exist_ok=True)

        gclient_file.write_text(
            """\
solutions = [
  { "name"        : "v8",
    "url"         : "https://chromium.googlesource.com/v8/v8.git",
    "deps_file"   : "DEPS",
    "managed"     : False,
    "custom_deps" : {},
    "custom_vars": {},
  },
]
""",
        )

    run(
        executable,
        str(get_depot_tools_path() / "gclient.py"),
        "sync",
        "--revision",
        f"v8@{revision}",
        cwd=get_workspace_path(),
    )

    link_name = get_v8_path() / "custom_deps" / "mini_racer"
    link_name.unlink(missing_ok=True)

    link_name.symlink_to(
        (ROOT_DIR / "src" / "v8_py_frontend").absolute(), target_is_directory=True
    )


def apply_patch(name: str) -> None:
    patch_filename = (ROOT_DIR / "builder" / name).absolute()

    applied_patches_filename = (ROOT_DIR / "builder" / ".applied_patches").absolute()

    if not applied_patches_filename.exists():
        applied_patches_filename.write_text("")

    with applied_patches_filename.open("r+") as f:
        applied_patches = set(f.read().splitlines())

        if str(patch_filename) in applied_patches:
            return

        run("patch", "-p0", "-i", str(patch_filename), cwd=get_v8_path())

        f.write(str(patch_filename) + "\n")


def run_build(build_dir: Path, args: Args) -> None:
    """Run the actual v8 build."""

    # As explained in the design principles in ARCHITECTURE.md, we want to reduce the
    # surface area of the V8 build system which PyMiniRacer depends upon. To accomodate
    # that goal, we run with as few non-default build options as possible.

    # The standard developer guide for V8 suggests we use the v8/tools/dev/v8gen.py
    # tool to both generate args.gn, and run gn to generate Ninja build files.

    # Unfortunately, v8/tools/dev/v8gen.py is unhappy about being run on non-amd64
    # architecture (it seems to think we're always cross-compiling from amd64). Thus
    # we reproduce what it does, which for our simple case devolves to just generating
    # args.gn with minimal arguments, and running "gn gen ...".

    target_cpu = args.target_cpu or get_local_v8_target_cpu()

    opts = {
        # These following settings are based those found for the "x64.release"
        # configuration. This can be verified by running:
        # tools/mb/mb.py lookup -b x64.release -m developer_default
        # ... from within the v8 directory.
        "is_debug": "false",
        "v8_use_external_startup_data": "false",
        "v8_monolithic": "true",
        # From https://groups.google.com/g/v8-users/c/qDJ_XYpig_M/m/qe5XO9PZAwAJ:
        "v8_monolithic_for_shared_library": "true",
        "target_cpu": f'"{target_cpu}"',
        "v8_target_cpu": f'"{target_cpu}"',
        # We sneak our C++ frontend into V8 as a symlinked "custom_dep" so
        # that we can reuse the V8 build system to make our dynamic link
        # library:
        "v8_custom_deps": '"//custom_deps/mini_racer"',
    }

    if is_linux() and target_cpu != get_local_v8_target_cpu():
        run(
            executable,
            "build/linux/sysroot_scripts/install-sysroot.py",
            "--arch=" + target_cpu,
            cwd=get_v8_path(),
        )

    args_text = "\n".join(f"{n}={v}" for n, v in opts.items())
    args_gn = f"""\
# This file is auto-generated by v8_build.py
{args_text}
"""

    LOGGER.info(f"Writing args.gn:\n{args_gn}")  # noqa: G004

    build_dir.mkdir(parents=True, exist_ok=True)
    Path(build_dir / "args.gn").write_text(args_gn, encoding="utf-8")

    # Now generate Ninja build files:
    run(
        executable,
        str(get_depot_tools_path() / "gn.py"),
        "gen",
        str(build_dir),
        "--check",
        cwd=get_v8_path(),
    )

    # Finally, actually do the build:
    run(
        executable,
        str(get_depot_tools_path() / "ninja.py"),
        # "-vv",  # too much spam for GitHub Actions
        "-C",
        str(build_dir),
        str(Path("custom_deps") / "mini_racer"),
        cwd=get_v8_path(),
    )


@dataclass(frozen=True)
class Args:
    target_cpu: str | None
    out_path: Path
    v8_revision: str
    fetch_only: bool
    skip_fetch: bool


def build_v8(args: Args) -> None:
    revision = args.v8_revision or V8_VERSION

    ensure_depot_tools()

    if not args.skip_fetch:
        ensure_v8_src(revision)

    if args.fetch_only:
        return

    build_dir = get_v8_path() / "out.gn" / "build"

    run_build(build_dir, args)

    # Fish out the build artifacts:
    args.out_path.mkdir(parents=True, exist_ok=True)

    for f in get_data_files_list():
        src = build_dir / f
        dst = args.out_path / f

        LOGGER.debug("Copying build artifact %s to %s", src, dst)
        dst.unlink(missing_ok=True)
        copyfile(src, dst)

    LOGGER.debug("Build complete!")


def clean_v8(out_path: Path) -> None:
    for f in get_data_files_list():
        (out_path / f).unlink(missing_ok=True)

    rmtree(get_workspace_path(), ignore_errors=True)


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("--target-cpu", help="v8 target cpu")
    parser.add_argument(
        "--out-path",
        type=Path,
        default=str(Path("src") / "py_mini_racer"),
        help="Build destination directory",
    )
    parser.add_argument("--v8-revision", default=V8_VERSION)
    parser.add_argument("--fetch-only", action="store_true", help="Only fetch V8")
    parser.add_argument("--skip-fetch", action="store_true", help="Do not fetch V8")
    args = parser.parse_args()
    build_v8(Args(**vars(args)))
