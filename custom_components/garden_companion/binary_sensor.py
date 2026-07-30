"""Prune-now binary sensor: on while today falls inside a pruning window (3.3).

Read together with the next-pruning sensor, it says the job is open and when it
opened. Computed locally; refreshes at local midnight (see the base entity).
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .dataset import GardenCompanionConfigEntry
from .entity import PlantEntity
from .resolver import Resolver
from .windows import is_pruning_now


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GardenCompanionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create a prune-now binary sensor for each plant subentry."""
    resolver = Resolver(entry.runtime_data.species)
    for subentry in entry.get_subentries_of_type("plant"):
        async_add_entities(
            [
                PruneNowBinarySensor(
                    subentry.subentry_id, subentry.title, dict(subentry.data), resolver
                )
            ],
            config_subentry_id=subentry.subentry_id,
        )


class PruneNowBinarySensor(PlantEntity, BinarySensorEntity):
    """On while today falls inside one of the plant's pruning windows (3.3)."""

    _attr_translation_key = "prune_now"
    _attr_icon = "mdi:content-cut"

    def __init__(
        self, subentry_id: str, title: str, data: dict[str, Any], resolver: Resolver
    ) -> None:
        """Set up the binary sensor for one plant."""
        super().__init__(subentry_id, title, data, resolver)
        self._attr_unique_id = f"{subentry_id}_prune_now"

    @property
    def is_on(self) -> bool | None:
        """Return whether today is inside a window, or None when timing is unknown."""
        windows = self._windows()
        if windows is None:
            return None
        return is_pruning_now(windows, dt_util.now().date())
