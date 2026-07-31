"""The Garden Companion integration.

The config entry stores nothing of its own. On setup it loads the species
dataset off the event loop and caches it on the entry's runtime data; the
entities and calendar in later steps read it from there. Loading the dataset is
the whole of this step.
"""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import _LOGGER
from .dataset import (
    GardenCompanionConfigEntry,
    GardenCompanionData,
    async_load_dataset,
)

_PLATFORMS = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.CALENDAR,
    Platform.IMAGE,
]


async def async_setup_entry(
    hass: HomeAssistant, entry: GardenCompanionConfigEntry
) -> bool:
    """Set up Garden Companion from a config entry."""
    species = await async_load_dataset(hass)
    entry.runtime_data = GardenCompanionData(species=species)
    _LOGGER.debug("Loaded %d species from the dataset", len(species))
    await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def _async_reload_entry(
    hass: HomeAssistant, entry: GardenCompanionConfigEntry
) -> None:
    """Reload so a plant added, changed or removed updates its entities (3.5)."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(
    hass: HomeAssistant, entry: GardenCompanionConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, _PLATFORMS)
