"""Tests for the resolver: normalisation, matching, ambiguity, search (2.6).

Pure logic, no Home Assistant. The datasets are built in the tests because the
shipped three-row fixture cannot exercise ambiguity or one-to-many common names.
"""

from __future__ import annotations

from typing import Any

from custom_components.garden_companion.models import Image, Window, build_dataset
from custom_components.garden_companion.resolver import (
    Resolver,
    normalise,
    repair_reason,
    resolve_photo,
    resolve_windows,
    timing_signature,
)


def _window(start: str, end: str, en: str, nl: str) -> dict[str, Any]:
    """Build one window dict."""
    return {"when": {"start": start, "end": end}, "description": {"nl": nl, "en": en}}


def _row(
    genus: str,
    windows: list[dict[str, Any]],
    *,
    species: str | None = None,
    names: dict[str, list[str]] | None = None,
    synonyms: list[str] | None = None,
) -> dict[str, Any]:
    """Build one record dict, defaulting the required fields."""
    row: dict[str, Any] = {
        "genus": genus,
        "names": names or {"nl": [genus.lower()], "en": [genus.lower()]},
        "source": "https://example.org",
        "windows": windows,
    }
    if species is not None:
        row["species"] = species
    if synonyms is not None:
        row["synonyms"] = synonyms
    return row


def _resolver(*rows: dict[str, Any]) -> Resolver:
    """Build a Resolver over rows, asserting the rows are valid first."""
    species, errors = build_dataset(list(rows))
    assert errors == []
    return Resolver(species)


_SPRING = _window("03-01", "04-15", "Cut back hard before growth.", "Snoei stevig.")
_APR_HARD = _window(
    "04-01", "04-30", "Cut back to a pair of buds.", "Snoei tot een knoppaar."
)
_APR_LIGHT = _window(
    "04-01", "04-30", "Dead wood only, do not cut back.", "Alleen dood hout."
)
_SUMMER = _window(
    "07-15", "08-31", "Trim in the growing season.", "Snoei in het groeiseizoen."
)


def test_normalise_strips_hybrid_quotes_and_case() -> None:
    """Hybrid markers, quotes, case and extra whitespace are removed."""
    assert normalise("Hydrangea × macrophylla") == "hydrangea macrophylla"  # noqa: RUF001
    assert normalise("Hydrangea x macrophylla") == "hydrangea macrophylla"
    assert (
        normalise("  Hydrangea  paniculata 'Limelight' ")
        == "hydrangea paniculata limelight"
    )


def test_normalise_keeps_x_inside_a_word() -> None:
    """An x inside a word (Ilex) is not a hybrid marker."""
    assert normalise("Ilex crenata") == "ilex crenata"


def test_resolve_exact_species() -> None:
    """An exact (genus, species) key resolves to that row."""
    resolver = _resolver(_row("Hydrangea", [_SPRING], species="paniculata"))
    match = resolver.resolve("Hydrangea", "paniculata")
    assert match is not None
    assert match.species == "paniculata"


def test_resolve_falls_back_to_the_genus_row() -> None:
    """An unknown species falls back to the genus-level row (2.6)."""
    resolver = _resolver(_row("Ligustrum", [_SUMMER]))
    match = resolver.resolve("Ligustrum", "ovalifolium")
    assert match is not None
    assert match.genus == "Ligustrum"


def test_resolve_a_species_asked_for_by_genus_alone() -> None:
    """Asking for a genus that only has a species row falls back to that row."""
    resolver = _resolver(_row("Hydrangea", [_SPRING], species="paniculata"))
    assert resolver.resolve("Hydrangea", "paniculata") is not None
    # There is no bare Hydrangea row, so the genus on its own resolves to nothing.
    assert resolver.resolve("Hydrangea") is None


def test_resolve_no_match_returns_none() -> None:
    """A genus not in the dataset resolves to nothing."""
    resolver = _resolver(_row("Hydrangea", [_SPRING], species="paniculata"))
    assert resolver.resolve("Wisteria") is None


def test_genus_is_ambiguous_when_species_disagree() -> None:
    """Hydrangea is ambiguous because its species rows disagree on timing."""
    resolver = _resolver(
        _row("Hydrangea", [_SPRING], species="paniculata"),
        _row("Hydrangea", [_APR_HARD], species="macrophylla"),
    )
    assert resolver.is_ambiguous("Hydrangea")


def test_same_dates_different_instruction_is_still_ambiguous() -> None:
    """Same dates with different instructions still count as distinct (macrophylla, aspera)."""
    resolver = _resolver(
        _row("Hydrangea", [_APR_HARD], species="macrophylla"),
        _row("Hydrangea", [_APR_LIGHT], species="aspera"),
    )
    assert resolver.is_ambiguous("Hydrangea")


