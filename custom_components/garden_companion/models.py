"""Schema and validator for the species dataset.

This module has no Home Assistant import on purpose. It is pure Python over the
structure `yaml.safe_load` returns, so `scripts/validate.py` can run it in CI
without installing Home Assistant, and the runtime loader in `dataset.py` reuses
the same parsing. That keeps the schema in exactly one place.

The dataclasses are the schema (2.3 to 2.5, 2.9). `build_dataset` turns the parsed
YAML into a list of `Species`, collecting every problem it finds rather than
raising on the first, so a contributor sees all of them at once.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Language codes the dataset may use. `nl` and `en` are required on every
# row; the set is extended by pull request as translations arrive.
ALLOWED_LANGUAGES = frozenset({"nl", "en"})

# Both bounds of a window are quoted MM-DD strings. 02-29 matches this but
# is rejected separately: it is not an annual date.
_MMDD = re.compile(r"^(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$")


@dataclass(frozen=True)
class Image:
    """A linked photo of the plant. Only `url` is required."""

    url: str
    author: str | None = None
    licence: str | None = None
    page: str | None = None


@dataclass(frozen=True)
class Window:
    """One pruning window: an inclusive MM-DD range plus localised prose."""

    start: str
    end: str
    description: dict[str, str]


@dataclass(frozen=True)
class Care:
    """One continuous-care job: the season it runs in, plus localised prose.

    Deadheading a rose is not a pruning window. It lasts months, it repeats, and
    what triggers it is a spent flower rather than a date, so it carries a season
    and advice instead of a job with a start.
    """

    start: str
    end: str
    description: dict[str, str]


@dataclass(frozen=True)
class Species:
    """One dataset record, keyed on (genus, species)."""

    genus: str
    species: str | None
    names: dict[str, list[str]]
    windows: tuple[Window, ...]
    source: str
    synonyms: tuple[str, ...] = ()
    image: Image | None = None
    care: tuple[Care, ...] = ()

    @property
    def key(self) -> tuple[str, str | None]:
        """The uniqueness key for this record."""
        return (self.genus, self.species)


_Signature = tuple[str, str, tuple[tuple[str, str], ...]]


def _span_signature(span: Window | Care) -> _Signature:
    """Return a hashable form of one window or care season, so rows can be compared."""
    return (span.start, span.end, tuple(sorted(span.description.items())))


def timing_signature(species: Species) -> tuple[tuple[_Signature, ...], ...]:
    """Return a hashable signature of the whole advice a row gives.

    Two rows say the same thing when their signatures are equal; order within
    windows or care does not matter. Descriptions are part of it, so two rows with
    the same dates but different instructions (Hydrangea macrophylla against
    aspera) count as different advice and must not be treated as one. Care is
    included for the same reason: rows that prune alike but need different
    continuous care are still a question the user has to answer.
    """
    return (
        tuple(sorted(_span_signature(window) for window in species.windows)),
        tuple(sorted(_span_signature(care) for care in species.care)),
    )


def _string_key_errors(node: object, path: str) -> list[str]:
    """Report any mapping key in the parsed dataset that is not a string.

    PyYAML is YAML 1.1, so an unquoted `no`, `yes`, `on` or `off` parses as a
    boolean, and `no` is the ISO code for Norwegian. This catches the class of
    bug rather than the instances anyone happens to think of.
    """
    errors: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if not isinstance(key, str):
                hint = ""
                if isinstance(key, bool):
                    hint = ' (an unquoted yes/no/on/off; quote it, e.g. "no")'
                errors.append(f"{path}: mapping key {key!r} is not a string{hint}")
            errors.extend(_string_key_errors(value, f"{path}/{key!r}"))
    elif isinstance(node, list):
        for index, item in enumerate(node):
            errors.extend(_string_key_errors(item, f"{path}[{index}]"))
    return errors


def _lang_map_errors(
    value: object,
    field: str,
    label: str,
    *,
    values_are_lists: bool,
    required_langs: tuple[str, ...],
) -> list[str]:
    """Validate a {language: value} map: allowed codes, required codes, types."""
    shape = "list of names" if values_are_lists else "text"
    if not isinstance(value, dict):
        return [f"{label}: {field} must be a map of language code to {shape}"]

    allowed = sorted(ALLOWED_LANGUAGES)
    errors: list[str] = [
        f"{label}: {field} has language {lang!r}, not in the allowlist {allowed}"
        for lang in value
        if isinstance(lang, str) and lang not in ALLOWED_LANGUAGES
    ]
    errors.extend(
        f"{label}: {field} is missing the required {required!r} entry"
        for required in required_langs
        if required not in value
    )
    for lang, content in value.items():
        if values_are_lists:
            ok = (
                isinstance(content, list)
                and bool(content)
                and all(isinstance(item, str) and item for item in content)
            )
            if not ok:
                errors.append(
                    f"{label}: {field}.{lang} must be a non-empty list of strings"
                )
        elif not isinstance(content, str) or not content.strip():
            errors.append(f"{label}: {field}.{lang} must be a non-empty string")
    return errors


def _build_span(
    raw: object, label: str, kind: str
) -> tuple[tuple[str, str, dict[str, str]] | None, list[str]]:
    """Validate a `when` range with localised prose, shared by windows and care.

    Returns the (start, end, description) it parsed, or None with the problems.
    """
    if not isinstance(raw, dict):
        return None, [f"{label}: each {kind} must be a map"]

    errors: list[str] = []
    start: str | None = None
    end: str | None = None
    when = raw.get("when")
    if not isinstance(when, dict):
        errors.append(f"{label}: {kind} needs a `when` map with start and end")
    else:
        for bound in ("start", "end"):
            value = when.get(bound)
            if not isinstance(value, str):
                errors.append(f'{label}: when.{bound} must be a quoted "MM-DD" string')
            elif not _MMDD.match(value):
                errors.append(
                    f'{label}: when.{bound} {value!r} is not a valid "MM-DD" date'
                )
            elif value == "02-29":
                errors.append(f"{label}: when.{bound} '02-29' is not an annual date")
            elif bound == "start":
                start = value
            else:
                end = value

    description = raw.get("description")
    errors.extend(
        _lang_map_errors(
            description,
            "description",
            label,
            values_are_lists=False,
            required_langs=("nl", "en"),
        )
    )

    if errors or start is None or end is None:
        return None, errors
    return (start, end, dict(description)), errors  # type: ignore[arg-type]


def _build_window(raw: object, label: str) -> tuple[Window | None, list[str]]:
    """Validate one pruning window and build it, or return the problems found."""
    span, errors = _build_span(raw, label, "window")
    if span is None:
        return None, errors
    start, end, description = span
    return Window(start=start, end=end, description=description), errors


def _build_care(raw: object, label: str) -> tuple[Care | None, list[str]]:
    """Validate one care season and build it, or return the problems found."""
    span, errors = _build_span(raw, label, "care season")
    if span is None:
        return None, errors
    start, end, description = span
    return Care(start=start, end=end, description=description), errors


def _build_species(raw: object, index: int) -> tuple[Species | None, list[str]]:
    """Validate one record and build it, or return the problems found."""
    label = f"row {index}"
    if not isinstance(raw, dict):
        return None, [f"{label}: each record must be a map"]

    genus = raw.get("genus")
    species = raw.get("species")
    if isinstance(genus, str) and genus:
        suffix = f"/{species}" if isinstance(species, str) and species else ""
        label = f"row {index} ({genus}{suffix})"

    errors: list[str] = []
    if not isinstance(genus, str) or not genus:
        errors.append(f"{label}: genus is required and must be a non-empty string")
    if species is not None and (not isinstance(species, str) or not species):
        errors.append(f"{label}: species, when present, must be a non-empty string")

    errors.extend(
        _lang_map_errors(
            raw.get("names"),
            "names",
            label,
            values_are_lists=True,
            required_langs=("nl", "en"),
        )
    )

    source = raw.get("source")
    if not isinstance(source, str) or not source.strip():
        errors.append(f"{label}: source is required and must be a non-empty string")

    built_windows: list[Window] = []
    windows_raw = raw.get("windows")
    if not isinstance(windows_raw, list) or not windows_raw:
        errors.append(f"{label}: windows is required and must hold at least one window")
    else:
        for w_index, window_raw in enumerate(windows_raw):
            window, window_errors = _build_window(
                window_raw, f"{label} window {w_index}"
            )
            errors.extend(window_errors)
            if window is not None:
                built_windows.append(window)

    built_care: list[Care] = []
    care_raw = raw.get("care")
    if care_raw is not None:
        if not isinstance(care_raw, list) or not care_raw:
            errors.append(f"{label}: care, when present, must hold at least one season")
        else:
            for c_index, care_item in enumerate(care_raw):
                care, care_errors = _build_care(care_item, f"{label} care {c_index}")
                errors.extend(care_errors)
                if care is not None:
                    built_care.append(care)

    built_image: Image | None = None
    image = raw.get("image")
    if image is not None:
        if not isinstance(image, dict):
            errors.append(f"{label}: image must be a map with at least a url")
        elif not isinstance(image.get("url"), str) or not image["url"]:
            errors.append(f"{label}: image is present but has no url")
        else:
            built_image = Image(
                url=image["url"],
                author=image.get("author"),
                licence=image.get("licence"),
                page=image.get("page"),
            )

    synonyms: tuple[str, ...] = ()
    synonyms_raw = raw.get("synonyms")
    if synonyms_raw is not None:
        if not isinstance(synonyms_raw, list) or not all(
            isinstance(item, str) and item for item in synonyms_raw
        ):
            errors.append(f"{label}: synonyms must be a list of non-empty strings")
        else:
            synonyms = tuple(synonyms_raw)

    if errors:
        return None, errors

    names = {lang: list(value) for lang, value in raw["names"].items()}
    return (
        Species(
            genus=genus,  # type: ignore[arg-type]
            species=species,
            names=names,
            windows=tuple(built_windows),
            source=source,  # type: ignore[arg-type]
            synonyms=synonyms,
            image=built_image,
            care=tuple(built_care),
        ),
        errors,
    )


def build_dataset(raw: object) -> tuple[list[Species], list[str]]:
    """Build the dataset from parsed YAML, collecting every problem found.

    Returns the records that parsed cleanly and a list of human-readable error
    messages. An empty error list means the dataset is valid.
    """
    errors = _string_key_errors(raw, "dataset")
    if raw is None:
        errors.append("dataset is empty; expected a list of records")
        return [], errors
    if not isinstance(raw, list):
        errors.append("dataset must be a list of records")
        return [], errors

    species_list: list[Species] = []
    for index, row in enumerate(raw):
        species, row_errors = _build_species(row, index)
        errors.extend(row_errors)
        if species is not None:
            species_list.append(species)

    seen: set[tuple[str, str | None]] = set()
    for species in species_list:
        if species.key in seen:
            errors.append(f"duplicate record key {species.key}; keys must be unique")
        else:
            seen.add(species.key)

    genera = {species.genus for species in species_list}
    for species in species_list:
        for synonym in species.synonyms:
            if synonym in genera:
                errors.append(
                    f"synonym {synonym!r} on {species.key} collides with an existing genus row"
                )

    return species_list, errors
