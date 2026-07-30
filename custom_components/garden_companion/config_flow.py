"""Config flow for Garden Companion.

The config entry stores nothing: it exists only to own the per-plant subentries
added later. So setup is a single confirm step with no fields. HA aborts a
second attempt on its own, because manifest.json sets single_config_entry.
"""

from __future__ import annotations

from typing import Any, override

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN


class GardenCompanionConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the config flow for Garden Companion."""

    VERSION = 1

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step: a confirm with nothing to fill in."""
        if user_input is not None:
            return self.async_create_entry(title="Garden Companion", data={})

        return self.async_show_form(step_id="user")
