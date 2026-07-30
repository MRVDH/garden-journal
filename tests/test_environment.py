"""Guards against the development environment drifting from the pins.

These are not tests of the integration. They exist because the test plugin is
tied to one Home Assistant release, and a silent mismatch between the venv and
requirements-dev.txt produces import errors that look like code bugs.
"""

from __future__ import annotations

import sys
from pathlib import Path

from homeassistant.const import REQUIRED_PYTHON_VER, __version__

REQUIREMENTS = Path(__file__).parent.parent / "requirements-dev.txt"


def _pinned(package: str) -> str:
    """Return the version requirements-dev.txt pins for a package."""
    for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{package}=="):
            return line.split("==", 1)[1].strip()
    raise AssertionError(f"{package} is not pinned in requirements-dev.txt")


def test_home_assistant_matches_the_pin() -> None:
    """The installed Home Assistant is the version we pin to."""
    assert __version__ == _pinned("homeassistant")


def test_python_is_new_enough() -> None:
    """The interpreter satisfies Home Assistant's minimum."""
    assert sys.version_info[:3] >= REQUIRED_PYTHON_VER
