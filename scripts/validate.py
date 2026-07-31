#!/usr/bin/env python3
"""Validate the species dataset against the schema (2.8).

Runs in CI on every pull request and by hand while editing the dataset. It
prints every problem it finds and exits non-zero when there are any, so a broken
data change fails on GitHub rather than on a user's Pi. It never touches the
network: image URLs are not fetched, so CI cannot flake.

Two extra report modes are informational rather than pass or fail. `--duplicates`
groups rows whose window sets are identical, so the repeated blocks stay
mechanical to deduplicate. `--uncredited` lists rows with a photo that has no
author or licence, since credit is optional in the schema.
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

from models import Species, build_dataset, timing_signature  # noqa: E402

DEFAULT_PATH = _PACKAGE / "data" / "species.yaml"


def _key(species: Species) -> str:
    """Return a readable key for one record."""
    return " ".join(p for p in (species.genus, species.species, species.variant) if p)


def duplicate_groups(dataset: list[Species]) -> list[list[str]]:
    """Return groups of two or more rows that share an identical window set.

    Dates and descriptions both count, so Hydrangea macrophylla and aspera,
    which share dates but not instructions, are not grouped.
    """
    by_signature: dict[object, list[str]] = {}
    for species in dataset:
        by_signature.setdefault(timing_signature(species), []).append(_key(species))
    return [keys for keys in by_signature.values() if len(keys) > 1]


def uncredited(dataset: list[Species]) -> list[str]:
    """Return rows whose photo is missing an author or a licence."""
    return [
        _key(species)
        for species in dataset
        if species.image is not None
        and (species.image.author is None or species.image.licence is None)
    ]


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
    parser.add_argument(
        "--duplicates",
        action="store_true",
        help="Report rows that share an identical window set (informational)",
    )
    parser.add_argument(
        "--uncredited",
        action="store_true",
        help="Report photos missing an author or licence (informational)",
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

    if args.duplicates:
        groups = duplicate_groups(species)
        if groups:
            print(f"{len(groups)} repeated window block(s):")
            for group in groups:
                print(f"  - {', '.join(group)}")
        else:
            print("No repeated window blocks.")

    if args.uncredited:
        rows = uncredited(species)
        if rows:
            print(f"{len(rows)} photo(s) without full credit:")
            for row in rows:
                print(f"  - {row}")
        else:
            print("Every photo has an author and a licence.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
