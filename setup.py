from __future__ import annotations

from pathlib import Path

from packaging.tags import platform_tags
from setuptools import setup
from wheel.bdist_wheel import bdist_wheel  # type: ignore[import-untyped]


def _get_platform_tag() -> str:
    """Return a pip platform tag indicating compatibility of the mini_racer binary.

    See https://packaging.python.org/en/latest/specifications/platform-compatibility-tags/.
    """

    # generally return the first, meaning the most-specific, platform tag:
    tag = next(platform_tags())

    if tag.startswith("macosx_"):
        # pip seems finicky about platform tags with larger macos versions, so just
        # tell arm64 is 11.0 and everything is is 10.9:
        if tag.endswith("_arm64"):
            return "macosx_11_0_arm64"

        return "macosx_10_9_x86_64"

    if tag.startswith("manylinux_"):
        # The v8 build process bundles its own Linux sysroots which work on Linuxes at
        # least this old (regardless of the platform we build on):
        if tag.endswith("_aarch64"):
            return "manylinux_2_27_aarch64"

        return "manylinux_2_27_x86_64"

    return tag


# From https://stackoverflow.com/questions/76450587/python-wheel-that-includes-shared-library-is-built-as-pure-python-platform-indep:
class PyMiniRacerBDistWheel(bdist_wheel):  # type: ignore[misc]
    def finalize_options(self) -> None:
        super().finalize_options()
        self.root_is_pure = False

    def get_tag(self) -> tuple[str, str, str]:
        return "py3", "none", _get_platform_tag()

    def run(self) -> None:
        mini_racer_src_dir = Path(__file__).parent / "src" / "py_mini_racer"
        if (
            not (mini_racer_src_dir / "mini_racer.dll").exists()
            and not (mini_racer_src_dir / "libmini_racer.so").exists()
            and not (mini_racer_src_dir / "libmini_racer.dylib").exists()
        ):
            # PyMiniRacer does not support a traditional from-source pip build, because
            # the v8 build is generally very slow, fragile, has many external
            # dependencies (exactly *which* depends on your system), and furthermore for
            # many systems the only viable build option is to cross-compile from
            # *another* system.
            # The intent of PyMiniRacer project is to build for all major platforms from
            # the GitHub home, and publish binary wheels to pip, so that you do not need
            # to build the wheel from source yourself.
            # If you want to build PyMiniRacer, you should use PyMiniRacer's build
            # system, starting with `just build-dll`, on a supported platform.
            # If you have an architecture that PyMiniRacer does not yet provide a wheel
            # for, consider contributing a pull request to add it at:
            # https://github.com/bpcreech/PyMiniRacer.
            msg = "Run `just build-dll` before building a PyMiniRacer wheel."
            raise RuntimeError(msg)

        super().run()


def _generate_readme() -> str:
    return "\n".join(
        [
            (Path(__file__).parent / "README.md")
            .read_text(encoding="utf-8")
            .replace(
                "(py_mini_racer.png)",
                "(https://github.com/bpcreech/PyMiniRacer/raw/main/py_mini_racer.png)",
            ),
            """
## Release history
""",
            "\n".join(
                (Path(__file__).parent / "HISTORY.md")
                .read_text(encoding="utf-8")
                .splitlines()[1:]
            ).replace("\n## ", "\n### "),
        ]
    )


setup(
    long_description=_generate_readme(),
    long_description_content_type="text/markdown",
    cmdclass={"bdist_wheel": PyMiniRacerBDistWheel},
)
