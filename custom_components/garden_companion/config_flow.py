"""Config flow and subentry flow for Garden Companion.

The config entry stores nothing and is a single confirm step (step 1). Each
plant is a subentry added and reconfigured through PlantSubentryFlow, which
gives add, reconfigure and delete in the UI for free and makes each plant its
own device (3.1).
"""

from __future__ import annotations

from typing import Any, override

import voluptuous as vol
from homeassistant.components import persistent_notification
from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import DOMAIN
from .models import Species
from .resolver import Resolver, normalise, timing_signature


class GardenCompanionConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the config flow for Garden Companion."""

    VERSION = 1

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Offer one subentry type: a plant."""
        return {"plant": PlantSubentryFlow}

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step: a confirm with nothing to fill in."""
        if user_input is not None:
            return self.async_create_entry(title="Garden Companion", data={})

        return self.async_show_form(step_id="user")


def _default_display_name(species: Species, language: str) -> str:
    """Return a common name in the user's language, else English, else botanical."""
    for lang in (language, "en"):
        names = species.names.get(lang)
        if names:
            return names[0]
    botanical = [species.genus]
    if species.species:
        botanical.append(species.species)
    return " ".join(botanical)


def _candidate_label(species: Species, language: str) -> str:
    """Return a disambiguation label: the distinguish text, else botanical plus a name."""
    if species.distinguish:
        text = species.distinguish.get(language) or species.distinguish.get("en")
        if text:
            return text
    return _borrow_label(species, language)


def _borrow_label(species: Species, language: str) -> str:
    """Label a plant in a picker: common name plus botanical name."""
    botanical = species.genus
    if species.species:
        botanical += f" {species.species}"
    common = _default_display_name(species, language)
    return f"{common} ({botanical})" if common != botanical else botanical


# Option values in the add picker. The prefix keeps them apart from a name the
# user types, since the same field accepts both, and the key is the row's own
# (genus, species, variant) so the custom panel can build the same value without
# knowing anything about option ordering.
_ROW_PREFIX = "dataset:"


def row_value(species: Species) -> str:
    """Return the picker value that identifies one dataset row."""
    parts = (species.genus, species.species or "", species.variant or "")
    return _ROW_PREFIX + "|".join(parts)


def picked_row(value: str, resolver: Resolver) -> Species | None:
    """Return the row a picker value names, or None if a name was typed instead.

    The lookup is exact: `Resolver.resolve` falls back to the genus row, which
    would silently substitute a different plant, so the resolved key is compared
    against the requested one.
    """
    if not value.startswith(_ROW_PREFIX):
        return None
    parts = value.removeprefix(_ROW_PREFIX).split("|")
    if len(parts) != 3 or not parts[0]:
        return None
    genus, species, variant = (part or None for part in parts)
    row = resolver.resolve(genus, species, variant)
    if row is None or (row.genus, row.species, row.variant) != (
        genus,
        species,
        variant,
    ):
        return None
    return row


def _picker_label(species: Species, language: str) -> str:
    """Label a row in the add picker, telling variants of one genus apart.

    Two rows of the same genus that differ only by variant would otherwise read
    identically, so the distinguishing text is appended.
    """
    label = _borrow_label(species, language)
    if not species.variant:
        return label
    hint = None
    if species.distinguish:
        hint = species.distinguish.get(language) or species.distinguish.get("en")
    return f"{label}, {hint or species.variant}"


def _distinct_by_timing(candidates: list[Species]) -> list[Species]:
    """Return one row per distinct timing, so identical timings are not offered twice (2.6)."""
    groups: dict[tuple[Any, ...], Species] = {}
    for candidate in candidates:
        groups.setdefault(timing_signature(candidate), candidate)
    return list(groups.values())


def _parse_botanical(botanical: str) -> tuple[str, str | None]:
    """Split a free-text botanical name into a (genus, species) pair."""
    tokens = normalise(botanical).split()
    if not tokens:
        return botanical.strip(), None
    genus = tokens[0].capitalize()
    species = tokens[1] if len(tokens) > 1 else None
    return genus, species


def _matched_on(species: Species) -> str:
    """Return how a dataset match resolved: variant, species or genus (3.2)."""
    if species.variant:
        return "variant"
    if species.species:
        return "species"
    return "genus"