def test_agreeing_species_are_not_ambiguous() -> None:
    """Two species rows sharing an identical window block are one answer."""
    resolver = _resolver(
        _row("Foo", [_SUMMER], species="a"),
        _row("Foo", [_SUMMER], species="b"),
    )
    assert not resolver.is_ambiguous("Foo")


def test_a_genus_row_is_never_ambiguous() -> None:
    """A genus-level row is a single answer, so the genus answers directly (2.6)."""
    resolver = _resolver(
        _row("Ligustrum", [_SUMMER]),
        _row("Ligustrum", [_APR_HARD], species="lucidum"),
    )
    assert not resolver.is_ambiguous("Ligustrum")


def test_search_by_botanical_name() -> None:
    """A botanical name matches its row and nothing else."""
    resolver = _resolver(_row("Hydrangea", [_SPRING], species="paniculata"))
    hits = resolver.search("Hydrangea paniculata")
    assert [h.species for h in hits] == ["paniculata"]


def test_search_by_common_name_in_any_language() -> None:
    """An English user typing the Dutch name still finds the plant."""
    resolver = _resolver(
        _row(
            "Hydrangea",
            [_SPRING],
            species="paniculata",
            names={"nl": ["Pluimhortensia"], "en": ["Panicle hydrangea"]},
        )
    )
    assert resolver.search("pluimhortensia")[0].species == "paniculata"
    assert resolver.search("Panicle hydrangea")[0].species == "paniculata"


def test_search_common_name_is_one_to_many() -> None:
    """A shared common name returns several rows, with the same timing here."""
    resolver = _resolver(
        _row(
            "Prunus",
            [_SUMMER],
            species="laurocerasus",
            names={"nl": ["Laurier"], "en": ["Cherry laurel"]},
        ),
        _row(
            "Laurus",
            [_SUMMER],
            species="nobilis",
            names={"nl": ["Laurier"], "en": ["Bay laurel"]},
        ),
    )
    hits = resolver.search("laurier")
    assert len(hits) == 2
    assert len({timing_signature(h) for h in hits}) == 1


def test_search_matches_a_common_name_substring() -> None:
    """Typing part of a compound common name finds all names containing it."""
    resolver = _resolver(
        _row(
            "Hydrangea",
            [_SPRING],
            species="paniculata",
            names={"nl": ["Pluimhortensia"], "en": ["Panicle hydrangea"]},
        ),
        _row(
            "Hydrangea",
            [_SPRING],
            species="arborescens",
            names={"nl": ["Sneeuwbalhortensia"], "en": ["Smooth hydrangea"]},
        ),
    )
    assert {h.species for h in resolver.search("hortensia")} == {
        "paniculata",
        "arborescens",
    }


def test_search_resolves_a_synonym() -> None:
    """A superseded botanical name resolves to the row that lists it."""
    resolver = _resolver(
        _row(
            "Buddleja",
            [_SUMMER],
            species="davidii",
            names={"nl": ["Vlinderstruik"], "en": ["Butterfly bush"]},
            synonyms=["Buddleia"],
        )
    )
    assert resolver.search("Buddleia")[0].genus == "Buddleja"


def test_search_ignores_the_cultivar() -> None:
    """A cultivar in the query is stripped; genus and species still match."""
    resolver = _resolver(_row("Weigela", [_SUMMER], species="florida"))
    hits = resolver.search("Weigela florida 'Bristol Ruby'")
    assert [h.species for h in hits] == ["florida"]


def test_search_unknown_returns_empty() -> None:
    """A name not in the dataset returns nothing."""
    resolver = _resolver(_row("Hydrangea", [_SPRING], species="paniculata"))
    assert resolver.search("Quercus robur") == []


def test_resolve_windows_for_a_dataset_plant() -> None:
    """A dataset plant resolves to its row's windows."""
    resolver = _resolver(_row("Hydrangea", [_SPRING], species="paniculata"))
    data = {
        "genus": "Hydrangea",
        "species": "paniculata",
        "in_dataset": True,
        "windows": None,
        "windows_like": None,
    }
    windows = resolve_windows(data, resolver)
    assert windows is not None
    assert windows[0].start == "03-01"


