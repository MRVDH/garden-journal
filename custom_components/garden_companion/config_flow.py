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
from .resolver import Resolver, timing_signature


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
    botanical = species.genus
    if species.species:
        botanical += f" {species.species}"
    common = _default_display_name(species, language)
    return f"{botanical}, {common}" if common != botanical else botanical


def _distinct_by_timing(candidates: list[Species]) -> list[Species]:
    """Return one row per distinct timing, so identical timings are not offered twice (2.6)."""
    groups: dict[tuple[Any, ...], Species] = {}
    for candidate in candidates:
        groups.setdefault(timing_signature(candidate), candidate)
    return list(groups.values())


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


class PlantSubentryFlow(ConfigSubentryFlow):
    """Add or reconfigure one plant."""

    _match: Species | None = None
    _candidates: list[Species] | None = None

    def _resolver(self) -> Resolver:
        """Build a resolver over the config entry's cached dataset."""
        return Resolver(self._get_entry().runtime_data.species)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Search for a plant by botanical or common name."""
        errors: dict[str, str] = {}
        if user_input is not None:
            groups = _distinct_by_timing(self._resolver().search(user_input["query"]))
            if not groups:
                errors["base"] = "not_found"
            elif len(groups) == 1:
                # One answer (a single row, or several that share timing).
                self._match = groups[0]
                return await self.async_step_name()
            else:
                self._candidates = groups
                return await self.async_step_disambiguate()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required("query"): str}),
            errors=errors,
        )

    async def async_step_disambiguate(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Choose between candidates that prune at different times (2.6, 3.6)."""
        candidates = self._candidates or []
        if user_input is not None:
            choice = user_input["choice"]
            if choice == "unsure":
                # Manual add is the destination here; it arrives in a later slice.
                return self.async_abort(reason="manual_not_ready")
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
        """Name the plant, then create the subentry."""
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