def _stored_plant(species: Species, display_name: str) -> dict[str, Any]:
    """Build the stored subentry data for a plant matched in the dataset (3.2)."""
    return {
        "genus": species.genus,
        "species": species.species,
        "variant": species.variant,
        "display_name": display_name,
        "matched_on": _matched_on(species),
        "in_dataset": True,
        "windows_like": None,
        "windows": None,
        "source": None,
        "image_url": None,
    }


def _stored_borrow(
    botanical: str, display_name: str, borrowed: Species
) -> dict[str, Any]:
    """Build stored data for a manual plant that borrows another plant's timing (3.2, 3.7)."""
    genus, species = _parse_botanical(botanical)
    return {
        "genus": genus,
        "species": species,
        "variant": None,
        "display_name": display_name,
        "matched_on": "manual",
        "in_dataset": False,
        "windows_like": {
            "genus": borrowed.genus,
            "species": borrowed.species,
            "variant": borrowed.variant,
        },
        "windows": None,
        "source": None,
        "image_url": None,
    }


_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
_DAYS_IN_MONTH = {
    1: 31,
    2: 28,
    3: 31,
    4: 30,
    5: 31,
    6: 30,
    7: 31,
    8: 31,
    9: 30,
    10: 31,
    11: 30,
    12: 31,
}


def _valid_day(month: int, day: int) -> bool:
    """Return whether day is a real day of the month, with February capped at 28."""
    return 1 <= day <= _DAYS_IN_MONTH.get(month, 0)


def _stored_author(
    botanical: str,
    display_name: str,
    windows: list[dict[str, Any]],
    source: str | None,
    image_url: str | None,
) -> dict[str, Any]:
    """Build stored data for a manual plant with its own authored windows (3.2, 3.7)."""
    genus, species = _parse_botanical(botanical)
    return {
        "genus": genus,
        "species": species,
        "variant": None,
        "display_name": display_name,
        "matched_on": "manual",
        "in_dataset": False,
        "windows_like": None,
        "windows": windows,
        "source": source,
        "image_url": image_url,
    }


def _snippet(
    genus: str,
    species: str | None,
    display_name: str,
    language: str,
    windows: list[dict[str, Any]],
    source: str | None,
) -> str:
    """Render a paste-ready species.yaml row for a manually added plant (3.7)."""
    other = "nl" if language != "nl" else "en"
    lines = [f"- genus: {genus}"]
    if species:
        lines.append(f"  species: {species}")
    lines.append("  names:")
    lines.append(f"    {language}: [{display_name}]")
    lines.append(f"    {other}: [TODO]")
    lines.append(f"  source: {source or 'TODO'}")
    lines.append("  windows:")
    for window in windows:
        when = window["when"]
        lines.append(
            f'    - when: {{ start: "{when["start"]}", end: "{when["end"]}" }}'
        )
        lines.append("      description:")
        for lang, text in window["description"].items():
            lines.append(f"        {lang}: {text}")
    return "\n".join(lines)


