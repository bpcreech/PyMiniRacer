from __future__ import annotations

from pathlib import Path
from platform import machine
from sys import platform

from packaging.tags import platform_tags
from setuptools import setup
from wheel.bdist_wheel import bdist_wheel  # type: ignore[import-untyped]


def _get_platform_tag() -> str:
    """Return a pip platform tag indicating compatibility of the mini_racer binary.

    See https://packaging.python.org/en/latest/specifications/platform-compatibility-tags/.
    """

    if platform == "darwin":
        # pip seems finicky about platform tags with larger macos versions, so just
        # tell arm64 is 11.0 and everything is is 10.9:
        if machine() == "arm64":
            return "macosx_11_0_arm64"

        return "macosx_10_9_x86_64"

    # return the first, meaning the most-specific, platform tag:
    return next(platform_tags())


# From https://stackoverflow.com/questions/76450587/python-wheel-that-includes-shared-library-is-built-as-pure-python-platform-indep:
class PyMiniRacerBDistWheel(bdist_wheel):  # type: ignore[misc]
    def finalize_options(self) -> None:
        super().finalize_options()
        self.root_is_pure = False

    def get_tag(self) -> tuple[str, str, str]:
        return "py3", "none", _get_platform_tag()


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
        ],
    )


setup(
    long_description=_generate_readme(),
    long_description_content_type="text/markdown",
    cmdclass={"bdist_wheel": PyMiniRacerBDistWheel},
)
