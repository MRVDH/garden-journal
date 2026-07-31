#!/usr/bin/env python3
"""Render the brand icon from its SVG source to the PNG sizes HACS wants.

Run by hand after editing brand/icon.svg, then commit the PNGs; the rendered
files are what Home Assistant and HACS read. Needs cairosvg, which is not part of
the test toolchain:

    .venv/bin/python -m pip install cairosvg
    .venv/bin/python scripts/render_icon.py
"""

from __future__ import annotations

from pathlib import Path

import cairosvg

_BRAND = (
    Path(__file__).resolve().parent.parent
    / "custom_components"
    / "garden_companion"
    / "brand"
)
_SOURCE = _BRAND / "icon.svg"

# icon.png is required; icon@2x.png covers hDPI displays.
_SIZES = {"icon.png": 256, "icon@2x.png": 512}


def main() -> int:
    """Render every size and report what was written."""
    if not _SOURCE.exists():
        print(f"error: {_SOURCE} not found")
        return 1
    for name, size in _SIZES.items():
        target = _BRAND / name
        cairosvg.svg2png(
            url=str(_SOURCE),
            write_to=str(target),
            output_width=size,
            output_height=size,
        )
        print(f"wrote {target.name} at {size}x{size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
