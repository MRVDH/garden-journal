"""Resolve a plant to its dataset record, and search by name (2.6).

Pure logic over the Species dataclasses, with no Home Assistant import, so it
runs and tests in plain Python. The add flow (step 5) searches with it, and
load-time re-resolution (3.2) looks up the stored key with it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .models import Image, Species, Window

# Straight and curly quotes, stripped during normalisation.
_QUOTES = ("'", '"', "‘", "’", "“", "”")  # noqa: RUF001


def normalise(text: str) -> str:
    """Lowercase, strip quotes and the x/hybrid marker, collapse whitespace (2.6).

    The hybrid marker is a standalone `x` or the Unicode multiplication sign, so
    `Hydrangea x macrophylla` normalises to `hydrangea macrophylla`. An `x`
    inside a word is left alone, so `Ilex` keeps its x.
    """
    lowered = text.lower()
    for quote in _QUOTES:
        lowered = lowered.replace(quote, "")
    lowered = lowered.replace("×", " ")  # noqa: RUF001
    tokens = [token for token in lowered.split() if token != "x"]
    return " ".join(tokens)


def _window_signature(window: Window) -> tuple[str, str, tuple[tuple[str, str], ...]]:
    """Return a hashable form of one window, so timings can be compared."""
    return (window.start, window.end, tuple(sorted(window.description.items())))


def timing_signature(
    species: Species,
) -> tuple[tuple[str, str, tuple[tuple[str, str], ...]], ...]:
    """Return a hashable signature of a row's whole set of windows.

    Two rows share timing when their signatures are equal; window order does not
    matter. Descriptions are part of the signature, so two rows with the same
    dates but different instructions (Hydrangea macrophylla against aspera) count
    as different timings and must not be treated as one.
    """
    return tuple(sorted(_window_signature(window) for window in species.windows))


class Resolver:
    """An indexed view over the dataset for lookup and search."""

    def __init__(self, dataset: list[Species]) -> None:
        """Build the lookup indices once from the dataset."""
        self._by_key: dict[tuple[str, str | None, str | None], Species] = {}
        self._by_genus: dict[str, list[Species]] = {}
        self._by_genus_species: dict[tuple[str, str], list[Species]] = {}
        self._name_terms: list[tuple[Species, tuple[str, ...]]] = []
        for species in dataset:
            self._index(species)

    def _index(self, species: Species) -> None:
        """Add one record to every index."""
        genus = normalise(species.genus)
        sp = normalise(species.species) if species.species else None
        variant = normalise(species.variant) if species.variant else None
        self._by_key[(genus, sp, variant)] = species
        self._by_genus.setdefault(genus, []).append(species)
        if sp is not None:
            self._by_genus_species.setdefault((genus, sp), []).append(species)
        terms = {normalise(synonym) for synonym in species.synonyms}
        for names in species.names.values():
            terms.update(normalise(name) for name in names)
        self._name_terms.append((species, tuple(terms)))

    def resolve(
        self, genus: str, species: str | None = None, variant: str | None = None
    ) -> Species | None:
        """Most-specific-wins lookup: exact key, then the genus row, else None (2.6)."""
        g = normalise(genus)
        s = normalise(species) if species else None
        v = normalise(variant) if variant else None
        exact = self._by_key.get((g, s, v))
        if exact is not None:
            return exact
        return self._by_key.get((g, None, None))

    def genus_rows(self, genus: str) -> list[Species]:
        """Return every row under a genus."""
        return list(self._by_genus.get(normalise(genus), []))

    def is_ambiguous(self, genus: str) -> bool:
        """Report whether a genus resolves to more than one distinct timing (2.6).

        A genus-level row is a single answer, so such a genus is never ambiguous.
        """
        rows = self._by_genus.get(normalise(genus), [])
        if any(row.species is None and row.variant is None for row in rows):
            return False
        return len({timing_signature(row) for row in rows}) > 1

    def search(self, query: str) -> list[Species]:
        """Find rows by botanical name, synonym or common name in any language (2.6).

        Common names and synonyms match as a substring, so "hortensia" finds
        Pluimhortensia and its siblings; botanical names match by genus and
        species token, so a trailing cultivar is ignored. One-to-many: a shared
        common name like "laurier" returns several rows.
        """
        q = normalise(query)
        if not q:
            return []
        tokens = q.split()
        found: list[Species] = []
        seen: set[int] = set()

        def add(rows: list[Species]) -> None:
            """Append rows not already collected, preserving order."""
            for row in rows:
                if id(row) not in seen:
                    seen.add(id(row))
                    found.append(row)

        if len(tokens) >= 2 and (tokens[0], tokens[1]) in self._by_genus_species:
            add(self._by_genus_species[(tokens[0], tokens[1])])
        elif tokens and tokens[0] in self._by_genus:
            add(self._by_genus[tokens[0]])
        for species, terms in self._name_terms:
            if any(q in term for term in terms):
                add([species])
        return found


def _window_from_stored(stored: Mapping[str, Any]) -> Window:
    """Build a Window from a stored authored-window dict."""
    when = stored["when"]
    return Window(
        start=when["start"], end=when["end"], description=dict(stored["description"])
    )


def resolve_windows(data: Mapping[str, Any], resolver: Resolver) -> list[Window] | None:
    """Resolve a stored plant to its effective windows (3.2).

    A manual plant with authored windows uses them; with windows_like it resolves
    that key; otherwise the stored (genus, species, variant) key is resolved in the
    dataset. Returns None when nothing resolves, which is a repair case (3.8).
    """
    if not data.get("in_dataset", True):
        stored = data.get("windows")
        if stored:
            return [_window_from_stored(window) for window in stored]
        like = data.get("windows_like")
        if like:
            row = resolver.resolve(
                like["genus"], like.get("species"), like.get("variant")
            )
            return list(row.windows) if row else None
        return None
    row = resolver.resolve(data["genus"], data.get("species"), data.get("variant"))
    return list(row.windows) if row else None


def resolve_photo(data: Mapping[str, Any], resolver: Resolver) -> Image | None:
    """Resolve a stored plant to its photo, or None when it has none (2.5, 3.7).

    A manually added plant carries a bare photo URL with no credit; a dataset
    plant borrows the row's image, credit and all. A dataset plant whose key no
    longer resolves has no photo.
    """
    if not data.get("in_dataset", True):
        url = data.get("image_url")
        return Image(url=url) if url else None
    row = resolver.resolve(data["genus"], data.get("species"), data.get("variant"))
    return row.image if row else None
