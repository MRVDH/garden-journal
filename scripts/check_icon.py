#!/usr/bin/env python3
"""Check the rendered brand icons sit square on their canvas.

The artwork once sat 11px right and 19px below centre, with a 52px left margin
against 29px on the right. Nobody spots that on a rounded square until it is
pointed out, and by then it has shipped, so this measures it instead of trusting
an eye.

It reads the committed PNGs rather than re-rendering the SVG, which keeps it free
of cairosvg (deliberately not a dev dependency, see scripts/render_icon.py) and
means it checks the files Home Assistant and HACS actually serve. Pillow comes in
with homeassistant, so this needs nothing extra installed.

Prints every problem and exits non-zero when there are any.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

_BRAND = (
    Path(__file__).resolve().parent.parent
    / "custom_components"
    / "garden_journal"
    / "brand"
)

# The sizes render_icon.py writes. A file at the wrong size means the two have
# drifted apart.
EXPECTED = {"icon.png": 256, "icon@2x.png": 512}

# How far the opposing margins may disagree, as a share of the canvas edge.
# Antialiasing moves an edge by a pixel or so, and a difference that small is
# invisible, so a flat pixel count would either nag at 256px or miss at 512px.
TOLERANCE = 0.01

# A pixel counts as artwork when it is opaque and differs from the background by
# more than this, summed across the channels. Low enough to catch the soft edge of
# an antialiased stroke, high enough to ignore compression noise.
COLOUR_DELTA = 24

# Alpha below this is a transparent corner of the rounded square, not artwork.
OPAQUE = 200


class Measurement:
    """The artwork's bounding box and margins within one rendered icon."""

    def __init__(self, path: Path, image: Image.Image) -> None:
        """Measure the artwork in an already-opened RGBA image."""
        self.path = path
        self.width, self.height = image.size
        pixels = image.load()
        # Sampled near the top edge, between the rounded corners, where the
        # background is never covered by artwork.
        self.background = pixels[self.width // 2, 8][:3]

        columns = set()
        rows = set()
        for y in range(self.height):
            for x in range(self.width):
                red, green, blue, alpha = pixels[x, y]
                if alpha <= OPAQUE:
                    continue
                difference = sum(
                    abs(a - b)
                    for a, b in zip((red, green, blue), self.background, strict=True)
                )
                if difference > COLOUR_DELTA:
                    columns.add(x)
                    rows.add(y)

        self.empty = not columns
        if self.empty:
            return
        self.left = min(columns)
        self.right = self.width - 1 - max(columns)
        self.top = min(rows)
        self.bottom = self.height - 1 - max(rows)
        self.artwork_width = max(columns) - min(columns) + 1
        self.artwork_height = max(rows) - min(rows) + 1

    def problems(self) -> list[str]:
        """Return every way this icon is off, or an empty list when it is square."""
        name = self.path.name
        if self.empty:
            return [f"{name}: no artwork found, the canvas is one flat colour"]

        expected = EXPECTED[name]
        problems = []
        if (self.width, self.height) != (expected, expected):
            problems.append(
                f"{name}: rendered {self.width}x{self.height}, expected "
                f"{expected}x{expected}. Re-run scripts/render_icon.py"
            )

        allowed = max(1, round(self.width * TOLERANCE))
        horizontal = abs(self.left - self.right)
        vertical = abs(self.top - self.bottom)
        if horizontal > allowed:
            problems.append(
                f"{name}: {horizontal}px more margin on one side than the other "
                f"(left {self.left}, right {self.right}), over the {allowed}px allowed"
            )
        if vertical > allowed:
            problems.append(
                f"{name}: {vertical}px more margin above than below or vice versa "
                f"(top {self.top}, bottom {self.bottom}), over the {allowed}px allowed"
            )
        return problems

    def report(self) -> str:
        """Return a one-line summary of where the artwork sits."""
        if self.empty:
            return f"{self.path.name}: empty"
        share = self.artwork_width / self.width
        return (
            f"{self.path.name} {self.width}x{self.height}: artwork "
            f"{self.artwork_width}x{self.artwork_height} ({share:.0%} of the canvas), "
            f"margins left {self.left} right {self.right} "
            f"top {self.top} bottom {self.bottom}"
        )


def measure(path: Path) -> Measurement:
    """Open one rendered icon and measure it."""
    with Image.open(path) as image:
        return Measurement(path, image.convert("RGBA"))


def main(argv: list[str] | None = None) -> int:
    """Measure every expected icon and report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--brand",
        type=Path,
        default=_BRAND,
        help="directory holding the rendered icons",
    )
    args = parser.parse_args(argv)

    problems: list[str] = []
    for name in EXPECTED:
        path = args.brand / name
        if not path.exists():
            problems.append(f"{name}: missing. Run scripts/render_icon.py")
            continue
        measurement = measure(path)
        print(measurement.report())
        problems.extend(measurement.problems())

    if problems:
        print()
        for problem in problems:
            print(f"error: {problem}")
        return 1
    print("\nOK: both icons sit square on their canvas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