def test_resolve_windows_for_a_borrowed_plant() -> None:
    """A borrowed plant resolves to the windows_like row's windows."""
    resolver = _resolver(_row("Wisteria", [_SUMMER]))
    data = {
        "genus": "Quercus",
        "species": "robur",
        "in_dataset": False,
        "windows": None,
        "windows_like": {"genus": "Wisteria", "species": None},
    }
    windows = resolve_windows(data, resolver)
    assert windows is not None
    assert windows[0].start == "07-15"


def test_resolve_windows_for_an_authored_plant() -> None:
    """An authored plant uses its own stored windows."""
    resolver = _resolver(_row("Wisteria", [_SUMMER]))
    data = {
        "genus": "Quercus",
        "species": None,
        "in_dataset": False,
        "windows_like": None,
        "windows": [
            {"when": {"start": "05-01", "end": "05-31"}, "description": {"en": "Trim"}}
        ],
    }
    windows = resolve_windows(data, resolver)
    assert windows == [Window(start="05-01", end="05-31", description={"en": "Trim"})]


def test_resolve_windows_unknown_returns_none() -> None:
    """A stored key that no longer resolves yields None (a repair case)."""
    resolver = _resolver(_row("Hydrangea", [_SPRING], species="paniculata"))
    data = {
        "genus": "Quercus",
        "species": "robur",
        "in_dataset": True,
        "windows": None,
        "windows_like": None,
    }
    assert resolve_windows(data, resolver) is None


def test_resolve_photo_borrows_a_dataset_rows_image() -> None:
    """A dataset plant resolves to its row's image, credit included."""
    row = _row("Hydrangea", [_SPRING], species="paniculata")
    row["image"] = {
        "url": "https://example.org/h.jpg",
        "author": "A Photographer",
        "licence": "CC BY-SA 4.0",
    }
    resolver = _resolver(row)
    data = {
        "genus": "Hydrangea",
        "species": "paniculata",
        "in_dataset": True,
    }
    assert resolve_photo(data, resolver) == Image(
        url="https://example.org/h.jpg", author="A Photographer", licence="CC BY-SA 4.0"
    )


def test_resolve_photo_none_when_the_row_has_no_image() -> None:
    """A dataset plant whose row has no image resolves to no photo."""
    resolver = _resolver(_row("Hydrangea", [_SPRING], species="paniculata"))
    data = {
        "genus": "Hydrangea",
        "species": "paniculata",
        "in_dataset": True,
    }
    assert resolve_photo(data, resolver) is None


def test_resolve_photo_uses_a_manual_plants_bare_url() -> None:
    """A manual plant resolves to a bare image URL with no credit."""
    resolver = _resolver(_row("Hydrangea", [_SPRING], species="paniculata"))
    data = {"in_dataset": False, "image_url": "https://example.test/mine.jpg"}
    assert resolve_photo(data, resolver) == Image(url="https://example.test/mine.jpg")


def test_resolve_photo_none_for_a_manual_plant_without_a_url() -> None:
    """A manual plant with no image URL resolves to no photo."""
    resolver = _resolver(_row("Hydrangea", [_SPRING], species="paniculata"))
    data = {"in_dataset": False, "image_url": None}
    assert resolve_photo(data, resolver) is None


def test_repair_reason_none_when_the_plant_resolves() -> None:
    """A plant whose key still resolves needs no repair."""
    resolver = _resolver(_row("Hydrangea", [_SPRING], species="paniculata"))
    data = {
        "genus": "Hydrangea",
        "species": "paniculata",
        "in_dataset": True,
    }
    assert repair_reason(data, resolver) is None


def test_repair_reason_missing_row_for_a_gone_key() -> None:
    """A stored key that matches no row reports missing_row."""
    resolver = _resolver(_row("Hydrangea", [_SPRING], species="paniculata"))
    data = {"genus": "Quercus", "species": "robur", "in_dataset": True}
    assert repair_reason(data, resolver) == "missing_row"


def test_repair_reason_ambiguous_genus() -> None:
    """A bare genus that has gained a disagreeing species row reports ambiguity."""
    resolver = _resolver(
        _row("Hydrangea", [_APR_HARD], species="paniculata"),
        _row("Hydrangea", [_APR_LIGHT], species="aspera"),
    )
    data = {"genus": "Hydrangea", "species": None, "in_dataset": True}
    assert repair_reason(data, resolver) == "ambiguous_genus"


def test_repair_reason_missing_borrow() -> None:
    """A manual plant whose borrowed key is gone reports missing_borrow."""
    resolver = _resolver(_row("Hydrangea", [_SPRING], species="paniculata"))
    data = {
        "in_dataset": False,
        "windows": None,
        "windows_like": {"genus": "Wisteria", "species": None},
    }
    assert repair_reason(data, resolver) == "missing_borrow"
