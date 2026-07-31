"""The Garden Companion integration.

The config entry stores nothing of its own. On setup it loads the species
dataset off the event loop, caches it on the entry's runtime data for the
platforms to read, and raises a repair for any plant whose stored key fails to
match a dataset row (3.8). Timing is resolved on every load, so a dataset update
is how corrections reach existing plants.
"""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import _LOGGER, DOMAIN
from .dataset import (
    GardenCompanionConfigEntry,
    GardenCompanionData,
    async_load_dataset,
)
from .resolver import Resolver, repair_reason

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
    _refresh_repairs(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


def _refresh_repairs(
    hass: HomeAssistant, entry: GardenCompanionConfigEntry
) -> None:
    """Raise or clear a repair per plant, according to whether its key resolves (3.8)."""
    resolver = Resolver(entry.runtime_data.species)
    plants = {s.subentry_id: s for s in entry.get_subentries_of_type("plant")}
    registry = ir.async_get(hass)
    for issue_domain, issue_id in list(registry.issues):
        if issue_domain == DOMAIN and issue_id not in plants:
            ir.async_delete_issue(hass, DOMAIN, issue_id)
    for subentry_id, subentry in plants.items():
        reason = repair_reason(dict(subentry.data), resolver)
        if reason is None:
            ir.async_delete_issue(hass, DOMAIN, subentry_id)
            continue
        ir.async_create_issue(
            hass,
            DOMAIN,
            subentry_id,
            is_fixable=False,
            is_persistent=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=reason,
            translation_placeholders={"name": subentry.title},
        )


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
