"""Config flow and subentry flow for Garden Companion.

The config entry stores nothing and is a single confirm step (step 1). Each
plant is a subentry added and reconfigured through PlantSubentryFlow, which
gives add, reconfigure and delete in the UI for free and makes each plant its
own device (3.1).
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


def _stored_plant(species: Species, display_name: str) -> dict[str, Any]:
    """Build the stored subentry data for a plant matched in the dataset (3.2)."""
    if species.variant:
        matched_on = "variant"
    elif species.species:
        matched_on = "species"
    else:
        matched_on = "genus"
    return {
        "genus": species.genus,
        "species": species.species,
        "variant": species.variant,
        "display_name": display_name,
        "matched_on": matched_on,
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


class PlantSubentryFlow(ConfigSubentryFlow):
    """Add or reconfigure one plant."""

    _match: Species | None = None
    _candidates: list[Species] | None = None
    _query: str | None = None
    _botanical: str | None = None
    _display: str | None = None

    def _species(self) -> list[Species]:
        """Return the config entry's cached dataset."""
        return self._get_entry().runtime_data.species

    def _resolver(self) -> Resolver:
        """Build a resolver over the config entry's cached dataset."""
        return Resolver(self._species())

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Search for a plant by botanical or common name."""
        if user_input is not None:
            groups = _distinct_by_timing(self._resolver().search(user_input["query"]))
            if not groups:
                # No match: offer manual add, seeding the botanical name (3.6).
                self._query = user_input["query"]
                return await self.async_step_manual()
            if len(groups) == 1:
                # One answer (a single row, or several that share timing).
                self._match = groups[0]
                return await self.async_step_name()
            self._candidates = groups
            return await self.async_step_disambiguate()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required("query"): str}),
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
            self._match = candidates[int(choice)]
            return await self.async_step_name()

        language = self.hass.config.language
        options = [
            SelectOptionDict(
                value=str(index), label=_candidate_label(candidate, language)
            )
            for index, candidate in enumerate(candidates)
        ]
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

    async def async_step_author(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Abort for now; authoring your own windows arrives in a later slice."""
        return self.async_abort(reason="author_not_ready")