class PlantSubentryFlow(ConfigSubentryFlow):
    """Add or reconfigure one plant."""

    _match: Species | None = None
    _candidates: list[Species] | None = None
    _query: str | None = None
    _botanical: str | None = None
    _display: str | None = None
    _windows: list[dict[str, Any]] | None = None

    def _species(self) -> list[Species]:
        """Return the config entry's cached dataset."""
        return self._get_entry().runtime_data.species

    def _resolver(self) -> Resolver:
        """Build a resolver over the config entry's cached dataset."""
        return Resolver(self._species())

    async def _select_match(self, species: Species) -> SubentryFlowResult:
        """Route a chosen dataset row: update on reconfigure, else name it (add)."""
        if self.source == SOURCE_RECONFIGURE:
            return self._apply_repick(species)
        self._match = species
        return await self.async_step_name()

    def _apply_repick(self, species: Species) -> SubentryFlowResult:
        """Re-map an existing plant to a dataset row, keeping its name (3.6)."""
        subentry = self._get_reconfigure_subentry()
        return self.async_update_and_abort(
            self._get_entry(),
            subentry,
            data={
                **subentry.data,
                "genus": species.genus,
                "species": species.species,
                "variant": species.variant,
                "matched_on": _matched_on(species),
                "in_dataset": True,
                "windows_like": None,
                "windows": None,
            },
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Re-pick which plant this maps to (3.6). Rename and delete are HA built-ins."""
        subentry = self._get_reconfigure_subentry()
        errors: dict[str, str] = {}
        if user_input is not None:
            groups = _distinct_by_timing(self._resolver().search(user_input["query"]))
            if not groups:
                errors["base"] = "not_found"
            elif len(groups) == 1:
                return await self._select_match(groups[0])
            else:
                self._candidates = groups
                return await self.async_step_disambiguate()

        default = subentry.data["genus"]
        if subentry.data.get("species"):
            default += f" {subentry.data['species']}"
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema({vol.Required("query", default=default): str}),
            errors=errors,
        )

    def _picker_rows(self) -> list[Species]:
        """Return every dataset row, ordered by the label the picker shows."""
        language = self.hass.config.language
        return sorted(
            self._species(), key=lambda row: _picker_label(row, language).casefold()
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Pick a plant from the dataset, or type any name to search for it.

        The picker is a combo box holding every row, so the whole dataset can be
        browsed, and typing filters it. A name typed that is not one of the
        options falls through to the same search that drives disambiguation and
        manual add, so a plant that is not in the dataset still works.
        """
        rows = self._picker_rows()
        if user_input is not None:
            chosen = user_input["query"]
            picked = picked_row(chosen, self._resolver())
            if picked is not None:
                return await self._select_match(picked)
            groups = _distinct_by_timing(self._resolver().search(chosen))
            if not groups:
                # No match: offer manual add, seeding the botanical name (3.6).
                self._query = chosen
                return await self.async_step_manual()
            if len(groups) == 1:
                # One answer (a single row, or several that share timing).
                return await self._select_match(groups[0])
            self._candidates = groups
            return await self.async_step_disambiguate()

        language = self.hass.config.language
        options = [
            SelectOptionDict(value=row_value(row), label=_picker_label(row, language))
            for row in rows
        ]
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("query"): SelectSelector(
                        SelectSelectorConfig(
                            options=options,
                            mode=SelectSelectorMode.DROPDOWN,
                            custom_value=True,
                        )
                    )
                }
            ),
        )

    async def async_step_disambiguate(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Choose between candidates that prune at different times (2.6, 3.6)."""
        candidates = self._candidates or []
        if user_input is not None:
            choice = user_input["choice"]
            if choice == "unsure":
                return await self.async_step_manual()
            return await self._select_match(candidates[int(choice)])

        language = self.hass.config.language
        options = [
            SelectOptionDict(
                value=str(index), label=_candidate_label(candidate, language)
            )
            for index, candidate in enumerate(candidates)
        ]
        if self.source != SOURCE_RECONFIGURE:
            options.append(SelectOptionDict(value="unsure", label="I am not sure"))
        return self.async_show_form(
            step_id="disambiguate",
            data_schema=vol.Schema(
                {
                    vol.Required("choice"): SelectSelector(
                        SelectSelectorConfig(options=options)
                    )
                }
            ),
        )

    async def async_step_name(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Name a dataset plant, then create the subentry."""
        if self._match is None:
            return await self.async_step_user()
        if user_input is not None:
            return self.async_create_entry(
                title=user_input["display_name"],
                data=_stored_plant(self._match, user_input["display_name"]),
            )

        default = _default_display_name(self._match, self.hass.config.language)
        return self.async_show_form(
            step_id="name",
            data_schema=vol.Schema(
                {vol.Required("display_name", default=default): str}
            ),
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Collect a botanical name and display name for a plant not in the dataset (3.7)."""
        if user_input is not None:
            self._botanical = user_input["botanical"]
            self._display = user_input["display_name"]
            return await self.async_step_timing()

        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema(
                {
                    vol.Required("botanical", default=self._query or ""): str,
                    vol.Required("display_name"): str,
                }
            ),
        )

    async def async_step_timing(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Offer to borrow another plant's timing or author your own (3.7)."""
        return self.async_show_menu(step_id="timing", menu_options=["borrow", "author"])

    async def async_step_borrow(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Reuse an existing plant's timing for the manual plant (3.7)."""
        species = self._species()
        if user_input is not None:
            borrowed = species[int(user_input["borrowed"])]
            windows = [
                {
                    "when": {"start": window.start, "end": window.end},
                    "description": dict(window.description),
                }
                for window in borrowed.windows
            ]
            self._notify_contribution(
                self._botanical or "", self._display or "", windows, None
            )
            return self.async_create_entry(
                title=self._display or "",
                data=_stored_borrow(
                    self._botanical or "", self._display or "", borrowed
                ),
            )

        language = self.hass.config.language
        options = [
            SelectOptionDict(value=str(index), label=_borrow_label(row, language))
            for index, row in enumerate(species)
        ]
        return self.async_show_form(
            step_id="borrow",
            data_schema=vol.Schema(
                {
                    vol.Required("borrowed"): SelectSelector(
                        SelectSelectorConfig(options=options)
                    )
                }
            ),
        )

    def _notify_contribution(
        self,
        botanical: str,
        display_name: str,
        windows: list[dict[str, Any]],
        source: str | None,
    ) -> None:
        """Raise a persistent notification with a paste-ready species.yaml snippet (3.7)."""
        genus, species = _parse_botanical(botanical)
        snippet = _snippet(
            genus, species, display_name, self.hass.config.language, windows, source
        )
        message = (
            "A plant that is not in the Garden Companion dataset was added. If it "
            "belongs in the dataset, paste this into species.yaml and open an issue:\n\n"
            f"```yaml\n{snippet}\n```\n\n"
            "Issues: https://github.com/MRVDH/garden-companion/issues"
        )
        persistent_notification.async_create(
            self.hass, message, title="Garden Companion: new plant"
        )

    async def async_step_author(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Start authoring one or more pruning windows (3.7)."""
        self._windows = []
        return await self.async_step_window()

    async def async_step_window(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Collect one window: a start and end date and what to do (3.7)."""
        if self._windows is None:
            self._windows = []
        errors: dict[str, str] = {}
        if user_input is not None:
            start_month = int(user_input["start_month"])
            start_day = int(user_input["start_day"])
            end_month = int(user_input["end_month"])
            end_day = int(user_input["end_day"])
            if not _valid_day(start_month, start_day) or not _valid_day(
                end_month, end_day
            ):
                errors["base"] = "invalid_date"
            else:
                language = self.hass.config.language
                self._windows.append(
                    {
                        "when": {
                            "start": f"{start_month:02d}-{start_day:02d}",
                            "end": f"{end_month:02d}-{end_day:02d}",
                        },
                        "description": {language: user_input["description"]},
                    }
                )
                return await self.async_step_window_menu()

        months = SelectSelector(
            SelectSelectorConfig(
                options=[
                    SelectOptionDict(value=str(number), label=name)
                    for number, name in enumerate(_MONTHS, start=1)
                ]
            )
        )
        day = NumberSelector(
            NumberSelectorConfig(min=1, max=31, step=1, mode=NumberSelectorMode.BOX)
        )
        return self.async_show_form(
            step_id="window",
            data_schema=vol.Schema(
                {
                    vol.Required("start_month"): months,
                    vol.Required("start_day"): day,
                    vol.Required("end_month"): months,
                    vol.Required("end_day"): day,
                    vol.Required("description"): str,
                }
            ),
            errors=errors,
        )

    async def async_step_window_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Offer another window or finishing up (3.7)."""
        return self.async_show_menu(
            step_id="window_menu", menu_options=["window", "details"]
        )

    async def async_step_details(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Ask for an optional source and photo, then create the plant (3.7)."""
        if user_input is not None:
            source = user_input.get("source") or None
            self._notify_contribution(
                self._botanical or "", self._display or "", self._windows or [], source
            )
            return self.async_create_entry(
                title=self._display or "",
                data=_stored_author(
                    self._botanical or "",
                    self._display or "",
                    self._windows or [],
                    source,
                    user_input.get("image_url") or None,
                ),
            )

        return self.async_show_form(
            step_id="details",
            data_schema=vol.Schema(
                {
                    vol.Optional("source"): str,
                    vol.Optional("image_url"): str,
                }
            ),
        )
