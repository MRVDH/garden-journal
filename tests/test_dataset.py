"""Tests for the dataset schema and validator (models.build_dataset).

Pure logic over Python structures, no Home Assistant involved. Each negative
test mutates a copy of one valid record so the failure under test is the only
thing wrong.
"""

from __future__ import annotations

from typing import Any

from custom_components.garden_companion.models import Species, Window, build_dataset


def _valid_row() -> dict[str, Any]:
    """Return a minimal well-formed record, copied per test and mutated."""
    return {
        "genus": "Hydrangea",
        "species": "paniculata",
        "names": {"nl": ["Pluimhortensia"], "en": ["Panicle hydrangea"]},
        "source": "https://example.org/snoeien",
        "windows": [
            {
                "when": {"start": "02-15", "end": "03-31"},
                "description": {"nl": "Snoei stevig terug.", "en": "Cut back hard."},
            }
        ],
    }


def test_valid_row_builds_one_species() -> None:
    """A well-formed record parses into a Species with no errors."""
    species, errors = build_dataset([_valid_row()])
    assert errors == []
    assert len(species) == 1
    assert isinstance(species[0], Species)
    assert species[0].key == ("Hydrangea", "paniculata")
    assert species[0].windows[0] == Window(
        start="02-15",
        end="03-31",
        description={"nl": "Snoei stevig terug.", "en": "Cut back hard."},
    )


def test_missing_dutch_name_is_rejected() -> None:
    """A missing nl name is rejected."""
    row = _valid_row()
    del row["names"]["nl"]
    _, errors = build_dataset([row])
    assert any("names" in error and "nl" in error for error in errors)


def test_unquoted_no_language_key_is_rejected() -> None:
    """PyYAML turns `no:` into the boolean False; that must be caught."""
    row = _valid_row()
    row["names"][False] = ["Blahortensia"]
    _, errors = build_dataset([row])
    assert any("not a string" in error for error in errors)


def test_feb_29_is_rejected() -> None:
    """02-29 is not an annual date."""
    row = _valid_row()
    row["windows"][0]["when"]["start"] = "02-29"
    _, errors = build_dataset([row])
    assert any("02-29" in error for error in errors)


def test_out_of_range_mmdd_is_rejected() -> None:
    """A month above 12 is not a valid MM-DD."""
    row = _valid_row()
    row["windows"][0]["when"]["end"] = "13-01"
    _, errors = build_dataset([row])
    assert any("MM-DD" in error for error in errors)


def test_unquoted_when_is_rejected() -> None:
    """A bare date parses as a non-string and must be rejected."""
    row = _valid_row()
    row["windows"][0]["when"]["start"] = 215
    _, errors = build_dataset([row])
    assert any("MM-DD" in error for error in errors)


def test_year_wrapping_window_is_allowed() -> None:
    """An end before start wraps the year and is supported (2.4)."""
    row = _valid_row()
    row["windows"][0]["when"] = {"start": "12-01", "end": "02-28"}
    species, errors = build_dataset([row])
    assert errors == []
    assert species[0].windows[0].start == "12-01"


def test_missing_source_is_rejected() -> None:
    """A missing source is rejected (2.3)."""
    row = _valid_row()
    del row["source"]
    _, errors = build_dataset([row])
    assert any("source" in error for error in errors)


def test_no_windows_is_rejected() -> None:
    """Every row needs at least one window (2.3)."""
    row = _valid_row()
    row["windows"] = []
    _, errors = build_dataset([row])
    assert any("window" in error.lower() for error in errors)


def test_window_missing_dutch_description_is_rejected() -> None:
    """Every window needs description.nl and description.en (2.4)."""
    row = _valid_row()
    del row["windows"][0]["description"]["nl"]
    _, errors = build_dataset([row])
    assert any("description" in error and "nl" in error for error in errors)


def test_duplicate_key_is_rejected() -> None:
    """(genus, species) must be unique (2.3)."""
    _, errors = build_dataset([_valid_row(), _valid_row()])
    assert any("duplicate" in error.lower() for error in errors)


def test_disallowed_language_is_rejected() -> None:
    """Language codes come from an explicit allowlist (2.8)."""
    row = _valid_row()
    row["names"]["fr"] = ["Hortensia paniculte"]
    _, errors = build_dataset([row])
    assert any("allowlist" in error for error in errors)


def test_a_genus_row_needs_no_species() -> None:
    """A row without a species is the genus-level answer, keyed on the genus alone."""
    row = {
        "genus": "Rosa",
        "names": {"nl": ["Roos"], "en": ["Rose"]},
        "source": "https://example.org/rozen",
        "windows": [
            {
                "when": {"start": "03-01", "end": "03-31"},
                "description": {"nl": "Snoei.", "en": "Prune."},
            }
        ],
    }
    species, errors = build_dataset([row])
    assert errors == []
    assert species[0].key == ("Rosa", None)


def test_an_unknown_field_is_ignored() -> None:
    """A field the schema does not know is passed over rather than failing the row.

    The dataset outlives any one version of the code, so an older install reading a
    newer file keeps working.
    """
    row = _valid_row()
    row["variant"] = "bush"
    species, errors = build_dataset([row])
    assert errors == []
    assert species[0].key == ("Hydrangea", "paniculata")


def test_image_without_url_is_rejected() -> None:
    """An image, where present, must have a url (2.8)."""
    row = _valid_row()
    row["image"] = {"author": "Someone"}
    _, errors = build_dataset([row])
    assert any("image" in error and "url" in error for error in errors)


def test_synonym_colliding_with_a_genus_row_is_rejected() -> None:
    """A synonym must not collide with an existing genus row key (2.8)."""
    other = {
        "genus": "Buddleja",
        "names": {"nl": ["Vlinderstruik"], "en": ["Butterfly bush"]},
        "synonyms": ["Hydrangea"],
        "source": "https://example.org/buddleja",
        "windows": [
            {
                "when": {"start": "02-15", "end": "03-31"},
                "description": {"nl": "Snoei.", "en": "Prune."},
            }
        ],
    }
    _, errors = build_dataset([_valid_row(), other])
    assert any("synonym" in error.lower() for error in errors)


def test_empty_dataset_is_rejected() -> None:
    """An empty file is not a valid dataset."""
    _, errors = build_dataset(None)
    assert errors
