#!/usr/bin/env python3
"""Validate the species dataset against the schema (2.8).

Runs in CI on every pull request and by hand while editing the dataset. It
prints every problem it finds and exits non-zero when there are any, so a broken
data change fails on GitHub rather than on a user's Pi. It never touches the
network: image URLs are not fetched, so CI cannot flake.

The `--duplicates` and `--uncredited` report modes in the plan are not built
yet; they are deferred to build step 11, where a large dataset makes them useful.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

# Import the schema from the integration package without triggering its
# __init__.py (which imports Home Assistant). Adding the package directory to
# the path lets us import models.py on its own, so validation stays fast and
# has no Home Assistant dependency, while the schema still lives in one place.
_PACKAGE = (
    Path(__file__).resolve().parent.parent / "custom_components" / "garden_companion"
)
sys.path.insert(0, str(_PACKAGE))

from models import build_dataset  # noqa: E402

DEFAULT_PATH = _PACKAGE / "data" / "species.yaml"


def main(argv: list[str] | None = None) -> int:
    """Validate the dataset file and report the outcome."""
    parser = argparse.ArgumentParser(
        description="Validate the Garden Companion species dataset."
    )
    parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=DEFAULT_PATH,
        help="Path to species.yaml (defaults to the packaged dataset)",
    )
    args = parser.parse_args(argv)

    if not args.path.exists():
        print(f"error: dataset not found at {args.path}")
        return 1
    try:
        raw = yaml.safe_load(args.path.read_text(encoding="utf-8"))
    except yaml.YAMLError as err:
        print(f"error: {args.path} is not valid YAML:\n{err}")
        return 1

    species, errors = build_dataset(raw)
    if errors:
        print(f"{len(errors)} problem(s) in {args.path}:")
        for message in errors:
            print(f"  - {message}")
        return 1

    print(f"OK: {len(species)} record(s) in {args.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
