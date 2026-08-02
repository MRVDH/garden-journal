"""Tests for the dataset loader (dataset._load).

The loader must never raise: a missing or malformed file has to degrade to an
empty dataset rather than stop the integration from loading.
"""

from __future__ import annotations

from pathlib import Path

from custom_components.garden_companion.dataset import DATA_FILE, _load

_VALID = """\
- genus: Hydrangea
  species: paniculata
  names:
    nl: [Pluimhortensia]
    en: [Panicle hydrangea]
  source: https://example.org/snoeien
  windows:
    - when: { start: "02-15", end: "03-31" }
      description:
        nl: Snoei stevig terug.
        en: Cut back hard.
"""


def test_load_valid_file(tmp_path: Path) -> None:
    """A valid file parses into the expected records."""
    path = tmp_path / "species.yaml"
    path.write_text(_VALID, encoding="utf-8")
    species = _load(path)
    assert len(species) == 1
    assert species[0].key == ("Hydrangea", "paniculata")


def test_missing_file_returns_empty(tmp_path: Path) -> None:
    """A missing dataset yields no plants instead of raising."""
    assert _load(tmp_path / "nope.yaml") == []


def test_invalid_yaml_returns_empty(tmp_path: Path) -> None:
    """Malformed YAML yields no plants instead of raising."""
    path = tmp_path / "species.yaml"
    path.write_text("genus: [unclosed\n", encoding="utf-8")
    assert _load(path) == []


def test_schema_errors_return_empty(tmp_path: Path) -> None:
    """A well-formed YAML file that breaks the schema yields no plants."""
    path = tmp_path / "species.yaml"
    path.write_text("- genus: Hydrangea\n", encoding="utf-8")
    assert _load(path) == []


def test_packaged_dataset_is_valid() -> None:
    """The shipped dataset parses cleanly. _load returns [] on any error."""
    assert _load(DATA_FILE)
