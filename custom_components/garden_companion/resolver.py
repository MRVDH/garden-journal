"""Resolve a plant to its dataset record, and search by name (2.6).

Pure logic over the Species dataclasses, with no Home Assistant import, so it
runs and tests in plain Python. The add flow (step 5) searches with it, and
load-time re-resolution (3.2) looks up the stored key with it.
"""

from __future__ import annotations

from .models import Species, Window

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
        self._synonyms: dict[str, list[Species]] = {}
        self._common: dict[str, list[Species]] = {}
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
        for synonym in species.synonyms:
            self._synonyms.setdefault(normalise(synonym), []).append(species)
        for names in species.names.values():
            for name in names:
                self._common.setdefault(normalise(name), []).append(species)

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

        One-to-many: a common name like "laurier" can return several rows. The
        cultivar is ignored, so "Weigela florida Bristol Ruby" matches on genus
        and species.
        """
        q = normalise(query)
        tokens = q.split()
        found: list[Species] = []
        seen: set[int] = set()

        def add(rows: list[Species]) -> None:
            """Append rows not already collected, preserving order."""
            for row in rows:
                if id(row) not in seen:
                    seen.add(id(row))
                    found.append(row)

        add(self._common.get(q, []))
        add(self._synonyms.get(q, []))
        if len(tokens) >= 2 and (tokens[0], tokens[1]) in self._by_genus_species:
            add(self._by_genus_species[(tokens[0], tokens[1])])
        elif tokens:
            add(self._synonyms.get(tokens[0], []))
            add(self._by_genus.get(tokens[0], []))
        return found
