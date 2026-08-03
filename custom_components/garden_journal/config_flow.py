"""Config flow and subentry flow for Garden Journal.

The config entry stores nothing and is a single confirm step. Each plant is a
subentry, which makes it its own device and gives rename and delete in the UI for
free.

Plants are added in the panel, not here. What is left of the subentry flow is
reconfigure, the route that re-points a plant at a different dataset row, plus the
helpers the panel imports for building stored plant data. The add step exists only
to say where to go: Home Assistant shows an "Add plant" button for every subentry
type an integration declares, and declaring the type is what keeps reconfigure
reachable.
"""

from __future__ import annotations

from typing import Any, override

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
)

from .const import DOMAIN
from .models import Species
from .resolver import Resolver, normalise, timing_signature


class GardenJournalConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the config flow for Garden Journal."""

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
            return self.async_create_entry(title="Garden Journal", data={})

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


def _label(species: Species, language: str) -> str:
    """Label a plant in a picker or a choice: common name plus botanical name."""
    botanical = species.genus
    if species.species:
        botanical += f" {species.species}"
    common = _default_display_name(species, language)
    return f"{common} ({botanical})" if common != botanical else botanical


# Option values in the add picker. The prefix keeps them apart from a name the
# user types, since the same field accepts both, and the key is the row's own
# (genus, species) so the custom panel can build the same value without knowing
# anything about option ordering.
_ROW_PREFIX = "dataset:"


def row_value(species: Species) -> str:
    """Return the picker value that identifies one dataset row."""
    return _ROW_PREFIX + "|".join((species.genus, species.species or ""))


def picked_row(value: str, resolver: Resolver) -> Species | None:
    """Return the row a picker value names, or None if a name was typed instead.

    The lookup is exact: `Resolver.resolve` falls back to the genus row, which
    would silently substitute a different plant, so the resolved key is compared
    against the requested one.
    """
    if not value.startswith(_ROW_PREFIX):
        return None
    parts = value.removeprefix(_ROW_PREFIX).split("|")
    if len(parts) != 2 or not parts[0]:
        return None
    genus, species = (part or None for part in parts)
    row = resolver.resolve(genus, species)
    if row is None or (row.genus, row.species) != (genus, species):
        return None
    return row


def _distinct_by_timing(candidates: list[Species]) -> list[Species]:
    """Return one row per distinct timing, so identical timings are not offered twice."""
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
    """Return how a dataset match resolved: species or genus."""
    return "species" if species.species else "genus"


def _stored_plant(species: Species, display_name: str) -> dict[str, Any]:
    """Build the stored subentry data for a plant matched in the dataset."""
    return {
        "genus": species.genus,
        "species": species.species,
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
    """Build stored data for a manual plant that borrows another plant's timing."""
    genus, species = _parse_botanical(botanical)
    return {
        "genus": genus,
        "species": species,
        "display_name": display_name,
        "matched_on": "manual",
        "in_dataset": False,
        "windows_like": {
            "genus": borrowed.genus,
            "species": borrowed.species,
        },
        "windows": None,
        "source": None,
        "image_url": None,
    }


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
    """Build stored data for a manual plant with its own authored windows."""
    genus, species = _parse_botanical(botanical)
    return {
        "genus": genus,
        "species": species,
        "display_name": display_name,
        "matched_on": "manual",
        "in_dataset": False,
        "windows_like": None,
        "windows": windows,
        "source": source,
        "image_url": image_url,
    }


class PlantSubentryFlow(ConfigSubentryFlow):
    """Re-point one plant at a different dataset row.

    Adding happens in the panel. This flow is declared so that reconfigure
    exists, since Home Assistant refuses a subentry flow whose type an
    integration does not declare, and the add step says as much.
    """

    _candidates: list[Species] | None = None

    def _species(self) -> list[Species]:
        """Return the config entry's cached dataset."""
        return self._get_entry().runtime_data.species

    def _resolver(self) -> Resolver:
        """Build a resolver over the config entry's cached dataset."""
        return Resolver(self._species())

    def _apply_repick(self, species: Species) -> SubentryFlowResult:
        """Re-map an existing plant to a dataset row, keeping its name."""
        subentry = self._get_reconfigure_subentry()
        return self.async_update_and_abort(
            self._get_entry(),
            subentry,
            data={
                **subentry.data,
                "genus": species.genus,
                "species": species.species,
                "matched_on": _matched_on(species),
                "in_dataset": True,
                "windows_like": None,
                "windows": None,
            },
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Re-pick which plant this maps to. Rename and delete are HA built-ins."""
        subentry = self._get_reconfigure_subentry()
        errors: dict[str, str] = {}
        if user_input is not None:
            groups = _distinct_by_timing(self._resolver().search(user_input["query"]))
            if not groups:
                errors["base"] = "not_found"
            elif len(groups) == 1:
                return self._apply_repick(groups[0])
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

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Send the reader to the panel, which is where plants are added.

        Home Assistant shows an "Add plant" button for every subentry type an
        integration declares, and there is no way to declare one without it. The
        panel is the only place plants are added, so this step exists to say so
        rather than to offer a second route that behaves differently.

        The type stays declared because dropping it would take reconfigure with
        it: `async_create_flow` rejects any subentry flow whose type is not
        declared, whatever its source, and reconfigure is what the repair issues
        tell people to use when a dataset update orphans one of their plants.
        """
        return self.async_abort(reason="add_from_panel")

    async def async_step_disambiguate(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Choose between candidates that prune at different times.

        Only reconfigure reaches this, so every option is a dataset row. There is
        no "I am not sure" way out: the plant already exists, and the question is
        which row it should point at rather than whether to create it.
        """
        candidates = self._candidates or []
        if user_input is not None:
            return self._apply_repick(candidates[int(user_input["choice"])])

        language = self.hass.config.language
        options = [
            SelectOptionDict(value=str(index), label=_label(candidate, language))
            for index, candidate in enumerate(candidates)
        ]
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
